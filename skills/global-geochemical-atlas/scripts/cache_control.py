#!/usr/bin/env python3
"""Inspect or explicitly delete one versioned D1 source cache."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class CacheControlError(ValueError):
    """Raised when a cache target is ambiguous or unsafe."""


def stable_request_cache_key(source_id: str, dataset_version: str, request: Mapping[str, Any]) -> str:
    """Hash source, immutable version and canonical request parameters."""

    if not source_id.strip() or not dataset_version.strip():
        raise CacheControlError("source_id and dataset_version are required")
    payload = {
        "cache_key_version": "d1-request-cache-key-v1",
        "dataset_version": dataset_version,
        "request": request,
        "source_id": source_id,
    }
    try:
        canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise CacheControlError(f"request is not canonical JSON: {exc}") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target(cache_dir: Path, source_id: str, dataset_version: str) -> Path:
    if not SAFE_COMPONENT.fullmatch(source_id) or not SAFE_COMPONENT.fullmatch(dataset_version):
        raise CacheControlError("source_id and dataset_version must be explicit safe path components")
    root = cache_dir.resolve()
    source_root = root / source_id
    target = source_root / dataset_version
    if source_root.is_symlink() or target.is_symlink():
        raise CacheControlError("source and version cache targets must not be symlinks")
    resolved_target = target.resolve(strict=False)
    try:
        resolved_target.relative_to(root)
    except ValueError as exc:
        raise CacheControlError("cache target escaped the requested root") from exc
    if target.parent.parent != root:
        raise CacheControlError("cache target escaped the requested root")
    return target


def inspect_cache(
    cache_dir: Path, source_id: str, dataset_version: str, request: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    target = _target(cache_dir, source_id, dataset_version)
    if target.is_symlink():
        raise CacheControlError("versioned cache target must not be a symlink")
    files = sorted(path for path in target.rglob("*") if path.is_file()) if target.is_dir() else []
    manifests: list[dict[str, Any]] = []
    verified = 0
    invalid = 0
    for manifest_path in (path for path in files if path.name.endswith(".download.json")):
        state: dict[str, Any] = {"path": str(manifest_path.relative_to(target))}
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            output_name = manifest.get("output_filename")
            data_path = manifest_path.parent / output_name if isinstance(output_name, str) else None
            if not data_path or not data_path.is_file() or not manifest.get("sha256"):
                raise CacheControlError("manifest lacks a present output file or SHA-256")
            if manifest.get("dataset_version") != dataset_version:
                raise CacheControlError("manifest dataset version does not match the requested version")
            observed = _sha256(data_path)
            state.update(
                {
                    "output_filename": output_name,
                    "recorded_sha256": manifest["sha256"],
                    "observed_sha256": observed,
                    "status": "verified" if observed == manifest["sha256"] else "invalid",
                }
            )
        except (OSError, json.JSONDecodeError, CacheControlError) as exc:
            state.update({"status": "invalid", "error": str(exc)})
        if state["status"] == "verified":
            verified += 1
        else:
            invalid += 1
        manifests.append(state)
    return {
        "cache_control_version": "d1-cache-control-v1",
        "status": (
            "missing"
            if not target.exists()
            else "invalid"
            if not target.is_dir() or invalid or not manifests
            else "present"
        ),
        "source_id": source_id,
        "dataset_version": dataset_version,
        "target": str(target),
        "file_count": len(files),
        "bytes": sum(path.stat().st_size for path in files),
        "manifests": manifests,
        "verified_manifest_count": verified,
        "invalid_manifest_count": invalid,
        "request_cache_key": stable_request_cache_key(source_id, dataset_version, request) if request else None,
    }


def delete_cache(cache_dir: Path, source_id: str, dataset_version: str, confirmation: str) -> dict[str, Any]:
    target = _target(cache_dir, source_id, dataset_version)
    expected = f"{source_id}@{dataset_version}"
    if confirmation != expected:
        raise CacheControlError(f"confirmation must exactly equal {expected}")
    if target.is_symlink():
        raise CacheControlError("refusing to delete a symlinked cache target")
    if not target.is_dir():
        raise CacheControlError(f"versioned cache does not exist: {target}")
    file_count = sum(1 for path in target.rglob("*") if path.is_file())
    byte_count = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    shutil.rmtree(target)
    return {
        "cache_control_version": "d1-cache-control-v1",
        "status": "deleted",
        "source_id": source_id,
        "dataset_version": dataset_version,
        "target": str(target),
        "deleted_file_count": file_count,
        "deleted_bytes": byte_count,
        "recoverable": False,
    }


def _request(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CacheControlError("request JSON must be an object")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "delete"):
        child = subparsers.add_parser(command)
        child.add_argument("--cache-dir", type=Path, required=True)
        child.add_argument("--source-id", required=True)
        child.add_argument("--dataset-version", required=True)
        if command == "status":
            child.add_argument("--request", type=Path)
        else:
            child.add_argument("--confirm", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            report = inspect_cache(args.cache_dir, args.source_id, args.dataset_version, _request(args.request))
        else:
            report = delete_cache(args.cache_dir, args.source_id, args.dataset_version, args.confirm)
    except (OSError, json.JSONDecodeError, CacheControlError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
