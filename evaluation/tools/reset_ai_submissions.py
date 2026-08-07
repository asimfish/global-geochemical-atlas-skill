#!/usr/bin/env python3
"""Reset Q01-Q24 AI submissions while preserving empty Git placeholders."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


VISIBLE_QUESTIONS = tuple(f"Q{number:02d}" for number in range(1, 25))


class ResetError(RuntimeError):
    """Raised when the submissions tree is unsafe to reset."""


def reset_submissions(bundle_root: Path, *, dry_run: bool = False) -> dict[str, object]:
    """Delete submitted answers and leave only an empty .gitkeep per question."""

    if bundle_root.is_symlink():
        raise ResetError(f"bundle root must not be a symlink: {bundle_root}")
    bundle_root = bundle_root.resolve()
    manifest_path = bundle_root / "BUNDLE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResetError(f"invalid bundle manifest: {manifest_path}: {exc}") from exc
    if manifest.get("bundle_type") != "ai-visible-q01-q24":
        raise ResetError("refusing to reset an unexpected bundle_type")
    if manifest.get("questions") != list(VISIBLE_QUESTIONS):
        raise ResetError("refusing to reset a bundle whose question set is not Q01-Q24")

    submissions_root = bundle_root / "submissions"
    if submissions_root.is_symlink() or not submissions_root.is_dir():
        raise ResetError(f"unsafe or missing submissions directory: {submissions_root}")
    question_roots = [submissions_root / question for question in VISIBLE_QUESTIONS]
    for question_root in question_roots:
        if question_root.is_symlink() or not question_root.is_dir():
            raise ResetError(f"unsafe or missing submission directory: {question_root}")
        placeholder = question_root / ".gitkeep"
        if placeholder.is_symlink() or (placeholder.exists() and not placeholder.is_file()):
            raise ResetError(f"unsafe .gitkeep placeholder: {placeholder}")

    removed_entries: list[str] = []
    for question_root in question_roots:
        for path in question_root.iterdir():
            if path.name == ".gitkeep":
                continue
            removed_entries.append(path.relative_to(bundle_root).as_posix())
            if dry_run:
                continue
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
        if not dry_run:
            (question_root / ".gitkeep").write_bytes(b"")

    return {
        "status": "PASS",
        "bundle_root": str(bundle_root),
        "questions": len(VISIBLE_QUESTIONS),
        "dry_run": dry_run,
        "removed_entries": len(removed_entries),
        "removed_paths": removed_entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "ai_visible_public",
        help="Q01-Q24 AI-visible bundle (default: evaluation/ai_visible_public)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report answer entries without deleting them",
    )
    args = parser.parse_args()

    try:
        summary = reset_submissions(args.bundle_root, dry_run=args.dry_run)
    except ResetError as exc:
        parser.exit(1, f"reset error: {exc}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
