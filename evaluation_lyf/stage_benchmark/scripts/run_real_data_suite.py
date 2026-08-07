#!/usr/bin/env python3
"""Run frozen real sources through minimal D1 -> real D2 -> minimal D3."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_common import (
    CONTRACT_ROOT,
    D2_SCRIPT,
    LAB_ROOT,
    CheckBook,
    atomic_write_json,
    load_json,
    prepare_empty_output_dir,
    sha256_file,
)

SUITE_VERSION = "d2-real-data-suite-v3"
FETCH_SCRIPT = LAB_ROOT / "scripts" / "fetch_real_fixtures.py"
D1_SCRIPT = LAB_ROOT / "scripts" / "real_d1_adapter.py"
D3_SCRIPT = LAB_ROOT / "scripts" / "d3_stub.py"
SOURCE_CONTRACT = CONTRACT_ROOT / "real-sources.json"
GOLD_CONTRACT = CONTRACT_ROOT / "real-gold.json"
DEFAULT_FIXTURE_DIR = LAB_ROOT / "real-data" / "fixtures" / "raw"
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
NUMERIC_FIELDS = {
    "original_value",
    "normalized_value",
    "normalized_censoring_limit",
    "conversion_factor",
    "latitude",
    "longitude",
    "coordinate_uncertainty_m",
    "sample_depth_min_m",
    "sample_depth_max_m",
    "detection_limit",
}


def run_json_command(command: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    elapsed = time.perf_counter() - started
    payload: Any = None
    parse_error: str | None = None
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
        "payload": payload,
        "parse_error": parse_error,
        "stderr_tail": result.stderr[-1000:],
    }


def stage_succeeded(result: Mapping[str, Any]) -> bool:
    return result.get("returncode") == 0 and isinstance(result.get("payload"), dict) and not result.get("parse_error")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_optional_number(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def parse_d2_database(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        for raw in reader:
            row: dict[str, Any] = {
                key: (value if value not in (None, "") else None) for key, value in raw.items()
            }
            for field in NUMERIC_FIELDS:
                row[field] = parse_optional_number(row.get(field))
            row["censored"] = str(raw.get("censored", "")).casefold() == "true"
            row["qc_flags"] = json.loads(raw.get("qc_flags") or "[]")
            row["operational_confidence"] = json.loads(raw.get("operational_confidence") or "{}")
            rows.append(row)
    return headers, rows


def values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return isinstance(actual, (int, float)) and math.isclose(
            float(actual), expected, rel_tol=1e-10, abs_tol=1e-12
        )
    return actual == expected


def add_stage_check(checks: CheckBook, name: str, result: Mapping[str, Any]) -> None:
    checks.add(
        name,
        stage_succeeded(result),
        category="stage_execution",
        expected={"returncode": 0, "stdout": "one JSON object"},
        actual={"returncode": result.get("returncode"), "parse_error": result.get("parse_error")},
    )


def write_early_report(
    output_dir: Path,
    checks: CheckBook,
    stages: Mapping[str, Any],
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
    atomic_write_json(output_dir / "real_data_report.json", report)
    return report


def source_data_hashes(contract: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(resource["dataset_id"]): str(resource["sha256"])
        for resource in contract["resources"]
        if resource["role"] == "data"
    }


def run_real_suite(output_dir: Path, fixture_dir: Path, max_source_samples: int) -> dict[str, Any]:
    prepare_empty_output_dir(output_dir)
    checks = CheckBook()
    stages: dict[str, Any] = {}
    source_contract = load_json(SOURCE_CONTRACT)
    gold = load_json(GOLD_CONTRACT)

    fetch_result = run_json_command(
        [
            sys.executable,
            str(FETCH_SCRIPT),
            "--fixture-dir",
            str(fixture_dir),
            "--offline",
        ]
    )
    stages["fixture_verification"] = fetch_result
    add_stage_check(checks, "offline_fixture_verification_succeeds", fetch_result)
    if not stage_succeeded(fetch_result):
        return write_early_report(output_dir, checks, stages, "fixture_verification")

    fixture_manifest_path = fixture_dir / "source_manifest.json"
    fixture_manifest = load_json(fixture_manifest_path)
    expected_resources = {resource["id"]: resource for resource in source_contract["resources"]}
    actual_resources = {resource["id"]: resource for resource in fixture_manifest["resources"]}
    resource_mismatches = []
    for resource_id, expected in expected_resources.items():
        actual = actual_resources.get(resource_id, {})
        if (
            actual.get("sha256") != expected["sha256"]
            or actual.get("bytes") != expected["bytes"]
            or not (fixture_dir / expected["local_file"]).is_file()
        ):
            resource_mismatches.append(resource_id)
    checks.add(
        "all_raw_resources_match_pinned_hashes_and_sizes",
        len(actual_resources) == len(expected_resources) and not resource_mismatches,
        category="source_evidence",
        expected=sorted(expected_resources),
        actual={"resources": sorted(actual_resources), "mismatches": resource_mismatches},
    )
    checks.add(
        "four_real_datasets_cover_rock_soil_sediment_and_water",
        {item["medium"] for item in source_contract["datasets"]}
        == {"rock", "soil", "sediment", "water"},
        category="source_coverage",
        expected=["rock", "sediment", "soil", "water"],
        actual=sorted({item["medium"] for item in source_contract["datasets"]}),
    )
    checks.add(
        "source_queries_citations_licenses_and_limits_are_declared",
        all(
            dataset.get("citation")
            and dataset.get("doi")
            and dataset.get("license")
            and len(dataset.get("scientific_limits", [])) >= 3
            for dataset in source_contract["datasets"]
        )
        and all(
            str(resource.get("url", "")).startswith("https://")
            and str(resource.get("landing_page", "")).startswith("https://")
            for resource in source_contract["resources"]
        ),
        category="source_evidence",
    )
    fixture_bytes = int(fixture_manifest["total_bytes"])
    checks.add(
        "frozen_real_fixture_is_between_one_and_five_megabytes",
        1_000_000 <= fixture_bytes <= 5_000_000,
        category="resource_budget",
        expected="1-5 MB",
        actual=fixture_bytes,
    )

    d1_dir = output_dir / "d1"
    d1_result = run_json_command(
        [
            sys.executable,
            str(D1_SCRIPT),
            "--fixture-dir",
            str(fixture_dir),
            "--output-dir",
            str(d1_dir),
            "--max-source-samples",
            str(max_source_samples),
        ]
    )
    stages["d1_real_adapters"] = d1_result
    add_stage_check(checks, "four_real_d1_adapters_succeed", d1_result)
    if not stage_succeeded(d1_result):
        return write_early_report(output_dir, checks, stages, "d1_real_adapters")

    d1_manifest = load_json(d1_dir / "d1_real_manifest.json")
    d1_rows = read_csv(d1_dir / "d1_real_export.csv")
    source_counts = Counter(row["source_id"] for row in d1_rows)
    medium_counts = Counter(row["medium"] for row in d1_rows)
    checks.add(
        "d1_adapter_retains_minimum_gold_coverage",
        all(
            source_counts[source_id] >= minimum
            for source_id, minimum in gold["minimum_adapter_counts"].items()
        ),
        category="d1_real_mapping",
        expected=gold["minimum_adapter_counts"],
        actual=dict(sorted(source_counts.items())),
    )
    checks.add(
        "d1_export_hash_and_count_match_manifest",
        d1_manifest["export"]["sha256"] == sha256_file(d1_dir / "d1_real_export.csv")
        and d1_manifest["export"]["record_count"] == len(d1_rows),
        category="evidence_chain",
        expected={"records": len(d1_rows), "sha256": sha256_file(d1_dir / "d1_real_export.csv")},
        actual={
            "records": d1_manifest["export"]["record_count"],
            "sha256": d1_manifest["export"]["sha256"],
        },
    )
    checks.add(
        "d1_export_contains_all_four_media",
        set(medium_counts) == {"rock", "soil", "sediment", "water"},
        category="d1_real_mapping",
        expected=["rock", "sediment", "soil", "water"],
        actual=sorted(medium_counts),
    )
    rows_by_id = {row["record_id"]: row for row in d1_rows}
    for record_id, raw_qualifier in gold["d1_raw_qualifier_expectations"].items():
        row = rows_by_id.get(record_id)
        checks.add(
            f"d1_preserves_raw_qualifier_{record_id}",
            row is not None and row.get("source_qualifier_raw") == raw_qualifier,
            category="scientific_gold",
            expected=raw_qualifier,
            actual=None if row is None else row.get("source_qualifier_raw"),
        )
    data_hashes = source_data_hashes(source_contract)
    bad_d1_provenance = [
        row["record_id"]
        for row in d1_rows
        if row.get("file_sha256") != data_hashes.get(row.get("source_id", ""))
        or not row.get("source_locator", "").startswith("https://")
        or not row.get("license")
        or not row.get("source_row")
    ]
    checks.add(
        "every_d1_measurement_has_row_level_source_evidence",
        not bad_d1_provenance,
        category="evidence_chain",
        actual=bad_d1_provenance[:20],
    )

    d2_dir = output_dir / "d2"
    d2_result = run_json_command(
        [
            sys.executable,
            str(D2_SCRIPT),
            "--input",
            str(d1_dir / "d1_real_export.csv"),
            "--output-dir",
            str(d2_dir),
        ]
    )
    stages["d2"] = d2_result
    add_stage_check(checks, "real_d2_cli_succeeds", d2_result)
    if not stage_succeeded(d2_result):
        return write_early_report(output_dir, checks, stages, "d2")

    present_d2_files = {path.name for path in d2_dir.iterdir() if path.is_file()}
    checks.add(
        "real_run_emits_all_nine_d2_files",
        REQUIRED_D2_FILES <= present_d2_files,
        category="d2_interface",
        expected=sorted(REQUIRED_D2_FILES),
        actual=sorted(present_d2_files),
    )
    d2_manifest = load_json(d2_dir / "run_manifest.json")
    bad_output_hashes = [
        entry["path"]
        for entry in d2_manifest.get("outputs", [])
        if not (d2_dir / entry["path"]).is_file()
        or sha256_file(d2_dir / entry["path"]) != entry["sha256"]
    ]
    checks.add(
        "real_d2_manifest_closes_input_and_output_hash_chain",
        d2_manifest["input"]["sha256"] == d1_manifest["export"]["sha256"]
        and not bad_output_hashes,
        category="evidence_chain",
        actual={"input": d2_manifest["input"]["sha256"], "bad_outputs": bad_output_hashes},
    )

    d2_headers, d2_rows = parse_d2_database(d2_dir / "geochemistry.csv")
    d2_by_id = {row["record_id"]: row for row in d2_rows}
    checks.add(
        "real_records_are_not_silently_dropped_or_collapsed",
        len(d2_rows) == len(d1_rows) and len(d2_by_id) == len(d1_rows),
        category="record_integrity",
        expected=len(d1_rows),
        actual={"rows": len(d2_rows), "unique_record_ids": len(d2_by_id)},
    )
    for record_id, expectations in gold["record_expectations"].items():
        row = d2_by_id.get(record_id)
        passed = row is not None
        actual_fields: dict[str, Any] = {}
        if row is not None:
            for field, expected in expectations.items():
                if field == "required_flags":
                    actual_fields[field] = row["qc_flags"]
                    passed = passed and all(flag in row["qc_flags"] for flag in expected)
                else:
                    actual_fields[field] = row.get(field)
                    passed = passed and values_equal(row.get(field), expected)
        checks.add(
            f"real_gold_{record_id}",
            passed,
            category="scientific_gold",
            expected=expectations,
            actual=actual_fields if row is not None else None,
        )

    bad_d2_provenance = [
        row["record_id"]
        for row in d2_rows
        if row.get("file_sha256") != data_hashes.get(row.get("source_id"))
        or not str(row.get("source_locator") or "").startswith("https://")
        or not row.get("license")
    ]
    checks.add(
        "d2_database_preserves_real_source_evidence",
        not bad_d2_provenance,
        category="evidence_chain",
        actual=bad_d2_provenance[:20],
    )
    censored_as_values = [
        row["record_id"] for row in d2_rows if row["censored"] and row["normalized_value"] is not None
    ]
    checks.add(
        "real_censored_and_nondetect_results_are_never_imputed_as_values",
        not censored_as_values,
        category="scientific_semantics",
        actual=censored_as_values[:20],
    )
    non_wgs_rows = [
        row
        for row in d2_rows
        if row.get("source_id")
        in {
            "usgs_rass_circle",
            "usgs_taylor_mountains_rock",
            "wqp_usgs_01594440_arsenic",
        }
    ]
    silently_mapped_non_wgs = [
        row["record_id"]
        for row in non_wgs_rows
        if row["latitude"] is not None
        or row["longitude"] is not None
        or "UNSUPPORTED_SOURCE_CRS" not in row["qc_flags"]
    ]
    checks.add(
        "nad27_and_nad83_are_not_silently_treated_as_wgs84",
        not silently_mapped_non_wgs,
        category="scientific_semantics",
        actual=silently_mapped_non_wgs[:20],
    )
    soil_rows = [row for row in d2_rows if row.get("source_id") == "usgs_ds801"]
    checks.add(
        "published_wgs84_soil_coordinates_remain_mappable",
        bool(soil_rows) and all(row["latitude"] is not None and row["longitude"] is not None for row in soil_rows),
        category="scientific_semantics",
        expected=len(soil_rows),
        actual=sum(row["latitude"] is not None and row["longitude"] is not None for row in soil_rows),
    )

    qc_report = load_json(d2_dir / "qc_report.json")
    confidence_report = load_json(d2_dir / "confidence_report.json")
    anomaly_report = load_json(d2_dir / "anomaly_report.json")
    anomalies = load_json(d2_dir / "anomalies.geojson")
    analyzed_groups = [group for group in anomaly_report.get("groups", []) if group.get("status") == "analyzed"]
    checks.add(
        "real_data_exercises_at_least_one_anomaly_background_group",
        bool(analyzed_groups),
        category="anomaly",
        expected=">=1 analyzed group",
        actual=len(analyzed_groups),
    )
    checks.add(
        "real_anomaly_screening_keeps_method_and_extraction_in_background_key",
        "method_family" in anomaly_report.get("group_by", [])
        and "digestion_or_extraction" in anomaly_report.get("group_by", [])
        and anomaly_report.get("scientific_status") == "screening_baseline_only",
        category="scientific_boundary",
        actual={
            "group_by": anomaly_report.get("group_by"),
            "scientific_status": anomaly_report.get("scientific_status"),
        },
    )
    anomaly_features = anomalies.get("features", [])
    bad_anomalies = [
        feature.get("properties", {}).get("record_id")
        for feature in anomaly_features
        if not feature.get("properties", {}).get("source_locator")
        or feature.get("properties", {}).get("status") != "candidate_anomaly"
        or "no causal claim" not in feature.get("properties", {}).get("interpretation_limit", "")
    ]
    checks.add(
        "real_candidate_anomalies_remain_traceable_and_noncausal",
        len(anomaly_features) == anomaly_report.get("candidate_count") and not bad_anomalies,
        category="scientific_boundary",
        actual={"candidate_count": len(anomaly_features), "bad": bad_anomalies[:20]},
    )

    # These review checks intentionally expose handoff gaps instead of laundering them into a pass.
    checks.add(
        "d2_public_database_preserves_source_qualifier_raw",
        "source_qualifier_raw" in d2_headers,
        category="interface_gap",
        severity="review",
        expected="source_qualifier_raw column survives D1 -> D2",
        actual=(
            "present in d1_real_export.csv and geochemistry.csv"
            if "source_qualifier_raw" in d2_headers
            else "present only in d1_real_export.csv"
        ),
        note="RASS L, Taylor < and WQP detection-condition wording must remain available beside the canonical qualifier.",
    )
    mappable_media = {row["medium"] for row in d2_rows if row["latitude"] is not None and row["longitude"] is not None}
    checks.add(
        "all_real_media_are_available_to_d3_as_canonical_wgs84_points",
        mappable_media == {"rock", "soil", "sediment", "water"},
        category="integration_gap",
        severity="review",
        expected=["rock", "sediment", "soil", "water"],
        actual=sorted(mappable_media),
        note="D1 needs a declared, tested reprojection step for RASS/Taylor NAD27 and WQP NAD83 before those media can be mapped.",
    )
    ambiguous_rock_percent = [
        row["record_id"]
        for row in d2_rows
        if row.get("source_id") == "usgs_taylor_mountains_rock"
        and row.get("original_unit") == "%"
        and "UNSUPPORTED_UNIT" in row["qc_flags"]
    ]
    checks.add(
        "published_rock_percent_has_explicit_mass_basis_before_normalization",
        not ambiguous_rock_percent,
        category="integration_gap",
        severity="review",
        expected="0 unresolved bare-percent rock measurements",
        actual=len(ambiguous_rock_percent),
        note=(
            "The source publishes Fe as bare percent. D2 correctly refuses to assume weight percent; "
            "D1 must bind an explicit source-dictionary mass basis before mapping it to wt.%/mg/kg."
        ),
    )
    method_fraction = sum(bool(row.get("analytical_method")) for row in d2_rows) / len(d2_rows)
    checks.add(
        "all_real_measurements_have_explicit_analytical_method",
        method_fraction == 1.0,
        category="source_completeness",
        severity="review",
        expected=1.0,
        actual=round(method_fraction, 6),
        note="The frozen WQP historical query legitimately omits methods for many rows; confidence and UI must expose this.",
    )
    geologic_fraction = sum(bool(row.get("geologic_unit")) for row in d2_rows) / len(d2_rows)
    checks.add(
        "real_holdout_has_versioned_geologic_context_for_spatial_backgrounds",
        geologic_fraction > 0,
        category="integration_gap",
        severity="review",
        expected=">0",
        actual=round(geologic_fraction, 6),
        note="Taylor rock formation is a versioned source-table observation; other media still need a declared geologic spatial join.",
    )

    d3_dir = output_dir / "d3"
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
    stages["d3"] = d3_result
    add_stage_check(checks, "real_d3_consumer_succeeds", d3_result)
    if not stage_succeeded(d3_result):
        return write_early_report(output_dir, checks, stages, "d3")
    d3_report = load_json(d3_dir / "d3_consumer_report.json")
    checks.add(
        "real_d3_has_no_blocking_contract_failures_and_builds_offline_atlas",
        d3_report.get("counts", {}).get("blocking", {}).get("failed") == 0
        and (d3_dir / "atlas.html").is_file()
        and d3_report.get("atlas", {}).get("offline") is True,
        category="d3_interface",
        actual={
            "blocking_failed": d3_report.get("counts", {}).get("blocking", {}).get("failed"),
            "atlas": (d3_dir / "atlas.html").is_file(),
        },
    )
    showcase_manifest = load_json(d3_dir / "showcase_manifest.json")
    source_confidence_showcase = load_json(d3_dir / "source_confidence.json")
    anomaly_regions = load_json(d3_dir / "anomaly_regions.geojson")
    anomaly_region_report = load_json(d3_dir / "anomaly_region_report.json")
    expected_deliverables = {
        "interactive_element_map",
        "standardized_geochemical_database",
        "source_and_confidence_explanation",
        "anomaly_region_results",
    }
    deliverables = showcase_manifest.get("deliverables", {})
    deliverable_hash_mismatches = []
    for name, item in deliverables.items():
        artifact_path = (d3_dir / str(item.get("path", ""))).resolve()
        if not artifact_path.is_file() or sha256_file(artifact_path) != item.get("sha256"):
            deliverable_hash_mismatches.append(name)
    checks.add(
        "real_showcase_emits_four_hashed_competition_deliverables",
        set(deliverables) == expected_deliverables and not deliverable_hash_mismatches,
        category="product_acceptance",
        expected=sorted(expected_deliverables),
        actual={
            "deliverables": sorted(deliverables),
            "hash_mismatches": deliverable_hash_mismatches,
        },
    )
    source_ids_in_showcase = {
        item.get("source_id") for item in source_confidence_showcase.get("sources", [])
    }
    checks.add(
        "real_source_confidence_covers_all_sources_with_components_and_limits",
        source_confidence_showcase.get("global_confidence", {}).get("not_a_probability") is True
        and source_ids_in_showcase == set(source_counts)
        and all(
            item.get("confidence", {}).get("component_means")
            and item.get("source_files")
            and item.get("license")
            for item in source_confidence_showcase.get("sources", [])
        )
        and len(source_confidence_showcase.get("interpretation_limits", [])) >= 3,
        category="product_acceptance",
        expected=sorted(source_counts),
        actual=sorted(source_id for source_id in source_ids_in_showcase if source_id),
    )
    region_features = anomaly_regions.get("features", [])
    region_record_ids = {
        record_id
        for feature in region_features
        for record_id in feature.get("properties", {}).get("record_ids", [])
    }
    checks.add(
        "real_anomaly_regions_reconcile_all_candidates_without_silent_loss",
        anomaly_region_report.get("candidate_point_count") == len(anomaly_features)
        and anomaly_region_report.get("mappable_candidate_point_count") == len(region_record_ids)
        and anomaly_region_report.get("unmappable_candidate_point_count")
        + len(region_record_ids)
        == len(anomaly_features)
        and (
            len(region_features) > 0
            or anomaly_region_report.get("mappable_candidate_point_count") == 0
        )
        and all(
            "not a geological boundary"
            in feature.get("properties", {}).get("interpretation_limit", "")
            for feature in region_features
        ),
        category="product_acceptance",
        expected=len(anomaly_features),
        actual={
            "mapped_candidate_ids": len(region_record_ids),
            "unmappable_candidate_ids": anomaly_region_report.get(
                "unmappable_candidate_point_count"
            ),
            "region_cells": len(region_features),
        },
    )

    confidence_bands = Counter(row["operational_confidence"].get("band") for row in d2_rows)
    total_elapsed = sum(float(stage.get("elapsed_seconds", 0)) for stage in stages.values())
    d2_output_bytes = sum(path.stat().st_size for path in d2_dir.iterdir() if path.is_file())
    checks.add(
        "real_flow_stays_inside_competition_runtime_and_repository_budgets",
        total_elapsed < 900 and fixture_bytes < 250_000_000,
        category="resource_budget",
        expected={"runtime_seconds": "<900", "frozen_fixture_bytes": "<250000000"},
        actual={"runtime_seconds": round(total_elapsed, 3), "frozen_fixture_bytes": fixture_bytes},
    )

    summary = checks.summary()
    report = {
        "suite_version": SUITE_VERSION,
        "interface_version": "d2-interface-v2",
        "status": summary["status"],
        "configuration": {
            "fixture_dir": str(fixture_dir),
            "max_source_samples": max_source_samples,
            "network": "disabled; pinned fixtures verified before use",
        },
        "source_inventory": [
            {
                "id": dataset["id"],
                "title": dataset["title"],
                "medium": dataset["medium"],
                "doi": dataset["doi"],
                "license": dataset["license"],
                "scientific_limits": dataset["scientific_limits"],
            }
            for dataset in source_contract["datasets"]
        ],
        "metrics": {
            "frozen_resource_count": len(actual_resources),
            "frozen_fixture_bytes": fixture_bytes,
            "d1_record_count": len(d1_rows),
            "records_by_source": dict(sorted(source_counts.items())),
            "records_by_medium": dict(sorted(medium_counts.items())),
            "d2_standardized_value_count": sum(row["normalized_value"] is not None for row in d2_rows),
            "d2_censored_record_count": sum(row["censored"] for row in d2_rows),
            "d2_mappable_record_count": sum(
                row["latitude"] is not None and row["longitude"] is not None for row in d2_rows
            ),
            "d2_qc_flag_counts": qc_report.get("flag_counts", {}),
            "confidence_band_counts": dict(sorted(confidence_bands.items())),
            "analyzed_background_groups": len(analyzed_groups),
            "candidate_anomalies": len(anomaly_features),
            "anomaly_region_cells": len(region_features),
            "candidate_anomaly_clusters": anomaly_region_report.get("status_counts", {}).get(
                "candidate_cluster", 0
            ),
            "unmappable_candidate_anomalies": anomaly_region_report.get(
                "unmappable_candidate_point_count", 0
            ),
            "d3_atlas_bytes": (d3_dir / "atlas.html").stat().st_size,
            "d2_output_bytes": d2_output_bytes,
            "stage_elapsed_seconds": {
                name: stage.get("elapsed_seconds") for name, stage in stages.items()
            },
            "total_stage_elapsed_seconds": round(total_elapsed, 6),
        },
        "artifacts": {
            "d1_export": "d1/d1_real_export.csv",
            "d1_manifest": "d1/d1_real_manifest.json",
            "d2_database": "d2/geochemistry.csv",
            "d2_qc": "d2/qc_report.json",
            "d2_confidence": "d2/confidence_report.json",
            "d2_anomaly_report": "d2/anomaly_report.json",
            "d3_atlas": "d3/atlas.html",
            "d3_showcase_manifest": "d3/showcase_manifest.json",
            "d3_source_confidence": "d3/source_confidence.json",
            "d3_anomaly_regions": "d3/anomaly_regions.geojson",
            "d3_anomaly_region_report": "d3/anomaly_region_report.json",
            "d3_report": "d3/d3_consumer_report.json",
        },
        "interpretation": {
            "scientific_status": "validation_evidence_only",
            "not_a_conclusion": True,
            "statement": (
                "Passing checks demonstrate behavior on the four frozen source products; they do not demonstrate "
                "global representativeness, geological cause, contamination, or mineralization."
            ),
        },
        "stages": stages,
        "confidence_report_not_probability": confidence_report.get("not_a_probability"),
        **summary,
    }
    atomic_write_json(output_dir / "real_data_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the offline real-data D1 -> D2 -> D3 validation suite.")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty result directory")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument(
        "--max-source-samples",
        type=int,
        default=0,
        help="0 uses all 4,857 DS801 and 1,422 selected RASS samples; smoke values must be >=20.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_source_samples != 0 and args.max_source_samples < 20:
        parser.error("--max-source-samples must be 0 (full) or at least 20 for gold/anomaly coverage")
    try:
        report = run_real_suite(args.output_dir, args.fixture_dir, args.max_source_samples)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.output_dir / "real_data_report.json"),
                "blocking_failed": report.get("counts", {}).get("blocking", {}).get("failed"),
                "review_failed": report.get("counts", {}).get("review", {}).get("failed"),
                "atlas": str(args.output_dir / "d3" / "atlas.html"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
