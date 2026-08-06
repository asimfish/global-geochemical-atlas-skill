#!/usr/bin/env python3
"""Prepare unsigned 30-source-row review sheets for GEOROC and USGS soil."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import generate_demo_data as demos
import source_adapters

REVIEW_VERSION = "geochemical-human-review-v1"
ANALYTES = ("As", "Cu", "Ni", "Zn")
SUPPORTED_SOURCES = ("georoc-archaean", "usgs-conus-soil", "geotraces-idp2025")


class ReviewPreparationError(RuntimeError):
    """Raised when a review sheet cannot be prepared without guessing."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _unsigned_reviewer() -> dict[str, None]:
    return {"decision": None, "reviewer": None, "reviewed_at": None, "notes": None}


def _source_row(record: source_adapters.RawRecord) -> int:
    _, _, row_text = record.source_locator.partition("#row=")
    if not row_text.isdigit():
        raise ReviewPreparationError(f"source locator has no row number: {record.source_locator}")
    return int(row_text)


def _georoc_eligible(record: source_adapters.RawRecord) -> bool:
    material = demos._strip_citation_suffix(record.fields.get("MATERIAL")).upper()
    if material != "WR":
        return False
    if not demos._exact_georoc_coordinate(record, "LATITUDE MIN", "LATITUDE MAX"):
        return False
    if not demos._exact_georoc_coordinate(record, "LONGITUDE MIN", "LONGITUDE MAX"):
        return False
    if not str(record.fields.get("SAMPLE NAME") or "").strip():
        return False
    return any(demos._reported_float(record.fields.get(f"{analyte.upper()}(PPM)")) is not None for analyte in ANALYTES)


