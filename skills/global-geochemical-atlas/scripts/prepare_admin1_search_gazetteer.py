#!/usr/bin/env python3
"""Build the compact Admin-1 gazetteer used only to name D1 search targets.

The runtime never treats these generalized cartographic boxes as sampling,
country-membership, or scientific coverage evidence.  They exist so a failed
regional grid becomes a useful query such as ``Xinjiang`` or ``Tibet`` rather
than an opaque longitude/latitude tuple.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


ASSET_VERSION = "ai4s-natural-earth-admin1-search-gazetteer-v1"
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

    regions: list[dict[str, Any]] = []
    for feature in raw["features"]:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = list(points(geometry.get("coordinates")))
        country = str(
            properties.get("adm0_a3") or properties.get("ADM0_A3") or ""
        ).strip()
        name = str(properties.get("name") or "").strip()
        if len(country) != 3 or not name or not coordinates:
            continue
        longitudes = [item[0] for item in coordinates]
        latitudes = [item[1] for item in coordinates]
        regions.append(
            {
                "adm0_a3": country,
                "name": name,
                "name_en": str(properties.get("name_en") or "").strip() or None,
                "name_zh": str(properties.get("name_zh") or "").strip() or None,
                "gn_name": str(properties.get("gn_name") or "").strip() or None,
                "bbox": [
                    round(min(longitudes), 4),
                    round(min(latitudes), 4),
                    round(max(longitudes), 4),
                    round(max(latitudes), 4),
                ],
            }
        )
    regions.sort(key=lambda item: (item["adm0_a3"], item["name"]))
    asset = {
        "asset_version": ASSET_VERSION,
        "title": "Natural Earth 1:50m Admin-1 search gazetteer",
        "natural_earth_version": "5.1.1",
        "source_geojson_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "source_sha256": digest,
        "license": "public domain",
        "semantics": (
            "Generalized Admin-1 names and bounding boxes are search-query hints only; "
            "they are not point-in-polygon results, legal boundaries, data coverage, "
            "or scientific evidence."
        ),
        "region_count": len(regions),
        "regions": regions,
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
                "region_count": asset["region_count"],
                "source_sha256": asset["source_sha256"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
