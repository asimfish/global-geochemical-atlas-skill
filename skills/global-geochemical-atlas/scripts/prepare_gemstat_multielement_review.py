#!/usr/bin/env python3
"""Prepare an unsigned 30-row review sheet across seven GEMStat elements."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import source_adapters

REVIEW_VERSION = "geochemical-human-review-v1"
ELEMENTS = ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")
QUOTAS = {"As": 5, "Cr": 5, "Cu": 4, "Hg": 4, "Ni": 4, "Pb": 4, "Zn": 4}


class ReviewError(RuntimeError):
    """Raised when a deterministic seven-element review cannot be prepared."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite(value: Any) -> bool:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed)


def prepare(cache_dir: Path) -> dict[str, Any]:
    adapter = source_adapters.get_adapter("gemstat-open-archive")
    candidate = adapter.discover({"sources": ["gemstat-open-archive"]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    by_name = {item.path.name: item for item in downloaded}
    parameter_first: dict[str, dict[str, source_adapters.RawRecord]] = defaultdict(dict)
    category_first: dict[str, dict[str, source_adapters.RawRecord]] = defaultdict(dict)
    parsed = 0
    for record in adapter.parse(downloaded):
        parsed += 1
        fields = record.fields
        element = str(fields["_element"])
        parameter = str(fields["Parameter Code"])
        parameter_first[element].setdefault(parameter, record)
        categories = (
            f"method={'undefined' if fields['Analysis Method Code'] == '0' else 'defined'}",
            f"qualifier={fields['Value Flags'] or 'reported'}",
            f"quality={fields['Data Quality']}",
            f"unit={fields['Unit']}",
            f"water_type={fields['_station_metadata']['Water Type']}",
        )
        for category in categories:
            category_first[element].setdefault(category, record)
    if parsed != candidate.registry_entry["expected_counts"]["target_observations"]:
        raise ReviewError(f"adapter emitted {parsed} target rows")

    selected: list[tuple[source_adapters.RawRecord, list[str]]] = []
    for element in ELEMENTS:
        chosen: dict[str, tuple[source_adapters.RawRecord, set[str]]] = {}
        configured = candidate.registry_entry["target_analytes"][element]
        for parameter in configured:
            record = parameter_first[element].get(parameter)
            if record is None:
                raise ReviewError(f"no review row for {parameter}")
            chosen[record.source_record_id] = (record, {f"parameter={parameter}"})
        preferred_categories = (
            "method=defined",
            "method=undefined",
            "qualifier=<",
            "quality=Pending review",
            "quality=Suspect",
            "unit=µg/l",
            "unit=mg/l",
        )
        for category in preferred_categories:
            if len(chosen) >= QUOTAS[element]:
                break
            record = category_first[element].get(category)
            if record is not None:
                current = chosen.get(record.source_record_id)
                if current is None:
                    chosen[record.source_record_id] = (record, {category})
                else:
                    current[1].add(category)
        if len(chosen) != QUOTAS[element]:
            raise ReviewError(
                f"{element} review produced {len(chosen)} rows, expected {QUOTAS[element]}"
            )
        selected.extend(
            (record, sorted(reasons)) for record, reasons in chosen.values()
        )

    records: list[dict[str, Any]] = []
    for position, (record, reasons) in enumerate(selected, start=1):
        fields = record.fields
        station = fields["_station_metadata"]
        method = fields["_method_metadata"]
        element = str(fields["_element"])
        raw_value = str(fields["Value"])
        unit = str(fields["Unit"])
        source_file = by_name[str(fields["_source_file"])]
        output_record_id = source_adapters.stable_record_id(
            record.source_id, record.source_record_id, element, raw_value, unit
        )
        observation = {
            "analyte": element,
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
            "registered_member_bytes_match": source_file.bytes
            == source_file.path.stat().st_size,
            "element_mapping_preserved": source_adapters.GemstatOpenArchiveAdapter.PARAMETER_MAP[
                fields["Parameter Code"]
            ][0]
            == element,
            "station_join_preserved": station["GEMS Station Number"]
            == fields["GEMS Station Number"],
            "coordinates_preserved": finite(station["Latitude"])
            and finite(station["Longitude"]),
            "sample_depth_preserved": finite(fields["Depth"]),
            "raw_value_qualifier_and_unit_preserved": finite(raw_value)
            and fields["Value Flags"] in {"", "<", ">"}
            and unit in {"mg/l", "µg/l", "ng/l", "µg/g"},
            "fraction_preserved": fields["_water_fraction"]
            in {"dissolved", "extractable", "suspended", "total"},
            "method_join_preserved": method["Parameter Code"]
            == fields["Parameter Code"]
            and method["Analysis Method Code"] == fields["Analysis Method Code"]
            and method["Unit"] == unit,
            "stable_observation_id_present": output_record_id.startswith("rec-"),
        }
        records.append(
            {
                "review_id": f"gemstat-open-archive-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": "|".join(
                    (
                        str(fields["GEMS Station Number"]),
                        str(fields["Sample Date"]),
                        str(fields["Sample Time"]),
                        str(fields["Depth"]),
                    )
                ),
                "selection_reasons": reasons,
                "published_target_raw_values": {element: raw_value},
                "adapter_observations": [observation],
                "automated_checks": checks,
                "automated_status": "PASS" if all(checks.values()) else "FAIL",
                "reviewer": {
                    "decision": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": None,
                },
            }
        )
    pass_count = sum(record["automated_status"] == "PASS" for record in records)
    return {
        "review_version": REVIEW_VERSION,
        "source_id": candidate.source_id,
        "dataset_version": candidate.version,
        "snapshot_id": f"gemstat-open-archive:v3-seven-elements:{candidate.version}",
        "status": "prepared",
        "required_record_count": 30,
        "prepared_record_count": len(records),
        "automated_pass_count": pass_count,
        "completed_record_count": 0,
        "element_quotas": QUOTAS,
        "selection_strategy": (
            "Thirty source rows cover all registered fraction codes for seven elements, plus defined/undefined method, "
            "qualifier, quality, unit and water-type edge cases where quota permits."
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
        print(
            json.dumps(
                {"status": "PASS", "prepared": review["prepared_record_count"]},
                sort_keys=True,
            )
        )
        return (
            0
            if review["automated_pass_count"] == review["prepared_record_count"] == 30
            else 1
        )
    except (
        OSError,
        ValueError,
        ReviewError,
        source_adapters.SourceAdapterError,
    ) as exc:
        print(f"prepare_gemstat_multielement_review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
