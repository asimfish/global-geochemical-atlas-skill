#!/usr/bin/env python3
"""Route a geochemical request to approved sources without overclaiming coverage."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"

CATALOG_VERSION = "geochemical-source-catalog-v1"
ROUTE_VERSION = "geochemical-source-route-v1"
VALID_MEDIA = {"rock", "soil", "sediment", "water", "mineral", "concentrate"}
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
        if entry.get("production_eligible"):
            if status not in {"approved", "conditional"}:
                raise SourceRoutingError(
                    f"catalog source {source_id} cannot be production eligible with status {status}"
                )
            if entry.get("license", {}).get("status") != "open":
                raise SourceRoutingError(f"catalog source {source_id} lacks an open production license")
            if entry.get("adapter", {}).get("status") != "implemented":
                raise SourceRoutingError(f"catalog source {source_id} lacks an implemented adapter")
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
    if not isinstance(elements, list) or not elements or not all(isinstance(item, str) and item.strip() for item in elements):
        raise SourceRoutingError("request elements must be a non-empty string array")
    media = request.get("media")
    if not isinstance(media, list) or not media or len(media) != len(set(media)):
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
        if not isinstance(sources, list) or not sources or not all(isinstance(item, str) for item in sources):
            raise SourceRoutingError("request sources must be 'auto' or a non-empty string array")
        unknown_sources = sorted(set(sources) - set(catalog["sources"]))
        if unknown_sources:
            raise SourceRoutingError(f"request names unknown sources: {', '.join(unknown_sources)}")
    if request.get("license_policy", "open_only") != "open_only":
        raise SourceRoutingError("v1 source routing supports only license_policy=open_only")
    normalized = dict(request)
    normalized.setdefault("sources", "auto")
    normalized.setdefault("license_policy", "open_only")
    normalized.setdefault("offline", False)
    return normalized


def _route_entry(source_id: str, entry: Mapping[str, Any], matching_media: list[str], reason: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "title": entry["title"],
        "status": entry["status"],
        "matching_media": matching_media,
        "coverage_extent": entry["coverage"]["extent_class"],
        "reason": reason,
    }


def route_sources(request: Mapping[str, Any], catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return production routes, review candidates and conservative coverage states."""

    resolved_catalog = dict(catalog) if catalog is not None else load_catalog()
    normalized = validate_request(request, resolved_catalog)
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
        if entry["production_eligible"] and entry["license"]["status"] == "open":
            selected.append(
                _route_entry(
                    source_id,
                    entry,
                    matching_media,
                    "approved source with an implemented adapter and open license",
                )
            )
        else:
            blockers = [f"status={entry['status']}", f"adapter={entry['adapter']['status']}"]
            if entry["license"]["status"] != "open":
                blockers.append(f"license={entry['license']['status']}")
            review.append(_route_entry(source_id, entry, matching_media, "; ".join(blockers)))

    coverage: dict[str, Any] = {}
    saturated = bool(resolved_catalog["discovery_state"]["saturated"])
    for medium in normalized["media"]:
        approved_ids = sorted(item["source_id"] for item in selected if medium in item["matching_media"])
        candidate_ids = sorted(item["source_id"] for item in review if medium in item["matching_media"])
        if approved_ids:
            coverage_status = "partial"
            note = "At least one approved source is routable, but geographic, temporal and method completeness remain bounded by its declared scope."
        elif candidate_ids:
            coverage_status = "unknown"
            note = "Relevant candidates exist but none has passed the production quality gates."
        elif saturated:
            coverage_status = "uncovered"
            note = "No relevant source remained after a discovery-saturated catalog review."
        else:
            coverage_status = "unknown"
            note = "No current candidate is recorded and source discovery is not saturated."
        coverage[medium] = {
            "status": coverage_status,
            "approved_sources": approved_ids,
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
        "Catalog routing identifies possible sources; analyte availability and record-level comparability still require source queries and D2 review.",
        "A partial route must not be presented as complete global coverage.",
    ]
    if not saturated:
        limitations.append("Source discovery is still in progress; absence from this route is not proof that no source exists.")
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
