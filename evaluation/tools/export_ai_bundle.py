#!/usr/bin/env python3
"""Export and validate a least-privilege Public bundle for a tested AI agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath


PUBLIC_QUESTIONS = tuple(f"Q{number:02d}" for number in range(1, 9))
FORBIDDEN_PATH_PARTS = {
    "checker",
    "evaluator_private",
    "gold",
    "results",
    "rubric.json",
    "task_inventory.csv",
}

AGENT_PROMPT = """# Instructions for the tested AI agent

You are the tested agent, not the evaluator. Complete Public tasks Q01-Q08.

## Visibility boundary

Treat this directory as your entire benchmark filesystem. Do not traverse to a
parent directory or search elsewhere for benchmark materials. This bundle does
not contain gold answers, checkers, rubrics, or private tasks.

For each task, read only:

- `contracts/benchmark-execution-contract.json`
- `tasks/Qxx/task.md`
- `tasks/Qxx/task.json`
- `tasks/Qxx/inputs/**`

Write every file listed in `task.json.required_outputs` to
`submissions/Qxx/`. Do not modify anything under `tasks/`.

You may use local code to process the supplied inputs. Do not invent sources,
identifiers, downloads, measurements, geological interpretations, or causal
claims. When evidence is insufficient, state the limitation or reject the
unsupported operation as required by the task.

Complete Q01 through Q08 independently. At the end, verify that all required
outputs exist and that structured files parse successfully. Report generated
paths and any genuine environment failures. Do not attempt to grade or repair
the submission against hidden expectations.
"""

BUNDLE_README = """# 使用指南

## 工作目录

```text
<仓库根目录>/evaluation/ai_visible_public
```

## 提示词

