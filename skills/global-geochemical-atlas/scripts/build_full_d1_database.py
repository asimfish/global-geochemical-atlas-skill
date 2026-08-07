#!/usr/bin/env python3
"""Build a resumable full D1 raw-observation database from registered adapters.

The command writes one immutable-by-metadata source partition at a time, then
publishes a combined CSV, observation-level evidence JSONL, run manifest,
coverage summary, and an optional read-only SQLite query index.  Source reuse is
decided by DOI/PID, version, file identity, byte count, schema and row metadata;
content hashes are deliberately not used.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import build_incremental_profiles
import build_v4_full_profiles as full_profiles
import generate_demo_data
import source_adapters


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_DIR = SKILL_DIR.parents[1]
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"
DEFAULT_CACHE = REPO_DIR / ".cache" / "data"
DEFAULT_OUTPUT = REPO_DIR / "outputs" / "d1-full"
STATE_VERSION = "d1-full-source-partition-state-v1"
FULL_COLUMNS = tuple(generate_demo_data.INPUT_COLUMNS) + (
    "dataset_doi",
    "dataset_pid",
    "dataset_version",
)


class FullDatabaseError(RuntimeError):
    """Raised when a full D1 database cannot be resumed or published safely."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _partition_paths(work_dir: Path, source_id: str) -> tuple[Path, Path, Path]:
    root = work_dir / "sources" / source_id
    return root / "raw_observations.csv", root / "sources.jsonl", root / "state.json"


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("state_version") == STATE_VERSION else None


def _row_for_export(
    source_id: str,
    entry: Mapping[str, Any],
    raw: source_adapters.RawRecord,
    registry_verified_at: str,
    analyte: str,
    field_name: str,
    value: str,
    values: Mapping[str, Any],
    ordinal: int,
) -> dict[str, str]:
    item = full_profiles._observation(  # noqa: SLF001 - shared D1 source mapping
        source_id,
        raw,
        entry,
        registry_verified_at,
        analyte,
        field_name,
        value,
        values,
        ordinal,
    )
    row = {field: str(item.row.get(field) or "") for field in generate_demo_data.INPUT_COLUMNS}
    row.update(
        {
            "dataset_doi": str(entry.get("dataset_doi") or ""),
            "dataset_pid": str(entry.get("dataset_pid") or ""),
            "dataset_version": str(entry.get("dataset_version") or ""),
        }
    )
    return row


