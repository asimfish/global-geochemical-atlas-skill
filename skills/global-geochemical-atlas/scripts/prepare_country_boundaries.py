#!/usr/bin/env python3
"""Create the compact, pinned Natural Earth Admin-0 asset used by D3.

This is a maintainer utility, not a runtime downloader.  Pass the exact pinned
GeoJSON file documented in references/licenses-and-citations.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ASSET_VERSION = "ai4s-natural-earth-admin0-v1"
EXPECTED_FEATURE_COUNT = 177
EXPECTED_POINT_COUNT = 10654
REQUIRED_COUNTRY_CODES = {"AUS", "CHN", "USA"}
SOURCE_COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{SOURCE_COMMIT}/geojson/ne_110m_admin_0_countries.geojson"
)


def rounded(value: Any) -> Any:
    if isinstance(value, list):
        return [rounded(item) for item in value]
    if isinstance(value, float):
        return round(value, 4)
    return value


def point_count(value: Any) -> int:
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(item, (int, float)) for item in value)
    ):
        return 1
    if isinstance(value, list):
        return sum(point_count(item) for item in value)
    return 0


def build(source: Path, output: Path) -> None:
    source_bytes = source.read_bytes()
    raw = json.loads(source_bytes)
    if raw.get("type") != "FeatureCollection" or not isinstance(raw.get("features"), list):
        raise ValueError("source must be a GeoJSON FeatureCollection")
    if len(raw["features"]) != EXPECTED_FEATURE_COUNT:
        raise ValueError(
            f"pinned Natural Earth release must contain {EXPECTED_FEATURE_COUNT} features"
        )
    countries = []
    seen_codes: set[str] = set()
    for feature in raw["features"]:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        iso_a3 = properties.get("ADM0_A3")
        if not isinstance(iso_a3, str) or len(iso_a3) != 3 or iso_a3 in seen_codes:
            raise ValueError("Natural Earth feature is missing ADM0_A3")
        seen_codes.add(iso_a3)
        countries.append(
            {
                "iso_a3": iso_a3,
                "name": properties.get("ADMIN") or properties.get("NAME") or iso_a3,
                "name_zh": properties.get("NAME_ZH") or None,
                "geometry": {
                    "type": geometry["type"],
                    "coordinates": rounded(geometry.get("coordinates")),
                },
            }
        )
    countries.sort(key=lambda item: (item["iso_a3"], item["name"]))
    total_points = sum(point_count(item["geometry"]["coordinates"]) for item in countries)
    if not REQUIRED_COUNTRY_CODES.issubset(seen_codes) or total_points != EXPECTED_POINT_COUNT:
        raise ValueError(
            "pinned Natural Earth release failed country-code or geometry-point statistics"
        )
    asset = {
        "asset_version": ASSET_VERSION,
        "title": "Natural Earth 1:110m Admin 0 Countries",
        "natural_earth_version": "5.1.1",
        "scale": "1:110m",
        "coordinate_reference_system": "WGS84 longitude/latitude",
        "source_page": (
            "https://www.naturalearthdata.com/downloads/110m-cultural-vectors/"
            "110m-admin-0-countries/"
        ),
        "source_geojson_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "source_filename": source.name,
        "source_bytes": len(source_bytes),
        "source_feature_count": len(raw["features"]),
        "license": "public domain",
        "boundary_semantics": "Natural Earth de facto Admin-0 cartographic boundaries",
        "country_count": len(countries),
        "point_count": total_points,
        "countries": countries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(asset, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "countries": len(countries),
                "points": total_points,
                "source": {
                    "filename": source.name,
                    "bytes": len(source_bytes),
                    "feature_count": len(raw["features"]),
                    "release_commit": SOURCE_COMMIT,
                },
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
