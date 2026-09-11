#!/usr/bin/env python3
"""Validate the stable outputs without third-party dependencies."""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

REQUIRED_FILES = {
    "database": "geochemistry.csv",
    "source_manifest": "source_manifest.json",
    "record_evidence": "record_evidence.jsonl",
    "qc_report": "qc_report.json",
    "confidence_report": "confidence_report.json",
    "sources_and_confidence": "sources_and_confidence.json",
    "anomalies": "anomalies.geojson",
    "anomaly_report": "anomaly_report.json",
    "anomaly_provenance": "anomaly_provenance.json",
    "batch_acceptance": "batch_acceptance.csv",
    "batch_qc_report": "batch_qc_report.json",
    "anomaly_regions": "anomaly_regions.geojson",
    "spatial_anomaly_report": "spatial_anomaly_report.json",
    "samples": "samples.geojson",
    "interactive_map": "interactive_map.html",
    "temporal_map": "temporal_map.html",
    "iteration_backlog": "iteration_backlog.csv",
    "run_summary": "run_summary.json",
}

ITERATION_BACKLOG_COLUMNS = {
    "item_id",
    "record_id",
    "source_id",
    "stage_owner",
    "severity",
    "status",
    "issue_code",
    "field",
    "observed_value",
    "detail",
    "recommended_action",
    "auto_recheck",
}

