#!/usr/bin/env python3
"""Create a deterministic, source-shaped D1 package for D2 integration tests."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lab_common import (
    D2_FIXTURE,
    atomic_write_json,
    prepare_empty_output_dir,
    repository_relative,
    sha256_file,
)

D1_VERSION = "d1-validation-stub-v1"

SOURCE_COLUMN_NAMES = {
    "record_id": "RecordKey",
    "source_record_id": "SourceRowKey",
    "sample_id": "SampleCode",
    "element_or_analyte": "ReportedAnalyte",
    "analyte_reported": "AnalyteLabel",
    "value": "ReportedResult",
    "unit": "ReportedUnit",
    "medium": "SampleMatrix",
    "measurement_basis": "ResultBasis",
    "value_qualifier": "LegacyQualifier",
    "detection_limit": "DetectionLimit",
    "detection_limit_unit": "DetectionLimitUnit",
    "latitude": "LatitudeReported",
    "longitude": "LongitudeReported",
    "source_crs": "CoordinateCRS",
    "coordinate_uncertainty_m": "CoordinateUncertaintyM",
    "geologic_unit": "GeologicUnitReported",
    "analytical_method": "AnalyticalMethodReported",
    "digestion_or_extraction": "PreparationMethodReported",
    "laboratory": "LaboratoryReported",
    "license": "SourceLicense",
    "source_tier": "SourceTier",
    "source_id": "DatasetKey",
    "source_locator": "SourceLocator",
    "sampled_at": "SampleDate",
    "sample_depth_min_m": "DepthFromM",
    "sample_depth_max_m": "DepthToM",
    "grain_fraction": "GrainFractionReported",
    "dataset_title": "DatasetTitle",
    "dataset_version": "DatasetVersion",
    "source_file": "OriginalSourceFile",
    "source_row": "OriginalSourceRow",
    "file_sha256": "OriginalFileSHA256",
}


def write_csv_atomic(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_d1_package(seed_path: Path, output_dir: Path) -> dict[str, Path]:
    if not seed_path.is_file():
        raise ValueError(f"seed CSV does not exist: {seed_path}")
    prepare_empty_output_dir(output_dir)
    seed_hash = sha256_file(seed_path)
    with seed_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("seed CSV has no header")
        seed_rows = list(reader)
    if not seed_rows:
        raise ValueError("seed CSV has no records")

    canonical_order = list(reader.fieldnames)
    for field in (
        "source_record_id",
        "analyte_reported",
        "dataset_title",
        "dataset_version",
        "source_file",
        "source_row",
        "file_sha256",
    ):
        if field not in canonical_order:
            canonical_order.append(field)

    unknown_columns = sorted(set(canonical_order) - set(SOURCE_COLUMN_NAMES))
    if unknown_columns:
        raise ValueError(f"D1 stub has no source-column mapping for: {', '.join(unknown_columns)}")

    source_rows: list[dict[str, str]] = []
    for source_row_number, seed_row in enumerate(seed_rows, start=2):
        canonical: dict[str, str] = dict(seed_row)
        record_id = canonical.get("record_id", "").strip()
        canonical["source_record_id"] = f"fixture-row:{record_id or source_row_number}"
        canonical["analyte_reported"] = canonical.get("element_or_analyte", "")
        canonical["dataset_title"] = "D2 validation synthetic geochemistry slice"
        canonical["dataset_version"] = "v1"
        canonical["source_file"] = seed_path.name
        canonical["source_row"] = str(source_row_number)
        canonical["file_sha256"] = seed_hash
        source_rows.append(
            {SOURCE_COLUMN_NAMES[field]: canonical.get(field, "") for field in canonical_order}
        )

    schema_map = {field: SOURCE_COLUMN_NAMES[field] for field in canonical_order}
    export_path = output_dir / "d1_export.csv"
    schema_map_path = output_dir / "schema_map.json"
    manifest_path = output_dir / "source_manifest.json"
    source_headers = [SOURCE_COLUMN_NAMES[field] for field in canonical_order]
    write_csv_atomic(export_path, source_headers, source_rows)
    atomic_write_json(schema_map_path, schema_map)
    manifest: dict[str, Any] = {
        "manifest_version": "d1-source-manifest-v1",
        "pipeline_version": D1_VERSION,
        "status": "success",
        "network_used": False,
        "synthetic_test_data": True,
        "scientific_conclusion_allowed": False,
        "source": {
            "path": repository_relative(seed_path),
            "sha256": seed_hash,
            "license": "CC0-1.0",
            "record_count": len(seed_rows),
        },
        "export": {
            "path": export_path.name,
            "sha256": sha256_file(export_path),
            "record_count": len(source_rows),
            "format": "UTF-8 CSV; one analyte determination per row",
        },
        "schema_map": {
            "path": schema_map_path.name,
            "sha256": sha256_file(schema_map_path),
            "direction": "canonical_field_to_source_column",
        },
        "rules_applied": [
            "Preserved source values, units, qualifiers, coordinates, and all input rows.",
            "Added deterministic source-row provenance without standardizing scientific values.",
            "Did not impute censored values or remove duplicate candidates.",
        ],
    }
    atomic_write_json(manifest_path, manifest)
    return {"export": export_path, "schema_map": schema_map_path, "manifest": manifest_path}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the deterministic D1 package used by D2 full-flow tests.")
    parser.add_argument("--seed", type=Path, default=D2_FIXTURE, help="Licensed local synthetic seed CSV")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty output directory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        outputs = build_d1_package(args.seed, args.output_dir)
    except (OSError, ValueError, csv.Error) as exc:
        parser.error(str(exc))
    print(json.dumps({key: str(path) for key, path in outputs.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