def _georoc_selection(records: Sequence[source_adapters.RawRecord]) -> list[tuple[source_adapters.RawRecord, list[str]]]:
    eligible = [record for record in records if _georoc_eligible(record)]
    by_file: dict[str, list[source_adapters.RawRecord]] = defaultdict(list)
    for record in eligible:
        by_file[str(record.fields.get("_source_file") or "")].append(record)
    selected: dict[str, tuple[source_adapters.RawRecord, set[str]]] = {}

    def add(record: source_adapters.RawRecord, reason: str) -> None:
        if record.source_record_id in selected:
            selected[record.source_record_id][1].add(reason)
        elif len(selected) < 30:
            selected[record.source_record_id] = (record, {reason})

    for filename in sorted(by_file):
        add(by_file[filename][0], "first_eligible_for_archive_member")
    partial = [
        record
        for record in eligible
        if sum(demos._reported_float(record.fields.get(f"{item.upper()}(PPM)")) is not None for item in ANALYTES)
        < len(ANALYTES)
    ]
    for record in partial:
        add(record, "target_missing_edge_case")
    multi_citation = [record for record in eligible if len(re.findall(r"\[([^\]]+)\]", str(record.fields.get("CITATIONS") or ""))) > 1]
    for record in multi_citation:
        add(record, "multiple_original_citations")
    spatial_orders = {
        "latitude_min_boundary": sorted(
            eligible,
            key=lambda item: float(demos._exact_georoc_coordinate(item, "LATITUDE MIN", "LATITUDE MAX")),
        ),
        "latitude_max_boundary": sorted(
            eligible,
            key=lambda item: float(demos._exact_georoc_coordinate(item, "LATITUDE MIN", "LATITUDE MAX")),
            reverse=True,
        ),
        "longitude_min_boundary": sorted(
            eligible,
            key=lambda item: float(demos._exact_georoc_coordinate(item, "LONGITUDE MIN", "LONGITUDE MAX")),
        ),
        "longitude_max_boundary": sorted(
            eligible,
            key=lambda item: float(demos._exact_georoc_coordinate(item, "LONGITUDE MIN", "LONGITUDE MAX")),
            reverse=True,
        ),
    }
    for reason, ordered in spatial_orders.items():
        if ordered:
            add(ordered[0], reason)
    if len(selected) < 30:
        step = max(1, len(eligible) // max(1, 30 - len(selected)))
        for record in eligible[::step]:
            add(record, "evenly_spaced_fill")
            if len(selected) == 30:
                break
    if len(selected) != 30:
        raise ReviewPreparationError(f"GEOROC selection produced {len(selected)} rows, expected 30")
    return [(record, sorted(reasons)) for record, reasons in selected.values()]


def _georoc_review(
    records: Sequence[source_adapters.RawRecord],
    files: Mapping[str, source_adapters.DownloadedFile],
    candidate: source_adapters.DatasetCandidate,
) -> list[dict[str, Any]]:
    references = {filename: demos._georoc_reference_map(item.path) for filename, item in files.items()}
    output: list[dict[str, Any]] = []
    for position, (record, reasons) in enumerate(_georoc_selection(records), start=1):
        filename = str(record.fields.get("_source_file") or "")
        downloaded = files[filename]
        latitude = demos._exact_georoc_coordinate(record, "LATITUDE MIN", "LATITUDE MAX")
        longitude = demos._exact_georoc_coordinate(record, "LONGITUDE MIN", "LONGITUDE MAX")
        sample_id = str(record.fields.get("SAMPLE NAME") or "").strip()
        raw_values = {item: str(record.fields.get(f"{item.upper()}(PPM)") or "").strip() for item in ANALYTES}
        citation_ids = re.findall(r"\[([^\]]+)\]", str(record.fields.get("CITATIONS") or ""))
        citations = [references[filename].get(item, f"[{item}] unresolved") for item in citation_ids]
        observations = []
        for analyte, raw_value in raw_values.items():
            if demos._reported_float(raw_value) is None:
                continue
            observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": "ppm",
                    "medium": "rock",
                    "sample_id": sample_id,
                    "latitude": latitude,
                    "longitude": longitude,
                    "material": demos._strip_citation_suffix(record.fields.get("MATERIAL")),
                    "rock_name": str(record.fields.get("ROCK NAME") or "").strip(),
                    "location": str(record.fields.get("LOCATION") or "").strip(),
                    "record_id": source_adapters.stable_record_id(
                        record.source_id,
                        record.source_record_id,
                        analyte,
                        raw_value,
                        "ppm",
                    ),
                }
            )
        checks = {
            "registered_member_hash_matches": downloaded.sha256 == demos.sha256_file(downloaded.path),
            "sample_id_preserved": bool(sample_id),
            "exact_point_coordinates_preserved": bool(latitude and longitude),
            "whole_rock_material_preserved": demos._strip_citation_suffix(record.fields.get("MATERIAL")).upper() == "WR",
            "target_values_preserved_without_imputation": len(observations)
            == sum(demos._reported_float(value) is not None for value in raw_values.values()),
            "citation_ids_resolved": bool(citation_ids) and all("unresolved" not in value for value in citations),
            "stable_observation_ids_unique": len({item["record_id"] for item in observations}) == len(observations),
        }
        output.append(
            {
                "review_id": f"georoc-archaean-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": sample_id,
                "selection_reasons": reasons,
                "published_target_raw_values": raw_values,
                "adapter_observations": observations,
                "automated_checks": checks,
                "automated_status": "PASS" if all(checks.values()) else "FAIL",
                "reviewer": _unsigned_reviewer(),
            }
        )
    return output


def _even_positions(length: int, count: int) -> list[int]:
    if length < count:
        raise ReviewPreparationError(f"cannot select {count} rows from {length}")
    if count == 1:
        return [0]
    positions = [round(index * (length - 1) / (count - 1)) for index in range(count)]
    if len(set(positions)) != count:
        raise ReviewPreparationError("even-position selection produced duplicates")
    return positions


