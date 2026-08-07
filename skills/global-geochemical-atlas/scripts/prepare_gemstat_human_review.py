#!/usr/bin/env python3
"""Prepare an unsigned, stratified 30-row GEMStat v3 arsenic review sheet."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import OrderedDict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import generate_demo_data as demos
import source_adapters

REVIEW_VERSION = "geochemical-human-review-v1"


class ReviewPreparationError(RuntimeError):
    """Raised when a deterministic review sample cannot be prepared."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def reported_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def prepare(cache_dir: Path) -> dict[str, Any]:
    adapter = source_adapters.get_adapter("gemstat-open-archive")
    candidate = adapter.discover({"sources": ["gemstat-open-archive"]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    by_id = {item.file_id: item for item in downloaded}
    observation_file = by_id["arsenic-observations"]
    total = candidate.registry_entry["expected_counts"]["arsenic_observations"]
    even_positions = {round(index * (total - 1) / 29) for index in range(30)}
    priority: OrderedDict[str, tuple[source_adapters.RawRecord, set[str]]] = OrderedDict()
    fill: OrderedDict[str, tuple[source_adapters.RawRecord, set[str]]] = OrderedDict()
    boundaries: dict[str, tuple[float, source_adapters.RawRecord]] = {}
    previous_key: tuple[str, ...] | None = None

    def add(record: source_adapters.RawRecord, reason: str, *, high_priority: bool = True) -> None:
        current = priority.get(record.source_record_id) or fill.get(record.source_record_id)
        if current is None:
            target = priority if high_priority else fill
            target[record.source_record_id] = (record, {reason})
        else:
            current[1].add(reason)
            if high_priority and record.source_record_id in fill:
                del fill[record.source_record_id]
                priority[record.source_record_id] = current

    key_fields = (
        "GEMS Station Number", "Sample Date", "Sample Time", "Depth", "Parameter Code",
        "Analysis Method Code", "Value Flags", "Value", "Unit", "Data Quality",
        "Integrated Value", "Remark", "License Information",
    )
    seen_categories: set[str] = set()
    seen_special_cases: set[str] = set()
    for index, record in enumerate(adapter.parse(downloaded)):
        fields = record.fields
        station = fields["_station_metadata"]
        value = reported_float(fields["Value"])
        latitude = reported_float(station["Latitude"])
        longitude = reported_float(station["Longitude"])
        depth = reported_float(fields["Depth"])
        if value is None or latitude is None or longitude is None or depth is None:
            raise ReviewPreparationError(f"numeric source fact missing at {record.source_locator}")
        categories = {
            f"fraction={fields['_water_fraction']}",
            f"value_flag={fields['Value Flags'] or 'reported'}",
            f"data_quality={fields['Data Quality']}",
            f"unit={fields['Unit']}",
            f"water_type={station['Water Type']}",
            f"method={'undefined' if fields['Analysis Method Code'] == '0' else 'defined'}",
        }
        for category in sorted(categories):
            if category not in seen_categories:
                add(record, category)
                seen_categories.add(category)
        if fields["Data Quality"] == "Pending review" and value == -999.999:
            if "pending_review_negative_sentinel" not in seen_special_cases:
                add(record, "pending_review_negative_sentinel")
                seen_special_cases.add("pending_review_negative_sentinel")
        if fields["Data Quality"] == "Pending review" and fields["Unit"] == "mg/l" and value >= 1000:
            if "pending_review_extreme_mg_l" not in seen_special_cases:
                add(record, "pending_review_extreme_mg_l")
                seen_special_cases.add("pending_review_extreme_mg_l")
        current_key = tuple(str(fields.get(name) or "") for name in key_fields)
        if current_key == previous_key and "adjacent_exact_duplicate_observation" not in seen_special_cases:
            add(record, "adjacent_exact_duplicate_observation")
            seen_special_cases.add("adjacent_exact_duplicate_observation")
        previous_key = current_key
        for label, numeric in (("longitude", longitude), ("latitude", latitude), ("depth", depth)):
            low = boundaries.get(f"{label}_min")
            high = boundaries.get(f"{label}_max")
            if low is None or numeric < low[0]:
                boundaries[f"{label}_min"] = (numeric, record)
            if high is None or numeric > high[0]:
                boundaries[f"{label}_max"] = (numeric, record)
        if index in even_positions:
            add(record, "evenly_spaced_source_order", high_priority=False)

    for reason, (_, record) in sorted(boundaries.items()):
        add(record, f"{reason}_boundary")
    selected = list(priority.values())
    selected.extend(item for source_id, item in fill.items() if source_id not in priority)
    selected = selected[:30]
    if len(selected) != 30:
        raise ReviewPreparationError(f"GEMStat selection produced {len(selected)} rows, expected 30")

    known_qualities = set(candidate.registry_entry["expected_counts"]["data_quality_counts"])
    records: list[dict[str, Any]] = []
    for position, (record, selection_reasons) in enumerate(selected, start=1):
        fields = record.fields
        station = fields["_station_metadata"]
        method = fields["_method_metadata"]
        raw_value = str(fields["Value"])
        unit = str(fields["Unit"])
        analyte = "As"
        output_record_id = source_adapters.stable_record_id(
            record.source_id, record.source_record_id, analyte, raw_value, unit
        )
        observation = {
            "analyte": analyte,
            "parameter_code": fields["Parameter Code"],
            "raw_value": raw_value,
            "value_qualifier": fields["Value Flags"],
            "unit": unit,
            "medium": "water",
            "water_fraction": fields["_water_fraction"],
            "station_id": fields["GEMS Station Number"],
            "country": station["Country Name"],
            "water_type": station["Water Type"],
            "sampled_at": fields["Sample Date"],
            "sample_time": fields["Sample Time"],
            "sample_depth_m": fields["Depth"],
            "latitude": station["Latitude"],
            "longitude": station["Longitude"],
            "analysis_method_code": fields["Analysis Method Code"],
            "analysis_method_name": method["Method Name"],
            "method_description": method["Method Description"],
            "data_quality": fields["Data Quality"],
            "record_id": output_record_id,
        }
        checks = {
            "registered_member_bytes_match": observation_file.bytes == observation_file.path.stat().st_size,
            "station_join_preserved": bool(station["GEMS Station Number"] == fields["GEMS Station Number"]),
            "coordinates_preserved": reported_float(station["Latitude"]) is not None
            and reported_float(station["Longitude"]) is not None,
            "sample_depth_preserved": reported_float(fields["Depth"]) is not None,
            "raw_value_qualifier_and_unit_preserved": reported_float(raw_value) is not None
            and fields["Value Flags"] in {"", "<", ">"}
            and unit in {"mg/l", "µg/l"},
            "fraction_preserved": fields["_water_fraction"] in {"dissolved", "suspended", "total"},
            "method_join_preserved": method["Parameter Code"] == fields["Parameter Code"]
            and method["Analysis Method Code"] == fields["Analysis Method Code"]
            and method["Unit"] == unit,
            "source_quality_preserved": fields["Data Quality"] in known_qualities,
            "stable_observation_id_present": output_record_id.startswith("rec-"),
        }
        records.append(
            {
                "review_id": f"gemstat-open-archive-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": fields["GEMS Station Number"],
                "selection_reasons": sorted(selection_reasons),
                "published_target_raw_values": {"As": raw_value},
                "adapter_observations": [observation],
                "automated_checks": checks,
                "automated_status": "PASS" if all(checks.values()) else "FAIL",
                "reviewer": {"decision": None, "reviewer": None, "reviewed_at": None, "notes": None},
            }
        )
    pass_count = sum(record["automated_status"] == "PASS" for record in records)
    return {
        "review_version": REVIEW_VERSION,
        "source_id": candidate.source_id,
        "dataset_version": candidate.version,
        "snapshot_id": f"gemstat-open-archive:v3:{candidate.version}",
        "status": "prepared",
        "required_record_count": 30,
        "prepared_record_count": len(records),
        "automated_pass_count": pass_count,
        "completed_record_count": 0,
        "selection_strategy": (
            "Thirty arsenic rows spanning three fractions, qualifiers, source quality labels, units, five water types, "
            "defined/undefined methods, spatial/depth boundaries, source-order coverage, duplicates and flagged extremes."
        ),
        "records": records,
        "claim_boundary": (
            "Automated PASS verifies source-to-adapter preservation only. Human decisions remain unsigned and add "
            "confidence when completed; they are not a binary permission gate for research use."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        review = prepare(args.cache_dir)
        atomic_json(args.output, review)
        print(json.dumps({"status": "PASS", "prepared": review["prepared_record_count"]}, sort_keys=True))
        return 0 if review["automated_pass_count"] == review["prepared_record_count"] == 30 else 1
    except (OSError, ValueError, ReviewPreparationError, source_adapters.SourceAdapterError) as exc:
        print(f"prepare_gemstat_human_review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
