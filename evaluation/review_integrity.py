"""Integrity envelope for independent evaluation review evidence."""

from __future__ import annotations

import re
from typing import Any


REVIEW_SCHEMA = "ai4s-bound-llm-review-v1"
BINDING_SCHEMA = "ai4s-evaluation-review-binding-v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BINDING_FIELDS = {
    "schema_version",
    "run_id",
    "question_id",
    "rubric_task_id",
    "condition",
    "repeat",
    "pair_fingerprint",
    "task_bundle_sha256",
    "submission_artifacts_sha256",
    "objective_report_sha256",
    "rubric_sha256",
    "frozen_skill_sha256",
    "grader_protocol_sha256",
}
REPORT_FIELDS = {
    "schema_version",
    "review_type",
    "run_binding",
    "reviewer",
    "task_id",
    "criteria",
    "redline_candidates",
    "grader_uncertainty",
    "human_review_required",
}


class ReviewIntegrityError(ValueError):
    """Review evidence is stale, ambiguous, or not bound to the current run."""


def validate_binding(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != BINDING_FIELDS:
        raise ReviewIntegrityError(
            "review binding fields do not match the frozen schema"
        )
    if value.get("schema_version") != BINDING_SCHEMA:
        raise ReviewIntegrityError("unsupported review binding schema")
    for field in (
        "run_id",
        "question_id",
        "rubric_task_id",
        "condition",
    ):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ReviewIntegrityError(f"review binding {field} must be non-empty")
    if value["condition"] not in {"B0", "S0"}:
        raise ReviewIntegrityError("review binding condition must be B0 or S0")
    if value.get("repeat") not in {1, 2, 3}:
        raise ReviewIntegrityError("review binding repeat must be 1..3")
    for field in BINDING_FIELDS - {
        "schema_version",
        "run_id",
        "question_id",
        "rubric_task_id",
        "condition",
        "repeat",
    }:
        if not isinstance(value.get(field), str) or not SHA256.fullmatch(value[field]):
            raise ReviewIntegrityError(
                f"review binding {field} must be lowercase SHA-256"
            )
    return value


def validate_llm_review_envelope(
    value: Any, expected_binding: dict[str, Any]
) -> dict[str, Any]:
    validate_binding(expected_binding)
    if not isinstance(value, dict) or set(value) != REPORT_FIELDS:
        raise ReviewIntegrityError("LLM review fields do not match the frozen envelope")
    if (
        value.get("schema_version") != REVIEW_SCHEMA
        or value.get("review_type") != "llm"
    ):
        raise ReviewIntegrityError("unsupported LLM review envelope")
    binding = validate_binding(value.get("run_binding"))
    if binding != expected_binding:
        raise ReviewIntegrityError("LLM review binding does not match the current run")
    if value.get("task_id") != expected_binding["rubric_task_id"]:
        raise ReviewIntegrityError(
            "LLM review task_id does not match the current rubric"
        )
    reviewer = value.get("reviewer")
    if not isinstance(reviewer, dict) or set(reviewer) != {
        "id",
        "model",
        "prompt_sha256",
    }:
        raise ReviewIntegrityError(
            "LLM reviewer identity fields do not match the frozen schema"
        )
    for field in ("id", "model"):
        if not isinstance(reviewer.get(field), str) or not reviewer[field].strip():
            raise ReviewIntegrityError(f"LLM reviewer {field} must be non-empty")
    if reviewer.get("prompt_sha256") != expected_binding["grader_protocol_sha256"]:
        raise ReviewIntegrityError(
            "LLM reviewer prompt is not the frozen grader protocol"
        )
    return value
