#!/usr/bin/env python3
"""Acquire seven pinned GEMStat v3 element files by verified ZIP ranges."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import acquire_gemstat_arsenic as base


ELEMENT_MEMBERS: tuple[dict[str, Any], ...] = (
    base.MEMBERS[0],
    {
        "name": "Chromium.csv",
        "range_start": 21_099_972,
        "range_end": 23_395_931,
        "range_sha256": "362df9fd528b7eab5cff03aadceffa330b83eed0d94b71b6e129b89adea4cc97",
        "compressed_bytes": 2_295_918,
        "uncompressed_bytes": 34_359_149,
        "crc32": "04be70ad",
        "sha256": "164294931268c7427cb7c768f23e20484db9c4130044d99c766483fb881cc62c",
    },
    {
        "name": "Copper.csv",
        "range_start": 24_122_334,
        "range_end": 26_169_314,
        "range_sha256": "cfb499687474fcb4575fd1eaecb33f40be7e4f528ca86430623661d9d6a709cd",
        "compressed_bytes": 2_046_941,
        "uncompressed_bytes": 28_448_872,
        "crc32": "9df0925e",
        "sha256": "82fb42ce1bba413a197825017727c8b2c04aa7042f92b07466f81fab3e93c451",
    },
    {
        "name": "Lead.csv",
        "range_start": 47_619_799,
        "range_end": 50_275_481,
        "range_sha256": "f2d7044ecc01d887429fb989f9b4d3e2f311d2100cf95157af4976b90dd9c683",
        "compressed_bytes": 2_655_645,
        "uncompressed_bytes": 40_765_015,
        "crc32": "731fe197",
        "sha256": "6c7edbf736a32985394967ff30c175e4618c6914b7c8a77b38d40c255af7b9f0",
    },
    {
        "name": "Mercury.csv",
        "range_start": 54_591_798,
        "range_end": 56_488_526,
        "range_sha256": "76c512c12cdcfdd3bf3d0edec0c4f83d5ba88f7176c9b96e313fb1a2039371bc",
        "compressed_bytes": 1_896_688,
        "uncompressed_bytes": 31_175_171,
        "crc32": "0f146078",
        "sha256": "13805529f39c9ff6c90a84b341491af9739c72c43d3ec0eba07165957058906f",
    },
    {
        "name": "Nickel.csv",
        "range_start": 57_019_516,
        "range_end": 59_767_178,
        "range_sha256": "e26717aeed36f3ba7781a670170954ad40e877ea1f2f9cbbf784041938f746a0",
        "compressed_bytes": 2_747_623,
        "uncompressed_bytes": 39_456_553,
        "crc32": "bf4c881c",
        "sha256": "fef4cc062e06ea4e3eafd8257b6849ed1d7ece2ac6522c5f9bfdef73ea206b8f",
    },
    {
        "name": "Zinc.csv",
        "range_start": 199_286_587,
        "range_end": 201_270_727,
        "range_sha256": "12e36f17cab48a074abd284dde218df739f4fec27b6db22dc5301b3b8e72b786",
        "compressed_bytes": 1_984_103,
        "uncompressed_bytes": 26_785_044,
        "crc32": "24b8426a",
        "sha256": "0d77884198cdb0c01fa9f0ad8e101e086c709bdbc36ca80dc955a1c6172a192d",
    },
)

MEMBERS = ELEMENT_MEMBERS + base.MEMBERS[1:]


def run(cache_dir: Path, mode: str, timeout: float) -> dict[str, Any]:
    root = cache_dir / base.SOURCE_ID / base.DATASET_VERSION
    metadata_path = root / "zenodo-record.json"
    if mode == "online":
        metadata_bytes = base.fetch(
            base.urllib.request.Request(
                base.RECORD_API,
                headers={"User-Agent": "global-geochemical-atlas-skill/1"},
            ),
            200_000,
            timeout,
        )
        base.atomic_bytes(metadata_path, metadata_bytes)
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise base.AcquisitionError("cached Zenodo metadata is missing or invalid") from exc
    base.validate_metadata(metadata)

    selected: list[dict[str, Any]] = []
    for specification in MEMBERS:
        range_path = root / "ranges" / f"{specification['name']}.range"
        if mode == "online":
            fragment, decoded = base.fetch_verified_range(specification, timeout)
            base.atomic_bytes(range_path, fragment)
        else:
            try:
                fragment = range_path.read_bytes()
            except OSError as exc:
                raise base.AcquisitionError(f"cached range is missing: {range_path}") from exc
            decoded = base.parse_range_fragment(fragment, specification)
        member_path = root / "members" / specification["name"]
        base.atomic_bytes(member_path, decoded)
        selected.append(
            {
                **specification,
                "range_path": str(range_path.relative_to(root)),
                "member_path": str(member_path.relative_to(root)),
            }
        )

    manifest = {
        "acquisition_version": "gemstat-v3-seven-element-selective-zip-range-v1",
        "source_id": base.SOURCE_ID,
        "dataset_version": base.DATASET_VERSION,
        "dataset_doi": base.DATASET_DOI,
        "concept_doi": base.CONCEPT_DOI,
        "mode": mode,
        "archive": {
            "filename": base.ARCHIVE_NAME,
            "bytes": base.ARCHIVE_BYTES,
            "publisher_md5": base.ARCHIVE_MD5,
            "publisher_record_file_count": 1,
            "zip_member_count": 84,
            "url": base.ARCHIVE_URL,
        },
        "selected_elements": ["As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"],
        "excluded_parameter_codes": {
            "Cr-VI": "hexavalent chromium is a species, not interchangeable with total elemental Cr"
        },
        "selected_members": selected,
        "claim_boundary": (
            "Seven element files and four metadata/readme members are materialized from exact verified ZIP byte "
            "ranges. Dissolved, suspended, extractable and total fractions remain separate; Cr-VI is excluded "
            "from elemental Cr analysis but retained in the source file."
        ),
    }
    base.atomic_json(root / "acquisition-seven-elements.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--accept-cc-by", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.accept_cc_by:
        print("acquire_gemstat_multielement: --accept-cc-by is required", file=sys.stderr)
        return 2
    try:
        manifest = run(args.cache_dir, args.mode, args.timeout)
    except (base.AcquisitionError, OSError, ValueError) as exc:
        print(f"acquire_gemstat_multielement: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "selected_members": len(manifest["selected_members"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
