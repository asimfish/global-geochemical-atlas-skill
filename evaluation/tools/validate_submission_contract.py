#!/usr/bin/env python3
"""Validate a candidate submission using only the public task contract.

This tool intentionally knows nothing about gold values, checker points, or
rubrics.  It lets a tested agent catch malformed physical artifacts and
``benchmark_evidence`` before handing a submission to the evaluator.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any


class ContractError(ValueError):
    """Raised when a candidate-visible contract cannot be evaluated safely."""


def _safe_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ContractError(f"path escapes root: {relative!r}") from exc
    return candidate


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _shape_errors(value: Any, schema: dict[str, Any], location: str) -> list[str]:
    if not schema:
        return []
    variants = schema.get("anyOf")
    if isinstance(variants, list):
        attempts = [
            _shape_errors(value, item, location)
            for item in variants
            if isinstance(item, dict)
        ]
        if any(not errors for errors in attempts):
            return []
        return [f"{location}: value does not match any declared type"]

    expected = schema.get("type")
    if not isinstance(expected, str) or not _matches_type(value, expected):
        return [f"{location}: expected {expected}, got {type(value).__name__}"]
    errors: list[str] = []
    if expected == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for key in required:
            if key not in value:
                errors.append(f"{location}: missing required key {key!r}")
        for key, item in value.items():
            if key in properties and isinstance(properties[key], dict):
                errors.extend(_shape_errors(item, properties[key], f"{location}.{key}"))
    elif expected == "array" and isinstance(schema.get("items"), dict):
        for index, item in enumerate(value):
            errors.extend(_shape_errors(item, schema["items"], f"{location}[{index}]"))
    return errors


def _validate_physical(path: Path, relative: str) -> list[str]:
    if not path.is_file() or path.is_symlink():
        return [f"missing required regular file: {relative}"]
    try:
        suffix = path.suffix.casefold()
        if suffix in {".json", ".geojson"}:
            _load_json(path)
        elif suffix == ".jsonl":
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if line.strip():
                    json.loads(line)
        elif suffix == ".csv":
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
                if not header:
                    return [f"{relative}: CSV header is missing"]
                list(reader)
        elif suffix == ".sqlite":
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                result = connection.execute("PRAGMA quick_check").fetchone()
            finally:
                connection.close()
            if not result or result[0] != "ok":
                return [f"{relative}: SQLite quick_check failed"]
        elif suffix == ".png":
            if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                return [f"{relative}: invalid PNG signature"]
        elif suffix in {".html", ".htm"}:
            text = path.read_text(encoding="utf-8")
            if "<html" not in text.casefold() or "</html>" not in text.casefold():
                return [f"{relative}: incomplete HTML document"]
    except (
        OSError,
        UnicodeError,
        csv.Error,
        json.JSONDecodeError,
        sqlite3.Error,
    ) as exc:
        return [f"{relative}: parse failed ({exc})"]
    return []


def _validate_logical_entry(
    relative: str, entry: Any, contract: dict[str, Any]
) -> list[str]:
    location = f"benchmark_evidence[{relative!r}]"
    if not isinstance(entry, dict):
        return [f"{location}: entry must be an object"]
    expected_format = contract.get("format")
    if entry.get("format") != expected_format:
        return [
            f"{location}: expected format {expected_format!r}, got {entry.get('format')!r}"
        ]
    errors: list[str] = []
    if expected_format == "csv":
        expected_columns = contract.get("columns", [])
        if entry.get("columns") != expected_columns:
            errors.append(f"{location}: columns must exactly match the declared order")
        rows = entry.get("rows")
        if not isinstance(rows, list):
            errors.append(f"{location}: rows must be an array of objects")
        else:
            expected_keys = set(expected_columns)
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    errors.append(f"{location}.rows[{index}]: row must be an object")
                elif set(row) != expected_keys:
                    errors.append(
                        f"{location}.rows[{index}]: keys must exactly match declared columns"
                    )
            if "row_count" in contract and len(rows) != int(contract["row_count"]):
                errors.append(
                    f"{location}: expected {contract['row_count']} rows, got {len(rows)}"
                )
    elif expected_format == "json":
        if "value" not in entry:
            errors.append(f"{location}: missing value")
        else:
            errors.extend(
                _shape_errors(
                    entry["value"], contract.get("json_shape", {}), f"{location}.value"
                )
            )
    elif expected_format == "jsonl":
        rows = entry.get("rows")
        if not isinstance(rows, list):
            errors.append(f"{location}: rows must be an array")
        else:
            for index, row in enumerate(rows):
                errors.extend(
                    _shape_errors(
                        row, contract.get("row_shape", {}), f"{location}.rows[{index}]"
                    )
                )
            if "row_count" in contract and len(rows) != int(contract["row_count"]):
                errors.append(
                    f"{location}: expected {contract['row_count']} rows, got {len(rows)}"
                )
    elif expected_format == "text":
        if not isinstance(entry.get("value"), str):
            errors.append(f"{location}: value must be a UTF-8 text string")
    elif expected_format == "base64":
        try:
            base64.b64decode(str(entry.get("value", "")), validate=True)
        except (ValueError, binascii.Error):
            errors.append(f"{location}: value is not valid RFC4648 base64")
    else:
        errors.append(f"{location}: unsupported public format {expected_format!r}")
    return errors


def validate_task(task_root: Path, submission_root: Path) -> dict[str, Any]:
    task_root = task_root.resolve()
    submission_root = submission_root.resolve()
    metadata = _load_json(task_root / "task.json")
    question = str(metadata.get("question_id", task_root.name))
    errors: list[str] = []
    required = metadata.get("required_outputs", [])
    if not isinstance(required, list) or not all(
        isinstance(item, str) for item in required
    ):
        raise ContractError(f"{question}: task.json.required_outputs is invalid")
    for relative in required:
        errors.extend(
            _validate_physical(_safe_path(submission_root, relative), relative)
        )

    visible = metadata.get("candidate_visible_contract")
    if not isinstance(visible, dict):
        errors.append("task.json.candidate_visible_contract is missing")
    else:
        container = str(visible.get("container", ""))
        try:
            manifest = _load_json(_safe_path(submission_root, container))
        except (OSError, json.JSONDecodeError, ContractError) as exc:
            errors.append(f"{container}: cannot load benchmark evidence ({exc})")
        else:
            field = str(visible.get("field", "benchmark_evidence"))
            evidence = manifest.get(field) if isinstance(manifest, dict) else None
            outputs = visible.get("logical_outputs")
            if not isinstance(evidence, dict) or not isinstance(outputs, dict):
                errors.append(f"{container}.{field}: must be an object")
            else:
                missing = sorted(set(outputs) - set(evidence))
                extra = sorted(set(evidence) - set(outputs))
                if missing:
                    errors.append(
                        f"{container}.{field}: missing logical outputs {missing}"
                    )
                if extra:
                    errors.append(
                        f"{container}.{field}: undeclared logical outputs {extra}"
                    )
                for relative, contract in outputs.items():
                    if relative in evidence and isinstance(contract, dict):
                        errors.extend(
                            _validate_logical_entry(
                                relative, evidence[relative], contract
                            )
                        )
    return {
        "question_id": question,
        "status": "PASS" if not errors else "FAIL",
        "required_outputs": len(required),
        "errors": errors,
    }


def validate_bundle(bundle_root: Path) -> dict[str, Any]:
    bundle_root = bundle_root.resolve()
    results = []
    for task_root in sorted((bundle_root / "tasks").glob("Q??")):
        results.append(
            validate_task(task_root, bundle_root / "submissions" / task_root.name)
        )
    if not results:
        raise ContractError(f"no tasks/Qxx directories found under {bundle_root}")
    return {
        "status": "PASS"
        if all(item["status"] == "PASS" for item in results)
        else "FAIL",
        "tasks_checked": len(results),
        "task_results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bundle-root", type=Path)
    mode.add_argument("--task-root", type=Path)
    parser.add_argument("--submission-root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.bundle_root:
            if args.submission_root:
                parser.error("--submission-root is only valid with --task-root")
            report = validate_bundle(args.bundle_root)
        else:
            if not args.submission_root:
                parser.error("--task-root requires --submission-root")
            report = validate_task(args.task_root, args.submission_root)
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        print(f"contract validation error: {exc}", file=sys.stderr)
        return 75
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
