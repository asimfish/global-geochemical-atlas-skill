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
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import report_claim_ledger
import manuscript_kit
import publication_lint
import render_figure
import validate_outputs

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ASSETS_DIR = SCRIPT_DIR.parent / "assets"
BUILD_RESEARCH_PRODUCTS = SCRIPT_DIR / "build_research_products.py"
BUILD_DISCOVERY_CANDIDATES = SCRIPT_DIR / "build_discovery_candidates.py"
# Deliverable kits copied into every run so the writer and figure roles work
# from the same frozen style, claim ledger, bibliography seed, plotting
# toolkit and offline basemap the gates later check against.
PAPER_KIT_DIR = "paper_kit"
FIGURE_KIT_DIR = "figure_kit"
FIGURE_KIT_FILES = ("paper_figures.py", "render_figure.py")
FIGURE_KIT_ASSETS = (
    "natural-earth-110m-land.json",
    "natural-earth-110m-admin0.json",
    "natural-earth-50m-admin1-china-visual.json",
)
# Figure roles whose SVG must carry the offline geographic frame.
SPATIAL_FIGURE_ROLES = {"spatial_pattern", "coverage_and_gaps"}
STATE_VERSION = "gga-auto-research-state-v5"
PUBLICATION_GRADES = (
    "camera_ready",
    "draft_with_disclosed_findings",
    "evidence_report",
)
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
# When no attempted direction could execute a paper-eligible pilot, the run
# still ends with a typeset, reviewed deliverable: a data-adequacy and research
# direction report built from the archived attempts.  Its figures answer
# different questions than an empirical article.
REQUIRED_REPORT_FIGURE_ROLES = {
    "coverage_and_gaps",
    "pilot_diagnostics",
    "acquisition_priority",
}
DELIVERABLE_MODES = ("empirical_article", "evidence_report")
WRITING_BASIS_STRONG = "supports_empirical_article"
WRITING_BASIS_BEST_AVAILABLE = "best_available_executed_pilot"
WRITING_BASIS_REPORT = "evidence_report"


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
    ledger = report_claim_ledger.build_claim_ledger(atlas_dir)
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


def candidate_data_signature(candidate: Mapping[str, Any]) -> str:
    """Identify candidates that draw on the same data design.

    Two candidates share a signature when they instantiate the same template
    on the same medium and the same sample-type pairing; they differ only by
    element.  When a pilot reports ``unsupported_inputs`` -- the archive cannot
    identify the estimand -- every sibling with this signature would fail for
    the same structural reason, so the fallback queue drops them instead of
    spending two fresh agent sessions per element on a known dead end.
    """
    sample_types = sorted(
        {
            str(item.get("sample_type") or "")
            for item in candidate.get("evidence") or []
            if isinstance(item, Mapping)
        }
    )
    return "|".join(
        [
            str(candidate.get("type") or ""),
            str(candidate.get("medium") or ""),
            ",".join(sample_types),
        ]
    )