REQUIRED_DATABASE_COLUMNS = {
    "record_id",
    "sample_id",
    "analysis_batch_id",
    "batch_qc_status",
    "batch_qc_disposition",
    "element_or_analyte",
    "medium",
    "measurement_basis",
    "sample_type_raw",
    "sample_type",
    "sample_type_mapping_status",
    "original_value_raw",
    "source_qualifier_raw",
    "original_unit",
    "value_qualifier",
    "normalized_value",
    "normalized_unit",
    "latitude",
    "longitude",
    "coordinate_evidence_scope",
    "coordinate_uncertainty_m",
    "coordinate_representation_resolution_m",
    "coordinate_representation_resolution_basis",
    "coordinate_accuracy_evidence_status",
    "coordinate_policy_id",
    "coordinate_policy_version",
    "coordinate_policy_url",
    "coordinate_policy_sha256",
    "analytical_method",
    "method_missing_reason",
    "method_source_locator",
    "method_scope",
    "digestion_or_extraction",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "citation_scope",
    "source_id",
    "source_locator",
    "official_source_url",
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


def valid_web_url(value: Any) -> bool:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def canonical_binding_url(value: Any) -> str:
    """Return the comparison key used by provenance URL binding gates.

    DOI paths are identifiers rather than ordinary web paths.  Publishers and
    serializers may represent reserved characters such as ``<`` and ``>``
    either literally or percent-encoded.  Decode and case-fold *only* DOI
    identifiers; every non-DOI URL keeps exact string semantics so this helper
    cannot turn a permissive URL normalizer into a provenance bypass.
    """

    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text
    if parsed.scheme.casefold() not in {"http", "https"}:
        return text
    if (parsed.hostname or "").casefold() not in {"doi.org", "dx.doi.org"}:
        return text
    identifier = unquote(parsed.path.lstrip("/")).strip().casefold()
    if not re.fullmatch(r"10\.\d{4,9}/\S+", identifier, flags=re.IGNORECASE):
        return text
    return f"https://doi.org/{identifier}"


def validate_database(
    path: Path, errors: list[str], warnings: list[str]
) -> dict[str, int]:
    metrics = {
        "record_count": 0,
        "source_locator_missing": 0,
        "official_source_url_missing": 0,
        "invalid_official_source_url": 0,
        "method_evidence_unaccounted": 0,
        "method_source_locator_missing": 0,
        "coordinate_accuracy_evidence_unaccounted": 0,
        "invalid_json_cells": 0,
    }
    coordinate_accuracy_statuses = {
        "source_reported_uncertainty",
        "not_reported",
        "not_applicable_no_canonical_coordinate",
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_DATABASE_COLUMNS - headers)
        if missing:
            errors.append(f"geochemistry.csv missing columns: {', '.join(missing)}")
        record_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            metrics["record_count"] += 1
            record_id = (row.get("record_id") or "").strip()
            if not record_id:
                errors.append(f"geochemistry.csv:{line_number} has no record_id")
            elif record_id in record_ids:
                errors.append(
                    f"geochemistry.csv:{line_number} repeats record_id {record_id}"
                )
            record_ids.add(record_id)
            if not (row.get("source_locator") or "").strip():
                metrics["source_locator_missing"] += 1
            official_source_url = (row.get("official_source_url") or "").strip()
            if not official_source_url:
                metrics["official_source_url_missing"] += 1
            elif not valid_web_url(official_source_url):
                metrics["invalid_official_source_url"] += 1
                errors.append(
                    f"geochemistry.csv:{line_number} has invalid official_source_url"
                )
            analytical_method = (row.get("analytical_method") or "").strip()
            method_missing_reason = (row.get("method_missing_reason") or "").strip()
            method_source_locator = (row.get("method_source_locator") or "").strip()
            if analytical_method:
                if method_missing_reason:
                    errors.append(
                        f"geochemistry.csv:{line_number} reports both analytical_method and method_missing_reason"
                    )
                if not method_source_locator:
                    metrics["method_source_locator_missing"] += 1
            elif not method_missing_reason:
                metrics["method_evidence_unaccounted"] += 1
            accuracy_status = (
                row.get("coordinate_accuracy_evidence_status") or ""
            ).strip()
            uncertainty = (row.get("coordinate_uncertainty_m") or "").strip()
            if accuracy_status not in coordinate_accuracy_statuses:
                metrics["coordinate_accuracy_evidence_unaccounted"] += 1
            elif accuracy_status == "source_reported_uncertainty" and not uncertainty:
                metrics["coordinate_accuracy_evidence_unaccounted"] += 1
                errors.append(
                    f"geochemistry.csv:{line_number} claims source-reported coordinate uncertainty without a value"
                )
            for column, expected in (
                ("qc_flags", list),
                ("operational_confidence", dict),
            ):
                try:
                    value = json.loads(row.get(column) or "null")
                except json.JSONDecodeError:
                    metrics["invalid_json_cells"] += 1
                    errors.append(
                        f"geochemistry.csv:{line_number} has invalid {column} JSON"
                    )
                    continue
                if not isinstance(value, expected):
                    metrics["invalid_json_cells"] += 1
                    errors.append(
                        f"geochemistry.csv:{line_number} has wrong {column} type"
                    )
    if metrics["record_count"] == 0:
        errors.append("geochemistry.csv contains no records")
    if metrics["source_locator_missing"]:
        warnings.append(
            f"{metrics['source_locator_missing']} record(s) lack source_locator"
        )
    if metrics["official_source_url_missing"]:
        warnings.append(
            f"{metrics['official_source_url_missing']} record(s) lack official_source_url"
        )
    if metrics["method_evidence_unaccounted"]:
        warnings.append(
            f"{metrics['method_evidence_unaccounted']} record(s) have neither analytical_method nor method_missing_reason"
        )
    if metrics["method_source_locator_missing"]:
        warnings.append(
            f"{metrics['method_source_locator_missing']} record(s) report a method without method_source_locator"
        )
    if metrics["coordinate_accuracy_evidence_unaccounted"]:
        warnings.append(
            f"{metrics['coordinate_accuracy_evidence_unaccounted']} record(s) do not explicitly account for coordinate accuracy evidence"
        )
    return metrics


def enforce_research_evidence_contract(
    data_mode: Any,
    metrics: Mapping[str, int],
    errors: list[str],
    *,
    synthetic_data_present: bool = False,
) -> None:
    """Fail closed for every real-data output with broken evidence debt.

    Only a package explicitly marked synthetic may omit external evidence.
    Hash-pinned real-data fixtures remain real observations and therefore must
    satisfy the same locator, URL, method-accounting and coordinate-accounting
    requirements as online or cached runs.
    """

    if data_mode == "synthetic_fixture" or synthetic_data_present:
        return
    requirements = {
        "source_locator_missing": "real-data records lack an exact source_locator",
        "official_source_url_missing": "real-data records lack a clickable official source URL or DOI",
        "method_evidence_unaccounted": (
            "real-data records have neither an analytical method nor an explicit source-not-reported reason"
        ),
        "method_source_locator_missing": "reported analytical methods lack a method_source_locator",
        "coordinate_accuracy_evidence_unaccounted": (
            "research records do not explicitly distinguish reported coordinate uncertainty from not reported"
        ),
    }
    for metric, message in requirements.items():
        count = int(metrics.get(metric, 0))
        if count:
            errors.append(f"{count} {message}")


def validate_iteration_backlog(
    path: Path, canonical_ids: set[str], errors: list[str]
) -> int:
    item_ids: set[str] = set()
    count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = sorted(ITERATION_BACKLOG_COLUMNS - set(reader.fieldnames or []))
        if missing:
            errors.append(
                "iteration_backlog.csv missing columns: " + ", ".join(missing)
            )
            return 0
        for line_number, row in enumerate(reader, start=2):
            count += 1
            item_id = (row.get("item_id") or "").strip()
            record_id = (row.get("record_id") or "").strip()
            if not item_id or item_id in item_ids:
                errors.append(
                    f"iteration_backlog.csv:{line_number} has missing or duplicate item_id"
                )
            item_ids.add(item_id)
            if record_id not in canonical_ids:
                errors.append(
                    f"iteration_backlog.csv:{line_number} references unknown record_id {record_id}"
                )
            if row.get("stage_owner") not in {"D1", "D2"}:
                errors.append(
                    f"iteration_backlog.csv:{line_number} has invalid stage_owner"
                )
            if row.get("status") not in {
                "action_required",
                "review_required",
                "scientific_limit",
            }:
                errors.append(f"iteration_backlog.csv:{line_number} has invalid status")
    return count


def validate_batch_acceptance(
    path: Path, errors: list[str]
) -> tuple[int, int, dict[str, bool]]:
    required = {
        "batch_id",
        "crm_recovery_percent",
        "crm_pass",
        "blank_value",
        "blank_pass",
        "duplicate_rpd_percent",
        "duplicate_pass",
        "batch_pass",
        "disposition",
    }
    count = 0
    passed = 0
    batch_ids: set[str] = set()
    decisions: dict[str, bool] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            errors.append("batch_acceptance.csv missing columns: " + ", ".join(missing))
            return 0, 0, {}
        for line_number, row in enumerate(reader, start=2):
            count += 1
            batch_id = (row.get("batch_id") or "").strip()
            if not batch_id or batch_id in batch_ids:
                errors.append(
                    f"batch_acceptance.csv:{line_number} has missing or duplicate batch_id"
                )
            batch_ids.add(batch_id)
            for field in ("crm_pass", "blank_pass", "duplicate_pass", "batch_pass"):
                if row.get(field) not in {"true", "false"}:
                    errors.append(
                        f"batch_acceptance.csv:{line_number} has invalid {field}"
                    )
            batch_pass = row.get("batch_pass") == "true"
            checks_pass = all(
                row.get(field) == "true"
                for field in ("crm_pass", "blank_pass", "duplicate_pass")
            )
            if batch_pass != checks_pass:
                errors.append(
                    f"batch_acceptance.csv:{line_number} violates all-checks-must-pass"
                )
            expected = (
                "accept_for_scientific_analysis"
                if batch_pass
                else "exclude_batch_and_investigate"
            )
            if row.get("disposition") != expected:
                errors.append(
                    f"batch_acceptance.csv:{line_number} has inconsistent disposition"
                )
            decisions[batch_id] = batch_pass
            passed += int(batch_pass)
    return count, passed, decisions


def validate_database_batch_gate(
    path: Path,
    report_status: str | None,
    decisions: Mapping[str, bool],
    errors: list[str],
) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            batch_id = (row.get("analysis_batch_id") or "").strip()
            status = (row.get("batch_qc_status") or "").strip()
            disposition = (row.get("batch_qc_disposition") or "").strip()
            if report_status == "not_supplied":
                expected_status, expected_disposition = "not_supplied", ""
            elif not batch_id or batch_id not in decisions:
                expected_status, expected_disposition = (
                    "incomplete",
                    "exclude_batch_and_investigate",
                )
            elif decisions[batch_id]:
                expected_status, expected_disposition = (
                    "pass",
                    "accept_for_scientific_analysis",
                )
            else:
                expected_status, expected_disposition = (
                    "fail",
                    "exclude_batch_and_investigate",
                )
            if (status, disposition) != (expected_status, expected_disposition):
                errors.append(
                    f"geochemistry.csv:{line_number} conflicts with the batch acceptance gate"
                )


def database_evidence_index(path: Path) -> dict[str, dict[str, str]]:
    fields = (
        "source_record_id",
        "source_id",
        "source_locator",
        "license",
        "analyte_reported",
        "dataset_title",
        "dataset_doi",
        "dataset_version",
        "source_file",
        "source_row",
        "file_sha256",
        "official_source_url",
    )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            (row.get("record_id") or "").strip(): {
                field: (row.get(field) or "").strip() for field in fields
            }
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
            errors.append(
                f"record_evidence.jsonl:{line_number} repeats record_id {record_id}"
            )
        record_ids.add(record_id)
        for field in ("source_id", "source_locator", "license", "analyte_reported"):
            if value.get(field) in (None, ""):
                errors.append(f"record_evidence.jsonl:{line_number} lacks {field}")
            elif (
                record_id in canonical
                and str(value[field]).strip() != canonical[record_id][field]
            ):
                errors.append(
                    f"record_evidence.jsonl:{line_number} conflicts with geochemistry.csv on {field}"
                )
        comparable = {
            "source_record_id": "source_record_id",
            "dataset_title": "dataset_title",
            "dataset_doi": "dataset_doi",
            "dataset_version": "dataset_version",
            "source_file": "source_file",
            "source_row": "source_row",
            "source_file_sha256": "file_sha256",
        }
        for evidence_field, canonical_field in comparable.items():
            evidence_value = value.get(evidence_field)
            canonical_value = canonical.get(record_id, {}).get(canonical_field)
            if (
                evidence_value not in (None, "")
                and canonical_value
                and str(evidence_value).strip() != canonical_value
            ):
                errors.append(
                    f"record_evidence.jsonl:{line_number} conflicts with geochemistry.csv on {evidence_field}"
                )
        canonical_official_url = canonical.get(record_id, {}).get("official_source_url")
        evidence_official_url = value.get("official_source_url") or value.get(
            "source_file_url"
        )
        if canonical_official_url and (
            evidence_official_url in (None, "")
            or str(evidence_official_url).strip() != canonical_official_url
        ):
            errors.append(
                f"record_evidence.jsonl:{line_number} does not bind geochemistry.csv official_source_url"
            )
        file_hash = value.get("source_file_sha256")
        if file_hash is not None and (
            not isinstance(file_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", file_hash)
        ):
            errors.append(
                f"record_evidence.jsonl:{line_number} has invalid source_file_sha256"
            )
        source_url = value.get("source_file_url")
        source_url_safe = isinstance(source_url, str) and (
            source_url.startswith("https://")
            or (
                source_url.startswith("http://weppi.gtk.fi/")
                and isinstance(file_hash, str)
                and re.fullmatch(r"[0-9a-f]{64}", file_hash) is not None
            )
        )
        if source_url is not None and not source_url_safe:
            errors.append(
                f"record_evidence.jsonl:{line_number} has invalid source_file_url"
            )
    if record_ids != set(canonical):
        errors.append(
            "record_evidence.jsonl record IDs do not exactly match geochemistry.csv"
        )
    return len(record_ids)


def validate_database_source_bindings(
    canonical: Mapping[str, Mapping[str, str]],
    manifest: Mapping[str, Any],
    errors: list[str],
) -> None:
    """Cross-check every canonical row against its declared source aggregate.

    The record sidecar proves row identity, while this gate independently
    prevents a valid row from being attached to the wrong dataset title,
    version, licence, file hash, or official URL in ``source_manifest.json``.
    Report aggregate counts so a large bad import cannot create an unbounded
    in-memory error list.
    """

    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list):
        return
    sources = {
        str(item.get("source_id")): item
        for item in raw_sources
        if isinstance(item, Mapping) and item.get("source_id")
    }
    mismatch_counts: Counter[tuple[str, str]] = Counter()

    def allowed_doi_urls(source: Mapping[str, Any]) -> set[str]:
        urls: set[str] = set()
        for raw_doi in list(source.get("dataset_dois") or []) + list(
            source.get("article_dois") or []
        ):
            doi = str(raw_doi or "").strip()
            if doi.casefold().startswith("https://doi.org/"):
                urls.add(doi)
            elif doi.casefold().startswith("doi:"):
                urls.add(f"https://doi.org/{doi[4:].strip()}")
            elif re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.IGNORECASE):
                urls.add(f"https://doi.org/{doi}")
        return urls

    for row in canonical.values():
        source_id = str(row.get("source_id") or "")
        source = sources.get(source_id)
        if source is None:
            mismatch_counts[("unknown_source_id", source_id or "<empty>")] += 1
            continue
        synthetic_source = (
            manifest.get("synthetic_data_present") is True
            and source.get("evidence_type") == "synthetic_demo"
        )
        scalar_lists = {
            "dataset_title": "dataset_titles",
            "dataset_doi": "dataset_dois",
            "dataset_version": "dataset_versions",
            "license": "licenses",
        }
        for row_field, manifest_field in scalar_lists.items():
            value = str(row.get(row_field) or "").strip()
            allowed = {
                str(item).strip()
                for item in source.get(manifest_field) or []
                if str(item).strip()
            }
            optional_blank = (
                not value
                and not allowed
                and (row_field == "dataset_doi" or synthetic_source)
            )
            if not optional_blank and (not value or value not in allowed):
                mismatch_counts[(f"{row_field}_mismatch", source_id)] += 1

        source_file = str(row.get("source_file") or "").strip()
        file_hash = str(row.get("file_sha256") or "").strip()
        source_files = {
            str(item.get("filename") or "").strip(): item
            for item in source.get("source_files") or []
            if isinstance(item, Mapping) and str(item.get("filename") or "").strip()
        }
        file_entry = source_files.get(source_file)
        if not source_file and not source_files and synthetic_source:
            pass
        elif file_entry is None:
            mismatch_counts[("source_file_mismatch", source_id)] += 1
        elif file_hash != str(file_entry.get("sha256") or "").strip():
            mismatch_counts[("source_file_sha256_mismatch", source_id)] += 1

        official_url = str(row.get("official_source_url") or "").strip()
        if official_url:
            allowed_urls = {
                str(url)
                for url in source.get("official_source_urls") or []
                if valid_web_url(url)
            }
            allowed_urls.update(
                str(item.get("url"))
                for item in source.get("source_files") or []
                if isinstance(item, Mapping) and valid_web_url(item.get("url"))
            )
            allowed_urls.update(allowed_doi_urls(source))
            if canonical_binding_url(official_url) not in {
                canonical_binding_url(url) for url in allowed_urls
            }:
                mismatch_counts[("official_source_url_mismatch", source_id)] += 1

    for (kind, source_id), count in sorted(mismatch_counts.items()):
        errors.append(
            f"{count} geochemistry record(s) have {kind} against source_manifest.json "
            f"for {source_id}"
        )


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
        elif (
            not isinstance(geometry, dict)
            or geometry.get("type") != "Point"
            or not valid_coordinate_pair(geometry.get("coordinates"))
        ):
            errors.append(f"{name}.features[{index}] has invalid Point geometry")
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            errors.append(f"{name}.features[{index}] has invalid properties")
        elif (
            require_candidate_status and properties.get("status") != "candidate_anomaly"
        ):
            errors.append(
                f"{name}.features[{index}] overstates or omits candidate_anomaly status"
            )
    return len(features)


