#!/usr/bin/env python3
"""Deterministic grader for Global Geochemical Atlas Benchmark v5.

Only Python's standard library is required. A task's hidden or public
``checker/grader_spec.json`` defines objective checks worth 80 points and
red-line predicates. The remaining 20 points are assigned separately with the
task's evidence-anchored LLM rubric.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any


GRADER_VERSION = "5.0.0-draft.1"


class GradeError(Exception):
    """Raised for an invalid grader specification or unsafe path."""


def _safe_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise GradeError(f"path escapes submission root: {relative}") from exc
    return candidate


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _json_path(document: Any, path: str) -> Any:
    value = document
    if path in ("", "$"):
        return value
    for token in path.removeprefix("$.").split("."):
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise KeyError(path)
    return value


def _to_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip() != "":
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _equivalent(actual: Any, expected: Any, tolerance: float = 0.0, unordered: bool = False) -> bool:
    if expected is None:
        return actual is None or actual == ""
    if isinstance(expected, bool):
        if isinstance(actual, str):
            return actual.strip().lower() == str(expected).lower()
        return actual is expected
    expected_number = _to_number(expected)
    actual_number = _to_number(actual)
    if expected_number is not None and actual_number is not None:
        return math.isclose(actual_number, expected_number, rel_tol=0.0, abs_tol=tolerance)
    if isinstance(expected, list) and isinstance(actual, list):
        if unordered:
            return sorted(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in actual) == sorted(
                json.dumps(x, sort_keys=True, ensure_ascii=False) for x in expected
            )
        return actual == expected
    return actual == expected or str(actual) == str(expected)


def _find_csv_row(rows: list[dict[str, str]], key: dict[str, Any]) -> dict[str, str]:
    matches = [row for row in rows if all(_equivalent(row.get(column), value) for column, value in key.items())]
    if len(matches) != 1:
        raise LookupError(f"expected exactly one row for key {key}, found {len(matches)}")
    return matches[0]


def _result(check: dict[str, Any], passed: bool, evidence: str) -> dict[str, Any]:
    points = int(check.get("points", 0))
    return {
        "id": check["id"],
        "type": check["type"],
        "passed": passed,
        "points_awarded": points if passed else 0,
        "points_possible": points,
        "evidence": evidence,
    }


def evaluate_check(root: Path, check: dict[str, Any]) -> dict[str, Any]:
    check_type = check["type"]
    relative = check.get("path", "")
    path = _safe_path(root, relative) if relative else root
    try:
        if check_type == "file_exists":
            passed = path.is_file()
            return _result(check, passed, f"{relative}: {'file' if passed else 'missing'}")

        if check_type == "file_min_bytes":
            size = path.stat().st_size
            minimum = int(check["minimum"])
            return _result(check, size >= minimum, f"{relative}: {size} bytes; required >= {minimum}")

        if check_type == "file_sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected = check["expected"].lower()
            return _result(check, digest == expected, f"{relative}: sha256={digest}")

        if check_type == "csv_columns":
            rows = _load_csv(path)
            columns = list(rows[0].keys()) if rows else []
            if not rows:
                with path.open("r", encoding="utf-8-sig", newline="") as handle:
                    columns = next(csv.reader(handle), [])
            missing = [column for column in check["required"] if column not in columns]
            return _result(check, not missing, f"{relative}: missing columns={missing}")

        if check_type == "csv_row_count":
            count = len(_load_csv(path))
            expected = int(check["expected"])
            return _result(check, count == expected, f"{relative}: rows={count}; expected={expected}")

        if check_type == "csv_key_set":
            rows = _load_csv(path)
            columns = check["columns"]
            actual = sorted(tuple(row.get(column, "") for column in columns) for row in rows)
            expected = sorted(tuple(str(value) for value in item) for item in check["expected"])
            return _result(check, actual == expected, f"{relative}: actual keys={actual}; expected={expected}")

        if check_type == "csv_cell":
            row = _find_csv_row(_load_csv(path), check["key"])
            actual = row.get(check["column"])
            expected = check.get("expected")
            tolerance = float(check.get("tolerance", 0.0))
            passed = _equivalent(actual, expected, tolerance=tolerance)
            return _result(
                check,
                passed,
                f"{relative} key={check['key']} column={check['column']} actual={actual!r} expected={expected!r} tol={tolerance}",
            )

        if check_type == "json_value":
            actual = _json_path(_load_json(path), check["json_path"])
            expected = check.get("expected")
            tolerance = float(check.get("tolerance", 0.0))
            passed = _equivalent(actual, expected, tolerance=tolerance, unordered=bool(check.get("unordered")))
            return _result(
                check,
                passed,
                f"{relative} path={check['json_path']} actual={actual!r} expected={expected!r}",
            )

        if check_type == "json_length":
            actual = _json_path(_load_json(path), check["json_path"])
            length = len(actual)
            expected = int(check["expected"])
            return _result(check, length == expected, f"{relative} path={check['json_path']} length={length}; expected={expected}")

        if check_type == "json_array_contains":
            actual = _json_path(_load_json(path), check["json_path"])
            expected = check["expected"]
            missing = [item for item in expected if item not in actual]
            return _result(check, not missing, f"{relative} path={check['json_path']} missing={missing}")

        if check_type == "json_object_has_keys":
            actual = _json_path(_load_json(path), check["json_path"])
            missing = [key for key in check["required"] if not isinstance(actual, dict) or key not in actual]
            return _result(check, not missing, f"{relative} path={check['json_path']} missing keys={missing}")

        if check_type == "jsonl_row_count":
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            for line in lines:
                json.loads(line)
            expected = int(check["expected"])
            return _result(check, len(lines) == expected, f"{relative}: JSONL rows={len(lines)}; expected={expected}")

        if check_type == "text_contains_all":
            content = path.read_text(encoding="utf-8").lower()
            missing = [term for term in check["terms"] if term.lower() not in content]
            return _result(check, not missing, f"{relative}: missing terms={missing}")

        if check_type == "text_regex_forbidden":
            content = path.read_text(encoding="utf-8")
            matches = re.findall(check["pattern"], content, flags=re.IGNORECASE | re.MULTILINE)
            return _result(check, not matches, f"{relative}: forbidden matches={matches[:5]}")

        raise GradeError(f"unsupported check type: {check_type}")
    except (FileNotFoundError, IsADirectoryError) as exc:
        return _result(check, False, f"{relative}: unavailable ({exc.__class__.__name__})")
    except (json.JSONDecodeError, csv.Error, KeyError, ValueError, LookupError, TypeError) as exc:
        return _result(check, False, f"{relative}: evaluation error: {exc}")


def grade(task_dir: Path, submission_dir: Path) -> dict[str, Any]:
    spec_path = task_dir / "checker" / "grader_spec.json"
    spec = _load_json(spec_path)
    checks = [evaluate_check(submission_dir, check) for check in spec["checks"]]
    points_possible = sum(item["points_possible"] for item in checks)
    if points_possible != int(spec.get("objective_max", 80)):
        raise GradeError(f"objective check points sum to {points_possible}, expected {spec.get('objective_max', 80)}")

    redline_events: list[dict[str, Any]] = []
    for rule in spec.get("redlines", []):
        result = evaluate_check(submission_dir, {**rule, "points": 0})
        # A missing or unparsable artifact already loses its objective checks;
        # it is not evidence that a scientific red line actually occurred.
        # Red lines require affirmative, evaluable output evidence.
        if "unavailable (" in result["evidence"] or "evaluation error:" in result["evidence"]:
            continue
        if not result["passed"]:
            redline_events.append(
                {
                    "id": rule["id"],
                    "consequence": rule["consequence"],
                    "evidence": result["evidence"],
                }
            )

    objective_score = sum(item["points_awarded"] for item in checks)
    if any(event["consequence"] in {"task_zero", "acceptance_fail"} for event in redline_events):
        objective_score = 0
    elif any(event["consequence"] == "task_cap_20" for event in redline_events):
        objective_score = min(objective_score, 20)

    return {
        "task_id": spec["task_id"],
        "objective_score": objective_score,
        "objective_max": points_possible,
        "checks": checks,
        "redline_events": redline_events,
        "grader_version": GRADER_VERSION,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_dir", type=Path)
    parser.add_argument("submission_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        report = grade(args.task_dir.resolve(), args.submission_dir.resolve())
    except (GradeError, OSError, json.JSONDecodeError) as exc:
        print(f"grader error: {exc}", file=sys.stderr)
        return 2

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
