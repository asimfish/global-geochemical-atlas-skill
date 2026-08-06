#!/usr/bin/env python3
"""Download and verify the official completion fixtures declared in the contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from lab_common import CONTRACT_ROOT, LAB_ROOT, atomic_write_json, sha256_file

CONTRACT = CONTRACT_ROOT / "completion-sources.json"
DEFAULT_OUTPUT = LAB_ROOT / "completion-data" / "fixtures" / "raw"
USER_AGENT = "global-geochemical-atlas-stage-benchmark/2.0 (+research reproducibility)"


class FixtureError(RuntimeError):
    pass


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=120) as response, tempfile.NamedTemporaryFile(
        "wb", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)
    os.replace(temporary, destination)


def validate(path: Path, resource: dict[str, object]) -> None:
    if not path.is_file():
        raise FixtureError(f"missing fixture: {path}")
    actual_size = path.stat().st_size
    actual_hash = sha256_file(path)
    if actual_size != int(resource["bytes"]):
        raise FixtureError(f"size mismatch for {path.name}: {actual_size} != {resource['bytes']}")
    if actual_hash != resource["sha256"]:
        raise FixtureError(f"sha256 mismatch for {path.name}: {actual_hash}")


def build(output_dir: Path, refresh: bool) -> dict[str, object]:
    contract_bytes = CONTRACT.read_bytes()
    contract = json.loads(contract_bytes)
    entries: list[dict[str, object]] = []
    for resource in contract["resources"]:
        path = output_dir / resource["local_file"]
        if refresh or not path.is_file():
            download(str(resource["url"]), path)
        validate(path, resource)
        entries.append(
            {
                "id": resource["id"],
                "path": str(resource["local_file"]),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "landing_page": resource["landing_page"],
            }
        )
    manifest = {
        "manifest_version": "stage-completion-fixtures-v2",
        "status": "verified",
        "contract": CONTRACT.name,
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "resource_count": len(entries),
        "resources": entries,
    }
    atomic_write_json(output_dir / "source_manifest.json", manifest)
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--refresh", action="store_true", help="Redownload every resource before verification")
    args = parser.parse_args(argv)
    try:
        manifest = build(args.output_dir, args.refresh)
    except (OSError, ValueError, json.JSONDecodeError, FixtureError) as exc:
        parser.error(str(exc))
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
