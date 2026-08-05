#!/usr/bin/env python3
"""Build a public E2 package from the frozen allowlist and reject private paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


class ExportError(ValueError):
    """The requested public export is unsafe or incomplete."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _copy_regular(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ExportError(f"public source must be a regular non-symlink file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def export(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    output = output.resolve(strict=False)
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ExportError("output directory must be outside the evaluation source tree")
    if output.exists() and any(output.iterdir()):
        raise ExportError("output directory must be absent or empty")
    contract = json.loads((root / "contracts" / "benchmark-execution-contract.json").read_text(encoding="utf-8"))
    allowlist = contract["isolation"]["public_export_allowlist"]
    output.mkdir(parents=True, exist_ok=True, mode=0o755)
    copied: list[Path] = []
    for relative in allowlist:
        source = root / relative
        if not source.exists():
            raise ExportError(f"allowlisted public source is missing: {relative}")
        if source.is_symlink():
            raise ExportError(f"allowlisted source is a symlink: {relative}")
        if source.is_file():
            destination = output / relative
            _copy_regular(source, destination)
            copied.append(destination)
            continue
        for item in sorted(source.rglob("*")):
            if item.is_symlink():
                raise ExportError(f"public tree contains a symlink: {item.relative_to(root)}")
            if item.is_file():
                destination = output / item.relative_to(root)
                _copy_regular(item, destination)
                copied.append(destination)
    forbidden = [path for path in output.rglob("*") if any(part in {"evaluator_private", "shadow", "final_holdout"} for part in path.relative_to(output).parts)]
    if forbidden:
        raise ExportError(f"private path entered public export: {forbidden[0]}")
    files = [
        {"path": path.relative_to(output).as_posix(), "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(copied)
    ]
    manifest = {
        "schema_version": "e2.public-export.v1",
        "benchmark_version": (root / "VERSION").read_text(encoding="utf-8").strip(),
        "e1_contract_sha256": contract["e1_contract_sha256"],
        "file_count": len(files),
        "files": files,
    }
    manifest_path = output / "PUBLIC_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = export(args.evaluation_root, args.output)
    except (ExportError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"artifact error: {exc}", file=sys.stderr)
        return 74
    print(json.dumps({"status": "PASS", "file_count": result["file_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
