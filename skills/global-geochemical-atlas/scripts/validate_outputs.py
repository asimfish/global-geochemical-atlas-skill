#!/usr/bin/env python3
"""Validate the stable outputs without third-party dependencies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REQUIRED_FILES = {
    "database": "geochemistry.csv",
    "source_manifest": "source_manifest.json",
    "record_evidence": "record_evidence.jsonl",
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
    "original_value_raw",
    "source_qualifier_raw",
    "original_unit",
    "value_qualifier",
    "normalized_value",
    "normalized_unit",
    "latitude",
    "longitude",
    "analytical_method",
    "digestion_or_extraction",
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def database_evidence_index(path: Path) -> dict[str, dict[str, str]]:
    fields = (
        "source_record_id", "source_id", "source_locator", "license", "analyte_reported",
        "dataset_title", "dataset_doi", "dataset_version", "source_file", "source_row", "file_sha256",
    )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            (row.get("record_id") or "").strip(): {field: (row.get(field) or "").strip() for field in fields}
            for row in csv.DictReader(handle)
            if (row.get("record_id") or "").strip()
        }


def validate_record_evidence(
    path: Path, canonical: dict[str, dict[str, str]], errors: list[str]
) -> int:
    record_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeError as exc:
        errors.append(f"record_evidence.jsonl is not valid UTF-8: {exc}")
        return 0
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"record_evidence.jsonl:{line_number} is invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"record_evidence.jsonl:{line_number} must be an object")
            continue
        record_id = value.get("record_id")
        if not isinstance(record_id, str) or not record_id:
            errors.append(f"record_evidence.jsonl:{line_number} has no record_id")
            continue
        if record_id in record_ids:
            errors.append(f"record_evidence.jsonl:{line_number} repeats record_id {record_id}")
        record_ids.add(record_id)
        for field in ("source_id", "source_locator", "license", "analyte_reported"):
            if value.get(field) in (None, ""):
                errors.append(f"record_evidence.jsonl:{line_number} lacks {field}")
            elif record_id in canonical and str(value[field]).strip() != canonical[record_id][field]:
                errors.append(f"record_evidence.jsonl:{line_number} conflicts with geochemistry.csv on {field}")
        comparable = {
            "source_record_id": "source_record_id", "dataset_title": "dataset_title",
            "dataset_doi": "dataset_doi", "dataset_version": "dataset_version",
            "source_file": "source_file", "source_row": "source_row", "source_file_sha256": "file_sha256",
        }
        for evidence_field, canonical_field in comparable.items():
            evidence_value = value.get(evidence_field)
            canonical_value = canonical.get(record_id, {}).get(canonical_field)
            if evidence_value not in (None, "") and canonical_value and str(evidence_value).strip() != canonical_value:
                errors.append(
                    f"record_evidence.jsonl:{line_number} conflicts with geochemistry.csv on {evidence_field}"
                )
        file_hash = value.get("source_file_sha256")
        if file_hash is not None and (not isinstance(file_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", file_hash)):
            errors.append(f"record_evidence.jsonl:{line_number} has invalid source_file_sha256")
        source_url = value.get("source_file_url")
        if source_url is not None and (not isinstance(source_url, str) or not source_url.startswith("https://")):
            errors.append(f"record_evidence.jsonl:{line_number} has invalid source_file_url")
    if record_ids != set(canonical):
        errors.append("record_evidence.jsonl record IDs do not exactly match geochemistry.csv")
    return len(record_ids)


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
    for block_id in ("anomalies-data", "basemap-data", "context-data"):
        if f'<script id="{block_id}" type="application/json">' not in text:
            errors.append(f"interactive_map.html does not embed the {block_id} block")
    if re.search(r"<script\b[^>]*\bsrc\s*=", text, re.IGNORECASE):
        errors.append("interactive_map.html contains an external script dependency")
    if re.search(r"<link\b[^>]*\bhref\s*=\s*['\"]https?://", text, re.IGNORECASE):
        errors.append("interactive_map.html contains an external stylesheet dependency")
    if "候选异常不代表污染" not in text:
        errors.append("interactive_map.html omits the causal interpretation boundary")
    if "d3-interactive-atlas-v3" not in text or "ALL DATA" not in text:
        errors.append("interactive_map.html omits the D3 map version or all-data default view")
    if "Natural Earth 1:110m" not in text or "public domain" not in text:
        errors.append("interactive_map.html omits offline basemap provenance")
    for marker in (
        'id="region"',
        'id="mapMode"',
        'id="colorMode"',
        'id="comboX"',
        'id="comboY"',
        'id="openAnomalyRegions"',
        "visual_aggregation_only",
        "样点密度热力图",
        "showAnomalyRegion",
    ):
        if marker not in text:
            errors.append(f"interactive_map.html omits required D3 v3 capability: {marker}")


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
    canonical_evidence = database_evidence_index(paths["database"])
    evidence_count = validate_record_evidence(paths["record_evidence"], canonical_evidence, errors)
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
        elif manifest_input.get("sha256") != summary_input.get("sha256"):
            errors.append("source manifest input hash does not match run summary")
        if isinstance(summary_input, dict):
            if manifest.get("data_mode") != summary_input.get("data_mode"):
                errors.append("source manifest data_mode does not match run summary")
            if manifest.get("not_for_scientific_interpretation") != summary_input.get(
                "not_for_scientific_interpretation"
            ):
                errors.append("source manifest scientific-interpretation boundary does not match run summary")
        binding = manifest.get("confidence_report")
        if not isinstance(binding, dict):
            errors.append("source_manifest.json must bind confidence_report.json")
        else:
            if binding.get("sha256") != sha256_file(paths["confidence_report"]):
                errors.append("source manifest confidence hash does not match confidence_report.json")
            if binding.get("not_a_probability") is not True:
                errors.append("source manifest must preserve the confidence interpretation boundary")
            if binding.get("confidence_version") != confidence.get("confidence_version"):
                errors.append("source manifest confidence_version does not match confidence_report.json")
            run_metadata = confidence.get("run_metadata")
            if not isinstance(run_metadata, dict) or binding.get("input_sha256") != run_metadata.get("input_sha256"):
                errors.append("source manifest confidence input hash does not match D2 run metadata")
        evidence_binding = manifest.get("record_evidence")
        if not isinstance(evidence_binding, dict):
            errors.append("source_manifest.json must bind record_evidence.jsonl")
        else:
            if evidence_binding.get("filename") != paths["record_evidence"].name:
                errors.append("source manifest record evidence filename is invalid")
            if evidence_binding.get("sha256") != sha256_file(paths["record_evidence"]):
                errors.append("source manifest record evidence hash does not match record_evidence.jsonl")
            if evidence_binding.get("record_count") != evidence_count:
                errors.append("source manifest record evidence count does not match record_evidence.jsonl")
            if evidence_binding.get("exact_record_id_match") is not True:
                errors.append("source manifest must declare exact record evidence linkage")
            if evidence_binding.get("schema_version") != "geochemical-record-evidence-v1":
                errors.append("source manifest has an unsupported record evidence schema_version")
            evidence_level = evidence_binding.get("evidence_level")
            if evidence_level not in {
                "source_declared_in_input", "validated_record_evidence", "verified_record_evidence"
            }:
                errors.append("source manifest has an unsupported evidence_level")
            coverage = manifest.get("coverage")
            if not isinstance(coverage, dict):
                errors.append("source manifest must contain evidence coverage")
            elif evidence_level == "verified_record_evidence":
                if (
                    coverage.get("records_with_verified_evidence") != evidence_count
                    or coverage.get("verified_evidence_rate") != 1.0
                    or evidence_binding.get("acquisition_manifest") is None
                ):
                    errors.append("verified evidence coverage is inconsistent with the acquisition binding")
            elif (
                coverage.get("records_with_verified_evidence") != 0
                or coverage.get("verified_evidence_rate") != 0.0
            ):
                errors.append("unverified evidence must not contribute to verified coverage")
    anomaly_report = parsed.get("anomaly_report")
    if not isinstance(anomaly_report, dict) or anomaly_report.get("scientific_status") != "screening_baseline_only":
        errors.append("anomaly_report.json must declare screening_baseline_only")
    elif anomaly_report.get("interface_version") != "d2-interface-v2":
        errors.append("anomaly_report.json has an unsupported interface_version")
    elif anomaly_report.get("method_version") != "d2-robust-mad-v2":
        errors.append("anomaly_report.json has an unsupported method_version")
    anomalies = parsed.get("anomalies")
    if isinstance(anomalies, dict):
        if anomalies.get("interface_version") != "d2-interface-v2":
            errors.append("anomalies.geojson has an unsupported interface_version")
        if anomalies.get("method_version") != "d2-robust-mad-v2":
            errors.append("anomalies.geojson has an unsupported method_version")
        for index, feature in enumerate(anomalies.get("features", [])):
            properties = feature.get("properties") if isinstance(feature, dict) else None
            if not isinstance(properties, dict) or properties.get("method_version") != "d2-robust-mad-v2":
                errors.append(f"anomalies.geojson feature {index} has an unsupported method_version")

    validate_html(paths["interactive_map"], errors)
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            **database_metrics,
            "record_evidence_count": evidence_count,
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
