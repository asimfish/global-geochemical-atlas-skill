#!/usr/bin/env python3
"""Evidence-driven research loop controller for the atlas workflow.

The controller wraps ``run_atlas_request.py`` with an auditable
detect -> repair -> re-run -> compare loop:

- Early gates catch dead work before a full round is spent: online routing
  viability, minimum input columns, and frozen-request drift are checked
  first, and every round is classified immediately after it exits.
- After each round it harvests machine-readable issues from the execution
  receipt, ``validate_outputs.py``, ``iteration_backlog.csv`` and
  ``anomaly_report.json``, then splits them into autonomously repairable
  and manual work.
- Online research is the default.  After each budget-bounded round the controller
  evaluates requested dimensions, source diversity, record volume,
  provenance completeness and anomaly-background viability.  If the result
  is still thin but the routed sources can yield more observations, it grows
  the acquisition target and runs another round.
- Transient source failures are retried. Schema, license, coordinate and
  method issues remain explicit manual work; censored values and scientific
  limits are never treated as repairable defects.
- The loop stops honestly: ``converged``, ``no_autonomous_repair``,
  ``no_progress`` (two rounds with an identical actionable signature),
  source-capacity exhaustion, round budget, the configured total budget, or
  ``needs_human_review``.

Every round writes into its own ``rounds/round-NN`` directory; canonical
artifacts are never edited in place. The cumulative ``loop_report.json``
follows ``references/loop-report.schema.json``. Re-invoking the controller
on the same output directory appends rounds (agent-in-the-loop manual
repairs between invocations), refuses to continue if the frozen request
changed, and runs at most one explicit probe round when the caller resumes
after a manual-repair stop (``no_autonomous_repair``, ``no_progress`` or
``repair_queue_pending``), so an out-of-loop source repair is observed instead
of restating the stale verdict.

Exit codes: 0 success/partial_success, 1 needs_human_review, 2 failed/usage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import source_adapters
import source_router
import skill_snapshot
import spatial_sufficiency
import spatial_scope
import validate_outputs as output_validator
import v4_semantics

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPORT_VERSION = "self-correction-loop-report-v7"
SUFFICIENCY_VERSION = "atlas-data-sufficiency-v9"
REPORT_FILENAME = "loop_report.json"
RESEARCH_RECEIPT_FILENAME = "research_delivery_receipt.json"
D1_REPAIR_QUEUE_FILENAME = "d1_repair_queue.json"
D1_QUEUE_CANDIDATE_FACT_KEYS = frozenset(
    {
        "viable_selected_source_ids",
        "observed_source_ids",
        "observed_lineage_ids",
        "observed_lineage_ids_by_medium",
    }
)
SOURCE_CATALOG_PATH = SKILL_DIR / "assets" / "source_catalog.json"
SOURCE_MANIFEST_PATH = SKILL_DIR / "assets" / "source_manifest.json"
FULL_PROFILE_ROOT = SKILL_DIR / "assets" / "v4-full-profiles"
ADMIN1_SEARCH_GAZETTEER_PATH = (
    SKILL_DIR / "assets" / "natural-earth-50m-admin1-search.json"
)
DEFAULT_MAX_ROUNDS = 24
MAX_ROUNDS_CAP = 24
MAX_TIME_BUDGET_SECONDS = 12 * 60 * 60.0
DEFAULT_TIME_BUDGET_SECONDS = MAX_TIME_BUDGET_SECONDS
DEFAULT_ROUND_TIMEOUT_SECONDS = 30 * 60.0
DEFAULT_RUN_TIMEOUT_SECONDS = 29 * 60.0
DEFAULT_SOURCE_TIMEOUT_SECONDS = 10 * 60.0
MINIMUM_DELIVERY_TIME_BUDGET_SECONDS = DEFAULT_ROUND_TIMEOUT_SECONDS
DEFAULT_PER_ANALYTE_OBSERVATIONS = 512
# One requested element may now use the complete 200k research ceiling.  The
# former 50k per-analyte cap could stop a sparse-dimension repair even while the
# frozen request still had capacity; the total request ceiling remains binding.
DEFAULT_MAX_PER_ANALYTE_OBSERVATIONS = 200_000
DEFAULT_ACQUISITION_GROWTH = 2.0
DEFAULT_MINIMUM_RECORDS = 5_000
DEFAULT_MINIMUM_UNIQUE_SAMPLES = 2_000
DEFAULT_MINIMUM_PROVENANCE_RATE = 1.0
DEFAULT_MINIMUM_GLOBAL_MACROREGIONS = 4
DEFAULT_MINIMUM_MACROREGION_SAMPLES = 100
DEFAULT_MAXIMUM_GLOBAL_MACROREGION_SHARE = 0.60
MINIMUM_ANALYTICAL_METHOD_RATE_BY_MEDIUM = 0.20
MINIMUM_METHOD_READY_SAMPLES_BY_MEDIUM = 20
MINIMUM_METHOD_READY_LINEAGES_BY_MEDIUM = 1
# A source/medium lineage that contributes a material share of the archive must
# not be hidden by method-ready rows from another lineage.  The broad archive
# may retain its real, traceable observations, but a dominant method-unknown
# compilation remains an explicit acquisition/evidence-repair debt.
MINIMUM_MATERIAL_SOURCE_RECORDS = 50
MINIMUM_MATERIAL_SOURCE_SHARE_BY_MEDIUM = 0.10
MINIMUM_ANALYTICAL_METHOD_RATE_BY_MATERIAL_SOURCE = 0.20
PUBLISHER_ABSENT_METHOD_REASON_CODES = frozenset(
    {
        "publisher_compilation_omits_row_method",
        "not_reported",
        "source_not_reported",
        "not_reported_in_concentration_csv",
        "workbook_reports_no_analytical_method",
    }
)
# A requested medium must not pass merely because one small dataset happened to
# contribute a handful of rows.  This is a coverage-capacity diagnostic, not a
# demand that natural archives contain equal numbers of rock, soil, sediment
# and water samples.  The target is bounded by the dominant observed medium,
# the request record ceiling and a deliberately modest absolute/relative floor.
MINIMUM_DIMENSION_BALANCE_SAMPLES = 100
MINIMUM_DIMENSION_BALANCE_SHARE = 0.20
MAXIMUM_DIMENSION_BALANCE_SAMPLES = 2_000
MINIMUM_ELEMENT_MEDIUM_BALANCE_SAMPLES = 20
MINIMUM_ELEMENT_MEDIUM_BALANCE_SHARE = 0.10
MAXIMUM_ELEMENT_MEDIUM_BALANCE_SAMPLES = 500
SPATIAL_SUFFICIENCY_POLICY = spatial_sufficiency.load_policy()
GLOBAL_SPATIAL_POLICY = SPATIAL_SUFFICIENCY_POLICY["global_scope"]
REGIONAL_SPATIAL_POLICY = SPATIAL_SUFFICIENCY_POLICY["regional_scope"]
GLOBAL_SPATIAL_POLICY_VERSION = SPATIAL_SUFFICIENCY_POLICY["policy_version"]
GLOBAL_PRIORITY_COUNTRY_COUNT = int(GLOBAL_SPATIAL_POLICY["priority_country_count"])
GLOBAL_CORE_PRIORITY_COUNTRY_COUNT = int(
    GLOBAL_SPATIAL_POLICY["core_priority_country_count"]
)
GLOBAL_MINIMUM_PRIORITY_COUNTRY_COVERAGE_RATE = float(
    GLOBAL_SPATIAL_POLICY["minimum_priority_country_pass_rate"]
)
GLOBAL_MINIMUM_COUNTRY_SAMPLES = int(
    GLOBAL_SPATIAL_POLICY["minimum_country_canonical_samples"]
)
GLOBAL_MINIMUM_COUNTRY_GRID_CELLS = int(
    GLOBAL_SPATIAL_POLICY["minimum_country_occupied_cells"]
)
GLOBAL_MAXIMUM_COUNTRY_GRID_CELLS = int(
    GLOBAL_SPATIAL_POLICY["maximum_country_occupied_cells"]
)
GLOBAL_MINIMUM_COUNTRY_GRID_COVERAGE_RATE = float(
    GLOBAL_SPATIAL_POLICY["minimum_country_grid_coverage_rate"]
)
GLOBAL_MINIMUM_MACROREGION_GRID_CELLS = int(
    GLOBAL_SPATIAL_POLICY["minimum_macroregion_occupied_cells"]
)
GLOBAL_MINIMUM_MACROREGION_GRID_COVERAGE_RATE = float(
    GLOBAL_SPATIAL_POLICY["minimum_macroregion_grid_coverage_rate"]
)
GLOBAL_MINIMUM_LAND_GRID_COVERAGE_RATE = float(
    GLOBAL_SPATIAL_POLICY["minimum_land_grid_coverage_rate"]
)
GLOBAL_SPATIAL_EXCLUDED_COUNTRIES = frozenset(
    GLOBAL_SPATIAL_POLICY["excluded_country_iso_a3"]
)


def _valid_web_url(value: Any) -> bool:
    text = str(value or "").strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


REGIONAL_MINIMUM_CANONICAL_SAMPLES = int(
    REGIONAL_SPATIAL_POLICY["minimum_canonical_samples"]
)
REGIONAL_MINIMUM_COVERAGE_GRID_CELLS = int(
    REGIONAL_SPATIAL_POLICY["minimum_assessable_coverage_cells"]
)
REGIONAL_MINIMUM_COVERAGE_GRID_RATE = float(
    REGIONAL_SPATIAL_POLICY["minimum_grid_coverage_rate"]
)
LAND_MACROREGIONS = frozenset(
    {
        "Africa",
        "Antarctica",
        "Asia",
        "Europe",
        "North America",
        "Oceania",
        "South America",
    }
)
GLOBAL_SPATIAL_MACROREGIONS = frozenset(LAND_MACROREGIONS - {"Antarctica"})
REQUIRED_INPUT_COLUMNS = ("element_or_analyte", "value", "unit", "medium")
MANUAL_PLAN_GROUP_CAP = 50

RETRYABLE_RUN_STATUSES = frozenset({"network_unavailable", "round_timeout"})
ONLINE_RETRYABLE_RUN_STATUSES = frozenset({"incomplete_retrieval"})
RETRYABLE_SOURCE_MARKERS = (
    "timeout",
    "timed out",
    "network",
    "connection",
    "unavailable",
    "temporarily",
    "budget",
    "http 5",
    "http error 5",
)
NON_RETRYABLE_SOURCE_MARKERS = (
    "source_not_accessible",
    "research use",
    "license",
    "conflicting_evidence",
    "unsupported",
    "invalid",
    "schema",
    "allocation",
)
GATE_STOP_REASONS = {
    "routing_viability": "unsupported_scope",
    "input_header": "invalid_input",
}
CLAIM_BOUNDARY = (
    "本报告记录工程修复与数据充分性循环的证据和停机原因。自主动作仅限重试瞬态"
    "获取失败及在冻结请求内扩大已路由来源的采集量；scientific_limit（如删失观测）"
    "不是缺陷。来源、许可、CRS 或方法证据不能由循环猜测。任何轮次都不修改冻结请求"
    "或既有证据。"
)

SCIENTIFIC_BLOCKING_QC_FLAGS = frozenset(
    {
        "MISSING_VALUE",
        "INVALID_NUMERIC_VALUE",
        "INVALID_MISSING_REASON",
        "INVALID_DETECTION_LIMIT",
        "INVALID_QUANTITATION_LIMIT",
        "NEGATIVE_CONCENTRATION",
        "UNSUPPORTED_UNIT",
        "UNSUPPORTED_MOLAR_MASS",
        "UNSUPPORTED_MOLAR_SPECIES",
        "UNSUPPORTED_SPECIES_CONVERSION",
        "OXIDE_ELEMENT_MISMATCH",
        "AMBIGUOUS_AQUEOUS_RATIO_UNIT",
        "INVALID_COORDINATE",
        "UNSUPPORTED_SOURCE_CRS",
        "INVALID_COORDINATE_POLICY",
        "DEPTH_RANGE_INVALID",
        "INVALID_GEOLOGIC_DISTANCE",
        "BATCH_QC_FAILED",
    }
)


class LoopUsageError(RuntimeError):
    """Raised for controller-level misuse that must abort before any round."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_last_json_line(text: str) -> dict[str, Any] | None:
    for raw_line in reversed(text.strip().splitlines()):
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def is_gate_round(record: dict[str, Any]) -> bool:
    return not record.get("command")


def persisted_elapsed_seconds(rounds: Sequence[Mapping[str, Any]]) -> float:
    """Return audited work time from prior invocations of the same loop."""

    return sum(
        max(0.0, float(item.get("duration_seconds") or 0.0))
        for item in rounds
        if item.get("command")
    )


def source_failure_retryable(error: str) -> bool:
    """Classify one per-source acquisition error string.

    Conservative default: unknown errors are NOT retryable, so the loop never
    burns rounds on failures it cannot reason about, and non-retryable markers
    (license, schema, accessibility) always win over transient markers.
    """
    lowered = error.casefold()
    if any(marker in lowered for marker in NON_RETRYABLE_SOURCE_MARKERS):
        return False
    return any(marker in lowered for marker in RETRYABLE_SOURCE_MARKERS)


def run_failure_retryable(status: str | None, mode: str) -> bool:
    if status is None:
        return False
    if status in RETRYABLE_RUN_STATUSES:
        return True
    return mode == "online" and status in ONLINE_RETRYABLE_RUN_STATUSES


def read_backlog(path: Path) -> dict[str, Any]:
    """Harvest iteration_backlog.csv into status counts and manual groups."""
    status_counts: Counter[str] = Counter()
    issue_codes: Counter[str] = Counter()
    auto_recheck = 0
    manual_groups: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.is_file():
        return {
            "available": False,
            "status_counts": {},
            "issue_codes": {},
            "auto_recheck": None,
            "manual_groups": [],
        }
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            status = (row.get("status") or "").strip()
            status_counts[status] += 1
            if (row.get("auto_recheck") or "").strip().casefold() == "true":
                auto_recheck += 1
            if status != "action_required":
                continue
            code = (row.get("issue_code") or "UNSPECIFIED").strip()
            issue_codes[code] += 1
            key = ((row.get("stage_owner") or "unknown").strip(), code)
            group = manual_groups.setdefault(
                key,
                {
                    "stage_owner": key[0],
                    "issue_code": key[1],
                    "count": 0,
                    "recommended_action": (row.get("recommended_action") or "").strip(),
                },
            )
            group["count"] += 1
    ordered = sorted(
        manual_groups.values(),
        key=lambda item: (-item["count"], item["stage_owner"], item["issue_code"]),
    )
    return {
        "available": True,
        "status_counts": dict(status_counts),
        "issue_codes": dict(issue_codes),
        "auto_recheck": auto_recheck,
        "manual_groups": ordered[:MANUAL_PLAN_GROUP_CAP],
    }


def read_anomaly_groups(path: Path) -> tuple[int | None, int | None, int | None]:
    if not path.is_file():
        return None, None, None
    try:
        report = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None, None, None
    groups = report.get("groups")
    if not isinstance(groups, list):
        return None, None, report.get("candidate_count")
    analyzed = sum(1 for group in groups if group.get("status") == "analyzed")
    insufficient = sum(
        1 for group in groups if str(group.get("status", "")).startswith("insufficient")
    )
    return analyzed, insufficient, report.get("candidate_count")


def acquisition_target(args: argparse.Namespace, round_index: int) -> int:
    """Return the target selected by the previous sufficiency decision.

    Round number alone must never increase acquisition. Transient retries keep
    the same target; only ``can_expand_acquisition`` advances it.
    """

    del round_index  # Retained in the signature for gate-record callers.
    selected = getattr(
        args, "active_per_analyte_observations", args.per_analyte_observations
    )
    return min(args.max_per_analyte_observations, max(1, int(selected)))


def source_order_offset(round_index: int) -> int:
    """Return the deterministic queue rotation for a one-indexed round."""

    if round_index < 1:
        raise LoopUsageError("round index must be positive")
    return round_index - 1


def requires_checkpoint_only(args: argparse.Namespace) -> bool:
    """Return whether an online run cannot complete even one default round."""

    return args.mode == "online" and (
        args.time_budget_seconds < MINIMUM_DELIVERY_TIME_BUDGET_SECONDS
    )


def read_database_coverage(path: Path) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    elements: Counter[str] = Counter()
    media: Counter[str] = Counter()
    spatial_domains: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    source_media: dict[str, set[str]] = {}
    source_spatial_domains: dict[str, set[str]] = {}
    lineage_media: dict[str, set[str]] = {}
    lineage_spatial_domains: dict[str, set[str]] = {}
    element_media: Counter[tuple[str, str]] = Counter()
    element_samples: dict[str, set[tuple[str, str]]] = {}
    element_medium_samples: dict[tuple[str, str], set[tuple[str, str]]] = {}
    dimension_bands: dict[str, Counter[str]] = {
        key: Counter()
        for key in (
            "source_evidence",
            "analytical_readiness",
            "spatial_usability",
            "workflow_usability",
        )
    }
    metadata_counts: Counter[str] = Counter()
    metadata_by_medium: dict[str, Counter[str]] = {}
    metadata_by_source_medium: dict[tuple[str, str], Counter[str]] = {}
    method_missing_reasons_by_source_medium: dict[tuple[str, str], Counter[str]] = {}
    medium_samples: dict[str, set[tuple[str, str]]] = {}
    method_ready_samples_by_medium: dict[str, set[tuple[str, str]]] = {}
    method_ready_lineages_by_medium: dict[str, set[str]] = {}
    source_medium_samples: dict[tuple[str, str], set[tuple[str, str]]] = {}
    method_ready_samples_by_source_medium: dict[
        tuple[str, str], set[tuple[str, str]]
    ] = {}
    official_source_url_counts: Counter[str] = Counter()
    traceable = 0
    strict_provenance = 0
    geology_accounted = 0
    geology_present = 0
    strict_provenance_by_medium: Counter[str] = Counter()
    geology_accounted_by_medium: Counter[str] = Counter()
    geology_present_by_medium: Counter[str] = Counter()
    scientific_ready_samples_by_medium: dict[str, set[tuple[str, str]]] = {}
    scientific_ready_lineages_by_medium: dict[str, set[str]] = {}
    canonical = 0
    reported = 0
    unique_samples: set[tuple[str, str]] = set()
    canonical_samples: set[tuple[str, str]] = set()
    reported_samples: set[tuple[str, str]] = set()
    source_samples: dict[str, set[tuple[str, str]]] = {}
    macroregion_samples: dict[str, set[tuple[str, str]]] = {}
    country_samples: dict[str, set[tuple[str, str]]] = {}
    country_grid_cells: dict[str, set[str]] = {}
    grid_cell_samples: dict[str, set[tuple[str, str]]] = {}
    macroregion_grid_cells: dict[str, set[str]] = {}
    source_country_samples: dict[str, dict[str, set[tuple[str, str]]]] = {}
    display_mapped_samples: set[tuple[str, str]] = set()
    display_country_samples: dict[str, set[tuple[str, str]]] = {}
    display_country_grid_cells: dict[str, set[str]] = {}
    display_grid_cell_samples: dict[str, set[tuple[str, str]]] = {}
    display_macroregion_grid_cells: dict[str, set[str]] = {}
    source_display_country_samples: dict[str, dict[str, set[tuple[str, str]]]] = {}
    spatial_sample_details: dict[tuple[str, str], dict[str, Any]] = {}
    macroregion_registry = spatial_scope.load_macroregion_registry()
    unresolved_sample_identity_records = 0
    if not path.is_file():
        return {
            "records": 0,
            "elements": {},
            "media": {},
            "spatial_domains": {},
            "sources": {},
            "official_source_url_counts": {},
            "sources_by_medium": {},
            "sources_by_spatial_domain": {},
            "lineages": {},
            "lineages_by_medium": {},
            "lineages_by_spatial_domain": {},
            "element_medium_cells": {},
            "element_unique_samples": {},
            "element_medium_unique_samples": {},
            "dimension_band_counts": {},
            "metadata_counts": {},
            "metadata_by_medium": {},
            "metadata_by_source_medium": [],
            "medium_unique_samples": {},
            "method_ready_unique_samples_by_medium": {},
            "method_ready_lineages_by_medium": {},
            "traceable_records": 0,
            "strict_provenance_records": 0,
            "strict_provenance_records_by_medium": {},
            "geology_accounted_records": 0,
            "geology_accounted_records_by_medium": {},
            "geology_present_records": 0,
            "geology_present_records_by_medium": {},
            "scientific_ready_unique_samples_by_medium": {},
            "scientific_ready_lineages_by_medium": {},
            "canonical_coordinate_records": 0,
            "reported_coordinate_records": 0,
            "unique_samples": 0,
            "canonical_coordinate_samples": 0,
            "reported_coordinate_samples": 0,
            "source_unique_samples": {},
            "macroregion_unique_samples": {},
            "country_unique_samples": {},
            "country_occupied_grid_cells": {},
            "grid_cell_unique_samples": {},
            "macroregion_occupied_grid_cells": {},
            "source_country_unique_samples": {},
            "display_country_unique_samples": {},
            "display_country_occupied_grid_cells": {},
            "display_grid_cell_unique_samples": {},
            "display_macroregion_occupied_grid_cells": {},
            "source_display_country_unique_samples": {},
            "spatial_samples": [],
            "unresolved_sample_identity_records": 0,
        }
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts["records"] += 1
            element = str(row.get("element_or_analyte") or "").strip()
            medium = str(row.get("medium") or "").strip()
            spatial_domain = spatial_scope.record_spatial_domain(row)
            source = str(row.get("source_id") or "").strip()
            sample_identity = next(
                (
                    str(row.get(field) or "").strip()
                    for field in (
                        "sample_identity_group",
                        "sample_id",
                    )
                    if str(row.get(field) or "").strip()
                ),
                "",
            )
            sample_key: tuple[str, str] | None = None
            if source and sample_identity:
                sample_key = (source, sample_identity)
                unique_samples.add(sample_key)
                source_samples.setdefault(source, set()).add(sample_key)
                spatial_entry = spatial_sample_details.setdefault(
                    sample_key,
                    {
                        "source_id": source,
                        "sample_identity": sample_identity,
                        "canonical_point": None,
                        "display_point": None,
                        "elements": set(),
                        "media": set(),
                        "spatial_domains": set(),
                        "element_medium": set(),
                    },
                )
            else:
                unresolved_sample_identity_records += 1
                spatial_entry = None
            if element:
                elements[element] += 1
                if sample_key is not None:
                    element_samples.setdefault(element, set()).add(sample_key)
                if spatial_entry is not None:
                    spatial_entry["elements"].add(element)
            if medium:
                media[medium] += 1
                if sample_key is not None:
                    medium_samples.setdefault(medium, set()).add(sample_key)
                if spatial_entry is not None:
                    spatial_entry["media"].add(medium)
            spatial_domains[spatial_domain] += 1
            if spatial_entry is not None:
                spatial_entry["spatial_domains"].add(spatial_domain)
            if element and medium:
                element_media[(element, medium)] += 1
                if sample_key is not None:
                    element_medium_samples.setdefault((element, medium), set()).add(
                        sample_key
                    )
                if spatial_entry is not None:
                    spatial_entry["element_medium"].add(f"{element}|{medium}")
            if source:
                sources[source] += 1
                lineage = source_adapters.source_lineage_id(source)
                if medium:
                    source_media.setdefault(medium, set()).add(source)
                    lineage_media.setdefault(medium, set()).add(lineage)
                source_spatial_domains.setdefault(spatial_domain, set()).add(source)
                lineage_spatial_domains.setdefault(spatial_domain, set()).add(lineage)
                official_source_url = str(row.get("official_source_url") or "").strip()
                if _valid_web_url(official_source_url):
                    official_source_url_counts[source] += 1
            if source and str(row.get("source_locator") or "").strip():
                traceable += 1
            strict_provenance_present = bool(
                source
                and str(row.get("source_record_id") or "").strip()
                and str(row.get("source_file") or "").strip()
                and str(row.get("source_locator") or "").strip()
                and _valid_web_url(row.get("official_source_url"))
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(row.get("file_sha256") or "").strip().casefold(),
                )
                and str(row.get("dataset_title") or "").strip()
                and str(row.get("dataset_version") or "").strip()
                and str(row.get("license") or "").strip()
            )
            if strict_provenance_present:
                strict_provenance += 1
                strict_provenance_by_medium[medium] += 1
            geologic_context_present = any(
                str(row.get(field) or "").strip()
                for field in (
                    "matched_geologic_unit",
                    "geologic_unit",
                    "geologic_unit_raw",
                    "lithology",
                    "lithology_raw",
                    "soil_horizon",
                    "sediment_environment",
                    "water_body_type",
                    "tectonic_setting_raw",
                )
            )
            geology_disposition_present = bool(
                geologic_context_present
                or str(row.get("geology_missing_reason") or "").strip()
            )
            if geology_disposition_present:
                geology_accounted += 1
                geology_accounted_by_medium[medium] += 1
            if geologic_context_present:
                geology_present += 1
                geology_present_by_medium[medium] += 1
            metadata_presence = {
                "analytical_method": bool(
                    str(row.get("analytical_method") or "").strip()
                ),
                "method_accounted": bool(
                    str(row.get("analytical_method") or "").strip()
                    or str(row.get("method_missing_reason") or "").strip()
                ),
                "method_source_locator": bool(
                    str(row.get("method_source_locator") or "").strip()
                ),
                "coordinate_uncertainty_reported": bool(
                    str(row.get("coordinate_uncertainty_m") or "").strip()
                ),
                "coordinate_representation_resolution": bool(
                    str(row.get("coordinate_representation_resolution_m") or "").strip()
                ),
                "coordinate_accuracy_accounted": str(
                    row.get("coordinate_accuracy_evidence_status") or ""
                ).strip()
                in {
                    "source_reported_uncertainty",
                    "not_reported",
                    "not_applicable_no_canonical_coordinate",
                },
                "exact_record_locator": bool(
                    str(row.get("source_locator") or "").strip()
                ),
            }
            medium_metadata = metadata_by_medium.setdefault(medium, Counter())
            medium_metadata["records"] += 1
            source_medium_key = (source, medium)
            source_medium_metadata = None
            if source and medium:
                source_medium_metadata = metadata_by_source_medium.setdefault(
                    source_medium_key, Counter()
                )
                source_medium_metadata["records"] += 1
                if sample_key is not None:
                    source_medium_samples.setdefault(source_medium_key, set()).add(
                        sample_key
                    )
                if not metadata_presence["analytical_method"]:
                    reason = str(row.get("method_missing_reason") or "").strip()
                    method_missing_reasons_by_source_medium.setdefault(
                        source_medium_key, Counter()
                    )[reason or "unaccounted_in_input"] += 1
            for field, present in metadata_presence.items():
                if present:
                    metadata_counts[field] += 1
                    medium_metadata[field] += 1
                    if source_medium_metadata is not None:
                        source_medium_metadata[field] += 1
            if metadata_presence["analytical_method"] and medium:
                if sample_key is not None:
                    method_ready_samples_by_medium.setdefault(medium, set()).add(
                        sample_key
                    )
                if source:
                    method_ready_lineages_by_medium.setdefault(medium, set()).add(
                        source_adapters.source_lineage_id(source)
                    )
                    if sample_key is not None:
                        method_ready_samples_by_source_medium.setdefault(
                            source_medium_key, set()
                        ).add(sample_key)
            geology_scientifically_ready = bool(
                geologic_context_present
                or (
                    spatial_domain == "marine"
                    and medium in {"water", "sediment"}
                    and str(row.get("geology_missing_reason") or "").strip()
                    in {
                        "not_applicable_marine_water",
                        "not_applicable_marine_sediment",
                    }
                )
            )
            raw_qc_flags = str(row.get("qc_flags") or "").strip()
            try:
                parsed_qc_flags = json.loads(raw_qc_flags)
            except json.JSONDecodeError:
                parsed_qc_flags = None
            qc_disposition_present = isinstance(parsed_qc_flags, list)
            qc_blocks_scientific_use = bool(
                qc_disposition_present
                and SCIENTIFIC_BLOCKING_QC_FLAGS.intersection(
                    str(item) for item in parsed_qc_flags
                )
            )
            scientific_ready = bool(
                strict_provenance_present
                and geology_scientifically_ready
                and metadata_presence["analytical_method"]
                and str(row.get("latitude") or "").strip()
                and str(row.get("longitude") or "").strip()
                and str(row.get("normalized_value") or "").strip()
                and str(row.get("normalized_unit") or "").strip()
                and qc_disposition_present
                and not qc_blocks_scientific_use
            )
            if scientific_ready and sample_key is not None and medium:
                scientific_ready_samples_by_medium.setdefault(medium, set()).add(
                    sample_key
                )
                scientific_ready_lineages_by_medium.setdefault(medium, set()).add(
                    source_adapters.source_lineage_id(source)
                )
            canonical_point: tuple[float, float] | None = None
            if spatial_entry is not None and isinstance(
                spatial_entry.get("canonical_point"), list
            ):
                canonical_point = tuple(spatial_entry["canonical_point"])
            if (
                str(row.get("latitude") or "").strip()
                and str(row.get("longitude") or "").strip()
            ):
                canonical += 1
                if sample_key is not None and sample_key not in canonical_samples:
                    try:
                        latitude = float(str(row.get("latitude") or ""))
                        longitude = float(str(row.get("longitude") or ""))
                        canonical_point = (longitude, latitude)
                        if spatial_entry is not None:
                            spatial_entry["canonical_point"] = [longitude, latitude]
                            spatial_entry["display_point"] = [longitude, latitude]
                        country_code = spatial_scope.country_at_coordinate(
                            longitude, latitude
                        )
                        macroregion = (
                            macroregion_registry[country_code]
                            if country_code is not None
                            else "Open ocean / unassigned"
                        )
                    except (ValueError, spatial_scope.SpatialScopeError):
                        country_code = None
                        macroregion = "Unresolved"
                    canonical_samples.add(sample_key)
                    macroregion_samples.setdefault(macroregion, set()).add(sample_key)
                    if country_code is not None and canonical_point is not None:
                        cell_id = spatial_scope.coverage_grid_cell_id(*canonical_point)
                        country_samples.setdefault(country_code, set()).add(sample_key)
                        country_grid_cells.setdefault(country_code, set()).add(cell_id)
                        grid_cell_samples.setdefault(cell_id, set()).add(sample_key)
                        macroregion_grid_cells.setdefault(macroregion, set()).add(
                            cell_id
                        )
                        source_country_samples.setdefault(source, {}).setdefault(
                            country_code, set()
                        ).add(sample_key)
            if (
                str(row.get("original_latitude_raw") or "").strip()
                and str(row.get("original_longitude_raw") or "").strip()
            ):
                reported += 1
                if sample_key is not None:
                    reported_samples.add(sample_key)
            if sample_key is not None and sample_key not in display_mapped_samples:
                display_point = canonical_point
                if display_point is None:
                    try:
                        display_point = (
                            float(str(row.get("original_longitude_raw") or "")),
                            float(str(row.get("original_latitude_raw") or "")),
                        )
                    except ValueError:
                        display_point = None
                if display_point is not None:
                    if (
                        spatial_entry is not None
                        and spatial_entry.get("display_point") is None
                    ):
                        spatial_entry["display_point"] = list(display_point)
                    try:
                        display_country = spatial_scope.country_at_coordinate(
                            *display_point
                        )
                        display_macroregion = (
                            macroregion_registry[display_country]
                            if display_country is not None
                            else "Open ocean / unassigned"
                        )
                        display_cell = spatial_scope.coverage_grid_cell_id(
                            *display_point
                        )
                    except spatial_scope.SpatialScopeError:
                        display_country = None
                    if display_country is not None:
                        display_mapped_samples.add(sample_key)
                        display_country_samples.setdefault(display_country, set()).add(
                            sample_key
                        )
                        display_country_grid_cells.setdefault(
                            display_country, set()
                        ).add(display_cell)
                        display_grid_cell_samples.setdefault(display_cell, set()).add(
                            sample_key
                        )
                        display_macroregion_grid_cells.setdefault(
                            display_macroregion, set()
                        ).add(display_cell)
                        source_display_country_samples.setdefault(
                            source, {}
                        ).setdefault(display_country, set()).add(sample_key)
            raw_confidence = str(row.get("operational_confidence") or "").strip()
            if raw_confidence:
                try:
                    confidence = json.loads(raw_confidence)
                except json.JSONDecodeError:
                    confidence = {}
                quality_dimensions = (
                    confidence.get("quality_dimensions")
                    if isinstance(confidence, Mapping)
                    else {}
                )
                if not isinstance(quality_dimensions, Mapping):
                    quality_dimensions = {}
                for dimension, band_counts in dimension_bands.items():
                    value = quality_dimensions.get(dimension)
                    if isinstance(value, Mapping):
                        band = str(value.get("band") or "unknown")
                    elif dimension == "workflow_usability" and isinstance(
                        confidence, Mapping
                    ):
                        band = str(confidence.get("band") or "unknown")
                    else:
                        band = "unknown"
                    band_counts[band] += 1
    lineages = Counter()
    for source, count in sources.items():
        lineages[source_adapters.source_lineage_id(source)] += count
    return {
        "records": counts["records"],
        "elements": dict(sorted(elements.items())),
        "media": dict(sorted(media.items())),
        "spatial_domains": dict(sorted(spatial_domains.items())),
        "sources": dict(sorted(sources.items())),
        "official_source_url_counts": dict(sorted(official_source_url_counts.items())),
        "sources_by_medium": {
            medium: sorted(source_ids)
            for medium, source_ids in sorted(source_media.items())
        },
        "sources_by_spatial_domain": {
            domain: sorted(source_ids)
            for domain, source_ids in sorted(source_spatial_domains.items())
        },
        "lineages": dict(sorted(lineages.items())),
        "lineages_by_medium": {
            medium: sorted(lineage_ids)
            for medium, lineage_ids in sorted(lineage_media.items())
        },
        "lineages_by_spatial_domain": {
            domain: sorted(lineage_ids)
            for domain, lineage_ids in sorted(lineage_spatial_domains.items())
        },
        "element_medium_cells": {
            f"{element}|{medium}": count
            for (element, medium), count in sorted(element_media.items())
        },
        "element_unique_samples": {
            element: len(samples)
            for element, samples in sorted(element_samples.items())
        },
        "element_medium_unique_samples": {
            f"{element}|{medium}": len(samples)
            for (element, medium), samples in sorted(element_medium_samples.items())
        },
        "dimension_band_counts": {
            dimension: dict(sorted(counts.items()))
            for dimension, counts in dimension_bands.items()
        },
        "metadata_counts": dict(sorted(metadata_counts.items())),
        "metadata_by_medium": {
            medium: dict(sorted(counts.items()))
            for medium, counts in sorted(metadata_by_medium.items())
        },
        "metadata_by_source_medium": [
            {
                "source_id": source,
                "source_lineage_id": source_adapters.source_lineage_id(source),
                "medium": medium,
                "record_count": int(counts.get("records", 0)),
                "analytical_method_count": int(counts.get("analytical_method", 0)),
                "method_accounted_count": int(counts.get("method_accounted", 0)),
                "unique_samples": len(
                    source_medium_samples.get((source, medium), set())
                ),
                "method_ready_unique_samples": len(
                    method_ready_samples_by_source_medium.get((source, medium), set())
                ),
                "method_missing_reason_counts": dict(
                    sorted(
                        method_missing_reasons_by_source_medium.get(
                            (source, medium), Counter()
                        ).items()
                    )
                ),
            }
            for (source, medium), counts in sorted(metadata_by_source_medium.items())
        ],
        "medium_unique_samples": {
            medium: len(samples) for medium, samples in sorted(medium_samples.items())
        },
        "method_ready_unique_samples_by_medium": {
            medium: len(samples)
            for medium, samples in sorted(method_ready_samples_by_medium.items())
        },
        "method_ready_lineages_by_medium": {
            medium: sorted(lineages)
            for medium, lineages in sorted(method_ready_lineages_by_medium.items())
        },
        "traceable_records": traceable,
        "strict_provenance_records": strict_provenance,
        "strict_provenance_records_by_medium": dict(
            sorted(strict_provenance_by_medium.items())
        ),
        "geology_accounted_records": geology_accounted,
        "geology_accounted_records_by_medium": dict(
            sorted(geology_accounted_by_medium.items())
        ),
        "geology_present_records": geology_present,
        "geology_present_records_by_medium": dict(
            sorted(geology_present_by_medium.items())
        ),
        "scientific_ready_unique_samples_by_medium": {
            medium: len(samples)
            for medium, samples in sorted(scientific_ready_samples_by_medium.items())
        },
        "scientific_ready_lineages_by_medium": {
            medium: sorted(lineages)
            for medium, lineages in sorted(scientific_ready_lineages_by_medium.items())
        },
        "canonical_coordinate_records": canonical,
        "reported_coordinate_records": reported,
        "unique_samples": len(unique_samples),
        "canonical_coordinate_samples": len(canonical_samples),
        "reported_coordinate_samples": len(reported_samples),
        "source_unique_samples": {
            source: len(samples) for source, samples in sorted(source_samples.items())
        },
        "macroregion_unique_samples": {
            macroregion: len(samples)
            for macroregion, samples in sorted(macroregion_samples.items())
        },
        "country_unique_samples": {
            country: len(samples)
            for country, samples in sorted(country_samples.items())
        },
        "country_occupied_grid_cells": {
            country: sorted(cells)
            for country, cells in sorted(country_grid_cells.items())
        },
        "grid_cell_unique_samples": {
            cell_id: len(samples)
            for cell_id, samples in sorted(grid_cell_samples.items())
        },
        "macroregion_occupied_grid_cells": {
            macroregion: sorted(cells)
            for macroregion, cells in sorted(macroregion_grid_cells.items())
        },
        "source_country_unique_samples": {
            source: {
                country: len(samples) for country, samples in sorted(by_country.items())
            }
            for source, by_country in sorted(source_country_samples.items())
        },
        "display_country_unique_samples": {
            country: len(samples)
            for country, samples in sorted(display_country_samples.items())
        },
        "display_country_occupied_grid_cells": {
            country: sorted(cells)
            for country, cells in sorted(display_country_grid_cells.items())
        },
        "display_grid_cell_unique_samples": {
            cell_id: len(samples)
            for cell_id, samples in sorted(display_grid_cell_samples.items())
        },
        "display_macroregion_occupied_grid_cells": {
            macroregion: sorted(cells)
            for macroregion, cells in sorted(display_macroregion_grid_cells.items())
        },
        "source_display_country_unique_samples": {
            source: {
                country: len(samples) for country, samples in sorted(by_country.items())
            }
            for source, by_country in sorted(source_display_country_samples.items())
        },
        "spatial_samples": [
            {
                "source_id": value["source_id"],
                "sample_identity": value["sample_identity"],
                "canonical_point": value["canonical_point"],
                "display_point": value["display_point"],
                "elements": sorted(value["elements"]),
                "media": sorted(value["media"]),
                "spatial_domains": sorted(value["spatial_domains"]),
                "element_medium": sorted(value["element_medium"]),
            }
            for _, value in sorted(spatial_sample_details.items())
        ],
        "unresolved_sample_identity_records": unresolved_sample_identity_records,
    }


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _complete_profile_country_codes(source_id: str) -> set[str]:
    profile = _json_object(FULL_PROFILE_ROOT / source_id / "spatial_coverage.json")
    applicability = profile.get("region_applicability")
    if not isinstance(applicability, Mapping):
        return set()
    if applicability.get("country_index_status") != "complete_for_snapshot":
        return set()
    raw_codes = applicability.get("country_iso_a3_codes")
    return {
        str(item)
        for item in (raw_codes if isinstance(raw_codes, list) else [])
        if isinstance(item, str)
    }


