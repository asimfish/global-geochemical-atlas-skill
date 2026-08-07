#!/usr/bin/env python3
"""Run the seven-continent frozen benchmark through D1 -> candidate D2 -> D3."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from build_expanded_fixtures import (
    DEFAULT_FIXTURE_DIR as DEFAULT_EXPANDED_FIXTURE_DIR,
)
from build_expanded_fixtures import (
    SOURCE_CONTRACT as EXPANDED_SOURCE_CONTRACT,
)
from build_global_fixtures import DEFAULT_FIXTURE_DIR, SOURCE_CONTRACT
from lab_common import (
    D2_SCRIPT,
    LAB_ROOT,
    CheckBook,
    atomic_write_json,
    load_json,
    prepare_empty_output_dir,
    sha256_file,
)
from run_real_data_suite import (
    REQUIRED_D2_FILES,
    add_stage_check,
    parse_d2_database,
    run_json_command,
    stage_succeeded,
)

SUITE_VERSION = "d2-global-data-suite-v2"
FIXTURE_SCRIPT = LAB_ROOT / "scripts" / "build_global_fixtures.py"
EXPANDED_FIXTURE_SCRIPT = LAB_ROOT / "scripts" / "build_expanded_fixtures.py"
D1_SCRIPT = LAB_ROOT / "scripts" / "global_d1_adapter.py"
EXPANDED_D1_SCRIPT = LAB_ROOT / "scripts" / "expanded_global_d1_adapter.py"
D3_SCRIPT = LAB_ROOT / "scripts" / "d3_stub.py"
SHA256_RE = re.compile(r"[0-9a-f]{64}")
EXPECTED_SOURCES = {
    "gemas_europe_soil",
    "gemstat_global_freshwater_v3",
    "georoc_antarctica_intraplate",
    "georoc_archaean_cratons",
    "ngsa_australia_hg",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_early_report(
    output_dir: Path,
    checks: CheckBook,
    stages: Mapping[str, Any],
    failed_stage: str,
    candidate_label: str,
) -> dict[str, Any]:
    summary = checks.summary()
    report = {
        "suite_version": SUITE_VERSION,
        "status": "fail",
        "candidate_label": candidate_label,
        "failed_stage": failed_stage,
        "stages": stages,
        **summary,
    }
    atomic_write_json(output_dir / "global_data_report.json", report)
    return report


def close_enough(value: Any, expected: float) -> bool:
    return isinstance(value, (float, int)) and math.isclose(
        float(value), expected, rel_tol=1e-10, abs_tol=1e-12
    )


def add_spot_check(
    checks: CheckBook,
    records: Mapping[str, Mapping[str, Any]],
    record_id: str,
    expected: Mapping[str, Any],
) -> None:
    record = records.get(record_id)
    passed = record is not None
    actual: dict[str, Any] = {}
    if record is not None:
        for field, value in expected.items():
            actual[field] = record.get(field)
            if isinstance(value, float):
                passed = passed and close_enough(record.get(field), value)
            elif field == "required_flags":
                passed = passed and all(
                    flag in record.get("qc_flags", []) for flag in value
                )
            else:
                passed = passed and record.get(field) == value
    checks.add(
        f"real_spot_check_{record_id}",
        passed,
        category="scientific_spot_check",
        expected=expected,
        actual=actual if record is not None else None,
    )


def deliverable_hash_failures(d3_dir: Path, manifest: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    for name, item in manifest.get("deliverables", {}).items():
        path = (d3_dir / str(item.get("path", ""))).resolve()
        if not path.is_file() or sha256_file(path) != item.get("sha256"):
            failures.append(str(name))
    return failures


def run_global_suite(
    output_dir: Path,
    fixture_dir: Path,
    candidate_d2_script: Path,
    candidate_label: str,
    *,
    expanded: bool = False,
    expanded_fixture_dir: Path = DEFAULT_EXPANDED_FIXTURE_DIR,
) -> dict[str, Any]:
    prepare_empty_output_dir(output_dir)
    checks = CheckBook()
    stages: dict[str, Any] = {}
    profile = "expanded" if expanded else "core"
    core_contract = load_json(SOURCE_CONTRACT)
    if expanded:
        extra_contract = load_json(EXPANDED_SOURCE_CONTRACT)
        source_contract = {
            "datasets": [*core_contract["datasets"], *extra_contract["datasets"]],
            "resources": [*core_contract["resources"], *extra_contract["resources"]],
            "coverage_acceptance": extra_contract["coverage_acceptance"],
        }
    else:
        source_contract = core_contract

    fixture_result = run_json_command(
        [
            sys.executable,
            str(FIXTURE_SCRIPT),
            "--offline",
            "--fixture-dir",
            str(fixture_dir),
        ]
    )
    stages["fixture_verification"] = fixture_result
    add_stage_check(
        checks, "global_fixture_verification_succeeds_offline", fixture_result
    )
    if not stage_succeeded(fixture_result):
        return write_early_report(
            output_dir, checks, stages, "fixture_verification", candidate_label
        )

    fixture_payload = dict(fixture_result["payload"])
    if expanded:
        expanded_fixture_result = run_json_command(
            [
                sys.executable,
                str(EXPANDED_FIXTURE_SCRIPT),
                "--offline",
                "--fixture-dir",
                str(expanded_fixture_dir),
            ]
        )
        stages["expanded_fixture_verification"] = expanded_fixture_result
        add_stage_check(
            checks,
            "expanded_fixture_verification_succeeds_offline",
            expanded_fixture_result,
        )
        if not stage_succeeded(expanded_fixture_result):
            return write_early_report(
                output_dir,
                checks,
                stages,
                "expanded_fixture_verification",
                candidate_label,
            )
        expanded_payload = expanded_fixture_result["payload"]
        fixture_payload["resource_count"] = int(
            fixture_payload["resource_count"]
        ) + int(expanded_payload["resource_count"])
        fixture_payload["total_bytes"] = int(fixture_payload["total_bytes"]) + int(
            expanded_payload["total_bytes"]
        )
        fixture_payload["expanded_resource_count"] = int(
            expanded_payload["resource_count"]
        )
        fixture_payload["expanded_total_bytes"] = int(expanded_payload["total_bytes"])
    fixture_bytes = int(fixture_payload["total_bytes"])
    checks.add(
        "global_fixture_is_small_enough_for_the_repository",
        (5_000_000 <= fixture_bytes <= 15_000_000)
        if expanded
        else (1_000_000 <= fixture_bytes <= 5_000_000),
        category="resource_budget",
        expected="5-15 MB" if expanded else "1-5 MB",
        actual=fixture_bytes,
    )
    checks.add(
        "declared_datasets_cover_all_four_media",
        len(source_contract["datasets"])
        >= source_contract["coverage_acceptance"]["minimum_source_datasets"]
        and {dataset["medium"] for dataset in source_contract["datasets"]}
        == {"rock", "sediment", "soil", "water"},
        category="source_coverage",
        expected={
            "minimum_datasets": source_contract["coverage_acceptance"][
                "minimum_source_datasets"
            ],
            "media": ["rock", "sediment", "soil", "water"],
        },
        actual={
            "datasets": len(source_contract["datasets"]),
            "media": sorted(
                {dataset["medium"] for dataset in source_contract["datasets"]}
            ),
        },
    )
    checks.add(
        "every_dataset_declares_identifier_license_and_multiple_limits",
        all(
            dataset.get("persistent_identifier")
            and dataset.get("license")
            and dataset.get("citation")
            and len(dataset.get("scientific_limits", [])) >= 3
            for dataset in source_contract["datasets"]
        ),
        category="source_evidence",
    )

    d1_dir = output_dir / "d1"
    if expanded:
        d1_command = [
            sys.executable,
            str(EXPANDED_D1_SCRIPT),
            "--core-fixture-dir",
            str(fixture_dir),
            "--expanded-fixture-dir",
            str(expanded_fixture_dir),
            "--output-dir",
            str(d1_dir),
        ]
    else:
        d1_command = [
            sys.executable,
            str(D1_SCRIPT),
            "--fixture-dir",
            str(fixture_dir),
            "--output-dir",
            str(d1_dir),
        ]
    d1_result = run_json_command(d1_command)
    stages["d1_global_adapters"] = d1_result
    add_stage_check(checks, "global_d1_adapters_succeed", d1_result)
    if not stage_succeeded(d1_result):
        return write_early_report(
            output_dir, checks, stages, "d1_global_adapters", candidate_label
        )

    d1_manifest_path = d1_dir / "d1_global_manifest.json"
    d1_export_path = d1_dir / "d1_global_export.csv"
    d1_manifest = load_json(d1_manifest_path)
    d1_rows = read_csv(d1_export_path)
    source_counts = Counter(row["source_id"] for row in d1_rows)
    medium_counts = Counter(row["medium"] for row in d1_rows)
    element_counts = Counter(row["element_or_analyte"] for row in d1_rows)
    continent_counts = Counter(row["benchmark_continent"] for row in d1_rows)
    required_continents = set(
        source_contract["coverage_acceptance"]["required_continents"]
    )
    checks.add(
        "d1_export_hash_and_record_count_match_manifest",
        d1_manifest["record_count"] == len(d1_rows)
        and d1_manifest["output"]["sha256"] == sha256_file(d1_export_path),
        category="evidence_chain",
        expected={"record_count": len(d1_rows), "sha256": sha256_file(d1_export_path)},
        actual={
            "record_count": d1_manifest["record_count"],
            "sha256": d1_manifest["output"]["sha256"],
        },
    )
    checks.add(
        "global_d1_has_all_seven_continents",
        set(continent_counts) == required_continents,
        category="geographic_coverage",
        expected=sorted(required_continents),
        actual=sorted(continent_counts),
    )
    checks.add(
        "global_d1_has_rock_soil_sediment_and_water",
        set(medium_counts) == {"rock", "soil", "sediment", "water"},
        category="source_coverage",
        expected=["rock", "sediment", "soil", "water"],
        actual=sorted(medium_counts),
    )
    expected_sources = (
        {str(dataset["id"]) for dataset in source_contract["datasets"]}
        if expanded
        else EXPECTED_SOURCES
    )
    checks.add(
        "global_d1_has_all_declared_source_datasets",
        set(source_counts) == expected_sources,
        category="source_coverage",
        expected=sorted(expected_sources),
        actual=sorted(source_counts),
    )
    checks.add(
        "global_water_slice_has_at_least_35_explicit_countries",
        d1_manifest.get("gemstat_country_count", 0)
        >= core_contract["coverage_acceptance"]["minimum_explicit_country_labels"],
        category="geographic_coverage",
        expected=f">={core_contract['coverage_acceptance']['minimum_explicit_country_labels']}",
        actual=d1_manifest.get("gemstat_country_count"),
    )
    country_counts = Counter(
        row["benchmark_country"] for row in d1_rows if row["benchmark_country"]
    )
    if expanded:
        required_focus_countries = set(
            source_contract["coverage_acceptance"].get("required_focus_countries", [])
        )
        checks.add(
            "expanded_d1_includes_china_japan_africa_and_small_country_focus_set",
            required_focus_countries <= set(country_counts),
            category="geographic_coverage",
            expected=sorted(required_focus_countries),
            actual=sorted(required_focus_countries & set(country_counts)),
        )
        checks.add(
            "expanded_d1_has_at_least_55_explicit_country_labels",
            len(country_counts)
            >= source_contract["coverage_acceptance"][
                "minimum_explicit_country_labels"
            ],
            category="geographic_coverage",
            expected=f">={source_contract['coverage_acceptance']['minimum_explicit_country_labels']}",
            actual=len(country_counts),
        )
    country_total = sum(country_counts.values())
    largest_country, largest_country_records = country_counts.most_common(1)[0]
    largest_country_share = largest_country_records / country_total
    checks.add(
        "no_single_explicit_country_dominates_the_geolocated_country_slice",
        largest_country_share
        <= source_contract["coverage_acceptance"]["maximum_single_country_share"],
        category="geographic_coverage",
        expected=f"<={source_contract['coverage_acceptance']['maximum_single_country_share']}",
        actual={
            "country_label": largest_country,
            "share": round(largest_country_share, 6),
        },
    )
    bad_d1_evidence = [
        row["record_id"]
        for row in d1_rows
        if not row.get("source_locator", "").startswith("https://")
        or not row.get("source_row")
        or not row.get("license")
        or not SHA256_RE.fullmatch(row.get("file_sha256", ""))
    ]
    checks.add(
        "every_global_d1_measurement_has_row_level_source_evidence",
        not bad_d1_evidence,
        category="evidence_chain",
        actual=bad_d1_evidence[:20],
    )
    checks.add(
        "global_d1_exercises_at_least_seven_elements",
        set(element_counts) == {"As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"},
        category="source_coverage",
        expected=["As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"],
        actual=sorted(element_counts),
    )

    if not candidate_d2_script.is_file():
        checks.add(
            "candidate_d2_script_exists",
            False,
            category="stage_execution",
            expected=str(candidate_d2_script),
            actual="missing",
        )
        return write_early_report(
            output_dir, checks, stages, "candidate_d2_missing", candidate_label
        )

    d2_dir = output_dir / "d2"
    d2_result = run_json_command(
        [
            sys.executable,
            str(candidate_d2_script),
            "--input",
            str(d1_export_path),
            "--output-dir",
            str(d2_dir),
        ]
    )
    stages["candidate_d2"] = d2_result
    add_stage_check(checks, "candidate_d2_cli_succeeds", d2_result)
    if not stage_succeeded(d2_result):
        return write_early_report(
            output_dir, checks, stages, "candidate_d2", candidate_label
        )

    present_d2_files = {path.name for path in d2_dir.iterdir() if path.is_file()}
    checks.add(
        "candidate_emits_all_nine_d2_interface_files",
        REQUIRED_D2_FILES <= present_d2_files,
        category="d2_interface",
        expected=sorted(REQUIRED_D2_FILES),
        actual=sorted(present_d2_files),
    )
    d2_manifest = load_json(d2_dir / "run_manifest.json")
    bad_manifest_hashes = [
        entry.get("path")
        for entry in d2_manifest.get("outputs", [])
        if not (d2_dir / str(entry.get("path", ""))).is_file()
        or sha256_file(d2_dir / str(entry.get("path", ""))) != entry.get("sha256")
    ]
    checks.add(
        "candidate_manifest_closes_input_and_output_hash_chain",
        d2_manifest.get("input", {}).get("sha256") == sha256_file(d1_export_path)
        and not bad_manifest_hashes,
        category="evidence_chain",
        actual={
            "input_sha256": d2_manifest.get("input", {}).get("sha256"),
            "bad_output_hashes": bad_manifest_hashes,
        },
    )

    _, d2_rows = parse_d2_database(d2_dir / "geochemistry.csv")
    d2_by_id = {str(row["record_id"]): row for row in d2_rows}
    d1_by_id = {row["record_id"]: row for row in d1_rows}
    checks.add(
        "candidate_does_not_silently_drop_or_collapse_records",
        len(d2_rows) == len(d1_rows) and len(d2_by_id) == len(d1_rows),
        category="record_integrity",
        expected=len(d1_rows),
        actual={"rows": len(d2_rows), "unique_record_ids": len(d2_by_id)},
    )
    bad_d2_evidence = [
        row["record_id"]
        for row in d2_rows
        if not str(row.get("source_locator") or "").startswith("https://")
        or not row.get("license")
        or not SHA256_RE.fullmatch(str(row.get("file_sha256") or ""))
    ]
    checks.add(
        "candidate_database_preserves_row_level_source_evidence",
        not bad_d2_evidence,
        category="evidence_chain",
        actual=bad_d2_evidence[:20],
    )
    censored_as_values = [
        row["record_id"]
        for row in d2_rows
        if row["censored"] and row["normalized_value"] is not None
    ]
    checks.add(
        "censored_global_water_results_are_not_imputed",
        not censored_as_values and any(row["censored"] for row in d2_rows),
        category="scientific_semantics",
        actual={
            "censored_records": sum(row["censored"] for row in d2_rows),
            "imputed_records": censored_as_values[:20],
        },
    )
    invalid_coordinate_rows = [
        row
        for row in d2_rows
        if "INVALID_COORDINATE" in row["qc_flags"]
        or "INCOMPLETE_COORDINATE" in row["qc_flags"]
    ]
    checks.add(
        "invalid_source_coordinates_remain_in_database_but_are_not_mapped",
        bool(invalid_coordinate_rows)
        and all(
            row["latitude"] is None and row["longitude"] is None
            for row in invalid_coordinate_rows
        ),
        category="scientific_semantics",
        expected=">=1 retained, unmapped invalid coordinate",
        actual=len(invalid_coordinate_rows),
    )
    mappable_continents = {
        d1_by_id[str(row["record_id"])]["benchmark_continent"]
        for row in d2_rows
        if row["latitude"] is not None
        and row["longitude"] is not None
        and str(row["record_id"]) in d1_by_id
    }
    checks.add(
        "candidate_retains_mappable_points_on_all_seven_continents",
        mappable_continents == required_continents,
        category="geographic_coverage",
        expected=sorted(required_continents),
        actual=sorted(mappable_continents),
    )

    add_spot_check(
        checks,
        d2_by_id,
        "gemas-3001-As",
        {
            "normalized_value": 1.55405313,
            "normalized_unit": "mg/kg",
            "source_id": "gemas_europe_soil",
        },
    )
    add_spot_check(
        checks,
        d2_by_id,
        "ngsa-2007190001001 Fine-Hg",
        {
            "normalized_value": 0.02196,
            "normalized_unit": "mg/kg",
            "source_crs": "GDA94 geographic (EPSG:4283)",
        },
    )
    add_spot_check(
        checks,
        d2_by_id,
        "gemstat-ARG00014-As-2",
        {
            "normalized_value": 3.0,
            "normalized_unit": "ug/L",
            "source_id": "gemstat_global_freshwater_v3",
        },
    )
    add_spot_check(
        checks,
        d2_by_id,
        "gemstat-AUT00404-As-9334",
        {
            "censored": True,
            "normalized_value": None,
            "normalized_censoring_limit": 0.35,
            "required_flags": ["CENSORED_VALUE"],
        },
    )
    add_spot_check(
        checks,
        d2_by_id,
        "georoc-georoc_antarctica_intraplate-1265343:Cu",
        {
            "normalized_value": 27.8,
            "normalized_unit": "mg/kg",
            "latitude": -72.1,
            "longitude": -0.3,
            "required_flags": ["MISSING_ANALYTICAL_METHOD"],
        },
    )
    if expanded:
        add_spot_check(
            checks,
            d2_by_id,
            "tpdc-cn-AL1-1-O-row2-Cr",
            {
                "normalized_value": 18.9559163,
                "normalized_unit": "mg/kg",
                "source_id": "tpdc_china_mountain_soil",
            },
        )
        add_spot_check(
            checks,
            d2_by_id,
            "afsis-icr005934-As",
            {
                "normalized_value": 0.262535152,
                "normalized_unit": "mg/kg",
                "source_id": "afsis_phase1_wet_chemistry",
            },
        )
        add_spot_check(
            checks,
            d2_by_id,
            "foregs_topsoil-N28E11T1-As-row128",
            {
                "normalized_value": 6.0,
                "normalized_unit": "mg/kg",
                "source_id": "foregs_topsoil",
            },
        )
        add_spot_check(
            checks,
            d2_by_id,
            "gsj-japan-1-occ1-Hg",
            {
                "normalized_value": 0.08,
                "normalized_unit": "mg/kg",
                "source_crs": "JGD2000 geographic (EPSG:4612)",
            },
        )
        add_spot_check(
            checks,
            d2_by_id,
            "pangaea-na-SC-5-As",
            {
                "normalized_value": 14.84,
                "normalized_unit": "mg/kg",
                "source_id": "pangaea_north_africa_soils",
            },
        )

    qc_report = load_json(d2_dir / "qc_report.json")
    confidence_report = load_json(d2_dir / "confidence_report.json")
    anomaly_report = load_json(d2_dir / "anomaly_report.json")
    anomalies = load_json(d2_dir / "anomalies.geojson")
    samples = load_json(d2_dir / "samples.geojson")
    analyzed_groups = [
        group
        for group in anomaly_report.get("groups", [])
        if group.get("status") == "analyzed"
    ]
    checks.add(
        "global_data_exercises_multiple_anomaly_background_groups",
        len(analyzed_groups) >= 4,
        category="anomaly",
        expected=">=4",
        actual=len(analyzed_groups),
    )
    checks.add(
        "anomaly_groups_keep_basis_geology_method_and_extraction_separate",
        {
            "measurement_basis",
            "geologic_unit",
            "method_family",
            "digestion_or_extraction",
        }
        <= set(anomaly_report.get("group_by", []))
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
        or "no causal claim"
        not in feature.get("properties", {}).get("interpretation_limit", "")
    ]
    checks.add(
        "candidate_anomalies_are_traceable_and_explicitly_noncausal",
        len(anomaly_features) == anomaly_report.get("candidate_count")
        and not bad_anomalies,
        category="scientific_boundary",
        actual={"candidate_count": len(anomaly_features), "bad": bad_anomalies[:20]},
    )
    coordinates = [
        feature.get("geometry", {}).get("coordinates", [])
        for feature in samples.get("features", [])
    ]
    valid_coordinates = [item for item in coordinates if len(item) == 2]
    longitude_span = max(item[0] for item in valid_coordinates) - min(
        item[0] for item in valid_coordinates
    )
    latitude_span = max(item[1] for item in valid_coordinates) - min(
        item[1] for item in valid_coordinates
    )
    checks.add(
        "sample_map_has_world_scale_longitude_and_latitude_extent",
        longitude_span >= 250 and latitude_span >= 130,
        category="map_semantics",
        expected={"longitude_span": ">=250", "latitude_span": ">=130"},
        actual={
            "longitude_span": round(longitude_span, 6),
            "latitude_span": round(latitude_span, 6),
        },
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
            "--coverage-context",
            str(d1_manifest_path),
        ]
    )
    stages["d3_global_products"] = d3_result
    add_stage_check(checks, "global_d3_consumer_succeeds", d3_result)
    if not stage_succeeded(d3_result):
        return write_early_report(
            output_dir, checks, stages, "d3_global_products", candidate_label
        )

    d3_report = load_json(d3_dir / "d3_consumer_report.json")
    showcase_manifest = load_json(d3_dir / "showcase_manifest.json")
    source_confidence = load_json(d3_dir / "source_confidence.json")
    anomaly_regions = load_json(d3_dir / "anomaly_regions.geojson")
    anomaly_region_report = load_json(d3_dir / "anomaly_region_report.json")
    expected_deliverables = {
        "interactive_element_map",
        "standardized_geochemical_database",
        "source_and_confidence_explanation",
        "anomaly_region_results",
    }
    checks.add(
        "d3_has_no_blocking_failures_and_builds_offline_atlas",
        d3_report.get("counts", {}).get("blocking", {}).get("failed") == 0
        and d3_report.get("atlas", {}).get("offline") is True,
        category="d3_interface",
        actual=d3_report.get("counts", {}).get("blocking", {}),
    )
    hash_failures = deliverable_hash_failures(d3_dir, showcase_manifest)
    checks.add(
        "global_showcase_emits_four_hashed_competition_deliverables",
        set(showcase_manifest.get("deliverables", {})) == expected_deliverables
        and not hash_failures,
        category="product_acceptance",
        expected=sorted(expected_deliverables),
        actual={
            "deliverables": sorted(showcase_manifest.get("deliverables", {})),
            "hash_failures": hash_failures,
        },
    )
    geographic_coverage = source_confidence.get("geographic_coverage", {})
    checks.add(
        "source_confidence_embeds_seven_continent_matrix_and_blind_spots",
        set(geographic_coverage.get("coverage_matrix", {})) == required_continents
        and len(geographic_coverage.get("declared_blind_spots", [])) >= 3
        and source_confidence.get("global_confidence", {}).get("not_a_probability")
        is True,
        category="product_acceptance",
        actual={
            "continents": sorted(geographic_coverage.get("coverage_matrix", {})),
            "blind_spots": geographic_coverage.get("declared_blind_spots", []),
        },
    )
    atlas_text = (d3_dir / "atlas.html").read_text(encoding="utf-8")
    checks.add(
        "atlas_is_self_contained_and_exposes_global_coverage_panel",
        "<script src=" not in atlas_text.casefold()
        and "全球覆盖矩阵" in atlas_text
        and "coverage_matrix" in atlas_text
        and "Natural Earth 1:110m" in atlas_text
        and "ai4s-natural-earth-land-v1" in atlas_text
        and "d3-evaluation-showcase-v3" in atlas_text
        and "const firstElement" not in atlas_text
        and "ALL DATA" in atlas_text
        and "全部元素按样品去重显示" in atlas_text
        and "介质分类总览 · 不跨元素或介质比较浓度" in atlas_text,
        category="product_acceptance",
    )
    region_features = anomaly_regions.get("features", [])
    region_record_ids = {
        record_id
        for feature in region_features
        for record_id in feature.get("properties", {}).get("record_ids", [])
    }
    checks.add(
        "anomaly_region_output_reconciles_every_candidate_point",
        anomaly_region_report.get("candidate_point_count") == len(anomaly_features)
        and anomaly_region_report.get("mappable_candidate_point_count")
        == len(region_record_ids)
        and anomaly_region_report.get("unmappable_candidate_point_count")
        + len(region_record_ids)
        == len(anomaly_features)
        and all(
            "not a geological boundary"
            in feature.get("properties", {}).get("interpretation_limit", "")
            for feature in region_features
        ),
        category="product_acceptance",
        actual={
            "candidate_points": len(anomaly_features),
            "mapped_to_regions": len(region_record_ids),
            "unmappable": anomaly_region_report.get("unmappable_candidate_point_count"),
        },
    )

    # Review findings are expected source-coverage gaps. They must stay visible instead of being scored as D2 defects.
    coverage_matrix = d1_manifest["coverage_matrix"]
    nonempty_cells = sum(
        count > 0
        for media_counts in coverage_matrix.values()
        for count in media_counts.values()
    )
    checks.add(
        "all_seven_continents_have_all_four_media",
        nonempty_cells == 28,
        category="coverage_gap",
        severity="review",
        expected="28/28 nonempty continent-medium cells",
        actual=f"{nonempty_cells}/28",
        note="The benchmark is global in union coverage, not a claim that every medium exists on every continent.",
    )
    method_fraction = sum(bool(row.get("analytical_method")) for row in d2_rows) / len(
        d2_rows
    )
    checks.add(
        "all_measurements_publish_an_explicit_analytical_method",
        method_fraction == 1.0,
        category="source_completeness",
        severity="review",
        expected=1.0,
        actual=round(method_fraction, 6),
        note="GEOROC precompiled rows and most GEMStat historical rows legitimately omit method detail; confidence must expose it.",
    )
    uncertainty_fraction = sum(
        row.get("coordinate_uncertainty_m") is not None for row in d2_rows
    ) / len(d2_rows)
    checks.add(
        "all_measurements_publish_coordinate_uncertainty",
        uncertainty_fraction == 1.0,
        category="source_completeness",
        severity="review",
        expected=1.0,
        actual=round(uncertainty_fraction, 6),
        note="Missing uncertainty remains a visible QC flag and lowers operational confidence.",
    )
    checks.add(
        "all_geographic_sources_declare_a_geodetic_datum",
        not any(
            "datum not declared" in str(row.get("source_crs") or "").casefold()
            for row in d2_rows
        ),
        category="source_completeness",
        severity="review",
        expected="declared datum for every coordinate",
        actual="GEOROC decimal-degree bounds do not declare a datum",
        note="GEOROC midpoint points use an explicit screening-only identity assumption, never an unlabeled WGS84 claim.",
    )
    water_continents = {
        row["benchmark_continent"] for row in d1_rows if row["medium"] == "water"
    }
    checks.add(
        "water_slice_covers_all_seven_continents",
        water_continents == required_continents,
        category="coverage_gap",
        severity="review",
        expected=sorted(required_continents),
        actual=sorted(water_continents),
        note="The openly licensed GEMStat v3 subset used here has target-element results in four continents only.",
    )

    confidence_bands = Counter(
        row["operational_confidence"].get("band") for row in d2_rows
    )
    total_elapsed = sum(
        float(stage.get("elapsed_seconds", 0)) for stage in stages.values()
    )
    d2_output_bytes = sum(
        path.stat().st_size for path in d2_dir.iterdir() if path.is_file()
    )
    checks.add(
        "global_flow_stays_inside_competition_runtime_and_repository_budgets",
        total_elapsed < 900 and fixture_bytes < 250_000_000,
        category="resource_budget",
        expected={"runtime_seconds": "<900", "fixture_bytes": "<250000000"},
        actual={
            "runtime_seconds": round(total_elapsed, 3),
            "fixture_bytes": fixture_bytes,
        },
    )

    summary = checks.summary()
    report = {
        "suite_version": SUITE_VERSION,
        "interface_version": "d2-interface-v2",
        "profile": profile,
        "status": summary["status"],
        "candidate": {
            "label": candidate_label,
            "d2_script": str(candidate_d2_script),
            "sha256": sha256_file(candidate_d2_script),
        },
        "configuration": {
            "fixture_dir": str(fixture_dir),
            "expanded_fixture_dir": str(expanded_fixture_dir) if expanded else None,
            "network_during_evaluation": "disabled; frozen resources are hash-verified",
            "full_parent_downloads_bundled": False,
        },
        "source_inventory": [
            {
                "id": dataset["id"],
                "title": dataset["title"],
                "medium": dataset["medium"],
                "persistent_identifier": dataset["persistent_identifier"],
                "license": dataset["license"],
                "geographic_scope": dataset["geographic_scope"],
                "scientific_limits": dataset["scientific_limits"],
            }
            for dataset in source_contract["datasets"]
        ],
        "coverage": {
            "continents": sorted(continent_counts),
            "records_by_continent": dict(sorted(continent_counts.items())),
            "media": sorted(medium_counts),
            "coverage_matrix": coverage_matrix,
            "gemstat_country_count": d1_manifest["gemstat_country_count"],
            "explicit_country_label_count": d1_manifest.get(
                "explicit_country_label_count"
            ),
            "explicit_country_labels": d1_manifest.get("explicit_country_labels", []),
            "declared_blind_spots": d1_manifest["declared_blind_spots"],
        },
        "metrics": {
            "frozen_resource_count": fixture_payload["resource_count"],
            "frozen_fixture_bytes": fixture_bytes,
            "d1_record_count": len(d1_rows),
            "records_by_source": dict(sorted(source_counts.items())),
            "records_by_medium": dict(sorted(medium_counts.items())),
            "records_by_element": dict(sorted(element_counts.items())),
            "standardized_value_count": sum(
                row["normalized_value"] is not None for row in d2_rows
            ),
            "censored_record_count": sum(row["censored"] for row in d2_rows),
            "mappable_record_count": sum(
                row["latitude"] is not None and row["longitude"] is not None
                for row in d2_rows
            ),
            "qc_flag_counts": qc_report.get("flag_counts", {}),
            "confidence_band_counts": dict(sorted(confidence_bands.items())),
            "analyzed_background_groups": len(analyzed_groups),
            "candidate_anomalies": len(anomaly_features),
            "anomaly_region_cells": len(region_features),
            "candidate_anomaly_clusters": anomaly_region_report.get(
                "status_counts", {}
            ).get("candidate_cluster", 0),
            "d2_output_bytes": d2_output_bytes,
            "d3_atlas_bytes": (d3_dir / "atlas.html").stat().st_size,
            "stage_elapsed_seconds": {
                name: stage.get("elapsed_seconds") for name, stage in stages.items()
            },
            "total_stage_elapsed_seconds": round(total_elapsed, 6),
        },
        "artifacts": {
            "d1_export": "d1/d1_global_export.csv",
            "d1_manifest": "d1/d1_global_manifest.json",
            "standardized_geochemical_database": "d2/geochemistry.csv",
            "d2_qc": "d2/qc_report.json",
            "d2_confidence": "d2/confidence_report.json",
            "d2_anomaly_report": "d2/anomaly_report.json",
            "interactive_element_map": "d3/atlas.html",
            "source_and_confidence_explanation": "d3/source_confidence.json",
            "anomaly_region_results": "d3/anomaly_regions.geojson",
            "anomaly_region_report": "d3/anomaly_region_report.json",
            "showcase_manifest": "d3/showcase_manifest.json",
            "d3_report": "d3/d3_consumer_report.json",
        },
        "interpretation": {
            "scientific_status": "validation_evidence_only",
            "not_a_global_population_estimate": True,
            "not_a_causal_conclusion": True,
            "statement": (
                "Passing checks demonstrate D2 behavior on a value-independent, frozen global coverage slice. "
                "They do not establish global representativeness, contamination, mineralization or geological cause."
            ),
        },
        "stages": stages,
        "confidence_report_not_probability": confidence_report.get("not_a_probability"),
        **summary,
    }
    atomic_write_json(output_dir / "global_data_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the offline seven-continent D1 -> candidate D2 -> D3 benchmark."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New or empty benchmark result directory",
    )
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument(
        "--expanded",
        action="store_true",
        help="add the frozen China/Africa/Europe/Japan profile while keeping the core data",
    )
    parser.add_argument(
        "--expanded-fixture-dir",
        type=Path,
        default=DEFAULT_EXPANDED_FIXTURE_DIR,
    )
    parser.add_argument(
        "--d2-script",
        type=Path,
        default=D2_SCRIPT,
        help="Candidate D2 CLI implementing --input and --output-dir (defaults to the team D2 baseline)",
    )
    parser.add_argument("--candidate-label", default="team-d2-baseline")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        started = time.perf_counter()
        report = run_global_suite(
            args.output_dir,
            args.fixture_dir,
            args.d2_script.resolve(),
            args.candidate_label,
            expanded=args.expanded,
            expanded_fixture_dir=args.expanded_fixture_dir,
        )
        wall_seconds = round(time.perf_counter() - started, 6)
    except (OSError, ValueError, csv.Error, json.JSONDecodeError, KeyError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.output_dir / "global_data_report.json"),
                "blocking_failed": report.get("counts", {})
                .get("blocking", {})
                .get("failed"),
                "review_failed": report.get("counts", {})
                .get("review", {})
                .get("failed"),
                "atlas": str(args.output_dir / "d3" / "atlas.html"),
                "database": str(args.output_dir / "d2" / "geochemistry.csv"),
                "source_confidence": str(
                    args.output_dir / "d3" / "source_confidence.json"
                ),
                "anomaly_regions": str(
                    args.output_dir / "d3" / "anomaly_regions.geojson"
                ),
                "profile": "expanded" if args.expanded else "core",
                "wall_seconds": wall_seconds,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
