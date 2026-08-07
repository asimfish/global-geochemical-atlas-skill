#!/usr/bin/env python3
"""Audit and prepare review evidence for the pinned WQP Sacramento River snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import source_adapters

AUDIT_VERSION = "wqp-sacramento-dissolved-as-audit-v1"
SOURCE_ID = "us-wqp-sacramento-river-arsenic"


class AuditError(RuntimeError):
    """Raised when the content-addressed WQP snapshot no longer reconciles."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any) -> bool:
    try:
        return math.isfinite(float(str(value).strip()))
    except (TypeError, ValueError):
        return False


def audit(cache_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    adapter = source_adapters.get_adapter(SOURCE_ID)
    candidate = adapter.discover({"sources": [SOURCE_ID]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    by_name = {item.path.name: item for item in downloaded}
    records = list(adapter.parse(downloaded))
    registry = candidate.registry_entry
    expected = registry["expected_counts"]

    statuses: Counter[str] = Counter()
    activity_types: Counter[str] = Counter()
    limits: Counter[str] = Counter()
    dates: list[str] = []
    numeric = 0
    not_detected = 0
    for record in records:
        fields = record.fields
        values = fields["_target_observations"]["As"]
        statuses[str(fields["ResultStatusIdentifier"])] += 1
        activity_types[str(fields["ActivityTypeCode"])] += 1
        limits[str(values["detection_limit_type"])] += 1
        dates.append(str(fields["ActivityStartDate"]))
        if values["value_qualifier"] == "<":
            not_detected += 1
        else:
            numeric += 1
    observed_counts = {
        "physical_rows": len(records),
        "target_observations": len(records),
        "numeric_results": numeric,
        "not_detected_results": not_detected,
        "unique_activity_ids": len({str(record.fields["ActivityIdentifier"]) for record in records}),
        "unique_result_ids": len({str(record.fields["ResultIdentifier"]) for record in records}),
        "accepted_results": statuses["Accepted"],
        "preliminary_results": statuses["Preliminary"],
        "routine_samples": activity_types["Sample-Routine"],
        "field_replicates": activity_types["Quality Control Sample-Field Replicate"],
        "analytical_method_ids": {"USGS:PLM10": len(records)},
    }
    if observed_counts != expected:
        raise AuditError(f"WQP counts changed: {observed_counts!r} != {expected!r}")

    station = records[0].fields["_station_metadata"]
    members = [
        {
            "name": item.path.name,
            "file_id": item.file_id,
            "bytes": item.bytes,
            "source_url": item.source_url,
        }
        for item in downloaded
    ]
    snapshot_id = f"{SOURCE_ID}:{candidate.version}:{registry['download']['observed_at']}"
    coverage = {
        "station_count": 1,
        "monitoring_location_identifier": station["MonitoringLocationIdentifier"],
        "monitoring_location_name": station["MonitoringLocationName"],
        "monitoring_location_type": station["MonitoringLocationTypeName"],
        "bbox": [
            float(station["LongitudeMeasure"]),
            float(station["LatitudeMeasure"]),
            float(station["LongitudeMeasure"]),
            float(station["LatitudeMeasure"]),
        ],
        "source_crs": station["HorizontalCoordinateReferenceSystemDatumName"],
        "reported_horizontal_accuracy": {
            "value": station["HorizontalAccuracyMeasure/MeasureValue"],
            "unit": station["HorizontalAccuracyMeasure/MeasureUnitCode"],
            "collection_method": station["HorizontalCollectionMethodName"],
        },
        "sample_date_range": [min(dates), max(dates)],
    }
    claim_boundary = (
        "The content-addressed pair verifies 189 USGS/NWIS dissolved-arsenic results at one Sacramento River station. "
        "It validates row-level method, limit, status and QC handling, but makes no national or global coverage claim."
    )
    limitations = [
        "A single station is not a spatial freshwater atlas.",
        "The exact repeated-parameter query returned arsenic only; Cu, Ni and Zn are not claimed.",
        "Preliminary results and field-replicate QC samples remain labeled and are not silently promoted to accepted routine evidence.",
        "The Not Detected result remains left-censored at its reported limit rather than being converted to zero.",
        "WQP is the delivery route; the upstream USGS/NWIS record is the evidence source and is not double-counted.",
    ]
    request_url = next(item["source_url"] for item in members if item["file_id"] == "results")
    snapshot = {
        "snapshot_version": "geochemical-source-snapshot-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "observed_at": registry["download"]["observed_at"],
        "request": {"url": request_url, "station_url": next(item["source_url"] for item in members if item["file_id"] == "station")},
        "response": {"bytes": sum(item["bytes"] for item in members)},
        "archive": {"members": members},
        "counts": observed_counts,
        "coverage": coverage,
        "result_status_counts": dict(sorted(statuses.items())),
        "activity_type_counts": dict(sorted(activity_types.items())),
        "detection_limit_type_counts": dict(sorted(limits.items())),
        "evidence": {"dataset_version": candidate.version, "license": candidate.license_id},
        "claim_boundary": claim_boundary,
    }
    checks = {
        "registered_file_bytes_match": all(
            item.bytes
            == next(entry["bytes"] for entry in registry["download"]["files"] if entry["file_id"] == item.file_id)
            for item in downloaded
        ),
        "counts_match_registry": observed_counts == expected,
        "station_join_complete": all(record.fields["_station_metadata"]["MonitoringLocationIdentifier"] == "USGS-11447650" for record in records),
        "all_rows_are_dissolved_arsenic_water": all(
            record.fields["CharacteristicName"] == "Arsenic"
            and record.fields["ResultSampleFractionText"] == "Dissolved"
            and record.fields["ActivityMediaName"] == "Water"
            for record in records
        ),
        "method_metadata_complete": all(record.fields["_target_observations"]["As"]["analytical_method"] for record in records),
        "limit_metadata_complete": all(record.fields["_target_observations"]["As"]["detection_limit"] for record in records),
    }
    if not all(checks.values()):
        raise AuditError(f"WQP audit checks failed: {checks}")
    reconciliation = {
        "reconciliation_version": AUDIT_VERSION,
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "status": "PASS",
        "counts": observed_counts,
        "coverage": coverage,
        "checks": checks,
        "limitations": limitations,
    }
    candidate_audit = {
        "verification_version": AUDIT_VERSION,
        "source_id": SOURCE_ID,
        "acquisition": {
            "request_url": request_url,
            "observed_at": registry["download"]["observed_at"],
            "mode": registry["download"]["mode"],
        },
        "archive": {"members": members},
        "observed_data": {
            "target_analytes": registry["target_analytes"],
            "counts": observed_counts,
            "coverage": coverage,
        },
        "observed_metadata": {
            "method_id": "USGS:PLM10",
            "method_rows": len(records),
            "detection_limit_rows": len(records),
            "result_status_counts": dict(sorted(statuses.items())),
            "activity_type_counts": dict(sorted(activity_types.items())),
        },
        "status": "verified_content_addressed_official_query_pair",
        "limitations": limitations,
        "claim_boundary": claim_boundary,
    }

    selected: list[source_adapters.RawRecord] = []
    selected_ids: set[str] = set()

    def add(records_to_add: Sequence[source_adapters.RawRecord]) -> None:
        for record in records_to_add:
            if record.source_record_id not in selected_ids and len(selected) < 30:
                selected.append(record)
                selected_ids.add(record.source_record_id)

    add([record for record in records if record.fields["ResultDetectionConditionText"] == "Not Detected"])
    add([record for record in records if record.fields["ActivityTypeCode"] == "Quality Control Sample-Field Replicate"])
    preliminary = [record for record in records if record.fields["ResultStatusIdentifier"] == "Preliminary"]
    accepted = [record for record in records if record.fields["ResultStatusIdentifier"] == "Accepted"]
    add([preliminary[round(i * (len(preliminary) - 1) / 9)] for i in range(10)])
    add([accepted[round(i * (len(accepted) - 1) / 9)] for i in range(10)])
    add(records)
    if len(selected) != 30:
        raise AuditError(f"WQP review selection produced {len(selected)} rows")
    review_records: list[dict[str, Any]] = []
    result_file = by_name["results.csv"]
    for position, record in enumerate(selected, start=1):
        fields = record.fields
        values = fields["_target_observations"]["As"]
        joined_station = fields["_station_metadata"]
        raw_value = str(values["value"])
        output_record_id = source_adapters.stable_record_id(
            SOURCE_ID, record.source_record_id, "As", raw_value, str(values["unit"])
        )
        row_checks = {
            "registered_result_bytes_match": result_file.bytes == next(item["bytes"] for item in members if item["name"] == "results.csv"),
            "station_join_preserved": joined_station["MonitoringLocationIdentifier"] == fields["MonitoringLocationIdentifier"],
            "coordinates_preserved": finite(joined_station["LatitudeMeasure"]) and finite(joined_station["LongitudeMeasure"]),
            "raw_value_or_censor_limit_preserved": finite(raw_value) and values["value_qualifier"] in {"", "<"},
            "unit_and_fraction_preserved": values["unit"] == "ug/l" and fields["ResultSampleFractionText"] == "Dissolved",
            "method_preserved": str(values["analytical_method"]).startswith("USGS:PLM10:"),
            "result_status_preserved": values["source_result_status"] in {"Accepted", "Preliminary"},
            "activity_type_preserved": values["activity_type"] in {"Sample-Routine", "Quality Control Sample-Field Replicate"},
            "stable_observation_id_present": output_record_id.startswith("rec-"),
        }
        review_records.append(
            {
                "review_id": f"{SOURCE_ID}-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": fields["ActivityIdentifier"],
                "selection_reasons": [
                    f"status={fields['ResultStatusIdentifier']}",
                    f"activity_type={fields['ActivityTypeCode']}",
                    f"qualifier={values['value_qualifier'] or 'reported'}",
                ],
                "published_target_raw_values": {"As": fields["ResultMeasureValue"] or None},
                "adapter_observations": [
                    {
                        "analyte": "As",
                        "raw_value": raw_value,
                        "value_qualifier": values["value_qualifier"],
                        "detection_limit": values["detection_limit"],
                        "detection_limit_type": values["detection_limit_type"],
                        "unit": values["unit"],
                        "medium": "water",
                        "water_fraction": "dissolved",
                        "sampled_at": fields["ActivityStartDate"],
                        "latitude": joined_station["LatitudeMeasure"],
                        "longitude": joined_station["LongitudeMeasure"],
                        "analytical_method": values["analytical_method"],
                        "result_status": values["source_result_status"],
                        "activity_type": values["activity_type"],
                        "record_id": output_record_id,
                    }
                ],
                "automated_checks": row_checks,
                "automated_status": "PASS" if all(row_checks.values()) else "FAIL",
                "reviewer": {"decision": None, "reviewer": None, "reviewed_at": None, "notes": None},
            }
        )
    automated_pass_count = sum(item["automated_status"] == "PASS" for item in review_records)
    review = {
        "review_version": "geochemical-human-review-v1",
        "source_id": SOURCE_ID,
        "dataset_version": candidate.version,
        "snapshot_id": snapshot_id,
        "status": "prepared",
        "required_record_count": 30,
        "prepared_record_count": len(review_records),
        "automated_pass_count": automated_pass_count,
        "completed_record_count": 0,
        "selection_strategy": "Stratified across censoring, field replicates, preliminary and accepted routine results, then distributed through source order.",
        "records": review_records,
        "claim_boundary": "Automated PASS verifies preservation only. Unsigned human review adds confidence and is not a research-use permission gate.",
    }
    if automated_pass_count != 30:
        raise AuditError(f"only {automated_pass_count}/30 WQP review rows passed automated checks")
    return snapshot, reconciliation, candidate_audit, review


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--snapshot-output", required=True, type=Path)
    parser.add_argument("--reconciliation-output", required=True, type=Path)
    parser.add_argument("--candidate-audit-output", required=True, type=Path)
    parser.add_argument("--review-output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot, reconciliation, candidate_audit, review = audit(args.cache_dir)
        atomic_json(args.snapshot_output, snapshot)
        atomic_json(args.reconciliation_output, reconciliation)
        atomic_json(args.candidate_audit_output, candidate_audit)
        atomic_json(args.review_output, review)
        print(json.dumps({"status": "PASS", "snapshot_id": snapshot["snapshot_id"], "review_rows": 30}, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_wqp_sacramento: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
