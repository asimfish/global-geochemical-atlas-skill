#!/usr/bin/env python3
"""Build pinned China Admin-1 linework for optional map orientation.

The generalized Natural Earth geometry is a visual aid only.  It is never
used for country filtering, coverage gates, spatial joins, or legal claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ASSET_VERSION = "ai4s-natural-earth-admin1-china-visual-v1"
EXPECTED_SOURCE_SHA256 = (
    "69a0e06e640b2d505858ae1cb63034e4677f3000b35a98e16312932b98c426b9"
)
SOURCE_COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{SOURCE_COMMIT}/geojson/ne_50m_admin_1_states_provinces.geojson"
)


def points(value: Any) -> Iterable[tuple[float, float]]:
    if (
        isinstance(value, list)
        and len(value) >= 2
        and isinstance(value[0], (int, float))
        and isinstance(value[1], (int, float))
    ):
        yield float(value[0]), float(value[1])
    elif isinstance(value, list):
        for item in value:
            yield from points(item)


def build(source: Path, output: Path) -> dict[str, Any]:
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            "source SHA-256 mismatch; use the pinned Natural Earth Admin-1 GeoJSON"
        )
    raw = json.loads(payload)
    if raw.get("type") != "FeatureCollection" or not isinstance(
        raw.get("features"), list
    ):
        raise ValueError("source must be a GeoJSON FeatureCollection")

    boundaries: list[dict[str, Any]] = []
    point_count = 0
    for feature in raw["features"]:
        properties = feature.get("properties") or {}
        country = str(
            properties.get("adm0_a3") or properties.get("ADM0_A3") or ""
        ).strip()
        if country != "CHN":
            continue
        geometry = feature.get("geometry") or {}
        geometry_points = list(points(geometry.get("coordinates")))
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("China Admin-1 feature has an unsupported geometry type")
        if not geometry_points or any(
            not (-180 <= longitude <= 180 and -90 <= latitude <= 90)
            for longitude, latitude in geometry_points
        ):
            raise ValueError("China Admin-1 feature has invalid coordinates")
        point_count += len(geometry_points)
        boundaries.append(
            {
                "name": str(properties.get("name") or "").strip(),
                "name_en": str(properties.get("name_en") or "").strip() or None,
                "name_zh": str(properties.get("name_zh") or "").strip() or None,
                "geometry": geometry,
            }
        )
    boundaries.sort(key=lambda item: item["name"])
    if len(boundaries) != 31:
        raise ValueError(f"expected 31 China Admin-1 features, found {len(boundaries)}")
    asset = {
        "asset_version": ASSET_VERSION,
        "title": "Natural Earth 1:50m China Admin-1 visual boundaries",
        "natural_earth_version": "5.1.1",
        "country_iso_a3": "CHN",
        "source_geojson_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "source_sha256": digest,
        "license": "public domain",
        "boundary_semantics": (
            "Generalized Natural Earth Admin-1 linework for visual orientation only; "
            "not an authoritative or legal administrative boundary, spatial join, "
            "country-membership result, or scientific coverage evidence."
        ),
        "boundary_count": len(boundaries),
        "point_count": point_count,
        "boundaries": boundaries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(asset, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return asset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    asset = build(args.source, args.output)
    print(
        json.dumps(
            {
                "status": "PASS",
                "output": str(args.output),
                "boundary_count": asset["boundary_count"],
                "point_count": asset["point_count"],
                "source_sha256": asset["source_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
