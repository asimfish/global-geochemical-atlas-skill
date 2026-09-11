#!/usr/bin/env python3
"""Create the compact, pinned Natural Earth Admin-0 asset used by D3.

This is a maintainer utility, not a runtime downloader.  Pass the exact pinned
GeoJSON files documented in references/licenses-and-citations.md.

Version 2 of the asset additionally applies three pinned analysis-geometry
edits so the China analysis-admission unit matches the Chinese official
cartographic standard (Ministry of Natural Resources standard map
GS(2023)2767):

* CHN gains the Southern Tibet (Zangnan) polygon taken from the pinned
  Natural Earth 1:10m Admin-0 Disputed Areas feature "Arunachal Pradesh".
* IND receives the same polygon as an interior exclusion ring so the disputed
  area is not double-counted into the India admission unit.
* TWN swaps its 9-point 1:110m outline for the pinned 1:50m geometry because
  the coarse outline rejected onshore points (for example Kaohsiung).

These edits define data-admission units for point filtering and reference
linework only; they are not an independent legal-boundary assertion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ASSET_VERSION = "ai4s-natural-earth-admin0-v2"
MACROREGION_ASSET_VERSION = "ai4s-natural-earth-macroregions-v1"
EXPECTED_SOURCE_SHA256 = (
    "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"
)
EXPECTED_DISPUTED_SHA256 = (
    "9cafef8b7dfb6b164dc58f218f981f4ace9f716f6c03795d4c62d1ac9f3d50f5"
)
EXPECTED_COUNTRIES_50M_SHA256 = (
    "3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb"
)
SOURCE_COMMIT = "ca96624a56bd078437bca8184e78163e5039ad19"
SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{SOURCE_COMMIT}/geojson/ne_110m_admin_0_countries.geojson"
)
DISPUTED_SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{SOURCE_COMMIT}/geojson/ne_10m_admin_0_disputed_areas.geojson"
)
COUNTRIES_50M_SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    f"{SOURCE_COMMIT}/geojson/ne_50m_admin_0_countries.geojson"
)
ZANGNAN_DISPUTED_BRK_NAME = "Arunachal Pradesh"


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


def read_pinned(path: Path, expected_sha256: str, label: str) -> Any:
    source_bytes = path.read_bytes()
    digest = hashlib.sha256(source_bytes).hexdigest()
    if digest != expected_sha256:
        raise ValueError(
            f"{label} SHA-256 mismatch; use the pinned Natural Earth GeoJSON ({expected_sha256})"
        )
    raw = json.loads(source_bytes)
    if raw.get("type") != "FeatureCollection" or not isinstance(
        raw.get("features"), list
    ):
        raise ValueError(f"{label} must be a GeoJSON FeatureCollection")
    return raw


def zangnan_polygon(disputed_raw: Any) -> list[Any]:
    for feature in disputed_raw["features"]:
        properties = feature.get("properties") or {}
        if properties.get("BRK_NAME") != ZANGNAN_DISPUTED_BRK_NAME:
            continue
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Polygon":
            raise ValueError("disputed-area feature geometry must be a Polygon")
        return rounded(geometry["coordinates"])
    raise ValueError(f"disputed-area feature is missing: {ZANGNAN_DISPUTED_BRK_NAME!r}")


def taiwan_geometry(countries_50m_raw: Any) -> dict[str, Any]:
    for feature in countries_50m_raw["features"]:
        properties = feature.get("properties") or {}
        if properties.get("ADM0_A3") != "TWN":
            continue
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "Polygon":
            return {
                "type": "MultiPolygon",
                "coordinates": [rounded(geometry["coordinates"])],
            }
        if geometry.get("type") == "MultiPolygon":
            return {
                "type": "MultiPolygon",
                "coordinates": rounded(geometry["coordinates"]),
            }
        raise ValueError("1:50m TWN geometry type is unsupported")
    raise ValueError("1:50m countries file is missing TWN")


def apply_china_analysis_edits(
    countries: list[dict[str, Any]],
    disputed_raw: Any,
    countries_50m_raw: Any,
) -> dict[str, Any]:
    by_code = {country["iso_a3"]: country for country in countries}
    for code in ("CHN", "IND", "TWN"):
        if code not in by_code:
            raise ValueError(f"admin-0 asset is missing {code}")
    polygon = zangnan_polygon(disputed_raw)

    chn_geometry = by_code["CHN"]["geometry"]
    if chn_geometry["type"] != "MultiPolygon":
        raise ValueError("CHN geometry must be a MultiPolygon")
    chn_geometry["coordinates"].append(polygon)

    ind_geometry = by_code["IND"]["geometry"]
    if ind_geometry["type"] != "Polygon" or len(ind_geometry["coordinates"]) != 1:
        raise ValueError("IND geometry must be a Polygon without pre-existing holes")
    ind_geometry["coordinates"].append(polygon[0])

    by_code["TWN"]["geometry"] = taiwan_geometry(countries_50m_raw)

    return {
        "purpose": (
            "Scientific analysis-admission geometry aligned with the Chinese "
            "official cartographic standard (Ministry of Natural Resources "
            "standard map GS(2023)2767). These edits define data-admission "
            "units for point filtering and reference linework only; they are "
            "not an independent legal-boundary assertion."
        ),
        "edits": [
            {
                "iso_a3": "CHN",
                "edit": "appended_polygon",
                "region": "Southern Tibet (Zangnan)",
                "geometry_source": {
                    "dataset": "Natural Earth 1:10m Admin 0 Disputed Areas",
                    "feature_brk_name": ZANGNAN_DISPUTED_BRK_NAME,
                    "source_geojson_url": DISPUTED_SOURCE_URL,
                    "source_commit": SOURCE_COMMIT,
                    "source_sha256": EXPECTED_DISPUTED_SHA256,
                    "license": "public domain",
                },
            },
            {
                "iso_a3": "IND",
                "edit": "added_interior_exclusion_ring",
                "region": "Southern Tibet (Zangnan)",
                "geometry_source": "same disputed-area polygon as the CHN edit",
            },
            {
                "iso_a3": "TWN",
                "edit": "replaced_geometry_with_1_50m",
                "reason": (
                    "The 9-point 1:110m outline rejected onshore points "
                    "(e.g. Kaohsiung)."
                ),
                "geometry_source": {
                    "dataset": "Natural Earth 1:50m Admin 0 Countries",
                    "source_geojson_url": COUNTRIES_50M_SOURCE_URL,
                    "source_commit": SOURCE_COMMIT,
                    "source_sha256": EXPECTED_COUNTRIES_50M_SHA256,
                    "license": "public domain",
                },
            },
        ],
    }


def build(
    source: Path,
    disputed_source: Path,
    countries_50m_source: Path,
    output: Path,
    macroregions_output: Path | None = None,
) -> None:
    raw = read_pinned(source, EXPECTED_SOURCE_SHA256, "source")
    disputed_raw = read_pinned(
        disputed_source, EXPECTED_DISPUTED_SHA256, "disputed source"
    )
    countries_50m_raw = read_pinned(
        countries_50m_source, EXPECTED_COUNTRIES_50M_SHA256, "1:50m countries source"
    )
    countries = []
    macroregions: dict[str, str] = {}
    for feature in raw["features"]:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        iso_a3 = properties.get("ADM0_A3")
        if not isinstance(iso_a3, str) or len(iso_a3) != 3:
            raise ValueError("Natural Earth feature is missing ADM0_A3")
        continent = properties.get("CONTINENT")
        if not isinstance(continent, str) or not continent.strip():
            raise ValueError(f"Natural Earth feature {iso_a3} is missing CONTINENT")
        if iso_a3 in macroregions:
            raise ValueError(f"Natural Earth ADM0_A3 is duplicated: {iso_a3}")
        macroregions[iso_a3] = continent.strip()
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
    analysis_modifications = apply_china_analysis_edits(
        countries, disputed_raw, countries_50m_raw
    )
    total_points = sum(
        point_count(item["geometry"]["coordinates"]) for item in countries
    )
    asset = {
        "asset_version": ASSET_VERSION,
        "title": "Natural Earth 1:110m Admin 0 Countries",
        "natural_earth_version": "5.1.1",
        "scale": "1:110m",
        "coordinate_reference_system": "WGS84 longitude/latitude",
        "source_page": (
            "https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/"
        ),
        "source_geojson_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "source_sha256": EXPECTED_SOURCE_SHA256,
        "license": "public domain",
        "boundary_semantics": (
            "Natural Earth de facto Admin-0 cartographic boundaries with "
            "pinned China analysis-admission edits (see analysis_modifications)"
        ),
        "analysis_modifications": analysis_modifications,
        "country_count": len(countries),
        "point_count": total_points,
        "countries": countries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(asset, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    if macroregions_output is not None:
        macroregion_asset = {
            "asset_version": MACROREGION_ASSET_VERSION,
            "title": "Natural Earth 1:110m Admin-0 continent crosswalk",
            "natural_earth_version": "5.1.1",
            "source_geojson_url": SOURCE_URL,
            "source_commit": SOURCE_COMMIT,
            "source_sha256": EXPECTED_SOURCE_SHA256,
            "license": "public domain",
            "semantics": (
                "CONTINENT values copied from the pinned Natural Earth Admin-0 "
                "properties; open-ocean coordinates remain a separate class"
            ),
            "country_count": len(macroregions),
            "macroregions": dict(sorted(macroregions.items())),
        }
        macroregions_output.parent.mkdir(parents=True, exist_ok=True)
        macroregions_output.write_text(
            json.dumps(
                macroregion_asset,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "output": str(output),
                "countries": len(countries),
                "points": total_points,
                "source_sha256": EXPECTED_SOURCE_SHA256,
                "macroregions_output": (
                    str(macroregions_output)
                    if macroregions_output is not None
                    else None
                ),
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument(
        "--disputed-source",
        required=True,
        type=Path,
        help="Pinned Natural Earth 1:10m Admin-0 Disputed Areas GeoJSON",
    )
    parser.add_argument(
        "--countries-50m-source",
        required=True,
        type=Path,
        help="Pinned Natural Earth 1:50m Admin-0 Countries GeoJSON",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--macroregions-output",
        type=Path,
        help="Optional compact ISO-A3 to Natural Earth continent crosswalk",
    )
    args = parser.parse_args()
    build(
        args.source,
        args.disputed_source,
        args.countries_50m_source,
        args.output,
        args.macroregions_output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
