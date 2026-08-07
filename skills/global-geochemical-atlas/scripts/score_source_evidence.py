#!/usr/bin/env python3
"""Score source evidence without treating incomplete metadata as a binary rejection."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import source_adapters

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"
DEFAULT_CANDIDATE_AUDITS = SKILL_DIR / "fixtures" / "candidate-audits"
DEFAULT_SNAPSHOT_ROOT = SKILL_DIR / "fixtures" / "four-media"

EVIDENCE_VERSION = "geochemical-source-evidence-v3"
EvidenceStatus = Literal["verified", "partial", "missing", "conflict", "not_applicable"]

DIMENSION_WEIGHTS = {
    "identity_publisher": 10,
    "version_snapshot": 15,
    "file_record_integrity": 15,
    "provenance": 15,
    "schema_semantics": 15,
    "method_qc_metadata": 10,
    "adapter_reproducibility": 10,
    "human_review": 10,
}
STATUS_FACTORS = {
    "verified": 1.0,
    "partial": 0.5,
    "missing": 0.0,
    "conflict": 0.0,
}
TIER_RANK = {"U": 0, "D": 1, "C": 2, "B": 3, "A": 4}
USE_MODE_RANK = {"discovery": 0, "raw_observation": 1, "normalized_analysis": 2, "benchmark_ready": 3}


class EvidenceScoringError(ValueError):
    """Raised when evidence inputs cannot be interpreted safely."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvidenceScoringError(f"{label} does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceScoringError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise EvidenceScoringError(f"{label} must be a JSON object")
    return value


def load_candidate_evidence(
    directory: Path = DEFAULT_CANDIDATE_AUDITS,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
) -> dict[str, dict[str, Any]]:
    """Load checked-in candidate evidence, keeping the newest file per source."""

    evidence: dict[str, dict[str, Any]] = {}
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            value = _read_json(path, "candidate evidence")
            source_id = value.get("source_id")
            if isinstance(source_id, str) and source_id:
                value = dict(value)
                value["_evidence_path"] = str(path.relative_to(SKILL_DIR))
                evidence[source_id] = value
    if snapshot_root.exists():
        for path in sorted(snapshot_root.rglob("snapshot_manifest.json")):
            snapshot = _read_json(path, "snapshot manifest")
            source_id = snapshot.get("source_id")
            if isinstance(source_id, str) and source_id:
                entry = evidence.setdefault(source_id, {"source_id": source_id})
                entry["_snapshot_manifest"] = snapshot
                entry["_snapshot_manifest_path"] = str(path.relative_to(SKILL_DIR))
        for path in sorted(snapshot_root.rglob("human_review.json")):
            review = _read_json(path, "human review")
            source_id = review.get("source_id")
            if isinstance(source_id, str) and source_id:
                entry = evidence.setdefault(source_id, {"source_id": source_id})
                entry["human_review"] = review
                entry["_human_review_path"] = str(path.relative_to(SKILL_DIR))
    return evidence


def _dimension(
    status: EvidenceStatus,
    weight: int,
    note: str,
    evidence: Sequence[str] = (),
    *,
    awarded_points: float | None = None,
) -> dict[str, Any]:
    if status == "not_applicable":
        points = 0.0
    elif awarded_points is None:
        points = weight * STATUS_FACTORS[status]
    else:
        points = awarded_points
    return {
        "status": status,
        "weight": weight,
        "awarded_points": round(points, 2),
        "note": note,
        "evidence": list(dict.fromkeys(item for item in evidence if item)),
    }


def _https_urls(values: Sequence[Any]) -> bool:
    return bool(values) and all(isinstance(value, str) and value.startswith("https://") for value in values)


def derive_access_status(entry: Mapping[str, Any]) -> str:
    """Derive the current normal-access mode from declared source interfaces."""

    accesses = [
        str(item.get("access", "")).casefold()
        for item in entry.get("interfaces", [])
        if isinstance(item, Mapping)
    ]
    combined = " ".join(accesses)
    if any(token in combined for token in ("open", "free_download", "public")):
        return "open"
    if "point_data_on_request" in combined:
        return "restricted"
    if "account" in combined or "login" in combined:
        return "account_required"
    if any(token in combined for token in ("acceptance", "registration", "moratorium", "form_or_station_limit")):
        return "application_required"
    return "unavailable"