def _usgs_selection(records: Sequence[source_adapters.RawRecord]) -> list[tuple[source_adapters.RawRecord, list[str]]]:
    layers = ("top-0-5cm", "a-horizon", "c-horizon")
    by_layer: dict[str, list[source_adapters.RawRecord]] = defaultdict(list)
    for record in records:
        layer = str(record.fields.get("_soil_layer") or "")
        if layer not in layers:
            continue
        prefix = {"top-0-5cm": "Top5_", "a-horizon": "A_", "c-horizon": "C_"}[layer]
        units = record.fields.get("_units")
        if not isinstance(units, Mapping):
            continue
        if not all(str(record.fields.get(f"{prefix}{item}") or "").strip() for item in ANALYTES):
            continue
        if not all(str(units.get(f"{prefix}{item}") or "").strip() for item in ANALYTES):
            continue
        if demos._reported_float(record.fields.get("Latitude")) is None or demos._reported_float(record.fields.get("Longitude")) is None:
            continue
        by_layer[layer].append(record)
    selected: list[tuple[source_adapters.RawRecord, list[str]]] = []
    for layer in layers:
        rows = by_layer[layer]
        for position in _even_positions(len(rows), 10):
            selected.append((rows[position], [f"soil_layer={layer}", "spatially_even_source_order"]))
    return selected


def _usgs_review(
    records: Sequence[source_adapters.RawRecord],
    files: Mapping[str, source_adapters.DownloadedFile],
    candidate: source_adapters.DatasetCandidate,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for position, (record, reasons) in enumerate(_usgs_selection(records), start=1):
        layer = str(record.fields.get("_soil_layer") or "")
        prefix = {"top-0-5cm": "Top5_", "a-horizon": "A_", "c-horizon": "C_"}[layer]
        units = record.fields["_units"]
        filename = str(record.fields.get("_source_file") or "")
        downloaded = files[filename]
        sample_id = str(record.fields.get(f"{prefix}LabID") or record.fields.get("SiteID") or "").strip()
        raw_values = {item: str(record.fields.get(f"{prefix}{item}") or "").strip() for item in ANALYTES}
        depth_min, depth_max = demos._depth_m(record)
        observations = []
        for analyte, raw_value in raw_values.items():
            unit = str(units.get(f"{prefix}{analyte}") or "").strip()
            observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": unit,
                    "medium": "soil",
                    "soil_layer": layer,
                    "sample_id": sample_id,
                    "latitude": str(record.fields.get("Latitude") or ""),
                    "longitude": str(record.fields.get("Longitude") or ""),
                    "sample_depth_min_m": depth_min,
                    "sample_depth_max_m": depth_max,
                    "record_id": source_adapters.stable_record_id(
                        record.source_id,
                        record.source_record_id,
                        analyte,
                        raw_value,
                        unit,
                    ),
                }
            )
        checks = {
            "registered_file_hash_matches": downloaded.sha256 == demos.sha256_file(downloaded.path),
            "sample_id_preserved": bool(sample_id),
            "coordinates_preserved": all(
                demos._reported_float(record.fields.get(field)) is not None for field in ("Latitude", "Longitude")
            ),
            "soil_layer_preserved": layer in {"top-0-5cm", "a-horizon", "c-horizon"},
            "four_target_values_preserved": len(observations) == 4 and all(raw_values.values()),
            "source_units_preserved": all(item["unit"] for item in observations),
            "depth_semantics_preserved": layer == "top-0-5cm" or bool(depth_min and depth_max),
            "stable_observation_ids_unique": len({item["record_id"] for item in observations}) == 4,
        }
        output.append(
            {
                "review_id": f"usgs-conus-soil-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": sample_id,
                "selection_reasons": reasons,
                "published_target_raw_values": raw_values,
                "adapter_observations": observations,
                "automated_checks": checks,
                "automated_status": "PASS" if all(checks.values()) else "FAIL",
                "reviewer": _unsigned_reviewer(),
            }
        )
    return output


def _geotraces_target_observations(record: source_adapters.RawRecord) -> Mapping[str, Mapping[str, str]]:
    observations = record.fields.get("_target_observations")
    if not isinstance(observations, Mapping):
        raise ReviewPreparationError(f"GEOTRACES target mapping is missing: {record.source_locator}")
    return {
        str(analyte): values
        for analyte, values in observations.items()
        if isinstance(values, Mapping) and str(values.get("value") or "").strip()
    }


