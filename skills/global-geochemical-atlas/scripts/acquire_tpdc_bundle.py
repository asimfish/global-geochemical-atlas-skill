#!/usr/bin/env python3
"""Acquire and verify the registered TPDC China mountain-soil POST bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REGISTRY_PATH = SKILL_DIR / "assets" / "source_manifest.json"
SOURCE_ID = "tpdc-china-mountain-soil"
MAX_BUNDLE_BYTES = 5_000_000
MAX_MEMBERS = 100
MAX_EXTRACTED_BYTES = 10_000_000


class TpdcAcquisitionError(RuntimeError):
    """Raised when the official bundle differs from the registered snapshot."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_entry() -> dict[str, Any]:
    try:
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        entry = registry["sources"][SOURCE_ID]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TpdcAcquisitionError("TPDC source registry is unreadable") from exc
    download = entry.get("download")
    if (
        not isinstance(download, Mapping)
        or download.get("mode") != "official-post-bundle-extracted-members"
        or not isinstance(download.get("files"), list)
    ):
        raise TpdcAcquisitionError("TPDC download registry contract is invalid")
    return dict(entry)


def fetch_bundle(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "User-Agent": "global-geochemical-atlas-skill/1",
            "Accept": "application/zip,application/octet-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_BUNDLE_BYTES:
                raise TpdcAcquisitionError(
                    "TPDC response exceeds the registered defensive byte ceiling"
                )
            value = response.read(MAX_BUNDLE_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise TpdcAcquisitionError(f"TPDC POST bundle download failed: {exc}") from exc
    if len(value) > MAX_BUNDLE_BYTES:
        raise TpdcAcquisitionError(
            "TPDC response exceeds the registered defensive byte ceiling"
        )
    return value


def verified_members(bundle: bytes, download: Mapping[str, Any]) -> dict[str, bytes]:
    expected_files = {
        str(item["filename"]): item
        for item in download["files"]
        if isinstance(item, Mapping)
    }
    try:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS:
                raise TpdcAcquisitionError("TPDC ZIP has too many members")
            if sum(item.file_size for item in members) > MAX_EXTRACTED_BYTES:
                raise TpdcAcquisitionError(
                    "TPDC ZIP exceeds the extraction byte ceiling"
                )
            matched: dict[str, zipfile.ZipInfo] = {}
            for member in members:
                pure = PurePosixPath(member.filename)
                if (
                    pure.is_absolute()
                    or ".." in pure.parts
                    or re.match(r"^[A-Za-z]:", member.filename)
                ):
                    raise TpdcAcquisitionError(
                        f"TPDC ZIP contains an unsafe member path: {member.filename!r}"
                    )
                basename = pure.name
                if basename not in expected_files or member.is_dir():
                    continue
                if basename in matched:
                    raise TpdcAcquisitionError(
                        f"TPDC ZIP duplicates a registered member: {basename}"
                    )
                matched[basename] = member
            missing = sorted(set(expected_files) - set(matched))
            if missing:
                raise TpdcAcquisitionError(
                    f"TPDC ZIP lacks registered members: {missing}"
                )
            output: dict[str, bytes] = {}
            for filename, specification in expected_files.items():
                value = archive.read(matched[filename])
                if len(value) != int(specification["bytes"]):
                    raise TpdcAcquisitionError(
                        f"TPDC member byte count changed: {filename}"
                    )
                if sha256_bytes(value) != specification["expected_sha256"]:
                    raise TpdcAcquisitionError(
                        f"TPDC member SHA-256 changed: {filename}"
                    )
                output[filename] = value
            return output
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        if isinstance(exc, TpdcAcquisitionError):
            raise
        raise TpdcAcquisitionError("TPDC response is not the registered ZIP") from exc


def cached_members_valid(root: Path, download: Mapping[str, Any]) -> bool:
    for item in download["files"]:
        path = root / item["filename"]
        try:
            value = path.read_bytes()
        except OSError:
            return False
        if (
            len(value) != int(item["bytes"])
            or sha256_bytes(value) != item["expected_sha256"]
        ):
            return False
    return True


def run(cache_dir: Path, mode: str, timeout: float) -> dict[str, Any]:
    entry = load_entry()
    download = entry["download"]
    root = cache_dir / SOURCE_ID / entry["dataset_version"]
    accessed_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    retrieved_at: str | None = None
    if cached_members_valid(root, download):
        status = "verified_cache"
        try:
            previous = json.loads(
                (root / "tpdc-acquisition.json").read_text(encoding="utf-8")
            )
            if isinstance(previous, Mapping) and isinstance(
                previous.get("retrieved_at"), str
            ):
                retrieved_at = str(previous["retrieved_at"])
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    else:
        if mode != "online":
            raise TpdcAcquisitionError(f"TPDC verified cache is incomplete at {root}")
        bundle = fetch_bundle(str(download["bundle_url"]), timeout)
        if len(bundle) != int(download["bundle_bytes"]):
            raise TpdcAcquisitionError("TPDC bundle byte count changed")
        if sha256_bytes(bundle) != download["bundle_sha256"]:
            raise TpdcAcquisitionError("TPDC bundle SHA-256 changed")
        members = verified_members(bundle, download)
        atomic_bytes(root / "tpdc-official-bundle.zip", bundle)
        for filename, value in members.items():
            atomic_bytes(root / filename, value)
        status = "downloaded_and_verified"
        retrieved_at = accessed_at
    manifest = {
        "acquisition_version": "tpdc-official-post-bundle-v1",
        "source_id": SOURCE_ID,
        "dataset_version": entry["dataset_version"],
        "mode": mode,
        "status": status,
        "accessed_at": accessed_at,
        "retrieved_at": retrieved_at,
        "bundle": {
            "url": download["bundle_url"],
            "bytes": download["bundle_bytes"],
            "sha256": download["bundle_sha256"],
        },
        "members": [
            {
                "filename": item["filename"],
                "bytes": item["bytes"],
                "sha256": item["expected_sha256"],
            }
            for item in download["files"]
        ],
    }
    atomic_bytes(
        root / "tpdc-acquisition.json",
        (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run(args.cache_dir, args.mode, args.timeout)
    except (TpdcAcquisitionError, OSError, ValueError) as exc:
        print(f"acquire_tpdc_bundle: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
