#!/usr/bin/env python3
"""Aggregate a complete E1 B0/S0 campaign from finalized score objects."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT_PATH = ROOT / "contracts" / "benchmark-execution-contract.json"


class AggregateError(ValueError):
    """Raw run evidence is incomplete or violates the frozen E1 campaign."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite(value: Any, field: str, minimum: float = 0, maximum: float = 100) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise AggregateError(f"{field} must be a finite number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise AggregateError(f"{field} must be between {minimum} and {maximum}")
    return result


def _mad(values: list[float]) -> float:
    center = statistics.median(values)
    return statistics.median(abs(value - center) for value in values)


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "runs": values,
        "median": statistics.median(values) if values else None,
        "range": max(values) - min(values) if values else None,
        "mad": _mad(values) if values else None,
        "low_confidence": (max(values) - min(values) > 20) if values else True,
    }


def _validate_record(record: dict[str, Any], alignment: dict[str, Any], dimensions: dict[str, float]) -> dict[str, Any]:
    required = {"run_id", "task_id", "split", "variant", "repeat", "pair_fingerprint", "status", "exit_code", "score"}
    missing = sorted(required - set(record))
    if missing:
        raise AggregateError(f"run record missing fields: {missing}")
    if record["variant"] not in {"B0", "S0"} or record["repeat"] not in {1, 2, 3}:
        raise AggregateError(f"{record['run_id']}: variant/repeat must be B0|S0 and 1..3")
    if record["split"] not in {"public", "shadow", "final_holdout"}:
        raise AggregateError(f"{record['run_id']}: invalid split")
    exit_meanings = {int(key): value for key, value in alignment["exit_codes"].items()}
    if record["exit_code"] not in exit_meanings:
        raise AggregateError(f"{record['run_id']}: exit code is outside E1")
    expected_status = {
        0: "success", 2: "partial_success", 71: "timed_out", 72: "resource_exceeded", 76: "cancelled"
    }.get(record["exit_code"], "failed")
    if record["status"] != expected_status:
        raise AggregateError(f"{record['run_id']}: status and E1 exit_code disagree")
    score = record["score"]
    if not isinstance(score, dict) or score.get("contract_sha256") != alignment["e1_contract_sha256"]:
        raise AggregateError(f"{record['run_id']}: score is not bound to the frozen E1 contract")
    if score.get("run_id") != record["run_id"] or score.get("candidate_status") != record["status"]:
        raise AggregateError(f"{record['run_id']}: score identity/status mismatch")
    score_status = score.get("score_status")
    total = score.get("total_score")
    if score_status in {"complete", "partial"}:
        total_value = _finite(total, f"{record['run_id']}.total_score")
        if not score.get("hard_gate_passed"):
            raise AggregateError(f"{record['run_id']}: scored run failed the E1 hard gate")
    elif score_status in {"not_scored", "ineligible"}:
        if total is not None:
            raise AggregateError(f"{record['run_id']}: unscored run exposes total_score")
        total_value = None
    else:
        raise AggregateError(f"{record['run_id']}: invalid score_status")
    dimension_scores: dict[str, float] = {}
    if score_status in {"complete", "partial"}:
        supplied = score.get("dimensions")
        if not isinstance(supplied, list) or {item.get("dimension_id") for item in supplied if isinstance(item, dict)} != set(dimensions):
            raise AggregateError(f"{record['run_id']}: score must contain the exact six E1 dimensions")
        for item in supplied:
            if item.get("weight") != dimensions[item["dimension_id"]]:
                raise AggregateError(f"{record['run_id']}: E1 dimension weight drift")
            value = _finite(item.get("score"), f"{record['run_id']}.{item['dimension_id']}")
            metrics = item.get("metrics")
            dimension_fully_scored = (
                isinstance(metrics, list)
                and bool(metrics)
                and all(isinstance(metric, dict) and metric.get("status") == "scored" for metric in metrics)
            )
            if score_status == "complete" and not dimension_fully_scored:
                raise AggregateError(f"{record['run_id']}: complete score has an unscored E1 dimension")
            if dimension_fully_scored:
                dimension_scores[item["dimension_id"]] = value
    return {**record, "total": total_value, "dimension_scores": dimension_scores}