def _geotraces_selection(
    records: Sequence[source_adapters.RawRecord],
) -> list[tuple[source_adapters.RawRecord, list[str]]]:
    eligible = [record for record in records if _geotraces_target_observations(record)]
    selected: dict[str, tuple[source_adapters.RawRecord, set[str]]] = {}

    def add(record: source_adapters.RawRecord, reason: str) -> None:
        if record.source_record_id in selected:
            selected[record.source_record_id][1].add(reason)
        elif len(selected) < 30:
            selected[record.source_record_id] = (record, {reason})

    for analyte in ("Cu", "Ni", "Zn"):
        for quality_flag in ("1", "2", "3", "4", "5", "6"):
            match = next(
                (
                    record
                    for record in eligible
                    if _geotraces_target_observations(record).get(analyte, {}).get("quality_flag")
                    == quality_flag
                ),
                None,
            )
            if match is not None:
                add(match, f"{analyte}_seadatanet_qc={quality_flag}")
    numeric_records = [
        record
        for record in eligible
        if all(
            demos._reported_float(record.fields.get(field)) is not None
            for field in ("Longitude [degrees_east]", "Latitude [degrees_north]", "DEPTH [m]")
        )
    ]
    boundary_orders = {
        "longitude_min_boundary": ("Longitude [degrees_east]", False),
        "longitude_max_boundary": ("Longitude [degrees_east]", True),
        "latitude_min_boundary": ("Latitude [degrees_north]", False),
        "latitude_max_boundary": ("Latitude [degrees_north]", True),
        "depth_min_boundary": ("DEPTH [m]", False),
        "depth_max_boundary": ("DEPTH [m]", True),
    }
    for reason, (field, reverse) in boundary_orders.items():
        ordered = sorted(numeric_records, key=lambda item: float(item.fields[field]), reverse=reverse)
        if ordered:
            add(ordered[0], reason)
    multi_analyte = [record for record in eligible if len(_geotraces_target_observations(record)) >= 2]
    if multi_analyte:
        add(multi_analyte[0], "multiple_target_analytes_on_sample")
    for position in _even_positions(len(eligible), 30):
        add(eligible[position], "evenly_spaced_target_bearing_fill")
        if len(selected) == 30:
            break
    if len(selected) != 30:
        raise ReviewPreparationError(f"GEOTRACES selection produced {len(selected)} rows, expected 30")
    return [(record, sorted(reasons)) for record, reasons in selected.values()]


def _geotraces_review(
    records: Sequence[source_adapters.RawRecord],
    files: Mapping[str, source_adapters.DownloadedFile],
    candidate: source_adapters.DatasetCandidate,
) -> list[dict[str, Any]]:
    downloaded = next(iter(files.values()))
    known_qc = set(candidate.registry_entry["quality_schema"]["flag_meanings"])
    output: list[dict[str, Any]] = []
    for position, (record, reasons) in enumerate(_geotraces_selection(records), start=1):
        targets = _geotraces_target_observations(record)
        cruise = str(record.fields.get("Cruise") or "").strip()
        station = str(record.fields.get("Station") or "").strip()
        depth = str(record.fields.get("DEPTH [m]") or "").strip()
        sample_id = f"{cruise}|{station}|{depth}m"
        observations = []
        for analyte, values in targets.items():
            raw_value = str(values.get("value") or "").strip()
            unit = str(values.get("unit") or "").strip()
            observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": unit,
                    "medium": "water",
                    "water_fraction": "dissolved",
                    "sample_id": sample_id,
                    "cruise": cruise,
                    "station": station,
                    "sample_depth_m": depth,
                    "sampled_at": str(record.fields.get("yyyy-mm-ddThh:mm:ss.sss") or ""),
                    "latitude": str(record.fields.get("Latitude [degrees_north]") or ""),
                    "longitude": str(record.fields.get("Longitude [degrees_east]") or ""),
                    "sampling_devices": str(record.fields.get("Sampling Devices") or ""),
                    "standard_deviation": str(values.get("standard_deviation") or ""),
                    "quality_schema": str(values.get("quality_schema") or ""),
                    "quality_flag": str(values.get("quality_flag") or ""),
                    "record_id": source_adapters.stable_record_id(
                        record.source_id,
                        record.source_record_id,
                        analyte,
                        raw_value,
                        unit,
                    ),
                }
            )
        checks = {
            "registered_member_hash_matches": downloaded.sha256 == demos.sha256_file(downloaded.path),
            "sample_identity_preserved": bool(cruise and station and depth),
            "coordinates_preserved": all(
                demos._reported_float(record.fields.get(field)) is not None
                for field in ("Latitude [degrees_north]", "Longitude [degrees_east]")
            ),
            "sample_depth_preserved": demos._reported_float(depth) is not None,
            "target_values_preserved_without_imputation": len(observations) == len(targets),
            "dissolved_fraction_and_unit_preserved": all(
                item["water_fraction"] == "dissolved" and item["unit"] == "nmol/kg"
                for item in observations
            ),
            "seadatanet_quality_flags_preserved": all(
                item["quality_schema"] == "SEADATANET" and item["quality_flag"] in known_qc
                for item in observations
            ),
            "stable_observation_ids_unique": len({item["record_id"] for item in observations})
            == len(observations),
        }
        output.append(
            {
                "review_id": f"geotraces-idp2025-review-{position:02d}",
                "source_locator": record.source_locator,
                "source_record_id": record.source_record_id,
                "sample_id": sample_id,
                "selection_reasons": reasons,
                "published_target_raw_values": {
                    analyte: str(values.get("value") or "") for analyte, values in targets.items()
                },
                "adapter_observations": observations,
                "automated_checks": checks,
                "automated_status": "PASS" if all(checks.values()) else "FAIL",
                "reviewer": _unsigned_reviewer(),
            }
        )
    return output


