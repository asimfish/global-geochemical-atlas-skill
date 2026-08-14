#!/usr/bin/env python3
"""Route a geochemical request by research-use, evidence tier and current use mode."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters
import score_source_evidence
import spatial_scope

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"
FULL_PROFILE_ROOT = SKILL_DIR / "assets" / "v4-full-profiles"

CATALOG_VERSION = "geochemical-source-catalog-v1"
ROUTE_VERSION = "geochemical-source-route-v5"
VALID_MEDIA = {"rock", "soil", "sediment", "water", "mineral", "concentrate"}
VALID_SPATIAL_DOMAINS = set(spatial_scope.VALID_SPATIAL_DOMAINS)
VALID_OUTPUT_FORMATS = {"csv", "json", "geojson", "html_map"}
VALID_SOURCE_STATUS = {
    "approved",
    "conditional",
    "metadata_only",
    "needs_human_review",
    "rejected",
}
ALLOWED_REQUEST_KEYS = {
    "elements",
    "region",
    "media",
    "coverage_mode",
    "minimum_elements",
    "minimum_media",
    "spatial_domains",
    "adjacent_marine_distance_km",
    "measurement_basis",
    "geology_units",
    "geology_match",
    "time_range",
    "sources",
    "output_formats",
    "target_crs",
    "license_policy",
    "research_use_policy",
    "minimum_evidence_tier",
    "minimum_use_mode",
    "max_records",
    "offline",
}


class SourceRoutingError(ValueError):
    """Raised when the catalog or routing request is invalid."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceRoutingError(f"{label} does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceRoutingError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SourceRoutingError(f"{label} must be a JSON object")
    return value


