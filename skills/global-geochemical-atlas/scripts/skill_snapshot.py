#!/usr/bin/env python3
"""Deterministically fingerprint the executable Skill tree.

The digest binds paths, sizes and file-content hashes. Interpreter caches are
excluded because importing a module may create them during an otherwise
read-only run; all authored instructions, scripts, references, assets and
fixtures remain in scope. Symlinks fail closed so a digest cannot silently
depend on content outside the submitted Skill directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SNAPSHOT_ALGORITHM = "skill-tree-sha256-v1"
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {"__pycache__", ".cache", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})


class SkillSnapshotError(RuntimeError):
    """Raised when the submitted Skill tree cannot be fingerprinted safely."""


@dataclass(frozen=True)
class SkillTreeEntry:
    """Content and filesystem identity captured for one submitted file."""

    relative_path: str
    size: int
    mtime_ns: int
    ctime_ns: int
    device: int
    inode: int
    mode: int
    content_sha256: str


@dataclass(frozen=True)
class SkillTreeCapture:
    """A publishable digest plus the private guard used at request completion."""

    snapshot: dict[str, Any]
    entries: tuple[SkillTreeEntry, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stat_identity(stat_result: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_mode,
    )


def _discover_files(root: Path) -> list[tuple[str, Path, os.stat_result]]:
    """Discover files with one scandir pass per directory.

    ``Path.rglob`` plus repeated ``is_*``/``stat`` calls is especially costly on
    network filesystems. ``scandir`` reuses directory-entry metadata while
    preserving the same deterministic path order and fail-closed symlink rule.
    """

    discovered: list[tuple[str, Path, os.stat_result]] = []
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                directory_entries = sorted(iterator, key=lambda item: item.name)
        except OSError as exc:
            relative = directory.relative_to(root).as_posix() or "."
            raise SkillSnapshotError(
                f"Skill snapshot cannot scan {relative}: {exc}"
            ) from exc
        child_directories: list[Path] = []
        for directory_entry in directory_entries:
            path = Path(directory_entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                if directory_entry.is_symlink():
                    raise SkillSnapshotError(
                        f"Skill snapshot refuses symbolic link: {relative}"
                    )
                if (
                    directory_entry.name in EXCLUDED_DIRECTORY_NAMES
                    and directory_entry.is_dir(follow_symlinks=False)
                ):
                    continue
                if directory_entry.is_dir(follow_symlinks=False):
                    child_directories.append(path)
                    continue
                if not directory_entry.is_file(follow_symlinks=False):
                    continue
                if path.suffix in EXCLUDED_SUFFIXES:
                    continue
                discovered.append(
                    (relative, path, directory_entry.stat(follow_symlinks=False))
                )
            except OSError as exc:
                raise SkillSnapshotError(
                    f"Skill snapshot cannot inspect {relative}: {exc}"
                ) from exc
        pending.extend(reversed(child_directories))
    return sorted(discovered, key=lambda item: item[0])


def _capture_entry(item: tuple[str, Path, os.stat_result]) -> SkillTreeEntry:
    relative, path, stat_before = item
    try:
        content_sha256 = sha256_file(path)
        stat_after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise SkillSnapshotError(
            f"Skill snapshot cannot read {relative}: {exc}"
        ) from exc
    if path.is_symlink() or _stat_identity(stat_before) != _stat_identity(stat_after):
        raise SkillSnapshotError(
            f"Skill file changed while its content was being captured: {relative}"
        )
    return SkillTreeEntry(
        relative_path=relative,
        size=stat_after.st_size,
        mtime_ns=stat_after.st_mtime_ns,
        ctime_ns=stat_after.st_ctime_ns,
        device=stat_after.st_dev,
        inode=stat_after.st_ino,
        mode=stat_after.st_mode,
        content_sha256=content_sha256,
    )


def capture_skill_tree(skill_dir: Path) -> SkillTreeCapture:
    root = skill_dir.resolve()
    if not root.is_dir():
        raise SkillSnapshotError(f"Skill directory does not exist: {skill_dir}")
    discovered = _discover_files(root)
    max_workers = min(16, max(1, len(discovered)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        entries = tuple(executor.map(_capture_entry, discovered))

    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry.size).encode("ascii"))
        digest.update(b"\0")
        digest.update(entry.content_sha256.encode("ascii"))
        digest.update(b"\n")
    return SkillTreeCapture(
        snapshot={
            "algorithm": SNAPSHOT_ALGORITHM,
            "sha256": digest.hexdigest(),
            "file_count": len(entries),
            "total_bytes": sum(item.size for item in entries),
            "excluded_runtime_paths": sorted(EXCLUDED_DIRECTORY_NAMES),
            "excluded_runtime_suffixes": sorted(EXCLUDED_SUFFIXES),
        },
        entries=entries,
    )


def fingerprint_skill_tree(skill_dir: Path) -> dict[str, Any]:
    """Return the deterministic publishable digest for the whole Skill tree."""

    return capture_skill_tree(skill_dir).snapshot


def verify_skill_tree_unchanged(
    skill_dir: Path, capture: SkillTreeCapture
) -> dict[str, Any]:
    """Verify that no submitted path or file identity changed after capture.

    The initial capture already binds every file's bytes. At request completion,
    checking the full path set plus inode, size, mtime, ctime and mode detects
    additions, removals, replacements and in-place edits without rereading every
    byte from a remote filesystem.
    """

    root = skill_dir.resolve()
    discovered = _discover_files(root)
    current = {
        relative: _stat_identity(stat_result)
        for relative, _path, stat_result in discovered
    }
    expected = {
        entry.relative_path: (
            entry.size,
            entry.mtime_ns,
            entry.ctime_ns,
            entry.device,
            entry.inode,
            entry.mode,
        )
        for entry in capture.entries
    }
    changed_paths = sorted(
        relative
        for relative in set(current) | set(expected)
        if current.get(relative) != expected.get(relative)
    )
    return {
        "stable": not changed_paths,
        "snapshot": dict(capture.snapshot),
        "changed_paths": changed_paths,
        "verification": "path-and-stat-identity-v1",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-dir", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot = fingerprint_skill_tree(args.skill_dir)
    except (OSError, SkillSnapshotError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps({"status": "PASS", **snapshot}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
