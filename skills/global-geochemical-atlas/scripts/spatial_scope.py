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
BOUNDARY_ASSET_VERSION = "ai4s-natural-earth-admin0-v1"

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

    return west <= longitude <= east if west <= east else longitude >= west or longitude <= east


def coordinate_in_bbox(longitude: float, latitude: float, bbox: Sequence[float]) -> bool:
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
    cross = (longitude - start[0]) * (end[1] - start[1]) - (
        latitude - start[1]
    ) * (end[0] - start[0])
    if abs(cross) > 1e-9:
        return False
    return (
        min(start[0], end[0]) - 1e-9 <= longitude <= max(start[0], end[0]) + 1e-9
        and min(start[1], end[1]) - 1e-9 <= latitude <= max(start[1], end[1]) + 1e-9
    )


def point_in_ring(longitude: float, latitude: float, ring: Sequence[Sequence[float]]) -> bool:
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


def point_in_country(longitude: float, latitude: float, country: Mapping[str, Any]) -> bool:
    for polygon in geometry_polygons(country.get("geometry") or {}):
        if not polygon or not point_in_ring(longitude, latitude, polygon[0]):
            continue
        if not any(point_in_ring(longitude, latitude, hole) for hole in polygon[1:]):
            return True
    return False


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
    return [west, min(point[1] for point in points), east, max(point[1] for point in points)]


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
        raise SpatialScopeError("bbox is outside WGS84 bounds or latitude order is invalid")
    return [west, south, east, north]


@lru_cache(maxsize=4)
def load_country_registry(path_text: str = str(DEFAULT_BOUNDARIES)) -> dict[str, Any]:
    path = Path(path_text)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpatialScopeError(f"country boundary asset does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpatialScopeError(f"country boundary asset is unreadable: {path}") from exc
    countries = value.get("countries") if isinstance(value, dict) else None
    if (
        value.get("asset_version") != BOUNDARY_ASSET_VERSION
        or value.get("license") != "public domain"
        or not isinstance(countries, list)
        or not countries
    ):
        raise SpatialScopeError("country boundary asset provenance or structure is invalid")
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
            raise SpatialScopeError("country boundary contains invalid identifiers or geometry")
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


def resolve_region(value: Any, boundaries_path: Path = DEFAULT_BOUNDARIES) -> dict[str, Any]:
    """Resolve global, bbox, frozen named bbox, or a Natural Earth country."""

    if isinstance(value, Mapping):
        if set(value) != {"bbox"} or not isinstance(value.get("bbox"), list):
            raise SpatialScopeError("region object must contain exactly bbox=[west,south,east,north]")
        bbox = _validate_bbox(value["bbox"])
        return {
            "key": "custom",
            "label": "WGS84 请求范围",
            "bbox": bbox,
            "country_code": None,
            "clip_method": "bbox_wrapped" if bbox[0] > bbox[2] else "bbox",
        }
    if not isinstance(value, str) or not value.strip():
        raise SpatialScopeError("region must be a non-empty name, global, or bbox object")
    alias = normalize_alias(value)
    if alias in {normalize_alias("global"), normalize_alias("world"), normalize_alias("全球")}:
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
            "clip_method": "country_polygon_and_bbox" if item.get("country_code") else "bbox",
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
