#!/usr/bin/env python3
"""Export a validated D1 archive bundle to the backward-compatible V4 exchange CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import generate_demo_data
import validate_acquisition


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_BUNDLE = SKILL_DIR / "fixtures" / "schema-v2" / "archive-bundle.json"


class ExportError(RuntimeError):
    """Raised when an archive cannot be exported without losing relationships."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExportError(f"cannot read archive bundle: {path}") from exc
    if not isinstance(value, dict):
        raise ExportError("archive bundle root must be an object")
    validation = validate_acquisition.validate_bundle(value)
    if validation["status"] != "PASS":
        raise ExportError(
            "archive bundle validation failed: " + "; ".join(validation["errors"])
        )
    return value


def _index(
    items: Sequence[Mapping[str, Any]], field: str
) -> dict[str, Mapping[str, Any]]:
    return {str(item[field]): item for item in items}


def _missing(entity: Mapping[str, Any], field: str) -> str:
    reasons = entity.get("missing_reasons")
    return str(reasons.get(field) or "") if isinstance(reasons, Mapping) else ""


def _joined(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return (
        json.dumps(values, ensure_ascii=False, separators=(",", ":")) if values else ""
    )


def export_rows(bundle: Mapping[str, Any]) -> list[dict[str, str]]:
    datasets = _index(bundle["datasets"], "dataset_id")
    publications = _index(bundle["publications"], "publication_id")
    events = _index(bundle["sampling_events"], "sampling_event_id")
    samples = _index(bundle["samples"], "sample_id")
    methods = _index(bundle["methods"], "method_id")
    provenance = _index(bundle["provenance"], "provenance_id")
    rows: list[dict[str, str]] = []
    for observation in bundle["observations"]:
        sample = samples[str(observation["sample_id"])]
        method = methods[str(observation["method_id"])]
        evidence = provenance[str(observation["provenance_id"])]
        event = events[str(sample["sampling_event_id"])]
        dataset = datasets[str(evidence["dataset_id"])]
        location = event.get("location")
        location = location if isinstance(location, Mapping) else {}
        publication_ids = method.get("publication_ids")
        publication_id = (
            str(publication_ids[0])
            if isinstance(publication_ids, list) and publication_ids
            else ""
        )
        publication = publications.get(publication_id, {})
        method_scope = str(method.get("method_scope") or "")
        sample_type = str(sample.get("sample_type") or "")
        geologic_unit_raw = str(sample.get("geologic_unit_raw") or "")
        row = {field: "" for field in generate_demo_data.INPUT_COLUMNS}
        row.update(
            {
                "record_id": str(observation["observation_id"]),
                "source_record_id": str(evidence["source_record_id"]),
                "sample_id": str(sample["sample_id"]),
                "element_or_analyte": str(observation["analyte_reported"]),
                "value": str(observation["value_raw"]),
                "unit": str(observation.get("unit_raw") or ""),
                "medium": str(sample["medium_raw"]),
                "measurement_basis": str(
                    observation.get("measurement_basis_raw") or ""
                ),
                "value_qualifier": str(observation.get("value_qualifier") or ""),
                "detection_limit": str(observation.get("detection_limit_raw") or ""),
                "detection_limit_unit": str(
                    observation.get("detection_limit_unit_raw") or ""
                ),
                "latitude": str(
                    location.get("latitude")
                    if location.get("latitude") is not None
                    else ""
                ),
                "longitude": str(
                    location.get("longitude")
                    if location.get("longitude") is not None
                    else ""
                ),
                "source_crs": str(location.get("source_crs") or ""),
                "coordinate_uncertainty_m": str(
                    location.get("coordinate_uncertainty_m")
                    if location.get("coordinate_uncertainty_m") is not None
                    else ""
                ),
                # Legacy geologic_unit remains blank. V4 never copies geographic context into it.
                "geologic_unit": "",
                "analytical_method": str(
                    method.get("technique_raw") or method.get("method_code_raw") or ""
                ),
                "digestion_or_extraction": str(
                    method.get("digestion_or_extraction_raw") or ""
                ),
                "laboratory": str(method.get("laboratory_raw") or ""),
                "license": str(dataset.get("license_id") or ""),
                "source_tier": "institutional_repository",
                "source_id": str(evidence["source_id"]),
                "source_locator": str(evidence["source_locator"]),
                "sampled_at": str(event.get("sampled_at_raw") or ""),
                "sample_depth_min_m": str(
                    location.get("depth_min_m")
                    if location.get("depth_min_m") is not None
                    else ""
                ),
                "sample_depth_max_m": str(
                    location.get("depth_max_m")
                    if location.get("depth_max_m") is not None
                    else ""
                ),
                "grain_fraction": str(sample.get("grain_fraction_raw") or ""),
                "sample_type_raw": str(sample.get("sample_type_raw") or ""),
                "sample_type": sample_type,
                "sample_type_mapping_status": str(
                    sample.get("sample_type_mapping_status") or ""
                ),
                "sample_type_missing_reason": _missing(sample, "sample_type")
                if not sample_type
                else "",
                "geographic_context_raw": str(
                    sample.get("geographic_context_raw")
                    or location.get("place_raw")
                    or ""
                ),
                "survey_area": str(sample.get("survey_area") or ""),
                "map_sheet": str(sample.get("map_sheet") or ""),
                "cruise_track": str(sample.get("cruise_track") or ""),
                "lithology_raw": str(sample.get("lithology_raw") or ""),
                "lithology": str(sample.get("lithology") or ""),
                "soil_horizon_raw": str(sample.get("soil_horizon_raw") or ""),
                "soil_horizon": str(sample.get("soil_horizon") or ""),
                "sediment_environment": str(sample.get("sediment_environment") or ""),
                "water_body_type": str(sample.get("water_body_type") or ""),
                "water_fraction": str(sample.get("water_fraction") or ""),
                "filtered_state": str(sample.get("filtered_state_raw") or ""),
                "geologic_unit_raw": geologic_unit_raw,
                "geologic_age_raw": str(sample.get("geologic_age_raw") or ""),
                "tectonic_setting_raw": str(sample.get("tectonic_setting_raw") or ""),
                "matched_geologic_unit": str(sample.get("matched_geologic_unit") or ""),
                "geology_map_source": str(sample.get("geology_map_source") or ""),
                "geology_map_version": str(sample.get("geology_map_version") or ""),
                "match_method": str(sample.get("match_method") or ""),
                "match_scale": str(sample.get("match_scale") or ""),
                "boundary_distance_m": str(
                    sample.get("boundary_distance_m")
                    if sample.get("boundary_distance_m") is not None
                    else ""
                ),
                "match_uncertainty": str(sample.get("match_uncertainty") or ""),
                "geology_missing_reason": _missing(sample, "geologic_unit_raw")
                if not geologic_unit_raw
                else "",
                "method_scope": method_scope,
                "method_assignment_basis": str(
                    method.get("method_assignment_basis") or ""
                ),
                "preparation": str(method.get("preparation_raw") or ""),
                "analytical_technique": str(method.get("technique_raw") or ""),
                "instrument": str(method.get("instrument_raw") or ""),
                "quantitation_limit": str(
                    method.get("quantitation_limit_raw") or ""
                ).split(" ", 1)[0],
                "quantitation_limit_unit": (
                    str(method.get("quantitation_limit_raw") or "").split(" ", 1)[1]
                    if " " in str(method.get("quantitation_limit_raw") or "")
                    else ""
                ),
                "reference_materials": _joined(method.get("reference_materials_raw")),
                "method_source_locator": str(method.get("method_source_locator") or ""),
                "method_publication_id": publication_id,
                "method_missing_reason": _missing(method, "technique_raw")
                if not method.get("technique_raw")
                else "",
                "publication_id": publication_id,
                "publication_doi": str(publication.get("doi") or ""),
                "citation_text_raw": str(publication.get("citation") or ""),
                "citation_scope": "method" if publication_id else "dataset",
                "citation_assignment_basis": "method_publication_relation"
                if publication_id
                else "dataset_metadata",
                "citation_resolution_status": "resolved"
                if publication_id
                else "not_reported",
                "citation_missing_reason": "" if publication_id else "not_reported",
                "access_status": "registered_landing_and_download",
                "research_use_status": "not_assessed_separately",
                "license_url": str(dataset.get("license_url") or ""),
                "license_scope": "dataset",
                "attribution_required": "false"
                if dataset.get("license_id") == "CC0-1.0"
                else "true",
                "redistribution_status": "not_assessed_separately",
                "terms_verified_at": str(dataset.get("retrieved_at") or ""),
            }
        )
        rows.append(row)
    return rows


def write_exchange(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    if path.exists():
        raise ExportError(f"refusing to overwrite exchange CSV: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=generate_demo_data.INPUT_COLUMNS,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        rows = export_rows(_load(args.bundle))
        write_exchange(args.output, rows)
    except (OSError, ExportError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"status": "PASS", "record_count": len(rows), "output": str(args.output)},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
