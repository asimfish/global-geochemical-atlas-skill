#!/usr/bin/env python3
"""Validate benchmark structure and smoke-grade every versioned gold output."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from grade_task import GradeError, grade


ALL_EXPECTED = {
    "public": set(range(1, 9)),
    "shadow": set(range(9, 17)),
    "final_holdout": set(range(17, 25)),
}


def task_locations(root: Path, private_root: Path | None = None, public_only: bool = False) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    locations: list[tuple[str, Path]] = [("public", root / "release" / "public")]
    if not public_only:
        selected = private_root or (root / "evaluator_private")
        if selected.is_dir():
            locations.extend((("shadow", selected / "shadow"), ("final_holdout", selected / "final_holdout")))
    for split, base in locations:
        if base.exists():
            result.extend((split, path) for path in sorted(base.glob("Q[0-9][0-9]")) if path.is_dir())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--private-root", type=Path, help="Private root containing shadow/ and final_holdout/ outside the E1 workspace")
    parser.add_argument("--public-only", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    private_root = args.private_root.resolve() if args.private_root else None
    benchmark_version = (root / "VERSION").read_text(encoding="utf-8").strip()
    alignment = json.loads((root / "contracts" / "benchmark-execution-contract.json").read_text(encoding="utf-8"))
    required_outputs = [item["path"] for item in alignment["submission"]["required_artifacts"]]
    expected = {"public": ALL_EXPECTED["public"]}
    selected_private = private_root or (root / "evaluator_private")
    if not args.public_only and selected_private.is_dir():
        expected.update({"shadow": ALL_EXPECTED["shadow"], "final_holdout": ALL_EXPECTED["final_holdout"]})

    errors: list[str] = []
    smoke: list[dict[str, object]] = []
    seen: dict[str, set[int]] = {key: set() for key in expected}
    task_ids: list[str] = []

    for split, task_dir in task_locations(root, private_root, args.public_only):
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
        if metadata.get("status") != "ALIGNED_E1":
            errors.append(f"{task_dir.name}: status is not ALIGNED_E1")
        if metadata.get("gold_version") != benchmark_version:
            errors.append(f"{task_dir.name}: gold_version mismatch")

        for asset in metadata.get("input_assets", []):
            asset_path = task_dir / "inputs" / asset
            if not asset_path.is_file():
                errors.append(f"{task_dir.name}: declared input missing: {asset}")
            elif asset_path.stat().st_size == 0:
                errors.append(f"{task_dir.name}: declared input is empty: {asset}")
        if metadata.get("required_outputs") != required_outputs:
            errors.append(f"{task_dir.name}: required_outputs do not exactly match the E1 artifact contract")
        for output in required_outputs:
            if not (task_dir / "gold" / output).is_file():
                errors.append(f"{task_dir.name}: gold output missing: {output}")
        try:
            manifest = json.loads((task_dir / "gold" / "artifacts" / "run_manifest.json").read_text(encoding="utf-8"))
            evidence = manifest.get("benchmark_evidence", {})
            missing_evidence = [item for item in metadata.get("legacy_logical_outputs", []) if item not in evidence]
            if missing_evidence:
                errors.append(f"{task_dir.name}: run_manifest benchmark_evidence missing {missing_evidence}")
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            errors.append(f"{task_dir.name}: invalid E1 run_manifest gold: {exc}")

        task_text = (task_dir / "task.md").read_text(encoding="utf-8") if (task_dir / "task.md").is_file() else ""
        if re.search(r"\b(TODO|TBD|PLACEHOLDER)\b|待补|后续任务", task_text, flags=re.IGNORECASE):
            errors.append(f"{task_dir.name}: task.md contains placeholder language")

        rubric_path = task_dir / "rubric.json"
        if rubric_path.is_file():
            try:
                rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
                criterion_points = sum(int(item["points"]) for item in rubric.get("criteria", []))
                if int(rubric.get("evidence_points", -1)) != criterion_points:
                    errors.append(
                        f"{task_dir.name}: rubric points invalid; evidence_points={rubric.get('evidence_points')}, criteria_sum={criterion_points}"
                    )
                if rubric.get("task_id") != metadata.get("task_id"):
                    errors.append(f"{task_dir.name}: rubric task_id mismatch")
                if rubric.get("scoring_contract") != "e1-six-dimension-v1":
                    errors.append(f"{task_dir.name}: rubric scoring contract mismatch")
                allowed_dimensions = {item["dimension_id"] for item in alignment["dimensions"]}
                bad_dimensions = [item.get("id") for item in rubric.get("criteria", []) if item.get("dimension_id") not in allowed_dimensions]
                if bad_dimensions:
                    errors.append(f"{task_dir.name}: rubric criteria missing valid E1 dimensions: {bad_dimensions}")
            except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{task_dir.name}: invalid rubric.json: {exc}")

        try:
            report = grade(task_dir, task_dir / "gold")
            passed = all(item["passed"] for item in report["checks"]) and report["hard_gate_passed"] and not report["redline_events"]
            smoke.append(
                {
                    "question_id": task_dir.name,
                    "task_id": metadata.get("task_id"),
                    "evidence_points_awarded": report["evidence_points_awarded"],
                    "evidence_points_possible": report["evidence_points_possible"],
                    "dimensions": report["dimensions"],
                    "redline_events": report["redline_events"],
                    "passed": passed,
                }
            )
            if not passed:
                failed_ids = [item["id"] for item in report["checks"] if not item["passed"]]
                errors.append(f"{task_dir.name}: gold smoke failed; checks={failed_ids}; redlines={report['redline_events']}")
        except (GradeError, OSError, json.JSONDecodeError) as exc:
            errors.append(f"{task_dir.name}: smoke grader error: {exc}")

    for split, expected_ids in expected.items():
        missing = sorted(expected_ids - seen[split])
        extra = sorted(seen[split] - expected_ids)
        if missing or extra:
            errors.append(f"{split}: missing={missing}, extra={extra}")

    duplicates = sorted(task_id for task_id, count in Counter(task_ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate task IDs: {duplicates}")

    inventory_paths = [root / "task_inventory.csv"]
    if private_root:
        inventory_paths.append(private_root / "task_inventory_private.csv")
    if not inventory_paths[0].is_file():
        errors.append("missing task_inventory.csv")
    else:
        import csv

        inventory_rows = []
        for inventory_path in inventory_paths:
            if inventory_path.is_file():
                with inventory_path.open("r", encoding="utf-8", newline="") as handle:
                    inventory_rows.extend(csv.DictReader(handle))
        if len(inventory_rows) != len(task_ids):
            errors.append(f"inventory rows={len(inventory_rows)}, expected={len(task_ids)}")
        inventory_ids = {row.get("task_id") for row in inventory_rows}
        if inventory_ids != set(task_ids):
            errors.append("task_inventory.csv task IDs do not match task directories")

    report = {
        "benchmark_version": benchmark_version,
        "tasks_found": len(task_ids),
        "alignment_contract": alignment["schema_version"],
        "e1_eval_version": alignment["e1_eval_version"],
        "e1_contract_sha256": alignment["e1_contract_sha256"],
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
