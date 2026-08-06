#!/usr/bin/env python3
"""Materialize the D1/D2/D3 stage-v2 reference run from frozen real sources."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from lab_common import LAB_ROOT, atomic_write_json, prepare_empty_output_dir, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT = LAB_ROOT / "contracts" / "stage-benchmark-v2.json"


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--refresh-downloads", action="store_true")
    args = parser.parse_args()
    prepare_empty_output_dir(args.output_dir)
    fixture_dir = LAB_ROOT / "completion-data" / "fixtures" / "raw"
    download_command = [
        sys.executable,
        str(LAB_ROOT / "scripts" / "build_completion_fixtures.py"),
        "--output-dir",
        str(fixture_dir),
    ]
    if args.refresh_downloads:
        download_command.append("--refresh")
    run(download_command)
    d1, d2, d3 = args.output_dir / "d1", args.output_dir / "d2", args.output_dir / "d3"
    run(
        [
            sys.executable,
            str(LAB_ROOT / "scripts" / "completion_global_d1_adapter.py"),
            "--completion-fixture-dir",
            str(fixture_dir),
            "--output-dir",
            str(d1),
        ]
    )
    run(
        [
            sys.executable,
            str(REPO_ROOT / "workstreams" / "d2" / "scripts" / "geochem_d2_pipeline.py"),
            "--input",
            str(d1 / "d1_completion_export.csv"),
            "--output-dir",
            str(d2),
            "--geology-grid",
            str(fixture_dir / "geology" / "pangaea-788537.zip"),
        ]
    )
    run(
        [
            sys.executable,
            str(LAB_ROOT / "scripts" / "d3_stub.py"),
            "--d2-output-dir",
            str(d2),
            "--coverage-context",
            str(d1 / "d1_completion_manifest.json"),
            "--output-dir",
            str(d3),
        ]
    )
    d1_report = json.loads((d1 / "d1_completion_manifest.json").read_text(encoding="utf-8"))
    qc = json.loads((d2 / "qc_report.json").read_text(encoding="utf-8"))
    geology = json.loads((d2 / "geology_report.json").read_text(encoding="utf-8"))
    anomaly = json.loads((d2 / "anomaly_report.json").read_text(encoding="utf-8"))
    d3_report = json.loads((d3 / "d3_consumer_report.json").read_text(encoding="utf-8"))
    report = {
        "benchmark_version": "geochemical-stage-benchmark-v2",
        "contract": CONTRACT.name,
        "contract_sha256": sha256_file(CONTRACT),
        "status": "pass" if d3_report["counts"]["blocking"]["failed"] == 0 else "fail",
        "d1": {
            "record_count": d1_report["record_count"],
            "source_dataset_count": d1_report["source_dataset_count"],
            "nonempty_continent_medium_cells": d1_report["nonempty_continent_medium_cells"],
            "water_continent_count": d1_report["water_continent_count"],
            "field_coverage": d1_report["field_coverage"],
        },
        "d2": {
            "record_count": qc["record_count"],
            "standardized_record_count": qc["standardized_record_count"],
            "valid_coordinate_count": qc["valid_coordinate_count"],
            "candidate_anomaly_count": anomaly["candidate_count"],
            "unsupported_unit_count": qc["flag_counts"].get("UNSUPPORTED_UNIT", 0),
            "spatial_geology": geology,
        },
        "d3": {
            "status": d3_report["status"],
            "metrics": d3_report["metrics"],
            "showcase": d3_report["showcase"],
            "blocking": d3_report["counts"]["blocking"],
        },
        "absolute_outputs": {
            "d1_exchange": str((d1 / "d1_completion_export.csv").resolve()),
            "d1_manifest": str((d1 / "d1_completion_manifest.json").resolve()),
            "d2_database": str((d2 / "geochemistry.csv").resolve()),
            "d2_directory": str(d2.resolve()),
            "d3_atlas": str((d3 / "atlas.html").resolve()),
            "d3_directory": str(d3.resolve()),
        },
    }
    atomic_write_json(args.output_dir / "stage_v2_reference_report.json", report)
    print(json.dumps(report["absolute_outputs"], ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
