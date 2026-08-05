#!/usr/bin/env python3
"""Build and compare content-addressed snapshots from checked-in source evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import score_source_evidence
import source_router

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"

SNAPSHOT_VERSION = "geochemical-dynamic-snapshot-v3"
DIFF_VERSION = "geochemical-snapshot-diff-v3"


class SnapshotError(ValueError):
    """Raised when source evidence cannot form a defensible snapshot."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SnapshotError(f"{label} does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"{label} is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SnapshotError(f"{label} must be a JSON object")
    return value


def _canonical_sha256(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SnapshotError(f"{label} must be an object")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SnapshotError(f"{label} must be a lowercase SHA-256")
    return value


def _request_contract(url: str) -> dict[str, Any]:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc:
        raise SnapshotError("snapshot request URL must be an absolute HTTPS URL")
    parameters = [{"name": key, "value": value} for key, value in parse_qsl(parts.query, keep_blank_values=True)]
    contract = {
        "method": "GET",
        "url": url,
        "endpoint": f"{parts.scheme}://{parts.netloc}{parts.path}",
        "parameters": parameters,
    }
    contract["canonical_request_sha256"] = _canonical_sha256(
        {"method": contract["method"], "endpoint": contract["endpoint"], "parameters": parameters}
    )
    return contract


def build_snapshot(
    candidate: Mapping[str, Any],
    catalog: Mapping[str, Any],
    *,
    evidence_path: str,
) -> dict[str, Any]:
    """Convert a verified candidate record into a deterministic snapshot manifest."""

    source_id = candidate.get("source_id")
    if not isinstance(source_id, str) or source_id not in catalog.get("sources", {}):
        raise SnapshotError("candidate source_id is missing from the source catalog")
    entry = catalog["sources"][source_id]
    acquisition = _require_mapping(candidate.get("acquisition"), "candidate acquisition")
    archive = _require_mapping(candidate.get("archive"), "candidate archive")
    observed_data = _require_mapping(candidate.get("observed_data"), "candidate observed_data")
    observed_at = acquisition.get("observed_at")
    request_url = acquisition.get("request_url")
    if not isinstance(observed_at, str) or not observed_at.endswith("Z"):
        raise SnapshotError("candidate acquisition observed_at must be UTC")
    if not isinstance(request_url, str):
        raise SnapshotError("candidate acquisition request_url is missing")
    archive_sha256 = _require_sha256(archive.get("sha256"), "candidate archive sha256")
    members = archive.get("members")
    if not isinstance(members, list) or not members:
        raise SnapshotError("candidate archive member inventory is empty")
    normalized_members: list[dict[str, Any]] = []
    for index, member in enumerate(members):
        item = _require_mapping(member, f"archive member {index}")
        name = item.get("name")
        size = item.get("bytes")
        if not isinstance(name, str) or not name or not isinstance(size, int) or size < 0:
            raise SnapshotError(f"archive member {index} has invalid name or size")
        normalized_members.append(
            {"name": name, "bytes": size, "sha256": _require_sha256(item.get("sha256"), f"member {name} sha256")}
        )

    record_count = observed_data.get("data_record_count")
    distinct_samples = observed_data.get("distinct_sample_code_count")
    target_rows = observed_data.get("target_bearing_row_count")
    if not all(isinstance(value, int) and value >= 0 for value in (record_count, distinct_samples, target_rows)):
        raise SnapshotError("candidate record and sample counts must be non-negative integers")
    invalid_values = sum(
        profile.get("invalid_count", 0)
        for profile in observed_data.get("target_analytes", {}).values()
        if isinstance(profile, Mapping) and isinstance(profile.get("invalid_count", 0), int)
    )
    research_use_status = score_source_evidence.derive_research_use_status(entry)
    request = _request_contract(request_url)
    snapshot_id = f"{source_id}:{observed_at}:{archive_sha256[:12]}"
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "snapshot_id": snapshot_id,
        "snapshot_kind": "dynamic_api_snapshot",
        "source_id": source_id,
        "observed_at": observed_at,
        "request": request,
        "response": {
            "http_status": None,
            "http_status_evidence": "missing_from_original_acquisition_manifest",
            "content_type": acquisition.get("response_content_type"),
            "bytes": archive.get("bytes"),
            "sha256": archive_sha256,
            "publisher_checksum_available": bool(acquisition.get("publisher_checksum_available")),
        },
        "archive": {
            "filename": archive.get("filename"),
            "member_count": len(normalized_members),
            "members": normalized_members,
        },
        "counts": {
            "raw_records": record_count,
            "parsed_records": record_count,
            "rejected_records": 0,
            "failed_records": invalid_values,
            "distinct_samples": distinct_samples,
            "target_bearing_records": target_rows,
        },
        "actual_scope": {
            "latitude_range": observed_data.get("latitude_range"),
            "longitude_range": observed_data.get("longitude_range"),
            "cruise_years": observed_data.get("cruise_years"),
            "target_analytes": sorted(observed_data.get("target_analytes", {})),
        },
        "software": {
            "snapshot_tool_version": SNAPSHOT_VERSION,
            "candidate_verifier_version": candidate.get("verification_version"),
        },
        "research_use": {
            "status": research_use_status,
            "license_id": entry.get("license", {}).get("id"),
            "terms_url": entry.get("license", {}).get("url"),
            "attribution_note": entry.get("license", {}).get("notes"),
        },
        "evidence": {
            "candidate_evidence_path": evidence_path,
            "candidate_evidence_sha256": _canonical_sha256(candidate),
            "publisher_checksum_status": "missing" if not acquisition.get("publisher_checksum_available") else "verified",
            "content_addressed_snapshot": True,
        },
        "limitations": list(entry.get("limitations", [])),
        "claim_boundary": (
            "This project snapshot fixes one observed official API response by request, time and content hashes. "
            "It is not a publisher DOI or proof that the upstream dynamic service will return identical content later."
        ),
    }


