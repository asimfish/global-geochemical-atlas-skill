#!/usr/bin/env python3
"""Resumable atlas-to-research controller with hash-bound agent stages.

The controller performs deterministic preparation itself and exposes fresh,
model-neutral packets for the genuinely model-authored stages.  It never calls
an unconfigured model and never invents a paper.  Direction selection is the
only human decision: after it, the run always terminates autonomously in a
packaged final deliverable — a camera-ready paper when every review gate
passes, a draft with disclosed reviewer findings when the revision budget is
spent, or a deterministic redirect to the next ranked empirical candidate when
the evidence cannot support the selected direction.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import claim_ledger
import publication_lint
import validate_outputs

SCRIPT_DIR = Path(__file__).resolve().parent
BUILD_RESEARCH_PRODUCTS = SCRIPT_DIR / "build_research_products.py"
BUILD_DISCOVERY_CANDIDATES = SCRIPT_DIR / "build_discovery_candidates.py"
STATE_VERSION = "gga-auto-research-state-v3"
PUBLICATION_GRADES = ("camera_ready", "draft_with_disclosed_findings")
REQUEST_VERSION = "gga-auto-research-request-v1"
PACKET_VERSION = "gga-auto-research-agent-packet-v2"
RESULT_VERSION = "gga-auto-research-agent-result-v2"
SNAPSHOT_VERSION = "gga-auto-research-atlas-snapshot-v1"
ROLES = (
    "pilot_analyst",
    "literature_researcher",
    "manuscript_writer",
    "figure_designer",
    "citation_auditor",
    "independent_reviewer",
)
FIRST_WAVE = ("pilot_analyst", "literature_researcher")
SECOND_WAVE = ("manuscript_writer", "figure_designer")
CITATION_VERDICTS = {"verified", "mismatch", "unverifiable"}
CITATION_CHECK_FIELDS = (
    "title_match",
    "authors_match",
    "author_order_match",
    "year_match",
    "venue_match",
    "identifier_resolves",
)
REFERENCE_IDENTIFIER_TYPES = {"doi", "arxiv", "official_url"}
MINIMUM_LITERATURE_CANDIDATES_SCREENED = 8
INITIAL_CYCLE = "initial"
MAX_REVISION_ROUNDS = 3
MAX_AGENT_ARTIFACT_BYTES = 50_000_000
PILOT_OUTCOMES = {
    "supported_effect",
    "supported_null",
    "unsupported_inputs",
    "acquisition_required",
    "invalid_analysis",
}
PAPER_ELIGIBLE_PILOT_OUTCOMES = {"supported_effect", "supported_null"}
FRONTIER_STATUSES = {
    "supports_empirical_article",
    "weak_frontier_position",
    "needs_verification",
}
REVIEW_GATE_CONTRACT = (
    ("a1", "evidence_integrity"),
    ("a2", "scientific_validity"),
    ("a3", "novelty_and_significance"),
    ("a4", "frontier_and_venue_fit"),
    ("a5", "manuscript_argument_and_contribution"),
    ("a6", "figure_evidence_and_visual_quality"),
    ("a7", "reproducibility_and_release"),
)
REVIEW_GATE_NAMES = dict(REVIEW_GATE_CONTRACT)
# Revision feedback routes to the role that owns the failing gate. Gates whose
# evidence spans both deliverables reopen both roles; an unknown gate fails
# safe by reopening both.
GATE_OWNER_ROLES = {
    "citation_audit": ("manuscript_writer",),
    "a1": ("manuscript_writer", "figure_designer"),
    "a2": ("manuscript_writer", "figure_designer"),
    "a3": ("manuscript_writer",),
    "a4": ("manuscript_writer",),
    "a5": ("manuscript_writer",),
    "a6": ("figure_designer",),
    "a7": ("manuscript_writer", "figure_designer"),
}
REQUIRED_EMPIRICAL_FIGURE_ROLES = {
    "primary_result",
    "spatial_pattern",
    "robustness_or_external_validation",
}


class AutoResearchError(RuntimeError):
    """Raised when the research state or an agent boundary fails closed."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AutoResearchError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AutoResearchError(f"{path} must contain a JSON object")
    return value


def _append_event(run_dir: Path, event: str, detail: Mapping[str, Any]) -> None:
    record = {
        "schema_version": "gga-auto-research-event-v1",
        "sequence": sum(
            1 for _ in (run_dir / "events.jsonl").open("r", encoding="utf-8")
        )
        + 1
        if (run_dir / "events.jsonl").is_file()
        else 1,
        "at": utc_now(),
        "event": event,
        "detail": dict(detail),
    }
    with (run_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"question", "candidate_id", "output_language", "target_venue"}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise AutoResearchError(
            "unknown research request fields: " + ", ".join(unknown)
        )
    question = str(raw.get("question") or "").strip()
    if len(question) > 2000 or "\x00" in question:
        raise AutoResearchError("question must be at most 2000 safe characters")
    candidate_id = str(raw.get("candidate_id") or "").strip() or None
    if candidate_id is not None and re.fullmatch(r"dc-\d{3}", candidate_id) is None:
        raise AutoResearchError("candidate_id must have the form dc-NNN")
    language = str(raw.get("output_language") or "zh-CN")
    if language not in {"zh-CN", "en"}:
        raise AutoResearchError("output_language must be zh-CN or en")
    venue = str(raw.get("target_venue") or "").strip()
    if len(venue) > 200 or "\x00" in venue:
        raise AutoResearchError("target_venue must be at most 200 safe characters")
    if not question and candidate_id is None:
        selection_mode = "candidate_selection_required"
    elif candidate_id is not None:
        selection_mode = "deterministic_candidate"
    else:
        selection_mode = "user_question"
    return {
        "schema_version": REQUEST_VERSION,
        "question": question or None,
        "candidate_id": candidate_id,
        "output_language": language,
        "target_venue": venue or None,
        "selection_mode": selection_mode,
    }


def _regular_file(path: Path, label: str) -> Path:
    if path.is_symlink() or not path.is_file():
        raise AutoResearchError(f"{label} must be a regular file: {path}")
    return path


def _reject_symlink_components(root: Path, candidate: Path, label: str) -> None:
    """Reject every symlink in a lexically root-relative path.

    Calling ``resolve()`` first is insufficient because it erases the evidence
    that a path traversed a symbolic link.  This check intentionally runs on
    the lexical path before the resolved containment check.
    """

    lexical_root = root.absolute()
    lexical_candidate = candidate.absolute()
    try:
        relative = lexical_candidate.relative_to(lexical_root)
    except ValueError as exc:
        raise AutoResearchError(f"{label} is outside the allowed root") from exc
    cursor = lexical_root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise AutoResearchError(f"{label} traverses a symbolic link: {cursor}")


def build_atlas_snapshot(atlas_dir: Path) -> dict[str, Any]:
    validation = validate_outputs.validate_dir(atlas_dir)
    if validation.get("status") != "valid":
        raise AutoResearchError(
            "atlas output validation failed: "
            + "; ".join(str(item) for item in validation.get("errors", []))
        )
    files: dict[str, dict[str, Any]] = {}
    for filename in sorted(validate_outputs.REQUIRED_FILES.values()):
        path = _regular_file(atlas_dir / filename, filename)
        files[filename] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    ledger = claim_ledger.build_claim_ledger(atlas_dir)
    body = {
        "schema_version": SNAPSHOT_VERSION,
        "files": files,
        "claim_ledger": ledger,
        "validation_status": "valid",
        "claim_boundary": (
            "This snapshot freezes existing atlas bytes for downstream research. "
            "It does not upgrade screening results to causal conclusions."
        ),
    }
    return {**body, "snapshot_sha256": sha256_bytes(canonical_json_bytes(body))}


def _copy_projection(atlas_dir: Path, run_dir: Path) -> Path:
    projection = run_dir / "atlas_snapshot_files"
    projection.mkdir(parents=True, exist_ok=True)
    for filename in (
        "geochemistry.csv",
        "sources_and_confidence.json",
        "run_summary.json",
    ):
        shutil.copy2(
            _regular_file(atlas_dir / filename, filename), projection / filename
        )
    queue_path = atlas_dir / "d1_repair_queue.json"
    if queue_path.is_file() and not queue_path.is_symlink():
        shutil.copy2(queue_path, projection / queue_path.name)
    else:
        _write_json(
            projection / "d1_repair_queue.json",
            {
                "queue_version": "auto-research-empty-projection-v1",
                "status": "not_available_from_core_only_atlas",
                "tasks": [],
                "claim_boundary": (
                    "No loop repair queue was present. This projection adds no inferred gaps; "
                    "research remains exploratory until formal delivery evidence is available."
                ),
            },
        )
    return projection