def rank_fallback_candidates(
    all_candidates: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Any],
    exhausted_candidate_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Order the untried empirical candidates for autonomous fallback.

    The list is a round-robin across template types so a direction that
    failed on one template does not burn the whole budget on its own
    siblings before a structurally different question gets a pilot.  Types
    rotate in order of their best-ranked member, except that the selected
    candidate's own type rotates last; inside a type the frozen discovery
    rank is preserved.  Exhausted candidates (already attempted, or sharing a
    dead-end data signature) never re-enter the queue.
    """
    exhausted = set(exhausted_candidate_ids or ())
    selected_id = str(selected.get("candidate_id") or "")
    pool = [
        item
        for item in all_candidates
        if str(item.get("candidate_id") or "")
        and str(item.get("candidate_id")) != selected_id
        and str(item.get("candidate_id")) not in exhausted
        and str((item.get("research_readiness") or {}).get("paper_track") or "")
        == "empirical_candidate"
    ]
    rank = {
        str(item.get("candidate_id")): index
        for index, item in enumerate(all_candidates)
    }
    by_type: dict[str, list[Mapping[str, Any]]] = {}
    for item in pool:
        by_type.setdefault(str(item.get("type") or ""), []).append(item)
    for members in by_type.values():
        members.sort(key=lambda item: rank[str(item.get("candidate_id"))])
    selected_type = str(selected.get("type") or "")
    types = sorted(
        by_type,
        key=lambda name: (
            name == selected_type,
            rank[str(by_type[name][0].get("candidate_id"))],
        ),
    )
    ordered: list[dict[str, Any]] = []
    depth = 0
    while any(depth < len(by_type[name]) for name in types):
        for name in types:
            if depth < len(by_type[name]):
                item = by_type[name][depth]
                ordered.append(
                    {
                        "candidate_id": str(item.get("candidate_id")),
                        "title": str(item.get("title") or ""),
                        "type": str(item.get("type") or ""),
                        "element": str(item.get("element") or ""),
                        "data_signature": candidate_data_signature(item),
                    }
                )
        depth += 1
    return ordered


def _build_research_contracts(
    run_dir: Path,
    selected: Mapping[str, Any],
    candidates_document: Mapping[str, Any],
    exhausted_candidate_ids: Iterable[str] | None = None,
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
        "schema_version": "gga-research-quality-contract-v2",
        "deliverable_mode": "empirical_article",
        "paper_entry_gate": {
            "eligible_pilot_outcomes": sorted(PAPER_ELIGIBLE_PILOT_OUTCOMES),
            "required_frontier_status": WRITING_BASIS_STRONG,
            "failure_status": "chain_then_best_available_or_evidence_report",
            "weak_frontier_policy": (
                "An executed pilot whose frontier is weak or unverified is kept as a "
                "writeable attempt while untried candidates are pursued; once none "
                "remain, the best executed pilot is written up with the frontier "
                "verdict disclosed and the grade capped at "
                "draft_with_disclosed_findings."
            ),
            "no_executed_pilot_policy": (
                "When no attempted direction executes a paper-eligible pilot, the "
                "run writes a typeset, cited, independently reviewed data-adequacy "
                "and research-direction report graded evidence_report."
            ),
            "rule": (
                "Unsupported, acquisition-only, invalid, or weak-frontier work never "
                "starts an empirical manuscript on its own merits; the run redirects "
                "to the next untried empirical candidate and, when the queue is "
                "empty, still ends with a packaged deliverable whose grade states its "
                "basis."
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
            "required_artifacts": [
                "LaTeX manuscript source built on gga-paper.sty",
                "references.bib loaded by \\bibliography",
                "typeset PDF produced by a TeX engine",
            ],
            "section_manifest_must_cover_spine": True,
            "typesetting_contract": {
                "contract": manuscript_kit.CONTRACT_ID,
                "paper_kit_dir": PAPER_KIT_DIR,
                "figure_kit_contract": "gga-figure-kit-v1",
                "min_pdf_pages": manuscript_kit.MIN_PDF_PAGES,
                "min_caption_chars": manuscript_kit.MIN_CAPTION_CHARS,
                "spine_headings_checked_in_source": True,
                "pdf_engines": ["pdfTeX", "XeTeX", "LuaTeX"],
                "claim_marks": (
                    "numbers are cited only through \\claimref{claim_id} marks that "
                    "resolve to the controller-generated claim ledger; legacy inline "
                    "\\claim{...} tags and typewriter identifiers in prose fail the gate"
                ),
                "figure_placement": (
                    "full-width (width=\\linewidth) figures with caption and label, "
                    "placed in the body before the bibliography and referenced in the text"
                ),
            },
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
                "The manuscript must ship a LaTeX source on the frozen paper kit, its "
                "bibliography and a TeX-produced PDF whose section manifest covers the "
                "frozen paper spine; prose without a compilable delivery fails."
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
        "figure_kit": _figure_kit_contract(),
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
    fallback_candidates = rank_fallback_candidates(
        all_candidates, selected, exhausted_candidate_ids
    )
    _write_json(
        run_dir / "candidate_fallback_queue.json",
        {
            "schema_version": "gga-candidate-fallback-queue-v2",
            "selected_candidate_id": selected_id,
            "exhausted_candidate_ids": sorted(exhausted_candidate_ids or []),
            "candidates": fallback_candidates,
            "rule": (
                "When the scientific opportunity gate rejects the selected "
                "direction, the controller archives that attempt and continues the "
                "same run on the first queued candidate. The queue holds every "
                "untried empirical candidate, ordered round-robin across template "
                "types (the type that just failed rotates last) and by rank inside "
                "each type; an unsupported_inputs pilot outcome also drops the "
                "siblings that share the failed candidate's data signature. The "
                "chain is finite and ends in an acquisition/audit redirect."
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
            "payload_contract": _pilot_payload_contract(),
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
            "payload_contract": _literature_payload_contract(),
        },
    )


ARTIFACT_PATH_RULE = (
    "Every artifacts[].path is relative to the run directory root and must start "
    "with this packet's artifact_output_dir (for example "
    "agent_outputs/<role>/results.json); paths relative to the artifact directory "
    "itself are rejected. Each entry needs the SHA-256 of the file bytes."
)
SELF_CHECK_RULE = (
    "Dry-run the payload before submitting: python scripts/auto_research.py submit "
    "--run-dir <run> --role <role> --invocation-id <id> --model-family <family> "
    "--payload <payload.json> --validate-only. It runs the identical acceptance "
    "checks without recording anything."
)


def _pilot_payload_contract() -> dict[str, Any]:
    """Machine-precise mirror of the pilot validators (field names and enums)."""
    return {
        "artifact_path_rule": ARTIFACT_PATH_RULE,
        "self_check": SELF_CHECK_RULE,
        "claims": {
            "type": "array",
            "item_required_keys": [
                "claim_id",
                "value",
                "unit",
                "artifact",
                "artifact_sha256",
            ],
            "rules": [
                "claim_id values must be unique",
                "artifact must equal one artifacts[].path and artifact_sha256 must "
                "equal that entry's sha256",
                "value may be a number, string or list but never null",
            ],
        },
        "analysis_outcome": {
            "required_keys": [
                "status",
                "analysis_executed",
                "result_claim_ids",
                "routing_destination",
                "evidence_summary",
            ],
            "status_enum": sorted(PILOT_OUTCOMES),
            "paper_eligible_statuses": sorted(PAPER_ELIGIBLE_PILOT_OUTCOMES),
            "rules": [
                "analysis_executed is boolean; result_claim_ids is a list of unique "
                "claim_id values from claims",
                "paper-eligible statuses require analysis_executed=true, at least one "
                "result claim and a scientific_rigor object",
                "non-eligible statuses require analysis_executed=false and an empty "
                "result_claim_ids list",
                "routing_destination and evidence_summary are non-empty strings",
            ],
            "scientific_rigor": {
                "site_identity": ["basis", "residual_risk"],
                "spatial_dependence": ["diagnostic", "finding", "uncertainty_method"],
                "holdout_replication": ["scheme", "result", "consistent (boolean)"],
                "regeneration": ["command", "deterministic (must be true)"],
            },
        },
    }


def _literature_payload_contract() -> dict[str, Any]:
    """Machine-precise mirror of the literature validators (field names and enums)."""
    return {
        "artifact_path_rule": ARTIFACT_PATH_RULE,
        "self_check": SELF_CHECK_RULE,
        "citations": {
            "type": "array (at least one record)",
            "item_required_keys": [
                "title",
                "authors (non-empty list of non-empty strings)",
                "year",
                "venue",
                "doi_or_official_url",
                "primary_source_verified (must be true)",
                "supported_claim",
                "retrieval",
            ],
            "retrieval_required_keys": ["retrieved_at", "evidence_artifact"],
            "rules": [
                "retrieval.retrieved_at is the exact field name (not timestamp) and "
                "must be a non-empty string",
                "retrieval.evidence_artifact must equal one artifacts[].path",
            ],
        },
        "search_coverage": {
            "required_keys": [
                "queries (non-empty list of strings)",
                "sources_searched (non-empty list of strings)",
                "candidates_screened (integer)",
                "inclusion_criteria (non-empty string)",
            ],
            "minimum_candidates_screened": MINIMUM_LITERATURE_CANDIDATES_SCREENED,
            "rules": [
                "candidates_screened must be at least the minimum and at least the "
                "number of citations returned"
            ],
        },
        "frontier_assessment": {
            "required_keys": [
                "status",
                "open_problem",
                "closest_prior_work",
                "novelty_delta",
                "venue_fit",
            ],
            "status_enum": sorted(FRONTIER_STATUSES),
            "rules": [
                "status must be exactly one enum value; descriptive variants such as "
                "does_not_support_empirical_article are rejected",
                "only supports_empirical_article lets the run write a paper; "
                "weak_frontier_position and needs_verification redirect the run to "
                "the next empirical candidate",
            ],
        },
    }


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
        "attempt": 1,
        "attempt_history": [],
        "exhausted_candidate_ids": [],
        "selected_candidate_id": selected.get("candidate_id") if selected else None,
        "human_approval_required": False,
        "publication_allowed": False,
        "claim_boundary": (
            "Direction selection is the only human decision. The run then advances "
            "autonomously to a packaged final deliverable whose grade discloses "
            "whether every review gate passed, redirecting itself to the next "
            "untried empirical candidate whenever a direction fails the "
            "scientific gate; packaging proves byte identity, not external peer "
            "review or venue acceptance."
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
    run_dir: Path,
    value: Any,
    declared_artifact_paths: set[str],
    declared_claim_ids: Sequence[str] = (),
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
    # Typesetting contract gga-paper-v1: the source must be a LaTeX manuscript
    # built on the frozen style, cite numbers only through registered claim
    # marks, keep figures in the body, and the PDF must be a TeX product.
    source_text = (run_dir / source_artifact).read_text(
        encoding="utf-8", errors="replace"
    )
    bib_artifact = str(value.get("bib_artifact") or "")
    available_bib_keys: set[str] | None = None
    if re.search(r"\\bibliography\{[^}]+\}", source_text):
        if (
            not bib_artifact
            or bib_artifact not in declared_artifact_paths
            or not bib_artifact.lower().endswith(".bib")
        ):
            raise AutoResearchError(
                "typeset_manifest.bib_artifact must name the submitted .bib file that "
                "\\bibliography loads"
            )
        available_bib_keys = manuscript_kit.bib_keys(
            (run_dir / bib_artifact).read_text(encoding="utf-8", errors="replace")
        )
    errors = manuscript_kit.lint_manuscript_source(
        source_text,
        bib_keys_available=available_bib_keys,
        registered_claim_ids=_allowed_claim_ids(run_dir),
        required_headings=_spine_required_sections(run_dir),
        declared_claim_ids=[str(item) for item in declared_claim_ids],
    )
    errors.extend(manuscript_kit.lint_manuscript_pdf(run_dir / pdf_artifact))
    if errors:
        raise AutoResearchError(
            "manuscript typesetting gate failed: " + "; ".join(errors)
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
        # Cross-format fidelity: the PDF and PNG must show the whole SVG (same
        # aspect), and spatial roles must carry the offline geographic frame.
        render_errors = publication_lint.lint_figure_renders(
            run_dir / str(artifact_paths["svg"]),
            run_dir / str(artifact_paths["pdf"]),
            run_dir / str(artifact_paths["png"]),
            requires_basemap=role in SPATIAL_FIGURE_ROLES,
        )
        if render_errors:
            raise AutoResearchError(
                f"figure {figure_id} failed render fidelity: "
                + "; ".join(render_errors)
            )
        figure_ids.append(figure_id)
        seen_roles.add(role)
    if len(figure_ids) != len(set(figure_ids)):
        raise AutoResearchError("figure IDs must be unique")
    missing = _required_figure_roles(run_dir) - seen_roles
    if missing:
        raise AutoResearchError(
            "figure storyboard lacks required roles: " + ", ".join(sorted(missing))
        )


def _required_figure_roles(run_dir: Path) -> set[str]:
    """The frozen figure contract decides which storyboard roles are mandatory.

    Empirical articles need primary/spatial/robustness evidence; an evidence
    report needs coverage, pilot-diagnostic and acquisition-priority figures.
    """
    contract_path = run_dir / "figure_contract.json"
    if contract_path.is_file():
        contract = _read_object(contract_path)
        roles = (contract.get("result_figures") or {}).get("required_roles")
        if isinstance(roles, list) and roles:
            return {str(role) for role in roles}
    return set(REQUIRED_EMPIRICAL_FIGURE_ROLES)


FEEDBACK_SCHEMA_PREFIX = "gga-research-feedback-tasks"
# Names that belong exclusively to review provenance; a deliverable never
# carries them, whatever its content.
NON_DELIVERABLE_BASENAMES = {"feedback_tasks.json", "review_receipt.json"}


def _review_provenance_hashes(run_dir: Path) -> dict[str, str]:
    """SHA-256 -> description for every feedback task file and review product.

    A later reviewer must never receive these, even re-declared as a role's
    artifact; the hash set makes byte-identical copies detectable wherever
    they are placed.
    """
    hashes: dict[str, str] = {}
    roots = (
        [
            run_dir,
            *sorted(
                path
                for path in (run_dir / "revisions").glob("revision-*")
                if path.is_dir()
            ),
        ]
        if (run_dir / "revisions").is_dir()
        else [run_dir]
    )
    for root in roots:
        for name in ("feedback_tasks.json", "review_receipt.json"):
            path = root / name
            if path.is_file():
                hashes[sha256_file(path)] = path.relative_to(run_dir).as_posix()
        review_result = root / "agents" / "independent_reviewer" / "result.json"
        if review_result.is_file():
            hashes[sha256_file(review_result)] = review_result.relative_to(
                run_dir
            ).as_posix()
            envelope = _read_object(review_result)
            for item in (envelope.get("payload") or {}).get("artifacts") or []:
                if isinstance(item, Mapping) and item.get("sha256"):
                    hashes[str(item["sha256"])] = str(item.get("path"))
    return hashes


def _reject_input_copies_as_artifacts(
    run_dir: Path, role: str, artifacts: Sequence[Mapping[str, Any]], cycle_id: str
) -> None:
    """Deliverables must be the role's own work, not review provenance or old work.

    A role that vendors its packet inputs as artifacts (observed: a figure
    designer re-declaring ``feedback_tasks.json`` and the previous cycle's SVGs
    under ``frozen_inputs/``) leaks feedback into the next reviewer's packet
    and creates same-basename collisions in the publication package, so the
    submission fails closed. Controller kit files (style, claim ledger, seeded
    bibliography) may be re-shipped unchanged: they carry no review
    provenance and make the package self-contained.
    """
    if role == "independent_reviewer":
        return
    packet_path = _role_root(run_dir, cycle_id, role) / "packet.json"
    previous_hashes: dict[str, str] = {}
    if packet_path.is_file():
        for key, item in (
            _read_object(packet_path).get("allowed_inputs") or {}
        ).items():
            if (
                str(key).startswith("previous_")
                and isinstance(item, Mapping)
                and item.get("sha256")
            ):
                previous_hashes[str(item["sha256"])] = f"packet input {key}"
    provenance = _review_provenance_hashes(run_dir)
    digests_by_basename: dict[str, set[str]] = {}
    for item in artifacts:
        digests_by_basename.setdefault(Path(str(item["path"])).name, set()).add(
            str(item["sha256"])
        )
    for item in artifacts:
        relative = str(item["path"])
        digest = str(item["sha256"])
        basename = Path(relative).name
        # An unchanged file may be re-submitted; a stale copy of the previous
        # cycle's file declared next to its revised namesake may not.
        if (
            digest in previous_hashes
            and len(digests_by_basename.get(basename, set())) > 1
        ):
            raise AutoResearchError(
                f"{role} artifact {relative} is a byte-identical copy of {previous_hashes[digest]} "
                f"declared alongside a revised {basename}; the previous cycle's deliverables carry "
                "forward by hash and stale copies must not be re-declared"
            )
        if digest in provenance:
            raise AutoResearchError(
                f"{role} artifact {relative} duplicates review provenance ({provenance[digest]}); "
                "feedback tasks and review prose must never reach the next reviewer"
            )
        if basename in NON_DELIVERABLE_BASENAMES:
            raise AutoResearchError(
                f"{role} artifact {relative} is named like review provenance ({basename}); "
                "deliverables must carry their own names"
            )
        if basename.lower().endswith(".json"):
            try:
                document = json.loads((run_dir / relative).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if isinstance(document, Mapping) and str(
                document.get("schema_version") or ""
            ).startswith(FEEDBACK_SCHEMA_PREFIX):
                raise AutoResearchError(
                    f"{role} artifact {relative} carries the feedback-task schema; "
                    "review feedback must not be re-emitted as a deliverable"
                )


def _validate_role_payload(
    run_dir: Path,
    role: str,
    payload: Mapping[str, Any],
    cycle_id: str = INITIAL_CYCLE,
) -> None:
    artifacts = _validate_agent_artifacts(run_dir, role, payload, cycle_id)
    artifacts_by_path = {item["path"]: item["sha256"] for item in artifacts}
    _reject_input_copies_as_artifacts(run_dir, role, artifacts, cycle_id)
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
            references = _validate_reference_list(payload.get("reference_list"))
            _validate_typeset_manifest(
                run_dir,
                payload.get("typeset_manifest"),
                set(artifacts_by_path),
                declared_claim_ids=[str(item) for item in claim_ids],
            )
            source_text = (
                run_dir / str(payload["typeset_manifest"]["source_artifact"])
            ).read_text(encoding="utf-8", errors="replace")
            cited = manuscript_kit.cited_keys(source_text)
            listed = {item["reference_id"] for item in references}
            if cited != listed:
                raise AutoResearchError(
                    "reference_list must list exactly the bib keys the manuscript cites "
                    f"(cited but unlisted: {sorted(cited - listed)[:4]}; listed but "
                    f"uncited: {sorted(listed - cited)[:4]})"
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
    # An evidence report cites the archived attempts' diagnostic claims, which
    # the controller re-registers (attempt-prefixed) in the claim registry.
    registry_path = run_dir / "research_claim_registry.json"
    if registry_path.is_file():
        registry = _read_object(registry_path)
        ids.update(
            str(item.get("claim_id"))
            for item in registry.get("pilot_claims", [])
            if isinstance(item, Mapping) and item.get("claim_id")
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


def _check_submission(
    run_dir: Path,
    *,
    role: str,
    invocation_id: str,
    model_family: str,
    payload: Mapping[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], Path]:
    """Run every acceptance check for a role result without writing anything.

    Returns the packet, the active cycle, the canonicalised payload and the
    result path so ``submit_agent_result`` can commit exactly what was checked.
    """
    if role not in ROLES:
        raise AutoResearchError(f"unsupported role: {role}")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", invocation_id) is None:
        raise AutoResearchError("invalid invocation_id")
    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,200}", model_family) is None:
        raise AutoResearchError("invalid model_family")
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
    attempts = run_dir / "attempts"
    if attempts.is_dir():
        # Archived directions keep their invocation IDs reserved: a session
        # from a failed attempt must not be replayed against a new one.
        existing_results.extend(attempts.glob("attempt-*/agents/*/result.json"))
        existing_results.extend(
            attempts.glob("attempt-*/revisions/revision-*/agents/*/result.json")
        )
    for other_path in existing_results:
        if _read_object(other_path).get("invocation_id") == invocation_id:
            raise AutoResearchError("invocation_id reuse across roles is forbidden")
    clean_payload = json.loads(canonical_json_bytes(dict(payload)))
    _validate_role_payload(run_dir, role, clean_payload, cycle_id)
    return packet, cycle_id, clean_payload, result_path


def validate_agent_result(
    run_dir: Path,
    *,
    role: str,
    invocation_id: str,
    model_family: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Dry-run the acceptance checks so a role can self-correct before submitting.

    Nothing is written and no state advances; the same checks run again at
    submission, so a passing dry run is a prediction, not a reservation.
    """
    run_dir = run_dir.resolve(strict=True)
    with _state_lock(run_dir):
        packet, cycle_id, clean_payload, _ = _check_submission(
            run_dir,
            role=role,
            invocation_id=invocation_id,
            model_family=model_family,
            payload=payload,
        )
    return {
        "valid": True,
        "run_id": run_dir.name,
        "cycle_id": cycle_id,
        "role": role,
        "packet_sha256": packet["packet_sha256"],
        "payload_sha256": sha256_bytes(canonical_json_bytes(clean_payload)),
        "claim_boundary": (
            "Validation only: no result was recorded and the run state did not "
            "advance. Submit the identical payload to commit it."
        ),
    }


