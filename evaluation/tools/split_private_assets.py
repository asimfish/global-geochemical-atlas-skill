#!/usr/bin/env python3
"""Move legacy hidden assets out of the public/E1 workspace without deleting them."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


class SplitError(ValueError):
    """The requested split would overwrite or fail to isolate private data."""


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _write_inventory(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def split(evaluation_root: Path, private_root: Path, e1_workspace: Path) -> dict[str, object]:
    evaluation_root = evaluation_root.resolve(strict=True)
    e1_workspace = e1_workspace.resolve(strict=True)
    private_root = private_root.absolute()
    source = evaluation_root / "evaluator_private"
    if not source.is_dir() or source.is_symlink():
        raise SplitError("evaluation/evaluator_private must be an existing real directory")
    if private_root.exists():
        raise SplitError("private destination already exists; refusing to overwrite")
    if _inside(private_root, evaluation_root) or _inside(private_root, e1_workspace):
        raise SplitError("private destination must be outside public evaluation and E1 workspace")
    inventory_path = evaluation_root / "task_inventory.csv"
    with inventory_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    public_rows = [row for row in rows if row.get("split") == "public"]
    private_rows = [row for row in rows if row.get("split") in {"shadow", "final_holdout"}]
    if len(public_rows) != 8 or len(private_rows) != 16:
        raise SplitError("inventory must contain 8 public and 16 private rows before splitting")
    private_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(private_root))
    private_root.chmod(0o700)
    for directory in private_root.rglob("*"):
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o700)
    _write_inventory(inventory_path, fieldnames, public_rows)
    _write_inventory(private_root / "task_inventory_private.csv", fieldnames, private_rows)
    status = {
        "schema_version": "e2.private-assets.v1",
        "benchmark_version": "6.0.0-draft.1",
        "status": "DEVELOPMENT_ONLY_COMPROMISED_LEGACY",
        "formal_final_eligible": False,
        "reason": "These tasks existed in public Git history and must be rotated before formal Final.",
        "shadow_tasks": 8,
        "final_holdout_tasks": 8,
    }
    (private_root / "PRIVATE_STATUS.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "public_tasks": 8, "private_tasks": 16, "private_root": str(private_root)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--e1-workspace", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = split(args.evaluation_root, args.private_root, args.e1_workspace)
    except (SplitError, OSError, csv.Error) as exc:
        print(f"environment error: {exc}", file=sys.stderr)
        return 73
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