def _run_checked(arguments: Sequence[str], *, timeout: float = 180.0) -> None:
    result = subprocess.run(
        list(arguments),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AutoResearchError(
            f"deterministic research stage failed ({result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )


def _materialize_deterministic_products(
    atlas_dir: Path, run_dir: Path
) -> dict[str, Any]:
    projection = _copy_projection(atlas_dir, run_dir)
    products = run_dir / "deterministic"
    products.mkdir(parents=True, exist_ok=True)
    _run_checked(
        [
            sys.executable,
            str(BUILD_RESEARCH_PRODUCTS),
            "--output-dir",
            str(projection),
            "--research-dir",
            str(products),
            "--minimum-confidence",
            "medium",
        ]
    )
    _run_checked(
        [
            sys.executable,
            str(BUILD_DISCOVERY_CANDIDATES),
            "--research-dir",
            str(products),
            "--output-dir",
            str(products),
        ]
    )
    candidates = _read_object(products / "discovery_candidates.json")
    return candidates


def _select_candidate(
    request: Mapping[str, Any], candidates_document: Mapping[str, Any]
) -> dict[str, Any] | None:
    candidates = candidates_document.get("discovery_candidates")
    if not isinstance(candidates, list):
        raise AutoResearchError("discovery_candidates.json lacks candidates")
    requested_id = request.get("candidate_id")
    if requested_id:
        selected = next(
            (
                dict(item)
                for item in candidates
                if isinstance(item, Mapping)
                and item.get("candidate_id") == requested_id
            ),
            None,
        )
        if selected is None:
            raise AutoResearchError(f"unknown candidate_id: {requested_id}")
        return selected
    if request.get("question"):
        return {
            "candidate_id": "user-question",
            "type": "user_defined_screening_question",
            "title": str(request["question"])[:240],
            "question": request["question"],
            "evidence": [],
            "suggested_design": (
                "Resolve the question to analysis_cohorts.csv before analysis; fail closed "
                "if no comparable cohort supports it."
            ),
            "expected_products": ["pilot result", "evidence gaps", "screening paper"],
            "caveats": "User question is not evidence and may be unsupported by the snapshot.",
        }
    return None


def _input_binding(run_dir: Path, path: Path) -> dict[str, Any]:
    resolved_run = run_dir.resolve(strict=True)
    _reject_symlink_components(resolved_run, path, "agent input")
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(resolved_run):
        raise AutoResearchError(f"agent input escapes the run directory: {path}")
    return {
        "path": resolved.relative_to(resolved_run).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def _cycle_root(run_dir: Path, cycle_id: str) -> Path:
    if cycle_id == INITIAL_CYCLE:
        return run_dir
    if re.fullmatch(r"revision-[0-9]{2}", cycle_id) is None:
        raise AutoResearchError(f"invalid research cycle: {cycle_id}")
    return run_dir / "revisions" / cycle_id


def _role_root(run_dir: Path, cycle_id: str, role: str) -> Path:
    return _cycle_root(run_dir, cycle_id) / "agents" / role


def _artifact_root(run_dir: Path, cycle_id: str, role: str) -> Path:
    return _cycle_root(run_dir, cycle_id) / "agent_outputs" / role


def _write_packet(
    run_dir: Path,
    *,
    role: str,
    purpose: str,
    inputs: Mapping[str, Path],
    required_output: Mapping[str, Any],
    cycle_id: str = INITIAL_CYCLE,
) -> dict[str, Any]:
    if role not in ROLES:
        raise AutoResearchError(f"unsupported research role: {role}")
    packet_path = _role_root(run_dir, cycle_id, role) / "packet.json"
    if packet_path.exists():
        return _read_object(packet_path)
    bindings = {
        key: _input_binding(run_dir, path) for key, path in sorted(inputs.items())
    }
    body = {
        "schema_version": PACKET_VERSION,
        "run_id": run_dir.name,
        "cycle_id": cycle_id,
        "role": role,
        "fresh_session_required": True,
        "previous_review_allowed": cycle_id != INITIAL_CYCLE and role in SECOND_WAVE,
        "executor_summary_allowed": False,
        "purpose": purpose,
        "allowed_inputs": bindings,
        "required_output": dict(required_output),
        "artifact_output_dir": _artifact_root(run_dir, cycle_id, role)
        .relative_to(run_dir)
        .as_posix(),
        "claim_boundary": (
            "Only listed inputs may be used. Numerical claims require a claim-ledger ID "
            "or a hash-bound pilot artifact; unsupported prose must be withheld."
        ),
    }
    packet = {**body, "packet_sha256": sha256_bytes(canonical_json_bytes(body))}
    _write_json(packet_path, packet)
    return packet


def _build_research_contracts(
    run_dir: Path,
    selected: Mapping[str, Any],
    candidates_document: Mapping[str, Any],
) -> None:
    selected_path = run_dir / "selected_hypothesis.json"
    _write_json(
        selected_path,
        {
            "schema_version": "gga-selected-hypothesis-v1",
            "candidate": dict(selected),
            "selection_status": "selected_for_pilot_not_confirmed_as_true",
        },
    )
    seed = int(sha256_file(selected_path)[:8], 16)
    pilot = {
        "schema_version": "gga-pilot-contract-v2",
        "candidate_id": selected.get("candidate_id"),
        "question": selected.get("question"),
        "frozen_random_seed": seed,
        "design": selected.get("suggested_design"),
        "required_checks": [
            "resolve every cohort and row to the frozen atlas snapshot",
            "retain censored values without mean substitution",
            "report sample size, effect, uncertainty and sensitivity",
            "emit an executable analysis script and machine-readable results",
        ],
        "inference_requirements": {
            "site_identity": (
                "state the evidence that paired or grouped rows resolve to the same "
                "physical site or sample lineage, and the residual risk when the "
                "pairing rests on coordinate rounding rather than sample identifiers"
            ),
            "spatial_dependence": (
                "diagnose spatial autocorrelation of the analysed quantity at site "
                "level and use a dependence-aware uncertainty method (for example a "
                "spatial block bootstrap) whenever dependence is material; plain iid "
                "inference must be justified, not assumed"
            ),
            "holdout_replication": (
                "re-estimate the headline effect on at least one disjoint split "
                "(spatial blocks, region hold-out or leave-one-source-out) and "
                "report whether the direction and magnitude replicate"
            ),
            "regeneration": (
                "one pinned-seed command regenerates every reported number from the "
                "frozen snapshot end to end"
            ),
        },
        "stop_rules": [
            "stop unsupported if no comparable cohort exists",
            "report a null/weak effect instead of changing the hypothesis",
            "route missing source or covariate evidence back to D1",
        ],
    }
    _write_json(run_dir / "pilot_contract.json", pilot)
    literature = {
        "schema_version": "gga-literature-verification-queue-v1",
        "question": selected.get("question"),
        "required_evidence_classes": [
            "domain baseline",
            "methodological limitation or counterargument",
            "two recent primary frontier studies",
            "relevant policy or data standard when applicable",
        ],
        "record_contract": {
            "required": [
                "title",
                "authors",
                "year",
                "venue",
                "doi_or_official_url",
                "primary_source_verified",
                "supported_claim",
                "retrieval",
            ],
            "rule": "one reviewed record per source; no citation from memory",
        },
        "search_contract": {
            "required": [
                "queries",
                "sources_searched",
                "candidates_screened",
                "inclusion_criteria",
            ],
            "minimum_candidates_screened": MINIMUM_LITERATURE_CANDIDATES_SCREENED,
            "rule": (
                "Search as widely as the question requires, record every query and "
                "source, and bind one downloaded retrieval-evidence artifact to "
                "every citation that survives screening."
            ),
        },
        "status": "awaiting_primary_source_verification",
    }
    _write_json(run_dir / "literature_queue.json", literature)
    quality_contract = {
        "schema_version": "gga-research-quality-contract-v1",
        "paper_entry_gate": {
            "eligible_pilot_outcomes": sorted(PAPER_ELIGIBLE_PILOT_OUTCOMES),
            "required_frontier_status": "supports_empirical_article",
            "failure_status": "candidate_fallback_or_research_redirection",
            "rule": (
                "Unsupported, acquisition-only, invalid, or weak-frontier work must "
                "stop before manuscript and figure generation; the run then "
                "redirects to the next ranked empirical candidate or, when the "
                "queue is empty, to acquisition/audit planning."
            ),
        },
        "contribution_gate": {
            "minimum_contributions": 2,
            "each_contribution_requires_claim_ids": True,
            "required_dimensions": [
                "scientific finding",
                "frontier delta",
                "uncertainty or robustness",
            ],
        },
        "figure_storyboard_gate": {
            "required_empirical_roles": sorted(REQUIRED_EMPIRICAL_FIGURE_ROLES),
            "minimum_data_bearing_figures": 3,
            "method_schematic_is_supplementary_to_result_roles": True,
            "render_inspect_revise_minimum_iterations": 1,
            "candidate_generation_minimum_alternatives": 2,
            "editable_vector_and_generation_source_required": True,
            "source_fidelity_statement_required": True,
            "typography_floor": {
                "min_print_font_pt": publication_lint.MIN_PRINT_FONT_PT,
                "min_raster_width_px": publication_lint.MIN_RASTER_WIDTH_PX,
                "rule": (
                    "The controller lints every submitted SVG/PNG/PDF render: "
                    "vector text below the print-equivalent font floor, rasters "
                    "below the print-quality width floor, and structurally "
                    "broken files are rejected at submission."
                ),
            },
        },
        "literature_search_gate": {
            "minimum_candidates_screened": MINIMUM_LITERATURE_CANDIDATES_SCREENED,
            "per_citation_retrieval_evidence_required": True,
            "rule": (
                "Literature research must document its search queries, sources and "
                "screening volume, and bind one retrieval-evidence artifact to every "
                "verified citation; citations from memory are rejected."
            ),
        },
        "citation_audit_gate": {
            "verdicts": sorted(CITATION_VERDICTS),
            "checks": list(CITATION_CHECK_FIELDS),
            "identifier_types": sorted(REFERENCE_IDENTIFIER_TYPES),
            "all_references_must_verify": True,
            "rule": (
                "Every manuscript reference is audited in a fresh session against "
                "registry evidence for title, author list and order, year, venue and "
                "identifier resolution. Any mismatch or unverifiable reference blocks "
                "independent review and routes to revision."
            ),
        },
        "typesetting_gate": {
            "required_artifacts": ["manuscript source", "typeset PDF"],
            "section_manifest_must_cover_spine": True,
            "layout_rules": [
                "Section and subsection headings are noun phrases; "
                "three-way coordinated headings of the form 'A, B and C' "
                "are rejected in review.",
                "Inline enumerations of three or more items are typeset as "
                "structured lists, not comma chains inside a paragraph.",
                "Figure typography follows a strict hierarchy: title above "
                "panel labels above axis and annotation text, and no visible "
                "text below the print-equivalent font floor.",
            ],
            "rule": (
                "The manuscript must ship a typeset PDF whose section manifest covers "
                "the frozen paper spine; prose without a compilable delivery fails."
            ),
        },
        "review_gates": [
            {
                "gate_id": gate_id,
                "gate_name": gate_name,
                "minimum_score": 3,
                "maximum_score": 4,
            }
            for gate_id, gate_name in REVIEW_GATE_CONTRACT
        ],
        "benchmark": {
            "reference": "research-products/paper-demo-20260817",
            "comparison_axes": [
                "executed quantitative result",
                "uncertainty and sensitivity",
                "spatial or external validation",
                "frontier-linked contribution",
                "data-bearing visual narrative",
            ],
            "claim_boundary": (
                "The benchmark defines quality axes, not numbers that may be copied "
                "or claims that may be reused."
            ),
        },
    }
    _write_json(run_dir / "research_quality_contract.json", quality_contract)
    spine = {
        "schema_version": "gga-paper-spine-v1",
        "status": "planned_awaiting_pilot_and_verified_literature",
        "contribution_first": True,
        "contributions": [],
        "minimum_supported_contributions": 2,
        "required_contribution_fields": [
            "contribution_id",
            "statement",
            "claim_ids",
            "frontier_delta",
        ],
        "section_order": [
            "Results",
            "Materials and methods",
            "Discussion",
            "Introduction",
            "Abstract",
            "Title",
        ],
        "required_sections": [
            "Position within the current frontier",
            "New questions generated",
            "Data and code availability",
            "Agent disclosure",
            "Limitations",
        ],
        "claim_policy": "every numerical sentence resolves to a claim ID",
    }
    _write_json(run_dir / "paper_spine.json", spine)
    figure = {
        "schema_version": "gga-figure-contract-v2",
        "status": "planned_awaiting_pilot",
        "method_figure": {
            "required": True,
            "panels": [
                "sampling and physical design",
                "harmonized evidence layer",
                "statistical design and output preview",
            ],
        },
        "result_figures": {
            "must_reference_claim_ids": True,
            "caption_fields": ["cohort", "n", "unit", "uncertainty", "claim_boundary"],
            "required_roles": sorted(REQUIRED_EMPIRICAL_FIGURE_ROLES),
            "minimum_data_bearing_figures": 3,
            "storyboard_fields": [
                "figure_role",
                "question_answered",
                "claim_ids",
                "visual_encoding",
                "artifact_paths",
                "render_review",
                "candidate_generation",
                "source_fidelity",
                "editable_source",
            ],
        },
        "formats": ["svg", "pdf", "png"],
        "candidate_generation": {
            "minimum_candidates_considered": 2,
            "rejected_alternatives_must_be_recorded": True,
        },
        "source_fidelity": (
            "every visual element must trace to frozen claim data; invented or "
            "decorative data points fail the storyboard"
        ),
        "spatial_pattern_semantics": (
            "the spatial_pattern figure must encode the claimed effect or measured "
            "values in space; a data-availability or cohort-coverage map does not "
            "satisfy the role and fails gate a6"
        ),
        "editable_delivery": (
            "each figure binds an editable source (generation script or editable "
            "vector) so reviewers and readers can regenerate and adapt it"
        ),
        "review_loop": "render_inspect_revise_at_least_once",
    }
    _write_json(run_dir / "figure_contract.json", figure)
    all_candidates = [
        dict(item)
        for item in candidates_document.get("discovery_candidates", [])
        if isinstance(item, Mapping)
    ]
    candidates: list[dict[str, Any]] = []
    represented_types: set[str] = set()
    for item in all_candidates:
        candidate_type = str(item.get("type") or "")
        if candidate_type in represented_types:
            continue
        candidates.append(item)
        represented_types.add(candidate_type)
        if len(candidates) == 5:
            break
    if len(candidates) < 5:
        selected_ids = {str(item.get("candidate_id")) for item in candidates}
        candidates.extend(
            item
            for item in all_candidates
            if str(item.get("candidate_id")) not in selected_ids
        )
        candidates = candidates[:5]
    if selected.get("candidate_id") == "user-question":
        candidates = [dict(selected), *candidates[:4]]
    _write_json(
        run_dir / "five-paper-program.json",
        {
            "schema_version": "gga-five-paper-research-program-v1",
            "status": "proposals_not_papers",
            "papers": [
                {
                    "paper_slot": index,
                    "candidate_id": item.get("candidate_id"),
                    "title": item.get("title"),
                    "pipeline": [
                        "pilot_analyst",
                        "literature_researcher",
                        "manuscript_writer",
                        "figure_designer",
                        "citation_auditor",
                        "independent_reviewer",
                        "publication",
                    ],
                }
                for index, item in enumerate(candidates, 1)
            ],
            "claim_boundary": (
                "These are an automatically ranked research program, not completed or "
                "accepted papers. Each slot requires its own gated run."
            ),
        },
    )
    selected_id = str(selected.get("candidate_id") or "")
    selected_index = next(
        (
            index
            for index, item in enumerate(all_candidates)
            if str(item.get("candidate_id")) == selected_id
        ),
        -1,
    )
    fallback_candidates = [
        {
            "candidate_id": str(item.get("candidate_id")),
            "title": str(item.get("title") or ""),
            "type": str(item.get("type") or ""),
        }
        for item in all_candidates[selected_index + 1 :]
        if str(item.get("paper_track") or "") == "empirical_candidate"
    ]
    _write_json(
        run_dir / "candidate_fallback_queue.json",
        {
            "schema_version": "gga-candidate-fallback-queue-v1",
            "selected_candidate_id": selected_id,
            "candidates": fallback_candidates,
            "rule": (
                "When the scientific opportunity gate rejects the selected "
                "direction, the run redirects to the first queued candidate; the "
                "queue strictly advances through the ranked list, so fallback "
                "chains are finite and end in an acquisition/audit redirect."
            ),
        },
    )
    common = {
        "atlas_snapshot": run_dir / "atlas_snapshot.json",
        "selected_hypothesis": selected_path,
        "research_quality_contract": run_dir / "research_quality_contract.json",
    }
    pilot_inputs = {
        **common,
        "pilot_contract": run_dir / "pilot_contract.json",
        "row_level_geochemistry": run_dir / "atlas_snapshot_files" / "geochemistry.csv",
        "sources_and_confidence": run_dir
        / "atlas_snapshot_files"
        / "sources_and_confidence.json",
        "atlas_run_summary": run_dir / "atlas_snapshot_files" / "run_summary.json",
        "analysis_cohorts": run_dir / "deterministic" / "analysis_cohorts.csv",
        "analysis_cohort_exclusions": run_dir
        / "deterministic"
        / "analysis_cohort_exclusions.csv",
        "research_context": run_dir / "deterministic" / "research_context.csv",
    }
    _write_packet(
        run_dir,
        role="pilot_analyst",
        purpose=(
            "Execute the frozen row-level pilot without altering the atlas or "
            "hypothesis; return a typed scientific outcome and fail closed when the "
            "evidence cannot support an empirical paper."
        ),
        inputs=pilot_inputs,
        required_output={
            "artifacts": "analysis script plus machine-readable results with SHA-256",
            "claims": "claim_id, value, unit, artifact and locator",
            "analysis_outcome": (
                "status, analysis_executed, result_claim_ids, routing_destination, "
                "and concise evidence_summary; paper-eligible outcomes must add a "
                "scientific_rigor object with site_identity (basis, residual_risk), "
                "spatial_dependence (diagnostic, finding, uncertainty_method), "
                "holdout_replication (scheme, result, consistent) and regeneration "
                "(command, deterministic=true) per the pilot contract"
            ),
        },
    )
    _write_packet(
        run_dir,
        role="literature_researcher",
        purpose=(
            "Search the relevant literature as completely as the question requires, "
            "download retrieval evidence for every surviving source, verify primary "
            "sources, map each source to one supported claim, and test whether the "
            "selected result could make a defensible empirical frontier contribution."
        ),
        inputs={**common, "literature_queue": run_dir / "literature_queue.json"},
        required_output={
            "artifacts": (
                "citation evidence file plus one retrieval-evidence artifact "
                "per verified citation"
            ),
            "citations": (
                "complete verified primary-source records, each binding a "
                "retrieval-evidence artifact and retrieval timestamp"
            ),
            "search_coverage": (
                "queries, sources_searched, candidates_screened, inclusion_criteria"
            ),
            "frontier_assessment": (
                "status, open_problem, closest_prior_work, novelty_delta, venue_fit"
            ),
        },
    )


def _state(run_dir: Path) -> dict[str, Any]:
    return _read_object(run_dir / "state.json")


def _write_state(run_dir: Path, state: Mapping[str, Any]) -> dict[str, Any]:
    value = {**dict(state), "updated_at": utc_now()}
    _write_json(run_dir / "state.json", value)
    return value


def start_research(
    atlas_dir: Path, research_root: Path, raw_request: Mapping[str, Any]
) -> dict[str, Any]:
    atlas_dir = atlas_dir.resolve(strict=True)
    if not atlas_dir.is_dir():
        raise AutoResearchError("atlas_dir must be a directory")
    research_root.mkdir(parents=True, exist_ok=True)
    if research_root.is_symlink():
        raise AutoResearchError("research_root must not be a symbolic link")
    research_root = research_root.resolve(strict=True)
    if not research_root.is_dir():
        raise AutoResearchError("research_root must be a directory")
    if research_root == atlas_dir or research_root.is_relative_to(atlas_dir):
        raise AutoResearchError("research_root must be separate from the frozen atlas")
    request = normalize_request(raw_request)
    snapshot = build_atlas_snapshot(atlas_dir)
    request_sha256 = sha256_bytes(canonical_json_bytes(request))
    run_id = (
        "run-"
        + sha256_bytes(f"{snapshot['snapshot_sha256']}:{request_sha256}".encode())[:20]
    )
    run_dir = research_root / run_id
    if run_dir.exists():
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise AutoResearchError("existing research run must be a regular directory")
        existing = _read_object(run_dir / "request.json")
        if canonical_json_bytes(existing) != canonical_json_bytes(request):
            raise AutoResearchError("existing run request does not match")
        return _state(run_dir)
    run_dir.mkdir()
    _write_json(run_dir / "request.json", request)
    _write_json(run_dir / "atlas_snapshot.json", snapshot)
    _append_event(
        run_dir, "run_created", {"snapshot_sha256": snapshot["snapshot_sha256"]}
    )
    candidates_document = _materialize_deterministic_products(atlas_dir, run_dir)
    selected = _select_candidate(request, candidates_document)
    if selected is None:
        status = "awaiting_selection"
        required_roles: list[str] = []
        stage = "candidate_selection"
    else:
        _build_research_contracts(run_dir, selected, candidates_document)
        status = "awaiting_agents"
        required_roles = list(FIRST_WAVE)
        stage = "pilot_and_literature"
    state = {
        "schema_version": STATE_VERSION,
        "run_id": run_id,
        "request_sha256": request_sha256,
        "atlas_snapshot_sha256": snapshot["snapshot_sha256"],
        "status": status,
        "stage": stage,
        "required_roles": required_roles,
        "completed_roles": [],
        "active_cycle": INITIAL_CYCLE,
        "revision_count": 0,
        "selected_candidate_id": selected.get("candidate_id") if selected else None,
        "human_approval_required": False,
        "publication_allowed": False,
        "claim_boundary": (
            "Direction selection is the only human decision. The run then advances "
            "autonomously to a packaged final deliverable whose grade discloses "
            "whether every review gate passed; packaging proves byte identity, "
            "not external peer review or venue acceptance."
        ),
        "created_at": utc_now(),
    }
    _append_event(run_dir, "deterministic_preparation_complete", {"status": status})
    return _write_state(run_dir, state)


def select_research_direction(
    run_dir: Path,
    *,
    candidate_id: str | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """Resume an ``awaiting_selection`` run with one explicit user choice."""

    run_dir = run_dir.resolve(strict=True)
    state = _state(run_dir)
    if state.get("status") != "awaiting_selection":
        raise AutoResearchError("research run is not awaiting a selection")
    original = _read_object(run_dir / "request.json")
    choice = normalize_request(
        {
            "question": question,
            "candidate_id": candidate_id,
            "output_language": original.get("output_language"),
            "target_venue": original.get("target_venue"),
        }
    )
    if choice["selection_mode"] == "candidate_selection_required":
        raise AutoResearchError("select exactly one candidate_id or research question")
    candidates = _read_object(run_dir / "deterministic" / "discovery_candidates.json")
    selected = _select_candidate(choice, candidates)
    if selected is None:  # pragma: no cover - normalize_request prevents this branch
        raise AutoResearchError("selection did not resolve to a research direction")
    selection_body = {
        "schema_version": "gga-auto-research-selection-v1",
        "run_id": run_dir.name,
        "choice": choice,
        "selected_candidate_id": selected.get("candidate_id"),
    }
    selection = {
        **selection_body,
        "selection_sha256": sha256_bytes(canonical_json_bytes(selection_body)),
    }
    _write_json(run_dir / "selection.json", selection)
    _build_research_contracts(run_dir, selected, candidates)
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "pilot_and_literature",
            "required_roles": list(FIRST_WAVE),
            "selected_candidate_id": selected.get("candidate_id"),
        }
    )
    _append_event(
        run_dir,
        "research_direction_selected",
        {
            "selected_candidate_id": selected.get("candidate_id"),
            "selection_sha256": selection["selection_sha256"],
        },
    )
    return _write_state(run_dir, state)


def _validate_packet(packet: Mapping[str, Any], role: str, cycle_id: str) -> None:
    if (
        packet.get("schema_version") != PACKET_VERSION
        or packet.get("role") != role
        or packet.get("cycle_id") != cycle_id
    ):
        raise AutoResearchError("agent packet role or version mismatch")
    if packet.get("fresh_session_required") is not True:
        raise AutoResearchError("agent packet does not require a fresh session")
    expected_review_access = cycle_id != INITIAL_CYCLE and role in SECOND_WAVE
    if packet.get("previous_review_allowed") is not expected_review_access:
        raise AutoResearchError("agent packet review-access policy is invalid")
    expected_output_dir = (
        _artifact_root(Path(str(packet.get("run_id"))), cycle_id, role)
        .relative_to(Path(str(packet.get("run_id"))))
        .as_posix()
    )
    if packet.get("artifact_output_dir") != expected_output_dir:
        raise AutoResearchError("agent packet artifact-output boundary is invalid")
    unsigned = dict(packet)
    expected = unsigned.pop("packet_sha256", None)
    if expected != sha256_bytes(canonical_json_bytes(unsigned)):
        raise AutoResearchError("agent packet hash mismatch")


def _validate_agent_artifacts(
    run_dir: Path,
    role: str,
    payload: Mapping[str, Any],
    cycle_id: str = INITIAL_CYCLE,
) -> list[dict[str, Any]]:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise AutoResearchError(f"{role} must declare at least one output artifact")
    result: list[dict[str, Any]] = []
    allowed_root = _artifact_root(run_dir, cycle_id, role).resolve()
    for item in artifacts:
        if not isinstance(item, Mapping):
            raise AutoResearchError("agent artifact declaration must be an object")
        relative = str(item.get("path") or "")
        if not relative or Path(relative).is_absolute():
            raise AutoResearchError("agent artifact path must be relative")
        raw_candidate = run_dir / relative
        _reject_symlink_components(run_dir, raw_candidate, "agent artifact")
        candidate = raw_candidate.resolve(strict=True)
        if not candidate.is_file() or not candidate.is_relative_to(allowed_root):
            raise AutoResearchError("agent artifact escapes its role output directory")
        if candidate.stat().st_size > MAX_AGENT_ARTIFACT_BYTES:
            raise AutoResearchError("agent artifact exceeds 50 MB")
        actual = sha256_file(candidate)
        if item.get("sha256") != actual:
            raise AutoResearchError("agent artifact SHA-256 mismatch")
        result.append(
            {
                "path": candidate.relative_to(run_dir.resolve()).as_posix(),
                "sha256": actual,
                "bytes": candidate.stat().st_size,
            }
        )
    return result


def _result_artifact_inputs(
    run_dir: Path,
    role: str,
    envelope: Mapping[str, Any],
    cycle_id: str = INITIAL_CYCLE,
) -> dict[str, Path]:
    artifacts = _validate_agent_artifacts(run_dir, role, envelope["payload"], cycle_id)
    return {
        f"{role}_artifact_{index:02d}": run_dir / item["path"]
        for index, item in enumerate(artifacts, 1)
    }


def _validate_scientific_rigor(value: Any) -> None:
    """Typed rigor evidence required before any paper-eligible pilot outcome."""
    if not isinstance(value, Mapping):
        raise AutoResearchError(
            "paper-eligible pilot outcome requires a scientific_rigor object"
        )
    text_fields = {
        "site_identity": ("basis", "residual_risk"),
        "spatial_dependence": ("diagnostic", "finding", "uncertainty_method"),
        "holdout_replication": ("scheme", "result"),
    }
    for section, keys in text_fields.items():
        block = value.get(section)
        if not isinstance(block, Mapping) or any(
            not str(block.get(key) or "").strip() for key in keys
        ):
            raise AutoResearchError(
                f"scientific_rigor.{section} must document: " + ", ".join(keys)
            )
    holdout = value["holdout_replication"]
    if not isinstance(holdout.get("consistent"), bool):
        raise AutoResearchError(
            "scientific_rigor.holdout_replication.consistent must be boolean"
        )
    regeneration = value.get("regeneration")
    if (
        not isinstance(regeneration, Mapping)
        or not str(regeneration.get("command") or "").strip()
        or regeneration.get("deterministic") is not True
    ):
        raise AutoResearchError(
            "scientific_rigor.regeneration requires a deterministic command"
        )


def _validate_analysis_outcome(outcome: Any, claim_ids: set[str]) -> dict[str, Any]:
    if not isinstance(outcome, Mapping):
        raise AutoResearchError("pilot_analyst must return analysis_outcome")
    status = str(outcome.get("status") or "")
    executed = outcome.get("analysis_executed")
    result_claim_ids = outcome.get("result_claim_ids")
    routing_destination = str(outcome.get("routing_destination") or "")
    evidence_summary = str(outcome.get("evidence_summary") or "").strip()
    if status not in PILOT_OUTCOMES:
        raise AutoResearchError("pilot analysis_outcome status is invalid")
    if not isinstance(executed, bool):
        raise AutoResearchError("pilot analysis_executed must be boolean")
    if (
        not isinstance(result_claim_ids, list)
        or len(result_claim_ids) != len(set(map(str, result_claim_ids)))
        or not set(map(str, result_claim_ids)).issubset(claim_ids)
    ):
        raise AutoResearchError("pilot result_claim_ids are malformed or unsupported")
    if not routing_destination or not evidence_summary:
        raise AutoResearchError("pilot outcome requires routing and evidence summary")
    if status in PAPER_ELIGIBLE_PILOT_OUTCOMES:
        if executed is not True or not result_claim_ids:
            raise AutoResearchError(
                "paper-eligible pilot outcome requires executed result claims"
            )
        _validate_scientific_rigor(outcome.get("scientific_rigor"))
    elif executed is not False or result_claim_ids:
        raise AutoResearchError(
            "non-paper-eligible pilot outcome cannot declare executed result claims"
        )
    return dict(outcome)


def _validate_frontier_assessment(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AutoResearchError("literature_researcher must return frontier_assessment")
    status = str(value.get("status") or "")
    if status not in FRONTIER_STATUSES:
        raise AutoResearchError("frontier assessment status is invalid")
    required_text = (
        "open_problem",
        "closest_prior_work",
        "novelty_delta",
        "venue_fit",
    )
    if any(not str(value.get(key) or "").strip() for key in required_text):
        raise AutoResearchError("frontier assessment lacks required evidence fields")
    return dict(value)


def _validate_citation_records(
    citations: Any, declared_artifact_paths: set[str]
) -> None:
    if not isinstance(citations, list) or not citations:
        raise AutoResearchError("literature_researcher must return citations")
    for item in citations:
        if not isinstance(item, Mapping):
            raise AutoResearchError("citation record must be an object")
        authors = item.get("authors")
        retrieval = item.get("retrieval")
        retrieval_valid = (
            isinstance(retrieval, Mapping)
            and str(retrieval.get("retrieved_at") or "").strip()
            and str(retrieval.get("evidence_artifact") or "") in declared_artifact_paths
        )
        if (
            item.get("primary_source_verified") is not True
            or not item.get("doi_or_official_url")
            or not str(item.get("title") or "").strip()
            or not isinstance(authors, list)
            or not authors
            or any(not str(author).strip() for author in authors)
            or not retrieval_valid
        ):
            raise AutoResearchError(
                "every citation must be primary-source verified with authors and a "
                "declared retrieval-evidence artifact"
            )


def _validate_search_coverage(value: Any, citation_count: int) -> None:
    if not isinstance(value, Mapping):
        raise AutoResearchError("literature_researcher must return search_coverage")
    queries = value.get("queries")
    sources = value.get("sources_searched")
    screened = value.get("candidates_screened")
    criteria = str(value.get("inclusion_criteria") or "").strip()
    if (
        not isinstance(queries, list)
        or not queries
        or any(not str(item).strip() for item in queries)
        or not isinstance(sources, list)
        or not sources
        or any(not str(item).strip() for item in sources)
        or not isinstance(screened, int)
        or isinstance(screened, bool)
        or screened < max(MINIMUM_LITERATURE_CANDIDATES_SCREENED, citation_count)
        or not criteria
    ):
        raise AutoResearchError(
            "search_coverage requires queries, sources, a screening volume of at "
            f"least {MINIMUM_LITERATURE_CANDIDATES_SCREENED} candidates covering "
            "every kept citation, and explicit inclusion criteria"
        )


def _validate_reference_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise AutoResearchError("manuscript requires a one-to-200-entry reference list")
    references: list[dict[str, Any]] = []
    reference_ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AutoResearchError("manuscript reference must be an object")
        reference_id = str(item.get("reference_id") or "")
        title = str(item.get("title") or "").strip()
        authors = item.get("authors")
        year = item.get("year")
        venue = str(item.get("venue") or "").strip()
        identifier = item.get("identifier")
        identifier_valid = (
            isinstance(identifier, Mapping)
            and str(identifier.get("type") or "") in REFERENCE_IDENTIFIER_TYPES
            and str(identifier.get("value") or "").strip()
        )
        if (
            not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", reference_id)
            or not title
            or not isinstance(authors, list)
            or not authors
            or any(not str(author).strip() for author in authors)
            or not isinstance(year, int)
            or isinstance(year, bool)
            or not 1500 <= year <= 2100
            or not venue
            or not identifier_valid
        ):
            raise AutoResearchError(
                "manuscript reference lacks id, title, ordered authors, year, "
                "venue, or a typed identifier"
            )
        assert isinstance(identifier, Mapping)
        reference_ids.append(reference_id)
        references.append(
            {
                "reference_id": reference_id,
                "title": title,
                "authors": [str(author) for author in authors],
                "year": year,
                "venue": venue,
                "identifier": {
                    "type": str(identifier["type"]),
                    "value": str(identifier["value"]).strip(),
                },
            }
        )
    if len(reference_ids) != len(set(reference_ids)):
        raise AutoResearchError("manuscript reference IDs must be unique")
    return references


def _spine_required_sections(run_dir: Path) -> set[str]:
    spine = _read_object(run_dir / "paper_spine.json")
    sections = {
        str(item)
        for key in ("section_order", "required_sections")
        for item in spine.get(key, [])
        if str(item).strip()
    }
    if not sections:
        raise AutoResearchError("paper spine declares no required sections")
    return sections


def _validate_typeset_manifest(
    run_dir: Path, value: Any, declared_artifact_paths: set[str]
) -> None:
    if not isinstance(value, Mapping):
        raise AutoResearchError("manuscript_writer must return typeset_manifest")
    source_artifact = str(value.get("source_artifact") or "")
    pdf_artifact = str(value.get("pdf_artifact") or "")
    section_manifest = value.get("section_manifest")
    if (
        source_artifact not in declared_artifact_paths
        or pdf_artifact not in declared_artifact_paths
        or source_artifact == pdf_artifact
        or not isinstance(section_manifest, list)
        or not section_manifest
        or any(not str(item).strip() for item in section_manifest)
    ):
        raise AutoResearchError(
            "typeset_manifest requires distinct declared source and PDF artifacts "
            "plus a non-empty section manifest"
        )
    _validate_render_artifact(run_dir, pdf_artifact, "pdf")
    missing = _spine_required_sections(run_dir) - {
        str(item) for item in section_manifest
    }
    if missing:
        raise AutoResearchError(
            "typeset section manifest misses spine sections: "
            + ", ".join(sorted(missing))
        )


def _reference_manifest_path(run_dir: Path, cycle_id: str) -> Path:
    return _cycle_root(run_dir, cycle_id) / "reference_manifest.json"


def _validate_reference_audit(
    run_dir: Path,
    payload: Mapping[str, Any],
    cycle_id: str,
    declared_artifact_paths: set[str],
) -> None:
    manifest = _read_object(_reference_manifest_path(run_dir, cycle_id))
    expected_ids = {
        str(item.get("reference_id"))
        for item in manifest.get("references", [])
        if isinstance(item, Mapping)
    }
    audit = payload.get("reference_audit")
    if not isinstance(audit, list) or not audit:
        raise AutoResearchError("citation_auditor must return reference_audit")
    verdict_counts = {verdict: 0 for verdict in CITATION_VERDICTS}
    audited_ids: list[str] = []
    for item in audit:
        if not isinstance(item, Mapping):
            raise AutoResearchError("reference audit entry must be an object")
        reference_id = str(item.get("reference_id") or "")
        verdict = str(item.get("verdict") or "")
        checks = item.get("checks")
        evidence = str(item.get("evidence") or "").strip()
        registry_artifact = str(item.get("registry_evidence_artifact") or "")
        checks_valid = isinstance(checks, Mapping) and all(
            isinstance(checks.get(field), bool) for field in CITATION_CHECK_FIELDS
        )
        if (
            not reference_id
            or verdict not in CITATION_VERDICTS
            or not checks_valid
            or not evidence
            or registry_artifact not in declared_artifact_paths
        ):
            raise AutoResearchError(
                "reference audit entry lacks verdict, typed checks, evidence, or a "
                "declared registry-evidence artifact"
            )
        assert isinstance(checks, Mapping)
        if verdict == "verified" and not all(
            checks[field] is True for field in CITATION_CHECK_FIELDS
        ):
            raise AutoResearchError(
                "a verified reference requires every registry check to pass"
            )
        if verdict == "mismatch" and (
            checks["identifier_resolves"] is not True
            or all(checks[field] is True for field in CITATION_CHECK_FIELDS)
        ):
            raise AutoResearchError(
                "a mismatch verdict requires a resolvable identifier and at least "
                "one failing registry check"
            )
        if verdict == "unverifiable" and checks["identifier_resolves"] is not False:
            raise AutoResearchError(
                "an unverifiable verdict requires identifier_resolves to be false"
            )
        audited_ids.append(reference_id)
        verdict_counts[verdict] += 1
    if len(audited_ids) != len(set(audited_ids)):
        raise AutoResearchError("reference audit IDs must be unique")
    if set(audited_ids) != expected_ids:
        raise AutoResearchError(
            "reference audit must cover exactly the manuscript reference manifest"
        )
    summary = payload.get("audit_summary")
    if not isinstance(summary, Mapping):
        raise AutoResearchError("citation_auditor must return audit_summary")
    expected_summary = {
        "total": len(audited_ids),
        "verified": verdict_counts["verified"],
        "mismatched": verdict_counts["mismatch"],
        "unverifiable": verdict_counts["unverifiable"],
        "all_verified": verdict_counts["verified"] == len(audited_ids),
    }
    if {key: summary.get(key) for key in expected_summary} != expected_summary:
        raise AutoResearchError("audit_summary does not match the reference audit")


def _validate_contribution_map(value: Any, allowed_ids: set[str]) -> None:
    if not isinstance(value, list) or not 2 <= len(value) <= 5:
        raise AutoResearchError("manuscript requires two to five contributions")
    contribution_ids: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise AutoResearchError("manuscript contribution must be an object")
        contribution_id = str(item.get("contribution_id") or "")
        statement = str(item.get("statement") or "").strip()
        frontier_delta = str(item.get("frontier_delta") or "").strip()
        claim_ids = item.get("claim_ids")
        if (
            not contribution_id
            or not statement
            or not frontier_delta
            or not isinstance(claim_ids, list)
            or not claim_ids
            or not set(map(str, claim_ids)).issubset(allowed_ids)
        ):
            raise AutoResearchError(
                "manuscript contribution lacks a statement, frontier delta, or claims"
            )
        contribution_ids.append(contribution_id)
    if len(contribution_ids) != len(set(contribution_ids)):
        raise AutoResearchError("manuscript contribution IDs must be unique")


def _validate_render_artifact(run_dir: Path, relative: str, output_format: str) -> None:
    path = run_dir / relative
    header = path.read_bytes()[:4096]
    if output_format == "svg":
        valid = path.suffix.lower() == ".svg" and b"<svg" in header.lower()
    elif output_format == "pdf":
        valid = path.suffix.lower() == ".pdf" and header.startswith(b"%PDF-")
    else:
        valid = path.suffix.lower() == ".png" and header.startswith(
            b"\x89PNG\r\n\x1a\n"
        )
    if not valid:
        raise AutoResearchError(
            f"figure {output_format} artifact has the wrong file signature"
        )


def _validate_figure_storyboard(
    run_dir: Path,
    value: Any,
    allowed_ids: set[str],
    declared_artifact_paths: set[str],
) -> None:
    if not isinstance(value, list) or len(value) < 3:
        raise AutoResearchError(
            "empirical figure storyboard requires at least three figures"
        )
    seen_roles: set[str] = set()
    figure_ids: list[str] = []
    seen_render_paths: set[str] = set()
    for spec in value:
        if not isinstance(spec, Mapping):
            raise AutoResearchError("figure spec must be an object")
        figure_id = str(spec.get("figure_id") or "")
        role = str(spec.get("figure_role") or "")
        question = str(spec.get("question_answered") or "").strip()
        visual_encoding = str(spec.get("visual_encoding") or "").strip()
        claim_ids = spec.get("claim_ids")
        artifact_paths = spec.get("artifact_paths")
        render_review = spec.get("render_review")
        candidate_generation = spec.get("candidate_generation")
        source_fidelity = str(spec.get("source_fidelity") or "").strip()
        editable_source = str(spec.get("editable_source") or "")
        render_paths_valid = (
            isinstance(artifact_paths, Mapping)
            and set(artifact_paths) == {"svg", "pdf", "png"}
            and all(
                isinstance(artifact_paths[output_format], str)
                and artifact_paths[output_format] in declared_artifact_paths
                for output_format in ("svg", "pdf", "png")
            )
        )
        review_lists_valid = (
            isinstance(render_review, Mapping)
            and isinstance(render_review.get("findings"), list)
            and bool(render_review["findings"])
            and all(str(item).strip() for item in render_review["findings"])
            and isinstance(render_review.get("revisions_applied"), list)
            and bool(render_review["revisions_applied"])
            and all(str(item).strip() for item in render_review["revisions_applied"])
        )
        candidate_generation_valid = (
            isinstance(candidate_generation, Mapping)
            and isinstance(candidate_generation.get("candidates_considered"), int)
            and not isinstance(candidate_generation.get("candidates_considered"), bool)
            and int(candidate_generation["candidates_considered"]) >= 2
            and isinstance(candidate_generation.get("alternatives_rejected"), list)
            and bool(candidate_generation["alternatives_rejected"])
            and all(
                str(item).strip()
                for item in candidate_generation["alternatives_rejected"]
            )
        )
        if (
            not figure_id
            or not role
            or not question
            or not visual_encoding
            or not isinstance(claim_ids, list)
            or not claim_ids
            or not set(map(str, claim_ids)).issubset(allowed_ids)
            or not render_paths_valid
            or not review_lists_valid
            or not candidate_generation_valid
            or not source_fidelity
            or editable_source not in declared_artifact_paths
            or not isinstance(render_review.get("iterations"), int)
            or isinstance(render_review.get("iterations"), bool)
            or int(render_review["iterations"]) < 1
            or render_review.get("inspected") is not True
        ):
            raise AutoResearchError(
                "figure spec lacks a supported question, encoding, render review, "
                "candidate comparison, source-fidelity statement, or editable source"
            )
        if editable_source in {
            str(artifact_paths[output_format]) for output_format in ("pdf", "png")
        }:
            raise AutoResearchError(
                "figure editable source must be an editable artifact, not a "
                "rasterized or fixed-layout render"
            )
        assert isinstance(artifact_paths, Mapping)
        for output_format in ("svg", "pdf", "png"):
            relative = str(artifact_paths[output_format])
            if relative in seen_render_paths:
                raise AutoResearchError(
                    "each empirical figure must bind distinct render artifacts"
                )
            _validate_render_artifact(run_dir, relative, output_format)
            seen_render_paths.add(relative)
        figure_ids.append(figure_id)
        seen_roles.add(role)
    if len(figure_ids) != len(set(figure_ids)):
        raise AutoResearchError("figure IDs must be unique")
    missing = REQUIRED_EMPIRICAL_FIGURE_ROLES - seen_roles
    if missing:
        raise AutoResearchError(
            "figure storyboard lacks empirical roles: " + ", ".join(sorted(missing))
        )


def _validate_role_payload(
    run_dir: Path,
    role: str,
    payload: Mapping[str, Any],
    cycle_id: str = INITIAL_CYCLE,
) -> None:
    artifacts = _validate_agent_artifacts(run_dir, role, payload, cycle_id)
    artifacts_by_path = {item["path"]: item["sha256"] for item in artifacts}
    if role == "pilot_analyst":
        claims = payload.get("claims")
        if not isinstance(claims, list):
            raise AutoResearchError("pilot_analyst must return claims")
        for claim in claims:
            required = {"claim_id", "value", "unit", "artifact", "artifact_sha256"}
            if (
                not isinstance(claim, Mapping)
                or not required.issubset(claim)
                or any(claim.get(key) in (None, "") for key in required - {"value"})
                or claim.get("value") is None
            ):
                raise AutoResearchError("pilot claim lacks a typed artifact binding")
            if (
                artifacts_by_path.get(str(claim["artifact"]))
                != claim["artifact_sha256"]
            ):
                raise AutoResearchError("pilot claim does not bind a declared artifact")
        claim_ids = [str(item["claim_id"]) for item in claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise AutoResearchError("pilot claim IDs must be unique")
        _validate_analysis_outcome(payload.get("analysis_outcome"), set(claim_ids))
    elif role == "literature_researcher":
        citations = payload.get("citations")
        _validate_citation_records(citations, set(artifacts_by_path))
        assert isinstance(citations, list)
        _validate_search_coverage(payload.get("search_coverage"), len(citations))
        _validate_frontier_assessment(payload.get("frontier_assessment"))
    elif role in SECOND_WAVE:
        lint_errors = [
            message
            for item in artifacts
            for message in publication_lint.lint_publication_artifact(
                run_dir / item["path"]
            )
        ]
        if lint_errors:
            raise AutoResearchError(
                f"{role} publication lint failed: " + "; ".join(lint_errors)
            )
        claim_ids = payload.get("claim_ids")
        if not isinstance(claim_ids, list):
            raise AutoResearchError(f"{role} must enumerate claim_ids")
        allowed_ids = _allowed_claim_ids(run_dir)
        if not set(claim_ids).issubset(allowed_ids):
            raise AutoResearchError(f"{role} references an unsupported claim ID")
        if role == "manuscript_writer":
            _validate_contribution_map(payload.get("contribution_map"), allowed_ids)
            _validate_reference_list(payload.get("reference_list"))
            _validate_typeset_manifest(
                run_dir, payload.get("typeset_manifest"), set(artifacts_by_path)
            )
        else:
            _validate_figure_storyboard(
                run_dir,
                payload.get("figure_specs"),
                allowed_ids,
                set(artifacts_by_path),
            )
    elif role == "citation_auditor":
        _validate_reference_audit(run_dir, payload, cycle_id, set(artifacts_by_path))
    elif role == "independent_reviewer":
        gates = payload.get("gate_results")
        if not isinstance(gates, list) or len(gates) != 7:
            raise AutoResearchError("independent review requires exactly seven gates")
        for item in gates:
            if not isinstance(item, Mapping):
                raise AutoResearchError("independent review gate must be an object")
            gate_id = str(item.get("gate_id") or "")
            score = item.get("score")
            evidence = item.get("evidence")
            passed = item.get("pass")
            if (
                gate_id not in REVIEW_GATE_NAMES
                or item.get("gate_name") != REVIEW_GATE_NAMES[gate_id]
                or not isinstance(score, int)
                or isinstance(score, bool)
                or not 0 <= score <= 4
                or not isinstance(evidence, list)
                or not evidence
                or any(not str(entry).strip() for entry in evidence)
                or not isinstance(passed, bool)
                or passed is not (score >= 3)
            ):
                raise AutoResearchError(
                    "independent review gate name, score, evidence, or pass is invalid"
                )
        if {str(item["gate_id"]) for item in gates} != {
            f"a{index}" for index in range(1, 8)
        }:
            raise AutoResearchError(
                "independent review must cover each gate a1..a7 once"
            )


def _read_valid_result(
    run_dir: Path, role: str, cycle_id: str = INITIAL_CYCLE
) -> dict[str, Any]:
    packet = _read_object(_role_root(run_dir, cycle_id, role) / "packet.json")
    _validate_packet(packet, role, cycle_id)
    envelope = _read_object(_result_path(run_dir, role, cycle_id))
    if (
        envelope.get("schema_version") != RESULT_VERSION
        or envelope.get("run_id") != run_dir.name
        or envelope.get("cycle_id") != cycle_id
        or envelope.get("role") != role
        or envelope.get("packet_sha256") != packet.get("packet_sha256")
    ):
        raise AutoResearchError(f"{role} result envelope identity mismatch")
    expected_inputs = {
        key: item["sha256"] for key, item in packet["allowed_inputs"].items()
    }
    if envelope.get("input_hashes") != expected_inputs:
        raise AutoResearchError(f"{role} result input hash mismatch")
    for item in packet["allowed_inputs"].values():
        path = run_dir / item["path"]
        _reject_symlink_components(run_dir, path, f"{role} allowed input")
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise AutoResearchError(
                f"{role} allowed input changed after packet creation"
            )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise AutoResearchError(f"{role} result payload must be an object")
    if envelope.get("payload_sha256") != sha256_bytes(canonical_json_bytes(payload)):
        raise AutoResearchError(f"{role} result payload hash mismatch")
    unsigned = dict(envelope)
    expected_result = unsigned.pop("result_sha256", None)
    if expected_result != sha256_bytes(canonical_json_bytes(unsigned)):
        raise AutoResearchError(f"{role} result envelope hash mismatch")
    _validate_role_payload(run_dir, role, payload, cycle_id)
    return envelope


def _allowed_claim_ids(run_dir: Path) -> set[str]:
    snapshot = _read_object(run_dir / "atlas_snapshot.json")
    ids = {
        str(item.get("claim_id"))
        for item in snapshot.get("claim_ledger", {}).get("claims", [])
        if isinstance(item, Mapping)
    }
    pilot_path = run_dir / "agents" / "pilot_analyst" / "result.json"
    if pilot_path.is_file():
        pilot = _read_valid_result(run_dir, "pilot_analyst")
        ids.update(
            str(item.get("claim_id"))
            for item in pilot.get("payload", {}).get("claims", [])
            if isinstance(item, Mapping)
        )
    return ids


def _result_path(run_dir: Path, role: str, cycle_id: str = INITIAL_CYCLE) -> Path:
    return _role_root(run_dir, cycle_id, role) / "result.json"


def _cycle_sequence(active_cycle: str) -> list[str]:
    if active_cycle == INITIAL_CYCLE:
        return [INITIAL_CYCLE]
    ordinal = int(active_cycle.split("-", 1)[1])
    return [INITIAL_CYCLE] + [
        f"revision-{index:02d}" for index in range(1, ordinal + 1)
    ]


def _latest_result_cycle(run_dir: Path, role: str, active_cycle: str) -> str:
    """Newest cycle at or before ``active_cycle`` with an accepted result.

    Targeted revisions reopen only the roles that own failing gates, so the
    canonical artifact set for an untouched role is its most recent accepted
    result, still bound by the hashes recorded when it was accepted.
    """
    for cycle_id in reversed(_cycle_sequence(active_cycle)):
        if _result_path(run_dir, role, cycle_id).is_file():
            return cycle_id
    raise AutoResearchError(f"{role} has no accepted result to carry forward")


@contextlib.contextmanager
def _state_lock(run_dir: Path) -> Iterator[None]:
    """Serialize state transitions so parallel agent sessions submit safely.

    Role sessions in the same wave run concurrently by design; only the
    ledger transition itself is serialized, mirroring shard-owned outputs
    with a single serialized ledger writer.
    """
    lock_path = run_dir / "state.lock"
    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def submit_agent_result(
    run_dir: Path,
    *,
    role: str,
    invocation_id: str,
    model_family: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    if role not in ROLES:
        raise AutoResearchError(f"unsupported role: {role}")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", invocation_id) is None:
        raise AutoResearchError("invalid invocation_id")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", model_family) is None:
        raise AutoResearchError("invalid model_family")
    # Role sessions in one wave run in parallel; the ledger transition itself
    # is serialized so concurrent submissions cannot interleave state writes.
    with _state_lock(run_dir):
        state = _state(run_dir)
        cycle_id = str(state.get("active_cycle") or INITIAL_CYCLE)
        if role not in state.get("required_roles", []):
            raise AutoResearchError(f"{role} is not requested in the active stage")
        packet = _read_object(_role_root(run_dir, cycle_id, role) / "packet.json")
        _validate_packet(packet, role, cycle_id)
        result_path = _result_path(run_dir, role, cycle_id)
        if result_path.exists():
            raise AutoResearchError(f"{role} already submitted a result")
        existing_results = list((run_dir / "agents").glob("*/result.json"))
        revisions = run_dir / "revisions"
        if revisions.is_dir():
            existing_results.extend(revisions.glob("revision-*/agents/*/result.json"))
        for other_path in existing_results:
            if _read_object(other_path).get("invocation_id") == invocation_id:
                raise AutoResearchError("invocation_id reuse across roles is forbidden")
        clean_payload = json.loads(canonical_json_bytes(dict(payload)))
        _validate_role_payload(run_dir, role, clean_payload, cycle_id)
        body = {
            "schema_version": RESULT_VERSION,
            "run_id": run_dir.name,
            "cycle_id": cycle_id,
            "role": role,
            "invocation_id": invocation_id,
            "model_family": model_family,
            "packet_sha256": packet["packet_sha256"],
            "input_hashes": {
                key: item["sha256"] for key, item in packet["allowed_inputs"].items()
            },
            "payload": clean_payload,
            "payload_sha256": sha256_bytes(canonical_json_bytes(clean_payload)),
        }
        envelope = {**body, "result_sha256": sha256_bytes(canonical_json_bytes(body))}
        _write_json(result_path, envelope)
        _append_event(
            run_dir,
            "agent_result_accepted",
            {
                "cycle_id": cycle_id,
                "role": role,
                "result_sha256": envelope["result_sha256"],
            },
        )
        return _advance(run_dir)


def _all_complete(
    run_dir: Path, roles: Sequence[str], cycle_id: str = INITIAL_CYCLE
) -> bool:
    return all(_result_path(run_dir, role, cycle_id).is_file() for role in roles)


def _completed_role_labels(run_dir: Path) -> list[str]:
    completed = [
        f"{INITIAL_CYCLE}/{role}"
        for role in ROLES
        if _result_path(run_dir, role, INITIAL_CYCLE).is_file()
    ]
    revisions = run_dir / "revisions"
    if revisions.is_dir():
        for cycle_root in sorted(revisions.glob("revision-*")):
            if not cycle_root.is_dir() or cycle_root.is_symlink():
                continue
            for role in ROLES:
                if (cycle_root / "agents" / role / "result.json").is_file():
                    completed.append(f"{cycle_root.name}/{role}")
    return completed


def _prepare_citation_audit(
    run_dir: Path, state: dict[str, Any], cycle_id: str
) -> None:
    manuscript_result = _read_valid_result(run_dir, "manuscript_writer", cycle_id)
    references = _validate_reference_list(
        manuscript_result["payload"].get("reference_list")
    )
    manifest_body = {
        "schema_version": "gga-reference-manifest-v1",
        "run_id": run_dir.name,
        "cycle_id": cycle_id,
        "manuscript_result_sha256": manuscript_result["result_sha256"],
        "references": references,
        "claim_boundary": (
            "These are the reference identities the manuscript claims. The audit "
            "verifies them against registry evidence; it never rewrites them."
        ),
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest_body)),
    }
    _write_json(_reference_manifest_path(run_dir, cycle_id), manifest)
    _write_packet(
        run_dir,
        role="citation_auditor",
        cycle_id=cycle_id,
        purpose=(
            "Audit every manuscript reference against authoritative registry "
            "evidence in a fresh session: confirm title, full author list and "
            "author order, year, venue and identifier resolution, bind one "
            "registry-evidence artifact per reference, and report mismatched or "
            "unverifiable entries honestly instead of silently correcting them."
        ),
        inputs={
            "atlas_snapshot": run_dir / "atlas_snapshot.json",
            "research_quality_contract": run_dir / "research_quality_contract.json",
            "claim_registry": run_dir / "research_claim_registry.json",
            "reference_manifest": _reference_manifest_path(run_dir, cycle_id),
            **_result_artifact_inputs(
                run_dir, "manuscript_writer", manuscript_result, cycle_id
            ),
        },
        required_output={
            "artifacts": "one registry-evidence artifact per audited reference",
            "reference_audit": (
                "per-reference verdict with typed title/author/order/year/venue/"
                "identifier checks, registry evidence and reasoning"
            ),
            "audit_summary": (
                "total, verified, mismatched, unverifiable, all_verified"
            ),
        },
    )
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "citation_audit",
            "required_roles": ["citation_auditor"],
        }
    )
    _append_event(
        run_dir,
        "citation_audit_ready",
        {"cycle_id": cycle_id, "reference_count": len(references)},
    )


def _prepare_reviewer(run_dir: Path, state: dict[str, Any], cycle_id: str) -> None:
    # Targeted revisions may leave a role untouched; the reviewer always sees
    # the newest accepted result per role, resolved and bound by hash.
    writer_cycle = _latest_result_cycle(run_dir, "manuscript_writer", cycle_id)
    figure_cycle = _latest_result_cycle(run_dir, "figure_designer", cycle_id)
    audit_cycle = _latest_result_cycle(run_dir, "citation_auditor", cycle_id)
    manuscript_result = _read_valid_result(run_dir, "manuscript_writer", writer_cycle)
    figure_result = _read_valid_result(run_dir, "figure_designer", figure_cycle)
    citation_result = _read_valid_result(run_dir, "citation_auditor", audit_cycle)
    _write_packet(
        run_dir,
        role="independent_reviewer",
        cycle_id=cycle_id,
        purpose=(
            "Audit canonical manuscript, figures, claim bindings and seven release gates "
            "in a fresh session; do not inherit executor summaries or prior review prose."
        ),
        inputs={
            "atlas_snapshot": run_dir / "atlas_snapshot.json",
            "claim_registry": run_dir / "research_claim_registry.json",
            "research_gate_receipt": run_dir / "research_gate_receipt.json",
            "research_quality_contract": run_dir / "research_quality_contract.json",
            "paper_spine": run_dir / "paper_spine.json",
            "figure_contract": run_dir / "figure_contract.json",
            "reference_manifest": _reference_manifest_path(run_dir, audit_cycle),
            "citation_audit_receipt": _cycle_root(run_dir, audit_cycle)
            / "citation_audit_receipt.json",
            **_result_artifact_inputs(
                run_dir, "manuscript_writer", manuscript_result, writer_cycle
            ),
            **_result_artifact_inputs(
                run_dir, "figure_designer", figure_result, figure_cycle
            ),
            **_result_artifact_inputs(
                run_dir, "citation_auditor", citation_result, audit_cycle
            ),
        },
        required_output={
            "artifacts": "review report",
            "gate_results": (
                "the exact controller-owned a1..a7 gate names, score 0..4, "
                "derived pass/fail, evidence, and feedback"
            ),
        },
    )
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "independent_review",
            "required_roles": ["independent_reviewer"],
        }
    )
    _append_event(
        run_dir,
        "independent_review_ready",
        {"cycle_id": cycle_id, "fresh_context": True},
    )


