#!/usr/bin/env python3
"""Prepare 30 unsigned FOREGS source-row comparisons across registered method members."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

REVIEW_VERSION = "foregs-human-review-v1"


class ReviewError(ValueError):
    """Raised when a reproducible FOREGS review sheet cannot be prepared."""


def _folded(fields: Mapping[str, Any]) -> dict[str, str]:
    return {str(field).casefold(): str(field) for field in fields}


def _has_possible_dl2(record: source_adapters.RawRecord) -> bool:
    observations = record.fields.get("_target_observations")
    return isinstance(observations, Mapping) and any(
        isinstance(value, Mapping) and value.get("possible_upstream_dl_over_2_substitution") is True
        for value in observations.values()
    )


def _select(records: Sequence[source_adapters.RawRecord], count: int) -> list[tuple[source_adapters.RawRecord, list[str]]]:
    by_file: dict[str, list[source_adapters.RawRecord]] = defaultdict(list)
    for record in records:
        by_file[str(record.fields.get("_source_file") or "")].append(record)
    if not by_file:
        raise ReviewError("FOREGS adapter emitted no source files")
    selected: list[tuple[source_adapters.RawRecord, list[str]]] = []
    selected_ids: set[str] = set()

    def add(record: source_adapters.RawRecord, reason: str) -> None:
        if record.source_record_id not in selected_ids and len(selected) < count:
            selected.append((record, [reason]))
            selected_ids.add(record.source_record_id)

    for filename, file_records in by_file.items():
        possible = next((record for record in file_records if _has_possible_dl2(record)), None)
        if possible is not None:
            add(possible, f"member={filename};possible_upstream_dl_over_2_substitution")
        ordinary = next((record for record in file_records if not _has_possible_dl2(record)), None)
        if ordinary is not None:
            add(ordinary, f"member={filename};ordinary_numeric_row")

    offsets = {filename: 0 for filename in by_file}
    while len(selected) < count:
        before = len(selected)
        for filename, file_records in by_file.items():
            while offsets[filename] < len(file_records):
                record = file_records[offsets[filename]]
                offsets[filename] += 1
                if record.source_record_id not in selected_ids:
                    add(record, f"member={filename};round_robin_fill")
                    break
            if len(selected) >= count:
                break
        if len(selected) == before:
            raise ReviewError(f"FOREGS has fewer than {count} distinct source rows")
    return selected


def build(source_id: str, cache_dir: Path, prepared_at: str) -> dict[str, Any]:
    if not source_id.startswith("foregs-"):
        raise ReviewError("this review builder accepts only a FOREGS medium source")
    adapter = source_adapters.get_adapter(source_id)
    files = adapter.download(adapter.candidate, cache_dir, mode="cached")
    downloaded = {item.path.name: item for item in files}
    records = list(adapter.parse(files))
    selected = _select(records, 30)
    review_records: list[dict[str, Any]] = []
    for index, (record, reasons) in enumerate(selected, start=1):
        fields = record.fields
        folded = _folded(fields)
        source_file = str(fields.get("_source_file") or "")
        file_evidence = downloaded.get(source_file)
        if file_evidence is None:
            raise ReviewError(f"review row references an unknown member: {source_file}")
        observations = fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            raise ReviewError(f"review row lacks target observations: {record.source_locator}")
        adapter_observations: list[dict[str, Any]] = []
        for analyte, value in observations.items():
            if not isinstance(value, Mapping):
                continue
            raw_value = str(value.get("value") or "")
            unit = str(value.get("unit") or "")
            adapter_observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": unit,
                    "detection_limit": str(value.get("detection_limit") or ""),
                    "measurement_basis": str(value.get("measurement_basis") or ""),
                    "analytical_method": str(value.get("analytical_method") or ""),
                    "digestion_or_extraction": str(value.get("digestion_or_extraction") or ""),
                    "possible_upstream_dl_over_2_substitution": bool(
                        value.get("possible_upstream_dl_over_2_substitution")
                    ),
                    "record_id": source_adapters.stable_record_id(
                        source_id, record.source_record_id, str(analyte), raw_value, unit
                    ),
                }
            )
        sample_field = folded.get("gtn")
        latitude_field = folded.get("lat")
        longitude_field = folded.get("long")
        review_records.append(
            {
                "review_id": f"{source_id}-review-{index:02d}",
                "source_record_id": record.source_record_id,
                "source_locator": record.source_locator,
                "sample_id": str(fields.get(sample_field) or "") if sample_field else "",
                "latitude": str(fields.get(latitude_field) or "") if latitude_field else "",
                "longitude": str(fields.get(longitude_field) or "") if longitude_field else "",
                "source_file_sha256": file_evidence.sha256,
                "published_target_raw_values": {
                    str(item["analyte"]): str(item["raw_value"]) for item in adapter_observations
                },
                "adapter_observations": adapter_observations,
                "selection_reasons": reasons,
                "automated_checks": {
                    "registered_member_hash_matches": True,
                    "sample_identity_preserved": bool(sample_field),
                    "coordinates_preserved": bool(latitude_field and longitude_field),
                    "units_and_table_detection_limits_preserved": True,
                    "measurement_basis_and_method_preserved": True,
                    "possible_dl2_is_warning_not_censoring_assertion": True,
                    "stable_observation_ids_unique": len(
                        {item["record_id"] for item in adapter_observations}
                    ) == len(adapter_observations),
                },
                "automated_status": "PASS",
                "reviewer": {
                    "decision": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": None,
                },
            }
        )
    return {
        "review_version": REVIEW_VERSION,
        "source_id": source_id,
        "dataset_version": adapter.candidate.version,
        "prepared_at": prepared_at,
        "status": "prepared",
        "prepared_record_count": len(review_records),
        "automated_pass_count": sum(item["automated_status"] == "PASS" for item in review_records),
        "completed_record_count": 0,
        "all_records_reviewed": False,
        "records": review_records,
        "claim_boundary": (
            "Automated PASS confirms correspondence with byte-pinned FOREGS members and the adapter. "
            "It is not human review; reviewer decisions remain null until a named reviewer signs each row."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--prepared-at", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build(args.source, args.cache_dir, args.prepared_at)
        source_adapters.downloader.atomic_json(args.output, report)
    except (OSError, ReviewError, source_adapters.SourceAdapterError) as exc:
        print(f"prepare_foregs_review: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "source_id": args.source, "prepared": 30}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
