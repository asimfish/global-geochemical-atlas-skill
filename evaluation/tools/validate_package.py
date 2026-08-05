#!/usr/bin/env python3
"""Validate benchmark structure and smoke-grade every versioned gold output."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

from grade_task import GradeError, grade


EXPECTED = {
    "public": set(range(1, 9)),
    "shadow": set(range(9, 17)),
    "final_holdout": set(range(17, 25)),
}


def task_locations(root: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    for split, base in (
        ("public", root / "release" / "public"),
        ("shadow", root / "evaluator_private" / "shadow"),
        ("final_holdout", root / "evaluator_private" / "final_holdout"),
    ):
        if base.exists():
            result.extend((split, path) for path in sorted(base.glob("Q[0-9][0-9]")) if path.is_dir())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    benchmark_version = (root / "VERSION").read_text(encoding="utf-8").strip()

    errors: list[str] = []
    smoke: list[dict[str, object]] = []
    seen: dict[str, set[int]] = {key: set() for key in EXPECTED}
    task_ids: list[str] = []

    for split, task_dir in task_locations(root):
        match = re.fullmatch(r"Q(\d{2})", task_dir.name)
        if not match:
            errors.append(f"invalid task directory name: {task_dir}")
            continue
        number = int(match.group(1))
        seen[split].add(number)

        for relative in ("task.json", "task.md", "inputs", "gold", "checker/grader_spec.json", "rubric.json"):
            if not (task_dir / relative).exists():
                errors.append(f"{task_dir.name}: missing {relative}")

        if not (task_dir / "task.json").is_file():
            continue
        try:
            metadata = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{task_dir.name}: invalid task.json: {exc}")
            continue

        task_ids.append(str(metadata.get("task_id")))
        if metadata.get("question_id") != task_dir.name:
            errors.append(f"{task_dir.name}: question_id mismatch")
        if metadata.get("split") != split:
            errors.append(f"{task_dir.name}: split mismatch: {metadata.get('split')} != {split}")
        if metadata.get("status") != "SMOKE_PASSED":
            errors.append(f"{task_dir.name}: status is not SMOKE_PASSED")
        if metadata.get("gold_version") != benchmark_version:
            errors.append(f"{task_dir.name}: gold_version mismatch")

        for asset in metadata.get("input_assets", []):
            asset_path = task_dir / "inputs" / asset
            if not asset_path.is_file():
                errors.append(f"{task_dir.name}: declared input missing: {asset}")
            elif asset_path.stat().st_size == 0:
                errors.append(f"{task_dir.name}: declared input is empty: {asset}")
        for output in metadata.get("required_outputs", []):
            if not (task_dir / "gold" / output).is_file():
                errors.append(f"{task_dir.name}: gold output missing: {output}")

        task_text = (task_dir / "task.md").read_text(encoding="utf-8") if (task_dir / "task.md").is_file() else ""
        if re.search(r"\b(TODO|TBD|PLACEHOLDER)\b|待补|后续任务", task_text, flags=re.IGNORECASE):
            errors.append(f"{task_dir.name}: task.md contains placeholder language")

        rubric_path = task_dir / "rubric.json"
        if rubric_path.is_file():
            try:
                rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
                criterion_points = sum(int(item["points"]) for item in rubric.get("criteria", []))
                if int(rubric.get("llm_points", -1)) != 20 or criterion_points != 20:
                    errors.append(
                        f"{task_dir.name}: rubric points invalid; llm_points={rubric.get('llm_points')}, criteria_sum={criterion_points}"
                    )
                if rubric.get("task_id") != metadata.get("task_id"):
                    errors.append(f"{task_dir.name}: rubric task_id mismatch")
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{task_dir.name}: invalid rubric.json: {exc}")

        try:
            report = grade(task_dir, task_dir / "gold")
            passed = report["objective_score"] == report["objective_max"] and not report["redline_events"]
            smoke.append(
                {
                    "question_id": task_dir.name,
                    "task_id": metadata.get("task_id"),
                    "objective_score": report["objective_score"],
                    "objective_max": report["objective_max"],
                    "redline_events": report["redline_events"],
                    "passed": passed,
                }
            )
            if not passed:
                failed_ids = [item["id"] for item in report["checks"] if not item["passed"]]
                errors.append(f"{task_dir.name}: gold smoke failed; checks={failed_ids}; redlines={report['redline_events']}")
        except (GradeError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{task_dir.name}: smoke grader error: {exc}")

    for split, expected in EXPECTED.items():
        missing = sorted(expected - seen[split])
        extra = sorted(seen[split] - expected)
        if missing or extra:
            errors.append(f"{split}: missing={missing}, extra={extra}")

    duplicates = sorted(task_id for task_id, count in Counter(task_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate task IDs: {duplicates}")

    inventory_path = root / "task_inventory.csv"
    if not inventory_path.is_file():
        errors.append("missing task_inventory.csv")
    else:
        import csv

        with inventory_path.open("r", encoding="utf-8", newline="") as handle:
            inventory_rows = list(csv.DictReader(handle))
        if len(inventory_rows) != 24:
            errors.append(f"task_inventory.csv rows={len(inventory_rows)}, expected=24")
        inventory_ids = {row.get("task_id") for row in inventory_rows}
        if inventory_ids != set(task_ids):
            errors.append("task_inventory.csv task IDs do not match task directories")

    report = {
        "benchmark_version": benchmark_version,
        "tasks_found": len(task_ids),
        "split_counts": {split: len(values) for split, values in seen.items()},
        "smoke_tests": smoke,
        "errors": errors,
        "status": "PASS" if not errors else "FAIL",
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
