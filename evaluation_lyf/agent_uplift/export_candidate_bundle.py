#!/usr/bin/env python3
"""Create a least-privilege uplift bundle before an Agent session starts."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


PUBLIC_FILES = (
    "TASK.md",
    "public_case/sources.json",
    "public_case/discovery_contract.json",
    "public_case/benchmark_export_crosswalk.json",
    "public_case/prepare_case.py",
)
DEVELOPMENT_FILES = ("public_case/score_submission.py",)
FORBIDDEN_PARTS = {".git", "gold", "checker", "private", "reference_implementation", "stage_benchmark", "experiment"}


class BundleError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_copy(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise BundleError(f"not a regular allowlisted file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def copy_skill(source: Path, destination: Path) -> None:
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise BundleError(f"Skill contains a symlink: {path}")
        if path.is_file():
            relative = path.relative_to(source)
            regular_copy(path, destination / relative)


def manifest_entries(root: Path) -> list[dict[str, object]]:
    result = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "BUNDLE_MANIFEST.json":
            continue
        result.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    return result


def validate(root: Path) -> dict[str, object]:
    manifest_path = root / "BUNDLE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid bundle manifest: {exc}") from exc
    entries = manifest.get("files")
    if manifest.get("schema_version") != "qwen-uplift-candidate-bundle-v1" or not isinstance(entries, list):
        raise BundleError("invalid bundle schema")
    expected = {item["path"]: item for item in entries}
    actual = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BundleError(f"symlink leaked: {path}")
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(root).as_posix()
        parts = {part.casefold() for part in Path(relative).parts}
        if parts & FORBIDDEN_PARTS:
            raise BundleError(f"forbidden path leaked: {relative}")
        actual[relative] = path
    if set(actual) != set(expected):
        raise BundleError(
            f"bundle file set mismatch; missing={sorted(set(expected)-set(actual))}; "
            f"extra={sorted(set(actual)-set(expected))}"
        )
    for relative, path in actual.items():
        item = expected[relative]
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise BundleError(f"bundle hash mismatch: {relative}")
    if manifest.get("mode") == "formal" and "public_case/score_submission.py" in actual:
        raise BundleError("formal bundle leaked the public development scorer")
    condition = manifest.get("condition")
    skill_exists = (root / ".agents/skills/global-geochemical-atlas/SKILL.md").is_file()
    if (condition == "S0") != skill_exists:
        raise BundleError("Skill visibility does not match B0/S0")
    return {
        "status": "PASS", "condition": condition, "mode": manifest.get("mode"),
        "file_count": len(actual), "content_manifest_sha256": manifest.get("content_manifest_sha256"),
    }


def export(repo_root: Path, output: Path, condition: str, mode: str, prompt: Path) -> dict[str, object]:
    repo_root, output = repo_root.resolve(), output.resolve()
    source = repo_root / "evaluation_lyf/agent_uplift"
    if output.exists():
        raise BundleError(f"refusing to overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
    try:
        for relative in (*PUBLIC_FILES, *(DEVELOPMENT_FILES if mode == "development" else ())):
            regular_copy(source / relative, staging / relative)
        regular_copy(prompt, staging / "AGENT_PROMPT.md")
        if condition == "S0":
            copy_skill(
                repo_root / "skills/global-geochemical-atlas",
                staging / ".agents/skills/global-geochemical-atlas",
            )
        (staging / "submission").mkdir()
        entries = manifest_entries(staging)
        canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
        commit = subprocess.run(
            ["git", "-c", f"safe.directory={repo_root}", "rev-parse", "HEAD"],
            cwd=repo_root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        manifest = {
            "schema_version": "qwen-uplift-candidate-bundle-v1",
            "condition": condition,
            "mode": mode,
            "source_commit": commit,
            "agent_start_directory": ".",
            "candidate_visible_scorer": mode == "development",
            "content_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
            "files": entries,
            "claim_boundary": (
                "Bundle was created before Agent launch from an explicit allowlist. "
                "Formal scoring and browser audit remain outside this directory."
            ),
        }
        (staging / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        summary = validate(staging)
        staging.rename(output)
        return {**summary, "bundle_root": str(output)}
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--condition", choices=("B0", "S0"))
    parser.add_argument("--mode", choices=("development", "formal"), default="formal")
    parser.add_argument("--prompt", type=Path)
    parser.add_argument("--validate-only", type=Path)
    args = parser.parse_args()
    try:
        if args.validate_only:
            result = validate(args.validate_only)
        else:
            if args.output is None or args.condition is None or args.prompt is None:
                parser.error("--output, --condition and --prompt are required for export")
            result = export(args.repo_root, args.output, args.condition, args.mode, args.prompt)
    except BundleError as exc:
        parser.exit(1, f"bundle error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
