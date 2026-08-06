#!/usr/bin/env python3
"""Run broad, data-driven and metamorphic checks against D2 alone."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lab_common import (
    CONTRACT_ROOT,
    D2_FIXTURE,
    D2_SCHEMA,
    D2_SCRIPT,
    CheckBook,
    atomic_write_json,
    load_d2_module,
    load_json,
    sha256_file,
)

SUITE_VERSION = "d2-isolated-suite-v1"
EXPECTED_OUTPUTS = {
    "geochemistry.csv",
    "samples.geojson",
    "anomalies.geojson",
    "qc_report.json",
    "confidence_report.json",
    "anomaly_report.json",
    "map_spec.json",
    "run_manifest.json",
}


def complete_row(**overrides: str) -> dict[str, str]:
    row = {
        "record_id": "record-1",
        "source_record_id": "source-row-1",
        "sample_id": "sample-1",
        "element_or_analyte": "As",
        "analyte_reported": "As",
        "value": "10",
        "unit": "mg/kg",
        "medium": "soil",
        "measurement_basis": "dry_total",
        "latitude": "35",
        "longitude": "103",
        "source_crs": "EPSG:4326",
        "coordinate_uncertainty_m": "25",
        "geologic_unit": "validation_granite",
        "analytical_method": "ICP-MS",
        "digestion_or_extraction": "four_acid",
        "laboratory": "Validation Lab",
        "license": "CC0-1.0",
        "source_tier": "government",
        "source_id": "validation-dataset-v1",
        "dataset_title": "D2 synthetic validation dataset",
        "dataset_version": "v1",
        "source_file": "synthetic-validation.csv",
        "source_row": "2",
        "file_sha256": "0" * 64,
        "source_locator": "local-test:synthetic-validation.csv#record-1",
    }
    row.update(overrides)
    return row


def close_enough(actual: Any, expected: float) -> bool:
    return isinstance(actual, (int, float)) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12)


def anomaly_records(d2: Any, values: Sequence[str], *, method: str = "ICP-MS", prefix: str = "a") -> list[dict[str, Any]]:
    return [
        d2.normalize_row(
            complete_row(
                record_id=f"{prefix}-{index}",
                source_record_id=f"{prefix}-source-{index}",
                sample_id=f"{prefix}-sample-{index}",
                value=value,
                analytical_method=method,
                source_row=str(index + 2),
            ),
            index + 2,
        )
        for index, value in enumerate(values)
    ]


def anomaly_ids(geojson: dict[str, Any]) -> set[str]:
    return {feature["properties"]["record_id"] for feature in geojson.get("features", [])}


def run_suite(stress_records: int) -> dict[str, Any]:
    d2 = load_d2_module()
    matrix = load_json(CONTRACT_ROOT / "isolated-matrix.json")
    checks = CheckBook()
    metrics: dict[str, Any] = {"stress_records": stress_records}

    checks.add(
        "interface_version_is_v2",
        d2.INTERFACE_VERSION == "d2-interface-v2",
        category="contract",
        expected="d2-interface-v2",
        actual=d2.INTERFACE_VERSION,
    )
    schema = load_json(D2_SCHEMA)
    checks.add(
        "schema_required_fields_match_csv_columns",
        set(schema.get("required", [])) == set(d2.SCHEMA_COLUMNS),
        category="contract",
        expected=len(d2.SCHEMA_COLUMNS),
        actual=len(schema.get("required", [])),
    )
    checks.add(
        "schema_rejects_uncontracted_properties",
        schema.get("additionalProperties") is False,
        category="contract",
        expected=False,
        actual=schema.get("additionalProperties"),
    )

    for case in matrix["solid_unit_cases"]:
        record = d2.normalize_row(
            complete_row(value=case["value"], unit=case["unit"], medium="soil"), 2
        )
        checks.add(
            f"solid_unit_{case['unit']}",
            close_enough(record["normalized_value"], case["expected"])
            and record["normalized_unit"] == "mg/kg",
            category="unit_normalization",
            expected={"value": case["expected"], "unit": "mg/kg"},
            actual={"value": record["normalized_value"], "unit": record["normalized_unit"]},
        )

    for case in matrix["water_unit_cases"]:
        record = d2.normalize_row(
            complete_row(
                value=case["value"],
                unit=case["unit"],
                medium="water",
                measurement_basis="dissolved",
            ),
            2,
        )
        checks.add(
            f"water_unit_{case['unit']}",
            close_enough(record["normalized_value"], case["expected"])
            and record["normalized_unit"] == "ug/L",
            category="unit_normalization",
            expected={"value": case["expected"], "unit": "ug/L"},
            actual={"value": record["normalized_value"], "unit": record["normalized_unit"]},
        )

    for index, case in enumerate(matrix["ambiguous_or_unsupported_cases"]):
        record = d2.normalize_row(
            complete_row(value="1", unit=case["unit"], medium=case["medium"]), index + 2
        )
        checks.add(
            f"fail_closed_unit_{index}_{case['medium']}_{case['unit']}",
            record["normalized_value"] is None and case["flag"] in record["qc_flags"],
            category="unit_normalization",
            expected={"normalized_value": None, "flag": case["flag"]},
            actual={"normalized_value": record["normalized_value"], "flags": record["qc_flags"]},
        )

    alias_cases = {"arsenic": "As", "AS": "As", "砷": "As", "lead": "Pb", "铅": "Pb"}
    for reported, expected in alias_cases.items():
        record = d2.normalize_row(complete_row(element_or_analyte=reported, analyte_reported=reported), 2)
        checks.add(
            f"analyte_alias_{reported}",
            record["element_or_analyte"] == expected and "UNRECOGNIZED_ANALYTE" not in record["qc_flags"],
            category="analyte",
            expected=expected,
            actual=record["element_or_analyte"],
        )

    for case in matrix["oxide_cases"]:
        record = d2.normalize_row(
            complete_row(
                element_or_analyte=case["element"],
                analyte_reported=case["formula"],
                species_or_oxide=case["formula"],
                value="1",
                unit="wt%",
                medium="rock",
            ),
            2,
        )
        checks.add(
            f"oxide_whitelist_{case['formula']}",
            isinstance(record["normalized_value"], (int, float))
            and 0 < record["normalized_value"] < 10000
            and "d2-atomic-weights-v1" in str(record["conversion_formula"]),
            category="oxide_conversion",
            expected="positive elemental value with versioned formula",
            actual={"value": record["normalized_value"], "formula": record["conversion_formula"]},
        )
    unsupported = d2.normalize_row(
        complete_row(element_or_analyte="Fe", species_or_oxide="Fe2O3T", value="1", unit="wt%"), 2
    )
    checks.add(
        "unsupported_total_iron_fails_closed",
        unsupported["normalized_value"] is None
        and "UNSUPPORTED_SPECIES_CONVERSION" in unsupported["qc_flags"],
        category="oxide_conversion",
        expected="UNSUPPORTED_SPECIES_CONVERSION",
        actual=unsupported["qc_flags"],
    )
    mismatch = d2.normalize_row(
        complete_row(element_or_analyte="Cu", species_or_oxide="NiO", value="1", unit="wt%"), 2
    )
    checks.add(
        "oxide_element_mismatch_fails_closed",
        mismatch["normalized_value"] is None and "OXIDE_ELEMENT_MISMATCH" in mismatch["qc_flags"],
        category="oxide_conversion",
        expected="OXIDE_ELEMENT_MISMATCH",
        actual=mismatch["qc_flags"],
    )

    qualifier_cases = [
        ("<0.1", "lt", 0.1),
        ("<=0.1", "le", 0.1),
        (">5", "gt", 5.0),
        (">=5", "ge", 5.0),
    ]
    for raw, qualifier, limit in qualifier_cases:
        record = d2.normalize_row(complete_row(value=raw), 2)
        checks.add(
            f"censor_qualifier_{qualifier}",
            record["censored"] is True
            and record["value_qualifier"] == qualifier
            and record["normalized_value"] is None
            and close_enough(record["normalized_censoring_limit"], limit),
            category="censoring",
            expected={"qualifier": qualifier, "limit": limit, "normalized_value": None},
            actual={
                "qualifier": record["value_qualifier"],
                "limit": record["normalized_censoring_limit"],
                "normalized_value": record["normalized_value"],
            },
        )
    for raw, qualifier in (("ND", "nd"), ("BDL", "bdl")):
        record = d2.normalize_row(
            complete_row(value=raw, detection_limit="0.01", detection_limit_unit="mg/kg"), 2
        )
        checks.add(
            f"nondetect_{qualifier}_preserves_limit",
            record["normalized_value"] is None
            and record["value_qualifier"] == qualifier
            and close_enough(record["normalized_censoring_limit"], 0.01),
            category="censoring",
            expected={"qualifier": qualifier, "limit": 0.01},
            actual={"qualifier": record["value_qualifier"], "limit": record["normalized_censoring_limit"]},
        )
    trace = d2.normalize_row(complete_row(value="trace"), 2)
    checks.add(
        "trace_is_unquantified_not_zero",
        trace["normalized_value"] is None
        and trace["normalized_censoring_limit"] is None
        and "UNQUANTIFIED_TRACE" in trace["qc_flags"],
        category="censoring",
        actual=trace,
    )
    missing = d2.normalize_row(complete_row(value="N/A"), 2)
    checks.add(
        "not_analyzed_is_distinct_from_nondetect",
        missing["missing_reason"] == "not_analyzed" and missing["censored"] is False,
        category="censoring",
        expected={"missing_reason": "not_analyzed", "censored": False},
        actual={"missing_reason": missing["missing_reason"], "censored": missing["censored"]},
    )

    valid_boundary = d2.normalize_row(complete_row(latitude="90", longitude="180"), 2)
    checks.add(
        "coordinate_boundary_is_valid",
        valid_boundary["latitude"] == 90 and valid_boundary["longitude"] == 180,
        category="coordinates",
        actual={"latitude": valid_boundary["latitude"], "longitude": valid_boundary["longitude"]},
    )
    swapped = d2.normalize_row(complete_row(latitude="120", longitude="30"), 2)
    checks.add(
        "coordinate_swap_is_flagged_not_applied",
        swapped["latitude"] is None
        and swapped["longitude"] is None
        and "POSSIBLE_COORDINATE_SWAP" in swapped["qc_flags"]
        and swapped["original_latitude_raw"] == "120",
        category="coordinates",
        actual=swapped["qc_flags"],
    )
    incomplete = d2.normalize_row(complete_row(latitude="35", longitude=""), 2)
    checks.add(
        "incomplete_coordinate_is_not_renderable",
        incomplete["latitude"] is None
        and incomplete["longitude"] is None
        and "INCOMPLETE_COORDINATE" in incomplete["qc_flags"],
        category="coordinates",
        actual=incomplete["qc_flags"],
    )
    zero_island = d2.normalize_row(complete_row(latitude="0", longitude="0"), 2)
    checks.add(
        "zero_island_is_visible_as_qc_warning",
        zero_island["latitude"] == 0
        and zero_island["longitude"] == 0
        and "ZERO_ISLAND_COORDINATE" in zero_island["qc_flags"],
        category="coordinates",
        actual=zero_island["qc_flags"],
    )
    outside = d2.normalize_row(complete_row(latitude="35", longitude="103"), 2, (100, 30, 102, 40))
    checks.add(
        "outside_requested_region_is_flagged",
        "OUTSIDE_REQUEST_REGION" in outside["qc_flags"],
        category="coordinates",
        actual=outside["qc_flags"],
    )
    inside_dateline = d2.normalize_row(complete_row(latitude="0", longitude="175"), 2, (170, -10, -170, 10))
    checks.add(
        "dateline_crossing_bbox_is_supported",
        "OUTSIDE_REQUEST_REGION" not in inside_dateline["qc_flags"],
        category="coordinates",
        actual=inside_dateline["qc_flags"],
    )
    projected = d2.normalize_row(complete_row(source_crs="EPSG:3857"), 2)
    checks.add(
        "untransformed_projected_crs_is_rejected",
        projected["latitude"] is None
        and projected["longitude"] is None
        and "UNSUPPORTED_SOURCE_CRS" in projected["qc_flags"],
        category="coordinates",
        actual=projected["qc_flags"],
    )

    method_cases = {"ICP-MS": "icp_ms", "XRF": "xrf", "AAS": "aas", "INAA": "inaa"}
    for method, family in method_cases.items():
        record = d2.normalize_row(complete_row(analytical_method=method), 2)
        checks.add(
            f"method_family_{family}",
            record["method_family"] == family,
            category="method",
            expected=family,
            actual=record["method_family"],
        )

    strong = d2.normalize_row(complete_row(source_tier="official_curated"), 2)
    weak = d2.normalize_row(
        complete_row(
            source_tier="unknown",
            source_id="",
            source_locator="",
            license="",
            analytical_method="",
            digestion_or_extraction="",
            latitude="",
            longitude="",
        ),
        3,
    )
    checks.add(
        "confidence_components_are_bounded",
        all(
            0 <= float(strong["operational_confidence"][name]) <= 1
            for name in ("source", "completeness", "method", "spatial", "qc", "overall")
        ),
        category="confidence",
        actual=strong["operational_confidence"],
    )
    checks.add(
        "confidence_degrades_with_missing_evidence",
        strong["operational_confidence"]["overall"] > weak["operational_confidence"]["overall"],
        category="confidence",
        expected="strong > weak",
        actual={
            "strong": strong["operational_confidence"]["overall"],
            "weak": weak["operational_confidence"]["overall"],
        },
    )
    error_record = d2.normalize_row(complete_row(unit="not-a-unit"), 4)
    checks.add(
        "error_flag_caps_confidence_at_059",
        error_record["operational_confidence"]["overall"] <= 0.59
        and error_record["operational_confidence"]["band"] == "low",
        category="confidence",
        expected="overall <= 0.59 and low",
        actual=error_record["operational_confidence"],
    )

    exact_duplicates = d2.process_rows(
        [complete_row(record_id="dup-a"), complete_row(record_id="dup-b")]
    )
    checks.add(
        "exact_duplicates_are_retained_and_flagged",
        len(exact_duplicates) == 2
        and all("DUPLICATE_CANDIDATE" in row["qc_flags"] for row in exact_duplicates),
        category="duplicates",
        actual=[row["qc_flags"] for row in exact_duplicates],
    )
    cross_row_duplicates = d2.process_rows(
        [
            complete_row(record_id="cross-a", source_record_id="source-a"),
            complete_row(record_id="cross-b", source_record_id="source-b"),
        ]
    )
    checks.add(
        "same_measurement_with_distinct_source_row_ids_is_reviewed_for_duplication",
        all("DUPLICATE_CANDIDATE" in row["qc_flags"] for row in cross_row_duplicates),
        category="duplicates",
        severity="review",
        expected="both rows flagged or an explicit documented alternative policy",
        actual=[row["qc_flags"] for row in cross_row_duplicates],
        note="D2 duplicate_key currently includes source_record_id; D1 normally supplies a unique ID per source row.",
    )
    different_methods = d2.process_rows(
        [
            complete_row(record_id="method-a", analytical_method="ICP-MS"),
            complete_row(record_id="method-b", analytical_method="XRF"),
        ]
    )
    checks.add(
        "different_methods_are_not_collapsed_as_exact_duplicates",
        all("DUPLICATE_CANDIDATE" not in row["qc_flags"] for row in different_methods),
        category="duplicates",
        actual=[row["qc_flags"] for row in different_methods],
    )

    high_values = ["8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5", "12", "500"]
    high_records = anomaly_records(d2, high_values, prefix="high")
    high_geojson, high_report = d2.detect_anomalies(high_records, min_group_size=8)
    checks.add(
        "robust_screen_finds_high_candidate",
        anomaly_ids(high_geojson) == {"high-9"}
        and high_report["scientific_status"] == "screening_baseline_only",
        category="anomaly",
        expected=["high-9"],
        actual=sorted(anomaly_ids(high_geojson)),
    )
    low_values = ["0.01", "8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5", "12"]
    low_geojson, _ = d2.detect_anomalies(anomaly_records(d2, low_values, prefix="low"), min_group_size=8)
    low_directions = {feature["properties"]["direction"] for feature in low_geojson["features"]}
    checks.add(
        "robust_screen_finds_low_candidate",
        anomaly_ids(low_geojson) == {"low-0"} and low_directions == {"low"},
        category="anomaly",
        expected={"ids": ["low-0"], "directions": ["low"]},
        actual={"ids": sorted(anomaly_ids(low_geojson)), "directions": sorted(low_directions)},
    )

    nineteen = anomaly_records(d2, [str(8 + index / 10) for index in range(19)], prefix="n19")
    _, report_19 = d2.detect_anomalies(nineteen)
    twenty = anomaly_records(d2, [str(8 + index / 10) for index in range(20)], prefix="n20")
    _, report_20 = d2.detect_anomalies(twenty)
    checks.add(
        "production_group_size_boundary_is_19_fail_20_analyze",
        report_19["groups"][0]["status"] == "insufficient_group_size"
        and report_20["groups"][0]["status"] == "analyzed",
        category="anomaly",
        expected={"n19": "insufficient_group_size", "n20": "analyzed"},
        actual={"n19": report_19["groups"][0]["status"], "n20": report_20["groups"][0]["status"]},
    )

    exact_70 = anomaly_records(
        d2,
        ["8", "9", "10", "11", "12", "13", "14", "<1", "ND", "trace"],
        prefix="q70",
    )
    _, report_70 = d2.detect_anomalies(exact_70, min_group_size=3, min_quantified_fraction=0.70)
    below_70 = anomaly_records(
        d2,
        ["8", "9", "10", "11", "12", "13", "<1", "<1", "ND", "trace"],
        prefix="q69",
    )
    _, report_below = d2.detect_anomalies(below_70, min_group_size=3, min_quantified_fraction=0.70)
    checks.add(
        "quantified_fraction_boundary_is_inclusive",
        report_70["groups"][0]["status"] == "analyzed"
        and report_below["groups"][0]["status"] == "insufficient_quantified_fraction",
        category="anomaly",
        expected={"0.70": "analyzed", "0.60": "insufficient_quantified_fraction"},
        actual={
            "0.70": report_70["groups"][0]["status"],
            "0.60": report_below["groups"][0]["status"],
        },
    )
    flat = anomaly_records(d2, ["10"] * 8, prefix="flat")
    _, flat_report = d2.detect_anomalies(flat, min_group_size=8)
    checks.add(
        "zero_mad_fails_visible_without_epsilon",
        flat_report["groups"][0]["status"] == "zero_dispersion",
        category="anomaly",
        expected="zero_dispersion",
        actual=flat_report["groups"][0]["status"],
    )

    method_a = anomaly_records(d2, ["8", "9", "10", "11", "12", "500"], method="ICP-MS", prefix="ma")
    method_b = anomaly_records(d2, ["8", "9", "10", "11", "12", "13"], method="XRF", prefix="mb")
    _, method_report = d2.detect_anomalies(method_a + method_b, min_group_size=5)
    checks.add(
        "method_families_form_separate_background_groups",
        len(method_report["groups"]) == 2
        and {group["group"]["method_family"] for group in method_report["groups"]} == {"icp_ms", "xrf"},
        category="anomaly",
        expected=["icp_ms", "xrf"],
        actual=sorted(group["group"]["method_family"] for group in method_report["groups"]),
    )

    reversed_geojson, _ = d2.detect_anomalies(list(reversed(high_records)), min_group_size=8)
    scaled_values = [str(float(value) * 100) for value in high_values]
    scaled_geojson, _ = d2.detect_anomalies(anomaly_records(d2, scaled_values, prefix="high"), min_group_size=8)
    checks.add(
        "anomaly_identity_is_invariant_to_input_order",
        anomaly_ids(reversed_geojson) == anomaly_ids(high_geojson),
        category="metamorphic",
        expected=sorted(anomaly_ids(high_geojson)),
        actual=sorted(anomaly_ids(reversed_geojson)),
    )
    checks.add(
        "anomaly_identity_is_invariant_to_positive_scale",
        anomaly_ids(scaled_geojson) == anomaly_ids(high_geojson),
        category="metamorphic",
        expected=sorted(anomaly_ids(high_geojson)),
        actual=sorted(anomaly_ids(scaled_geojson)),
    )
    equivalent_ppm = d2.normalize_row(complete_row(value="10", unit="ppm"), 2)
    equivalent_wt = d2.normalize_row(complete_row(value="0.001", unit="wt%"), 3)
    checks.add(
        "equivalent_units_produce_equal_canonical_values",
        close_enough(equivalent_ppm["normalized_value"], equivalent_wt["normalized_value"]),
        category="metamorphic",
        expected=equivalent_ppm["normalized_value"],
        actual=equivalent_wt["normalized_value"],
    )

    help_result = subprocess.run(
        [sys.executable, str(D2_SCRIPT), "--help"], capture_output=True, text=True, check=False
    )
    checks.add(
        "cli_help_is_available",
        help_result.returncode == 0 and "--schema-map" in help_result.stdout and "--min-group-size" in help_result.stdout,
        category="cli",
        expected=0,
        actual=help_result.returncode,
    )
    with tempfile.TemporaryDirectory(prefix="d2-isolated-cli-") as temporary:
        temporary_path = Path(temporary)
        bad_csv = temporary_path / "missing-columns.csv"
        bad_csv.write_text("element,value\nAs,10\n", encoding="utf-8")
        bad_result = subprocess.run(
            [
                sys.executable,
                str(D2_SCRIPT),
                "--input",
                str(bad_csv),
                "--output-dir",
                str(temporary_path / "bad-output"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        checks.add(
            "invalid_cli_input_exits_2_without_traceback",
            bad_result.returncode == 2 and "traceback" not in bad_result.stderr.casefold(),
            category="cli",
            expected=2,
            actual={"returncode": bad_result.returncode, "stderr": bad_result.stderr[-300:]},
        )
        parameter_result = subprocess.run(
            [
                sys.executable,
                str(D2_SCRIPT),
                "--input",
                str(D2_FIXTURE),
                "--output-dir",
                str(temporary_path / "bad-parameter"),
                "--min-group-size",
                "2",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        checks.add(
            "invalid_scientific_parameter_exits_2",
            parameter_result.returncode == 2 and "at least 3" in parameter_result.stderr,
            category="cli",
            expected=2,
            actual=parameter_result.returncode,
        )

        first_dir = temporary_path / "first"
        second_dir = temporary_path / "second"
        first_outputs = d2.run_pipeline(D2_FIXTURE, first_dir, min_group_size=8)
        second_outputs = d2.run_pipeline(D2_FIXTURE, second_dir, min_group_size=8)
        first_bytes = {path.name: path.read_bytes() for path in first_outputs.values()}
        second_bytes = {path.name: path.read_bytes() for path in second_outputs.values()}
        checks.add(
            "all_eight_outputs_are_emitted",
            set(first_bytes) == EXPECTED_OUTPUTS,
            category="determinism",
            expected=sorted(EXPECTED_OUTPUTS),
            actual=sorted(first_bytes),
        )
        checks.add(
            "same_input_produces_byte_identical_outputs",
            first_bytes == second_bytes,
            category="determinism",
            expected="all output bytes equal",
            actual=[name for name in first_bytes if first_bytes[name] != second_bytes.get(name)],
        )
        manifest = load_json(first_dir / "run_manifest.json")
        bad_hashes = [
            entry["path"]
            for entry in manifest.get("outputs", [])
            if sha256_file(first_dir / entry["path"]) != entry["sha256"]
        ]
        checks.add(
            "manifest_hashes_match_business_outputs",
            not bad_hashes,
            category="evidence_chain",
            actual=bad_hashes,
        )
        with (first_dir / "geochemistry.csv").open(encoding="utf-8", newline="") as handle:
            serialized_rows = list(csv.DictReader(handle))
        nested_parse_errors = []
        for index, row in enumerate(serialized_rows):
            try:
                json.loads(row["qc_flags"])
                json.loads(row["operational_confidence"])
            except json.JSONDecodeError:
                nested_parse_errors.append(index + 2)
        checks.add(
            "serialized_nested_fields_are_valid_json",
            not nested_parse_errors,
            category="contract",
            actual=nested_parse_errors,
        )
        nonfinite_tokens = [
            name
            for name, content in first_bytes.items()
            if b"NaN" in content or b"Infinity" in content or b"-Infinity" in content
        ]
        checks.add(
            "outputs_contain_no_nonfinite_json_tokens",
            not nonfinite_tokens,
            category="contract",
            actual=nonfinite_tokens,
        )

    tracemalloc.start()
    stress_start = time.perf_counter()
    stress_rows = [
        complete_row(
            record_id=f"stress-{index}",
            source_record_id=f"stress-source-{index}",
            sample_id=f"stress-sample-{index}",
            source_row=str(index + 2),
            value=str(1 + (index % 997) / 10),
            latitude=str(-80 + (index % 160)),
            longitude=str(-170 + (index % 340)),
        )
        for index in range(stress_records)
    ]
    stress_normalized = d2.process_rows(stress_rows)
    _, stress_anomaly_report = d2.detect_anomalies(stress_normalized)
    stress_seconds = time.perf_counter() - stress_start
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    metrics.update(
        {
            "stress_elapsed_seconds": round(stress_seconds, 6),
            "stress_peak_bytes": peak_bytes,
            "stress_output_records": len(stress_normalized),
            "stress_anomaly_groups": len(stress_anomaly_report.get("groups", [])),
        }
    )
    checks.add(
        "stress_test_preserves_all_records",
        len(stress_normalized) == stress_records,
        category="resources",
        expected=stress_records,
        actual=len(stress_normalized),
    )
    checks.add(
        "stress_runtime_below_team_warning_line",
        stress_seconds < 30,
        category="resources",
        severity="review",
        expected="<30 seconds",
        actual=round(stress_seconds, 6),
    )
    checks.add(
        "stress_peak_memory_below_team_warning_line",
        peak_bytes < 512 * 1024 * 1024,
        category="resources",
        severity="review",
        expected="<512 MiB",
        actual=peak_bytes,
    )

    summary = checks.summary()
    return {
        "suite_version": SUITE_VERSION,
        "matrix_version": matrix["version"],
        "target": {
            "interface_version": d2.INTERFACE_VERSION,
            "pipeline_version": d2.PIPELINE_VERSION,
            "script_sha256": sha256_file(D2_SCRIPT),
        },
        "status": summary["status"],
        "metrics": metrics,
        "acceptance": {
            "blocking_requirement": "100%",
            "review_failures": "reported as findings and require team disposition",
        },
        "limitations": [
            "Synthetic checks do not validate global coverage or third-party data licenses.",
            "Resource measurements are local warning indicators, not official sandbox benchmarks.",
            "Anomaly checks validate the declared robust baseline, not causal interpretation.",
        ],
        **summary,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the independent D2 scientific and engineering validation suite.")
    parser.add_argument("--report", type=Path, help="Optional path for the JSON report")
    parser.add_argument(
        "--stress-records",
        type=int,
        default=10_000,
        help="Number of records for the local resource smoke test (default: 10000)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.stress_records < 100:
        parser.error("--stress-records must be at least 100")
    try:
        report = run_suite(args.stress_records)
        if args.report is not None:
            atomic_write_json(args.report, report)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    result = {
        "status": report["status"],
        "report": str(args.report) if args.report is not None else None,
        "blocking_failed": report["counts"]["blocking"]["failed"],
        "review_failed": report["counts"]["review"]["failed"],
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
