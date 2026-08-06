#!/usr/bin/env python3
"""Combine the verified source demos into one traceable four-media fixture."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import generate_demo_data as demos
import score_source_evidence
import source_adapters
import source_router
import standardize_geochemistry as standardizer

COMBINED_VERSION = "d1-four-media-combined-v1"
SOURCE_ORDER = (
    "georoc-archaean",
    "usgs-conus-soil",
    "norway-marchem",
    "geotraces-idp2025",
    "gemstat-open-archive",
    "japan-gsj-geochemical-map",
    "pangaea-north-africa-soil",
    "foregs-topsoil",
    "foregs-subsoil",
    "foregs-humus",
    "foregs-stream-water",
    "foregs-stream-sediment",
    "foregs-floodplain-sediment",
    "afsis-phase-i-wet-chemistry",
)
EXPECTED_MEDIA = {
    "georoc-archaean": "rock",
    "usgs-conus-soil": "soil",
    "norway-marchem": "sediment",
    "geotraces-idp2025": "water",
    "gemstat-open-archive": "water",
    "japan-gsj-geochemical-map": "sediment",
    "pangaea-north-africa-soil": "soil",
    "foregs-topsoil": "soil",
    "foregs-subsoil": "soil",
    "foregs-humus": "soil",
    "foregs-stream-water": "water",
    "foregs-stream-sediment": "sediment",
    "foregs-floodplain-sediment": "sediment",
    "afsis-phase-i-wet-chemistry": "soil",
}


class CombinedDemoError(RuntimeError):
    """Raised when checked-in source fixtures cannot be combined exactly."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CombinedDemoError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise CombinedDemoError(f"{label} must be a JSON object: {path}")
    return value


def csv_text(rows: Sequence[Mapping[str, str]]) -> str:
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=demos.INPUT_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.seek(0)
        return handle.read()


def jsonl_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for row in rows
    )


def comparison_key(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in standardizer.DEFAULT_GROUP_BY)