def export_source(
    source_id: str,
    entry: Mapping[str, Any],
    registry_verified_at: str,
    cache_root: Path,
    work_dir: Path,
    *,
    force: bool = False,
) -> dict[str, Any]:
    csv_path, evidence_path, state_path = _partition_paths(work_dir, source_id)
    identity = build_incremental_profiles.source_identity(source_id, entry)
    previous = _read_state(state_path)
    if (
        not force
        and previous
        and previous.get("source_identity") == identity
        and csv_path.is_file()
        and evidence_path.is_file()
        and csv_path.stat().st_size == previous.get("csv_bytes")
        and evidence_path.stat().st_size == previous.get("evidence_bytes")
    ):
        return {**previous, "build_action": "reused"}

    files, drift = full_profiles._downloaded_files(source_id, entry, cache_root)  # noqa: SLF001
    adapter = source_adapters.get_adapter(source_id)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=csv_path.parent, prefix=".observations.", delete=False
    )
    evidence_handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=evidence_path.parent, prefix=".evidence.", delete=False
    )
    csv_temp = Path(csv_handle.name)
    evidence_temp = Path(evidence_handle.name)
    observation_count = 0
    parsed_source_records = 0
    samples: set[str] = set()
    located_samples: set[str] = set()
    elements: Counter[str] = Counter()
    try:
        writer = csv.DictWriter(csv_handle, fieldnames=FULL_COLUMNS, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        for raw in adapter.parse(files):
            parsed_source_records += 1
            for ordinal, (analyte, field_name, value, values) in enumerate(
                full_profiles._target_values(source_id, raw.fields, entry)  # noqa: SLF001
            ):
                row = _row_for_export(
                    source_id,
                    entry,
                    raw,
                    registry_verified_at,
                    analyte,
                    field_name,
                    value,
                    values,
                    ordinal,
                )
                writer.writerow(row)
                observation_count += 1
                sample_key = row["sample_id"] or row["source_record_id"]
                samples.add(sample_key)
                try:
                    latitude = float(row["latitude"])
                    longitude = float(row["longitude"])
                except ValueError:
                    pass
                else:
                    if math.isfinite(latitude) and math.isfinite(longitude) and -90 <= latitude <= 90 and -180 <= longitude <= 180:
                        located_samples.add(sample_key)
                elements[row["element_or_analyte"]] += 1
                evidence_handle.write(
                    json.dumps(
                        {
                            "record_id": row["record_id"],
                            "source_id": source_id,
                            "source_record_id": row["source_record_id"],
                            "source_locator": row["source_locator"],
                            "dataset_doi": row["dataset_doi"] or None,
                            "dataset_pid": row["dataset_pid"] or None,
                            "dataset_version": row["dataset_version"],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
        csv_handle.flush()
        evidence_handle.flush()
        os.fsync(csv_handle.fileno())
        os.fsync(evidence_handle.fileno())
    except Exception:
        csv_handle.close()
        evidence_handle.close()
        csv_temp.unlink(missing_ok=True)
        evidence_temp.unlink(missing_ok=True)
        raise
    else:
        csv_handle.close()
        evidence_handle.close()
    os.replace(csv_temp, csv_path)
    os.replace(evidence_temp, evidence_path)
    state = {
        "state_version": STATE_VERSION,
        "source_id": source_id,
        "source_identity": identity,
        "built_at": _now(),
        "build_action": "rebuilt",
        "parsed_source_record_count": parsed_source_records,
        "observation_count": observation_count,
        "distinct_sample_count": len(samples),
        "valid_coordinate_sample_count": len(located_samples),
        "elements": dict(sorted(elements.items())),
        "csv_path": str(csv_path),
        "csv_bytes": csv_path.stat().st_size,
        "evidence_path": str(evidence_path),
        "evidence_bytes": evidence_path.stat().st_size,
        "source_drift": drift,
    }
    _atomic_json(state_path, state)
    return state


def _combine_files(paths: Sequence[Path], output: Path, *, keep_first_header: bool) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        for position, path in enumerate(paths):
            with path.open("rb") as source:
                if position and keep_first_header:
                    source.readline()
                while True:
                    block = source.read(1024 * 1024)
                    if not block:
                        break
                    handle.write(block)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, output)


FLAT_COLUMNS = (
    "observation_id", "analyte_reported", "value_raw", "value_qualifier", "unit_raw",
    "measurement_basis_raw", "sample_id", "sampling_event_id", "medium_raw", "sample_type",
    "lithology_raw", "lithology", "soil_horizon", "sediment_environment", "water_body_type",
    "water_fraction", "geologic_unit_raw", "matched_geologic_unit", "technique_raw", "method_scope",
    "sampled_at_raw", "latitude", "longitude", "source_crs", "source_id", "source_locator",
    "dataset_id", "dataset_version", "dataset_doi", "license_id"
)


def build_flat_index(csv_path: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        connection = sqlite3.connect(temporary)
        connection.executescript(
            f"""
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            CREATE TABLE observation_search ({','.join(f'{name} TEXT' for name in FLAT_COLUMNS)});
            CREATE TABLE sampling_events (
              sampling_event_id TEXT PRIMARY KEY, latitude REAL, longitude REAL
            );
            CREATE VIRTUAL TABLE sampling_event_rtree USING rtree(
              event_rowid, min_longitude, max_longitude, min_latitude, max_latitude
            );
            CREATE VIRTUAL TABLE archive_fts USING fts5(entity_type, entity_id UNINDEXED, searchable_text);
            CREATE VIEW provenance_trace AS
              SELECT observation_id, source_id, source_locator, dataset_version, dataset_doi
              FROM observation_search;
            """
        )
        insert_observation = f"INSERT INTO observation_search VALUES ({','.join('?' for _ in FLAT_COLUMNS)})"
        seen_sources: set[str] = set()
        batch: list[tuple[Any, ...]] = []
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                event_id = f"{row.get('source_id','')}|{row.get('sample_id','')}"
                latitude = full_profiles._numeric(row.get("latitude"))  # noqa: SLF001
                longitude = full_profiles._numeric(row.get("longitude"))  # noqa: SLF001
                connection.execute(
                    "INSERT OR IGNORE INTO sampling_events VALUES (?, ?, ?)",
                    (event_id, latitude, longitude),
                )
                values = {
                    "observation_id": row.get("record_id", ""),
                    "analyte_reported": row.get("element_or_analyte", ""),
                    "value_raw": row.get("value", ""),
                    "value_qualifier": row.get("value_qualifier", ""),
                    "unit_raw": row.get("unit", ""),
                    "measurement_basis_raw": row.get("measurement_basis", ""),
                    "sample_id": row.get("sample_id", ""),
                    "sampling_event_id": event_id,
                    "medium_raw": row.get("medium", ""),
                    "sample_type": row.get("sample_type", ""),
                    "lithology_raw": row.get("lithology_raw", ""),
                    "lithology": row.get("lithology", ""),
                    "soil_horizon": row.get("soil_horizon", ""),
                    "sediment_environment": row.get("sediment_environment", ""),
                    "water_body_type": row.get("water_body_type", ""),
                    "water_fraction": row.get("water_fraction", ""),
                    "geologic_unit_raw": row.get("geologic_unit_raw", ""),
                    "matched_geologic_unit": row.get("matched_geologic_unit", ""),
                    "technique_raw": row.get("analytical_technique") or row.get("analytical_method", ""),
                    "method_scope": row.get("method_scope", ""),
                    "sampled_at_raw": row.get("sampled_at", ""),
                    "latitude": row.get("latitude", ""),
                    "longitude": row.get("longitude", ""),
                    "source_crs": row.get("source_crs", ""),
                    "source_id": row.get("source_id", ""),
                    "source_locator": row.get("source_locator", ""),
                    "dataset_id": row.get("source_id", ""),
                    "dataset_version": row.get("dataset_version", ""),
                    "dataset_doi": row.get("dataset_doi", ""),
                    "license_id": row.get("license", ""),
                }
                batch.append(tuple(values[name] for name in FLAT_COLUMNS))
                source_id = values["source_id"]
                if source_id not in seen_sources:
                    connection.execute(
                        "INSERT INTO archive_fts VALUES ('dataset', ?, ?)",
                        (source_id, " ".join((source_id, values["dataset_doi"], values["dataset_version"]))),
                    )
                    seen_sources.add(source_id)
                if len(batch) >= 10_000:
                    connection.executemany(insert_observation, batch)
                    batch.clear()
            if batch:
                connection.executemany(insert_observation, batch)
        connection.executescript(
            """
            INSERT INTO sampling_event_rtree
              SELECT rowid, longitude, longitude, latitude, latitude
              FROM sampling_events WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
            CREATE INDEX idx_flat_analyte ON observation_search(analyte_reported);
            CREATE INDEX idx_flat_medium ON observation_search(medium_raw);
            CREATE INDEX idx_flat_source ON observation_search(source_id);
            CREATE INDEX idx_flat_sample_type ON observation_search(sample_type);
            CREATE INDEX idx_flat_lithology ON observation_search(lithology, lithology_raw);
            CREATE INDEX idx_flat_geology ON observation_search(geologic_unit_raw, matched_geologic_unit);
            CREATE INDEX idx_flat_method ON observation_search(technique_raw, method_scope);
            CREATE INDEX idx_flat_basis ON observation_search(measurement_basis_raw);
            CREATE INDEX idx_flat_qualifier ON observation_search(value_qualifier);
            """
        )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        count = connection.execute("SELECT COUNT(*) FROM observation_search").fetchone()[0]
        connection.close()
        if integrity != "ok":
            raise FullDatabaseError(f"flat SQLite integrity failure: {integrity}")
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {"path": str(output), "bytes": output.stat().st_size, "observation_count": count, "integrity": "ok"}


def build(
    registry_path: Path,
    cache_root: Path,
    output_dir: Path,
    *,
    source_ids: Sequence[str] | None = None,
    forced_sources: Sequence[str] | None = None,
    with_index: bool = False,
) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = registry.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise FullDatabaseError("source registry is empty")
    selected = sorted(source_ids or sources)
    unknown = sorted(set(selected) - set(sources))
    if unknown:
        raise FullDatabaseError("unknown source IDs: " + ", ".join(unknown))
    force = set(forced_sources or [])
    states = []
    work_dir = output_dir / ".partitions"
    for source_id in selected:
        states.append(
            export_source(
                source_id,
                sources[source_id],
                str(registry.get("verified_at") or ""),
                cache_root,
                work_dir,
                force=source_id in force,
            )
        )
    csv_paths = [_partition_paths(work_dir, source_id)[0] for source_id in selected]
    evidence_paths = [_partition_paths(work_dir, source_id)[1] for source_id in selected]
    combined_csv = output_dir / "raw_observations.csv"
    combined_evidence = output_dir / "sources.jsonl"
    _combine_files(csv_paths, combined_csv, keep_first_header=True)
    _combine_files(evidence_paths, combined_evidence, keep_first_header=False)
    coverage = {
        "coverage_version": "d1-full-database-coverage-v1",
        "source_count": len(states),
        "observation_count": sum(state["observation_count"] for state in states),
        "distinct_sample_count_source_sum": sum(state["distinct_sample_count"] for state in states),
        "valid_coordinate_sample_count_source_sum": sum(state["valid_coordinate_sample_count"] for state in states),
        "sources": [
            {
                key: state[key]
                for key in (
                    "source_id", "observation_count", "distinct_sample_count",
                    "valid_coordinate_sample_count", "elements", "build_action",
                )
            }
            for state in states
        ],
        "claim_boundary": "Counts are observed source records; they do not imply continuous global coverage.",
    }
    _atomic_json(output_dir / "coverage.json", coverage)
    index_report = build_flat_index(combined_csv, output_dir / "index.sqlite") if with_index else None
    manifest = {
        "manifest_version": "d1-full-database-run-v1",
        "built_at": _now(),
        "registry": str(registry_path),
        "source_count": len(states),
        "rebuilt_sources": [state["source_id"] for state in states if state["build_action"] == "rebuilt"],
        "reused_sources": [state["source_id"] for state in states if state["build_action"] == "reused"],
        "outputs": {
            "raw_observations.csv": {"bytes": combined_csv.stat().st_size, "rows": coverage["observation_count"]},
            "sources.jsonl": {"bytes": combined_evidence.stat().st_size, "rows": coverage["observation_count"]},
            "coverage.json": {"bytes": (output_dir / "coverage.json").stat().st_size},
            "index.sqlite": index_report,
        },
        "source_identities": {state["source_id"]: state["source_identity"] for state in states},
        "identity_policy": "readable-source-metadata-only",
    }
    _atomic_json(output_dir / "run_manifest.json", manifest)
    return {"status": "PASS", "manifest": manifest, "coverage": coverage}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument("--force-source", action="append", dest="forced_sources")
    parser.add_argument("--with-index", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build(
            args.registry,
            args.cache_root,
            args.output_dir,
            source_ids=args.source_ids,
            forced_sources=args.forced_sources,
            with_index=args.with_index,
        )
    except (OSError, ValueError, json.JSONDecodeError, FullDatabaseError, source_adapters.SourceAdapterError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
