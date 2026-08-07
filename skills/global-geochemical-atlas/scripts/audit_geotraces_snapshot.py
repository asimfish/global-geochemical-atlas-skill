#!/usr/bin/env python3
"""Audit the pinned GEOTRACES IDP2025 webODV seawater export."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

AUDIT_VERSION = "geotraces-idp2025-export-audit-v1"
TARGETS = ("Cu", "Ni", "Zn")


class AuditError(RuntimeError):
    """Raised when the frozen export cannot be reconciled exactly."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def optional_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def collection_audit(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise AuditError("--collection-info is required to prove parameter and QC coverage")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuditError("GEOTRACES collection metadata is unreadable") from exc
    if not isinstance(value, Mapping):
        raise AuditError("GEOTRACES collection metadata must be a JSON object")
    names = value.get("datavar_names")
    units = value.get("datavar_units")
    counts = value.get("datavar_data_counts")
    schemas = value.get("datavar_qfschema_ids")
    if not all(isinstance(item, list) for item in (names, units, counts, schemas)):
        raise AuditError("GEOTRACES collection metadata lacks aligned variable arrays")
    targets: dict[str, Any] = {}
    for analyte, expected_name in {"Cu": "Cu_D_CONC", "Ni": "Ni_D_CONC", "Zn": "Zn_D_CONC"}.items():
        try:
            index = names.index(expected_name)
        except ValueError as exc:
            raise AuditError(f"GEOTRACES collection lacks {expected_name}") from exc
        targets[analyte] = {
            "zero_based_index": index,
            "one_based_webodv_id": index + 1,
            "field": expected_name,
            "unit": units[index],
            "data_count": counts[index],
            "quality_schema_id": schemas[index],
        }
    arsenic_matches = [
        name for name in names if re.search(r"(^|_)As(_|$)|Arsenic", str(name), flags=re.IGNORECASE)
    ]
    return {
        "source_file_bytes": path.stat().st_size,
        "collection_name": value.get("name"),
        "description": value.get("description"),
        "station_count": value.get("station_count"),
        "cruise_count": len(value.get("cruise_names", [])),
        "metadata_variable_count": value.get("metavar_count"),
        "data_variable_count": value.get("datavar_count"),
        "targets": targets,
        "arsenic_variable_matches": arsenic_matches,
        "quality_schemas": value.get("qf_schemas", []),
    }