def build(request_path: Path, source_demos: Path, output_dir: Path, generated_at: str, overwrite: bool) -> dict[str, Any]:
    output_paths = {
        "input": output_dir / "demo_input.csv",
        "sources": output_dir / "sources.jsonl",
        "manifest": output_dir / "run_manifest.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing and not overwrite:
        raise CombinedDemoError(f"outputs already exist; use --overwrite after review: {existing}")

    request = load_json(request_path, "combined request")
    catalog = source_router.load_catalog()
    registry = source_adapters.load_source_registry()
    route = source_router.route_sources(request, catalog, registry)
    selected_route = {item["source_id"] for item in route["selected_sources"]}
    if selected_route != set(SOURCE_ORDER):
        raise CombinedDemoError(
            f"combined request no longer selects the frozen source route: {sorted(selected_route)}"
        )
    evidence_report = score_source_evidence.run()

    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    fixture_inputs: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    for source_id in SOURCE_ORDER:
        fixture_dir = source_demos / source_id
        input_path = fixture_dir / "demo_input.csv"
        evidence_path = fixture_dir / "sources.jsonl"
        manifest_path = fixture_dir / "run_manifest.json"
        manifest = load_json(manifest_path, f"{source_id} demo manifest")
        expected_hashes = {item["path"]: item["sha256"] for item in manifest.get("outputs", [])}
        if expected_hashes != {
            "demo_input.csv": sha256_file(input_path),
            "sources.jsonl": sha256_file(evidence_path),
        }:
            raise CombinedDemoError(f"{source_id} fixture hashes no longer match its manifest")
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = [dict(row) for row in csv.DictReader(handle)]
        source_evidence = [
            json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        if len(source_rows) != len(source_evidence) or not source_rows:
            raise CombinedDemoError(f"{source_id} fixture lacks one-to-one observation evidence")
        row_ids = {row.get("record_id", "") for row in source_rows}
        evidence_ids = {str(row.get("record_id") or "") for row in source_evidence if isinstance(row, Mapping)}
        if row_ids != evidence_ids or "" in row_ids or record_ids.intersection(row_ids):
            raise CombinedDemoError(f"{source_id} fixture record IDs are missing, mismatched or duplicated")
        if {row.get("source_id") for row in source_rows} != {source_id}:
            raise CombinedDemoError(f"{source_id} fixture source IDs changed")
        if {row.get("medium") for row in source_rows} != {EXPECTED_MEDIA[source_id]}:
            raise CombinedDemoError(f"{source_id} fixture medium changed")
        record_ids.update(row_ids)
        rows.extend(source_rows)
        evidence_rows.extend(source_evidence)
        fixture_inputs.append(
            {
                "source_id": source_id,
                "input_path": str(input_path.relative_to(source_demos.parent.parent)),
                "input_sha256": sha256_file(input_path),
                "evidence_path": str(evidence_path.relative_to(source_demos.parent.parent)),
                "evidence_sha256": sha256_file(evidence_path),
                "record_count": len(source_rows),
                "source_evidence_score": evidence_report["sources"][source_id]["source_evidence_score"],
                "evidence_tier": evidence_report["sources"][source_id]["evidence_tier"],
                "use_mode": evidence_report["sources"][source_id]["use_mode"],
            }
        )

    input_text = csv_text(rows)
    evidence_text = jsonl_text(evidence_rows)
    atomic_text(output_paths["input"], input_text)
    atomic_text(output_paths["sources"], evidence_text)
    partitions = Counter(comparison_key(row) for row in rows)
    water_partitions = {
        json.dumps(key, ensure_ascii=False): count
        for key, count in sorted(partitions.items())
        if key[1] == "water"
    }
    source_counts = Counter(row["source_id"] for row in rows)
    medium_counts = Counter(row["medium"] for row in rows)
    analyte_counts = Counter(row["element_or_analyte"] for row in rows)
    manifest = {
        "combined_demo_version": COMBINED_VERSION,
        "generated_at": generated_at,
        "data_mode": "fixture",
        "scientific_scope": f"{len(SOURCE_ORDER)} verified source demos combined to exercise one four-media workflow",
        "not_for_scientific_interpretation": True,
        "request": request,
        "route": {
            "status": route["status"],
            "selected_sources": [item["source_id"] for item in route["selected_sources"]],
            "coverage": route["coverage"],
        },
        "fixture_inputs": fixture_inputs,
        "record_counts": {
            "total": len(rows),
            "by_source": dict(sorted(source_counts.items())),
            "by_medium": dict(sorted(medium_counts.items())),
            "by_analyte": dict(sorted(analyte_counts.items())),
        },
        "comparison_isolation": {
            "group_fields": [
                *standardizer.DEFAULT_GROUP_BY,
            ],
            "partition_count": len(partitions),
            "water_partition_count": len(water_partitions),
            "water_partitions": water_partitions,
            "explicit_boundaries": [
                "GEOTRACES seawater nmol/kg is not mixed with GEMStat freshwater mass-per-volume arsenic.",
                "GEMStat dissolved, suspended and total arsenic remain separate comparison groups.",
                "MarChem partial nitric-acid sediment is not interpreted as total content.",
                "USGS soil layers and GEOROC precompiled selected rock values retain their measurement bases.",
                "PANGAEA fine-fraction HF-HNO3 soil is not mixed with USGS bulk-soil layers.",
                "GSJ JGD2000 river sediment keeps its source-specific units and missing method/QC boundary.",
                "FOREGS topsoil, subsoil and humus remain separate sample media within the canonical soil class.",
                "FOREGS total, aqua-regia-leachable, mild-acid-leachable and dissolved values remain separate comparison groups.",
                "FOREGS stream and floodplain sediment remain distinct sampling media and grain-fraction contexts.",
                "AfSIS aqua-regia quasi-total topsoil and subsoil remain separate from total and differently extracted soil values.",
                "AfSIS numeric below-DL or below-QL results retain explicit observation evidence and are not promoted to ordinary detections.",
            ],
        },
        "outputs": [
            {
                "path": output_paths["input"].name,
                "bytes": output_paths["input"].stat().st_size,
                "sha256": sha256_file(output_paths["input"]),
            },
            {
                "path": output_paths["sources"].name,
                "bytes": output_paths["sources"].stat().st_size,
                "sha256": sha256_file(output_paths["sources"]),
            },
        ],
        "warnings": [
            "This combined fixture proves interface compatibility, not representative global coverage.",
            "A common CSV and map do not make different media, fractions, methods, units or extraction bases scientifically comparable.",
            "Anomalies produced from fixture groups are pipeline candidates only and cannot support pollution or depletion claims.",
        ],
        "claim_boundary": (
            f"The combined package binds {len(SOURCE_ORDER)} already verified mini-slices to one request and evidence chain. "
            "It does not increase their geographic representativeness or create independent replication."
        ),
    }
    atomic_json(output_paths["manifest"], manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    skill_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request", type=Path,
        default=skill_dir / "fixtures" / "four-media" / "combined-v3" / "request.json",
    )
    parser.add_argument("--source-demos", type=Path, default=skill_dir / "fixtures" / "source-demos")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = build(
            args.request, args.source_demos, args.output_dir, args.generated_at, args.overwrite
        )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "record_count": manifest["record_counts"]["total"],
                    "partition_count": manifest["comparison_isolation"]["partition_count"],
                },
                sort_keys=True,
            )
        )
        return 0
    except (CombinedDemoError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"build_four_media_demo: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
