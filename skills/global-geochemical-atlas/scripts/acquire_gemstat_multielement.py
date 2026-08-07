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
        "compressed_bytes": 2_295_918,
        "uncompressed_bytes": 34_359_149,
    },
    {
        "name": "Copper.csv",
        "range_start": 24_122_334,
        "range_end": 26_169_314,
        "compressed_bytes": 2_046_941,
        "uncompressed_bytes": 28_448_872,
    },
    {
        "name": "Lead.csv",
        "range_start": 47_619_799,
        "range_end": 50_275_481,
        "compressed_bytes": 2_655_645,
        "uncompressed_bytes": 40_765_015,
    },
    {
        "name": "Mercury.csv",
        "range_start": 54_591_798,
        "range_end": 56_488_526,
        "compressed_bytes": 1_896_688,
        "uncompressed_bytes": 31_175_171,
    },
    {
        "name": "Nickel.csv",
        "range_start": 57_019_516,
        "range_end": 59_767_178,
        "compressed_bytes": 2_747_623,
        "uncompressed_bytes": 39_456_553,
    },
    {
        "name": "Zinc.csv",
        "range_start": 199_286_587,
        "range_end": 201_270_727,
        "compressed_bytes": 1_984_103,
        "uncompressed_bytes": 26_785_044,
    },
)

MEMBERS = ELEMENT_MEMBERS + base.MEMBERS[1:]


def registered_members() -> tuple[dict[str, Any], ...]:
    """Bind range and decoded payload hashes to the checked source registry."""

    registry_path = (
        Path(__file__).resolve().parents[1] / "assets" / "source_manifest.json"
    )
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    configured = {
        item["filename"]: item
        for item in registry["sources"][base.SOURCE_ID]["download"]["selected_members"]
    }
    output = []
    for specification in MEMBERS:
        registered = configured.get(specification["name"])
        if not isinstance(registered, dict):
            raise base.AcquisitionError(
                f"GEMStat member is not registered: {specification['name']}"
            )
        output.append(
            {
                **specification,
                "range_sha256": registered["range_sha256"],
                "sha256": registered["expected_sha256"],
            }
        )
    return tuple(output)


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
        raise base.AcquisitionError(
            "cached Zenodo metadata is missing or invalid"
        ) from exc
    base.validate_metadata(metadata)

    selected: list[dict[str, Any]] = []
    for specification in registered_members():
        range_path = root / "ranges" / f"{specification['name']}.range"
        if mode == "online":
            fragment, decoded = base.fetch_verified_range(specification, timeout)
            base.atomic_bytes(range_path, fragment)
        else:
            try:
                fragment = range_path.read_bytes()
            except OSError as exc:
                raise base.AcquisitionError(
                    f"cached range is missing: {range_path}"
                ) from exc
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
            "Seven element files and four metadata/readme members are materialized from exact ZIP byte "
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
        print(
            "acquire_gemstat_multielement: --accept-cc-by is required", file=sys.stderr
        )
        return 2
    try:
        manifest = run(args.cache_dir, args.mode, args.timeout)
    except (base.AcquisitionError, OSError, ValueError) as exc:
        print(f"acquire_gemstat_multielement: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": "PASS", "selected_members": len(manifest["selected_members"])},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
