#!/usr/bin/env python3
"""Match D1 samples to geologic map context without altering source geology.

The authoritative input field ``geologic_unit_raw`` is copied verbatim to the
result and is never used to choose a map unit.  Point mode preserves every
Macrostrat candidate and reports overlaps as ambiguous.  Tile mode uses the
Macrostrat ``carto`` vector layer for scalable, incremental point-in-polygon
matching and explicitly labels its blended-scale limitation.

No content digest is computed or consumed.  Cache identity is the readable API
version/endpoint plus coordinates or z/x/y tile coordinates.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import struct
import sys
import tempfile
import time
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCHEMA_VERSION = "d1-geology-context-result-v1"
MATCHER_VERSION = "d1-macrostrat-geology-context-v1"
MACROSTRAT_API_ROOT = "https://macrostrat.org/api/v2"
MACROSTRAT_POINT_ENDPOINT = f"{MACROSTRAT_API_ROOT}/geologic_units/map"
MACROSTRAT_META_ENDPOINT = f"{MACROSTRAT_API_ROOT}/meta"
MACROSTRAT_TILE_TEMPLATE = "https://tiles.macrostrat.org/carto/{z}/{x}/{y}.mvt"
MACROSTRAT_LICENSE = "CC-BY-4.0"
VALID_MATCH_STATUSES = {
    "matched",
    "ambiguous",
    "unmatched",
    "failed",
    "not_attempted_missing_coordinate",
}


class GeologyContextError(ValueError):
    """Raised for invalid input or unusable upstream data."""


@dataclass(frozen=True)
class SampleLocation:
    sample_id: str
    latitude: float | None
    longitude: float | None
    geologic_unit_raw: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coordinate(value: Any, *, latitude: bool) -> float | None:
    number = _optional_number(value)
    if number is None:
        return None
    low, high = (-90.0, 90.0) if latitude else (-180.0, 180.0)
    if not low <= number <= high:
        raise GeologyContextError(f"coordinate outside WGS84 bounds: {number}")
    return number


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data):
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7
        if shift > 70:
            break
    raise GeologyContextError("invalid protobuf varint")


def _protobuf_fields(data: bytes) -> Iterator[tuple[int, int, Any]]:
    offset = 0
    while offset < len(data):
        tag, offset = _read_varint(data, offset)
        field_number, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, offset = _read_varint(data, offset)
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise GeologyContextError("truncated protobuf fixed64")
            value = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            size, offset = _read_varint(data, offset)
            end = offset + size
            if end > len(data):
                raise GeologyContextError("truncated protobuf field")
            value = data[offset:end]
            offset = end
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise GeologyContextError("truncated protobuf fixed32")
            value = data[offset : offset + 4]
            offset += 4
        else:
            raise GeologyContextError(f"unsupported protobuf wire type: {wire_type}")
        yield field_number, wire_type, value


def _decode_mvt_value(data: bytes) -> Any:
    for field, wire, value in _protobuf_fields(data):
        if field == 1 and wire == 2:
            return value.decode("utf-8")
        if field == 2 and wire == 5:
            return struct.unpack("<f", value)[0]
        if field == 3 and wire == 1:
            return struct.unpack("<d", value)[0]
        if field in {4, 5} and wire == 0:
            return value
        if field == 6 and wire == 0:
            return (value >> 1) ^ -(value & 1)
        if field == 7 and wire == 0:
            return bool(value)
    return None


def _packed_varints(data: bytes) -> list[int]:
    values: list[int] = []
    offset = 0
    while offset < len(data):
        value, offset = _read_varint(data, offset)
        values.append(value)
    return values


def _decode_geometry(commands: Sequence[int]) -> list[list[tuple[int, int]]]:
    x = y = 0
    rings: list[list[tuple[int, int]]] = []
    active: list[tuple[int, int]] | None = None
    offset = 0
    while offset < len(commands):
        command = commands[offset]
        offset += 1
        command_id, count = command & 7, command >> 3
        if command_id in {1, 2}:
            for _ in range(count):
                if offset + 1 >= len(commands):
                    raise GeologyContextError("truncated MVT geometry")
                dx, dy = commands[offset], commands[offset + 1]
                offset += 2
                x += (dx >> 1) ^ -(dx & 1)
                y += (dy >> 1) ^ -(dy & 1)
                if command_id == 1:
                    active = [(x, y)]
                    rings.append(active)
                elif active is not None:
                    active.append((x, y))
        elif command_id == 7:
            for _ in range(count):
                if active and active[-1] != active[0]:
                    active.append(active[0])
        else:
            raise GeologyContextError(f"unsupported MVT geometry command: {command_id}")
    return [ring for ring in rings if len(ring) >= 4]


def decode_mvt_units(tile: bytes) -> tuple[int, list[dict[str, Any]]]:
    """Decode the polygon attributes and tile-coordinate rings of the units layer."""

    layer_payloads = [value for field, wire, value in _protobuf_fields(tile) if field == 3 and wire == 2]
    for layer in layer_payloads:
        name = ""
        extent = 4096
        keys: list[str] = []
        values: list[Any] = []
        features: list[bytes] = []
        for field, wire, value in _protobuf_fields(layer):
            if field == 1 and wire == 2:
                name = value.decode("utf-8")
            elif field == 2 and wire == 2:
                features.append(value)
            elif field == 3 and wire == 2:
                keys.append(value.decode("utf-8"))
            elif field == 4 and wire == 2:
                values.append(_decode_mvt_value(value))
            elif field == 5 and wire == 0:
                extent = int(value)
        if name != "units":
            continue
        decoded: list[dict[str, Any]] = []
        for feature in features:
            feature_id: int | None = None
            tags: list[int] = []
            geometry_type = 0
            geometry: list[int] = []
            for field, wire, value in _protobuf_fields(feature):
                if field == 1 and wire == 0:
                    feature_id = int(value)
                elif field == 2 and wire == 2:
                    tags = _packed_varints(value)
                elif field == 3 and wire == 0:
                    geometry_type = int(value)
                elif field == 4 and wire == 2:
                    geometry = _packed_varints(value)
            if geometry_type != 3:
                continue
            properties = {
                keys[tags[i]]: values[tags[i + 1]]
                for i in range(0, len(tags) - 1, 2)
                if tags[i] < len(keys) and tags[i + 1] < len(values)
            }
            decoded.append(
                {
                    "feature_id": feature_id,
                    "properties": properties,
                    "rings": _decode_geometry(geometry),
                }
            )
        return extent, decoded
    # Empty ocean tiles legitimately have no units layer.
    return 4096, []


def _point_in_ring(px: float, py: float, ring: Sequence[tuple[int, int]]) -> bool:
    inside = False
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        if (y1 > py) != (y2 > py):
            crossing = (x2 - x1) * (py - y1) / (y2 - y1) + x1
            if px < crossing:
                inside = not inside
    return inside


def _point_in_polygon(px: float, py: float, rings: Sequence[Sequence[tuple[int, int]]]) -> bool:
    return sum(1 for ring in rings if _point_in_ring(px, py, ring)) % 2 == 1


def _distance_to_segment(px: float, py: float, a: tuple[int, int], b: tuple[int, int]) -> float:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + fraction * dx), py - (ay + fraction * dy))


def _boundary_distance_units(px: float, py: float, rings: Sequence[Sequence[tuple[int, int]]]) -> float | None:
    distances = [
        _distance_to_segment(px, py, ring[index], ring[index + 1])
        for ring in rings
        for index in range(len(ring) - 1)
    ]
    return min(distances) if distances else None


def _tile_position(latitude: float, longitude: float, zoom: int) -> tuple[int, int, float, float]:
    latitude = max(-85.05112878, min(85.05112878, latitude))
    tiles = 1 << zoom
    xf = (longitude + 180.0) / 360.0 * tiles
    latitude_radians = math.radians(latitude)
    yf = (1.0 - math.asinh(math.tan(latitude_radians)) / math.pi) / 2.0 * tiles
    x = min(tiles - 1, max(0, int(math.floor(xf))))
    y = min(tiles - 1, max(0, int(math.floor(yf))))
    return x, y, xf - x, yf - y


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class MacrostratClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        offline: bool = False,
        timeout: float = 30.0,
        retries: int = 2,
        user_agent: str = "global-geochemical-atlas-skill/d1-geology-context-v1",
        fixture: bool = False,
    ) -> None:
        self.cache_dir = cache_dir
        self.offline = offline
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.fixture = fixture
        self._decoded_tiles: OrderedDict[tuple[int, int, int], tuple[int, list[dict[str, Any]]]] = OrderedDict()

    def _request(self, url: str) -> bytes:
        error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json,*/*"})
                with urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                error = exc
                if attempt < self.retries:
                    time.sleep(0.25 * (2**attempt))
        raise GeologyContextError(f"Macrostrat request failed: {error}")

    def _cached(self, path: Path, url: str) -> tuple[bytes, str]:
        if path.is_file():
            return path.read_bytes(), "fixture" if self.fixture else "cache"
        if self.offline:
            raise GeologyContextError(f"offline cache miss: {path}")
        payload = self._request(url)
        _atomic_write(path, payload)
        return payload, "online"

    def api_version(self) -> tuple[str | None, str]:
        path = self.cache_dir / "macrostrat-api-meta-v2.json"
        payload, cache_status = self._cached(path, MACROSTRAT_META_ENDPOINT)
        try:
            version = json.loads(payload)["success"]["data"].get("version")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise GeologyContextError("Macrostrat metadata response is invalid") from exc
        return _optional_text(version), cache_status

    def point(self, latitude: float, longitude: float) -> tuple[dict[str, Any], str, str]:
        coordinate_id = f"lat-{latitude:+.6f}_lng-{longitude:+.6f}"
        path = self.cache_dir / "points" / f"{coordinate_id}.json"
        url = f"{MACROSTRAT_POINT_ENDPOINT}?{urlencode({'lat': f'{latitude:.8f}', 'lng': f'{longitude:.8f}'})}"
        payload, cache_status = self._cached(path, url)
        try:
            response = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GeologyContextError("Macrostrat point response is not valid JSON") from exc
        return response, cache_status, url

    def tile(self, zoom: int, x: int, y: int, *, refresh: bool = False) -> tuple[bytes, str, str]:
        url = MACROSTRAT_TILE_TEMPLATE.format(z=zoom, x=x, y=y)
        path = self.cache_dir / "tiles" / "carto" / str(zoom) / str(x) / f"{y}.mvt"
        if refresh:
            if self.offline or self.fixture:
                raise GeologyContextError(f"offline mode cannot refresh tile: {path}")
            payload = self._request(url)
            _atomic_write(path, payload)
            return payload, "online", url
        payload, cache_status = self._cached(path, url)
        return payload, cache_status, url

    def tile_units(self, zoom: int, x: int, y: int) -> tuple[int, list[dict[str, Any]], str, str]:
        """Decode a tile once and retain a bounded in-process LRU for batch runs."""

        key = (zoom, x, y)
        payload, cache_status, url = self.tile(zoom, x, y)
        cached = self._decoded_tiles.get(key)
        if cached is not None:
            self._decoded_tiles.move_to_end(key)
            return cached[0], cached[1], cache_status, url
        try:
            decoded = decode_mvt_units(payload)
        except GeologyContextError:
            # A prematurely closed chunked response can leave a readable but
            # truncated cache entry. Re-request once online; offline mode must
            # report the cache corruption instead of silently dropping data.
            payload, cache_status, url = self.tile(zoom, x, y, refresh=True)
            decoded = decode_mvt_units(payload)
        self._decoded_tiles[key] = decoded
        self._decoded_tiles.move_to_end(key)
        while len(self._decoded_tiles) > 128:
            self._decoded_tiles.popitem(last=False)
        return decoded[0], decoded[1], cache_status, url


def _candidate(properties: Mapping[str, Any], refs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source_id = _optional_text(properties.get("source_id"))
    unit_name = _optional_text(properties.get("name"))
    strat_name = _optional_text(properties.get("strat_name"))
    return {
        "map_id": _optional_text(properties.get("map_id")),
        "source_id": source_id,
        "unit_name": strat_name or unit_name,
        "strat_name": strat_name,
        "lithology": _optional_text(properties.get("lith")),
        "top_age_ma": _optional_number(properties.get("t_age", properties.get("best_t_age"))),
        "bottom_age_ma": _optional_number(properties.get("b_age", properties.get("best_b_age"))),
        "source_reference": _optional_text((refs or {}).get(str(source_id))),
        "map_scale": _optional_text(properties.get("scale")),
    }


def _base_result(sample: SampleLocation) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_id": sample.sample_id,
        "latitude": sample.latitude,
        "longitude": sample.longitude,
        "geologic_unit_raw": sample.geologic_unit_raw,
        "matched_geologic_unit": None,
        "geology_map_source": None,
        "geology_map_source_id": None,
        "geology_map_version": None,
        "match_method": None,
        "match_scale": None,
        "boundary_distance_m": None,
        "match_uncertainty": None,
        "match_status": "failed",
        "match_candidates": [],
        "source_endpoint": None,
        "source_license": None,
        "accessed_at": None,
        "cache_status": "failed",
        "error": None,
    }


def match_point(sample: SampleLocation, client: MacrostratClient) -> dict[str, Any]:
    result = _base_result(sample)
    if sample.latitude is None or sample.longitude is None:
        result.update(
            match_status="not_attempted_missing_coordinate",
            cache_status="not_applicable",
            match_uncertainty="No WGS84 coordinate was available; no map lookup was attempted.",
        )
        return result
    try:
        response, cache_status, endpoint = client.point(sample.latitude, sample.longitude)
        success = response["success"]
        data = success.get("data", [])
        refs = success.get("refs", {})
        if not isinstance(data, list):
            raise GeologyContextError("Macrostrat point data must be a list")
        candidates = [_candidate(item, refs) for item in data if isinstance(item, Mapping)]
        candidates = [item for item in candidates if item["unit_name"]]
        version, _ = client.api_version()
        result.update(
            geology_map_source="Macrostrat",
            geology_map_version=version,
            match_method="macrostrat_v2_point_candidates",
            match_scale="multiple_source_scales" if len(candidates) > 1 else None,
            match_candidates=candidates,
            source_endpoint=endpoint,
            source_license=_optional_text(success.get("license")) or MACROSTRAT_LICENSE,
            accessed_at=_utc_now(),
            cache_status=cache_status,
        )
        if not candidates:
            result.update(
                match_status="unmatched",
                match_uncertainty="Macrostrat returned no covering geologic map unit.",
            )
        elif len(candidates) == 1:
            candidate = candidates[0]
            result.update(
                matched_geologic_unit=candidate["unit_name"],
                geology_map_source_id=candidate["source_id"],
                match_scale=candidate["map_scale"],
                match_status="matched",
                match_uncertainty="Single point-query candidate; polygon boundary distance is unavailable in point mode.",
            )
        else:
            result.update(
                match_status="ambiguous",
                match_uncertainty=(
                    "Multiple map units or source scales cover this coordinate; no candidate was forced into "
                    "matched_geologic_unit."
                ),
            )
    except Exception as exc:  # a failed source must become an explicit result row
        result.update(
            match_status="failed",
            match_uncertainty="The lookup failed; no geologic unit was inferred.",
            error=str(exc),
            accessed_at=_utc_now(),
        )
    return result


def match_tile(sample: SampleLocation, client: MacrostratClient, *, zoom: int = 5) -> dict[str, Any]:
    result = _base_result(sample)
    if sample.latitude is None or sample.longitude is None:
        result.update(
            match_status="not_attempted_missing_coordinate",
            cache_status="not_applicable",
            match_uncertainty="No WGS84 coordinate was available; no map lookup was attempted.",
        )
        return result
    if abs(sample.latitude) > 85.05112878:
        fallback = match_point(sample, client)
        fallback["match_method"] = "macrostrat_v2_point_candidates_polar_fallback"
        note = "Carto Web Mercator tiles stop at ±85.05112878°; point-candidate mode was used instead."
        fallback["match_uncertainty"] = f"{note} {fallback.get('match_uncertainty') or ''}".strip()
        return fallback
    try:
        x, y, local_x, local_y = _tile_position(sample.latitude, sample.longitude, zoom)
        extent, features, cache_status, endpoint = client.tile_units(zoom, x, y)
        point_x, point_y = local_x * extent, local_y * extent
        covering = [feature for feature in features if _point_in_polygon(point_x, point_y, feature["rings"])]
        version, _ = client.api_version()
        candidates = [_candidate(feature["properties"]) for feature in covering]
        candidates = [candidate for candidate in candidates if candidate["unit_name"]]
        result.update(
            geology_map_source="Macrostrat",
            geology_map_version=version,
            match_method="macrostrat_carto_mvt_point_in_polygon",
            match_scale=f"carto_blended_z{zoom}",
            match_candidates=candidates,
            source_endpoint=endpoint,
            source_license=MACROSTRAT_LICENSE,
            accessed_at=_utc_now(),
            cache_status=cache_status,
        )
        if not covering or not candidates:
            result.update(
                match_status="unmatched",
                match_uncertainty="No polygon in the cached carto tile covered the coordinate.",
            )
        elif len(candidates) > 1:
            result.update(
                match_status="ambiguous",
                match_uncertainty=(
                    "Overlapping polygons remained in the carto tile; no candidate was forced into "
                    "matched_geologic_unit."
                ),
            )
        else:
            candidate = candidates[0]
            distance_units = _boundary_distance_units(point_x, point_y, covering[0]["rings"])
            latitude_factor = max(0.01, math.cos(math.radians(sample.latitude)))
            tile_width_m = 40075016.686 * latitude_factor / (1 << zoom)
            result.update(
                matched_geologic_unit=candidate["unit_name"],
                geology_map_source_id=candidate["source_id"],
                boundary_distance_m=(
                    round(distance_units / extent * tile_width_m, 3) if distance_units is not None else None
                ),
                match_status="matched",
                match_uncertainty=(
                    f"Macrostrat carto z{zoom} is a visualization layer that blends source scales. Boundary "
                    "distance is estimated from clipped tile geometry and may be a lower bound near tile edges."
                ),
            )
    except Exception as exc:
        result.update(
            match_status="failed",
            match_uncertainty="The tile lookup failed; no geologic unit was inferred.",
            error=str(exc),
            accessed_at=_utc_now(),
        )
    return result


def sample_patch(sample: Mapping[str, Any], result: Mapping[str, Any]) -> dict[str, Any]:
    """Return the existing sample-v2 geology fields without touching source geology."""

    if sample.get("geologic_unit_raw") != result.get("geologic_unit_raw"):
        raise GeologyContextError("geologic_unit_raw changed between source sample and match result")
    patch = dict(sample)
    patch.update(
        matched_geologic_unit=result.get("matched_geologic_unit"),
        geology_map_source=result.get("geology_map_source"),
        geology_map_version=result.get("geology_map_version"),
        match_method=result.get("match_method"),
        match_scale=result.get("match_scale"),
        boundary_distance_m=result.get("boundary_distance_m"),
        match_uncertainty=result.get("match_uncertainty"),
    )
    return patch


def iter_locations(path: Path) -> Iterator[SampleLocation]:
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                yield _location_from_row(row, index)
    else:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=2):
                yield _location_from_row(row, index)


def _location_from_row(row: Any, index: int) -> SampleLocation:
    if not isinstance(row, Mapping):
        raise GeologyContextError(f"row {index} is not an object")
    sample_id = _optional_text(row.get("sample_id"))
    if not sample_id:
        raise GeologyContextError(f"row {index} lacks sample_id")
    return SampleLocation(
        sample_id=sample_id,
        latitude=_coordinate(row.get("latitude"), latitude=True),
        longitude=_coordinate(row.get("longitude"), latitude=False),
        geologic_unit_raw=_optional_text(row.get("geologic_unit_raw")),
    )


def load_locations(path: Path) -> list[SampleLocation]:
    """Materialize locations for callers that explicitly need an in-memory list."""

    return list(iter_locations(path))


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _atomic_write(path, payload.encode("utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="CSV or JSONL with sample_id/latitude/longitude")
    parser.add_argument("--output", type=Path, required=True, help="Output geology context JSONL")
    storage = parser.add_mutually_exclusive_group(required=True)
    storage.add_argument("--cache-dir", type=Path, help="Readable incremental API/tile cache")
    storage.add_argument("--fixture-dir", type=Path, help="Tracked offline fixture cache")
    parser.add_argument("--mode", choices=("point", "tile"), default="point")
    parser.add_argument("--offline", action="store_true", help="Require all API responses or tiles to exist in cache")
    parser.add_argument(
        "--zoom",
        type=int,
        default=5,
        help="Carto tile zoom (default 5 for global coarse coverage; higher zoom can expose local-map gaps)",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--run-manifest", type=Path, help="Optional non-hash run identity and count report")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0 <= args.zoom <= 14:
        print("error: --zoom must be between 0 and 14", file=sys.stderr)
        return 2
    try:
        started_at = _utc_now()
        cache_dir = args.fixture_dir or args.cache_dir
        client = MacrostratClient(
            cache_dir,
            offline=args.offline or args.fixture_dir is not None,
            timeout=args.timeout,
            retries=args.retries,
            fixture=args.fixture_dir is not None,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{args.output.name}.", dir=args.output.parent)
        counts: dict[str, int] = {}
        cache_counts: dict[str, int] = {}
        occupied_tiles: set[tuple[int, int, int]] = set()
        record_count = 0
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                for location in iter_locations(args.input):
                    if args.mode == "point":
                        row = match_point(location, client)
                    else:
                        row = match_tile(location, client, zoom=args.zoom)
                        if location.latitude is not None and location.longitude is not None:
                            tile_x, tile_y, _, _ = _tile_position(location.latitude, location.longitude, args.zoom)
                            occupied_tiles.add((args.zoom, tile_x, tile_y))
                    status = str(row["match_status"])
                    if status not in VALID_MATCH_STATUSES:
                        raise GeologyContextError(f"invalid match status: {status}")
                    counts[status] = counts.get(status, 0) + 1
                    cache_status = str(row["cache_status"])
                    cache_counts[cache_status] = cache_counts.get(cache_status, 0) + 1
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
                    record_count += 1
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, args.output)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        api_version, _ = client.api_version()
        finished_at = _utc_now()
        if args.run_manifest:
            manifest = {
                "run_version": MATCHER_VERSION,
                "mode": args.mode,
                "source": "Macrostrat",
                "source_api_version": api_version,
                "source_license": MACROSTRAT_LICENSE,
                "point_endpoint": MACROSTRAT_POINT_ENDPOINT,
                "tile_endpoint_template": MACROSTRAT_TILE_TEMPLATE,
                "input": str(args.input),
                "output": str(args.output),
                "started_at": started_at,
                "finished_at": finished_at,
                "record_count": record_count,
                "match_status_counts": counts,
                "cache_status_counts": cache_counts,
                "tile_zoom": args.zoom if args.mode == "tile" else None,
                "occupied_tile_count": len(occupied_tiles) if args.mode == "tile" else None,
                "cache_identity_fields": (
                    ["api_version", "latitude", "longitude"]
                    if args.mode == "point"
                    else ["api_version", "layer", "z", "x", "y"]
                ),
                "content_hashing_used": False,
                "result_schema": SCHEMA_VERSION,
                "result_fields": list(_base_result(SampleLocation("schema", None, None)).keys()),
            }
            _atomic_write(args.run_manifest, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
    except (GeologyContextError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "success", "records": record_count, "match_statuses": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
