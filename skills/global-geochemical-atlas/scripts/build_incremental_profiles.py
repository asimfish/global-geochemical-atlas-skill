#!/usr/bin/env python3
"""Incrementally rebuild D1 full-population profiles without content hashes.

Each source is keyed by readable publication and file metadata.  An unchanged
source reuses its last complete full profile and coverage-cube rows; a changed
source alone is reparsed from the verified acquisition cache.  Aggregate
artifacts are always regenerated from the per-source states.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import build_v4_full_profiles as full_profiles
import source_adapters


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_DIR = SKILL_DIR.parents[1]
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"
DEFAULT_CACHE = REPO_DIR / ".cache" / "data"
DEFAULT_STATE = REPO_DIR / ".cache" / "d1-incremental-profiles"
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]+$")
STATE_VERSION = "d1-incremental-profile-state-v1"


class IncrementalBuildError(RuntimeError):
    """Raised when an incremental build cannot safely reuse or publish state."""


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise IncrementalBuildError(f"required JSON does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IncrementalBuildError(f"invalid UTF-8 JSON: {path}") from exc


def source_identity(source_id: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    """Return the readable identity fields that determine source reuse."""

    if not SAFE_SOURCE_ID.fullmatch(source_id):
        raise IncrementalBuildError(f"unsafe source_id: {source_id}")
    download = entry.get("download")
    download = download if isinstance(download, Mapping) else {}
    files = download.get("files")
    if not isinstance(files, list):
        files = download.get("members")
    files = files if isinstance(files, list) else []
    file_identity = []
    for item in files:
        if not isinstance(item, Mapping):
            continue
        file_identity.append(
            {
                "file_id": item.get("file_id"),
                "filename": item.get("filename") or item.get("name"),
                "bytes": item.get("bytes"),
                "member_names": item.get("member_names"),
                "schema_fields": item.get("schema_fields"),
                "row_count": item.get("row_count"),
            }
        )
    file_identity.sort(key=lambda value: (str(value.get("file_id")), str(value.get("filename"))))
    return {
        "identity_version": "d1-readable-source-identity-v1",
        "source_id": source_id,
        "dataset_doi": entry.get("dataset_doi"),
        "dataset_pid": entry.get("dataset_pid"),
        "dataset_version": entry.get("dataset_version"),
        "release_date": entry.get("release_date") or download.get("release_date"),
        "observed_at": download.get("observed_at"),
        "adapter": entry.get("adapter"),
        "media": entry.get("media"),
        "target_analytes": entry.get("target_analytes"),
        "files": file_identity,
        "expected_source_records": download.get("expected_source_records"),
        "expected_target_observations": download.get("expected_target_observations"),
    }


def _state_path(state_dir: Path, source_id: str) -> Path:
    if not SAFE_SOURCE_ID.fullmatch(source_id):
        raise IncrementalBuildError(f"unsafe source_id: {source_id}")
    return state_dir / "sources" / f"{source_id}.json"


def _read_state(state_dir: Path, source_id: str) -> dict[str, Any] | None:
    path = _state_path(state_dir, source_id)
    if not path.is_file():
        return None
    value = _load_json(path)
    if not isinstance(value, dict) or value.get("state_version") != STATE_VERSION:
        return None
    if value.get("source_id") != source_id:
        raise IncrementalBuildError(f"source state ID mismatch: {path}")
    if not isinstance(value.get("profile"), dict) or not isinstance(value.get("cube_rows"), list):
        return None
    return value


def plan_sources(
    registry: Mapping[str, Any],
    state_dir: Path,
    *,
    selected_sources: Sequence[str] | None = None,
    forced_sources: Sequence[str] | None = None,
) -> dict[str, Any]:
    sources = registry.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise IncrementalBuildError("registry has no sources")
    selected = set(selected_sources or sources)
    forced = set(forced_sources or [])
    unknown = sorted((selected | forced) - set(sources))
    if unknown:
        raise IncrementalBuildError("unknown source IDs: " + ", ".join(unknown))
    changed: list[str] = []
    reused: list[str] = []
    unavailable: list[str] = []
    identities: dict[str, dict[str, Any]] = {}
    for source_id, entry in sorted(sources.items()):
        if not isinstance(entry, Mapping):
            raise IncrementalBuildError(f"invalid registry entry: {source_id}")
        identity = source_identity(source_id, entry)
        identities[source_id] = identity
        state = _read_state(state_dir, source_id)
        matches = bool(state and state.get("source_identity") == identity)
        if source_id in selected and (source_id in forced or not matches):
            changed.append(source_id)
        elif matches:
            reused.append(source_id)
        else:
            unavailable.append(source_id)
    return {
        "plan_version": "d1-incremental-profile-plan-v1",
        "registered_source_count": len(sources),
        "changed_sources": changed,
        "reused_sources": reused,
        "unavailable_sources": unavailable,
        "source_identities": identities,
        "can_publish_complete_aggregate": not unavailable,
    }


def _summary(
    registry: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    cube_rows: Sequence[Mapping[str, Any]],
    balance: Mapping[str, Any],
) -> dict[str, Any]:
    sources = registry["sources"]
    source_summaries = []
    for source_id, profile in sorted(profiles.items()):
        entry = sources[source_id]
        metrics = profile["coverage_metrics"]
        method_field = profile["field_completeness"]["fields"]["analytical_method"]
        source_summaries.append(
            {
                "source_id": source_id,
                "medium": str((entry.get("media") or [""])[0]),
                **{
                    key: metrics[key]
                    for key in (
                        "observation_count",
                        "distinct_sample_count",
                        "valid_coordinate_sample_count",
                        "comparable_observation_count",
                        "covered_spatial_cells",
                    )
                },
                "method_rate": method_field["rate"],
            }
        )
    return {
        "profile_version": full_profiles.PROFILE_VERSION,
        "coverage_cube_version": full_profiles.CUBE_VERSION,
        "as_of": registry.get("verified_at"),
        "registered_source_count": len(sources),
        "source_count": len(profiles),
        "observation_count": sum(item["observation_count"] for item in source_summaries),
        "distinct_sample_count": sum(item["distinct_sample_count"] for item in source_summaries),
        "valid_coordinate_sample_count": sum(item["valid_coordinate_sample_count"] for item in source_summaries),
        "comparable_observation_count": sum(item["comparable_observation_count"] for item in source_summaries),
        "covered_spatial_cells_source_sum": sum(item["covered_spatial_cells"] for item in source_summaries),
        "coverage_cube_rows": len(cube_rows),
        "media": balance["media"],
        "sources": source_summaries,
        "denominator_definition": "all non-empty registered target observations parsed from verified full caches",
    }


def execute(
    registry_path: Path,
    cache_root: Path,
    state_dir: Path,
    *,
    selected_sources: Sequence[str] | None = None,
    forced_sources: Sequence[str] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    registry = _load_json(registry_path)
    if not isinstance(registry, dict):
        raise IncrementalBuildError("registry root must be an object")
    plan = plan_sources(registry, state_dir, selected_sources=selected_sources, forced_sources=forced_sources)
    sources = registry["sources"]
    for source_id in plan["changed_sources"]:
        profile, cube_rows = full_profiles._profile_one(  # noqa: SLF001 - same D1 subsystem
            source_id,
            sources[source_id],
            str(registry.get("verified_at") or ""),
            cache_root,
        )
        _atomic_json(
            _state_path(state_dir, source_id),
            {
                "state_version": STATE_VERSION,
                "source_id": source_id,
                "source_identity": plan["source_identities"][source_id],
                "profile": profile,
                "cube_rows": cube_rows,
            },
        )
    profiles: dict[str, dict[str, Any]] = {}
    all_cube_rows: list[dict[str, Any]] = []
    missing = []
    for source_id in sorted(sources):
        state = _read_state(state_dir, source_id)
        if not state or state.get("source_identity") != plan["source_identities"][source_id]:
            missing.append(source_id)
            continue
        profiles[source_id] = state["profile"]
        all_cube_rows.extend(state["cube_rows"])
    if missing:
        raise IncrementalBuildError(
            "complete aggregate cannot be published; sources lack current state: " + ", ".join(missing)
        )
    all_cube_rows.sort(
        key=lambda row: tuple(str(row.get(key) or "") for key in full_profiles.CUBE_COLUMNS)
    )
    balance = full_profiles._coverage_balance(profiles)  # noqa: SLF001 - same D1 subsystem
    summary = _summary(registry, profiles, all_cube_rows, balance)
    return {**plan, "executed_source_count": len(plan["changed_sources"])}, profiles, all_cube_rows, {
        "summary": summary,
        "balance": balance,
    }


def publish(
    plan: Mapping[str, Any],
    profiles: Mapping[str, Mapping[str, Any]],
    cube_rows: Sequence[Mapping[str, Any]],
    aggregates: Mapping[str, Any],
    *,
    output_dir: Path,
    coverage_cube: Path,
    coverage_balance: Path,
    report: Path,
) -> None:
    expected_outputs: dict[Path, str] = {
        coverage_cube: full_profiles._csv_text(cube_rows),  # noqa: SLF001
        coverage_balance: json.dumps(aggregates["balance"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        report: full_profiles._markdown(aggregates["summary"]),  # noqa: SLF001
    }
    for source_id, profile in profiles.items():
        for filename, value in full_profiles._split_profile(profile).items():  # noqa: SLF001
            expected_outputs[output_dir / source_id / filename] = (
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            )
    manifest = {
        **aggregates["summary"],
        "incremental_build": {
            key: plan[key]
            for key in ("plan_version", "changed_sources", "reused_sources", "executed_source_count")
        },
        "artifacts": [
            {"path": str(path.relative_to(SKILL_DIR)), "bytes": len(content.encode("utf-8"))}
            for path, content in sorted(expected_outputs.items(), key=lambda item: str(item[0]))
        ],
    }
    expected_outputs[output_dir / "manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ) + "\n"
    for path, content in expected_outputs.items():
        _atomic_text(path, content)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--output-dir", type=Path, default=full_profiles.DEFAULT_OUTPUT)
    parser.add_argument("--coverage-cube", type=Path, default=full_profiles.DEFAULT_CUBE)
    parser.add_argument("--coverage-balance", type=Path, default=full_profiles.DEFAULT_BALANCE)
    parser.add_argument("--report", type=Path, default=full_profiles.DEFAULT_REPORT)
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument("--force-source", action="append", dest="forced_sources")
    parser.add_argument("--plan-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        registry = _load_json(args.registry)
        if args.plan_only:
            result = plan_sources(
                registry,
                args.state_dir,
                selected_sources=args.source_ids,
                forced_sources=args.forced_sources,
            )
        else:
            plan, profiles, cube_rows, aggregates = execute(
                args.registry,
                args.cache_root,
                args.state_dir,
                selected_sources=args.source_ids,
                forced_sources=args.forced_sources,
            )
            publish(
                plan,
                profiles,
                cube_rows,
                aggregates,
                output_dir=args.output_dir,
                coverage_cube=args.coverage_cube,
                coverage_balance=args.coverage_balance,
                report=args.report,
            )
            result = {"status": "PASS", "plan": plan, "summary": aggregates["summary"]}
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        IncrementalBuildError,
        full_profiles.FullProfileError,
        source_adapters.SourceAdapterError,
    ) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
