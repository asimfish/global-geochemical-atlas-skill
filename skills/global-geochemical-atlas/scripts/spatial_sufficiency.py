#!/usr/bin/env python3
"""Policy-driven spatial sufficiency for request-specific atlas map views.

This module contains no source or place-name decisions.  It derives a target
coverage grid from the frozen request, audits canonical independent samples for
each requested filter view, and ranks geographic repair targets from observed
holes.  The grid is an evidence audit index, never an interpolation surface.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import spatial_scope


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = SKILL_DIR / "assets" / "spatial-sufficiency-policy.json"
POLICY_VERSION = "atlas-spatial-sufficiency-policy-v6"
VIEW_KINDS = ("element", "medium", "element_medium")


class SpatialSufficiencyPolicyError(ValueError):
    """Raised when the versioned policy is absent, ambiguous, or unsafe."""


def _exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise SpatialSufficiencyPolicyError(
            f"{label} keys are invalid; missing={missing}; unknown={unknown}"
        )


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SpatialSufficiencyPolicyError(f"{label} must be a positive integer")
    return value


def _fraction(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not 0 < float(value) <= 1
    ):
        raise SpatialSufficiencyPolicyError(f"{label} must be within (0, 1]")
    return float(value)


def _grid_size(value: Any, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        raise SpatialSufficiencyPolicyError(f"{label} must be positive and finite")
    result = float(value)
    try:
        spatial_scope.coverage_grid_cell_id(0.0, 0.0, result)
    except spatial_scope.SpatialScopeError as exc:
        raise SpatialSufficiencyPolicyError(f"{label}: {exc}") from exc
    return result


def validate_policy(value: Any) -> dict[str, Any]:
    """Validate and normalize the policy without optional schema libraries."""

    if not isinstance(value, Mapping):
        raise SpatialSufficiencyPolicyError(
            "spatial sufficiency policy must be an object"
        )
    _exact_keys(
        value,
        {
            "policy_version",
            "global_scope",
            "regional_scope",
            "dimension_views",
            "claim_boundary",
        },
        "policy",
    )
    if value.get("policy_version") != POLICY_VERSION:
        raise SpatialSufficiencyPolicyError(
            f"unsupported spatial policy version: {value.get('policy_version')!r}"
        )
    if (
        not isinstance(value.get("claim_boundary"), str)
        or not str(value["claim_boundary"]).strip()
    ):
        raise SpatialSufficiencyPolicyError("policy claim_boundary must be non-empty")

    global_scope = value.get("global_scope")
    if not isinstance(global_scope, Mapping):
        raise SpatialSufficiencyPolicyError("global_scope must be an object")
    global_keys = {
        "grid_cell_degrees",
        "excluded_country_iso_a3",
        "priority_country_count",
        "core_priority_country_count",
        "minimum_priority_country_pass_rate",
        "minimum_country_canonical_samples",
        "minimum_country_occupied_cells",
        "maximum_country_occupied_cells",
        "minimum_country_grid_coverage_rate",
        "minimum_macroregion_occupied_cells",
        "minimum_macroregion_grid_coverage_rate",
        "minimum_land_grid_coverage_rate",
        "breadth_mode_minimum_land_macroregions",
        "core_country_longitude_band_count",
        "minimum_core_country_longitude_span_degrees",
        "minimum_overall_core_country_longitude_band_rate",
        "minimum_cells_per_core_country_longitude_band",
    }
    _exact_keys(global_scope, global_keys, "global_scope")
    normalized_global = dict(global_scope)
    normalized_global["grid_cell_degrees"] = _grid_size(
        global_scope["grid_cell_degrees"], "global_scope.grid_cell_degrees"
    )
    for key in (
        "priority_country_count",
        "core_priority_country_count",
        "minimum_country_canonical_samples",
        "minimum_country_occupied_cells",
        "maximum_country_occupied_cells",
        "minimum_macroregion_occupied_cells",
        "breadth_mode_minimum_land_macroregions",
        "core_country_longitude_band_count",
        "minimum_cells_per_core_country_longitude_band",
    ):
        normalized_global[key] = _positive_integer(
            global_scope[key], f"global_scope.{key}"
        )
    if (
        normalized_global["core_priority_country_count"]
        > normalized_global["priority_country_count"]
    ):
        raise SpatialSufficiencyPolicyError(
            "core_priority_country_count cannot exceed priority_country_count"
        )
    if not 2 <= normalized_global["core_country_longitude_band_count"] <= 12:
        raise SpatialSufficiencyPolicyError(
            "core_country_longitude_band_count must be between 2 and 12"
        )
    if (
        normalized_global["minimum_country_occupied_cells"]
        > normalized_global["maximum_country_occupied_cells"]
    ):
        raise SpatialSufficiencyPolicyError(
            "minimum_country_occupied_cells cannot exceed its maximum"
        )
    for key in (
        "minimum_priority_country_pass_rate",
        "minimum_country_grid_coverage_rate",
        "minimum_macroregion_grid_coverage_rate",
        "minimum_land_grid_coverage_rate",
        "minimum_overall_core_country_longitude_band_rate",
    ):
        normalized_global[key] = _fraction(global_scope[key], f"global_scope.{key}")
    excluded = global_scope.get("excluded_country_iso_a3")
    if (
        not isinstance(excluded, list)
        or len(excluded) != len(set(excluded))
        or any(
            not isinstance(item, str)
            or len(item) != 3
            or not item.isascii()
            or not item.isupper()
            for item in excluded
        )
    ):
        raise SpatialSufficiencyPolicyError(
            "global_scope.excluded_country_iso_a3 must contain unique ISO-A3 codes"
        )
    normalized_global["excluded_country_iso_a3"] = sorted(excluded)
    minimum_span = global_scope["minimum_core_country_longitude_span_degrees"]
    if (
        isinstance(minimum_span, bool)
        or not isinstance(minimum_span, (int, float))
        or not math.isfinite(float(minimum_span))
        or not 0 < float(minimum_span) <= 360
    ):
        raise SpatialSufficiencyPolicyError(
            "global_scope.minimum_core_country_longitude_span_degrees must be within (0, 360]"
        )
    normalized_global["minimum_core_country_longitude_span_degrees"] = float(
        minimum_span
    )

    regional_scope = value.get("regional_scope")
    if not isinstance(regional_scope, Mapping):
        raise SpatialSufficiencyPolicyError("regional_scope must be an object")
    regional_keys = {
        "allowed_grid_cell_degrees",
        "target_cells_across_long_axis",
        "minimum_assessable_coverage_cells",
        "minimum_canonical_samples",
        "minimum_grid_coverage_rate",
        "longitude_band_count",
        "latitude_band_count",
        "minimum_overall_coverage_zone_rate",
    }
    _exact_keys(regional_scope, regional_keys, "regional_scope")
    raw_sizes = regional_scope.get("allowed_grid_cell_degrees")
    if not isinstance(raw_sizes, list) or not raw_sizes:
        raise SpatialSufficiencyPolicyError(
            "regional_scope.allowed_grid_cell_degrees must be a non-empty array"
        )
    sizes = [
        _grid_size(item, "regional_scope.allowed_grid_cell_degrees")
        for item in raw_sizes
    ]
    if len(sizes) != len(set(sizes)) or sizes != sorted(sizes, reverse=True):
        raise SpatialSufficiencyPolicyError(
            "regional grid sizes must be unique and ordered largest to smallest"
        )
    normalized_regional = dict(regional_scope)
    normalized_regional["allowed_grid_cell_degrees"] = sizes
    for key in (
        "target_cells_across_long_axis",
        "minimum_assessable_coverage_cells",
        "minimum_canonical_samples",
        "longitude_band_count",
        "latitude_band_count",
    ):
        normalized_regional[key] = _positive_integer(
            regional_scope[key], f"regional_scope.{key}"
        )
    if normalized_regional["target_cells_across_long_axis"] < 2:
        raise SpatialSufficiencyPolicyError(
            "regional_scope.target_cells_across_long_axis must be at least 2"
        )
    for key in ("longitude_band_count", "latitude_band_count"):
        if not 2 <= normalized_regional[key] <= 12:
            raise SpatialSufficiencyPolicyError(
                f"regional_scope.{key} must be within [2, 12]"
            )
    normalized_regional["minimum_grid_coverage_rate"] = _fraction(
        regional_scope["minimum_grid_coverage_rate"],
        "regional_scope.minimum_grid_coverage_rate",
    )
    normalized_regional["minimum_overall_coverage_zone_rate"] = _fraction(
        regional_scope["minimum_overall_coverage_zone_rate"],
        "regional_scope.minimum_overall_coverage_zone_rate",
    )

    dimension_views = value.get("dimension_views")
    if not isinstance(dimension_views, Mapping):
        raise SpatialSufficiencyPolicyError("dimension_views must be an object")
    _exact_keys(dimension_views, set(VIEW_KINDS), "dimension_views")
    dimension_keys = {
        "minimum_canonical_samples",
        "minimum_occupied_cells",
        "overall_cell_target_fraction",
        "minimum_global_coverage_zones",
        "minimum_cells_per_global_coverage_zone",
        "minimum_regional_coverage_zone_rate",
        "maximum_country_targets",
        "minimum_core_country_longitude_band_rate",
    }
    normalized_dimensions: dict[str, dict[str, Any]] = {}
    for kind in VIEW_KINDS:
        rule = dimension_views.get(kind)
        if not isinstance(rule, Mapping):
            raise SpatialSufficiencyPolicyError(
                f"dimension_views.{kind} must be an object"
            )
        _exact_keys(rule, dimension_keys, f"dimension_views.{kind}")
        normalized_rule = dict(rule)
        for key in dimension_keys - {
            "overall_cell_target_fraction",
            "minimum_regional_coverage_zone_rate",
            "minimum_core_country_longitude_band_rate",
        }:
            normalized_rule[key] = _positive_integer(
                rule[key], f"dimension_views.{kind}.{key}"
            )
        normalized_rule["overall_cell_target_fraction"] = _fraction(
            rule["overall_cell_target_fraction"],
            f"dimension_views.{kind}.overall_cell_target_fraction",
        )
        normalized_rule["minimum_regional_coverage_zone_rate"] = _fraction(
            rule["minimum_regional_coverage_zone_rate"],
            f"dimension_views.{kind}.minimum_regional_coverage_zone_rate",
        )
        normalized_rule["minimum_core_country_longitude_band_rate"] = _fraction(
            rule["minimum_core_country_longitude_band_rate"],
            f"dimension_views.{kind}.minimum_core_country_longitude_band_rate",
        )
        normalized_dimensions[kind] = normalized_rule

    return {
        "policy_version": POLICY_VERSION,
        "global_scope": normalized_global,
        "regional_scope": normalized_regional,
        "dimension_views": normalized_dimensions,
        "claim_boundary": str(value["claim_boundary"]).strip(),
    }


@lru_cache(maxsize=8)
def _load_policy_cached(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SpatialSufficiencyPolicyError(
            f"spatial sufficiency policy does not exist: {path}"
        ) from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SpatialSufficiencyPolicyError(
            f"spatial sufficiency policy is unreadable: {path}"
        ) from exc
    return validate_policy(value)


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    """Load one strict, versioned policy from disk."""

    return _load_policy_cached(str(path.resolve()))


def longitude_span(bbox: Sequence[float]) -> float:
    west, _, east, _ = bbox
    return east - west if west <= east else 360.0 - west + east


def select_regional_grid_degrees(
    resolved_region: Mapping[str, Any], policy: Mapping[str, Any]
) -> float:
    """Choose a bounded grid resolution from scope extent, never its name."""

    bbox = resolved_region["bbox"]
    span = max(longitude_span(bbox), float(bbox[3]) - float(bbox[1]))
    regional = policy["regional_scope"]
    ideal = span / int(regional["target_cells_across_long_axis"])
    sizes = [float(size) for size in regional["allowed_grid_cell_degrees"]]
    # Always rounding down to the next finer grid creates a discontinuous
    # burden when a scope is just below a cutoff.  Multiplicative distance is
    # scale invariant; an exact tie deliberately prefers the coarser grid.
    return min(
        sizes,
        key=lambda size: (abs(math.log(size / ideal)), -size),
    )


def _ocean_coverage_zone(longitude: float) -> str:
    sector = min(5, max(0, math.floor((longitude + 180.0) / 60.0)))
    west = -180 + sector * 60
    east = west + 60
    return f"Open ocean longitude sector {west:+d}..{east:+d}"


def _longitude_offset(longitude: float, west: float) -> float:
    """Return eastward angular distance from ``west`` in [0, 360)."""

    return (longitude - west) % 360.0


def _regional_coverage_zone(
    longitude: float,
    latitude: float,
    bbox: Sequence[float],
    longitude_bands: int,
    latitude_bands: int,
) -> str:
    """Assign a point to a request-derived sector without place-name rules."""

    west, south, _, north = (float(item) for item in bbox)
    lon_span = longitude_span(bbox)
    lat_span = north - south
    longitude_index = min(
        longitude_bands - 1,
        max(
            0,
            math.floor(_longitude_offset(longitude, west) / lon_span * longitude_bands),
        ),
    )
    latitude_index = min(
        latitude_bands - 1,
        max(0, math.floor((latitude - south) / lat_span * latitude_bands)),
    )
    return (
        f"regional:r{latitude_index + 1}of{latitude_bands}:"
        f"c{longitude_index + 1}of{longitude_bands}"
    )


def _regional_zone_bbox(
    zone_id: str,
    bbox: Sequence[float],
    longitude_bands: int,
    latitude_bands: int,
) -> list[float]:
    """Resolve one deterministic regional sector to an auditable target bbox."""

    match = re.fullmatch(
        r"regional:r(?P<row>\d+)of(?P<rows>\d+):c(?P<column>\d+)of(?P<columns>\d+)",
        zone_id,
    )
    if match is None:
        raise SpatialSufficiencyPolicyError(f"invalid regional zone ID: {zone_id}")
    if int(match["rows"]) != latitude_bands or int(match["columns"]) != longitude_bands:
        raise SpatialSufficiencyPolicyError(f"regional zone policy mismatch: {zone_id}")
    row = int(match["row"]) - 1
    column = int(match["column"]) - 1
    west, south, _, north = (float(item) for item in bbox)
    lon_width = longitude_span(bbox) / longitude_bands
    lat_height = (north - south) / latitude_bands
    zone_west = ((west + column * lon_width + 180.0) % 360.0) - 180.0
    zone_east = ((west + (column + 1) * lon_width + 180.0) % 360.0) - 180.0
    zone_south = south + row * lat_height
    zone_north = south + (row + 1) * lat_height
    return [zone_west, zone_south, zone_east, zone_north]


def _minimal_circular_longitude_order(longitudes: Sequence[float]) -> list[float]:
    """Order longitude centres along their shortest occupied circular arc."""

    unique = sorted({((float(value) + 180.0) % 360.0) - 180.0 for value in longitudes})
    if len(unique) < 2:
        return unique
    circular = [value % 360.0 for value in unique]
    circular.sort()
    gaps = [
        ((circular[(index + 1) % len(circular)] - circular[index]) % 360.0, index)
        for index in range(len(circular))
    ]
    _, gap_index = max(gaps, key=lambda item: (item[0], -item[1]))
    start = (gap_index + 1) % len(circular)
    ordered = circular[start:] + circular[:start]
    return [((value + 180.0) % 360.0) - 180.0 for value in ordered]


def _core_country_longitude_bands(
    country_cells: Mapping[str, Sequence[str]],
    cell_degrees: float,
    global_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive generic west/central/east evidence bands for the largest countries.

    Bands use the frozen land-cell footprint rather than country names or a
    manually maintained region list.  Ordering follows the shortest occupied
    circular longitude arc, so countries crossing the antimeridian remain
    contiguous.  Cell-longitude quantiles keep every target band non-empty.
    """

    core_count = int(global_policy["core_priority_country_count"])
    band_count = int(global_policy["core_country_longitude_band_count"])
    minimum_span = float(global_policy["minimum_core_country_longitude_span_degrees"])
    ranked = sorted(
        country_cells,
        key=lambda code: (-len(country_cells[code]), code),
    )[:core_count]
    by_cell: dict[str, str] = {}
    cells_by_band: dict[str, list[str]] = {}
    bboxes: dict[str, list[float]] = {}
    bands_by_country: dict[str, list[str]] = {}
    eligible_codes: list[str] = []
    for code in ranked:
        centres = {
            cell_id: spatial_scope.coverage_grid_cell_center(cell_id, cell_degrees)
            for cell_id in country_cells[code]
        }
        ordered_longitudes = _minimal_circular_longitude_order(
            [point[0] for point in centres.values()]
        )
        if len(ordered_longitudes) < band_count:
            continue
        offsets = [
            _longitude_offset(value, ordered_longitudes[0])
            for value in ordered_longitudes
        ]
        occupied_span = max(offsets) - min(offsets) + cell_degrees
        if occupied_span < minimum_span:
            continue
        rank_by_longitude = {
            value: index for index, value in enumerate(ordered_longitudes)
        }
        country_band_ids = [
            f"country:{code}:longitude:{index + 1}of{band_count}"
            for index in range(band_count)
        ]
        bands_by_country[code] = country_band_ids
        eligible_codes.append(code)
        for cell_id, (longitude, _) in centres.items():
            rank = rank_by_longitude[longitude]
            band_index = min(
                band_count - 1,
                math.floor(rank * band_count / len(ordered_longitudes)),
            )
            band_id = country_band_ids[band_index]
            by_cell[cell_id] = band_id
            cells_by_band.setdefault(band_id, []).append(cell_id)
        for band_id in country_band_ids:
            band_cells = cells_by_band[band_id]
            points = [centres[cell_id] for cell_id in band_cells]
            ordered_band_longitudes = _minimal_circular_longitude_order(
                [point[0] for point in points]
            )
            west = ordered_band_longitudes[0] - cell_degrees / 2
            east = ordered_band_longitudes[-1] + cell_degrees / 2
            west = ((west + 180.0) % 360.0) - 180.0
            east = ((east + 180.0) % 360.0) - 180.0
            south = max(-90.0, min(point[1] for point in points) - cell_degrees / 2)
            north = min(90.0, max(point[1] for point in points) + cell_degrees / 2)
            bboxes[band_id] = [west, south, east, north]
    return {
        "core_country_codes": eligible_codes,
        "country_longitude_band_by_cell": dict(sorted(by_cell.items())),
        "country_longitude_band_cells": {
            band_id: sorted(cells) for band_id, cells in sorted(cells_by_band.items())
        },
        "country_longitude_band_bboxes": dict(sorted(bboxes.items())),
        "country_longitude_bands": {
            code: list(bands) for code, bands in sorted(bands_by_country.items())
        },
    }


