#!/usr/bin/env python3
"""Fail closed unless hidden tasks are physically outside the E1 workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class IsolationError(ValueError):
    """Hidden assets are reachable from a public or E1-owned tree."""


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def verify(evaluation_root: Path, private_root: Path, e1_workspace: Path) -> dict[str, object]:
    evaluation_root = evaluation_root.resolve(strict=True)
    private_root = private_root.resolve(strict=True)
    e1_workspace = e1_workspace.resolve(strict=True)
    if _inside(private_root, evaluation_root) or _inside(private_root, e1_workspace):
        raise IsolationError("private root must be outside both the public evaluation repository and E1 workspace")
    if (evaluation_root / "evaluator_private").exists():
        raise IsolationError("public evaluation repository still contains evaluator_private")
    if private_root.is_symlink() or not private_root.is_dir():
        raise IsolationError("private root must be a real directory")
    if private_root.stat().st_mode & 0o077:
        raise IsolationError("private root must not grant group/other permissions")
    for split in ("shadow", "final_holdout"):
        split_root = private_root / split
        tasks = sorted(path.name for path in split_root.glob("Q[0-9][0-9]") if path.is_dir())
        if len(tasks) != 8:
            raise IsolationError(f"private {split} must contain exactly 8 task directories")
    return {
        "schema_version": "e2.isolation-audit.v1",
        "status": "PASS",
        "evaluation_root": str(evaluation_root),
        "private_root": str(private_root),
        "e1_workspace": str(e1_workspace),
        "private_mode": oct(private_root.stat().st_mode & 0o777),
        "current_v5_holdout_usable_for_formal_final": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--e1-workspace", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evaluation_root, args.private_root, args.e1_workspace)
    except (IsolationError, OSError) as exc:
        print(f"environment error: {exc}", file=sys.stderr)
        return 73
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
