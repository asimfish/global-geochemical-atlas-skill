#!/usr/bin/env python3
"""Prepare, but never auto-sign, the 30-record MarChem human review sheet."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CANDIDATE = SKILL_DIR / "fixtures" / "candidate-audits" / "marchem-inorganic-20260805T102709Z.json"
REVIEW_VERSION = "geochemical-human-review-v1"
ANALYTES = ("As", "Cu", "Ni", "Zn")


class ReviewPreparationError(RuntimeError):
    """Raised when the frozen review sample no longer matches adapter output."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _candidate(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewPreparationError(f"candidate evidence is unreadable: {path}") from exc
    rows = value.get("prepared_human_review_sample")
    if not isinstance(rows, list) or len(rows) != 30:
        raise ReviewPreparationError("candidate evidence must contain the frozen 30-record review sample")
    return value


def prepare(archive: Path, candidate_path: Path = DEFAULT_CANDIDATE) -> dict[str, Any]:
    candidate_evidence = _candidate(candidate_path)
    adapter = source_adapters.get_adapter("norway-marchem")
    if not isinstance(adapter, source_adapters.MarchemSnapshotAdapter):
        raise ReviewPreparationError("norway-marchem does not resolve to the canonical adapter")
    with tempfile.TemporaryDirectory(prefix="marchem-review-") as temporary:
        files = adapter.files_from_archive(archive, Path(temporary) / "members")
        records = list(adapter.parse(files))
    by_row: dict[int, source_adapters.RawRecord] = {}
    for record in records:
        _, _, row_text = record.source_locator.partition("#row=")
        if row_text.isdigit():
            by_row[int(row_text)] = record

    target_fields: Mapping[str, str] = adapter.candidate.registry_entry["target_analytes"]
    review_records: list[dict[str, Any]] = []
    for position, prepared in enumerate(candidate_evidence["prepared_human_review_sample"], start=1):
        source_row = prepared["source_row_number"]
        record = by_row.get(source_row)
        if record is None:
            raise ReviewPreparationError(f"prepared source row is absent: {source_row}")
        methods = record.fields.get("_lab_parameters")
        if not isinstance(methods, Mapping):
            raise ReviewPreparationError(f"method map is absent at source row {source_row}")
        published_values = {analyte: str(record.fields.get(target_fields[analyte]) or "") for analyte in ANALYTES}
        observations: list[dict[str, Any]] = []
        for analyte in ANALYTES:
            field_name = target_fields[analyte]
            raw_value = published_values[analyte]
            if not raw_value:
                continue
            method = methods.get(field_name)
            if not isinstance(method, Mapping):
                raise ReviewPreparationError(
                    f"target method is absent at source row {source_row}: {analyte}"
                )
            observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": method.get("Unit"),
                    "weight_basis": method.get("Wet_or_dry_weight"),
                    "analytical_method": method.get("Analysis_method"),
                    "llq": method.get("LLQ"),
                    "laboratory": method.get("Laboratory"),
                    "accreditation_status": method.get("_accreditation_status"),
                    "digestion_scope": "partial",
                    "metadata_source_locator": method.get("_metadata_source_locator"),
                    "record_id": source_adapters.stable_record_id(
                        record.source_id,
                        record.source_record_id,
                        analyte,
                        raw_value,
                        str(method.get("Unit") or ""),
                    ),
                }
            )
        expected_values = prepared["target_raw_values"]
        expected_target_count = sum(bool(str(value or "")) for value in expected_values.values())
        automated_checks = {
            "sample_id_matches": str(record.fields.get("Sample_code") or "") == prepared["sample_code"],
            "batch_code_matches": str(record.fields.get("Batch_code") or "") == prepared["batch_code"],
            "cruise_year_matches": str(record.fields.get("Cruise_year") or "") == prepared["cruise_year"],
            "latitude_matches": str(record.fields.get("Latitude") or "") == prepared["latitude"],
            "longitude_matches": str(record.fields.get("Longitude") or "") == prepared["longitude"],
            "target_raw_values_match": published_values == expected_values,
            "target_row_classification_matches": len(observations) == expected_target_count,
            "method_links_complete": len(observations) == sum(
                field_name in methods
                for field_name in target_fields.values()
                if str(record.fields.get(field_name) or "")
            ),
            "dry_weight_mg_per_kg_preserved": all(
                item["unit"] == "mg/kg" and item["weight_basis"] == "Dry weight"
                for item in observations
            ),
            "partial_digestion_preserved": all(item["digestion_scope"] == "partial" for item in observations),
        }
        review_records.append(
            {
                "review_id": f"norway-marchem-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": str(record.fields.get("Sample_code") or ""),
                "batch_code": str(record.fields.get("Batch_code") or ""),
                "selection_reasons": prepared["selection_reasons"],
                "published_target_raw_values": published_values,
                "adapter_observations": observations,
                "automated_checks": automated_checks,
                "automated_status": "PASS" if all(automated_checks.values()) else "FAIL",
                "reviewer": {
                    "decision": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": None,
                },
            }
        )
    automated_pass_count = sum(record["automated_status"] == "PASS" for record in review_records)
    return {
        "review_version": REVIEW_VERSION,
        "source_id": adapter.source_id,
        "dataset_version": adapter.candidate.version,
        "snapshot_id": adapter.candidate.version,
        "status": "prepared",
        "required_record_count": 30,
        "prepared_record_count": len(review_records),
        "automated_pass_count": automated_pass_count,
        "completed_record_count": 0,
        "selection_strategy": (
            "Stratified prepared sample covering normal, missing, censored, duplicate-parameter-group, "
            "early not-accredited, extreme and spatial-boundary source rows."
        ),
        "records": review_records,
        "claim_boundary": (
            "Automated PASS confirms that the adapter matches the frozen source facts. It is not a human-review "
            "decision. Each reviewer.decision remains null until a named reviewer checks and signs the record."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--candidate-evidence", type=Path, default=DEFAULT_CANDIDATE)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        review = prepare(args.archive, args.candidate_evidence)
        if args.output:
            atomic_json(args.output, review)
        print(json.dumps(review, ensure_ascii=False, sort_keys=True))
        return 0 if review["automated_pass_count"] == review["prepared_record_count"] else 1
    except (OSError, ValueError, ReviewPreparationError, source_adapters.SourceAdapterError) as exc:
        print(f"prepare_marchem_human_review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