def build_scope_coverage_grid(
    resolved_region: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    spatial_domains: Sequence[str] = ("land",),
    adjacent_marine_distance_km: float = 0.0,
) -> dict[str, Any]:
    """Build request cells plus land and ocean audit-zone evidence."""

    global_scope = resolved_region.get("key") == "global"
    analysis_bbox = spatial_scope.request_analysis_bbox(
        resolved_region, spatial_domains, adjacent_marine_distance_km
    )
    country_by_cell: dict[str, str]
    target_cell_ids: set[str]
    if global_scope:
        cell_degrees = float(policy["global_scope"]["grid_cell_degrees"])
        frozen = spatial_scope.load_global_land_grid(cell_degrees)
        excluded = set(policy["global_scope"]["excluded_country_iso_a3"])
        country_by_cell = {
            cell_id: code
            for cell_id, code in frozen["country_by_cell"].items()
            if code not in excluded
        }
        longitude_cells = round(360 / cell_degrees)
        latitude_cells = round(180 / cell_degrees)
        target_cell_ids = {
            spatial_scope.coverage_grid_cell_id(
                -180.0 + (longitude_index + 0.5) * cell_degrees,
                -90.0 + (latitude_index + 0.5) * cell_degrees,
                cell_degrees,
            )
            for latitude_index in range(latitude_cells)
            for longitude_index in range(longitude_cells)
        }
        target_cell_ids.difference_update(
            cell_id
            for cell_id, code in frozen["country_by_cell"].items()
            if code in excluded
        )
    else:
        cell_degrees = select_regional_grid_degrees(resolved_region, policy)
        longitude_cells = round(360 / cell_degrees)
        latitude_cells = round(180 / cell_degrees)
        country_by_cell = {}
        target_cell_ids = set()
        bbox = analysis_bbox
        country_limited = bool(resolved_region.get("country_code"))
        for latitude_index in range(latitude_cells):
            latitude = -90.0 + (latitude_index + 0.5) * cell_degrees
            if not float(bbox[1]) <= latitude <= float(bbox[3]):
                continue
            for longitude_index in range(longitude_cells):
                longitude = -180.0 + (longitude_index + 0.5) * cell_degrees
                if not spatial_scope.coordinate_in_bbox(longitude, latitude, bbox):
                    continue
                country_code = spatial_scope.country_at_coordinate(longitude, latitude)
                if country_limited:
                    on_requested_land = spatial_scope.coordinate_in_request_scope(
                        longitude,
                        latitude,
                        resolved_region,
                        spatial_domain="land",
                        spatial_domains=spatial_domains,
                        adjacent_marine_distance_km=adjacent_marine_distance_km,
                    )
                    in_adjacent_ocean = (
                        country_code is None
                        and spatial_scope.coordinate_in_request_scope(
                            longitude,
                            latitude,
                            resolved_region,
                            spatial_domain="marine",
                            spatial_domains=spatial_domains,
                            adjacent_marine_distance_km=adjacent_marine_distance_km,
                        )
                    )
                    if not (on_requested_land or in_adjacent_ocean):
                        continue
                cell_id = spatial_scope.coverage_grid_cell_id(
                    longitude, latitude, cell_degrees
                )
                target_cell_ids.add(cell_id)
                if country_code is None:
                    continue
                country_by_cell[cell_id] = country_code

    macroregions = spatial_scope.load_macroregion_registry()
    regional = policy["regional_scope"]
    longitude_bands = int(regional["longitude_band_count"])
    latitude_bands = int(regional["latitude_band_count"])
    coverage_zone_by_cell: dict[str, str] = {}
    for cell_id in target_cell_ids:
        longitude, latitude = spatial_scope.coverage_grid_cell_center(
            cell_id, cell_degrees
        )
        country_code = country_by_cell.get(cell_id)
        if not global_scope:
            coverage_zone_by_cell[cell_id] = _regional_coverage_zone(
                longitude,
                latitude,
                analysis_bbox,
                longitude_bands,
                latitude_bands,
            )
        elif country_code in macroregions:
            coverage_zone_by_cell[cell_id] = macroregions[country_code]
        else:
            coverage_zone_by_cell[cell_id] = _ocean_coverage_zone(longitude)
    country_cells: dict[str, list[str]] = {}
    coverage_zone_cells: dict[str, list[str]] = {}
    for cell_id, country_code in country_by_cell.items():
        country_cells.setdefault(country_code, []).append(cell_id)
    for cell_id, zone in coverage_zone_by_cell.items():
        coverage_zone_cells.setdefault(zone, []).append(cell_id)
    coverage_zone_bboxes = (
        {}
        if global_scope
        else {
            zone: _regional_zone_bbox(
                zone, analysis_bbox, longitude_bands, latitude_bands
            )
            for zone in coverage_zone_cells
        }
    )
    country_longitude_bands = (
        _core_country_longitude_bands(
            country_cells,
            cell_degrees,
            policy["global_scope"],
        )
        if global_scope
        else {
            "core_country_codes": [],
            "country_longitude_band_by_cell": {},
            "country_longitude_band_cells": {},
            "country_longitude_band_bboxes": {},
            "country_longitude_bands": {},
        }
    )
    return {
        "cell_degrees": cell_degrees,
        "target_cell_ids": sorted(target_cell_ids),
        "reference_land_cell_ids": sorted(country_by_cell),
        "country_by_cell": dict(sorted(country_by_cell.items())),
        "coverage_zone_by_cell": dict(sorted(coverage_zone_by_cell.items())),
        "country_cells": {
            code: sorted(cells) for code, cells in sorted(country_cells.items())
        },
        "coverage_zone_cells": {
            zone: sorted(cells) for zone, cells in sorted(coverage_zone_cells.items())
        },
        "coverage_zone_bboxes": dict(sorted(coverage_zone_bboxes.items())),
        **country_longitude_bands,
    }


