#!/usr/bin/env python3
"""Build the D3 self-contained interactive atlas and map-ready GeoJSON."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


MAP_VERSION = "d3-interactive-atlas-v3"
PAYLOAD_VERSION = "d3-compact-payload-v1"
ANOMALY_RENDER_MODE = "zoom-adaptive-anomaly-bubbles-v1"
PROFILE_VERSION = "d3-visualization-profile-v2"
BASEMAP_ASSET_VERSION = "ai4s-natural-earth-land-v1"
MAX_OUTPUT_BYTES = 100_000_000
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BASEMAP = SKILL_DIR / "assets" / "natural-earth-110m-land.json"
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "interactive-atlas-v3.html"
DEFAULT_PROFILE = SKILL_DIR / "assets" / "visualization-profile.template.json"
REGION_PRESETS: dict[str, dict[str, Any]] = {
    "global": {
        "label": "全球",
        "bounds": {"w": -180.0, "e": 180.0, "s": -90.0, "n": 90.0},
    },
    "usa": {
        "label": "美国范围框（含阿拉斯加）",
        "bounds": {"w": -170.0, "e": -66.0, "s": 18.0, "n": 72.0},
    },
    "usa48": {
        "label": "美国本土范围框",
        "bounds": {"w": -125.0, "e": -66.0, "s": 24.0, "n": 50.0},
    },
    "china": {
        "label": "中国范围框",
        "bounds": {"w": 73.0, "e": 135.0, "s": 18.0, "n": 54.0},
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
        "label": "澳大利亚范围框",
        "bounds": {"w": 112.0, "e": 154.0, "s": -44.0, "n": -10.0},
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


def coordinate_in_bounds(longitude: float, latitude: float, bounds: Mapping[str, float]) -> bool:
    return (
        bounds["w"] <= longitude <= bounds["e"]
        and bounds["s"] <= latitude <= bounds["n"]
    )


def load_records(
    path: Path, max_points: int, scope_bounds: Mapping[str, float]
) -> tuple[list[dict[str, Any]], int, int]:
    """Consume, but never reinterpret, the public D2 canonical CSV."""
    if not path.is_file():
        raise MapBuildError(f"database does not exist: {path}")
    records: list[dict[str, Any]] = []
    total_records = 0
    source_mappable_records = 0
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
            total_records += 1
            latitude = optional_float(row.get("latitude"))
            longitude = optional_float(row.get("longitude"))
            if latitude is None or longitude is None:
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            source_mappable_records += 1
            if not coordinate_in_bounds(longitude, latitude, scope_bounds):
                continue
            confidence = parse_json_cell(row.get("operational_confidence"), {})
            qc_flags = parse_json_cell(row.get("qc_flags"), [])
            if not isinstance(confidence, dict):
                confidence = {}
            if not isinstance(qc_flags, list):
                qc_flags = []
            records.append(
                {
                    "record_id": row.get("record_id"),
                    "sample_id": row.get("sample_id") or None,
                    "element": row.get("element_or_analyte"),
                    "analyte_reported": row.get("analyte_reported") or None,
                    "medium": row.get("medium"),
                    "material": row.get("material") or None,
                    "measurement_basis": row.get("measurement_basis") or None,
                    "original_value_raw": row.get("original_value_raw") or None,
                    "original_unit": row.get("original_unit") or None,
                    "source_qualifier_raw": row.get("source_qualifier_raw") or None,
                    "qualifier": row.get("value_qualifier") or None,
                    "censored": parse_bool_cell(row.get("censored")),
                    "censoring_limit": optional_float(row.get("normalized_censoring_limit")),
                    "value": optional_float(row.get("normalized_value")),
                    "unit": row.get("normalized_unit") or None,
                    "latitude": latitude,
                    "longitude": longitude,
                    "lithology": row.get("lithology") or None,
                    "geologic_unit": row.get("geologic_unit") or None,
                    "analytical_method": row.get("analytical_method") or None,
                    "method_family": row.get("method_family") or None,
                    "digestion_or_extraction": row.get("digestion_or_extraction") or None,
                    "source_id": row.get("source_id") or None,
                    "dataset_title": row.get("dataset_title") or None,
                    "dataset_doi": row.get("dataset_doi") or None,
                    "dataset_version": row.get("dataset_version") or None,
                    "source_locator": row.get("source_locator") or None,
                    "license": row.get("license") or None,
                    "confidence_band": confidence.get("band", "unknown"),
                    "confidence_overall": optional_float(confidence.get("overall")),
                    "confidence_components": {
                        key: optional_float(confidence.get(key))
                        for key in ("source", "completeness", "method", "spatial", "qc")
                    },
                    "qc_flags": [str(flag) for flag in qc_flags],
                }
            )
            if len(records) > max_points:
                raise MapBuildError(
                    f"valid map points within the configured scope exceed --max-points "
                    f"({max_points}); filter the input first"
                )
    return records, total_records, source_mappable_records


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


def require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unknown:
            details.append("unknown " + ", ".join(unknown))
        raise MapBuildError(f"{label} fields are invalid: {'; '.join(details)}")


def profile_text(value: Any, label: str, maximum: int, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MapBuildError(f"visualization profile {label} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise MapBuildError(f"visualization profile {label} exceeds {maximum} characters")
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
    if story not in {"overview", "coverage", "anomaly", "comparison", "evidence"}:
        raise MapBuildError("visualization profile story is unsupported")
    default_region = profile.get("default_region")
    if default_region not in {*REGION_PRESETS, "custom"}:
        raise MapBuildError("visualization profile default_region is unsupported")
    spatial_scope = profile.get("spatial_scope")
    if spatial_scope not in {"global", "regional"}:
        raise MapBuildError("visualization profile spatial_scope must be global or regional")
    if spatial_scope == "global" and default_region != "global":
        raise MapBuildError("spatial_scope=global requires default_region=global")
    if spatial_scope == "regional" and default_region == "global":
        raise MapBuildError("spatial_scope=regional requires a non-global default_region")

    custom_region = profile.get("custom_region")
    if custom_region is not None:
        if not isinstance(custom_region, dict):
            raise MapBuildError("visualization profile custom_region must be null or an object")
        require_exact_keys(custom_region, {"label", "bounds"}, "custom_region")
        bounds = custom_region.get("bounds")
        if not isinstance(bounds, dict):
            raise MapBuildError("visualization profile custom_region.bounds must be an object")
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
            -180 <= numbers["w"] < numbers["e"] <= 180
            and -90 <= numbers["s"] < numbers["n"] <= 90
        ):
            raise MapBuildError("visualization profile custom bounds must satisfy W<E and S<N")
        custom_region = {
            "label": profile_text(custom_region.get("label"), "custom_region.label", 80),
            "bounds": numbers,
        }
    if default_region == "custom" and custom_region is None:
        raise MapBuildError("default_region=custom requires custom_region")
    if default_region != "custom" and custom_region is not None:
        raise MapBuildError("custom_region must be null unless default_region=custom")

    filters = profile.get("filters")
    filter_keys = {"element", "medium", "basis", "geology", "method", "source", "confidence"}
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
        raise MapBuildError("visualization profile anomaly grid must be 1, 2, or 5 degrees")
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
    return {"label": str(region["label"]), "bounds": dict(region["bounds"])}


def visualization_profile_warnings(
    profile: Mapping[str, Any], records: Sequence[Mapping[str, Any]], anomaly_ids: set[str]
) -> list[str]:
    method_values = {
        str(record.get("method_family") or record.get("analytical_method") or "unknown")
        for record in records
    }
    available = {
        "element": {str(record.get("element")) for record in records if record.get("element")},
        "medium": {str(record.get("medium")) for record in records if record.get("medium")},
        "basis": {
            str(record.get("measurement_basis"))
            for record in records
            if record.get("measurement_basis")
        },
        "geology": {
            str(record.get("geologic_unit")) for record in records if record.get("geologic_unit")
        },
        "method": method_values,
        "source": {str(record.get("source_id")) for record in records if record.get("source_id")},
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
    bounds = region["bounds"]
    region_records = [
        record
        for record in records
        if bounds["w"] <= float(record["longitude"]) <= bounds["e"]
        and bounds["s"] <= float(record["latitude"]) <= bounds["n"]
    ]
    if not region_records:
        warnings.append("默认区域没有可上图记录；页面将显示覆盖缺口")
    filters = profile["filters"]
    field_map = {
        "element": "element",
        "medium": "medium",
        "basis": "measurement_basis",
        "geology": "geologic_unit",
        "source": "source_id",
        "confidence": "confidence_band",
    }

    def matches_filters(record: Mapping[str, Any]) -> bool:
        for profile_key, record_key in field_map.items():
            requested = filters.get(profile_key)
            if requested and record.get(record_key) != requested:
                return False
        requested_method = filters.get("method")
        method = record.get("method_family") or record.get("analytical_method") or "unknown"
        return not requested_method or method == requested_method

    configured_records = [record for record in region_records if matches_filters(record)]
    if region_records and not configured_records:
        warnings.append("默认区域与筛选组合没有可上图记录")
    if profile["story"] == "anomaly" and not any(
        str(record.get("record_id")) in anomaly_ids for record in configured_records
    ):
        warnings.append("当前异常任务配置没有匹配的 D2 候选")
    return warnings


def load_anomalies(path: Path) -> dict[str, Any]:
    value = load_json_object(path, "anomalies GeoJSON")
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
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


def sample_display_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record.get("source_id"),
        record.get("sample_id") or record.get("record_id"),
        record.get("medium"),
        record.get("longitude"),
        record.get("latitude"),
    )


def region_coverage(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for key, region in REGION_PRESETS.items():
        bounds = region["bounds"]
        matched = [
            record
            for record in records
            if bounds["w"] <= float(record["longitude"]) <= bounds["e"]
            and bounds["s"] <= float(record["latitude"]) <= bounds["n"]
        ]
        coverage[key] = {
            "label": region["label"],
            "bounds": dict(bounds),
            "record_count": len(matched),
            "sample_count": len({sample_display_key(record) for record in matched}),
            "elements": sorted(
                {str(record.get("element")) for record in matched if record.get("element")}
            ),
            "media": sorted(
                {str(record.get("medium")) for record in matched if record.get("medium")}
            ),
            "administrative_clip": False,
        }
    return coverage


def samples_geojson(
    records: Sequence[Mapping[str, Any]],
    anomaly_ids: set[str],
    profile: Mapping[str, Any],
    scope_region: Mapping[str, Any],
) -> dict[str, Any]:
    features = []
    for record in records:
        properties = {
            key: value for key, value in record.items() if key not in {"latitude", "longitude"}
        }
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
        "spatial_scope": {
            "mode": profile["spatial_scope"],
            "region_key": profile["default_region"],
            "region_label": scope_region["label"],
            "bounds": dict(scope_region["bounds"]),
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
    "material",
    "measurement_basis",
    "original_value_raw",
    "original_unit",
    "source_qualifier_raw",
    "qualifier",
    "censored",
    "censoring_limit",
    "value",
    "unit",
    "lithology",
    "geologic_unit",
    "analytical_method",
    "method_family",
    "digestion_or_extraction",
    "source_id",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_locator",
    "license",
    "confidence_band",
    "confidence_overall",
    "confidence_source",
    "confidence_completeness",
    "confidence_method",
    "confidence_spatial",
    "confidence_qc",
    "qc_flags",
    "candidate_anomaly",
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
                string_index(record.get("material")),
                string_index(record.get("measurement_basis")),
                string_index(record.get("original_value_raw")),
                string_index(record.get("original_unit")),
                string_index(record.get("source_qualifier_raw")),
                string_index(record.get("qualifier")),
                1 if record.get("censored") else 0,
                record.get("censoring_limit"),
                record.get("value"),
                string_index(record.get("unit")),
                string_index(record.get("lithology")),
                string_index(record.get("geologic_unit")),
                string_index(record.get("analytical_method")),
                string_index(record.get("method_family")),
                string_index(record.get("digestion_or_extraction")),
                string_index(record.get("source_id")),
                string_index(record.get("dataset_title")),
                string_index(record.get("dataset_doi")),
                string_index(record.get("dataset_version")),
                string_index(record.get("source_locator")),
                string_index(record.get("license")),
                string_index(record.get("confidence_band")),
                record.get("confidence_overall"),
                confidence.get("source"),
                confidence.get("completeness"),
                confidence.get("method"),
                confidence.get("spatial"),
                confidence.get("qc"),
                [string_index(flag) for flag in record.get("qc_flags", [])],
                1 if str(record.get("record_id")) in anomaly_ids else 0,
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


def load_html_template(path: Path = DEFAULT_TEMPLATE) -> str:
    if not path.is_file():
        raise MapBuildError(f"interactive map template does not exist: {path}")
    template = path.read_text(encoding="utf-8")
    required = {
        "__SAMPLES_JSON__",
        "__ANOMALIES_JSON__",
        "__BASEMAP_JSON__",
        "__CONTEXT_JSON__",
        MAP_VERSION,
        PAYLOAD_VERSION,
        ANOMALY_RENDER_MODE,
        PROFILE_VERSION,
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
    max_points: int = 50_000,
    qc_report_path: Path | None = None,
    confidence_report_path: Path | None = None,
    source_manifest_path: Path | None = None,
    anomaly_report_path: Path | None = None,
    basemap_path: Path = DEFAULT_BASEMAP,
    visualization_profile_path: Path | None = None,
) -> dict[str, Any]:
    if max_points < 1 or max_points > 200_000:
        raise MapBuildError("--max-points must be between 1 and 200000")
    profile = load_visualization_profile(visualization_profile_path)
    scope_region = selected_region(profile)
    records, total_records, source_mappable_records = load_records(
        database, max_points, scope_region["bounds"]
    )
    anomalies = load_anomalies(anomalies_path)
    basemap = load_basemap(basemap_path)
    anomaly_ids = {
        str(feature.get("properties", {}).get("record_id"))
        for feature in anomalies["features"]
        if feature.get("properties", {}).get("record_id") is not None
    }
    scoped_record_ids = {str(record["record_id"]) for record in records}
    scoped_anomalies = {
        **anomalies,
        "features": [
            feature
            for feature in anomalies["features"]
            if str(feature.get("properties", {}).get("record_id")) in scoped_record_ids
        ],
    }
    profile_warnings = visualization_profile_warnings(profile, records, anomaly_ids)
    geojson = samples_geojson(records, anomaly_ids, profile, scope_region)
    map_payload = compact_map_payload(records, anomaly_ids)
    spatial_scope = {
        "mode": profile["spatial_scope"],
        "region_key": profile["default_region"],
        "region_label": scope_region["label"],
        "bounds": dict(scope_region["bounds"]),
        "output_clipped": profile["spatial_scope"] == "regional",
    }
    context = {
        "map_version": MAP_VERSION,
        "anomaly_region_render_mode": ANOMALY_RENDER_MODE,
        "visualization_profile": profile,
        "visualization_profile_warnings": profile_warnings,
        "spatial_scope": spatial_scope,
        "total_record_count": total_records,
        "source_mappable_record_count": source_mappable_records,
        "mappable_record_count": len(records),
        "region_presets": REGION_PRESETS,
        "qc_report": load_json_object(qc_report_path, "QC report"),
        "confidence_report": load_json_object(confidence_report_path, "confidence report"),
        "source_manifest": load_json_object(source_manifest_path, "source manifest"),
        "anomaly_report": load_json_object(anomaly_report_path, "anomaly report"),
    }
    html = (
        load_html_template().replace("__SAMPLES_JSON__", safe_embedded_json(map_payload))
        .replace("__ANOMALIES_JSON__", safe_embedded_json(scoped_anomalies))
        .replace("__BASEMAP_JSON__", safe_embedded_json(basemap))
        .replace("__CONTEXT_JSON__", safe_embedded_json(context))
    )
    geojson_text = (
        json.dumps(geojson, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )
    html_bytes = len(html.encode("utf-8"))
    geojson_bytes = len(geojson_text.encode("utf-8"))
    if html_bytes > MAX_OUTPUT_BYTES or geojson_bytes > MAX_OUTPUT_BYTES:
        raise MapBuildError(
            "map output would exceed the 100 MB single-file limit; filter or split the input"
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
        "mapped_record_count": len(records),
        "source_mappable_record_count": source_mappable_records,
        "scope_excluded_mappable_record_count": source_mappable_records - len(records),
        "display_sample_count": len(sample_keys),
        "unmappable_record_count": total_records - source_mappable_records,
        "candidate_record_count": sum(
            str(record["record_id"]) in anomaly_ids for record in records
        ),
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
        "visualization_modes": [
            "distribution_points",
            "sample_density_heatmap",
            "element_pair_comparison",
            "candidate_anomaly_region_aggregation",
        ],
        "region_presets": [*REGION_PRESETS, "custom_bbox"],
        "region_coverage": region_coverage(records),
        "external_assets": 0,
        "interpolation": False,
        "html_bytes": html_bytes,
        "samples_geojson_bytes": geojson_bytes,
        "basemap": {
            "asset_version": basemap["asset_version"],
            "title": basemap["title"],
            "scale": basemap["scale"],
            "license": basemap["license"],
            "archive_sha256": basemap["archive_sha256"],
            "embedded": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the self-contained D3 interactive atlas and samples GeoJSON."
    )
    parser.add_argument("--database", required=True, type=Path, help="D2 geochemistry.csv")
    parser.add_argument(
        "--anomalies", required=True, type=Path, help="D2 candidate anomalies GeoJSON"
    )
    parser.add_argument("--output-html", required=True, type=Path, help="Self-contained HTML path")
    parser.add_argument(
        "--output-geojson", required=True, type=Path, help="Map-ready samples GeoJSON path"
    )
    parser.add_argument("--qc-report", type=Path, help="Optional D2 qc_report.json")
    parser.add_argument(
        "--confidence-report", type=Path, help="Optional D2 confidence_report.json"
    )
    parser.add_argument("--source-manifest", type=Path, help="Optional D1 source_manifest.json")
    parser.add_argument("--anomaly-report", type=Path, help="Optional D2 anomaly_report.json")
    parser.add_argument(
        "--basemap", type=Path, default=DEFAULT_BASEMAP, help="Pinned offline basemap asset"
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="Optional d3-visualization-profile-v2 JSON; defaults to the bundled template",
    )
    parser.add_argument(
        "--max-points", type=int, default=50_000, help="Fail if valid coordinate points exceed this"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = build_map(
            args.database,
            args.anomalies,
            args.output_html,
            args.output_geojson,
            args.max_points,
            args.qc_report,
            args.confidence_report,
            args.source_manifest,
            args.anomaly_report,
            args.basemap,
            args.profile,
        )
    except (MapBuildError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
