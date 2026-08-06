#!/usr/bin/env python3
"""Run the minimal D1 -> real D2 -> minimal D3 consumer-driven validation."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lab_common import (
    CONTRACT_ROOT,
    D2_FIXTURE,
    D2_SCRIPT,
    LAB_ROOT,
    REPO_ROOT,
    CheckBook,
    atomic_write_json,
    load_json,
    prepare_empty_output_dir,
    sha256_file,
)

SUITE_VERSION = "d2-e2e-suite-v1"
D1_SCRIPT = LAB_ROOT / "scripts" / "d1_stub.py"
D3_SCRIPT = LAB_ROOT / "scripts" / "d3_stub.py"
INTERFACE_CONTRACT = (
    REPO_ROOT
    / "evaluation_lyf"
    / "reference_implementation"
    / "d2"
    / "contracts"
    / "interface-contract.json"
)
REQUIRED_D2_FILES = {
    "geochemistry.csv",
    "samples.geojson",
    "anomalies.geojson",
    "qc_report.json",
    "confidence_report.json",
    "geology_report.json",
    "anomaly_report.json",
    "map_spec.json",
    "run_manifest.json",
}


def run_json_command(command: list[str]) -> dict[str, Any]:
    start = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - start
    payload = None
    parse_error = None
    lines = result.stdout.strip().splitlines()
    if len(lines) == 1:
        try:
            payload = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    elif lines:
        parse_error = f"expected one stdout line, received {len(lines)}"
    else:
        parse_error = "stdout was empty"
    return {
        "returncode": result.returncode,
        "elapsed_seconds": round(elapsed, 6),
        "stdout": result.stdout,
        "stderr": result.stderr,
        "payload": payload,
        "parse_error": parse_error,
    }


def parse_d2_database(path: Path) -> list[dict[str, Any]]:
    numeric_fields = {
        "normalized_value",
        "normalized_censoring_limit",
        "latitude",
        "longitude",
    }
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in numeric_fields:
            raw = row.get(field, "")
            row[field] = float(raw) if raw not in (None, "") else None
        row["normalized_unit"] = row.get("normalized_unit") or None
        row["censored"] = str(row.get("censored", "")).casefold() == "true"
        row["qc_flags"] = json.loads(row["qc_flags"])
        row["operational_confidence"] = json.loads(row["operational_confidence"])
    return rows


def values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)
    return actual == expected


def write_early_report(
    output_dir: Path,
    checks: CheckBook,
    stages: dict[str, Any],
    failed_stage: str,
) -> dict[str, Any]:
    summary = checks.summary()
    report = {
        "suite_version": SUITE_VERSION,
        "status": "fail",
        "failed_stage": failed_stage,
        "stages": stages,
        **summary,
    }
    atomic_write_json(output_dir / "e2e_report.json", report)
    return report


def run_e2e(output_dir: Path) -> dict[str, Any]:
    prepare_empty_output_dir(output_dir)
    checks = CheckBook()
    stages: dict[str, Any] = {}
    expectations = load_json(CONTRACT_ROOT / "e2e-expectations.json")
    d1_dir = output_dir / "d1"
    d2_dir = output_dir / "d2"
    d2_repeat_dir = output_dir / "d2-repeat"
    d3_dir = output_dir / "d3"

    d1_result = run_json_command(
        [
            sys.executable,
            str(D1_SCRIPT),
            "--seed",
            str(D2_FIXTURE),
            "--output-dir",
            str(d1_dir),
        ]
    )
    stages["d1"] = {
        key: value for key, value in d1_result.items() if key not in {"stdout", "stderr", "payload"}
    }
    stages["d1"]["stderr_tail"] = d1_result["stderr"][-500:]
    checks.add(
        "d1_cli_succeeds_with_one_json_stdout",
        d1_result["returncode"] == 0
        and isinstance(d1_result["payload"], dict)
        and d1_result["parse_error"] is None,
        category="stage_execution",
        expected={"returncode": 0, "stdout": "one JSON object"},
        actual={"returncode": d1_result["returncode"], "parse_error": d1_result["parse_error"]},
    )
    if d1_result["returncode"] != 0 or not isinstance(d1_result["payload"], dict):
        return write_early_report(output_dir, checks, stages, "d1")

    d1_manifest = load_json(d1_dir / "source_manifest.json")
    schema_map = load_json(d1_dir / "schema_map.json")
    checks.add(
        "d1_manifest_binds_original_seed",
        d1_manifest["source"]["sha256"] == sha256_file(D2_FIXTURE)
        and d1_manifest["source"]["record_count"] == expectations["input_row_count"],
        category="evidence_chain",
        expected={"sha256": sha256_file(D2_FIXTURE), "rows": expectations["input_row_count"]},
        actual={
            "sha256": d1_manifest["source"]["sha256"],
            "rows": d1_manifest["source"]["record_count"],
        },
    )
    checks.add(
        "d1_export_and_schema_map_hashes_match_manifest",
        d1_manifest["export"]["sha256"] == sha256_file(d1_dir / "d1_export.csv")
        and d1_manifest["schema_map"]["sha256"] == sha256_file(d1_dir / "schema_map.json"),
        category="evidence_chain",
    )
    with (d1_dir / "d1_export.csv").open(encoding="utf-8", newline="") as handle:
        d1_reader = csv.DictReader(handle)
        d1_headers = list(d1_reader.fieldnames or [])
        d1_rows = list(d1_reader)
    checks.add(
        "d1_uses_source_shaped_columns_and_explicit_mapping",
        schema_map.get("element_or_analyte") == "ReportedAnalyte"
        and schema_map.get("value") == "ReportedResult"
        and "element_or_analyte" not in d1_rows[0],
        category="d1_to_d2_contract",
        expected="source column names plus canonical->source schema map",
        actual={
            "element_column": schema_map.get("element_or_analyte"),
            "value_column": schema_map.get("value"),
            "headers": d1_headers,
        },
    )
    with D2_FIXTURE.open(encoding="utf-8", newline="") as handle:
        seed_rows = list(csv.DictReader(handle))
    checks.add(
        "d1_preserves_values_units_qualifiers_and_row_count",
        len(d1_rows) == len(seed_rows)
        and [row["ReportedResult"] for row in d1_rows] == [row["value"] for row in seed_rows]
        and [row["ReportedUnit"] for row in d1_rows] == [row["unit"] for row in seed_rows]
        and [row["LegacyQualifier"] for row in d1_rows] == [row["value_qualifier"] for row in seed_rows],
        category="d1_to_d2_contract",
        expected=len(seed_rows),
        actual=len(d1_rows),
    )
    checks.add(
        "d1_assigns_row_level_provenance",
        all(
            row.get("SourceRowKey")
            and row.get("OriginalSourceRow")
            and row.get("OriginalFileSHA256") == sha256_file(D2_FIXTURE)
            for row in d1_rows
        ),
        category="evidence_chain",
    )

    d2_result = run_json_command(
        [
            sys.executable,
            str(D2_SCRIPT),
            "--input",
            str(d1_dir / "d1_export.csv"),
            "--schema-map",
            str(d1_dir / "schema_map.json"),
            "--output-dir",
            str(d2_dir),
            "--min-group-size",
            "8",
        ]
    )
    stages["d2"] = {
        key: value for key, value in d2_result.items() if key not in {"stdout", "stderr", "payload"}
    }
    stages["d2"]["stderr_tail"] = d2_result["stderr"][-500:]
    checks.add(
        "d2_cli_succeeds_with_one_json_stdout",
        d2_result["returncode"] == 0
        and isinstance(d2_result["payload"], dict)
        and d2_result["parse_error"] is None,
        category="stage_execution",
        expected={"returncode": 0, "stdout": "one JSON object"},
        actual={"returncode": d2_result["returncode"], "parse_error": d2_result["parse_error"]},
    )
    if d2_result["returncode"] != 0 or not isinstance(d2_result["payload"], dict):
        return write_early_report(output_dir, checks, stages, "d2")

    present_d2_files = {path.name for path in d2_dir.iterdir() if path.is_file()}
    checks.add(
        "d2_emits_all_nine_public_files",
        REQUIRED_D2_FILES <= present_d2_files,
        category="d2_interface",
        expected=sorted(REQUIRED_D2_FILES),
        actual=sorted(present_d2_files),
    )
    d2_manifest = load_json(d2_dir / "run_manifest.json")
    checks.add(
        "d1_to_d2_hash_chain_is_continuous",
        d2_manifest["input"]["sha256"] == d1_manifest["export"]["sha256"]
        and d2_manifest["input"]["schema_map_sha256"] == d1_manifest["schema_map"]["sha256"],
        category="evidence_chain",
        expected={
            "input": d1_manifest["export"]["sha256"],
            "schema_map": d1_manifest["schema_map"]["sha256"],
        },
        actual={
            "input": d2_manifest["input"]["sha256"],
            "schema_map": d2_manifest["input"]["schema_map_sha256"],
        },
    )
    bad_manifest_hashes = [
        entry["path"]
        for entry in d2_manifest.get("outputs", [])
        if sha256_file(d2_dir / entry["path"]) != entry["sha256"]
    ]
    checks.add(
        "d2_manifest_hashes_match_all_business_outputs",
        not bad_manifest_hashes,
        category="evidence_chain",
        actual=bad_manifest_hashes,
    )

    d2_rows = parse_d2_database(d2_dir / "geochemistry.csv")
    rows_by_id = {row["record_id"]: row for row in d2_rows}
    checks.add(
        "d2_preserves_all_d1_rows",
        len(d2_rows) == expectations["input_row_count"],
        category="record_integrity",
        expected=expectations["input_row_count"],
        actual=len(d2_rows),
    )
    for record_id, field_expectations in expectations["record_expectations"].items():
        row = rows_by_id.get(record_id)
        passed = row is not None
        actual_fields: dict[str, Any] = {}
        if row is not None:
            for field, expected in field_expectations.items():
                if field == "required_flag":
                    actual_fields[field] = row["qc_flags"]
                    passed = passed and expected in row["qc_flags"]
                else:
                    actual_fields[field] = row.get(field)
                    passed = passed and values_equal(row.get(field), expected)
        checks.add(
            f"gold_record_{record_id}",
            passed,
            category="scientific_gold",
            expected=field_expectations,
            actual=actual_fields if row is not None else None,
        )

    qc_report = load_json(d2_dir / "qc_report.json")
    checks.add(
        "qc_counts_match_full_flow_expectations",
        qc_report.get("record_count") == expectations["input_row_count"]
        and qc_report.get("valid_coordinate_count") == expectations["valid_coordinate_count"]
        and qc_report.get("censored_record_count") == expectations["censored_record_count"]
        and all(
            qc_report.get("flag_counts", {}).get(flag) == count
            for flag, count in expectations["expected_flag_counts"].items()
        ),
        category="scientific_gold",
        expected={
            "records": expectations["input_row_count"],
            "valid_coordinates": expectations["valid_coordinate_count"],
            "censored": expectations["censored_record_count"],
            "flags": expectations["expected_flag_counts"],
        },
        actual={
            "records": qc_report.get("record_count"),
            "valid_coordinates": qc_report.get("valid_coordinate_count"),
            "censored": qc_report.get("censored_record_count"),
            "flags": qc_report.get("flag_counts"),
        },
    )
    anomaly_report = load_json(d2_dir / "anomaly_report.json")
    anomalies = load_json(d2_dir / "anomalies.geojson")
    candidate_ids = sorted(
        feature.get("properties", {}).get("record_id") for feature in anomalies.get("features", [])
    )
    checks.add(
        "candidate_anomalies_match_demo_gold",
        candidate_ids == expectations["candidate_record_ids"]
        and anomaly_report.get("scientific_status") == "screening_baseline_only",
        category="scientific_gold",
        expected=expectations["candidate_record_ids"],
        actual=candidate_ids,
    )
    interface_contract = load_json(INTERFACE_CONTRACT)
    checks.add(
        "demo_override_does_not_change_production_default",
        anomaly_report.get("minimum_group_size") == 8
        and interface_contract["d2_to_e2"]["default_anomaly_gates"]["minimum_group_size"] == 20,
        category="scientific_boundary",
        expected={"demo": 8, "production": 20},
        actual={
            "demo": anomaly_report.get("minimum_group_size"),
            "production": interface_contract["d2_to_e2"]["default_anomaly_gates"]["minimum_group_size"],
        },
    )

    duplicate_ids = {"water-pb-001", "water-pb-duplicate"}
    duplicate_flags = {record_id: rows_by_id[record_id]["qc_flags"] for record_id in duplicate_ids}
    checks.add(
        "d1_unique_source_row_ids_do_not_hide_duplicate_candidates",
        all("DUPLICATE_CANDIDATE" in flags for flags in duplicate_flags.values()),
        category="integration_policy",
        severity="review",
        expected="both same-sample Pb rows flagged or explicit alternative policy",
        actual=duplicate_flags,
        note="The full-flow D1 correctly emits distinct source_record_id values, which changes the current duplicate key.",
    )
    checks.add(
        "standalone_anomaly_geojson_is_interface_versioned",
        anomalies.get("interface_version") == expectations["interface_version"],
        category="integration_policy",
        severity="review",
        expected=expectations["interface_version"],
        actual=anomalies.get("interface_version"),
        note="The manifest binds the file, but a standalone GeoJSON consumer cannot identify its interface version.",
    )

    d2_repeat_result = run_json_command(
        [
            sys.executable,
            str(D2_SCRIPT),
            "--input",
            str(d1_dir / "d1_export.csv"),
            "--schema-map",
            str(d1_dir / "schema_map.json"),
            "--output-dir",
            str(d2_repeat_dir),
            "--min-group-size",
            "8",
        ]
    )
    stages["d2_repeat"] = {
        key: value for key, value in d2_repeat_result.items() if key not in {"stdout", "stderr", "payload"}
    }
    byte_mismatches = []
    if d2_repeat_result["returncode"] == 0:
        byte_mismatches = [
            name
            for name in REQUIRED_D2_FILES
            if (d2_dir / name).read_bytes() != (d2_repeat_dir / name).read_bytes()
        ]
    checks.add(
        "full_flow_d2_is_byte_deterministic",
        d2_repeat_result["returncode"] == 0 and not byte_mismatches,
        category="determinism",
        expected="all nine files byte-identical",
        actual={"returncode": d2_repeat_result["returncode"], "mismatches": sorted(byte_mismatches)},
    )

    d3_result = run_json_command(
        [
            sys.executable,
            str(D3_SCRIPT),
            "--d2-output-dir",
            str(d2_dir),
            "--output-dir",
            str(d3_dir),
        ]
    )
    stages["d3"] = {
        key: value for key, value in d3_result.items() if key not in {"stdout", "stderr", "payload"}
    }
    stages["d3"]["stderr_tail"] = d3_result["stderr"][-500:]
    checks.add(
        "d3_cli_succeeds_with_one_json_stdout",
        d3_result["returncode"] == 0
        and isinstance(d3_result["payload"], dict)
        and d3_result["parse_error"] is None,
        category="stage_execution",
        expected={"returncode": 0, "stdout": "one JSON object"},
        actual={"returncode": d3_result["returncode"], "parse_error": d3_result["parse_error"]},
    )
    if d3_result["returncode"] != 0 or not (d3_dir / "d3_consumer_report.json").is_file():
        return write_early_report(output_dir, checks, stages, "d3")

    d3_report = load_json(d3_dir / "d3_consumer_report.json")
    checks.add(
        "d3_consumer_has_no_blocking_contract_failures",
        d3_report.get("counts", {}).get("blocking", {}).get("failed") == 0,
        category="consumer_contract",
        expected=0,
        actual=d3_report.get("counts", {}).get("blocking", {}).get("failed"),
    )
    checks.add(
        "d3_renders_valid_missing_and_censored_counts",
        d3_report.get("metrics", {}).get("rendered_sample_points") == expectations["valid_coordinate_count"]
        and d3_report.get("metrics", {}).get("missing_coordinate_records")
        == expectations["input_row_count"] - expectations["valid_coordinate_count"]
        and d3_report.get("metrics", {}).get("candidate_anomalies") == len(expectations["candidate_record_ids"]),
        category="consumer_contract",
        expected={
            "points": expectations["valid_coordinate_count"],
            "missing": expectations["input_row_count"] - expectations["valid_coordinate_count"],
            "anomalies": len(expectations["candidate_record_ids"]),
        },
        actual=d3_report.get("metrics"),
    )
    atlas_path = d3_dir / "atlas.html"
    atlas_text = atlas_path.read_text(encoding="utf-8") if atlas_path.is_file() else ""
    checks.add(
        "d3_atlas_is_offline_and_contains_scientific_boundaries",
        atlas_path.is_file()
        and "<script src=" not in atlas_text.casefold()
        and "Candidate anomalies" in atlas_text
        and "not probability" in atlas_text,
        category="offline_demo",
        expected="single-file HTML with no remote runtime and both disclaimers",
        actual={"exists": atlas_path.is_file(), "bytes": len(atlas_text.encode("utf-8"))},
    )
    checks.add(
        "d2_to_d3_hash_chain_is_continuous",
        d3_report.get("consumed_sha256", {}).get("run_manifest.json")
        == sha256_file(d2_dir / "run_manifest.json"),
        category="evidence_chain",
        expected=sha256_file(d2_dir / "run_manifest.json"),
        actual=d3_report.get("consumed_sha256", {}).get("run_manifest.json"),
    )

    summary = checks.summary()
    report = {
        "suite_version": SUITE_VERSION,
        "expectations_version": expectations["version"],
        "interface_version": expectations["interface_version"],
        "status": summary["status"],
        "stages": stages,
        "artifacts": {
            "d1_manifest": "d1/source_manifest.json",
            "d2_manifest": "d2/run_manifest.json",
            "d3_report": "d3/d3_consumer_report.json",
            "atlas": "d3/atlas.html",
        },
        "evidence_chain": {
            "seed_sha256": sha256_file(D2_FIXTURE),
            "d1_export_sha256": sha256_file(d1_dir / "d1_export.csv"),
            "d2_manifest_sha256": sha256_file(d2_dir / "run_manifest.json"),
            "atlas_sha256": sha256_file(atlas_path),
        },
        "limitations": [
            "D1 uses a local CC0 synthetic slice and does not test public API availability.",
            "D3 uses an equirectangular SVG test view, not the production geographic UI.",
            "A passing result validates interface sufficiency, not global scientific completeness.",
        ],
        **summary,
    }
    atomic_write_json(output_dir / "e2e_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the minimal D1-D2-D3 full-flow validation suite.")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty directory for all test evidence")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = run_e2e(args.output_dir)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    result = {
        "status": report["status"],
        "report": str(args.output_dir / "e2e_report.json"),
        "atlas": str(args.output_dir / "d3" / "atlas.html") if (args.output_dir / "d3" / "atlas.html").is_file() else None,
        "blocking_failed": report["counts"]["blocking"]["failed"],
        "review_failed": report["counts"]["review"]["failed"],
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