def _view_specs(request: Mapping[str, Any]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "view_id": "overall",
            "view_kind": "overall",
            "required_elements": [],
            "required_media": [],
        }
    ]
    for element in request.get("elements") or []:
        specs.append(
            {
                "view_id": f"element:{element}",
                "view_kind": "element",
                "required_elements": [str(element)],
                "required_media": [],
            }
        )
    for medium in request.get("media") or []:
        specs.append(
            {
                "view_id": f"medium:{medium}",
                "view_kind": "medium",
                "required_elements": [],
                "required_media": [str(medium)],
            }
        )
    for element in request.get("elements") or []:
        for medium in request.get("media") or []:
            specs.append(
                {
                    "view_id": f"element_medium:{element}|{medium}",
                    "view_kind": "element_medium",
                    "required_elements": [str(element)],
                    "required_media": [str(medium)],
                }
            )
    return specs


def _sample_matches(sample: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    kind = spec["view_kind"]
    if kind == "overall":
        return True
    elements = {str(item) for item in sample.get("elements") or []}
    media = {str(item) for item in sample.get("media") or []}
    if kind == "element":
        return spec["required_elements"][0] in elements
    if kind == "medium":
        return spec["required_media"][0] in media
    pair = f"{spec['required_elements'][0]}|{spec['required_media'][0]}"
    return pair in {str(item) for item in sample.get("element_medium") or []}


def _point(sample: Mapping[str, Any], key: str) -> tuple[float, float] | None:
    raw = sample.get(key)
    if not isinstance(raw, list) or len(raw) != 2:
        return None
    try:
        longitude, latitude = (float(item) for item in raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    return longitude, latitude


def _occupancy(
    samples: Sequence[Mapping[str, Any]],
    spec: Mapping[str, Any],
    grid: Mapping[str, Any],
    resolved_region: Mapping[str, Any],
    request: Mapping[str, Any],
    point_key: str,
) -> dict[str, Any]:
    target_cells = set(grid["target_cell_ids"])
    occupied: set[str] = set()
    sample_count = 0
    for sample in samples:
        if not _sample_matches(sample, spec):
            continue
        point = _point(sample, point_key)
        if point is None:
            continue
        try:
            sample_domains = {
                str(item) for item in sample.get("spatial_domains") or []
            } or {"land"}
            if not any(
                spatial_scope.coordinate_in_request_scope(
                    *point,
                    resolved_region,
                    spatial_domain=domain,
                    spatial_domains=request.get("spatial_domains") or ["land"],
                    adjacent_marine_distance_km=float(
                        request.get("adjacent_marine_distance_km") or 0
                    ),
                )
                for domain in sample_domains
            ):
                continue
            cell_id = spatial_scope.coverage_grid_cell_id(
                *point, float(grid["cell_degrees"])
            )
        except spatial_scope.SpatialScopeError:
            continue
        if cell_id not in target_cells:
            continue
        sample_count += 1
        occupied.add(cell_id)
    by_country: dict[str, int] = {}
    by_coverage_zone: dict[str, int] = {}
    by_country_longitude_band: dict[str, int] = {}
    for cell_id in occupied:
        country = grid["country_by_cell"].get(cell_id)
        coverage_zone = grid["coverage_zone_by_cell"].get(cell_id)
        country_longitude_band = grid["country_longitude_band_by_cell"].get(cell_id)
        if country:
            by_country[country] = by_country.get(country, 0) + 1
        if coverage_zone:
            by_coverage_zone[coverage_zone] = by_coverage_zone.get(coverage_zone, 0) + 1
        if country_longitude_band:
            by_country_longitude_band[country_longitude_band] = (
                by_country_longitude_band.get(country_longitude_band, 0) + 1
            )
    return {
        "unique_samples": sample_count,
        "occupied_grid_cells": len(occupied),
        "occupied_grid_cell_ids": sorted(occupied),
        "country_occupied_grid_cells": dict(sorted(by_country.items())),
        "coverage_zone_occupied_grid_cells": dict(sorted(by_coverage_zone.items())),
        "country_longitude_band_occupied_grid_cells": dict(
            sorted(by_country_longitude_band.items())
        ),
    }


def _minimum_overall_cells(
    target_cell_count: int, global_scope: bool, policy: Mapping[str, Any]
) -> int:
    if target_cell_count <= 0:
        return 0
    if global_scope:
        rate = float(policy["global_scope"]["minimum_land_grid_coverage_rate"])
        minimum = 1
    else:
        regional = policy["regional_scope"]
        rate = float(regional["minimum_grid_coverage_rate"])
        minimum = int(regional["minimum_assessable_coverage_cells"])
    return min(target_cell_count, max(minimum, math.ceil(target_cell_count * rate)))


def audit_spatial_views(
    spatial_samples: Sequence[Mapping[str, Any]],
    request: Mapping[str, Any],
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit all request-derived map views and return exact gap facts."""

    selected_policy = dict(policy or load_policy())
    resolved = spatial_scope.resolve_region(request.get("region"))
    grid = build_scope_coverage_grid(
        resolved,
        selected_policy,
        spatial_domains=request.get("spatial_domains") or ["land"],
        adjacent_marine_distance_km=float(
            request.get("adjacent_marine_distance_km") or 0
        ),
    )
    global_scope = resolved["key"] == "global"
    country_band_scope = global_scope and "land" in set(
        request.get("spatial_domains") or ["land"]
    )
    breadth_mode = bool(
        global_scope and request.get("coverage_mode") == "maximize_evidence_breadth"
    )
    land_macroregions = (
        sorted(
            {
                zone
                for zone in grid["coverage_zone_cells"]
                if not str(zone).startswith("Open ocean")
            }
        )
        if global_scope
        else []
    )
    target_coverage_zones = sorted(grid["coverage_zone_cells"])
    target_cell_count = len(grid["target_cell_ids"])
    reference_cell_count = len(grid["reference_land_cell_ids"])
    overall_cell_minimum = _minimum_overall_cells(
        reference_cell_count or target_cell_count, global_scope, selected_policy
    )
    regional_minimum = int(
        selected_policy["regional_scope"]["minimum_assessable_coverage_cells"]
    )
    assessable = target_cell_count > 0 and (
        global_scope or target_cell_count >= regional_minimum
    )
    views: list[dict[str, Any]] = []
    for spec in _view_specs(request):
        kind = str(spec["view_kind"])
        if kind == "overall":
            minimum_samples = (
                int(
                    selected_policy["global_scope"]["minimum_country_canonical_samples"]
                )
                if country_band_scope
                else int(selected_policy["regional_scope"]["minimum_canonical_samples"])
            )
            minimum_cells = overall_cell_minimum
            minimum_coverage_zones = (
                0
                if country_band_scope
                else math.ceil(
                    len(target_coverage_zones)
                    * float(
                        selected_policy["regional_scope"][
                            "minimum_overall_coverage_zone_rate"
                        ]
                    )
                )
            )
            minimum_cells_per_coverage_zone = 0 if global_scope else 1
            minimum_core_country_longitude_band_rate = (
                float(
                    selected_policy["global_scope"][
                        "minimum_overall_core_country_longitude_band_rate"
                    ]
                )
                if global_scope
                else 0.0
            )
        else:
            rule = selected_policy["dimension_views"][kind]
            minimum_samples = int(rule["minimum_canonical_samples"])
            minimum_cells = min(
                target_cell_count,
                max(
                    int(rule["minimum_occupied_cells"]),
                    math.ceil(
                        overall_cell_minimum
                        * float(rule["overall_cell_target_fraction"])
                    ),
                ),
            )
            minimum_coverage_zones = (
                int(rule["minimum_global_coverage_zones"])
                if global_scope
                else math.ceil(
                    len(target_coverage_zones)
                    * float(rule["minimum_regional_coverage_zone_rate"])
                )
            )
            minimum_cells_per_coverage_zone = (
                int(rule["minimum_cells_per_global_coverage_zone"])
                if global_scope
                else 1
            )
            minimum_core_country_longitude_band_rate = (
                float(rule["minimum_core_country_longitude_band_rate"])
                if global_scope
                else 0.0
            )
        canonical = _occupancy(
            spatial_samples, spec, grid, resolved, request, "canonical_point"
        )
        displayed = _occupancy(
            spatial_samples, spec, grid, resolved, request, "display_point"
        )
        minimum_cells_per_core_country_band = (
            int(
                selected_policy["global_scope"][
                    "minimum_cells_per_core_country_longitude_band"
                ]
            )
            if global_scope
            else 0
        )
        country_longitude_band_metrics: dict[str, dict[str, Any]] = {}
        missing_country_longitude_band_targets: list[dict[str, Any]] = []
        core_country_longitude_bands_pass = True
        display_core_country_longitude_bands_pass = True
        for country_code in grid["core_country_codes"] if country_band_scope else []:
            target_bands = list(grid["country_longitude_bands"][country_code])
            minimum_bands = math.ceil(
                len(target_bands) * minimum_core_country_longitude_band_rate
            )
            canonical_bands = [
                band_id
                for band_id in target_bands
                if int(
                    canonical["country_longitude_band_occupied_grid_cells"].get(
                        band_id, 0
                    )
                )
                >= minimum_cells_per_core_country_band
            ]
            display_bands = [
                band_id
                for band_id in target_bands
                if int(
                    displayed["country_longitude_band_occupied_grid_cells"].get(
                        band_id, 0
                    )
                )
                >= minimum_cells_per_core_country_band
            ]
            missing_bands = [
                band_id for band_id in target_bands if band_id not in canonical_bands
            ]
            country_passes = len(canonical_bands) >= minimum_bands
            display_country_passes = len(display_bands) >= minimum_bands
            core_country_longitude_bands_pass = (
                core_country_longitude_bands_pass and country_passes
            )
            display_core_country_longitude_bands_pass = (
                display_core_country_longitude_bands_pass and display_country_passes
            )
            country_longitude_band_metrics[country_code] = {
                "target_band_ids": target_bands,
                "qualifying_canonical_band_ids": canonical_bands,
                "qualifying_reported_display_band_ids": display_bands,
                "missing_canonical_band_ids": missing_bands,
                "minimum_qualifying_bands": minimum_bands,
                "passes": country_passes,
            }
            if not country_passes:
                for band_id in missing_bands:
                    missing_country_longitude_band_targets.append(
                        {
                            "country_iso_a3": country_code,
                            "band_id": band_id,
                            "bbox": list(
                                grid["country_longitude_band_bboxes"][band_id]
                            ),
                            "target_grid_cells": len(
                                grid["country_longitude_band_cells"][band_id]
                            ),
                            "canonical_occupied_grid_cells": int(
                                canonical[
                                    "country_longitude_band_occupied_grid_cells"
                                ].get(band_id, 0)
                            ),
                            "reported_display_occupied_grid_cells": int(
                                displayed[
                                    "country_longitude_band_occupied_grid_cells"
                                ].get(band_id, 0)
                            ),
                        }
                    )
        qualifying_coverage_zones = sorted(
            region
            for region, count in canonical["coverage_zone_occupied_grid_cells"].items()
            if count >= minimum_cells_per_coverage_zone
        )
        display_qualifying_coverage_zones = sorted(
            region
            for region, count in displayed["coverage_zone_occupied_grid_cells"].items()
            if count >= minimum_cells_per_coverage_zone
        )
        missing_coverage_zones = (
            []
            if global_scope
            else sorted(set(target_coverage_zones) - set(qualifying_coverage_zones))
        )
        coverage_zone_targets = [
            {
                "zone_id": zone,
                "bbox": list(grid["coverage_zone_bboxes"][zone]),
                "target_grid_cells": len(grid["coverage_zone_cells"][zone]),
                "canonical_occupied_grid_cells": int(
                    canonical["coverage_zone_occupied_grid_cells"].get(zone, 0)
                ),
                "reported_display_occupied_grid_cells": int(
                    displayed["coverage_zone_occupied_grid_cells"].get(zone, 0)
                ),
            }
            for zone in missing_coverage_zones
        ]
        samples_pass = canonical["unique_samples"] >= minimum_samples
        cells_pass = canonical["occupied_grid_cells"] >= minimum_cells
        coverage_zones_pass = len(qualifying_coverage_zones) >= minimum_coverage_zones
        minimum_land_macroregions = (
            int(
                selected_policy["global_scope"][
                    "breadth_mode_minimum_land_macroregions"
                ]
            )
            if breadth_mode
            else 0
        )
        land_zone_cell_minimum = max(1, minimum_cells_per_coverage_zone)
        covered_land_macroregions = sorted(
            region
            for region in land_macroregions
            if int(canonical["coverage_zone_occupied_grid_cells"].get(region, 0))
            >= land_zone_cell_minimum
        )
        missing_land_macroregions = sorted(
            set(land_macroregions) - set(covered_land_macroregions)
        )
        land_macroregions_pass = (
            len(covered_land_macroregions) >= minimum_land_macroregions
        )
        display_covered_land_macroregions = sorted(
            region
            for region in land_macroregions
            if int(displayed["coverage_zone_occupied_grid_cells"].get(region, 0))
            >= land_zone_cell_minimum
        )
        display_land_macroregions_pass = (
            len(display_covered_land_macroregions) >= minimum_land_macroregions
        )
        passes = (
            assessable
            and samples_pass
            and cells_pass
            and coverage_zones_pass
            and land_macroregions_pass
            and core_country_longitude_bands_pass
        )
        reasons: list[str] = []
        if assessable and not samples_pass:
            reasons.append("canonical_sample_shortfall")
        if assessable and not cells_pass:
            reasons.append("canonical_cell_shortfall")
        if assessable and not coverage_zones_pass:
            reasons.append("canonical_coverage_zone_shortfall")
        if assessable and not land_macroregions_pass:
            reasons.append("land_macroregion_coverage_debt")
        if assessable and not core_country_longitude_bands_pass:
            reasons.append("core_country_longitude_band_coverage_debt")
        display_would_pass = (
            displayed["unique_samples"] >= minimum_samples
            and displayed["occupied_grid_cells"] >= minimum_cells
            and len(display_qualifying_coverage_zones) >= minimum_coverage_zones
            and display_land_macroregions_pass
            and display_core_country_longitude_bands_pass
        )
        if assessable and not passes and display_would_pass:
            reasons.append("reported_only_coordinate_evidence")
        views.append(
            {
                **spec,
                "canonical_unique_samples": canonical["unique_samples"],
                "reported_display_unique_samples": displayed["unique_samples"],
                "canonical_occupied_grid_cells": canonical["occupied_grid_cells"],
                "reported_display_occupied_grid_cells": displayed[
                    "occupied_grid_cells"
                ],
                "minimum_canonical_unique_samples": minimum_samples,
                "minimum_canonical_occupied_grid_cells": minimum_cells,
                "canonical_country_occupied_grid_cells": canonical[
                    "country_occupied_grid_cells"
                ],
                "canonical_coverage_zone_occupied_grid_cells": canonical[
                    "coverage_zone_occupied_grid_cells"
                ],
                "qualifying_coverage_zones": qualifying_coverage_zones,
                "target_coverage_zones": target_coverage_zones,
                "missing_coverage_zones": missing_coverage_zones,
                "coverage_zone_targets": coverage_zone_targets,
                "minimum_qualifying_coverage_zones": minimum_coverage_zones,
                "minimum_cells_per_qualifying_coverage_zone": (
                    minimum_cells_per_coverage_zone
                ),
                "breadth_mode": breadth_mode,
                "covered_land_macroregions": covered_land_macroregions,
                "missing_land_macroregions": missing_land_macroregions,
                "minimum_land_macroregions": minimum_land_macroregions,
                "core_country_longitude_band_metrics": (country_longitude_band_metrics),
                "country_longitude_band_targets": (
                    missing_country_longitude_band_targets
                ),
                "minimum_cells_per_core_country_longitude_band": (
                    minimum_cells_per_core_country_band
                ),
                "minimum_core_country_longitude_band_rate": (
                    minimum_core_country_longitude_band_rate
                ),
                "reason_codes": reasons,
                "status": "pass" if passes else "gap" if assessable else "unassessable",
                "passes": passes,
            }
        )
    return {
        "policy_version": selected_policy["policy_version"],
        "scope": {
            "key": resolved["key"],
            "label": resolved["label"],
            "country_iso_a3": resolved.get("country_code"),
            "analysis_country_iso_a3": list(
                resolved.get("analysis_country_codes")
                or ([resolved["country_code"]] if resolved.get("country_code") else [])
            ),
            "bbox": list(resolved["bbox"]),
            "analysis_bbox": spatial_scope.request_analysis_bbox(
                resolved,
                request.get("spatial_domains") or ["land"],
                float(request.get("adjacent_marine_distance_km") or 0),
            ),
            "spatial_domains": list(request.get("spatial_domains") or ["land"]),
            "adjacent_marine_distance_km": float(
                request.get("adjacent_marine_distance_km") or 0
            ),
            "clip_method": resolved["clip_method"],
            "boundary_semantics": resolved.get("boundary_semantics"),
            "cartographic_reference": resolved.get("cartographic_reference"),
            "global": global_scope,
        },
        "grid_cell_degrees": grid["cell_degrees"],
        "target_coverage_grid_cells": target_cell_count,
        "reference_land_grid_cells": reference_cell_count,
        "minimum_overall_occupied_grid_cells": overall_cell_minimum,
        "assessable": assessable,
        "views": views,
        "passes": assessable and all(item["passes"] for item in views),
        "claim_boundary": selected_policy["claim_boundary"],
    }


def rank_global_country_targets(
    view: Mapping[str, Any], policy: Mapping[str, Any] | None = None
) -> list[str]:
    """Rank country backfills from a failed view without a named-country list."""

    selected_policy = dict(policy or load_policy())
    global_policy = selected_policy["global_scope"]
    land_grid = spatial_scope.load_global_land_grid(
        float(global_policy["grid_cell_degrees"])
    )
    macroregions = spatial_scope.load_macroregion_registry()
    excluded = set(global_policy["excluded_country_iso_a3"])
    country_cells = {
        code: set(cells)
        for code, cells in land_grid["country_cells"].items()
        if code not in excluded
    }
    occupied = {
        str(code): int(count)
        for code, count in (
            view.get("canonical_country_occupied_grid_cells") or {}
        ).items()
    }
    eligible = sorted(
        country_cells,
        key=lambda code: (-len(country_cells[code]), code),
    )
    priority_count = int(global_policy["priority_country_count"])
    priority_rank = {
        code: index for index, code in enumerate(eligible[:priority_count])
    }
    maximum_targets = (
        int(
            selected_policy["dimension_views"][view["view_kind"]][
                "maximum_country_targets"
            ]
        )
        if view.get("view_kind") in VIEW_KINDS
        else int(global_policy["core_priority_country_count"])
    )
    # Prefer the exact debt emitted by ``audit_spatial_views``.  Recomputing
    # it from the legacy coverage-zone threshold is unsafe for the overall
    # view because that view historically used a zero threshold: every
    # macroregion would then appear covered even when it contained no sample.
    declared_missing = view.get("missing_land_macroregions")
    if isinstance(declared_missing, list):
        known_land_macroregions = {str(region) for region in macroregions.values()}
        missing_land_coverage_zones = sorted(
            {
                str(region)
                for region in declared_missing
                if str(region) in known_land_macroregions
            }
        )
    else:
        minimum_cells_per_coverage_zone = max(
            1,
            int(view.get("minimum_cells_per_qualifying_coverage_zone") or 0),
        )
        observed_by_coverage_zone = (
            view.get("canonical_coverage_zone_occupied_grid_cells") or {}
        )
        missing_land_coverage_zones = sorted(
            {macroregions[code] for code in country_cells if code in macroregions}
            - {
                str(region)
                for region, count in observed_by_coverage_zone.items()
                if int(count) >= minimum_cells_per_coverage_zone
            }
        )
    selected: list[str] = []
    for region in missing_land_coverage_zones:
        candidates = [
            code
            for code in eligible
            if macroregions.get(code) == region
            and len(country_cells[code]) > occupied.get(code, 0)
        ]
        if candidates:
            selected.append(candidates[0])
        if len(selected) >= maximum_targets:
            return selected
    for target in view.get("country_longitude_band_targets") or []:
        if not isinstance(target, Mapping):
            continue
        code = str(target.get("country_iso_a3") or "")
        if code in country_cells and code not in selected:
            selected.append(code)
        if len(selected) >= maximum_targets:
            return selected
    remaining = sorted(
        (
            code
            for code in eligible
            if code not in selected and len(country_cells[code]) > occupied.get(code, 0)
        ),
        key=lambda code: (
            0 if code in priority_rank else 1,
            priority_rank.get(code, priority_count),
            -(len(country_cells[code]) - occupied.get(code, 0)),
            code,
        ),
    )
    selected.extend(remaining[: max(0, maximum_targets - len(selected))])
    return selected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate the versioned atlas spatial sufficiency policy."
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY_PATH)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
    except SpatialSufficiencyPolicyError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"status": "PASS", "policy_version": policy["policy_version"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