def submit_agent_result(
    run_dir: Path,
    *,
    role: str,
    invocation_id: str,
    model_family: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    run_dir = run_dir.resolve(strict=True)
    # Role sessions in one wave run in parallel; the ledger transition itself
    # is serialized so concurrent submissions cannot interleave state writes.
    with _state_lock(run_dir):
        packet, cycle_id, clean_payload, result_path = _check_submission(
            run_dir,
            role=role,
            invocation_id=invocation_id,
            model_family=model_family,
            payload=payload,
        )
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
    reviewer_inputs = {
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
    }
    # Isolation invariant: nothing the reviewer receives may be feedback or
    # earlier review material, whatever path it was re-declared under.
    provenance = _review_provenance_hashes(run_dir)
    for key, path in reviewer_inputs.items():
        digest = sha256_file(path)
        if digest in provenance or path.name in {
            "feedback_tasks.json",
            "review_receipt.json",
        }:
            raise AutoResearchError(
                f"reviewer isolation violated: input {key} ({path.relative_to(run_dir).as_posix()}) "
                f"is review provenance ({provenance.get(digest, path.name)})"
            )
    _write_packet(
        run_dir,
        role="independent_reviewer",
        cycle_id=cycle_id,
        purpose=(
            "Audit canonical manuscript, figures, claim bindings and seven release gates "
            "in a fresh session; do not inherit executor summaries or prior review prose."
        ),
        inputs=reviewer_inputs,
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
    paper_inputs, figure_inputs = _deliverable_kit_inputs(run_dir)
    if "manuscript_writer" in reopened:
        _write_packet(
            run_dir,
            role="manuscript_writer",
            cycle_id=cycle_id,
            purpose=(
                "Revise the manuscript only against enumerated review tasks and frozen "
                "claims, on the same paper kit; re-submit the complete LaTeX source, "
                "bibliography and TeX-compiled PDF, never copies of the inputs."
            ),
            inputs={
                **common,
                **paper_inputs,
                **figure_inputs,
                "paper_spine": run_dir / "paper_spine.json",
            },
            required_output={
                "artifacts": "revised LaTeX manuscript source, references.bib and typeset PDF",
                "claim_ids": "all numerical claims",
                "contribution_map": "two to five claim-bound frontier contributions",
                "reference_list": (
                    "every cited reference with id, title, ordered authors, year, "
                    "venue and a typed identifier"
                ),
                "typeset_manifest": (
                    "source_artifact, pdf_artifact, bib_artifact and a section manifest "
                    "covering the frozen paper spine"
                ),
                "payload_contract": _manuscript_payload_contract(),
            },
        )
    if "figure_designer" in reopened:
        _write_packet(
            run_dir,
            role="figure_designer",
            cycle_id=cycle_id,
            purpose=(
                "Revise figures only against enumerated review tasks and frozen claims, "
                "with the same figure kit; re-submit every storyboard figure as your own "
                "SVG source plus renders, never copies of the previous cycle's files."
            ),
            inputs={
                **common,
                **figure_inputs,
                "figure_contract": run_dir / "figure_contract.json",
            },
            required_output={
                "artifacts": "revised figure generation source and renders",
                "claim_ids": "all plotted claims",
                "figure_specs": (
                    "data-bearing primary, spatial, and robustness storyboard with "
                    "render-inspect-revise evidence, candidate comparison, "
                    "source-fidelity statement and an editable source per figure"
                ),
                "payload_contract": _figure_payload_contract(),
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
    # The grade can never overstate the basis the run was written on: an
    # evidence report stays an evidence report, and a manuscript written on the
    # best available (weak-frontier) pilot stays a disclosed-findings draft
    # even when every review gate passes.
    disclosed: list[dict[str, Any]] = [dict(item) for item in findings]
    gate = dict(state.get("research_gate") or {})
    if state.get("deliverable_mode") == "evidence_report":
        grade = "evidence_report"
        disclosed.append(
            {
                "gate_id": "deliverable_mode",
                "feedback": (
                    "evidence report: no attempted direction executed a paper-eligible "
                    "pilot; this deliverable assesses data adequacy and recommends "
                    "acquisition or audit work, and claims no empirical effect"
                ),
            }
        )
    elif (
        grade == "camera_ready"
        and gate.get("writing_basis") == WRITING_BASIS_BEST_AVAILABLE
    ):
        grade = "draft_with_disclosed_findings"
        receipt = _read_object(run_dir / "research_gate_receipt.json")
        disclosed.extend(
            dict(item)
            for item in receipt.get("disclosures", [])
            if isinstance(item, Mapping)
        )
    findings = disclosed
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
            # Keep the artifact's own sub-path below its role directory so two
            # deliverables that share a basename (e.g. figures/fig1.svg and
            # canonical/fig1.svg) never collapse onto one packaged file.
            artifact_root = f"agent_outputs/{role}/"
            marker = relative.find(artifact_root)
            packaged_name = (
                relative[marker + len(artifact_root) :]
                if marker >= 0
                else Path(relative).name
            )
            destination = package_dir / role / packaged_name
            if destination.exists():
                raise AutoResearchError(
                    f"publication packaging collides on {destination.relative_to(run_dir)}"
                )
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
        "schema_version": "gga-publication-manifest-v2",
        "grade": grade,
        "deliverable_mode": str(state.get("deliverable_mode") or "empirical_article"),
        "writing_basis": str(gate.get("writing_basis") or WRITING_BASIS_STRONG),
        "attempted_directions": len(state.get("attempt_history") or []) + 1,
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
    status = {
        "camera_ready": "completed_published",
        "draft_with_disclosed_findings": "completed_with_findings",
        "evidence_report": "completed_evidence_report",
    }[grade]
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


# Everything the controller writes for one research direction.  A redirect
# moves these into ``attempts/attempt-NN-<candidate>/`` so the next direction
# starts from a clean run root while the failed attempt stays auditable.
ATTEMPT_SCOPED_ENTRIES = (
    "agents",
    "agent_outputs",
    "revisions",
    "publication",
    "selected_hypothesis.json",
    "pilot_contract.json",
    "literature_queue.json",
    "research_quality_contract.json",
    "paper_spine.json",
    "figure_contract.json",
    "five-paper-program.json",
    "candidate_fallback_queue.json",
    "research_gate_receipt.json",
    "research_claim_registry.json",
    "review_receipt.json",
    "feedback_tasks.json",
    "citation_audit_receipt.json",
    "reference_manifest.json",
    "publication_manifest.json",
)


def _archive_attempt(
    run_dir: Path, state: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    attempt = int(state.get("attempt") or 1)
    candidate_id = str(state.get("selected_candidate_id") or "unselected")
    archive_dir = run_dir / "attempts" / f"attempt-{attempt:02d}-{candidate_id}"
    if archive_dir.exists():
        raise AutoResearchError(f"attempt archive already exists: {archive_dir.name}")
    archive_dir.mkdir(parents=True)
    moved: list[dict[str, Any]] = []
    for name in ATTEMPT_SCOPED_ENTRIES:
        source = run_dir / name
        if not source.exists() or source.is_symlink():
            continue
        shutil.move(str(source), str(archive_dir / name))
        moved.append(
            {
                "path": name,
                "kind": "directory" if (archive_dir / name).is_dir() else "file",
            }
        )
    result_hashes = {
        path.relative_to(archive_dir).as_posix(): _read_object(path).get(
            "result_sha256"
        )
        for path in sorted(archive_dir.glob("agents/*/result.json"))
    }
    gate = dict(state.get("research_gate") or {})
    writeable = gate.get("pilot_outcome") in PAPER_ELIGIBLE_PILOT_OUTCOMES
    manifest_body = {
        "schema_version": "gga-research-attempt-v1",
        "attempt": attempt,
        "candidate_id": candidate_id,
        "reason": reason,
        "research_gate": gate,
        "writeable": writeable,
        "archived_entries": moved,
        "result_sha256": result_hashes,
        "claim_boundary": (
            "An archived attempt records why a direction could not support a "
            "paper; its artifacts remain hash-bound evidence and are never reused "
            "as results for another candidate."
        ),
    }
    manifest = {
        **manifest_body,
        "manifest_sha256": sha256_bytes(canonical_json_bytes(manifest_body)),
    }
    _write_json(archive_dir / "attempt_manifest.json", manifest)
    return {
        "attempt": attempt,
        "candidate_id": candidate_id,
        "archive_dir": archive_dir.relative_to(run_dir).as_posix(),
        "manifest_sha256": manifest["manifest_sha256"],
        "pilot_outcome": gate.get("pilot_outcome"),
        "frontier_status": gate.get("frontier_status"),
        "writeable": writeable,
        "reason": reason,
    }


def _frontier_disclosure(
    frontier: Mapping[str, Any], pilot_outcome: str
) -> dict[str, Any]:
    """The reviewer-visible statement that a manuscript rests on a weak frontier."""
    return {
        "gate_id": "frontier",
        "frontier_status": str(frontier.get("status") or ""),
        "pilot_outcome": pilot_outcome,
        "closest_prior_work": frontier.get("closest_prior_work"),
        "novelty_delta": str(frontier.get("novelty_delta") or ""),
        "feedback": (
            f"literature frontier verdict {frontier.get('status')}: the manuscript "
            "must be framed as a bounded replication, regional confirmation or "
            "null-result note; the contribution map states the closest prior work "
            "and claims no novelty beyond the disclosed delta"
        ),
    }


def _figure_kit_contract() -> dict[str, Any]:
    """What the figure gate checks beyond the storyboard, stated in the contract."""
    return {
        "contract": "gga-figure-kit-v1",
        "toolkit": f"{FIGURE_KIT_DIR}/paper_figures.py",
        "renderer": f"{FIGURE_KIT_DIR}/render_figure.py",
        "basemap_assets": list(FIGURE_KIT_ASSETS),
        "spatial_roles_require_basemap": sorted(SPATIAL_FIGURE_ROLES),
        "render_fidelity": (
            "SVG, PDF and PNG of one figure must share the SVG aspect ratio within "
            f"{publication_lint.ASPECT_TOLERANCE:.0%}; clipped or letter-boxed exports fail"
        ),
        "typography": {
            "min_print_font_pt": publication_lint.MIN_PRINT_FONT_PT,
            "max_text_run_chars": publication_lint.MAX_TEXT_RUN_CHARS,
            "rule": (
                "no in-figure captions or disclaimer boxes; caveats go in the manuscript "
                "caption; no gradients, glow or drop shadows"
            ),
        },
    }


def _install_deliverable_kits(
    run_dir: Path, citations: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Path], dict[str, Path]]:
    """Write the paper kit and figure kit into the run; return packet inputs.

    The paper kit is the style, the skeleton, the claim ledger generated from
    the frozen registry and a bibliography seeded from the verified
    citations.  The figure kit is the dependency-free plotting toolkit, the
    SVG->PDF/PNG renderer and the offline basemap assets.  Both are re-written
    from the skill on every call so a run can never carry a stale kit.
    """
    paper_dir = run_dir / PAPER_KIT_DIR
    figure_dir = run_dir / FIGURE_KIT_DIR
    if paper_dir.exists():
        shutil.rmtree(paper_dir)
    if figure_dir.exists():
        shutil.rmtree(figure_dir)
    paper_files = manuscript_kit.install_kit(paper_dir, SKILL_ASSETS_DIR / "paper")
    registry = _read_object(run_dir / "research_claim_registry.json")
    (paper_dir / manuscript_kit.CLAIMS_FILE).write_text(
        manuscript_kit.claims_tex(registry), encoding="utf-8"
    )
    bib_text, seeded_references = manuscript_kit.references_bib(citations)
    (paper_dir / manuscript_kit.BIB_FILE).write_text(bib_text, encoding="utf-8")
    _write_json(
        paper_dir / "seeded_reference_list.json",
        {
            "schema_version": "gga-seeded-reference-list-v1",
            "contract": manuscript_kit.CONTRACT_ID,
            "references": seeded_references,
            "rule": (
                "These reference_ids are the bib keys of references.bib. Cite them "
                "with \\cite{key}; report exactly the bib keys you cite as the "
                "manuscript reference_list (add verified references to the bib and "
                "the list together)."
            ),
        },
    )
    figure_dir.mkdir(parents=True, exist_ok=True)
    for name in FIGURE_KIT_FILES:
        shutil.copyfile(SCRIPT_DIR / name, figure_dir / name)
    for name in FIGURE_KIT_ASSETS:
        shutil.copyfile(SKILL_ASSETS_DIR / name, figure_dir / name)
    (figure_dir / "publication_lint.py").write_bytes(
        (SCRIPT_DIR / "publication_lint.py").read_bytes()
    )
    paper_inputs = {
        "paper_style": paper_files[manuscript_kit.STYLE_FILE],
        "paper_template": paper_files[manuscript_kit.TEMPLATE_FILE],
        "claims_tex": paper_dir / manuscript_kit.CLAIMS_FILE,
        "references_bib": paper_dir / manuscript_kit.BIB_FILE,
        "seeded_reference_list": paper_dir / "seeded_reference_list.json",
    }
    figure_inputs = {
        "figure_toolkit": figure_dir / "paper_figures.py",
        "figure_renderer": figure_dir / "render_figure.py",
        "figure_lint": figure_dir / "publication_lint.py",
        **{
            f"basemap_{index:02d}": figure_dir / name
            for index, name in enumerate(FIGURE_KIT_ASSETS, 1)
        },
    }
    return paper_inputs, figure_inputs


def _deliverable_kit_inputs(run_dir: Path) -> tuple[dict[str, Path], dict[str, Path]]:
    """Packet inputs for the kits already installed at the start of the wave.

    Revision cycles re-bind the same files (the registry and citations are
    frozen for the run), so a revising writer or designer may read the kit
    without the controller re-installing it.
    """
    paper_dir = run_dir / PAPER_KIT_DIR
    figure_dir = run_dir / FIGURE_KIT_DIR
    paper_inputs = {
        "paper_style": paper_dir / manuscript_kit.STYLE_FILE,
        "paper_template": paper_dir / manuscript_kit.TEMPLATE_FILE,
        "claims_tex": paper_dir / manuscript_kit.CLAIMS_FILE,
        "references_bib": paper_dir / manuscript_kit.BIB_FILE,
        "seeded_reference_list": paper_dir / "seeded_reference_list.json",
    }
    figure_inputs = {
        "figure_toolkit": figure_dir / "paper_figures.py",
        "figure_renderer": figure_dir / "render_figure.py",
        "figure_lint": figure_dir / "publication_lint.py",
        **{
            f"basemap_{index:02d}": figure_dir / name
            for index, name in enumerate(FIGURE_KIT_ASSETS, 1)
        },
    }
    missing = [
        str(path.relative_to(run_dir))
        for path in (*paper_inputs.values(), *figure_inputs.values())
        if not path.is_file()
    ]
    if missing:
        raise AutoResearchError(
            "deliverable kits are incomplete: " + ", ".join(missing)
        )
    return paper_inputs, figure_inputs


PREFLIGHT_RULE = (
    "Before compiling or rendering, run python scripts/auto_research.py doctor: exit 0 means "
    "this host has a TeX engine, a usable font stack, every LaTeX package gga-paper.sty needs, "
    "an SVG renderer and (ideally) poppler; exit 2 lists the blockers to report to the host "
    "instead of substituting a browser or office export."
)
DELIVERABLE_RULE = (
    "Declare only your own deliverables as artifacts. Never re-declare packet inputs "
    "that are review provenance or earlier work: feedback_tasks.json, review prose or "
    "receipts, and the previous cycle's manuscript or figure files (vendored copies "
    "under frozen_inputs/ or similar are rejected by hash and would leak feedback into "
    "the next reviewer's packet). Kit files you ship unchanged (gga-paper.sty, "
    "claims.tex, references.bib) may be declared."
)


def _manuscript_payload_contract() -> dict[str, Any]:
    return {
        "artifact_path_rule": ARTIFACT_PATH_RULE,
        "deliverable_rule": DELIVERABLE_RULE,
        "preflight": PREFLIGHT_RULE,
        "self_check": SELF_CHECK_RULE,
        "typesetting": {
            "contract": manuscript_kit.CONTRACT_ID,
            "start_from": f"{PAPER_KIT_DIR}/{manuscript_kit.TEMPLATE_FILE}",
            "must_load": "\\usepackage{gga-paper} (copy gga-paper.sty next to the source)",
            "claims": (
                "\\input{claims} from the paper kit; cite every number with "
                "\\claimref{claim_id}; every id listed in payload claim_ids must appear as a "
                "mark in the source; \\claim{...} inline tags and \\texttt identifiers "
                "in prose are rejected; finish with \\printclaimledger"
            ),
            "sections": (
                "every frozen paper-spine section (except Title/Abstract) must exist as a "
                "\\section or \\subsection heading in the source; the section_manifest is "
                "checked against the headings, not trusted on its own"
            ),
            "captions": (
                f"each figure caption states the takeaway, then the encoding, then what is a "
                f"diagnostic rather than an effect (at least {manuscript_kit.MIN_CAPTION_CHARS} characters)"
            ),
            "references": (
                "\\bibliography{references} with a submitted references.bib (start from the "
                "seeded file); every \\cite key must exist in the bib and the payload "
                "reference_list must list exactly the bib keys you cite"
            ),
            "figures": (
                "\\includegraphics[width=\\linewidth]{...pdf} inside \\begin{figure}[t] with "
                "\\caption and \\label, placed in the body before the bibliography and "
                "referenced in the text; never fix a height. Draw embedded figures with the "
                f"bound figure kit ({FIGURE_KIT_DIR}/paper_figures.py + render_figure.py) so they "
                "share the storyboard's visual language; in revision cycles embed the figure "
                "designer's canonical renders (previous_figure_designer_artifact_* inputs)"
            ),
            "pdf": (
                "compile with latexmk -pdf (or pdflatex+bibtex); the PDF must be a TeX "
                "product with an Abstract on page one, numbered sections and at least "
                f"{manuscript_kit.MIN_PDF_PAGES} pages"
            ),
        },
        "required_keys": [
            "artifacts",
            "claim_ids",
            "contribution_map",
            "reference_list",
            "typeset_manifest",
        ],
        "typeset_manifest_keys": [
            "source_artifact",
            "pdf_artifact",
            "section_manifest",
            "bib_artifact",
        ],
    }


def _figure_payload_contract() -> dict[str, Any]:
    return {
        "artifact_path_rule": ARTIFACT_PATH_RULE,
        "deliverable_rule": DELIVERABLE_RULE,
        "preflight": PREFLIGHT_RULE,
        "self_check": SELF_CHECK_RULE,
        "figure_kit": {
            "contract": "gga-figure-kit-v1",
            "toolkit": f"{FIGURE_KIT_DIR}/paper_figures.py (Figure, Axes, MapPanel; Okabe-Ito palette; pt-based typography)",
            "renderer": (
                f"python {FIGURE_KIT_DIR}/render_figure.py --svg fig.svg --pdf fig.pdf --png fig.png "
                "exports same-size vector PDF and 288 dpi PNG and verifies their aspect"
            ),
            "basemap": (
                f"{FIGURE_KIT_DIR}/natural-earth-*.json; MapPanel draws coastline, Admin-0 and "
                'China Admin-1 and tags the group data-gga-layer="basemap"'
            ),
        },
        "rules": [
            "one figure = one SVG source + PDF + PNG with identical aspect ratio (lint compares them)",
            f"spatial roles ({', '.join(sorted(SPATIAL_FIGURE_ROLES))}) must contain the basemap layer",
            "no text below the print font floor; no text run longer than 120 characters -- caveats go in the manuscript caption",
            "no gradients, glow, drop shadows or decorative boxes; grayscale must remain readable",
            "every plotted number traces to a claim id listed in figure_specs[].claim_ids",
        ],
        "required_keys": ["artifacts", "claim_ids", "figure_specs"],
    }


def _start_paper_production(
    run_dir: Path, state: dict[str, Any], *, writing_basis: str
) -> None:
    """Open the manuscript and figure wave on the pilot result now at the run root.

    ``writing_basis`` records why writing is allowed: a strong frontier, the
    best available executed pilot after every other direction failed (its
    frontier weakness is disclosed to the writer, the reviewer and the final
    manifest), or an evidence report.
    """
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
    disclosure = (
        None
        if writing_basis == WRITING_BASIS_STRONG
        else _frontier_disclosure(frontier, pilot_outcome["status"])
    )
    if writing_basis != WRITING_BASIS_STRONG:
        # Re-issue the gate receipt: the earlier one honestly said this
        # direction was not eligible on its own; it is eligible now only as the
        # best available executed pilot, and the receipt must say so.
        gate_receipt = {
            "schema_version": "gga-research-gate-receipt-v2",
            "paper_eligible": True,
            "executed_pilot": True,
            "writing_basis": writing_basis,
            "pilot_outcome": pilot_outcome["status"],
            "pilot_result_sha256": pilot_result["result_sha256"],
            "frontier_status": frontier["status"],
            "literature_result_sha256": literature_result["result_sha256"],
            "routing_destination": "paper_production",
            "disclosures": [disclosure],
            "decision_rule": (
                "No attempted direction reached a strong frontier position; the "
                "best executed pilot is written up with its frontier weakness "
                "disclosed, and the final grade cannot exceed "
                "draft_with_disclosed_findings."
            ),
        }
        gate_receipt["receipt_sha256"] = sha256_bytes(
            canonical_json_bytes(gate_receipt)
        )
        _write_json(run_dir / "research_gate_receipt.json", gate_receipt)
    paper_inputs, figure_inputs = _install_deliverable_kits(
        run_dir,
        [
            item
            for item in literature_result["payload"].get("citations", [])
            if isinstance(item, Mapping)
        ],
    )
    common = {
        "atlas_snapshot": run_dir / "atlas_snapshot.json",
        "selected_hypothesis": run_dir / "selected_hypothesis.json",
        "claim_registry": run_dir / "research_claim_registry.json",
        "research_gate_receipt": run_dir / "research_gate_receipt.json",
        "research_quality_contract": run_dir / "research_quality_contract.json",
        **_result_artifact_inputs(run_dir, "pilot_analyst", pilot_result),
        **_result_artifact_inputs(run_dir, "literature_researcher", literature_result),
    }
    framing = (
        ""
        if disclosure is None
        else (
            " The literature frontier verdict is "
            f"{frontier['status']}; frame the manuscript as a bounded replication, "
            "regional confirmation or null-result note, name the closest prior work "
            "in the contribution map, and claim no novelty beyond the disclosed delta."
        )
    )
    writer_output: dict[str, Any] = {
        "artifacts": "manuscript source plus a typeset PDF",
        "claim_ids": "all numerical claims",
        "contribution_map": "two to five claim-bound contributions with frontier delta",
        "reference_list": (
            "every cited reference with id, title, ordered authors, "
            "year, venue and a typed identifier"
        ),
        "typeset_manifest": (
            "source_artifact, pdf_artifact, and a section manifest "
            "covering the frozen paper spine"
        ),
    }
    figure_output: dict[str, Any] = {
        "artifacts": "figure generation source and SVG/PDF/PNG renders per figure",
        "claim_ids": "all plotted claims",
        "figure_specs": (
            "primary, spatial, and robustness storyboard with render "
            "review, candidate comparison, source-fidelity statement "
            "and an editable source per figure"
        ),
    }
    writer_output["payload_contract"] = _manuscript_payload_contract()
    figure_output["payload_contract"] = _figure_payload_contract()
    if disclosure is not None:
        writer_output["frontier_disclosure"] = disclosure
        figure_output["frontier_disclosure"] = disclosure
    _write_packet(
        run_dir,
        role="manuscript_writer",
        purpose=(
            "Draft an evidence-first empirical manuscript whose contribution "
            "map states the frontier delta and binds every contribution to "
            "executed claims, then typeset it with the frozen gga-paper style into "
            "a section-complete PDF." + framing
        ),
        inputs={
            **common,
            **paper_inputs,
            **figure_inputs,
            "paper_spine": run_dir / "paper_spine.json",
        },
        required_output=writer_output,
    )
    _write_packet(
        run_dir,
        role="figure_designer",
        purpose=(
            "Design a data-bearing visual argument, not a status dashboard: "
            "primary result, spatial pattern, and robustness or independent "
            "validation must each answer a scientific question after "
            "comparing candidate designs and auditing source fidelity. Draw with "
            "the frozen figure kit (offline basemap, print typography, same-size "
            "PDF/PNG export); caveats belong in captions, never inside the figure."
        ),
        inputs={
            **common,
            **figure_inputs,
            "figure_contract": run_dir / "figure_contract.json",
        },
        required_output=figure_output,
    )
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "manuscript_and_figures",
            "active_cycle": INITIAL_CYCLE,
            "required_roles": list(SECOND_WAVE),
            "revision_count": 0,
            "deliverable_mode": "empirical_article",
            "research_gate": {
                "paper_eligible": True,
                "pilot_outcome": pilot_outcome["status"],
                "frontier_status": frontier["status"],
                "routing_destination": "paper_production",
                "writing_basis": writing_basis,
            },
        }
    )
    _append_event(
        run_dir,
        "second_agent_wave_ready",
        {"roles": list(SECOND_WAVE), "writing_basis": writing_basis},
    )


def _restore_attempt(
    run_dir: Path, state: dict[str, Any], entry: Mapping[str, Any]
) -> None:
    """Bring an archived attempt back to the run root as the manuscript basis.

    The archive stays byte-complete (its manifest keeps pointing at real
    files); the run root receives a copy, and ``restored.json`` records the
    correspondence so auditors can verify both sides by hash.
    """
    archive_dir = run_dir / str(entry["archive_dir"])
    copied: list[str] = []
    for name in ATTEMPT_SCOPED_ENTRIES:
        source = archive_dir / name
        if source.exists() and not source.is_symlink():
            if (run_dir / name).exists():
                raise AutoResearchError(f"cannot restore {name}: run root is not clean")
            if source.is_dir():
                shutil.copytree(source, run_dir / name, symlinks=False)
            else:
                shutil.copyfile(source, run_dir / name)
            copied.append(name)
    restored_as = int(state.get("attempt") or 1) + 1
    _write_json(
        archive_dir / "restored.json",
        {
            "schema_version": "gga-research-attempt-restore-v2",
            "restored_as_attempt": restored_as,
            "copied_entries": copied,
            "archive_retained": True,
            "reason": "best available executed pilot after every other direction failed",
        },
    )
    for item in state.get("attempt_history") or []:
        if item.get("archive_dir") == entry["archive_dir"]:
            item["restored_as_attempt"] = restored_as
    state["attempt"] = restored_as
    state["selected_candidate_id"] = str(entry["candidate_id"])


def _writeable_rank(item: Mapping[str, Any]) -> tuple[int, int, int]:
    outcome_rank = 0 if item.get("pilot_outcome") == "supported_effect" else 1
    frontier_rank = 0 if item.get("frontier_status") == "needs_verification" else 1
    return (outcome_rank, frontier_rank, int(item.get("attempt") or 0))


def _start_evidence_report(run_dir: Path, state: dict[str, Any], reason: str) -> None:
    """Turn a run without any executed pilot into a reviewed evidence report.

    Every archived attempt's diagnostic claims, literature verdict and gate
    receipt become the report's evidence; the acquisition/audit candidates
    become its recommendation.  The same writer, figure, citation-audit and
    review roles run, so the deliverable is typeset, cited and independently
    reviewed -- graded ``evidence_report``, never an empirical article.
    """
    attempts_dir = run_dir / "attempts"
    archives = (
        sorted(path for path in attempts_dir.glob("attempt-*") if path.is_dir())
        if attempts_dir.is_dir()
        else []
    )
    if not archives:
        raise AutoResearchError(
            "evidence report requires at least one archived attempt"
        )
    attempt_outcomes: list[dict[str, Any]] = []
    pilot_claims: list[dict[str, Any]] = []
    verified_citations: list[dict[str, Any]] = []
    attempt_inputs: dict[str, Path] = {}
    for archive in archives:
        manifest = _read_object(archive / "attempt_manifest.json")
        pilot_path = archive / "agents" / "pilot_analyst" / "result.json"
        literature_path = archive / "agents" / "literature_researcher" / "result.json"
        gate_path = archive / "research_gate_receipt.json"
        outcome: dict[str, Any] = {
            "attempt": manifest.get("attempt"),
            "candidate_id": manifest.get("candidate_id"),
            "research_gate": manifest.get("research_gate"),
            "archive_dir": archive.relative_to(run_dir).as_posix(),
        }
        if pilot_path.is_file():
            pilot = _read_object(pilot_path)
            outcome["evidence_summary"] = (
                (pilot.get("payload") or {}).get("analysis_outcome") or {}
            ).get("evidence_summary")
            for claim in (pilot.get("payload") or {}).get("claims", []):
                if isinstance(claim, Mapping):
                    pilot_claims.append(
                        {
                            **dict(claim),
                            "claim_id": f"{archive.name}:{claim.get('claim_id')}",
                            "source_attempt": manifest.get("attempt"),
                            "source_candidate_id": manifest.get("candidate_id"),
                            "artifact": f"{archive.relative_to(run_dir).as_posix()}/{claim.get('artifact')}",
                        }
                    )
            attempt_inputs[f"{archive.name}_pilot_result"] = pilot_path
        if literature_path.is_file():
            literature = _read_object(literature_path)
            for citation in (literature.get("payload") or {}).get("citations", []):
                if isinstance(citation, Mapping):
                    verified_citations.append(
                        {**dict(citation), "source_attempt": manifest.get("attempt")}
                    )
            attempt_inputs[f"{archive.name}_literature_result"] = literature_path
        if gate_path.is_file():
            attempt_inputs[f"{archive.name}_gate_receipt"] = gate_path
        attempt_outcomes.append(outcome)
    candidates_document = _read_object(
        run_dir / "deterministic" / "discovery_candidates.json"
    )
    acquisition_candidates = [
        dict(item)
        for item in candidates_document.get("discovery_candidates") or []
        if isinstance(item, Mapping)
        and str((item.get("research_readiness") or {}).get("paper_track") or "")
        == "acquisition_or_audit_plan"
    ]
    snapshot = _read_object(run_dir / "atlas_snapshot.json")
    selected = {
        "candidate_id": "evidence-report",
        "type": "data_adequacy_and_direction_report",
        "title": "Data adequacy and research-direction report for the frozen atlas",
        "question": (
            "Which empirical directions did the frozen atlas support, why did each "
            "attempted direction stop at the scientific gate, and which acquisition "
            "or audit work would unlock an empirical article?"
        ),
        "attempted_candidate_ids": [item["candidate_id"] for item in attempt_outcomes],
        "acquisition_candidate_ids": [
            item.get("candidate_id") for item in acquisition_candidates
        ],
    }
    _write_json(
        run_dir / "selected_hypothesis.json",
        {
            "schema_version": "gga-selected-hypothesis-v1",
            "candidate": selected,
            "selection_status": "evidence_report_after_exhausted_empirical_candidates",
        },
    )
    _write_json(
        run_dir / "research_claim_registry.json",
        {
            "schema_version": "gga-auto-research-claim-registry-v2",
            "deliverable_mode": "evidence_report",
            "atlas_claims": snapshot["claim_ledger"]["claims"],
            "pilot_claims": pilot_claims,
            "verified_citations": verified_citations,
            "attempt_outcomes": attempt_outcomes,
            "acquisition_candidates": acquisition_candidates,
            "claim_boundary": (
                "Atlas claims are recomputed from frozen outputs; attempt-prefixed "
                "pilot claims are diagnostic numbers from directions that could not "
                "support an empirical article and must be reported as such."
            ),
        },
    )
    latest_gate = dict(state.get("research_gate") or {})
    gate_receipt = {
        "schema_version": "gga-research-gate-receipt-v2",
        "paper_eligible": True,
        "executed_pilot": False,
        "writing_basis": WRITING_BASIS_REPORT,
        "pilot_outcome": latest_gate.get("pilot_outcome"),
        "frontier_status": latest_gate.get("frontier_status"),
        "routing_destination": "evidence_report",
        "attempted_directions": len(attempt_outcomes),
        "decision_rule": (
            "No attempted direction executed a paper-eligible pilot; the run "
            "delivers a typeset, cited and independently reviewed data-adequacy "
            "and research-direction report instead of stopping without a product."
        ),
    }
    gate_receipt["receipt_sha256"] = sha256_bytes(canonical_json_bytes(gate_receipt))
    _write_json(run_dir / "research_gate_receipt.json", gate_receipt)
    # Contracts for the report: reuse the frozen quality contract, adapt the
    # paper spine and the figure roles to what a report must show.
    latest_archive = archives[-1]
    quality = _read_object(latest_archive / "research_quality_contract.json")
    quality["deliverable_mode"] = "evidence_report"
    quality["paper_entry_gate"] = {
        **dict(quality.get("paper_entry_gate") or {}),
        "evidence_report_rule": (
            "When every empirical candidate is exhausted without an executed "
            "pilot, the run writes an evidence report: a3 judges the value and "
            "honesty of the data-adequacy finding, a4 judges fit for a data or "
            "methods venue, and no empirical effect may be claimed."
        ),
    }
    _write_json(run_dir / "research_quality_contract.json", quality)
    _write_json(
        run_dir / "paper_spine.json",
        {
            "schema_version": "gga-paper-spine-v1",
            "deliverable_mode": "evidence_report",
            "status": "planned_from_archived_attempts",
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
                "Findings per attempted direction",
                "Data adequacy assessment",
                "Recommended acquisition and audit plan",
                "Materials and methods",
                "Introduction",
                "Abstract",
                "Title",
            ],
            "required_sections": [
                "Position within the current frontier",
                "Data and code availability",
                "Agent disclosure",
                "Limitations",
            ],
            "claim_policy": "every numerical sentence resolves to a claim ID",
        },
    )
    _write_json(
        run_dir / "figure_contract.json",
        {
            "schema_version": "gga-figure-contract-v2",
            "deliverable_mode": "evidence_report",
            "status": "planned_from_archived_attempts",
            "method_figure": {"required": False, "panels": []},
            "result_figures": {
                "must_reference_claim_ids": True,
                "caption_fields": [
                    "cohort",
                    "n",
                    "unit",
                    "uncertainty",
                    "claim_boundary",
                ],
                "required_roles": sorted(REQUIRED_REPORT_FIGURE_ROLES),
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
                "every visual element must trace to frozen atlas claims or "
                "attempt-prefixed pilot diagnostics"
            ),
            "role_semantics": {
                "coverage_and_gaps": "where the frozen atlas has evidence and where it does not",
                "pilot_diagnostics": "what each attempted direction measured and why it stopped",
                "acquisition_priority": "which acquisition or audit tasks would unlock an article",
            },
            "editable_delivery": (
                "each figure binds an editable source so reviewers can regenerate it"
            ),
            "review_loop": "render_inspect_revise_at_least_once",
            "figure_kit": _figure_kit_contract(),
        },
    )
    paper_inputs, figure_inputs = _install_deliverable_kits(run_dir, verified_citations)
    common = {
        "atlas_snapshot": run_dir / "atlas_snapshot.json",
        "selected_hypothesis": run_dir / "selected_hypothesis.json",
        "claim_registry": run_dir / "research_claim_registry.json",
        "research_gate_receipt": run_dir / "research_gate_receipt.json",
        "research_quality_contract": run_dir / "research_quality_contract.json",
        "discovery_candidates": run_dir / "deterministic" / "discovery_candidates.json",
        **attempt_inputs,
    }
    _write_packet(
        run_dir,
        role="manuscript_writer",
        purpose=(
            "Write a typeset data-adequacy and research-direction report: state what "
            "each attempted direction measured, why it stopped at the scientific gate, "
            "what the frozen atlas can and cannot support, and which acquisition or "
            "audit work would unlock an empirical article. Claim no empirical effect. "
            "Typeset with the frozen gga-paper style from the paper kit."
        ),
        inputs={
            **common,
            **paper_inputs,
            **figure_inputs,
            "paper_spine": run_dir / "paper_spine.json",
        },
        required_output={
            "artifacts": "report source plus a typeset PDF",
            "claim_ids": "all numerical claims (atlas claims and attempt-prefixed pilot diagnostics)",
            "contribution_map": (
                "two to five claim-bound contributions whose frontier_delta states "
                "the adequacy finding, not a scientific effect"
            ),
            "reference_list": (
                "every cited reference with id, title, ordered authors, "
                "year, venue and a typed identifier"
            ),
            "typeset_manifest": (
                "source_artifact, pdf_artifact, bib_artifact and a section manifest "
                "covering the report spine"
            ),
            "deliverable_mode": "evidence_report",
            "payload_contract": _manuscript_payload_contract(),
        },
    )
    _write_packet(
        run_dir,
        role="figure_designer",
        purpose=(
            "Design three data-bearing report figures: coverage and gaps of the "
            "frozen atlas, diagnostics of every attempted pilot, and the ranked "
            "acquisition or audit priorities; every mark traces to a claim ID. Draw "
            "with the frozen figure kit (offline basemap, print typography, same-size "
            "PDF/PNG export)."
        ),
        inputs={
            **common,
            **figure_inputs,
            "figure_contract": run_dir / "figure_contract.json",
        },
        required_output={
            "artifacts": "figure generation source and SVG/PDF/PNG renders per figure",
            "claim_ids": "all plotted claims",
            "figure_specs": (
                "coverage_and_gaps, pilot_diagnostics and acquisition_priority "
                "storyboard with render review, candidate comparison, source-fidelity "
                "statement and an editable source per figure"
            ),
            "deliverable_mode": "evidence_report",
            "payload_contract": _figure_payload_contract(),
        },
    )
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "manuscript_and_figures",
            "active_cycle": INITIAL_CYCLE,
            "required_roles": list(SECOND_WAVE),
            "revision_count": 0,
            "deliverable_mode": "evidence_report",
            "selected_candidate_id": "evidence-report",
            "attempt": int(state.get("attempt") or 1) + 1,
            "research_gate": {
                "paper_eligible": True,
                "pilot_outcome": latest_gate.get("pilot_outcome"),
                "frontier_status": latest_gate.get("frontier_status"),
                "routing_destination": "evidence_report",
                "writing_basis": WRITING_BASIS_REPORT,
            },
        }
    )
    _append_event(
        run_dir,
        "evidence_report_started",
        {
            "reason": reason,
            "attempted_directions": len(attempt_outcomes),
            "roles": list(SECOND_WAVE),
        },
    )


