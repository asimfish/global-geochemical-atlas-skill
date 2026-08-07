#!/usr/bin/env python3
"""Validate the stable outputs without third-party dependencies."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REQUIRED_FILES = {
    "database": "geochemistry.csv",
    "source_manifest": "source_manifest.json",
    "qc_report": "qc_report.json",
    "confidence_report": "confidence_report.json",
    "anomalies": "anomalies.geojson",
    "anomaly_report": "anomaly_report.json",
    "samples": "samples.geojson",
    "interactive_map": "interactive_map.html",
    "run_summary": "run_summary.json",
}

REQUIRED_DATABASE_COLUMNS = {
    "record_id",
    "sample_id",
    "element_or_analyte",
    "medium",
    "measurement_basis",
    "sample_type_raw",
    "sample_type",
    "sample_type_mapping_status",
    "original_value_raw",
    "original_unit",
    "value_qualifier",
    "normalized_value",
    "normalized_unit",
    "latitude",
    "longitude",
    "analytical_method",
    "method_scope",
    "digestion_or_extraction",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "citation_scope",
    "source_id",
    "source_locator",
    "license",
    "qc_flags",
    "operational_confidence",
}


def strict_json(path: Path) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def valid_coordinate_pair(coordinates: Any) -> bool:
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return False
    longitude, latitude = coordinates[:2]
    return (
        isinstance(longitude, (int, float))
        and not isinstance(longitude, bool)
        and math.isfinite(longitude)
        and -180 <= longitude <= 180
        and isinstance(latitude, (int, float))
        and not isinstance(latitude, bool)
        and math.isfinite(latitude)
        and -90 <= latitude <= 90
    )


def validate_database(path: Path, errors: list[str], warnings: list[str]) -> dict[str, int]:
    metrics = {"record_count": 0, "source_locator_missing": 0, "invalid_json_cells": 0}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_DATABASE_COLUMNS - headers)
        if missing:
            errors.append(f"geochemistry.csv missing columns: {', '.join(missing)}")
            return metrics
        record_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            metrics["record_count"] += 1
            record_id = (row.get("record_id") or "").strip()
            if not record_id:
                errors.append(f"geochemistry.csv:{line_number} has no record_id")
            elif record_id in record_ids:
                errors.append(f"geochemistry.csv:{line_number} repeats record_id {record_id}")
            record_ids.add(record_id)
            if not (row.get("source_locator") or "").strip():
                metrics["source_locator_missing"] += 1
            for column, expected in (("qc_flags", list), ("operational_confidence", dict)):
                try:
                    value = json.loads(row.get(column) or "null")
                except json.JSONDecodeError:
                    metrics["invalid_json_cells"] += 1
                    errors.append(f"geochemistry.csv:{line_number} has invalid {column} JSON")
                    continue
                if not isinstance(value, expected):
                    metrics["invalid_json_cells"] += 1
                    errors.append(f"geochemistry.csv:{line_number} has wrong {column} type")
    if metrics["record_count"] == 0:
        errors.append("geochemistry.csv contains no records")
    if metrics["source_locator_missing"]:
        warnings.append(f"{metrics['source_locator_missing']} record(s) lack source_locator")
    return metrics


def validate_feature_collection(
    value: Any,
    name: str,
    errors: list[str],
    allow_null_geometry: bool,
    require_candidate_status: bool = False,
) -> int:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        errors.append(f"{name} is not a GeoJSON FeatureCollection")
        return 0
    features = value.get("features")
    if not isinstance(features, list):
        errors.append(f"{name}.features is not an array")
        return 0
    for index, feature in enumerate(features):
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            errors.append(f"{name}.features[{index}] is not a Feature")
            continue
        geometry = feature.get("geometry")
        if geometry is None and allow_null_geometry:
            pass
        elif not isinstance(geometry, dict) or geometry.get("type") != "Point" or not valid_coordinate_pair(
            geometry.get("coordinates")
        ):
            errors.append(f"{name}.features[{index}] has invalid Point geometry")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            errors.append(f"{name}.features[{index}] has invalid properties")
        elif require_candidate_status and properties.get("status") != "candidate_anomaly":
            errors.append(f"{name}.features[{index}] overstates or omits candidate_anomaly status")
    return len(features)


def validate_html(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if '<script id="samples-data" type="application/json">' not in text:
        errors.append("interactive_map.html does not embed the samples data block")
    if re.search(r"<script\b[^>]*\bsrc\s*=", text, re.IGNORECASE):
        errors.append("interactive_map.html contains an external script dependency")
    if re.search(r"<link\b[^>]*\bhref\s*=\s*['\"]https?://", text, re.IGNORECASE):
        errors.append("interactive_map.html contains an external stylesheet dependency")
    if "候选异常不代表污染" not in text:
        errors.append("interactive_map.html omits the causal interpretation boundary")


def validate_dir(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    paths = {key: output_dir / filename for key, filename in REQUIRED_FILES.items()}
    for key, path in paths.items():
        if not path.is_file():
            errors.append(f"missing required output {key}: {path.name}")
        elif path.stat().st_size == 0:
            errors.append(f"required output is empty: {path.name}")
        elif path.stat().st_size > 100_000_000:
            errors.append(f"output exceeds 100 MB safety limit: {path.name}")
    if errors:
        return {"status": "invalid", "errors": errors, "warnings": warnings, "metrics": {}}

    database_metrics = validate_database(paths["database"], errors, warnings)
    parsed: dict[str, Any] = {}
    for key in ("source_manifest", "qc_report", "confidence_report", "anomalies", "anomaly_report", "samples", "run_summary"):
        try:
            parsed[key] = strict_json(paths[key])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{paths[key].name} is invalid JSON: {exc}")

    anomaly_count = 0
    sample_count = 0
    if "anomalies" in parsed:
        anomaly_count = validate_feature_collection(
            parsed["anomalies"], "anomalies.geojson", errors, allow_null_geometry=True, require_candidate_status=True
        )
    if "samples" in parsed:
        sample_count = validate_feature_collection(
            parsed["samples"], "samples.geojson", errors, allow_null_geometry=False
        )
    if sample_count > database_metrics["record_count"]:
        errors.append("samples.geojson contains more features than geochemistry.csv records")

    summary = parsed.get("run_summary")
    if isinstance(summary, dict):
        if summary.get("schema_version") != "global-geochemical-atlas-result-v1":
            errors.append("run_summary.json has an unsupported schema_version")
        outputs = summary.get("outputs")
        if not isinstance(outputs, dict):
            errors.append("run_summary.json outputs is not an object")
        else:
            expected = {key: path.name for key, path in paths.items() if key != "run_summary"}
            for key, filename in expected.items():
                if outputs.get(key) != filename:
                    errors.append(f"run_summary.json outputs.{key} must equal {filename}")
        metrics = summary.get("metrics", {})
        if metrics.get("record_count") != database_metrics["record_count"]:
            errors.append("run_summary record_count does not match geochemistry.csv")
        if metrics.get("candidate_anomaly_count") != anomaly_count:
            errors.append("run_summary candidate count does not match anomalies.geojson")
    else:
        errors.append("run_summary.json must contain an object")

    manifest = parsed.get("source_manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        errors.append("source_manifest.json must contain a sources array")
    confidence = parsed.get("confidence_report")
    if not isinstance(confidence, dict) or confidence.get("not_a_probability") is not True:
        errors.append("confidence_report.json must state that operational confidence is not a probability")
    if isinstance(manifest, dict) and isinstance(confidence, dict):
        if manifest.get("manifest_version") != "geochemical-source-manifest-v2":
            errors.append("source_manifest.json has an unsupported manifest_version")
        manifest_input = manifest.get("input")
        summary_input = summary.get("input") if isinstance(summary, dict) else None
        if not isinstance(manifest_input, dict) or not isinstance(summary_input, dict):
            errors.append("source manifest and run summary must contain input objects")
        elif any(manifest_input.get(field) != summary_input.get(field) for field in ("filename", "bytes", "record_count")):
            errors.append("source manifest input identity does not match run summary")
        binding = manifest.get("confidence_report")
        if not isinstance(binding, dict):
            errors.append("source_manifest.json must bind confidence_report.json")
        else:
            if binding.get("bytes") != paths["confidence_report"].stat().st_size:
                errors.append("source manifest confidence byte count does not match confidence_report.json")
            if binding.get("not_a_probability") is not True:
                errors.append("source manifest must preserve the confidence interpretation boundary")
            if binding.get("confidence_version") != confidence.get("confidence_version"):
                errors.append("source manifest confidence_version does not match confidence_report.json")
            run_metadata = confidence.get("run_metadata")
            if not isinstance(run_metadata, dict) or binding.get("input_identity") != run_metadata.get("input_identity"):
                errors.append("source manifest confidence input identity does not match D2 run metadata")
    anomaly_report = parsed.get("anomaly_report")
    if not isinstance(anomaly_report, dict) or anomaly_report.get("scientific_status") != "screening_baseline_only":
        errors.append("anomaly_report.json must declare screening_baseline_only")

    validate_html(paths["interactive_map"], errors)
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            **database_metrics,
            "sample_feature_count": sample_count,
            "candidate_feature_count": anomaly_count,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate all global geochemical atlas workflow outputs.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Workflow output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_dir(args.output_dir)
    except OSError as exc:
        report = {"status": "invalid", "errors": [str(exc)], "warnings": [], "metrics": {}}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
