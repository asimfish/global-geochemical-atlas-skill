#!/usr/bin/env python3
"""Inspect a MarChem inorganic export without treating it as analysis-ready.

The script is deliberately source-specific: it records the raw archive inventory,
profiles the four hackathon target analytes, checks the batch-level method table,
and prepares a deterministic 30-row sample for later human review.  It does not
download data, normalize censored values, or change source acceptance status.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

TARGET_COLUMNS = {
    "As": "As_ICPOES_mg/kg",
    "Cu": "Cu_ICPOES_mg/kg",
    "Ni": "Ni_ICPOES_mg/kg",
    "Zn": "Zn_ICPOES_mg/kg",
}
VALUE_PATTERN = re.compile(r"^\s*([<>])?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*$")


class VerificationError(RuntimeError):
    """Raised when the observed export does not match the documented contract."""


def read_csv(payload: bytes) -> list[dict[str, str]]:
    text = payload.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def one_member(names: Iterable[str], pattern: re.Pattern[str], label: str) -> str:
    matches = [name for name in names if pattern.fullmatch(name)]
    if len(matches) != 1:
        raise VerificationError(f"expected one {label} member, observed {matches}")
    return matches[0]


def parse_value(raw_value: str) -> tuple[str, float | None]:
    raw = raw_value.strip()
    if not raw:
        return "missing", None
    match = VALUE_PATTERN.fullmatch(raw)
    if not match:
        return "invalid", None
    qualifier, numeric_text = match.groups()
    if qualifier == "<":
        return "censored_lt", float(numeric_text)
    if qualifier == ">":
        return "censored_gt", float(numeric_text)
    return "numeric", float(numeric_text)


def value_profiles(rows: Sequence[dict[str, str]]) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for element, column in TARGET_COLUMNS.items():
        statuses: Counter[str] = Counter()
        parsed: list[float] = []
        for row in rows:
            status, value = parse_value(row.get(column, ""))
            statuses[status] += 1
            if value is not None:
                parsed.append(value)
        profiles[element] = {
            "source_column": column,
            "reported_unit": "mg/kg",
            "weight_basis": "dry",
            "record_count": len(rows),
            "present_count": len(rows) - statuses["missing"],
            "missing_count": statuses["missing"],
            "numeric_count": statuses["numeric"],
            "censored_lt_count": statuses["censored_lt"],
            "censored_gt_count": statuses["censored_gt"],
            "invalid_count": statuses["invalid"],
            "reported_numeric_min": min(parsed) if parsed else None,
            "reported_numeric_max": max(parsed) if parsed else None,
        }
    return profiles


def metadata_profile(rows: Sequence[dict[str, str]]) -> dict[str, Any]:
    target_codes = {f"{element}_ICPOES" for element in TARGET_COLUMNS}
    target_rows = [row for row in rows if row.get("Lab_parameter_code") in target_codes]
    accreditation: Counter[str] = Counter()
    batches_by_element: dict[str, set[str]] = defaultdict(set)
    limits_by_element: dict[str, set[str]] = defaultdict(set)
    for row in target_rows:
        comment = row.get("Comment", "").strip().lower()
        if comment.startswith("not accredited"):
            accreditation["not_accredited"] += 1
        elif comment.startswith("accredited"):
            accreditation["accredited"] += 1
        else:
            accreditation["unclear"] += 1
        element = row["Lab_parameter_code"].split("_", 1)[0]
        if row.get("Batch"):
            batches_by_element[element].add(row["Batch"])
        if row.get("LLQ"):
            limits_by_element[element].add(row["LLQ"])
    comments = "\n".join(row.get("Comment", "") for row in target_rows).lower()
    preparation = "\n".join(row.get("Sample_preparation_method", "") for row in target_rows).lower()
    return {
        "metadata_record_count": len(rows),
        "target_metadata_record_count": len(target_rows),
        "target_batches": {key: sorted(value) for key, value in sorted(batches_by_element.items())},
        "target_llq_values_mg_per_kg": {
            key: sorted(value, key=float) for key, value in sorted(limits_by_element.items())
        },
        "accreditation_rows": {
            status: accreditation.get(status, 0)
            for status in ("accredited", "not_accredited", "unclear")
        },
        "partial_digestion_disclosed": (
            "partial" in comments
            or "partiell" in comments
            or "partiell" in preparation
        ),
        "not_total_content_disclosed": (
            "not total" in comments
            or "ikke total" in comments
            or "ikke totalt" in comments
            or "representerer ikke total" in comments
        ),
    }


def row_reasons(row: dict[str, str]) -> set[str]:
    reasons: set[str] = set()
    statuses = [parse_value(row.get(column, ""))[0] for column in TARGET_COLUMNS.values()]
    if "missing" in statuses:
        reasons.add("target_missing")
    if any(status.startswith("censored_") for status in statuses):
        reasons.add("target_censored")
    if all(status == "numeric" for status in statuses):
        reasons.add("all_targets_numeric")
    return reasons


def audit_sample(rows: Sequence[dict[str, str]], size: int = 30) -> list[dict[str, Any]]:
    if not rows:
        return []
    selected: dict[int, set[str]] = defaultdict(set)

    def select(index: int, reason: str) -> None:
        if 0 <= index < len(rows):
            selected[index].add(reason)

    for index in (0, len(rows) - 1, len(rows) // 4, len(rows) // 2, 3 * len(rows) // 4):
        select(index, "position_boundary")

    seen_years: set[str] = set()
    seen_batches: set[str] = set()
    seen_categories: set[str] = set()
    for index, row in enumerate(rows):
        year = row.get("Cruise_year", "")
        batch = row.get("Batch_code", "")
        if year and year not in seen_years:
            select(index, "first_for_cruise_year")
            seen_years.add(year)
        if batch and batch not in seen_batches:
            select(index, "first_for_batch")
            seen_batches.add(batch)
        for reason in sorted(row_reasons(row)):
            if reason not in seen_categories:
                select(index, reason)
                seen_categories.add(reason)

    for element, column in TARGET_COLUMNS.items():
        parsed = [
            (parse_value(row.get(column, ""))[1], index)
            for index, row in enumerate(rows)
            if parse_value(row.get(column, ""))[1] is not None
        ]
        if parsed:
            select(min(parsed)[1], f"{element}_reported_min")
            select(max(parsed)[1], f"{element}_reported_max")

    if len(selected) < min(size, len(rows)):
        denominator = max(1, min(size, len(rows)) - 1)
        for ordinal in range(min(size, len(rows))):
            index = round(ordinal * (len(rows) - 1) / denominator)
            select(index, "evenly_spaced_fill")
            if len(selected) >= min(size, len(rows)):
                break

    chosen = sorted(selected)[: min(size, len(rows))]
    result = []
    for index in chosen:
        row = rows[index]
        result.append(
            {
                "source_row_number": index + 2,
                "sample_code": row.get("Sample_code"),
                "batch_code": row.get("Batch_code"),
                "cruise_year": row.get("Cruise_year"),
                "longitude": row.get("Longitude"),
                "latitude": row.get("Latitude"),
                "target_raw_values": {
                    element: row.get(column, "") for element, column in TARGET_COLUMNS.items()
                },
                "selection_reasons": sorted(selected[index]),
            }
        )
    return result


def verify(
    path: Path,
    request_url: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    archive_bytes = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        data_name = one_member(
            names,
            re.compile(r"MarChem_Inorganic_Data_\d{8}T\d{6}Z\.csv"),
            "data",
        )
        metadata_name = one_member(
            names,
            re.compile(r"MetaData/MarChem_Inorganic_LabParameter_\d{8}T\d{6}Z\.csv"),
            "metadata",
        )
        info_name = one_member(
            names,
            re.compile(r"MarChem_Info_\d{8}T\d{6}Z"),
            "information",
        )
        members = []
        payloads: dict[str, bytes] = {}
        for info in archive.infolist():
            payload = archive.read(info.filename)
            payloads[info.filename] = payload
            members.append(
                {
                    "name": info.filename,
                    "bytes": info.file_size,
                }
            )

    data_rows = read_csv(payloads[data_name])
    metadata_rows = read_csv(payloads[metadata_name])
    if not data_rows:
        raise VerificationError("data member has no records")
    missing_columns = sorted(set(TARGET_COLUMNS.values()) - set(data_rows[0]))
    if missing_columns:
        raise VerificationError(f"missing target columns: {missing_columns}")

    numeric_coordinates = [
        (float(row["Longitude"]), float(row["Latitude"]))
        for row in data_rows
        if row.get("Longitude") and row.get("Latitude")
    ]
    years = sorted({row.get("Cruise_year", "") for row in data_rows if row.get("Cruise_year")})
    batches = sorted({row.get("Batch_code", "") for row in data_rows if row.get("Batch_code")})
    samples = [row.get("Sample_code", "") for row in data_rows]
    sample_counts = Counter(samples)
    target_rows_by_sample: Counter[str] = Counter()
    target_bearing_row_count = 0
    for row in data_rows:
        if any(row.get(column, "").strip() for column in TARGET_COLUMNS.values()):
            target_bearing_row_count += 1
            target_rows_by_sample[row.get("Sample_code", "")] += 1
    sample = audit_sample(data_rows)
    return {
        "verification_version": "marchem-candidate-verification-v1",
        "source_id": "norway-marchem",
        "acquisition": {
            "request_url": request_url,
            "observed_at": observed_at,
            "response_content_type": "application/zip",
        },
        "archive": {
            "filename": path.name,
            "bytes": len(archive_bytes),
            "members": members,
            "dynamic_export_filenames": True,
        },
        "observed_data": {
            "data_record_count": len(data_rows),
            "distinct_sample_code_count": len(sample_counts),
            "duplicate_sample_code_count": sum(1 for count in sample_counts.values() if count > 1),
            "target_bearing_row_count": target_bearing_row_count,
            "sample_codes_with_target_count": len(target_rows_by_sample),
            "sample_codes_without_target_count": len(set(samples) - set(target_rows_by_sample)),
            "sample_codes_with_multiple_target_rows_count": sum(
                1 for count in target_rows_by_sample.values() if count > 1
            ),
            "distinct_batch_count": len(batches),
            "batches": batches,
            "cruise_years": years,
            "longitude_range": [
                min(value[0] for value in numeric_coordinates),
                max(value[0] for value in numeric_coordinates),
            ],
            "latitude_range": [
                min(value[1] for value in numeric_coordinates),
                max(value[1] for value in numeric_coordinates),
            ],
            "target_analytes": value_profiles(data_rows),
        },
        "observed_metadata": metadata_profile(metadata_rows),
        "prepared_human_review_sample": sample,
        "human_review": {
            "required_record_count": min(30, len(data_rows)),
            "prepared_record_count": len(sample),
            "status": "pending",
        },
        "claim_boundary": (
            "These are observations from one dynamic MarChem export. They verify file structure and "
            "field content, not immutable-version status, human row review, or production approval."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="MarChem inorganic ZIP export")
    parser.add_argument("--request-url", help="Exact public export URL used for this response")
    parser.add_argument("--observed-at", help="UTC timestamp reported by the export information member")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)
    try:
        result = verify(args.archive, request_url=args.request_url, observed_at=args.observed_at)
    except (OSError, ValueError, zipfile.BadZipFile, VerificationError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
