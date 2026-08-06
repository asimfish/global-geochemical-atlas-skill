#!/usr/bin/env python3
"""Run isolated, synthetic integration, US holdout, and global D2 validation layers."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lab_common import LAB_ROOT, atomic_write_json, load_json, prepare_empty_output_dir

ISOLATED_SCRIPT = LAB_ROOT / "scripts" / "run_isolated_suite.py"
E2E_SCRIPT = LAB_ROOT / "scripts" / "run_e2e_suite.py"
REAL_SCRIPT = LAB_ROOT / "scripts" / "run_real_data_suite.py"
GLOBAL_SCRIPT = LAB_ROOT / "scripts" / "run_global_data_suite.py"


def stage(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    payload = None
    if len(result.stdout.strip().splitlines()) == 1:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
    return {
        "returncode": result.returncode,
        "payload": payload,
        "stderr_tail": result.stderr[-500:],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run all four D2 validation layers.")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty combined output directory")
    parser.add_argument("--stress-records", type=int, default=10_000, help="Isolated-suite resource smoke size")
    parser.add_argument(
        "--real-max-source-samples",
        type=int,
        default=20,
        help="Real-suite DS801/RASS/Taylor smoke cap; use 0 for the full 40,131-record baseline",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        prepare_empty_output_dir(args.output_dir)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    isolated_path = args.output_dir / "isolated_report.json"
    isolated_stage = stage(
        [
            sys.executable,
            str(ISOLATED_SCRIPT),
            "--report",
            str(isolated_path),
            "--stress-records",
            str(args.stress_records),
        ]
    )
    e2e_dir = args.output_dir / "e2e"
    e2e_stage = stage([sys.executable, str(E2E_SCRIPT), "--output-dir", str(e2e_dir)])
    real_dir = args.output_dir / "real"
    real_stage = stage(
        [
            sys.executable,
            str(REAL_SCRIPT),
            "--output-dir",
            str(real_dir),
            "--max-source-samples",
            str(args.real_max_source_samples),
        ]
    )
    global_dir = args.output_dir / "global"
    global_stage = stage(
        [sys.executable, str(GLOBAL_SCRIPT), "--output-dir", str(global_dir)]
    )
    isolated_report = load_json(isolated_path) if isolated_path.is_file() else None
    e2e_report_path = e2e_dir / "e2e_report.json"
    e2e_report = load_json(e2e_report_path) if e2e_report_path.is_file() else None
    real_report_path = real_dir / "real_data_report.json"
    real_report = load_json(real_report_path) if real_report_path.is_file() else None
    global_report_path = global_dir / "global_data_report.json"
    global_report = load_json(global_report_path) if global_report_path.is_file() else None
    reports = [
        report
        for report in (isolated_report, e2e_report, real_report, global_report)
        if isinstance(report, dict)
    ]
    if (
        isolated_stage["returncode"] != 0
        or e2e_stage["returncode"] != 0
        or real_stage["returncode"] != 0
        or global_stage["returncode"] != 0
        or len(reports) != 4
    ):
        status = "fail"
    elif any(report.get("status") == "pass_with_findings" for report in reports):
        status = "pass_with_findings"
    else:
        status = "pass"
    summary = {
        "suite_version": "d2-validation-combined-v3",
        "status": status,
        "stages": {
            "isolated": isolated_stage,
            "e2e": e2e_stage,
            "real": real_stage,
            "global": global_stage,
        },
        "reports": {
            "isolated": isolated_path.name,
            "e2e": "e2e/e2e_report.json",
            "synthetic_atlas": "e2e/d3/atlas.html",
            "real": "real/real_data_report.json",
            "real_atlas": "real/d3/atlas.html",
            "real_database": "real/d2/geochemistry.csv",
            "real_source_confidence": "real/d3/source_confidence.json",
            "real_anomaly_regions": "real/d3/anomaly_regions.geojson",
            "real_showcase_manifest": "real/d3/showcase_manifest.json",
            "global": "global/global_data_report.json",
            "global_atlas": "global/d3/atlas.html",
            "global_database": "global/d2/geochemistry.csv",
            "global_source_confidence": "global/d3/source_confidence.json",
            "global_anomaly_regions": "global/d3/anomaly_regions.geojson",
            "global_showcase_manifest": "global/d3/showcase_manifest.json",
        },
        "blocking_failed": sum(
            report.get("counts", {}).get("blocking", {}).get("failed", 0) for report in reports
        ),
        "review_failed": sum(
            report.get("counts", {}).get("review", {}).get("failed", 0) for report in reports
        ),
    }
    atomic_write_json(args.output_dir / "summary.json", summary)
    print(
        json.dumps(
            {"status": status, "summary": str(args.output_dir / "summary.json"), **summary["reports"]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
