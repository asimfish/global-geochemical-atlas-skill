#!/usr/bin/env python3
"""Benchmark a synthetic 100k-row SQLite parse/index/filter workload."""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA = SCRIPT_DIR.parent / "references" / "sqlite-schema.sql"


def benchmark(record_count: int = 100_000, schema_path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    if record_count < 1 or record_count > 1_000_000:
        raise ValueError("record_count must be between 1 and 1000000")
    schema_sql = schema_path.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="d1-index-benchmark-") as temporary:
        database = Path(temporary) / "benchmark.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.executescript(schema_sql)
            with connection:
                connection.execute(
                    "INSERT INTO datasets VALUES (?,?,?,?,?,?,?,?,?,?)",
                    ("benchmark-dataset", "synthetic-benchmark", "Synthetic benchmark", "AI4S", None, "v1", "https://example.org/benchmark", "CC0-1.0", "https://creativecommons.org/publicdomain/zero/1.0/", "2026-08-05T00:00:00Z"),
                )
                connection.execute(
                    "INSERT INTO sampling_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("benchmark-event", "benchmark-dataset", "SITE-1", "2026-01-01", "synthetic", "39", "-105", "EPSG:4326", 39.0, -105.0, 1.0, None, 0.0, 0.1, "Synthetic benchmark"),
                )
                connection.execute(
                    "INSERT INTO samples (sample_id, native_sample_id, igsn, parent_sample_id, sampling_event_id, medium_raw, material_raw, lithology_raw, geologic_unit_raw, soil_horizon_raw, grain_fraction_raw, filtered_state_raw, description_raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("benchmark-sample", "SAMPLE-1", None, None, "benchmark-event", "soil", "synthetic", None, None, None, None, None, "Not scientific data"),
                )
                connection.execute(
                    "INSERT INTO analytical_methods (method_id, method_code_raw, preparation_raw, digestion_or_extraction_raw, technique_raw, instrument_raw, laboratory_raw, calibration_raw) VALUES (?,?,?,?,?,?,?,?)",
                    ("benchmark-method", "synthetic", None, None, "synthetic", None, None, None),
                )
                connection.execute(
                    "INSERT INTO acquisition_runs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("benchmark-run", "{}", "[\"benchmark-dataset\"]", "{}", "{}", "2026-08-05T00:00:00Z", "2026-08-05T00:00:00Z", "success", "not_applicable", "{}", "[]"),
                )
                connection.execute(
                    "INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("benchmark-provenance", "synthetic-benchmark", "benchmark-dataset", "benchmark-run", "synthetic-row", "synthetic", None, None, None, None, "0" * 64, "benchmark", "v1", "[]"),
                )

            started = time.perf_counter()
            analytes = ("As", "Cu", "Ni", "Zn")
            batch: list[tuple[Any, ...]] = []
            with connection:
                for offset in range(record_count):
                    value = float(offset % 10_000) / 10.0
                    batch.append(
                        (
                            f"benchmark-observation-{offset:07d}", "benchmark-sample", "benchmark-method",
                            "benchmark-provenance", analytes[offset % len(analytes)], str(value), value,
                            "reported", "mg/kg", "dry weight", None, None, None, None, None,
                        )
                    )
                    if len(batch) == 5000:
                        connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                        batch.clear()
                if batch:
                    connection.executemany("INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
            build_seconds = time.perf_counter() - started

            query_started = time.perf_counter()
            query_count = connection.execute(
                "SELECT COUNT(*) FROM observation_search WHERE analyte_reported = ? AND medium_raw = ? AND parsed_value >= ?",
                ("As", "soil", 500.0),
            ).fetchone()[0]
            query_seconds = time.perf_counter() - query_started
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            index_bytes = database.stat().st_size
        finally:
            connection.close()
    target_seconds = 10.0
    return {
        "benchmark_version": "d1-sqlite-benchmark-v1",
        "status": "PASS" if build_seconds + query_seconds < target_seconds and integrity == "ok" else "FAIL",
        "data_mode": "synthetic_performance_fixture",
        "not_for_scientific_use": True,
        "record_count": record_count,
        "matched_record_count": query_count,
        "parse_and_index_seconds": round(build_seconds, 6),
        "filter_seconds": round(query_seconds, 6),
        "combined_seconds": round(build_seconds + query_seconds, 6),
        "target_seconds": target_seconds,
        "index_bytes": index_bytes,
        "integrity_check": integrity,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=int, default=100_000)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = benchmark(args.records, args.schema)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