def derive_research_use_status(entry: Mapping[str, Any]) -> str:
    """Map legacy licence descriptions to research-use conditions, not redistribution rights."""

    license_entry = entry.get("license", {})
    status = license_entry.get("status")
    license_id = str(license_entry.get("id") or "")
    if license_id == "LicenseRef-USGS-Public-Domain":
        return "open_research"
    if status in {"open", "open_reuse_terms", "dataset_specific_open_government", "citation_and_copyright_terms"}:
        return "attribution_required"
    if status == "restricted" and "noncommercial" in str(license_entry.get("notes", "")).casefold():
        return "noncommercial_research_only"
    if status in {
        "mixed_record_or_batch",
        "upstream_specific",
        "dataset_specific",
        "open_with_privacy_and_aggregation_conditions",
        "restricted",
    }:
        return "permission_required"
    return "unknown"


def _registry_integrity(registry_entry: Mapping[str, Any] | None) -> dict[str, Any]:
    weight = DIMENSION_WEIGHTS["file_record_integrity"]
    if registry_entry is None:
        return _dimension("missing", weight, "No frozen file or archive inventory is registered.")
    download = registry_entry.get("download")
    if not isinstance(download, Mapping):
        return _dimension("conflict", weight, "A production registry entry exists without a download contract.")
    files = download.get("files")
    if isinstance(files, list) and files:
        valid = all(
            isinstance(item, Mapping)
            and bool(item.get("file_id") or item.get("filename"))
            and bool(item.get("url"))
            and isinstance(item.get("bytes"), int)
            and item["bytes"] > 0
            for item in files
        )
        return _dimension(
            "verified" if valid else "conflict",
            weight,
            "Every registered file has a stable identity, official URL and byte count."
            if valid
            else "One or more registered files lack a stable identity, official URL or byte count.",
        )
    selected_members = download.get("selected_members")
    if isinstance(selected_members, list) and selected_members:
        valid = all(
            isinstance(item, Mapping)
            and isinstance(item.get("bytes"), int)
            and item["bytes"] > 0
            and bool(item.get("file_id") or item.get("filename") or item.get("name"))
            and isinstance(item.get("range_start"), int)
            and isinstance(item.get("range_end"), int)
            and item["range_end"] >= item["range_start"]
            for item in selected_members
        )
        return _dimension(
            "verified" if valid else "conflict",
            weight,
            "Every selected ZIP member is identified by name, byte range and decoded byte count."
            if valid
            else "One or more selected ZIP members lacks a valid identity, range or byte-count contract.",
        )
    members = download.get("members")
    if isinstance(members, list) and members:
        valid = all(
            isinstance(item, Mapping)
            and isinstance(item.get("bytes"), int)
            and item["bytes"] > 0
            and bool(item.get("file_id") or item.get("filename") or item.get("name"))
            for item in members
        )
        return _dimension(
            "verified" if valid else "conflict",
            weight,
            "Archive members are pinned by identity and byte count."
            if valid
            else "Archive member identity or byte-count inventory is incomplete.",
        )
    return _dimension("conflict", weight, "The registered download has no verifiable file inventory.")