def _entry_matches_request(
    entry: Mapping[str, Any], request: Mapping[str, Any]
) -> bool:
    media = {
        str(item)
        for item in (entry.get("media") if isinstance(entry.get("media"), list) else [])
    }
    if not media.intersection(str(item) for item in request.get("media") or []):
        return False
    target_analytes = entry.get("target_analytes")
    if isinstance(target_analytes, Mapping):
        elements = {str(item) for item in target_analytes}
        expected_counts = entry.get("expected_counts")
        count_by_analyte: Mapping[str, Any] = {}
        if isinstance(expected_counts, Mapping):
            for count_field in (
                "target_observations_by_analyte",
                "target_value_counts",
            ):
                candidate = expected_counts.get(count_field)
                if isinstance(candidate, Mapping):
                    count_by_analyte = candidate
                    break
        elements = {
            element
            for element in elements
            if element not in count_by_analyte
            or not isinstance(count_by_analyte[element], (int, float))
            or count_by_analyte[element] > 0
        }
        if not elements.intersection(
            str(item) for item in request.get("elements") or []
        ):
            return False
    return True


def _profile_spatial_domain(source_id: str) -> str | None:
    profile = _json_object(FULL_PROFILE_ROOT / source_id / "spatial_coverage.json")
    applicability = profile.get("region_applicability")
    if not isinstance(applicability, Mapping):
        return None
    domain = str(applicability.get("spatial_domain") or "").strip()
    return domain if domain in spatial_scope.VALID_SPATIAL_DOMAINS else None


def _entry_spatial_domains(source_id: str, entry: Mapping[str, Any] | None) -> set[str]:
    """Return only explicit, auditable source-domain semantics."""

    profile_domain = _profile_spatial_domain(source_id)
    if profile_domain:
        return {profile_domain}
    contract = v4_semantics.SOURCE_CONTRACTS.get(source_id, {})
    if str(contract.get("sediment_environment") or "").casefold() == "marine":
        return {"marine"}
    if str(contract.get("water_body_type") or "").casefold() == "seawater":
        return {"marine"}
    if source_id == "pangaea-east-china-sea-clay":
        return {"inland_water", "marine"}
    media = {
        str(item)
        for item in (
            entry.get("media")
            if isinstance(entry, Mapping) and isinstance(entry.get("media"), list)
            else []
        )
    }
    domains: set[str] = set()
    if media.intersection({"rock", "soil", "mineral", "concentrate"}):
        domains.add("land")
    # Unqualified sediment is not promoted to ocean evidence. It may be a land
    # or inland-water collection and therefore cannot prove the marine domain.
    if "sediment" in media:
        domains.update({"land", "inland_water"})
    if "water" in media:
        domains.add("inland_water")
    return domains


def _source_matches_requested_domain(
    source_id: str, entry: Mapping[str, Any] | None, request: Mapping[str, Any]
) -> bool:
    requested = {str(item) for item in request.get("spatial_domains") or []}
    return not requested or bool(_entry_spatial_domains(source_id, entry) & requested)


def _entry_declares_country(
    entry: Mapping[str, Any], country_code: str, country_registry: Mapping[str, Any]
) -> bool:
    coverage = entry.get("coverage")
    regions = (
        coverage.get("regions")
        if isinstance(coverage, Mapping) and isinstance(coverage.get("regions"), list)
        else []
    )
    aliases = {
        alias
        for alias, code in (country_registry.get("country_aliases") or {}).items()
        if code == country_code and len(alias) >= 3
    }
    for raw_region in regions:
        region = spatial_scope.normalize_alias(str(raw_region))
        if any(
            region == alias
            or (len(alias) >= 5 and alias in region)
            or (len(region) >= 5 and region in alias)
            for alias in aliases
        ):
            return True
    return False


def _country_source_candidates(
    country_code: str,
    selected_source_ids: set[str],
    request: Mapping[str, Any],
) -> dict[str, list[str]]:
    country_registry = spatial_scope.load_country_registry()
    manifest_sources = _json_object(SOURCE_MANIFEST_PATH).get("sources")
    manifest_sources = manifest_sources if isinstance(manifest_sources, Mapping) else {}
    catalog_sources = _json_object(SOURCE_CATALOG_PATH).get("sources")
    catalog_sources = catalog_sources if isinstance(catalog_sources, Mapping) else {}

    try:
        resolved_country = spatial_scope.resolve_region(country_code)
    except spatial_scope.SpatialScopeError:
        resolved_country = {}

    def applicable(source_id: str, entry: Mapping[str, Any] | None) -> bool:
        if not _source_matches_requested_domain(source_id, entry, request):
            return False
        domains = _entry_spatial_domains(source_id, entry)
        if "marine" in domains and "marine" in request.get("spatial_domains", []):
            source_bbox = _profile_bbox(source_id)
            if source_bbox is None or not resolved_country:
                return False
            analysis_bbox = spatial_scope.request_analysis_bbox(
                resolved_country,
                request.get("spatial_domains"),
                float(request.get("adjacent_marine_distance_km") or 0),
            )
            if spatial_scope.bbox_intersects(source_bbox, analysis_bbox):
                return True
        declared = entry is not None and _entry_declares_country(
            entry, country_code, country_registry
        )
        return country_code in _complete_profile_country_codes(source_id) or declared

    selected: list[str] = []
    for source_id in selected_source_ids:
        registry_entry = manifest_sources.get(source_id)
        if isinstance(registry_entry, Mapping) and not _entry_matches_request(
            registry_entry, request
        ):
            continue
        catalog_entry = catalog_sources.get(source_id)
        candidate_entry = (
            catalog_entry if isinstance(catalog_entry, Mapping) else registry_entry
        )
        if applicable(source_id, candidate_entry):
            selected.append(source_id)
    registered: list[str] = []
    for source_id, raw_entry in manifest_sources.items():
        if source_id in selected_source_ids or not isinstance(raw_entry, Mapping):
            continue
        if not _entry_matches_request(raw_entry, request):
            continue
        catalog_entry = catalog_sources.get(source_id)
        candidate_entry = (
            catalog_entry if isinstance(catalog_entry, Mapping) else raw_entry
        )
        if applicable(str(source_id), candidate_entry):
            registered.append(str(source_id))

    catalog: list[str] = []
    for source_id, raw_entry in catalog_sources.items():
        if source_id in selected_source_ids or source_id in registered:
            continue
        if not isinstance(raw_entry, Mapping) or not _entry_matches_request(
            raw_entry, request
        ):
            continue
        registered_entry = manifest_sources.get(source_id)
        if isinstance(registered_entry, Mapping) and not _entry_matches_request(
            registered_entry, request
        ):
            # Catalog metadata can be broader than one implemented product.
            # A registered Hg-only Australian adapter, for example, must not
            # be suggested for an As/Cu/Pb/Zn spatial gap.
            continue
        if applicable(str(source_id), raw_entry):
            catalog.append(str(source_id))
    return {
        "selected": sorted(selected),
        "registered": sorted(registered),
        "catalog": sorted(catalog),
    }


def _valid_bbox(value: Any) -> list[float] | None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in value
        )
    ):
        return None
    return [float(item) for item in value]


def _profile_bbox(source_id: str) -> list[float] | None:
    """Return an audited source envelope for scheduling, never for acceptance.

    Canonical profile bboxes are preferred.  A reported-coordinate envelope is
    reconstructed only when canonical coordinates are unavailable; callers use
    it to avoid retrying a demonstrably disjoint source, not to pass a WGS84
    coverage gate.
    """

    profile = _json_object(FULL_PROFILE_ROOT / source_id / "spatial_coverage.json")
    canonical_bbox = _valid_bbox(profile.get("bbox"))
    if canonical_bbox is not None:
        return canonical_bbox
    reported_cells = profile.get("reported_spatial_cell_ids")
    if not isinstance(reported_cells, list):
        return None
    points: list[tuple[float, float]] = []
    for raw_cell in reported_cells:
        try:
            cell_text = str(raw_cell)
            signed = re.fullmatch(r"(?P<lat>[+-]\d+):(?P<lon>[+-]\d+)", cell_text)
            if signed is not None:
                points.append(
                    (
                        float(int(signed["lon"])) + 0.5,
                        float(int(signed["lat"])) + 0.5,
                    )
                )
            else:
                points.append(spatial_scope.coverage_grid_cell_center(cell_text, 1.0))
        except (ValueError, spatial_scope.SpatialScopeError):
            continue
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return [
        min(longitudes) - 0.5,
        min(latitudes) - 0.5,
        max(longitudes) + 0.5,
        max(latitudes) + 0.5,
    ]


def _bbox_compatible_source_ids(
    source_ids: Sequence[str],
    target_bbox: Sequence[Any] | None,
    *,
    require_spatial_evidence: bool = False,
) -> list[str]:
    bbox = _valid_bbox(list(target_bbox or []))
    if bbox is None:
        return sorted({str(item) for item in source_ids})
    compatible: list[str] = []
    for raw_source_id in source_ids:
        source_id = str(raw_source_id)
        source_bbox = _profile_bbox(source_id)
        profile_path = FULL_PROFILE_ROOT / source_id / "spatial_coverage.json"
        if require_spatial_evidence and profile_path.is_file() and source_bbox is None:
            # A completed full-population profile with no canonical or reported
            # coordinate envelope cannot repair a spatial hole by requerying.
            continue
        # Unknown coverage remains a discovery possibility. A known disjoint
        # profile is the only case that can be safely removed from this target.
        if source_bbox is None or spatial_scope.bbox_intersects(source_bbox, bbox):
            compatible.append(source_id)
    return sorted(set(compatible))


def _source_matches_scope(
    source_id: str,
    catalog_entry: Mapping[str, Any] | None,
    request: Mapping[str, Any],
) -> bool:
    """Conservatively prove that a candidate can intersect the request scope."""

    try:
        resolved = spatial_scope.resolve_region(request.get("region"))
    except (KeyError, TypeError, ValueError, spatial_scope.SpatialScopeError):
        return False
    if resolved.get("key") == "global":
        return True
    country_code = str(resolved.get("country_code") or "")
    if country_code:
        if not _source_matches_requested_domain(source_id, catalog_entry, request):
            return False
        if "marine" in _entry_spatial_domains(
            source_id, catalog_entry
        ) and "marine" in request.get("spatial_domains", []):
            source_bbox = _profile_bbox(source_id)
            analysis_bbox = spatial_scope.request_analysis_bbox(
                resolved,
                request.get("spatial_domains"),
                float(request.get("adjacent_marine_distance_km") or 0),
            )
            if source_bbox and spatial_scope.bbox_intersects(
                source_bbox, analysis_bbox
            ):
                return True
        if country_code in _complete_profile_country_codes(source_id):
            return True
        if catalog_entry is not None:
            return _entry_declares_country(
                catalog_entry,
                country_code,
                spatial_scope.load_country_registry(),
            )
        return False
    source_bbox = _profile_bbox(source_id)
    request_bbox = resolved.get("bbox")
    return bool(
        source_bbox
        and isinstance(request_bbox, list)
        and len(request_bbox) == 4
        and spatial_scope.bbox_intersects(source_bbox, request_bbox)
    )


def _source_candidate_layers(
    *,
    selected_source_ids: set[str],
    request: Mapping[str, Any],
    elements: Sequence[str],
    media: Sequence[str],
    target_bbox: Sequence[Any] | None = None,
    target_spatial_domains: Sequence[str] | None = None,
    require_spatial_evidence: bool = False,
    excluded_lineages: set[str] | None = None,
) -> dict[str, list[str]]:
    """Resolve selected → registered → catalog candidates for a D1 task.

    Registry candidates have executable adapters and explicit analyte contracts.
    Catalog-only candidates are discovery leads whose content still needs
    verification; their inclusion never asserts that the requested analyte is
    present. Independent-lineage tasks may exclude already observed lineages.
    """

    narrowed_request = {
        "region": request.get("region"),
        "spatial_domains": list(target_spatial_domains)
        if target_spatial_domains is not None
        else list(request.get("spatial_domains") or []),
        "adjacent_marine_distance_km": request.get("adjacent_marine_distance_km", 0),
        "elements": list(elements)
        or [str(item) for item in request.get("elements") or []],
        "media": list(media) or [str(item) for item in request.get("media") or []],
    }
    excluded = excluded_lineages or set()
    manifest_sources = _json_object(SOURCE_MANIFEST_PATH).get("sources")
    manifest_sources = manifest_sources if isinstance(manifest_sources, Mapping) else {}
    catalog_sources = _json_object(SOURCE_CATALOG_PATH).get("sources")
    catalog_sources = catalog_sources if isinstance(catalog_sources, Mapping) else {}

    def lineage_allowed(source_id: str) -> bool:
        return source_adapters.source_lineage_id(source_id) not in excluded

    try:
        resolved = spatial_scope.resolve_region(request.get("region"))
    except (KeyError, TypeError, ValueError, spatial_scope.SpatialScopeError):
        resolved = {}
    country_code = str(resolved.get("country_code") or "")
    if country_code:
        layered = _country_source_candidates(
            country_code, selected_source_ids, narrowed_request
        )
        return {
            key: _bbox_compatible_source_ids(
                [source_id for source_id in values if lineage_allowed(source_id)],
                target_bbox,
                require_spatial_evidence=require_spatial_evidence,
            )
            for key, values in layered.items()
        }

    selected: list[str] = []
    registered: list[str] = []
    for raw_source_id, raw_entry in manifest_sources.items():
        source_id = str(raw_source_id)
        if not isinstance(raw_entry, Mapping) or not lineage_allowed(source_id):
            continue
        if not _entry_matches_request(raw_entry, narrowed_request):
            continue
        catalog_entry = catalog_sources.get(source_id)
        catalog_entry = catalog_entry if isinstance(catalog_entry, Mapping) else None
        if not _source_matches_scope(source_id, catalog_entry, narrowed_request):
            continue
        target = selected if source_id in selected_source_ids else registered
        target.append(source_id)

    catalog: list[str] = []
    for raw_source_id, raw_entry in catalog_sources.items():
        source_id = str(raw_source_id)
        if (
            source_id in manifest_sources
            or not isinstance(raw_entry, Mapping)
            or raw_entry.get("status") == "rejected"
            or not lineage_allowed(source_id)
            or not _entry_matches_request(raw_entry, narrowed_request)
            or not _source_matches_scope(source_id, raw_entry, narrowed_request)
        ):
            continue
        catalog.append(source_id)
    return {
        "selected": _bbox_compatible_source_ids(
            selected,
            target_bbox,
            require_spatial_evidence=require_spatial_evidence,
        ),
        "registered": _bbox_compatible_source_ids(
            registered,
            target_bbox,
            require_spatial_evidence=require_spatial_evidence,
        ),
        "catalog": _bbox_compatible_source_ids(catalog, target_bbox),
    }


@lru_cache(maxsize=1)
def _admin1_search_regions() -> tuple[dict[str, Any], ...]:
    asset = _json_object(ADMIN1_SEARCH_GAZETTEER_PATH)
    if asset.get("asset_version") != "ai4s-natural-earth-admin1-search-gazetteer-v1":
        return ()
    regions = asset.get("regions")
    if not isinstance(regions, list):
        return ()
    return tuple(item for item in regions if isinstance(item, dict))


def _bbox_overlap_area(left: Sequence[float], right: Sequence[float]) -> float:
    def longitude_segments(bbox: Sequence[float]) -> tuple[tuple[float, float], ...]:
        west = float(bbox[0])
        east = float(bbox[2])
        if west <= east:
            return ((west, east),)
        return ((west, 180.0), (-180.0, east))

    south = max(float(left[1]), float(right[1]))
    north = min(float(left[3]), float(right[3]))
    latitude_overlap = max(0.0, north - south)
    longitude_overlap = sum(
        max(0.0, min(left_east, right_east) - max(left_west, right_west))
        for left_west, left_east in longitude_segments(left)
        for right_west, right_east in longitude_segments(right)
    )
    return longitude_overlap * latitude_overlap


def _longitude_fraction(bbox: Sequence[float], longitude: float) -> float:
    """Locate a longitude inside a possibly antimeridian-wrapped bbox."""

    west = float(bbox[0])
    east = float(bbox[2])
    span = east - west if west <= east else east + 360.0 - west
    offset = (float(longitude) - west) % 360.0
    return min(1.0, max(0.0, offset / max(span, 1e-9)))


def _longitude_midpoint(bbox: Sequence[float]) -> float:
    west = float(bbox[0])
    east = float(bbox[2])
    span = east - west if west <= east else east + 360.0 - west
    midpoint = west + span / 2.0
    return midpoint - 360.0 if midpoint > 180.0 else midpoint


def regional_search_target(
    *,
    scope_label: str,
    scope_bbox: Sequence[Any],
    target_bbox: Sequence[Any],
    country_iso_a3: str | None,
    coverage_zone_id: str | None,
) -> dict[str, Any]:
    """Name one grid debt with directional and Admin-1 search hints.

    Gazetteer matches are deliberately annotations.  They improve discovery
    queries but never become point membership, canonical coordinates, or
    evidence that a named subdivision has been sampled.
    """

    target = _valid_bbox(list(target_bbox))
    scope = _valid_bbox(list(scope_bbox))
    aliases: list[str] = []
    direction = ""
    direction_zh = ""
    match = re.search(r"r([1-9])of([1-9]):c([1-9])of([1-9])", coverage_zone_id or "")
    if match:
        row, rows, column, columns = (int(item) for item in match.groups())
        # Regional rows are numbered south-to-north by the coverage engine.
        vertical = "south" if row <= rows / 2 else "north"
        horizontal = (
            "west"
            if column <= columns / 3
            else "east"
            if column > columns * 2 / 3
            else "central"
        )
        direction = f"{vertical}{horizontal}" if horizontal != "central" else vertical
    elif target is not None and scope is not None:
        x_fraction = _longitude_fraction(scope, _longitude_midpoint(target))
        y_fraction = ((target[1] + target[3]) / 2 - scope[1]) / max(
            1e-9, scope[3] - scope[1]
        )
        vertical = (
            "north" if y_fraction >= 0.6 else "south" if y_fraction <= 0.4 else ""
        )
        horizontal = (
            "west" if x_fraction <= 0.4 else "east" if x_fraction >= 0.6 else "central"
        )
        direction = f"{vertical}{horizontal}" if vertical else horizontal
    direction_zh = {
        "northwest": "西北",
        "northeast": "东北",
        "southwest": "西南",
        "southeast": "东南",
        "north": "北部",
        "south": "南部",
        "west": "西部",
        "east": "东部",
        "central": "中部",
    }.get(direction, "")
    if direction:
        aliases.extend((f"{direction} {scope_label}", f"{scope_label} {direction}"))
    if direction_zh:
        aliases.append(f"{scope_label}{direction_zh}")

    admin_matches: list[tuple[float, dict[str, Any]]] = []
    if target is not None and country_iso_a3:
        for region in _admin1_search_regions():
            if region.get("adm0_a3") != country_iso_a3:
                continue
            region_bbox = _valid_bbox(region.get("bbox"))
            if region_bbox is None:
                continue
            overlap = _bbox_overlap_area(target, region_bbox)
            if overlap > 0:
                admin_matches.append((overlap, region))
    admin_matches.sort(key=lambda item: (-item[0], str(item[1].get("name") or "")))
    admin1_names: list[str] = []
    for _, region in admin_matches[:8]:
        for key in ("name_en", "name", "name_zh", "gn_name"):
            value = str(region.get(key) or "").strip()
            if value and value not in aliases and value not in admin1_names:
                admin1_names.append(value)
    aliases.extend(admin1_names)
    aliases = list(dict.fromkeys(item for item in aliases if item))
    label_parts = [scope_label]
    if direction:
        label_parts.append(direction)
    if admin1_names:
        label_parts.append(", ".join(admin1_names[:4]))
    return {
        "target_label": " · ".join(label_parts),
        "search_aliases": aliases,
        "admin1_search_hints": admin1_names,
        "gazetteer_semantics": (
            "search hints only; bbox overlap is not point membership or coverage evidence"
        ),
    }


def _minimum_country_grid_cells(target_cell_count: int) -> int:
    """Scale a sentinel-country target without demanding uniform sampling."""

    if target_cell_count <= 0:
        return 0
    proportional = math.ceil(
        target_cell_count * GLOBAL_MINIMUM_COUNTRY_GRID_COVERAGE_RATE
    )
    return min(
        target_cell_count,
        GLOBAL_MAXIMUM_COUNTRY_GRID_CELLS,
        max(GLOBAL_MINIMUM_COUNTRY_GRID_CELLS, proportional),
    )


def _minimum_macroregion_grid_cells(target_cell_count: int) -> int:
    if target_cell_count <= 0:
        return 0
    return min(
        target_cell_count,
        max(
            GLOBAL_MINIMUM_MACROREGION_GRID_CELLS,
            math.ceil(
                target_cell_count * GLOBAL_MINIMUM_MACROREGION_GRID_COVERAGE_RATE
            ),
        ),
    )