```text
请完整阅读当前工作目录中的 AGENT_PROMPT.md，并严格执行其中的全部要求。自主完成 Public Q01-Q08，把每道题要求的输出写入 submissions/Qxx/。不要访问父目录，不要寻找 gold、checker、rubric 或私有评测材料，也不要自行评分。除非遇到真正无法解决的环境错误，否则持续执行到八道题全部完成。
```
"""


class BundleError(RuntimeError):
    """Raised when source metadata or an exported bundle violates the contract."""


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise BundleError(f"unsafe relative path in task metadata: {value!r}")
    return path


def _copy_regular_file(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise BundleError(f"source asset is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_entries(root: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "BUNDLE_MANIFEST.json":
            continue
        relative = path.relative_to(root).as_posix()
        entries.append({"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)})
    return entries


def _load_execution_contract(path: Path) -> tuple[dict[str, object], tuple[str, ...]]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid {path}: {exc}") from exc
    try:
        artifacts = contract["submission"]["required_artifacts"]
        required_outputs = tuple(str(item["path"]) for item in artifacts)
    except (KeyError, TypeError) as exc:
        raise BundleError(f"invalid E1 artifact contract: {path}") from exc
    if not required_outputs or len(required_outputs) != len(set(required_outputs)):
        raise BundleError("E1 artifact contract must contain unique required paths")
    for value in required_outputs:
        _safe_relative_path(value)
    return contract, required_outputs


def _load_task_metadata(
    path: Path,
    question: str,
    expected_outputs: tuple[str, ...] | None = None,
    execution_contract: Mapping[str, object] | None = None,
) -> dict[str, object]:
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid {path}: {exc}") from exc
    if metadata.get("question_id") != question:
        raise BundleError(f"{question}: question_id mismatch")
    if metadata.get("split") != "public":
        raise BundleError(f"{question}: expected public split")
    input_assets = metadata.get("input_assets")
    required_outputs = metadata.get("required_outputs")
    if not isinstance(input_assets, list) or not all(isinstance(item, str) for item in input_assets):
        raise BundleError(f"{question}: input_assets must be a list of strings")
    if not isinstance(required_outputs, list) or not all(isinstance(item, str) for item in required_outputs):
        raise BundleError(f"{question}: required_outputs must be a list of strings")
    if len(input_assets) != len(set(input_assets)):
        raise BundleError(f"{question}: input_assets must be unique")
    if len(required_outputs) != len(set(required_outputs)):
        raise BundleError(f"{question}: required_outputs must be unique")
    for value in [*input_assets, *required_outputs]:
        _safe_relative_path(value)
    if expected_outputs is not None and tuple(required_outputs) != expected_outputs:
        raise BundleError(f"{question}: required_outputs drifted from the E1 execution contract")
    if execution_contract is not None:
        try:
            expected_contract_fields = {
                "benchmark_contract": execution_contract["schema_version"],
                "e1_contract_sha256": execution_contract["e1_contract_sha256"],
                "e1_eval_version": execution_contract["e1_eval_version"],
                "gold_version": execution_contract["benchmark_version"],
                "benchmark_evidence_container": execution_contract["submission"][
                    "benchmark_evidence"
                ]["container"],
            }
        except (KeyError, TypeError) as exc:
            raise BundleError("E1 execution contract lacks task-alignment fields") from exc
        for field, expected_value in expected_contract_fields.items():
            if metadata.get(field) != expected_value:
                raise BundleError(f"{question}: {field} drifted from the E1 execution contract")
    return metadata


def populate_bundle(source_root: Path, bundle_root: Path) -> None:
    """Populate an empty staging directory from the explicit Public allowlist."""

    source_root = source_root.resolve()
    public_root = source_root / "release" / "public"
    if not public_root.is_dir():
        raise BundleError(f"missing Public task root: {public_root}")

    version_path = source_root / "VERSION"
    interface_path = source_root / "docs" / "public_interface.md"
    contract_path = source_root / "contracts" / "benchmark-execution-contract.json"
    execution_contract, expected_outputs = _load_execution_contract(contract_path)
    _copy_regular_file(version_path, bundle_root / "VERSION")
    _copy_regular_file(interface_path, bundle_root / "public_interface.md")
    _copy_regular_file(
        contract_path,
        bundle_root / "contracts" / "benchmark-execution-contract.json",
    )
    (bundle_root / "README.md").write_text(BUNDLE_README, encoding="utf-8")
    (bundle_root / "AGENT_PROMPT.md").write_text(AGENT_PROMPT, encoding="utf-8")

    for question in PUBLIC_QUESTIONS:
        source_task = public_root / question
        destination_task = bundle_root / "tasks" / question
        metadata = _load_task_metadata(
            source_task / "task.json",
            question,
            expected_outputs,
            execution_contract,
        )
        _copy_regular_file(source_task / "task.json", destination_task / "task.json")
        _copy_regular_file(source_task / "task.md", destination_task / "task.md")
        for asset in metadata["input_assets"]:
            relative = Path(*_safe_relative_path(str(asset)).parts)
            _copy_regular_file(source_task / "inputs" / relative, destination_task / "inputs" / relative)
        submission_dir = bundle_root / "submissions" / question
        submission_dir.mkdir(parents=True, exist_ok=True)
        (submission_dir / ".gitkeep").write_bytes(b"")

    entries = _manifest_entries(bundle_root)
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    manifest = {
        "bundle_type": "ai-visible-public-development",
        "benchmark_version": version_path.read_text(encoding="utf-8").strip(),
        "questions": list(PUBLIC_QUESTIONS),
        "file_count": len(entries),
        "content_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
        "files": entries,
    }
    (bundle_root / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def validate_bundle(bundle_root: Path, *, allow_submissions: bool = True) -> dict[str, object]:
    """Validate paths, task assets, and content hashes in an exported bundle."""

    bundle_root = bundle_root.resolve()
    manifest_path = bundle_root / "BUNDLE_MANIFEST.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"invalid bundle manifest: {exc}") from exc

    if manifest.get("bundle_type") != "ai-visible-public-development":
        raise BundleError("unexpected bundle_type")
    if manifest.get("questions") != list(PUBLIC_QUESTIONS):
        raise BundleError("manifest question set is not Public Q01-Q08")

    manifest_entries = manifest.get("files")
    if not isinstance(manifest_entries, list):
        raise BundleError("manifest files must be a list")
    if manifest.get("file_count") != len(manifest_entries):
        raise BundleError("manifest file_count does not match its file entries")
    version_path = bundle_root / "VERSION"
    if manifest.get("benchmark_version") != version_path.read_text(encoding="utf-8").strip():
        raise BundleError("manifest benchmark_version does not match VERSION")
    expected: dict[str, dict[str, object]] = {}
    for item in manifest_entries:
        if not isinstance(item, dict) or set(item) != {"path", "bytes", "sha256"}:
            raise BundleError("manifest file entries must contain path, bytes and sha256")
        relative = item["path"]
        byte_count = item["bytes"]
        sha256 = item["sha256"]
        if not isinstance(relative, str):
            raise BundleError("manifest file path must be a string")
        _safe_relative_path(relative)
        if relative in expected:
            raise BundleError(f"duplicate manifest file path: {relative}")
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise BundleError(f"invalid manifest byte count: {relative}")
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise BundleError(f"invalid manifest SHA-256: {relative}")
        expected[relative] = item
    if list(expected) != sorted(expected):
        raise BundleError("manifest file entries must be sorted by path")
    canonical = json.dumps(manifest_entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if manifest.get("content_manifest_sha256") != hashlib.sha256(canonical).hexdigest():
        raise BundleError("content_manifest_sha256 does not match the canonical file entries")
    placeholders = {f"submissions/{question}/.gitkeep" for question in PUBLIC_QUESTIONS}

    actual_input_files: set[str] = set()
    submission_files: set[str] = set()
    for path in bundle_root.rglob("*"):
        if path.is_symlink():
            raise BundleError(f"symlink is not allowed in AI bundle: {path}")
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(bundle_root).as_posix()
        parts_lower = {part.lower() for part in PurePosixPath(relative).parts}
        if parts_lower & FORBIDDEN_PATH_PARTS:
            raise BundleError(f"forbidden path leaked into AI bundle: {relative}")
        if relative in placeholders:
            actual_input_files.add(relative)
        elif relative.startswith("submissions/"):
            submission_files.add(relative)
        else:
            actual_input_files.add(relative)

    if submission_files and not allow_submissions:
        raise BundleError(f"fresh bundle unexpectedly contains submissions: {sorted(submission_files)}")
    if actual_input_files != set(expected):
        missing = sorted(set(expected) - actual_input_files)
        extra = sorted(actual_input_files - set(expected))
        raise BundleError(f"bundle file set mismatch; missing={missing}, extra={extra}")

    for relative, item in expected.items():
        path = bundle_root / relative
        if path.stat().st_size != int(item["bytes"]):
            raise BundleError(f"size mismatch: {relative}")
        if _sha256(path) != item["sha256"]:
            raise BundleError(f"SHA-256 mismatch: {relative}")

    execution_contract, expected_outputs = _load_execution_contract(
        bundle_root / "contracts" / "benchmark-execution-contract.json"
    )
    for question in PUBLIC_QUESTIONS:
        task_root = bundle_root / "tasks" / question
        metadata = _load_task_metadata(
            task_root / "task.json",
            question,
            expected_outputs,
            execution_contract,
        )
        declared = {Path(*_safe_relative_path(str(item)).parts).as_posix() for item in metadata["input_assets"]}
        present = {
            path.relative_to(task_root / "inputs").as_posix()
            for path in (task_root / "inputs").rglob("*")
            if path.is_file()
        }
        if declared != present:
            raise BundleError(f"{question}: declared inputs differ from exported inputs")
        if not (bundle_root / "submissions" / question).is_dir():
            raise BundleError(f"{question}: missing submission directory")

    return {
        "status": "PASS",
        "bundle_root": str(bundle_root),
        "questions": len(PUBLIC_QUESTIONS),
        "input_files": len(actual_input_files),
        "submission_files": len(submission_files),
        "content_manifest_sha256": manifest["content_manifest_sha256"],
    }


def export_bundle(source_root: Path, output_root: Path) -> dict[str, object]:
    """Build into a sibling staging directory, validate, then publish atomically."""

    source_root = source_root.resolve()
    output_root = output_root.resolve()
    integrated_output = source_root / "ai_visible_public"
    if output_root == source_root or (source_root in output_root.parents and output_root != integrated_output):
        raise BundleError("output inside the evaluator root is allowed only at ai_visible_public/")
    if output_root.exists():
        raise BundleError(f"refusing to overwrite existing output directory: {output_root}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_root.name}.staging-", dir=output_root.parent))
    try:
        populate_bundle(source_root, staging)
        summary = validate_bundle(staging, allow_submissions=False)
        staging.rename(output_root)
        summary["bundle_root"] = str(output_root)
        return summary
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_root", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("output_root", type=Path, nargs="?")
    parser.add_argument("--validate-only", type=Path, metavar="BUNDLE_ROOT")
    args = parser.parse_args()

    try:
        if args.validate_only:
            summary = validate_bundle(args.validate_only)
        else:
            if args.output_root is None:
                parser.error("output_root is required unless --validate-only is used")
            summary = export_bundle(args.source_root, args.output_root)
    except BundleError as exc:
        parser.exit(1, f"bundle error: {exc}\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
