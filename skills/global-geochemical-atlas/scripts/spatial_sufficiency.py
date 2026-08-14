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
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import spatial_scope


SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_POLICY_PATH = SKILL_DIR / "assets" / "spatial-sufficiency-policy.json"
POLICY_VERSION = "atlas-spatial-sufficiency-policy-v3"
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

    regional_scope = value.get("regional_scope")
    if not isinstance(regional_scope, Mapping):
        raise SpatialSufficiencyPolicyError("regional_scope must be an object")
    regional_keys = {
        "allowed_grid_cell_degrees",
        "target_cells_across_long_axis",
        "minimum_assessable_coverage_cells",
        "minimum_canonical_samples",
        "minimum_grid_coverage_rate",
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
    ):
        normalized_regional[key] = _positive_integer(
            regional_scope[key], f"regional_scope.{key}"
        )
    normalized_regional["minimum_grid_coverage_rate"] = _fraction(
        regional_scope["minimum_grid_coverage_rate"],
        "regional_scope.minimum_grid_coverage_rate",
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
        "maximum_country_targets",
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
        for key in dimension_keys - {"overall_cell_target_fraction"}:
            normalized_rule[key] = _positive_integer(
                rule[key], f"dimension_views.{kind}.{key}"
            )
        normalized_rule["overall_cell_target_fraction"] = _fraction(
            rule["overall_cell_target_fraction"],
            f"dimension_views.{kind}.overall_cell_target_fraction",
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


def build_scope_coverage_grid(
    resolved_region: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    spatial_domains: Sequence[str] = ("land",),
    adjacent_marine_distance_km: float = 0.0,
) -> dict[str, Any]:
    """Build request cells plus land and ocean audit-zone evidence."""

    global_scope = resolved_region.get("key") == "global"
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
        bbox = spatial_scope.request_analysis_bbox(
            resolved_region, spatial_domains, adjacent_marine_distance_km
        )
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
    coverage_zone_by_cell: dict[str, str] = {}
    for cell_id in target_cell_ids:
        country_code = country_by_cell.get(cell_id)
        if country_code in macroregions:
            coverage_zone_by_cell[cell_id] = macroregions[country_code]
        else:
            longitude, _ = spatial_scope.coverage_grid_cell_center(
                cell_id, cell_degrees
            )
            coverage_zone_by_cell[cell_id] = _ocean_coverage_zone(longitude)
    country_cells: dict[str, list[str]] = {}
    coverage_zone_cells: dict[str, list[str]] = {}
    for cell_id, country_code in country_by_cell.items():
        country_cells.setdefault(country_code, []).append(cell_id)
    for cell_id, zone in coverage_zone_by_cell.items():
        coverage_zone_cells.setdefault(zone, []).append(cell_id)
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
    for cell_id in occupied:
        country = grid["country_by_cell"].get(cell_id)
        coverage_zone = grid["coverage_zone_by_cell"].get(cell_id)
        if country:
            by_country[country] = by_country.get(country, 0) + 1
        if coverage_zone:
            by_coverage_zone[coverage_zone] = by_coverage_zone.get(coverage_zone, 0) + 1
    return {
        "unique_samples": sample_count,
        "occupied_grid_cells": len(occupied),
        "country_occupied_grid_cells": dict(sorted(by_country.items())),
        "coverage_zone_occupied_grid_cells": dict(sorted(by_coverage_zone.items())),
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
    breadth_mode = bool(
        global_scope and request.get("coverage_mode") == "maximize_evidence_breadth"
    )
    land_macroregions = sorted(
        {
            zone
            for zone in grid["coverage_zone_cells"]
            if not str(zone).startswith("Open ocean")
        }
    )
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
                if global_scope
                else int(selected_policy["regional_scope"]["minimum_canonical_samples"])
            )
            minimum_cells = overall_cell_minimum
            minimum_coverage_zones = 0
            minimum_cells_per_coverage_zone = 0
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
                int(rule["minimum_global_coverage_zones"]) if global_scope else 0
            )
            minimum_cells_per_coverage_zone = (
                int(rule["minimum_cells_per_global_coverage_zone"])
                if global_scope
                else 0
            )
        canonical = _occupancy(
            spatial_samples, spec, grid, resolved, request, "canonical_point"
        )
        displayed = _occupancy(
            spatial_samples, spec, grid, resolved, request, "display_point"
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
        display_would_pass = (
            displayed["unique_samples"] >= minimum_samples
            and displayed["occupied_grid_cells"] >= minimum_cells
            and len(display_qualifying_coverage_zones) >= minimum_coverage_zones
            and display_land_macroregions_pass
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
                "minimum_qualifying_coverage_zones": minimum_coverage_zones,
                "minimum_cells_per_qualifying_coverage_zone": (
                    minimum_cells_per_coverage_zone
                ),
                "breadth_mode": breadth_mode,
                "covered_land_macroregions": covered_land_macroregions,
                "missing_land_macroregions": missing_land_macroregions,
                "minimum_land_macroregions": minimum_land_macroregions,
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
