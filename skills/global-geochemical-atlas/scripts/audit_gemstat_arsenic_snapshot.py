#!/usr/bin/env python3
"""Audit the pinned GEMStat v3 arsenic ZIP-member subset without hiding source defects."""

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

AUDIT_VERSION = "gemstat-v3-arsenic-audit-v1"


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

    parameters: Counter[str] = Counter()
    units: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    qualities: Counter[str] = Counter()
    water_types: Counter[str] = Counter()
    countries: set[str] = set()
    stations: set[str] = set()
    methods: set[tuple[str, str, str]] = set()
    observation_keys: Counter[tuple[str, ...]] = Counter()
    coordinates: list[tuple[float, float]] = []
    depths: list[float] = []
    dates: list[str] = []
    undefined_method_observations = 0
    pending_negative_sentinels = 0
    pending_extreme_mg_l = 0
    count = 0

    key_fields = (
        "GEMS Station Number", "Sample Date", "Sample Time", "Depth", "Parameter Code",
        "Analysis Method Code", "Value Flags", "Value", "Unit", "Data Quality",
        "Integrated Value", "Remark", "License Information",
    )
    for record in adapter.parse(downloaded):
        count += 1
        fields = record.fields
        station = fields.get("_station_metadata")
        method = fields.get("_method_metadata")
        if not isinstance(station, Mapping) or not isinstance(method, Mapping):
            raise AuditError(f"joined metadata missing at {record.source_locator}")
        parameter = str(fields["Parameter Code"])
        unit = str(fields["Unit"])
        quality = str(fields["Data Quality"])
        value = finite_float(fields["Value"], "arsenic value")
        method_code = str(fields["Analysis Method Code"])
        station_id = str(fields["GEMS Station Number"])
        parameters[parameter] += 1
        units[unit] += 1
        flags[str(fields["Value Flags"])] += 1
        qualities[quality] += 1
        water_types[str(station["Water Type"])] += 1
        countries.add(str(station["Country Name"]))
        stations.add(station_id)
        methods.add((parameter, method_code, unit))
        observation_keys[tuple(str(fields.get(name) or "") for name in key_fields)] += 1
        coordinates.append(
            (finite_float(station["Longitude"], "longitude"), finite_float(station["Latitude"], "latitude"))
        )
        depths.append(finite_float(fields["Depth"], "depth"))
        dates.append(str(fields["Sample Date"]))
        if method_code == "0":
            undefined_method_observations += 1
        if quality == "Pending review" and value == -999.999:
            pending_negative_sentinels += 1
        if quality == "Pending review" and unit == "mg/l" and value >= 1000:
            pending_extreme_mg_l += 1

    duplicate_extra = sum(multiplicity - 1 for multiplicity in observation_keys.values())
    duplicate_groups = sum(multiplicity > 1 for multiplicity in observation_keys.values())
    maximum_multiplicity = max(observation_keys.values())
    observed = {
        "arsenic_observations": count,
        "arsenic_station_count": len(stations),
        "arsenic_country_count": len(countries),
        "arsenic_parameter_counts": dict(sorted(parameters.items())),
        "unit_counts": dict(sorted(units.items())),
        "value_flag_counts": dict(sorted(flags.items())),
        "data_quality_counts": dict(sorted(qualities.items())),
        "water_type_counts": dict(sorted(water_types.items())),
        "method_combinations_used": len(methods),
        "undefined_method_observations": undefined_method_observations,
        "unmatched_method_rows": 0,
        "unmatched_station_rows": 0,
        "exact_duplicate_extra_observations": duplicate_extra,
        "exact_duplicate_groups": duplicate_groups,
        "maximum_exact_duplicate_multiplicity": maximum_multiplicity,
        "pending_review_negative_sentinels": pending_negative_sentinels,
        "pending_review_extreme_mg_l": pending_extreme_mg_l,
    }
    checks = {f"{key}_match": observed[key] == value for key, value in expected.items() if key in observed}
    if not all(checks.values()):
        raise AuditError(f"GEMStat arsenic reconciliation failed: {checks}")

    selected_members = [
        {
            "file_id": item.file_id,
            "filename": item.path.name,
            "bytes": item.bytes,
            "range_start": next(
                entry["range_start"] for entry in registry["download"]["selected_members"]
                if entry["file_id"] == item.file_id
            ),
            "range_end": next(
                entry["range_end"] for entry in registry["download"]["selected_members"]
                if entry["file_id"] == item.file_id
            ),
        }
        for item in downloaded
    ]
    snapshot_id = f"gemstat-open-archive:v3:{registry['download']['observed_at']}"
    coverage = {
        "country_count": len(countries),
        "water_types": dict(sorted(water_types.items())),
        "bbox": [
            min(item[0] for item in coordinates), min(item[1] for item in coordinates),
            max(item[0] for item in coordinates), max(item[1] for item in coordinates),
        ],
        "sample_depth_range_m": [min(depths), max(depths)],
        "sample_date_range": [min(dates), max(dates)],
    }
    limitations = [
        "The arsenic observations cover 33 contributing countries unevenly; this is not a uniform global freshwater grid.",
        "Dissolved, suspended and total arsenic fractions remain separate and are not interchangeable.",
        "449,714 observations use undefined method code 0, limiting method comparability.",
        "Censored values and all source quality labels are preserved; Pending review and Suspect rows are excluded from demos.",
        "5,655 extra exact duplicate observations are retained and flagged rather than silently removed.",
        "Three negative sentinel values and 78 extreme mg/l values are Pending review and cannot support anomaly claims.",
        "The publisher page and metadata files differ by one station and one parameter; both claims are recorded.",
    ]
    claim_boundary = (
        "This snapshot validates five byte-range-selected members from the official v3 ZIP by DOI, version, member identity, ranges and sizes. "
        "The complete archive was not downloaded locally. The subset supports traceable freshwater arsenic "
        "analysis only and does not prove global spatial completeness or cross-method comparability."
    )
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
        "publisher_archive_claim": {
            "filename": registry["download"]["archive_filename"],
            "bytes": registry["download"]["archive_bytes"],
            "locally_full_archive_verified": False,
        },
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
        "archive": snapshot["publisher_archive_claim"],
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
        print(f"audit_gemstat_arsenic_snapshot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
