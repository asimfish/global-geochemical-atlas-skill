#!/usr/bin/env python3
"""Merge independently reproduced V4 profile runs without weakening CRS rules.

The full-profile builder can be run for a bounded source set.  This helper
combines an existing checked baseline with those bounded runs.  An optional
reported-union balance, produced from the same complete source population,
is used only to prove that expansion cells are already contained in the base
canonical union and to recover the reported-coordinate union.  Scientific
counts never come from demo rows.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import build_v4_full_profiles
import source_adapters


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


class MergeError(RuntimeError):
    """Raised when independently generated profile assets cannot be merged."""


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MergeError(f"expected JSON object: {path}")
    return value


def _read_cube(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != build_v4_full_profiles.CUBE_COLUMNS:
            raise MergeError(f"coverage cube schema mismatch: {path}")
        return list(reader)


def _merge_cube(
    base: Path,
    expansions: Sequence[Path],
    replacement_source_id: str | None = None,
    replacement_cube: Path | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    base_rows = _read_cube(base)
    replaced_rows = []
    if replacement_source_id:
        replaced_rows = [row for row in base_rows if row["source_id"] == replacement_source_id]
        base_rows = [row for row in base_rows if row["source_id"] != replacement_source_id]
    paths_and_rows = [(base, base_rows), *((path, _read_cube(path)) for path in expansions)]
    if replacement_source_id:
        if replacement_cube is None:
            raise MergeError("a replacement source requires --replacement-cube")
        replacement_rows = _read_cube(replacement_cube)
        if {row["source_id"] for row in replacement_rows} != {replacement_source_id}:
            raise MergeError("replacement cube must contain exactly the replacement source")
        paths_and_rows.append((replacement_cube, replacement_rows))
    for path, current in paths_and_rows:
        source_ids = {row["source_id"] for row in current}
        overlap = seen_sources & source_ids
        if overlap:
            raise MergeError(f"coverage cube source overlap: {', '.join(sorted(overlap))}")
        seen_sources.update(source_ids)
        rows.extend(current)
    return (
        sorted(rows, key=lambda row: tuple(row[column] for column in build_v4_full_profiles.CUBE_COLUMNS[:8])),
        replaced_rows,
    )


def _replace_source_balance(
    balance: dict[str, Any],
    source_id: str,
    old_rows: Sequence[Mapping[str, str]],
    replacement: Mapping[str, Any],
    reported_union: Mapping[str, Any] | None,
) -> None:
    if not old_rows:
        raise MergeError(f"replacement source is absent from the base cube: {source_id}")
    old_elements = sorted({row["element"] for row in old_rows})
    old_by_element: dict[str, dict[str, int]] = {}
    for element in old_elements:
        rows = [row for row in old_rows if row["element"] == element]
        old_by_element[element] = {
            field: sum(int(row[field]) for row in rows)
            for field in (
                "observation_count",
                "distinct_sample_count",
                "reported_coordinate_sample_count",
                "valid_coordinate_sample_count",
                "comparable_observation_count",
            )
        }
    replacement_media = replacement.get("media", {})
    if len(replacement_media) != 1:
        raise MergeError("replacement balance must contain exactly one medium")
    medium, replacement_medium = next(iter(replacement_media.items()))
    target_medium = balance["media"][medium]
    old_total = {
        field: sum(value[field] for value in old_by_element.values())
        for field in (
            "observation_count",
            "distinct_sample_count",
            "reported_coordinate_sample_count",
            "valid_coordinate_sample_count",
            "comparable_observation_count",
        )
    }
    # A multi-element source can repeat one sample across elements.  Source-level
    # distinct coordinates come from its old single-element profile in the only
    # supported replacement migration (GEMStat As -> seven elements).
    if len(old_elements) != 1:
        raise MergeError("automatic replacement currently requires a single-element base source")
    for field in old_total:
        target_medium[field] = (
            int(target_medium[field]) - old_total[field] + int(replacement_medium[field])
        )
    target_medium["source_ids"] = sorted(set(target_medium["source_ids"]) | {source_id})
    target_medium["lineage_ids"] = sorted(
        set(target_medium["lineage_ids"]) | set(replacement_medium.get("lineage_ids", []))
    )
    target_medium["independent_lineage_count"] = len(target_medium["lineage_ids"])
    if reported_union:
        target_medium["covered_spatial_cells"] = int(reported_union["media"][medium]["covered_spatial_cells"])
        target_medium["reported_covered_spatial_cells"] = int(
            reported_union["media"][medium]["covered_spatial_cells"]
        )
    for key, new_value in replacement.get("medium_elements", {}).items():
        element = new_value["element"]
        target = balance["medium_elements"].get(key)
        old_value = old_by_element.get(element)
        if target is None:
            target = {**new_value}
            balance["medium_elements"][key] = target
        else:
            for field in (
                "observation_count",
                "distinct_sample_count",
                "reported_coordinate_sample_count",
                "valid_coordinate_sample_count",
                "comparable_observation_count",
            ):
                target[field] = int(target[field]) - int((old_value or {}).get(field, 0)) + int(new_value[field])
            target["source_ids"] = sorted(set(target["source_ids"]) | {source_id})
            target["lineage_ids"] = sorted(
                set(target["lineage_ids"]) | set(new_value.get("lineage_ids", []))
            )
            target["independent_lineage_count"] = len(target["lineage_ids"])
        if reported_union and key in reported_union.get("medium_elements", {}):
            union_cells = int(reported_union["medium_elements"][key]["covered_spatial_cells"])
            target["covered_spatial_cells"] = union_cells
            target["reported_covered_spatial_cells"] = union_cells


def _merge_metric(
    base: Mapping[str, Any] | None,
    additions: Sequence[Mapping[str, Any]],
    reported_union: Mapping[str, Any] | None,
) -> dict[str, Any]:
    parts = ([base] if base else []) + list(additions)
    if not parts:
        raise MergeError("cannot merge an empty balance cell")
    source_ids = sorted({value for part in parts for value in part.get("source_ids", [])})
    lineage_ids = sorted(
        {source_adapters.source_lineage_id(source_id) for source_id in source_ids}
        | {value for part in parts for value in part.get("lineage_ids", [])}
    )
    canonical_base_cells = int((base or {}).get("covered_spatial_cells", 0))
    if reported_union is not None:
        reported_cells = int(reported_union["covered_spatial_cells"])
        if reported_cells < canonical_base_cells:
            raise MergeError("reported spatial union cannot be smaller than the canonical baseline")
        canonical_expansion_max = max(
            (int(part.get("covered_spatial_cells", 0)) for part in additions),
            default=0,
        )
        if reported_cells == canonical_base_cells and canonical_expansion_max > canonical_base_cells:
            raise MergeError("expansion cells cannot fit inside the verified baseline union")
    else:
        reported_cells = max(int(part.get("reported_covered_spatial_cells", 0)) for part in parts)
    canonical_cells = max(int(part.get("covered_spatial_cells", 0)) for part in parts)
    if reported_union is not None and int(reported_union["covered_spatial_cells"]) == canonical_base_cells:
        canonical_cells = canonical_base_cells
    return {
        "observation_count": sum(int(part["observation_count"]) for part in parts),
        "distinct_sample_count": sum(int(part["distinct_sample_count"]) for part in parts),
        "independent_lineage_count": len(lineage_ids),
        "source_ids": source_ids,
        "lineage_ids": lineage_ids,
        "reported_coordinate_sample_count": sum(
            int(part.get("reported_coordinate_sample_count", part.get("valid_coordinate_sample_count", 0)))
            for part in parts
        ),
        "valid_coordinate_sample_count": sum(int(part["valid_coordinate_sample_count"]) for part in parts),
        "comparable_observation_count": sum(int(part["comparable_observation_count"]) for part in parts),
        "covered_spatial_cells": canonical_cells,
        "reported_covered_spatial_cells": reported_cells,
        "spatial_grid": "canonical EPSG:4326 1-degree floor cell; no interpolation",
    }


def _merge_balance(
    base: Mapping[str, Any],
    expansions: Sequence[Mapping[str, Any]],
    reported_union: Mapping[str, Any] | None,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "coverage_balance_version": "d1-v4-medium-balance-v1",
        "denominator_definition": "full-cache target observations; sample IDs are deduplicated within source, not across sources",
        "media": {},
        "medium_elements": {},
        "claim_boundary": (
            "More observations do not imply broader coverage. Independent lineage and observed grid-cell counts "
            "must be interpreted alongside sample type, method and region."
        ),
    }
    for section in ("media", "medium_elements"):
        keys = set(base.get(section, {}))
        for expansion in expansions:
            keys.update(expansion.get(section, {}))
        for key in sorted(keys):
            base_value = base.get(section, {}).get(key)
            additions = [
                expansion[section][key]
                for expansion in expansions
                if key in expansion.get(section, {})
            ]
            union_value = (reported_union or {}).get(section, {}).get(key)
            merged = _merge_metric(base_value, additions, union_value)
            if section == "medium_elements":
                medium, element = key.split("|", 1)
                merged = {"medium": medium, "element": element, **merged}
            output[section][key] = merged
    return output


def _profile_summary(profile_dir: Path, source_id: str) -> dict[str, Any]:
    field = _load_json(profile_dir / source_id / "field_completeness.json")
    sample = _load_json(profile_dir / source_id / "sample_type_coverage.json")
    spatial = _load_json(profile_dir / source_id / "spatial_coverage.json")
    media = list(sample.get("media", {}))
    if len(media) != 1:
        raise MergeError(f"{source_id} must resolve to exactly one medium")
    return {
        "source_id": source_id,
        "medium": media[0],
        "observation_count": int(field["observation_count"]),
        "distinct_sample_count": int(spatial["distinct_sample_count"]),
        "reported_coordinate_sample_count": int(spatial["reported_coordinate_sample_count"]),
        "valid_coordinate_sample_count": int(spatial["valid_coordinate_sample_count"]),
        "covered_spatial_cells": int(spatial["covered_spatial_cells"]),
        "method_rate": float(field["fields"]["analytical_method"]["rate"]),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-cube", type=Path, required=True)
    parser.add_argument("--expansion-cube", type=Path, action="append", default=[])
    parser.add_argument("--base-balance", type=Path, required=True)
    parser.add_argument("--expansion-balance", type=Path, action="append", default=[])
    parser.add_argument("--reported-union-balance", type=Path)
    parser.add_argument("--replacement-source-id")
    parser.add_argument("--replacement-cube", type=Path)
    parser.add_argument("--replacement-balance", type=Path)
    parser.add_argument("--profile-dir", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=build_v4_full_profiles.DEFAULT_REGISTRY)
    parser.add_argument("--output-cube", type=Path, required=True)
    parser.add_argument("--output-balance", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows, replaced_rows = _merge_cube(
            args.base_cube,
            args.expansion_cube,
            args.replacement_source_id,
            args.replacement_cube,
        )
        base_balance = _load_json(args.base_balance)
        expansion_balances = [_load_json(path) for path in args.expansion_balance]
        reported_union = _load_json(args.reported_union_balance) if args.reported_union_balance else None
        balance = _merge_balance(base_balance, expansion_balances, reported_union)
        if args.replacement_source_id:
            if args.replacement_balance is None:
                raise MergeError("a replacement source requires --replacement-balance")
            _replace_source_balance(
                balance,
                args.replacement_source_id,
                replaced_rows,
                _load_json(args.replacement_balance),
                reported_union,
            )
        registry = _load_json(args.registry)
        source_ids = sorted({row["source_id"] for row in rows})
        if source_ids != sorted(registry["sources"]):
            raise MergeError("coverage cube sources do not match the source registry")
        cube_totals: dict[str, dict[str, int]] = {}
        for row in rows:
            totals = cube_totals.setdefault(
                row["source_id"],
                {"comparable_observation_count": 0},
            )
            totals["comparable_observation_count"] += int(row["comparable_observation_count"])
        sources = []
        for source_id in source_ids:
            source = _profile_summary(args.profile_dir, source_id)
            source["comparable_observation_count"] = cube_totals[source_id]["comparable_observation_count"]
            sources.append(source)
        summary = {
            "profile_version": build_v4_full_profiles.PROFILE_VERSION,
            "coverage_cube_version": build_v4_full_profiles.CUBE_VERSION,
            "as_of": registry.get("verified_at"),
            "registered_source_count": len(registry["sources"]),
            "source_count": len(sources),
            "observation_count": sum(item["observation_count"] for item in sources),
            "distinct_sample_count": sum(item["distinct_sample_count"] for item in sources),
            "reported_coordinate_sample_count": sum(item["reported_coordinate_sample_count"] for item in sources),
            "valid_coordinate_sample_count": sum(item["valid_coordinate_sample_count"] for item in sources),
            "comparable_observation_count": sum(item["comparable_observation_count"] for item in sources),
            "covered_spatial_cells_source_sum": sum(item["covered_spatial_cells"] for item in sources),
            "coverage_cube_rows": len(rows),
            "media": balance["media"],
            "sources": sources,
            "denominator_definition": "all non-empty registered target observations parsed from verified full caches",
        }
        cube_text = build_v4_full_profiles._csv_text(rows)
        balance_text = json.dumps(balance, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        report_text = build_v4_full_profiles._markdown(summary)
        outputs = {
            args.output_cube: cube_text,
            args.output_balance: balance_text,
            args.output_report: report_text,
        }
        for path, content in outputs.items():
            _atomic_text(path, content)
        artifact_paths = sorted(
            [args.output_cube, args.output_balance, args.output_report]
            + [path for source_id in source_ids for path in (args.profile_dir / source_id).glob("*.json")],
            key=str,
        )
        manifest = {
            **summary,
            "artifacts": [
                {
                    "path": str(path.relative_to(SKILL_DIR)),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
                for path in artifact_paths
            ],
        }
        _atomic_text(
            args.profile_dir / "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, MergeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "summary": summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