def validate_anomaly_regions(value: Any, errors: list[str]) -> int:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        errors.append("anomaly_regions.geojson is not a GeoJSON FeatureCollection")
        return 0
    if (
        value.get("interface_version") != "d2-interface-v2"
        or value.get("method_version") != "d2-spatial-hypergeometric-fdr-v1"
    ):
        errors.append(
            "anomaly_regions.geojson has an unsupported interface or method version"
        )
    features = value.get("features")
    if not isinstance(features, list):
        errors.append("anomaly_regions.geojson.features is not an array")
        return 0
    for index, feature in enumerate(features):
        geometry = feature.get("geometry") if isinstance(feature, dict) else None
        properties = feature.get("properties") if isinstance(feature, dict) else None
        rings = geometry.get("coordinates") if isinstance(geometry, dict) else None
        if (
            geometry is None
            or geometry.get("type") != "Polygon"
            or not isinstance(rings, list)
            or not rings
        ):
            errors.append(
                f"anomaly_regions.geojson feature {index} has invalid Polygon geometry"
            )
            continue
        ring = rings[0]
        if (
            not isinstance(ring, list)
            or len(ring) < 4
            or ring[0] != ring[-1]
            or any(not valid_coordinate_pair(point) for point in ring)
        ):
            errors.append(f"anomaly_regions.geojson feature {index} has invalid ring")
        if (
            not isinstance(properties, dict)
            or properties.get("status") != "candidate_anomaly_region"
            or properties.get("scientific_status") != "screening_candidate_only"
            or properties.get("method_version") != "d2-spatial-hypergeometric-fdr-v1"
            or properties.get("boundary_model")
            != "fixed_wgs84_grid_cell_not_geologic_boundary"
            or not isinstance(properties.get("p_value"), (int, float))
            or not 0 <= float(properties["p_value"]) <= 1
            or not isinstance(properties.get("fdr_q_value"), (int, float))
            or not 0 <= float(properties["fdr_q_value"]) <= 1
        ):
            errors.append(
                f"anomaly_regions.geojson feature {index} overstates or omits screening status"
            )
    return len(features)


