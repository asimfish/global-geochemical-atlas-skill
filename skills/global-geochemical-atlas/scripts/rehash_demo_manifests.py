#!/usr/bin/env python3
"""Bind checked-in D1 demo outputs to SHA-256 without claiming upstream checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_ROOT = SKILL_DIR / "fixtures" / "source-demos"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: object) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def update(root: Path, *, check: bool) -> dict[str, int | str]:
    changed = 0
    checked = 0
    for manifest_path in sorted(root.glob("*/run_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        outputs = manifest.get("outputs")
        if not isinstance(outputs, list):
            raise ValueError(f"outputs are missing: {manifest_path}")
        for item in outputs:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError(f"invalid output entry: {manifest_path}")
            output_path = manifest_path.parent / item["path"]
            if not output_path.is_file():
                raise ValueError(f"demo output is missing: {output_path}")
            expected = {
                "path": item["path"],
                "bytes": output_path.stat().st_size,
                "sha256": sha256_file(output_path),
            }
            if item != expected:
                item.clear()
                item.update(expected)
                changed += 1
        checked += 1
        rendered = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if check:
            if manifest_path.read_text(encoding="utf-8") != rendered:
                raise ValueError(f"demo manifest is not SHA-256 bound: {manifest_path}")
        else:
            atomic_json(manifest_path, manifest)
    return {
        "status": "PASS",
        "manifest_count": checked,
        "updated_output_count": changed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = update(args.root, check=args.check)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