def _prepare_revision_cycle(
    run_dir: Path,
    state: dict[str, Any],
    *,
    previous_cycle: str,
    feedback: Sequence[Mapping[str, Any]],
) -> None:
    revision_count = int(state.get("revision_count") or 0) + 1
    cycle_id = f"revision-{revision_count:02d}"
    cycle_root = _cycle_root(run_dir, cycle_id)
    feedback_path = cycle_root / "feedback_tasks.json"
    tasks = []
    reopened: set[str] = set()
    for item in feedback:
        owners = GATE_OWNER_ROLES.get(str(item.get("gate_id")), tuple(SECOND_WAVE))
        reopened.update(owners)
        tasks.append({**dict(item), "owner_roles": sorted(owners)})
    reopened_roles = sorted(reopened)
    _write_json(
        feedback_path,
        {
            "schema_version": "gga-research-feedback-tasks-v1",
            "source_cycle": previous_cycle,
            "tasks": tasks,
            "task_count": len(tasks),
            "reopened_roles": reopened_roles,
        },
    )
    writer_cycle = _latest_result_cycle(run_dir, "manuscript_writer", previous_cycle)
    figure_cycle = _latest_result_cycle(run_dir, "figure_designer", previous_cycle)
    previous_writer = _read_valid_result(run_dir, "manuscript_writer", writer_cycle)
    previous_figure = _read_valid_result(run_dir, "figure_designer", figure_cycle)
    common = {
        "atlas_snapshot": run_dir / "atlas_snapshot.json",
        "selected_hypothesis": run_dir / "selected_hypothesis.json",
        "claim_registry": run_dir / "research_claim_registry.json",
        "research_gate_receipt": run_dir / "research_gate_receipt.json",
        "research_quality_contract": run_dir / "research_quality_contract.json",
        "feedback_tasks": feedback_path,
        **{
            f"previous_{key}": value
            for key, value in _result_artifact_inputs(
                run_dir, "manuscript_writer", previous_writer, writer_cycle
            ).items()
        },
        **{
            f"previous_{key}": value
            for key, value in _result_artifact_inputs(
                run_dir, "figure_designer", previous_figure, figure_cycle
            ).items()
        },
    }
    if "manuscript_writer" in reopened:
        _write_packet(
            run_dir,
            role="manuscript_writer",
            cycle_id=cycle_id,
            purpose="Revise the manuscript only against enumerated review tasks and frozen claims.",
            inputs={**common, "paper_spine": run_dir / "paper_spine.json"},
            required_output={
                "artifacts": "revised manuscript source plus a typeset PDF",
                "claim_ids": "all numerical claims",
                "contribution_map": "two to five claim-bound frontier contributions",
                "reference_list": (
                    "every cited reference with id, title, ordered authors, year, "
                    "venue and a typed identifier"
                ),
                "typeset_manifest": (
                    "source_artifact, pdf_artifact, and a section manifest covering "
                    "the frozen paper spine"
                ),
            },
        )
    if "figure_designer" in reopened:
        _write_packet(
            run_dir,
            role="figure_designer",
            cycle_id=cycle_id,
            purpose="Revise figures only against enumerated review tasks and frozen claims.",
            inputs={**common, "figure_contract": run_dir / "figure_contract.json"},
            required_output={
                "artifacts": "revised figure generation source and renders",
                "claim_ids": "all plotted claims",
                "figure_specs": (
                    "data-bearing primary, spatial, and robustness storyboard with "
                    "render-inspect-revise evidence, candidate comparison, "
                    "source-fidelity statement and an editable source per figure"
                ),
            },
        )
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "manuscript_and_figures",
            "required_roles": reopened_roles,
            "active_cycle": cycle_id,
            "revision_count": revision_count,
        }
    )
    _append_event(
        run_dir,
        "revision_cycle_ready",
        {
            "cycle_id": cycle_id,
            "previous_cycle": previous_cycle,
            "feedback_task_count": len(feedback),
            "reopened_roles": reopened_roles,
        },
    )


