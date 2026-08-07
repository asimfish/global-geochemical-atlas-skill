#!/usr/bin/env python3
"""Fetch and verify the frozen public-domain real-data holdout.

The command is deliberately standard-library-only and fail-closed: a changed
upstream byte stream is reported as source drift and never replaces the pinned
fixture.  Offline mode performs the same structural and hash checks without
opening the network.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_common import (
    CONTRACT_ROOT,
    LAB_ROOT,
    atomic_write_json,
    load_json,
    sha256_file,
)

SOURCE_CONTRACT = CONTRACT_ROOT / "real-sources.json"
DEFAULT_FIXTURE_DIR = LAB_ROOT / "real-data" / "fixtures" / "raw"
USER_AGENT = "AI4S-D2-real-holdout/1.0 (+offline reproducibility test)"


class FixtureError(ValueError):
    """Raised when a source is unsafe, unavailable, structurally invalid, or has drifted."""


def resource_path(fixture_dir: Path, resource: Mapping[str, Any]) -> Path:
    name = str(resource.get("local_file", ""))
    if not name or Path(name).name != name:
        raise FixtureError(f"unsafe local_file in source contract: {name!r}")
    return fixture_dir / name


def validate_url(value: Any) -> str:
    url = str(value or "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise FixtureError(f"only absolute HTTPS source URLs are accepted: {url!r}")
    return url


def nonempty_csv_record_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for row in reader if any(cell.strip() for cell in row))


def ds801_record_count(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        lines = handle.readlines()
    try:
        header_index = next(
            index for index, line in enumerate(lines) if line.startswith("Top5_LabID\t")
        )
    except StopIteration as exc:
        raise FixtureError(f"DS801 table header not found: {path}") from exc
    # One unit row follows the header. Empty lines after that are ignored.
    return sum(1 for line in lines[header_index + 2 :] if line.strip())


def validate_resource(
    path: Path, resource: Mapping[str, Any], max_bytes: int
) -> dict[str, Any]:
    if not path.is_file():
        raise FixtureError(f"fixture is missing: {path}")
    actual_bytes = path.stat().st_size
    expected_bytes = int(resource["bytes"])
    if actual_bytes > max_bytes:
        raise FixtureError(
            f"fixture exceeds --max-bytes-per-file ({actual_bytes} > {max_bytes}): {path.name}"
        )
    if actual_bytes != expected_bytes:
        raise FixtureError(
            f"byte-size drift for {path.name}: expected {expected_bytes}, got {actual_bytes}"
        )
    actual_sha256 = sha256_file(path)
    expected_sha256 = str(resource["sha256"]).lower()
    if actual_sha256 != expected_sha256:
        raise FixtureError(
            f"SHA-256 drift for {path.name}: expected {expected_sha256}, got {actual_sha256}"
        )

    raw = path.read_bytes()
    for token in resource.get("required_tokens", []):
        if str(token).encode("ascii") not in raw:
            raise FixtureError(f"required token {token!r} missing from {path.name}")

    record_count: int | None = None
    data_format = resource.get("format")
    if data_format == "csv":
        record_count = nonempty_csv_record_count(path)
    elif data_format == "tsv_with_preamble":
        record_count = ds801_record_count(path)
    minimum_records = resource.get("minimum_records")
    if minimum_records is not None and (
        record_count is None or record_count < int(minimum_records)
    ):
        raise FixtureError(
            f"too few records in {path.name}: expected at least {minimum_records}, got {record_count}"
        )
    return {
        "id": resource["id"],
        "dataset_id": resource["dataset_id"],
        "role": resource["role"],
        "path": path.name,
        "url": resource["url"],
        "landing_page": resource["landing_page"],
        "bytes": actual_bytes,
        "sha256": actual_sha256,
        "record_count": record_count,
        "verification": "pinned_sha256_size_structure",
    }


def download_to_temporary(
    url: str,
    fixture_dir: Path,
    timeout_seconds: float,
    max_bytes: int,
    retries: int,
) -> Path:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        temporary_path: Path | None = None
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                final_url = response.geturl()
                if urllib.parse.urlsplit(final_url).scheme != "https":
                    raise FixtureError(
                        f"source redirected away from HTTPS: {final_url}"
                    )
                content_length = response.headers.get("Content-Length")
                if content_length is not None and int(content_length) > max_bytes:
                    raise FixtureError(
                        f"declared response exceeds --max-bytes-per-file ({content_length} > {max_bytes})"
                    )
                with tempfile.NamedTemporaryFile(
                    "wb", dir=fixture_dir, delete=False
                ) as handle:
                    temporary_path = Path(handle.name)
                    received = 0
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > max_bytes:
                            raise FixtureError(
                                f"response exceeds --max-bytes-per-file ({received} > {max_bytes})"
                            )
                        handle.write(chunk)
            if temporary_path is None:
                raise FixtureError(f"download produced no temporary file: {url}")
            return temporary_path
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = exc
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
            if attempt < retries:
                time.sleep(min(2.0, 0.25 * (2**attempt)))
    raise FixtureError(
        f"download failed after {retries + 1} attempts: {url}: {last_error}"
    )


def materialize_fixtures(
    fixture_dir: Path,
    *,
    offline: bool,
    refresh: bool,
    timeout_seconds: float,
    max_bytes_per_file: int,
    retries: int,
) -> dict[str, Any]:
    contract = load_json(SOURCE_CONTRACT)
    resources = contract.get("resources")
    if not isinstance(resources, list) or not resources:
        raise FixtureError("real source contract has no resources")
    fixture_dir.mkdir(parents=True, exist_ok=True)
    verified: list[dict[str, Any]] = []
    total_bytes = 0
    downloaded_any = False

    for raw_resource in resources:
        if not isinstance(raw_resource, dict):
            raise FixtureError("each source resource must be an object")
        resource = raw_resource
        url = validate_url(resource.get("url"))
        destination = resource_path(fixture_dir, resource)
        should_download = not destination.is_file() or refresh
        if offline and should_download:
            raise FixtureError(
                f"offline mode cannot supply missing or refreshed fixture: {destination.name}"
            )
        if should_download:
            downloaded_any = True
            temporary = download_to_temporary(
                url,
                fixture_dir,
                timeout_seconds,
                max_bytes_per_file,
                retries,
            )
            try:
                # Validate before replacement so upstream drift cannot corrupt the frozen holdout.
                validate_resource(temporary, resource, max_bytes_per_file)
                os.replace(temporary, destination)
            finally:
                if temporary.exists():
                    temporary.unlink()
        entry = validate_resource(destination, resource, max_bytes_per_file)
        total_bytes += int(entry["bytes"])
        verified.append(entry)

    manifest = {
        "manifest_version": "d2-real-fixture-manifest-v2",
        "source_contract": SOURCE_CONTRACT.name,
        "source_contract_sha256": sha256_file(SOURCE_CONTRACT),
        "frozen_on": contract["frozen_on"],
        "offline": offline,
        "network_used": downloaded_any,
        "resource_count": len(verified),
        "total_bytes": total_bytes,
        "resources": verified,
        "datasets": contract["datasets"],
        "scientific_scope": contract["purpose"],
    }
    manifest_path = fixture_dir / "source_manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {"manifest": manifest_path, "payload": manifest}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch or offline-verify the pinned real geochemistry fixtures."
    )
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Open no network connections; require pinned files",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Redownload every file and reject any byte drift",
    )
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--max-bytes-per-file", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--retries", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.offline and args.refresh:
        parser.error("--offline and --refresh are mutually exclusive")
    if (
        args.timeout_seconds <= 0
        or args.max_bytes_per_file <= 0
        or not 0 <= args.retries <= 5
    ):
        parser.error(
            "timeout/max-bytes must be positive and retries must be between 0 and 5"
        )
    try:
        result = materialize_fixtures(
            args.fixture_dir,
            offline=args.offline,
            refresh=args.refresh,
            timeout_seconds=args.timeout_seconds,
            max_bytes_per_file=args.max_bytes_per_file,
            retries=args.retries,
        )
    except (FixtureError, OSError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": "verified",
                "manifest": str(result["manifest"]),
                "resource_count": result["payload"]["resource_count"],
                "total_bytes": result["payload"]["total_bytes"],
                "offline": args.offline,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