def aggregate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    alignment = _load(ALIGNMENT_PATH)
    dimensions = {item["dimension_id"]: item["weight"] for item in alignment["dimensions"]}
    if not records:
        raise AggregateError("raw run file is empty")
    normalized = [_validate_record(record, alignment, dimensions) for record in records]
    run_ids = [record["run_id"] for record in normalized]
    if len(run_ids) != len(set(run_ids)):
        raise AggregateError("run_id values must be unique")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in normalized:
        grouped[(record["task_id"], record["split"])].append(record)
    rows = []
    task_results = []
    for (task_id, split), members in sorted(grouped.items()):
        slots = {(item["variant"], item["repeat"]) for item in members}
        expected_slots = {(variant, repeat) for variant in ("B0", "S0") for repeat in (1, 2, 3)}
        if slots != expected_slots or len(members) != 6:
            raise AggregateError(f"{task_id}: campaign must contain exactly B0/S0 x repeats 1..3")
        for repeat in (1, 2, 3):
            pair = [item for item in members if item["repeat"] == repeat]
            if len({item["pair_fingerprint"] for item in pair}) != 1:
                raise AggregateError(f"{task_id} repeat {repeat}: B0/S0 pair_fingerprint mismatch")
        by_variant = {variant: sorted((item for item in members if item["variant"] == variant), key=lambda item: item["repeat"]) for variant in ("B0", "S0")}
        variant_summaries = {}
        for variant, items in by_variant.items():
            values = [item["total"] for item in items if item["total"] is not None]
            summary = _summary(values)
            summary["scored_runs"] = len(values)
            summary["run_count"] = len(items)
            variant_summaries[variant] = summary
            rows.append(
                {
                    "task_id": task_id,
                    "split": split,
                    "variant": variant,
                    "runs": "|".join("NA" if item["total"] is None else f"{item['total']:g}" for item in items),
                    "median": summary["median"],
                    "range": summary["range"],
                    "mad": summary["mad"],
                    "low_confidence": str(summary["low_confidence"]).lower(),
                    "scored_runs": summary["scored_runs"],
                    "uplift": "",
                }
            )
        b0 = variant_summaries["B0"]["median"] if variant_summaries["B0"]["scored_runs"] == 3 else None
        s0 = variant_summaries["S0"]["median"] if variant_summaries["S0"]["scored_runs"] == 3 else None
        uplift = None if b0 is None or s0 is None else s0 - b0
        rows[-2]["uplift"] = "" if uplift is None else uplift
        rows[-1]["uplift"] = "" if uplift is None else uplift
        task_results.append({"task_id": task_id, "split": split, "variants": variant_summaries, "uplift": uplift})

    split_metrics: dict[str, Any] = {}
    dimension_metrics: dict[str, Any] = {}
    for split in ("public", "shadow", "final_holdout"):
        tasks = [item for item in task_results if item["split"] == split]
        if not tasks:
            continue
        b0 = [item["variants"]["B0"]["median"] for item in tasks if item["variants"]["B0"]["median"] is not None]
        s0 = [item["variants"]["S0"]["median"] for item in tasks if item["variants"]["S0"]["median"] is not None]
        uplifts = [item["uplift"] for item in tasks if item["uplift"] is not None]
        split_metrics[split] = {
            "task_count": len(tasks),
            "b0_mean_of_task_medians": statistics.mean(b0) if len(b0) == len(tasks) else None,
            "s0_mean_of_task_medians": statistics.mean(s0) if len(s0) == len(tasks) else None,
            "mean_uplift": statistics.mean(uplifts) if len(uplifts) == len(tasks) else None,
        }
        split_dimensions: dict[str, Any] = {}
        for dimension_id, weight in dimensions.items():
            b0_medians: list[float] = []
            s0_medians: list[float] = []
            dimension_uplifts: list[float] = []
            for (task_id, task_split), members in sorted(grouped.items()):
                if task_split != split:
                    continue
                b0_values = [
                    item["dimension_scores"][dimension_id]
                    for item in members
                    if item["variant"] == "B0" and dimension_id in item["dimension_scores"]
                ]
                s0_values = [
                    item["dimension_scores"][dimension_id]
                    for item in members
                    if item["variant"] == "S0" and dimension_id in item["dimension_scores"]
                ]
                if len(b0_values) == 3 and len(s0_values) == 3:
                    b0_median = statistics.median(b0_values)
                    s0_median = statistics.median(s0_values)
                    b0_medians.append(b0_median)
                    s0_medians.append(s0_median)
                    dimension_uplifts.append(s0_median - b0_median)
            split_dimensions[dimension_id] = {
                "weight": weight,
                "complete_task_pairs": len(dimension_uplifts),
                "b0_mean_of_task_medians": statistics.mean(b0_medians) if len(b0_medians) == len(tasks) else None,
                "s0_mean_of_task_medians": statistics.mean(s0_medians) if len(s0_medians) == len(tasks) else None,
                "mean_uplift": statistics.mean(dimension_uplifts) if len(dimension_uplifts) == len(tasks) else None,
            }
        dimension_metrics[split] = split_dimensions
    complete_scores = sum(record["score"].get("score_status") == "complete" for record in normalized)
    return rows, {
        "schema_version": "e2.e1-campaign-aggregate.v1",
        "e1_contract_sha256": alignment["e1_contract_sha256"],
        "records": len(normalized),
        "complete_score_records": complete_scores,
        "official_ready": complete_scores == len(normalized),
        "tasks": task_results,
        "split_metrics": split_metrics,
        "dimension_metrics": dimension_metrics,
        "descriptive_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_jsonl", type=Path)
    parser.add_argument("--csv-output", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        records = [json.loads(line) for line in args.raw_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows, summary = aggregate(records)
        args.csv_output.parent.mkdir(parents=True, exist_ok=True)
        with args.csv_output.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["task_id", "split", "variant", "runs", "median", "range", "mad", "low_confidence", "scored_runs", "uplift"])
            writer.writeheader()
            writer.writerows(rows)
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (AggregateError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"artifact error: {exc}", file=sys.stderr)
        return 74
    print(json.dumps({"records": summary["records"], "tasks": len(summary["tasks"]), "status": "PASS"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