def prepare(source_id: str, cache_dir: Path) -> dict[str, Any]:
    adapter = source_adapters.get_adapter(source_id)
    candidate = adapter.discover({"sources": [source_id]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    records = list(adapter.parse(downloaded))
    files = {item.path.name: item for item in downloaded}
    if source_id == "georoc-archaean":
        review_records = _georoc_review(records, files, candidate)
        strategy = "Thirty whole-rock exact-coordinate source rows across archive members plus missing, citation and spatial edge cases."
        snapshot_id = f"doi:{candidate.dataset_doi}@{candidate.version}"
    elif source_id == "usgs-conus-soil":
        review_records = _usgs_review(records, files, candidate)
        strategy = "Ten spatially distributed source rows from each of 0-5 cm, A-horizon and C-horizon tables."
        snapshot_id = f"doi:{candidate.dataset_doi}@{candidate.version}"
    elif source_id == "geotraces-idp2025":
        review_records = _geotraces_review(records, files, candidate)
        strategy = (
            "Thirty target-bearing seawater rows spanning Cu/Ni/Zn, SeaDataNet QC edge flags, "
            "geographic/depth boundaries and evenly spaced source order."
        )
        snapshot_id = f"doi:{candidate.dataset_doi}@{candidate.version}#sha256:{downloaded[0].sha256}"
    else:
        raise ReviewPreparationError(f"unsupported source: {source_id}")
    pass_count = sum(record["automated_status"] == "PASS" for record in review_records)
    return {
        "review_version": REVIEW_VERSION,
        "source_id": source_id,
        "dataset_version": candidate.version,
        "snapshot_id": snapshot_id,
        "status": "prepared",
        "required_record_count": 30,
        "prepared_record_count": len(review_records),
        "automated_pass_count": pass_count,
        "completed_record_count": 0,
        "selection_strategy": strategy,
        "records": review_records,
        "claim_boundary": (
            "Automated PASS proves that the prepared comparison matches the hash-verified source and adapter. "
            "It is not human review; reviewer decisions remain null until a named reviewer signs each row."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=SUPPORTED_SOURCES)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        review = prepare(args.source, args.cache_dir)
        if args.output:
            atomic_json(args.output, review)
        print(json.dumps(review, ensure_ascii=False, sort_keys=True))
        return 0 if review["automated_pass_count"] == review["prepared_record_count"] == 30 else 1
    except (OSError, ValueError, ReviewPreparationError, source_adapters.SourceAdapterError) as exc:
        print(f"prepare_reference_human_review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
