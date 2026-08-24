#!/usr/bin/env python3
"""Build a source-facing confidence explanation without collapsing quality dimensions."""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit


DIMENSIONS = (
    "source_evidence",
    "analytical_readiness",
    "spatial_usability",
    "workflow_usability",
)
METADATA_FIELDS = (
    "analytical_method",
    "method_source_locator",
    "canonical_coordinate",
    "source_reported_coordinate_uncertainty",
    "coordinate_representation_resolution",
    "exact_record_locator",
    "official_source_link",
)
METHOD_ABSENCE_REASON_FIELD = "method_missing_reason"
COORDINATE_ACCURACY_STATUS_FIELD = "coordinate_accuracy_evidence_status"


class SourceConfidenceError(RuntimeError):
    """Raised when the canonical evidence products cannot be summarized safely."""


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceConfidenceError(f"unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SourceConfidenceError(f"JSON must be an object: {path}")
    return value


def _band(confidence: Mapping[str, Any], dimension: str) -> str:
    quality_dimensions = confidence.get("quality_dimensions")
    if isinstance(quality_dimensions, Mapping):
        value = quality_dimensions.get(dimension)
        if isinstance(value, Mapping):
            return str(value.get("band") or "unknown")
    if dimension == "workflow_usability":
        return str(confidence.get("band") or "unknown")
    return "unknown"


def _score(confidence: Mapping[str, Any], dimension: str) -> float | None:
    quality_dimensions = confidence.get("quality_dimensions")
    if not isinstance(quality_dimensions, Mapping):
        return None
    value = quality_dimensions.get(dimension)
    if not isinstance(value, Mapping):
        return None
    try:
        score = float(value.get("score"))
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def _web_url(value: Any) -> str | None:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    return text if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _doi_url(value: Any) -> str | None:
    doi = str(value or "").strip()
    if not doi:
        return None
    if doi.casefold().startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]
    if doi.casefold().startswith("doi:"):
        doi = doi[4:].strip()
    if re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.IGNORECASE) is None:
        return None
    return f"https://doi.org/{quote(doi, safe='/()-.;:_')}"


def _rate(count: int, total: int) -> float:
    return round(count / total if total else 0.0, 6)


def _metadata_summary(counts: Mapping[str, int], total: int) -> dict[str, Any]:
    return {
        "record_count": total,
        **{
            field: {
                "count": int(counts.get(field, 0)),
                "rate": _rate(int(counts.get(field, 0)), total),
            }
            for field in METADATA_FIELDS
        },
        "claim_boundary": (
            "Completeness reports whether evidence is present, not whether the measurement is correct. "
            "Coordinate representation resolution is derived from numeric text and is not positional accuracy; "
            "only source_reported_coordinate_uncertainty is accuracy/uncertainty evidence."
        ),
    }


def _reason_summary(counts: Mapping[str, int], total: int) -> dict[str, Any]:
    """Keep absence responsibility explicit instead of emitting one quality label."""

    normalized = {
        str(reason): int(count)
        for reason, count in sorted(counts.items())
        if str(reason).strip() and int(count) > 0
    }
    return {
        "record_count": total,
        "counts": normalized,
        "accounted_count": sum(normalized.values()),
        "accounted_rate": _rate(sum(normalized.values()), total),
    }


def _empty_observed() -> dict[str, Any]:
    return {
        "record_count": 0,
        "dimension_band_counts": {dimension: Counter() for dimension in DIMENSIONS},
        "dimension_score_sums": {dimension: 0.0 for dimension in DIMENSIONS},
        "dimension_score_counts": {dimension: 0 for dimension in DIMENSIONS},
        "metadata_counts": Counter(),
        "element_counts": Counter(),
        "medium_counts": Counter(),
        "method_absence_reasons": Counter(),
        "coordinate_accuracy_statuses": Counter(),
        "coordinate_reference_statuses": Counter(),
    }


