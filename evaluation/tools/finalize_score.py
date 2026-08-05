#!/usr/bin/env python3
"""Combine E2 evidence into an E1 score.json without inventing missing dimensions."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCORER_VERSION = "6.0.0"
ROOT = Path(__file__).resolve().parents[1]
ALIGNMENT_PATH = ROOT / "contracts" / "benchmark-execution-contract.json"


class FinalizeError(ValueError):
    """The supplied evidence cannot produce a contract-safe score."""


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_relative(value: str, field: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or not value:
        raise FinalizeError(f"{field} must be a safe relative path")
    return path.as_posix()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _finite_score(value: Any, maximum: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise FinalizeError(f"{field} must be a finite number")
    result = float(value)
    if result < 0 or result > maximum:
        raise FinalizeError(f"{field} must be between 0 and {maximum}")
    return result


def _objective_metrics(report: dict[str, Any], evidence_path: str, dimensions: set[str]) -> list[dict[str, Any]]:
    metrics = []
    for check in report.get("checks", []):
        dimension_id = check.get("dimension_id")
        if dimension_id not in dimensions:
            raise FinalizeError(f"objective check {check.get('id')} has invalid dimension_id")
        possible = _finite_score(check.get("points_possible"), 1_000_000, "points_possible")
        awarded = _finite_score(check.get("points_awarded"), possible, "points_awarded")
        metrics.append(
            {
                "metric_id": f"objective.{check['id']}",
                "dimension_id": dimension_id,
                "points": possible,
                "direction": "pass_fail",
                "status": "scored",
                "value": awarded,
                "expected": possible,
                "normalized_score": round(awarded / possible * 100, 6) if possible else 0.0,
                "passed": bool(check.get("passed")),
                "evidence": [evidence_path],
                "reason": None if check.get("passed") else str(check.get("evidence", "check failed"))[:1000],
            }
        )
    return metrics


def _review_metrics(report: dict[str, Any], evidence_path: str, prefix: str, dimensions: set[str]) -> list[dict[str, Any]]:
    metrics = []
    criteria = report.get("criteria", [])
    if not isinstance(criteria, list):
        raise FinalizeError(f"{prefix} criteria must be an array")
    for criterion in criteria:
        dimension_id = criterion.get("dimension_id")
        if dimension_id not in dimensions:
            raise FinalizeError(f"{prefix} criterion {criterion.get('id')} has invalid dimension_id")
        maximum = _finite_score(criterion.get("max"), 1_000_000, f"{prefix}.max")
        score = _finite_score(criterion.get("score"), maximum, f"{prefix}.score")
        metrics.append(
            {
                "metric_id": f"{prefix}.{criterion['id']}",
                "dimension_id": dimension_id,
                "points": maximum,
                "direction": "higher_better",
                "status": "scored",
                "value": score,
                "expected": maximum,
                "normalized_score": round(score / maximum * 100, 6) if maximum else 0.0,
                "passed": score == maximum,
                "evidence": [evidence_path],
                "reason": str(criterion.get("reason"))[:1000] if criterion.get("reason") else None,
            }
        )
    return metrics


def finalize(
    *,
    objective_path: Path,
    rubric_path: Path,
    run_id: str,
    candidate_status: str,
    objective_evidence: str,
    llm_path: Path | None = None,
    llm_evidence: str = "llm_grader_report.json",
    static_path: Path | None = None,
    static_evidence: str = "static_review.json",
) -> dict[str, Any]:
    alignment = _load(ALIGNMENT_PATH)
    dimension_specs = {item["dimension_id"]: item for item in alignment["dimensions"]}
    dimension_ids = set(dimension_specs)
    objective = _load(objective_path)
    if objective.get("scoring_contract") != "e1-six-dimension-v1":
        raise FinalizeError("objective report does not use the E1 scoring contract")
    metrics = _objective_metrics(objective, _safe_relative(objective_evidence, "objective_evidence"), dimension_ids)
    if llm_path:
        metrics.extend(_review_metrics(_load(llm_path), _safe_relative(llm_evidence, "llm_evidence"), "llm", dimension_ids))
    if static_path:
        metrics.extend(_review_metrics(_load(static_path), _safe_relative(static_evidence, "static_evidence"), "static", dimension_ids))

    hard_gate = bool(objective.get("hard_gate_passed")) and candidate_status in {"success", "partial_success"}
    if not hard_gate:
        return {
            "schema_version": "1.0.0",
            "eval_version": alignment["e1_eval_version"],
            "contract_sha256": alignment["e1_contract_sha256"],
            "run_id": run_id,
            "scorer_version": SCORER_VERSION,
            "rubric_sha256": _sha256(rubric_path),
            "candidate_status": candidate_status,
            "score_status": "ineligible",
            "hard_gate_passed": False,
            "dimensions": [],
            "total_score": None,
            "checks_path": _safe_relative(objective_evidence, "checks_path"),
            "evidence": sorted({item for metric in metrics for item in metric["evidence"]}) or [_safe_relative(objective_evidence, "evidence")],
            "computed_at": _timestamp(),
        }

    dimensions = []
    missing = False
    for dimension_id, spec in dimension_specs.items():
        members = [dict(metric) for metric in metrics if metric["dimension_id"] == dimension_id]
        possible = sum(metric.pop("points") for metric in members)
        if not members or possible <= 0:
            missing = True
            body_metrics = [
                {
                    "metric_id": f"{dimension_id}.missing_evidence",
                    "direction": "pass_fail",
                    "weight": 1.0,
                    "status": "not_scored",
                    "value": None,
                    "expected": True,
                    "normalized_score": None,
                    "passed": None,
                    "evidence": [_safe_relative(objective_evidence, "evidence")],
                    "reason": "No frozen metric evidence was supplied for this E1 dimension.",
                }
            ]
            score = 0.0
        else:
            body_metrics = []
            for metric in members:
                metric.pop("dimension_id")
                metric["weight"] = 0.0
                body_metrics.append(metric)
            # Weight by the frozen evidence point maxima retained in each metric's expected field.
            denominators = [float(metric["expected"]) for metric in body_metrics]
            denominator = sum(denominators)
            for metric, value in zip(body_metrics, denominators):
                metric["weight"] = round(value / denominator, 12)
            score = round(sum(metric["weight"] * float(metric["normalized_score"]) for metric in body_metrics), 6)
        dimensions.append(
            {
                "dimension_id": dimension_id,
                "direction": "higher_better",
                "weight": spec["weight"],
                "score": score,
                "metrics": body_metrics,
            }
        )

    if any(event.get("consequence") == "task_cap_20" for event in objective.get("redline_events", [])):
        for dimension in dimensions:
            if dimension["dimension_id"] == "scientific_credibility":
                dimension["score"] = min(dimension["score"], 20.0)
    total = round(sum(item["score"] * item["weight"] for item in dimensions), 6)
    return {
        "schema_version": "1.0.0",
        "eval_version": alignment["e1_eval_version"],
        "contract_sha256": alignment["e1_contract_sha256"],
        "run_id": run_id,
        "scorer_version": SCORER_VERSION,
        "rubric_sha256": _sha256(rubric_path),
        "candidate_status": candidate_status,
        "score_status": "partial" if missing else "complete",
        "hard_gate_passed": True,
        "dimensions": dimensions,
        "total_score": total,
        "checks_path": _safe_relative(objective_evidence, "checks_path"),
        "evidence": sorted({item for metric in metrics for item in metric["evidence"]}) or [_safe_relative(objective_evidence, "evidence")],
        "computed_at": _timestamp(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--objective-report", required=True, type=Path)
    parser.add_argument("--rubric", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--candidate-status", required=True, choices=("success", "partial_success", "failed", "timed_out", "resource_exceeded", "cancelled"))
    parser.add_argument("--objective-evidence", default="objective_report.json")
    parser.add_argument("--llm-report", type=Path)
    parser.add_argument("--llm-evidence", default="llm_grader_report.json")
    parser.add_argument("--static-review", type=Path)
    parser.add_argument("--static-evidence", default="static_review.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        score = finalize(
            objective_path=args.objective_report.resolve(),
            rubric_path=args.rubric.resolve(),
            run_id=args.run_id,
            candidate_status=args.candidate_status,
            objective_evidence=args.objective_evidence,
            llm_path=args.llm_report.resolve() if args.llm_report else None,
            llm_evidence=args.llm_evidence,
            static_path=args.static_review.resolve() if args.static_review else None,
            static_evidence=args.static_evidence,
        )
        _atomic_json(args.output, score)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, FinalizeError) as exc:
        print(f"scorer error: {exc}")
        return 75
    print(json.dumps({"status": "scored", "run_id": score["run_id"], "score_status": score["score_status"], "total_score": score["total_score"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
