#!/usr/bin/env python3
"""Run independent D1, D2 and D3 benchmarks against frozen real data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parents[1]
CONTRACT_PATH = LAB_ROOT / "contracts" / "stage-benchmark-v1.json"
CORE_FIXTURE_DIR = LAB_ROOT / "global-data" / "fixtures" / "raw"
EXPANDED_FIXTURE_DIR = LAB_ROOT / "expanded-data" / "fixtures" / "raw"
GOLD_RUN_DIR = LAB_ROOT / "runs" / "expanded-latest"
GOLD_D1_DIR = GOLD_RUN_DIR / "d1"
GOLD_D2_DIR = GOLD_RUN_DIR / "d2"
GOLD_D3_DIR = GOLD_RUN_DIR / "d3"
REFERENCE_D1 = LAB_ROOT / "scripts" / "expanded_global_d1_adapter.py"
REFERENCE_D2 = (
    REPO_ROOT
    / "evaluation_lyf"
    / "reference_implementation"
    / "d2"
    / "scripts"
    / "geochem_d2_pipeline.py"
)
REFERENCE_D3 = (
    REPO_ROOT
    / "global-geochemical-atlas-skill-d3"
    / "skills"
    / "global-geochemical-atlas"
    / "scripts"
    / "render_visualization.py"
)
GLOBAL_SUITE = LAB_ROOT / "scripts" / "run_global_data_suite.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_empty_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"output directory must not exist or must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def run_command(command: Sequence[str], timeout: int = 900) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        return {
            "command": list(command),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-4000:],
            "stderr_tail": completed.stderr[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": list(command),
            "elapsed_seconds": round(time.perf_counter() - started, 6),
            "returncode": 124,
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "timeout": timeout,
        }


class Checks:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def add(
        self,
        name: str,
        passed: bool,
        *,
        category: str,
        severity: str = "blocking",
        expected: Any = None,
        actual: Any = None,
        note: str | None = None,
    ) -> None:
        if severity not in {"blocking", "review"}:
            raise ValueError(f"unsupported severity: {severity}")
        self.items.append(
            {
                "name": name,
                "category": category,
                "severity": severity,
                "passed": bool(passed),
                "expected": expected,
                "actual": actual,
                "note": note,
            }
        )

    def absorb(self, items: Iterable[Mapping[str, Any]], prefix: str = "") -> None:
        for item in items:
            self.add(
                f"{prefix}{item.get('name', 'unnamed')}",
                bool(item.get("passed")),
                category=str(item.get("category", "upstream")),
                severity=str(item.get("severity", "blocking")),
                expected=item.get("expected"),
                actual=item.get("actual"),
                note=item.get("note"),
            )

    def summary(self) -> dict[str, Any]:
        counts: dict[str, dict[str, int]] = {}
        for severity in ("blocking", "review"):
            selected = [item for item in self.items if item["severity"] == severity]
            counts[severity] = {
                "total": len(selected),
                "passed": sum(item["passed"] for item in selected),
                "failed": sum(not item["passed"] for item in selected),
            }
        if counts["blocking"]["failed"]:
            status = "fail"
        elif counts["review"]["failed"]:
            status = "pass_with_findings"
        else:
            status = "pass"
        return {
            "status": status,
            "counts": counts,
            "review_required": bool(counts["review"]["failed"]),
            "findings": [item for item in self.items if not item["passed"]],
            "checks": self.items,
        }


def nonempty(row: Mapping[str, str], field: str) -> bool:
    return bool(str(row.get(field, "")).strip())


def field_rate(rows: Sequence[Mapping[str, str]], field: str) -> float:
    return sum(nonempty(row, field) for row in rows) / len(rows) if rows else 0.0


def pair_rate(rows: Sequence[Mapping[str, str]], left: str, right: str) -> float:
    return (
        sum(nonempty(row, left) and nonempty(row, right) for row in rows) / len(rows)
        if rows
        else 0.0
    )


def all_nonempty(rows: Sequence[Mapping[str, str]], fields: Sequence[str]) -> bool:
    return all(all(nonempty(row, field) for field in fields) for row in rows)


def run_d1_benchmark(
    root: Path,
    script: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    stage_root = root / "d1"
    stage_root.mkdir(parents=True, exist_ok=True)
    candidate_dir = stage_root / "candidate_output"
    checks = Checks()
    checks.add(
        "candidate_d1_script_exists",
        script.is_file(),
        category="stage_execution",
        expected=str(script),
        actual=script.is_file(),
    )
    execution: dict[str, Any] | None = None
    if script.is_file():
        execution = run_command(
            [
                sys.executable,
                str(script),
                "--core-fixture-dir",
                str(CORE_FIXTURE_DIR),
                "--expanded-fixture-dir",
                str(EXPANDED_FIXTURE_DIR),
                "--output-dir",
                str(candidate_dir),
            ]
        )
        checks.add(
            "candidate_d1_cli_succeeds",
            execution["returncode"] == 0,
            category="stage_execution",
            expected=0,
            actual=execution["returncode"],
            note=execution.get("stderr_tail") or None,
        )

    expected_files = set(contract["required_outputs"])
    present_files = {path.name for path in candidate_dir.iterdir()} if candidate_dir.is_dir() else set()
    checks.add(
        "candidate_d1_emits_required_outputs",
        expected_files <= present_files,
        category="interface",
        expected=sorted(expected_files),
        actual=sorted(present_files),
    )
    export_path = candidate_dir / "d1_global_export.csv"
    manifest_path = candidate_dir / "d1_global_manifest.json"
    metrics: dict[str, Any] = {}
    if export_path.is_file() and manifest_path.is_file():
        fields, rows = read_csv(export_path)
        _, gold_rows = read_csv(GOLD_D1_DIR / "d1_global_export.csv")
        manifest = read_json(manifest_path)
        expected = contract["expected"]
        required_columns = set(contract["required_columns"])
        checks.add(
            "d1_schema_contains_task_fields",
            required_columns <= set(fields),
            category="schema",
            expected=sorted(required_columns),
            actual=sorted(set(fields) & required_columns),
        )
        checks.add(
            "d1_record_count_matches_frozen_raw_sources",
            len(rows) == expected["record_count"],
            category="collection_completeness",
            expected=expected["record_count"],
            actual=len(rows),
        )
        ids = [row.get("record_id", "") for row in rows]
        gold_ids = {row.get("record_id", "") for row in gold_rows}
        checks.add(
            "d1_record_ids_are_unique_and_match_frozen_selection",
            len(ids) == len(set(ids)) and set(ids) == gold_ids,
            category="collection_completeness",
            expected={"unique": True, "record_id_count": len(gold_ids)},
            actual={"unique": len(ids) == len(set(ids)), "record_id_count": len(set(ids))},
        )
        source_counts = Counter(row.get("source_id", "") for row in rows)
        medium_counts = Counter(row.get("medium", "") for row in rows)
        element_counts = Counter(row.get("element_or_analyte", "") for row in rows)
        continents = {row.get("benchmark_continent", "") for row in rows if row.get("benchmark_continent")}
        countries = {row.get("benchmark_country", "") for row in rows if row.get("benchmark_country")}
        checks.add(
            "d1_source_counts_match_frozen_contract",
            dict(sorted(source_counts.items())) == expected["records_by_source"],
            category="collection_completeness",
            expected=expected["records_by_source"],
            actual=dict(sorted(source_counts.items())),
        )
        checks.add(
            "d1_covers_all_four_media",
            set(medium_counts) == set(expected["media"]),
            category="domain_coverage",
            expected=expected["media"],
            actual=sorted(medium_counts),
        )
        checks.add(
            "d1_covers_all_seven_target_elements",
            set(element_counts) == set(expected["elements"]),
            category="domain_coverage",
            expected=expected["elements"],
            actual=sorted(element_counts),
        )
        checks.add(
            "d1_has_union_coverage_on_all_seven_continents",
            continents == set(expected["continents"]),
            category="geographic_coverage",
            expected=expected["continents"],
            actual=sorted(continents),
        )
        checks.add(
            "d1_retains_at_least_reference_country_region_labels",
            len(countries) >= expected["explicit_country_label_count"],
            category="geographic_coverage",
            expected=f">={expected['explicit_country_label_count']}",
            actual=len(countries),
            note="Labels are source country/region labels, not proof of sovereign-state representativeness.",
        )
        rates = {
            "coordinate_pair": pair_rate(rows, "latitude", "longitude"),
            "analytical_method": field_rate(rows, "analytical_method"),
            "geologic_context_source": field_rate(rows, "geologic_context_source"),
            "coordinate_uncertainty_m": field_rate(rows, "coordinate_uncertainty_m"),
            "source_crs": field_rate(rows, "source_crs"),
        }
        provenance_fields = [
            "source_id",
            "dataset_title",
            "dataset_doi",
            "dataset_version",
            "source_file",
            "source_row",
            "source_locator",
            "file_sha256",
            "license",
        ]
        rates["record_provenance"] = (
            sum(all(nonempty(row, field) for field in provenance_fields) for row in rows) / len(rows)
            if rows
            else 0.0
        )
        for name, minimum in expected["minimum_rates"].items():
            checks.add(
                f"d1_{name}_rate_meets_reference_floor",
                rates.get(name, 0.0) >= minimum,
                category="field_completeness",
                expected=f">={minimum}",
                actual=round(rates.get(name, 0.0), 6),
            )
        checks.add(
            "d1_file_hashes_are_well_formed",
            all(SHA256_RE.fullmatch(row.get("file_sha256", "")) for row in rows),
            category="evidence_chain",
            expected="64 lowercase hexadecimal characters on every record",
            actual=sum(bool(SHA256_RE.fullmatch(row.get("file_sha256", ""))) for row in rows),
        )
        by_id = {row.get("record_id", ""): row for row in rows}
        for record_id, expected_fields in contract["spot_checks"].items():
            actual_row = by_id.get(record_id)
            actual = (
                {field: actual_row.get(field) for field in expected_fields}
                if actual_row is not None
                else None
            )
            checks.add(
                f"d1_spot_{record_id}",
                actual_row is not None
                and all(actual_row.get(field) == value for field, value in expected_fields.items()),
                category="scientific_spot_check",
                expected=expected_fields,
                actual=actual,
            )
        output = manifest.get("output", {})
        checks.add(
            "d1_manifest_closes_output_hash_chain",
            manifest.get("status") == "success"
            and manifest.get("record_count") == len(rows)
            and manifest.get("source_dataset_count") == len(source_counts)
            and output.get("sha256") == sha256_file(export_path)
            and output.get("bytes") == export_path.stat().st_size,
            category="evidence_chain",
            expected="manifest status/count/bytes/hash agree with CSV",
            actual={
                "status": manifest.get("status"),
                "record_count": manifest.get("record_count"),
                "source_dataset_count": manifest.get("source_dataset_count"),
                "sha256": output.get("sha256"),
            },
        )
        coverage_cells = {
            (row.get("benchmark_continent", ""), row.get("medium", "")) for row in rows
        }
        water_continents = {
            row.get("benchmark_continent", "") for row in rows if row.get("medium") == "water"
        }
        checks.add(
            "d1_all_seven_continents_have_all_four_media",
            len(coverage_cells) == 28,
            category="coverage_gap",
            severity="review",
            expected="28/28 nonempty continent-medium cells",
            actual=f"{len(coverage_cells)}/28",
            note="Union coverage is global, but the fixture is not a complete global four-medium survey.",
        )
        checks.add(
            "d1_all_records_publish_analytical_method",
            math.isclose(rates["analytical_method"], 1.0),
            category="source_metadata_gap",
            severity="review",
            expected=1.0,
            actual=round(rates["analytical_method"], 6),
            note="Missing source methods must stay missing and lower confidence; do not invent them.",
        )
        checks.add(
            "d1_all_records_have_geologic_context_or_point_match",
            math.isclose(rates["geologic_context_source"], 1.0),
            category="spatial_geology_gap",
            severity="review",
            expected=1.0,
            actual=round(rates["geologic_context_source"], 6),
            note="The reference contains source-reported geology for part of the data, not a global polygon join.",
        )
        checks.add(
            "d1_all_coordinates_publish_uncertainty",
            math.isclose(rates["coordinate_uncertainty_m"], 1.0),
            category="spatial_metadata_gap",
            severity="review",
            expected=1.0,
            actual=round(rates["coordinate_uncertainty_m"], 6),
        )
        checks.add(
            "d1_water_slice_covers_all_seven_continents",
            water_continents == set(expected["continents"]),
            category="coverage_gap",
            severity="review",
            expected=expected["continents"],
            actual=sorted(water_continents),
        )
        metrics = {
            "record_count": len(rows),
            "source_dataset_count": len(source_counts),
            "records_by_source": dict(sorted(source_counts.items())),
            "records_by_medium": dict(sorted(medium_counts.items())),
            "records_by_element": dict(sorted(element_counts.items())),
            "continent_medium_nonempty_cells": len(coverage_cells),
            "explicit_country_label_count": len(countries),
            "field_rates": {key: round(value, 6) for key, value in rates.items()},
            "output_sha256": sha256_file(export_path),
        }
    summary = checks.summary()
    report = {
        "stage": "d1",
        "benchmark_version": "geochemical-stage-benchmark-v1",
        "candidate_script": str(script),
        "candidate_sha256": sha256_file(script) if script.is_file() else None,
        "execution": execution,
        "metrics": metrics,
        **summary,
    }
    write_json(stage_root / "d1_stage_report.json", report)
    return report


def parse_json_field(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


def run_d2_benchmark(
    root: Path,
    script: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    stage_root = root / "d2"
    stage_root.mkdir(parents=True, exist_ok=True)
    suite_dir = stage_root / "suite"
    checks = Checks()
    checks.add(
        "candidate_d2_script_exists",
        script.is_file(),
        category="stage_execution",
        expected=str(script),
        actual=script.is_file(),
    )
    execution: dict[str, Any] | None = None
    suite_report: dict[str, Any] = {}
    if script.is_file():
        execution = run_command(
            [
                sys.executable,
                str(GLOBAL_SUITE),
                "--expanded",
                "--output-dir",
                str(suite_dir),
                "--d2-script",
                str(script),
                "--candidate-label",
                "stage-benchmark-d2",
            ]
        )
        checks.add(
            "candidate_d2_suite_command_completes",
            execution["returncode"] == 0,
            category="stage_execution",
            expected=0,
            actual=execution["returncode"],
            note=execution.get("stderr_tail") or None,
        )
        report_path = suite_dir / "global_data_report.json"
        if report_path.is_file():
            suite_report = read_json(report_path)
            checks.absorb(suite_report.get("checks", []), prefix="global_suite__")
        else:
            checks.add(
                "global_suite_report_exists",
                False,
                category="interface",
                expected=str(report_path),
                actual="missing",
            )

    d2_dir = suite_dir / "d2"
    database_path = d2_dir / "geochemistry.csv"
    metrics: dict[str, Any] = {}
    if database_path.is_file():
        fields, rows = read_csv(database_path)
        _, d1_rows = read_csv(suite_dir / "d1" / "d1_global_export.csv")
        expected = contract["expected"]
        required_preserved = [
            "record_id",
            "original_value_raw",
            "original_unit",
            "source_qualifier_raw",
            "normalized_value",
            "normalized_unit",
            "normalized_censoring_limit",
            "latitude",
            "longitude",
            "source_crs",
            "geologic_unit",
            "geologic_context_source",
            "geologic_match_method",
            "analytical_method",
            "method_family",
            "digestion_or_extraction",
            "source_id",
            "dataset_doi",
            "dataset_version",
            "source_locator",
            "file_sha256",
            "license",
            "qc_flags",
            "operational_confidence",
        ]
        checks.add(
            "d2_database_contains_standard_scientific_and_evidence_fields",
            set(required_preserved) <= set(fields),
            category="schema",
            expected=required_preserved,
            actual=sorted(set(fields) & set(required_preserved)),
        )
        checks.add(
            "d2_retains_every_d1_measurement",
            len(rows) == len(d1_rows) == expected["record_count"],
            category="record_retention",
            expected=expected["record_count"],
            actual={"d1": len(d1_rows), "d2": len(rows)},
        )
        d1_by_id = {row["record_id"]: row for row in d1_rows}
        d2_by_id = {row.get("record_id", ""): row for row in rows}
        source_fields = [
            "source_id",
            "dataset_title",
            "dataset_doi",
            "dataset_version",
            "source_file",
            "source_row",
            "source_locator",
            "file_sha256",
            "license",
        ]
        provenance_preserved = all(
            record_id in d2_by_id
            and all(d2_by_id[record_id].get(field, "") == row.get(field, "") for field in source_fields)
            for record_id, row in d1_by_id.items()
        )
        checks.add(
            "d2_preserves_record_level_provenance_exactly",
            provenance_preserved,
            category="evidence_chain",
            expected=True,
            actual=provenance_preserved,
        )
        spatial_fields = [
            "source_crs",
            "coordinate_transform_method",
            "coordinate_uncertainty_m",
            "geologic_unit",
            "geologic_unit_id",
            "geologic_context_source",
            "geologic_context_version",
            "geologic_match_method",
            "geologic_match_confidence",
        ]
        def spatial_value_preserved(d1_row: Mapping[str, str], d2_row: Mapping[str, str], field: str) -> bool:
            source_value = d1_row.get(field, "")
            if not source_value:
                return True
            output_value = d2_row.get(field, "")
            if field in {"coordinate_uncertainty_m", "distance_to_geologic_boundary_m"}:
                try:
                    return math.isclose(
                        float(source_value),
                        float(output_value),
                        rel_tol=1e-12,
                        abs_tol=1e-12,
                    )
                except (TypeError, ValueError):
                    return False
            return output_value == source_value

        spatial_evidence_preserved = all(
            record_id in d2_by_id
            and all(
                spatial_value_preserved(d1_row, d2_by_id[record_id], field)
                for field in spatial_fields
            )
            for record_id, d1_row in d1_by_id.items()
        )
        checks.add(
            "d2_preserves_all_declared_spatial_and_geologic_evidence",
            spatial_evidence_preserved,
            category="spatial_matching",
            expected=True,
            actual=spatial_evidence_preserved,
        )
        quantified_rows = [
            row
            for row in rows
            if row.get("normalized_value", "") or row.get("normalized_censoring_limit", "")
        ]
        wrong_solid_units = [
            row.get("record_id")
            for row in quantified_rows
            if row.get("medium") in {"rock", "soil", "sediment"}
            and row.get("normalized_unit") != "mg/kg"
        ]
        wrong_water_units = [
            row.get("record_id")
            for row in quantified_rows
            if row.get("medium") == "water" and row.get("normalized_unit") != "ug/L"
        ]
        checks.add(
            "d2_units_are_medium_aware",
            not wrong_solid_units and not wrong_water_units,
            category="standardization",
            expected={"solid": "mg/kg", "water": "ug/L"},
            actual={
                "wrong_solid_count": len(wrong_solid_units),
                "wrong_water_count": len(wrong_water_units),
            },
        )
        censored_rows = [row for row in rows if row.get("censored", "").lower() == "true"]
        checks.add(
            "d2_censored_values_are_not_imputed",
            len(censored_rows) == expected["censored_record_count"]
            and all(not row.get("normalized_value", "") for row in censored_rows)
            and all(row.get("normalized_censoring_limit", "") for row in censored_rows),
            category="scientific_semantics",
            expected=expected["censored_record_count"],
            actual=len(censored_rows),
        )
        geology_matches = [row for row in rows if row.get("geologic_match_method", "")]
        non_source_join_methods = {
            row.get("geologic_match_method", "")
            for row in geology_matches
            if not row.get("geologic_match_method", "").startswith("source_reported")
        }
        method_rate = field_rate(rows, "analytical_method")
        uncertainty_rate = field_rate(rows, "coordinate_uncertainty_m")
        checks.add(
            "d2_all_records_have_a_documented_geologic_spatial_match",
            len(geology_matches) == len(rows),
            category="spatial_geology_gap",
            severity="review",
            expected=len(rows),
            actual=len(geology_matches),
            note="The current reference preserves source-reported context but does not run one global geology polygon join.",
        )
        checks.add(
            "d2_performs_an_independent_versioned_spatial_join",
            bool(non_source_join_methods),
            category="spatial_geology_gap",
            severity="review",
            expected="at least one documented non-source-reported match method",
            actual=sorted(non_source_join_methods),
        )
        checks.add(
            "d2_all_records_have_analysis_method",
            math.isclose(method_rate, 1.0),
            category="source_metadata_gap",
            severity="review",
            expected=1.0,
            actual=round(method_rate, 6),
        )
        checks.add(
            "d2_all_records_have_coordinate_uncertainty",
            math.isclose(uncertainty_rate, 1.0),
            category="spatial_metadata_gap",
            severity="review",
            expected=1.0,
            actual=round(uncertainty_rate, 6),
        )
        confidence_path = d2_dir / "confidence_report.json"
        anomaly_path = d2_dir / "anomaly_report.json"
        anomalies_path = d2_dir / "anomalies.geojson"
        samples_path = d2_dir / "samples.geojson"
        if all(path.is_file() for path in (confidence_path, anomaly_path, anomalies_path, samples_path)):
            confidence = read_json(confidence_path)
            anomaly_report = read_json(anomaly_path)
            anomalies = read_json(anomalies_path)
            samples = read_json(samples_path)
            components = set(confidence.get("component_means", {})) - {"overall"}
            checks.add(
                "d2_confidence_has_five_named_components_and_is_not_probability",
                set(expected["confidence_components"]) <= components
                and confidence.get("not_a_probability") is True,
                category="confidence",
                expected=expected["confidence_components"],
                actual=sorted(components),
            )
            checks.add(
                "d2_anomaly_groups_keep_scientific_comparability_fields",
                set(expected["group_by_required"]) <= set(anomaly_report.get("group_by", [])),
                category="anomaly",
                expected=expected["group_by_required"],
                actual=anomaly_report.get("group_by", []),
            )
            metrics = {
                "record_count": len(rows),
                "standardized_or_censoring_limit_count": len(quantified_rows),
                "censored_record_count": len(censored_rows),
                "mappable_record_count": len(samples.get("features", [])),
                "candidate_anomaly_count": len(anomalies.get("features", [])),
                "geologic_match_count": len(geology_matches),
                "geologic_match_rate": round(len(geology_matches) / len(rows), 6),
                "analytical_method_rate": round(method_rate, 6),
                "coordinate_uncertainty_rate": round(uncertainty_rate, 6),
                "non_source_spatial_join_methods": sorted(non_source_join_methods),
            }
    summary = checks.summary()
    report = {
        "stage": "d2",
        "benchmark_version": "geochemical-stage-benchmark-v1",
        "candidate_script": str(script),
        "candidate_sha256": sha256_file(script) if script.is_file() else None,
        "execution": execution,
        "metrics": metrics,
        "suite_report": str(suite_dir / "global_data_report.json"),
        **summary,
    }
    write_json(stage_root / "d2_stage_report.json", report)
    return report


def build_d3_source_manifest(target: Path) -> dict[str, Any]:
    d1_manifest = read_json(GOLD_D1_DIR / "d1_global_manifest.json")
    _, d1_rows = read_csv(GOLD_D1_DIR / "d1_global_export.csv")
    rows_by_source: dict[str, list[dict[str, str]]] = {}
    for row in d1_rows:
        rows_by_source.setdefault(row["source_id"], []).append(row)
    sources: list[dict[str, Any]] = []
    for source_id, rows in sorted(rows_by_source.items()):
        source_files: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (row.get("source_file", ""), row.get("file_sha256", ""))
            source_files.setdefault(
                key,
                {
                    "filename": row.get("source_file"),
                    "sha256": row.get("file_sha256"),
                    "url": row.get("source_locator"),
                },
            )
        sources.append(
            {
                "source_id": source_id,
                "record_count": len(rows),
                "dataset_titles": sorted({row["dataset_title"] for row in rows if row.get("dataset_title")}),
                "dataset_dois": sorted({row["dataset_doi"] for row in rows if row.get("dataset_doi")}),
                "dataset_versions": sorted(
                    {row["dataset_version"] for row in rows if row.get("dataset_version")}
                ),
                "licenses": sorted({row["license"] for row in rows if row.get("license")}),
                "source_tiers": sorted({row["source_tier"] for row in rows if row.get("source_tier")}),
                "located_record_count": sum(bool(row.get("source_locator")) for row in rows),
                "source_files": list(source_files.values()),
            }
        )
    manifest = {
        "manifest_version": "d1-d3-stage-benchmark-source-manifest-v1",
        "scientific_scope": d1_manifest.get("scientific_scope"),
        "source_count": len(sources),
        "record_count": d1_manifest.get("record_count"),
        "sources": sources,
        "coverage": {
            "records_by_source": d1_manifest.get("records_by_source"),
            "records_by_medium": d1_manifest.get("records_by_medium"),
            "records_by_element": d1_manifest.get("records_by_element"),
            "records_by_continent": d1_manifest.get("records_by_continent"),
            "coverage_matrix": d1_manifest.get("coverage_matrix"),
            "explicit_country_label_count": d1_manifest.get("explicit_country_label_count"),
        },
        "claim_boundary": (
            "This manifest describes a frozen evaluation slice. Source presence is not proof of national "
            "representativeness; blank regions are coverage gaps, not zero concentration."
        ),
        "interpretation_limits": d1_manifest.get("interpretation_limits", []),
        "inputs": {
            "d1_export_sha256": sha256_file(GOLD_D1_DIR / "d1_global_export.csv"),
            "d1_manifest_sha256": sha256_file(GOLD_D1_DIR / "d1_global_manifest.json"),
        },
    }
    write_json(target, manifest)
    return manifest


def stage_d3_inputs(input_dir: Path) -> dict[str, Path]:
    input_dir.mkdir(parents=True, exist_ok=False)
    required = [
        "geochemistry.csv",
        "anomalies.geojson",
        "qc_report.json",
        "confidence_report.json",
        "anomaly_report.json",
    ]
    paths: dict[str, Path] = {}
    for name in required:
        source = (GOLD_D2_DIR / name).resolve()
        target = input_dir / name
        target.symlink_to(source)
        paths[name] = target
    source_manifest_path = input_dir / "source_manifest.json"
    build_d3_source_manifest(source_manifest_path)
    paths["source_manifest.json"] = source_manifest_path
    return paths


def contains_all(text: str, values: Sequence[str]) -> bool:
    folded = text.casefold()
    return all(value.casefold() in folded for value in values)


def run_d3_benchmark(
    root: Path,
    script: Path,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    stage_root = root / "d3"
    stage_root.mkdir(parents=True, exist_ok=True)
    input_dir = stage_root / "gold_input"
    input_paths = stage_d3_inputs(input_dir)
    candidate_dir = stage_root / "candidate_output"
    checks = Checks()
    checks.add(
        "candidate_d3_script_exists",
        script.is_file(),
        category="stage_execution",
        expected=str(script),
        actual=script.is_file(),
    )
    execution: dict[str, Any] | None = None
    if script.is_file():
        execution = run_command(
            [
                sys.executable,
                str(script),
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(candidate_dir),
            ]
        )
        checks.add(
            "candidate_d3_cli_succeeds",
            execution["returncode"] == 0,
            category="stage_execution",
            expected=0,
            actual=execution["returncode"],
            note=execution.get("stderr_tail") or None,
        )
    present = {path.name for path in candidate_dir.iterdir()} if candidate_dir.is_dir() else set()
    preferred = set(contract["preferred_outputs"])
    map_names = set(contract["compatibility_map_names"])
    evidence_outputs = preferred - {"interactive_map.html"}
    checks.add(
        "d3_emits_complete_portable_product_bundle",
        evidence_outputs <= present and bool(map_names & present),
        category="product_deliverables",
        expected={"evidence_outputs": sorted(evidence_outputs), "map_one_of": sorted(map_names)},
        actual=sorted(present),
    )
    metrics: dict[str, Any] = {}
    map_path = next((candidate_dir / name for name in contract["compatibility_map_names"] if (candidate_dir / name).is_file()), None)
    report_path = candidate_dir / "visualization_report.json"
    if map_path is not None and report_path.is_file():
        report = read_json(report_path)
        checks.add(
            "d3_report_declares_success",
            report.get("status") == "success",
            category="interface",
            expected="success",
            actual=report.get("status"),
        )
        for name, input_path in input_paths.items():
            output_path = candidate_dir / name
            checks.add(
                f"d3_preserves_{name}_byte_for_byte",
                output_path.is_file() and sha256_file(output_path) == sha256_file(input_path),
                category="evidence_preservation",
                expected=sha256_file(input_path),
                actual=sha256_file(output_path) if output_path.is_file() else "missing",
            )
        map_report = report.get("map_report", {})
        expected = contract["expected"]
        checks.add(
            "d3_map_counts_match_frozen_d2",
            map_report.get("mapped_record_count") == expected["mappable_record_count"]
            and map_report.get("candidate_record_count") == expected["candidate_anomaly_count"]
            and map_report.get("display_sample_count") == expected["display_sample_count"],
            category="product_correctness",
            expected={
                "mapped_record_count": expected["mappable_record_count"],
                "candidate_record_count": expected["candidate_anomaly_count"],
                "display_sample_count": expected["display_sample_count"],
            },
            actual={
                "mapped_record_count": map_report.get("mapped_record_count"),
                "candidate_record_count": map_report.get("candidate_record_count"),
                "display_sample_count": map_report.get("display_sample_count"),
            },
        )
        modes = set(map_report.get("visualization_modes", []))
        required_modes = {
            "distribution_points",
            "sample_density_heatmap",
            "element_pair_comparison",
            "candidate_anomaly_region_aggregation",
        }
        checks.add(
            "d3_supports_distribution_heatmap_comparison_and_anomaly_views",
            required_modes <= modes,
            category="professional_workflow",
            expected=sorted(required_modes),
            actual=sorted(modes),
        )
        checks.add(
            "d3_does_not_interpolate_concentration",
            map_report.get("interpolation") is False,
            category="scientific_semantics",
            expected=False,
            actual=map_report.get("interpolation"),
            note="The heatmap is sampling density; concentration interpolation needs a separate validated model.",
        )
        checks.add(
            "d3_has_no_external_runtime_assets",
            map_report.get("external_assets") == expected["external_runtime_asset_count"],
            category="offline_reproducibility",
            expected=expected["external_runtime_asset_count"],
            actual=map_report.get("external_assets"),
        )
        html_text = map_path.read_text(encoding="utf-8")
        external_tag = re.search(
            r"<(?:script|img)[^>]+src\s*=\s*['\"](?:https?:)?//|<link[^>]+href\s*=\s*['\"](?:https?:)?//",
            html_text,
            flags=re.IGNORECASE,
        )
        checks.add(
            "d3_html_is_offline_and_self_contained",
            external_tag is None,
            category="offline_reproducibility",
            expected="no remote script, image or stylesheet tags",
            actual=external_tag.group(0) if external_tag else None,
        )
        filter_terms = ["区域", "元素", "介质", "地质单元", "方法组", "来源", "置信度"]
        checks.add(
            "d3_exposes_professional_filters",
            contains_all(html_text, filter_terms),
            category="professional_workflow",
            expected=filter_terms,
            actual={term: term in html_text for term in filter_terms},
        )
        view_terms = [
            "分布图",
            "热力图",
            "元素组合",
            "来源与置信度",
            "异常结果",
            "质量与边界",
        ]
        checks.add(
            "d3_exposes_all_required_product_views",
            contains_all(html_text, view_terms),
            category="product_deliverables",
            expected=view_terms,
            actual={term: term in html_text for term in view_terms},
        )
        evidence_terms = [
            "原始值",
            "分析方法",
            "地质单元",
            "source_locator",
            "QC",
            "删失值",
        ]
        checks.add(
            "d3_record_detail_supports_evidence_down_drill",
            contains_all(html_text, evidence_terms),
            category="professional_workflow",
            expected=evidence_terms,
            actual={term: term.casefold() in html_text.casefold() for term in evidence_terms},
        )
        boundary_terms = [
            "覆盖缺口",
            "不代表元素不存在",
            "候选异常不代表污染",
            "不是地质边界",
            "置信度不是概率",
        ]
        checks.add(
            "d3_makes_scientific_boundaries_visible",
            contains_all(html_text, boundary_terms),
            category="scientific_semantics",
            expected=boundary_terms,
            actual={term: term in html_text for term in boundary_terms},
        )
        checks.add(
            "d3_has_basic_accessibility_and_responsive_layout",
            "aria-label=" in html_text and "@media" in html_text and "role=\"img\"" in html_text,
            category="usability",
            expected=["aria-label", "role=img", "responsive media rules"],
            actual={
                "aria_label": "aria-label=" in html_text,
                "role_img": "role=\"img\"" in html_text,
                "responsive": "@media" in html_text,
            },
        )
        oversized = {
            path.name: path.stat().st_size
            for path in candidate_dir.iterdir()
            if path.is_file() and path.stat().st_size > expected["maximum_single_file_bytes"]
        }
        checks.add(
            "d3_single_files_stay_below_competition_limit",
            not oversized,
            category="engineering",
            expected=f"<={expected['maximum_single_file_bytes']} bytes",
            actual=oversized,
        )
        source_manifest = read_json(candidate_dir / "source_manifest.json")
        checks.add(
            "d3_source_view_receives_all_fifteen_sources_and_claim_boundary",
            source_manifest.get("source_count") == expected["source_count"]
            and len(source_manifest.get("sources", [])) == expected["source_count"]
            and bool(source_manifest.get("claim_boundary")),
            category="evidence_chain",
            expected=expected["source_count"],
            actual={
                "source_count": source_manifest.get("source_count"),
                "source_cards": len(source_manifest.get("sources", [])),
                "claim_boundary": bool(source_manifest.get("claim_boundary")),
            },
        )
        checks.add(
            "d3_has_completed_domain_expert_usability_study",
            False,
            category="human_validation_gap",
            severity="review",
            expected="documented geochemist task study on search, filtering, evidence and anomaly interpretation",
            actual="deterministic static and render checks only",
            note="Machine checks establish functionality, not a formal professional usability study.",
        )
        metrics = {
            "map_path": str(map_path),
            "map_bytes": map_path.stat().st_size,
            "mapped_record_count": map_report.get("mapped_record_count"),
            "display_sample_count": map_report.get("display_sample_count"),
            "candidate_anomaly_count": map_report.get("candidate_record_count"),
            "visualization_modes": sorted(modes),
            "external_runtime_assets": map_report.get("external_assets"),
            "profile_warnings": report.get("profile_warnings", []),
        }
    summary = checks.summary()
    report = {
        "stage": "d3",
        "benchmark_version": "geochemical-stage-benchmark-v1",
        "candidate_script": str(script),
        "candidate_sha256": sha256_file(script) if script.is_file() else None,
        "execution": execution,
        "gold_input": {name: str(path) for name, path in sorted(input_paths.items())},
        "metrics": metrics,
        **summary,
    }
    write_json(stage_root / "d3_stage_report.json", report)
    return report


def aggregate(stage_reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    blocking_total = sum(report["counts"]["blocking"]["total"] for report in stage_reports.values())
    blocking_failed = sum(report["counts"]["blocking"]["failed"] for report in stage_reports.values())
    review_total = sum(report["counts"]["review"]["total"] for report in stage_reports.values())
    review_failed = sum(report["counts"]["review"]["failed"] for report in stage_reports.values())
    if blocking_failed:
        status = "fail"
    elif review_failed:
        status = "pass_with_findings"
    else:
        status = "pass"
    return {
        "benchmark_version": "geochemical-stage-benchmark-v1",
        "profile": "expanded-global-real-v1",
        "status": status,
        "counts": {
            "blocking": {
                "total": blocking_total,
                "passed": blocking_total - blocking_failed,
                "failed": blocking_failed,
            },
            "review": {
                "total": review_total,
                "passed": review_total - review_failed,
                "failed": review_failed,
            },
        },
        "stage_status": {name: report["status"] for name, report in stage_reports.items()},
        "stage_reports": {
            name: f"{name}/{name}_stage_report.json" for name in stage_reports
        },
        "interpretation": {
            "pass": "all blocking and review checks pass",
            "pass_with_findings": (
                "all blocking checks pass; real source coverage, metadata, spatial matching or human validation gaps remain"
            ),
            "fail": "at least one interface, evidence-chain, product or scientific-red-line check fails",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark D1, D2 or D3 independently against frozen expanded global real data."
    )
    parser.add_argument("--stage", choices=("d1", "d2", "d3", "all"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--contract", type=Path, default=CONTRACT_PATH)
    parser.add_argument("--d1-script", type=Path, default=REFERENCE_D1)
    parser.add_argument("--d2-script", type=Path, default=REFERENCE_D2)
    parser.add_argument("--d3-script", type=Path, default=REFERENCE_D3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        prepare_empty_directory(args.output_dir)
        contract = read_json(args.contract)
        selected = ("d1", "d2", "d3") if args.stage == "all" else (args.stage,)
        reports: dict[str, dict[str, Any]] = {}
        if "d1" in selected:
            reports["d1"] = run_d1_benchmark(args.output_dir, args.d1_script.resolve(), contract["d1"])
        if "d2" in selected:
            reports["d2"] = run_d2_benchmark(args.output_dir, args.d2_script.resolve(), contract["d2"])
        if "d3" in selected:
            reports["d3"] = run_d3_benchmark(args.output_dir, args.d3_script.resolve(), contract["d3"])
        final_report = aggregate(reports)
        write_json(args.output_dir / "stage_benchmark_report.json", final_report)
    except (OSError, ValueError, KeyError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": final_report["status"],
                "report": str(args.output_dir / "stage_benchmark_report.json"),
                "counts": final_report["counts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 1 if final_report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
