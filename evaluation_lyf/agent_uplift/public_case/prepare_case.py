#!/usr/bin/env python3
"""Download the hash-pinned public uplift case."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    contract_path = Path(__file__).with_name("sources.json")
    discovery_contract_path = Path(__file__).with_name("discovery_contract.json")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    discovery_contract = json.loads(discovery_contract_path.read_text(encoding="utf-8"))
    manifest = {
        "case_version": contract["case_version"],
        "resource_semantics": contract["resource_semantics"],
        "anchor_contract_sha256": hashlib.sha256(
            contract_path.read_bytes()
        ).hexdigest(),
        "discovery_contract_sha256": hashlib.sha256(
            discovery_contract_path.read_bytes()
        ).hexdigest(),
        "discovery_contract_version": discovery_contract["schema_version"],
        "resources": [],
    }
    for item in contract["resources"]:
        destination = args.output_dir / item["file"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file():
            request = urllib.request.Request(
                item["url"], headers={"User-Agent": "geochem-qwen-uplift/3.0"}
            )
            last_error: Exception | None = None
            for attempt in range(3):
                try:
                    with (
                        urllib.request.urlopen(request, timeout=120) as response,
                        tempfile.NamedTemporaryFile(
                            "wb", dir=destination.parent, delete=False
                        ) as handle,
                    ):
                        temporary = Path(handle.name)
                        while chunk := response.read(1024 * 1024):
                            handle.write(chunk)
                    os.replace(temporary, destination)
                    last_error = None
                    break
                except (TimeoutError, urllib.error.URLError) as exc:
                    last_error = exc
                    if attempt < 2:
                        time.sleep(2**attempt)
            if last_error is not None:
                parser.error(
                    f"download failed after 3 attempts for {item['id']}: {last_error}"
                )
        actual = {"bytes": destination.stat().st_size, "sha256": sha256(destination)}
        if actual != {"bytes": item["bytes"], "sha256": item["sha256"]}:
            parser.error(f"fixture mismatch: {destination}")
        # Preserve the public authority contract beside the verified local bytes so
        # the scorer can perform exact record-level provenance checks offline.
        manifest["resources"].append({**item, **actual})
    (args.output_dir / "case_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
