#!/usr/bin/env python3
"""Aggregate exactly three independent, paired B0/S0 evaluation reports."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "global-geochemical-evaluation-report-v1":
        raise ValueError(f"unsupported report schema: {path}")
    return value


def fingerprint(report: dict[str, Any]) -> str | None:
    manifest = report["experiment"].get("manifest") or {}
    return manifest.get("pair_fingerprint") or manifest.get("experiment_fingerprint")


def median_absolute_deviation(values: list[float]) -> float:
    median = statistics.median(values)
    return statistics.median(abs(value - median) for value in values)


def summarize(values: list[float]) -> dict[str, float | list[float]]:
    return {
        "raw": values,
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "range": max(values) - min(values),
        "mad": median_absolute_deviation(values),
    }


def diagnostic_comparison(arms: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Compare incomplete/development runs without promoting them to formal uplift."""

    arm_summary: dict[str, Any] = {}
    task_values: dict[str, dict[str, list[float]]] = {"B0": {}, "S0": {}}
    stages: dict[str, dict[str, list[float]]] = {"B0": {}, "S0": {}}
    deliverables: dict[str, dict[str, float]] = {}
    for condition, reports in arms.items():
        partial = [
            float(report.get("score", {}).get("descriptive_partial_mean"))
            for report in reports
            if isinstance(report.get("score", {}).get("descriptive_partial_mean"), (int, float))
        ]
        arm_summary[condition] = {
            "run_count": len(reports),
            "descriptive_partial": summarize(partial) if partial else None,
            "formal_observed_count": sum(
                isinstance(report.get("score", {}).get("observed"), (int, float))
                and not isinstance(report.get("score", {}).get("observed"), bool)
                for report in reports
            ),
        }
        for report in reports:
            benchmark = report.get("benchmark") or {}
            for item in benchmark.get("task_results", []):
                value = item.get("descriptive_total_score")
                question = item.get("question_id")
                if question and isinstance(value, (int, float)):
                    task_values[condition].setdefault(str(question), []).append(float(value))
            for stage, item in (benchmark.get("stage_summaries") or {}).items():
                value = item.get("descriptive_partial_mean")
                if isinstance(value, (int, float)):
                    stages[condition].setdefault(str(stage), []).append(float(value))
        names = sorted({name for report in reports for name in report.get("deliverables", {})})
        deliverables[condition] = {
            name: (
                sum(report.get("deliverables", {}).get(name, {}).get("usable") is True for report in reports)
                / len(reports)
                if reports else 0.0
            )
            for name in names
        }

    per_task = []
    wins = ties = losses = 0
    for question in sorted(set(task_values["B0"]) | set(task_values["S0"])):
        b_values, s_values = task_values["B0"].get(question, []), task_values["S0"].get(question, [])
        b_median = statistics.median(b_values) if b_values else None
        s_median = statistics.median(s_values) if s_values else None
        delta = s_median - b_median if b_median is not None and s_median is not None else None
        if delta is not None:
            if delta > 1e-9:
                wins += 1
            elif delta < -1e-9:
                losses += 1
            else:
                ties += 1
        per_task.append({"question_id": question, "b0_median": b_median, "s0_median": s_median, "delta_s0_minus_b0": delta})
    stage_delta = {}
    for stage in sorted(set(stages["B0"]) | set(stages["S0"])):
        b_values, s_values = stages["B0"].get(stage, []), stages["S0"].get(stage, [])
        stage_delta[stage] = (
            statistics.median(s_values) - statistics.median(b_values)
            if b_values and s_values else None
        )
    return {
        "claim_boundary": "Diagnostic partial totals compare observed artifacts only; they are not a formal competition score or Skill uplift claim.",
        "arms": arm_summary,
        "stage_partial_delta_s0_minus_b0": stage_delta,
        "task_partial_comparison": per_task,
        "task_win_tie_loss": {"S0_win": wins, "tie": ties, "S0_loss": losses},
        "deliverable_usable_run_rates": deliverables,
    }


