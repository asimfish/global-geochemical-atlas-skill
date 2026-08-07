#!/usr/bin/env python3
"""Acquire the pinned GEMStat v3 arsenic subset using identified ZIP byte ranges."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SOURCE_ID = "gemstat-open-archive"
DATASET_VERSION = "v3"
DATASET_DOI = "10.5281/zenodo.18459694"
CONCEPT_DOI = "10.5281/zenodo.13881899"
RECORD_ID = 18459694
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
ARCHIVE_URL = f"https://zenodo.org/records/{RECORD_ID}/files/GFQA_v3.zip?download=1"
ARCHIVE_NAME = "GFQA_v3.zip"
ARCHIVE_BYTES = 201_278_791

MEMBERS: tuple[dict[str, Any], ...] = (
    {
        "name": "Arsenic.csv",
        "range_start": 3_033_466,
        "range_end": 5_138_990,
        "compressed_bytes": 2_105_484,
        "uncompressed_bytes": 30_585_144,
    },
    {
        "name": "GEMStat_methods_metadata.csv",
        "range_start": 37_150_286,
        "range_end": 37_236_391,
        "compressed_bytes": 86_048,
        "uncompressed_bytes": 521_959,
    },
    {
        "name": "GEMStat_parameter_metadata.csv",
        "range_start": 37_236_392,
        "range_end": 37_279_436,
        "compressed_bytes": 42_985,
        "uncompressed_bytes": 146_762,
    },
    {
        "name": "GEMStat_station_metadata.csv",
        "range_start": 37_279_437,
        "range_end": 37_914_330,
        "compressed_bytes": 634_836,
        "uncompressed_bytes": 3_571_887,
    },
    {
        "name": "README_output_format.txt",
        "range_start": 171_533_195,
        "range_end": 171_536_953,
        "compressed_bytes": 3_705,
        "uncompressed_bytes": 16_727,
    },
)


class AcquisitionError(RuntimeError):
    """Raised when pinned GEMStat evidence cannot be acquired or verified."""


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def read_limited(response: Any, maximum: int) -> bytes:
    value = response.read(maximum + 1)
    if len(value) > maximum:
        raise AcquisitionError(f"response exceeds {maximum} bytes")
    return value


def fetch(request: urllib.request.Request, maximum: int, timeout: float, retries: int = 3) -> bytes:
    context = ssl.create_default_context()
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                final = urllib.parse.urlparse(response.geturl())
                if final.scheme != "https" or final.hostname != "zenodo.org":
                    raise AcquisitionError("Zenodo request resolved to an unexpected host")
                return read_limited(response, maximum)
        except (OSError, urllib.error.URLError, AcquisitionError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1 + attempt)
    raise AcquisitionError(f"official request failed after {retries} attempts: {last_error}")


def validate_metadata(value: Mapping[str, Any]) -> None:
    metadata = value.get("metadata")
    files = value.get("files")
    if not isinstance(metadata, Mapping) or not isinstance(files, list):
        raise AcquisitionError("Zenodo record metadata has an unexpected shape")
    archive = next((item for item in files if isinstance(item, Mapping) and item.get("key") == ARCHIVE_NAME), None)
    if (
        value.get("id") != RECORD_ID
        or value.get("doi") != DATASET_DOI
        or metadata.get("publication_date") != "2026-02-02"
        or not isinstance(metadata.get("license"), Mapping)
        or metadata["license"].get("id") != "cc-by-4.0"
        or archive is None
        or archive.get("size") != ARCHIVE_BYTES
    ):
        raise AcquisitionError("Zenodo record no longer matches the pinned GEMStat v3 release")


def parse_range_fragment(value: bytes, specification: Mapping[str, Any]) -> bytes:
    expected_range_bytes = specification["range_end"] - specification["range_start"] + 1
    if len(value) != expected_range_bytes:
        raise AcquisitionError(f"range fragment changed: {specification['name']}")
    if len(value) < 30:
        raise AcquisitionError(f"range fragment is truncated: {specification['name']}")
    signature, _, flags, method, _, _, _, compressed, uncompressed, name_length, extra_length = struct.unpack(
        "<IHHHHHIIIHH", value[:30]
    )
    filename = value[30 : 30 + name_length].decode("utf-8")
    payload_start = 30 + name_length + extra_length
    payload = value[payload_start : payload_start + compressed]
    if (
        signature != 0x04034B50
        or flags != 0
        or method != 8
        or filename != specification["name"]
        or compressed != specification["compressed_bytes"]
        or uncompressed != specification["uncompressed_bytes"]
        or len(payload) != compressed
    ):
        raise AcquisitionError(f"local ZIP header changed: {specification['name']}")
    try:
        decoded = zlib.decompress(payload, -15)
    except zlib.error as exc:
        raise AcquisitionError(f"compressed member is corrupt: {specification['name']}") from exc
    if len(decoded) != uncompressed:
        raise AcquisitionError(f"decoded member changed: {specification['name']}")
    return decoded


def fetch_verified_range(specification: Mapping[str, Any], timeout: float, retries: int = 3) -> tuple[bytes, bytes]:
    """Retry short or corrupt partial responses as well as transport exceptions."""

    expected_bytes = specification["range_end"] - specification["range_start"] + 1
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(
            ARCHIVE_URL,
            headers={
                "User-Agent": "global-geochemical-atlas-skill/1",
                "Range": f"bytes={specification['range_start']}-{specification['range_end']}",
            },
        )
        try:
            fragment = fetch(request, expected_bytes, timeout, retries=1)
            decoded = parse_range_fragment(fragment, specification)
            return fragment, decoded
        except (OSError, urllib.error.URLError, AcquisitionError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1 + attempt)
    raise AcquisitionError(
        f"verified range failed after {retries} attempts for {specification['name']}: {last_error}"
    )


def run(cache_dir: Path, mode: str, timeout: float) -> dict[str, Any]:
    root = cache_dir / SOURCE_ID / DATASET_VERSION
    metadata_path = root / "zenodo-record.json"
    if mode == "online":
        metadata_bytes = fetch(
            urllib.request.Request(RECORD_API, headers={"User-Agent": "global-geochemical-atlas-skill/1"}),
            200_000,
            timeout,
        )
        atomic_bytes(metadata_path, metadata_bytes)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError("cached Zenodo metadata is missing or invalid") from exc
    validate_metadata(metadata)

    selected: list[dict[str, Any]] = []
    for specification in MEMBERS:
        range_path = root / "ranges" / f"{specification['name']}.range"
        if mode == "online":
            fragment, decoded = fetch_verified_range(specification, timeout)
            atomic_bytes(range_path, fragment)
        else:
            try:
                fragment = range_path.read_bytes()
            except OSError as exc:
                raise AcquisitionError(f"cached range is missing: {range_path}") from exc
            decoded = parse_range_fragment(fragment, specification)
        member_path = root / "members" / specification["name"]
        atomic_bytes(member_path, decoded)
        selected.append(
            {
                **specification,
                "range_path": str(range_path.relative_to(root)),
                "member_path": str(member_path.relative_to(root)),
            }
        )

    manifest = {
        "acquisition_version": "gemstat-v3-selective-zip-range-v1",
        "source_id": SOURCE_ID,
        "dataset_version": DATASET_VERSION,
        "dataset_doi": DATASET_DOI,
        "concept_doi": CONCEPT_DOI,
        "mode": mode,
        "archive": {
            "filename": ARCHIVE_NAME,
            "bytes": ARCHIVE_BYTES,
            "publisher_record_file_count": 1,
            "zip_member_count": 84,
            "url": ARCHIVE_URL,
        },
        "selected_members": selected,
        "claim_boundary": (
            "Only the arsenic observations and four required metadata/readme members are materialized. "
            "The range selection is tied to the pinned Zenodo record, file name, byte ranges, member names and sizes; "
            "it is not a new publisher release."
        ),
    }
    atomic_json(root / "acquisition.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--accept-cc-by", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.accept_cc_by:
        print("acquire_gemstat_arsenic: --accept-cc-by is required", file=sys.stderr)
        return 2
    if not 1 <= args.timeout <= 300:
        print("acquire_gemstat_arsenic: timeout is outside the safety range", file=sys.stderr)
        return 2
    try:
        manifest = run(args.cache_dir, args.mode, args.timeout)
        print(json.dumps({"status": "PASS", "selected_members": len(manifest["selected_members"])}, sort_keys=True))
        return 0
    except (AcquisitionError, OSError, ValueError) as exc:
        print(f"acquire_gemstat_arsenic: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