def validate_temporal_html(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if '<script id="temporal-payload" type="application/json">' not in text:
        errors.append("temporal_map.html does not embed the temporal payload block")
    if '"temporal-atlas-payload-v2"' not in text:
        errors.append("temporal_map.html omits the temporal payload schema version")
    if '"source_time_semantics"' not in text or '"dated_tiers"' not in text:
        errors.append(
            "temporal_map.html omits the per-source sampling-time semantics and dated tiers"
        )
    if 'id="timeSemanticsTable"' not in text:
        errors.append("temporal_map.html omits the sampling-time reason table")
    if '<script id="basemap-data" type="application/json">' not in text:
        errors.append("temporal_map.html does not embed the offline basemap block")
    if re.search(r"<script\b[^>]*\bsrc\s*=", text, re.IGNORECASE):
        errors.append("temporal_map.html contains an external script dependency")
    if re.search(r"<link\b[^>]*\bhref\s*=\s*['\"]https?://", text, re.IGNORECASE):
        errors.append("temporal_map.html contains an external stylesheet dependency")
    if "publisher_reported" not in text or "publisher_not_reported" not in text:
        errors.append(
            "temporal_map.html omits the honest sampling-time coverage statement"
        )
    if "Natural Earth" not in text:
        errors.append("temporal_map.html omits offline basemap provenance")


def validate_html(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8")
    if '<script id="samples-data" type="application/json">' not in text:
        errors.append("interactive_map.html does not embed the samples data block")
    for block_id in (
        "anomalies-data",
        "basemap-data",
        "boundaries-data",
        "context-data",
    ):
        if f'<script id="{block_id}" type="application/json">' not in text:
            errors.append(f"interactive_map.html does not embed the {block_id} block")
    if re.search(r"<script\b[^>]*\bsrc\s*=", text, re.IGNORECASE):
        errors.append("interactive_map.html contains an external script dependency")
    if re.search(r"<link\b[^>]*\bhref\s*=\s*['\"]https?://", text, re.IGNORECASE):
        errors.append("interactive_map.html contains an external stylesheet dependency")
    if "候选异常不代表污染" not in text:
        errors.append("interactive_map.html omits the causal interpretation boundary")
    if "d3-interactive-atlas-v3" not in text or "ALL DATA" not in text:
        errors.append(
            "interactive_map.html omits the D3 map version or all-data default view"
        )
    if "Natural Earth 1:110m" not in text or "public domain" not in text:
        errors.append("interactive_map.html omits offline basemap provenance")
    if "ai4s-natural-earth-admin0-v2" not in text or "pointInCountry" not in text:
        errors.append(
            "interactive_map.html omits strict offline country boundary support"
        )
    for marker in (
        'id="region"',
        'id="mapMode"',
        'id="colorMode"',
        'id="comboX"',
        'id="comboY"',
        'id="comboRegionSelect"',
        'id="comboCustomBounds"',
        'id="applyComboBounds"',
        "applyCustomBounds",
        'id="exportComparisonProfile"',
        "comparisonProfile",
        "导出可复现配置",
        'id="openAnomalyRegions"',
        "d3-domain-confidence-atlas-v5",
        'id="projectionMode"',
        'id="globe"',
        'id="statisticalRegionTable"',
        'id="anomalyDensityCanvas"',
        "spatial_anomaly_report.json",
        "样点密度热力图",
        "发布方未报告分析方法",
        "该结果比较同类样品的统计背景",
        "showAnomalyRegion",
        'id="deliverableCenter"',
        'id="taskContext"',
        "atlas-progressive-disclosure-v2",
        "d3-visual-question-contract-v1",
        "competition-geochemistry-v1",
        "可交互元素分布地图",
        "标准化地球化学数据库",
        "元素组合对比",
        "数据来源与置信度说明",
        "异常区域识别结果",
        'id="databaseView"',
        'id="databaseDistributionCanvas"',
        'id="databaseCoverageMatrix"',
        'id="databaseBoxCanvas"',
        "d3-database-visual-summary-v1",
        'id="databaseSearch"',
        'id="confidenceSummary"',
        'id="confidenceComponents"',
        'href="geochemistry.csv"',
        'href="confidence_report.json"',
        'href="sources_and_confidence.json"',
        "不是正确概率",
        'id="backView"',
        'id="zoomIn"',
        'id="zoomOut"',
        "comboQuadrants",
        "threshold-values",
        "rememberView",
        "basisLabel",
        'id="databaseEditor"',
        "geochemistry-research-patch-v1",
        'id="sourceTableBody"',
        'id="anomalyInspector"',
        "anomaly-contrast",
        "comboConclusion",
        'id="temporalView"',
        'id="temporalFrame"',
        'id="temporal-document"',
        "loadTemporalView",
        'id="autoResearchView"',
        'id="autoResearchForm"',
        'id="exportAutoResearch"',
        "startAutoResearch",
        "/api/v1/research-runs",
        "静态模式没有创建后台任务",
    ):
        if marker not in text:
            errors.append(
                f"interactive_map.html omits required D3 v3 capability: {marker}"
            )
    if 'id="storyPreset"' in text or text.count('class="tabs"') != 1:
        errors.append(
            "interactive_map.html duplicates task navigation or story selection"
        )
    for informal_label in (
        ">看分布<",
        ">查记录<",
        ">比元素<",
        ">核来源<",
        ">懂异常<",
        ">修质量<",
    ):
        if informal_label in text:
            errors.append(
                f"interactive_map.html uses an informal primary navigation label: {informal_label}"
            )


def validate_temporal_embedding(
    interactive_path: Path, temporal_path: Path, errors: list[str]
) -> None:
    """Prove the first-class temporal view embeds the compatibility bytes."""

    text = interactive_path.read_text(encoding="utf-8")
    navigation = re.search(r'<nav class="tabs".*?</nav>', text, re.DOTALL)
    if navigation is None or 'data-view="temporalView"' not in navigation.group(0):
        errors.append("interactive_map.html lacks a temporal top-level view")
    elif re.search(
        r'<a\b[^>]*href="temporal_map\.html"', navigation.group(0), re.IGNORECASE
    ):
        errors.append(
            "interactive_map.html still uses temporal_map.html as primary navigation"
        )
    frame = re.search(r'<iframe\b[^>]*id="temporalFrame"[^>]*>', text, re.IGNORECASE)
    if frame is None:
        errors.append("interactive_map.html lacks the embedded temporal frame")
    elif re.search(r"\bsrc\s*=", frame.group(0), re.IGNORECASE):
        errors.append(
            "embedded temporal frame must use srcdoc and must not depend on src"
        )
    block = re.search(
        r'<script id="temporal-document" type="application/octet-stream">(.*?)</script>',
        text,
        re.DOTALL,
    )
    if block is None:
        errors.append("interactive_map.html lacks the embedded temporal document")
        return
    try:
        embedded = base64.b64decode(block.group(1).strip(), validate=True)
    except (ValueError, binascii.Error):
        errors.append("interactive_map.html temporal document is not valid base64")
        return
    if temporal_path.is_file() and embedded != temporal_path.read_bytes():
        errors.append(
            "interactive_map.html temporal view differs from temporal_map.html"
        )


def summary_outputs_for_validation(paths: Mapping[str, Path]) -> dict[str, str]:
    return {
        logical_name: path.name
        for logical_name, path in paths.items()
        if logical_name != "run_summary"
    }


def validate_dir(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    paths = {key: output_dir / filename for key, filename in REQUIRED_FILES.items()}
    for key, path in paths.items():
        if not path.is_file():
            errors.append(f"missing required output {key}: {path.name}")
        elif path.stat().st_size == 0:
            errors.append(f"required output is empty: {path.name}")
        elif path.stat().st_size > 600_000_000:
            errors.append(
                f"output exceeds the 600 MB bounded-research safety limit: {path.name}"
            )
    if errors:
        return {
            "status": "invalid",
            "errors": errors,
            "warnings": warnings,
            "metrics": {},
        }

    database_metrics = validate_database(paths["database"], errors, warnings)
    canonical_evidence = database_evidence_index(paths["database"])
    iteration_count = validate_iteration_backlog(
        paths["iteration_backlog"], set(canonical_evidence), errors
    )
    evidence_count = validate_record_evidence(
        paths["record_evidence"], canonical_evidence, errors
    )
    batch_count, passed_batch_count, batch_decisions = validate_batch_acceptance(
        paths["batch_acceptance"], errors
    )
    parsed: dict[str, Any] = {}
    for key in (
        "source_manifest",
        "qc_report",
        "confidence_report",
        "sources_and_confidence",
        "anomalies",
        "anomaly_report",
        "batch_qc_report",
        "anomaly_regions",
        "spatial_anomaly_report",
        "samples",
        "run_summary",
    ):
        try:
            parsed[key] = strict_json(paths[key])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{paths[key].name} is invalid JSON: {exc}")

    anomaly_count = 0
    sample_count = 0
    anomaly_region_count = 0
    if "anomalies" in parsed:
        anomaly_count = validate_feature_collection(
            parsed["anomalies"],
            "anomalies.geojson",
            errors,
            allow_null_geometry=True,
            require_candidate_status=True,
        )
    if "samples" in parsed:
        sample_count = validate_feature_collection(
            parsed["samples"], "samples.geojson", errors, allow_null_geometry=False
        )
    if "anomaly_regions" in parsed:
        anomaly_region_count = validate_anomaly_regions(
            parsed["anomaly_regions"], errors
        )
    if sample_count > database_metrics["record_count"]:
        errors.append(
            "samples.geojson contains more features than geochemistry.csv records"
        )

    summary = parsed.get("run_summary")
    if isinstance(summary, dict):
        if summary.get("schema_version") != "global-geochemical-atlas-result-v1":
            errors.append("run_summary.json has an unsupported schema_version")
        outputs = summary.get("outputs")
        if not isinstance(outputs, dict):
            errors.append("run_summary.json outputs is not an object")
        else:
            expected = {
                key: path.name for key, path in paths.items() if key != "run_summary"
            }
            for key, filename in expected.items():
                if outputs.get(key) != filename:
                    errors.append(
                        f"run_summary.json outputs.{key} must equal {filename}"
                    )
        metrics = summary.get("metrics", {})
        if metrics.get("record_count") != database_metrics["record_count"]:
            errors.append("run_summary record_count does not match geochemistry.csv")
        if metrics.get("candidate_anomaly_count") != anomaly_count:
            errors.append(
                "run_summary candidate count does not match anomalies.geojson"
            )
        if metrics.get("candidate_anomaly_region_count") != anomaly_region_count:
            errors.append(
                "run_summary candidate-region count does not match anomaly_regions.geojson"
            )
        map_report = summary.get("map_report")
        template_path = (
            Path(__file__).resolve().parent.parent
            / "assets"
            / "interactive-atlas-v3.html"
        )
        if not isinstance(map_report, dict):
            errors.append("run_summary map_report is missing")
        else:
            spatial_scope = map_report.get("spatial_scope")
            scope_mode = (
                spatial_scope.get("mode") if isinstance(spatial_scope, dict) else None
            )
            expected_variant = None
            if scope_mode == "global":
                expected_variant = "global_globe"
            elif scope_mode == "regional":
                expected_variant = "regional_focus"
            if (
                map_report.get("template_contract_version")
                != "d3-domain-confidence-atlas-v5"
                or expected_variant is None
                or map_report.get("template_variant") != expected_variant
                or map_report.get("template_sha256") != sha256_file(template_path)
            ):
                errors.append("run_summary map template identity is invalid")
        transaction = summary.get("artifact_transaction")
        if (
            not isinstance(transaction, dict)
            or transaction.get("transaction_version")
            != "geochemical-workflow-artifact-transaction-v1"
            or transaction.get("state") != "committed"
            or transaction.get("commit_marker") != "run_summary.json"
        ):
            errors.append("run_summary artifact transaction is missing or uncommitted")
        else:
            transaction_artifacts = transaction.get("artifacts")
            if not isinstance(transaction_artifacts, dict):
                errors.append("run_summary artifact transaction has no artifact index")
            else:
                for logical_name, filename in summary_outputs_for_validation(
                    paths
                ).items():
                    binding = transaction_artifacts.get(logical_name)
                    path = paths[logical_name]
                    if (
                        not isinstance(binding, dict)
                        or binding.get("filename") != filename
                        or binding.get("bytes") != path.stat().st_size
                        or binding.get("sha256") != sha256_file(path)
                    ):
                        errors.append(
                            f"run_summary artifact transaction mismatch for {filename}"
                        )
    else:
        errors.append("run_summary.json must contain an object")

    manifest = parsed.get("source_manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), list):
        errors.append("source_manifest.json must contain a sources array")
    else:
        validate_database_source_bindings(canonical_evidence, manifest, errors)
        enforce_research_evidence_contract(
            manifest.get("data_mode"),
            database_metrics,
            errors,
            synthetic_data_present=manifest.get("synthetic_data_present") is True,
        )
    confidence = parsed.get("confidence_report")
    if (
        not isinstance(confidence, dict)
        or confidence.get("not_a_probability") is not True
    ):
        errors.append(
            "confidence_report.json must state that operational confidence is not a probability"
        )
    source_confidence = parsed.get("sources_and_confidence")
    dimensions = {
        "source_evidence",
        "analytical_readiness",
        "spatial_usability",
        "workflow_usability",
    }
    if (
        not isinstance(source_confidence, dict)
        or source_confidence.get("report_version") != "sources-and-confidence-v3"
        or source_confidence.get("single_quality_label_prohibited") is not True
    ):
        errors.append(
            "sources_and_confidence.json must preserve the four-dimensional interpretation boundary"
        )
    else:
        overall_counts = source_confidence.get("overall_dimension_band_counts")
        overall_means = source_confidence.get("overall_dimension_score_means")
        overall_workflow = source_confidence.get("overall_workflow_confidence")
        if (
            not isinstance(overall_means, dict)
            or set(overall_means) != dimensions
            or any(
                value is not None
                and (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not 0 <= value <= 1
                )
                for value in overall_means.values()
            )
        ):
            errors.append(
                "sources_and_confidence.json must report valid means for all four quality dimensions"
            )
        if (
            not isinstance(overall_workflow, dict)
            or overall_workflow.get("not_a_probability") is not True
            or overall_workflow.get("record_count") != database_metrics["record_count"]
            or overall_workflow.get("score_mean")
            != (
                overall_means.get("workflow_usability")
                if isinstance(overall_means, dict)
                else None
            )
        ):
            errors.append(
                "sources_and_confidence.json overall workflow confidence is invalid"
            )
        if not isinstance(overall_counts, dict) or set(overall_counts) != dimensions:
            errors.append(
                "sources_and_confidence.json must report all four quality dimensions"
            )
        else:
            for dimension, counts in overall_counts.items():
                if (
                    not isinstance(counts, dict)
                    or any(
                        band not in {"high", "medium", "low", "unknown"}
                        or not isinstance(count, int)
                        or isinstance(count, bool)
                        or count < 0
                        for band, count in counts.items()
                    )
                    or sum(counts.values()) != database_metrics["record_count"]
                ):
                    errors.append(
                        f"sources_and_confidence.json has invalid band counts for {dimension}"
                    )
        source_items = source_confidence.get("sources")
        valid_source_items = source_items if isinstance(source_items, list) else []
        metadata_completeness = source_confidence.get("metadata_completeness")
        if (
            not isinstance(metadata_completeness, dict)
            or metadata_completeness.get("record_count")
            != database_metrics["record_count"]
        ):
            errors.append(
                "sources_and_confidence.json metadata completeness does not match geochemistry.csv"
            )
        overall_absence = source_confidence.get("metadata_absence_accounting")
        overall_method_present = (
            metadata_completeness.get("analytical_method", {}).get("count")
            if isinstance(metadata_completeness, dict)
            else None
        )
        if (
            not isinstance(overall_absence, dict)
            or not isinstance(overall_method_present, int)
            or overall_absence.get("analytical_method", {}).get("record_count")
            != database_metrics["record_count"] - overall_method_present
            or overall_absence.get("analytical_method", {}).get("accounted_count")
            != database_metrics["record_count"] - overall_method_present
            or overall_absence.get("coordinate_accuracy", {}).get("record_count")
            != database_metrics["record_count"]
            or overall_absence.get("coordinate_accuracy", {}).get("accounted_count")
            != database_metrics["record_count"]
        ):
            errors.append(
                "sources_and_confidence.json overall metadata-absence accounting does not match geochemistry.csv"
            )
        if not isinstance(source_items, list):
            errors.append("sources_and_confidence.json sources must be an array")
        else:
            record_total = 0
            seen_source_ids: set[str] = set()
            for item in source_items:
                if not isinstance(item, dict):
                    errors.append(
                        "sources_and_confidence.json source entries must be objects"
                    )
                    continue
                source_id = item.get("source_id")
                source_record_count = item.get("record_count")
                source_sample_count = item.get("independent_sample_count")
                if (
                    not isinstance(source_id, str)
                    or not source_id
                    or source_id in seen_source_ids
                ):
                    errors.append(
                        "sources_and_confidence.json source_id values must be unique and non-empty"
                    )
                else:
                    seen_source_ids.add(source_id)
                if (
                    not isinstance(source_record_count, int)
                    or isinstance(source_record_count, bool)
                    or source_record_count < 0
                    or not isinstance(source_sample_count, int)
                    or isinstance(source_sample_count, bool)
                    or source_sample_count < 0
                    or source_sample_count > source_record_count
                ):
                    errors.append(
                        f"sources_and_confidence.json has invalid counts for {source_id}"
                    )
                else:
                    record_total += source_record_count
                band_counts = item.get("dimension_band_counts")
                dimension_means = item.get("dimension_score_means")
                if (
                    not isinstance(dimension_means, dict)
                    or set(dimension_means) != dimensions
                    or any(
                        value is not None
                        and (
                            not isinstance(value, (int, float))
                            or isinstance(value, bool)
                            or not 0 <= value <= 1
                        )
                        for value in dimension_means.values()
                    )
                ):
                    errors.append(
                        f"sources_and_confidence.json has invalid dimension means for {source_id}"
                    )
                if not isinstance(band_counts, dict) or set(band_counts) != dimensions:
                    errors.append(
                        f"sources_and_confidence.json lacks four-dimensional counts for {source_id}"
                    )
                elif isinstance(source_record_count, int):
                    for dimension, counts in band_counts.items():
                        if (
                            not isinstance(counts, dict)
                            or any(
                                band not in {"high", "medium", "low", "unknown"}
                                or not isinstance(count, int)
                                or isinstance(count, bool)
                                or count < 0
                                for band, count in counts.items()
                            )
                            or sum(
                                count
                                for count in counts.values()
                                if isinstance(count, int)
                                and not isinstance(count, bool)
                            )
                            != source_record_count
                        ):
                            errors.append(
                                "sources_and_confidence.json source band counts do not "
                                f"match records for {source_id}/{dimension}"
                            )
                official_links = item.get("official_links")
                provenance = item.get("record_provenance")
                if (
                    not isinstance(official_links, list)
                    or any(
                        not isinstance(link, dict)
                        or not isinstance(link.get("kind"), str)
                        or not isinstance(link.get("url"), str)
                        or not valid_web_url(link.get("url"))
                        for link in official_links
                    )
                    or not isinstance(provenance, dict)
                    or not isinstance(
                        provenance.get("official_linked_record_count"), int
                    )
                ):
                    errors.append(
                        f"sources_and_confidence.json has invalid official provenance links for {source_id}"
                    )
                elif isinstance(source_record_count, int):
                    linked_count = provenance["official_linked_record_count"]
                    metadata = item.get("metadata_completeness")
                    metadata_link_count = (
                        metadata.get("official_source_link", {}).get("count")
                        if isinstance(metadata, dict)
                        and isinstance(metadata.get("official_source_link"), dict)
                        else None
                    )
                    if (
                        linked_count < 0
                        or linked_count > source_record_count
                        or metadata_link_count != linked_count
                        or (linked_count > 0 and not official_links)
                    ):
                        errors.append(
                            "sources_and_confidence.json official-link record counts "
                            f"do not match metadata completeness for {source_id}"
                        )
                acquisition_times = item.get("acquisition_times")
                acquisition_time = item.get("acquisition_time")
                acquisition_status = item.get("acquisition_time_status")
                if (
                    not isinstance(acquisition_times, list)
                    or any(
                        not isinstance(value, str) or not value
                        for value in acquisition_times
                    )
                    or len(acquisition_times) != len(set(acquisition_times))
                    or (
                        acquisition_time is not None
                        and acquisition_time not in acquisition_times
                    )
                    or not isinstance(acquisition_status, str)
                    or not acquisition_status
                ):
                    errors.append(
                        f"sources_and_confidence.json has invalid acquisition-time evidence for {source_id}"
                    )
                absence = item.get("metadata_absence_accounting")
                if not isinstance(absence, dict):
                    errors.append(
                        f"sources_and_confidence.json lacks metadata-absence accounting for {source_id}"
                    )
                elif isinstance(source_record_count, int):
                    metadata = item.get("metadata_completeness")
                    method_present = (
                        metadata.get("analytical_method", {}).get("count")
                        if isinstance(metadata, dict)
                        else None
                    )
                    method_absence = absence.get("analytical_method")
                    coordinate_status = absence.get("coordinate_accuracy")
                    if (
                        not isinstance(method_present, int)
                        or not isinstance(method_absence, dict)
                        or method_absence.get("record_count")
                        != source_record_count - method_present
                        or method_absence.get("accounted_count")
                        != method_absence.get("record_count")
                        or not isinstance(coordinate_status, dict)
                        or coordinate_status.get("record_count") != source_record_count
                        or coordinate_status.get("accounted_count")
                        != source_record_count
                    ):
                        errors.append(
                            f"sources_and_confidence.json metadata-absence counts do not match records for {source_id}"
                        )
                    elif "unaccounted_in_input" in (
                        method_absence.get("counts") or {}
                    ) or "unaccounted_in_input" in (
                        coordinate_status.get("counts") or {}
                    ):
                        errors.append(
                            f"sources_and_confidence.json contains unaccounted metadata absence for {source_id}"
                        )
            if record_total != database_metrics["record_count"]:
                errors.append(
                    "sources_and_confidence.json source record counts do not match geochemistry.csv"
                )
        portfolio = source_confidence.get("source_portfolio")
        if (
            not isinstance(portfolio, dict)
            or portfolio.get("formal_included_source_count") != len(valid_source_items)
            or set(portfolio.get("formal_included_source_ids") or [])
            != {
                str(item.get("source_id"))
                for item in valid_source_items
                if isinstance(item, dict) and item.get("source_id")
            }
            or portfolio.get("routed_selected_source_count")
            != len(portfolio.get("selected_sources") or [])
            or portfolio.get("review_or_blocked_source_count")
            != len(portfolio.get("review_or_blocked_sources") or [])
        ):
            errors.append(
                "sources_and_confidence.json source portfolio is internally inconsistent"
            )
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
                errors.append(
                    "source manifest scientific-interpretation boundary does not match run summary"
                )
        binding = manifest.get("confidence_report")
        if not isinstance(binding, dict):
            errors.append("source_manifest.json must bind confidence_report.json")
        else:
            if binding.get("sha256") != sha256_file(paths["confidence_report"]):
                errors.append(
                    "source manifest confidence hash does not match confidence_report.json"
                )
            if binding.get("not_a_probability") is not True:
                errors.append(
                    "source manifest must preserve the confidence interpretation boundary"
                )
            if binding.get("confidence_version") != confidence.get(
                "confidence_version"
            ):
                errors.append(
                    "source manifest confidence_version does not match confidence_report.json"
                )
            run_metadata = confidence.get("run_metadata")
            if not isinstance(run_metadata, dict) or binding.get(
                "input_sha256"
            ) != run_metadata.get("input_sha256"):
                errors.append(
                    "source manifest confidence input hash does not match D2 run metadata"
                )
        evidence_binding = manifest.get("record_evidence")
        if not isinstance(evidence_binding, dict):
            errors.append("source_manifest.json must bind record_evidence.jsonl")
        else:
            if evidence_binding.get("filename") != paths["record_evidence"].name:
                errors.append("source manifest record evidence filename is invalid")
            if evidence_binding.get("sha256") != sha256_file(paths["record_evidence"]):
                errors.append(
                    "source manifest record evidence hash does not match record_evidence.jsonl"
                )
            if evidence_binding.get("record_count") != evidence_count:
                errors.append(
                    "source manifest record evidence count does not match record_evidence.jsonl"
                )
            if evidence_binding.get("exact_record_id_match") is not True:
                errors.append(
                    "source manifest must declare exact record evidence linkage"
                )
            if (
                evidence_binding.get("schema_version")
                != "geochemical-record-evidence-v1"
            ):
                errors.append(
                    "source manifest has an unsupported record evidence schema_version"
                )
            evidence_level = evidence_binding.get("evidence_level")
            if evidence_level not in {
                "source_declared_in_input",
                "validated_record_evidence",
                "verified_record_evidence",
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
                    errors.append(
                        "verified evidence coverage is inconsistent with the acquisition binding"
                    )
            elif (
                coverage.get("records_with_verified_evidence") != 0
                or coverage.get("verified_evidence_rate") != 0.0
            ):
                errors.append(
                    "unverified evidence must not contribute to verified coverage"
                )
        if isinstance(source_confidence, dict):
            if source_confidence.get("data_mode") != manifest.get("data_mode"):
                errors.append(
                    "sources_and_confidence.json data_mode does not match source_manifest.json"
                )
            source_ids = {
                str(item.get("source_id"))
                for item in manifest.get("sources", [])
                if isinstance(item, dict) and item.get("source_id")
            }
            confidence_source_ids = {
                str(item.get("source_id"))
                for item in source_confidence.get("sources", [])
                if isinstance(item, dict) and item.get("source_id")
            }
            if confidence_source_ids != source_ids:
                errors.append(
                    "sources_and_confidence.json source IDs do not match source_manifest.json"
                )
            manifest_sources = {
                str(item.get("source_id")): item
                for item in manifest.get("sources", [])
                if isinstance(item, dict) and item.get("source_id")
            }
            for item in source_confidence.get("sources", []):
                if not isinstance(item, dict):
                    continue
                source_id = str(item.get("source_id") or "")
                source_manifest = manifest_sources.get(source_id, {})
                allowed_urls = {
                    str(url)
                    for url in source_manifest.get("official_source_urls", [])
                    if valid_web_url(url)
                }
                allowed_urls.update(
                    str(source_file.get("url"))
                    for source_file in source_manifest.get("source_files", [])
                    if isinstance(source_file, dict)
                    and valid_web_url(source_file.get("url"))
                )
                for doi in list(source_manifest.get("dataset_dois", [])) + list(
                    source_manifest.get("article_dois", [])
                ):
                    doi_text = str(doi or "").strip()
                    if doi_text.casefold().startswith("https://doi.org/"):
                        allowed_urls.add(doi_text)
                    elif doi_text.casefold().startswith("doi:"):
                        allowed_urls.add(f"https://doi.org/{doi_text[4:].strip()}")
                    elif re.fullmatch(
                        r"10\.\d{4,9}/\S+", doi_text, flags=re.IGNORECASE
                    ):
                        allowed_urls.add(f"https://doi.org/{doi_text}")
                confidence_urls = {
                    str(link.get("url"))
                    for link in item.get("official_links", [])
                    if isinstance(link, dict) and valid_web_url(link.get("url"))
                }
                if not {canonical_binding_url(url) for url in confidence_urls}.issubset(
                    {canonical_binding_url(url) for url in allowed_urls}
                ):
                    errors.append(
                        "sources_and_confidence.json contains official links not bound "
                        f"by source_manifest.json for {source_id}"
                    )
    anomaly_report = parsed.get("anomaly_report")
    if (
        not isinstance(anomaly_report, dict)
        or anomaly_report.get("scientific_status") != "screening_baseline_only"
    ):
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
            properties = (
                feature.get("properties") if isinstance(feature, dict) else None
            )
            if (
                not isinstance(properties, dict)
                or properties.get("method_version") != "d2-robust-mad-v2"
            ):
                errors.append(
                    f"anomalies.geojson feature {index} has an unsupported method_version"
                )
    batch_report = parsed.get("batch_qc_report")
    if (
        not isinstance(batch_report, dict)
        or batch_report.get("schema_version") != "geochemical-batch-qc-report-v1"
    ):
        errors.append("batch_qc_report.json has an unsupported schema_version")
    elif batch_report.get("status") not in {"not_supplied", "evaluated"}:
        errors.append("batch_qc_report.json has an unsupported status")
    elif (
        batch_report.get("batch_count") != batch_count
        or batch_report.get("passed_batch_count") != passed_batch_count
        or batch_report.get("failed_or_incomplete_batch_count")
        != batch_count - passed_batch_count
    ):
        errors.append("batch_qc_report.json counts do not match batch_acceptance.csv")
    if isinstance(batch_report, dict):
        validate_database_batch_gate(
            paths["database"], batch_report.get("status"), batch_decisions, errors
        )
    spatial_report = parsed.get("spatial_anomaly_report")
    if (
        not isinstance(spatial_report, dict)
        or spatial_report.get("method_version") != "d2-spatial-hypergeometric-fdr-v1"
        or spatial_report.get("scientific_status") != "screening_candidate_regions_only"
        or spatial_report.get("point_candidate_method_version") != "d2-robust-mad-v2"
        or spatial_report.get("multiple_testing_method") != "Benjamini-Hochberg FDR"
        or not str(spatial_report.get("null_model") or "").startswith(
            "one-sided exact hypergeometric enrichment"
        )
        or not isinstance(spatial_report.get("hypothesis_count"), int)
        or spatial_report.get("hypothesis_count", -1) < anomaly_region_count
        or spatial_report.get("candidate_region_count") != anomaly_region_count
    ):
        errors.append(
            "spatial_anomaly_report.json is missing the screened-region contract"
        )

    qc_report = parsed.get("qc_report")
    if isinstance(batch_report, dict) and isinstance(qc_report, dict):
        batch_qc = qc_report.get("batch_qc")
        if (
            not isinstance(batch_qc, dict)
            or batch_qc.get("report_status") != batch_report.get("status")
            or batch_qc.get("passed_batch_count") != passed_batch_count
            or batch_qc.get("failed_or_incomplete_batch_count")
            != batch_count - passed_batch_count
        ):
            errors.append("qc_report.json batch gate does not match batch QC artifacts")
    if isinstance(summary, dict) and isinstance(batch_report, dict):
        if summary.get("metrics", {}).get("batch_qc_failed_or_incomplete_count") != (
            batch_count - passed_batch_count
        ):
            errors.append("run_summary batch count does not match batch QC artifacts")

    validate_html(paths["interactive_map"], errors)
    validate_temporal_html(paths["temporal_map"], errors)
    validate_temporal_embedding(paths["interactive_map"], paths["temporal_map"], errors)
    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            **database_metrics,
            "record_evidence_count": evidence_count,
            "sample_feature_count": sample_count,
            "candidate_feature_count": anomaly_count,
            "iteration_backlog_count": iteration_count,
            "batch_count": batch_count,
            "passed_batch_count": passed_batch_count,
            "candidate_anomaly_region_count": anomaly_region_count,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate all global geochemical atlas workflow outputs."
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="Workflow output directory"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_dir(args.output_dir)
    except OSError as exc:
        report = {
            "status": "invalid",
            "errors": [str(exc)],
            "warnings": [],
            "metrics": {},
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
