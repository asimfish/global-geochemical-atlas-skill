#!/usr/bin/env python3
"""Resolve frozen request regions and apply WGS84 wrapped-longitude semantics."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BOUNDARIES = SKILL_DIR / "assets" / "natural-earth-110m-admin0.json"
DEFAULT_MACROREGIONS = SKILL_DIR / "assets" / "natural-earth-110m-macroregions.json"
BOUNDARY_ASSET_VERSION = "ai4s-natural-earth-admin0-v1"
MACROREGION_ASSET_VERSION = "ai4s-natural-earth-macroregions-v1"
GLOBAL_COVERAGE_GRID_DEGREES = 5.0
VALID_SPATIAL_DOMAINS = ("land", "inland_water", "marine")
DEFAULT_ADJACENT_MARINE_DISTANCE_KM = 600.0
EARTH_KM_PER_DEGREE = 111.195

NAMED_BBOXES: dict[str, dict[str, Any]] = {
    "europe": {
        "aliases": ("europe", "欧洲"),
        "label": "欧洲范围框",
        "bbox": [-25.0, 34.0, 45.0, 72.0],
    },
    "shanghai": {
        "aliases": ("shanghai", "上海", "上海市"),
        "label": "上海范围框",
        "bbox": [120.85, 30.65, 122.2, 31.9],
    },
    "usa48": {
        "aliases": ("usa48", "conus", "contiguous united states", "美国本土"),
        "label": "美国本土（国界 + 范围框）",
        "bbox": [-125.0, 24.0, -66.0, 50.0],
        "country_code": "USA",
    },
}

COUNTRY_ALIAS_OVERRIDES = {
    "us": "USA",
    "u.s.": "USA",
    "usa": "USA",
    "america": "USA",
    "united states": "USA",
    "中国": "CHN",
    "中国大陆": "CHN",
    "prc": "CHN",
    "uk": "GBR",
    "u.k.": "GBR",
    "britain": "GBR",
    "great britain": "GBR",
    "south korea": "KOR",
    "north korea": "PRK",
    "russia": "RUS",
}


class SpatialScopeError(ValueError):
    """Raised when a region cannot be resolved against frozen spatial evidence."""


def normalize_alias(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def longitude_in_interval(longitude: float, west: float, east: float) -> bool:
    """Return containment for ordinary or antimeridian-crossing longitude intervals."""

    return (
        west <= longitude <= east
        if west <= east
        else longitude >= west or longitude <= east
    )


def coordinate_in_bbox(
    longitude: float, latitude: float, bbox: Sequence[float]
) -> bool:
    west, south, east, north = bbox
    return longitude_in_interval(longitude, west, east) and south <= latitude <= north


def bbox_intersects(first: Sequence[float], second: Sequence[float]) -> bool:
    def ranges(bbox: Sequence[float]) -> list[tuple[float, float]]:
        west, _, east, _ = bbox
        return [(west, east)] if west <= east else [(west, 180.0), (-180.0, east)]

    if first[3] < second[1] or second[3] < first[1]:
        return False
    return any(
        left_a <= right_b and left_b <= right_a
        for left_a, right_a in ranges(first)
        for left_b, right_b in ranges(second)
    )


def geometry_polygons(geometry: Mapping[str, Any]) -> Sequence[Any]:
    coordinates = geometry.get("coordinates") or []
    if geometry.get("type") == "Polygon":
        return [coordinates]
    if geometry.get("type") == "MultiPolygon":
        return coordinates
    return []


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
    if not ring:
        return False
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


def point_in_country(
    longitude: float, latitude: float, country: Mapping[str, Any]
) -> bool:
    for polygon in geometry_polygons(country.get("geometry") or {}):
        if not polygon or not point_in_ring(longitude, latitude, polygon[0]):
            continue
        if not any(point_in_ring(longitude, latitude, hole) for hole in polygon[1:]):
            return True
    return False


def record_spatial_domain(record: Mapping[str, Any]) -> str:
    """Classify an observation domain from explicit medium semantics only.

    This helper never infers ocean membership from a coordinate.  A sediment
    point is marine only when the source/adapter says so; otherwise stream,
    river and lake semantics remain inland water and unqualified sediment stays
    on the land-country path.  Unknown media deliberately default to land so a
    broad country bbox cannot pull in unrelated offshore points.
    """

    medium = str(record.get("medium") or "").strip().casefold()
    sediment = str(record.get("sediment_environment") or "").strip().casefold()
    water = str(record.get("water_body_type") or "").strip().casefold()
    sample_type = str(record.get("sample_type") or "").strip().casefold()
    marine_tokens = ("marine", "ocean", "sea", "seawater")
    if (
        any(token in sediment for token in marine_tokens)
        or any(token in water for token in marine_tokens)
        or any(token in sample_type for token in ("marine", "seawater"))
    ):
        return "marine"
    if medium == "water" or sediment in {
        "stream",
        "river",
        "lake",
        "reservoir",
        "wetland",
        "floodplain",
        "outlet_catchment",
        "catchment_fluvial_alluvial",
    }:
        return "inland_water"
    return "land"


def _expanded_bbox(bbox: Sequence[float], distance_km: float) -> list[float]:
    """Return a conservative non-wrapped bbox expanded by a distance budget."""

    if distance_km <= 0:
        return [float(item) for item in bbox]
    west, south, east, north = (float(item) for item in bbox)
    if west > east:
        # All current country polygons have a minimal wrapped interval; keeping
        # the original global longitude span is safer than narrowing it.
        return [
            -180.0,
            max(-90.0, south - distance_km / EARTH_KM_PER_DEGREE),
            180.0,
            min(90.0, north + distance_km / EARTH_KM_PER_DEGREE),
        ]
    latitude_margin = distance_km / EARTH_KM_PER_DEGREE
    maximum_abs_latitude = min(89.0, max(abs(south), abs(north)) + latitude_margin)
    longitude_scale = max(0.05, math.cos(math.radians(maximum_abs_latitude)))
    longitude_margin = distance_km / (EARTH_KM_PER_DEGREE * longitude_scale)
    return [
        max(-180.0, west - longitude_margin),
        max(-90.0, south - latitude_margin),
        min(180.0, east + longitude_margin),
        min(90.0, north + latitude_margin),
    ]


def request_analysis_bbox(
    region: Mapping[str, Any],
    spatial_domains: Sequence[str] | None = None,
    adjacent_marine_distance_km: float = 0.0,
) -> list[float]:
    """Return an acquisition/display bbox for a domain-aware request.

    Only named-country requests with an explicit marine domain are expanded.
    Record admission still runs the polygon/distance gate below, so this bbox is
    a retrieval window rather than evidence that every enclosed point belongs
    to the requested country.
    """

    bbox = region.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise SpatialScopeError("resolved region has no valid bbox")
    domains = {str(item) for item in (spatial_domains or ())}
    if region.get("country_code") and "marine" in domains:
        return _expanded_bbox(bbox, float(adjacent_marine_distance_km))
    return [float(item) for item in bbox]


def _point_segment_distance_km(
    longitude: float,
    latitude: float,
    start: Sequence[float],
    end: Sequence[float],
) -> float:
    """Approximate local geodesic distance to one Natural Earth segment."""

    scale = max(0.05, math.cos(math.radians(latitude)))

    def unwrap(value: float) -> float:
        while value - longitude > 180.0:
            value -= 360.0
        while value - longitude < -180.0:
            value += 360.0
        return value

    ax = (unwrap(float(start[0])) - longitude) * scale
    ay = float(start[1]) - latitude
    bx = (unwrap(float(end[0])) - longitude) * scale
    by = float(end[1]) - latitude
    dx, dy = bx - ax, by - ay
    denominator = dx * dx + dy * dy
    fraction = (
        max(0.0, min(1.0, -(ax * dx + ay * dy) / denominator)) if denominator else 0.0
    )
    return math.hypot(ax + fraction * dx, ay + fraction * dy) * EARTH_KM_PER_DEGREE


def distance_to_country_boundary_km(
    longitude: float,
    latitude: float,
    country: Mapping[str, Any],
) -> float:
    """Return minimum distance to the frozen Admin-0 boundary geometry."""

    if point_in_country(longitude, latitude, country):
        return 0.0
    best = math.inf
    for polygon in geometry_polygons(country.get("geometry") or {}):
        for ring in polygon:
            if len(ring) < 2:
                continue
            previous = ring[-1]
            for current in ring:
                best = min(
                    best,
                    _point_segment_distance_km(longitude, latitude, previous, current),
                )
                previous = current
    return best


def _geometry_points(geometry: Mapping[str, Any]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for polygon in geometry_polygons(geometry):
        for ring in polygon:
            for raw in ring:
                if isinstance(raw, list) and len(raw) == 2:
                    points.append((float(raw[0]), float(raw[1])))
    return points


def _minimum_longitude_interval(longitudes: Sequence[float]) -> tuple[float, float]:
    """Return the smallest circular interval containing all supplied longitudes."""

    ordered = sorted(set(float(value) for value in longitudes))
    if not ordered:
        raise SpatialScopeError("country boundary has no longitude coordinates")
    if len(ordered) == 1:
        return ordered[0], ordered[0]
    gaps: list[tuple[float, int]] = [
        (ordered[index + 1] - ordered[index], index)
        for index in range(len(ordered) - 1)
    ]
    gaps.append((ordered[0] + 360.0 - ordered[-1], len(ordered) - 1))
    _, gap_index = max(gaps, key=lambda item: (item[0], -item[1]))
    west = ordered[(gap_index + 1) % len(ordered)]
    east = ordered[gap_index]
    return west, east


def country_bbox(country: Mapping[str, Any]) -> list[float]:
    points = _geometry_points(country.get("geometry") or {})
    if not points:
        raise SpatialScopeError("country boundary has no polygon coordinates")
    west, east = _minimum_longitude_interval([point[0] for point in points])
    return [
        west,
        min(point[1] for point in points),
        east,
        max(point[1] for point in points),
    ]


def _validate_bbox(raw: Sequence[Any]) -> list[float]:
    if len(raw) != 4 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        for value in raw
    ):
        raise SpatialScopeError("bbox must contain four finite numbers")
    west, south, east, north = (float(value) for value in raw)
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90):
        raise SpatialScopeError(
            "bbox is outside WGS84 bounds or latitude order is invalid"
        )
    return [west, south, east, north]


@lru_cache(maxsize=4)
def load_country_registry(path_text: str = str(DEFAULT_BOUNDARIES)) -> dict[str, Any]:
    path = Path(path_text)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpatialScopeError(
            f"country boundary asset does not exist: {path}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpatialScopeError(
            f"country boundary asset is unreadable: {path}"
        ) from exc
    countries = value.get("countries") if isinstance(value, dict) else None
    if (
        value.get("asset_version") != BOUNDARY_ASSET_VERSION
        or value.get("license") != "public domain"
        or not isinstance(countries, list)
        or not countries
    ):
        raise SpatialScopeError(
            "country boundary asset provenance or structure is invalid"
        )
    by_code: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for country in countries:
        if not isinstance(country, dict):
            raise SpatialScopeError("country boundary contains a non-object country")
        code = country.get("iso_a3")
        name = country.get("name")
        name_zh = country.get("name_zh")
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[A-Z]{3}", code)
            or code in by_code
            or not isinstance(name, str)
            or not name
            or not geometry_polygons(country.get("geometry") or {})
        ):
            raise SpatialScopeError(
                "country boundary contains invalid identifiers or geometry"
            )
        normalized = dict(country)
        normalized["bbox"] = country_bbox(country)
        by_code[code] = normalized
        for alias in (code, name, name_zh):
            if isinstance(alias, str) and alias.strip():
                aliases[normalize_alias(alias)] = code
    for alias, code in COUNTRY_ALIAS_OVERRIDES.items():
        if code in by_code:
            aliases[normalize_alias(alias)] = code
    named_aliases: dict[str, str] = {}
    for key, item in NAMED_BBOXES.items():
        for alias in item["aliases"]:
            named_aliases[normalize_alias(alias)] = key
    return {
        "asset_version": value["asset_version"],
        "source_sha256": value.get("source_sha256"),
        "by_code": by_code,
        "country_aliases": aliases,
        "named_aliases": named_aliases,
    }


@lru_cache(maxsize=4)
def load_macroregion_registry(
    path_text: str = str(DEFAULT_MACROREGIONS),
) -> dict[str, str]:
    """Load the pinned Natural Earth ISO-A3 → continent crosswalk."""

    path = Path(path_text)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpatialScopeError(
            f"macroregion crosswalk does not exist: {path}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpatialScopeError(f"macroregion crosswalk is unreadable: {path}") from exc
    raw = value.get("macroregions") if isinstance(value, dict) else None
    if (
        value.get("asset_version") != MACROREGION_ASSET_VERSION
        or value.get("license") != "public domain"
        or not isinstance(raw, dict)
        or not raw
    ):
        raise SpatialScopeError(
            "macroregion crosswalk provenance or structure is invalid"
        )
    output: dict[str, str] = {}
    for code, macroregion in raw.items():
        if (
            not isinstance(code, str)
            or not re.fullmatch(r"[A-Z]{3}", code)
            or not isinstance(macroregion, str)
            or not macroregion.strip()
        ):
            raise SpatialScopeError(
                "macroregion crosswalk contains an invalid country or label"
            )
        output[code] = macroregion.strip()
    return output


def country_at_coordinate(
    longitude: float,
    latitude: float,
    boundaries_path: Path = DEFAULT_BOUNDARIES,
) -> str | None:
    """Return the frozen Natural Earth country code containing a coordinate."""

    registry = load_country_registry(str(boundaries_path.resolve()))
    for code, country in registry["by_code"].items():
        if not coordinate_in_bbox(longitude, latitude, country["bbox"]):
            continue
        if point_in_country(longitude, latitude, country):
            return str(code)
    return None


def coordinate_macroregion(
    longitude: float,
    latitude: float,
    boundaries_path: Path = DEFAULT_BOUNDARIES,
    macroregions_path: Path = DEFAULT_MACROREGIONS,
) -> str:
    """Classify a WGS84 coordinate without treating oceans as land coverage."""

    code = country_at_coordinate(longitude, latitude, boundaries_path)
    if code is None:
        return "Open ocean / unassigned"
    registry = load_macroregion_registry(str(macroregions_path.resolve()))
    macroregion = registry.get(code)
    if macroregion is None:
        raise SpatialScopeError(
            f"country {code} is absent from the frozen macroregion crosswalk"
        )
    return macroregion


def coverage_grid_cell_id(
    longitude: float,
    latitude: float,
    cell_degrees: float = GLOBAL_COVERAGE_GRID_DEGREES,
) -> str:
    """Return a stable global lon/lat cell ID for coverage auditing.

    The grid is an audit index, not an interpolation surface or equal-area
    scientific model.  It is used only to detect large observation holes that
    a continent-level sample count can hide.
    """

    if (
        not math.isfinite(longitude)
        or not math.isfinite(latitude)
        or not -180 <= longitude <= 180
        or not -90 <= latitude <= 90
        or not math.isfinite(cell_degrees)
        or cell_degrees <= 0
        or not math.isclose(360 / cell_degrees, round(360 / cell_degrees))
        or not math.isclose(180 / cell_degrees, round(180 / cell_degrees))
    ):
        raise SpatialScopeError(
            "coverage grid requires finite WGS84 coordinates and a cell size that divides both 180 and 360 degrees"
        )
    longitude_cells = round(360 / cell_degrees)
    latitude_cells = round(180 / cell_degrees)
    longitude_index = min(
        longitude_cells - 1,
        max(0, math.floor((longitude + 180.0) / cell_degrees)),
    )
    latitude_index = min(
        latitude_cells - 1,
        max(0, math.floor((latitude + 90.0) / cell_degrees)),
    )
    return f"{latitude_index:02d}:{longitude_index:02d}"


def coverage_grid_cell_center(
    cell_id: str,
    cell_degrees: float = GLOBAL_COVERAGE_GRID_DEGREES,
) -> tuple[float, float]:
    """Return the WGS84 centre of a coverage-audit cell ID."""

    # Reuse the public validator for cell-size semantics before parsing an ID.
    coverage_grid_cell_id(0.0, 0.0, cell_degrees)
    match = re.fullmatch(r"(\d+):(\d+)", cell_id)
    if match is None:
        raise SpatialScopeError(f"invalid coverage grid cell ID: {cell_id!r}")
    latitude_index, longitude_index = (int(value) for value in match.groups())
    latitude_cells = round(180 / cell_degrees)
    longitude_cells = round(360 / cell_degrees)
    if latitude_index >= latitude_cells or longitude_index >= longitude_cells:
        raise SpatialScopeError(f"coverage grid cell ID is out of range: {cell_id!r}")
    return (
        -180.0 + (longitude_index + 0.5) * cell_degrees,
        -90.0 + (latitude_index + 0.5) * cell_degrees,
    )


@lru_cache(maxsize=4)
def load_global_land_grid(
    cell_degrees: float = GLOBAL_COVERAGE_GRID_DEGREES,
    boundaries_path_text: str = str(DEFAULT_BOUNDARIES),
    macroregions_path_text: str = str(DEFAULT_MACROREGIONS),
) -> dict[str, Any]:
    """Build a frozen Natural Earth land-cell index for spatial gap checks.

    A cell belongs to the Admin-0 polygon containing its centre.  Five-degree
    cells deliberately provide a coarse, dependency-free audit that is stable
    in the 2-core/4-GB competition environment.  Coastal slivers can be absent;
    country sample counts are therefore checked alongside cell occupancy.
    """

    # Validate the step once through the same public contract used for samples.
    coverage_grid_cell_id(0.0, 0.0, cell_degrees)
    boundaries_path = Path(boundaries_path_text)
    macroregions_path = Path(macroregions_path_text)
    longitude_cells = round(360 / cell_degrees)
    latitude_cells = round(180 / cell_degrees)
    country_cells: dict[str, list[str]] = {}
    macroregion_cells: dict[str, list[str]] = {}
    country_by_cell: dict[str, str] = {}
    macroregions = load_macroregion_registry(str(macroregions_path.resolve()))
    for latitude_index in range(latitude_cells):
        latitude = -90.0 + (latitude_index + 0.5) * cell_degrees
        for longitude_index in range(longitude_cells):
            longitude = -180.0 + (longitude_index + 0.5) * cell_degrees
            country_code = country_at_coordinate(longitude, latitude, boundaries_path)
            if country_code is None:
                continue
            cell_id = coverage_grid_cell_id(longitude, latitude, cell_degrees)
            country_by_cell[cell_id] = country_code
            country_cells.setdefault(country_code, []).append(cell_id)
            macroregion = macroregions.get(country_code)
            if macroregion is None:
                raise SpatialScopeError(
                    f"country {country_code} is absent from the frozen macroregion crosswalk"
                )
            macroregion_cells.setdefault(macroregion, []).append(cell_id)
    return {
        "boundary_asset_version": BOUNDARY_ASSET_VERSION,
        "macroregion_asset_version": MACROREGION_ASSET_VERSION,
        "cell_degrees": cell_degrees,
        "country_by_cell": country_by_cell,
        "country_cells": {
            code: tuple(sorted(cells)) for code, cells in sorted(country_cells.items())
        },
        "macroregion_cells": {
            region: tuple(sorted(cells))
            for region, cells in sorted(macroregion_cells.items())
        },
    }


def resolve_region(
    value: Any, boundaries_path: Path = DEFAULT_BOUNDARIES
) -> dict[str, Any]:
    """Resolve global, bbox, frozen named bbox, or a Natural Earth country."""

    if isinstance(value, Mapping):
        if set(value) != {"bbox"} or not isinstance(value.get("bbox"), list):
            raise SpatialScopeError(
                "region object must contain exactly bbox=[west,south,east,north]"
            )
        bbox = _validate_bbox(value["bbox"])
        return {
            "key": "custom",
            "label": "WGS84 请求范围",
            "bbox": bbox,
            "country_code": None,
            "clip_method": "bbox_wrapped" if bbox[0] > bbox[2] else "bbox",
        }
    if not isinstance(value, str) or not value.strip():
        raise SpatialScopeError(
            "region must be a non-empty name, global, or bbox object"
        )
    alias = normalize_alias(value)
    if alias in {
        normalize_alias("global"),
        normalize_alias("world"),
        normalize_alias("全球"),
    }:
        return {
            "key": "global",
            "label": "全球",
            "bbox": [-180.0, -90.0, 180.0, 90.0],
            "country_code": None,
            "clip_method": "global",
        }
    registry = load_country_registry(str(boundaries_path.resolve()))
    named_key = registry["named_aliases"].get(alias)
    if named_key is not None:
        item = NAMED_BBOXES[named_key]
        bbox = list(item["bbox"])
        return {
            "key": named_key,
            "label": item["label"],
            "bbox": bbox,
            "country_code": item.get("country_code"),
            "clip_method": "country_polygon_and_bbox"
            if item.get("country_code")
            else "bbox",
        }
    code = registry["country_aliases"].get(alias)
    if code is None:
        raise SpatialScopeError(
            f"named region is absent from the frozen country/region registry: {value!r}; use a WGS84 bbox"
        )
    country = registry["by_code"][code]
    return {
        "key": f"country:{code}",
        "label": str(country.get("name_zh") or country["name"]),
        "bbox": list(country["bbox"]),
        "country_code": code,
        "clip_method": "country_polygon_and_bbox",
    }


def coordinate_in_region(
    longitude: float,
    latitude: float,
    region: Mapping[str, Any],
    boundaries_path: Path = DEFAULT_BOUNDARIES,
) -> bool:
    bbox = region.get("bbox")
    if not isinstance(bbox, list) or not coordinate_in_bbox(longitude, latitude, bbox):
        return False
    country_code = region.get("country_code")
    if not country_code:
        return True
    registry = load_country_registry(str(boundaries_path.resolve()))
    country = registry["by_code"].get(str(country_code))
    if country is None:
        raise SpatialScopeError(f"country boundary is unavailable: {country_code}")
    return point_in_country(longitude, latitude, country)


def coordinate_in_request_scope(
    longitude: float,
    latitude: float,
    region: Mapping[str, Any],
    *,
    spatial_domain: str,
    spatial_domains: Sequence[str],
    adjacent_marine_distance_km: float,
    boundaries_path: Path = DEFAULT_BOUNDARIES,
) -> bool:
    """Apply land/inland-water polygons and a bounded adjacent-marine domain.

    The marine buffer is an analysis/retrieval domain, not a territorial-sea,
    EEZ or sovereignty claim.  Explicit source semantics must classify a row as
    marine before the buffer can apply; all other rows remain subject to the
    strict country polygon.
    """

    if spatial_domain not in VALID_SPATIAL_DOMAINS:
        raise SpatialScopeError(f"unsupported spatial domain: {spatial_domain}")
    requested = {str(item) for item in spatial_domains}
    if spatial_domain not in requested:
        return False
    country_code = region.get("country_code")
    if not country_code:
        bbox = region.get("bbox")
        return bool(
            isinstance(bbox, list) and coordinate_in_bbox(longitude, latitude, bbox)
        )
    registry = load_country_registry(str(boundaries_path.resolve()))
    country = registry["by_code"].get(str(country_code))
    if country is None:
        raise SpatialScopeError(f"country boundary is unavailable: {country_code}")
    if spatial_domain != "marine":
        return coordinate_in_bbox(
            longitude, latitude, region["bbox"]
        ) and point_in_country(
            longitude,
            latitude,
            country,
        )
    if adjacent_marine_distance_km <= 0:
        return False
    analysis_bbox = request_analysis_bbox(
        region, spatial_domains, adjacent_marine_distance_km
    )
    if not coordinate_in_bbox(longitude, latitude, analysis_bbox):
        return False
    # A source-labelled marine observation inside a coarse land polygon is
    # admitted; otherwise it must be within the declared proximity budget.
    return distance_to_country_boundary_km(longitude, latitude, country) <= float(
        adjacent_marine_distance_km
    )
