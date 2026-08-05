#!/usr/bin/env python3
"""Create a deterministic SHA-256 manifest for a benchmark freeze candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


EXCLUDED_PARTS = {"__pycache__", ".git"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label", default="freeze-candidate")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()

    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if output == path.resolve() or any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith("results/raw/") or relative.startswith("results/llm_grader_prompts/"):
            continue
        data = path.read_bytes()
        entries.append({"path": relative, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest = {
        "label": args.label,
        "benchmark_version": (root / "VERSION").read_text(encoding="utf-8").strip(),
        "file_count": len(entries),
        "content_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": entries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("label", "benchmark_version", "file_count", "content_manifest_sha256")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