def load_catalog(path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    """Load and fail-closed validate the source discovery catalog."""

    catalog = _read_json(path, "source catalog")
    if catalog.get("catalog_version") != CATALOG_VERSION:
        raise SourceRoutingError("unsupported source catalog version")
    sources = catalog.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise SourceRoutingError(
            "source catalog must contain a non-empty sources object"
        )
    for source_id, entry in sources.items():
        if (
            not isinstance(source_id, str)
            or not source_id
            or not isinstance(entry, dict)
        ):
            raise SourceRoutingError("source catalog contains an invalid source entry")
        required = {
            "title",
            "publisher",
            "status",
            "production_eligible",
            "media",
            "coverage",
            "landing_page",
            "interfaces",
            "license",
            "version",
            "adapter",
            "evidence_urls",
            "limitations",
        }
        missing = sorted(required - set(entry))
        if missing:
            raise SourceRoutingError(
                f"catalog source {source_id} lacks keys: {', '.join(missing)}"
            )
        status = entry.get("status")
        if status not in VALID_SOURCE_STATUS:
            raise SourceRoutingError(
                f"catalog source {source_id} has invalid status: {status}"
            )
        media = entry.get("media")
        if (
            not isinstance(media, list)
            or not media
            or not set(media).issubset(VALID_MEDIA)
        ):
            raise SourceRoutingError(f"catalog source {source_id} has invalid media")
        if not isinstance(entry.get("production_eligible"), bool):
            raise SourceRoutingError(
                f"catalog source {source_id} has invalid legacy production_eligible flag"
            )
    discovery = catalog.get("discovery_state")
    if not isinstance(discovery, dict) or not isinstance(
        discovery.get("saturated"), bool
    ):
        raise SourceRoutingError("source catalog has invalid discovery_state")
    return catalog


def validate_request(
    request: Mapping[str, Any], catalog: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the shared v1 request fields needed for source routing."""

    unknown_keys = sorted(set(request) - ALLOWED_REQUEST_KEYS)
    if unknown_keys:
        raise SourceRoutingError(
            f"request has unsupported keys: {', '.join(unknown_keys)}"
        )
    elements = request.get("elements")
    if (
        not isinstance(elements, list)
        or not elements
        or not all(isinstance(item, str) and item.strip() for item in elements)
        or len(elements) != len(set(elements))
    ):
        raise SourceRoutingError("request elements must be a non-empty string array")
    media = request.get("media")
    if (
        not isinstance(media, list)
        or not media
        or not all(isinstance(item, str) for item in media)
        or len(media) != len(set(media))
    ):
        raise SourceRoutingError("request media must be a non-empty unique array")
    if not set(media).issubset(VALID_MEDIA):
        raise SourceRoutingError(
            f"request contains unsupported media: {sorted(set(media) - VALID_MEDIA)}"
        )
    coverage_mode = request.get("coverage_mode", "fixed")
    if coverage_mode not in {"fixed", "maximize_evidence_breadth"}:
        raise SourceRoutingError(
            "coverage_mode must be fixed or maximize_evidence_breadth"
        )
    for key, selected in (
        ("minimum_elements", elements),
        ("minimum_media", media),
    ):
        minimum = request.get(key)
        if minimum is None:
            continue
        if (
            isinstance(minimum, bool)
            or not isinstance(minimum, int)
            or minimum < 1
            or minimum > len(selected)
        ):
            raise SourceRoutingError(
                f"{key} must be an integer from 1 to the selected dimension count"
            )
    region = request.get("region")
    if not isinstance(region, (str, dict)) or not region:
        raise SourceRoutingError(
            "request region must be a non-empty name, 'global', or bbox object"
        )
    if isinstance(region, dict):
        if (
            set(region) != {"bbox"}
            or not isinstance(region["bbox"], list)
            or len(region["bbox"]) != 4
        ):
            raise SourceRoutingError(
                "request region object must contain exactly bbox=[west,south,east,north]"
            )
        try:
            spatial_scope.resolve_region(region)
        except spatial_scope.SpatialScopeError as exc:
            raise SourceRoutingError(str(exc)) from exc
    try:
        resolved_region = spatial_scope.resolve_region(region)
    except spatial_scope.SpatialScopeError as exc:
        raise SourceRoutingError(str(exc)) from exc
    spatial_domains = request.get("spatial_domains")
    if spatial_domains is None:
        derived: set[str] = set()
        if set(media).intersection({"rock", "soil", "mineral", "concentrate"}):
            derived.add("land")
        if "sediment" in media:
            derived.update({"land", "inland_water", "marine"})
        if "water" in media:
            derived.update({"inland_water", "marine"})
        spatial_domains = [
            item for item in spatial_scope.VALID_SPATIAL_DOMAINS if item in derived
        ]
    if (
        not isinstance(spatial_domains, list)
        or not spatial_domains
        or not all(isinstance(item, str) for item in spatial_domains)
        or len(spatial_domains) != len(set(spatial_domains))
        or not set(spatial_domains).issubset(VALID_SPATIAL_DOMAINS)
    ):
        raise SourceRoutingError(
            "spatial_domains must be a non-empty unique subset of land, inland_water and marine"
        )
    adjacent_default = (
        int(spatial_scope.DEFAULT_ADJACENT_MARINE_DISTANCE_KM)
        if resolved_region.get("country_code") and "marine" in spatial_domains
        else 0
    )
    adjacent_marine_distance_km = request.get(
        "adjacent_marine_distance_km", adjacent_default
    )
    if (
        isinstance(adjacent_marine_distance_km, bool)
        or not isinstance(adjacent_marine_distance_km, (int, float))
        or not 0 <= float(adjacent_marine_distance_km) <= 1000
    ):
        raise SourceRoutingError(
            "adjacent_marine_distance_km must be a number from 0 to 1000"
        )
    if float(adjacent_marine_distance_km) > 0 and (
        "marine" not in spatial_domains or not resolved_region.get("country_code")
    ):
        raise SourceRoutingError(
            "a positive adjacent_marine_distance_km requires a named-country request with marine in spatial_domains"
        )
    sources = request.get("sources", "auto")
    if sources != "auto":
        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(item, str) for item in sources)
            or len(sources) != len(set(sources))
        ):
            raise SourceRoutingError(
                "request sources must be 'auto' or a non-empty string array"
            )
        unknown_sources = sorted(set(sources) - set(catalog["sources"]))
        if unknown_sources:
            raise SourceRoutingError(
                f"request names unknown sources: {', '.join(unknown_sources)}"
            )
    measurement_basis = request.get("measurement_basis")
    if measurement_basis is not None and (
        not isinstance(measurement_basis, list)
        or not measurement_basis
        or not all(isinstance(item, str) and item for item in measurement_basis)
        or len(measurement_basis) != len(set(measurement_basis))
    ):
        raise SourceRoutingError(
            "measurement_basis must be null or a unique string array"
        )
    geology_units = request.get("geology_units")
    if geology_units is not None and (
        not isinstance(geology_units, list)
        or not geology_units
        or len(geology_units) > 50
        or not all(
            isinstance(item, str) and 0 < len(item.strip()) <= 160
            for item in geology_units
        )
        or len(geology_units) != len(set(geology_units))
    ):
        raise SourceRoutingError(
            "geology_units must be null or a unique array of 1-50 non-empty labels"
        )
    geology_match = request.get("geology_match", "reported_or_matched")
    if geology_match not in {"reported_or_matched", "reported", "matched"}:
        raise SourceRoutingError(
            "geology_match must be reported_or_matched, reported, or matched"
        )
    time_range = request.get("time_range")
    if time_range is not None and (
        not isinstance(time_range, list)
        or len(time_range) != 2
        or not all(isinstance(item, str) for item in time_range)
    ):
        raise SourceRoutingError("time_range must be null or a two-string array")
    if time_range is not None and _year(time_range[0]) > _year(time_range[1]):
        raise SourceRoutingError("time_range start must not be after end")
    output_formats = request.get(
        "output_formats", ["csv", "json", "geojson", "html_map"]
    )
    if (
        not isinstance(output_formats, list)
        or not all(isinstance(item, str) for item in output_formats)
        or len(output_formats) != len(set(output_formats))
        or not set(output_formats).issubset(VALID_OUTPUT_FORMATS)
    ):
        raise SourceRoutingError(
            "output_formats must be a unique array of supported formats"
        )
    if request.get("target_crs", "EPSG:4326") != "EPSG:4326":
        raise SourceRoutingError("target_crs supports only EPSG:4326")
    if request.get("license_policy", "open_only") != "open_only":
        raise SourceRoutingError(
            "legacy license_policy supports only open_only; use research_use_policy in V3"
        )
    research_use_policy = request.get("research_use_policy", "permitted_research")
    if research_use_policy not in {
        "permitted_research",
        "open_research_only",
        "include_permission_required",
    }:
        raise SourceRoutingError("invalid research_use_policy")
    minimum_evidence_tier = request.get("minimum_evidence_tier", "D")
    if minimum_evidence_tier not in score_source_evidence.TIER_RANK:
        raise SourceRoutingError("minimum_evidence_tier must be A, B, C, D or U")
    minimum_use_mode = request.get("minimum_use_mode", "normalized_analysis")
    if minimum_use_mode not in score_source_evidence.USE_MODE_RANK:
        raise SourceRoutingError(
            "minimum_use_mode must be discovery, raw_observation, normalized_analysis or benchmark_ready"
        )
    default_max_records = (
        200000 if coverage_mode == "maximize_evidence_breadth" else 50000
    )
    max_records = request.get("max_records", default_max_records)
    if (
        isinstance(max_records, bool)
        or not isinstance(max_records, int)
        or not 1 <= max_records <= 200000
    ):
        raise SourceRoutingError("max_records must be an integer from 1 to 200000")
    if not isinstance(request.get("offline", False), bool):
        raise SourceRoutingError("offline must be a boolean")
    normalized = dict(request)
    normalized.setdefault("coverage_mode", "fixed")
    normalized.setdefault("minimum_elements", None)
    normalized.setdefault("minimum_media", None)
    normalized["spatial_domains"] = list(spatial_domains)
    normalized["adjacent_marine_distance_km"] = adjacent_marine_distance_km
    normalized.setdefault("measurement_basis", None)
    normalized.setdefault("geology_units", None)
    normalized.setdefault("geology_match", "reported_or_matched")
    normalized.setdefault("time_range", None)
    normalized.setdefault("sources", "auto")
    normalized.setdefault("output_formats", ["csv", "json", "geojson", "html_map"])
    normalized.setdefault("target_crs", "EPSG:4326")
    normalized.setdefault("license_policy", "open_only")
    normalized.setdefault("research_use_policy", "permitted_research")
    normalized.setdefault("minimum_evidence_tier", "D")
    normalized.setdefault("minimum_use_mode", "normalized_analysis")
    normalized.setdefault("max_records", default_max_records)
    normalized.setdefault("offline", False)
    return normalized


def _route_entry(
    source_id: str,
    entry: Mapping[str, Any],
    evidence: Mapping[str, Any],
    matching_media: list[str],
    reason: str,
    request_compatibility: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "title": entry["title"],
        "status": entry["status"],
        "access_status": evidence["access_status"],
        "research_use_status": evidence["research_use_status"],
        "evidence_tier": evidence["evidence_tier"],
        "source_evidence_score": evidence["source_evidence_score"],
        "use_mode": evidence["use_mode"],
        "attribution_note": evidence["attribution_note"],
        "matching_media": matching_media,
        "coverage_extent": entry["coverage"]["extent_class"],
        "request_compatibility": dict(request_compatibility),
        "reason": reason,
    }


def _normalized_scope(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _walk_values(value: Any, key: str) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, Mapping):
        for current_key, current_value in value.items():
            if current_key == key:
                found.append(current_value)
            found.extend(_walk_values(current_value, key))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_values(item, key))
    return found


def _year(value: str) -> int:
    match = re.match(r"^(\d{4})(?:-|$)", value.strip())
    if not match:
        raise SourceRoutingError("time_range entries must start with a four-digit year")
    return int(match.group(1))


def _source_spatial_profile(source_id: str) -> dict[str, Any]:
    path = FULL_PROFILE_ROOT / source_id / "spatial_coverage.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _source_bbox(source_id: str) -> list[float] | None:
    bbox = _source_spatial_profile(source_id).get("bbox")
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(
            isinstance(item, (int, float)) and not isinstance(item, bool)
            for item in bbox
        )
    ):
        return None
    return [float(item) for item in bbox]


def _profile_country_applicability(
    source_id: str,
    resolved_request: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Return a fail-closed country decision from audited full-profile semantics.

    Bounding boxes answer only whether two rectangles overlap.  They cannot
    prove that a partial global archive actually contains observations for a
    named country, and an ocean cruise cannot satisfy a land Admin-0 request.
    This gate is used only when the profile explicitly declares auditable
    applicability semantics; sources without them retain the older conservative
    bbox/declaration path.
    """

    country_code = resolved_request.get("country_code")
    if not isinstance(country_code, str) or not country_code:
        return None
    profile = _source_spatial_profile(source_id)
    applicability = profile.get("region_applicability")
    if not isinstance(applicability, Mapping):
        return None
    domain = str(applicability.get("spatial_domain") or "unknown")
    index_status = str(applicability.get("country_index_status") or "unknown")
    raw_codes = applicability.get("country_iso_a3_codes")
    country_codes = sorted(
        str(item)
        for item in (raw_codes if isinstance(raw_codes, list) else [])
        if isinstance(item, str)
    )
    evidence = {
        "profile_version": profile.get("profile_version"),
        "dataset_version": profile.get("dataset_version"),
        "spatial_domain": domain,
        "country_index_status": index_status,
        "country_iso_a3_codes": country_codes,
        "evidence_basis": applicability.get("evidence_basis"),
    }
    if domain == "marine":
        if "marine" in request.get("spatial_domains", []):
            source_bbox = _source_bbox(source_id)
            analysis_bbox = spatial_scope.request_analysis_bbox(
                resolved_request,
                request.get("spatial_domains"),
                float(request.get("adjacent_marine_distance_km") or 0),
            )
            if source_bbox is not None and not spatial_scope.bbox_intersects(
                analysis_bbox, source_bbox
            ):
                return {
                    "status": "incompatible",
                    "reason_code": "adjacent_marine_bbox_disjoint",
                    "note": (
                        f"audited marine source bbox {source_bbox} does not intersect "
                        f"the bounded adjacent-marine analysis bbox {analysis_bbox}"
                    ),
                    "profile_evidence": evidence,
                }
            return {
                "status": "compatible",
                "reason_code": "adjacent_marine_domain_requested",
                "note": (
                    f"request explicitly includes the marine domain within "
                    f"{request.get('adjacent_marine_distance_km')} km of the frozen "
                    "Admin-0 boundary; record-level distance filtering still runs and "
                    "the buffer is not a territorial or sovereignty claim"
                ),
                "profile_evidence": evidence,
            }
        return {
            "status": "incompatible",
            "reason_code": "marine_domain_not_requested",
            "note": (
                f"resolved request {resolved_request['key']} does not include the "
                "marine spatial domain, while the audited full profile is marine-only"
            ),
            "profile_evidence": evidence,
        }
    if index_status == "complete_for_snapshot":
        if country_code not in country_codes:
            return {
                "status": "incompatible",
                "reason_code": "profile_country_absent",
                "note": (
                    f"audited full-snapshot country index contains {len(country_codes)} "
                    f"countries but not {country_code}; bbox overlap cannot promote the source"
                ),
                "profile_evidence": evidence,
            }
        return {
            "status": "compatible",
            "reason_code": "profile_country_present",
            "note": (
                f"audited full-snapshot country index explicitly contains {country_code}; "
                "record-level country/polygon filtering still runs after acquisition"
            ),
            "profile_evidence": evidence,
        }
    return None


def _bbox_contains(
    outer: Sequence[float], inner: Sequence[float], tolerance_degrees: float = 0.5
) -> bool:
    """Return conservative containment for ordinary scopes.

    A half-degree tolerance accommodates rounded task boxes such as China's
    documented 73--135 E, 18--54 N shorthand versus the frozen Natural Earth
    coastline bounds.  It is used only for source routing, never record joins.
    """

    if outer[0] > outer[2] or inner[0] > inner[2]:
        return False
    return (
        outer[0] - tolerance_degrees <= inner[0]
        and outer[1] - tolerance_degrees <= inner[1]
        and outer[2] + tolerance_degrees >= inner[2]
        and outer[3] + tolerance_degrees >= inner[3]
    )


def _declared_region_scopes(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Resolve catalog region labels without promoting their coordinates to WGS84.

    Some publishers state a country or named region but omit the source CRS.
    That evidence is sufficient to decide whether the dataset is worth
    acquiring for the region; it is *not* sufficient to canonicalize or map
    individual coordinates.  Returned scopes are therefore routing evidence
    only and always lead to ``compatible_reported_only``.
    """

    declared = [
        str(item)
        for item in (entry.get("coverage") or {}).get("regions", [])
        if str(item or "").strip()
    ]
    if not declared:
        return []
    normalized_labels = [_normalized_scope(item) for item in declared]
    candidates: dict[str, dict[str, Any]] = {}

    def label_mentions(alias: str) -> bool:
        normalized = _normalized_scope(alias)
        if len(normalized) < 3:
            return False
        compact = normalized.replace("_", "")
        return any(
            normalized in label.split("_")
            or (len(compact) >= 5 and compact in label.replace("_", ""))
            for label in normalized_labels
        )

    for key, definition in spatial_scope.NAMED_BBOXES.items():
        aliases = [key, *definition.get("aliases", ())]
        if any(label_mentions(str(alias)) for alias in aliases):
            try:
                candidates[key] = spatial_scope.resolve_region(key)
            except spatial_scope.SpatialScopeError:
                pass

    registry = spatial_scope.load_country_registry()
    for code, country in registry["by_code"].items():
        aliases = (code, country.get("name"), country.get("name_zh"))
        if any(label_mentions(str(alias)) for alias in aliases if alias):
            try:
                candidates[code] = spatial_scope.resolve_region(code)
            except spatial_scope.SpatialScopeError:
                pass
    return list(candidates.values())


def _declared_region_matches(
    entry: Mapping[str, Any], resolved_request: Mapping[str, Any]
) -> dict[str, Any] | None:
    for declared_scope in _declared_region_scopes(entry):
        if resolved_request.get("key") == declared_scope.get("key") or _bbox_contains(
            resolved_request["bbox"], declared_scope["bbox"]
        ):
            return declared_scope
    return None


def basis_matches(requested: str, declared: str) -> bool:
    wanted = _normalized_scope(requested)
    available = _normalized_scope(declared)
    if not wanted or not available:
        return False
    if wanted == available:
        return True
    generic = {
        "total": ("total", "near_total", "quasi_total"),
        "dissolved": ("dissolved", "filtered"),
        "extractable": (
            "extract",
            "extraction",
            "extractable",
            "leachable",
            "digestion",
        ),
    }
    padded_available = f"_{available}_"
    return any(
        f"_{token}_" in padded_available for token in generic.get(wanted, (wanted,))
    )


def request_compatibility(
    source_id: str,
    entry: Mapping[str, Any],
    registry_entry: Mapping[str, Any] | None,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare every retrieval-changing request field with frozen source evidence."""

    registered = registry_entry if isinstance(registry_entry, Mapping) else {}
    registered_media = sorted(str(item) for item in entry.get("media", []))
    matched_media = sorted(set(request["media"]).intersection(registered_media))
    media_status = "compatible" if matched_media else "incompatible"
    target_analytes = sorted(
        str(item) for item in registered.get("target_analytes", {})
    )
    matched_analytes = sorted(set(request["elements"]).intersection(target_analytes))
    analyte_status = (
        "compatible"
        if matched_analytes
        else "incompatible"
        if target_analytes
        else "unverified"
    )

    region = request["region"]
    source_bbox = _source_bbox(source_id)
    region_reason_code = "global_request"
    region_profile_evidence: dict[str, Any] | None = None
    if region == "global":
        region_status = "not_applicable"
        region_note = "global request; source coverage remains partial as declared"
    else:
        try:
            resolved_region = spatial_scope.resolve_region(region)
        except spatial_scope.SpatialScopeError as exc:
            resolved_region = None
            region_status = "unverified"
            region_note = str(exc)
    if region != "global" and resolved_region is not None:
        profile_decision = _profile_country_applicability(
            source_id, resolved_region, request
        )
        if profile_decision is not None:
            region_status = str(profile_decision["status"])
            region_reason_code = str(profile_decision["reason_code"])
            region_note = str(profile_decision["note"])
            profile_evidence = profile_decision.get("profile_evidence")
            region_profile_evidence = (
                dict(profile_evidence)
                if isinstance(profile_evidence, Mapping)
                else None
            )
        elif source_bbox is None:
            declared_scope = _declared_region_matches(entry, resolved_region)
            if declared_scope is None:
                region_status = "unverified"
                region_reason_code = "canonical_scope_unverified"
                region_note = (
                    "canonical source bbox unavailable and the catalog's declared region "
                    "does not resolve to the request scope"
                )
            else:
                region_status = "compatible_reported_only"
                region_reason_code = "catalog_declared_scope_match"
                region_note = (
                    f"catalog-declared scope {declared_scope['key']} matches the request; "
                    "acquisition is relevant, but source coordinates remain reported-only "
                    "until a CRS is evidenced"
                )
        elif spatial_scope.bbox_intersects(
            spatial_scope.request_analysis_bbox(
                resolved_region,
                request.get("spatial_domains"),
                float(request.get("adjacent_marine_distance_km") or 0),
            ),
            source_bbox,
        ):
            region_status = "compatible"
            region_reason_code = "canonical_bbox_intersection"
            region_note = f"resolved request scope {resolved_region['key']} intersects frozen canonical source bbox {source_bbox}"
        else:
            region_status = "incompatible"
            region_reason_code = "canonical_bbox_disjoint"
            region_note = (
                f"resolved request scope {resolved_region['key']} does not intersect frozen "
                f"canonical source bbox {source_bbox}"
            )

    requested_geology = request.get("geology_units")
    geology_status = "enforced_downstream" if requested_geology else "not_applicable"
    geology_note = (
        "exact normalized geological-unit filtering runs after source-reported fields and optional "
        "frozen spatial geology matching"
        if requested_geology
        else "no geological-unit filter requested"
    )

    requested_basis = request.get("measurement_basis")
    declared_basis = sorted(
        {
            str(item)
            for value in _walk_values(registered, "measurement_basis")
            for item in (value if isinstance(value, list) else [value])
            if str(item or "").strip()
        }
    )
    if requested_basis is None:
        basis_status = "not_applicable"
        matched_basis: list[str] = []
    else:
        matched_basis = sorted(
            declared
            for declared in declared_basis
            if any(basis_matches(requested, declared) for requested in requested_basis)
        )
        basis_status = (
            "compatible"
            if matched_basis
            else "incompatible"
            if declared_basis
            else "unverified"
        )

    requested_time = request.get("time_range")
    declared_bounds = [
        value
        for value in _walk_values(registered, "date_bounds")
        if isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, str) for item in value)
    ]
    if requested_time is None:
        time_status = "not_applicable"
        matched_bounds: list[list[str]] = []
    else:
        requested_start, requested_end = (_year(item) for item in requested_time)
        matched_bounds = [
            list(bounds)
            for bounds in declared_bounds
            if requested_start <= _year(bounds[1]) and _year(bounds[0]) <= requested_end
        ]
        time_status = (
            "compatible"
            if matched_bounds
            else "incompatible"
            if declared_bounds
            else "unverified"
        )

    return {
        "media": {
            "status": media_status,
            "requested": list(request["media"]),
            "registered": registered_media,
            "matched": matched_media,
        },
        "analytes": {
            "status": analyte_status,
            "requested": list(request["elements"]),
            "registered": target_analytes,
            "matched": matched_analytes,
        },
        "region": {
            "status": region_status,
            "reason_code": region_reason_code,
            "declared_regions": list(entry["coverage"].get("regions", [])),
            "canonical_bbox": source_bbox,
            "profile_evidence": region_profile_evidence,
            "note": region_note,
        },
        "geology": {
            "status": geology_status,
            "requested": requested_geology,
            "match_policy": request.get("geology_match", "reported_or_matched"),
            "note": geology_note,
        },
        "measurement_basis": {
            "status": basis_status,
            "requested": requested_basis,
            "declared": declared_basis,
            "matched": matched_basis,
        },
        "time_range": {
            "status": time_status,
            "requested": requested_time,
            "declared_bounds": declared_bounds,
            "matched_bounds": matched_bounds,
        },
        "max_records": {
            "status": "enforced_downstream",
            "requested": request["max_records"],
        },
    }


def _research_policy_allows(policy: str, status: str) -> bool:
    if policy == "include_permission_required":
        return status != "unknown"
    if policy == "open_research_only":
        return status == "open_research"
    return status in {
        "open_research",
        "attribution_required",
        "noncommercial_research_only",
    }


def route_sources(
    request: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return usable routes, lower-use candidates and conservative coverage states."""

    resolved_catalog = dict(catalog) if catalog is not None else load_catalog()
    resolved_registry = (
        dict(registry)
        if registry is not None
        else source_adapters.load_source_registry()
    )
    normalized = validate_request(request, resolved_catalog)
    evidence_report = score_source_evidence.score_catalog(
        resolved_catalog,
        resolved_registry,
        score_source_evidence.load_candidate_evidence(),
    )
    requested_media = set(normalized["media"])
    explicit_sources = normalized["sources"]
    allowed_ids = (
        set(resolved_catalog["sources"])
        if explicit_sources == "auto"
        else set(explicit_sources)
    )

    selected: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for source_id in sorted(allowed_ids):
        entry = resolved_catalog["sources"][source_id]
        matching_media = sorted(requested_media.intersection(entry["media"]))
        if not matching_media and explicit_sources == "auto":
            continue
        evidence = evidence_report["sources"][source_id]
        compatibility = request_compatibility(
            source_id,
            entry,
            resolved_registry.get("sources", {}).get(source_id),
            normalized,
        )
        compatibility_blockers = [
            f"{dimension}={details['status']}"
            for dimension, details in compatibility.items()
            if isinstance(details, Mapping)
            and details.get("status") in {"incompatible", "unverified"}
            and dimension != "max_records"
        ]
        evidence_ok = (
            score_source_evidence.TIER_RANK[evidence["evidence_tier"]]
            >= score_source_evidence.TIER_RANK[normalized["minimum_evidence_tier"]]
        )
        use_mode_ok = (
            score_source_evidence.USE_MODE_RANK[evidence["use_mode"]]
            >= score_source_evidence.USE_MODE_RANK[normalized["minimum_use_mode"]]
        )
        research_ok = _research_policy_allows(
            normalized["research_use_policy"], evidence["research_use_status"]
        )
        offline_ok = not normalized["offline"]
        compatibility_ok = not compatibility_blockers
        if (
            evidence_ok
            and use_mode_ok
            and research_ok
            and offline_ok
            and compatibility_ok
        ):
            selected.append(
                _route_entry(
                    source_id,
                    entry,
                    evidence,
                    matching_media,
                    (
                        f"meets minimum tier {normalized['minimum_evidence_tier']}, "
                        f"use mode {normalized['minimum_use_mode']} and research-use policy"
                    ),
                    compatibility,
                )
            )
        else:
            blockers: list[str] = []
            if not evidence_ok:
                blockers.append(
                    f"evidence_tier={evidence['evidence_tier']} below {normalized['minimum_evidence_tier']}"
                )
            if not use_mode_ok:
                blockers.append(
                    f"use_mode={evidence['use_mode']} below {normalized['minimum_use_mode']}"
                )
            if not research_ok:
                blockers.append(
                    f"research_use_status={evidence['research_use_status']}"
                )
            if not offline_ok:
                blockers.append("offline_cache_not_verified")
            blockers.extend(compatibility_blockers)
            blockers.extend(f"conflict={item}" for item in evidence["conflicts"])
            review.append(
                _route_entry(
                    source_id,
                    entry,
                    evidence,
                    matching_media,
                    "; ".join(blockers) or "request compatibility requires review",
                    compatibility,
                )
            )

    coverage: dict[str, Any] = {}
    saturated = bool(resolved_catalog["discovery_state"]["saturated"])
    for medium in normalized["media"]:
        selected_ids = sorted(
            item["source_id"] for item in selected if medium in item["matching_media"]
        )
        candidate_ids = sorted(
            item["source_id"] for item in review if medium in item["matching_media"]
        )
        if selected_ids:
            coverage_status = "partial"
            note = "At least one source meets the requested evidence and use mode, but geographic, temporal and method completeness remain bounded by its declared scope."
        elif candidate_ids:
            coverage_status = "unknown"
            note = "Relevant candidates exist, but none currently meets the requested evidence, research-use and use-mode conditions."
        elif saturated:
            coverage_status = "uncovered"
            note = "No relevant source remained after a discovery-saturated catalog review."
        else:
            coverage_status = "unknown"
            note = "No current candidate is recorded and source discovery is not saturated."
        coverage[medium] = {
            "status": coverage_status,
            "selected_sources": selected_ids,
            "candidate_sources": candidate_ids,
            "note": note,
        }

    def dimension_audit(
        requested: Sequence[str],
        dimension: str,
    ) -> dict[str, Any]:
        items: dict[str, Any] = {}
        for value in requested:
            if dimension == "elements":
                selected_ids = sorted(
                    item["source_id"]
                    for item in selected
                    if value
                    in (
                        (
                            (item["request_compatibility"].get("analytes") or {}).get(
                                "matched"
                            )
                        )
                        or []
                    )
                )
                candidate_ids = sorted(
                    item["source_id"]
                    for item in review
                    if value
                    in (
                        (
                            (item["request_compatibility"].get("analytes") or {}).get(
                                "matched"
                            )
                        )
                        or []
                    )
                )
            else:
                selected_ids = sorted(
                    item["source_id"]
                    for item in selected
                    if value in item["matching_media"]
                )
                candidate_ids = sorted(
                    item["source_id"]
                    for item in review
                    if value in item["matching_media"]
                )
            status = (
                "selected"
                if selected_ids
                else "review_only"
                if candidate_ids
                else "uncovered"
            )
            items[value] = {
                "status": status,
                "selected_sources": selected_ids,
                "candidate_sources": candidate_ids,
            }
        return {
            "minimum_required": normalized[
                "minimum_elements" if dimension == "elements" else "minimum_media"
            ],
            "audited_candidates": list(requested),
            "items": items,
        }

    breadth_audit = {
        "coverage_mode": normalized["coverage_mode"],
        "elements": dimension_audit(normalized["elements"], "elements"),
        "media": dimension_audit(normalized["media"], "media"),
        "claim_boundary": (
            "selected means at least one currently routable source declares the candidate; "
            "it does not prove that acquisition will return enough in-scope observations. "
            "review_only and uncovered candidates remain explicit D1 discovery work."
        ),
    }

    if selected:
        status = (
            "partial"
            if any(item["status"] != "covered" for item in coverage.values())
            else "ready"
        )
    elif review:
        status = "needs_human_review"
    else:
        status = "unsupported_scope"
    limitations = [
        "Catalog routing applies frozen analyte, region, measurement-basis and temporal evidence; record-level availability and comparability still require acquisition plus D2 review.",
        "Requested geological units are enforced after source-reported geology and optional frozen spatial matching; unmatched records remain explicit coverage gaps.",
        "A partial route must not be presented as complete global coverage.",
        "max_records is an acquisition/output ceiling enforced by the downstream runner, not evidence that the selected records are representative.",
    ]
    if not saturated:
        limitations.append(
            "Source discovery is still in progress; absence from this route is not proof that no source exists."
        )
    if normalized["offline"]:
        limitations.append(
            "Offline routing cannot inspect an external cache, so it does not select any source until the caller separately verifies a versioned cache and SHA-256."
        )
    return {
        "route_version": ROUTE_VERSION,
        "status": status,
        "request": normalized,
        "selected_sources": selected,
        "review_sources": review,
        "coverage": coverage,
        "breadth_audit": breadth_audit,
        "limitations": limitations,
        "claim_boundary": resolved_catalog["claim_boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request",
        type=Path,
        required=True,
        help="Request JSON conforming to request.schema.json",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=DEFAULT_CATALOG,
        help="Discovered source catalog JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional route-result JSON path; stdout emits only a compact receipt when set",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        request = _read_json(args.request, "request")
        result = route_sources(request, catalog)
        rendered = (
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
            print(
                json.dumps(
                    {
                        "status": result["status"],
                        "output": str(args.output),
                        "selected_source_count": len(result["selected_sources"]),
                        "review_source_count": len(result["review_sources"]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        else:
            print(rendered, end="")
        return 0
    except (OSError, SourceRoutingError) as exc:
        print(
            json.dumps(
                {"status": "invalid_input", "error": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
