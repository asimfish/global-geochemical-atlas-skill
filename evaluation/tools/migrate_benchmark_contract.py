#!/usr/bin/env python3
"""Migrate v5 task contracts and gold evidence to the frozen E1 envelope."""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


VERSION = "6.0.0-draft.1"
ALIGNMENT_FILE = "contracts/benchmark-execution-contract.json"
MARKER = "<!-- e1-alignment-v1 -->"


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _task_dirs(evaluation_root: Path, private_root: Path | None) -> list[Path]:
    result = sorted((evaluation_root / "release" / "public").glob("Q[0-9][0-9]"))
    internal = evaluation_root / "evaluator_private"
    selected_private = private_root or (internal if internal.is_dir() else None)
    if selected_private:
        result.extend(sorted((selected_private / "shadow").glob("Q[0-9][0-9]")))
        result.extend(sorted((selected_private / "final_holdout").glob("Q[0-9][0-9]")))
    return [path for path in result if path.is_dir()]


def _encode_evidence(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".json", ".geojson"}:
        return {"format": "json", "value": _load_json(path)}
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            return {"format": "csv", "columns": reader.fieldnames or [], "rows": rows}
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {"format": "jsonl", "rows": rows}
    try:
        return {"format": "text", "value": path.read_text(encoding="utf-8")}
    except UnicodeDecodeError:
        return {"format": "base64", "value": base64.b64encode(path.read_bytes()).decode("ascii")}


def _primary_dimension(task_id: str, check: dict[str, Any]) -> str:
    check_id = str(check.get("id", "")).lower()
    check_type = str(check.get("type", ""))
    path = str(check.get("path", "")).lower()
    if check_type in {"file_exists", "file_min_bytes", "file_sha256"}:
        return "engineering_quality"
    if any(token in check_id + " " + path for token in ("source", "provenance", "doi", "license", "integrity", "hash")):
        return "scientific_credibility"
    if any(token in check_id for token in ("schema", "column", "field", "identity", "manifest", "traceability")):
        return "platform_reusability"
    category = task_id.split("-")[1] if "-" in task_id else ""
    if category in {"DATA", "PROV", "LICENSE"}:
        return "scientific_credibility"
    if category == "INGEST":
        return "platform_reusability"
    if category in {"MAP", "E2E"}:
        return "engineering_quality"
    return "domain_understanding"


def _rubric_dimension(criterion: dict[str, Any]) -> str:
    text = " ".join(str(criterion.get(key, "")) for key in ("id", "full_credit")).lower()
    if any(token in text for token in ("source", "provenance", "license", "integrity", "evidence", "traceability", "引用", "来源", "许可")):
        return "scientific_credibility"
    if any(token in text for token in ("reproduc", "audit", "stable", "failure_behavior", "可复现", "审计")):
        return "engineering_quality"
    if any(token in text for token in ("schema", "mapping", "identity_model", "interface", "结构", "复用")):
        return "platform_reusability"
    return "domain_understanding"


def _rewrite_evidence_path(value: str, legacy_outputs: set[str]) -> str:
    base, separator, pointer = value.partition(":")
    if base not in legacy_outputs:
        return value
    escaped = base.replace("~", "~0").replace("/", "~1")
    target = f"artifacts/run_manifest.json#/benchmark_evidence/{escaped}"
    return f"{target}/{pointer}" if separator and pointer else target


