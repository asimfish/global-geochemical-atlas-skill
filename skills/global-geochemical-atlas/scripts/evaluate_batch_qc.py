#!/usr/bin/env python3
"""Evaluate laboratory CRM, blank and duplicate batch acceptance deterministically.

The input is a small, normalized laboratory-QC table.  The tool deliberately
does not guess missing controls, certified values, units, or acceptance limits.
It can emit a physical CSV/report for the production workflow or a logical CSV
container on stdout for benchmark tasks that forbid extra physical artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


REPORT_VERSION = "geochemical-batch-qc-report-v1"
OUTPUT_COLUMNS = (
    "batch_id",
    "crm_recovery_percent",
    "crm_pass",
    "blank_value",
    "blank_pass",
    "duplicate_rpd_percent",
    "duplicate_pass",
    "batch_pass",
    "disposition",
)
REQUIRED_INPUT_COLUMNS = {"batch_id", "qc_type", "qc_id", "value", "certified_value", "pair_id"}
VALID_QC_TYPES = {"CRM", "BLANK", "DUPLICATE"}


class BatchQCError(ValueError):
    """Raised when a batch QC input or policy is unsafe or ambiguous."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_number(value: Any, label: str, *, positive: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise BatchQCError(f"{label} must be numeric") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        qualifier = "positive" if positive else "non-negative"
        raise BatchQCError(f"{label} must be a finite {qualifier} number")
    return number


