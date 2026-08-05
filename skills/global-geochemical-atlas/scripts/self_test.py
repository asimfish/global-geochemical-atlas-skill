#!/usr/bin/env python3
"""Run deterministic offline regression tests for the bundled Skill."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEMO_INPUT = SKILL_DIR / "fixtures" / "demo_input.csv"
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
VALIDATOR = SCRIPT_DIR / "validate_outputs.py"
DOWNLOADER = SCRIPT_DIR / "download_data.py"

EXPECTED_OUTPUTS = {
    "geochemistry.csv",
    "source_manifest.json",
    "qc_report.json",
    "confidence_report.json",
    "anomalies.geojson",
    "anomaly_report.json",
    "samples.geojson",
    "interactive_map.html",
    "run_summary.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_command(arguments: list[str], expected_code: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != expected_code:
        raise AssertionError(
            f"unexpected exit {result.returncode}, expected {expected_code}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def by_id(rows: list[dict[str, str]], record_id: str) -> dict[str, str]:
    return next(row for row in rows if row["record_id"] == record_id)


def json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_suite() -> dict[str, Any]:
    require(DEMO_INPUT.is_file(), "bundled demo_input.csv is missing")
    for schema_name in (
        "request.schema.json",
        "result.schema.json",
        "geochemistry-record.schema.json",
        "source-manifest.schema.json",
        "confidence-report.schema.json",
        "source-catalog.schema.json",
        "source-route-result.schema.json",
        "source-audit.schema.json",
    ):
        schema = json_value(SKILL_DIR / "references" / schema_name)
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", f"bad {schema_name}")

    with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
        first = Path(first_temp)
        second = Path(second_temp)
        command = [sys.executable, str(WORKFLOW), "--input", str(DEMO_INPUT), "--output-dir"]
        run_command([*command, str(first)])
        run_command([*command, str(second)])
        require({path.name for path in first.iterdir()} == EXPECTED_OUTPUTS, "first run output set is unstable")
        require({path.name for path in second.iterdir()} == EXPECTED_OUTPUTS, "second run output set is unstable")
        for filename in EXPECTED_OUTPUTS:
            require((first / filename).read_bytes() == (second / filename).read_bytes(), f"{filename} is not deterministic")

        validation = run_command([sys.executable, str(VALIDATOR), "--output-dir", str(first)])
        validation_report = json.loads(validation.stdout)
        require(validation_report["status"] == "valid", "output validator did not return valid")

        rows = read_csv(first / "geochemistry.csv")
        require(len(rows) == 19, "demo should contain 19 canonical records")
        require(float(by_id(rows, "rock-fe-001")["normalized_value"]) == 25_000, "wt% conversion failed")
        require(float(by_id(rows, "water-pb-001")["normalized_value"]) == 20, "water mg/L conversion failed")
        ambiguous = by_id(rows, "water-as-ambiguous")
        require(ambiguous["normalized_value"] == "", "ambiguous water ppm must not be converted")
        require("AMBIGUOUS_AQUEOUS_RATIO_UNIT" in ambiguous["qc_flags"], "ambiguous water flag missing")
        censored = by_id(rows, "soil-as-013")
        require(censored["normalized_value"] == "", "censored value was imputed")
        require(float(censored["normalized_censoring_limit"]) == 0.1, "censoring limit was not preserved")
        swapped = by_id(rows, "swap-coord-001")
        require(swapped["latitude"] == "" and swapped["longitude"] == "", "coordinate swap was silently applied")
        require("POSSIBLE_COORDINATE_SWAP" in swapped["qc_flags"], "coordinate swap flag missing")
        duplicates = [row for row in rows if "DUPLICATE_CANDIDATE" in row["qc_flags"]]
        require(len(duplicates) == 2, "duplicate candidates should be retained and flagged")

        anomaly_report = json_value(first / "anomaly_report.json")
        anomalies = json_value(first / "anomalies.geojson")
        require(anomaly_report["candidate_count"] == 1, "demo should contain one anomaly candidate")
        require(anomalies["features"][0]["properties"]["record_id"] == "soil-as-012", "wrong anomaly")
        require(anomalies["features"][0]["properties"]["status"] == "candidate_anomaly", "causal overclaim")
        summary = json_value(first / "run_summary.json")
        require(summary["input"]["synthetic_demo"] is True, "demo must be labeled synthetic")
        require(summary["coverage"]["interpolation"] is False, "demo must not interpolate blank areas")
        manifest = json_value(first / "source_manifest.json")
        confidence_hash = hashlib.sha256((first / "confidence_report.json").read_bytes()).hexdigest()
        require(manifest["confidence_report"]["sha256"] == confidence_hash, "confidence evidence hash mismatch")
        require(manifest["coverage"]["source_locator_rate"] == 1.0, "demo provenance coverage should be complete")

        html = (first / "interactive_map.html").read_text(encoding="utf-8")
        require("<script src=" not in html.casefold(), "map has an external script dependency")
        require("候选异常不代表污染" in html, "map omits interpretation boundary")
        require("\\u003c/script\\u003e" in __import__("build_interactive_map").safe_embedded_json("</script>"), "unsafe JSON embedding")

        limited = first / "limited"
        run_command(
            [sys.executable, str(WORKFLOW), "--input", str(DEMO_INPUT), "--output-dir", str(limited), "--max-records", "5"],
            expected_code=2,
        )
        limited_summary = json_value(limited / "run_summary.json")
        require(limited_summary["status"] == "unsupported_scope", "record limit must fail closed")

        bad_manifest = first / "bad-download.json"
        run_command(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                "http://127.0.0.1/private.csv",
                "--output",
                str(first / "should-not-exist.csv"),
                "--manifest",
                str(bad_manifest),
                "--license",
                "unresolved",
                "--retries",
                "0",
            ],
            expected_code=2,
        )
        require(not (first / "should-not-exist.csv").exists(), "unsafe downloader wrote an output")

        return {
            "status": "PASS",
            "tests": 22,
            "records": len(rows),
            "mapped_records": len(json_value(first / "samples.geojson")["features"]),
            "candidate_anomalies": anomaly_report["candidate_count"],
        }


def main() -> int:
    try:
        report = run_suite()
    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