def audit(cache_dir: Path, collection_info: Path | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    adapter = source_adapters.get_adapter("geotraces-idp2025")
    candidate = adapter.discover({"sources": ["geotraces-idp2025"]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    records = list(adapter.parse(downloaded))
    data_file = downloaded[0]
    root = data_file.path.parent.parent
    archive_path = root / candidate.registry_entry["download"]["archive_filename"]
    expected = candidate.registry_entry["expected_counts"]

    target_counts: Counter[str] = Counter()
    qc_counts: dict[str, Counter[str]] = {analyte: Counter() for analyte in TARGETS}
    target_rows = 0
    cruises: set[str] = set()
    stations: set[tuple[str, str]] = set()
    coordinates: list[tuple[float, float]] = []
    depths: list[float] = []
    dates: list[str] = []
    for record in records:
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            raise AuditError(f"target mapping missing at {record.source_locator}")
        reported = 0
        for analyte in TARGETS:
            values = observations.get(analyte)
            if not isinstance(values, Mapping) or not str(values.get("value") or "").strip():
                continue
            reported += 1
            target_counts[analyte] += 1
            qc_counts[analyte][str(values.get("quality_flag") or "")] += 1
        if not reported:
            continue
        target_rows += 1
        cruise = str(record.fields.get("Cruise") or "")
        station = str(record.fields.get("Station") or "")
        cruises.add(cruise)
        stations.add((cruise, station))
        longitude = optional_float(record.fields.get("Longitude [degrees_east]"))
        latitude = optional_float(record.fields.get("Latitude [degrees_north]"))
        depth = optional_float(record.fields.get("DEPTH [m]"))
        if longitude is not None and latitude is not None:
            coordinates.append((longitude, latitude))
        if depth is not None:
            depths.append(depth)
        sampled_at = str(record.fields.get("yyyy-mm-ddThh:mm:ss.sss") or "")[:10]
        if sampled_at:
            dates.append(sampled_at)

    observed_counts = {
        "physical_rows": len(records),
        "target_bearing_rows": target_rows,
        "target_observations": sum(target_counts.values()),
        "selected_cruises": len(cruises),
        "selected_cruise_station_pairs": len(stations),
        "target_value_counts": dict(sorted(target_counts.items())),
        "target_quality_flag_counts": {
            analyte: dict(sorted(counts.items())) for analyte, counts in qc_counts.items()
        },
    }
    checks = {
        "physical_rows_match": observed_counts["physical_rows"] == expected["physical_rows"],
        "target_rows_match": observed_counts["target_bearing_rows"] == expected["target_bearing_rows"],
        "target_observations_match": observed_counts["target_observations"] == expected["target_observations"],
        "target_counts_match": observed_counts["target_value_counts"] == expected["target_value_counts"],
        "selected_cruises_match": observed_counts["selected_cruises"] == expected["selected_cruises"],
        "selected_stations_match": observed_counts["selected_cruise_station_pairs"]
        == expected["selected_cruise_station_pairs"],
        "all_target_units_preserved": all(
            values.get("unit") == "nmol/kg"
            for record in records
            for values in record.fields["_target_observations"].values()
        ),
    }
    if not all(checks.values()):
        raise AuditError(f"GEOTRACES reconciliation failed: {checks}")

    parameter_audit = collection_audit(collection_info)
    if parameter_audit["arsenic_variable_matches"]:
        raise AuditError("the collection inventory unexpectedly contains an arsenic variable")
    archive_members = [
        {
            "name": str(path.relative_to(data_file.path.parent)),
            "bytes": path.stat().st_size,
        }
        for path in sorted(data_file.path.parent.rglob("*"))
        if path.is_file()
    ]
    snapshot_id = f"geotraces-idp2025:{candidate.version}:{candidate.registry_entry['download']['observed_at']}"
    snapshot = {
        "snapshot_version": "geochemical-source-snapshot-v1",
        "source_id": candidate.source_id,
        "snapshot_id": snapshot_id,
        "observed_at": candidate.registry_entry["download"]["observed_at"],
        "request": {
            "url": candidate.registry_entry["download"]["exporter_landing_page"],
            "selection": candidate.registry_entry["download"]["selection"],
        },
        "response": {
            "filename": archive_path.name,
            "bytes": archive_path.stat().st_size,
        },
        "archive": {
            "member_count": len(archive_members),
            "members": archive_members,
        },
        "counts": observed_counts,
        "evidence": {
            "dataset_doi": candidate.dataset_doi,
            "dataset_version": candidate.version,
            "license": candidate.license_id,
            "primary_member": data_file.path.name,
            "primary_member_bytes": data_file.bytes,
            "collection_metadata_bytes": parameter_audit["source_file_bytes"],
        },
        "claim_boundary": (
            "This snapshot pins one official webODV export selection. It is not the complete IDP2025, "
            "a regular ocean grid or evidence that unsampled locations have no trace elements."
        ),
    }
    reconciliation = {
        "reconciliation_version": AUDIT_VERSION,
        "source_id": candidate.source_id,
        "snapshot_id": snapshot_id,
        "status": "PASS",
        "counts": observed_counts,
        "coverage": {
            "bbox": [
                min(item[0] for item in coordinates),
                min(item[1] for item in coordinates),
                max(item[0] for item in coordinates),
                max(item[1] for item in coordinates),
            ],
            "sample_depth_range_m": [min(depths), max(depths)],
            "sample_date_range": [min(dates), max(dates)],
        },
        "checks": checks,
        "parameter_inventory": parameter_audit,
        "limitations": [
            "Arsenic is absent and requires another water source.",
            "Rows with SeaDataNet flags 3 or 4 remain traceable raw observations but are not accepted for demos.",
            "Contributor-specific methods and citations must be followed through the cruise and IDP metadata links.",
        ],
    }
    candidate_audit = {
        "verification_version": AUDIT_VERSION,
        "source_id": candidate.source_id,
        "acquisition": {
            "request_url": candidate.registry_entry["download"]["exporter_landing_page"],
            "observed_at": candidate.registry_entry["download"]["observed_at"],
            "selection": candidate.registry_entry["download"]["selection"],
        },
        "archive": {
            "filename": archive_path.name,
            "bytes": archive_path.stat().st_size,
            "members": archive_members,
        },
        "observed_data": {
            "target_analytes": parameter_audit["targets"],
            "counts": observed_counts,
            "coverage": reconciliation["coverage"],
            "arsenic_variable_matches": [],
        },
        "observed_metadata": {
            "quality_schemas": parameter_audit["quality_schemas"],
            "source_fraction": "dissolved seawater",
            "source_unit": "nmol/kg",
            "collection_metadata_bytes": parameter_audit["source_file_bytes"],
        },
        "status": "verified_frozen_export",
        "claim_boundary": snapshot["claim_boundary"],
    }
    return snapshot, reconciliation, candidate_audit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--collection-info", required=True, type=Path)
    parser.add_argument("--snapshot-output", required=True, type=Path)
    parser.add_argument("--reconciliation-output", required=True, type=Path)
    parser.add_argument("--candidate-audit-output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        snapshot, reconciliation, candidate_audit = audit(args.cache_dir, args.collection_info)
        atomic_json(args.snapshot_output, snapshot)
        atomic_json(args.reconciliation_output, reconciliation)
        atomic_json(args.candidate_audit_output, candidate_audit)
        print(json.dumps({"status": "PASS", "snapshot_id": snapshot["snapshot_id"]}, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_geotraces_snapshot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