def _dimension_score_means(observed: Mapping[str, Any]) -> dict[str, float | None]:
    sums = observed.get("dimension_score_sums") or {}
    counts = observed.get("dimension_score_counts") or {}
    return {
        dimension: (
            round(float(sums.get(dimension, 0.0)) / int(counts.get(dimension, 0)), 6)
            if int(counts.get(dimension, 0)) > 0
            else None
        )
        for dimension in DIMENSIONS
    }


def _route_source_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    compatibility = item.get("request_compatibility")
    compatibility = compatibility if isinstance(compatibility, Mapping) else {}
    analytes = compatibility.get("analytes")
    analytes = analytes if isinstance(analytes, Mapping) else {}
    region = compatibility.get("region")
    region = region if isinstance(region, Mapping) else {}
    return {
        "source_id": str(item.get("source_id") or ""),
        "title": str(item.get("title") or ""),
        "route_status": str(item.get("status") or "unknown"),
        "reason": str(item.get("reason") or "not_reported"),
        "use_mode": str(item.get("use_mode") or "unknown"),
        "evidence_tier": str(item.get("evidence_tier") or "unknown"),
        "research_use_status": str(item.get("research_use_status") or "unknown"),
        "matching_elements": sorted(
            {str(value) for value in analytes.get("matched") or [] if value}
        ),
        "matching_media": sorted(
            {str(value) for value in item.get("matching_media") or [] if value}
        ),
        "region_status": str(region.get("status") or "unknown"),
        "region_reason_code": str(region.get("reason_code") or "not_reported"),
    }


def _source_portfolio(
    source_route: Mapping[str, Any], formal_source_ids: list[str]
) -> dict[str, Any]:
    selected = [
        _route_source_summary(item)
        for item in source_route.get("selected_sources") or []
        if isinstance(item, Mapping) and item.get("source_id")
    ]
    review = [
        _route_source_summary(item)
        for item in source_route.get("review_sources") or []
        if isinstance(item, Mapping) and item.get("source_id")
    ]
    formal = sorted(set(formal_source_ids))
    selected_ids = {item["source_id"] for item in selected}
    return {
        "route_status": str(source_route.get("status") or "not_available")
        if source_route
        else "not_available",
        "formal_included_source_count": len(formal),
        "formal_included_source_ids": formal,
        "routed_selected_source_count": len(selected),
        "review_or_blocked_source_count": len(review),
        "routed_but_not_included_source_ids": sorted(selected_ids - set(formal)),
        "selected_sources": selected,
        "review_or_blocked_sources": review,
        "claim_boundary": (
            "Formal included sources produced admitted records in this output. Routed selected sources passed "
            "request-level catalog checks but may still fail acquisition or record filtering. Review/blocked "
            "sources are discovery leads only. Counts must never be added together as admitted data sources."
        ),
    }