def _copy_template(template: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    expected = {path.name for path in template.iterdir() if path.is_file()}
    for existing in destination.iterdir():
        if existing.is_file() and existing.name in expected:
            existing.unlink()
    for source in template.iterdir():
        if source.is_file():
            shutil.copyfile(source, destination / source.name)


def _align_task(task_dir: Path, contract: dict[str, Any], template: Path) -> dict[str, Any]:
    metadata_path = task_dir / "task.json"
    metadata = _load_json(metadata_path)
    legacy_outputs = list(metadata.get("legacy_logical_outputs") or metadata.get("required_outputs", []))
    required = [item["path"] for item in contract["submission"]["required_artifacts"]]
    metadata.update(
        {
            "status": "ALIGNED_E1",
            "gold_version": VERSION,
            "benchmark_contract": "e2.e1-alignment.v1",
            "e1_eval_version": contract["e1_eval_version"],
            "e1_contract_sha256": contract["e1_contract_sha256"],
            "required_outputs": required,
            "legacy_logical_outputs": legacy_outputs,
            "benchmark_evidence_container": contract["submission"]["benchmark_evidence"]["container"],
        }
    )
    _atomic_json(metadata_path, metadata)

    evidence: dict[str, Any] = {}
    for relative in legacy_outputs:
        source = task_dir / "gold" / relative
        if not source.is_file():
            raise FileNotFoundError(f"{task_dir.name}: missing legacy gold evidence {relative}")
        evidence[relative] = _encode_evidence(source)

    artifact_root = task_dir / "gold" / "artifacts"
    _copy_template(template, artifact_root)
    run_manifest_path = artifact_root / "run_manifest.json"
    run_manifest = _load_json(run_manifest_path)
    run_manifest["benchmark_contract"] = {
        "schema_version": contract["schema_version"],
        "benchmark_version": VERSION,
        "task_id": metadata["task_id"],
        "question_id": metadata["question_id"],
        "split": metadata["split"],
        "e1_contract_sha256": contract["e1_contract_sha256"],
    }
    run_manifest["benchmark_evidence"] = evidence
    _atomic_json(run_manifest_path, run_manifest)

    spec_path = task_dir / "checker" / "grader_spec.json"
    spec = _load_json(spec_path)
    if "objective_max" in spec:
        spec["evidence_points"] = spec.pop("objective_max")
    for check in spec.get("checks", []):
        check["dimension_id"] = _primary_dimension(metadata["task_id"], check)
        check["evidence_location"] = "run_manifest.benchmark_evidence"
    for redline in spec.get("redlines", []):
        redline["dimension_id"] = "scientific_credibility"
        redline["evidence_location"] = "run_manifest.benchmark_evidence"
    spec["scoring_contract"] = "e1-six-dimension-v1"
    _atomic_json(spec_path, spec)

    rubric_path = task_dir / "rubric.json"
    rubric = _load_json(rubric_path)
    if "llm_points" in rubric:
        rubric["evidence_points"] = rubric.pop("llm_points")
    legacy_set = set(legacy_outputs)
    rubric["evidence_paths"] = [_rewrite_evidence_path(item, legacy_set) for item in rubric.get("evidence_paths", [])]
    for criterion in rubric.get("criteria", []):
        criterion["dimension_id"] = _rubric_dimension(criterion)
    rubric["scoring_contract"] = "e1-six-dimension-v1"
    _atomic_json(rubric_path, rubric)

    task_markdown = task_dir / "task.md"
    content = task_markdown.read_text(encoding="utf-8")
    if MARKER not in content:
        logical = "、".join(f"`{item}`" for item in legacy_outputs)
        preface = (
            f"{MARKER}\n"
            "## E1 统一交卷要求\n\n"
            "只生成 `task.json.required_outputs` 列出的十个 E1 物理产物，并保持 `artifacts/` 固定路径。"
            "不得另外创建题目专用文件。\n\n"
            f"下文提到的 {logical} 是逻辑评测证据键，不是物理文件。"
            "把它们按 JSON/CSV/JSONL/text 的原结构写入 "
            "`artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。\n\n"
        )
        _atomic_text(task_markdown, preface + content)
    return {"question_id": metadata["question_id"], "task_id": metadata["task_id"], "legacy_outputs": legacy_outputs}


def _update_inventory(path: Path) -> None:
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return
    for row in rows:
        row["required_output_count"] = "10"
        row["evidence_points"] = row.pop("objective_points", row.get("evidence_points", ""))
        row["llm_evidence_points"] = row.pop("llm_points", row.get("llm_evidence_points", ""))
        row["status"] = "ALIGNED_E1"
        row["gold_version"] = VERSION
        row["scoring_contract"] = "e1-six-dimension-v1"
    fieldnames = list(rows[0])
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evaluation_root", type=Path)
    parser.add_argument("--private-root", type=Path)
    args = parser.parse_args()
    root = args.evaluation_root.resolve()
    private_root = args.private_root.resolve() if args.private_root else None
    contract = _load_json(root / ALIGNMENT_FILE)
    template = root / "contracts" / "submission-artifact-template" / "artifacts"
    if not template.is_dir():
        raise SystemExit(f"missing E1 artifact template: {template}")
    tasks = [_align_task(task_dir, contract, template) for task_dir in _task_dirs(root, private_root)]
    _atomic_text(root / "VERSION", VERSION + "\n")
    _update_inventory(root / "task_inventory.csv")
    if private_root:
        _update_inventory(private_root / "task_inventory_private.csv")
    print(json.dumps({"status": "PASS", "benchmark_version": VERSION, "tasks_aligned": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