def assess_global_spatial_coverage(
    database: Mapping[str, Any],
    selected_source_ids: set[str],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit continent, large-country and five-degree canonical coverage.

    This gate detects observation holes; it never interpolates them or treats
    an empty cell as evidence that an element is absent.  Country priorities
    are derived from the frozen Natural Earth cell index instead of a manually
    chosen geopolitical list. Antarctica and Greenland remain reported as
    polar gaps but are not default blockers for a general global atlas.
    """

    land_grid = spatial_scope.load_global_land_grid()
    country_registry = spatial_scope.load_country_registry()
    macroregions = spatial_scope.load_macroregion_registry()
    country_cells = {
        code: set(cells)
        for code, cells in (land_grid.get("country_cells") or {}).items()
    }
    eligible = [
        (code, len(cells))
        for code, cells in country_cells.items()
        if code not in GLOBAL_SPATIAL_EXCLUDED_COUNTRIES
    ]
    eligible.sort(key=lambda item: (-item[1], item[0]))
    priority_country_codes = [
        code for code, _ in eligible[:GLOBAL_PRIORITY_COUNTRY_COUNT]
    ]
    core_country_codes = priority_country_codes[:GLOBAL_CORE_PRIORITY_COUNTRY_COUNT]
    canonical_country_samples = database.get("country_unique_samples") or {}
    display_country_samples = database.get("display_country_unique_samples") or {}
    canonical_country_cells = {
        code: set(cells)
        for code, cells in (database.get("country_occupied_grid_cells") or {}).items()
    }
    display_country_cells = {
        code: set(cells)
        for code, cells in (
            database.get("display_country_occupied_grid_cells") or {}
        ).items()
    }
    canonical_macroregion_cells = {
        region: set(cells)
        for region, cells in (
            database.get("macroregion_occupied_grid_cells") or {}
        ).items()
    }

    country_metrics: dict[str, dict[str, Any]] = {}
    covered_priority_codes: list[str] = []
    for code in priority_country_codes:
        target_cell_count = len(country_cells.get(code, set()))
        minimum_cells = _minimum_country_grid_cells(target_cell_count)
        canonical_samples = int(canonical_country_samples.get(code, 0))
        occupied_cells = len(canonical_country_cells.get(code, set()))
        covered = (
            canonical_samples >= GLOBAL_MINIMUM_COUNTRY_SAMPLES
            and occupied_cells >= minimum_cells
        )
        if covered:
            covered_priority_codes.append(code)
        country = country_registry["by_code"][code]
        country_metrics[code] = {
            "country_name": country["name"],
            "country_name_zh": str(country.get("name_zh") or ""),
            "macroregion": macroregions[code],
            "target_land_grid_cells": target_cell_count,
            "canonical_unique_samples": canonical_samples,
            "reported_display_unique_samples": int(
                display_country_samples.get(code, 0)
            ),
            "canonical_occupied_grid_cells": occupied_cells,
            "reported_display_occupied_grid_cells": len(
                display_country_cells.get(code, set())
            ),
            "minimum_canonical_unique_samples": GLOBAL_MINIMUM_COUNTRY_SAMPLES,
            "minimum_canonical_occupied_grid_cells": minimum_cells,
            "status": "pass" if covered else "gap",
        }

    undercovered_priority_codes = [
        code for code in priority_country_codes if code not in covered_priority_codes
    ]
    undercovered_core_codes = [
        code for code in core_country_codes if code not in covered_priority_codes
    ]
    priority_coverage_rate = (
        len(covered_priority_codes) / len(priority_country_codes)
        if priority_country_codes
        else 0.0
    )
    macroregion_target_cell_counts = {
        region: len((land_grid.get("macroregion_cells") or {}).get(region, ()))
        for region in sorted(GLOBAL_SPATIAL_MACROREGIONS)
    }
    macroregion_minimum_cell_counts = {
        region: _minimum_macroregion_grid_cells(target_count)
        for region, target_count in macroregion_target_cell_counts.items()
    }
    macroregion_cell_counts = {
        region: len(canonical_macroregion_cells.get(region, set()))
        for region in sorted(GLOBAL_SPATIAL_MACROREGIONS)
    }
    macroregions_below_grid_minimum = [
        region
        for region, count in macroregion_cell_counts.items()
        if count < macroregion_minimum_cell_counts[region]
    ]

    target_tiers: dict[str, str] = {
        code: ("core" if code in core_country_codes else "extended")
        for code in undercovered_priority_codes
    }
    for region in macroregions_below_grid_minimum:
        remaining_cell_deficit = (
            macroregion_minimum_cell_counts[region] - macroregion_cell_counts[region]
        )
        region_candidates = [
            (code, len(cells))
            for code, cells in country_cells.items()
            if code not in GLOBAL_SPATIAL_EXCLUDED_COUNTRIES
            and macroregions.get(code) == region
        ]
        region_candidates.sort(key=lambda item: (-item[1], item[0]))
        for code, target_cell_count in region_candidates:
            occupied = len(canonical_country_cells.get(code, set()))
            local_deficit = max(
                0, _minimum_country_grid_cells(target_cell_count) - occupied
            )
            if local_deficit <= 0:
                continue
            target_tiers.setdefault(code, "macroregion_backfill")
            remaining_cell_deficit -= local_deficit
            if remaining_cell_deficit <= 0:
                break

    nonpolar_land_cells = {
        cell_id
        for code, cells in country_cells.items()
        if code not in GLOBAL_SPATIAL_EXCLUDED_COUNTRIES
        for cell_id in cells
    }
    canonical_land_cells = {
        cell_id
        for cells in canonical_country_cells.values()
        for cell_id in cells
        if cell_id in nonpolar_land_cells
    }
    display_land_cells = {
        cell_id
        for cells in display_country_cells.values()
        for cell_id in cells
        if cell_id in nonpolar_land_cells
    }
    minimum_land_cells = math.ceil(
        len(nonpolar_land_cells) * GLOBAL_MINIMUM_LAND_GRID_COVERAGE_RATE
    )
    remaining_global_deficit = max(0, minimum_land_cells - len(canonical_land_cells))
    if remaining_global_deficit:
        global_candidates = sorted(
            (
                (
                    code,
                    len(cells),
                    len(cells - canonical_country_cells.get(code, set())),
                )
                for code, cells in country_cells.items()
                if code not in GLOBAL_SPATIAL_EXCLUDED_COUNTRIES
            ),
            key=lambda item: (-item[2], -item[1], item[0]),
        )
        for code, target_cell_count, uncovered_cell_count in global_candidates:
            if uncovered_cell_count <= 0:
                continue
            occupied = len(canonical_country_cells.get(code, set()))
            local_deficit = max(
                0, _minimum_country_grid_cells(target_cell_count) - occupied
            )
            if local_deficit <= 0:
                continue
            if code in target_tiers:
                remaining_global_deficit -= local_deficit
                if remaining_global_deficit <= 0:
                    break
                continue
            target_tiers[code] = "global_backfill"
            remaining_global_deficit -= local_deficit
            if remaining_global_deficit <= 0:
                break

    tier_order = {
        "core": 0,
        "extended": 1,
        "macroregion_backfill": 2,
        "global_backfill": 3,
    }
    ordered_target_codes = sorted(
        target_tiers,
        key=lambda code: (
            tier_order[target_tiers[code]],
            -len(country_cells.get(code, set())),
            code,
        ),
    )
    geographic_search_targets: list[dict[str, Any]] = []
    for code in ordered_target_codes:
        target_cell_count = len(country_cells.get(code, set()))
        minimum_cells = _minimum_country_grid_cells(target_cell_count)
        canonical_samples = int(canonical_country_samples.get(code, 0))
        display_samples = int(display_country_samples.get(code, 0))
        canonical_cells = len(canonical_country_cells.get(code, set()))
        reasons: list[str] = []
        if canonical_samples < GLOBAL_MINIMUM_COUNTRY_SAMPLES:
            reasons.append("canonical_sample_shortfall")
        if canonical_cells < minimum_cells:
            reasons.append("canonical_cell_shortfall")
        if (
            display_samples >= GLOBAL_MINIMUM_COUNTRY_SAMPLES
            and canonical_samples < GLOBAL_MINIMUM_COUNTRY_SAMPLES
        ):
            reasons.append("reported_only_coordinate_evidence")
        macroregion = macroregions[code]
        if macroregion in macroregions_below_grid_minimum:
            reasons.append("macroregion_grid_shortfall")
        if len(canonical_land_cells) < minimum_land_cells:
            reasons.append("global_land_grid_shortfall")
        candidates = _country_source_candidates(code, selected_source_ids, request)
        if "reported_only_coordinate_evidence" in reasons:
            repair_mode = "repair_coordinate_evidence"
        elif candidates["selected"]:
            repair_mode = "requery_selected_source"
        elif candidates["registered"]:
            repair_mode = "route_registered_source"
        elif candidates["catalog"]:
            repair_mode = "implement_catalog_candidate"
        else:
            repair_mode = "targeted_source_discovery"
        country = country_registry["by_code"][code]
        geographic_search_targets.append(
            {
                "country_iso_a3": code,
                "country_name": country["name"],
                "country_name_zh": str(country.get("name_zh") or ""),
                "macroregion": macroregion,
                "priority_tier": target_tiers[code],
                "reason_codes": reasons,
                "canonical_unique_samples": canonical_samples,
                "reported_display_unique_samples": display_samples,
                "target_land_grid_cells": target_cell_count,
                "canonical_occupied_grid_cells": canonical_cells,
                "minimum_canonical_unique_samples": GLOBAL_MINIMUM_COUNTRY_SAMPLES,
                "minimum_canonical_occupied_grid_cells": minimum_cells,
                "macroregion_canonical_occupied_grid_cells": (
                    macroregion_cell_counts[macroregion]
                ),
                "macroregion_minimum_occupied_grid_cells": (
                    macroregion_minimum_cell_counts[macroregion]
                ),
                "repair_mode": repair_mode,
                "selected_source_candidates": candidates["selected"],
                "registered_source_candidates": candidates["registered"],
                "catalog_candidate_source_ids": candidates["catalog"],
            }
        )

    land_grid_coverage_rate = (
        len(canonical_land_cells) / len(nonpolar_land_cells)
        if nonpolar_land_cells
        else 0.0
    )
    passes = (
        not undercovered_core_codes
        and priority_coverage_rate >= GLOBAL_MINIMUM_PRIORITY_COUNTRY_COVERAGE_RATE
        and not macroregions_below_grid_minimum
        and land_grid_coverage_rate >= GLOBAL_MINIMUM_LAND_GRID_COVERAGE_RATE
    )
    return {
        "policy_version": GLOBAL_SPATIAL_POLICY_VERSION,
        "grid_cell_degrees": land_grid["cell_degrees"],
        "priority_country_codes": priority_country_codes,
        "core_priority_country_codes": core_country_codes,
        "covered_priority_country_codes": covered_priority_codes,
        "undercovered_priority_country_codes": undercovered_priority_codes,
        "undercovered_core_priority_country_codes": undercovered_core_codes,
        "priority_country_coverage_rate": round(priority_coverage_rate, 6),
        "country_metrics": country_metrics,
        "canonical_nonpolar_land_occupied_grid_cells": len(canonical_land_cells),
        "reported_display_nonpolar_land_occupied_grid_cells": len(display_land_cells),
        "target_nonpolar_land_grid_cells": len(nonpolar_land_cells),
        "minimum_nonpolar_land_occupied_grid_cells": minimum_land_cells,
        "canonical_nonpolar_land_grid_coverage_rate": round(land_grid_coverage_rate, 6),
        "macroregion_canonical_occupied_grid_cells": macroregion_cell_counts,
        "macroregion_target_land_grid_cells": macroregion_target_cell_counts,
        "macroregion_minimum_occupied_grid_cells": macroregion_minimum_cell_counts,
        "macroregions_below_grid_minimum": macroregions_below_grid_minimum,
        "geographic_search_targets": geographic_search_targets,
        "passes": passes,
        "claim_boundary": (
            "Grid and priority-country checks identify observation holes only. "
            "They do not imply uniform sampling, interpolate unsampled cells, or "
            "treat a blank area as elemental absence."
        ),
    }


def assess_regional_spatial_coverage(
    database: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    """Audit any non-global request with the shared adaptive policy engine."""

    audit = spatial_sufficiency.audit_spatial_views(
        database.get("spatial_samples") or [],
        request,
        SPATIAL_SUFFICIENCY_POLICY,
    )
    overall = next(
        item for item in audit["views"] if item.get("view_kind") == "overall"
    )
    scope = audit["scope"]
    reasons = list(overall["reason_codes"])
    repair_mode = (
        "repair_coordinate_evidence"
        if "reported_only_coordinate_evidence" in reasons
        else "targeted_source_discovery"
    )
    return {
        "policy_version": audit["policy_version"],
        "scope_key": scope["key"],
        "scope_label": scope["label"],
        "clip_method": scope["clip_method"],
        "country_iso_a3": scope["country_iso_a3"],
        "bbox": scope["bbox"],
        "grid_cell_degrees": audit["grid_cell_degrees"],
        "target_coverage_grid_cells": audit["target_coverage_grid_cells"],
        "reference_land_grid_cells": audit["reference_land_grid_cells"],
        "minimum_canonical_occupied_grid_cells": overall[
            "minimum_canonical_occupied_grid_cells"
        ],
        "canonical_occupied_grid_cells": overall["canonical_occupied_grid_cells"],
        "reported_display_occupied_grid_cells": overall[
            "reported_display_occupied_grid_cells"
        ],
        "minimum_canonical_unique_samples": overall["minimum_canonical_unique_samples"],
        "canonical_unique_samples": overall["canonical_unique_samples"],
        "reported_display_unique_samples": overall["reported_display_unique_samples"],
        "canonical_grid_coverage_rate": round(
            overall["canonical_occupied_grid_cells"]
            / audit["target_coverage_grid_cells"]
            if audit["target_coverage_grid_cells"]
            else 0.0,
            6,
        ),
        "target_coverage_zones": list(overall.get("target_coverage_zones") or []),
        "qualifying_coverage_zones": list(
            overall.get("qualifying_coverage_zones") or []
        ),
        "missing_coverage_zones": list(overall.get("missing_coverage_zones") or []),
        "coverage_zone_targets": list(overall.get("coverage_zone_targets") or []),
        "minimum_qualifying_coverage_zones": int(
            overall.get("minimum_qualifying_coverage_zones") or 0
        ),
        "reason_codes": reasons,
        "repair_mode": repair_mode,
        "assessable": audit["assessable"],
        "passes": overall["passes"],
        "claim_boundary": audit["claim_boundary"],
    }


def build_spatial_dimension_gaps(
    audit: Mapping[str, Any],
    selected_source_ids: set[str],
    request: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Turn failed map views into dimension-specific D1 research targets."""

    scope = audit.get("scope") or {}
    global_scope = bool(scope.get("global"))
    country_registry = spatial_scope.load_country_registry()
    macroregions = spatial_scope.load_macroregion_registry()
    regional_country_codes: list[str] = []
    if not global_scope:
        country_code = scope.get("country_iso_a3")
        if isinstance(country_code, str):
            regional_country_codes = [country_code]
        else:
            resolved = spatial_scope.resolve_region(request.get("region"))
            grid = spatial_sufficiency.build_scope_coverage_grid(
                resolved, SPATIAL_SUFFICIENCY_POLICY
            )
            regional_country_codes = [
                code
                for code, _ in sorted(
                    (
                        (code, len(cells))
                        for code, cells in grid["country_cells"].items()
                    ),
                    key=lambda item: (-item[1], item[0]),
                )[:4]
            ]

    gaps: list[dict[str, Any]] = []
    for view in audit.get("views") or []:
        if not isinstance(view, Mapping) or view.get("status") != "gap":
            continue
        required_elements = [str(item) for item in view.get("required_elements") or []]
        required_media = [str(item) for item in view.get("required_media") or []]
        narrowed_request = {
            "elements": required_elements
            or [str(item) for item in request.get("elements") or []],
            "media": required_media
            or [str(item) for item in request.get("media") or []],
            "spatial_domains": list(request.get("spatial_domains") or []),
            "adjacent_marine_distance_km": request.get(
                "adjacent_marine_distance_km", 0
            ),
        }
        country_codes = (
            spatial_sufficiency.rank_global_country_targets(
                view, SPATIAL_SUFFICIENCY_POLICY
            )
            if global_scope
            else regional_country_codes
        )
        country_targets: list[dict[str, Any]] = []
        longitude_band_targets = [
            dict(target)
            for target in view.get("country_longitude_band_targets") or []
            if isinstance(target, Mapping)
        ]
        for code in country_codes:
            candidates = _country_source_candidates(
                code, selected_source_ids, narrowed_request
            )
            if "reported_only_coordinate_evidence" in view.get("reason_codes", []):
                repair_mode = "repair_coordinate_evidence"
            elif candidates["selected"]:
                repair_mode = "requery_selected_source"
            elif candidates["registered"]:
                repair_mode = "route_registered_source"
            elif candidates["catalog"]:
                repair_mode = "implement_catalog_candidate"
            else:
                repair_mode = "targeted_source_discovery"
            country = country_registry["by_code"][code]
            target_bboxes = [
                list(target.get("bbox") or [])
                for target in longitude_band_targets
                if target.get("country_iso_a3") == code
                and len(target.get("bbox") or []) == 4
            ]
            if not target_bboxes and len(country.get("bbox") or []) == 4:
                target_bboxes = [list(country["bbox"])]
            country_targets.append(
                {
                    "country_iso_a3": code,
                    "country_name": country["name"],
                    "country_name_zh": str(country.get("name_zh") or ""),
                    "macroregion": macroregions[code],
                    "repair_mode": repair_mode,
                    "selected_source_candidates": candidates["selected"],
                    "registered_source_candidates": candidates["registered"],
                    "catalog_candidate_source_ids": candidates["catalog"],
                    "target_bboxes": target_bboxes,
                }
            )
        if "reported_only_coordinate_evidence" in view.get("reason_codes", []):
            primary_repair_mode = "repair_coordinate_evidence"
        elif country_targets:
            primary_repair_mode = country_targets[0]["repair_mode"]
        else:
            primary_repair_mode = "targeted_source_discovery"
        gaps.append(
            {
                "view_id": str(view["view_id"]),
                "view_kind": str(view["view_kind"]),
                "required_elements": required_elements,
                "required_media": required_media,
                "scope_key": str(scope.get("key") or ""),
                "scope_label": str(scope.get("label") or ""),
                "bbox": list(scope.get("bbox") or []),
                "reason_codes": list(view.get("reason_codes") or []),
                "canonical_unique_samples": int(
                    view.get("canonical_unique_samples") or 0
                ),
                "reported_display_unique_samples": int(
                    view.get("reported_display_unique_samples") or 0
                ),
                "canonical_occupied_grid_cells": int(
                    view.get("canonical_occupied_grid_cells") or 0
                ),
                "reported_display_occupied_grid_cells": int(
                    view.get("reported_display_occupied_grid_cells") or 0
                ),
                "minimum_canonical_unique_samples": int(
                    view.get("minimum_canonical_unique_samples") or 0
                ),
                "minimum_canonical_occupied_grid_cells": int(
                    view.get("minimum_canonical_occupied_grid_cells") or 0
                ),
                "qualifying_coverage_zones": list(
                    view.get("qualifying_coverage_zones") or []
                ),
                "target_coverage_zones": list(view.get("target_coverage_zones") or []),
                "missing_coverage_zones": list(
                    view.get("missing_coverage_zones") or []
                ),
                "coverage_zone_targets": list(view.get("coverage_zone_targets") or []),
                "country_longitude_band_targets": longitude_band_targets,
                "covered_land_macroregions": list(
                    view.get("covered_land_macroregions") or []
                ),
                "missing_land_macroregions": list(
                    view.get("missing_land_macroregions") or []
                ),
                "minimum_land_macroregions": int(
                    view.get("minimum_land_macroregions") or 0
                ),
                "minimum_qualifying_coverage_zones": int(
                    view.get("minimum_qualifying_coverage_zones") or 0
                ),
                "repair_mode": primary_repair_mode,
                "country_targets": country_targets,
            }
        )
    return gaps


def spatial_requery_source_ids(
    geographic_targets: Sequence[Mapping[str, Any]],
    spatial_dimension_gaps: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Return selected sources that a machine-generated spatial gap can grow.

    A spatial warning alone is not enough: only targets whose preferred action
    is ``requery_selected_source`` authorize another autonomous acquisition
    round.  CRS repair, unimplemented candidates and new-source discovery stay
    in the explicit D1 repair queue.
    """

    selected: set[str] = set()

    def collect(target: Mapping[str, Any]) -> None:
        if target.get("repair_mode") != "requery_selected_source":
            return
        selected.update(
            str(source_id)
            for source_id in target.get("selected_source_candidates") or []
            if isinstance(source_id, str) and source_id
        )

    for target in geographic_targets:
        if isinstance(target, Mapping):
            collect(target)
    for gap in spatial_dimension_gaps:
        if not isinstance(gap, Mapping):
            continue
        for target in gap.get("country_targets") or []:
            if isinstance(target, Mapping):
                collect(target)
    return sorted(selected)


def _criterion(
    passed: bool, observed: Any, target: Any, detail: str, *, required: bool = True
) -> dict[str, Any]:
    return {
        "status": "pass" if passed else "fail" if required else "warning",
        "required": required,
        "observed": observed,
        "target": target,
        "detail": detail,
    }


def acquisition_breadth_state(
    request: Mapping[str, Any],
    outcomes: Sequence[Mapping[str, Any]],
    viable_selected_ids: set[str],
    observed_source_ids: set[str],
    database_records: int,
    current_target: int,
    maximum_target: int,
    mode: str,
) -> dict[str, Any]:
    """Decide whether a breadth request has exhausted autonomous acquisition.

    Minimum scientific gates answer whether an atlas is usable; they do not
    answer a user's separate request to collect as much registered evidence as
    practical.  In ``maximize_evidence_breadth`` mode, keep expanding while a
    successful source filled its allocated slice exactly.  Stop only when the
    request record ceiling or per-analyte ceiling is reached, or every viable
    source returned fewer records than allocated (an auditable capacity signal).
    A no-progress guard in the outer loop remains the final protection against
    fixed-size adapters whose exact capacity equals their allocation.
    """

    required = (
        mode == "online" and request.get("coverage_mode") == "maximize_evidence_breadth"
    )
    successful = {
        str(item.get("source_id")): item
        for item in outcomes
        if item.get("status") == "success" and item.get("source_id")
    }
    unobserved = sorted(viable_selected_ids - observed_source_ids)
    filled_allocations: list[str] = []
    capacity_signals: list[str] = []
    for source_id in sorted(viable_selected_ids):
        outcome = successful.get(source_id)
        if outcome is None:
            continue
        try:
            record_count = int(outcome.get("record_count") or 0)
            allocation = int(outcome.get("allocated_max_records") or 0)
        except (TypeError, ValueError):
            continue
        if allocation > 0 and record_count >= allocation:
            filled_allocations.append(source_id)
        elif allocation > 0:
            capacity_signals.append(source_id)

    record_ceiling = int(request.get("max_records") or 0)
    record_ceiling_reached = record_ceiling > 0 and database_records >= record_ceiling
    target_ceiling_reached = current_target >= maximum_target
    all_viable_observed = bool(viable_selected_ids) and not unobserved
    source_capacity_reached = (
        all_viable_observed
        and viable_selected_ids.issubset(successful)
        and not filled_allocations
    )
    passed = (
        not required
        or record_ceiling_reached
        or target_ceiling_reached
        or source_capacity_reached
    )
    return {
        "required": required,
        "passed": passed,
        "record_ceiling_reached": record_ceiling_reached,
        "target_ceiling_reached": target_ceiling_reached,
        "source_capacity_reached": source_capacity_reached,
        "viable_selected_source_count": len(viable_selected_ids),
        "observed_viable_source_count": len(
            viable_selected_ids.intersection(observed_source_ids)
        ),
        "unobserved_viable_source_ids": unobserved,
        "sources_filling_current_allocation": filled_allocations,
        "sources_below_current_allocation": capacity_signals,
        "current_per_analyte_observations": current_target,
        "maximum_per_analyte_observations": maximum_target,
        "database_records": database_records,
        "max_records": record_ceiling,
    }


def assess_sufficiency(
    round_dir: Path,
    request: Mapping[str, Any],
    execution: Mapping[str, Any],
    mode: str,
    current_target: int,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Assess whether another acquisition round can materially improve the atlas.

    This is deliberately a data-coverage gate, not a claim that the resulting
    observations are representative.  Thresholds are visible in the report
    and can be overridden from the CLI.
    """

    database = read_database_coverage(round_dir / "geochemistry.csv")
    try:
        route = read_json(round_dir / "request_evidence" / "source_route.json")
    except (OSError, json.JSONDecodeError):
        route = {}
    try:
        sources_and_confidence = read_json(round_dir / "sources_and_confidence.json")
    except (OSError, json.JSONDecodeError):
        sources_and_confidence = {}
    selected = route.get("selected_sources") or []
    selected_ids = {
        str(item.get("source_id")) for item in selected if item.get("source_id")
    }
    outcomes = [
        item
        for item in (execution.get("source_outcomes") or [])
        if isinstance(item, Mapping)
    ]
    permanent_failed_source_ids = {
        str(item.get("source_id"))
        for item in outcomes
        if item.get("status") == "failed"
        and not source_failure_retryable(str(item.get("error") or ""))
    }
    viable_selected_ids = selected_ids - permanent_failed_source_ids
    available_by_medium = {
        medium: {
            str(item.get("source_id"))
            for item in selected
            if str(item.get("source_id")) in viable_selected_ids
            if medium in (item.get("matching_media") or [])
        }
        for medium in request["media"]
    }
    available_by_element = {
        element: {
            str(item.get("source_id"))
            for item in selected
            if str(item.get("source_id")) in viable_selected_ids
            if element
            in (
                ((item.get("request_compatibility") or {}).get("analytes") or {}).get(
                    "matched"
                )
                or []
            )
        }
        for element in request["elements"]
    }
    observed_elements = set(database["elements"])
    observed_media = set(database["media"])
    requested_spatial_domains = {
        str(item) for item in request.get("spatial_domains") or []
    }
    observed_spatial_domains = set(database.get("spatial_domains") or {})
    missing_elements = sorted(set(request["elements"]) - observed_elements)
    missing_media = sorted(set(request["media"]) - observed_media)
    missing_spatial_domains = sorted(
        requested_spatial_domains - observed_spatial_domains
    )
    minimum_records = min(
        int(request["max_records"]),
        max(
            args.minimum_records,
            500 * len(request["elements"]) * len(request["media"]),
        ),
    )
    minimum_unique_samples = min(
        int(request["max_records"]),
        max(
            int(
                getattr(
                    args,
                    "minimum_unique_samples",
                    DEFAULT_MINIMUM_UNIQUE_SAMPLES,
                )
            ),
            250 * len(request["elements"]) * len(request["media"]),
        ),
    )
    global_scope = request["region"] == "global"
    desired_lineage_count = 6 if global_scope else 3
    observed_source_ids = set(database["sources"])
    observed_lineage_ids = set(database["lineages"])
    # Input mode has no executable source route to grow.  Its diversity target
    # therefore describes the submitted evidence rather than pretending that
    # the controller can download more sources by itself.
    if mode == "input" and not selected_ids:
        selected_ids = set(observed_source_ids)
        available_by_medium = {
            medium: set(database["sources_by_medium"].get(medium, []))
            for medium in request["media"]
        }
        available_by_element = {
            element: set(observed_source_ids) if element in observed_elements else set()
            for element in request["elements"]
        }
    trace_rate = (
        database["traceable_records"] / database["records"]
        if database["records"]
        else 0.0
    )
    strict_provenance_rate = (
        database["strict_provenance_records"] / database["records"]
        if database["records"]
        else 0.0
    )
    analyzed, insufficient, candidates = read_anomaly_groups(
        round_dir / "anomaly_report.json"
    )
    execution_mode = str(execution.get("mode") or "")
    online_attempted = execution_mode.startswith("online_") and bool(
        execution.get("source_outcomes")
    )
    criteria: dict[str, dict[str, Any]] = {}
    criteria["online_acquisition"] = _criterion(
        mode != "online" or online_attempted,
        execution_mode or None,
        "online source acquisition with record-level outcomes"
        if mode == "online"
        else "not required for explicit input/demo mode",
        "Research mode must attempt compatible online sources; fixtures are explicit demos only.",
        required=mode == "online",
    )
    breadth_state = acquisition_breadth_state(
        request,
        outcomes,
        viable_selected_ids,
        observed_source_ids,
        database["records"],
        current_target,
        args.max_per_analyte_observations,
        mode,
    )
    criteria["acquisition_breadth"] = _criterion(
        breadth_state["passed"],
        breadth_state,
        {
            "stop_when_any": [
                "request max_records reached",
                "maximum per-analyte target reached",
                "all viable sources return below their current allocation",
            ]
        },
        (
            "maximize_evidence_breadth is an expansion contract, not a synonym for "
            "passing minimum delivery gates. A source that fills its allocation keeps "
            "the next 30-minute round eligible; source capacities and the request ceiling "
            "remain explicit stopping evidence."
        ),
        required=breadth_state["required"],
    )
    criteria["requested_dimensions"] = _criterion(
        not missing_elements and not missing_media and not missing_spatial_domains,
        {
            "elements": sorted(observed_elements),
            "media": sorted(observed_media),
            "spatial_domains": sorted(observed_spatial_domains),
        },
        {
            "elements": list(request["elements"]),
            "media": list(request["media"]),
            "spatial_domains": sorted(requested_spatial_domains),
        },
        (
            f"missing_elements={missing_elements}; missing_media={missing_media}; "
            f"missing_spatial_domains={missing_spatial_domains}"
        ),
    )
    requested_cells = {
        f"{element}|{medium}"
        for element in request["elements"]
        for medium in request["media"]
    }
    observed_cells = set(database["element_medium_cells"])
    missing_element_medium_cells = sorted(requested_cells - observed_cells)
    cell_rate = len(requested_cells.intersection(observed_cells)) / len(requested_cells)
    criteria["element_medium_coverage"] = _criterion(
        not missing_element_medium_cells,
        {
            "covered_cells": len(requested_cells.intersection(observed_cells)),
            "requested_cells": len(requested_cells),
            "coverage_rate": round(cell_rate, 6),
            "missing_cells": missing_element_medium_cells,
        },
        {"minimum_coverage_rate": 1.0},
        "Every explicitly requested element × medium cell needs observations; union-only or partial matrix coverage is not enough.",
        required=mode != "demo",
    )
    criteria["record_volume"] = _criterion(
        database["records"] >= minimum_records,
        database["records"],
        minimum_records,
        "Adaptive floor = max(5000, 500 × requested elements × media), capped by max_records.",
        required=mode != "demo",
    )
    criteria["independent_sample_volume"] = _criterion(
        database["unique_samples"] >= minimum_unique_samples,
        {
            "unique_samples": database["unique_samples"],
            "measurement_records": database["records"],
            "unresolved_sample_identity_records": database[
                "unresolved_sample_identity_records"
            ],
        },
        minimum_unique_samples,
        "Counts source-scoped physical sample identities, not sample × element measurement rows. The adaptive floor is max(2000, 250 × requested elements × media), capped by max_records.",
        required=mode != "demo",
    )
    criteria["source_diversity"] = _criterion(
        len(observed_lineage_ids) >= desired_lineage_count,
        {
            "source_ids": len(observed_source_ids),
            "independent_lineages": len(observed_lineage_ids),
            "lineage_ids": sorted(observed_lineage_ids),
        },
        {"independent_lineages": desired_lineage_count},
        "Counts upstream project lineages, so multiple GEOROC or FOREGS members do not masquerade as independent evidence.",
        required=mode != "demo",
    )
    per_medium_observed = {
        medium: len(database["lineages_by_medium"].get(medium, []))
        for medium in request["media"]
    }
    per_medium_targets = {medium: 2 for medium in request["media"]}
    medium_source_pass = all(
        per_medium_targets[medium] > 0
        and per_medium_observed[medium] >= per_medium_targets[medium]
        for medium in request["media"]
    )
    criteria["source_diversity_by_medium"] = _criterion(
        medium_source_pass,
        per_medium_observed,
        per_medium_targets,
        "Each requested medium needs two independent upstream lineages; a sparse route becomes an explicit D1 discovery gap rather than a lowered target.",
        required=mode != "demo",
    )

    def balance_shortfalls(
        counts: Mapping[str, int],
        *,
        capacity_per_dimension: int,
        absolute_floor: int,
        minimum_share: float,
        maximum_target: int,
    ) -> tuple[int, dict[str, dict[str, int]]]:
        largest = max((int(value) for value in counts.values()), default=0)
        target = min(
            largest,
            max(1, int(capacity_per_dimension)),
            maximum_target,
            max(absolute_floor, math.ceil(largest * minimum_share)),
        )
        return target, {
            dimension: {
                "observed_unique_samples": int(count),
                "target_unique_samples": target,
                "deficit_unique_samples": max(0, target - int(count)),
            }
            for dimension, count in counts.items()
            if int(count) < target
        }

    medium_sample_counts = {
        medium: int((database.get("medium_unique_samples") or {}).get(medium, 0))
        for medium in request["media"]
    }
    largest_medium_sample_count = max(medium_sample_counts.values(), default=0)
    per_medium_request_capacity = max(
        1,
        int(request["max_records"])
        // max(1, len(request["media"]) * len(request["elements"])),
    )
    medium_balance_target, medium_sample_shortfalls = balance_shortfalls(
        medium_sample_counts,
        capacity_per_dimension=per_medium_request_capacity,
        absolute_floor=MINIMUM_DIMENSION_BALANCE_SAMPLES,
        minimum_share=MINIMUM_DIMENSION_BALANCE_SHARE,
        maximum_target=MAXIMUM_DIMENSION_BALANCE_SAMPLES,
    )
    medium_balance_required = mode != "demo" and len(request["media"]) > 1
    criteria["medium_sample_balance"] = _criterion(
        not medium_sample_shortfalls,
        {
            "unique_samples_by_medium": medium_sample_counts,
            "largest_medium_unique_samples": largest_medium_sample_count,
            "shortfalls": medium_sample_shortfalls,
        },
        {
            "minimum_unique_samples_per_requested_medium": medium_balance_target,
            "absolute_floor_before_caps": MINIMUM_DIMENSION_BALANCE_SAMPLES,
            "minimum_share_of_largest_medium": MINIMUM_DIMENSION_BALANCE_SHARE,
            "maximum_target_per_medium": MAXIMUM_DIMENSION_BALANCE_SAMPLES,
            "request_capacity_cap_per_medium": per_medium_request_capacity,
        },
        (
            "Counts source-scoped physical samples, not measurement rows. The "
            "bounded target detects severe medium imbalance without claiming that "
            "natural source populations should be equal or statistically representative."
        ),
        required=medium_balance_required,
    )
    element_sample_counts = {
        element: int((database.get("element_unique_samples") or {}).get(element, 0))
        for element in request["elements"]
    }
    per_element_request_capacity = max(
        1, int(request["max_records"]) // max(1, len(request["elements"]))
    )
    element_balance_target, element_sample_shortfalls = balance_shortfalls(
        element_sample_counts,
        capacity_per_dimension=per_element_request_capacity,
        absolute_floor=MINIMUM_DIMENSION_BALANCE_SAMPLES,
        minimum_share=MINIMUM_DIMENSION_BALANCE_SHARE,
        maximum_target=MAXIMUM_DIMENSION_BALANCE_SAMPLES,
    )
    element_balance_required = mode != "demo" and len(request["elements"]) > 1
    criteria["element_sample_balance"] = _criterion(
        not element_sample_shortfalls,
        {
            "unique_samples_by_element": element_sample_counts,
            "largest_element_unique_samples": max(
                element_sample_counts.values(), default=0
            ),
            "shortfalls": element_sample_shortfalls,
        },
        {
            "minimum_unique_samples_per_requested_element": element_balance_target,
            "absolute_floor_before_caps": MINIMUM_DIMENSION_BALANCE_SAMPLES,
            "minimum_share_of_largest_element": MINIMUM_DIMENSION_BALANCE_SHARE,
            "maximum_target_per_element": MAXIMUM_DIMENSION_BALANCE_SAMPLES,
            "request_capacity_cap_per_element": per_element_request_capacity,
        },
        (
            "Counts source-scoped physical samples for every requested element. "
            "A high-volume element cannot hide a thin requested element; the bounded "
            "target triggers acquisition without claiming equal natural abundance."
        ),
        required=element_balance_required,
    )
    requested_element_medium_cells = [
        f"{element}|{medium}"
        for element in request["elements"]
        for medium in request["media"]
    ]
    element_medium_sample_counts = {
        cell: int((database.get("element_medium_unique_samples") or {}).get(cell, 0))
        for cell in requested_element_medium_cells
    }
    per_element_medium_capacity = max(
        1,
        int(request["max_records"]) // max(1, len(requested_element_medium_cells)),
    )
    (
        element_medium_balance_target,
        element_medium_sample_shortfalls,
    ) = balance_shortfalls(
        element_medium_sample_counts,
        capacity_per_dimension=per_element_medium_capacity,
        absolute_floor=MINIMUM_ELEMENT_MEDIUM_BALANCE_SAMPLES,
        minimum_share=MINIMUM_ELEMENT_MEDIUM_BALANCE_SHARE,
        maximum_target=MAXIMUM_ELEMENT_MEDIUM_BALANCE_SAMPLES,
    )
    element_medium_balance_required = (
        mode != "demo" and len(request["elements"]) > 1 and len(request["media"]) > 1
    )
    criteria["element_medium_sample_balance"] = _criterion(
        not element_medium_sample_shortfalls,
        {
            "unique_samples_by_element_medium": element_medium_sample_counts,
            "largest_element_medium_unique_samples": max(
                element_medium_sample_counts.values(), default=0
            ),
            "shortfalls": element_medium_sample_shortfalls,
        },
        {
            "minimum_unique_samples_per_requested_cell": (
                element_medium_balance_target
            ),
            "absolute_floor_before_caps": MINIMUM_ELEMENT_MEDIUM_BALANCE_SAMPLES,
            "minimum_share_of_largest_cell": (MINIMUM_ELEMENT_MEDIUM_BALANCE_SHARE),
            "maximum_target_per_cell": MAXIMUM_ELEMENT_MEDIUM_BALANCE_SAMPLES,
            "request_capacity_cap_per_cell": per_element_medium_capacity,
        },
        (
            "Every requested element × medium filter cell receives an independent-sample "
            "capacity audit. Empty or thin cells remain repair debt instead of being hidden "
            "by another element or medium."
        ),
        required=element_medium_balance_required,
    )
    top_source_count = max(database["source_unique_samples"].values(), default=0)
    top_source_share = (
        top_source_count / database["unique_samples"]
        if database["unique_samples"]
        else 0
    )
    maximum_source_share = 0.50 if global_scope else 0.80
    criteria["source_balance"] = _criterion(
        top_source_share <= maximum_source_share,
        {
            "largest_source_share": round(top_source_share, 6),
            "largest_source_unique_samples": top_source_count,
            "source_unique_sample_counts": database["source_unique_samples"],
            "measurement_record_counts": database["sources"],
        },
        {"maximum_largest_source_share": maximum_source_share},
        "Uses independent samples so multi-element rows cannot hide dominance by one archive.",
        required=mode != "demo",
    )
    criteria["record_provenance"] = _criterion(
        trace_rate >= args.minimum_provenance_rate
        and (mode != "online" or strict_provenance_rate == 1.0),
        {
            "traceable_rate": round(trace_rate, 6),
            "strict_provenance_rate": round(strict_provenance_rate, 6),
            "strict_provenance_records": database["strict_provenance_records"],
            "records": database["records"],
        },
        {
            "minimum_traceable_rate": args.minimum_provenance_rate,
            "online_strict_provenance_rate": 1.0,
        },
        "Online strict provenance requires source_id, source_record_id, source file, exact locator, official URL/DOI, 64-hex file SHA-256, dataset title and license on every row. The independent output validator still verifies row-to-manifest/hash consistency.",
    )
    source_link_gaps: list[dict[str, Any]] = []
    official_linked_records = 0
    source_confidence_items = sources_and_confidence.get("sources")
    if not isinstance(source_confidence_items, list):
        source_confidence_items = []
    summarized_source_ids: set[str] = set()
    for item in source_confidence_items:
        if not isinstance(item, Mapping):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if not source_id:
            continue
        summarized_source_ids.add(source_id)
        record_count = int(item.get("record_count") or 0)
        row_official_link_count = int(
            (database.get("official_source_url_counts") or {}).get(source_id, 0)
        )
        provenance = item.get("record_provenance")
        provenance = provenance if isinstance(provenance, Mapping) else {}
        linked_count = min(
            record_count,
            int(provenance.get("official_linked_record_count") or 0),
        )
        official_links = item.get("official_links")
        valid_links = [
            dict(link)
            for link in (official_links if isinstance(official_links, list) else [])
            if isinstance(link, Mapping) and _valid_web_url(link.get("url"))
        ]
        if not valid_links:
            linked_count = 0
        linked_count = min(linked_count, row_official_link_count)
        official_linked_records += linked_count
        if record_count > linked_count:
            source_link_gaps.append(
                {
                    "source_id": source_id,
                    "record_count": record_count,
                    "official_linked_record_count": linked_count,
                    "official_link_count": len(valid_links),
                    "row_official_link_count": row_official_link_count,
                    "reason_codes": ["official_source_link_missing"],
                }
            )
    for source_id, record_count in sorted(database["sources"].items()):
        if source_id not in summarized_source_ids:
            source_link_gaps.append(
                {
                    "source_id": source_id,
                    "record_count": int(record_count),
                    "official_linked_record_count": 0,
                    "official_link_count": 0,
                    "row_official_link_count": int(
                        (database.get("official_source_url_counts") or {}).get(
                            source_id, 0
                        )
                    ),
                    "reason_codes": ["source_confidence_summary_missing"],
                }
            )
    official_link_rate = (
        official_linked_records / database["records"] if database["records"] else 0.0
    )
    criteria["official_source_links"] = _criterion(
        mode != "online"
        or (not source_link_gaps and official_linked_records == database["records"]),
        {
            "official_linked_records": official_linked_records,
            "records": database["records"],
            "official_link_rate": round(official_link_rate, 6),
            "source_link_gaps": len(source_link_gaps),
        },
        {"official_link_rate": 1.0, "source_link_gaps": 0},
        "Online research output keeps two provenance paths: every row has an exact local record locator, and every represented source has at least one official data-page, file URL or DOI link. One cannot substitute for the other.",
        required=mode == "online",
    )
    successful_outcomes = sum(item.get("status") == "success" for item in outcomes)
    acquisition_success_rate = (
        successful_outcomes / len(outcomes)
        if outcomes
        else (0.0 if mode == "online" else 1.0)
    )
    criteria["source_acquisition_success"] = _criterion(
        mode != "online" or acquisition_success_rate >= 0.75,
        {
            "attempted": len(outcomes),
            "successful": successful_outcomes,
            "success_rate": round(acquisition_success_rate, 6),
        },
        {"minimum_success_rate": 0.75},
        "A high source failure rate is an engineering/data-access deficit, not a successful broad search.",
        required=mode == "online",
    )
    dimension_counts = database["dimension_band_counts"]

    def non_low_rate(dimension: str) -> float:
        bands = dimension_counts.get(dimension, {})
        known = sum(int(bands.get(key, 0)) for key in ("high", "medium", "low"))
        return (
            (int(bands.get("high", 0)) + int(bands.get("medium", 0))) / known
            if known
            else 0.0
        )

    source_evidence_rate = non_low_rate("source_evidence")
    analytical_rate = non_low_rate("analytical_readiness")
    criteria["source_evidence_readiness"] = _criterion(
        source_evidence_rate >= 0.95,
        {
            "non_low_rate": round(source_evidence_rate, 6),
            "bands": dimension_counts.get("source_evidence", {}),
        },
        {"minimum_non_low_rate": 0.95},
        "Source evidence is assessed separately from coordinates and method comparability.",
    )
    metadata_counts = database.get("metadata_counts") or {}
    metadata_by_medium = database.get("metadata_by_medium") or {}
    metadata_accounting_pass = bool(database["records"]) and all(
        int(metadata_counts.get(field, 0)) == database["records"]
        for field in (
            "method_accounted",
            "coordinate_accuracy_accounted",
            "exact_record_locator",
        )
    )
    criteria["metadata_evidence_accounting"] = _criterion(
        metadata_accounting_pass,
        {
            "records": database["records"],
            "method_accounted": int(metadata_counts.get("method_accounted", 0)),
            "coordinate_accuracy_accounted": int(
                metadata_counts.get("coordinate_accuracy_accounted", 0)
            ),
            "exact_record_locator": int(metadata_counts.get("exact_record_locator", 0)),
            "source_reported_coordinate_uncertainty": int(
                metadata_counts.get("coordinate_uncertainty_reported", 0)
            ),
            "coordinate_representation_resolution": int(
                metadata_counts.get("coordinate_representation_resolution", 0)
            ),
        },
        {"accounted_rate": 1.0},
        "Every record must explicitly distinguish present evidence from source-not-reported evidence. Decimal-place resolution is recorded separately and never substitutes for positional accuracy.",
        required=mode != "demo",
    )
    geology_accounting_rate = (
        database["geology_accounted_records"] / database["records"]
        if database["records"]
        else 0.0
    )
    criteria["geology_evidence_accounting"] = _criterion(
        geology_accounting_rate == 1.0,
        {
            "records": database["records"],
            "accounted_records": database["geology_accounted_records"],
            "context_present_records": database["geology_present_records"],
            "accounted_by_medium": database["geology_accounted_records_by_medium"],
            "context_present_by_medium": database["geology_present_records_by_medium"],
        },
        {"accounted_rate": 1.0},
        "Every record must carry publisher/matched geological context or an explicit scientific not-applicable/not-available reason. Missing context is never silently interpreted as a processing success.",
        required=mode != "demo",
    )
    minimum_method_rate = MINIMUM_ANALYTICAL_METHOD_RATE_BY_MEDIUM
    method_readiness_by_medium: dict[str, dict[str, Any]] = {}
    medium_method_evidence_gaps: list[dict[str, Any]] = []
    for medium in request["media"]:
        counts = metadata_by_medium.get(medium) or {}
        total = int(counts.get("records", 0))
        method_count = int(counts.get("analytical_method", 0))
        rate = method_count / total if total else 0.0
        unique_samples = int(
            (database.get("medium_unique_samples") or {}).get(medium, 0)
        )
        method_ready_samples = int(
            (database.get("method_ready_unique_samples_by_medium") or {}).get(medium, 0)
        )
        method_ready_lineages = list(
            (database.get("method_ready_lineages_by_medium") or {}).get(medium, [])
        )
        minimum_method_ready_samples = (
            min(unique_samples, MINIMUM_METHOD_READY_SAMPLES_BY_MEDIUM)
            if unique_samples
            else 0
        )
        medium_passes = not total or (
            rate >= minimum_method_rate
            and method_ready_samples >= minimum_method_ready_samples
            and len(method_ready_lineages) >= MINIMUM_METHOD_READY_LINEAGES_BY_MEDIUM
        )
        method_readiness_by_medium[medium] = {
            "record_count": total,
            "analytical_method_count": method_count,
            "analytical_method_rate": round(rate, 6),
            "unique_samples": unique_samples,
            "method_ready_unique_samples": method_ready_samples,
            "minimum_method_ready_unique_samples": minimum_method_ready_samples,
            "method_ready_lineage_count": len(method_ready_lineages),
            "method_ready_lineage_ids": method_ready_lineages,
            "minimum_method_ready_lineages": (MINIMUM_METHOD_READY_LINEAGES_BY_MEDIUM),
            "status": "pass" if medium_passes else "gap",
        }
        if total and not medium_passes:
            medium_method_evidence_gaps.append(
                {
                    "medium": medium,
                    "record_count": total,
                    "analytical_method_count": method_count,
                    "analytical_method_rate": round(rate, 6),
                    "minimum_analytical_method_rate": minimum_method_rate,
                    "unique_samples": unique_samples,
                    "method_ready_unique_samples": method_ready_samples,
                    "minimum_method_ready_unique_samples": (
                        minimum_method_ready_samples
                    ),
                    "method_ready_lineage_count": len(method_ready_lineages),
                    "minimum_method_ready_lineages": (
                        MINIMUM_METHOD_READY_LINEAGES_BY_MEDIUM
                    ),
                    "reason_codes": ["analytical_method_evidence_shortfall"],
                }
            )
    analytical_subset_pass = not medium_method_evidence_gaps
    criteria["analytical_readiness"] = _criterion(
        analytical_subset_pass,
        {
            "record_weighted_non_low_rate": round(analytical_rate, 6),
            "bands": dimension_counts.get("analytical_readiness", {}),
            "comparison_ready_subsets_by_medium": method_readiness_by_medium,
        },
        {
            "minimum_method_record_rate_by_observed_medium": minimum_method_rate,
            "minimum_method_ready_unique_samples_by_observed_medium": (
                MINIMUM_METHOD_READY_SAMPLES_BY_MEDIUM
            ),
            "minimum_method_ready_lineages_by_observed_medium": (
                MINIMUM_METHOD_READY_LINEAGES_BY_MEDIUM
            ),
        },
        "A broad archive may retain publisher-accounted method-unknown records, but every observed requested medium must also contain a declared comparison-ready subset. The gate combines a 20% record floor, up to 20 independent samples and at least one method-bearing lineage; method-unknown rows remain screening-only and are never assigned an inferred method.",
    )
    criteria["analytical_method_evidence_by_medium"] = _criterion(
        analytical_subset_pass,
        method_readiness_by_medium,
        {
            "minimum_record_rate": minimum_method_rate,
            "minimum_unique_samples": MINIMUM_METHOD_READY_SAMPLES_BY_MEDIUM,
            "minimum_lineages": MINIMUM_METHOD_READY_LINEAGES_BY_MEDIUM,
        },
        "An overall majority cannot hide a requested medium with no comparison-ready method subset. Missing methods remain explicit and trigger evidence repair; they are not guessed, discarded, or allowed to lower source-truth confidence.",
        required=mode != "demo",
    )
    material_source_readiness: list[dict[str, Any]] = []
    source_method_evidence_gaps: list[dict[str, Any]] = []
    for raw_item in database.get("metadata_by_source_medium") or []:
        if not isinstance(raw_item, Mapping):
            continue
        source_id = str(raw_item.get("source_id") or "")
        medium = str(raw_item.get("medium") or "")
        record_count = int(raw_item.get("record_count") or 0)
        method_count = int(raw_item.get("analytical_method_count") or 0)
        medium_total = int((metadata_by_medium.get(medium) or {}).get("records", 0))
        share = record_count / medium_total if medium_total else 0.0
        method_rate = method_count / record_count if record_count else 0.0
        material = bool(
            source_id
            and medium
            and record_count >= MINIMUM_MATERIAL_SOURCE_RECORDS
            and share >= MINIMUM_MATERIAL_SOURCE_SHARE_BY_MEDIUM
        )
        passes = not material or (
            method_rate >= MINIMUM_ANALYTICAL_METHOD_RATE_BY_MATERIAL_SOURCE
        )
        item = {
            "source_id": source_id,
            "source_lineage_id": str(raw_item.get("source_lineage_id") or source_id),
            "medium": medium,
            "record_count": record_count,
            "medium_record_share": round(share, 6),
            "analytical_method_count": method_count,
            "analytical_method_rate": round(method_rate, 6),
            "unique_samples": int(raw_item.get("unique_samples") or 0),
            "method_ready_unique_samples": int(
                raw_item.get("method_ready_unique_samples") or 0
            ),
            "method_missing_reason_counts": dict(
                raw_item.get("method_missing_reason_counts") or {}
            ),
            "material": material,
            "status": "pass" if passes else "gap",
        }
        material_source_readiness.append(item)
        if material and not passes:
            source_method_evidence_gaps.append(
                {
                    **item,
                    "minimum_analytical_method_rate": (
                        MINIMUM_ANALYTICAL_METHOD_RATE_BY_MATERIAL_SOURCE
                    ),
                    "minimum_material_source_records": MINIMUM_MATERIAL_SOURCE_RECORDS,
                    "minimum_material_source_share_by_medium": (
                        MINIMUM_MATERIAL_SOURCE_SHARE_BY_MEDIUM
                    ),
                    "reason_codes": [
                        "material_source_analytical_method_evidence_shortfall"
                    ],
                }
            )
    material_source_method_pass = not source_method_evidence_gaps
    criteria["analytical_method_evidence_by_material_source"] = _criterion(
        material_source_method_pass,
        material_source_readiness,
        {
            "minimum_source_records": MINIMUM_MATERIAL_SOURCE_RECORDS,
            "minimum_source_share_by_medium": (MINIMUM_MATERIAL_SOURCE_SHARE_BY_MEDIUM),
            "minimum_method_record_rate": (
                MINIMUM_ANALYTICAL_METHOD_RATE_BY_MATERIAL_SOURCE
            ),
        },
        "A material source-medium lineage cannot be masked by method-ready records from another lineage. Real method-unknown rows remain in the traceable screening archive, while the dominant lineage triggers source-specific evidence repair or replacement acquisition; methods are never inferred.",
        required=mode != "demo",
    )
    method_evidence_gaps = medium_method_evidence_gaps + source_method_evidence_gaps
    scientific_readiness_by_medium: dict[str, dict[str, Any]] = {}
    scientific_evidence_gaps: list[dict[str, Any]] = []
    for medium in request["media"]:
        unique_samples = int(
            (database.get("medium_unique_samples") or {}).get(medium, 0)
        )
        ready_samples = int(
            (database.get("scientific_ready_unique_samples_by_medium") or {}).get(
                medium, 0
            )
        )
        ready_lineages = list(
            (database.get("scientific_ready_lineages_by_medium") or {}).get(medium, [])
        )
        minimum_ready_samples = 20
        medium_passes = unique_samples >= minimum_ready_samples and (
            ready_samples >= minimum_ready_samples and len(ready_lineages) >= 1
        )
        scientific_readiness_by_medium[medium] = {
            "unique_samples": unique_samples,
            "scientific_ready_unique_samples": ready_samples,
            "minimum_scientific_ready_unique_samples": minimum_ready_samples,
            "scientific_ready_lineage_ids": ready_lineages,
            "minimum_scientific_ready_lineages": 1,
            "status": "pass" if medium_passes else "gap",
        }
        if not medium_passes:
            scientific_evidence_gaps.append(
                {
                    "medium": medium,
                    "unique_samples": unique_samples,
                    "scientific_ready_unique_samples": ready_samples,
                    "minimum_scientific_ready_unique_samples": minimum_ready_samples,
                    "scientific_ready_lineage_count": len(ready_lineages),
                    "minimum_scientific_ready_lineages": 1,
                    "reason_codes": ["strict_scientific_evidence_subset_shortfall"],
                }
            )
    criteria["scientific_evidence_subset_by_medium"] = _criterion(
        not scientific_evidence_gaps,
        scientific_readiness_by_medium,
        {
            "minimum_unique_samples_per_requested_medium": 20,
            "minimum_independent_lineages_per_observed_medium": 1,
            "row_contract": (
                "normalized quantitative value + canonical coordinate + analytical "
                "method + geological/depositional context (or justified marine "
                "not-applicable disposition) + strict provenance + QC disposition"
            ),
        },
        "The archive may retain source-accounted incomplete rows, but every requested medium needs a non-empty strict research subset. This prevents a large screening-only population from masquerading as fully comparable evidence without fabricating publisher metadata.",
        required=mode != "demo",
    )
    criteria["anomaly_background"] = _criterion(
        isinstance(analyzed, int) and analyzed > 0,
        {
            "analyzed_groups": analyzed,
            "insufficient_groups": insufficient,
            "candidate_anomalies": candidates,
        },
        {"analyzed_groups_minimum": 1},
        "At least one comparable production background group must pass the declared n threshold.",
    )
    canonical_rate = (
        database["canonical_coordinate_records"] / database["records"]
        if database["records"]
        else 0.0
    )
    reported_rate = (
        database["reported_coordinate_records"] / database["records"]
        if database["records"]
        else 0.0
    )
    coordinate_mode = execution.get("coordinate_mode") or {}
    effective_coordinate_mode = (
        str(coordinate_mode.get("effective") or "canonical")
        if isinstance(coordinate_mode, Mapping)
        else "canonical"
    )
    mappable_samples = (
        database["canonical_coordinate_samples"]
        if effective_coordinate_mode == "canonical"
        else max(
            database["canonical_coordinate_samples"],
            database["reported_coordinate_samples"],
        )
    )
    minimum_mappable_samples = min(
        database["unique_samples"], 500 if global_scope else 250
    )
    criteria["mappable_records"] = _criterion(
        mappable_samples >= minimum_mappable_samples,
        {
            "effective_coordinate_mode": effective_coordinate_mode,
            "mappable_unique_samples": mappable_samples,
            "canonical_records": database["canonical_coordinate_records"],
            "reported_coordinate_records": database["reported_coordinate_records"],
            "canonical_unique_samples": database["canonical_coordinate_samples"],
            "reported_coordinate_unique_samples": database[
                "reported_coordinate_samples"
            ],
        },
        {"minimum_mappable_unique_samples": minimum_mappable_samples},
        "The interactive atlas needs a meaningful population of distinct mapped samples; reported mode remains explicitly non-canonical.",
        required=mode != "demo",
    )
    land_macroregion_counts = {
        key: int(value)
        for key, value in database["macroregion_unique_samples"].items()
        if key in LAND_MACROREGIONS
    }
    minimum_macroregion_samples = int(
        getattr(
            args,
            "minimum_macroregion_samples",
            DEFAULT_MINIMUM_MACROREGION_SAMPLES,
        )
    )
    minimum_global_macroregions = int(
        getattr(
            args,
            "minimum_global_macroregions",
            DEFAULT_MINIMUM_GLOBAL_MACROREGIONS,
        )
    )
    maximum_global_macroregion_share = float(
        getattr(
            args,
            "maximum_global_macroregion_share",
            DEFAULT_MAXIMUM_GLOBAL_MACROREGION_SHARE,
        )
    )
    qualifying_macroregions = sorted(
        key
        for key, value in land_macroregion_counts.items()
        if value >= minimum_macroregion_samples
    )
    land_sample_total = sum(land_macroregion_counts.values())
    largest_macroregion_share = (
        max(land_macroregion_counts.values(), default=0) / land_sample_total
        if land_sample_total
        else 0.0
    )
    geographic_breadth_pass = (
        len(qualifying_macroregions) >= minimum_global_macroregions
        and largest_macroregion_share <= maximum_global_macroregion_share
    )
    criteria["global_geographic_breadth"] = _criterion(
        not global_scope or geographic_breadth_pass,
        {
            "canonical_land_unique_samples": land_sample_total,
            "macroregion_unique_samples": land_macroregion_counts,
            "qualifying_macroregions": qualifying_macroregions,
            "largest_macroregion_share": round(largest_macroregion_share, 6),
            "reported-only samples excluded": True,
        },
        {
            "minimum_macroregions": minimum_global_macroregions,
            "minimum_unique_samples_per_macroregion": minimum_macroregion_samples,
            "maximum_largest_macroregion_share": maximum_global_macroregion_share,
        },
        "A global atlas must have canonical land samples across multiple Natural Earth macroregions; reported-only coordinates remain visible but cannot prove canonical geographic breadth.",
        required=global_scope and mode != "demo",
    )
    global_spatial = (
        assess_global_spatial_coverage(database, viable_selected_ids, request)
        if global_scope
        else None
    )
    criteria["global_spatial_coverage"] = _criterion(
        not global_scope or bool(global_spatial and global_spatial["passes"]),
        (
            {
                "policy_version": global_spatial["policy_version"],
                "grid_cell_degrees": global_spatial["grid_cell_degrees"],
                "priority_country_codes": global_spatial["priority_country_codes"],
                "core_priority_country_codes": global_spatial[
                    "core_priority_country_codes"
                ],
                "covered_priority_country_codes": global_spatial[
                    "covered_priority_country_codes"
                ],
                "undercovered_priority_country_codes": global_spatial[
                    "undercovered_priority_country_codes"
                ],
                "undercovered_core_priority_country_codes": global_spatial[
                    "undercovered_core_priority_country_codes"
                ],
                "priority_country_coverage_rate": global_spatial[
                    "priority_country_coverage_rate"
                ],
                "country_metrics": global_spatial["country_metrics"],
                "canonical_nonpolar_land_occupied_grid_cells": global_spatial[
                    "canonical_nonpolar_land_occupied_grid_cells"
                ],
                "reported_display_nonpolar_land_occupied_grid_cells": (
                    global_spatial["reported_display_nonpolar_land_occupied_grid_cells"]
                ),
                "target_nonpolar_land_grid_cells": global_spatial[
                    "target_nonpolar_land_grid_cells"
                ],
                "minimum_nonpolar_land_occupied_grid_cells": global_spatial[
                    "minimum_nonpolar_land_occupied_grid_cells"
                ],
                "canonical_nonpolar_land_grid_coverage_rate": global_spatial[
                    "canonical_nonpolar_land_grid_coverage_rate"
                ],
                "macroregion_canonical_occupied_grid_cells": global_spatial[
                    "macroregion_canonical_occupied_grid_cells"
                ],
                "macroregion_target_land_grid_cells": global_spatial[
                    "macroregion_target_land_grid_cells"
                ],
                "macroregion_minimum_occupied_grid_cells": global_spatial[
                    "macroregion_minimum_occupied_grid_cells"
                ],
                "macroregions_below_grid_minimum": global_spatial[
                    "macroregions_below_grid_minimum"
                ],
                "reported-only samples excluded from canonical pass": True,
            }
            if global_spatial
            else {"not_applicable": True}
        ),
        {
            "all_core_priority_countries_pass": True,
            "minimum_priority_country_coverage_rate": (
                GLOBAL_MINIMUM_PRIORITY_COUNTRY_COVERAGE_RATE
            ),
            "minimum_canonical_unique_samples_per_priority_country": (
                GLOBAL_MINIMUM_COUNTRY_SAMPLES
            ),
            "country_grid_rule": (
                "max(2, ceil(10% of country land cells)), capped at 6"
            ),
            "minimum_macroregion_grid_coverage_rate": (
                GLOBAL_MINIMUM_MACROREGION_GRID_COVERAGE_RATE
            ),
            "minimum_global_land_grid_coverage_rate": (
                GLOBAL_MINIMUM_LAND_GRID_COVERAGE_RATE
            ),
        },
        (
            "A global request is audited hierarchically: six largest non-polar "
            "country sentinels, policy-derived priority-country coverage, every non-Antarctic "
            "macroregion, and a coarse global land-cell floor. Empty cells are "
            "observation gaps, never interpolated absence claims."
        ),
        required=global_scope and mode != "demo",
    )
    regional_spatial = (
        None if global_scope else assess_regional_spatial_coverage(database, request)
    )
    regional_spatial_required = bool(
        regional_spatial and regional_spatial["assessable"] and mode != "demo"
    )
    criteria["regional_spatial_coverage"] = _criterion(
        global_scope
        or not regional_spatial_required
        or bool(regional_spatial and regional_spatial["passes"]),
        regional_spatial or {"not_applicable": True},
        {
            "minimum_canonical_unique_samples": (REGIONAL_MINIMUM_CANONICAL_SAMPLES),
            "minimum_coverage_grid_rate": (REGIONAL_MINIMUM_COVERAGE_GRID_RATE),
            "minimum_assessable_coverage_grid_cells": (
                REGIONAL_MINIMUM_COVERAGE_GRID_CELLS
            ),
        },
        (
            "Any named-country or bbox request needs canonical samples across a "
            "policy-selected fraction of its land-or-water coverage cells. The "
            "resolution is derived from extent; unassessable micro-scopes fail "
            "open only for this advisory grid and retain exact point/boundary checks."
        ),
        required=regional_spatial_required,
    )
    spatial_dimension_audit = spatial_sufficiency.audit_spatial_views(
        database.get("spatial_samples") or [],
        request,
        SPATIAL_SUFFICIENCY_POLICY,
    )
    spatial_dimension_required = bool(
        spatial_dimension_audit["assessable"] and mode != "demo"
    )
    criteria["spatial_dimension_coverage"] = _criterion(
        not spatial_dimension_required or spatial_dimension_audit["passes"],
        spatial_dimension_audit,
        {
            "policy_version": SPATIAL_SUFFICIENCY_POLICY["policy_version"],
            "required_views": (
                "overall + every requested element + every requested medium + every requested element × medium"
            ),
        },
        (
            "Each interactive filter view needs its own canonical sample, coverage-cell, "
            "and for global requests coverage-zone breadth. Broad As data cannot hide "
            "a geographically narrow Cu or water layer."
        ),
        required=spatial_dimension_required,
    )
    criteria["spatial_usability"] = _criterion(
        canonical_rate > 0,
        {
            "canonical_rate": round(canonical_rate, 6),
            "reported_coordinate_rate": round(reported_rate, 6),
        },
        {"canonical_rate": ">0 preferred"},
        "Advisory only: missing canonical coordinates reduce spatial usability, not source evidence quality.",
        required=False,
    )
    unmet = sorted(
        key
        for key, criterion in criteria.items()
        if criterion["required"] and criterion["status"] != "pass"
    )
    route_can_cover_missing_dimensions = all(
        available_by_element[item] for item in missing_elements
    ) and all(available_by_medium[item] for item in missing_media)
    available_by_spatial_domain = {
        domain: {
            source_id
            for source_id in viable_selected_ids
            if domain
            in _entry_spatial_domains(
                source_id,
                (_json_object(SOURCE_MANIFEST_PATH).get("sources") or {}).get(
                    source_id
                ),
            )
        }
        for domain in requested_spatial_domains
    }
    route_can_cover_missing_dimensions = route_can_cover_missing_dimensions and all(
        available_by_spatial_domain[item] for item in missing_spatial_domains
    )
    uncovered_element_medium_cells: list[str] = []
    for cell in missing_element_medium_cells:
        element, medium = cell.split("|", 1)
        if not available_by_element[element].intersection(available_by_medium[medium]):
            uncovered_element_medium_cells.append(cell)
    route_can_cover_missing_cells = not uncovered_element_medium_cells
    can_grow = current_target < args.max_per_analyte_observations
    # More observations from the same routed sources can repair volume, a
    # still-thin background group, or a requested dimension known to exist in
    # those sources. They cannot repair the other criteria; those remain in the
    # manual plan even when an independent acquisition improvement proceeds.
    independently_repairable = {
        "acquisition_breadth",
        "record_volume",
        "independent_sample_volume",
        "anomaly_background",
        "source_balance",
        "analytical_readiness",
        "analytical_method_evidence_by_material_source",
        "mappable_records",
        "medium_sample_balance",
        "element_sample_balance",
        "element_medium_sample_balance",
    }
    expansion_targets = set(unmet).intersection(independently_repairable)
    geographic_search_targets = (
        list(global_spatial["geographic_search_targets"]) if global_spatial else []
    )
    spatial_dimension_gaps = build_spatial_dimension_gaps(
        spatial_dimension_audit, viable_selected_ids, request
    )
    spatial_requery_ids = spatial_requery_source_ids(
        geographic_search_targets, spatial_dimension_gaps
    )
    if route_can_cover_missing_dimensions:
        expansion_targets.update(set(unmet).intersection({"requested_dimensions"}))
    if route_can_cover_missing_cells:
        expansion_targets.update(set(unmet).intersection({"element_medium_coverage"}))
    if spatial_requery_ids:
        expansion_targets.update(
            set(unmet).intersection(
                {
                    "global_geographic_breadth",
                    "global_spatial_coverage",
                    "regional_spatial_coverage",
                    "spatial_dimension_coverage",
                }
            )
        )
    expandable_unmet = sorted(expansion_targets)
    non_expandable_unmet = sorted(set(unmet) - expansion_targets)
    discovery_gaps = {
        "viable_selected_source_ids": sorted(viable_selected_ids),
        "observed_source_ids": sorted(observed_source_ids),
        "observed_lineage_ids": sorted(observed_lineage_ids),
        "observed_lineage_ids_by_medium": {
            medium: sorted(database["lineages_by_medium"].get(medium, []))
            for medium in request["media"]
        },
        "elements": sorted(
            item for item in missing_elements if not available_by_element[item]
        ),
        "media": sorted(
            item for item in missing_media if not available_by_medium[item]
        ),
        "spatial_domains": sorted(
            item
            for item in missing_spatial_domains
            if not available_by_spatial_domain[item]
        ),
        "element_medium_cells": uncovered_element_medium_cells,
        "independent_lineages": max(
            0, desired_lineage_count - len(observed_lineage_ids)
        ),
        "medium_lineages": {
            medium: max(0, 2 - per_medium_observed[medium])
            for medium in request["media"]
            if per_medium_observed[medium] < 2
        },
        "medium_sample_balance": medium_sample_shortfalls,
        "element_sample_balance": element_sample_shortfalls,
        "element_medium_sample_balance": element_medium_sample_shortfalls,
        "macroregions_below_minimum": (
            sorted(
                key
                for key in LAND_MACROREGIONS
                if land_macroregion_counts.get(key, 0) < minimum_macroregion_samples
            )
            if global_scope
            else []
        ),
        "priority_countries_below_minimum": (
            list(global_spatial["undercovered_priority_country_codes"])
            if global_spatial
            else []
        ),
        "macroregions_below_grid_minimum": (
            list(global_spatial["macroregions_below_grid_minimum"])
            if global_spatial
            else []
        ),
        "geographic_search_targets": geographic_search_targets,
        "regional_spatial_gap": (
            regional_spatial
            if regional_spatial_required and not regional_spatial["passes"]
            else None
        ),
        "spatial_dimension_gaps": spatial_dimension_gaps,
        "spatial_requery_source_ids": spatial_requery_ids,
        "metadata_evidence_gaps": method_evidence_gaps,
        "scientific_evidence_gaps": scientific_evidence_gaps,
        "source_link_gaps": source_link_gaps,
    }
    # Do not abandon an independently repairable volume/background improvement
    # merely because source diversity is still below target.  Evidence-integrity
    # defects (no online attempt or broken record provenance) do block expansion,
    # as does a requested dimension that no routed source can supply.  This keeps
    # the loop effect-oriented without manufacturing quantity from weak evidence.
    integrity_blockers = {
        "online_acquisition",
        "record_provenance",
        "source_evidence_readiness",
        "metadata_evidence_accounting",
        "geology_evidence_accounting",
        "official_source_links",
    }.intersection(non_expandable_unmet)
    can_expand = (
        mode == "online"
        and bool(expandable_unmet)
        and can_grow
        and not integrity_blockers
    )
    status = "sufficient" if not unmet else "insufficient"

    def shortfall_factor(observed: int, target: int) -> float | None:
        if observed >= target:
            return None
        if observed <= 0:
            return None
        return round(target / observed, 6)

    required_measurement_records = minimum_records if mode != "demo" else 0
    required_independent_samples = minimum_unique_samples if mode != "demo" else 0
    reporting_facts = {
        "measurement_records": database["records"],
        "required_measurement_records": required_measurement_records,
        "measurement_record_shortfall_factor": shortfall_factor(
            database["records"], required_measurement_records
        ),
        "independent_samples": database["unique_samples"],
        "required_independent_samples": required_independent_samples,
        "independent_sample_shortfall_factor": shortfall_factor(
            database["unique_samples"], required_independent_samples
        ),
        "quality_dimension_band_counts": dimension_counts,
        "single_quality_label_prohibited": True,
    }
    return {
        "assessment_version": SUFFICIENCY_VERSION,
        "status": status,
        "criteria": criteria,
        "unmet_required_criteria": unmet,
        "acquisition_repairable_criteria": expandable_unmet,
        "acquisition_blocking_criteria": non_expandable_unmet,
        "discovery_gaps": discovery_gaps,
        "reporting_facts": reporting_facts,
        "can_expand_acquisition": can_expand,
        "current_per_analyte_observations": current_target,
        "next_per_analyte_observations": (
            min(
                args.max_per_analyte_observations,
                max(
                    current_target + 1,
                    int(current_target * args.acquisition_growth_factor),
                ),
            )
            if can_expand
            else None
        ),
        "claim_boundary": (
            "Passing means the requested output has a useful evidence-bearing minimum, not that sampling is "
            "globally/nationally representative. Failing spatial usability does not downgrade source evidence."
        ),
    }


def actionable_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    """Stable signature used to detect a round that changed nothing."""
    fingerprints = record.get("input_fingerprints", {})
    return (
        record.get("execution_status"),
        record.get("counts", {}).get("action_required"),
        tuple(sorted(item["source_id"] for item in record.get("failed_sources", []))),
        fingerprints.get("input_sha256"),
        fingerprints.get("evidence_sha256"),
        (record.get("acquisition_target") or {}).get("per_analyte_observations"),
        tuple((record.get("sufficiency") or {}).get("unmet_required_criteria") or []),
    )


def acquisition_progress_signature(record: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return content metrics that must change after a larger acquisition target."""

    sufficiency = record.get("sufficiency") or {}
    reporting_facts = sufficiency.get("reporting_facts") or {}
    criteria = sufficiency.get("criteria") or {}
    observed_criteria = {
        str(key): value.get("observed")
        for key, value in criteria.items()
        if isinstance(value, Mapping)
    }
    sample_observed = (
        (sufficiency.get("criteria") or {}).get("independent_sample_volume") or {}
    ).get("observed") or {}
    return (
        reporting_facts.get(
            "measurement_records", (record.get("counts") or {}).get("records")
        ),
        reporting_facts.get(
            "independent_samples",
            sample_observed.get("unique_samples")
            if isinstance(sample_observed, Mapping)
            else None,
        ),
        json.dumps(
            observed_criteria,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def build_repair_plan(record: dict[str, Any]) -> dict[str, Any]:
    autonomous: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = list(record.get("manual_groups", []))
    retryable_ids = sorted(
        item["source_id"]
        for item in record.get("failed_sources", [])
        if item.get("retryable")
    )
    if retryable_ids:
        autonomous.append(
            {
                "action": "retry_failed_sources",
                "detail": "重试瞬态获取失败的来源；成功来源命中缓存，不重复下载。",
                "source_ids": retryable_ids,
            }
        )
    if record.get("run_failure_retryable"):
        autonomous.append(
            {
                "action": "retry_run",
                "detail": f"整轮失败状态 {record.get('execution_status')} 判定为瞬态，重试一轮。",
                "source_ids": [],
            }
        )
    sufficiency = record.get("sufficiency") or {}
    if sufficiency.get("status") == "insufficient" and sufficiency.get(
        "can_expand_acquisition"
    ):
        expansion_source_ids = sorted(
            str(item)
            for item in (
                (sufficiency.get("discovery_gaps") or {}).get(
                    "spatial_requery_source_ids"
                )
                or []
            )
        )
        autonomous.append(
            {
                "action": "expand_acquisition",
                "detail": (
                    "数据充分性门禁未通过；在冻结请求和已路由来源内把每元素目标提高到 "
                    f"{sufficiency.get('next_per_analyte_observations')} 后继续一轮。"
                    + (
                        " 空间缺口已证明这些已选来源仍值得重查："
                        + ", ".join(expansion_source_ids)
                        + "。"
                        if expansion_source_ids
                        else ""
                    )
                ),
                "source_ids": expansion_source_ids,
            }
        )
    discovery_gaps = sufficiency.get("discovery_gaps") or {}
    if any(
        discovery_gaps.get(key)
        for key in ("elements", "media", "spatial_domains", "element_medium_cells")
    ):
        dimension_gaps = {
            key: discovery_gaps.get(key) or []
            for key in ("elements", "media", "spatial_domains", "element_medium_cells")
        }
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": "SOURCE_COVERAGE_GAP",
                "count": sum(
                    len(discovery_gaps.get(key) or [])
                    for key in (
                        "elements",
                        "media",
                        "spatial_domains",
                        "element_medium_cells",
                    )
                ),
                "recommended_action": (
                    "现有可执行来源无法覆盖缺口；回到 source_catalog/source discovery，核验并实现"
                    f"与请求相符的来源。缺失={dimension_gaps}。不得用增加同源记录掩盖。"
                ),
            }
        )
    geographic_targets = [
        item
        for item in (discovery_gaps.get("geographic_search_targets") or [])
        if isinstance(item, Mapping)
    ]
    if geographic_targets:
        target_summary = [
            {
                "country": item.get("country_iso_a3"),
                "tier": item.get("priority_tier"),
                "mode": item.get("repair_mode"),
                "canonical_samples": item.get("canonical_unique_samples"),
                "canonical_cells": item.get("canonical_occupied_grid_cells"),
                "minimum_cells": item.get("minimum_canonical_occupied_grid_cells"),
                "selected": item.get("selected_source_candidates") or [],
                "registered": item.get("registered_source_candidates") or [],
                "catalog": item.get("catalog_candidate_source_ids") or [],
            }
            for item in geographic_targets
        ]
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": "GLOBAL_SPATIAL_COVERAGE_GAP",
                "count": len(geographic_targets),
                "recommended_action": (
                    "按 core→extended→macroregion/global backfill 顺序逐区域修复；"
                    "repair_coordinate_evidence=核验原坐标/CRS，requery_selected_source="
                    "对已选来源执行国家定向抽取，route_registered_source=路由已注册来源，"
                    "implement_catalog_candidate=核验许可与内容后实现候选适配器，"
                    "targeted_source_discovery=在线检索国家地调、PANGAEA、EarthChem 等"
                    "可追溯记录并注册。repair_mode 是首选动作；若以真实尝试证明无法"
                    "修复，必须沿候选层级继续到 targeted_source_discovery。每次修复后"
                    "恢复同一冻结请求 Loop，直到门禁通过或"
                    "逐项记录不可获得证据。不得插值填空、伪造坐标、删除高密度区域来优化"
                    "比例，也不得用所属大洲其他国家代替空白国家。目标="
                    f"{json.dumps(target_summary, ensure_ascii=False, sort_keys=True)}"
                ),
            }
        )
    regional_gap = discovery_gaps.get("regional_spatial_gap")
    if isinstance(regional_gap, Mapping):
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": "REGIONAL_SPATIAL_COVERAGE_GAP",
                "count": 1,
                "recommended_action": (
                    "区域空间门禁未通过；按请求 scope 定向采集并保留 canonical 坐标"
                    "证据。若 repair_mode=repair_coordinate_evidence，先核验已展示记录的"
                    "datum/CRS；不能证实时保留 reported-only 并转在线来源发现。不得用"
                    "同一区域内一个局部簇、复制记录或插值填补范围。缺口="
                    f"{json.dumps(dict(regional_gap), ensure_ascii=False, sort_keys=True)}"
                ),
            }
        )
    spatial_dimension_gaps = [
        item
        for item in (discovery_gaps.get("spatial_dimension_gaps") or [])
        if isinstance(item, Mapping)
    ]
    if spatial_dimension_gaps:
        target_summary = [
            {
                "view_id": item.get("view_id"),
                "elements": item.get("required_elements") or [],
                "media": item.get("required_media") or [],
                "canonical_samples": item.get("canonical_unique_samples"),
                "minimum_samples": item.get("minimum_canonical_unique_samples"),
                "canonical_cells": item.get("canonical_occupied_grid_cells"),
                "minimum_cells": item.get("minimum_canonical_occupied_grid_cells"),
                "coverage_zones": item.get("qualifying_coverage_zones") or [],
                "minimum_coverage_zones": item.get("minimum_qualifying_coverage_zones"),
                "repair_mode": item.get("repair_mode"),
                "country_targets": [
                    {
                        "country_iso_a3": target.get("country_iso_a3"),
                        "target_bboxes": target.get("target_bboxes") or [],
                    }
                    for target in item.get("country_targets") or []
                    if isinstance(target, Mapping)
                ],
                "country_longitude_band_targets": item.get(
                    "country_longitude_band_targets"
                )
                or [],
            }
            for item in spatial_dimension_gaps
        ]
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": "SPATIAL_DIMENSION_COVERAGE_GAP",
                "count": len(spatial_dimension_gaps),
                "recommended_action": (
                    "逐个处理机器生成的 map-view 缺口，不按示例国家写规则：以"
                    " required_elements + required_media + country_targets/bbox 组成定向"
                    "检索契约，依次执行该项 repair_mode 及候选层级；每次纳入新证据后"
                    "用同一冻结请求续跑。一个元素、介质或组合在其他区域的高记录量"
                    "不能替代该视图的空间广度。不得复制、插值或借用别的视图填空。目标="
                    f"{json.dumps(target_summary, ensure_ascii=False, sort_keys=True)}"
                ),
            }
        )
    blocking_actions = {
        "source_diversity": (
            "SOURCE_DIVERSITY_GAP",
            "审计失败来源与 review_sources，增加可验证的独立来源血缘；不能用同一来源扩量代替。",
        ),
        "source_diversity_by_medium": (
            "MEDIUM_LINEAGE_GAP",
            "为缺少独立血缘的介质补充可验证来源，并保留逐来源失败与排除理由。",
        ),
        "record_provenance": (
            "RECORD_PROVENANCE_GAP",
            "修复 source_id/source_locator 与 manifest/hash 绑定后再扩采；不得用更多不可追溯记录提高数量。",
        ),
        "official_source_links": (
            "OFFICIAL_SOURCE_LINK_GAP",
            "逐来源补齐可点击的官方数据页、下载 URL 或 DOI，并与记录级 source_locator 分开保留；本地行定位和官网链接不能互相替代。",
        ),
        "source_balance": (
            "SOURCE_CONCENTRATION_GAP",
            "最大来源占比过高；优先补充并扩展其他独立来源，不得把单一大库记录量描述为广泛覆盖。",
        ),
        "source_acquisition_success": (
            "SOURCE_ACQUISITION_COVERAGE_GAP",
            "逐源获取成功率不足；修复适配器容量、下载哈希、缓存或访问问题，并保留每源失败证据。",
        ),
        "source_evidence_readiness": (
            "SOURCE_EVIDENCE_READINESS_GAP",
            "先补齐来源定位、许可、版本与哈希证据；空间或方法分数不能代替来源证据。",
        ),
        "metadata_evidence_accounting": (
            "METADATA_EVIDENCE_ACCOUNTING_GAP",
            "逐记录补齐方法、坐标精度和记录定位的 present / publisher-not-reported 责任状态；不得用空字符串冒充已说明。",
        ),
        "geology_evidence_accounting": (
            "GEOLOGY_EVIDENCE_ACCOUNTING_GAP",
            "逐记录补齐发布方地质背景、带边界不确定度的点匹配背景，或明确的不可适用/不可获得原因；不得把空值当成已完成空间匹配。",
        ),
        "scientific_evidence_subset_by_medium": (
            "STRICT_SCIENTIFIC_SUBSET_GAP",
            "为每个请求介质补充同时具备定量值、canonical 坐标、分析方法、地质背景、严格来源链和 QC 的独立样品子集；保留不完整归档行但不得把它们用于严格比较。",
        ),
        "analytical_readiness": (
            "ANALYTICAL_READINESS_GAP",
            "方法/QC 就绪记录比例不足；补充方法证据或增加具备可比方法语义的来源，不得推测分析方法。",
        ),
        "mappable_records": (
            "MAPPABLE_POPULATION_GAP",
            "可上图记录不足；补充带可验证坐标的来源。reported-only 可示意展示，但不得冒充 canonical WGS84。",
        ),
        "element_medium_coverage": (
            "ELEMENT_MEDIUM_MATRIX_GAP",
            "元素×介质覆盖矩阵过稀；按缺失单元补充相符来源，不能只满足元素和介质的集合并集。",
        ),
        "medium_sample_balance": (
            "MEDIUM_SAMPLE_BALANCE_GAP",
            "请求介质之间的独立物理样点容量严重失衡；按短缺介质补充新样品和独立来源，不能用同一样品的多元素记录行抬高数量。",
        ),
        "element_sample_balance": (
            "ELEMENT_SAMPLE_BALANCE_GAP",
            "请求元素之间的独立物理样点容量严重失衡；按短缺元素补充新样品和独立来源，不能让优势元素的记录量掩盖薄弱元素。",
        ),
        "element_medium_sample_balance": (
            "ELEMENT_MEDIUM_SAMPLE_BALANCE_GAP",
            "元素×介质单元的独立物理样点容量严重失衡；只补精确短缺单元，不能用同元素其他介质或同介质其他元素代替。",
        ),
        "record_volume": (
            "RECORD_VOLUME_GAP",
            "已验证记录量仍低于自适应门槛；在来源容量和证据边界内继续扩采或补充来源。",
        ),
        "independent_sample_volume": (
            "INDEPENDENT_SAMPLE_VOLUME_GAP",
            "独立物理样品数不足；补充新的 sample identity，不能把同一样品的多元素测定行当作新增样品。",
        ),
        "global_geographic_breadth": (
            "GLOBAL_MACROREGION_COVERAGE_GAP",
            "全球 canonical 样品的大区广度或均衡性不足；按缺失大区补来源。reported-only 点可展示，但不能代替 WGS84 覆盖证据。",
        ),
        "global_spatial_coverage": (
            "GLOBAL_SPATIAL_COVERAGE_GAP",
            "按 sufficiency.discovery_gaps.geographic_search_targets 的国家、宏区和修复模式逐项补证；大洲总量不能代替空白国家，空白格不得插值。",
        ),
        "regional_spatial_coverage": (
            "REGIONAL_SPATIAL_COVERAGE_GAP",
            "按冻结国家/范围框定向补充带 canonical 坐标的独立样品；局部高密度簇和 reported-only 点不能证明区域空间广度。",
        ),
        "spatial_dimension_coverage": (
            "SPATIAL_DIMENSION_COVERAGE_GAP",
            "按 spatial_dimension_gaps 的元素、介质、范围和动态国家队列补充证据；不得用其他筛选视图的覆盖代替。",
        ),
        "anomaly_background": (
            "ANOMALY_BACKGROUND_GAP",
            "没有生产阈值可分析背景组；补充同介质、同方法、同基准且可定量的独立样品，不降低阈值。",
        ),
        "online_acquisition": (
            "ONLINE_ACQUISITION_NOT_ATTEMPTED",
            "检查执行入口与 source_outcomes，实际尝试请求兼容的在线来源后再评估充分性。",
        ),
        "assessment_unavailable": (
            "SUFFICIENCY_ASSESSMENT_UNAVAILABLE",
            "修复充分性报告读取或 schema 错误，不能把无法评估当作已充分。",
        ),
    }
    existing_codes = {str(item.get("issue_code")) for item in manual}
    plan_criteria = set(sufficiency.get("acquisition_blocking_criteria") or [])
    if sufficiency.get("status") == "insufficient" and not sufficiency.get(
        "can_expand_acquisition"
    ):
        plan_criteria.update(sufficiency.get("unmet_required_criteria") or [])
    if geographic_targets:
        # The hierarchical task already contains the macroregion deficits; do
        # not create a second, less specific D1 ticket for the same holes.
        plan_criteria.discard("global_geographic_breadth")
    for criterion in sorted(plan_criteria):
        action = blocking_actions.get(str(criterion))
        if action is None or action[0] in existing_codes:
            continue
        code, detail = action
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": code,
                "count": 1,
                "recommended_action": detail,
            }
        )
        existing_codes.add(code)
    for item in record.get("failed_sources", []):
        if item.get("retryable"):
            continue
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": "SOURCE_ACQUISITION_FAILED",
                "count": 1,
                "recommended_action": (
                    f"来源 {item['source_id']} 非瞬态失败（{item['error'][:160]}）；"
                    "核对来源准入、许可与接口后重跑，或从请求中移除该来源。"
                ),
            }
        )
    return {"autonomous": autonomous, "manual": manual[:MANUAL_PLAN_GROUP_CAP]}


def next_round_priority_source_ids(record: Mapping[str, Any] | None) -> list[str]:
    """Extract the last round's machine-authorized source scheduling priorities.

    Only source IDs attached to autonomous repair actions are eligible. Manual
    discovery or adapter work therefore cannot cross the immutable-Skill
    boundary merely because the spatial audit found an empty region.
    """

    if not isinstance(record, Mapping):
        return []
    plan = build_repair_plan(dict(record))
    ordered: list[str] = []
    seen: set[str] = set()
    for action in plan.get("autonomous") or []:
        if not isinstance(action, Mapping):
            continue
        for raw_source_id in action.get("source_ids") or []:
            source_id = str(raw_source_id)
            if source_id and source_id not in seen:
                seen.add(source_id)
                ordered.append(source_id)
    return ordered


def build_d1_action_groups(tasks: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated view debts into bounded, receipt-driven field actions.

    A single empty northwest zone can fail overall, element, medium and every
    element×medium view. Those remain separate scientific assertions, but an
    operator should search or audit the zone once, then recompute all affected
    views. Grouping prevents hundreds of near-identical bbox queries from
    exhausting an Agent's context without producing a new source.
    """

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for task in tasks:
        identity = json.dumps(
            {
                "bbox": task.get("bbox") or [],
                "country_iso_a3": task.get("country_iso_a3"),
                "scope_key": task.get("scope_key"),
                "required_spatial_domains": task.get("required_spatial_domains") or [],
                "preferred_repair_mode": task.get("preferred_repair_mode"),
                "execution_class": task.get("execution_class"),
                "selected": task.get("selected_source_candidates") or [],
                "registered": task.get("registered_source_candidates") or [],
                "catalog": task.get("catalog_candidate_source_ids") or [],
                "continuation_strategy": task.get("continuation_strategy"),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        grouped.setdefault(identity, []).append(task)

    action_groups: list[dict[str, Any]] = []
    for identity, members in grouped.items():
        members = sorted(
            members,
            key=lambda item: (int(item.get("priority") or 0), str(item.get("task_id"))),
        )
        first = members[0]

        def merged_strings(field: str) -> list[str]:
            return list(
                dict.fromkeys(
                    str(value)
                    for member in members
                    for value in member.get(field) or []
                    if str(value)
                )
            )

        group_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        action_groups.append(
            {
                "action_group_id": group_id,
                "priority": min(int(item.get("priority") or 0) for item in members),
                "status": "pending",
                "target_label": str(
                    first.get("target_label") or first.get("scope_key") or "target"
                ),
                "search_aliases": merged_strings("search_aliases"),
                "admin1_search_hints": merged_strings("admin1_search_hints"),
                "gazetteer_semantics": str(first.get("gazetteer_semantics") or ""),
                "scope_key": str(first.get("scope_key") or ""),
                "country_iso_a3": first.get("country_iso_a3"),
                "country_name": first.get("country_name"),
                "macroregion": first.get("macroregion"),
                "bbox": list(first.get("bbox") or []),
                "member_task_ids": [str(item.get("task_id")) for item in members],
                "view_ids": list(
                    dict.fromkeys(str(item.get("view_id") or "") for item in members)
                ),
                "task_kinds": list(
                    dict.fromkeys(str(item.get("task_kind") or "") for item in members)
                ),
                "required_elements": merged_strings("required_elements"),
                "required_media": merged_strings("required_media"),
                "required_spatial_domains": merged_strings("required_spatial_domains"),
                "reason_codes": merged_strings("reason_codes"),
                "preferred_repair_mode": first.get("preferred_repair_mode"),
                "execution_class": first.get("execution_class"),
                "fallback_action_chain": list(first.get("fallback_action_chain") or []),
                "selected_source_candidates": list(
                    first.get("selected_source_candidates") or []
                ),
                "registered_source_candidates": list(
                    first.get("registered_source_candidates") or []
                ),
                "catalog_candidate_source_ids": list(
                    first.get("catalog_candidate_source_ids") or []
                ),
                "discovery_queries": merged_strings("discovery_queries")[:24],
                "discovery_platform_sequence": merged_strings(
                    "discovery_platform_sequence"
                ),
                "completion_evidence_required": merged_strings(
                    "completion_evidence_required"
                ),
                "continuation_strategy": first.get("continuation_strategy"),
                "attempt_receipt_required": True,
                "attempt_receipt_status": "unattempted",
            }
        )
    action_groups.sort(key=lambda item: (item["priority"], item["action_group_id"]))
    return action_groups


def build_d1_repair_queue(
    report: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    """Flatten structural D1 gaps into an executable, auditable work queue."""

    # Keep failure reporting failure-safe: malformed top-level JSON must not
    # trigger a second exception while the controller is writing diagnostics.
    request = request if isinstance(request, Mapping) else {}

    rounds = report.get("rounds") if isinstance(report.get("rounds"), list) else []
    last = next(
        (
            item
            for item in reversed(rounds)
            if isinstance(item, Mapping) and item.get("sufficiency")
        ),
        {},
    )
    sufficiency = last.get("sufficiency") if isinstance(last, Mapping) else {}
    sufficiency = sufficiency if isinstance(sufficiency, Mapping) else {}
    gaps = sufficiency.get("discovery_gaps")
    gaps = gaps if isinstance(gaps, Mapping) else {}
    action_chain = [
        "repair_coordinate_evidence",
        "requery_selected_source",
        "route_registered_source",
        "implement_catalog_candidate",
        "targeted_source_discovery",
    ]
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()

    def request_scope() -> tuple[str, list[float], str | None, str | None, str | None]:
        try:
            resolved = spatial_scope.resolve_region(request.get("region"))
        except (KeyError, TypeError, ValueError, spatial_scope.SpatialScopeError):
            return "request", [], None, None, None
        country_code = str(resolved.get("country_code") or "") or None
        country_name = None
        macroregion = None
        if country_code:
            registry = spatial_scope.load_country_registry()
            country = registry["by_code"].get(country_code) or {}
            country_name = str(country.get("name") or "") or None
            macroregion = spatial_scope.load_macroregion_registry().get(country_code)
        return (
            str(resolved.get("key") or "request"),
            [float(item) for item in resolved.get("bbox") or []],
            country_code,
            country_name,
            macroregion,
        )

    scope_key, scope_bbox, scope_country, scope_country_name, scope_macroregion = (
        request_scope()
    )
    viable_selected_source_ids = {
        str(item) for item in gaps.get("viable_selected_source_ids") or []
    }
    observed_lineage_ids = {
        str(item) for item in gaps.get("observed_lineage_ids") or []
    }
    raw_medium_lineages = gaps.get("observed_lineage_ids_by_medium")
    raw_medium_lineages = (
        raw_medium_lineages if isinstance(raw_medium_lineages, Mapping) else {}
    )

    def task_candidates(
        elements: Sequence[str],
        media: Sequence[str],
        *,
        bbox: Sequence[Any] | None = None,
        spatial_domains: Sequence[str] | None = None,
        require_spatial_evidence: bool = False,
        excluded_lineages: set[str] | None = None,
    ) -> dict[str, list[str]]:
        return _source_candidate_layers(
            selected_source_ids=viable_selected_source_ids,
            request=request,
            elements=elements,
            media=media,
            target_bbox=bbox,
            target_spatial_domains=spatial_domains,
            require_spatial_evidence=require_spatial_evidence,
            excluded_lineages=excluded_lineages,
        )

    def candidate_repair_mode(candidates: Mapping[str, Any]) -> str:
        if candidates.get("selected"):
            return "requery_selected_source"
        if candidates.get("registered"):
            return "route_registered_source"
        if candidates.get("catalog"):
            return "implement_catalog_candidate"
        return "targeted_source_discovery"

    def add_task(
        *,
        priority: int,
        task_kind: str,
        scope_key: str,
        view_id: str,
        elements: Sequence[str],
        media: Sequence[str],
        bbox: Sequence[Any],
        country: Mapping[str, Any] | None,
        source_candidates: Mapping[str, Any] | None = None,
        repair_mode: str,
        reason_codes: Sequence[str],
        observed: Mapping[str, Any],
        target: Mapping[str, Any],
        required_spatial_domains: Sequence[str] | None = None,
        completion_evidence_required: Sequence[str] | None = None,
    ) -> None:
        country_code = str((country or {}).get("country_iso_a3") or "")
        identity = "|".join(
            (
                task_kind,
                scope_key,
                view_id,
                ",".join(elements),
                ",".join(media),
                ",".join(required_spatial_domains or []),
                country_code,
                ",".join(str(item) for item in bbox),
            )
        )
        task_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        if task_id in seen:
            return
        seen.add(task_id)
        location = country or {}
        candidates = source_candidates or location
        base_scope_label = str(
            location.get("country_name")
            or location.get("macroregion")
            or scope_key
            or "requested region"
        )
        target_descriptor = regional_search_target(
            scope_label=base_scope_label,
            scope_bbox=(
                spatial_scope.load_country_registry()["by_code"]
                .get(country_code, {})
                .get("bbox", scope_bbox)
                if country_code
                else scope_bbox
            ),
            target_bbox=bbox,
            country_iso_a3=country_code or None,
            coverage_zone_id=str(observed.get("coverage_zone_id") or "") or None,
        )
        if repair_mode == "rerun_current_controller":
            normalized_repair_mode = repair_mode
            fallback_action_chain = [repair_mode]
            discovery_queries: list[str] = []
            discovery_platform_sequence: list[str] = []
            minimum_distinct_discovery_families = 0
        else:
            normalized_repair_mode = (
                repair_mode
                if repair_mode in action_chain
                else "targeted_source_discovery"
            )
            start_index = action_chain.index(normalized_repair_mode)
            fallback_action_chain = action_chain[start_index:]
            query_elements = list(elements) or [
                str(item) for item in request.get("elements") or []
            ]
            query_media = list(media) or [
                str(item) for item in request.get("media") or []
            ]
            element_terms = " ".join(query_elements) or "elements"
            medium_terms = " ".join(query_media) or "rock soil sediment water"
            query_labels = list(target_descriptor["search_aliases"][:4]) or [
                target_descriptor["target_label"]
            ]
            discovery_queries = [
                f'"{label}" geochemical open dataset {element_terms} {medium_terms} latitude longitude'
                for label in query_labels
            ]
            discovery_queries.extend(
                [
                    f'"{target_descriptor["target_label"]}" geological survey geochemistry data download {element_terms}',
                    f'site:pangaea.de "{target_descriptor["target_label"]}" geochemistry {element_terms}',
                    f'site:earthchem.org "{target_descriptor["target_label"]}" {element_terms} {medium_terms}',
                    f'(site:zenodo.org OR site:figshare.com) "{target_descriptor["target_label"]}" geochemical {element_terms}',
                ]
            )
            discovery_queries = list(dict.fromkeys(discovery_queries))
            discovery_platform_sequence = [
                "registered_source_catalog",
                "national_geological_or_environmental_survey",
            ]
            if "rock" in query_media:
                discovery_platform_sequence.extend(["GEOROC", "EarthChem"])
            if {"soil", "sediment"}.intersection(query_media):
                discovery_platform_sequence.extend(["PANGAEA", "EarthChem"])
            if "water" in query_media:
                discovery_platform_sequence.extend(["GEMStat", "PANGAEA"])
            discovery_platform_sequence.extend(
                ["Zenodo", "Figshare", "publisher_supplementary_data"]
            )
            discovery_platform_sequence = list(
                dict.fromkeys(discovery_platform_sequence)
            )
            minimum_distinct_discovery_families = min(
                3, len(discovery_platform_sequence)
            )
        selected_source_candidates = list(
            candidates.get("selected_source_candidates")
            or candidates.get("selected")
            or []
        )
        registered_source_candidates = list(
            candidates.get("registered_source_candidates")
            or candidates.get("registered")
            or []
        )
        catalog_candidate_source_ids = list(
            candidates.get("catalog_candidate_source_ids")
            or candidates.get("catalog")
            or []
        )
        execution_class = {
            "rerun_current_controller": "controller_rerun_current_skill",
            "requery_selected_source": "data_action_current_skill",
            "route_registered_source": "data_action_current_skill",
            "repair_coordinate_evidence": "evidence_audit_current_skill",
            "implement_catalog_candidate": "skill_maintenance_new_run",
            "targeted_source_discovery": "skill_maintenance_new_run",
        }[normalized_repair_mode]
        evidence_requirements = list(
            completion_evidence_required
            or (
                "attempted action and timestamp",
                "source URL/DOI, license and version decision",
                "record/sample/canonical-cell delta or explicit no-hit evidence",
                "same frozen scientific request resumed under an auditable continuation strategy",
            )
        )
        discovery_family_evidence = "at least three distinct discovery families attempted with per-family hit, no-hit or blocked evidence"
        if (
            minimum_distinct_discovery_families >= 3
            and discovery_family_evidence not in evidence_requirements
        ):
            evidence_requirements.append(discovery_family_evidence)
        tasks.append(
            {
                "task_id": task_id,
                "priority": priority,
                "status": "pending",
                "task_kind": task_kind,
                "scope_key": scope_key,
                "view_id": view_id,
                "required_elements": list(elements),
                "required_media": list(media),
                "required_spatial_domains": list(required_spatial_domains or []),
                "bbox": list(bbox),
                "country_iso_a3": country_code or None,
                "country_name": str(location.get("country_name") or "") or None,
                "macroregion": str(location.get("macroregion") or "") or None,
                "target_label": target_descriptor["target_label"],
                "search_aliases": target_descriptor["search_aliases"],
                "admin1_search_hints": target_descriptor["admin1_search_hints"],
                "gazetteer_semantics": target_descriptor["gazetteer_semantics"],
                "reason_codes": list(reason_codes),
                "observed": dict(observed),
                "target": dict(target),
                "preferred_repair_mode": normalized_repair_mode,
                "execution_class": execution_class,
                "fallback_action_chain": fallback_action_chain,
                "selected_source_candidates": selected_source_candidates,
                "registered_source_candidates": registered_source_candidates,
                "catalog_candidate_source_ids": catalog_candidate_source_ids,
                "discovery_queries": discovery_queries,
                "discovery_platform_sequence": discovery_platform_sequence,
                "minimum_distinct_discovery_families": minimum_distinct_discovery_families,
                "completion_evidence_required": evidence_requirements,
                "continuation_strategy": (
                    "new_output_after_skill_change"
                    if any(
                        action
                        in {"implement_catalog_candidate", "targeted_source_discovery"}
                        for action in fallback_action_chain
                    )
                    else "same_output_data_only"
                ),
            }
        )

    assessment_version = str(sufficiency.get("assessment_version") or "")
    assessment_status = str(sufficiency.get("status") or "")
    unmet_criteria = {
        str(item) for item in sufficiency.get("unmet_required_criteria") or []
    }
    if (
        assessment_version != SUFFICIENCY_VERSION
        or assessment_status not in {"sufficient", "insufficient"}
        or "assessment_unavailable" in unmet_criteria
        or not D1_QUEUE_CANDIDATE_FACT_KEYS.issubset(gaps)
    ):
        if assessment_version and assessment_version != SUFFICIENCY_VERSION:
            reason = "unsupported_sufficiency_assessment_version"
        elif (
            assessment_version == SUFFICIENCY_VERSION
            and not D1_QUEUE_CANDIDATE_FACT_KEYS.issubset(gaps)
        ):
            reason = "d1_candidate_facts_unavailable"
        else:
            reason = "sufficiency_assessment_unavailable"
        add_task(
            priority=100,
            task_kind="sufficiency_assessment_gap",
            scope_key=scope_key,
            view_id="overall",
            elements=[str(item) for item in request.get("elements") or []],
            media=[str(item) for item in request.get("media") or []],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            repair_mode="rerun_current_controller",
            reason_codes=[reason],
            observed={
                "assessment_version": assessment_version or None,
                "assessment_status": assessment_status or None,
            },
            target={
                "assessment_version": SUFFICIENCY_VERSION,
                "required_candidate_facts": sorted(D1_QUEUE_CANDIDATE_FACT_KEYS),
            },
            completion_evidence_required=[
                "same frozen request hash evaluated by the current controller",
                "current-version sufficiency assessment persisted in loop_report.json",
                "D1 repair queue regenerated from the current assessment",
            ],
        )
        # Old or failed assessments cannot safely define current D1 targets.
        # Re-evaluate first, then regenerate the queue from v5 facts.
        gaps = {}

    view_gaps = [
        item
        for item in gaps.get("spatial_dimension_gaps") or []
        if isinstance(item, Mapping)
    ]
    for view_rank, gap in enumerate(view_gaps):
        countries = [
            item
            for item in gap.get("country_targets") or []
            if isinstance(item, Mapping)
        ] or [None]
        coverage_zone_targets = [
            item
            for item in gap.get("coverage_zone_targets") or []
            if isinstance(item, Mapping)
        ]
        country_band_targets = [
            item
            for item in gap.get("country_longitude_band_targets") or []
            if isinstance(item, Mapping)
        ]
        for country_rank, country in enumerate(countries):
            matching_band_targets = [
                item
                for item in country_band_targets
                if country is not None
                and item.get("country_iso_a3") == country.get("country_iso_a3")
            ]
            country_bbox_targets = (
                [
                    {
                        "zone_id": f"country:{country.get('country_iso_a3')}:bbox:{index}",
                        "bbox": list(bbox),
                    }
                    for index, bbox in enumerate(country.get("target_bboxes") or [])
                    if isinstance(bbox, Sequence)
                    and not isinstance(bbox, (str, bytes))
                    and len(bbox) == 4
                ]
                if country is not None
                else []
            )
            zone_targets = (
                matching_band_targets
                or country_bbox_targets
                or coverage_zone_targets
                or [None]
            )
            for zone_rank, zone in enumerate(zone_targets):
                zone_bbox = list((zone or {}).get("bbox") or gap.get("bbox") or [])
                required_elements = [
                    str(item) for item in gap.get("required_elements") or []
                ]
                required_media = [str(item) for item in gap.get("required_media") or []]
                if str(gap.get("view_id") or "").startswith("spatial_domain:"):
                    target_domains = [str(gap.get("view_id")).split(":", 1)[1]]
                else:
                    target_domains = []
                    media_for_domain = required_media or [
                        str(item) for item in request.get("media") or []
                    ]
                    if {"rock", "soil"}.intersection(media_for_domain):
                        target_domains.append("land")
                    if {"sediment", "water"}.intersection(media_for_domain):
                        target_domains.append("inland_water")
                    target_domains = list(dict.fromkeys(target_domains)) or ["land"]
                candidates = task_candidates(
                    required_elements,
                    required_media,
                    bbox=zone_bbox,
                    spatial_domains=target_domains,
                    require_spatial_evidence=True,
                )
                if "reported_only_coordinate_evidence" in set(
                    str(item) for item in gap.get("reason_codes") or []
                ) and candidates.get("selected"):
                    mode = "repair_coordinate_evidence"
                else:
                    mode = candidate_repair_mode(candidates)
                add_task(
                    priority=1000 + view_rank * 100 + country_rank * 10 + zone_rank,
                    task_kind="spatial_dimension_gap",
                    scope_key=str(gap.get("scope_key") or ""),
                    view_id=str(gap.get("view_id") or ""),
                    elements=required_elements,
                    media=required_media,
                    bbox=zone_bbox,
                    country=country,
                    source_candidates=candidates,
                    repair_mode=mode,
                    reason_codes=[str(item) for item in gap.get("reason_codes") or []],
                    observed={
                        "coverage_zone_id": (zone or {}).get("zone_id")
                        or (zone or {}).get("band_id"),
                        "canonical_unique_samples": int(
                            gap.get("canonical_unique_samples") or 0
                        ),
                        "canonical_occupied_grid_cells": int(
                            (
                                (zone or {}).get("canonical_occupied_grid_cells")
                                if zone is not None
                                else gap.get("canonical_occupied_grid_cells")
                            )
                            or 0
                        ),
                        "reported_display_occupied_grid_cells": int(
                            (
                                (zone or {}).get("reported_display_occupied_grid_cells")
                                if zone is not None
                                else gap.get("reported_display_occupied_grid_cells")
                            )
                            or 0
                        ),
                        "qualifying_coverage_zones": list(
                            gap.get("qualifying_coverage_zones") or []
                        ),
                        "covered_land_macroregions": list(
                            gap.get("covered_land_macroregions") or []
                        ),
                        "missing_land_macroregions": list(
                            gap.get("missing_land_macroregions") or []
                        ),
                    },
                    target={
                        "coverage_zone_id": (zone or {}).get("zone_id")
                        or (zone or {}).get("band_id"),
                        "minimum_zone_occupied_grid_cells": 1
                        if zone is not None
                        else 0,
                        "minimum_canonical_unique_samples": int(
                            gap.get("minimum_canonical_unique_samples") or 0
                        ),
                        "minimum_canonical_occupied_grid_cells": int(
                            gap.get("minimum_canonical_occupied_grid_cells") or 0
                        ),
                        "minimum_qualifying_coverage_zones": int(
                            gap.get("minimum_qualifying_coverage_zones") or 0
                        ),
                        "minimum_land_macroregions": int(
                            gap.get("minimum_land_macroregions") or 0
                        ),
                    },
                    required_spatial_domains=target_domains,
                )

    medium_balance_gaps = gaps.get("medium_sample_balance")
    medium_balance_gaps = (
        medium_balance_gaps if isinstance(medium_balance_gaps, Mapping) else {}
    )
    for rank, (medium, raw_gap) in enumerate(sorted(medium_balance_gaps.items())):
        gap = raw_gap if isinstance(raw_gap, Mapping) else {}
        candidates = task_candidates(
            [str(item) for item in request.get("elements") or []],
            [str(medium)],
        )
        add_task(
            priority=1200 + rank,
            task_kind="medium_sample_balance_gap",
            scope_key=scope_key,
            view_id=f"medium:{medium}",
            elements=[str(item) for item in request.get("elements") or []],
            media=[str(medium)],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=["medium_independent_sample_capacity_shortfall"],
            observed={
                "unique_samples": int(gap.get("observed_unique_samples") or 0),
            },
            target={
                "minimum_unique_samples": int(gap.get("target_unique_samples") or 0),
                "additional_unique_samples": int(
                    gap.get("deficit_unique_samples") or 0
                ),
            },
            completion_evidence_required=[
                "positive source-scoped physical-sample delta for the requested medium",
                "new measurement rows must not be counted as new samples when sample identity is unchanged",
                "source URL/DOI, license, immutable version or acquisition hash and exact record locators",
                "same frozen request re-evaluated after the verified marginal data are integrated",
            ],
        )

    element_balance_gaps = gaps.get("element_sample_balance")
    element_balance_gaps = (
        element_balance_gaps if isinstance(element_balance_gaps, Mapping) else {}
    )
    for rank, (element, raw_gap) in enumerate(sorted(element_balance_gaps.items())):
        gap = raw_gap if isinstance(raw_gap, Mapping) else {}
        candidates = task_candidates(
            [str(element)],
            [str(item) for item in request.get("media") or []],
        )
        add_task(
            priority=1250 + rank,
            task_kind="element_sample_balance_gap",
            scope_key=scope_key,
            view_id=f"element:{element}",
            elements=[str(element)],
            media=[str(item) for item in request.get("media") or []],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=["element_independent_sample_capacity_shortfall"],
            observed={
                "unique_samples": int(gap.get("observed_unique_samples") or 0),
            },
            target={
                "minimum_unique_samples": int(gap.get("target_unique_samples") or 0),
                "additional_unique_samples": int(
                    gap.get("deficit_unique_samples") or 0
                ),
            },
            completion_evidence_required=[
                "positive source-scoped physical-sample delta for the requested element",
                "additional measurement rows from an existing physical sample do not count as new samples",
                "source URL/DOI, license, immutable version or acquisition hash and exact record locators",
                "same frozen request re-evaluated after the verified marginal data are integrated",
            ],
        )

    cell_balance_gaps = gaps.get("element_medium_sample_balance")
    cell_balance_gaps = (
        cell_balance_gaps if isinstance(cell_balance_gaps, Mapping) else {}
    )
    for rank, (cell, raw_gap) in enumerate(sorted(cell_balance_gaps.items())):
        if "|" not in str(cell):
            continue
        element, medium = str(cell).split("|", 1)
        gap = raw_gap if isinstance(raw_gap, Mapping) else {}
        candidates = task_candidates([element], [medium])
        add_task(
            priority=1300 + rank,
            task_kind="element_medium_sample_balance_gap",
            scope_key=scope_key,
            view_id=f"element_medium:{element}|{medium}",
            elements=[element],
            media=[medium],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=["element_medium_independent_sample_capacity_shortfall"],
            observed={
                "unique_samples": int(gap.get("observed_unique_samples") or 0),
            },
            target={
                "minimum_unique_samples": int(gap.get("target_unique_samples") or 0),
                "additional_unique_samples": int(
                    gap.get("deficit_unique_samples") or 0
                ),
            },
            completion_evidence_required=[
                "positive source-scoped physical-sample delta for this exact element and medium",
                "another element or medium cannot satisfy this filter-cell target",
                "source URL/DOI, license, immutable version or acquisition hash and exact record locators",
                "same frozen request re-evaluated after the verified marginal data are integrated",
            ],
        )

    metadata_gaps = [
        item
        for item in gaps.get("metadata_evidence_gaps") or []
        if isinstance(item, Mapping)
    ]
    for rank, gap in enumerate(metadata_gaps):
        medium = str(gap.get("medium") or "")
        source_id = str(gap.get("source_id") or "")
        missing_reason_counts = {
            str(code): int(count)
            for code, count in (gap.get("method_missing_reason_counts") or {}).items()
            if int(count) > 0
        }
        publisher_absent_only = bool(missing_reason_counts) and set(
            missing_reason_counts
        ).issubset(PUBLISHER_ABSENT_METHOD_REASON_CODES)
        source_lineage_id = str(gap.get("source_lineage_id") or source_id)
        if (
            source_id
            and source_id in viable_selected_source_ids
            and not publisher_absent_only
        ):
            candidates = {"selected": [source_id], "registered": [], "catalog": []}
        else:
            candidates = task_candidates(
                [str(item) for item in request.get("elements") or []],
                [medium] if medium else [],
                excluded_lineages={source_lineage_id}
                if publisher_absent_only and source_lineage_id
                else None,
            )
        add_task(
            priority=1500 + rank,
            task_kind="metadata_evidence_gap",
            scope_key=scope_key,
            view_id=(
                f"source:{source_id}|medium:{medium}"
                if source_id and medium
                else f"medium:{medium}"
                if medium
                else "overall"
            ),
            elements=[str(item) for item in request.get("elements") or []],
            media=[medium] if medium else [],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=[
                *[str(item) for item in gap.get("reason_codes") or []],
                *(
                    ["publisher_method_absence_requires_replacement_source"]
                    if publisher_absent_only
                    else []
                ),
            ],
            observed={
                "source_id": source_id or None,
                "source_lineage_id": gap.get("source_lineage_id"),
                "record_count": int(gap.get("record_count") or 0),
                "analytical_method_count": int(gap.get("analytical_method_count") or 0),
                "analytical_method_rate": float(
                    gap.get("analytical_method_rate") or 0.0
                ),
                "medium_record_share": float(gap.get("medium_record_share") or 0.0),
                "unique_samples": int(gap.get("unique_samples") or 0),
                "method_ready_unique_samples": int(
                    gap.get("method_ready_unique_samples") or 0
                ),
                "method_ready_lineage_count": int(
                    gap.get("method_ready_lineage_count") or 0
                ),
                "method_missing_reason_counts": missing_reason_counts,
                "publisher_absent_only": publisher_absent_only,
            },
            target={
                "minimum_analytical_method_rate": float(
                    gap.get("minimum_analytical_method_rate") or 0.0
                ),
                "minimum_method_ready_unique_samples": int(
                    gap.get("minimum_method_ready_unique_samples") or 0
                ),
                "minimum_method_ready_lineages": int(
                    gap.get("minimum_method_ready_lineages") or 0
                ),
            },
            completion_evidence_required=[
                (
                    "replacement lineage with observation-bound method evidence; the publisher-absent source remains in the screening archive and is never relabelled"
                    if publisher_absent_only
                    else "verified method documentation linked to each repaired observation or an explicit source-not-reported finding"
                ),
                (
                    "positive method-ready independent-sample delta from a different lineage or complete multi-family no-hit evidence"
                    if publisher_absent_only
                    else "positive method-evidence record delta or complete no-hit evidence for the attempted source"
                ),
                "no inferred analytical method, digestion or coordinate accuracy",
                "same frozen scientific request resumed under an auditable continuation strategy",
            ],
        )

    scientific_gaps = [
        item
        for item in gaps.get("scientific_evidence_gaps") or []
        if isinstance(item, Mapping)
    ]
    for rank, gap in enumerate(scientific_gaps):
        medium = str(gap.get("medium") or "")
        candidates = task_candidates(
            [str(item) for item in request.get("elements") or []],
            [medium] if medium else [],
        )
        add_task(
            priority=1600 + rank,
            task_kind="scientific_evidence_subset_gap",
            scope_key=scope_key,
            view_id=f"medium:{medium}" if medium else "overall",
            elements=[str(item) for item in request.get("elements") or []],
            media=[medium] if medium else [],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=[str(item) for item in gap.get("reason_codes") or []],
            observed={
                "unique_samples": int(gap.get("unique_samples") or 0),
                "scientific_ready_unique_samples": int(
                    gap.get("scientific_ready_unique_samples") or 0
                ),
                "scientific_ready_lineage_count": int(
                    gap.get("scientific_ready_lineage_count") or 0
                ),
            },
            target={
                "minimum_scientific_ready_unique_samples": int(
                    gap.get("minimum_scientific_ready_unique_samples") or 0
                ),
                "minimum_scientific_ready_lineages": int(
                    gap.get("minimum_scientific_ready_lineages") or 0
                ),
            },
            completion_evidence_required=[
                "quantitative standardized value and retained original value/unit",
                "canonical coordinate evidence with explicit accuracy disposition",
                "publisher-linked analytical method without inference",
                "publisher or labeled point-matched geological context",
                "record-to-file SHA-256 and official-source provenance validation",
                "QC disposition and a positive independent-sample delta for the requested medium",
            ],
        )

    source_link_gaps = [
        item for item in gaps.get("source_link_gaps") or [] if isinstance(item, Mapping)
    ]
    for rank, gap in enumerate(source_link_gaps):
        source_id = str(gap.get("source_id") or "")
        selected_candidates = (
            [source_id] if source_id in viable_selected_source_ids else []
        )
        add_task(
            priority=1600 + rank,
            task_kind="metadata_evidence_gap",
            scope_key=scope_key,
            view_id=f"source:{source_id}" if source_id else "source:unknown",
            elements=[str(item) for item in request.get("elements") or []],
            media=[str(item) for item in request.get("media") or []],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates={"selected": selected_candidates},
            repair_mode=(
                "requery_selected_source"
                if selected_candidates
                else "targeted_source_discovery"
            ),
            reason_codes=[str(item) for item in gap.get("reason_codes") or []],
            observed={
                "source_id": source_id,
                "record_count": int(gap.get("record_count") or 0),
                "official_linked_record_count": int(
                    gap.get("official_linked_record_count") or 0
                ),
                "official_link_count": int(gap.get("official_link_count") or 0),
            },
            target={
                "official_linked_record_rate": 1.0,
                "minimum_official_link_count": 1,
            },
            completion_evidence_required=[
                "official data-page, download URL or DOI verified for the represented source",
                "exact record-level source_locator retained separately",
                "license/version decision and downloaded-file hash remain bound in the source manifest",
                "same frozen scientific request resumed after the provenance repair",
            ],
        )

    missing_elements = sorted({str(item) for item in gaps.get("elements") or []})
    missing_media = sorted({str(item) for item in gaps.get("media") or []})
    missing_spatial_domains = sorted(
        {str(item) for item in gaps.get("spatial_domains") or []}
    )
    missing_cells = sorted(
        {str(item) for item in gaps.get("element_medium_cells") or []}
    )
    for rank, (task_kind, elements, media, view_id) in enumerate(
        [
            *(
                ("source_dimension_gap", [element], [], f"element:{element}")
                for element in missing_elements
            ),
            *(
                ("source_dimension_gap", [], [medium], f"medium:{medium}")
                for medium in missing_media
            ),
            *(
                (
                    "source_dimension_gap",
                    [],
                    [
                        medium
                        for medium in request.get("media") or []
                        if (domain == "land" or medium in {"sediment", "water"})
                    ],
                    f"spatial_domain:{domain}",
                )
                for domain in missing_spatial_domains
            ),
            *(
                (
                    "source_dimension_gap",
                    [cell.split("|", 1)[0]],
                    [cell.split("|", 1)[1]],
                    f"element_medium:{cell}",
                )
                for cell in missing_cells
                if "|" in cell
            ),
        ]
    ):
        candidates = task_candidates(elements, media)
        add_task(
            priority=3000 + rank,
            task_kind=task_kind,
            scope_key=scope_key,
            view_id=view_id,
            elements=elements,
            media=media,
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=[
                "requested_spatial_domain_not_observed"
                if view_id.startswith("spatial_domain:")
                else "requested_dimension_not_observed"
            ],
            observed={"compatible_executable_lineages": 0},
            target={"minimum_compatible_executable_lineages": 1},
        )

    lineage_deficit = int(gaps.get("independent_lineages") or 0)
    if lineage_deficit:
        candidates = task_candidates(
            [str(item) for item in request.get("elements") or []],
            [str(item) for item in request.get("media") or []],
            excluded_lineages=observed_lineage_ids,
        )
        add_task(
            priority=4000,
            task_kind="source_lineage_gap",
            scope_key=scope_key,
            view_id="overall",
            elements=[str(item) for item in request.get("elements") or []],
            media=[str(item) for item in request.get("media") or []],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=["independent_lineage_shortfall"],
            observed={"lineage_deficit": lineage_deficit},
            target={"additional_independent_lineages": lineage_deficit},
        )
    medium_lineages = gaps.get("medium_lineages")
    medium_lineages = medium_lineages if isinstance(medium_lineages, Mapping) else {}
    for rank, (medium, deficit) in enumerate(sorted(medium_lineages.items())):
        if int(deficit or 0) <= 0:
            continue
        excluded_medium_lineages = {
            str(item) for item in raw_medium_lineages.get(str(medium)) or []
        }
        candidates = task_candidates(
            [str(item) for item in request.get("elements") or []],
            [str(medium)],
            excluded_lineages=excluded_medium_lineages,
        )
        add_task(
            priority=4100 + rank,
            task_kind="medium_lineage_gap",
            scope_key=scope_key,
            view_id=f"medium:{medium}",
            elements=[str(item) for item in request.get("elements") or []],
            media=[str(medium)],
            bbox=scope_bbox,
            country={
                "country_iso_a3": scope_country,
                "country_name": scope_country_name,
                "macroregion": scope_macroregion,
            },
            source_candidates=candidates,
            repair_mode=candidate_repair_mode(candidates),
            reason_codes=["medium_lineage_shortfall"],
            observed={"lineage_deficit": int(deficit)},
            target={"additional_independent_lineages": int(deficit)},
        )

    tier_order = {
        "core": 0,
        "extended": 1,
        "macroregion_backfill": 2,
        "global_backfill": 3,
    }
    geographic = [
        item
        for item in gaps.get("geographic_search_targets") or []
        if isinstance(item, Mapping)
    ]
    geographic.sort(
        key=lambda item: (
            tier_order.get(str(item.get("priority_tier")), 9),
            -int(item.get("target_land_grid_cells") or 0),
            str(item.get("country_iso_a3") or ""),
        )
    )
    for rank, country in enumerate(geographic):
        add_task(
            priority=2000 + rank,
            task_kind="global_geographic_gap",
            scope_key="global",
            view_id="overall",
            elements=[str(item) for item in request.get("elements") or []],
            media=[str(item) for item in request.get("media") or []],
            bbox=[],
            country=country,
            repair_mode=str(country.get("repair_mode") or "targeted_source_discovery"),
            reason_codes=[str(item) for item in country.get("reason_codes") or []],
            observed={
                "canonical_unique_samples": int(
                    country.get("canonical_unique_samples") or 0
                ),
                "canonical_occupied_grid_cells": int(
                    country.get("canonical_occupied_grid_cells") or 0
                ),
            },
            target={
                "minimum_canonical_unique_samples": int(
                    country.get("minimum_canonical_unique_samples") or 0
                ),
                "minimum_canonical_occupied_grid_cells": int(
                    country.get("minimum_canonical_occupied_grid_cells") or 0
                ),
            },
        )

    tasks.sort(key=lambda item: (item["priority"], item["task_id"]))
    action_groups = build_d1_action_groups(tasks)
    execution_class_counts = {
        name: sum(1 for item in tasks if item["execution_class"] == name)
        for name in (
            "controller_rerun_current_skill",
            "data_action_current_skill",
            "evidence_audit_current_skill",
            "skill_maintenance_new_run",
        )
    }
    return {
        "queue_version": "d1-repair-queue-v3",
        "request_sha256": report.get("request_sha256"),
        "generated_from_round": last.get("round")
        if isinstance(last, Mapping)
        else None,
        "status": "pending" if tasks else "clear",
        "task_count": len(tasks),
        "action_group_count": len(action_groups),
        "unattempted_action_group_count": len(action_groups),
        "operator_continuation_required": bool(action_groups),
        "final_response_permitted": not bool(action_groups),
        "control_state": "continue_research" if action_groups else "queue_clear",
        "required_next_action": (
            "consume_next_action_group_and_resume_frozen_request"
            if action_groups
            else "validate_research_delivery"
        ),
        "execution_class_counts": execution_class_counts,
        "tasks": tasks,
        "action_groups": action_groups,
        "execution_rule": (
            "Process pending action_groups in priority order while the total budget remains. "
            "One action group may close many view-level tasks; write one attempt receipt with "
            "queries/platforms, source URL/DOI, licence/version decision and measured deltas before "
            "recomputing all member views. Try preferred_repair_mode then the remaining fallback chain; "
            "record real no-hit/license/access evidence before advancing. Accept and preserve "
            "every verified positive marginal delta even when one source cannot close the whole task; "
            "recompute the remaining debt after integration instead of rejecting a useful dataset for "
            "being individually insufficient. Data-only repairs "
            "resume the same output directory. If a task requires source discovery, catalog "
            "registration or adapter code, the queue does not itself authorize repository mutation: "
            "only when the original user scope authorizes Skill maintenance, finish and validate the "
            "change outside the active run, preserve the prior checkpoint, "
            "then restart the byte-identical scientific request in a new output directory with "
            "a continuation record linking both Skill hashes and checkpoint paths."
        ),
        "claim_boundary": (
            "The queue identifies observation/evidence gaps; it does not authorize interpolation, "
            "fabricated coordinates, threshold reduction or causal interpretation."
        ),
    }


def write_d1_repair_queue(
    loop_root: Path, report: Mapping[str, Any], request: Mapping[str, Any]
) -> dict[str, Any]:
    queue = build_d1_repair_queue(report, request)
    tasks = queue.get("tasks")
    action_groups = queue.get("action_groups")
    inconsistent_candidates = [
        item.get("task_id")
        for item in tasks or []
        if (
            item.get("preferred_repair_mode") == "requery_selected_source"
            and not item.get("selected_source_candidates")
        )
        or (
            item.get("preferred_repair_mode") == "route_registered_source"
            and not item.get("registered_source_candidates")
        )
        or (
            item.get("preferred_repair_mode") == "implement_catalog_candidate"
            and not item.get("catalog_candidate_source_ids")
        )
    ]
    if (
        not isinstance(tasks, list)
        or not isinstance(action_groups, list)
        or queue.get("task_count") != len(tasks)
        or queue.get("action_group_count") != len(action_groups)
        or queue.get("unattempted_action_group_count") != len(action_groups)
        or queue.get("operator_continuation_required") != bool(action_groups)
        or queue.get("final_response_permitted") != (not bool(action_groups))
        or queue.get("control_state")
        != ("continue_research" if action_groups else "queue_clear")
        or queue.get("required_next_action")
        != (
            "consume_next_action_group_and_resume_frozen_request"
            if action_groups
            else "validate_research_delivery"
        )
        or queue.get("status") != ("pending" if tasks else "clear")
        or len({str(item.get("task_id")) for item in tasks}) != len(tasks)
        or sum(int(value) for value in queue.get("execution_class_counts", {}).values())
        != len(tasks)
        or [int(item.get("priority") or 0) for item in tasks]
        != sorted(int(item.get("priority") or 0) for item in tasks)
        or [int(item.get("priority") or 0) for item in action_groups]
        != sorted(int(item.get("priority") or 0) for item in action_groups)
        or set(
            str(task_id)
            for group in action_groups
            for task_id in group.get("member_task_ids") or []
        )
        != {str(item.get("task_id")) for item in tasks}
        or inconsistent_candidates
    ):
        raise LoopUsageError(
            "generated D1 repair queue violates its deterministic contract"
        )
    write_json(loop_root / D1_REPAIR_QUEUE_FILENAME, queue)
    return queue


def decide_next(
    rounds: list[dict[str, Any]],
    max_rounds: int,
    elapsed_seconds: float,
    time_budget_seconds: float | None,
) -> tuple[str, str]:
    """Return ("continue" | "stop", stop_reason). Pure function, unit-tested."""
    last = rounds[-1]
    if last.get("gate_stop_reason"):
        return "stop", str(last["gate_stop_reason"])
    execution_status = last.get("execution_status")
    run_failed = last.get("exit_code") != 0
    if run_failed and not last.get("run_failure_retryable"):
        if execution_status == "needs_human_review":
            return "stop", "needs_human_review"
        return "stop", "run_failed"
    if not run_failed and last.get("validation_status") == "invalid":
        return "stop", "contract_validation_failed"
    plan = build_repair_plan(last)
    has_autonomous = bool(plan["autonomous"])
    action_required = last.get("counts", {}).get("action_required")
    open_failures = bool(last.get("failed_sources"))
    sufficient = (last.get("sufficiency") or {}).get("status") != "insufficient"
    if (
        not run_failed
        and not open_failures
        and action_required in (0, None)
        and sufficient
    ):
        return "stop", "converged"
    if not has_autonomous:
        if not sufficient:
            return "stop", "repair_queue_pending"
        return "stop", "no_autonomous_repair"
    previous = rounds[-2] if len(rounds) >= 2 else None
    if previous is not None:
        previous_target = (previous.get("acquisition_target") or {}).get(
            "per_analyte_observations"
        )
        current_target = (last.get("acquisition_target") or {}).get(
            "per_analyte_observations"
        )
        if (
            isinstance(previous_target, int)
            and isinstance(current_target, int)
            and current_target > previous_target
            and acquisition_progress_signature(previous)
            == acquisition_progress_signature(last)
        ):
            return "stop", "no_progress"
    if (
        previous is not None
        and actionable_signature(previous) == actionable_signature(last)
        and not (last.get("sufficiency") or {}).get("can_expand_acquisition")
    ):
        return "stop", "no_progress"
    if len(rounds) >= max_rounds:
        return "stop", "round_budget_exhausted"
    if time_budget_seconds is not None and elapsed_seconds >= time_budget_seconds:
        return "stop", "time_budget_exhausted"
    return "continue", ""


PROBE_STOP_REASONS = (
    "no_autonomous_repair",
    "no_progress",
    "repair_queue_pending",
)


def allow_probe_round(
    resumed: bool,
    probe_used: bool,
    stop_reason: str,
    rounds: list[dict[str, Any]],
    max_rounds: int,
) -> bool:
    """Return True when a resumed controller may run one probe round.

    Pure function, unit-tested. Every reason in ``PROBE_STOP_REASONS`` tells
    the operator to repair sources or evidence outside the loop and re-run in
    the same directory; the probe round is how the controller observes that
    repair instead of restating the stale verdict. ``repair_queue_pending`` is
    included so a newly adapted or newly cached source (for example a
    previously failed lineage) can be retried; a fresh invocation still fails
    closed because ``resumed`` is False, and one probe per invocation keeps a
    no-op resume from spinning.
    """
    return (
        resumed
        and not probe_used
        and stop_reason in PROBE_STOP_REASONS
        and len(rounds) < max_rounds
        and not is_gate_round(rounds[-1])
    )


def final_status(stop_reason: str, last: dict[str, Any] | None) -> str:
    if stop_reason == "converged" and last is not None:
        return (
            "success"
            if last.get("execution_status") == "success"
            else "partial_success"
        )
    if stop_reason in (
        "round_budget_exhausted",
        "time_budget_exhausted",
        "repair_queue_pending",
    ):
        # A schema-valid checkpoint is still not a completed research result
        # when the explicit sufficiency gate failed. Returning exit 0 here was
        # the reason thin 296/1328-row runs were mistaken for completion.
        return "needs_human_review"
    if stop_reason in ("run_failed", "invalid_input"):
        return "failed"
    return "needs_human_review"


def next_step_text(
    stop_reason: str,
    plan: dict[str, Any],
    *,
    mode: str,
    checkpoint_only: bool,
) -> str:
    manual_count = sum(item.get("count", 1) for item in plan.get("manual", []))
    queue_instruction = (
        f"读取 {D1_REPAIR_QUEUE_FILENAME}，按 priority 逐项执行首选动作及 fallback chain，"
        "记录真实尝试证据后在同一冻结请求与输出目录续跑。"
    )
    if stop_reason == "converged":
        if mode == "demo":
            return (
                "演示工作流已收敛，但 fixture 只证明可复现执行，不是本次在线研究交付；"
                f"当前仍有 {manual_count} 项建议研究队列。正式任务必须改用 online 模式，"
                "处理动态空间/来源缺口并通过 validate_research_delivery.py。"
            )
        if mode == "input":
            return (
                "外部输入处理已收敛，但未证明 D1 在线采集和来源覆盖；可作为输入数据产物，"
                "不得标作完整在线研究交付。正式任务需补齐 D1 证据并通过"
                " validate_research_delivery.py。"
            )
        if checkpoint_only:
            return (
                "在线检查点已收敛，但 --checkpoint-only 明确禁止正式交付；在同一输出目录"
                "恢复完整预算，随后运行 validate_research_delivery.py。"
            )
        if manual_count:
            return (
                f"自动循环已收敛但仍有 {manual_count} 项研究队列；{queue_instruction}"
                "队列清空且 validate_research_delivery.py 通过前不得宣称完成。"
            )
        return (
            "自动循环已收敛；运行 validate_research_delivery.py，只有"
            " research_delivery_receipt.json.delivery_ready=true 时才按 SKILL.md 第 8 节"
            "输出正式回复。"
        )
    mapping = {
        "no_autonomous_repair": (
            f"存在 {manual_count} 项需证据或人工判断的问题；{queue_instruction}"
            "非 D1 项再按 repair_plan.manual 补 schema map 或人工复核。"
        ),
        "no_progress": f"连续两轮问题签名相同；停止无目标重试。{queue_instruction}",
        "repair_queue_pending": (
            "数据充分性门禁未通过，且存在尚未执行的结构化 D1 修复动作；"
            f"{queue_instruction}"
            "禁止把控制器返回当作任务结束；Agent 必须在剩余任务预算内消费 action_groups，"
            "每组写尝试回执并续跑。当前目录仅为 needs_human_review 检查点，"
            "不是正式研究交付。"
        ),
        "round_budget_exhausted": "轮次预算用尽；如任务预算允许，提高 --max-rounds 在同一目录续跑。",
        "time_budget_exhausted": (
            f"声明的累计时间预算用尽；保留检查点并审计 {D1_REPAIR_QUEUE_FILENAME}，"
            "不得通过重启目录规避总时限或宣称已完成。"
        ),
        "needs_human_review": "流水线返回 needs_human_review；按 run_summary.json 与失败矩阵处理后续跑。",
        "contract_validation_failed": (
            "产物违反十六文件契约；这是工程缺陷，勿盲目重试，检查 validate_outputs 输出并修复代码或输入。"
        ),
        "run_failed": "非瞬态运行失败；按 stderr 状态码与 SKILL.md 第 8 节失败矩阵处理。",
        "unsupported_scope": "路由无任何候选来源；调整请求（元素/介质/区域/许可政策）或改用 --input 提供数据。",
        "invalid_input": "输入缺少最低必需列；按 D2 契约修正输入文件后重跑。",
        "in_progress": "循环在本轮后中断；在同一输出目录重新调用控制器续跑。",
    }
    return mapping.get(
        stop_reason, "查看 loop_report.json 与最后一轮 run_summary.json。"
    )


def build_run_command(
    args: argparse.Namespace,
    round_dir: Path,
    round_index: int,
    priority_source_ids: Sequence[str] = (),
) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "run_atlas_request.py"),
        "--request",
        str(args.request),
        "--output-dir",
        str(round_dir),
        "--analysis-profile",
        args.analysis_profile,
    ]
    if args.mode == "input":
        command.extend(["--input", str(args.input)])
        if args.evidence_jsonl:
            command.extend(["--evidence-jsonl", str(args.evidence_jsonl)])
        if args.acquisition_manifest:
            command.extend(["--acquisition-manifest", str(args.acquisition_manifest)])
    elif args.mode == "online":
        target = acquisition_target(args, round_index)
        command.extend(
            [
                "--online-source",
                args.online_source,
                "--controller-round",
                "--cache-dir",
                str(args.cache_dir),
                "--acquisition-mode",
                args.acquisition_mode,
                "--per-analyte-observations",
                str(target),
                "--source-timeout-seconds",
                str(args.source_timeout_seconds),
                "--source-order-offset",
                str(source_order_offset(round_index)),
            ]
        )
        for source_id in priority_source_ids:
            command.extend(["--priority-source-id", str(source_id)])
    else:
        command.extend(["--demo", args.demo])
    if args.generated_at:
        command.extend(["--generated-at", args.generated_at])
    if args.batch_qc_input:
        command.extend(["--batch-qc-input", str(args.batch_qc_input)])
    if args.batch_qc_policy:
        command.extend(["--batch-qc-policy", str(args.batch_qc_policy)])
    if args.no_geology:
        command.append("--no-geology")
    command.extend(
        [
            "--coordinate-mode",
            args.coordinate_mode,
            "--total-timeout-seconds",
            str(args.run_timeout_seconds),
            "--workflow-reserve-seconds",
            str(min(180.0, args.run_timeout_seconds * 0.1)),
        ]
    )
    if args.require_all_sources:
        command.append("--require-all-sources")
    return command


def run_pre_gates(args: argparse.Namespace, round_index: int) -> dict[str, Any] | None:
    """Run cheap viability gates before spending a full round.

    Returns a terminal gate-round record on failure, or None when execution
    may proceed. Gates are conservative: uncertainty defers to the pipeline.
    """
    if args.mode == "online":
        viable, detail = gate_routing(args.request)
        if not viable:
            return make_gate_round(
                round_index,
                args,
                "routing_viability",
                detail,
                GATE_STOP_REASONS["routing_viability"],
            )
    elif args.mode == "input":
        viable, detail = gate_input_header(args.input)
        if not viable:
            return make_gate_round(
                round_index,
                args,
                "input_header",
                detail,
                GATE_STOP_REASONS["input_header"],
            )
    return None


def gate_routing(request: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        route_path = Path(tmp) / "route.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "source_router.py"),
                "--request",
                str(request),
                "--output",
                str(route_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not route_path.is_file():
            return True, "router unavailable; deferring to the pipeline's own routing"
        try:
            route = read_json(route_path)
        except (OSError, json.JSONDecodeError):
            return True, "route result unreadable; deferring to the pipeline"
    selected = len(route.get("selected_sources") or [])
    review = len(route.get("review_sources") or [])
    if selected == 0:
        return (
            False,
            f"router selected 0 executable sources ({review} review candidates); source discovery/adaptation is required before acquisition",
        )
    return True, f"router found {selected} selected and {review} review-tier sources"


def gate_input_header(input_path: Path) -> tuple[bool, str]:
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except OSError as exc:
        return False, f"input unreadable: {exc}"
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in header]
    if missing:
        return False, f"input is missing required columns: {missing}"
    return True, "minimum D2 columns present"


def execute_round(
    args: argparse.Namespace,
    round_index: int,
    loop_root: Path,
    priority_source_ids: Sequence[str] = (),
) -> dict[str, Any]:
    round_dir = loop_root / "rounds" / f"round-{round_index:02d}"
    command = build_run_command(
        args, round_dir, round_index, priority_source_ids=priority_source_ids
    )
    gate_events: list[dict[str, str]] = []
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=getattr(
                args, "active_round_timeout_seconds", args.round_timeout_seconds
            ),
            check=False,
        )
        exit_code: int | None = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = None

        def _decode(stream: Any) -> str:
            if isinstance(stream, bytes):
                return stream.decode("utf-8", "replace")
            return stream or ""

        stdout, stderr = _decode(exc.stdout), _decode(exc.stderr)
    duration = round(time.monotonic() - started, 1)

    execution_status: str | None = None
    route_status: str | None = None
    records: int | None = None
    failed_sources: list[dict[str, Any]] = []
    receipt: dict[str, Any] = {}
    if exit_code == 0:
        receipt = parse_last_json_line(stdout) or {}
        execution_status = receipt.get("status")
        route_status = receipt.get("route_status")
        records = (receipt.get("record_counts") or {}).get("after_request_filters")
        for outcome in receipt.get("source_outcomes") or []:
            if outcome.get("status") != "failed":
                continue
            error = str(outcome.get("error") or "")
            failed_sources.append(
                {
                    "source_id": str(outcome.get("source_id")),
                    "error": error,
                    "retryable": source_failure_retryable(error),
                }
            )
        gate_events.append(
            {
                "gate": "run_exit",
                "status": "pass",
                "detail": f"exit 0, status {execution_status}",
            }
        )
    elif exit_code is None:
        execution_status = "round_timeout"
        gate_events.append(
            {
                "gate": "run_exit",
                "status": "info",
                "detail": (
                    "round killed after "
                    f"{getattr(args, 'active_round_timeout_seconds', args.round_timeout_seconds):.0f}s; "
                    "classified retryable"
                ),
            }
        )
    else:
        failure = parse_last_json_line(stderr) or {}
        execution_status = str(failure.get("status") or "invalid_input")
        for outcome in failure.get("source_outcomes") or []:
            if not isinstance(outcome, Mapping) or outcome.get("status") != "failed":
                continue
            error = str(outcome.get("error") or "")
            failed_sources.append(
                {
                    "source_id": str(outcome.get("source_id")),
                    "error": error,
                    "retryable": source_failure_retryable(error),
                }
            )
        gate_events.append(
            {
                "gate": "run_exit",
                "status": "info",
                "detail": (
                    f"exit {exit_code}, status {execution_status}: {str(failure.get('error') or '')[:200]}"
                ),
            }
        )

    if exit_code != 0 and not failed_sources:
        for filename in ("execution_failure.json", "execution_progress.json"):
            evidence_path = round_dir / "request_evidence" / filename
            if not evidence_path.is_file():
                continue
            try:
                persisted = read_json(evidence_path)
            except (OSError, json.JSONDecodeError):
                continue
            nested = persisted.get("evidence")
            outcomes = (
                nested.get("source_outcomes")
                if isinstance(nested, Mapping)
                else persisted.get("source_outcomes")
            )
            for outcome in outcomes or []:
                if (
                    not isinstance(outcome, Mapping)
                    or outcome.get("status") != "failed"
                ):
                    continue
                error = str(outcome.get("error") or "")
                failed_sources.append(
                    {
                        "source_id": str(outcome.get("source_id")),
                        "error": error,
                        "retryable": source_failure_retryable(error),
                    }
                )
            if failed_sources:
                break

    validation_status = "not_run"
    validation_warnings: int | None = None
    if exit_code == 0:
        validation = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "validate_outputs.py"),
                "--output-dir",
                str(round_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        validation_report = parse_last_json_line(validation.stdout) or {}
        validation_status = "valid" if validation.returncode == 0 else "invalid"
        warnings = validation_report.get("warnings")
        validation_warnings = len(warnings) if isinstance(warnings, list) else None
        gate_events.append(
            {
                "gate": "output_validation",
                "status": "pass" if validation_status == "valid" else "stop",
                "detail": f"validate_outputs: {validation_status}",
            }
        )

    backlog = read_backlog(round_dir / "iteration_backlog.csv")
    analyzed_groups, insufficient_groups, candidates = read_anomaly_groups(
        round_dir / "anomaly_report.json"
    )
    gate_events.append(
        {
            "gate": "issue_harvest",
            "status": "info",
            "detail": (
                f"action_required={backlog['status_counts'].get('action_required', 0)}, "
                f"failed_sources={len(failed_sources)}, "
                f"insufficient_background_groups={insufficient_groups}"
            ),
        }
    )

    sufficiency: dict[str, Any] | None = None
    current_target = acquisition_target(args, round_index)
    if exit_code == 0 and validation_status == "valid":
        try:
            request = args.normalized_request
            sufficiency = assess_sufficiency(
                round_dir, request, receipt, args.mode, current_target, args
            )
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            sufficiency = {
                "assessment_version": SUFFICIENCY_VERSION,
                "status": "insufficient",
                "criteria": {},
                "unmet_required_criteria": ["assessment_unavailable"],
                "acquisition_repairable_criteria": [],
                "acquisition_blocking_criteria": ["assessment_unavailable"],
                "discovery_gaps": {
                    "viable_selected_source_ids": [],
                    "observed_source_ids": [],
                    "observed_lineage_ids": [],
                    "observed_lineage_ids_by_medium": {},
                    "elements": [],
                    "media": [],
                    "spatial_domains": [],
                    "element_medium_cells": [],
                    "independent_lineages": 0,
                    "medium_lineages": {},
                    "macroregions_below_minimum": [],
                    "priority_countries_below_minimum": [],
                    "macroregions_below_grid_minimum": [],
                    "geographic_search_targets": [],
                    "regional_spatial_gap": None,
                    "spatial_dimension_gaps": [],
                },
                "reporting_facts": {
                    "measurement_records": 0,
                    "required_measurement_records": 0,
                    "measurement_record_shortfall_factor": None,
                    "independent_samples": 0,
                    "required_independent_samples": 0,
                    "independent_sample_shortfall_factor": None,
                    "quality_dimension_band_counts": {},
                    "single_quality_label_prohibited": True,
                },
                "can_expand_acquisition": False,
                "current_per_analyte_observations": current_target,
                "next_per_analyte_observations": None,
                "claim_boundary": f"Sufficiency assessment failed closed: {exc}",
            }
        gate_events.append(
            {
                "gate": "data_sufficiency",
                "status": "pass" if sufficiency["status"] == "sufficient" else "info",
                "detail": (
                    f"status={sufficiency['status']}; unmet="
                    f"{sufficiency['unmet_required_criteria']}; "
                    f"can_expand={sufficiency['can_expand_acquisition']}"
                ),
            }
        )

    # Include validation and sufficiency assessment in the persisted round
    # duration so a resumed controller cannot reset the 12-hour total budget.
    duration = round(time.monotonic() - started, 1)

    return {
        "round": round_index,
        "output_dir": str(round_dir),
        "command": [Path(command[0]).name] + command[1:],
        "exit_code": exit_code,
        "execution_status": execution_status,
        "route_status": route_status,
        "validation_status": validation_status,
        "duration_seconds": duration,
        "input_fingerprints": {
            "request_sha256": args.request_sha256,
            "input_sha256": sha256_file(args.input) if args.mode == "input" else None,
            "evidence_sha256": (
                sha256_file(args.evidence_jsonl)
                if args.mode == "input" and args.evidence_jsonl
                else None
            ),
        },
        "counts": {
            "records": records,
            "action_required": (
                backlog["status_counts"].get("action_required", 0)
                if backlog["available"]
                else None
            ),
            "review_required": (
                backlog["status_counts"].get("review_required", 0)
                if backlog["available"]
                else None
            ),
            "scientific_limit": (
                backlog["status_counts"].get("scientific_limit", 0)
                if backlog["available"]
                else None
            ),
            "auto_recheck": backlog["auto_recheck"],
            "failed_sources": len(failed_sources),
            "insufficient_background_groups": insufficient_groups,
            "analyzed_background_groups": analyzed_groups,
            "candidate_anomalies": candidates,
            "validation_warnings": validation_warnings,
        },
        "issue_codes": backlog["issue_codes"],
        "acquisition_target": {
            "per_analyte_observations": current_target,
            "maximum_per_analyte_observations": args.max_per_analyte_observations,
        },
        "sufficiency": sufficiency,
        "failed_sources": failed_sources,
        "gate_events": gate_events,
        "delta_vs_previous": None,
        # Controller-internal fields, stripped by public_round() before writing:
        "manual_groups": backlog["manual_groups"],
        "run_failure_retryable": exit_code != 0
        and run_failure_retryable(execution_status, args.mode),
        "gate_stop_reason": None,
    }


def make_gate_round(
    round_index: int, args: argparse.Namespace, gate: str, detail: str, stop_reason: str
) -> dict[str, Any]:
    return {
        "round": round_index,
        "output_dir": "",
        "command": [],
        "exit_code": None,
        "execution_status": None,
        "route_status": None,
        "validation_status": "not_run",
        "duration_seconds": 0.0,
        "input_fingerprints": {
            "request_sha256": args.request_sha256,
            "input_sha256": None,
            "evidence_sha256": None,
        },
        "counts": {
            "records": None,
            "action_required": None,
            "review_required": None,
            "scientific_limit": None,
            "auto_recheck": None,
            "failed_sources": 0,
            "insufficient_background_groups": None,
            "analyzed_background_groups": None,
            "candidate_anomalies": None,
            "validation_warnings": None,
        },
        "issue_codes": {},
        "acquisition_target": {
            "per_analyte_observations": acquisition_target(args, round_index),
            "maximum_per_analyte_observations": args.max_per_analyte_observations,
        },
        "sufficiency": None,
        "failed_sources": [],
        "gate_events": [{"gate": gate, "status": "stop", "detail": detail}],
        "delta_vs_previous": None,
        "manual_groups": [],
        "run_failure_retryable": False,
        "gate_stop_reason": stop_reason,
    }


def public_round(record: dict[str, Any]) -> dict[str, Any]:
    """Strip controller-internal fields before writing the schema-bound report."""
    internal = ("manual_groups", "run_failure_retryable", "gate_stop_reason")
    return {key: value for key, value in record.items() if key not in internal}


def rehydrate_round(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Rebuild controller-internal fields for rounds loaded from a report."""
    hydrated = dict(record)
    hydrated["run_failure_retryable"] = record.get(
        "exit_code"
    ) != 0 and run_failure_retryable(record.get("execution_status"), mode)
    hydrated["gate_stop_reason"] = None
    if is_gate_round(record):
        for event in record.get("gate_events", []):
            if event.get("status") == "stop" and event.get("gate") in GATE_STOP_REASONS:
                hydrated["gate_stop_reason"] = GATE_STOP_REASONS[str(event.get("gate"))]
    output_dir = record.get("output_dir") or ""
    backlog_path = Path(output_dir) / "iteration_backlog.csv" if output_dir else None
    if backlog_path is not None and backlog_path.is_file():
        hydrated["manual_groups"] = read_backlog(backlog_path)["manual_groups"]
    else:
        hydrated["manual_groups"] = []
    return hydrated


def compute_delta(rounds: list[dict[str, Any]]) -> None:
    if len(rounds) < 2:
        return
    current, previous = rounds[-1], rounds[-2]
    if is_gate_round(current):
        return
    current_counts = current.get("counts", {})
    previous_counts = previous.get("counts", {})

    def diff(key: str) -> int | None:
        now, before = current_counts.get(key), previous_counts.get(key)
        if isinstance(now, int) and isinstance(before, int):
            return now - before
        return None

    current["delta_vs_previous"] = {
        "action_required": diff("action_required"),
        "failed_sources": diff("failed_sources"),
    }


def assemble_report(
    args: argparse.Namespace, rounds: list[dict[str, Any]], stop_reason: str
) -> dict[str, Any]:
    executed = [item for item in rounds if not is_gate_round(item)]
    last = executed[-1] if executed else None
    plan = build_repair_plan(last) if last else {"autonomous": [], "manual": []}
    return {
        "schema_version": REPORT_VERSION,
        "request_path": str(args.request),
        "request_sha256": args.request_sha256,
        "mode": args.mode,
        "analysis_profile": args.analysis_profile,
        "checkpoint_only": bool(args.checkpoint_only),
        "max_rounds": args.max_rounds,
        "time_budget_seconds": args.time_budget_seconds,
        "published_round": next(
            (
                int(item["round"])
                for item in reversed(rounds)
                if item.get("exit_code") == 0
                and item.get("validation_status") == "valid"
            ),
            None,
        ),
        "published_output_dir": str(args.output_dir),
        "rounds": [public_round(item) for item in rounds],
        "repair_plan": plan,
        "stop_reason": stop_reason,
        "status": final_status(stop_reason, last),
        "next_step": next_step_text(
            stop_reason,
            plan,
            mode=str(args.mode),
            checkpoint_only=bool(args.checkpoint_only),
        ),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def load_previous_rounds(loop_root: Path, request_sha256: str) -> list[dict[str, Any]]:
    report_path = loop_root / REPORT_FILENAME
    if not report_path.is_file():
        return []
    previous = read_json(report_path)
    previous_version = str(previous.get("schema_version") or "")
    if previous_version != REPORT_VERSION:
        raise LoopUsageError(
            f"cannot resume {previous_version} in place with {REPORT_VERSION}; "
            "start a new output directory with the same frozen request so current "
            "sufficiency and repair-queue semantics are recomputed"
        )
    if previous.get("request_sha256") != request_sha256:
        raise LoopUsageError(
            "frozen request changed between invocations; start a new output directory"
        )
    rounds = previous.get("rounds")
    if not isinstance(rounds, list):
        return []
    mode = str(previous.get("mode") or "demo")
    return [rehydrate_round(item, mode) for item in rounds]


def needs_current_sufficiency_probe(rounds: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether a resumed loop must replace stale/absent assessment facts."""

    last = next(
        (item for item in reversed(rounds) if not is_gate_round(item)),
        None,
    )
    if last is None:
        return False
    sufficiency = last.get("sufficiency")
    discovery_gaps = (
        sufficiency.get("discovery_gaps") if isinstance(sufficiency, Mapping) else None
    )
    return (
        not isinstance(sufficiency, Mapping)
        or sufficiency.get("assessment_version") != SUFFICIENCY_VERSION
        or not isinstance(discovery_gaps, Mapping)
        or not D1_QUEUE_CANDIDATE_FACT_KEYS.issubset(discovery_gaps)
    )


def publish_latest_valid_round(
    loop_root: Path, rounds: Sequence[dict[str, Any]]
) -> int | None:
    """Expose the latest valid sixteen-file bundle at the requested output root.

    Immutable round directories remain the audit history.  The root-level
    files are a convenience publication view required by prompts that expect
    ``./output/interactive_map.html`` and sibling deliverables.
    """

    selected = next(
        (
            item
            for item in reversed(rounds)
            if item.get("exit_code") == 0
            and item.get("validation_status") == "valid"
            and item.get("output_dir")
        ),
        None,
    )
    if selected is None:
        return None
    source = Path(str(selected["output_dir"]))
    for child in source.iterdir():
        destination = loop_root / child.name
        if child.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(child, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(child, destination)
    return int(selected["round"])


def write_research_delivery_receipt(
    loop_root: Path,
    report: Mapping[str, Any],
    rounds: Sequence[Mapping[str, Any]],
    queue: Mapping[str, Any],
) -> None:
    """Bind the root publication to one immutable validated loop round."""

    published_round = report.get("published_round")
    selected = next(
        (item for item in rounds if item.get("round") == published_round), None
    )
    if selected is None:
        return
    round_dir = Path(str(selected.get("output_dir") or ""))
    artifacts: dict[str, dict[str, str]] = {}
    for filename in output_validator.REQUIRED_FILES.values():
        root_path = loop_root / filename
        round_path = round_dir / filename
        if not root_path.is_file() or not round_path.is_file():
            continue
        artifacts[filename] = {
            "root_sha256": sha256_file(root_path),
            "round_sha256": sha256_file(round_path),
        }
    sufficiency = selected.get("sufficiency") or {}
    execution_path = loop_root / "request_evidence" / "execution.json"
    execution_mode = None
    execution_skill_snapshot: Mapping[str, Any] = {}
    if execution_path.is_file():
        try:
            execution = read_json(execution_path)
            execution_mode = execution.get("mode")
            raw_snapshot = execution.get("skill_snapshot")
            if isinstance(raw_snapshot, Mapping):
                execution_skill_snapshot = raw_snapshot
        except (OSError, json.JSONDecodeError):
            execution_mode = None
    try:
        current_skill_snapshot = skill_snapshot.fingerprint_skill_tree(SKILL_DIR)
    except (OSError, skill_snapshot.SkillSnapshotError):
        current_skill_snapshot = {}
    expected_skill_sha256 = execution_skill_snapshot.get("end_sha256")
    current_skill_sha256 = current_skill_snapshot.get("sha256")
    stable_execution_skill = (
        execution_skill_snapshot.get("stable_during_execution") is True
        and isinstance(expected_skill_sha256, str)
        and expected_skill_sha256 == current_skill_sha256
    )
    delivery_ready = (
        selected.get("validation_status") == "valid"
        and sufficiency.get("status") == "sufficient"
        and str(execution_mode or "").startswith("online_")
        and report.get("stop_reason") == "converged"
        and report.get("status") in ("success", "partial_success")
        and report.get("checkpoint_only") is not True
        and queue.get("status") == "clear"
        and stable_execution_skill
        and len(artifacts) == len(output_validator.REQUIRED_FILES)
        and all(
            item["root_sha256"] == item["round_sha256"] for item in artifacts.values()
        )
    )
    control_files = {
        "loop_report_sha256": sha256_file(loop_root / REPORT_FILENAME),
        "d1_repair_queue_sha256": sha256_file(loop_root / D1_REPAIR_QUEUE_FILENAME),
        "execution_sha256": (
            sha256_file(execution_path) if execution_path.is_file() else None
        ),
    }
    write_json(
        loop_root / RESEARCH_RECEIPT_FILENAME,
        {
            "schema_version": "atlas-research-delivery-receipt-v3",
            "request_sha256": report.get("request_sha256"),
            "published_round": published_round,
            "published_round_dir": f"rounds/round-{int(published_round):02d}",
            "loop_status": report.get("status"),
            "loop_stop_reason": report.get("stop_reason"),
            "sufficiency_status": sufficiency.get("status"),
            "execution_mode": execution_mode,
            "checkpoint_only": report.get("checkpoint_only") is True,
            "d1_repair_queue_status": queue.get("status"),
            "control_files": control_files,
            "skill_snapshot": {
                "algorithm": current_skill_snapshot.get("algorithm"),
                "execution_sha256": expected_skill_sha256,
                "current_sha256": current_skill_sha256,
                "matches_execution": stable_execution_skill,
                "file_count": current_skill_snapshot.get("file_count"),
                "total_bytes": current_skill_snapshot.get("total_bytes"),
            },
            "delivery_ready": delivery_ready,
            "artifacts": artifacts,
            "claim_boundary": (
                "delivery_ready binds a validated online loop round, a clear D1 repair queue, "
                "the stable executable Skill snapshot and its sufficiency gate; "
                "it does not claim national/global statistical representativeness."
            ),
        },
    )


def run_loop(args: argparse.Namespace) -> dict[str, Any]:
    loop_root = args.output_dir
    loop_root.mkdir(parents=True, exist_ok=True)
    rounds = load_previous_rounds(loop_root, args.request_sha256)
    resumed = bool(rounds)
    started = time.monotonic()
    prior_elapsed = persisted_elapsed_seconds(rounds)

    force_execute = resumed and needs_current_sufficiency_probe(rounds)
    if not resumed:
        gate_failure = run_pre_gates(args, 1)
        if gate_failure is not None:
            rounds.append(gate_failure)
    elif is_gate_round(rounds[-1]):
        gate_failure = run_pre_gates(args, len(rounds) + 1)
        if gate_failure is not None:
            rounds.append(gate_failure)
        else:
            force_execute = True

    probe_used = False
    stop_reason = "in_progress"
    while True:
        if rounds and not force_execute:
            action, stop_reason = decide_next(
                rounds,
                args.max_rounds,
                prior_elapsed + (time.monotonic() - started),
                args.time_budget_seconds,
            )
            if action == "stop":
                if not allow_probe_round(
                    resumed, probe_used, stop_reason, rounds, args.max_rounds
                ):
                    break
                probe_used = True
        force_execute = False
        if len(rounds) >= args.max_rounds:
            stop_reason = "round_budget_exhausted"
            break
        if args.time_budget_seconds is not None:
            remaining = args.time_budget_seconds - (
                prior_elapsed + (time.monotonic() - started)
            )
            if remaining < 1:
                stop_reason = "time_budget_exhausted"
                break
            args.active_round_timeout_seconds = min(
                args.round_timeout_seconds, remaining
            )
        previous_executed = next(
            (item for item in reversed(rounds) if not is_gate_round(item)), None
        )
        selected_target = args.per_analyte_observations
        if previous_executed is not None:
            selected_target = int(
                (previous_executed.get("acquisition_target") or {}).get(
                    "per_analyte_observations", selected_target
                )
            )
            previous_sufficiency = previous_executed.get("sufficiency") or {}
            if previous_sufficiency.get("can_expand_acquisition"):
                selected_target = int(
                    previous_sufficiency.get("next_per_analyte_observations")
                    or selected_target
                )
        args.active_per_analyte_observations = selected_target
        priority_source_ids = next_round_priority_source_ids(previous_executed)
        if previous_executed is None and not priority_source_ids:
            # Round 1 starts from cross-run memory instead of starting blind.
            priority_source_ids = [str(s) for s in args.seed_priority_source_id]
        record = execute_round(
            args,
            len(rounds) + 1,
            loop_root,
            priority_source_ids=priority_source_ids,
        )
        rounds.append(record)
        compute_delta(rounds)
        interim_report = assemble_report(args, rounds, "in_progress")
        write_json(loop_root / REPORT_FILENAME, interim_report)
        write_d1_repair_queue(loop_root, interim_report, args.normalized_request)

    publish_latest_valid_round(loop_root, rounds)
    report = assemble_report(args, rounds, stop_reason)
    write_json(loop_root / REPORT_FILENAME, report)
    queue = write_d1_repair_queue(loop_root, report, args.normalized_request)
    write_research_delivery_receipt(loop_root, report, rounds, queue)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic self-correction loop around run_atlas_request.py: "
            "early gates, safe autonomous retries, honest convergence. "
            "Exit codes: 0 success/partial_success, 1 needs_human_review, 2 failed/usage."
        )
    )
    parser.add_argument(
        "--request", type=Path, help="Frozen request JSON (required unless --self-test)"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Loop root; rounds live in rounds/round-NN"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--input", type=Path, help="Existing D1 CSV to process")
    mode.add_argument("--online-source", help="Routed source ID or 'auto'")
    mode.add_argument(
        "--demo",
        choices=("production-usgs", "four-media", "china"),
        help="Explicit deterministic demo fixture; omitted means online-source auto",
    )
    parser.add_argument("--evidence-jsonl", type=Path)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/data"))
    parser.add_argument(
        "--acquisition-mode", choices=("online", "cached"), default="online"
    )
    parser.add_argument(
        "--coordinate-mode",
        choices=("auto", "canonical", "reported"),
        default="auto",
        help="Coordinate policy passed to the request runner (default: auto)",
    )
    parser.add_argument(
        "--per-analyte-observations",
        type=int,
        default=DEFAULT_PER_ANALYTE_OBSERVATIONS,
        help="Initial per-analyte acquisition target (default: 512)",
    )
    parser.add_argument(
        "--max-per-analyte-observations",
        type=int,
        default=DEFAULT_MAX_PER_ANALYTE_OBSERVATIONS,
        help="Largest per-analyte target reached by the sufficiency loop (default: 200000)",
    )
    parser.add_argument(
        "--acquisition-growth-factor",
        type=float,
        default=DEFAULT_ACQUISITION_GROWTH,
        help="Multiplier applied after an insufficient but expandable round (default: 2)",
    )
    parser.add_argument(
        "--minimum-records",
        type=int,
        default=DEFAULT_MINIMUM_RECORDS,
        help="Absolute data-sufficiency record floor before request-size adaptation",
    )
    parser.add_argument(
        "--minimum-unique-samples",
        type=int,
        default=DEFAULT_MINIMUM_UNIQUE_SAMPLES,
        help=(
            "Absolute independent-sample floor before request-size adaptation "
            "(default: 2000; measurement rows do not count as new samples)"
        ),
    )
    parser.add_argument(
        "--minimum-provenance-rate",
        type=float,
        default=DEFAULT_MINIMUM_PROVENANCE_RATE,
        help="Required fraction with source_id and source_locator (default: 1.0)",
    )
    parser.add_argument(
        "--minimum-global-macroregions",
        type=int,
        default=DEFAULT_MINIMUM_GLOBAL_MACROREGIONS,
        help="Required canonical land macroregions for a global result (default: 4)",
    )
    parser.add_argument(
        "--minimum-macroregion-samples",
        type=int,
        default=DEFAULT_MINIMUM_MACROREGION_SAMPLES,
        help="Unique canonical samples required for a macroregion to count (default: 100)",
    )
    parser.add_argument(
        "--maximum-global-macroregion-share",
        type=float,
        default=DEFAULT_MAXIMUM_GLOBAL_MACROREGION_SHARE,
        help="Largest allowed canonical land macroregion share (default: 0.60)",
    )
    parser.add_argument(
        "--source-timeout-seconds",
        type=float,
        default=DEFAULT_SOURCE_TIMEOUT_SECONDS,
        help="Per-source timeout inside each research round (default: 600)",
    )
    parser.add_argument(
        "--run-timeout-seconds",
        type=float,
        default=DEFAULT_RUN_TIMEOUT_SECONDS,
        help="Internal atlas timeout, leaving one minute in the default 1800-second round",
    )
    parser.add_argument(
        "--analysis-profile", choices=("demo", "production"), default="production"
    )
    parser.add_argument(
        "--generated-at", help="ISO-8601 acquisition timestamp passthrough"
    )
    parser.add_argument("--batch-qc-input", type=Path)
    parser.add_argument("--batch-qc-policy", type=Path)
    parser.add_argument("--no-geology", action="store_true")
    parser.add_argument("--require-all-sources", action="store_true")
    parser.add_argument(
        "--seed-priority-source-id",
        action="append",
        default=[],
        help=(
            "Source ID scheduled first in round 1 (repeatable). Intended for "
            "cross-run acquisition memory (acquisition_memory.py advise); "
            "later rounds keep deriving priorities from repair actions. "
            "Seeds only reorder already-routable sources."
        ),
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=DEFAULT_MAX_ROUNDS,
        help=(
            f"Total rounds recorded in this loop directory "
            f"(default {DEFAULT_MAX_ROUNDS}, cap {MAX_ROUNDS_CAP}); "
            "pass a higher value when resuming to append rounds"
        ),
    )
    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=DEFAULT_TIME_BUDGET_SECONDS,
        help=(
            "Total wall-clock ceiling across adaptive 30-minute rounds "
            "for explicitly authorized extended research "
            "(direct-controller default and maximum: 43200 seconds / 12 hours; "
            "official tasks must enter through task_router.py)"
        ),
    )
    parser.add_argument(
        "--round-timeout-seconds",
        type=float,
        default=DEFAULT_ROUND_TIMEOUT_SECONDS,
        help="Hard per-round subprocess timeout (default: 1800 seconds)",
    )
    parser.add_argument(
        "--checkpoint-only",
        action="store_true",
        help=(
            "Explicitly allow an online run shorter than one 1800-second research round. "
            "The receipt remains delivery_ready=false even if this checkpoint passes."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run embedded decision-logic tests and exit",
    )
    return parser


def _self_test() -> int:
    checks = 0

    def check(condition: bool, label: str) -> None:
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    # 1. Source-error classification is conservative.
    check(
        source_failure_retryable("HTTP Error 503: connection timed out"),
        "transient retryable",
    )
    check(
        not source_failure_retryable("research use conditions unclear"),
        "license manual",
    )
    check(not source_failure_retryable("mystery failure"), "unknown defaults to manual")
    check(
        not source_failure_retryable("network schema drift detected"),
        "non-retryable marker wins over retryable marker",
    )
    # 2. Run-level classification.
    check(
        run_failure_retryable("network_unavailable", "demo"),
        "network retryable in any mode",
    )
    check(
        run_failure_retryable("incomplete_retrieval", "online"),
        "incomplete retryable online",
    )
    check(
        not run_failure_retryable("incomplete_retrieval", "input"),
        "incomplete manual offline",
    )
    check(
        not run_failure_retryable("needs_human_review", "online"),
        "human review never retried",
    )
    terminal_plan = {
        "autonomous": [],
        "manual": [{"issue_code": "SPATIAL_DIMENSION_COVERAGE_GAP", "count": 3}],
    }
    check(
        "不是本次在线研究交付"
        in next_step_text(
            "converged", terminal_plan, mode="demo", checkpoint_only=False
        ),
        "a converged demo cannot tell the agent that formal research is complete",
    )
    check(
        "未证明 D1 在线采集"
        in next_step_text(
            "converged", terminal_plan, mode="input", checkpoint_only=False
        ),
        "a converged external-input run preserves its acquisition evidence boundary",
    )
    check(
        "队列清空"
        in next_step_text(
            "converged", terminal_plan, mode="online", checkpoint_only=False
        ),
        "a converged online controller cannot ignore a remaining research queue",
    )
    check(
        needs_current_sufficiency_probe(
            [
                {
                    "round": 1,
                    "command": ["python"],
                    "sufficiency": {"assessment_version": "atlas-data-sufficiency-v3"},
                }
            ]
        )
        and not needs_current_sufficiency_probe(
            [
                {
                    "round": 1,
                    "command": ["python"],
                    "sufficiency": {
                        "assessment_version": SUFFICIENCY_VERSION,
                        "discovery_gaps": {
                            "viable_selected_source_ids": [],
                            "observed_source_ids": [],
                            "observed_lineage_ids": [],
                            "observed_lineage_ids_by_medium": {},
                        },
                    },
                }
            ]
        ),
        "resuming a stale report forces one current sufficiency assessment",
    )

    def stub_round(
        *,
        exit_code: int | None = 0,
        execution_status: str = "partial_success",
        validation: str = "valid",
        action_required: int = 0,
        failed: list[dict[str, Any]] | None = None,
        retry_run: bool = False,
        input_sha: str | None = None,
    ) -> dict[str, Any]:
        return {
            "round": 1,
            "command": ["python"],
            "exit_code": exit_code,
            "execution_status": execution_status,
            "validation_status": validation,
            "counts": {
                "action_required": action_required,
                "failed_sources": len(failed or []),
            },
            "failed_sources": failed or [],
            "manual_groups": [],
            "run_failure_retryable": retry_run,
            "gate_stop_reason": None,
            "input_fingerprints": {"input_sha256": input_sha, "evidence_sha256": None},
        }

    # 3. Convergence: clean round stops as converged.
    check(
        decide_next([stub_round()], 3, 0.0, None) == ("stop", "converged"),
        "clean converges",
    )
    # 4. Retryable source failure continues; identical repeat stops as no_progress.
    failing = stub_round(
        failed=[{"source_id": "s1", "error": "timeout", "retryable": True}]
    )
    check(decide_next([failing], 3, 0.0, None)[0] == "continue", "retryable continues")
    check(
        decide_next([failing, failing], 3, 0.0, None) == ("stop", "no_progress"),
        "identical signature stops",
    )
    improving = stub_round(
        failed=[{"source_id": "s2", "error": "timeout", "retryable": True}]
    )
    check(
        decide_next([failing, improving], 2, 0.0, None)
        == ("stop", "round_budget_exhausted"),
        "round budget enforced",
    )
    # 5. Manual-only issues stop immediately with a grouped plan.
    manual_only = stub_round(action_required=5)
    manual_only["manual_groups"] = [
        {
            "stage_owner": "D2",
            "issue_code": "MISSING_UNIT",
            "count": 5,
            "recommended_action": "补显式 schema map",
        }
    ]
    check(
        decide_next([manual_only], 3, 0.0, None) == ("stop", "no_autonomous_repair"),
        "manual issues stop the loop",
    )
    plan = build_repair_plan(manual_only)
    check(
        plan["autonomous"] == [] and plan["manual"][0]["count"] == 5,
        "manual plan built",
    )
    # 6. Non-retryable source failure joins the manual plan.
    hard_fail = stub_round(
        failed=[{"source_id": "s9", "error": "license unclear", "retryable": False}]
    )
    plan = build_repair_plan(hard_fail)
    check(
        plan["autonomous"] == []
        and plan["manual"][0]["issue_code"] == "SOURCE_ACQUISITION_FAILED",
        "hard source failure routed to manual",
    )
    check(
        decide_next([hard_fail], 3, 0.0, None) == ("stop", "no_autonomous_repair"),
        "hard source failure stops",
    )
    # 7. Changed input fingerprint (agent repaired data) defeats no_progress.
    round_a = stub_round(
        action_required=5,
        failed=[{"source_id": "s1", "error": "timeout", "retryable": True}],
        input_sha="a" * 64,
    )
    round_b = stub_round(
        action_required=5,
        failed=[{"source_id": "s1", "error": "timeout", "retryable": True}],
        input_sha="b" * 64,
    )
    check(
        actionable_signature(round_a) != actionable_signature(round_b),
        "input change changes signature",
    )
    # 8. Validation failure is terminal; run-failure classification is honored.
    check(
        decide_next([stub_round(validation="invalid")], 3, 0.0, None)
        == ("stop", "contract_validation_failed"),
        "invalid contract stops",
    )
    check(
        decide_next(
            [stub_round(exit_code=2, execution_status="invalid_input")], 3, 0.0, None
        )
        == ("stop", "run_failed"),
        "hard failure stops",
    )
    check(
        decide_next(
            [stub_round(exit_code=2, execution_status="needs_human_review")],
            3,
            0.0,
            None,
        )
        == ("stop", "needs_human_review"),
        "human review stops",
    )
    check(
        decide_next(
            [
                stub_round(
                    exit_code=2, execution_status="network_unavailable", retry_run=True
                )
            ],
            3,
            0.0,
            None,
        )[0]
        == "continue",
        "transient run failure retries",
    )
    # 9. Time budget stops a loop that would otherwise continue.
    check(
        decide_next([failing], 5, 100.0, 50.0) == ("stop", "time_budget_exhausted"),
        "time budget enforced",
    )
    # 10. Final status mapping.
    check(
        final_status("converged", {"execution_status": "success"}) == "success",
        "success maps",
    )
    check(
        final_status("converged", {"execution_status": "partial_success"})
        == "partial_success",
        "partial maps",
    )
    check(
        final_status("no_autonomous_repair", {}) == "needs_human_review",
        "manual maps to review",
    )
    check(final_status("run_failed", {}) == "failed", "run_failed maps to failed")
    check(
        persisted_elapsed_seconds(
            [
                {"command": [], "duration_seconds": 99},
                {"command": ["python"], "duration_seconds": 1200.5},
                {"command": ["python"], "duration_seconds": 600},
            ]
        )
        == 1800.5,
        "resumed loop preserves cumulative executed time",
    )
    target_args = argparse.Namespace(
        per_analyte_observations=512,
        max_per_analyte_observations=10_000,
    )
    check(
        acquisition_target(target_args, 9) == 512,
        "round number alone does not expand acquisition",
    )
    target_args.active_per_analyte_observations = 1024
    check(
        acquisition_target(target_args, 2) == 1024,
        "explicit sufficiency decision advances acquisition target",
    )
    # 11. A valid but thin online result expands; an uncovered dimension stops
    # honestly instead of repeating the same source or claiming convergence.
    thin = stub_round()
    thin["sufficiency"] = {
        "status": "insufficient",
        "can_expand_acquisition": True,
        "next_per_analyte_observations": 1024,
        "unmet_required_criteria": ["record_volume"],
        "discovery_gaps": {
            "elements": [],
            "media": [],
            "spatial_domains": [],
            "element_medium_cells": [],
        },
    }
    check(decide_next([thin], 3, 0.0, 100.0)[0] == "continue", "thin data expands")
    check(
        build_repair_plan(thin)["autonomous"][0]["action"] == "expand_acquisition",
        "expansion appears in repair plan",
    )
    uncovered = stub_round()
    uncovered["sufficiency"] = {
        "status": "insufficient",
        "can_expand_acquisition": False,
        "next_per_analyte_observations": None,
        "unmet_required_criteria": ["requested_dimensions"],
        "discovery_gaps": {
            "elements": ["As"],
            "media": ["sediment"],
            "spatial_domains": ["marine"],
            "element_medium_cells": ["As|sediment"],
        },
    }
    check(
        decide_next([uncovered], 3, 0.0, 100.0) == ("stop", "repair_queue_pending"),
        "uncovered source dimensions expose a mandatory repair queue",
    )
    uncovered_plan = build_repair_plan(uncovered)
    check(
        uncovered_plan["manual"][0]["issue_code"] == "SOURCE_COVERAGE_GAP",
        "coverage gap routes to D1 discovery",
    )
    check(
        final_status("repair_queue_pending", uncovered) == "needs_human_review",
        "insufficient output cannot masquerade as completed research",
    )
    check(
        allow_probe_round(True, False, "repair_queue_pending", [uncovered], 3),
        "resumed controller probes once after a queued repair",
    )
    check(
        not allow_probe_round(False, False, "repair_queue_pending", [uncovered], 3),
        "fresh invocation never probes past an unconsumed repair queue",
    )
    check(
        not allow_probe_round(True, True, "repair_queue_pending", [uncovered], 3),
        "a no-op resume gets exactly one probe round",
    )
    check(
        not allow_probe_round(True, False, "repair_queue_pending", [uncovered], 1),
        "probe round respects the round budget",
    )
    check(
        not allow_probe_round(True, False, "run_failed", [uncovered], 3),
        "hard failures are not probed",
    )
    # 12. Backlog harvesting, gate-round rehydration and frozen-request enforcement.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        backlog = tmp_path / "iteration_backlog.csv"
        backlog.write_text(
            "item_id,record_id,source_id,stage_owner,severity,status,issue_code,field,"
            "observed_value,detail,recommended_action,auto_recheck\n"
            "I1,r1,s1,D2,info,scientific_limit,CENSORED_OBSERVATION,censored,<,d,keep,false\n"
            "I2,r2,s1,D1,warn,action_required,MISSING_LICENSE,license,,d,confirm use,true\n"
            "I3,r3,s1,D1,warn,action_required,MISSING_LICENSE,license,,d,confirm use,false\n",
            encoding="utf-8",
        )
        harvested = read_backlog(backlog)
        check(
            harvested["status_counts"]["action_required"] == 2, "backlog action count"
        )
        check(
            harvested["status_counts"]["scientific_limit"] == 1,
            "scientific limit separate",
        )
        check(harvested["auto_recheck"] == 1, "auto_recheck counted")
        check(harvested["manual_groups"][0]["count"] == 2, "manual grouping")
        gate_public = {
            "round": 1,
            "command": [],
            "exit_code": None,
            "execution_status": None,
            "output_dir": "",
            "gate_events": [
                {"gate": "input_header", "status": "stop", "detail": "missing columns"}
            ],
        }
        hydrated = rehydrate_round(gate_public, "input")
        check(hydrated["gate_stop_reason"] == "invalid_input", "gate round rehydrated")
        check(
            decide_next([hydrated], 3, 0.0, None) == ("stop", "invalid_input"),
            "rehydrated gate stops with original reason",
        )
        request = tmp_path / "request.json"
        request.write_text("{}\n", encoding="utf-8")
        digest = sha256_file(request)
        write_json(
            tmp_path / REPORT_FILENAME,
            {
                "schema_version": REPORT_VERSION,
                "request_sha256": digest,
                "mode": "demo",
                "rounds": [gate_public],
            },
        )
        check(len(load_previous_rounds(tmp_path, digest)) == 1, "resume loads rounds")
        try:
            load_previous_rounds(tmp_path, "0" * 64)
            check(False, "freeze violation must raise")
        except LoopUsageError:
            check(True, "freeze violation raises")
        write_json(
            tmp_path / REPORT_FILENAME,
            {
                "schema_version": "self-correction-loop-report-v5",
                "request_sha256": digest,
                "mode": "online",
                "rounds": [gate_public],
            },
        )
        try:
            load_previous_rounds(tmp_path, digest)
            check(False, "stale loop report must not be resumed in place")
        except LoopUsageError:
            check(True, "stale loop report fails closed before resumption")
    # 13. The real sufficiency assessor expands only repairable acquisition
    # gaps and refuses to hide a provenance defect behind more records.
    with tempfile.TemporaryDirectory() as tmp:
        round_dir = Path(tmp)
        fieldnames = (
            "sample_identity_group",
            "element_or_analyte",
            "medium",
            "source_id",
            "source_record_id",
            "source_file",
            "source_locator",
            "official_source_url",
            "file_sha256",
            "dataset_title",
            "dataset_version",
            "license",
            "analytical_method",
            "method_missing_reason",
            "latitude",
            "longitude",
            "original_latitude_raw",
            "original_longitude_raw",
            "coordinate_accuracy_evidence_status",
            "normalized_value",
            "normalized_unit",
            "geologic_unit",
            "geology_missing_reason",
            "qc_flags",
            "operational_confidence",
        )
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for index in range(100):
                writer.writerow(
                    {
                        "sample_identity_group": f"sample-{index % 10}",
                        "element_or_analyte": "As",
                        "medium": "soil",
                        "source_id": "source-a",
                        "source_record_id": f"source-record-{index}",
                        "source_file": "fixture.csv",
                        "source_locator": f"https://example.test/record/{index}",
                        "official_source_url": "https://example.test/source-a",
                        "file_sha256": "a" * 64,
                        "dataset_title": "Self-test source A",
                        "dataset_version": "self-test-v1",
                        "license": "CC0-1.0",
                        "analytical_method": "fixture method",
                        "method_missing_reason": "",
                        "latitude": "50",
                        "longitude": "10",
                        "original_latitude_raw": "50",
                        "original_longitude_raw": "10",
                        "coordinate_accuracy_evidence_status": "not_reported",
                        "normalized_value": "1.0",
                        "normalized_unit": "mg/kg",
                        "geologic_unit": "Self-test unit",
                        "geology_missing_reason": "",
                        "qc_flags": "[]",
                        "operational_confidence": json.dumps(
                            {
                                "band": "high",
                                "quality_dimensions": {
                                    "source_evidence": {"band": "high"},
                                    "analytical_readiness": {"band": "high"},
                                    "spatial_usability": {"band": "high"},
                                    "workflow_usability": {"band": "high"},
                                },
                            }
                        ),
                    }
                )
        write_json(
            round_dir / "request_evidence" / "source_route.json",
            {
                "selected_sources": [
                    {
                        "source_id": "source-a",
                        "matching_media": ["soil"],
                        "request_compatibility": {"analytes": {"matched": ["As"]}},
                    },
                    {
                        "source_id": "source-b",
                        "matching_media": ["soil"],
                        "request_compatibility": {"analytes": {"matched": ["As"]}},
                    },
                ]
            },
        )
        write_json(
            round_dir / "anomaly_report.json",
            {"groups": [{"status": "analyzed"}], "candidate_count": 0},
        )
        write_json(
            round_dir / "sources_and_confidence.json",
            {
                "sources": [
                    {
                        "source_id": "source-a",
                        "record_count": 100,
                        "official_links": [
                            {
                                "kind": "record_official_url",
                                "url": "https://example.test/source-a",
                            }
                        ],
                        "record_provenance": {"official_linked_record_count": 100},
                    }
                ]
            },
        )
        request = {
            "elements": ["As"],
            "media": ["soil"],
            "max_records": 10_000,
            "region": "global",
        }
        assess_args = argparse.Namespace(
            minimum_records=5_000,
            minimum_provenance_rate=1.0,
            max_per_analyte_observations=10_000,
            acquisition_growth_factor=2.0,
        )
        assessed = assess_sufficiency(
            round_dir,
            request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        check(
            assessed["unmet_required_criteria"]
            == [
                "global_geographic_breadth",
                "global_spatial_coverage",
                "independent_sample_volume",
                "record_volume",
                "scientific_evidence_subset_by_medium",
                "source_balance",
                "source_diversity",
                "source_diversity_by_medium",
                "spatial_dimension_coverage",
            ],
            "thin online result separates independent samples, strict per-medium evidence, geography, rows, balance and lineage gaps",
        )
        database_coverage = read_database_coverage(round_dir / "geochemistry.csv")
        check(
            database_coverage["records"] == 100
            and database_coverage["unique_samples"] == 10,
            "multi-element or repeated rows do not inflate independent sample volume",
        )
        check(
            database_coverage["macroregion_unique_samples"] == {"Europe": 10},
            "canonical sample geography uses the pinned country-to-macroregion evidence",
        )
        spatial_audit = assess_global_spatial_coverage(
            database_coverage,
            {"gemstat-open-archive"},
            {
                "elements": ["As", "Cu", "Pb", "Zn"],
                "media": ["soil", "sediment", "water"],
            },
        )
        target_by_country = {
            item["country_iso_a3"]: item
            for item in spatial_audit["geographic_search_targets"]
        }
        check(
            spatial_audit["priority_country_codes"][:6]
            == ["RUS", "CAN", "USA", "CHN", "AUS", "BRA"],
            "global spatial policy derives the six largest non-polar country sentinels",
        )
        check(
            len(spatial_audit["priority_country_codes"]) == 30
            and {"DZA", "EGY", "IRN", "SAU", "TUR", "ZAF"}.issubset(
                spatial_audit["priority_country_codes"]
            ),
            "global spatial policy derives thirty broad land sentinels that include African and Middle-Eastern coverage without named control-flow branches",
        )
        check(
            target_by_country["RUS"]["repair_mode"] == "route_registered_source"
            and target_by_country["RUS"]["canonical_unique_samples"] == 0
            and target_by_country["RUS"]["registered_source_candidates"]
            == ["pangaea-barents-c-horizon-soil", "pangaea-batagay-soil"],
            "a blank Russia target routes both registered terrestrial lineages instead of passing Europe as a proxy",
        )
        check(
            target_by_country["IND"]["repair_mode"] == "requery_selected_source"
            and target_by_country["IND"]["selected_source_candidates"]
            == ["gemstat-open-archive"],
            "a selected full-profile source with India observations is distinguished from a catalog gap",
        )
        check(
            spatial_requery_source_ids(spatial_audit["geographic_search_targets"], [])
            == ["gemstat-open-archive"],
            "machine-generated geographic gaps expose selected sources that can be expanded autonomously",
        )
        georoc_antarctica = _json_object(SOURCE_MANIFEST_PATH)["sources"][
            "georoc-antarctica-intraplate"
        ]
        check(
            not _entry_matches_request(
                georoc_antarctica,
                {"elements": ["Hg"], "media": ["rock"]},
            )
            and _entry_matches_request(
                georoc_antarctica,
                {"elements": ["Cu"], "media": ["rock"]},
            ),
            "source routing ignores a declared analyte whose audited full-source count is zero",
        )
        check(
            "australia-ngsa-mercury"
            not in target_by_country["AUS"]["catalog_candidate_source_ids"],
            "a registered Hg-only product is not suggested for an As/Cu/Pb/Zn Australian gap",
        )
        check(
            {
                spatial_scope.coordinate_macroregion(105, 35),
                spatial_scope.coordinate_macroregion(25, -2),
                spatial_scope.coordinate_macroregion(134, -25),
                spatial_scope.coordinate_macroregion(-100, 40),
                spatial_scope.coordinate_macroregion(-60, -15),
            }
            == {"Asia", "Africa", "Oceania", "North America", "South America"}
            and spatial_scope.coordinate_macroregion(0, 0) == "Open ocean / unassigned",
            "pinned macroregion evidence distinguishes five continents from open ocean",
        )
        check(
            assessed["can_expand_acquisition"],
            "repairable volume can expand while lineage repair stays manual",
        )
        structural_gap_request = {
            "elements": ["As"],
            "media": ["soil", "water"],
            "max_records": 10_000,
            "region": "China",
        }
        structural_gap = assess_sufficiency(
            round_dir,
            structural_gap_request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        regional_gap = structural_gap["discovery_gaps"]["regional_spatial_gap"]
        check(
            structural_gap["status"] == "insufficient"
            and structural_gap["can_expand_acquisition"]
            and structural_gap["next_per_analyte_observations"] == 1024
            and "record_volume" in structural_gap["acquisition_repairable_criteria"]
            and "independent_sample_volume"
            in structural_gap["acquisition_repairable_criteria"]
            and "requested_dimensions"
            in structural_gap["acquisition_blocking_criteria"]
            and "element_medium_coverage"
            in structural_gap["acquisition_blocking_criteria"],
            "an uncovered dimension stays manual without blocking independently useful volume expansion",
        )
        check(
            structural_gap["criteria"]["element_medium_coverage"]["status"] == "fail"
            and structural_gap["criteria"]["element_medium_coverage"]["target"]
            == {"minimum_coverage_rate": 1.0},
            "an explicit element-medium matrix requires 100 percent coverage",
        )
        medium_balance = structural_gap["criteria"]["medium_sample_balance"]
        check(
            medium_balance["status"] == "fail"
            and medium_balance["observed"]["unique_samples_by_medium"]
            == {"soil": 10, "water": 0}
            and medium_balance["target"]["minimum_unique_samples_per_requested_medium"]
            == 10
            and structural_gap["discovery_gaps"]["medium_sample_balance"]["water"][
                "deficit_unique_samples"
            ]
            == 10,
            "severe requested-medium imbalance is measured on independent samples and becomes explicit D1 debt",
        )
        multidimensional_gap = assess_sufficiency(
            round_dir,
            {
                "elements": ["As", "Cu"],
                "media": ["soil", "water"],
                "max_records": 10_000,
                "region": "China",
            },
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        element_balance = multidimensional_gap["criteria"]["element_sample_balance"]
        cell_balance = multidimensional_gap["criteria"]["element_medium_sample_balance"]
        check(
            element_balance["status"] == "fail"
            and element_balance["observed"]["shortfalls"]["Cu"][
                "deficit_unique_samples"
            ]
            == 10
            and cell_balance["status"] == "fail"
            and set(cell_balance["observed"]["shortfalls"])
            == {"As|water", "Cu|soil", "Cu|water"}
            and multidimensional_gap["discovery_gaps"]["element_sample_balance"]["Cu"][
                "target_unique_samples"
            ]
            == 10,
            "element and element×medium sample imbalance become separate machine-actionable debts",
        )
        check(
            structural_gap["criteria"]["regional_spatial_coverage"]["status"] == "fail"
            and regional_gap["country_iso_a3"] == "CHN"
            and regional_gap["canonical_occupied_grid_cells"] == 0,
            "a named-country request fails closed when its samples are outside the requested region",
        )
        bbox_spatial_gap = assess_regional_spatial_coverage(
            database_coverage,
            {"region": {"bbox": [73.0, 18.0, 135.0, 54.0]}},
        )
        check(
            bbox_spatial_gap["scope_key"] == "custom"
            and bbox_spatial_gap["target_coverage_grid_cells"] > 0
            and not bbox_spatial_gap["passes"],
            "a China-sized bbox receives the same coarse regional observation-hole audit",
        )
        china_cell = spatial_scope.coverage_grid_cell_id(105.0, 35.0)
        check(
            spatial_scope.coverage_grid_cell_id(
                *spatial_scope.coverage_grid_cell_center(china_cell)
            )
            == china_cell,
            "coverage grid cell IDs round-trip through their frozen centres",
        )
        policy = spatial_sufficiency.load_policy()
        invalid_zone_policy = json.loads(json.dumps(policy))
        invalid_zone_policy["regional_scope"]["longitude_band_count"] = 1
        try:
            spatial_sufficiency.validate_policy(invalid_zone_policy)
            check(False, "regional zone policy bounds must fail closed")
        except spatial_sufficiency.SpatialSufficiencyPolicyError:
            check(True, "regional zone policy bounds match the published schema")
        shanghai_grid = spatial_sufficiency.build_scope_coverage_grid(
            spatial_scope.resolve_region("Shanghai"), policy
        )
        check(
            shanghai_grid["cell_degrees"] == 0.25
            and len(shanghai_grid["target_cell_ids"]) >= 2,
            "regional grid resolution is derived from extent so a city-scale scope is not silently skipped",
        )
        adaptive_cell = shanghai_grid["target_cell_ids"][0]
        check(
            spatial_scope.coverage_grid_cell_id(
                *spatial_scope.coverage_grid_cell_center(adaptive_cell, 0.25),
                0.25,
            )
            == adaptive_cell,
            "coverage cell IDs support every policy-approved adaptive resolution",
        )
        scale_cases = [
            ({"bbox": [-30.0, -10.0, 30.0, 10.0]}, 2.0),
            ({"bbox": [-10.0, -5.0, 10.0, 5.0]}, 1.0),
            ({"bbox": [-4.0, -2.0, 4.0, 2.0]}, 0.5),
            ({"bbox": [-1.5, -1.0, 1.5, 1.0]}, 0.25),
        ]
        check(
            [
                spatial_sufficiency.select_regional_grid_degrees(
                    spatial_scope.resolve_region(region), policy
                )
                for region, _ in scale_cases
            ]
            == [expected for _, expected in scale_cases],
            "regional resolution follows request extent across four scales without place-name branches",
        )
        arbitrary_view_audit = spatial_sufficiency.audit_spatial_views(
            [],
            {
                "region": {"bbox": [-10.0, -5.0, 10.0, 5.0]},
                "elements": ["As", "Cu", "Pb"],
                "media": ["soil", "water"],
            },
            policy,
        )
        check(
            len(arbitrary_view_audit["views"]) == 12
            and {item["view_id"] for item in arbitrary_view_audit["views"]}
            == {
                "overall",
                "element:As",
                "element:Cu",
                "element:Pb",
                "medium:soil",
                "medium:water",
                "element_medium:As|soil",
                "element_medium:As|water",
                "element_medium:Cu|soil",
                "element_medium:Cu|water",
                "element_medium:Pb|soil",
                "element_medium:Pb|water",
            },
            "view audit expands the request Cartesian product rather than a fixed element or medium list",
        )
        edge_audit = spatial_sufficiency.audit_spatial_views(
            [
                {
                    "source_id": "edge",
                    "sample_identity": "outside",
                    "canonical_point": [120.84, 31.0],
                    "display_point": [120.84, 31.0],
                    "elements": ["As"],
                    "media": ["soil"],
                    "element_medium": ["As|soil"],
                }
            ],
            {"region": "Shanghai", "elements": ["As"], "media": ["soil"]},
            policy,
        )
        check(
            edge_audit["views"][0]["canonical_unique_samples"] == 0,
            "adaptive cells do not admit a point outside the exact frozen bbox",
        )
        china_grid = spatial_sufficiency.build_scope_coverage_grid(
            spatial_scope.resolve_region("China"), policy
        )
        zone_cells = [
            list(cells)
            for _, cells in sorted(china_grid["coverage_zone_cells"].items())
        ]
        broad_target = max(
            20,
            math.ceil(
                len(china_grid["target_cell_ids"])
                * float(policy["regional_scope"]["minimum_grid_coverage_rate"])
            ),
        )
        broad_cells: list[str] = []
        for offset in range(max(len(cells) for cells in zone_cells)):
            for cells in zone_cells:
                if offset < len(cells):
                    broad_cells.append(cells[offset])
                if len(broad_cells) == broad_target:
                    break
            if len(broad_cells) == broad_target:
                break
        view_samples: list[dict[str, Any]] = []
        for index, cell_id in enumerate(broad_cells):
            point = list(
                spatial_scope.coverage_grid_cell_center(
                    cell_id, china_grid["cell_degrees"]
                )
            )
            view_samples.append(
                {
                    "source_id": "broad-as",
                    "sample_identity": f"as-{index}",
                    "canonical_point": point,
                    "display_point": point,
                    "elements": ["As"],
                    "media": ["soil"],
                    "element_medium": ["As|soil"],
                }
            )
        clustered_point = list(
            spatial_scope.coverage_grid_cell_center(
                broad_cells[0], china_grid["cell_degrees"]
            )
        )
        for index in range(8):
            view_samples.append(
                {
                    "source_id": "clustered-cu",
                    "sample_identity": f"cu-{index}",
                    "canonical_point": clustered_point,
                    "display_point": clustered_point,
                    "elements": ["Cu"],
                    "media": ["water"],
                    "element_medium": ["Cu|water"],
                }
            )
        dimension_audit = spatial_sufficiency.audit_spatial_views(
            view_samples,
            {
                "region": "China",
                "elements": ["As", "Cu"],
                "media": ["soil", "water"],
            },
            policy,
        )
        view_status = {
            item["view_id"]: item["status"] for item in dimension_audit["views"]
        }
        check(
            view_status["overall"] == "pass"
            and view_status["element:As"] == "pass"
            and view_status["medium:soil"] == "pass"
            and view_status["element_medium:As|soil"] == "pass"
            and view_status["element:Cu"] == "gap"
            and view_status["medium:water"] == "gap"
            and view_status["element_medium:Cu|water"] == "gap",
            "broad overall or As coverage cannot hide a clustered Cu/water filter view",
        )
        east_cells = [
            cell_id
            for cell_id in china_grid["target_cell_ids"]
            if spatial_scope.coverage_grid_cell_center(
                cell_id, china_grid["cell_degrees"]
            )[0]
            >= 112.0
        ]
        east_only_samples: list[dict[str, Any]] = []
        for index in range(24):
            cell_id = east_cells[index % len(east_cells)]
            point = list(
                spatial_scope.coverage_grid_cell_center(
                    cell_id, china_grid["cell_degrees"]
                )
            )
            east_only_samples.append(
                {
                    "source_id": "east-only",
                    "sample_identity": f"east-{index}",
                    "canonical_point": point,
                    "display_point": point,
                    "elements": ["As"],
                    "media": ["soil"],
                    "element_medium": ["As|soil"],
                }
            )
        east_only_audit = spatial_sufficiency.audit_spatial_views(
            east_only_samples,
            {"region": "China", "elements": ["As"], "media": ["soil"]},
            policy,
        )
        east_only_overall = next(
            item for item in east_only_audit["views"] if item["view_id"] == "overall"
        )
        check(
            not east_only_audit["passes"]
            and "canonical_coverage_zone_shortfall" in east_only_overall["reason_codes"]
            and east_only_overall["missing_coverage_zones"]
            and east_only_overall["coverage_zone_targets"]
            and all(
                len(item["bbox"]) == 4
                for item in east_only_overall["coverage_zone_targets"]
            ),
            "regional east-only density cannot hide western or subregional observation holes",
        )
        dimension_gaps = build_spatial_dimension_gaps(
            dimension_audit,
            set(),
            {
                "region": "China",
                "elements": ["As", "Cu"],
                "media": ["soil", "water"],
            },
        )
        cu_gap = next(
            item for item in dimension_gaps if item["view_id"] == "element:Cu"
        )
        check(
            cu_gap["required_elements"] == ["Cu"]
            and cu_gap["country_targets"][0]["country_iso_a3"] == "CHN",
            "a failed view becomes a machine-readable where-plus-dimension D1 target",
        )
        russia_bbox = spatial_scope.load_country_registry()["by_code"]["RUS"]["bbox"]
        west_russia = regional_search_target(
            scope_label="Russia",
            scope_bbox=russia_bbox,
            target_bbox=[25.0, 40.0, 80.0, 75.0],
            country_iso_a3="RUS",
            coverage_zone_id=None,
        )
        east_russia = regional_search_target(
            scope_label="Russia",
            scope_bbox=russia_bbox,
            target_bbox=[135.0, 45.0, -175.0, 75.0],
            country_iso_a3="RUS",
            coverage_zone_id=None,
        )
        check(
            "west" in west_russia["target_label"].casefold()
            and "east" in east_russia["target_label"].casefold()
            and _bbox_overlap_area(
                [135.0, 45.0, -175.0, 75.0], [-180.0, 60.0, -160.0, 75.0]
            )
            > 0,
            "wrapped Russian targets retain correct east/west labels and antimeridian Admin-1 overlap",
        )
        queue_request = {
            "elements": ["As", "Cu"],
            "region": "China",
            "media": ["soil", "water"],
        }
        queue_report = {
            "request_sha256": "a" * 64,
            "rounds": [
                {
                    "round": 1,
                    "sufficiency": {
                        "assessment_version": SUFFICIENCY_VERSION,
                        "status": "insufficient",
                        "discovery_gaps": {
                            "viable_selected_source_ids": [],
                            "observed_source_ids": [],
                            "observed_lineage_ids": [],
                            "observed_lineage_ids_by_medium": {},
                            "spatial_dimension_gaps": dimension_gaps,
                            "geographic_search_targets": [],
                        },
                    },
                }
            ],
        }
        d1_queue = build_d1_repair_queue(queue_report, queue_request)
        queued_cu = next(
            item for item in d1_queue["tasks"] if item["view_id"] == "element:Cu"
        )
        check(
            d1_queue["queue_version"] == "d1-repair-queue-v3"
            and d1_queue["status"] == "pending"
            and d1_queue["task_count"] == len(d1_queue["tasks"])
            and d1_queue["action_group_count"] == len(d1_queue["action_groups"])
            and d1_queue["action_group_count"] < d1_queue["task_count"]
            and d1_queue["unattempted_action_group_count"]
            == d1_queue["action_group_count"]
            and d1_queue["operator_continuation_required"] is True
            and d1_queue["final_response_permitted"] is False
            and d1_queue["control_state"] == "continue_research"
            and d1_queue["required_next_action"]
            == "consume_next_action_group_and_resume_frozen_request"
            and sum(d1_queue["execution_class_counts"].values())
            == d1_queue["task_count"]
            and queued_cu["required_elements"] == ["Cu"]
            and queued_cu["required_spatial_domains"] == ["land", "inland_water"]
            and queued_cu["country_iso_a3"] == "CHN"
            and queued_cu["fallback_action_chain"][-1] == "targeted_source_discovery"
            and queued_cu["continuation_strategy"] == "new_output_after_skill_change"
            and queued_cu["execution_class"] == "data_action_current_skill"
            and queued_cu["target_label"]
            and queued_cu["gazetteer_semantics"].startswith("search hints only")
            and any(
                "China" in query and "Cu" in query
                for query in queued_cu["discovery_queries"]
            )
            and "national_geological_or_environmental_survey"
            in queued_cu["discovery_platform_sequence"]
            and queued_cu["minimum_distinct_discovery_families"] >= 3
            and any(
                group["required_spatial_domains"] == ["land", "inland_water"]
                for group in d1_queue["action_groups"]
                if queued_cu["task_id"] in group["member_task_ids"]
            )
            and any(
                "distinct discovery families" in item
                for item in queued_cu["completion_evidence_required"]
            )
            and [item["priority"] for item in d1_queue["tasks"]]
            == sorted(item["priority"] for item in d1_queue["tasks"]),
            "the loop groups repeated region-by-view gaps into named receipt-driven D1 actions",
        )
        global_russia_queue = build_d1_repair_queue(
            {
                "request_sha256": "f" * 64,
                "rounds": [
                    {
                        "round": 1,
                        "sufficiency": {
                            "assessment_version": SUFFICIENCY_VERSION,
                            "status": "insufficient",
                            "discovery_gaps": {
                                "viable_selected_source_ids": [],
                                "observed_source_ids": [],
                                "observed_lineage_ids": [],
                                "observed_lineage_ids_by_medium": {},
                                "spatial_dimension_gaps": [
                                    {
                                        "view_id": "overall",
                                        "view_kind": "overall",
                                        "scope_key": "global",
                                        "scope_label": "Global",
                                        "bbox": [-180.0, -90.0, 180.0, 90.0],
                                        "required_elements": ["As"],
                                        "required_media": ["soil"],
                                        "reason_codes": [
                                            "priority_country_coverage_shortfall"
                                        ],
                                        "country_targets": [
                                            {
                                                "country_iso_a3": "RUS",
                                                "country_name": "Russia",
                                                "macroregion": "Europe and Northern Asia",
                                                "target_bboxes": [russia_bbox],
                                            }
                                        ],
                                    }
                                ],
                                "geographic_search_targets": [],
                            },
                        },
                    }
                ],
            },
            {"region": "global", "elements": ["As"], "media": ["soil"]},
        )
        russia_task = next(
            item
            for item in global_russia_queue["tasks"]
            if item["country_iso_a3"] == "RUS"
        )
        check(
            russia_task["bbox"] == russia_bbox
            and russia_task["bbox"] != [-180.0, -90.0, 180.0, 90.0]
            and "Russia" in russia_task["target_label"],
            "a country-specific Russian repair never falls back to the whole-world bbox",
        )
        structural_queue_request = {
            "elements": ["As", "Cu"],
            "region": "China",
            "media": ["soil", "sediment", "water"],
        }
        structural_queue = build_d1_repair_queue(
            {
                "request_sha256": "c" * 64,
                "rounds": [
                    {
                        "round": 1,
                        "sufficiency": {
                            "assessment_version": SUFFICIENCY_VERSION,
                            "status": "insufficient",
                            "discovery_gaps": {
                                "viable_selected_source_ids": [
                                    "tpdc-china-mountain-soil",
                                    "pangaea-east-china-sea-clay",
                                ],
                                "observed_source_ids": ["tpdc-china-mountain-soil"],
                                "observed_lineage_ids": ["tpdc-china-mountain-soil"],
                                "observed_lineage_ids_by_medium": {
                                    "soil": ["tpdc-china-mountain-soil"],
                                    "water": [],
                                },
                                "elements": ["Pb"],
                                "media": ["water"],
                                "element_medium_cells": ["Cu|water"],
                                "independent_lineages": 2,
                                "medium_lineages": {"soil": 1},
                                "spatial_dimension_gaps": [],
                                "geographic_search_targets": [],
                            },
                        },
                    }
                ],
            },
            structural_queue_request,
        )
        structural_kinds = {
            str(item["task_kind"]) for item in structural_queue["tasks"]
        }
        pb_task = next(
            item
            for item in structural_queue["tasks"]
            if item["view_id"] == "element:Pb"
        )
        lineage_task = next(
            item
            for item in structural_queue["tasks"]
            if item["task_kind"] == "source_lineage_gap"
        )
        check(
            structural_queue["status"] == "pending"
            and structural_kinds
            == {
                "source_dimension_gap",
                "source_lineage_gap",
                "medium_lineage_gap",
            }
            and all(
                item["fallback_action_chain"][-1] == "targeted_source_discovery"
                for item in structural_queue["tasks"]
            ),
            "missing dimensions and lineage deficits share the auditable D1 repair queue",
        )
        check(
            pb_task["preferred_repair_mode"] == "requery_selected_source"
            and pb_task["execution_class"] == "data_action_current_skill"
            and set(pb_task["selected_source_candidates"])
            == {
                "pangaea-east-china-sea-clay",
                "tpdc-china-mountain-soil",
            }
            and lineage_task["preferred_repair_mode"] == "requery_selected_source"
            and lineage_task["execution_class"] == "data_action_current_skill"
            and lineage_task["selected_source_candidates"]
            == ["pangaea-east-china-sea-clay"]
            and "tpdc-china-mountain-soil"
            not in lineage_task["selected_source_candidates"],
            "dimension and lineage repairs reuse compatible D1 sources before online discovery without double-counting an observed lineage",
        )
        clear_queue = build_d1_repair_queue(
            {
                "request_sha256": "b" * 64,
                "rounds": [
                    {
                        "round": 2,
                        "sufficiency": {
                            "assessment_version": SUFFICIENCY_VERSION,
                            "status": "sufficient",
                            "discovery_gaps": {
                                "viable_selected_source_ids": [],
                                "observed_source_ids": [],
                                "observed_lineage_ids": [],
                                "observed_lineage_ids_by_medium": {},
                                "spatial_dimension_gaps": [],
                                "geographic_search_targets": [],
                            },
                        },
                    }
                ],
            },
            queue_request,
        )
        check(
            clear_queue["status"] == "clear"
            and clear_queue["task_count"] == 0
            and clear_queue["action_group_count"] == 0
            and clear_queue["unattempted_action_group_count"] == 0
            and clear_queue["operator_continuation_required"] is False
            and clear_queue["final_response_permitted"] is True
            and clear_queue["control_state"] == "queue_clear"
            and clear_queue["required_next_action"] == "validate_research_delivery"
            and all(
                value == 0 for value in clear_queue["execution_class_counts"].values()
            )
            and clear_queue["tasks"] == [],
            "the D1 repair queue clears only after observed structural gaps disappear",
        )
        stale_assessment_queue = build_d1_repair_queue(
            {
                "request_sha256": "d" * 64,
                "rounds": [
                    {
                        "round": 1,
                        "sufficiency": {
                            "assessment_version": "atlas-data-sufficiency-v3",
                            "status": "sufficient",
                            "discovery_gaps": {},
                        },
                    }
                ],
            },
            queue_request,
        )
        check(
            stale_assessment_queue["status"] == "pending"
            and stale_assessment_queue["task_count"] == 1
            and stale_assessment_queue["tasks"][0]["task_kind"]
            == "sufficiency_assessment_gap"
            and stale_assessment_queue["tasks"][0]["execution_class"]
            == "controller_rerun_current_skill"
            and stale_assessment_queue["tasks"][0]["preferred_repair_mode"]
            == "rerun_current_controller"
            and stale_assessment_queue["tasks"][0]["fallback_action_chain"]
            == ["rerun_current_controller"]
            and stale_assessment_queue["tasks"][0]["discovery_queries"] == [],
            "an absent or stale sufficiency assessment fails closed instead of clearing the D1 queue",
        )
        global_grid = spatial_sufficiency.build_scope_coverage_grid(
            spatial_scope.resolve_region("global"), policy
        )
        ocean_cells_by_zone: dict[str, list[str]] = {}
        for cell_id in global_grid["target_cell_ids"]:
            if cell_id in global_grid["country_by_cell"]:
                continue
            zone = global_grid["coverage_zone_by_cell"][cell_id]
            ocean_cells_by_zone.setdefault(zone, []).append(cell_id)
        marine_cells = [
            cell_id
            for zone in sorted(ocean_cells_by_zone)[:3]
            for cell_id in ocean_cells_by_zone[zone][:20]
        ]
        marine_samples = [
            {
                "source_id": "marine-water",
                "sample_identity": f"marine-{index}",
                "canonical_point": list(
                    spatial_scope.coverage_grid_cell_center(
                        cell_id, global_grid["cell_degrees"]
                    )
                ),
                "display_point": list(
                    spatial_scope.coverage_grid_cell_center(
                        cell_id, global_grid["cell_degrees"]
                    )
                ),
                "elements": ["As"],
                "media": ["water"],
                "spatial_domains": ["marine"],
                "element_medium": ["As|water"],
            }
            for index, cell_id in enumerate(marine_cells)
        ]
        marine_audit = spatial_sufficiency.audit_spatial_views(
            marine_samples,
            {
                "region": "global",
                "elements": ["As"],
                "media": ["water"],
                "spatial_domains": ["marine"],
            },
            policy,
        )
        marine_status = {
            item["view_id"]: item["status"] for item in marine_audit["views"]
        }
        check(
            marine_status["element:As"] == "pass"
            and marine_status["medium:water"] == "pass"
            and marine_status["element_medium:As|water"] == "pass",
            "global marine observations count in ocean coverage zones without weakening the separate land sentinel gate",
        )
        empty_global_view = next(
            item
            for item in arbitrary_view_audit["views"]
            if item["view_id"] == "overall"
        )
        empty_global_view = {
            **empty_global_view,
            "view_kind": "element",
            "canonical_country_occupied_grid_cells": {},
            "canonical_coverage_zone_occupied_grid_cells": {},
            "minimum_cells_per_qualifying_coverage_zone": 1,
        }
        initial_targets = spatial_sufficiency.rank_global_country_targets(
            empty_global_view, policy
        )
        filled_code = initial_targets[0]
        frozen_land_grid = spatial_scope.load_global_land_grid(
            float(policy["global_scope"]["grid_cell_degrees"])
        )
        retargeted_view = {
            **empty_global_view,
            "canonical_country_occupied_grid_cells": {
                filled_code: len(frozen_land_grid["country_cells"][filled_code])
            },
        }
        check(
            filled_code
            not in spatial_sufficiency.rank_global_country_targets(
                retargeted_view, policy
            ),
            "global repair targets are recomputed from observed holes after every round",
        )
        invalid_policy = json.loads(json.dumps(policy))
        invalid_policy["country_override"] = {"CHN": "pass"}
        invalid_policy_path = round_dir / "invalid-spatial-policy.json"
        write_json(invalid_policy_path, invalid_policy)
        try:
            spatial_sufficiency.load_policy(invalid_policy_path)
            check(False, "unknown spatial policy keys must fail closed")
        except spatial_sufficiency.SpatialSufficiencyPolicyError:
            check(True, "unknown spatial policy keys fail closed")
        structural_plan = build_repair_plan(
            {
                "sufficiency": structural_gap,
                "failed_sources": [],
                "manual_groups": [],
                "run_failure_retryable": False,
            }
        )
        check(
            structural_plan["autonomous"][0]["action"] == "expand_acquisition"
            and "SOURCE_COVERAGE_GAP"
            in {item["issue_code"] for item in structural_plan["manual"]}
            and "REGIONAL_SPATIAL_COVERAGE_GAP"
            in {item["issue_code"] for item in structural_plan["manual"]},
            "dimension and regional discovery work remain visible during checkpoint improvement",
        )
        check(
            structural_gap["reporting_facts"]["measurement_records"] == 100
            and structural_gap["reporting_facts"]["independent_samples"] == 10
            and structural_gap["reporting_facts"]["independent_sample_shortfall_factor"]
            == 200.0
            and structural_gap["reporting_facts"]["single_quality_label_prohibited"]
            is True,
            "loop publishes exact count, shortfall and multidimensional-quality facts for final reporting",
        )
        thin_plan = build_repair_plan(
            {
                "sufficiency": assessed,
                "failed_sources": [],
                "manual_groups": [],
                "run_failure_retryable": False,
            }
        )
        check(
            thin_plan["autonomous"][0]["action"] == "expand_acquisition"
            and {item["issue_code"] for item in thin_plan["manual"]}
            == {
                "GLOBAL_SPATIAL_COVERAGE_GAP",
                "SPATIAL_DIMENSION_COVERAGE_GAP",
                "SOURCE_DIVERSITY_GAP",
                "MEDIUM_LINEAGE_GAP",
                "STRICT_SCIENTIFIC_SUBSET_GAP",
            },
            "expansion retains separate D1 lineage, strict-evidence and geographic work",
        )
        saturated_a = stub_round(input_sha="a" * 64)
        saturated_a["counts"]["records"] = 100
        saturated_a["acquisition_target"] = {"per_analyte_observations": 512}
        saturated_a["sufficiency"] = {
            "status": "insufficient",
            "can_expand_acquisition": True,
            "next_per_analyte_observations": 1024,
            "unmet_required_criteria": ["record_volume"],
            "criteria": {
                "independent_sample_volume": {"observed": {"unique_samples": 10}}
            },
            "discovery_gaps": {
                "elements": [],
                "media": [],
                "spatial_domains": [],
                "element_medium_cells": [],
            },
        }
        saturated_b = json.loads(json.dumps(saturated_a))
        saturated_b["acquisition_target"]["per_analyte_observations"] = 1024
        saturated_b["sufficiency"]["next_per_analyte_observations"] = 2048
        check(
            decide_next([saturated_a, saturated_b], 5, 0.0, 100.0)
            == ("stop", "no_progress"),
            "a larger acquisition target that adds no records or samples stops at source capacity",
        )
        with (round_dir / "geochemistry.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        complete_rows = [dict(row) for row in rows]
        qc_blocked_rows = [dict(row) for row in complete_rows]
        for row in qc_blocked_rows:
            if row["sample_identity_group"] == "sample-0":
                row["qc_flags"] = '["BATCH_QC_FAILED"]'
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(qc_blocked_rows)
        qc_blocked_coverage = read_database_coverage(round_dir / "geochemistry.csv")
        check(
            qc_blocked_coverage["scientific_ready_unique_samples_by_medium"]["soil"]
            == 9,
            "D2 error-severity QC flags exclude a sample from the strict scientific subset",
        )
        rows = [dict(row) for row in complete_rows]
        for row in rows:
            row["analytical_method"] = ""
            row["method_missing_reason"] = "source_not_reported"
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        write_json(
            round_dir / "sources_and_confidence.json",
            {
                "sources": [
                    {
                        "source_id": "source-a",
                        "record_count": 100,
                        "official_links": [],
                        "record_provenance": {"official_linked_record_count": 0},
                    }
                ]
            },
        )
        evidence_debt = assess_sufficiency(
            round_dir,
            request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        evidence_queue = build_d1_repair_queue(
            {
                "request_sha256": "e" * 64,
                "rounds": [{"round": 1, "sufficiency": evidence_debt}],
            },
            request,
        )
        method_task = next(
            item
            for item in evidence_queue["tasks"]
            if item["view_id"] == "medium:soil"
            and "analytical_method_evidence_shortfall" in item["reason_codes"]
        )
        source_link_task = next(
            item
            for item in evidence_queue["tasks"]
            if item["view_id"] == "source:source-a"
        )
        check(
            evidence_debt["criteria"]["metadata_evidence_accounting"]["status"]
            == "pass"
            and evidence_debt["criteria"]["analytical_method_evidence_by_medium"][
                "status"
            ]
            == "fail"
            and evidence_debt["criteria"]["official_source_links"]["status"] == "fail",
            "explicit missing metadata stays scientifically honest but cannot satisfy method evidence or official-link gates",
        )
        check(
            method_task["task_kind"] == "metadata_evidence_gap"
            and method_task["observed"]["analytical_method_rate"] == 0.0
            and source_link_task["task_kind"] == "metadata_evidence_gap"
            and source_link_task["target"]["official_linked_record_rate"] == 1.0,
            "method and official-link evidence debts become separate executable D1 repair tasks",
        )
        partial_method_rows = [dict(row) for row in complete_rows]
        for row in partial_method_rows[50:]:
            row["analytical_method"] = ""
            row["method_missing_reason"] = "source_not_reported"
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(partial_method_rows)
        comparison_subset = assess_sufficiency(
            round_dir,
            request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        check(
            comparison_subset["criteria"]["analytical_method_evidence_by_medium"][
                "status"
            ]
            == "pass"
            and comparison_subset["criteria"]["analytical_readiness"]["status"]
            == "pass",
            "a transparent broad archive passes method readiness when every observed medium retains a sufficiently large method-bearing comparison subset",
        )
        source_masked_rows = [dict(row) for row in complete_rows]
        for index, row in enumerate(source_masked_rows):
            if index >= 50:
                row["source_id"] = "source-method-unknown"
                row["source_record_id"] = f"unknown-{index}"
                row["analytical_method"] = ""
                row["method_missing_reason"] = "publisher_compilation_omits_row_method"
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(source_masked_rows)
        source_masked = assess_sufficiency(
            round_dir,
            request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [
                    {"source_id": "source-a", "status": "success"},
                    {"source_id": "source-method-unknown", "status": "success"},
                ],
            },
            "online",
            512,
            assess_args,
        )
        source_masked_queue = build_d1_repair_queue(
            {
                "request_sha256": "1" * 64,
                "rounds": [{"round": 1, "sufficiency": source_masked}],
            },
            request,
        )
        source_method_task = next(
            item
            for item in source_masked_queue["tasks"]
            if item["view_id"] == "source:source-method-unknown|medium:soil"
        )
        check(
            source_masked["criteria"]["analytical_method_evidence_by_material_source"][
                "status"
            ]
            == "fail"
            and source_method_task["observed"]["source_id"] == "source-method-unknown"
            and source_method_task["observed"]["publisher_absent_only"] is True
            and set(source_method_task["reason_codes"])
            == {
                "material_source_analytical_method_evidence_shortfall",
                "publisher_method_absence_requires_replacement_source",
            }
            and "source-method-unknown"
            not in source_method_task["selected_source_candidates"],
            "a large publisher-method-absent source triggers replacement-lineage acquisition instead of an impossible same-source retry",
        )
        rows = [dict(row) for row in complete_rows]
        write_json(
            round_dir / "sources_and_confidence.json",
            {
                "sources": [
                    {
                        "source_id": "source-a",
                        "record_count": 100,
                        "official_links": [
                            {
                                "kind": "record_official_url",
                                "url": "https://example.test/source-a",
                            }
                        ],
                        "record_provenance": {"official_linked_record_count": 100},
                    }
                ]
            },
        )
        rows[0]["official_source_url"] = ""
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        row_link_debt = assess_sufficiency(
            round_dir,
            request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        check(
            row_link_debt["criteria"]["official_source_links"]["status"] == "fail"
            and row_link_debt["criteria"]["official_source_links"]["observed"][
                "official_linked_records"
            ]
            == 99,
            "one source-level homepage cannot hide a canonical record whose official URL/DOI path is missing",
        )
        rows = [dict(row) for row in complete_rows]
        for row in rows[:3]:
            row["source_locator"] = ""
        with (round_dir / "geochemistry.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        assessed = assess_sufficiency(
            round_dir,
            request,
            {
                "mode": "online_sources:auto",
                "source_outcomes": [{"source_id": "source-a", "status": "success"}],
            },
            "online",
            512,
            assess_args,
        )
        check(
            "record_provenance" in assessed["acquisition_blocking_criteria"],
            "provenance defect is acquisition-blocking",
        )
        check(
            not assessed["can_expand_acquisition"],
            "more same-source records cannot hide provenance defects",
        )
    breadth_request = {
        "coverage_mode": "maximize_evidence_breadth",
        "max_records": 200_000,
    }
    breadth = acquisition_breadth_state(
        breadth_request,
        [
            {
                "source_id": "source-a",
                "status": "success",
                "record_count": 512,
                "allocated_max_records": 512,
            }
        ],
        {"source-a"},
        {"source-a"},
        512,
        512,
        50_000,
        "online",
    )
    check(
        breadth["required"]
        and not breadth["passed"]
        and breadth["sources_filling_current_allocation"] == ["source-a"],
        "maximize-breadth continues after minimum gates while a source fills its current allocation",
    )
    breadth = acquisition_breadth_state(
        breadth_request,
        [
            {
                "source_id": "source-a",
                "status": "success",
                "record_count": 320,
                "allocated_max_records": 512,
            }
        ],
        {"source-a"},
        {"source-a"},
        320,
        512,
        50_000,
        "online",
    )
    check(
        breadth["passed"] and breadth["source_capacity_reached"],
        "maximize-breadth stops with an explicit all-source capacity signal",
    )
    breadth = acquisition_breadth_state(
        breadth_request,
        [],
        {"source-a"},
        {"source-a"},
        200_000,
        512,
        50_000,
        "online",
    )
    check(
        breadth["passed"] and breadth["record_ceiling_reached"],
        "maximize-breadth stops at the frozen request record ceiling",
    )
    checkpoint_args = argparse.Namespace(
        mode="online",
        max_rounds=2,
        time_budget_seconds=600.0,
    )
    check(
        requires_checkpoint_only(checkpoint_args),
        "runs shorter than one complete research round require an explicit checkpoint-only declaration",
    )
    checkpoint_args.max_rounds = DEFAULT_MAX_ROUNDS
    checkpoint_args.time_budget_seconds = DEFAULT_TIME_BUDGET_SECONDS
    check(
        not requires_checkpoint_only(checkpoint_args),
        "the default 12-hour controller may deliver after one or more 30-minute rounds when all gates pass",
    )
    check(
        [source_order_offset(round_index) for round_index in range(1, 25)]
        == list(range(24)),
        "successive research rounds advance every queue start instead of starving one tail",
    )
    priority_record = {
        "manual_groups": [],
        "failed_sources": [
            {"source_id": "retry-source", "retryable": True, "error": "timeout"}
        ],
        "run_failure_retryable": False,
        "sufficiency": {
            "status": "insufficient",
            "can_expand_acquisition": True,
            "next_per_analyte_observations": 2048,
            "unmet_required_criteria": ["global_spatial_coverage"],
            "acquisition_blocking_criteria": [],
            "discovery_gaps": {
                "spatial_requery_source_ids": ["russia-source", "xinjiang-source"],
                "geographic_search_targets": [],
                "spatial_dimension_gaps": [],
            },
        },
    }
    check(
        next_round_priority_source_ids(priority_record)
        == ["retry-source", "russia-source", "xinjiang-source"],
        "the next acquisition round consumes retry and spatial-requery source IDs from the audited repair plan",
    )
    check(
        DEFAULT_MAX_PER_ANALYTE_OBSERVATIONS == 200_000,
        "the default per-element expansion target cannot silently truncate a still-open research request",
    )
    print(json.dumps({"status": "PASS", "tests": checks}, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        if not args.request or not args.output_dir:
            raise LoopUsageError(
                "--request and --output-dir are required unless --self-test"
            )
        if not args.request.is_file():
            raise LoopUsageError(f"request file not found: {args.request}")
        if args.input is not None:
            args.mode = "input"
            if not args.input.is_file():
                raise LoopUsageError(f"input file not found: {args.input}")
        elif args.online_source:
            args.mode = "online"
        elif args.demo:
            args.mode = "demo"
        else:
            args.mode = "online"
            args.online_source = "auto"
        if not 1 <= args.max_rounds <= MAX_ROUNDS_CAP:
            raise LoopUsageError(f"--max-rounds must be within 1..{MAX_ROUNDS_CAP}")
        if not 1 <= args.per_analyte_observations <= args.max_per_analyte_observations:
            raise LoopUsageError(
                "--per-analyte-observations must be positive and not exceed its maximum"
            )
        if not 1 <= args.max_per_analyte_observations <= 200_000:
            raise LoopUsageError(
                "--max-per-analyte-observations must be within 1..200000"
            )
        if not 1 < args.acquisition_growth_factor <= 10:
            raise LoopUsageError("--acquisition-growth-factor must be within (1, 10]")
        if args.minimum_records < 1:
            raise LoopUsageError("--minimum-records must be positive")
        if args.minimum_unique_samples < 1:
            raise LoopUsageError("--minimum-unique-samples must be positive")
        if not 0 < args.minimum_provenance_rate <= 1:
            raise LoopUsageError("--minimum-provenance-rate must be within (0, 1]")
        if not 1 <= args.minimum_global_macroregions <= len(LAND_MACROREGIONS):
            raise LoopUsageError(
                f"--minimum-global-macroregions must be within 1..{len(LAND_MACROREGIONS)}"
            )
        if args.minimum_macroregion_samples < 1:
            raise LoopUsageError("--minimum-macroregion-samples must be positive")
        if not 0 < args.maximum_global_macroregion_share <= 1:
            raise LoopUsageError(
                "--maximum-global-macroregion-share must be within (0, 1]"
            )
        if not 1 <= args.source_timeout_seconds <= args.run_timeout_seconds:
            raise LoopUsageError(
                "--source-timeout-seconds must be positive and not exceed --run-timeout-seconds"
            )
        if not 60 <= args.run_timeout_seconds < args.round_timeout_seconds:
            raise LoopUsageError(
                "--run-timeout-seconds must be at least 60 and below --round-timeout-seconds"
            )
        if not 1 <= args.time_budget_seconds <= MAX_TIME_BUDGET_SECONDS:
            raise LoopUsageError(
                "--time-budget-seconds must be within 1..43200 (12 hours)"
            )
        if requires_checkpoint_only(args) and not args.checkpoint_only:
            raise LoopUsageError(
                "online budgets below one 1800-second research round "
                "require --checkpoint-only"
            )
        args.request_sha256 = sha256_file(args.request)
        args.normalized_request = source_router.validate_request(
            read_json(args.request), source_router.load_catalog()
        )
        report = run_loop(args)
    except LoopUsageError as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] in ("success", "partial_success"):
        return 0
    if report["status"] == "needs_human_review":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
