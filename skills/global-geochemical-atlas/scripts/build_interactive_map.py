#!/usr/bin/env python3
"""Build the D3 self-contained interactive atlas and map-ready GeoJSON."""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import build_iteration_backlog as backlog_builder
import spatial_scope


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


MAP_VERSION = "d3-interactive-atlas-v3"
PAYLOAD_VERSION = "d3-compact-payload-v1"
SAMPLES_GEOJSON_PROPERTY_VERSION = "d3-map-sample-properties-v3"
ANOMALY_RENDER_MODE = "zoom-adaptive-anomaly-bubbles-v1"
PROFILE_VERSION = "d3-visualization-profile-v2"
UI_HIERARCHY_VERSION = "atlas-progressive-disclosure-v2"
TEMPLATE_CONTRACT_VERSION = "d3-domain-confidence-atlas-v5"
VISUAL_QUESTION_VERSION = "d3-visual-question-contract-v1"
TERMINOLOGY_CONTRACT = "competition-geochemistry-v1"
BASEMAP_ASSET_VERSION = "ai4s-natural-earth-land-v1"
BOUNDARY_ASSET_VERSION = "ai4s-natural-earth-admin0-v2"
ADMIN1_BOUNDARY_ASSET_VERSION = "ai4s-natural-earth-admin1-china-visual-v1"
MISSING_METHOD_LABEL = "发布方未报告分析方法"
MAX_OUTPUT_BYTES = 100_000_000
# The canonical database may contain 200k rows, but embedding every verbose
# observation in both HTML and GeoJSON can breach the competition/runtime
# 100 MB single-file gate.  Instead of a fixed record cap, the build embeds as
# many records as the byte budget below allows: it assembles the full preview
# first and, only when the serialized HTML or GeoJSON exceeds the budget,
# deterministically shrinks the coverage-preserving preview and rebuilds.  The
# preview retains complete physical sample groups, anomalies and source ×
# medium × element × spatial strata; unsampled rows always remain in
# geochemistry.csv and all aggregate summaries.
DEFAULT_MAX_EMBEDDED_RECORDS = 200_000
EMBED_TARGET_BYTES = 96_000_000
COORDINATE_MODES = ("canonical", "reported")
COORDINATE_BASIS_CANONICAL = "canonical_wgs84"
COORDINATE_BASIS_REPORTED = "reported_unverified"
REPORTED_BANNER_ID = "coordinate-mode-banner"
REPORTED_BANNER_PHRASE = "报告坐标，datum 未验证，仅供示意浏览"
STRICT_SCIENTIFIC_LAYER = "strict_scientific_ready"
TRACEABLE_SCREENING_LAYER = "traceable_screening_only"
PROVENANCE_INCOMPLETE_LAYER = "provenance_incomplete"
D2_ERROR_QC_FLAGS = frozenset(
    {
        "MISSING_VALUE",
        "INVALID_NUMERIC_VALUE",
        "INVALID_MISSING_REASON",
        "INVALID_DETECTION_LIMIT",
        "INVALID_QUANTITATION_LIMIT",
        "NEGATIVE_CONCENTRATION",
        "UNSUPPORTED_UNIT",
        "UNSUPPORTED_MOLAR_MASS",
        "UNSUPPORTED_MOLAR_SPECIES",
        "UNSUPPORTED_SPECIES_CONVERSION",
        "OXIDE_ELEMENT_MISMATCH",
        "AMBIGUOUS_AQUEOUS_RATIO_UNIT",
        "INVALID_COORDINATE",
        "UNSUPPORTED_SOURCE_CRS",
        "INVALID_COORDINATE_POLICY",
        "DEPTH_RANGE_INVALID",
        "INVALID_GEOLOGIC_DISTANCE",
        "BATCH_QC_FAILED",
    }
)
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BASEMAP = SKILL_DIR / "assets" / "natural-earth-110m-land.json"
DEFAULT_BOUNDARIES = SKILL_DIR / "assets" / "natural-earth-110m-admin0.json"
DEFAULT_ADMIN1_BOUNDARIES = (
    SKILL_DIR / "assets" / "natural-earth-50m-admin1-china-visual.json"
)
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "interactive-atlas-v3.html"
DEFAULT_PROFILE = SKILL_DIR / "assets" / "visualization-profile.template.json"
REGION_PRESETS: dict[str, dict[str, Any]] = {
    "global": {
        "label": "全球",
        "bounds": {"w": -180.0, "e": 180.0, "s": -90.0, "n": 90.0},
    },
    "usa": {
        "label": "美国（国家边界严格裁剪）",
        "bounds": {"w": -170.0, "e": -66.0, "s": 18.0, "n": 72.0},
        "country_code": "USA",
    },
    "usa48": {
        "label": "美国本土（国界 + 范围框）",
        "bounds": {"w": -125.0, "e": -66.0, "s": 24.0, "n": 50.0},
        "country_code": "USA",
    },
    "china": {
        "label": "中国（国家边界严格裁剪）",
        "bounds": {"w": 73.0, "e": 135.0, "s": 18.0, "n": 54.0},
        "country_code": "CHN",
        # Scientific analysis-admission units: Natural Earth stores Taiwan as
        # a separate Admin-0 feature, so a China preset that clips on the CHN
        # polygon alone would silently drop real Taiwanese observations.
        "analysis_country_codes": ["CHN", "TWN"],
    },
    "shanghai": {
        "label": "上海范围框",
        "bounds": {"w": 120.85, "e": 122.2, "s": 30.65, "n": 31.9},
    },
    "europe": {
        "label": "欧洲范围框",
        "bounds": {"w": -25.0, "e": 45.0, "s": 34.0, "n": 72.0},
    },
    "australia": {
        "label": "澳大利亚（国家边界严格裁剪）",
        "bounds": {"w": 112.0, "e": 154.0, "s": -44.0, "n": -10.0},
        "country_code": "AUS",
    },
}

VISUAL_QUESTION_CONTRACT: dict[str, Any] = {
    "schema_version": VISUAL_QUESTION_VERSION,
    "views": {
        "map": {
            "question": "当前区域有哪些观测，采样覆盖有多密？",
            "comparison_baseline": "当前筛选范围内的物理采样点与记录",
            "encoding": [
                "position=WGS84 coordinate",
                "glow=physical sample density",
                "symbol=clickable observation",
            ],
            "boundary": "密度不编码浓度；空白不等于元素不存在。",
        },
        "database": {
            "question": "每条标准化测定能否被检索、追溯并提出审计修订？",
            "comparison_baseline": "canonical geochemistry.csv",
            "encoding": ["row=one analyte measurement", "patch=proposal only"],
            "boundary": "页面修订不直接改写 canonical 数据或证据。",
        },
        "combination": {
            "question": "同一批可比样品中的两个元素是否共同升降？",
            "comparison_baseline": "同区域、介质、basis、方法与单位的同样品配对",
            "encoding": [
                "position=log10 paired value",
                "quadrant=relative to paired medians",
                "rho=Spearman association",
            ],
            "boundary": "共测与相关不证明因果、污染来源或矿化成因。",
        },
        "sources": {
            "question": "这些记录来自哪里，证据和工作流置信度允许怎样使用？",
            "comparison_baseline": "D1 source manifest and D2 confidence components",
            "encoding": ["table=source coverage", "components=workflow usability"],
            "boundary": "工作流置信度不是正确概率或统计置信区间。",
        },
        "anomalies": {
            "question": "候选值相对可比背景中位数和稳健阈值偏离多少？",
            "comparison_baseline": "D2 declared comparable background group",
            "encoding": [
                "position=robust-z threshold scale",
                "color=high or low candidate",
                "ring=count-only visual aggregation",
            ],
            "boundary": "候选不是空间邻域均值结论，也不证明污染或成因。",
        },
        "quality": {
            "question": "下一轮应由 D1/D2 修复什么，哪些只能复核或保留为科学限制？",
            "comparison_baseline": "versioned QC and iteration backlog",
            "encoding": ["status=action/review/scientific limit", "owner=D1 or D2"],
            "boundary": "无证据时停止自动补齐，删失值不自动视为失败。",
        },
    },
}


class MapBuildError(ValueError):
    """Raised when D2 map inputs or the bundled basemap are invalid."""


def optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_json_cell(value: Any, fallback: Any) -> Any:
    if value is None or str(value).strip() == "":
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def parse_bool_cell(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def valid_web_url(value: Any) -> bool:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def record_evidence_classification(
    row: Mapping[str, Any],
    *,
    coordinate_basis: str,
    spatial_domain: str,
    qc_flags: Sequence[Any],
) -> dict[str, Any]:
    """Classify display eligibility without inventing missing source evidence."""

    strict_provenance_fields = (
        "source_id",
        "source_record_id",
        "source_file",
        "source_locator",
        "dataset_title",
        "dataset_version",
        "license",
    )
    missing_provenance = [
        field
        for field in strict_provenance_fields
        if not str(row.get(field) or "").strip()
    ]
    if not valid_web_url(row.get("official_source_url")):
        missing_provenance.append("official_source_url")
    if not re.fullmatch(
        r"[0-9a-f]{64}", str(row.get("file_sha256") or "").strip().casefold()
    ):
        missing_provenance.append("file_sha256")
    traceable = bool(
        str(row.get("source_id") or "").strip()
        and str(row.get("source_locator") or "").strip()
    )
    strict_provenance = not missing_provenance

    scientific_gaps: list[str] = []
    if not strict_provenance:
        scientific_gaps.append("strict_provenance_incomplete")
    if coordinate_basis != COORDINATE_BASIS_CANONICAL:
        scientific_gaps.append("canonical_wgs84_coordinate_missing")
    if not str(row.get("method_family") or row.get("analytical_method") or "").strip():
        scientific_gaps.append("analytical_method_missing")
    geologic_context_present = any(
        str(row.get(field) or "").strip()
        for field in (
            "matched_geologic_unit",
            "geologic_unit",
            "geologic_unit_raw",
            "lithology",
            "lithology_raw",
            "soil_horizon",
            "sediment_environment",
            "water_body_type",
            "tectonic_setting_raw",
        )
    )
    marine_not_applicable = bool(
        spatial_domain == "marine"
        and str(row.get("medium") or "") in {"water", "sediment"}
        and str(row.get("geology_missing_reason") or "")
        in {"not_applicable_marine_water", "not_applicable_marine_sediment"}
    )
    if not geologic_context_present and not marine_not_applicable:
        scientific_gaps.append("geological_context_missing")
    if (
        optional_float(row.get("normalized_value")) is None
        or not str(row.get("normalized_unit") or "").strip()
    ):
        scientific_gaps.append("quantitative_standardization_missing")

    raw_qc_flags = str(row.get("qc_flags") or "").strip()
    qc_evaluated = bool(raw_qc_flags) and isinstance(qc_flags, list)
    blocking_qc_flags = sorted(
        D2_ERROR_QC_FLAGS.intersection(str(item) for item in qc_flags)
    )
    if not qc_evaluated:
        scientific_gaps.append("qc_disposition_missing")
        qc_status = "not_evaluated"
    elif blocking_qc_flags:
        scientific_gaps.append("qc_blocking_flag")
        qc_status = "failed_or_excluded"
    elif qc_flags:
        qc_status = "completed_with_flags"
    else:
        qc_status = "completed_no_flags"

    if not scientific_gaps:
        evidence_layer = STRICT_SCIENTIFIC_LAYER
    elif traceable:
        evidence_layer = TRACEABLE_SCREENING_LAYER
    else:
        evidence_layer = PROVENANCE_INCOMPLETE_LAYER
    return {
        "evidence_layer": evidence_layer,
        "provenance_status": (
            "strict_complete"
            if strict_provenance
            else "traceable_partial"
            if traceable
            else "incomplete"
        ),
        "quality_control_status": qc_status,
        "scientific_readiness_reasons": scientific_gaps,
        "missing_provenance_fields": missing_provenance,
        "blocking_qc_flags": blocking_qc_flags,
    }


def geological_context_display(
    row: Mapping[str, Any], *, spatial_domain: str
) -> dict[str, Any]:
    """Separate formal map-unit evidence from publisher background text.

    Missing canonical coordinates can prevent a polygon join even when the
    publisher reports useful lithology, horizon, depositional environment or
    survey-area context. The UI exposes both facts without upgrading descriptive
    text into a formal geologic-unit match.
    """

    formal_geologic_unit = (
        str(row.get("matched_geologic_unit") or row.get("geologic_unit") or "").strip()
        or None
    )
    fields = (
        ("geologic_unit_raw", "发布方地质单元"),
        ("lithology_raw", "发布方岩性"),
        ("lithology", "标准化岩性"),
        ("soil_horizon", "土层 / 层位"),
        ("sediment_environment", "沉积环境"),
        ("water_body_type", "水体类型"),
        ("tectonic_setting_raw", "构造背景"),
        ("geographic_context_raw", "调查区 / 地理背景"),
        ("survey_area", "调查范围"),
    )
    parts: list[str] = []
    seen_values: set[str] = set()
    for field, label in fields:
        value = str(row.get(field) or "").strip()
        if not value or value in seen_values:
            continue
        seen_values.add(value)
        parts.append(f"{label}: {value}")
    publisher_background = "；".join(parts) or None
    missing_reason = str(row.get("geology_missing_reason") or "").strip()
    if formal_geologic_unit:
        status = "formal_geologic_unit_available"
    elif publisher_background:
        status = "publisher_context_reported"
    elif spatial_domain == "marine" and missing_reason.startswith(
        "not_applicable_marine"
    ):
        status = "formal_unit_not_applicable_marine"
    elif missing_reason in {
        "invalid_or_missing_canonical_coordinate",
        "canonical_coordinate_unavailable",
        "reported_only_coordinate_evidence",
    }:
        status = "spatial_match_unavailable"
    elif missing_reason:
        status = "publisher_context_not_reported"
    else:
        status = "geological_context_unaccounted"
    return {
        "geologic_unit": formal_geologic_unit,
        "formal_geologic_unit": formal_geologic_unit,
        "publisher_geological_background": publisher_background,
        "geological_context_status": status,
    }


def coordinate_in_bounds(
    longitude: float, latitude: float, bounds: Mapping[str, float]
) -> bool:
    return spatial_scope.coordinate_in_bbox(
        longitude,
        latitude,
        [bounds["w"], bounds["s"], bounds["e"], bounds["n"]],
    )


def point_on_segment(
    longitude: float, latitude: float, start: Sequence[float], end: Sequence[float]
) -> bool:
    cross = (longitude - start[0]) * (end[1] - start[1]) - (latitude - start[1]) * (
        end[0] - start[0]
    )
    if abs(cross) > 1e-9:
        return False
    return (
        min(start[0], end[0]) - 1e-9 <= longitude <= max(start[0], end[0]) + 1e-9
        and min(start[1], end[1]) - 1e-9 <= latitude <= max(start[1], end[1]) + 1e-9
    )


def point_in_ring(
    longitude: float, latitude: float, ring: Sequence[Sequence[float]]
) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        if point_on_segment(longitude, latitude, previous, current):
            return True
        if (current[1] > latitude) != (previous[1] > latitude):
            intersection = (previous[0] - current[0]) * (latitude - current[1]) / (
                previous[1] - current[1]
            ) + current[0]
            if longitude < intersection:
                inside = not inside
        previous = current
    return inside


def geometry_polygons(geometry: Mapping[str, Any]) -> Sequence[Any]:
    coordinates = geometry.get("coordinates") or []
    return [coordinates] if geometry.get("type") == "Polygon" else coordinates


def point_in_country(
    longitude: float, latitude: float, country: Mapping[str, Any]
) -> bool:
    for polygon in geometry_polygons(country.get("geometry") or {}):
        if not polygon or not point_in_ring(longitude, latitude, polygon[0]):
            continue
        if not any(point_in_ring(longitude, latitude, hole) for hole in polygon[1:]):
            return True
    return False


def coordinate_in_region(
    longitude: float,
    latitude: float,
    region: Mapping[str, Any],
    countries_by_code: Mapping[str, Mapping[str, Any]],
) -> bool:
    if not coordinate_in_bounds(longitude, latitude, region["bounds"]):
        return False
    country_codes = [
        str(code)
        for code in (
            region.get("analysis_country_codes")
            or ([region["country_code"]] if region.get("country_code") else [])
        )
    ]
    if not country_codes:
        return True
    for code in country_codes:
        country = countries_by_code.get(code)
        if country is None:
            raise MapBuildError(f"country boundary is unavailable: {code}")
        if point_in_country(longitude, latitude, country):
            return True
    return False


def parse_row_coordinates(
    row: Mapping[str, Any], coordinate_mode: str
) -> tuple[float, float, str] | str:
    """Resolve one row's plotting coordinates without reinterpreting evidence.

    Returns (latitude, longitude, coordinate_basis) when the row is plottable
    under the requested mode, otherwise a rejection category string:
    "reported_only" (canonical mode refuses an unverified-datum row) or
    "no_plottable_coordinates" (neither canonical nor parsable reported pair).
    """
    latitude = optional_float(row.get("latitude"))
    longitude = optional_float(row.get("longitude"))
    if (
        latitude is not None
        and longitude is not None
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return latitude, longitude, COORDINATE_BASIS_CANONICAL
    reported_latitude = optional_float(row.get("original_latitude_raw"))
    reported_longitude = optional_float(row.get("original_longitude_raw"))
    reported_plottable = (
        reported_latitude is not None
        and reported_longitude is not None
        and -90 <= reported_latitude <= 90
        and -180 <= reported_longitude <= 180
    )
    if not reported_plottable:
        return "no_plottable_coordinates"
    if coordinate_mode != "reported":
        return "reported_only"
    assert reported_latitude is not None and reported_longitude is not None
    return reported_latitude, reported_longitude, COORDINATE_BASIS_REPORTED


def load_records(
    path: Path,
    max_points: int,
    scope_region: Mapping[str, Any],
    countries_by_code: Mapping[str, Mapping[str, Any]],
    coordinate_mode: str = "canonical",
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Consume, but never reinterpret, the public D2 canonical CSV."""
    if not path.is_file():
        raise MapBuildError(f"database does not exist: {path}")
    if coordinate_mode not in COORDINATE_MODES:
        raise MapBuildError(
            f"--coordinate-mode must be one of {', '.join(COORDINATE_MODES)}"
        )
    records: list[dict[str, Any]] = []
    counts = {
        "total_records": 0,
        "canonical_coordinate_records": 0,
        "reported_fallback_records": 0,
        "reported_only_records": 0,
        "records_without_plottable_coordinates": 0,
    }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "record_id",
            "element_or_analyte",
            "medium",
            "normalized_value",
            "normalized_unit",
            "latitude",
            "longitude",
            "qc_flags",
            "operational_confidence",
            "source_id",
            "source_locator",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise MapBuildError(f"database missing map columns: {', '.join(missing)}")
        for row in reader:
            counts["total_records"] += 1
            resolved = parse_row_coordinates(row, coordinate_mode)
            if resolved == "reported_only":
                counts["reported_only_records"] += 1
                continue
            if resolved == "no_plottable_coordinates":
                counts["records_without_plottable_coordinates"] += 1
                continue
            assert not isinstance(resolved, str)
            latitude, longitude, coordinate_basis = resolved
            if coordinate_basis == COORDINATE_BASIS_CANONICAL:
                counts["canonical_coordinate_records"] += 1
            else:
                counts["reported_fallback_records"] += 1
                counts["reported_only_records"] += 1
            if not coordinate_in_region(
                longitude, latitude, scope_region, countries_by_code
            ):
                continue
            confidence = parse_json_cell(row.get("operational_confidence"), {})
            qc_flags = parse_json_cell(row.get("qc_flags"), [])
            if not isinstance(confidence, dict):
                confidence = {}
            if not isinstance(qc_flags, list):
                qc_flags = []
            quality_dimensions = confidence.get("quality_dimensions")
            if not isinstance(quality_dimensions, Mapping):
                quality_dimensions = {}

            def quality_value(dimension: str, key: str) -> Any:
                value = quality_dimensions.get(dimension)
                return value.get(key) if isinstance(value, Mapping) else None

            spatial_domain = spatial_scope.record_spatial_domain(row)
            geological_context = geological_context_display(
                row, spatial_domain=spatial_domain
            )
            workflow_score = optional_float(
                quality_value("workflow_usability", "score")
            )
            evidence_classification = record_evidence_classification(
                row,
                coordinate_basis=coordinate_basis,
                spatial_domain=spatial_domain,
                qc_flags=qc_flags,
            )
            records.append(
                {
                    "record_id": row.get("record_id"),
                    "sample_id": row.get("sample_id") or None,
                    "element": row.get("element_or_analyte"),
                    "analyte_reported": row.get("analyte_reported") or None,
                    "medium": row.get("medium"),
                    "spatial_domain": spatial_domain,
                    "material": row.get("material") or None,
                    "sample_type_raw": row.get("sample_type_raw") or None,
                    "sample_type": row.get("sample_type") or None,
                    "soil_horizon": row.get("soil_horizon") or None,
                    "sediment_environment": row.get("sediment_environment") or None,
                    "water_body_type": row.get("water_body_type") or None,
                    "water_fraction": row.get("water_fraction") or None,
                    "measurement_basis": row.get("measurement_basis") or None,
                    "original_value_raw": row.get("original_value_raw") or None,
                    "original_value": optional_float(row.get("original_value")),
                    "original_unit": row.get("original_unit") or None,
                    "source_qualifier_raw": row.get("source_qualifier_raw") or None,
                    "qualifier": row.get("value_qualifier") or None,
                    "censored": parse_bool_cell(row.get("censored")),
                    "censoring_limit": optional_float(
                        row.get("normalized_censoring_limit")
                    ),
                    "value": optional_float(row.get("normalized_value")),
                    "unit": row.get("normalized_unit") or None,
                    "latitude": latitude,
                    "longitude": longitude,
                    "coordinate_basis": coordinate_basis,
                    "coordinate_uncertainty_m": optional_float(
                        row.get("coordinate_uncertainty_m")
                    ),
                    "coordinate_representation_resolution_m": optional_float(
                        row.get("coordinate_representation_resolution_m")
                    ),
                    "coordinate_representation_resolution_basis": row.get(
                        "coordinate_representation_resolution_basis"
                    )
                    or None,
                    "coordinate_accuracy_evidence_status": row.get(
                        "coordinate_accuracy_evidence_status"
                    )
                    or None,
                    "lithology": row.get("lithology") or None,
                    **geological_context,
                    "geologic_unit_raw": row.get("geologic_unit_raw") or None,
                    "matched_geologic_unit": row.get("matched_geologic_unit") or None,
                    "geology_missing_reason": row.get("geology_missing_reason") or None,
                    "analytical_method": row.get("analytical_method") or None,
                    "method_family": row.get("method_family") or None,
                    "method_scope": row.get("method_scope") or None,
                    "method_source_locator": row.get("method_source_locator") or None,
                    "method_missing_reason": row.get("method_missing_reason") or None,
                    "digestion_or_extraction": row.get("digestion_or_extraction")
                    or None,
                    "preparation": row.get("preparation") or None,
                    "grain_fraction": row.get("grain_fraction") or None,
                    "reference_materials": row.get("reference_materials")
                    or row.get("reference_material")
                    or None,
                    "source_id": row.get("source_id") or None,
                    "dataset_title": row.get("dataset_title") or None,
                    "dataset_doi": row.get("dataset_doi") or None,
                    "dataset_version": row.get("dataset_version") or None,
                    "source_locator": row.get("source_locator") or None,
                    "official_source_url": row.get("official_source_url") or None,
                    "license": row.get("license") or None,
                    "confidence_band": confidence.get("band", "unknown"),
                    "confidence_overall": optional_float(confidence.get("overall")),
                    "confidence_source_evidence_band": quality_value(
                        "source_evidence", "band"
                    )
                    or "unknown",
                    "confidence_source_evidence_score": optional_float(
                        quality_value("source_evidence", "score")
                    ),
                    "confidence_analytical_readiness_band": quality_value(
                        "analytical_readiness", "band"
                    )
                    or "unknown",
                    "confidence_analytical_readiness_score": optional_float(
                        quality_value("analytical_readiness", "score")
                    ),
                    "confidence_spatial_usability_band": quality_value(
                        "spatial_usability", "band"
                    )
                    or "unknown",
                    "confidence_spatial_usability_score": optional_float(
                        quality_value("spatial_usability", "score")
                    ),
                    "confidence_workflow_usability_band": quality_value(
                        "workflow_usability", "band"
                    )
                    or confidence.get("band", "unknown"),
                    "confidence_workflow_usability_score": (
                        workflow_score
                        if workflow_score is not None
                        else optional_float(confidence.get("overall"))
                    ),
                    "confidence_components": {
                        key: optional_float(confidence.get(key))
                        for key in ("source", "completeness", "method", "spatial", "qc")
                    },
                    "qc_flags": [str(flag) for flag in qc_flags],
                    **evidence_classification,
                }
            )
            if len(records) > max_points:
                raise MapBuildError(
                    f"valid map points within the configured scope exceed --max-points "
                    f"({max_points}); filter the input first"
                )
    return records, counts


def database_visual_summary(path: Path) -> dict[str, Any]:
    """Aggregate the complete canonical CSV for D3 charts without embedding every row."""
    coverage: dict[str, dict[str, int]] = {}
    map_availability: dict[str, dict[str, dict[str, int]]] = {
        "elements": {},
        "media": {},
    }
    strata: dict[tuple[str, str, str, str, str], list[float]] = {}
    complete = {
        "standardized": 0,
        "coordinates": 0,
        "method": 0,
        "geology": 0,
        "provenance": 0,
        "qc": 0,
    }
    total = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            total += 1
            element = str(row.get("element_or_analyte") or "").strip()
            medium = str(row.get("medium") or "").strip()
            if element and medium:
                coverage.setdefault(element, {})[medium] = (
                    coverage.setdefault(element, {}).get(medium, 0) + 1
                )
            value = optional_float(row.get("normalized_value"))
            unit = str(row.get("normalized_unit") or "").strip()
            basis = str(row.get("measurement_basis") or "").strip()
            method = str(
                row.get("method_family") or row.get("analytical_method") or ""
            ).strip()
            if value is not None and unit:
                complete["standardized"] += 1
            latitude = optional_float(row.get("latitude"))
            longitude = optional_float(row.get("longitude"))
            canonical_coordinates = (
                latitude is not None
                and longitude is not None
                and -90 <= latitude <= 90
                and -180 <= longitude <= 180
            )
            reported_latitude = optional_float(row.get("original_latitude_raw"))
            reported_longitude = optional_float(row.get("original_longitude_raw"))
            reported_coordinates = (
                reported_latitude is not None
                and reported_longitude is not None
                and -90 <= reported_latitude <= 90
                and -180 <= reported_longitude <= 180
            )
            if canonical_coordinates:
                complete["coordinates"] += 1
                coordinate_class = "canonical_coordinate_records"
            elif reported_coordinates:
                coordinate_class = "reported_only_coordinate_records"
            else:
                coordinate_class = "unplottable_records"
            for dimension, dimension_value in (
                ("elements", element),
                ("media", medium),
            ):
                if not dimension_value:
                    continue
                availability = map_availability[dimension].setdefault(
                    dimension_value,
                    {
                        "database_records": 0,
                        "canonical_coordinate_records": 0,
                        "reported_only_coordinate_records": 0,
                        "unplottable_records": 0,
                    },
                )
                availability["database_records"] += 1
                availability[coordinate_class] += 1
            if method:
                complete["method"] += 1
            if (
                row.get("matched_geologic_unit")
                or row.get("geologic_unit")
                or row.get("lithology")
            ):
                complete["geology"] += 1
            if row.get("source_id") and row.get("source_locator"):
                complete["provenance"] += 1
            if str(row.get("qc_flags") or "").strip():
                complete["qc"] += 1
            if (
                element
                and medium
                and basis
                and method
                and unit
                and value is not None
                and value > 0
                and not parse_bool_cell(row.get("censored"))
            ):
                strata.setdefault((element, medium, basis, method, unit), []).append(
                    value
                )

    distributions: dict[str, dict[str, Any]] = {}
    by_element: dict[str, list[tuple[tuple[str, str, str, str, str], list[float]]]] = {}
    for key, values in strata.items():
        by_element.setdefault(key[0], []).append((key, values))
    for element, candidates in by_element.items():
        key, values = sorted(candidates, key=lambda item: (-len(item[1]), item[0]))[0]
        if len(values) < 2:
            continue
        ordered = sorted(values)

        def quantile(fraction: float) -> float:
            index = (len(ordered) - 1) * fraction
            lower = math.floor(index)
            upper = min(len(ordered) - 1, lower + 1)
            return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)

        logs = [math.log10(value) for value in values]
        low, high = min(logs), max(logs)
        span = max(high - low, 1e-12)
        bins = [0] * 16
        for value in logs:
            index = min(15, math.floor((value - low) / span * 16))
            bins[index] += 1
        distributions[element] = {
            "element": element,
            "medium": key[1],
            "basis": key[2],
            "method": key[3],
            "unit": key[4],
            "record_count": len(values),
            "p10": quantile(0.1),
            "median": quantile(0.5),
            "p90": quantile(0.9),
            "log10_min": low,
            "log10_max": high,
            "histogram": bins,
        }
    return {
        "schema_version": "d3-database-visual-summary-v1",
        "record_count": total,
        "coverage": coverage,
        "map_availability": map_availability,
        "completeness": {
            key: {"count": count, "rate": count / total if total else 0.0}
            for key, count in complete.items()
        },
        "distributions": distributions,
    }


def load_json_object(path: Path | None, label: str) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.is_file():
        raise MapBuildError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MapBuildError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise MapBuildError(f"{label} must be a JSON object")
    return value


def require_exact_keys(
    value: Mapping[str, Any], expected: set[str], label: str
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise MapBuildError(f"{label} fields are invalid: {'; '.join(details)}")


def profile_text(
    value: Any, label: str, maximum: int, nullable: bool = False
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MapBuildError(f"visualization profile {label} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise MapBuildError(
            f"visualization profile {label} exceeds {maximum} characters"
        )
    return text


def load_visualization_profile(path: Path | None = None) -> dict[str, Any]:
    profile = load_json_object(path or DEFAULT_PROFILE, "visualization profile")
    top_keys = {
        "schema_version",
        "title",
        "subtitle",
        "story",
        "theme",
        "spatial_scope",
        "default_region",
        "custom_region",
        "filters",
        "comparison",
        "display",
    }
    require_exact_keys(profile, top_keys, "visualization profile")
    if profile.get("schema_version") != PROFILE_VERSION:
        raise MapBuildError(f"visualization profile must use {PROFILE_VERSION}")
    if profile.get("theme") != "evidence-dark":
        raise MapBuildError("visualization profile theme must be evidence-dark")
    story = profile.get("story")
    if story not in {
        "overview",
        "coverage",
        "anomaly",
        "comparison",
        "database",
        "evidence",
    }:
        raise MapBuildError("visualization profile story is unsupported")
    default_region = profile.get("default_region")
    if default_region not in {*REGION_PRESETS, "custom"}:
        raise MapBuildError("visualization profile default_region is unsupported")
    spatial_scope = profile.get("spatial_scope")
    if spatial_scope not in {"global", "regional"}:
        raise MapBuildError(
            "visualization profile spatial_scope must be global or regional"
        )
    if spatial_scope == "global" and default_region != "global":
        raise MapBuildError("spatial_scope=global requires default_region=global")
    if spatial_scope == "regional" and default_region == "global":
        raise MapBuildError(
            "spatial_scope=regional requires a non-global default_region"
        )

    custom_region = profile.get("custom_region")
    if custom_region is not None:
        if not isinstance(custom_region, dict):
            raise MapBuildError(
                "visualization profile custom_region must be null or an object"
            )
        missing = sorted({"label", "bounds"} - set(custom_region))
        unknown = sorted(
            set(custom_region)
            - {"label", "bounds", "country_code", "highlight_country_codes"}
        )
        if missing or unknown:
            details = []
            if missing:
                details.append("missing " + ", ".join(missing))
            if unknown:
                details.append("unknown " + ", ".join(unknown))
            raise MapBuildError(
                f"custom_region fields are invalid: {'; '.join(details)}"
            )
        bounds = custom_region.get("bounds")
        if not isinstance(bounds, dict):
            raise MapBuildError(
                "visualization profile custom_region.bounds must be an object"
            )
        require_exact_keys(bounds, {"w", "s", "e", "n"}, "custom_region.bounds")
        numbers: dict[str, float] = {}
        for key in ("w", "s", "e", "n"):
            raw_value = bounds.get(key)
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise MapBuildError(
                    f"visualization profile custom_region.bounds.{key} is invalid"
                )
            value = float(raw_value)
            if not math.isfinite(value):
                raise MapBuildError(
                    f"visualization profile custom_region.bounds.{key} is invalid"
                )
            numbers[key] = value
        if not (
            -180 <= numbers["w"] <= 180
            and -180 <= numbers["e"] <= 180
            and -90 <= numbers["s"] < numbers["n"] <= 90
        ):
            raise MapBuildError(
                "visualization profile custom bounds must be WGS84 with S<N; W>E denotes antimeridian crossing"
            )
        country_code = custom_region.get("country_code")
        if country_code is not None and (
            not isinstance(country_code, str)
            or not re.fullmatch(r"[A-Z]{3}", country_code)
        ):
            raise MapBuildError(
                "visualization profile custom_region.country_code must be null or ISO-3"
            )
        highlight_codes = custom_region.get("highlight_country_codes")
        if highlight_codes is not None:
            if (
                not isinstance(highlight_codes, list)
                or not highlight_codes
                or len(highlight_codes) > 6
                or len(set(highlight_codes)) != len(highlight_codes)
                or not all(
                    isinstance(code, str) and re.fullmatch(r"[A-Z]{3}", code)
                    for code in highlight_codes
                )
            ):
                raise MapBuildError(
                    "visualization profile custom_region.highlight_country_codes "
                    "must be 1-6 unique ISO-3 codes"
                )
        normalized_custom_region: dict[str, Any] = {
            "label": profile_text(
                custom_region.get("label"), "custom_region.label", 80
            ),
            "bounds": numbers,
            "country_code": country_code,
        }
        if highlight_codes is not None:
            normalized_custom_region["highlight_country_codes"] = [
                str(code) for code in highlight_codes
            ]
        custom_region = normalized_custom_region
    if default_region == "custom" and custom_region is None:
        raise MapBuildError("default_region=custom requires custom_region")
    if default_region != "custom" and custom_region is not None:
        raise MapBuildError("custom_region must be null unless default_region=custom")

    filters = profile.get("filters")
    filter_keys = {
        "element",
        "medium",
        "sample_type",
        "basis",
        "geology",
        "method",
        "method_scope",
        "source",
        "confidence",
    }
    if not isinstance(filters, dict):
        raise MapBuildError("visualization profile filters must be an object")
    require_exact_keys(filters, filter_keys, "visualization profile filters")
    normalized_filters = {
        key: profile_text(filters.get(key), f"filters.{key}", 160, nullable=True)
        for key in sorted(filter_keys)
    }

    comparison = profile.get("comparison")
    comparison_keys = {"x", "y", "medium"}
    if not isinstance(comparison, dict):
        raise MapBuildError("visualization profile comparison must be an object")
    require_exact_keys(comparison, comparison_keys, "visualization profile comparison")
    normalized_comparison = {
        key: profile_text(comparison.get(key), f"comparison.{key}", 160, nullable=True)
        for key in sorted(comparison_keys)
    }
    if (normalized_comparison["x"] is None) != (normalized_comparison["y"] is None):
        raise MapBuildError(
            "visualization profile comparison.x and comparison.y must be paired"
        )
    if story == "comparison" and (
        normalized_comparison["x"] is None or normalized_comparison["y"] is None
    ):
        raise MapBuildError(
            "visualization profile story=comparison requires comparison.x and comparison.y"
        )
    if (
        normalized_comparison["x"] is not None
        and normalized_comparison["x"] == normalized_comparison["y"]
    ):
        raise MapBuildError(
            "visualization profile comparison elements must be different"
        )

    display = profile.get("display")
    display_keys = {
        "map_mode",
        "color_by",
        "anomaly_grid_degrees",
        "show_anomaly_points",
        "show_anomaly_regions",
    }
    if not isinstance(display, dict):
        raise MapBuildError("visualization profile display must be an object")
    require_exact_keys(display, display_keys, "visualization profile display")
    if display.get("map_mode") not in {"distribution", "heat", "combined"}:
        raise MapBuildError("visualization profile display.map_mode is unsupported")
    if display.get("color_by") not in {"medium", "element", "value"}:
        raise MapBuildError("visualization profile display.color_by is unsupported")
    grid_degrees = display.get("anomaly_grid_degrees")
    if isinstance(grid_degrees, bool) or grid_degrees not in {1, 2, 5}:
        raise MapBuildError(
            "visualization profile anomaly grid must be 1, 2, or 5 degrees"
        )
    for key in ("show_anomaly_points", "show_anomaly_regions"):
        if not isinstance(display.get(key), bool):
            raise MapBuildError(f"visualization profile display.{key} must be boolean")

    return {
        "schema_version": PROFILE_VERSION,
        "title": profile_text(profile.get("title"), "title", 120),
        "subtitle": profile_text(profile.get("subtitle"), "subtitle", 500),
        "story": story,
        "theme": "evidence-dark",
        "spatial_scope": spatial_scope,
        "default_region": default_region,
        "custom_region": custom_region,
        "filters": normalized_filters,
        "comparison": normalized_comparison,
        "display": {key: display[key] for key in sorted(display_keys)},
    }


def selected_region(profile: Mapping[str, Any]) -> dict[str, Any]:
    region = (
        profile["custom_region"]
        if profile["default_region"] == "custom"
        else REGION_PRESETS[profile["default_region"]]
    )
    selected = {"label": str(region["label"]), "bounds": dict(region["bounds"])}
    if region.get("country_code"):
        selected["country_code"] = str(region["country_code"])
        if region.get("analysis_country_codes"):
            selected["analysis_country_codes"] = [
                str(code) for code in region["analysis_country_codes"]
            ]
    selected["clip_method"] = (
        "country_polygon_and_bbox" if region.get("country_code") else "bbox"
    )
    # Cartographic emphasis is independent of clipping: an explicit
    # highlight list wins, otherwise the analysis/clip countries frame the
    # view, otherwise nothing is emphasised.
    highlight = region.get("highlight_country_codes") or region.get(
        "analysis_country_codes"
    )
    if not highlight and region.get("country_code"):
        highlight = [region["country_code"]]
    if highlight:
        selected["highlight_country_codes"] = [str(code) for code in highlight]
    return selected


def visualization_profile_warnings(
    profile: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    anomaly_ids: set[str],
    countries_by_code: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    method_values = {
        str(
            record.get("method_family")
            or record.get("analytical_method")
            or MISSING_METHOD_LABEL
        )
        for record in records
    }
    available = {
        "element": {
            str(record.get("element")) for record in records if record.get("element")
        },
        "medium": {
            str(record.get("medium")) for record in records if record.get("medium")
        },
        "sample_type": {
            str(record.get("sample_type"))
            for record in records
            if record.get("sample_type")
        },
        "basis": {
            str(record.get("measurement_basis"))
            for record in records
            if record.get("measurement_basis")
        },
        "geology": {
            str(record.get("geologic_unit"))
            for record in records
            if record.get("geologic_unit")
        },
        "method": method_values,
        "method_scope": {
            str(record.get("method_scope"))
            for record in records
            if record.get("method_scope")
        },
        "source": {
            str(record.get("source_id"))
            for record in records
            if record.get("source_id")
        },
        "confidence": {
            str(record.get("confidence_band"))
            for record in records
            if record.get("confidence_band")
        },
    }
    warnings = []
    for key, requested in profile["filters"].items():
        if requested and requested not in available[key]:
            warnings.append(f"请求筛选值在当前数据中未观测到：{key}={requested}")
    for key in ("x", "y"):
        requested = profile["comparison"].get(key)
        if requested and requested not in available["element"]:
            warnings.append(f"请求的组合元素在当前数据中未观测到：{key}={requested}")
    requested_medium = profile["comparison"].get("medium")
    if requested_medium and requested_medium not in available["medium"]:
        warnings.append(f"请求的组合介质在当前数据中未观测到：{requested_medium}")
    region = selected_region(profile)
    region_records = [
        record
        for record in records
        if coordinate_in_region(
            float(record["longitude"]),
            float(record["latitude"]),
            region,
            countries_by_code,
        )
    ]
    if not region_records:
        warnings.append("默认区域没有可上图记录；页面将显示覆盖缺口")
    filters = profile["filters"]
    field_map = {
        "element": "element",
        "medium": "medium",
        "sample_type": "sample_type",
        "basis": "measurement_basis",
        "geology": "geologic_unit",
        "source": "source_id",
        "confidence": "confidence_band",
        "method_scope": "method_scope",
    }

    def matches_filters(record: Mapping[str, Any]) -> bool:
        for profile_key, record_key in field_map.items():
            requested = filters.get(profile_key)
            if requested and record.get(record_key) != requested:
                return False
        requested_method = filters.get("method")
        method = (
            record.get("method_family")
            or record.get("analytical_method")
            or MISSING_METHOD_LABEL
        )
        return not requested_method or method == requested_method

    configured_records = [
        record for record in region_records if matches_filters(record)
    ]
    if region_records and not configured_records:
        warnings.append("默认区域与筛选组合没有可上图记录")
    if profile["story"] == "anomaly" and not any(
        str(record.get("record_id")) in anomaly_ids for record in configured_records
    ):
        warnings.append("当前异常任务配置没有匹配的 D2 候选")
    return warnings


def load_anomalies(path: Path) -> dict[str, Any]:
    value = load_json_object(path, "anomalies GeoJSON")
    if value.get("type") != "FeatureCollection" or not isinstance(
        value.get("features"), list
    ):
        raise MapBuildError("anomalies input must be a GeoJSON FeatureCollection")
    return value


def load_basemap(path: Path) -> dict[str, Any]:
    value = load_json_object(path, "offline basemap")
    rings = value.get("rings")
    if (
        value.get("asset_version") != BASEMAP_ASSET_VERSION
        or value.get("license") != "public domain"
        or not isinstance(rings, list)
        or not rings
        or len(rings) > 1_000
    ):
        raise MapBuildError("offline basemap provenance or structure is invalid")
    point_count = 0
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 3:
            raise MapBuildError("offline basemap contains an invalid polygon ring")
        for point in ring:
            point_count += 1
            if (
                not isinstance(point, list)
                or len(point) != 2
                or optional_float(point[0]) is None
                or optional_float(point[1]) is None
                or not (-180 <= float(point[0]) <= 180)
                or not (-90 <= float(point[1]) <= 90)
            ):
                raise MapBuildError("offline basemap contains an invalid coordinate")
    if point_count > 100_000:
        raise MapBuildError("offline basemap exceeds the point safety limit")
    return {
        "asset_version": value["asset_version"],
        "title": value.get("title", "Natural Earth land"),
        "natural_earth_version": value.get("natural_earth_version"),
        "scale": value.get("scale", "1:110m"),
        "coordinate_reference_system": value.get(
            "coordinate_reference_system", "WGS84 longitude/latitude"
        ),
        "source_page": value.get("source_page"),
        "license": value["license"],
        "archive_sha256": value.get("archive_sha256"),
        "point_count": point_count,
        "rings": rings,
    }


def load_country_boundaries(path: Path) -> dict[str, Any]:
    value = load_json_object(path, "offline country boundaries")
    countries = value.get("countries")
    if (
        value.get("asset_version") != BOUNDARY_ASSET_VERSION
        or value.get("license") != "public domain"
        or not isinstance(countries, list)
        or not countries
        or len(countries) > 300
    ):
        raise MapBuildError(
            "offline country boundary provenance or structure is invalid"
        )
    point_total = 0
    seen: set[str] = set()
    normalized = []
    for country in countries:
        if not isinstance(country, dict):
            raise MapBuildError("offline country boundary contains an invalid country")
        iso_a3 = country.get("iso_a3")
        geometry = country.get("geometry")
        if (
            not isinstance(iso_a3, str)
            or len(iso_a3) != 3
            or iso_a3 in seen
            or not isinstance(geometry, dict)
            or geometry.get("type") not in {"Polygon", "MultiPolygon"}
        ):
            raise MapBuildError(
                "offline country boundary identifiers or geometry are invalid"
            )
        seen.add(iso_a3)
        polygons = geometry_polygons(geometry)
        if not polygons:
            raise MapBuildError("offline country boundary has no polygon")
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                raise MapBuildError("offline country boundary has an invalid polygon")
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4:
                    raise MapBuildError("offline country boundary has an invalid ring")
                for point in ring:
                    point_total += 1
                    if (
                        not isinstance(point, list)
                        or len(point) != 2
                        or optional_float(point[0]) is None
                        or optional_float(point[1]) is None
                        or not (-180 <= float(point[0]) <= 180)
                        or not (-90 <= float(point[1]) <= 90)
                    ):
                        raise MapBuildError(
                            "offline country boundary has an invalid coordinate"
                        )
        normalized.append(country)
    if point_total > 200_000 or value.get("point_count") != point_total:
        raise MapBuildError("offline country boundary point count is invalid")
    required = {"CHN", "USA", "AUS"}
    if not required.issubset(seen):
        raise MapBuildError("offline country boundary omits a supported strict country")
    return {
        "asset_version": value["asset_version"],
        "title": value.get("title"),
        "natural_earth_version": value.get("natural_earth_version"),
        "scale": value.get("scale"),
        "coordinate_reference_system": value.get("coordinate_reference_system"),
        "source_page": value.get("source_page"),
        "source_geojson_url": value.get("source_geojson_url"),
        "source_commit": value.get("source_commit"),
        "source_sha256": value.get("source_sha256"),
        "license": value["license"],
        "boundary_semantics": value.get("boundary_semantics"),
        "country_count": len(normalized),
        "point_count": point_total,
        "countries": normalized,
    }


def load_admin1_boundaries(path: Path) -> dict[str, Any]:
    """Load optional generalized China province linework for visual orientation."""
    value = load_json_object(path, "offline China Admin-1 visual boundaries")
    boundaries = value.get("boundaries")
    if (
        value.get("asset_version") != ADMIN1_BOUNDARY_ASSET_VERSION
        or value.get("license") != "public domain"
        or value.get("country_iso_a3") != "CHN"
        or not isinstance(boundaries, list)
        or len(boundaries) != 31
    ):
        raise MapBuildError(
            "offline China Admin-1 boundary provenance or structure is invalid"
        )
    point_total = 0
    normalized: list[dict[str, Any]] = []
    for boundary in boundaries:
        if not isinstance(boundary, dict) or not str(boundary.get("name") or ""):
            raise MapBuildError("offline China Admin-1 boundary has an invalid name")
        geometry = boundary.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("type") not in {
            "Polygon",
            "MultiPolygon",
        }:
            raise MapBuildError(
                "offline China Admin-1 boundary has an invalid geometry"
            )
        polygons = geometry_polygons(geometry)
        if not polygons:
            raise MapBuildError("offline China Admin-1 boundary has no polygon")
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                raise MapBuildError(
                    "offline China Admin-1 boundary has an invalid polygon"
                )
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4:
                    raise MapBuildError(
                        "offline China Admin-1 boundary has an invalid ring"
                    )
                for point in ring:
                    point_total += 1
                    if (
                        not isinstance(point, list)
                        or len(point) != 2
                        or optional_float(point[0]) is None
                        or optional_float(point[1]) is None
                        or not (-180 <= float(point[0]) <= 180)
                        or not (-90 <= float(point[1]) <= 90)
                    ):
                        raise MapBuildError(
                            "offline China Admin-1 boundary has an invalid coordinate"
                        )
        normalized.append(boundary)
    if point_total > 50_000 or value.get("point_count") != point_total:
        raise MapBuildError("offline China Admin-1 boundary point count is invalid")
    return {
        "asset_version": value["asset_version"],
        "title": value.get("title"),
        "natural_earth_version": value.get("natural_earth_version"),
        "country_iso_a3": value["country_iso_a3"],
        "source_geojson_url": value.get("source_geojson_url"),
        "source_commit": value.get("source_commit"),
        "source_sha256": value.get("source_sha256"),
        "license": value["license"],
        "boundary_semantics": value.get("boundary_semantics"),
        "boundary_count": len(normalized),
        "point_count": point_total,
        "boundaries": normalized,
    }


def sample_display_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("source_id"),
        record.get("sample_id") or record.get("record_id"),
        record.get("medium"),
        record.get("longitude"),
        record.get("latitude"),
    )


def _stable_group_digest(key: tuple[Any, ...]) -> str:
    return hashlib.sha256(
        json.dumps(key, ensure_ascii=False, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def coverage_preserving_map_preview(
    records: Sequence[Mapping[str, Any]],
    anomaly_ids: set[str],
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Select a deterministic physical-sample preview without changing the CSV.

    The browser does not need every overlapping analyte row to communicate
    coverage.  Keep whole physical-sample groups, every candidate-anomaly
    group, and at least one group per source × medium × element × coarse cell;
    use a stable hash to fill remaining capacity.  The complete canonical CSV
    and aggregate charts remain unsampled.
    """

    if limit < 1:
        raise MapBuildError("map preview limit must be positive")
    normalized_records = [dict(record) for record in records]
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for record in normalized_records:
        groups.setdefault(sample_display_key(record), []).append(record)
    if len(normalized_records) <= limit:
        return normalized_records, {
            "policy_version": "d3-coverage-preserving-preview-v2",
            "applied": False,
            "input_record_count": len(normalized_records),
            "embedded_record_count": len(normalized_records),
            "input_physical_sample_count": len(groups),
            "embedded_physical_sample_count": len(groups),
            "maximum_embedded_records": limit,
            "byte_budget_bytes": EMBED_TARGET_BYTES,
            "limit_basis": "single_file_byte_budget",
            "stratification_cell_degrees": None,
            "candidate_anomaly_records_preserved": True,
            "whole_physical_sample_groups_preserved": True,
            "complete_database_artifact": "geochemistry.csv",
        }

    digests = {key: _stable_group_digest(key) for key in groups}
    mandatory = {
        key
        for key, grouped in groups.items()
        if any(str(record.get("record_id")) in anomaly_ids for record in grouped)
    }
    mandatory_records = sum(len(groups[key]) for key in mandatory)
    if mandatory_records > limit:
        raise MapBuildError(
            "candidate-anomaly physical samples exceed the map preview limit; "
            "raise --max-embedded-records rather than dropping anomaly evidence"
        )

    def preview_cell(record: Mapping[str, Any], degrees: float) -> str:
        longitude = float(record["longitude"])
        latitude = float(record["latitude"])
        lon_index = min(
            math.ceil(360.0 / degrees) - 1,
            max(0, math.floor((longitude + 180.0) / degrees)),
        )
        lat_index = min(
            math.ceil(180.0 / degrees) - 1,
            max(0, math.floor((latitude + 90.0) / degrees)),
        )
        return f"{degrees:g}:{lat_index}:{lon_index}"

    selected: set[tuple[Any, ...]] = set(mandatory)
    chosen_degrees = 360.0
    for degrees in (5.0, 10.0, 20.0, 40.0, 90.0, 360.0):
        representatives: dict[tuple[str, str, str, str], tuple[Any, ...]] = {}
        for group_key, grouped in groups.items():
            for record in grouped:
                stratum = (
                    str(record.get("source_id") or "unknown"),
                    str(record.get("medium") or "unknown"),
                    str(record.get("element") or "unknown"),
                    preview_cell(record, degrees),
                )
                current = representatives.get(stratum)
                if current is None or digests[group_key] < digests[current]:
                    representatives[stratum] = group_key
        candidate = mandatory.union(representatives.values())
        if sum(len(groups[key]) for key in candidate) <= limit:
            selected = set(candidate)
            chosen_degrees = degrees
            break

    selected_record_count = sum(len(groups[key]) for key in selected)
    for group_key in sorted(groups, key=lambda key: digests[key]):
        if group_key in selected:
            continue
        next_size = selected_record_count + len(groups[group_key])
        if next_size <= limit:
            selected.add(group_key)
            selected_record_count = next_size
    preview = [
        record
        for record in normalized_records
        if sample_display_key(record) in selected
    ]
    preserved_anomaly_ids = {
        str(record.get("record_id"))
        for record in preview
        if str(record.get("record_id")) in anomaly_ids
    }
    expected_anomaly_ids = {
        str(record.get("record_id"))
        for record in normalized_records
        if str(record.get("record_id")) in anomaly_ids
    }
    return preview, {
        "policy_version": "d3-coverage-preserving-preview-v2",
        "applied": True,
        "input_record_count": len(normalized_records),
        "embedded_record_count": len(preview),
        "input_physical_sample_count": len(groups),
        "embedded_physical_sample_count": len(selected),
        "maximum_embedded_records": limit,
        "byte_budget_bytes": EMBED_TARGET_BYTES,
        "limit_basis": "single_file_byte_budget",
        "stratification_cell_degrees": chosen_degrees,
        "candidate_anomaly_records_preserved": (
            preserved_anomaly_ids == expected_anomaly_ids
        ),
        "candidate_anomaly_record_count": len(expected_anomaly_ids),
        "whole_physical_sample_groups_preserved": True,
        "strata": "source_id × medium × element × coarse spatial cell",
        "selection_tiebreaker": "SHA-256 of the physical-sample display key",
        "complete_database_artifact": "geochemistry.csv",
        "claim_boundary": (
            "The map is a coverage-preserving interactive preview. Aggregate "
            "database charts and geochemistry.csv use the full canonical population."
        ),
    }


def region_coverage(
    records: Sequence[Mapping[str, Any]],
    countries_by_code: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for key, region in REGION_PRESETS.items():
        bounds = region["bounds"]
        matched = [
            record
            for record in records
            if coordinate_in_region(
                float(record["longitude"]),
                float(record["latitude"]),
                region,
                countries_by_code,
            )
        ]
        coverage[key] = {
            "label": region["label"],
            "bounds": dict(bounds),
            "record_count": len(matched),
            "sample_count": len({sample_display_key(record) for record in matched}),
            "elements": sorted(
                {
                    str(record.get("element"))
                    for record in matched
                    if record.get("element")
                }
            ),
            "media": sorted(
                {
                    str(record.get("medium"))
                    for record in matched
                    if record.get("medium")
                }
            ),
            "administrative_clip": bool(region.get("country_code")),
            "clip_method": (
                "country_polygon_and_bbox" if region.get("country_code") else "bbox"
            ),
        }
    return coverage


def data_coverage_diagnostics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    media: dict[str, dict[str, Any]] = {}
    evidence_layer_counts: dict[str, int] = {}
    provenance_status_counts: dict[str, int] = {}
    quality_control_status_counts: dict[str, int] = {}
    for record in records:
        medium = str(record.get("medium") or "unknown")
        item = media.setdefault(
            medium,
            {
                "record_count": 0,
                "sample_keys": set(),
                "method_missing_record_count": 0,
            },
        )
        item["record_count"] += 1
        item["sample_keys"].add(sample_display_key(record))
        if not record.get("method_family") and not record.get("analytical_method"):
            item["method_missing_record_count"] += 1
        for counts, field, fallback in (
            (evidence_layer_counts, "evidence_layer", PROVENANCE_INCOMPLETE_LAYER),
            (provenance_status_counts, "provenance_status", "incomplete"),
            (quality_control_status_counts, "quality_control_status", "not_evaluated"),
        ):
            value = str(record.get(field) or fallback)
            counts[value] = counts.get(value, 0) + 1
    normalized_media = {}
    for medium, item in sorted(media.items()):
        normalized_media[medium] = {
            "record_count": item["record_count"],
            "sample_count": len(item["sample_keys"]),
            "method_missing_record_count": item["method_missing_record_count"],
            "method_completeness_rate": round(
                1 - item["method_missing_record_count"] / item["record_count"], 6
            ),
        }
    missing_method = sum(
        not record.get("method_family") and not record.get("analytical_method")
        for record in records
    )
    missing_geology = sum(not record.get("geologic_unit") for record in records)
    missing_background = sum(
        not record.get("geologic_unit")
        and not record.get("publisher_geological_background")
        for record in records
    )
    return {
        "by_medium": normalized_media,
        "method_missing_record_count": missing_method,
        "method_completeness_rate": round(1 - missing_method / len(records), 6)
        if records
        else None,
        "geologic_unit_missing_record_count": missing_geology,
        "geologic_unit_completeness_rate": round(1 - missing_geology / len(records), 6)
        if records
        else None,
        "geological_background_missing_record_count": missing_background,
        "geological_background_completeness_rate": round(
            1 - missing_background / len(records), 6
        )
        if records
        else None,
        "evidence_layer_counts": dict(sorted(evidence_layer_counts.items())),
        "strict_scientific_ready_rate": round(
            evidence_layer_counts.get(STRICT_SCIENTIFIC_LAYER, 0) / len(records), 6
        )
        if records
        else None,
        "provenance_status_counts": dict(sorted(provenance_status_counts.items())),
        "quality_control_status_counts": dict(
            sorted(quality_control_status_counts.items())
        ),
        "sample_type_field": "medium",
        "analysis_method_fields": ["analytical_method", "method_family"],
        "interpretation": (
            "Sample type and analytical method are independent fields; media count imbalance "
            "describes input coverage, not concentration or anomaly prevalence."
        ),
    }


def samples_geojson(
    records: Sequence[Mapping[str, Any]],
    anomaly_ids: set[str],
    profile: Mapping[str, Any],
    scope_region: Mapping[str, Any],
    coordinate_mode: str = "canonical",
    map_preview_sampling: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # GeoJSON is a spatial exchange view, not a second copy of the complete
    # canonical database.  Repeating fifty-plus provenance/method fields on
    # every feature made a 109k-record atlas exceed 250 MB even though the
    # compact self-contained HTML was only 45 MB.  Keep every eligible feature
    # and its stable database join key, but expose only fields needed for GIS
    # filtering plus one clearly named workflow band. Full confidence
    # dimensions, QC flags, provenance, methods, raw values and clickable links
    # remain losslessly available in geochemistry.csv through ``record_id``.
    # Large runs expose the same explicitly-attested, coverage-preserving
    # preview in GeoJSON and HTML; neither artifact pretends to replace the CSV.
    property_fields = (
        "record_id",
        "element",
        "medium",
        "value",
        "unit",
        "source_id",
        "confidence_workflow_usability_band",
        "coordinate_basis",
    )
    features = []
    for record in records:
        properties = {key: record.get(key) for key in property_fields}
        properties["candidate_anomaly"] = str(record["record_id"]) in anomaly_ids
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [record["longitude"], record["latitude"]],
                },
                "properties": properties,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "standardized_geochemical_samples",
        "map_version": MAP_VERSION,
        "property_contract_version": SAMPLES_GEOJSON_PROPERTY_VERSION,
        "database_join_key": "record_id",
        "property_scope": (
            "compact coverage-preserving spatial preview; join geochemistry.csv "
            "on record_id for the complete population, raw values, methods, "
            "provenance and source links"
        ),
        "map_preview_sampling": dict(map_preview_sampling or {}),
        "coordinate_mode": coordinate_mode,
        "spatial_scope": {
            "mode": profile["spatial_scope"],
            "region_key": profile["default_region"],
            "region_label": scope_region["label"],
            "bounds": dict(scope_region["bounds"]),
            "country_code": scope_region.get("country_code"),
            "highlight_country_codes": list(
                scope_region.get("highlight_country_codes") or []
            ),
            "clip_method": scope_region["clip_method"],
            "output_clipped": profile["spatial_scope"] == "regional",
        },
        "features": features,
    }


PACKED_FIELDS = (
    "longitude",
    "latitude",
    "record_id",
    "sample_id",
    "element",
    "analyte_reported",
    "medium",
    "spatial_domain",
    "material",
    "sample_type_raw",
    "sample_type",
    "measurement_basis",
    "original_value_raw",
    "original_value",
    "original_unit",
    "source_qualifier_raw",
    "qualifier",
    "censored",
    "censoring_limit",
    "value",
    "unit",
    "lithology",
    "geologic_unit",
    "formal_geologic_unit",
    "publisher_geological_background",
    "geological_context_status",
    "analytical_method",
    "method_family",
    "method_scope",
    "digestion_or_extraction",
    "preparation",
    "grain_fraction",
    "reference_materials",
    "source_id",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_locator",
    "official_source_url",
    "license",
    "confidence_band",
    "confidence_overall",
    "confidence_source_evidence_band",
    "confidence_source_evidence_score",
    "confidence_analytical_readiness_band",
    "confidence_analytical_readiness_score",
    "confidence_spatial_usability_band",
    "confidence_spatial_usability_score",
    "confidence_workflow_usability_band",
    "confidence_workflow_usability_score",
    "confidence_source",
    "confidence_completeness",
    "confidence_method",
    "confidence_spatial",
    "confidence_qc",
    "qc_flags",
    "candidate_anomaly",
    "coordinate_basis",
    "coordinate_uncertainty_m",
    "coordinate_representation_resolution_m",
    "coordinate_representation_resolution_basis",
    "coordinate_accuracy_evidence_status",
    "method_source_locator",
    "method_missing_reason",
    "geology_missing_reason",
    "evidence_layer",
    "provenance_status",
    "quality_control_status",
    "scientific_readiness_reasons",
    "missing_provenance_fields",
    "blocking_qc_flags",
)


def compact_map_payload(
    records: Sequence[Mapping[str, Any]], anomaly_ids: set[str]
) -> dict[str, Any]:
    """Pack repeated strings and property names for a smaller self-contained HTML."""
    strings: list[str] = []
    indexes: dict[str, int] = {}

    def string_index(value: Any) -> int:
        if value is None or value == "":
            return -1
        text = str(value)
        if text not in indexes:
            indexes[text] = len(strings)
            strings.append(text)
        return indexes[text]

    packed_rows: list[list[Any]] = []
    for record in records:
        confidence = record.get("confidence_components") or {}
        packed_rows.append(
            [
                record.get("longitude"),
                record.get("latitude"),
                string_index(record.get("record_id")),
                string_index(record.get("sample_id")),
                string_index(record.get("element")),
                string_index(record.get("analyte_reported")),
                string_index(record.get("medium")),
                string_index(record.get("spatial_domain")),
                string_index(record.get("material")),
                string_index(record.get("sample_type_raw")),
                string_index(record.get("sample_type")),
                string_index(record.get("measurement_basis")),
                string_index(record.get("original_value_raw")),
                record.get("original_value"),
                string_index(record.get("original_unit")),
                string_index(record.get("source_qualifier_raw")),
                string_index(record.get("qualifier")),
                1 if record.get("censored") else 0,
                record.get("censoring_limit"),
                record.get("value"),
                string_index(record.get("unit")),
                string_index(record.get("lithology")),
                string_index(record.get("geologic_unit")),
                string_index(record.get("formal_geologic_unit")),
                string_index(record.get("publisher_geological_background")),
                string_index(record.get("geological_context_status")),
                string_index(record.get("analytical_method")),
                string_index(record.get("method_family")),
                string_index(record.get("method_scope")),
                string_index(record.get("digestion_or_extraction")),
                string_index(record.get("preparation")),
                string_index(record.get("grain_fraction")),
                string_index(record.get("reference_materials")),
                string_index(record.get("source_id")),
                string_index(record.get("dataset_title")),
                string_index(record.get("dataset_doi")),
                string_index(record.get("dataset_version")),
                string_index(record.get("source_locator")),
                string_index(record.get("official_source_url")),
                string_index(record.get("license")),
                string_index(record.get("confidence_band")),
                record.get("confidence_overall"),
                string_index(record.get("confidence_source_evidence_band")),
                record.get("confidence_source_evidence_score"),
                string_index(record.get("confidence_analytical_readiness_band")),
                record.get("confidence_analytical_readiness_score"),
                string_index(record.get("confidence_spatial_usability_band")),
                record.get("confidence_spatial_usability_score"),
                string_index(record.get("confidence_workflow_usability_band")),
                record.get("confidence_workflow_usability_score"),
                confidence.get("source"),
                confidence.get("completeness"),
                confidence.get("method"),
                confidence.get("spatial"),
                confidence.get("qc"),
                [string_index(flag) for flag in record.get("qc_flags", [])],
                1 if str(record.get("record_id")) in anomaly_ids else 0,
                string_index(record.get("coordinate_basis")),
                record.get("coordinate_uncertainty_m"),
                record.get("coordinate_representation_resolution_m"),
                string_index(record.get("coordinate_representation_resolution_basis")),
                string_index(record.get("coordinate_accuracy_evidence_status")),
                string_index(record.get("method_source_locator")),
                string_index(record.get("method_missing_reason")),
                string_index(record.get("geology_missing_reason")),
                string_index(record.get("evidence_layer")),
                string_index(record.get("provenance_status")),
                string_index(record.get("quality_control_status")),
                [
                    string_index(item)
                    for item in record.get("scientific_readiness_reasons", [])
                ],
                [
                    string_index(item)
                    for item in record.get("missing_provenance_fields", [])
                ],
                [string_index(item) for item in record.get("blocking_qc_flags", [])],
            ]
        )
    return {
        "schema_version": PAYLOAD_VERSION,
        "map_version": MAP_VERSION,
        "fields": list(PACKED_FIELDS),
        "strings": strings,
        "rows": packed_rows,
    }


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def safe_embedded_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def inject_reported_coordinate_banner(html: str, statistics: Mapping[str, Any]) -> str:
    """Insert a prominent unverified-datum warning strip right below <body>."""
    fallback = int(statistics["mapped_reported_fallback_records"])
    canonical = int(statistics["mapped_canonical_records"])
    unplottable = int(statistics["records_without_plottable_coordinates"])
    banner = (
        f'<div id="{REPORTED_BANNER_ID}" role="alert" style="position:sticky;'
        "top:0;z-index:99999;background:#7a5b00;color:#fff7df;"
        "padding:10px 16px;font:14px/1.5 system-ui,sans-serif;"
        'border-bottom:2px solid #ffd54d;">'
        f"⚠️ 报告坐标模式：{fallback} 条记录按来源报告坐标绘制"
        f"（{REPORTED_BANNER_PHRASE}），不作为 WGS84 精确位置依据"
        + (f"；{canonical} 条记录仍使用已验证的 WGS84 坐标" if canonical else "")
        + (
            f"；另有 {unplottable} 条记录无任何可用坐标，未上图并计入统计"
            if unplottable
            else ""
        )
        + "。Reported coordinates with an unverified datum are for indicative "
        "browsing only.</div>"
    )
    match = re.search(r"<body[^>]*>", html)
    if match is None:
        raise MapBuildError(
            "interactive map template lacks a <body> tag for the coordinate banner"
        )
    return html[: match.end()] + banner + html[match.end() :]


def load_html_template(path: Path = DEFAULT_TEMPLATE) -> str:
    if not path.is_file():
        raise MapBuildError(f"interactive map template does not exist: {path}")
    template = path.read_text(encoding="utf-8")
    required = {
        "__SAMPLES_JSON__",
        "__ANOMALIES_JSON__",
        "__BASEMAP_JSON__",
        "__BOUNDARIES_JSON__",
        "__ADMIN1_BOUNDARIES_JSON__",
        "__CONTEXT_JSON__",
        "__TEMPORAL_HTML_BASE64__",
        MAP_VERSION,
        PAYLOAD_VERSION,
        ANOMALY_RENDER_MODE,
        PROFILE_VERSION,
        UI_HIERARCHY_VERSION,
        TEMPLATE_CONTRACT_VERSION,
        VISUAL_QUESTION_VERSION,
        'id="deliverableCenter"',
        'id="databaseView"',
        'id="confidenceSummary"',
        'id="confidenceGateReasons"',
        'id="databaseDistributionCanvas"',
        'id="databaseCoverageMatrix"',
        'id="databaseBoxCanvas"',
        "d3-database-visual-summary-v1",
        'id="projectionMode"',
        'id="globe"',
        'id="anomalyDensityCanvas"',
        "不是正确概率",
        "来源证据画像（不是空间工作流评分）",
        "空间工作流复核（不等于数据质量）",
        'id="qualityDimension"',
        "工作流可用性 / 复核级别",
        'id="sourcePortfolioSummary"',
        'id="comboUniverse"',
        "returnToAnomalyRegion",
        "发布方未报告位置不确定度；不代表坐标无效或处理失败",
        'id="backView"',
        'id="databaseEditor"',
        'id="sourceTableBody"',
        'id="anomalyInspector"',
        'id="temporalView"',
        'id="temporalFrame"',
        'id="autoResearchView"',
        'id="autoResearchForm"',
        "startAutoResearch",
        'id="exportComparisonProfile"',
        "comparisonProfile",
        "officialSourceLinks",
        "记录级文件定位",
        "官方来源 / DOI",
        "来源声明坐标不确定度",
        "坐标表达分辨率（非位置精度）",
        "方法缺失责任",
        "坐标精度证据状态",
        "管线输入未记账（需修复）",
        "中国省级参考线",
        "Natural Earth 1:50m Admin‑1",
        "zoom-aware-pixel-lod-v1",
        "数据缺口与处理状态",
        "发布方样品描述",
        "标准化样品类型（Skill 控制词）",
        "综合工作流可用性（非概率）",
        "record ID（点击展开）",
    }
    missing = sorted(marker for marker in required if marker not in template)
    if missing:
        raise MapBuildError(
            f"interactive map template missing markers: {', '.join(missing)}"
        )
    return template


def build_map(
    database: Path,
    anomalies_path: Path,
    output_html: Path,
    output_geojson: Path,
    max_points: int = 200_000,
    max_embedded_records: int = DEFAULT_MAX_EMBEDDED_RECORDS,
    qc_report_path: Path | None = None,
    confidence_report_path: Path | None = None,
    source_manifest_path: Path | None = None,
    sources_and_confidence_path: Path | None = None,
    anomaly_report_path: Path | None = None,
    anomaly_regions_path: Path | None = None,
    spatial_anomaly_report_path: Path | None = None,
    iteration_backlog_path: Path | None = None,
    basemap_path: Path = DEFAULT_BASEMAP,
    visualization_profile_path: Path | None = None,
    boundaries_path: Path = DEFAULT_BOUNDARIES,
    admin1_boundaries_path: Path = DEFAULT_ADMIN1_BOUNDARIES,
    coordinate_mode: str = "canonical",
    temporal_html_path: Path | None = None,
) -> dict[str, Any]:
    if max_points < 1 or max_points > 200_000:
        raise MapBuildError("--max-points must be between 1 and 200000")
    if max_embedded_records < 1 or max_embedded_records > max_points:
        raise MapBuildError("--max-embedded-records must be between 1 and --max-points")
    profile = load_visualization_profile(visualization_profile_path)
    scope_region = selected_region(profile)
    database_summary = database_visual_summary(database)
    boundaries = load_country_boundaries(boundaries_path)
    admin1_boundaries = load_admin1_boundaries(admin1_boundaries_path)
    countries_by_code = {
        str(country["iso_a3"]): country for country in boundaries["countries"]
    }
    unknown_highlights = [
        code
        for code in scope_region.get("highlight_country_codes") or []
        if code not in countries_by_code
    ]
    if unknown_highlights:
        raise MapBuildError(
            "highlight_country_codes reference countries missing from the "
            f"offline Admin-0 asset: {', '.join(unknown_highlights)}"
        )
    records, coordinate_counts = load_records(
        database, max_points, scope_region, countries_by_code, coordinate_mode
    )
    full_scope_records = records
    total_records = coordinate_counts["total_records"]
    source_mappable_records = (
        coordinate_counts["canonical_coordinate_records"]
        + coordinate_counts["reported_fallback_records"]
    )
    scope_excludes_all_records = False
    if not records:
        if (
            coordinate_mode == "canonical"
            and coordinate_counts["reported_only_records"]
        ):
            raise MapBuildError(
                "0 records carry canonical WGS84 coordinates, but "
                f"{coordinate_counts['reported_only_records']} records carry "
                "reported-only coordinates whose datum is unverified. Do not "
                "hand-write map HTML. Rerun with --coordinate-mode reported to "
                "draw an explicitly-flagged indicative map, or register datum "
                "evidence in references/coordinate-policy-registry.json"
            )
        if not source_mappable_records:
            raise MapBuildError(
                "no record carries plottable coordinates (canonical or "
                "reported); an empty interactive map must not be delivered - "
                "report the coverage gap instead"
            )
        # An explicitly requested scope may legitimately contain zero records;
        # the map still renders the basemap, boundaries and scope frame, and
        # the emptiness is declared as a warning instead of a hard failure.
        scope_excludes_all_records = True
    mapped_reported_fallback = sum(
        record["coordinate_basis"] == COORDINATE_BASIS_REPORTED
        for record in full_scope_records
    )
    coordinate_statistics = {
        "coordinate_mode": coordinate_mode,
        **coordinate_counts,
        "mapped_record_count": len(full_scope_records),
        "mapped_canonical_records": len(full_scope_records) - mapped_reported_fallback,
        "mapped_reported_fallback_records": mapped_reported_fallback,
    }
    reported_banner = mapped_reported_fallback > 0
    anomalies = load_anomalies(anomalies_path)
    anomaly_regions = (
        load_anomalies(anomaly_regions_path)
        if anomaly_regions_path is not None
        else {"type": "FeatureCollection", "features": []}
    )
    basemap = load_basemap(basemap_path)
    anomaly_ids = {
        str(feature.get("properties", {}).get("record_id"))
        for feature in anomalies["features"]
        if feature.get("properties", {}).get("record_id") is not None
    }
    records, map_preview = coverage_preserving_map_preview(
        full_scope_records, anomaly_ids, max_embedded_records
    )
    coordinate_statistics["embedded_record_count"] = len(records)
    coordinate_statistics["embedded_canonical_records"] = sum(
        record["coordinate_basis"] == COORDINATE_BASIS_CANONICAL for record in records
    )
    coordinate_statistics["embedded_reported_fallback_records"] = sum(
        record["coordinate_basis"] == COORDINATE_BASIS_REPORTED for record in records
    )
    scoped_record_ids = {str(record["record_id"]) for record in records}
    scoped_anomalies = {
        **anomalies,
        "features": [
            feature
            for feature in anomalies["features"]
            if str(feature.get("properties", {}).get("record_id")) in scoped_record_ids
        ],
    }
    profile_warnings = visualization_profile_warnings(
        profile, records, anomaly_ids, countries_by_code
    )
    if map_preview["applied"]:
        profile_warnings.append(
            "交互地图为覆盖保持预览：内嵌 "
            f"{map_preview['embedded_record_count']}/{map_preview['input_record_count']} "
            "条范围内可绘记录；完整记录、聚合统计与来源链保留在 geochemistry.csv。"
        )
    if scope_excludes_all_records:
        profile_warnings.append(
            "选定区域范围内没有可绘制记录"
            f"（0/{source_mappable_records} 条可绘源数据落入范围）；"
            "主画布仅显示底图与区域框架，请核对 bbox 或扩大范围。"
        )
    geojson = samples_geojson(
        records,
        anomaly_ids,
        profile,
        scope_region,
        coordinate_mode,
        map_preview,
    )
    map_payload = compact_map_payload(records, anomaly_ids)
    spatial_scope = {
        "mode": profile["spatial_scope"],
        "region_key": profile["default_region"],
        "region_label": scope_region["label"],
        "bounds": dict(scope_region["bounds"]),
        "country_code": scope_region.get("country_code"),
        "highlight_country_codes": list(
            scope_region.get("highlight_country_codes") or []
        ),
        "clip_method": scope_region["clip_method"],
        "output_clipped": profile["spatial_scope"] == "regional",
    }
    capability_matrix = {
        "filter_dimensions": {
            "element": True,
            "region": True,
            "geologic_unit": True,
            "sample_type_medium": True,
        },
        "outputs": {
            "global_or_regional_distribution_map": True,
            "global_interactive_globe": True,
            "regional_focus_template": True,
            "clickable_sample_density_heatmap": True,
            "concentration_classified_points": True,
            "database_distribution_charts": True,
            "anomaly_candidate_density_surface": True,
            "element_pair_comparison": True,
            "enrichment_and_depletion_candidates": True,
            "statistically_screened_anomaly_regions": anomaly_regions_path is not None,
        },
        "deliverables": {
            "standardized_database_first_class_ui": True,
            "confidence_and_sources_first_class_ui": True,
            "anomaly_results_first_class_ui": True,
            "interactive_map_first_class_ui": True,
            "iteration_backlog_first_class_ui": True,
            "temporal_evolution_first_class_ui": True,
            "auto_research_continuation_first_class_ui": True,
        },
        "interaction_design": {
            "hierarchy_version": UI_HIERARCHY_VERSION,
            "template_contract_version": TEMPLATE_CONTRACT_VERSION,
            "terminology_contract": TERMINOLOGY_CONTRACT,
            "single_primary_navigation": True,
            "compact_deliverable_dock": True,
            "collapsible_deliverable_dock": True,
            "professional_navigation_labels": True,
            "combination_region_selector": True,
            "combination_custom_bbox": True,
            "regional_combination_scope_lock_supported": True,
            "comparison_profile_export": True,
            "formal_comparison_requires_profile_rerender": True,
            "four_primary_map_controls": True,
            "four_top_level_kpis": True,
            "advanced_filters_progressive_disclosure": True,
            "duplicate_story_selector": False,
            "recoverable_map_navigation": True,
            "keyboard_map_navigation": True,
            "single_world_no_repeat_planar_navigation": True,
            "regional_pan_without_scope_expansion": True,
            "optional_china_admin1_orientation_boundaries": True,
            "localized_measurement_basis": True,
            "research_patch_crud": "proposal_only_no_direct_mutation",
        },
        "scientific_semantics": {
            "visual_question_contract": VISUAL_QUESTION_VERSION,
            "heatmap_encodes": "physical_sample_density",
            "heatmap_interpolates_concentration": False,
            "anomaly_density_surface_encodes": "candidate observation density only",
            "anomaly_density_surface_interpolates_concentration": False,
            "anomaly_basis": "D2 robust z within declared comparable background groups",
            "anomaly_region_semantics": (
                "D2 fixed-cell candidate over-representation with BH-FDR is supplied separately; "
                "D3 zoom bubbles remain count-only visual aggregation"
            ),
            "anomaly_contrast": "candidate_vs_comparable_group_median_and_robust_thresholds",
            "element_pair_analysis": "log10_scatter_median_quadrant_shares_spearman_and_coverage_matrix",
        },
    }
    template = load_html_template()
    if temporal_html_path is None:
        temporal_document = (
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>"
            "<title>时序视图未生成</title><body><h1>时序视图未生成</h1>"
            "<p>请使用 run_workflow.py 生成完整图谱。</p></body></html>"
        ).encode("utf-8")
        temporal_embedded = False
        temporal_sha256 = None
    else:
        if temporal_html_path.is_symlink() or not temporal_html_path.is_file():
            raise MapBuildError("temporal HTML must be a regular file")
        temporal_document = temporal_html_path.read_bytes()
        if len(temporal_document) > 20_000_000:
            raise MapBuildError("temporal HTML exceeds the 20 MB embedding limit")
        try:
            temporal_document.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MapBuildError("temporal HTML must be UTF-8") from exc
        temporal_embedded = True
        temporal_sha256 = hashlib.sha256(temporal_document).hexdigest()
    temporal_base64 = base64.b64encode(temporal_document).decode("ascii")
    template_sha256 = hashlib.sha256(template.encode("utf-8")).hexdigest()
    template_variant = (
        "regional_focus" if profile["spatial_scope"] == "regional" else "global_globe"
    )
    coverage_diagnostics = data_coverage_diagnostics(full_scope_records)
    context = {
        "map_version": MAP_VERSION,
        "ui_hierarchy_version": UI_HIERARCHY_VERSION,
        "template_contract_version": TEMPLATE_CONTRACT_VERSION,
        "template_sha256": template_sha256,
        "template_variant": template_variant,
        "terminology_contract": TERMINOLOGY_CONTRACT,
        "anomaly_region_render_mode": ANOMALY_RENDER_MODE,
        "visualization_profile": profile,
        "visualization_profile_warnings": profile_warnings,
        "spatial_scope": spatial_scope,
        "admin1_boundary_asset": {
            "asset_version": admin1_boundaries["asset_version"],
            "title": admin1_boundaries["title"],
            "natural_earth_version": admin1_boundaries["natural_earth_version"],
            "country_iso_a3": admin1_boundaries["country_iso_a3"],
            "source_geojson_url": admin1_boundaries["source_geojson_url"],
            "source_commit": admin1_boundaries["source_commit"],
            "source_sha256": admin1_boundaries["source_sha256"],
            "license": admin1_boundaries["license"],
            "boundary_semantics": admin1_boundaries["boundary_semantics"],
            "boundary_count": admin1_boundaries["boundary_count"],
            "point_count": admin1_boundaries["point_count"],
        },
        "capability_matrix": capability_matrix,
        "visual_question_contract": VISUAL_QUESTION_CONTRACT,
        "total_record_count": total_records,
        "source_mappable_record_count": source_mappable_records,
        "mappable_record_count": len(full_scope_records),
        "embedded_record_count": len(records),
        "map_preview_sampling": map_preview,
        "coordinate_mode": coordinate_mode,
        "coordinate_statistics": coordinate_statistics,
        "database_visual_summary": database_summary,
        "data_coverage_diagnostics": coverage_diagnostics,
        "region_presets": REGION_PRESETS,
        "qc_report": load_json_object(qc_report_path, "QC report"),
        "confidence_report": load_json_object(
            confidence_report_path, "confidence report"
        ),
        "source_manifest": load_json_object(source_manifest_path, "source manifest"),
        "sources_and_confidence": load_json_object(
            sources_and_confidence_path, "sources and confidence report"
        ),
        "anomaly_report": load_json_object(anomaly_report_path, "anomaly report"),
        "spatial_anomaly_regions": anomaly_regions,
        "spatial_anomaly_report": load_json_object(
            spatial_anomaly_report_path, "spatial anomaly report"
        ),
        "iteration_backlog": backlog_builder.load(iteration_backlog_path)
        if iteration_backlog_path
        else backlog_builder.load(Path("")),
        "temporal_view": {
            "embedded": temporal_embedded,
            "sha256": temporal_sha256,
            "compatibility_artifact": "temporal_map.html",
        },
    }
    html = (
        template.replace("__SAMPLES_JSON__", safe_embedded_json(map_payload))
        .replace("__ANOMALIES_JSON__", safe_embedded_json(scoped_anomalies))
        .replace("__BASEMAP_JSON__", safe_embedded_json(basemap))
        .replace("__BOUNDARIES_JSON__", safe_embedded_json(boundaries))
        .replace("__ADMIN1_BOUNDARIES_JSON__", safe_embedded_json(admin1_boundaries))
        .replace("__CONTEXT_JSON__", safe_embedded_json(context))
        .replace("__TEMPORAL_HTML_BASE64__", temporal_base64)
    )
    if reported_banner:
        html = inject_reported_coordinate_banner(html, coordinate_statistics)
    geojson_text = (
        json.dumps(geojson, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    html_bytes = len(html.encode("utf-8"))
    geojson_bytes = len(geojson_text.encode("utf-8"))
    if html_bytes > EMBED_TARGET_BYTES or geojson_bytes > EMBED_TARGET_BYTES:
        # Byte-budget adaptive preview: rebuild with a proportionally smaller
        # coverage-preserving preview instead of failing or fixing an arbitrary
        # record cap.  Deterministic: identical inputs shrink identically.
        embedded_count = len(records)
        scale = min(EMBED_TARGET_BYTES / html_bytes, EMBED_TARGET_BYTES / geojson_bytes)
        reduced_limit = max(
            1, min(embedded_count - 1, int(embedded_count * scale * 0.97))
        )
        if embedded_count <= 1 or reduced_limit >= embedded_count:
            raise MapBuildError(
                "map output exceeds the single-file byte budget even at the "
                "minimum preview size; filter or split the input"
            )
        return build_map(
            database,
            anomalies_path,
            output_html,
            output_geojson,
            max_points=max_points,
            max_embedded_records=reduced_limit,
            qc_report_path=qc_report_path,
            confidence_report_path=confidence_report_path,
            source_manifest_path=source_manifest_path,
            sources_and_confidence_path=sources_and_confidence_path,
            anomaly_report_path=anomaly_report_path,
            anomaly_regions_path=anomaly_regions_path,
            spatial_anomaly_report_path=spatial_anomaly_report_path,
            iteration_backlog_path=iteration_backlog_path,
            basemap_path=basemap_path,
            visualization_profile_path=visualization_profile_path,
            boundaries_path=boundaries_path,
            admin1_boundaries_path=admin1_boundaries_path,
            coordinate_mode=coordinate_mode,
            temporal_html_path=temporal_html_path,
        )
    if html_bytes > MAX_OUTPUT_BYTES or geojson_bytes > MAX_OUTPUT_BYTES:
        raise MapBuildError(
            "map output would exceed the 100 MB runtime safety limit; filter or split the input"
        )
    atomic_text(output_geojson, geojson_text)
    atomic_text(output_html, html)
    sample_keys = {sample_display_key(record) for record in records}
    all_data_overview = (
        profile["story"] == "overview"
        and profile["spatial_scope"] == "global"
        and profile["default_region"] == "global"
        and not any(profile["filters"].values())
    )
    return {
        "map_version": MAP_VERSION,
        "ui_hierarchy_version": UI_HIERARCHY_VERSION,
        "template_contract_version": TEMPLATE_CONTRACT_VERSION,
        "template_sha256": template_sha256,
        "template_variant": template_variant,
        "terminology_contract": TERMINOLOGY_CONTRACT,
        "mapped_record_count": len(records),
        "scope_mappable_record_count": len(full_scope_records),
        "map_preview_sampling": map_preview,
        "coordinate_mode": coordinate_mode,
        "coordinate_statistics": coordinate_statistics,
        "reported_coordinate_banner": reported_banner,
        "source_mappable_record_count": source_mappable_records,
        "scope_excluded_mappable_record_count": (
            source_mappable_records - len(full_scope_records)
        ),
        "display_sample_count": len(sample_keys),
        "unmappable_record_count": total_records - source_mappable_records,
        "candidate_record_count": sum(
            str(record["record_id"]) in anomaly_ids for record in records
        ),
        "candidate_anomaly_region_count": len(anomaly_regions.get("features", [])),
        "default_view": (
            "all_data_sample_deduplicated"
            if all_data_overview
            else (
                "regional_scope_task_view"
                if profile["spatial_scope"] == "regional"
                else "profile_driven_task_view"
            )
        ),
        "embedded_payload_schema": PAYLOAD_VERSION,
        "anomaly_region_render_mode": ANOMALY_RENDER_MODE,
        "visualization_profile": profile,
        "visualization_profile_warnings": profile_warnings,
        "spatial_scope": spatial_scope,
        "admin1_boundary_asset": context["admin1_boundary_asset"],
        "visual_question_contract": VISUAL_QUESTION_CONTRACT,
        "visualization_modes": [
            "distribution_points",
            "sample_density_heatmap",
            "classified_concentration_points",
            "database_concentration_histogram",
            "database_element_medium_coverage_matrix",
            "database_field_completeness",
            "anomaly_candidate_density_surface",
            *(
                ["interactive_orthographic_globe"]
                if profile["spatial_scope"] == "global"
                else []
            ),
            "element_pair_comparison",
            "candidate_anomaly_region_aggregation",
            "fdr_screened_candidate_anomaly_regions",
            "embedded_temporal_evolution_and_provenance",
            "auto_research_continuation_launcher",
        ],
        "capability_matrix": capability_matrix,
        "region_presets": [*REGION_PRESETS, "custom_bbox"],
        "region_coverage": region_coverage(full_scope_records, countries_by_code),
        "data_coverage_diagnostics": coverage_diagnostics,
        "database_visual_summary_schema": database_summary["schema_version"],
        "external_assets": 0,
        "interpolation": False,
        "html_bytes": html_bytes,
        "samples_geojson_bytes": geojson_bytes,
        "artifact_bindings": {
            "database_sha256": sha256_file(database),
            "anomalies_sha256": sha256_file(anomalies_path),
            "interactive_map_sha256": sha256_file(output_html),
            "samples_geojson_sha256": sha256_file(output_geojson),
            "temporal_map_sha256": temporal_sha256,
        },
        "basemap": {
            "asset_version": basemap["asset_version"],
            "title": basemap["title"],
            "scale": basemap["scale"],
            "license": basemap["license"],
            "archive_sha256": basemap["archive_sha256"],
            "embedded": True,
        },
        "country_boundaries": {
            "asset_version": boundaries["asset_version"],
            "title": boundaries["title"],
            "scale": boundaries["scale"],
            "license": boundaries["license"],
            "source_sha256": boundaries["source_sha256"],
            "country_count": boundaries["country_count"],
            "point_count": boundaries["point_count"],
            "embedded": True,
            "semantics": boundaries["boundary_semantics"],
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the self-contained D3 interactive atlas and samples GeoJSON."
    )
    parser.add_argument(
        "--database", required=True, type=Path, help="D2 geochemistry.csv"
    )
    parser.add_argument(
        "--anomalies", required=True, type=Path, help="D2 candidate anomalies GeoJSON"
    )
    parser.add_argument(
        "--output-html", required=True, type=Path, help="Self-contained HTML path"
    )
    parser.add_argument(
        "--output-geojson",
        required=True,
        type=Path,
        help="Map-ready samples GeoJSON path",
    )
    parser.add_argument("--qc-report", type=Path, help="Optional D2 qc_report.json")
    parser.add_argument(
        "--confidence-report", type=Path, help="Optional D2 confidence_report.json"
    )
    parser.add_argument(
        "--source-manifest", type=Path, help="Optional D1 source_manifest.json"
    )
    parser.add_argument(
        "--sources-and-confidence",
        type=Path,
        help="Optional sources_and_confidence.json metadata-completeness report",
    )
    parser.add_argument(
        "--anomaly-report", type=Path, help="Optional D2 anomaly_report.json"
    )
    parser.add_argument(
        "--anomaly-regions",
        type=Path,
        help="Optional D2 FDR-screened anomaly_regions.geojson",
    )
    parser.add_argument(
        "--spatial-anomaly-report",
        type=Path,
        help="Optional D2 spatial_anomaly_report.json",
    )
    parser.add_argument(
        "--iteration-backlog", type=Path, help="Optional D1/D2 iteration_backlog.csv"
    )
    parser.add_argument(
        "--basemap",
        type=Path,
        default=DEFAULT_BASEMAP,
        help="Pinned offline basemap asset",
    )
    parser.add_argument(
        "--boundaries",
        type=Path,
        default=DEFAULT_BOUNDARIES,
        help="Pinned offline Natural Earth Admin-0 boundary asset",
    )
    parser.add_argument(
        "--admin1-boundaries",
        type=Path,
        default=DEFAULT_ADMIN1_BOUNDARIES,
        help=(
            "Pinned offline Natural Earth China Admin-1 visual boundary asset; "
            "never used as a scientific or legal spatial join"
        ),
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Optional d3-visualization-profile-v2 JSON; defaults to the bundled template",
    )
    parser.add_argument(
        "--max-points",
        type=int,
        default=200_000,
        help="Hard safety ceiling for valid coordinate rows read from the CSV",
    )
    parser.add_argument(
        "--max-embedded-records",
        type=int,
        default=DEFAULT_MAX_EMBEDDED_RECORDS,
        help=(
            "Maximum measurement rows embedded in the interactive preview; "
            "the complete canonical CSV and aggregate summaries remain unsampled"
        ),
    )
    parser.add_argument(
        "--coordinate-mode",
        choices=COORDINATE_MODES,
        default="canonical",
        help=(
            "canonical (default) plots only verified WGS84 coordinates; reported "
            "additionally plots reported-only coordinates with an unverified datum "
            "and injects a prominent warning banner into the HTML"
        ),
    )
    parser.add_argument(
        "--temporal-html",
        type=Path,
        help="Generated temporal_map.html to embed as a first-class atlas view",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = build_map(
            database=args.database,
            anomalies_path=args.anomalies,
            output_html=args.output_html,
            output_geojson=args.output_geojson,
            max_points=args.max_points,
            max_embedded_records=args.max_embedded_records,
            qc_report_path=args.qc_report,
            confidence_report_path=args.confidence_report,
            source_manifest_path=args.source_manifest,
            sources_and_confidence_path=args.sources_and_confidence,
            anomaly_report_path=args.anomaly_report,
            anomaly_regions_path=args.anomaly_regions,
            spatial_anomaly_report_path=args.spatial_anomaly_report,
            iteration_backlog_path=args.iteration_backlog,
            basemap_path=args.basemap,
            visualization_profile_path=args.profile,
            boundaries_path=args.boundaries,
            admin1_boundaries_path=args.admin1_boundaries,
            coordinate_mode=args.coordinate_mode,
            temporal_html_path=args.temporal_html,
        )
    except (MapBuildError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