def _finalize_publication(
    run_dir: Path,
    state: dict[str, Any],
    cycle_id: str,
    *,
    grade: str,
    findings: Sequence[Mapping[str, Any]],
) -> None:
    """Package the newest accepted deliverables into a final publication tree.

    Packaging proves byte identity and records gate outcomes; it does not
    replace external peer review.  A failing run is packaged too, but its
    grade discloses the unresolved reviewer findings instead of hiding them.
    """
    if grade not in PUBLICATION_GRADES:
        raise AutoResearchError(f"unknown publication grade: {grade}")
    writer_cycle = _latest_result_cycle(run_dir, "manuscript_writer", cycle_id)
    figure_cycle = _latest_result_cycle(run_dir, "figure_designer", cycle_id)
    audit_cycle = _latest_result_cycle(run_dir, "citation_auditor", cycle_id)
    writer_result = _read_valid_result(run_dir, "manuscript_writer", writer_cycle)
    figure_result = _read_valid_result(run_dir, "figure_designer", figure_cycle)
    package_dir = run_dir / "publication"
    files: list[dict[str, str]] = []
    for role, result, source_cycle in (
        ("manuscript_writer", writer_result, writer_cycle),
        ("figure_designer", figure_result, figure_cycle),
    ):
        for item in result["payload"]["artifacts"]:
            relative = str(item["path"])
            source = (
                run_dir / relative
                if source_cycle == INITIAL_CYCLE
                else _cycle_root(run_dir, source_cycle) / relative
            )
            if not source.is_file():
                source = run_dir / relative
            if sha256_file(source) != item["sha256"]:
                raise AutoResearchError(
                    f"publication packaging found a hash drift in {relative}"
                )
            destination = package_dir / role / Path(relative).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            files.append(
                {
                    "path": destination.relative_to(run_dir).as_posix(),
                    "sha256": item["sha256"],
                    "source_role": role,
                    "source_cycle": source_cycle,
                }
            )
    for name, source in (
        ("review_receipt.json", _cycle_root(run_dir, cycle_id) / "review_receipt.json"),
        (
            "citation_audit_receipt.json",
            _cycle_root(run_dir, audit_cycle) / "citation_audit_receipt.json",
        ),
        ("reference_manifest.json", _reference_manifest_path(run_dir, audit_cycle)),
        ("research_gate_receipt.json", run_dir / "research_gate_receipt.json"),
        ("research_claim_registry.json", run_dir / "research_claim_registry.json"),
    ):
        if source.is_file():
            destination = package_dir / "receipts" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            files.append(
                {
                    "path": destination.relative_to(run_dir).as_posix(),
                    "sha256": sha256_file(source),
                    "source_role": "controller",
                    "source_cycle": cycle_id,
                }
            )
    manifest = {
        "schema_version": "gga-publication-manifest-v1",
        "grade": grade,
        "packaged_cycle": cycle_id,
        "writer_result_sha256": writer_result["result_sha256"],
        "figure_result_sha256": figure_result["result_sha256"],
        "disclosed_findings": [dict(item) for item in findings],
        "files": files,
        "claim_boundary": (
            "Autonomous packaging proves byte identity and records controller "
            "gate outcomes; it does not constitute external peer review or "
            "venue acceptance."
        ),
    }
    manifest["manifest_sha256"] = sha256_bytes(canonical_json_bytes(manifest))
    _write_json(run_dir / "publication_manifest.json", manifest)
    status = (
        "completed_published" if grade == "camera_ready" else "completed_with_findings"
    )
    state.update(
        {
            "status": status,
            "stage": "publication",
            "required_roles": [],
            "publication_allowed": True,
            "publication": {
                "grade": grade,
                "package_dir": "publication",
                "manifest_sha256": manifest["manifest_sha256"],
                "packaged_cycle": cycle_id,
                "disclosed_finding_count": len(manifest["disclosed_findings"]),
            },
        }
    )
    _append_event(
        run_dir,
        "publication_packaged",
        {
            "grade": grade,
            "cycle_id": cycle_id,
            "manifest_sha256": manifest["manifest_sha256"],
            "file_count": len(files),
        },
    )


