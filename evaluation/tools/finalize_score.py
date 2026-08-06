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


def _frozen_criteria(rubric: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if rubric.get("scoring_contract") != "e1-six-dimension-v1":
        raise FinalizeError("rubric does not use the E1 scoring contract")
    criteria = rubric.get("criteria")
    if not isinstance(criteria, list):
        raise FinalizeError("rubric criteria must be an array")
    frozen: dict[str, dict[str, Any]] = {}
    total = 0.0
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise FinalizeError("rubric criteria must contain objects")
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id:
            raise FinalizeError("rubric criterion id must be a non-empty string")
        if criterion_id in frozen:
            raise FinalizeError(f"rubric repeats criterion id {criterion_id}")
        points = _finite_score(criterion.get("points"), 1_000_000, f"rubric.{criterion_id}.points")
        if points <= 0:
            raise FinalizeError(f"rubric criterion {criterion_id} points must be positive")
        frozen[criterion_id] = criterion
        total += points
    declared = _finite_score(rubric.get("evidence_points"), 1_000_000, "rubric.evidence_points")
    if not math.isclose(total, declared, rel_tol=0.0, abs_tol=1e-12):
        raise FinalizeError("rubric evidence_points do not equal the criterion maxima")
    return frozen


def _objective_metrics(report: dict[str, Any], evidence_path: str, dimensions: set[str]) -> list[dict[str, Any]]:
    metrics = []
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise FinalizeError("objective checks must be an array")
    seen: set[str] = set()
    awarded_total = 0.0
    possible_total = 0.0
    for check in checks:
        if not isinstance(check, dict):
            raise FinalizeError("objective checks must contain objects")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise FinalizeError("objective check id must be a non-empty string")
        if check_id in seen:
            raise FinalizeError(f"objective report repeats check id {check_id}")
        seen.add(check_id)
        dimension_id = check.get("dimension_id")
        if dimension_id not in dimensions:
            raise FinalizeError(f"objective check {check_id} has invalid dimension_id")
        possible = _finite_score(check.get("points_possible"), 1_000_000, "points_possible")
        if possible <= 0:
            raise FinalizeError(f"objective check {check_id} points_possible must be positive")
        awarded = _finite_score(check.get("points_awarded"), possible, "points_awarded")
        passed = check.get("passed")
        if not isinstance(passed, bool):
            raise FinalizeError(f"objective check {check_id} passed must be boolean")
        if not math.isclose(awarded, possible if passed else 0.0, rel_tol=0.0, abs_tol=1e-12):
            raise FinalizeError(f"objective check {check_id} points disagree with passed")
        awarded_total += awarded
        possible_total += possible
        metrics.append(
            {
                "metric_id": f"objective.{check_id}",
                "dimension_id": dimension_id,
                "points": possible,
                "direction": "pass_fail",
                "status": "scored",
                "value": awarded,
                "expected": possible,
                "normalized_score": round(awarded / possible * 100, 6) if possible else 0.0,
                "passed": passed,
                "evidence": [evidence_path],
                "reason": None if check.get("passed") else str(check.get("evidence", "check failed"))[:1000],
            }
        )
    declared_awarded = _finite_score(
        report.get("evidence_points_awarded"), 1_000_000, "objective.evidence_points_awarded"
    )
    declared_possible = _finite_score(
        report.get("evidence_points_possible"), 1_000_000, "objective.evidence_points_possible"
    )
    if not math.isclose(awarded_total, declared_awarded, rel_tol=0.0, abs_tol=1e-12):
        raise FinalizeError("objective awarded total does not match its checks")
    if not math.isclose(possible_total, declared_possible, rel_tol=0.0, abs_tol=1e-12):
        raise FinalizeError("objective possible total does not match its checks")
    return metrics


def _review_metrics(
    report: dict[str, Any],
    evidence_path: str,
    prefix: str,
    dimensions: set[str],
    *,
    expected_task_id: str | None = None,
    frozen_criteria: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    metrics = []
    if expected_task_id is not None and report.get("task_id") != expected_task_id:
        raise FinalizeError(f"{prefix} report task_id does not match the frozen rubric")
    criteria = report.get("criteria", [])
    if not isinstance(criteria, list):
        raise FinalizeError(f"{prefix} criteria must be an array")
    seen: set[str] = set()
    for criterion in criteria:
        if not isinstance(criterion, dict):
            raise FinalizeError(f"{prefix} criteria must contain objects")
        criterion_id = criterion.get("id")
        if not isinstance(criterion_id, str) or not criterion_id:
            raise FinalizeError(f"{prefix} criterion id must be a non-empty string")
        if criterion_id in seen:
            raise FinalizeError(f"{prefix} report repeats criterion id {criterion_id}")
        seen.add(criterion_id)
        dimension_id = criterion.get("dimension_id")
        if dimension_id not in dimensions:
            raise FinalizeError(f"{prefix} criterion {criterion_id} has invalid dimension_id")
        maximum = _finite_score(criterion.get("max"), 1_000_000, f"{prefix}.max")
        if maximum <= 0:
            raise FinalizeError(f"{prefix} criterion {criterion_id} max must be positive")
        if frozen_criteria is not None:
            frozen = frozen_criteria.get(criterion_id)
            if frozen is None:
                raise FinalizeError(f"{prefix} criterion {criterion_id} is not in the frozen rubric")
            if dimension_id != frozen.get("dimension_id"):
                raise FinalizeError(f"{prefix} criterion {criterion_id} dimension drifted from the rubric")
            if not math.isclose(maximum, float(frozen["points"]), rel_tol=0.0, abs_tol=1e-12):
                raise FinalizeError(f"{prefix} criterion {criterion_id} max drifted from the rubric")
        score = _finite_score(criterion.get("score"), maximum, f"{prefix}.score")
        evidence = criterion.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise FinalizeError(f"{prefix} criterion {criterion_id} must cite evidence")
        for index, item in enumerate(evidence):
            if not isinstance(item, str):
                raise FinalizeError(f"{prefix} criterion {criterion_id} evidence must be strings")
            _safe_relative(item, f"{prefix}.{criterion_id}.evidence[{index}]")
        reason = criterion.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise FinalizeError(f"{prefix} criterion {criterion_id} reason must be non-empty")
        metrics.append(
            {
                "metric_id": f"{prefix}.{criterion_id}",
                "dimension_id": dimension_id,
                "points": maximum,
                "direction": "higher_better",
                "status": "scored",
                "value": score,
                "expected": maximum,
                "normalized_score": round(score / maximum * 100, 6) if maximum else 0.0,
                "passed": score == maximum,
                "evidence": [evidence_path],
                "reason": reason[:1000],
            }
        )
    if frozen_criteria is not None and seen != set(frozen_criteria):
        missing = sorted(set(frozen_criteria) - seen)
        raise FinalizeError(f"{prefix} report is missing frozen criteria: {missing}")
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
    rubric = _load(rubric_path)
    if objective.get("scoring_contract") != "e1-six-dimension-v1":
        raise FinalizeError("objective report does not use the E1 scoring contract")
    if objective.get("task_id") != rubric.get("task_id"):
        raise FinalizeError("objective report task_id does not match the frozen rubric")
    frozen_criteria = _frozen_criteria(rubric)
    redline_events = objective.get("redline_events")
    if not isinstance(redline_events, list):
        raise FinalizeError("objective redline_events must be an array")
    expected_hard_gate = not any(
        isinstance(event, dict)
        and event.get("consequence") in {"task_zero", "acceptance_fail"}
        for event in redline_events
    )
    if objective.get("hard_gate_passed") is not expected_hard_gate:
        raise FinalizeError("objective hard gate disagrees with its redline events")
    metrics = _objective_metrics(objective, _safe_relative(objective_evidence, "objective_evidence"), dimension_ids)
    review_pending = False
    if llm_path:
        llm_report = _load(llm_path)
        if llm_report.get("grader_uncertainty") not in {"low", "medium", "high"}:
            raise FinalizeError("llm grader_uncertainty is invalid")
        if not isinstance(llm_report.get("human_review_required"), bool):
            raise FinalizeError("llm human_review_required must be boolean")
        redline_candidates = llm_report.get("redline_candidates")
        if not isinstance(redline_candidates, list):
            raise FinalizeError("llm redline_candidates must be an array")
        if redline_candidates and not llm_report["human_review_required"]:
            raise FinalizeError("llm redline candidates require human review")
        if llm_report["grader_uncertainty"] == "high" and not llm_report["human_review_required"]:
            raise FinalizeError("high LLM grader uncertainty requires human review")
        metrics.extend(
            _review_metrics(
                llm_report,
                _safe_relative(llm_evidence, "llm_evidence"),
                "llm",
                dimension_ids,
                expected_task_id=str(rubric.get("task_id")),
                frozen_criteria=frozen_criteria,
            )
        )
        review_pending = llm_report["human_review_required"]
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

    if review_pending:
        return {
            "schema_version": "1.0.0",
            "eval_version": alignment["e1_eval_version"],
            "contract_sha256": alignment["e1_contract_sha256"],
            "run_id": run_id,
            "scorer_version": SCORER_VERSION,
            "rubric_sha256": _sha256(rubric_path),
            "candidate_status": candidate_status,
            "score_status": "not_scored",
            "hard_gate_passed": True,
            "dimensions": [],
            "total_score": None,
            "checks_path": _safe_relative(objective_evidence, "checks_path"),
            "evidence": sorted({item for metric in metrics for item in metric["evidence"]}),
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