def _human_review_dimension(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    weight = DIMENSION_WEIGHTS["human_review"]
    review = candidate.get("human_review") if isinstance(candidate, Mapping) else None
    evidence = [candidate.get("_human_review_path", "")] if isinstance(candidate, Mapping) else []
    if not isinstance(review, Mapping):
        return _dimension("missing", weight, "No checked-in human review record is available.")
    completed = review.get("completed_record_count", 0)
    if review.get("status") in {"complete", "passed"} and not completed:
        completed = review.get("reviewed_record_count", review.get("required_record_count", 0))
    if not isinstance(completed, int) or completed < 0:
        return _dimension("conflict", weight, "Human review count is invalid.")
    if review.get("status") == "conflict":
        return _dimension(
            "conflict", weight, "Human review found an unresolved systematic mapping error.", evidence
        )
    if completed >= 30 or (
        review.get("all_records_reviewed") is True and review.get("status") in {"complete", "passed"}
    ):
        return _dimension(
            "verified", weight, f"{completed} stratified records were reviewed and passed.", evidence
        )
    if completed >= 10:
        return _dimension(
            "partial",
            weight,
            f"{completed} records were reviewed; 30 are required for full credit.",
            evidence,
            awarded_points=5,
        )
    if completed >= 1:
        return _dimension(
            "partial",
            weight,
            f"{completed} records were reviewed; 30 are required for full credit.",
            evidence,
            awarded_points=2,
        )
    prepared = review.get("prepared_record_count", 0)
    return _dimension(
        "missing",
        weight,
        f"A {prepared}-record review sample is prepared but no completed review is recorded."
        if prepared
        else "Human review has not started.",
        evidence,
    )


def _score_tier(score: float, scoreable: bool) -> str:
    if not scoreable:
        return "U"
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def _derive_use_mode(
    access_status: str,
    research_use_status: str,
    dimensions: Mapping[str, Mapping[str, Any]],
    tier: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    research_permitted = research_use_status in {
        "open_research",
        "attribution_required",
        "noncommercial_research_only",
    }
    if access_status != "open":
        reasons.append(f"access_status={access_status}")
    if not research_permitted:
        reasons.append(f"research_use_status={research_use_status}")
    if access_status != "open" or not research_permitted:
        return "discovery", reasons

    if (
        tier == "A"
        and dimensions["adapter_reproducibility"]["status"] == "verified"
        and dimensions["human_review"]["status"] == "verified"
    ):
        return "benchmark_ready", []
    if (
        dimensions["adapter_reproducibility"]["status"] == "verified"
        and dimensions["file_record_integrity"]["status"] == "verified"
        and dimensions["schema_semantics"]["status"] in {"verified", "partial"}
    ):
        if dimensions["human_review"]["status"] != "verified":
            reasons.append("30-record human review is incomplete")
        return "normalized_analysis", reasons
    if (
        dimensions["file_record_integrity"]["status"] == "verified"
        and dimensions["schema_semantics"]["status"] in {"verified", "partial"}
    ):
        reasons.append("a production adapter is not yet verified")
        return "raw_observation", reasons
    reasons.append("record integrity or schema semantics are not sufficiently evidenced")
    return "discovery", reasons


def score_source(
    source_id: str,
    entry: Mapping[str, Any],
    registry_entry: Mapping[str, Any] | None,
    candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return independently visible research-use, evidence and use-mode states."""

    evidence_urls = entry.get("evidence_urls", [])
    identity_ok = bool(entry.get("title") and entry.get("publisher") and entry.get("landing_page")) and _https_urls(
        evidence_urls
    )
    dimensions: dict[str, dict[str, Any]] = {
        "identity_publisher": _dimension(
            "verified" if identity_ok else "conflict",
            DIMENSION_WEIGHTS["identity_publisher"],
            "Publisher, title, landing page and official HTTPS evidence are recorded."
            if identity_ok
            else "Publisher, title, landing page or official evidence is incomplete.",
            [entry.get("landing_page", ""), *evidence_urls],
        )
    }

    version = entry.get("version", {})
    snapshot_manifest = candidate.get("_snapshot_manifest") if isinstance(candidate, Mapping) else None
    if isinstance(snapshot_manifest, Mapping):
        candidate_archive = {
            "members": snapshot_manifest.get("archive", {}).get("members"),
            "bytes": snapshot_manifest.get("response", {}).get("bytes"),
        }
        candidate_acquisition = {
            "request_url": snapshot_manifest.get("request", {}).get("url"),
            "observed_at": snapshot_manifest.get("observed_at"),
        }
    else:
        candidate_archive = candidate.get("archive") if isinstance(candidate, Mapping) else None
        candidate_acquisition = candidate.get("acquisition") if isinstance(candidate, Mapping) else None
    dynamic_snapshot = (
        isinstance(candidate_archive, Mapping)
        and isinstance(candidate_acquisition, Mapping)
        and bool(candidate_acquisition.get("request_url"))
        and bool(candidate_acquisition.get("observed_at"))
        and (
            isinstance(candidate_archive.get("bytes"), int)
            or isinstance(candidate_archive.get("members"), list)
        )
    )
    if version.get("status") == "pinned" and version.get("value"):
        version_dimension = _dimension(
            "verified",
            DIMENSION_WEIGHTS["version_snapshot"],
            f"A concrete publisher version is pinned: {version['value']}",
        )
    elif dynamic_snapshot:
        version_dimension = _dimension(
            "verified",
            DIMENSION_WEIGHTS["version_snapshot"],
            "A dynamic API response is frozen by exact request, observation time, member inventory and byte counts.",
            [
                candidate.get("_snapshot_manifest_path", ""),
                candidate.get("_evidence_path", ""),
                candidate_acquisition.get("request_url", ""),
            ],
        )
    elif version.get("status") in {"snapshot_available", "annual_repository_versions", "dataset_specific"}:
        version_dimension = _dimension(
            "partial",
            DIMENSION_WEIGHTS["version_snapshot"],
            "A versioning route exists, but this catalog entry does not yet pin one concrete release.",
        )
    else:
        version_dimension = _dimension(
            "missing",
            DIMENSION_WEIGHTS["version_snapshot"],
            "No concrete publisher version or observation snapshot is currently recorded.",
        )
    dimensions["version_snapshot"] = version_dimension

    if dynamic_snapshot:
        members = candidate_archive.get("members", [])
        valid_members = bool(members) and all(
            isinstance(item, Mapping)
            and bool(item.get("file_id") or item.get("name") or item.get("filename"))
            and isinstance(item.get("bytes"), int)
            and item["bytes"] > 0
            for item in members
        )
        dimensions["file_record_integrity"] = _dimension(
            "verified" if valid_members else "partial",
            DIMENSION_WEIGHTS["file_record_integrity"],
            "The dynamic snapshot records a complete member identity and byte-count inventory."
            if valid_members
            else "The dynamic snapshot exists but its member identity or byte-count inventory is incomplete.",
            [candidate.get("_snapshot_manifest_path", ""), candidate.get("_evidence_path", "")],
        )
    else:
        dimensions["file_record_integrity"] = _registry_integrity(registry_entry)

    identifiers = entry.get("identifiers", {})
    if registry_entry is not None:
        provenance_status: EvidenceStatus = "verified"
        provenance_note = "The registered source can be traced to its dataset, frozen files and source locators."
    elif dynamic_snapshot:
        provenance_status = "partial"
        provenance_note = "Dataset and API snapshot provenance are recorded; adapter-level row locators are still pending."
    elif entry.get("landing_page") and evidence_urls:
        provenance_status = "partial"
        provenance_note = "Dataset-level provenance is known, but record-level locators have not been verified."
    else:
        provenance_status = "missing"
        provenance_note = "Dataset and record provenance are not sufficiently identified."
    provenance_evidence = [entry.get("landing_page", ""), *evidence_urls]
    if identifiers.get("dataset_doi"):
        provenance_evidence.append(f"doi:{identifiers['dataset_doi']}")
    dimensions["provenance"] = _dimension(
        provenance_status,
        DIMENSION_WEIGHTS["provenance"],
        provenance_note,
        provenance_evidence,
    )

    required_fields = registry_entry.get("required_fields") if isinstance(registry_entry, Mapping) else None
    observed_data = candidate.get("observed_data") if isinstance(candidate, Mapping) else None
    target_analytes = observed_data.get("target_analytes") if isinstance(observed_data, Mapping) else None
    if isinstance(required_fields, list) and required_fields:
        schema_status: EvidenceStatus = "verified"
        schema_note = "The production registry freezes required source fields and a parsed output contract."
    elif isinstance(target_analytes, Mapping) and target_analytes:
        schema_status = "partial"
        schema_note = "Core analyte, value, unit and coordinate fields were inspected; canonical adapter mapping is pending."
    else:
        schema_status = "missing"
        schema_note = "No verified field mapping to the canonical schema is recorded."
    dimensions["schema_semantics"] = _dimension(
        schema_status,
        DIMENSION_WEIGHTS["schema_semantics"],
        schema_note,
        [candidate.get("_evidence_path", "")] if isinstance(candidate, Mapping) else [],
    )

    observed_metadata = candidate.get("observed_metadata") if isinstance(candidate, Mapping) else None
    if isinstance(observed_metadata, Mapping) and (
        observed_metadata.get("partial_digestion_disclosed")
        or observed_metadata.get("target_llq_values_mg_per_kg")
        or observed_metadata.get("accreditation_rows")
    ):
        method_status: EvidenceStatus = "partial"
        method_note = "Digestion scope, LLQ and accreditation evidence are available, but method/QC coverage is not complete."
    elif registry_entry is not None:
        method_status = "partial"
        method_note = "The source adapter preserves available method fields, but method/QC completeness is not yet audited."
    elif any("method" in str(item).casefold() for item in entry.get("limitations", [])):
        method_status = "partial"
        method_note = "Method limitations are disclosed, but record-level method/QC mapping is not verified."
    else:
        method_status = "missing"
        method_note = "No verified record-level method or QC inventory is available."
    dimensions["method_qc_metadata"] = _dimension(
        method_status,
        DIMENSION_WEIGHTS["method_qc_metadata"],
        method_note,
        [candidate.get("_evidence_path", "")] if isinstance(candidate, Mapping) else [],
    )

    adapter_status: EvidenceStatus
    adapter_note: str
    if registry_entry is None:
        if candidate is not None:
            adapter_status = "partial"
            adapter_note = "A reproducible candidate verifier exists, but no canonical production adapter is implemented."
        else:
            adapter_status = "missing"
            adapter_note = "No callable adapter and frozen parsing contract are registered."
    else:
        try:
            adapter = source_adapters.get_adapter(source_id)
        except source_adapters.SourceAdapterError:
            adapter_status = "conflict"
            adapter_note = "The production registry entry has no callable adapter."
        else:
            registry_version = str(registry_entry.get("dataset_version"))
            if adapter.candidate.version == registry_version == str(version.get("value")):
                adapter_status = "verified"
                adapter_note = "Adapter, registry and catalog resolve the same frozen version."
            else:
                adapter_status = "conflict"
                adapter_note = "Adapter, registry and catalog versions do not align."
    dimensions["adapter_reproducibility"] = _dimension(
        adapter_status,
        DIMENSION_WEIGHTS["adapter_reproducibility"],
        adapter_note,
        [candidate.get("_evidence_path", "")] if isinstance(candidate, Mapping) else [],
    )
    dimensions["human_review"] = _human_review_dimension(candidate)

    denominator = sum(
        item["weight"] for item in dimensions.values() if item["status"] != "not_applicable"
    )
    awarded = sum(item["awarded_points"] for item in dimensions.values())
    scoreable = denominator > 0 and dimensions["identity_publisher"]["status"] != "conflict"
    score = round((awarded / denominator) * 100, 2) if scoreable else 0.0
    tier = _score_tier(score, scoreable)
    access_status = derive_access_status(entry)
    research_use_status = derive_research_use_status(entry)
    use_mode, use_mode_limitations = _derive_use_mode(access_status, research_use_status, dimensions, tier)
    conflicts = [name for name, item in dimensions.items() if item["status"] == "conflict"]
    missing_dimensions = [name for name, item in dimensions.items() if item["status"] == "missing"]
    return {
        "source_id": source_id,
        "access_status": access_status,
        "research_use_status": research_use_status,
        "attribution_note": entry.get("license", {}).get("notes", ""),
        "source_evidence_dimensions": dimensions,
        "source_evidence_score": score,
        "score_denominator": denominator,
        "evidence_tier": tier,
        "use_mode": use_mode,
        "use_mode_limitations": use_mode_limitations,
        "conflicts": conflicts,
        "missing_dimensions": missing_dimensions,
        "score_interpretation": "Evidence completeness score; not the probability that a measurement is true.",
    }


def score_catalog(
    catalog: Mapping[str, Any],
    registry: Mapping[str, Any],
    candidate_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates = candidate_evidence or {}
    sources = {
        source_id: score_source(
            source_id,
            entry,
            registry.get("sources", {}).get(source_id),
            candidates.get(source_id),
        )
        for source_id, entry in sorted(catalog["sources"].items())
    }
    tier_counts = Counter(item["evidence_tier"] for item in sources.values())
    mode_counts = Counter(item["use_mode"] for item in sources.values())
    return {
        "evidence_version": EVIDENCE_VERSION,
        "catalog_version": catalog["catalog_version"],
        "registry_version": registry["registry_version"],
        "scored_at": catalog["reviewed_at"],
        "source_count": len(sources),
        "dimension_weights": DIMENSION_WEIGHTS,
        "summary": {
            "evidence_tiers": {tier: tier_counts.get(tier, 0) for tier in ("A", "B", "C", "D", "U")},
            "use_modes": {
                mode: mode_counts.get(mode, 0)
                for mode in ("benchmark_ready", "normalized_analysis", "raw_observation", "discovery")
            },
        },
        "sources": sources,
        "claim_boundary": (
            "Higher scores mean that more source, version, integrity, provenance, schema, method, adapter and review "
            "evidence is documented. They do not express the probability that every measurement is true or that coverage is complete."
        ),
    }


def run(
    catalog_path: Path = DEFAULT_CATALOG,
    registry_path: Path = DEFAULT_REGISTRY,
    candidate_audits: Path = DEFAULT_CANDIDATE_AUDITS,
) -> dict[str, Any]:
    catalog = _read_json(catalog_path, "source catalog")
    registry = source_adapters.load_source_registry(registry_path)
    return score_catalog(catalog, registry, load_candidate_evidence(candidate_audits))


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
    except (OSError, EvidenceScoringError, source_adapters.SourceAdapterError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