def _prepare_candidate_fallback(
    run_dir: Path, state: dict[str, Any], reason: str
) -> None:
    """Route a failed direction to the next ranked empirical candidate.

    The fallback queue was frozen at contract time and strictly advances
    through the ranked candidate list, so a chain of failing directions is
    finite and ends in an honest acquisition/audit redirect.
    """
    queue_path = run_dir / "candidate_fallback_queue.json"
    queue: list[dict[str, Any]] = []
    if queue_path.is_file():
        document = _read_object(queue_path)
        raw_queue = document.get("candidates")
        if isinstance(raw_queue, list):
            queue = [dict(item) for item in raw_queue if isinstance(item, Mapping)]
    if not queue:
        state.update(
            {
                "status": "needs_research_redirection",
                "stage": "research_quality_gate",
                "required_roles": [],
            }
        )
        return
    next_candidate = queue[0]
    request = _read_object(run_dir / "request.json")
    next_request = {
        key: request[key]
        for key in ("output_language", "target_venue")
        if request.get(key)
    }
    next_request["candidate_id"] = next_candidate["candidate_id"]
    _write_json(run_dir / "next_request.json", next_request)
    state.update(
        {
            "status": "redirected_next_candidate",
            "stage": "research_quality_gate",
            "required_roles": [],
            "fallback": {
                "next_candidate_id": str(next_candidate["candidate_id"]),
                "next_candidate_title": str(next_candidate.get("title") or ""),
                "remaining_candidates": len(queue),
                "reason": reason,
            },
        }
    )
    _append_event(
        run_dir,
        "candidate_fallback_prepared",
        {
            "next_candidate_id": str(next_candidate["candidate_id"]),
            "remaining_candidates": len(queue),
            "reason": reason,
        },
    )


