#!/usr/bin/env python3
"""Aggregate raw JSONL run records into per-task medians, stability, and uplift."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path


def median_absolute_deviation(values: list[float]) -> float:
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_jsonl", type=Path)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()

    records = [json.loads(line) for line in args.raw_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
    grouped: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    redlines: dict[tuple[str, str, str], int] = defaultdict(int)
    for record in records:
        key = (record["task_id"], record["split"], record["condition"])
        total = float(record["objective_score"]) + float(record["llm_score"])
        grouped[key].append(total)
        redlines[key] += len(record.get("redline_events", []))

    summaries = {}
    for key, values in grouped.items():
        summaries[key] = {
            "runs": values,
            "median": statistics.median(values),
            "range": max(values) - min(values),
            "mad": median_absolute_deviation(values),
            "low_confidence": (max(values) - min(values) > 20) or redlines[key] > 0,
            "redline_count": redlines[key],
        }

    rows = []
    task_keys = sorted({(task_id, split) for task_id, split, _ in summaries})
    for task_id, split in task_keys:
        bare = summaries.get((task_id, split, "bare"))
        skill = summaries.get((task_id, split, "skill"))
        uplift = None if not bare or not skill else skill["median"] - bare["median"]
        for condition, summary in (("bare", bare), ("skill", skill)):
            if not summary:
                continue
            rows.append({
                "task_id": task_id,
                "split": split,
                "condition": condition,
                "runs": "|".join(f"{value:g}" for value in summary["runs"]),
                "median": summary["median"],
                "range": summary["range"],
                "mad": summary["mad"],
                "low_confidence": str(summary["low_confidence"]).lower(),
                "redline_count": summary["redline_count"],
                "uplift": "" if uplift is None else uplift,
            })

    args.csv_output.parent.mkdir(parents=True, exist_ok=True)
    with args.csv_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["task_id", "split", "condition", "runs", "median", "range", "mad", "low_confidence", "redline_count", "uplift"])
        writer.writeheader()
        writer.writerows(rows)

    split_metrics = {}
    for split in ("shadow", "final_holdout"):
        bare_values = [value["median"] for (task, item_split, condition), value in summaries.items() if item_split == split and condition == "bare"]
        skill_values = [value["median"] for (task, item_split, condition), value in summaries.items() if item_split == split and condition == "skill"]
        split_metrics[split] = {
            "bare_mean_of_task_medians": statistics.mean(bare_values) if bare_values else None,
            "skill_mean_of_task_medians": statistics.mean(skill_values) if skill_values else None,
            "uplift": statistics.mean(skill_values) - statistics.mean(bare_values) if bare_values and skill_values and len(bare_values) == len(skill_values) else None,
        }
    if split_metrics["shadow"]["uplift"] is not None and split_metrics["final_holdout"]["uplift"] is not None:
        split_metrics["blind_weighted_uplift"] = 0.375 * split_metrics["shadow"]["uplift"] + 0.625 * split_metrics["final_holdout"]["uplift"]
    else:
        split_metrics["blind_weighted_uplift"] = None

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(split_metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"records": len(records), "summary_rows": len(rows), "metrics": split_metrics}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