def build_snapshot_from_paths(candidate_path: Path, catalog_path: Path = DEFAULT_CATALOG) -> dict[str, Any]:
    candidate = _read_json(candidate_path, "candidate evidence")
    catalog = source_router.load_catalog(catalog_path)
    try:
        evidence_path = str(candidate_path.resolve().relative_to(SKILL_DIR))
    except ValueError:
        evidence_path = str(candidate_path.resolve())
    return build_snapshot(candidate, catalog, evidence_path=evidence_path)


def diff_snapshots(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Report content, request and count changes without overwriting either snapshot."""

    if before.get("source_id") != after.get("source_id"):
        raise SnapshotError("snapshot diff requires the same source_id")
    before_members = {item["name"]: item for item in before.get("archive", {}).get("members", [])}
    after_members = {item["name"]: item for item in after.get("archive", {}).get("members", [])}
    added = sorted(set(after_members) - set(before_members))
    removed = sorted(set(before_members) - set(after_members))
    changed_members = sorted(
        name
        for name in set(before_members).intersection(after_members)
        if before_members[name] != after_members[name]
    )
    comparisons = {
        "request_changed": before.get("request", {}).get("canonical_request_sha256")
        != after.get("request", {}).get("canonical_request_sha256"),
        "response_changed": before.get("response", {}).get("sha256") != after.get("response", {}).get("sha256"),
        "counts_changed": before.get("counts") != after.get("counts"),
        "research_use_changed": before.get("research_use") != after.get("research_use"),
        "limitations_changed": before.get("limitations") != after.get("limitations"),
        "observation_time_changed": before.get("observed_at") != after.get("observed_at"),
    }
    content_changed = any(
        (
            comparisons["request_changed"],
            comparisons["response_changed"],
            comparisons["counts_changed"],
            comparisons["research_use_changed"],
            comparisons["limitations_changed"],
            bool(added),
            bool(removed),
            bool(changed_members),
        )
    )
    if content_changed:
        status = "changed"
    elif comparisons["observation_time_changed"] or before.get("snapshot_id") != after.get("snapshot_id"):
        status = "content_unchanged_new_observation"
    else:
        status = "identical"
    return {
        "diff_version": DIFF_VERSION,
        "source_id": before.get("source_id"),
        "before_snapshot_id": before.get("snapshot_id"),
        "after_snapshot_id": after.get("snapshot_id"),
        "status": status,
        "requires_rescore": content_changed,
        "comparisons": comparisons,
        "members": {"added": added, "removed": removed, "changed": changed_members},
        "claim_boundary": (
            "A snapshot diff reports observed request, content, inventory and metadata changes. "
            "It does not determine whether upstream scientific values are correct."
        ),
    }


def _write_or_print(value: Mapping[str, Any], output: Path | None) -> None:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create", help="Create a snapshot manifest from candidate evidence")
    create.add_argument("--candidate-evidence", type=Path, required=True)
    create.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    create.add_argument("--output", type=Path)
    diff = subparsers.add_parser("diff", help="Compare two snapshot manifests")
    diff.add_argument("--before", type=Path, required=True)
    diff.add_argument("--after", type=Path, required=True)
    diff.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "create":
            result = build_snapshot_from_paths(args.candidate_evidence, args.catalog)
        else:
            result = diff_snapshots(_read_json(args.before, "before snapshot"), _read_json(args.after, "after snapshot"))
        _write_or_print(result, args.output)
        return 0
    except (OSError, SnapshotError, source_router.SourceRoutingError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