def _prepare_candidate_fallback(
    run_dir: Path, state: dict[str, Any], reason: str
) -> None:
    """Continue the same run on the next untried empirical candidate.

    The failed direction is archived under ``attempts/``, the contracts and
    first-wave packets are rebuilt for the next candidate, and the run returns
    to ``awaiting_agents`` -- the agent host keeps serving packets without ever
    noticing a redirect.  Every attempted candidate (plus, after an
    ``unsupported_inputs`` pilot, its same-data-signature siblings) becomes
    exhausted, so the chain is finite and ends honestly at
    ``needs_research_redirection`` when no empirical direction remains.
    """
    queue_path = run_dir / "candidate_fallback_queue.json"
    queue: list[dict[str, Any]] = []
    if queue_path.is_file():
        raw_queue = _read_object(queue_path).get("candidates")
        if isinstance(raw_queue, list):
            queue = [dict(item) for item in raw_queue if isinstance(item, Mapping)]
    candidates_document = _read_object(
        run_dir / "deterministic" / "discovery_candidates.json"
    )
    all_candidates = [
        item
        for item in candidates_document.get("discovery_candidates") or []
        if isinstance(item, Mapping)
    ]
    by_id = {str(item.get("candidate_id")): item for item in all_candidates}
    failed_id = str(state.get("selected_candidate_id") or "")
    exhausted = set(str(item) for item in state.get("exhausted_candidate_ids") or [])
    exhausted.add(failed_id)
    gate = dict(state.get("research_gate") or {})
    if gate.get("pilot_outcome") == "unsupported_inputs" and failed_id in by_id:
        failed_signature = candidate_data_signature(by_id[failed_id])
        for item in queue:
            if item.get("data_signature") == failed_signature:
                exhausted.add(str(item["candidate_id"]))
    next_candidate = next(
        (item for item in queue if str(item["candidate_id"]) not in exhausted),
        None,
    )
    history = list(state.get("attempt_history") or [])
    if next_candidate is None or str(next_candidate["candidate_id"]) not in by_id:
        # No untried empirical direction remains.  The run still has to end
        # with a product: write up the best executed pilot with its frontier
        # weakness disclosed, or -- when no attempt ever executed -- a reviewed
        # evidence report built from the archived attempts.
        state["exhausted_candidate_ids"] = sorted(exhausted)
        state["attempt_history"] = history
        _append_event(
            run_dir,
            "candidate_fallback_exhausted",
            {"reason": reason, "exhausted_candidate_ids": sorted(exhausted)},
        )
        current = {
            "attempt": int(state.get("attempt") or 1),
            "candidate_id": failed_id,
            "pilot_outcome": gate.get("pilot_outcome"),
            "frontier_status": gate.get("frontier_status"),
            "writeable": gate.get("pilot_outcome") in PAPER_ELIGIBLE_PILOT_OUTCOMES,
            "archive_dir": None,
        }
        writeable = [item for item in history if item.get("writeable")]
        if current["writeable"]:
            writeable.append(current)
        state["fallback"] = {
            "next_candidate_id": None,
            "remaining_candidates": 0,
            "reason": reason,
            "exhausted_candidate_ids": sorted(exhausted),
            "decision": (
                "best_available_executed_pilot" if writeable else "evidence_report"
            ),
        }
        if writeable:
            best = min(writeable, key=_writeable_rank)
            if best["archive_dir"] is not None:
                archived = _archive_attempt(run_dir, state, reason)
                history.append(archived)
                state["attempt_history"] = history
                _restore_attempt(run_dir, state, best)
            state["fallback"]["written_candidate_id"] = str(best["candidate_id"])
            _start_paper_production(
                run_dir, state, writing_basis=WRITING_BASIS_BEST_AVAILABLE
            )
            return
        archived = _archive_attempt(run_dir, state, reason)
        history.append(archived)
        state["attempt_history"] = history
        _start_evidence_report(run_dir, state, reason)
        return
    archived = _archive_attempt(run_dir, state, reason)
    history.append(archived)
    selected = dict(by_id[str(next_candidate["candidate_id"])])
    _build_research_contracts(
        run_dir, selected, candidates_document, exhausted_candidate_ids=exhausted
    )
    remaining = [
        item
        for item in queue
        if str(item["candidate_id"]) not in exhausted
        and str(item["candidate_id"]) != str(next_candidate["candidate_id"])
    ]
    state.pop("research_gate", None)
    state.update(
        {
            "status": "awaiting_agents",
            "stage": "pilot_and_literature",
            "active_cycle": INITIAL_CYCLE,
            "required_roles": list(FIRST_WAVE),
            "revision_count": 0,
            "selected_candidate_id": str(next_candidate["candidate_id"]),
            "attempt": archived["attempt"] + 1,
            "attempt_history": history,
            "exhausted_candidate_ids": sorted(exhausted),
            "fallback": {
                "next_candidate_id": str(next_candidate["candidate_id"]),
                "next_candidate_title": str(next_candidate.get("title") or ""),
                "remaining_candidates": len(remaining),
                "reason": reason,
                "from_candidate_id": failed_id,
                "archived_attempt": archived["archive_dir"],
            },
        }
    )
    _append_event(
        run_dir,
        "candidate_redirected_in_run",
        {
            "from_candidate_id": failed_id,
            "to_candidate_id": str(next_candidate["candidate_id"]),
            "attempt": archived["attempt"] + 1,
            "archived_attempt": archived["archive_dir"],
            "remaining_candidates": len(remaining),
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
        executed_pilot = pilot_outcome["status"] in PAPER_ELIGIBLE_PILOT_OUTCOMES
        paper_eligible = executed_pilot and frontier["status"] == WRITING_BASIS_STRONG
        routing_destination = (
            "paper_production"
            if paper_eligible
            else str(pilot_outcome.get("routing_destination") or "candidate_selection")
        )
        gate_receipt = {
            "schema_version": "gga-research-gate-receipt-v2",
            "paper_eligible": paper_eligible,
            "executed_pilot": executed_pilot,
            "writing_basis": WRITING_BASIS_STRONG if paper_eligible else None,
            "pilot_outcome": pilot_outcome["status"],
            "pilot_result_sha256": pilot_result["result_sha256"],
            "frontier_status": frontier["status"],
            "literature_result_sha256": literature_result["result_sha256"],
            "routing_destination": routing_destination,
            "decision_rule": (
                "An executed supported effect or null and a verified empirical "
                "frontier position start writing immediately. An executed pilot "
                "with a weak or unverified frontier is kept as a writeable "
                "attempt while other candidates are tried, and becomes the "
                "manuscript basis with a disclosed frontier finding once no "
                "stronger direction remains. A run whose attempts never execute "
                "a pilot still ends with a reviewed evidence report."
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
            _start_paper_production(run_dir, state, writing_basis=WRITING_BASIS_STRONG)
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
                raise AutoResearchError("carried citation audit is not fully verified")
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


# LaTeX packages gga-paper.sty requires unconditionally (the Times stack is
# probed separately because it degrades newtx -> mathptmx -> lmodern).
REQUIRED_LATEX_PACKAGES = (
    "geometry",
    "amsmath",
    "fontenc",
    "microtype",
    "graphicx",
    "booktabs",
    "array",
    "tabularx",
    "enumitem",
    "caption",
    "subcaption",
    "placeins",
    "fancyhdr",
    "xcolor",
    "hyperref",
    "natbib",
)
FONT_STACKS = (
    ("newtx", ("newtxtext", "newtxmath", "centernot")),
    ("mathptmx", ("mathptmx",)),
    ("lmodern", ("lmodern",)),
)
TOOLCHAIN_REPORT_VERSION = "gga-deliverable-toolchain-v1"


def _which_with_user_bin(*names: str) -> str | None:
    """PATH lookup that also sees ~/.local/bin (TinyTeX) in non-login shells."""
    user_bin = Path.home() / ".local" / "bin"
    for name in names:
        found = shutil.which(name) or shutil.which(name, path=str(user_bin))
        if found:
            return found
    return None


def _kpsewhich(kpsewhich: str, filename: str) -> bool:
    try:
        completed = subprocess.run(
            [kpsewhich, filename],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())


def toolchain_report() -> dict[str, Any]:
    """Pre-flight for the manuscript and figure waves: what the host can compile and render.

    Hosts run this before opening writer/figure sessions so a missing TeX
    engine, font stack, LaTeX package or browser surfaces as an explicit
    blocker instead of a run that waits on a packet forever.
    """
    tex_engine = _which_with_user_bin("latexmk", "pdflatex", "xelatex", "lualatex")
    kpsewhich = _which_with_user_bin("kpsewhich")
    font_stack = None
    packages: dict[str, bool] = {}
    if kpsewhich:
        for stack_name, styles in FONT_STACKS:
            if all(_kpsewhich(kpsewhich, f"{style}.sty") for style in styles):
                font_stack = stack_name
                break
        packages = {
            name: _kpsewhich(kpsewhich, f"{name}.sty")
            for name in REQUIRED_LATEX_PACKAGES
        }
    missing_packages = sorted(name for name, present in packages.items() if not present)
    browser = render_figure.find_chrome()
    svg_renderer = (
        "chrome"
        if browser
        else "rsvg-convert"
        if shutil.which("rsvg-convert")
        else "inkscape"
        if shutil.which("inkscape")
        else None
    )
    poppler = {
        name: bool(shutil.which(name))
        for name in ("pdfinfo", "pdftotext", "pdffonts", "pdftoppm")
    }
    blockers: list[str] = []
    if not tex_engine:
        blockers.append(
            "no TeX engine (latexmk/pdflatex) on PATH or in ~/.local/bin; the manuscript cannot be compiled"
        )
    if tex_engine and not kpsewhich:
        blockers.append(
            "kpsewhich not found; LaTeX package availability cannot be verified"
        )
    if kpsewhich and font_stack is None:
        blockers.append(
            "no usable Times stack (newtx, mathptmx) nor lmodern; gga-paper.sty cannot load"
        )
    if missing_packages:
        blockers.append("missing LaTeX packages: " + ", ".join(missing_packages))
    if svg_renderer is None:
        blockers.append(
            "no SVG renderer (Chrome/Chromium, rsvg-convert or inkscape); figures cannot be exported"
        )
    notes: list[str] = []
    if not poppler["pdftoppm"]:
        notes.append(
            "pdftoppm absent: figure PNGs fall back to cropped browser screenshots"
        )
    if not (poppler["pdfinfo"] and poppler["pdftotext"] and poppler["pdffonts"]):
        notes.append(
            "poppler text/font probes absent: manuscript PDF checks degrade to byte-level producer and page-count checks"
        )
    return {
        "schema_version": TOOLCHAIN_REPORT_VERSION,
        "ready": not blockers,
        "tex_engine": tex_engine,
        "kpsewhich": kpsewhich,
        "font_stack": font_stack,
        "latex_packages": packages,
        "missing_latex_packages": missing_packages,
        "browser": browser,
        "svg_renderer": svg_renderer,
        "poppler": poppler,
        "blockers": blockers,
        "notes": notes,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "doctor",
        help="report whether this host can compile the manuscript and render the figures (exit 2 when blocked)",
    )
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
    submit.add_argument(
        "--validate-only",
        action="store_true",
        help=(
            "run every acceptance check against the active packet without "
            "recording a result or advancing the run"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            result = toolchain_report()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["ready"] else 2
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
        elif args.validate_only:
            result = validate_agent_result(
                args.run_dir,
                role=args.role,
                invocation_id=args.invocation_id,
                model_family=args.model_family,
                payload=_read_object(args.payload),
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
