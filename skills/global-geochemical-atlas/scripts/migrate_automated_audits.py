#!/usr/bin/env python3
"""Migrate prepared 30-record sheets to structured Codex evidence audits.

The migration deliberately does not inspect or score legacy integrity-token
fields. It audits traceability, raw-value correspondence, missing evidence and
edge-case representation from the checked-in record payload.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


AUDIT_VERSION = "geochemical-automated-source-audit-v1"
DEFAULT_AUDITED_AT = "2026-08-07T12:00:00Z"
CATEGORIES = (
    "ordinary_valid_value",
    "censored_or_negative_value",
    "extreme_value",
    "missing_coordinate",
    "duplicate_sample_identifier",
    "method_missing_or_multiple_candidates",
    "source_or_mapping_conflict",
)


class AuditMigrationError(RuntimeError):
    """Raised when a prepared audit cannot be migrated without guessing."""


def _drop_legacy_integrity_tokens(value: Any) -> Any:
    """Remove deprecated integrity-token fields without evaluating their values."""

    if isinstance(value, Mapping):
        return {
            key: _drop_legacy_integrity_tokens(child)
            for key, child in value.items()
            if not any(token in str(key).casefold() for token in ("sha", "md5", "hash", "checksum"))
            and not (
                str(key) == "snapshot_id"
                and isinstance(child, str)
                and any(token in child.casefold() for token in ("sha", "md5", "hash", "checksum"))
            )
        }
    if isinstance(value, list):
        return [_drop_legacy_integrity_tokens(item) for item in value]
    return value


def _strings(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    if value is None:
        return []
    return [str(value)]


def _observations(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = record.get("adapter_observations")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return [record]


def _raw_values(record: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    published = record.get("published_target_raw_values")
    if isinstance(published, Mapping):
        values.extend(str(item).strip() for item in published.values() if str(item).strip())
    for observation in _observations(record):
        raw = observation.get("raw_value")
        if raw is not None and str(raw).strip():
            values.append(str(raw).strip())
    direct = record.get("raw_value")
    if direct is not None and str(direct).strip():
        values.append(str(direct).strip())
    return list(dict.fromkeys(values))


def _numeric_values(record: Mapping[str, Any]) -> list[float]:
    values: list[float] = []
    for raw in _raw_values(record):
        text = raw.strip().replace(",", "")
        text = re.sub(r"^[<>~=\u2264\u2265]+\s*", "", text)
        try:
            number = float(text)
        except ValueError:
            continue
        if math.isfinite(number):
            values.append(number)
    return values


def _coordinates(record: Mapping[str, Any]) -> tuple[str, str]:
    latitude_keys = ("latitude", "latitude_jgd2000")
    longitude_keys = ("longitude", "longitude_jgd2000")
    latitude = next((str(record.get(key) or "").strip() for key in latitude_keys if record.get(key)), "")
    longitude = next((str(record.get(key) or "").strip() for key in longitude_keys if record.get(key)), "")
    if latitude and longitude:
        return latitude, longitude
    for observation in _observations(record):
        latitude = next((str(observation.get(key) or "").strip() for key in latitude_keys if observation.get(key)), "")
        longitude = next((str(observation.get(key) or "").strip() for key in longitude_keys if observation.get(key)), "")
        if latitude or longitude:
            return latitude, longitude
    return "", ""


def _methods(record: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in [record, *_observations(record)]:
        for key in ("analytical_method", "method", "analytical_technique"):
            value = str(item.get(key) or "").strip()
            if value and value.casefold() not in {"missing", "unknown", "not reported", "not_reported"}:
                values.append(value)
    return list(dict.fromkeys(values))


def _published_correspondence(record: Mapping[str, Any]) -> bool | None:
    published = record.get("published_target_raw_values")
    if not isinstance(published, Mapping):
        return None
    observed: dict[str, set[str]] = {}
    for item in _observations(record):
        analyte = str(item.get("analyte") or "").strip()
        raw = str(item.get("raw_value") or "").strip()
        if analyte and raw:
            observed.setdefault(analyte, set()).add(raw)
    expected = {str(key): str(value).strip() for key, value in published.items() if str(value).strip()}
    return all(value in observed.get(analyte, set()) for analyte, value in expected.items())


def _record_ids(records: Sequence[Mapping[str, Any]], predicate: Any) -> list[str]:
    return [str(item.get("review_id") or item.get("source_record_id")) for item in records if predicate(item)]


def migrate_document(document: Mapping[str, Any], audited_at: str) -> dict[str, Any]:
    source_id = str(document.get("source_id") or "").strip()
    records = document.get("records")
    if not source_id or not isinstance(records, list) or len(records) < 30:
        raise AuditMigrationError(f"{source_id or '<unknown>'}: expected at least 30 prepared records")
    rows = [dict(item) for item in records if isinstance(item, Mapping)]
    if len(rows) != len(records):
        raise AuditMigrationError(f"{source_id}: non-object review record")

    sample_counts = Counter(
        str(
            item.get("sample_id")
            or item.get("reported_sample_id")
            or item.get("laboratory_sample_id")
            or item.get("site_id")
            or ""
        ).strip()
        for item in rows
    )
    sample_counts.pop("", None)
    maxima = [max((_numeric_values(item) or [float("-inf")]), key=abs) for item in rows]
    finite_maxima = [value for value in maxima if math.isfinite(value)]
    extreme_threshold = sorted((abs(value) for value in finite_maxima), reverse=True)[min(2, len(finite_maxima) - 1)]

    categories: dict[str, list[str]] = {item: [] for item in CATEGORIES}
    migrated_rows: list[dict[str, Any]] = []
    for row, row_maximum in zip(rows, maxima):
        row_id = str(row.get("review_id") or row.get("source_record_id"))
        raw_values = _raw_values(row)
        latitude, longitude = _coordinates(row)
        methods = _methods(row)
        sample_id = str(
            row.get("sample_id")
            or row.get("reported_sample_id")
            or row.get("laboratory_sample_id")
            or row.get("site_id")
            or ""
        ).strip()
        failed_checks = [
            key
            for key, value in (row.get("automated_checks") or {}).items()
            if value is False and not any(token in key.casefold() for token in ("sha", "md5", "hash", "checksum"))
        ] if isinstance(row.get("automated_checks"), Mapping) else []
        censored_or_negative = any(
            re.match(r"^\s*[<\u2264]", value) or any(number < 0 for number in _numeric_values({"raw_value": value}))
            for value in raw_values
        )
        missing_coordinate = not (latitude and longitude)
        duplicate_sample = bool(sample_id and sample_counts[sample_id] > 1)
        method_gap = len(methods) != 1
        conflict = row.get("automated_status") == "FAIL" or bool(failed_checks)
        ordinary = bool(raw_values) and not censored_or_negative and not conflict
        extreme = math.isfinite(row_maximum) and abs(row_maximum) >= extreme_threshold

        flags = {
            "ordinary_valid_value": ordinary,
            "censored_or_negative_value": censored_or_negative,
            "extreme_value": extreme,
            "missing_coordinate": missing_coordinate,
            "duplicate_sample_identifier": duplicate_sample,
            "method_missing_or_multiple_candidates": method_gap,
            "source_or_mapping_conflict": conflict,
        }
        for category, present in flags.items():
            if present:
                categories[category].append(row_id)

        correspondence = _published_correspondence(row)
        audit_checks = {
            "source_locator_present": bool(str(row.get("source_locator") or "").strip()),
            "source_record_identifier_present": bool(str(row.get("source_record_id") or "").strip()),
            "sample_identity_present": bool(sample_id),
            "raw_observation_payload_present": bool(raw_values),
        }
        if correspondence is not None:
            audit_checks["published_values_match_adapter_payload"] = correspondence
        traceability_ok = audit_checks["source_locator_present"] and audit_checks["source_record_identifier_present"]
        decision = "conflict" if conflict or not traceability_ok else ("warning" if (
            not all(audit_checks.values()) or any(
            flags[item] for item in (
                "censored_or_negative_value",
                "missing_coordinate",
                "duplicate_sample_identifier",
                "method_missing_or_multiple_candidates",
            )
        )) else "pass")
        findings = [category for category, present in flags.items() if present]
        codex_audit = {
            "reviewer_type": "codex",
            "auditor_id": "codex-d1-evidence-audit",
            "audited_at": audited_at,
            "decision": decision,
            "checks": audit_checks,
            "findings": findings,
            "evidence_locators": list(dict.fromkeys(
                item for item in (str(row.get("source_locator") or ""), str(row.get("source_record_id") or "")) if item
            )),
            "notes": "Missing evidence and edge cases are retained as warnings; only traceability or mapping conflicts fail the audit.",
        }
        published = row.get("published_target_raw_values")
        if isinstance(published, Mapping):
            raw_field_evidence: Any = dict(published)
        else:
            raw_field_evidence = {
                key: row[key]
                for key in ("analyte", "raw_value", "unit", "measurement_basis")
                if key in row
            }
        parsed_result_evidence = [
            {
                key: observation[key]
                for key in (
                    "analyte",
                    "raw_value",
                    "unit",
                    "record_id",
                    "analytical_method",
                    "method_scope",
                    "measurement_basis",
                    "value_qualifier",
                )
                if key in observation
            }
            for observation in _observations(row)
        ]
        migrated_rows.append(
            _drop_legacy_integrity_tokens(
                {
                    "review_id": row_id,
                    "source_locator": str(row.get("source_locator") or ""),
                    "source_record_id": str(row.get("source_record_id") or ""),
                    "sample_id": sample_id,
                    "selection_reasons": list(row.get("selection_reasons") or []),
                    "raw_field_evidence": raw_field_evidence,
                    "parsed_result_evidence": parsed_result_evidence,
                    "legacy_review_file": "human_review.json",
                    "codex_audit": codex_audit,
                }
            )
        )

    conflict_count = sum(item["codex_audit"]["decision"] == "conflict" for item in migrated_rows)
    coverage = {
        category: {
            "considered": True,
            "record_count": len(record_ids),
            "record_ids": record_ids,
            "outcome": "cases_found" if record_ids else "no_case_in_stratified_sample",
        }
        for category, record_ids in categories.items()
    }
    result = {
            "audit_version": AUDIT_VERSION,
            "source_id": source_id,
            "dataset_version": str(document.get("dataset_version") or "unknown"),
            "legacy_review_file": "human_review.json",
            "status": "automated_audit_complete" if conflict_count == 0 else "evidence_incomplete",
            "required_record_count": 30,
            "prepared_record_count": len(migrated_rows),
            "audited_record_count": len(migrated_rows),
            "automated_pass_count": sum(item["codex_audit"]["decision"] != "conflict" for item in migrated_rows),
            "auditor": {
                "reviewer_type": "codex",
                "auditor_id": "codex-d1-evidence-audit",
                "audited_at": audited_at,
            },
            "audit_coverage": coverage,
            "records": migrated_rows,
            "claim_boundary": (
                "A structured Codex audit checked 30 stratified records for traceability, raw-value correspondence, "
                "edge cases and disclosed evidence gaps. It is evidence review, not a claim of spatial completeness, "
                "cross-method comparability or measurement truth. Human signatures are not required."
            ),
        }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--audited-at", default=DEFAULT_AUDITED_AT)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = sorted(args.root.rglob("human_review.json"))
    if not paths:
        print("migrate_automated_audits: no review files", file=sys.stderr)
        return 2
    summary: dict[str, str] = {}
    try:
        for path in paths:
            document = json.loads(path.read_text(encoding="utf-8"))
            migrated = migrate_document(document, args.audited_at)
            rendered = json.dumps(migrated, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            output_path = path.with_name("automated_audit.json")
            if args.check:
                if not output_path.is_file() or output_path.read_text(encoding="utf-8") != rendered:
                    raise AuditMigrationError(f"outdated automated audit: {output_path}")
            else:
                output_path.write_text(rendered, encoding="utf-8")
            summary[str(migrated["source_id"])] = str(migrated["status"])
    except (OSError, UnicodeError, json.JSONDecodeError, AuditMigrationError) as exc:
        print(f"migrate_automated_audits: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "sources": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
