"""Shared deterministic helpers for the Docker evaluation runner."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


IGNORED_TREE_PARTS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache", ".venv", "node_modules"}
IGNORED_TREE_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def hash_records(records: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(records):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def hash_tree(root: Path) -> str:
    return hash_records(
        (path.relative_to(root).as_posix(), sha256_file(path))
        for path in root.rglob("*")
        if (
            path.is_file()
            and not path.is_symlink()
            and not any(part in IGNORED_TREE_PARTS for part in path.relative_to(root).parts)
            and path.suffix.casefold() not in IGNORED_TREE_SUFFIXES
        )
    )


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
