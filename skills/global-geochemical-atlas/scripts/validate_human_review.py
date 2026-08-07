#!/usr/bin/env python3
"""Validate a prepared D1 human-review sheet without inventing reviewer decisions."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _date_time(value: Any) -> bool:
    if not _text(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def validate(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {"status": "invalid", "path": str(path), "errors": [f"unreadable JSON: {exc}"]}
    if not isinstance(document, dict):
        return {"status": "invalid", "path": str(path), "errors": ["root must be an object"]}

    errors: list[str] = []
    records = document.get("records")
    if not isinstance(records, list):
        records = []
        errors.append("records must be an array")
    required = document.get("required_record_count", 30)
    if not isinstance(required, int) or isinstance(required, bool) or required < 1:
        required = 30
        errors.append("required_record_count must be a positive integer")
    if document.get("prepared_record_count") != len(records):
        errors.append("prepared_record_count does not equal len(records)")

    automated_pass = 0
    completed = 0
    human_pass = 0
    human_fail = 0
    identifiers: set[str] = set()
    for position, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            errors.append(f"records[{position}] must be an object")
            continue
        review_id = record.get("review_id")
        if not _text(review_id):
            errors.append(f"records[{position}].review_id is missing")
        elif review_id in identifiers:
            errors.append(f"records[{position}].review_id is duplicated: {review_id}")
        else:
            identifiers.add(review_id)
        checks = record.get("automated_checks")
        check_values = list(checks.values()) if isinstance(checks, dict) else []
        machine_pass = record.get("automated_status") == "PASS" and bool(check_values) and all(
            item is True for item in check_values
        )
        automated_pass += int(machine_pass)
        reviewer = record.get("reviewer")
        reviewer = reviewer if isinstance(reviewer, dict) else {}
        decision = reviewer.get("decision")
        signed = (
            decision in {"pass", "fail"}
            and _text(reviewer.get("reviewer"))
            and _date_time(reviewer.get("reviewed_at"))
            and _text(reviewer.get("notes"))
        )
        completed += int(signed)
        human_pass += int(signed and decision == "pass")
        human_fail += int(signed and decision == "fail")

    if document.get("automated_pass_count") != automated_pass:
        errors.append("automated_pass_count does not match record checks")
    if document.get("completed_record_count") != completed:
        errors.append("completed_record_count does not match signed reviewer blocks")
    complete = len(records) >= required and completed == len(records) and automated_pass == len(records)
    passed = complete and human_pass == len(records)
    expected_status = "passed" if passed else "failed" if complete and human_fail else "in_progress" if completed else "prepared"
    if document.get("status") != expected_status:
        errors.append(f"status must be {expected_status!r} for the current record decisions")
    if "all_records_reviewed" in document and document.get("all_records_reviewed") is not complete:
        errors.append("all_records_reviewed does not match review completion")

    return {
        "status": "invalid" if errors else "passed" if passed else "pending",
        "path": str(path),
        "source_id": document.get("source_id"),
        "required_record_count": required,
        "prepared_record_count": len(records),
        "automated_pass_count": automated_pass,
        "completed_record_count": completed,
        "human_pass_count": human_pass,
        "human_fail_count": human_fail,
        "benchmark_ready_review": passed and not errors,
        "errors": errors,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args(argv)
    result = validate(args.input)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if result["status"] == "invalid":
        return 2
    if args.require_complete and not result["benchmark_ready_review"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
