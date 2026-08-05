#!/usr/bin/env python3
"""Audit source access boundaries and report V3 progressive evidence scores."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import score_source_evidence
import source_adapters
import source_router

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"
DEFAULT_CANDIDATE_AUDITS = SKILL_DIR / "fixtures" / "candidate-audits"

AUDIT_VERSION = "geochemical-source-audit-v3"


def _operational_boundaries(
    score: Mapping[str, Any],
) -> tuple[str, list[str]]:
    """Return executable-operation boundaries, separate from evidence points."""

    boundaries: list[str] = []
    access_status = score["access_status"]
    research_use_status = score["research_use_status"]
    if access_status != "open":
        boundaries.append(f"normal automatic access is unavailable: {access_status}")
    if research_use_status in {"permission_required", "unknown"}:
        boundaries.append(f"research-use conditions do not yet permit automatic analysis: {research_use_status}")
    if score["source_evidence_dimensions"]["identity_publisher"]["status"] == "conflict":
        boundaries.append("source identity is unresolved; retain only as an unverified discovery lead")
    if score["source_evidence_dimensions"]["file_record_integrity"]["status"] == "conflict":
        boundaries.append("registered file integrity is contradictory; do not present the response as complete")
    return ("restricted" if boundaries else "available"), boundaries


def audit_catalog(
    catalog: Mapping[str, Any],
    registry: Mapping[str, Any],
    candidate_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit every source without rejecting useful data for missing soft evidence."""

    evidence_report = score_source_evidence.score_catalog(catalog, registry, candidate_evidence)
    sources: dict[str, Any] = {}
    for source_id, score in evidence_report["sources"].items():
        entry = catalog["sources"][source_id]
        operational_status, operational_boundaries = _operational_boundaries(score)
        sources[source_id] = {
            "legacy_declared_status": entry["status"],
            "legacy_production_eligible": entry["production_eligible"],
            "access_status": score["access_status"],
            "research_use_status": score["research_use_status"],
            "operational_status": operational_status,
            "operational_boundaries": operational_boundaries,
            "source_evidence_score": score["source_evidence_score"],
            "evidence_tier": score["evidence_tier"],
            "use_mode": score["use_mode"],
            "use_mode_limitations": score["use_mode_limitations"],
            "conflicts": score["conflicts"],
            "missing_dimensions": score["missing_dimensions"],
            "dimensions": score["source_evidence_dimensions"],
        }

    operational_counts = Counter(item["operational_status"] for item in sources.values())
    restricted_sources = [
        source_id for source_id, item in sources.items() if item["operational_status"] == "restricted"
    ]
    return {
        "audit_version": AUDIT_VERSION,
        "status": "PASS",
        "catalog_version": catalog["catalog_version"],
        "registry_version": registry["registry_version"],
        "audited_at": catalog["reviewed_at"],
        "source_count": len(sources),
        "summary": {
            "evidence_tiers": evidence_report["summary"]["evidence_tiers"],
            "use_modes": evidence_report["summary"]["use_modes"],
            "operational_statuses": {
                status: operational_counts.get(status, 0) for status in ("available", "restricted")
            },
        },
        "operationally_restricted_sources": restricted_sources,
        "sources": sources,
        "claim_boundary": (
            "PASS means the V3 audit completed and exposed access, research-use conditions and evidence gaps. "
            "It does not mean all sources are equally evidenced, automatically accessible, globally complete, or scientifically comparable."
        ),
    }


def run(
    catalog_path: Path = DEFAULT_CATALOG,
    registry_path: Path = DEFAULT_REGISTRY,
    candidate_audits: Path = DEFAULT_CANDIDATE_AUDITS,
) -> dict[str, Any]:
    catalog = source_router.load_catalog(catalog_path)
    registry = source_adapters.load_source_registry(registry_path)
    candidate_evidence = score_source_evidence.load_candidate_evidence(candidate_audits)
    return audit_catalog(catalog, registry, candidate_evidence)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--candidate-audits", type=Path, default=DEFAULT_CANDIDATE_AUDITS)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args.catalog, args.registry, args.candidate_audits)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (
        OSError,
        ValueError,
        score_source_evidence.EvidenceScoringError,
        source_adapters.SourceAdapterError,
    ) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