def aggregate(reports: list[dict[str, Any]]) -> dict[str, Any]:
    arms = {"B0": [], "S0": []}
    errors: list[str] = []
    for report in reports:
        condition = report.get("experiment", {}).get("condition")
        if condition not in arms:
            errors.append(f"unexpected condition: {condition}")
            continue
        arms[condition].append(report)
    for condition, values in arms.items():
        run_ids = [item["experiment"].get("run_id") for item in values]
        if len(values) != 3:
            errors.append(f"{condition} requires exactly 3 reports, got {len(values)}")
        if len(set(run_ids)) != len(run_ids) or any(not value for value in run_ids):
            errors.append(f"{condition} run IDs are missing or not independent")
        if any(not item.get("fairness", {}).get("eligible_run_component") for item in values):
            errors.append(f"{condition} contains an ineligible run component")
    fingerprints = {fingerprint(item) for item in reports}
    if None in fingerprints or len(fingerprints) != 1:
        errors.append("reports do not share one audited pair fingerprint")
    scores: dict[str, dict[str, Any]] = {}
    red_lines: dict[str, dict[str, float]] = {}
    deliverable_usability: dict[str, dict[str, float]] = {}
    if not errors:
        for condition, values in arms.items():
            raw = [item["score"].get("observed") for item in values]
            if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw):
                errors.append(f"{condition} has a missing or nonnumeric score")
                continue
            scores[condition] = summarize([float(value) for value in raw])
            codes = sorted({
                str(item.get("code"))
                for report in values
                for item in report.get("scientific_red_lines", [])
                if isinstance(item, dict) and item.get("code")
            })
            counts_per_run: list[Counter[str]] = []
            for report in values:
                counter: Counter[str] = Counter()
                for item in report.get("scientific_red_lines", []):
                    if isinstance(item, dict) and item.get("code"):
                        counter[str(item["code"])] += float(item.get("count", 1))
                counts_per_run.append(counter)
            red_lines[condition] = {
                code: statistics.median(counter[code] for counter in counts_per_run)
                for code in codes
            }
            deliverable_names = sorted({
                name for report in values for name in report.get("deliverables", {})
            })
            deliverable_usability[condition] = {
                name: sum(
                    report.get("deliverables", {}).get(name, {}).get("usable") is True
                    for report in values
                ) / len(values)
                for name in deliverable_names
            }
    eligible = not errors
    uplift = scores.get("S0", {}).get("median", 0) - scores.get("B0", {}).get("median", 0) if eligible else None
    ceiling = bool(eligible and scores["B0"]["median"] >= 90)
    both_full = bool(eligible and scores["B0"]["median"] == 100 and scores["S0"]["median"] == 100)
    return {
        "schema_version": "global-geochemical-uplift-aggregate-v1",
        "status": "eligible" if eligible else "not_eligible",
        "errors": errors,
        "pair_fingerprint": next(iter(fingerprints)) if len(fingerprints) == 1 else None,
        "arms": scores,
        "scientific_red_line_median_counts": red_lines,
        "scientific_red_line_change_s0_minus_b0": {
            code: red_lines.get("S0", {}).get(code, 0) - red_lines.get("B0", {}).get(code, 0)
            for code in sorted(set(red_lines.get("B0", {})) | set(red_lines.get("S0", {})))
        },
        "deliverable_usable_run_rates": deliverable_usability,
        "median_uplift_s0_minus_b0": uplift,
        "ceiling_saturated": ceiling,
        "valid_uplift_evidence": eligible and not ceiling and not both_full,
        "both_arms_full_score": both_full,
        "diagnostic_comparison": diagnostic_comparison(arms),
        "interpretation": (
            "A ceiling-saturated task is retained as a regression check but cannot establish Skill uplift."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="return success after writing an explicitly non-formal comparison of incomplete runs",
    )
    args = parser.parse_args()
    result = aggregate([load(path) for path in args.reports])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": result["status"], "uplift": result["median_uplift_s0_minus_b0"]}, sort_keys=True))
    return 0 if result["status"] == "eligible" or args.diagnostic else 1


if __name__ == "__main__":
    raise SystemExit(main())
