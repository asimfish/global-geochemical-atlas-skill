#!/usr/bin/env python3
"""Build the pinned, compact Natural Earth land asset used by the offline atlas."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import tempfile
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path

from lab_common import LAB_ROOT, atomic_write_json

SOURCE_URL = "https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_land.zip"
SOURCE_PAGE = "https://www.naturalearthdata.com/downloads/110m-physical-vectors/"
TERMS_URL = "https://www.naturalearthdata.com/about/terms-of-use/"
EXPECTED_ARCHIVE_SHA256 = "1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de"
MAXIMUM_DOWNLOAD_BYTES = 1_000_000
DEFAULT_OUTPUT = LAB_ROOT / "assets" / "natural-earth-110m-land.json"
DEFAULT_CACHE = Path(tempfile.gettempdir()) / "natural-earth-110m-land.zip"


class BasemapError(RuntimeError):
    """Raised when the pinned basemap cannot be verified or decoded."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def download_archive(destination: Path) -> Path:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "ai4s-geochemistry-basemap-builder/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAXIMUM_DOWNLOAD_BYTES:
            raise BasemapError(f"basemap archive exceeds limit: {declared}")
        content = response.read(MAXIMUM_DOWNLOAD_BYTES + 1)
    if len(content) > MAXIMUM_DOWNLOAD_BYTES:
        raise BasemapError("basemap archive exceeds download byte limit")
    if sha256_bytes(content) != EXPECTED_ARCHIVE_SHA256:
        raise BasemapError("Natural Earth archive SHA-256 does not match the pinned version")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return destination


def verified_archive(path: Path) -> Path:
    if not path.is_file():
        raise BasemapError(f"archive does not exist: {path}")
    content = path.read_bytes()
    if len(content) > MAXIMUM_DOWNLOAD_BYTES:
        raise BasemapError("basemap archive exceeds byte limit")
    if sha256_bytes(content) != EXPECTED_ARCHIVE_SHA256:
        raise BasemapError("Natural Earth archive SHA-256 does not match the pinned version")
    return path


def rounded_ring(points: Sequence[tuple[float, float]]) -> list[list[float]]:
    result: list[list[float]] = []
    for longitude, latitude in points:
        point = [round(longitude, 4), round(latitude, 4)]
        if not result or result[-1] != point:
            result.append(point)
    if result and result[0] != result[-1]:
        result.append(result[0])
    return result if len(result) >= 4 else []


def polygon_rings(shapefile: bytes) -> tuple[list[list[list[float]]], int]:
    if len(shapefile) < 100 or struct.unpack_from(">i", shapefile, 0)[0] != 9994:
        raise BasemapError("invalid ESRI shapefile header")
    if struct.unpack_from("<i", shapefile, 32)[0] != 5:
        raise BasemapError("Natural Earth land asset is not Polygon shape type 5")

    offset = 100
    rings: list[list[list[float]]] = []
    record_count = 0
    while offset < len(shapefile):
        if offset + 8 > len(shapefile):
            raise BasemapError("truncated shapefile record header")
        _, content_words = struct.unpack_from(">2i", shapefile, offset)
        offset += 8
        content_bytes = content_words * 2
        record = shapefile[offset : offset + content_bytes]
        offset += content_bytes
        if len(record) != content_bytes:
            raise BasemapError("truncated shapefile record")
        shape_type = struct.unpack_from("<i", record, 0)[0]
        if shape_type == 0:
            continue
        if shape_type != 5 or len(record) < 44:
            raise BasemapError(f"unsupported shapefile record type: {shape_type}")
        part_count, point_count = struct.unpack_from("<2i", record, 36)
        parts_offset = 44
        points_offset = parts_offset + part_count * 4
        expected_bytes = points_offset + point_count * 16
        if part_count < 1 or point_count < 3 or expected_bytes > len(record):
            raise BasemapError("invalid polygon part or point count")
        part_starts = list(struct.unpack_from(f"<{part_count}i", record, parts_offset))
        part_starts.append(point_count)
        points = [
            struct.unpack_from("<2d", record, points_offset + index * 16)
            for index in range(point_count)
        ]
        for start, end in zip(part_starts, part_starts[1:]):
            ring = rounded_ring(points[start:end])
            if ring:
                rings.append(ring)
        record_count += 1
    if not rings:
        raise BasemapError("no polygon rings decoded from Natural Earth")
    return rings, record_count


def build_asset(archive_path: Path, output_path: Path) -> dict[str, object]:
    with zipfile.ZipFile(verified_archive(archive_path)) as archive:
        shapefile_name = "ne_110m_land.shp"
        version_name = "ne_110m_land.VERSION.txt"
        shapefile = archive.read(shapefile_name)
        version = archive.read(version_name).decode("ascii").strip()
    rings, record_count = polygon_rings(shapefile)
    payload: dict[str, object] = {
        "asset_version": "ai4s-natural-earth-land-v1",
        "title": "Natural Earth 1:110m Land",
        "natural_earth_version": version,
        "scale": "1:110m",
        "coordinate_reference_system": "WGS84 longitude/latitude",
        "source_url": SOURCE_URL,
        "source_page": SOURCE_PAGE,
        "terms_url": TERMS_URL,
        "license": "public domain",
        "archive_sha256": EXPECTED_ARCHIVE_SHA256,
        "selection": "all land polygon rings; coordinates rounded to 4 decimals",
        "record_count": record_count,
        "ring_count": len(rings),
        "point_count": sum(len(ring) for ring in rings),
        "rings": rings,
    }
    atomic_write_json(output_path, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the pinned Natural Earth offline land asset.")
    parser.add_argument("--archive", type=Path, help="Existing pinned Natural Earth ZIP")
    parser.add_argument("--download", action="store_true", help="Download the pinned ZIP to --cache")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.archive and args.download:
        parser.error("use either --archive or --download")
    try:
        archive = args.archive or (download_archive(args.cache) if args.download else args.cache)
        payload = build_asset(archive, args.output)
    except (BasemapError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": "pass",
                "output": str(args.output),
                "rings": payload["ring_count"],
                "points": payload["point_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
