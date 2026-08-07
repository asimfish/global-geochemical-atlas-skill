#!/usr/bin/env python3
"""Audit representative D1 source claims against an independent frozen contract."""

from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = REPO_ROOT / "evaluation" / "evaluator_private" / "source_truth" / "source_truth_contract.json"
DEFAULT_DEMOS = REPO_ROOT / "skills" / "global-geochemical-atlas" / "fixtures" / "source-demos"
SOURCE_METADATA_FIELDS = (
    "source_id",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "license",
)
SPOT_FIELDS = (
    "source_record_id",
    "element_or_analyte",
    "value",
    "unit",
    "latitude",
    "longitude",
    "source_locator",
)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def display(value: Any) -> str:
    return "" if value is None else str(value)


def mismatch(path: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {"path": path, "expected": expected, "actual": actual}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{number} is not an object")
                rows.append(value)
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def validate_contract(contract: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if contract.get("schema_version") != "source-truth-contract-v1":
        errors.append(mismatch("schema_version", "source-truth-contract-v1", contract.get("schema_version")))
    sources = contract.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append(mismatch("sources", "non-empty array", type(sources).__name__))
        return errors
    ids = [item.get("source_id") for item in sources if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append(mismatch("sources[].source_id", "unique", ids))
    media = {item.get("medium") for item in sources if isinstance(item, dict)}
    required_media = set(contract.get("required_media") or [])
    if not required_media <= media:
        errors.append(mismatch("required_media coverage", sorted(required_media), sorted(media)))
    required = set(SOURCE_METADATA_FIELDS) | {
        "source_file", "source_file_sha256",
        "authority_url", "allowed_resolution_hosts", "medium", "spot_record"
    }
    for index, item in enumerate(sources):
        if not isinstance(item, dict):
            errors.append(mismatch(f"sources[{index}]", "object", type(item).__name__))
            continue
        missing = sorted(required - set(item))
        if missing:
            errors.append(mismatch(f"sources[{index}].required_fields", [], missing))
        spot = item.get("spot_record")
        if not isinstance(spot, dict) or set(SPOT_FIELDS) - set(spot):
            errors.append(
                mismatch(
                    f"sources[{index}].spot_record.fields",
                    sorted(SPOT_FIELDS),
                    sorted(spot) if isinstance(spot, dict) else type(spot).__name__,
                )
            )
        authority = urlparse(str(item.get("authority_url") or ""))
        if authority.scheme != "https" or not authority.hostname:
            errors.append(mismatch(f"sources[{index}].authority_url", "absolute HTTPS URL", item.get("authority_url")))
    return errors


def audit_demo(source: dict[str, Any], demos_root: Path) -> dict[str, Any]:
    source_id = source["source_id"]
    root = demos_root / source_id
    errors: list[dict[str, Any]] = []
    required_files = [root / "sources.jsonl", root / "demo_input.csv", root / "run_manifest.json"]
    missing = [str(path.relative_to(demos_root)) for path in required_files if not path.is_file()]
    if missing:
        return {"source_id": source_id, "status": "conflict", "mismatches": [mismatch("files", [], missing)]}

    try:
        source_rows = read_jsonl(required_files[0])
        demo_rows = read_csv(required_files[1])
        manifest = load_json(required_files[2])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {"source_id": source_id, "status": "conflict", "mismatches": [{"path": "parse", "error": str(exc)}]}
    if not source_rows or not demo_rows:
        errors.append(mismatch("record_count", "non-zero source and demo rows", {"sources": len(source_rows), "demo": len(demo_rows)}))

    for row_kind, rows in (("sources.jsonl", source_rows), ("demo_input.csv", demo_rows)):
        for row_index, row in enumerate(rows, 1):
            for field in SOURCE_METADATA_FIELDS:
                expected = display(source.get(field))
                actual = display(row.get(field))
                if actual != expected:
                    errors.append(mismatch(f"{row_kind}[{row_index}].{field}", expected, actual))
            if row_kind == "demo_input.csv" and display(row.get("medium")) != display(source["medium"]):
                errors.append(mismatch(f"{row_kind}[{row_index}].medium", source["medium"], row.get("medium")))
            hash_field = "source_file_sha256" if row_kind == "sources.jsonl" else "file_sha256"
            record_hash = display(row.get(hash_field))
            if not re.fullmatch(r"[0-9a-f]{64}", record_hash):
                errors.append(mismatch(f"{row_kind}[{row_index}].{hash_field}", "lowercase SHA-256", record_hash))
            locator = display(row.get("source_locator"))
            if not locator or "#row=" not in locator:
                errors.append(mismatch(f"{row_kind}[{row_index}].source_locator", "row-addressable locator", locator))

    expected_spot = {key: display(value) for key, value in source["spot_record"].items()}
    spot = next((row for row in demo_rows if row.get("source_record_id") == expected_spot["source_record_id"]), None)
    if spot is None:
        errors.append(mismatch("spot_record.source_record_id", expected_spot["source_record_id"], None))
    else:
        for field in SPOT_FIELDS:
            if display(spot.get(field)) != expected_spot[field]:
                errors.append(mismatch(f"spot_record.{field}", expected_spot[field], spot.get(field)))
        if display(spot.get("source_file")) != source["source_file"]:
            errors.append(mismatch("spot_record.source_file", source["source_file"], spot.get("source_file")))
        if display(spot.get("file_sha256")) != source["source_file_sha256"]:
            errors.append(mismatch("spot_record.file_sha256", source["source_file_sha256"], spot.get("file_sha256")))

    manifest_text = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    if source["source_file_sha256"] not in manifest_text:
        errors.append(mismatch("run_manifest source hash", source["source_file_sha256"], "not found"))
    if source_id not in manifest_text:
        errors.append(mismatch("run_manifest source_id", source_id, "not found"))

    return {
        "source_id": source_id,
        "medium": source["medium"],
        "status": "verified" if not errors else "conflict",
        "source_rows_checked": len(source_rows),
        "demo_rows_checked": len(demo_rows),
        "mismatches": errors,
    }


def online_resolution(source: dict[str, Any], timeout: float) -> dict[str, Any]:
    url = source["authority_url"]
    request = urllib.request.Request(url, headers={"User-Agent": "gga-source-truth-audit/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            status_code = response.status
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {"status": "unreachable", "authority_url": url, "error": str(exc)}
    final_host = (urlparse(final_url).hostname or "").casefold()
    allowed = {str(host).casefold() for host in source["allowed_resolution_hosts"]}
    if final_host not in allowed:
        return {
            "status": "conflict",
            "authority_url": url,
            "final_url": final_url,
            "error": f"redirected to unapproved host: {final_host}",
        }
    return {"status": "verified", "authority_url": url, "final_url": final_url, "http_status": status_code}


def run_audit(contract_path: Path, demos_root: Path, online: bool, timeout: float) -> dict[str, Any]:
    contract = load_json(contract_path)
    contract_errors = validate_contract(contract)
    source_results = [] if contract_errors else [audit_demo(source, demos_root) for source in contract["sources"]]
    if online and not contract_errors:
        for result, source in zip(source_results, contract["sources"]):
            result["online_resolution"] = online_resolution(source, timeout)

    offline_conflict = bool(contract_errors) or any(item["status"] == "conflict" for item in source_results)
    online_conflict = any((item.get("online_resolution") or {}).get("status") == "conflict" for item in source_results)
    unreachable = [
        item["source_id"]
        for item in source_results
        if (item.get("online_resolution") or {}).get("status") == "unreachable"
    ]
    if offline_conflict or online_conflict:
        status = "conflict"
    elif unreachable:
        status = "needs_human_review"
    else:
        status = "verified"
    return {
        "schema_version": "source-truth-audit-report-v1",
        "status": status,
        "blocking_gate_passed": not (offline_conflict or online_conflict),
        "human_review_required": bool(unreachable),
        "online_check_requested": online,
        "contract": str(contract_path),
        "contract_verified_at": contract.get("verified_at"),
        "contract_errors": contract_errors,
        "sources_checked": len(source_results),
        "media_checked": sorted({item.get("medium") for item in source_results}),
        "unreachable_sources": unreachable,
        "source_results": source_results,
        "claim_boundary": contract.get("claim_boundary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--demos-root", type=Path, default=DEFAULT_DEMOS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--online", action="store_true", help="also resolve authority URLs; network failures require review")
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args()
    report = run_audit(args.contract.resolve(), args.demos_root.resolve(), args.online, args.timeout_seconds)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "blocking_gate_passed", "human_review_required", "sources_checked")}, sort_keys=True))
    if report["status"] == "conflict":
        return 74
    if report["status"] == "needs_human_review":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