def _advance(run_dir: Path) -> dict[str, Any]:
    state = _state(run_dir)
    cycle_id = str(state.get("active_cycle") or INITIAL_CYCLE)
    stage = str(state.get("stage") or "")
    if stage == "pilot_and_literature" and _all_complete(
        run_dir, FIRST_WAVE, INITIAL_CYCLE
    ):
        pilot_result = _read_valid_result(run_dir, "pilot_analyst")
        literature_result = _read_valid_result(run_dir, "literature_researcher")
        pilot_outcome = _validate_analysis_outcome(
            pilot_result["payload"].get("analysis_outcome"),
            {
                str(item.get("claim_id"))
                for item in pilot_result["payload"].get("claims", [])
                if isinstance(item, Mapping)
            },
        )
        frontier = _validate_frontier_assessment(
            literature_result["payload"].get("frontier_assessment")
        )
        paper_eligible = (
            pilot_outcome["status"] in PAPER_ELIGIBLE_PILOT_OUTCOMES
            and frontier["status"] == "supports_empirical_article"
        )
        routing_destination = (
            "paper_production"
            if paper_eligible
            else str(pilot_outcome.get("routing_destination") or "candidate_selection")
        )
        gate_receipt = {
            "schema_version": "gga-research-gate-receipt-v1",
            "paper_eligible": paper_eligible,
            "pilot_outcome": pilot_outcome["status"],
            "pilot_result_sha256": pilot_result["result_sha256"],
            "frontier_status": frontier["status"],
            "literature_result_sha256": literature_result["result_sha256"],
            "routing_destination": routing_destination,
            "decision_rule": (
                "An executed supported effect or null and a verified empirical "
                "frontier position are both required before writing."
            ),
        }
        gate_receipt["receipt_sha256"] = sha256_bytes(
            canonical_json_bytes(gate_receipt)
        )
        _write_json(run_dir / "research_gate_receipt.json", gate_receipt)
        claim_registry = {
            "schema_version": "gga-auto-research-claim-registry-v1",
            "atlas_claims": _read_object(run_dir / "atlas_snapshot.json")[
                "claim_ledger"
            ]["claims"],
            "pilot_claims": pilot_result["payload"]["claims"],
            "verified_citations": literature_result["payload"]["citations"],
            "claim_boundary": (
                "Atlas claims are recomputed from frozen outputs; pilot claims are bound "
                "to role artifacts; citations support prose but do not replace data."
            ),
        }
        _write_json(run_dir / "research_claim_registry.json", claim_registry)
        _append_event(
            run_dir,
            "research_quality_gate_completed",
            {
                "paper_eligible": paper_eligible,
                "pilot_outcome": pilot_outcome["status"],
                "frontier_status": frontier["status"],
                "routing_destination": routing_destination,
            },
        )
        if not paper_eligible:
            state["research_gate"] = {
                "paper_eligible": False,
                "pilot_outcome": pilot_outcome["status"],
                "frontier_status": frontier["status"],
                "routing_destination": routing_destination,
            }
            _prepare_candidate_fallback(
                run_dir,
                state,
                reason=(
                    f"pilot outcome {pilot_outcome['status']} with frontier "
                    f"status {frontier['status']}"
                ),
            )
        else:
            common = {
                "atlas_snapshot": run_dir / "atlas_snapshot.json",
                "selected_hypothesis": run_dir / "selected_hypothesis.json",
                "claim_registry": run_dir / "research_claim_registry.json",
                "research_gate_receipt": run_dir / "research_gate_receipt.json",
                "research_quality_contract": run_dir / "research_quality_contract.json",
                **_result_artifact_inputs(run_dir, "pilot_analyst", pilot_result),
                **_result_artifact_inputs(
                    run_dir, "literature_researcher", literature_result
                ),
            }
            _write_packet(
                run_dir,
                role="manuscript_writer",
                purpose=(
                    "Draft an evidence-first empirical manuscript whose contribution "
                    "map states the frontier delta and binds every contribution to "
                    "executed claims, then typeset it into a section-complete PDF."
                ),
                inputs={**common, "paper_spine": run_dir / "paper_spine.json"},
                required_output={
                    "artifacts": "manuscript source plus a typeset PDF",
                    "claim_ids": "all numerical claims",
                    "contribution_map": (
                        "two to five claim-bound contributions with frontier delta"
                    ),
                    "reference_list": (
                        "every cited reference with id, title, ordered authors, "
                        "year, venue and a typed identifier"
                    ),
                    "typeset_manifest": (
                        "source_artifact, pdf_artifact, and a section manifest "
                        "covering the frozen paper spine"
                    ),
                },
            )
            _write_packet(
                run_dir,
                role="figure_designer",
                purpose=(
                    "Design a data-bearing visual argument, not a status dashboard: "
                    "primary result, spatial pattern, and robustness or independent "
                    "validation must each answer a scientific question after "
                    "comparing candidate designs and auditing source fidelity."
                ),
                inputs={**common, "figure_contract": run_dir / "figure_contract.json"},
                required_output={
                    "artifacts": (
                        "figure generation source and SVG/PDF/PNG renders per figure"
                    ),
                    "claim_ids": "all plotted claims",
                    "figure_specs": (
                        "primary, spatial, and robustness storyboard with render "
                        "review, candidate comparison, source-fidelity statement "
                        "and an editable source per figure"
                    ),
                },
            )
            state.update(
                {
                    "status": "awaiting_agents",
                    "stage": "manuscript_and_figures",
                    "required_roles": list(SECOND_WAVE),
                    "research_gate": {
                        "paper_eligible": True,
                        "pilot_outcome": pilot_outcome["status"],
                        "frontier_status": frontier["status"],
                        "routing_destination": "paper_production",
                    },
                }
            )
            _append_event(
                run_dir, "second_agent_wave_ready", {"roles": list(SECOND_WAVE)}
            )
    elif stage == "manuscript_and_figures" and _all_complete(
        run_dir,
        [role for role in state.get("required_roles", []) if role in SECOND_WAVE]
        or list(SECOND_WAVE),
        cycle_id,
    ):
        if _result_path(run_dir, "manuscript_writer", cycle_id).is_file():
            _prepare_citation_audit(run_dir, state, cycle_id)
        else:
            # Figure-only revision: the reference list is unchanged, so the
            # verified citation audit from the manuscript's own cycle carries
            # forward by hash instead of being re-run against identical input.
            audit_cycle = _latest_result_cycle(run_dir, "citation_auditor", cycle_id)
            receipt = _read_object(
                _cycle_root(run_dir, audit_cycle) / "citation_audit_receipt.json"
            )
            if receipt.get("all_references_verified") is not True:
                raise AutoResearchError(
                    "carried citation audit is not fully verified"
                )
            _append_event(
                run_dir,
                "citation_audit_carried_forward",
                {"cycle_id": cycle_id, "audit_cycle": audit_cycle},
            )
            _prepare_reviewer(run_dir, state, cycle_id)
    elif (
        stage == "citation_audit"
        and _result_path(run_dir, "citation_auditor", cycle_id).is_file()
    ):
        citation_result = _read_valid_result(run_dir, "citation_auditor", cycle_id)
        summary = citation_result["payload"]["audit_summary"]
        all_verified = summary["all_verified"] is True
        receipt_body = {
            "schema_version": "gga-citation-audit-receipt-v1",
            "cycle_id": cycle_id,
            "all_references_verified": all_verified,
            "total_references": int(summary["total"]),
            "verified": int(summary["verified"]),
            "mismatched": int(summary["mismatched"]),
            "unverifiable": int(summary["unverifiable"]),
            "reference_manifest_sha256": sha256_file(
                _reference_manifest_path(run_dir, cycle_id)
            ),
            "audit_result_sha256": citation_result["result_sha256"],
            "decision_rule": (
                "Every manuscript reference must be registry-verified for title, "
                "authors, order, year, venue and identifier before independent "
                "review may start."
            ),
        }
        receipt = {
            **receipt_body,
            "receipt_sha256": sha256_bytes(canonical_json_bytes(receipt_body)),
        }
        _write_json(
            _cycle_root(run_dir, cycle_id) / "citation_audit_receipt.json", receipt
        )
        if cycle_id != INITIAL_CYCLE:
            _write_json(run_dir / "citation_audit_receipt.json", receipt)
        _append_event(
            run_dir,
            "citation_audit_completed",
            {
                "cycle_id": cycle_id,
                "all_references_verified": all_verified,
                "mismatched": int(summary["mismatched"]),
                "unverifiable": int(summary["unverifiable"]),
            },
        )
        if all_verified:
            _prepare_reviewer(run_dir, state, cycle_id)
        else:
            feedback = [
                {
                    "gate_id": "citation_audit",
                    "feedback": (
                        f"reference {item['reference_id']} is {item['verdict']}: "
                        f"{item['evidence']}"
                    ),
                }
                for item in citation_result["payload"]["reference_audit"]
                if item["verdict"] != "verified"
            ]
            if int(state.get("revision_count") or 0) >= MAX_REVISION_ROUNDS:
                _finalize_publication(
                    run_dir,
                    state,
                    cycle_id,
                    grade="draft_with_disclosed_findings",
                    findings=feedback,
                )
            else:
                _prepare_revision_cycle(
                    run_dir,
                    state,
                    previous_cycle=cycle_id,
                    feedback=feedback,
                )
    elif (
        stage == "independent_review"
        and _result_path(run_dir, "independent_reviewer", cycle_id).is_file()
    ):
        review = _read_valid_result(run_dir, "independent_reviewer", cycle_id)
        gates = review["payload"]["gate_results"]
        passed = all(item["pass"] for item in gates)
        writer_family = _read_valid_result(
            run_dir,
            "manuscript_writer",
            _latest_result_cycle(run_dir, "manuscript_writer", cycle_id),
        )["model_family"]
        review_family = review["model_family"]
        feedback = [
            {"gate_id": item["gate_id"], "feedback": item.get("feedback", "")}
            for item in gates
            if not item["pass"]
        ]
        receipt = {
            "schema_version": "gga-independent-review-receipt-v2",
            "cycle_id": cycle_id,
            "all_seven_gates_pass": passed,
            "gate_scores": {str(item["gate_id"]): int(item["score"]) for item in gates},
            "gate_contract_sha256": sha256_file(
                run_dir / "research_quality_contract.json"
            ),
            "cross_model_status": (
                "provisional_same_family"
                if writer_family == review_family
                else "cross_family"
            ),
            "review_result_sha256": review["result_sha256"],
            "human_approval_required": False,
            "publication_decision": (
                "auto_publish_camera_ready"
                if passed
                else "revise_or_auto_publish_with_disclosed_findings"
            ),
        }
        _write_json(_cycle_root(run_dir, cycle_id) / "review_receipt.json", receipt)
        if cycle_id != INITIAL_CYCLE:
            _write_json(run_dir / "review_receipt.json", receipt)
        feedback_document = {
            "schema_version": "gga-research-feedback-tasks-v1",
            "source_cycle": cycle_id,
            "tasks": feedback,
            "task_count": len(feedback),
        }
        _write_json(run_dir / "feedback_tasks.json", feedback_document)
        _append_event(
            run_dir,
            "review_completed",
            {
                "cycle_id": cycle_id,
                "passed": passed,
                "feedback_tasks": len(feedback),
            },
        )
        if passed:
            _finalize_publication(
                run_dir, state, cycle_id, grade="camera_ready", findings=[]
            )
        elif int(state.get("revision_count") or 0) >= MAX_REVISION_ROUNDS:
            _finalize_publication(
                run_dir,
                state,
                cycle_id,
                grade="draft_with_disclosed_findings",
                findings=feedback,
            )
        else:
            _prepare_revision_cycle(
                run_dir,
                state,
                previous_cycle=cycle_id,
                feedback=feedback,
            )
    state["completed_roles"] = _completed_role_labels(run_dir)
    return _write_state(run_dir, state)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--atlas-dir", type=Path, required=True)
    start.add_argument("--research-root", type=Path, required=True)
    start.add_argument("--request", type=Path, required=True)
    status = sub.add_parser("status")
    status.add_argument("--run-dir", type=Path, required=True)
    select = sub.add_parser("select")
    select.add_argument("--run-dir", type=Path, required=True)
    selection = select.add_mutually_exclusive_group(required=True)
    selection.add_argument("--candidate-id")
    selection.add_argument("--question")
    submit = sub.add_parser("submit")
    submit.add_argument("--run-dir", type=Path, required=True)
    submit.add_argument("--role", choices=ROLES, required=True)
    submit.add_argument("--invocation-id", required=True)
    submit.add_argument("--model-family", required=True)
    submit.add_argument("--payload", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_research(
                args.atlas_dir,
                args.research_root,
                _read_object(args.request),
            )
        elif args.command == "status":
            result = _state(args.run_dir.resolve(strict=True))
        elif args.command == "select":
            result = select_research_direction(
                args.run_dir,
                candidate_id=args.candidate_id,
                question=args.question,
            )
        else:
            result = submit_agent_result(
                args.run_dir,
                role=args.role,
                invocation_id=args.invocation_id,
                model_family=args.model_family,
                payload=_read_object(args.payload),
            )
    except (AutoResearchError, OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
