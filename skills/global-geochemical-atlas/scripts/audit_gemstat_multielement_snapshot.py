#!/usr/bin/env python3
"""Audit the pinned GEMStat v3 seven-element ZIP-range snapshot."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

AUDIT_VERSION = "gemstat-v3-seven-element-audit-v1"


class AuditError(RuntimeError):
    """Raised when the selected official members no longer reconcile exactly."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def finite_float(value: Any, label: str) -> float:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise AuditError(f"invalid {label}: {value!r}") from exc
    if not math.isfinite(parsed):
        raise AuditError(f"non-finite {label}: {value!r}")
    return parsed


def audit(cache_dir: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    adapter = source_adapters.get_adapter("gemstat-open-archive")
    candidate = adapter.discover({"sources": ["gemstat-open-archive"]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    registry = candidate.registry_entry
    expected = registry["expected_counts"]

    elements: Counter[str] = Counter()
    parameters: Counter[str] = Counter()
    units: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    qualities: Counter[str] = Counter()
    water_types: Counter[str] = Counter()
    undefined_methods: Counter[str] = Counter()
    method_combinations: set[tuple[str, str, str]] = set()
    countries: set[str] = set()
    stations: set[str] = set()
    physical_samples: set[str] = set()
    bbox: list[float] | None = None
    depth_range: list[float] | None = None
    date_range: list[str] | None = None
    count = 0

    for record in adapter.parse(downloaded):
        fields = record.fields
        station = fields.get("_station_metadata")
        method = fields.get("_method_metadata")
        if not isinstance(station, Mapping) or not isinstance(method, Mapping):
            raise AuditError(f"joined metadata missing at {record.source_locator}")
        count += 1
        element = str(fields["_element"])
        parameter = str(fields["Parameter Code"])
        unit = str(fields["Unit"])
        method_code = str(fields["Analysis Method Code"])
        station_id = str(fields["GEMS Station Number"])
        date = str(fields["Sample Date"])
        depth = finite_float(fields["Depth"], "depth")
        longitude = finite_float(station["Longitude"], "longitude")
        latitude = finite_float(station["Latitude"], "latitude")
        finite_float(fields["Value"], "element value")
        elements[element] += 1
        parameters[parameter] += 1
        units[unit] += 1
        flags[str(fields["Value Flags"])] += 1
        qualities[str(fields["Data Quality"])] += 1
        water_types[str(station["Water Type"])] += 1
        countries.add(str(station["Country Name"]))
        stations.add(station_id)
        method_combinations.add((parameter, method_code, unit))
        if method_code == "0":
            undefined_methods[element] += 1
        physical_samples.add(
            "|".join((station_id, date, str(fields["Sample Time"]), str(fields["Depth"])))
        )
        bbox = (
            [longitude, latitude, longitude, latitude]
            if bbox is None
            else [min(bbox[0], longitude), min(bbox[1], latitude), max(bbox[2], longitude), max(bbox[3], latitude)]
        )
        depth_range = [depth, depth] if depth_range is None else [min(depth_range[0], depth), max(depth_range[1], depth)]
        date_range = [date, date] if date_range is None else [min(date_range[0], date), max(date_range[1], date)]

    checks = {
        "target_observations_match": count == expected["target_observations"],
        "target_value_counts_match": dict(sorted(elements.items())) == expected["target_value_counts"],
        "excluded_parameter_counts_registered": expected["excluded_parameter_counts"] == {"Cr-VI": 15855},
        "all_joined_rows_have_station_metadata": True,
        "all_joined_rows_have_method_metadata": True,
    }
    if not all(checks.values()):
        raise AuditError(f"GEMStat seven-element reconciliation failed: {checks}")

    registered_members = {item["file_id"]: item for item in registry["download"]["selected_members"]}
    selected_members = [
        {
            "file_id": item.file_id,
            "filename": item.path.name,
            "bytes": item.bytes,
            "range_start": registered_members[item.file_id]["range_start"],
            "range_end": registered_members[item.file_id]["range_end"],
        }
        for item in downloaded
    ]
    snapshot_id = f"gemstat-open-archive:v3-seven-elements:{registry['download']['observed_at']}"
    observed = {
        "target_observations": count,
        "target_value_counts": dict(sorted(elements.items())),
        "parameter_counts": dict(sorted(parameters.items())),
        "excluded_parameter_counts": expected["excluded_parameter_counts"],
        "distinct_physical_samples": len(physical_samples),
        "station_count": len(stations),
        "country_count": len(countries),
        "unit_counts": dict(sorted(units.items())),
        "value_flag_counts": dict(sorted(flags.items())),
        "data_quality_counts": dict(sorted(qualities.items())),
        "water_type_counts": dict(sorted(water_types.items())),
        "method_combinations_used": len(method_combinations),
        "undefined_method_observations": dict(sorted(undefined_methods.items())),
        "defined_method_observations": count - sum(undefined_methods.values()),
        "unmatched_method_rows": 0,
        "unmatched_station_rows": 0,
    }
    coverage = {
        "country_count": len(countries),
        "station_count": len(stations),
        "distinct_physical_samples": len(physical_samples),
        "water_types": dict(sorted(water_types.items())),
        "bbox": bbox,
        "sample_depth_range_m": depth_range,
        "sample_date_range": date_range,
    }
    claim_boundary = (
        "This snapshot verifies seven element CSVs and four metadata/readme members selected by exact ZIP byte ranges. "
        "It describes voluntary freshwater observations rather than continuous global coverage. Operational fractions, "
        "units, methods and water-body types remain separate; Cr-VI is retained upstream but excluded from elemental Cr."
    )
    limitations = [
        "Coverage is spatially and temporally uneven and does not form a global grid.",
        "Rows sharing station, date, time and depth are one physical sampling event across elements and fractions.",
        "Dissolved, extractable, suspended and total fractions are not interchangeable.",
        "Most observations use undefined method code 0 and therefore remain in method-unknown comparison groups.",
        "Censored values and all source quality labels remain traceable; production filtering is use-case dependent.",
        "The workflow verifies only the selected byte ranges, member identities, decoded sizes, schemas and counts.",
    ]
    publisher_archive = {
        "filename": registry["download"]["archive_filename"],
        "bytes": registry["download"]["archive_bytes"],
        "locally_full_archive_verified": False,
    }
    snapshot = {
        "snapshot_version": "geochemical-source-snapshot-v1",
        "source_id": candidate.source_id,
        "snapshot_id": snapshot_id,
        "observed_at": registry["download"]["observed_at"],
        "request": {
            "record_doi": candidate.dataset_doi,
            "archive_url": registry["download"]["archive_url"],
            "selection": [item["filename"] for item in selected_members],
        },
        "publisher_archive_claim": publisher_archive,
        "selected_members": selected_members,
        "counts": observed,
        "coverage": coverage,
        "evidence": {
            "dataset_doi": candidate.dataset_doi,
            "concept_doi": registry["concept_doi"],
            "dataset_version": candidate.version,
            "license": candidate.license_id,
        },
        "claim_boundary": claim_boundary,
    }
    reconciliation = {
        "reconciliation_version": AUDIT_VERSION,
        "source_id": candidate.source_id,
        "snapshot_id": snapshot_id,
        "status": "PASS",
        "counts": observed,
        "coverage": coverage,
        "checks": checks,
        "limitations": limitations,
    }
    candidate_audit = {
        "verification_version": AUDIT_VERSION,
        "source_id": candidate.source_id,
        "acquisition": {
            "record_doi": candidate.dataset_doi,
            "observed_at": registry["download"]["observed_at"],
            "mode": registry["download"]["mode"],
        },
        "archive": publisher_archive,
        "selected_members": selected_members,
        "observed_data": {
            "target_analytes": registry["target_analytes"],
            "counts": observed,
            "coverage": coverage,
        },
        "observed_metadata": {
            "station_rows": expected["station_metadata_rows"],
            "station_unique_ids": expected["station_metadata_unique_ids"],
            "station_exact_duplicates": expected["station_metadata_exact_duplicate_rows"],
            "parameter_rows": expected["parameter_metadata_rows"],
            "method_rows": expected["method_metadata_rows"],
        },
        "status": "verified_selective_official_archive_members",
        "limitations": limitations,
        "claim_boundary": claim_boundary,
    }
    return snapshot, reconciliation, candidate_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--snapshot-output", required=True, type=Path)
    parser.add_argument("--reconciliation-output", required=True, type=Path)
    parser.add_argument("--candidate-audit-output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot, reconciliation, candidate_audit = audit(args.cache_dir)
        atomic_json(args.snapshot_output, snapshot)
        atomic_json(args.reconciliation_output, reconciliation)
        atomic_json(args.candidate_audit_output, candidate_audit)
        print(json.dumps({"status": "PASS", "snapshot_id": snapshot["snapshot_id"]}, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_gemstat_multielement_snapshot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
