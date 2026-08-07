#!/usr/bin/env python3
"""Build a derived SQLite search index from a validated D1 archive bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import validate_acquisition

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_SCHEMA = SKILL_DIR / "references" / "sqlite-schema.sql"
DEFAULT_BUNDLE = SKILL_DIR / "fixtures" / "schema-v1" / "archive-bundle.json"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_bundle(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"archive bundle does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"archive bundle is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("archive bundle must be a JSON object")
    validation = validate_acquisition.validate_bundle(value)
    if validation["status"] != "PASS":
        raise ValueError(f"archive bundle validation failed: {validation['errors']}")
    return value


def _populate(connection: sqlite3.Connection, bundle: Mapping[str, Any]) -> None:
    connection.execute("INSERT INTO archive_metadata VALUES (?, ?)", ("archive_model", "d1-archive-model-v1"))
    connection.execute("INSERT INTO archive_metadata VALUES (?, ?)", ("bundle_version", bundle["bundle_version"]))
    for dataset in bundle["datasets"]:
        connection.execute(
            "INSERT INTO datasets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                dataset["dataset_id"],
                dataset["source_id"],
                dataset["title"],
                dataset["publisher"],
                dataset["dataset_doi"],
                dataset["dataset_version"],
                dataset["landing_page"],
                dataset["license_id"],
                dataset["license_url"],
                dataset["retrieved_at"],
            ),
        )
        for item in dataset["files"]:
            connection.execute(
                "INSERT INTO dataset_files VALUES (?, ?, ?, ?, ?, ?)",
                (
                    dataset["dataset_id"],
                    item["file_id"],
                    item["filename"],
                    item["source_url"],
                    item["bytes"],
                    item["sha256"],
                ),
            )
        connection.execute(
            "INSERT INTO archive_fts(entity_type, entity_id, searchable_text) VALUES (?, ?, ?)",
            ("dataset", dataset["dataset_id"], " ".join((dataset["title"], dataset["publisher"], dataset["source_id"]))),
        )
    for publication in bundle["publications"]:
        connection.execute(
            "INSERT INTO publications VALUES (?, ?, ?, ?, ?)",
            (
                publication["publication_id"],
                publication["doi"],
                publication["citation"],
                publication["title"],
                publication["year"],
            ),
        )
        for dataset_id in publication["dataset_ids"]:
            for relation_type in publication["relation_types"]:
                connection.execute(
                    "INSERT INTO publication_datasets VALUES (?, ?, ?)",
                    (publication["publication_id"], dataset_id, relation_type),
                )
        connection.execute(
            "INSERT INTO archive_fts(entity_type, entity_id, searchable_text) VALUES (?, ?, ?)",
            (
                "publication",
                publication["publication_id"],
                " ".join(filter(None, (publication["citation"], publication["title"], publication["doi"]))),
            ),
        )
    for event in bundle["sampling_events"]:
        location = event["location"]
        connection.execute(
            "INSERT INTO sampling_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event["sampling_event_id"],
                event["dataset_id"],
                event["site_id"],
                event["sampled_at_raw"],
                event["collection_method_raw"],
                location["latitude_raw"],
                location["longitude_raw"],
                location["source_crs"],
                location["latitude"],
                location["longitude"],
                location["coordinate_uncertainty_m"],
                location["elevation_m"],
                location["depth_min_m"],
                location["depth_max_m"],
                location["place_raw"],
            ),
        )
        if location["place_raw"]:
            connection.execute(
                "INSERT INTO archive_fts(entity_type, entity_id, searchable_text) VALUES (?, ?, ?)",
                ("sampling_event", event["sampling_event_id"], location["place_raw"]),
            )
    for sample in bundle["samples"]:
        connection.execute(
            "INSERT INTO samples (sample_id, native_sample_id, igsn, parent_sample_id, sampling_event_id, "
            "medium_raw, material_raw, sample_type_raw, sample_type, sample_type_mapping_status, "
            "geographic_context_raw, survey_area, map_sheet, cruise_track, lithology_raw, lithology, "
            "geologic_unit_raw, geologic_age_raw, tectonic_setting_raw, matched_geologic_unit, "
            "geology_map_source, geology_map_version, match_method, match_scale, boundary_distance_m, "
            "match_uncertainty, soil_horizon_raw, soil_horizon, sediment_environment, grain_fraction_raw, "
            "water_body_type, water_fraction, filtered_state_raw, description_raw) "
            "VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sample["sample_id"],
                sample["native_sample_id"],
                sample["igsn"],
                sample["sampling_event_id"],
                sample["medium_raw"],
                sample["material_raw"],
                sample.get("sample_type_raw"),
                sample.get("sample_type"),
                sample.get("sample_type_mapping_status"),
                sample.get("geographic_context_raw"),
                sample.get("survey_area"),
                sample.get("map_sheet"),
                sample.get("cruise_track"),
                sample["lithology_raw"],
                sample.get("lithology"),
                sample["geologic_unit_raw"],
                sample.get("geologic_age_raw"),
                sample.get("tectonic_setting_raw"),
                sample.get("matched_geologic_unit"),
                sample.get("geology_map_source"),
                sample.get("geology_map_version"),
                sample.get("match_method"),
                sample.get("match_scale"),
                sample.get("boundary_distance_m"),
                sample.get("match_uncertainty"),
                sample["soil_horizon_raw"],
                sample.get("soil_horizon"),
                sample.get("sediment_environment"),
                sample["grain_fraction_raw"],
                sample.get("water_body_type"),
                sample.get("water_fraction"),
                sample["filtered_state_raw"],
                sample["description_raw"],
            ),
        )
        connection.execute(
            "INSERT INTO archive_fts(entity_type, entity_id, searchable_text) VALUES (?, ?, ?)",
            (
                "sample",
                sample["sample_id"],
                " ".join(
                    filter(
                        None,
                        (
                            sample["native_sample_id"],
                            sample["igsn"],
                            sample["medium_raw"],
                            sample["material_raw"],
                            sample.get("sample_type_raw"),
                            sample.get("sample_type"),
                            sample.get("geographic_context_raw"),
                            sample["lithology_raw"],
                            sample.get("lithology"),
                            sample["geologic_unit_raw"],
                            sample.get("matched_geologic_unit"),
                            sample["description_raw"],
                        ),
                    )
                ),
            ),
        )
    for sample in bundle["samples"]:
        if sample["parent_sample_id"]:
            connection.execute(
                "UPDATE samples SET parent_sample_id = ? WHERE sample_id = ?",
                (sample["parent_sample_id"], sample["sample_id"]),
            )
    for method in bundle["methods"]:
        connection.execute(
            "INSERT INTO analytical_methods (method_id, method_code_raw, method_scope, method_assignment_basis, "
            "preparation_raw, digestion_or_extraction_raw, technique_raw, instrument_raw, laboratory_raw, "
            "calibration_raw, quantitation_limit_raw, blank_qc_raw, replicate_qc_raw, method_source_locator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                method["method_id"],
                method["method_code_raw"],
                method.get("method_scope"),
                method.get("method_assignment_basis"),
                method["preparation_raw"],
                method["digestion_or_extraction_raw"],
                method["technique_raw"],
                method["instrument_raw"],
                method["laboratory_raw"],
                method["calibration_raw"],
                method.get("quantitation_limit_raw"),
                method.get("blank_qc_raw"),
                method.get("replicate_qc_raw"),
                method.get("method_source_locator"),
            ),
        )
        for publication_id in method["publication_ids"]:
            connection.execute("INSERT INTO method_publications VALUES (?, ?)", (method["method_id"], publication_id))
        connection.execute(
            "INSERT INTO archive_fts(entity_type, entity_id, searchable_text) VALUES (?, ?, ?)",
            (
                "method",
                method["method_id"],
                " ".join(
                    filter(
                        None,
                        (
                            method["method_code_raw"],
                            method["preparation_raw"],
                            method["digestion_or_extraction_raw"],
                            method["technique_raw"],
                            method["instrument_raw"],
                            method["laboratory_raw"],
                        ),
                    )
                ),
            ),
        )
    for run in bundle["acquisition_runs"]:
        connection.execute(
            "INSERT INTO acquisition_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run["acquisition_run_id"],
                _json(run["request"]),
                _json(run["dataset_ids"]),
                _json(run["schema_versions"]),
                _json(run["vocabulary_versions"]),
                run["started_at"],
                run["finished_at"],
                run["status"],
                run["cache_status"],
                _json(run["counts"]),
                _json(run["outputs"]),
            ),
        )
    for item in bundle["provenance"]:
        connection.execute(
            "INSERT INTO provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item["provenance_id"],
                item["source_id"],
                item["dataset_id"],
                item["acquisition_run_id"],
                item["source_record_id"],
                item["source_locator"],
                item["source_file"],
                item["source_sheet"],
                item["source_row"],
                item["source_column"],
                item["input_sha256"],
                item["adapter_name"],
                item["adapter_version"],
                _json(item["processing_steps"]),
            ),
        )
    for observation in bundle["observations"]:
        connection.execute(
            "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                observation["observation_id"],
                observation["sample_id"],
                observation["method_id"],
                observation["provenance_id"],
                observation["analyte_reported"],
                observation["value_raw"],
                observation["parsed_value"],
                observation["value_qualifier"],
                observation["unit_raw"],
                observation["measurement_basis_raw"],
                observation["detection_limit_raw"],
                observation["parsed_detection_limit"],
                observation["detection_limit_unit_raw"],
                observation["uncertainty_raw"],
                observation["replicate_id"],
            ),
        )


def build_index(bundle_path: Path, output: Path, schema_path: Path = DEFAULT_SCHEMA) -> dict[str, Any]:
    if output.exists():
        raise ValueError(f"refusing to overwrite existing index: {output}")
    bundle = _load_bundle(bundle_path)
    try:
        schema_sql = schema_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"SQLite schema does not exist: {schema_path}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_handle = tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    )
    temporary_path = Path(temporary_handle.name)
    temporary_handle.close()
    try:
        connection = sqlite3.connect(temporary_path)
        try:
            connection.executescript(schema_sql)
            with connection:
                _populate(connection, bundle)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise ValueError(f"SQLite integrity failure: integrity={integrity}, foreign_keys={foreign_keys}")
            counts = {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("datasets", "dataset_files", "sampling_events", "samples", "analytical_methods", "observations", "provenance")
            }
        finally:
            connection.close()
        os.replace(temporary_path, output)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return {
        "status": "PASS",
        "index_version": "d1-sqlite-index-v1",
        "output": str(output),
        "bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "counts": counts,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = build_index(args.bundle, args.output, args.schema)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