def read_policy(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BatchQCError(f"QC policy does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BatchQCError(f"QC policy is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise BatchQCError("QC policy must be a JSON object")
    allowed = {
        "schema_version", "version", "crm_recovery_percent", "blank_maximum",
        "duplicate_rpd_maximum_percent", "batch_rule", "unit",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BatchQCError(f"QC policy has unsupported keys: {', '.join(unknown)}")
    version_fields = [key for key in ("schema_version", "version") if key in value]
    if len(version_fields) != 1:
        raise BatchQCError("QC policy requires exactly one of schema_version or version")
    version = value[version_fields[0]]
    if not isinstance(version, str) or not version.strip():
        raise BatchQCError("QC policy version must be a non-empty string")
    recovery = value.get("crm_recovery_percent")
    if not isinstance(recovery, dict) or set(recovery) != {"minimum", "maximum", "inclusive"}:
        raise BatchQCError(
            "crm_recovery_percent must contain exactly minimum, maximum and inclusive"
        )
    minimum = finite_number(recovery["minimum"], "CRM recovery minimum")
    maximum = finite_number(recovery["maximum"], "CRM recovery maximum")
    if minimum > maximum or not isinstance(recovery["inclusive"], bool):
        raise BatchQCError("CRM recovery bounds are invalid")
    blank_maximum = finite_number(value.get("blank_maximum"), "blank maximum")
    duplicate_maximum = finite_number(
        value.get("duplicate_rpd_maximum_percent"), "duplicate RPD maximum"
    )
    if value.get("batch_rule") != "all_checks_must_pass":
        raise BatchQCError("batch_rule must be all_checks_must_pass")
    unit = value.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise BatchQCError("policy unit must be a non-empty string when supplied")
    return {
        "schema_version": str(version),
        "crm_recovery_percent": {
            "minimum": minimum,
            "maximum": maximum,
            "inclusive": recovery["inclusive"],
        },
        "blank_maximum": blank_maximum,
        "duplicate_rpd_maximum_percent": duplicate_maximum,
        "batch_rule": "all_checks_must_pass",
        "unit": unit.strip() if isinstance(unit, str) else None,
    }


def read_rows(path: Path, policy_unit: str | None) -> list[dict[str, Any]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise BatchQCError(f"batch QC CSV is unreadable: {path}") from exc
    with handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        missing = sorted(REQUIRED_INPUT_COLUMNS - set(headers))
        if missing:
            raise BatchQCError(f"batch QC CSV lacks columns: {', '.join(missing)}")
        if len(headers) != len(set(headers)):
            raise BatchQCError("batch QC CSV has duplicate columns")
        rows: list[dict[str, Any]] = []
        seen_ids: set[tuple[str, str]] = set()
        for line_number, raw in enumerate(reader, start=2):
            batch_id = str(raw.get("batch_id") or "").strip()
            qc_type = str(raw.get("qc_type") or "").strip().upper()
            qc_id = str(raw.get("qc_id") or "").strip()
            if not batch_id or not qc_id:
                raise BatchQCError(f"batch QC CSV:{line_number} lacks batch_id or qc_id")
            if qc_type not in VALID_QC_TYPES:
                raise BatchQCError(f"batch QC CSV:{line_number} has unsupported qc_type {qc_type!r}")
            identity = (batch_id, qc_id)
            if identity in seen_ids:
                raise BatchQCError(f"batch QC CSV:{line_number} repeats qc_id within batch")
            seen_ids.add(identity)
            unit = str(raw.get("unit") or "").strip() or None
            if policy_unit is not None and unit != policy_unit:
                raise BatchQCError(
                    f"batch QC CSV:{line_number} unit must equal policy unit {policy_unit!r}"
                )
            row = {
                "batch_id": batch_id,
                "qc_type": qc_type,
                "qc_id": qc_id,
                "value": finite_number(raw.get("value"), f"batch QC CSV:{line_number} value"),
                "certified_value": None,
                "pair_id": str(raw.get("pair_id") or "").strip() or None,
                "unit": unit,
                "line_number": line_number,
            }
            certified = str(raw.get("certified_value") or "").strip()
            if qc_type == "CRM":
                row["certified_value"] = finite_number(
                    certified, f"batch QC CSV:{line_number} certified_value", positive=True
                )
            elif certified:
                raise BatchQCError(
                    f"batch QC CSV:{line_number} certified_value is only valid for CRM rows"
                )
            if qc_type == "DUPLICATE" and row["pair_id"] is None:
                raise BatchQCError(f"batch QC CSV:{line_number} duplicate row lacks pair_id")
            if qc_type != "DUPLICATE" and row["pair_id"] is not None:
                raise BatchQCError(
                    f"batch QC CSV:{line_number} pair_id is only valid for DUPLICATE rows"
                )
            rows.append(row)
    if not rows:
        raise BatchQCError("batch QC CSV has no data rows")
    return rows


def rpd(first: float, second: float) -> float:
    denominator = (first + second) / 2.0
    if denominator == 0:
        return 0.0
    return abs(first - second) / denominator * 100.0


def within(value: float, minimum: float, maximum: float, inclusive: bool) -> bool:
    return minimum <= value <= maximum if inclusive else minimum < value < maximum


def worst_recovery(values: Sequence[float]) -> float | None:
    return max(values, key=lambda item: (abs(item - 100.0), item)) if values else None


def evaluate(input_path: Path, policy_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    policy = read_policy(policy_path)
    rows = read_rows(input_path, policy["unit"])
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["batch_id"]].append(row)

    acceptance: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    recovery_policy = policy["crm_recovery_percent"]
    for batch_id in sorted(grouped):
        batch_rows = grouped[batch_id]
        crm_checks = []
        for row in batch_rows:
            if row["qc_type"] != "CRM":
                continue
            recovery = row["value"] / row["certified_value"] * 100.0
            crm_checks.append({
                "qc_id": row["qc_id"],
                "observed_value": row["value"],
                "certified_value": row["certified_value"],
                "recovery_percent": recovery,
                "pass": within(
                    recovery,
                    recovery_policy["minimum"],
                    recovery_policy["maximum"],
                    recovery_policy["inclusive"],
                ),
            })
        blank_checks = [
            {
                "qc_id": row["qc_id"],
                "value": row["value"],
                "pass": row["value"] <= policy["blank_maximum"],
            }
            for row in batch_rows
            if row["qc_type"] == "BLANK"
        ]
        pair_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in batch_rows:
            if row["qc_type"] == "DUPLICATE":
                pair_rows[str(row["pair_id"])].append(row)
        duplicate_checks = []
        malformed_pairs: list[str] = []
        for pair_id in sorted(pair_rows):
            pair = pair_rows[pair_id]
            if len(pair) != 2:
                malformed_pairs.append(pair_id)
                continue
            pair_rpd = rpd(pair[0]["value"], pair[1]["value"])
            duplicate_checks.append({
                "pair_id": pair_id,
                "qc_ids": [pair[0]["qc_id"], pair[1]["qc_id"]],
                "values": [pair[0]["value"], pair[1]["value"]],
                "rpd_percent": pair_rpd,
                "pass": pair_rpd <= policy["duplicate_rpd_maximum_percent"],
            })

        incomplete = []
        if not crm_checks:
            incomplete.append("missing_crm")
        if not blank_checks:
            incomplete.append("missing_blank")
        if not duplicate_checks:
            incomplete.append("missing_complete_duplicate_pair")
        if malformed_pairs:
            incomplete.append("duplicate_pair_must_contain_exactly_two_rows")
        crm_pass = bool(crm_checks) and all(item["pass"] for item in crm_checks)
        blank_pass = bool(blank_checks) and all(item["pass"] for item in blank_checks)
        duplicate_pass = (
            bool(duplicate_checks)
            and not malformed_pairs
            and all(item["pass"] for item in duplicate_checks)
        )
        batch_pass = not incomplete and crm_pass and blank_pass and duplicate_pass
        recoveries = [item["recovery_percent"] for item in crm_checks]
        blank_values = [item["value"] for item in blank_checks]
        duplicate_values = [item["rpd_percent"] for item in duplicate_checks]
        row = {
            "batch_id": batch_id,
            "crm_recovery_percent": worst_recovery(recoveries),
            "crm_pass": crm_pass,
            "blank_value": max(blank_values) if blank_values else None,
            "blank_pass": blank_pass,
            "duplicate_rpd_percent": max(duplicate_values) if duplicate_values else None,
            "duplicate_pass": duplicate_pass,
            "batch_pass": batch_pass,
            "disposition": (
                "accept_for_scientific_analysis"
                if batch_pass
                else "exclude_batch_and_investigate"
            ),
        }
        acceptance.append(row)
        details.append({
            "batch_id": batch_id,
            "status": "pass" if batch_pass else "incomplete" if incomplete else "fail",
            "incomplete_reasons": incomplete,
            "malformed_duplicate_pair_ids": malformed_pairs,
            "crm_checks": crm_checks,
            "blank_checks": blank_checks,
            "duplicate_checks": duplicate_checks,
            "batch_pass": batch_pass,
            "disposition": row["disposition"],
        })

    passed = sum(bool(item["batch_pass"]) for item in acceptance)
    report = {
        "schema_version": REPORT_VERSION,
        "status": "evaluated",
        "input_sha256": sha256_file(input_path),
        "policy_sha256": sha256_file(policy_path),
        "policy": policy,
        "formulae": {
            "crm_recovery_percent": "observed / certified * 100",
            "duplicate_rpd_percent": "abs(x1-x2) / ((x1+x2)/2) * 100",
            "crm_summary": "worst absolute deviation from 100 percent",
            "blank_summary": "maximum blank value",
            "duplicate_summary": "maximum complete-pair RPD",
        },
        "batch_rule": "all CRM, blank and duplicate checks must pass",
        "batch_count": len(acceptance),
        "passed_batch_count": passed,
        "failed_or_incomplete_batch_count": len(acceptance) - passed,
        "batch_results": details,
        "scientific_boundary": (
            "Batch acceptance gates analytical comparability only; it does not prove measurement truth "
            "or establish an anomaly cause. Failed and incomplete batches remain traceable."
        ),
    }
    return acceptance, report


def display_number(value: Any) -> str:
    if value is None:
        return ""
    return format(float(value), ".12g")


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for item in rows:
            row = dict(item)
            for field in ("crm_recovery_percent", "blank_value", "duplicate_rpd_percent"):
                row[field] = display_number(row[field])
            for field in ("crm_pass", "blank_pass", "duplicate_pass", "batch_pass"):
                row[field] = "true" if row[field] else "false"
            writer.writerow(row)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def logical_csv(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "format": "csv",
        "columns": list(OUTPUT_COLUMNS),
        "rows": [{column: row.get(column) for column in OUTPUT_COLUMNS} for row in rows],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate CRM recovery, blank maximum and duplicate RPD with a supplied batch policy."
    )
    parser.add_argument("--input", required=True, type=Path, help="Normalized laboratory QC CSV")
    parser.add_argument("--policy", required=True, type=Path, help="Explicit JSON acceptance policy")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Optional directory for batch_acceptance.csv and batch_qc_report.json",
    )
    parser.add_argument(
        "--stdout-contract",
        action="store_true",
        help="Print the candidate-visible logical CSV object instead of a path summary",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        rows, report = evaluate(args.input, args.policy)
        if args.output_dir is not None:
            write_csv(args.output_dir / "batch_acceptance.csv", rows)
            write_report(args.output_dir / "batch_qc_report.json", report)
    except (BatchQCError, OSError) as exc:
        parser.error(str(exc))
    if args.stdout_contract:
        print(json.dumps(logical_csv(rows), ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps({
            "status": report["status"],
            "batch_count": report["batch_count"],
            "passed_batch_count": report["passed_batch_count"],
            "output_dir": str(args.output_dir) if args.output_dir is not None else None,
        }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
