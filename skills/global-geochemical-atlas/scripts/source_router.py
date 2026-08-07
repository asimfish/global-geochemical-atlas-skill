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

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"
FULL_PROFILE_ROOT = SKILL_DIR / "assets" / "v4-full-profiles"

CATALOG_VERSION = "geochemical-source-catalog-v1"
ROUTE_VERSION = "geochemical-source-route-v3"
VALID_MEDIA = {"rock", "soil", "sediment", "water", "mineral", "concentrate"}
VALID_OUTPUT_FORMATS = {"csv", "json", "geojson", "html_map"}
VALID_SOURCE_STATUS = {"approved", "conditional", "metadata_only", "needs_human_review", "rejected"}
ALLOWED_REQUEST_KEYS = {
    "elements",
    "region",
    "media",
    "measurement_basis",
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
        raise SourceRoutingError("source catalog must contain a non-empty sources object")
    for source_id, entry in sources.items():
        if not isinstance(source_id, str) or not source_id or not isinstance(entry, dict):
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
            raise SourceRoutingError(f"catalog source {source_id} lacks keys: {', '.join(missing)}")
        status = entry.get("status")
        if status not in VALID_SOURCE_STATUS:
            raise SourceRoutingError(f"catalog source {source_id} has invalid status: {status}")
        media = entry.get("media")
        if not isinstance(media, list) or not media or not set(media).issubset(VALID_MEDIA):
            raise SourceRoutingError(f"catalog source {source_id} has invalid media")
        if not isinstance(entry.get("production_eligible"), bool):
            raise SourceRoutingError(f"catalog source {source_id} has invalid legacy production_eligible flag")
    discovery = catalog.get("discovery_state")
    if not isinstance(discovery, dict) or not isinstance(discovery.get("saturated"), bool):
        raise SourceRoutingError("source catalog has invalid discovery_state")
    return catalog


def validate_request(request: Mapping[str, Any], catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the shared v1 request fields needed for source routing."""

    unknown_keys = sorted(set(request) - ALLOWED_REQUEST_KEYS)
    if unknown_keys:
        raise SourceRoutingError(f"request has unsupported keys: {', '.join(unknown_keys)}")
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
        raise SourceRoutingError(f"request contains unsupported media: {sorted(set(media) - VALID_MEDIA)}")
    region = request.get("region")
    if not isinstance(region, (str, dict)) or not region:
        raise SourceRoutingError("request region must be a non-empty name, 'global', or bbox object")
    if isinstance(region, dict):
        if set(region) != {"bbox"} or not isinstance(region["bbox"], list) or len(region["bbox"]) != 4:
            raise SourceRoutingError("request region object must contain exactly bbox=[west,south,east,north]")
        west, south, east, north = region["bbox"]
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in region["bbox"]):
            raise SourceRoutingError("bbox coordinates must be numbers")
        if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
            raise SourceRoutingError("bbox coordinates are outside WGS84 bounds or latitude order is invalid")
    sources = request.get("sources", "auto")
    if sources != "auto":
        if (
            not isinstance(sources, list)
            or not sources
            or not all(isinstance(item, str) for item in sources)
            or len(sources) != len(set(sources))
        ):
            raise SourceRoutingError("request sources must be 'auto' or a non-empty string array")
        unknown_sources = sorted(set(sources) - set(catalog["sources"]))
        if unknown_sources:
            raise SourceRoutingError(f"request names unknown sources: {', '.join(unknown_sources)}")
    measurement_basis = request.get("measurement_basis")
    if measurement_basis is not None and (
        not isinstance(measurement_basis, list)
        or not measurement_basis
        or not all(isinstance(item, str) and item for item in measurement_basis)
        or len(measurement_basis) != len(set(measurement_basis))
    ):
        raise SourceRoutingError("measurement_basis must be null or a unique string array")
    time_range = request.get("time_range")
    if time_range is not None and (
        not isinstance(time_range, list)
        or len(time_range) != 2
        or not all(isinstance(item, str) for item in time_range)
    ):
        raise SourceRoutingError("time_range must be null or a two-string array")
    if time_range is not None and _year(time_range[0]) > _year(time_range[1]):
        raise SourceRoutingError("time_range start must not be after end")
    output_formats = request.get("output_formats", ["csv", "json", "geojson", "html_map"])
    if (
        not isinstance(output_formats, list)
        or not all(isinstance(item, str) for item in output_formats)
        or len(output_formats) != len(set(output_formats))
        or not set(output_formats).issubset(VALID_OUTPUT_FORMATS)
    ):
        raise SourceRoutingError("output_formats must be a unique array of supported formats")
    if request.get("target_crs", "EPSG:4326") != "EPSG:4326":
        raise SourceRoutingError("target_crs supports only EPSG:4326")
    if request.get("license_policy", "open_only") != "open_only":
        raise SourceRoutingError("legacy license_policy supports only open_only; use research_use_policy in V3")
    research_use_policy = request.get("research_use_policy", "permitted_research")
    if research_use_policy not in {"permitted_research", "open_research_only", "include_permission_required"}:
        raise SourceRoutingError("invalid research_use_policy")
    minimum_evidence_tier = request.get("minimum_evidence_tier", "D")
    if minimum_evidence_tier not in score_source_evidence.TIER_RANK:
        raise SourceRoutingError("minimum_evidence_tier must be A, B, C, D or U")
    minimum_use_mode = request.get("minimum_use_mode", "normalized_analysis")
    if minimum_use_mode not in score_source_evidence.USE_MODE_RANK:
        raise SourceRoutingError(
            "minimum_use_mode must be discovery, raw_observation, normalized_analysis or benchmark_ready"
        )
    max_records = request.get("max_records", 50000)
    if isinstance(max_records, bool) or not isinstance(max_records, int) or not 1 <= max_records <= 200000:
        raise SourceRoutingError("max_records must be an integer from 1 to 200000")
    if not isinstance(request.get("offline", False), bool):
        raise SourceRoutingError("offline must be a boolean")
    normalized = dict(request)
    normalized.setdefault("measurement_basis", None)
    normalized.setdefault("time_range", None)
    normalized.setdefault("sources", "auto")
    normalized.setdefault("output_formats", ["csv", "json", "geojson", "html_map"])
    normalized.setdefault("target_crs", "EPSG:4326")
    normalized.setdefault("license_policy", "open_only")
    normalized.setdefault("research_use_policy", "permitted_research")
    normalized.setdefault("minimum_evidence_tier", "D")
    normalized.setdefault("minimum_use_mode", "normalized_analysis")
    normalized.setdefault("max_records", 50000)
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


def _bbox_intersects(first: Sequence[float], second: Sequence[float]) -> bool:
    def longitude_ranges(bbox: Sequence[float]) -> list[tuple[float, float]]:
        west, _, east, _ = bbox
        return [(west, east)] if west <= east else [(west, 180.0), (-180.0, east)]

    if first[3] < second[1] or second[3] < first[1]:
        return False
    return any(
        left_a <= right_b and left_b <= right_a
        for left_a, right_a in longitude_ranges(first)
        for left_b, right_b in longitude_ranges(second)
    )


def _source_bbox(source_id: str) -> list[float] | None:
    path = FULL_PROFILE_ROOT / source_id / "spatial_coverage.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    bbox = value.get("bbox") if isinstance(value, dict) else None
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or not all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in bbox)
    ):
        return None
    return [float(item) for item in bbox]


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
        "extractable": ("extract", "extraction", "extractable", "leachable", "digestion"),
    }
    padded_available = f"_{available}_"
    return any(f"_{token}_" in padded_available for token in generic.get(wanted, (wanted,)))


def request_compatibility(
    source_id: str,
    entry: Mapping[str, Any],
    registry_entry: Mapping[str, Any] | None,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare every retrieval-changing request field with frozen source evidence."""

    registered = registry_entry if isinstance(registry_entry, Mapping) else {}
    target_analytes = sorted(str(item) for item in registered.get("target_analytes", {}))
    matched_analytes = sorted(set(request["elements"]).intersection(target_analytes))
    analyte_status = "compatible" if matched_analytes else "incompatible" if target_analytes else "unverified"

    region = request["region"]
    source_bbox = _source_bbox(source_id)
    if region == "global":
        region_status = "not_applicable"
        region_note = "global request; source coverage remains partial as declared"
    elif isinstance(region, dict):
        if source_bbox is None:
            region_status = "unverified"
            region_note = "canonical source bbox unavailable; WGS84 filtering cannot be verified"
        elif _bbox_intersects(region["bbox"], source_bbox):
            region_status = "compatible"
            region_note = f"requested bbox intersects frozen canonical source bbox {source_bbox}"
        else:
            region_status = "incompatible"
            region_note = f"requested bbox does not intersect frozen canonical source bbox {source_bbox}"
    else:
        requested_region = _normalized_scope(region)
        declared_regions = [_normalized_scope(item) for item in entry["coverage"].get("regions", [])]
        if any(
            requested_region == item
            or requested_region in item.split("_")
            or item in requested_region
            for item in declared_regions
        ):
            region_status = "compatible"
            region_note = "named region matches a declared catalog scope"
        else:
            region_status = "unverified"
            region_note = "named region has no frozen polygon/equivalence mapping for this source"

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
        basis_status = "compatible" if matched_basis else "incompatible" if declared_basis else "unverified"

    requested_time = request.get("time_range")
    declared_bounds = [
        value
        for value in _walk_values(registered, "date_bounds")
        if isinstance(value, list) and len(value) == 2 and all(isinstance(item, str) for item in value)
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
        time_status = "compatible" if matched_bounds else "incompatible" if declared_bounds else "unverified"

    return {
        "analytes": {
            "status": analyte_status,
            "requested": list(request["elements"]),
            "registered": target_analytes,
            "matched": matched_analytes,
        },
        "region": {
            "status": region_status,
            "declared_regions": list(entry["coverage"].get("regions", [])),
            "canonical_bbox": source_bbox,
            "note": region_note,
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
    return status in {"open_research", "attribution_required", "noncommercial_research_only"}


def route_sources(
    request: Mapping[str, Any],
    catalog: Mapping[str, Any] | None = None,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return usable routes, lower-use candidates and conservative coverage states."""

    resolved_catalog = dict(catalog) if catalog is not None else load_catalog()
    resolved_registry = dict(registry) if registry is not None else source_adapters.load_source_registry()
    normalized = validate_request(request, resolved_catalog)
    evidence_report = score_source_evidence.score_catalog(
        resolved_catalog,
        resolved_registry,
        score_source_evidence.load_candidate_evidence(),
    )
    requested_media = set(normalized["media"])
    explicit_sources = normalized["sources"]
    allowed_ids = set(resolved_catalog["sources"]) if explicit_sources == "auto" else set(explicit_sources)

    selected: list[dict[str, Any]] = []
    review: list[dict[str, Any]] = []
    for source_id in sorted(allowed_ids):
        entry = resolved_catalog["sources"][source_id]
        matching_media = sorted(requested_media.intersection(entry["media"]))
        if not matching_media:
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
        if evidence_ok and use_mode_ok and research_ok and offline_ok and compatibility_ok:
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
                blockers.append(f"use_mode={evidence['use_mode']} below {normalized['minimum_use_mode']}")
            if not research_ok:
                blockers.append(f"research_use_status={evidence['research_use_status']}")
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
        selected_ids = sorted(item["source_id"] for item in selected if medium in item["matching_media"])
        candidate_ids = sorted(item["source_id"] for item in review if medium in item["matching_media"])
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

    if selected:
        status = "partial" if any(item["status"] != "covered" for item in coverage.values()) else "ready"
    elif review:
        status = "needs_human_review"
    else:
        status = "unsupported_scope"
    limitations = [
        "Catalog routing applies frozen analyte, region, measurement-basis and temporal evidence; record-level availability and comparability still require acquisition plus D2 review.",
        "A partial route must not be presented as complete global coverage.",
        "max_records is an acquisition/output ceiling enforced by the downstream runner, not evidence that the selected records are representative.",
    ]
    if not saturated:
        limitations.append("Source discovery is still in progress; absence from this route is not proof that no source exists.")
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
        "limitations": limitations,
        "claim_boundary": resolved_catalog["claim_boundary"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True, help="Request JSON conforming to request.schema.json")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG, help="Discovered source catalog JSON")
    parser.add_argument("--output", type=Path, help="Optional route-result JSON path; stdout is always emitted")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        request = _read_json(args.request, "request")
        result = route_sources(request, catalog)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (OSError, SourceRoutingError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