def build(
    database_path: Path,
    source_manifest_path: Path,
    confidence_report_path: Path,
    acquisition_manifest_path: Path | None = None,
    source_route_path: Path | None = None,
) -> dict[str, Any]:
    manifest = _read_object(source_manifest_path)
    confidence_report = _read_object(confidence_report_path)
    acquisition_manifest = (
        _read_object(acquisition_manifest_path)
        if acquisition_manifest_path is not None
        else {}
    )
    source_route = (
        _read_object(source_route_path) if source_route_path is not None else {}
    )
    per_source: dict[str, dict[str, Any]] = {}
    sample_sets: dict[str, set[str]] = {}
    metadata_counts: Counter[str] = Counter()
    method_absence_reasons: Counter[str] = Counter()
    coordinate_accuracy_statuses: Counter[str] = Counter()
    coordinate_reference_statuses: Counter[str] = Counter()
    row_official_urls: dict[str, set[str]] = {}
    try:
        handle = database_path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise SourceConfidenceError(f"unreadable database: {database_path}") from exc
    with handle:
        for row in csv.DictReader(handle):
            source_id = str(row.get("source_id") or "").strip()
            if not source_id:
                continue
            item = per_source.setdefault(source_id, _empty_observed())
            item["record_count"] += 1
            element = str(row.get("element_or_analyte") or "").strip()
            medium = str(row.get("medium") or "").strip()
            if element:
                item["element_counts"][element] += 1
            if medium:
                item["medium_counts"][medium] += 1
            row_metadata = {
                "analytical_method": bool(
                    str(row.get("analytical_method") or "").strip()
                ),
                "method_source_locator": bool(
                    str(row.get("method_source_locator") or "").strip()
                ),
                "canonical_coordinate": bool(
                    str(row.get("latitude") or "").strip()
                    and str(row.get("longitude") or "").strip()
                ),
                "source_reported_coordinate_uncertainty": bool(
                    str(row.get("coordinate_uncertainty_m") or "").strip()
                ),
                "coordinate_representation_resolution": bool(
                    str(row.get("coordinate_representation_resolution_m") or "").strip()
                ),
                "exact_record_locator": bool(
                    str(row.get("source_locator") or "").strip()
                ),
                "official_source_link": bool(
                    _web_url(row.get("official_source_url"))
                    or _doi_url(row.get("dataset_doi"))
                    or _doi_url(row.get("publication_doi"))
                ),
            }
            for field, present in row_metadata.items():
                if present:
                    item["metadata_counts"][field] += 1
                    metadata_counts[field] += 1
            if not row_metadata["analytical_method"]:
                reason = str(row.get(METHOD_ABSENCE_REASON_FIELD) or "").strip()
                item["method_absence_reasons"][reason or "unaccounted_in_input"] += 1
                method_absence_reasons[reason or "unaccounted_in_input"] += 1
            coordinate_status = str(
                row.get(COORDINATE_ACCURACY_STATUS_FIELD) or ""
            ).strip()
            item["coordinate_accuracy_statuses"][
                coordinate_status or "unaccounted_in_input"
            ] += 1
            coordinate_accuracy_statuses[
                coordinate_status or "unaccounted_in_input"
            ] += 1
            original_latitude = str(row.get("original_latitude_raw") or "").strip()
            original_longitude = str(row.get("original_longitude_raw") or "").strip()
            original_coordinate_present = bool(original_latitude and original_longitude)
            original_coordinate_incomplete = bool(original_latitude) != bool(
                original_longitude
            )
            source_crs_present = bool(str(row.get("source_crs") or "").strip())
            if row_metadata["canonical_coordinate"] and source_crs_present:
                coordinate_reference_status = "canonical_crs_evidenced"
            elif row_metadata["canonical_coordinate"]:
                coordinate_reference_status = (
                    "unaccounted_canonical_coordinate_without_source_crs"
                )
            elif original_coordinate_incomplete:
                coordinate_reference_status = "publisher_coordinate_pair_incomplete"
            elif original_coordinate_present and not source_crs_present:
                coordinate_reference_status = "publisher_datum_not_declared"
            elif original_coordinate_present:
                coordinate_reference_status = (
                    "coordinate_not_canonicalized_under_policy"
                )
            else:
                coordinate_reference_status = "not_applicable_no_reported_coordinate"
            item["coordinate_reference_statuses"][coordinate_reference_status] += 1
            coordinate_reference_statuses[coordinate_reference_status] += 1
            official_url = _web_url(row.get("official_source_url"))
            if official_url:
                row_official_urls.setdefault(source_id, set()).add(official_url)
            sample_identity = str(
                row.get("sample_identity_group") or row.get("sample_id") or ""
            ).strip()
            if sample_identity:
                sample_sets.setdefault(source_id, set()).add(sample_identity)
            raw = str(row.get("operational_confidence") or "").strip()
            try:
                confidence = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                confidence = {}
            if not isinstance(confidence, Mapping):
                confidence = {}
            for dimension in DIMENSIONS:
                item["dimension_band_counts"][dimension][
                    _band(confidence, dimension)
                ] += 1
                score = _score(confidence, dimension)
                if score is not None:
                    item["dimension_score_sums"][dimension] += score
                    item["dimension_score_counts"][dimension] += 1

    manifest_sources = {
        str(item.get("source_id")): item
        for item in manifest.get("sources", [])
        if isinstance(item, Mapping) and item.get("source_id")
    }
    acquisition_times: dict[str, set[str]] = {}
    acquisition_files = acquisition_manifest.get("source_files")
    if isinstance(acquisition_files, list):
        only_source_id = (
            next(iter(manifest_sources)) if len(manifest_sources) == 1 else None
        )
        for item in acquisition_files:
            if not isinstance(item, Mapping):
                continue
            source_id = str(item.get("source_id") or "").strip()
            if not source_id:
                filename = str(item.get("filename") or "")
                source_id = next(
                    (
                        candidate
                        for candidate in manifest_sources
                        if filename.startswith(f"{candidate}--")
                    ),
                    only_source_id or "",
                )
            retrieved_at = str(item.get("retrieved_at") or "").strip()
            if source_id and retrieved_at:
                acquisition_times.setdefault(source_id, set()).add(retrieved_at)
    sources: list[dict[str, Any]] = []
    for source_id in sorted(set(manifest_sources) | set(per_source)):
        source = manifest_sources.get(source_id, {})
        observed = per_source.get(source_id, _empty_observed())
        source_files = source.get("source_files") or []
        retrieved_times = sorted(acquisition_times.get(source_id, set()))
        official_links: list[dict[str, str]] = []
        for item in source_files:
            if not isinstance(item, Mapping):
                continue
            url = _web_url(item.get("url"))
            if url:
                official_links.append({"kind": "source_file", "url": url})
        for value in source.get("official_source_urls") or []:
            url = _web_url(value)
            if url:
                official_links.append({"kind": "source_file", "url": url})
        for doi in source.get("dataset_dois") or []:
            url = _doi_url(doi)
            if url:
                official_links.append({"kind": "dataset_doi", "url": url})
        for doi in source.get("article_dois") or []:
            url = _doi_url(doi)
            if url:
                official_links.append({"kind": "publication_doi", "url": url})
        for url in sorted(row_official_urls.get(source_id, set())):
            official_links.append({"kind": "record_official_url", "url": url})
        official_links = [
            {"kind": kind, "url": url}
            for kind, url in sorted(
                {(item["kind"], item["url"]) for item in official_links}
            )
        ]
        source_record_count = int(observed["record_count"])
        official_linked_record_count = int(
            observed["metadata_counts"].get("official_source_link", 0)
        )
        sources.append(
            {
                "source_id": source_id,
                "dataset_titles": list(source.get("dataset_titles") or []),
                "dataset_dois": list(source.get("dataset_dois") or []),
                "dataset_versions": list(source.get("dataset_versions") or []),
                "licenses": list(source.get("licenses") or []),
                "source_urls": sorted(
                    set(source.get("official_source_urls") or [])
                    | {
                        str(item.get("url"))
                        for item in source_files
                        if isinstance(item, Mapping) and item.get("url")
                    }
                ),
                "official_links": official_links,
                "record_count": source_record_count,
                "independent_sample_count": len(sample_sets.get(source_id, set())),
                "element_record_counts": dict(
                    sorted(observed["element_counts"].items())
                ),
                "medium_record_counts": dict(sorted(observed["medium_counts"].items())),
                "record_provenance": {
                    "located_record_count": int(
                        source.get("located_record_count") or 0
                    ),
                    "verified_record_count": int(
                        source.get("verified_record_count") or 0
                    ),
                    "official_linked_record_count": official_linked_record_count,
                    "file_hashes": [
                        {
                            "filename": item.get("filename"),
                            "sha256": item.get("sha256"),
                        }
                        for item in source_files
                        if isinstance(item, Mapping)
                    ],
                },
                "dimension_band_counts": {
                    dimension: dict(
                        sorted(observed["dimension_band_counts"][dimension].items())
                    )
                    for dimension in DIMENSIONS
                },
                "dimension_score_means": _dimension_score_means(observed),
                "metadata_completeness": _metadata_summary(
                    observed["metadata_counts"], source_record_count
                ),
                "metadata_absence_accounting": {
                    "analytical_method": _reason_summary(
                        observed["method_absence_reasons"],
                        source_record_count
                        - int(observed["metadata_counts"].get("analytical_method", 0)),
                    ),
                    "coordinate_accuracy": _reason_summary(
                        observed["coordinate_accuracy_statuses"],
                        source_record_count,
                    ),
                    "coordinate_reference": _reason_summary(
                        observed["coordinate_reference_statuses"],
                        source_record_count,
                    ),
                    "claim_boundary": (
                        "Method reasons distinguish publisher absence or unresolved publisher linkage from "
                        "unaccounted pipeline input. Coordinate-reference status distinguishes evidenced canonical "
                        "coordinates from publisher datum absence, incomplete coordinate pairs and policy-stopped "
                        "transformations. Coordinate-accuracy status separately distinguishes source-reported "
                        "uncertainty, publisher-not-reported uncertainty and records without canonical coordinates. "
                        "Neither status is a measurement-quality grade."
                    ),
                },
                "acquisition_time": (
                    retrieved_times[0] if len(retrieved_times) == 1 else None
                ),
                "acquisition_times": retrieved_times,
                "acquisition_time_status": (
                    "verified_from_acquisition_manifest"
                    if retrieved_times
                    else "not_available; consult request_evidence/acquisition manifests; no time is inferred from normalized records"
                ),
            }
        )

    total_records = sum(int(item["record_count"]) for item in sources)
    missing_method_records = total_records - int(
        metadata_counts.get("analytical_method", 0)
    )
    overall_means = {
        dimension: (
            round(
                float(
                    confidence_report.get("dimension_score_means", {}).get(dimension)
                ),
                6,
            )
            if isinstance(confidence_report.get("dimension_score_means"), Mapping)
            and isinstance(
                confidence_report.get("dimension_score_means", {}).get(dimension),
                (int, float),
            )
            and not isinstance(
                confidence_report.get("dimension_score_means", {}).get(dimension), bool
            )
            else None
        )
        for dimension in DIMENSIONS
    }
    workflow_bands = dict(
        (confidence_report.get("dimension_band_counts") or {}).get("workflow_usability")
        or {}
    )
    return {
        "report_version": "sources-and-confidence-v3",
        "data_mode": manifest.get("data_mode"),
        "not_for_scientific_interpretation": manifest.get(
            "not_for_scientific_interpretation"
        ),
        "single_quality_label_prohibited": True,
        "interpretation": (
            "source_evidence measures traceability; analytical_readiness measures method/QC comparability; "
            "spatial_usability measures coordinate fitness; workflow_usability is the operational pipeline band. "
            "A low workflow or spatial band does not mean the source or measurement is false or low quality."
        ),
        "dimension_meaning": confidence_report.get("dimension_meaning", {}),
        "overall_dimension_score_means": overall_means,
        "overall_dimension_band_counts": confidence_report.get(
            "dimension_band_counts", {}
        ),
        "overall_workflow_confidence": {
            "label": "overall workflow usability and review confidence",
            "score_mean": overall_means["workflow_usability"],
            "band_counts": workflow_bands,
            "record_count": total_records,
            "not_a_probability": True,
            "interpretation": (
                "This aggregate summarizes end-to-end usability and review priority. It is not source quality, "
                "measurement truth probability, positional accuracy, or statistical confidence."
            ),
        },
        "metadata_completeness": _metadata_summary(metadata_counts, total_records),
        "metadata_absence_accounting": {
            "analytical_method": _reason_summary(
                method_absence_reasons, missing_method_records
            ),
            "coordinate_accuracy": _reason_summary(
                coordinate_accuracy_statuses, total_records
            ),
            "coordinate_reference": _reason_summary(
                coordinate_reference_statuses, total_records
            ),
            "claim_boundary": (
                "These totals assign metadata absence to publisher reporting, unresolved publisher linkage, "
                "publisher datum/CRS absence, policy-stopped canonicalization, lack of positional-accuracy evidence, "
                "or unaccounted pipeline input. They are diagnostics, not a single quality grade."
            ),
        },
        "source_portfolio": _source_portfolio(
            source_route, [item["source_id"] for item in sources]
        ),
        "sources": sources,
        "claim_boundary": (
            "Counts describe the processed request slice. Confidence bands are workflow evidence classes, "
            "not probabilities, accuracy guarantees, or statistical representativeness."
        ),
    }
