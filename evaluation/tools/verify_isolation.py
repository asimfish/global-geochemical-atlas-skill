#!/usr/bin/env python3
"""Verify that the tested AI bundle is the only candidate-visible filesystem root."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from export_ai_bundle import BundleError, validate_bundle


class IsolationError(ValueError):
    """The repo-local evaluator sources and AI-visible projection are not isolated."""


def verify(evaluation_root: Path, bundle_root: Path | None = None) -> dict[str, object]:
    evaluation_root = evaluation_root.resolve(strict=True)
    expected_bundle = (evaluation_root / "ai_visible_public").resolve(strict=True)
    selected_bundle = (bundle_root or expected_bundle).resolve(strict=True)
    if selected_bundle != expected_bundle:
        raise IsolationError("tested AI bundle must be evaluation/ai_visible_public")

    evaluator_root = evaluation_root / "evaluator_private"
    if evaluator_root.is_symlink() or not evaluator_root.is_dir():
        raise IsolationError("evaluation/evaluator_private must be a real repo-local directory")
    expected_sources = {
        "shadow": {f"Q{number:02d}" for number in range(9, 17)},
        "final_holdout": {f"Q{number:02d}" for number in range(17, 25)},
    }
    for split, expected in expected_sources.items():
        split_root = evaluator_root / split
        actual = {path.name for path in split_root.glob("Q[0-9][0-9]") if path.is_dir()}
        if actual != expected:
            raise IsolationError(f"{split} evaluator source mismatch: {sorted(actual)}")

    try:
        bundle_summary = validate_bundle(selected_bundle)
    except BundleError as exc:
        raise IsolationError(str(exc)) from exc

    return {
        "schema_version": "e2.ai-visibility-audit.v2",
        "status": "PASS",
        "evaluation_root": str(evaluation_root),
        "candidate_visible_root": str(selected_bundle),
        "evaluator_source_root": str(evaluator_root.resolve()),
        "candidate_visible_questions": bundle_summary["questions"],
        "candidate_submission_files": bundle_summary["submission_files"],
        "forbidden_evaluator_material_in_bundle": False,
        "formal_final_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-root", required=True, type=Path)
    parser.add_argument("--bundle-root", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evaluation_root, args.bundle_root)
    except (IsolationError, OSError) as exc:
        print(f"environment error: {exc}", file=sys.stderr)
        return 73
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
