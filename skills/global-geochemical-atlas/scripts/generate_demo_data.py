#!/usr/bin/env python3
"""Generate deterministic, provenance-complete D1 demo slices from verified caches."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from source_adapters import (
    DownloadedFile,
    RawRecord,
    SourceAdapterError,
    get_adapter,
    load_source_registry,
    stable_record_id,
)
import v4_semantics

DEMO_VERSION = "d1-demo-slice-v1"
ANALYTES = ("As", "Cu", "Ni", "Zn")
MARCHEM_REVIEW_SAMPLE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "candidate-audits"
    / "marchem-inorganic-20260805T102709Z.json"
)
LEGACY_INPUT_COLUMNS = (
    "record_id",
    "source_record_id",
    "sample_id",
    "element_or_analyte",
    "value",
    "unit",
    "medium",
    "measurement_basis",
    "value_qualifier",
    "detection_limit",
    "detection_limit_unit",
    "latitude",
    "longitude",
    "source_crs",
    "coordinate_uncertainty_m",
    "geologic_unit",
    "analytical_method",
    "digestion_or_extraction",
    "laboratory",
    "license",
    "source_tier",
    "source_id",
    "source_locator",
    "sampled_at",
    "sample_depth_min_m",
    "sample_depth_max_m",
    "grain_fraction",
)

# Optional V4 exchange columns. Older V3 inputs remain readable; generators now
# always emit these headers so information extracted by adapters is not lost at
# the D1 -> D2 boundary.
V4_INPUT_COLUMNS = (
    "sample_type_raw",
    "sample_type",
    "sample_type_mapping_status",
    "sample_type_missing_reason",
    "material_raw",
    "geographic_context_raw",
    "survey_area",
    "map_sheet",
    "cruise_track",
    "lithology_raw",
    "lithology",
    "soil_horizon_raw",
    "soil_horizon",
    "soil_horizon_missing_reason",
    "sediment_environment",
    "water_body_type",
    "water_fraction",
    "filtered_state",
    "geologic_unit_raw",
    "geologic_age_raw",
    "tectonic_setting_raw",
    "matched_geologic_unit",
    "geology_map_source",
    "geology_map_source_id",
    "geology_map_version",
    "match_method",
    "match_scale",
    "boundary_distance_m",
    "match_uncertainty",
    "match_status",
    "match_candidates",
    "coordinate_status",
    "geology_missing_reason",
    "method_scope",
    "method_candidates",
    "method_assignment_basis",
    "preparation",
    "analytical_technique",
    "instrument",
    "quantitation_limit",
    "quantitation_limit_unit",
    "reference_materials",
    "method_source_locator",
    "method_publication_id",
    "method_missing_reason",
    "citation_id_raw",
    "publication_id",
    "publication_doi",
    "citation_text_raw",
    "citation_scope",
    "citation_assignment_basis",
    "upstream_primary_source_id",
    "citation_resolution_status",
    "citation_missing_reason",
    "access_status",
    "research_use_status",
    "license_url",
    "license_scope",
    "attribution_required",
    "redistribution_status",
    "terms_verified_at",
)

INPUT_COLUMNS = LEGACY_INPUT_COLUMNS + V4_INPUT_COLUMNS


class DemoError(RuntimeError):
    """Raised when a deterministic demo cannot be generated safely."""


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _reported_float(value: Any) -> float | None:
    text = str(value or "").strip()
    try:
        parsed = float(text)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def _exact_georoc_coordinate(record: RawRecord, minimum: str, maximum: str) -> str:
    lower = _reported_float(record.fields.get(minimum))
    upper = _reported_float(record.fields.get(maximum))
    if lower is None or upper is None or lower != upper:
        return ""
    return format(lower, ".12g")


def _strip_citation_suffix(value: Any) -> str:
    return re.sub(r"\s*\[[^\]]+\](?:\[[^\]]+\])*\s*$", "", str(value or "")).strip()


def _georoc_reference_map(path: Path) -> dict[str, str]:
    references: dict[str, str] = {}
    in_references = False
    with path.open("r", encoding="latin-1", newline="") as handle:
        for row in csv.reader(handle):
            first = str(row[0] if row else "").strip()
            if first == "References:":
                in_references = True
                continue
            if not in_references or not first:
                continue
            match = re.match(r"^\[([^\]]+)\]\s*(.*)$", first)
            if match:
                references[match.group(1)] = first
    return references


def _base_evidence(
    record: RawRecord,
    downloaded: DownloadedFile,
    candidate: Any,
    output_record_id: str,
    analyte: str,
) -> dict[str, Any]:
    file_locator, _, row_text = record.source_locator.partition("#row=")
    return {
        "record_id": output_record_id,
        "source_record_id": record.source_record_id,
        "source_id": record.source_id,
        "source_locator": record.source_locator,
        "source_file": file_locator,
        "source_row": int(row_text) if row_text.isdigit() else None,
        "source_file_bytes": downloaded.bytes,
        "source_file_url": downloaded.source_url,
        "dataset_title": candidate.title,
        "dataset_doi": candidate.dataset_doi,
        "dataset_version": candidate.version,
        "retrieved_at": downloaded.retrieved_at,
        "license": candidate.license_id,
        "analyte_reported": analyte,
        "generation_version": DEMO_VERSION,
    }


def georoc_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    references: Mapping[str, Mapping[str, str]],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit % len(ANALYTES) != 0:
        raise DemoError("GEOROC observation limit must be divisible by 4 for balanced analytes")
    per_analyte_limit = observation_limit // len(ANALYTES)
    selected_per_analyte: Counter[str] = Counter()
    rows: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for record in records:
        if all(selected_per_analyte[item] >= per_analyte_limit for item in ANALYTES):
            break
        material = _strip_citation_suffix(record.fields.get("MATERIAL")).upper()
        if material != "WR":
            continue
        latitude = _exact_georoc_coordinate(record, "LATITUDE MIN", "LATITUDE MAX")
        longitude = _exact_georoc_coordinate(record, "LONGITUDE MIN", "LONGITUDE MAX")
        if not latitude or not longitude:
            continue
        sample_id = str(record.fields.get("SAMPLE NAME") or "").strip()
        if not sample_id:
            continue
        downloaded = files.get(str(record.fields.get("_source_file")))
        if downloaded is None:
            raise DemoError(f"GEOROC record references an unknown member: {record.source_locator}")
        for analyte in ANALYTES:
            if selected_per_analyte[analyte] >= per_analyte_limit:
                continue
            original_value = str(record.fields.get(f"{analyte.upper()}(PPM)") or "").strip()
            if _reported_float(original_value) is None:
                continue
            record_id = stable_record_id(
                record.source_id,
                record.source_record_id,
                analyte,
                original_value,
                "ppm",
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": sample_id,
                    "element_or_analyte": analyte,
                    "value": original_value,
                    "unit": "ppm",
                    "medium": "rock",
                    "measurement_basis": "GEOROC_precompiled_selected_value",
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": str(record.fields.get("LOCATION") or "").strip(),
                    "analytical_method": "",
                    "digestion_or_extraction": "",
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "official_curated",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": "",
                    "material_raw": str(record.fields.get("MATERIAL") or "").strip(),
                    "lithology_raw": str(record.fields.get("ROCK NAME") or "").strip(),
                    "geologic_age_raw": str(record.fields.get("AGE") or "").strip(),
                    "tectonic_setting_raw": str(record.fields.get("TECTONIC SETTING") or "").strip(),
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            citation_ids = re.findall(r"\[([^\]]+)\]", str(record.fields.get("CITATIONS") or ""))
            article_citations = [
                references.get(downloaded.path.name, {}).get(citation_id, f"[{citation_id}] unresolved")
                for citation_id in citation_ids
            ]
            article_dois = sorted(
                {
                    match.group(1).rstrip(".,;)")
                    for citation in article_citations
                    for match in [re.search(r"\bdoi:\s*(10\.\d{4,9}/\S+)", citation, flags=re.IGNORECASE)]
                    if match
                }
            )
            entry.update(
                {
                    "citation_ids": citation_ids,
                    "article_citations": article_citations,
                    "article_dois": article_dois,
                    "selection_rule": "whole-rock; exact point coordinates; balanced As/Cu/Ni/Zn; source order",
                    "material_raw": str(record.fields.get("MATERIAL") or "").strip(),
                    "lithology_raw": str(record.fields.get("ROCK NAME") or "").strip(),
                    "geologic_age_raw": str(record.fields.get("AGE") or "").strip(),
                    "tectonic_setting_raw": str(record.fields.get("TECTONIC SETTING") or "").strip(),
                    "scientific_note": "GEOROC precompiled selected value; not every replicate determination.",
                }
            )
            evidence.append(entry)
            selected_source_rows.add(record.source_record_id)
            selected_per_analyte[analyte] += 1
    if len(rows) != observation_limit:
        raise DemoError(f"GEOROC produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence, len(selected_source_rows)


def _depth_m(record: RawRecord) -> tuple[str, str]:
    layer = str(record.fields.get("_soil_layer") or "")
    if layer == "top-0-5cm":
        return "0", "0.05"
    prefix = "A_" if layer == "a-horizon" else "C_"
    text = str(record.fields.get(f"{prefix}Depth") or "").strip()
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*", text)
    if not match:
        return "", ""
    return format(float(match.group(1)) / 100, ".12g"), format(float(match.group(2)) / 100, ".12g")


def usgs_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    layers = ("top-0-5cm", "a-horizon", "c-horizon")
    if observation_limit % (len(layers) * len(ANALYTES)) != 0:
        raise DemoError("USGS observation limit must be divisible by 12 for balanced layers and analytes")
    site_limit = observation_limit // (len(layers) * len(ANALYTES))
    selected_per_layer: Counter[str] = Counter()
    rows: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for record in records:
        layer = str(record.fields.get("_soil_layer") or "")
        if layer not in layers or selected_per_layer[layer] >= site_limit:
            continue
        latitude = str(record.fields.get("Latitude") or "").strip()
        longitude = str(record.fields.get("Longitude") or "").strip()
        if _reported_float(latitude) is None or _reported_float(longitude) is None:
            continue
        prefix = {"top-0-5cm": "Top5_", "a-horizon": "A_", "c-horizon": "C_"}[layer]
        downloaded = files.get(str(record.fields.get("_source_file")))
        if downloaded is None:
            raise DemoError(f"USGS record references an unknown file: {record.source_locator}")
        analyte_values: list[tuple[str, str, str]] = []
        units = record.fields.get("_units")
        if not isinstance(units, Mapping):
            raise DemoError("USGS record has no units mapping")
        for analyte in ANALYTES:
            field = f"{prefix}{analyte}"
            original_value = str(record.fields.get(field) or "").strip()
            unit = str(units.get(field) or "").strip()
            if not original_value or not unit:
                break
            analyte_values.append((analyte, original_value, unit))
        if len(analyte_values) != len(ANALYTES):
            continue
        depth_min, depth_max = _depth_m(record)
        sample_id = str(record.fields.get(f"{prefix}LabID") or record.fields.get("SiteID") or "").strip()
        for analyte, original_value, unit in analyte_values:
            record_id = stable_record_id(
                record.source_id,
                record.source_record_id,
                analyte,
                original_value,
                unit,
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": sample_id,
                    "element_or_analyte": analyte,
                    "value": original_value,
                    "unit": unit,
                    "medium": "soil",
                    "measurement_basis": "total_or_near_total_<2mm",
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "",
                    "analytical_method": "",
                    "digestion_or_extraction": "",
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "government",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": str(record.fields.get("CollDate") or "").strip(),
                    "sample_depth_min_m": depth_min,
                    "sample_depth_max_m": depth_max,
                    "grain_fraction": "<2 mm",
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [candidate.dataset_doi],
                    "selection_rule": "balanced first source rows per layer; analytes As/Cu/Ni/Zn; source order",
                    "soil_layer": layer,
                }
            )
            evidence.append(entry)
            selected_source_rows.add(record.source_record_id)
        selected_per_layer[layer] += 1
        if all(selected_per_layer[item] >= site_limit for item in layers):
            break
    if len(rows) != observation_limit:
        raise DemoError(f"USGS produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence, len(selected_source_rows)


def _marchem_depth_m(record: RawRecord) -> tuple[str, str]:
    minimum = _reported_float(record.fields.get("Slice_interval_from_cm"))
    maximum = _reported_float(record.fields.get("Slice_interval_to_cm"))
    if minimum is None or maximum is None:
        return "", ""
    return format(minimum / 100, ".12g"), format(maximum / 100, ".12g")


def _marchem_review_rows() -> list[dict[str, Any]]:
    try:
        evidence = json.loads(MARCHEM_REVIEW_SAMPLE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DemoError("MarChem prepared review sample is unreadable") from exc
    rows = evidence.get("prepared_human_review_sample")
    if not isinstance(rows, list) or len(rows) != 30:
        raise DemoError("MarChem prepared review sample must contain exactly 30 records")
    return rows


def marchem_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit % len(ANALYTES) != 0:
        raise DemoError("MarChem observation limit must be divisible by 4")
    sample_limit = observation_limit // len(ANALYTES)
    review_rows = [
        row
        for row in _marchem_review_rows()
        if any(str(value or "").strip() for value in row.get("target_raw_values", {}).values())
    ]
    if sample_limit > len(review_rows):
        raise DemoError("MarChem fixture is capped at the 28 target-bearing prepared review rows")
    by_source_row: dict[int, RawRecord] = {}
    for record in records:
        _, _, row_text = record.source_locator.partition("#row=")
        if row_text.isdigit():
            by_source_row[int(row_text)] = record
    data_file = next((item for item in files.values() if item.file_id == "data"), None)
    if data_file is None:
        raise DemoError("MarChem fixture has no verified data member")

    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for prepared in review_rows[:sample_limit]:
        source_row = prepared.get("source_row_number")
        record = by_source_row.get(source_row)
        if record is None:
            raise DemoError(f"MarChem prepared source row is missing: {source_row}")
        if str(record.fields.get("Sample_code") or "") != prepared.get("sample_code"):
            raise DemoError(f"MarChem review sample changed at source row {source_row}")
        methods = record.fields.get("_lab_parameters")
        if not isinstance(methods, Mapping):
            raise DemoError(f"MarChem method mapping is missing at source row {source_row}")
        depth_min, depth_max = _marchem_depth_m(record)
        for analyte in ANALYTES:
            field_name = target_fields[analyte]
            raw_value = str(record.fields.get(field_name) or "").strip()
            if raw_value != prepared.get("target_raw_values", {}).get(analyte):
                raise DemoError(f"MarChem prepared {analyte} value changed at source row {source_row}")
            method = methods.get(field_name)
            if not isinstance(method, Mapping):
                raise DemoError(f"MarChem {analyte} method is missing at source row {source_row}")
            unit = str(method.get("Unit") or "").strip()
            record_id = stable_record_id(
                record.source_id,
                record.source_record_id,
                analyte,
                raw_value,
                unit,
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": str(record.fields.get("Sample_code") or ""),
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": "sediment",
                    "measurement_basis": "dry_weight_partial_nitric_acid",
                    "value_qualifier": "",
                    "detection_limit": str(method.get("LLQ") or ""),
                    "detection_limit_unit": unit,
                    "latitude": str(record.fields.get("Latitude") or ""),
                    "longitude": str(record.fields.get("Longitude") or ""),
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "",
                    "analytical_method": str(method.get("Analysis_method") or ""),
                    "digestion_or_extraction": str(method.get("Sample_preparation_method") or ""),
                    "laboratory": str(method.get("Laboratory") or ""),
                    "license": candidate.license_id,
                    "source_tier": "government",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": str(record.fields.get("Cruise_year") or ""),
                    "sample_depth_min_m": depth_min,
                    "sample_depth_max_m": depth_max,
                    "grain_fraction": "",
                }
            )
            entry = _base_evidence(record, data_file, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [],
                    "selection_rule": "prepared stratified 30-row review sample; four target analytes per row",
                    "snapshot_id": candidate.version,
                    "batch_code": str(record.fields.get("Batch_code") or ""),
                    "cruise_year": str(record.fields.get("Cruise_year") or ""),
                    "station_event_code": str(record.fields.get("Station_event_code") or ""),
                    "sampling_tool": str(record.fields.get("Sampling_tool") or ""),
                    "core_code": str(record.fields.get("Core_code") or ""),
                    "metadata_source_locator": method.get("_metadata_source_locator"),
                    "metadata_batch_expression": method.get("_metadata_batch_expression"),
                    "lab_parameter_code": method.get("Lab_parameter_code"),
                    "wet_or_dry_weight": method.get("Wet_or_dry_weight"),
                    "llq": method.get("LLQ"),
                    "accreditation_status": method.get("_accreditation_status"),
                    "digestion_scope": "partial",
                    "not_total_content": True,
                    "review_selection_reasons": prepared.get("selection_reasons", []),
                }
            )
            evidence_rows.append(entry)
            selected_source_rows.add(record.source_record_id)
    if len(rows) != observation_limit:
        raise DemoError(f"MarChem produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


def geotraces_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    analytes = ("Cu", "Ni", "Zn")
    if observation_limit % len(analytes) != 0:
        raise DemoError("GEOTRACES observation limit must be divisible by 3")
    per_analyte_limit = observation_limit // len(analytes)
    selected_per_analyte: Counter[str] = Counter()
    accepted_qc = set(candidate.registry_entry["quality_schema"]["accepted_for_demo"])
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for record in records:
        if all(selected_per_analyte[item] >= per_analyte_limit for item in analytes):
            break
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            raise DemoError(f"GEOTRACES target mapping is missing: {record.source_locator}")
        latitude = str(record.fields.get("Latitude [degrees_north]") or "").strip()
        longitude = str(record.fields.get("Longitude [degrees_east]") or "").strip()
        depth = str(record.fields.get("DEPTH [m]") or "").strip()
        if any(_reported_float(value) is None for value in (latitude, longitude, depth)):
            continue
        filename = str(record.fields.get("_source_file") or "")
        downloaded = files.get(filename)
        if downloaded is None:
            raise DemoError(f"GEOTRACES record references an unknown file: {record.source_locator}")
        cruise = str(record.fields.get("Cruise") or "").strip()
        station = str(record.fields.get("Station") or "").strip()
        sample_id = f"{cruise}|{station}|{depth}m"
        for analyte in analytes:
            if selected_per_analyte[analyte] >= per_analyte_limit:
                continue
            values = observations.get(analyte)
            if not isinstance(values, Mapping):
                continue
            raw_value = str(values.get("value") or "").strip()
            quality_flag = str(values.get("quality_flag") or "").strip()
            unit = str(values.get("unit") or "").strip()
            if _reported_float(raw_value) is None or quality_flag not in accepted_qc or unit != "nmol/kg":
                continue
            analytical_method = str(values.get("analytical_method") or "")
            method_candidates = values.get("method_metadata_candidates")
            if not isinstance(method_candidates, list) or not method_candidates:
                raise DemoError(f"GEOTRACES contributor/method connection is missing: {record.source_locator}")
            record_id = stable_record_id(
                record.source_id,
                record.source_record_id,
                analyte,
                raw_value,
                unit,
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": sample_id,
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": "water",
                    "measurement_basis": "dissolved_seawater_molar_per_mass",
                    "value_qualifier": "reported",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "global_ocean_cruise_track",
                    "analytical_method": analytical_method,
                    "digestion_or_extraction": (
                        "dissolved_fraction; linked BODC cruise-analyte method record"
                        if analytical_method
                        else "dissolved_fraction; multiple linked BODC method records unresolved to observation"
                    ),
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "official_curated",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": str(record.fields.get("yyyy-mm-ddThh:mm:ss.sss") or ""),
                    "sample_depth_min_m": depth,
                    "sample_depth_max_m": depth,
                    "grain_fraction": "",
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [candidate.dataset_doi],
                    "selection_rule": "dissolved Cu/Ni/Zn; SeaDataNet QC 1 or 2; valid coordinates and depth; balanced source order",
                    "cruise": cruise,
                    "station": station,
                    "sample_depth_m": depth,
                    "sampling_devices": str(record.fields.get("Sampling Devices") or ""),
                    "cruise_information_link": str(record.fields.get("Cruise Information Link") or ""),
                    "seadatanet_quality_flag": quality_flag,
                    "standard_deviation": str(values.get("standard_deviation") or ""),
                    "water_fraction": "dissolved",
                    "method_metadata_status": str(values.get("method_metadata_status") or ""),
                    "method_metadata_candidates": method_candidates,
                    "method_source_locator": str(values.get("variable_metadata_locator") or ""),
                    "scientific_note": (
                        "nmol/kg is preserved. A single cruise-analyte method record is assigned only when the export "
                        "contains exactly one candidate; multi-record candidate sets remain unresolved."
                    ),
                }
            )
            evidence_rows.append(entry)
            selected_source_rows.add(record.source_record_id)
            selected_per_analyte[analyte] += 1
    if len(rows) != observation_limit:
        raise DemoError(f"GEOTRACES produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


def gemstat_demo(
    records: Iterable[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit != 56:
        raise DemoError("GEMStat demo is fixed at 56 observations: eight for each of seven elements")
    expected_files = {
        "Arsenic.csv",
        "Chromium.csv",
        "Copper.csv",
        "Mercury.csv",
        "Nickel.csv",
        "Lead.csv",
        "Zinc.csv",
    }
    if expected_files - set(files):
        raise DemoError(f"GEMStat observation members are missing: {sorted(expected_files - set(files))}")
    bucket_targets = {
        "As-Dis": 3,
        "As-Sus": 2,
        "As-Tot": 3,
        "Cr-Dis": 3,
        "Cr-Ext": 2,
        "Cr-Tot": 3,
        **{
            f"{element}-{fraction}": 2
            for element in ("Cu", "Hg", "Ni", "Pb", "Zn")
            for fraction in ("Dis", "Ext", "Sus", "Tot")
        },
    }
    buckets: dict[str, dict[str, list[RawRecord]]] = {
        key: {"censored": [], "reported": []} for key in bucket_targets
    }
    for record in records:
        fields = record.fields
        station = fields.get("_station_metadata")
        if not isinstance(station, Mapping):
            raise DemoError(f"GEMStat station join is missing: {record.source_locator}")
        value = _reported_float(fields.get("Value"))
        if (
            value is None
            or value < 0
            or fields.get("Data Quality") not in {"Good", "Fair"}
            or fields.get("Analysis Method Code") == "0"
            or (fields.get("Unit") == "mg/l" and value >= 1000)
        ):
            continue
        parameter = str(fields.get("Parameter Code") or "")
        if parameter not in buckets:
            continue
        qualifier_bucket = "censored" if fields.get("Value Flags") == "<" else "reported"
        capacity = bucket_targets[parameter]
        if len(buckets[parameter][qualifier_bucket]) < capacity:
            buckets[parameter][qualifier_bucket].append(record)

    selected: list[RawRecord] = []
    for key, target in bucket_targets.items():
        censored = buckets[key]["censored"][:target]
        reported = buckets[key]["reported"][: target - len(censored)]
        cell = [*censored, *reported]
        if len(cell) != target:
            raise DemoError(f"GEMStat demo bucket {key} produced {len(cell)} rows, expected {target}")
        selected.extend(cell)
    element_order = {element: index for index, element in enumerate(("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"))}
    selected.sort(
        key=lambda item: (
            element_order[str(item.fields["_element"])],
            int(item.source_locator.partition("#row=")[2]),
        )
    )

    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    for record in selected:
        fields = record.fields
        station = fields["_station_metadata"]
        method = fields["_method_metadata"]
        raw_value = str(fields["Value"])
        unit = str(fields["Unit"])
        unit_basis = unit.lower().replace("µ", "u").replace("/", "_per_").replace(" ", "_")
        qualifier = str(fields["Value Flags"])
        fraction = str(fields["_water_fraction"])
        depth = str(fields["Depth"])
        sampled_at = str(fields["Sample Date"])
        if fields.get("Sample Time"):
            sampled_at += "T" + str(fields["Sample Time"])
        sample_id = "|".join(
            (str(fields["GEMS Station Number"]), sampled_at, depth)
        )
        element = str(fields["_element"])
        record_id = stable_record_id(
            record.source_id, record.source_record_id, element, raw_value, unit
        )
        method_name = str(method.get("Method Name") or method.get("Method Description") or "")
        rows.append(
            {
                "record_id": record_id,
                "source_record_id": record.source_record_id,
                "sample_id": sample_id,
                "element_or_analyte": element,
                "value": raw_value,
                "unit": unit,
                "medium": "water",
                "measurement_basis": f"freshwater_{fraction}_operational_fraction_{unit_basis}",
                "value_qualifier": qualifier,
                "detection_limit": raw_value if qualifier == "<" else "",
                "detection_limit_unit": unit if qualifier == "<" else "",
                "latitude": str(station["Latitude"]),
                "longitude": str(station["Longitude"]),
                "source_crs": "EPSG:4326",
                "coordinate_uncertainty_m": "",
                "geologic_unit": "",
                "analytical_method": method_name,
                "digestion_or_extraction": f"GEMStat {fraction} operational fraction",
                "laboratory": "",
                "license": candidate.license_id,
                "source_tier": "official_curated",
                "source_id": record.source_id,
                "source_locator": record.source_locator,
                "sampled_at": sampled_at,
                "sample_depth_min_m": depth,
                "sample_depth_max_m": depth,
                "grain_fraction": "",
            }
        )
        entry = _base_evidence(record, files[str(fields["_source_file"])], candidate, record_id, element)
        entry.update(
            {
                "article_citations": [candidate.registry_entry["citation"]],
                "article_dois": [candidate.dataset_doi],
                "selection_rule": (
                    "Good/Fair source quality; defined method; nonnegative and nonextreme; eight observations per element; "
                    "registered operational fractions balanced within each element; up to one censored value per parameter"
                ),
                "station_id": fields["GEMS Station Number"],
                "country": station["Country Name"],
                "water_type": station["Water Type"],
                "sample_depth_m": depth,
                "water_fraction": fraction,
                "parameter_code": fields["Parameter Code"],
                "analysis_method_code": fields["Analysis Method Code"],
                "analysis_method_name": method_name,
                "method_source_locator": method.get("_metadata_source_locator"),
                "station_source_locators": station.get("_metadata_source_locators"),
                "source_value_flag": qualifier,
                "source_data_quality": fields["Data Quality"],
                "scientific_note": (
                    "Dissolved, extractable, suspended and total operational fractions are not interchangeable. "
                    "Cr-VI is excluded from elemental chromium, and censored values retain their limits."
                ),
            }
        )
        evidence_rows.append(entry)
    return rows, evidence_rows, len({record.source_record_id for record in selected})


def wqp_sacramento_demo(
    records: Iterable[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit != 48:
        raise DemoError("WQP Sacramento demo is fixed at 48 observations")
    source_records = list(records)
    if len(source_records) != 189:
        raise DemoError(f"WQP Sacramento produced {len(source_records)} source rows, expected 189")

    selected: list[RawRecord] = []
    selected_ids: set[str] = set()

    def add_first(predicate: Any) -> None:
        for record in source_records:
            if predicate(record.fields) and record.source_record_id not in selected_ids:
                selected.append(record)
                selected_ids.add(record.source_record_id)
                return
        raise DemoError("WQP Sacramento could not satisfy a required demo stratum")

    add_first(lambda fields: fields.get("ResultDetectionConditionText") == "Not Detected")
    add_first(lambda fields: fields.get("ActivityTypeCode") == "Quality Control Sample-Field Replicate")
    add_first(lambda fields: fields.get("ResultStatusIdentifier") == "Preliminary")
    add_first(
        lambda fields: fields.get("ResultStatusIdentifier") == "Accepted"
        and fields.get("ActivityTypeCode") == "Sample-Routine"
    )
    for index in (round(i * (len(source_records) - 1) / 47) for i in range(48)):
        record = source_records[index]
        if record.source_record_id not in selected_ids:
            selected.append(record)
            selected_ids.add(record.source_record_id)
        if len(selected) == observation_limit:
            break
    for record in source_records:
        if len(selected) == observation_limit:
            break
        if record.source_record_id not in selected_ids:
            selected.append(record)
            selected_ids.add(record.source_record_id)
    if len(selected) != observation_limit:
        raise DemoError(f"WQP Sacramento selected {len(selected)} observations, expected {observation_limit}")
    selected.sort(key=lambda record: str(record.fields["ActivityStartDate"]) + str(record.fields.get("ActivityStartTime/Time") or ""))

    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    result_file = files["results.csv"]
    for record in selected:
        fields = record.fields
        values = fields["_target_observations"]["As"]
        station = fields["_station_metadata"]
        sampled_at = str(fields["ActivityStartDate"])
        sample_time = str(fields.get("ActivityStartTime/Time") or "")
        if sample_time:
            sampled_at += "T" + sample_time
        raw_value = str(values["value"])
        unit = str(values["unit"])
        record_id = stable_record_id(record.source_id, record.source_record_id, "As", raw_value, unit)
        rows.append(
            {
                "record_id": record_id,
                "source_record_id": record.source_record_id,
                "sample_id": str(fields["ActivityIdentifier"]),
                "element_or_analyte": "As",
                "value": raw_value,
                "unit": unit,
                "medium": "water",
                "measurement_basis": str(values["measurement_basis"]),
                "value_qualifier": str(values["value_qualifier"]),
                "detection_limit": str(values["detection_limit"]),
                "detection_limit_unit": str(values["detection_limit_unit"]),
                "latitude": str(station["LatitudeMeasure"]),
                "longitude": str(station["LongitudeMeasure"]),
                "source_crs": str(station["HorizontalCoordinateReferenceSystemDatumName"]),
                "coordinate_uncertainty_m": "15",
                "geologic_unit": "",
                "analytical_method": str(values["analytical_method"]),
                "digestion_or_extraction": str(values["digestion_or_extraction"]),
                "laboratory": str(values["laboratory"]),
                "license": candidate.license_id,
                "source_tier": "government",
                "source_id": record.source_id,
                "source_locator": record.source_locator,
                "sampled_at": sampled_at,
                "sample_depth_min_m": "",
                "sample_depth_max_m": "",
                "grain_fraction": "",
            }
        )
        entry = _base_evidence(record, result_file, candidate, record_id, "As")
        entry.update(
            {
                "article_citations": [candidate.registry_entry["citation"]],
                "article_dois": [],
                "selection_rule": (
                    "One censored result, one field replicate, one preliminary result and one accepted routine result "
                    "are required; remaining rows are deterministic evenly spaced observations across source order."
                ),
                "monitoring_location_identifier": fields["MonitoringLocationIdentifier"],
                "monitoring_location_name": station["MonitoringLocationName"],
                "provider_name": fields["ProviderName"],
                "organization_identifier": fields["OrganizationIdentifier"],
                "result_identifier": fields["ResultIdentifier"],
                "result_status": values["source_result_status"],
                "activity_type": values["activity_type"],
                "water_fraction": "dissolved",
                "detection_limit_type": values["detection_limit_type"],
                "method_source_locator": values["variable_metadata_locator"],
                "station_source_locator": station["_metadata_source_locator"],
                "horizontal_accuracy_source": (
                    f"{station['HorizontalAccuracyMeasure/MeasureValue']} "
                    f"{station['HorizontalAccuracyMeasure/MeasureUnitCode']}"
                ),
                "horizontal_collection_method": station["HorizontalCollectionMethodName"],
                "scientific_note": (
                    "A single-station dissolved-arsenic time series is useful for method and temporal validation, "
                    "but it is not evidence of national or global river coverage. Field replicates remain QC samples."
                ),
            }
        )
        evidence_rows.append(entry)
    return rows, evidence_rows, len(selected)


def pangaea_north_africa_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit % len(ANALYTES) != 0:
        raise DemoError("PANGAEA observation limit must be divisible by 4")
    sample_limit = observation_limit // len(ANALYTES)
    downloaded = files.get("Table_S5.tab")
    if downloaded is None:
        raise DemoError("PANGAEA Table S5 file is missing")
    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for record in records[:sample_limit]:
        sample_id = str(record.fields.get("Sample ID") or "").strip()
        latitude = str(record.fields.get("Latitude") or "").strip()
        longitude = str(record.fields.get("Longitude") or "").strip()
        if not sample_id or any(_reported_float(value) is None for value in (latitude, longitude)):
            raise DemoError(f"PANGAEA sample identity or coordinates are invalid: {record.source_locator}")
        for analyte in ANALYTES:
            field_name = target_fields[analyte]
            raw_value = str(record.fields.get(field_name) or "").strip()
            if _reported_float(raw_value) is None:
                raise DemoError(f"PANGAEA {analyte} value is invalid: {record.source_locator}")
            record_id = stable_record_id(
                record.source_id, record.source_record_id, analyte, raw_value, "mg/kg"
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": sample_id,
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": "mg/kg",
                    "medium": "soil",
                    "measurement_basis": "deflatable_soil_fraction_total_acid_digest",
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": str(record.fields.get("Area") or "").strip(),
                    "analytical_method": str(record.fields.get("_analytical_method") or ""),
                    "digestion_or_extraction": str(record.fields.get("_digestion_or_extraction") or ""),
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "official_curated",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": "<20 µm fine silt-clay fraction",
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [candidate.registry_entry["publication_doi"]],
                    "selection_rule": "first source samples with valid coordinates; balanced As/Cu/Ni/Zn",
                    "event": str(record.fields.get("Event") or ""),
                    "potential_source_area": str(record.fields.get("Area") or ""),
                    "reported_location": str(record.fields.get("Location") or ""),
                    "digestion_scope": "HF-HNO3 total acid digestion",
                    "scientific_note": (
                        "The source describes deflatable North African soil fractions; border locations remain publisher text and are not forced into a country field."
                    ),
                }
            )
            evidence_rows.append(entry)
            selected_source_rows.add(record.source_record_id)
    if len(rows) != observation_limit:
        raise DemoError(f"PANGAEA produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


def gsj_japan_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit % len(ANALYTES) != 0:
        raise DemoError("GSJ observation limit must be divisible by 4")
    sample_limit = observation_limit // len(ANALYTES)
    sample_file = files.get("samplejoho.csv")
    concentration_file = files.get("noudo.csv")
    if sample_file is None or concentration_file is None:
        raise DemoError("GSJ sample and concentration files are required")
    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    target_units: Mapping[str, str] = candidate.registry_entry["target_units"]
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for record in records[:sample_limit]:
        raw_id = str(record.fields.get("試料番号") or "").strip()
        occurrence = int(record.fields.get("_sample_id_occurrence") or 1)
        sample_id = raw_id if occurrence == 1 else f"{raw_id}#{occurrence}"
        latitude = str(record.fields.get("緯度(JGD2000)") or "").strip()
        longitude = str(record.fields.get("経度(JGD2000)") or "").strip()
        if not sample_id or any(_reported_float(value) is None for value in (latitude, longitude)):
            raise DemoError(f"GSJ sample identity or coordinates are invalid: {record.source_locator}")
        for analyte in ANALYTES:
            field_name = target_fields[analyte]
            raw_value = str(record.fields.get(field_name) or "").strip()
            unit = target_units[analyte]
            if _reported_float(raw_value) is None:
                raise DemoError(f"GSJ {analyte} value is invalid: {record.source_locator}")
            record_id = stable_record_id(
                record.source_id, record.source_record_id, analyte, raw_value, unit
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": sample_id,
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": "sediment",
                    "measurement_basis": "river_sediment_<180um_national_geochemical_map",
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "20",
                    "geologic_unit": str(record.fields.get("地図名") or "").strip(),
                    "analytical_method": "",
                    "digestion_or_extraction": "",
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "government",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": "<180 µm fine stream sediment",
                }
            )
            entry = _base_evidence(record, concentration_file, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [],
                    "selection_rule": "first ordinal-joined samples with valid coordinates; balanced As/Cu/Ni/Zn",
                    "sample_source_locator": record.fields["_sample_source_locator"],
                    "concentration_source_locator": record.fields["_concentration_source_locator"],
                    "sample_file_bytes": sample_file.bytes,
                    "reported_sample_id": raw_id,
                    "sample_id_occurrence": occurrence,
                    "map_sheet": str(record.fields.get("地図名") or ""),
                    "reported_place": str(record.fields.get("採取地") or ""),
                    "reported_river": str(record.fields.get("川") or ""),
                    "reported_sample_grain": str(record.fields.get("試料粒度") or ""),
                    "original_coordinate_crs": "EPSG:4612 (JGD2000)",
                    "coordinate_transform": (
                        "JGD2000 latitude/longitude carried numerically to WGS84 for regional display; "
                        "20 m uncertainty floor prevents sub-point precision claims"
                    ),
                    "scientific_note": (
                        "The CSV pair has no row-level method, detection-limit or QC fields; do not infer them from concentration values."
                    ),
                }
            )
            evidence_rows.append(entry)
            selected_source_rows.add(record.source_record_id)
    if len(rows) != observation_limit:
        raise DemoError(f"GSJ produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


def foregs_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    registered_classes = {
        (analyte, member["measurement_basis"])
        for member in candidate.registry_entry["download"]["members"]
        for analyte in member.get("target_analytes", {})
        if analyte in ANALYTES
    }
    if not registered_classes or observation_limit % len(registered_classes) != 0:
        raise DemoError(
            f"FOREGS observation limit must be divisible by {len(registered_classes)} "
            "to balance analyte and measurement basis"
        )
    per_class_limit = observation_limit // len(registered_classes)
    selected: Counter[tuple[str, str]] = Counter()
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for record in records:
        if all(selected[item] >= per_class_limit for item in registered_classes):
            break
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            raise DemoError(f"FOREGS target mapping is missing: {record.source_locator}")
        folded = {str(field).casefold(): field for field in record.fields}
        sample_field = folded.get("gtn")
        latitude_field = folded.get("lat")
        longitude_field = folded.get("long")
        if not sample_field or not latitude_field or not longitude_field:
            raise DemoError(f"FOREGS identity or coordinate fields are missing: {record.source_locator}")
        sample_id = str(record.fields.get(sample_field) or "").strip()
        latitude = str(record.fields.get(latitude_field) or "").strip()
        longitude = str(record.fields.get(longitude_field) or "").strip()
        if not sample_id or any(_reported_float(value) is None for value in (latitude, longitude)):
            continue
        downloaded = files.get(str(record.fields.get("_source_file") or ""))
        if downloaded is None:
            raise DemoError(f"FOREGS record references an unknown file: {record.source_locator}")
        country_field = folded.get("country")
        reported_country = str(record.fields.get(country_field) or "").strip() if country_field else ""
        for analyte, values in observations.items():
            if analyte not in ANALYTES or not isinstance(values, Mapping):
                continue
            measurement_basis = str(values.get("measurement_basis") or "")
            observation_class = (analyte, measurement_basis)
            if observation_class not in registered_classes or selected[observation_class] >= per_class_limit:
                continue
            raw_value = str(values.get("value") or "").strip()
            unit = str(values.get("unit") or "").strip()
            if _reported_float(raw_value) is None or not unit:
                continue
            record_id = stable_record_id(
                record.source_id, record.source_record_id, analyte, raw_value, unit
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": sample_id,
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": str(record.fields.get("_medium") or ""),
                    "measurement_basis": measurement_basis,
                    "value_qualifier": "",
                    "detection_limit": str(values.get("detection_limit") or ""),
                    "detection_limit_unit": unit,
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "",
                    "analytical_method": str(values.get("analytical_method") or ""),
                    "digestion_or_extraction": str(values.get("digestion_or_extraction") or ""),
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "official_curated",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "",
                    "sample_depth_min_m": str(record.fields.get("_sample_depth_min_m") or ""),
                    "sample_depth_max_m": str(record.fields.get("_sample_depth_max_m") or ""),
                    "grain_fraction": str(record.fields.get("_grain_fraction") or ""),
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [],
                    "selection_rule": (
                        "balanced source order by analyte and measurement basis; valid coordinates; "
                        "publisher numeric value preserved"
                    ),
                    "reported_country": reported_country,
                    "sample_type": str(record.fields.get("_sample_type") or ""),
                    "measurement_basis": measurement_basis,
                    "detection_limit": str(values.get("detection_limit") or ""),
                    "possible_upstream_dl_over_2_substitution": bool(
                        values.get("possible_upstream_dl_over_2_substitution")
                    ),
                    "scientific_note": str(record.fields.get("_censoring_boundary") or ""),
                }
            )
            evidence_rows.append(entry)
            selected_source_rows.add(record.source_record_id)
            selected[observation_class] += 1
    if len(rows) != observation_limit:
        raise DemoError(f"FOREGS produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


def afsis_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit % len(ANALYTES) != 0:
        raise DemoError("AfSIS observation limit must be divisible by 4 for balanced analytes")
    source_row_limit = observation_limit // len(ANALYTES)
    preferred_countries = (
        "Tanzania", "Ethiopia", "Kenya", "Madagascar", "Uganda", "Angola",
        "Botswana", "Nigeria", "Mali", "Guinea", "SAfrica", "Zimbambwe",
    )
    if source_row_limit != len(preferred_countries):
        raise DemoError("the checked-in AfSIS fixture requires exactly 48 observations from 12 country labels")
    selected_records: list[RawRecord] = []
    for index, country in enumerate(preferred_countries):
        preferred_depth = "Topsoil" if index % 2 == 0 else "Subsoil"
        matches = [
            record for record in records
            if str(record.fields.get("Country") or "") == country
            and str(record.fields.get("Latitude") or "").strip()
            and str(record.fields.get("Longitude") or "").strip()
            and isinstance(record.fields.get("_target_observations"), Mapping)
            and all(
                _reported_float(record.fields["_target_observations"][analyte]["value"]) is not None
                and float(record.fields["_target_observations"][analyte]["value"]) > 0
                for analyte in ANALYTES
            )
        ]
        if not matches:
            raise DemoError(f"AfSIS has no positive complete-coordinate demo row for {country}")
        selected_records.append(
            next((item for item in matches if item.fields.get("Depth") == preferred_depth), matches[0])
        )

    measurement = files.get(candidate.registry_entry["download"]["files"][0]["filename"])
    if measurement is None:
        raise DemoError("AfSIS measurement file evidence is missing")
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    for record in selected_records:
        observations = record.fields["_target_observations"]
        for analyte in ANALYTES:
            values = observations[analyte]
            raw_value = str(values["value"])
            unit = str(values["unit"])
            record_id = stable_record_id(
                record.source_id, record.source_record_id, analyte, raw_value, unit
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": str(record.fields.get("SSN") or ""),
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": "soil",
                    "measurement_basis": str(values["measurement_basis"]),
                    "value_qualifier": "",
                    "detection_limit": str(values["detection_limit"]),
                    "detection_limit_unit": unit,
                    "latitude": str(record.fields.get("Latitude") or ""),
                    "longitude": str(record.fields.get("Longitude") or ""),
                    "source_crs": str(record.fields.get("_source_crs") or ""),
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "",
                    "analytical_method": str(values["analytical_method"]),
                    "digestion_or_extraction": str(values["digestion_or_extraction"]),
                    "laboratory": str(values["laboratory"]),
                    "license": candidate.license_id,
                    "source_tier": "official_curated",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "2009/2013",
                    "sample_depth_min_m": str(record.fields.get("_sample_depth_min_m") or ""),
                    "sample_depth_max_m": str(record.fields.get("_sample_depth_max_m") or ""),
                    "grain_fraction": str(record.fields.get("_grain_fraction") or ""),
                }
            )
            entry = _base_evidence(record, measurement, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": ["10.5194/soil-7-305-2021"],
                    "selection_rule": (
                        "one positive complete-coordinate source row from each of 12 fixed country labels; "
                        "alternating preferred topsoil and subsoil depth; As/Cu/Ni/Zn preserved"
                    ),
                    "reported_country": str(record.fields.get("Country") or ""),
                    "normalized_country": str(record.fields.get("_country_normalized") or ""),
                    "site": str(record.fields.get("Site") or ""),
                    "reported_depth": str(record.fields.get("Depth") or ""),
                    "measurement_basis": str(values["measurement_basis"]),
                    "detection_limit": str(values["detection_limit"]),
                    "quantitation_limit": str(values["quantitation_limit"]),
                    "below_detection_limit": bool(values["below_detection_limit"]),
                    "below_quantitation_limit": bool(values["below_quantitation_limit"]),
                    "negative_numeric_result": False,
                    "variable_metadata_locator": str(values["variable_metadata_locator"]),
                    "threshold_metadata_locator": str(values["threshold_metadata_locator"]),
                    "source_variable_description": str(values["source_variable_description"]),
                    "metadata_conflicts": list(record.fields.get("_metadata_conflicts") or []),
                    "source_crs_status": "not_reported_in_registered_files_or_related_article",
                    "grain_fraction_source_scope": "related_article_dataset_level",
                    "scientific_note": str(record.fields.get("_quality_boundary") or ""),
                }
            )
            evidence_rows.append(entry)
    if len(rows) != observation_limit:
        raise DemoError(f"AfSIS produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_records)


def ngsa_mercury_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    if observation_limit != 48:
        raise DemoError("the frozen NGSA fixture requires exactly 48 observations")
    downloaded = files.get("150328_00_1.CSV")
    if downloaded is None:
        raise DemoError("NGSA mercury CSV is missing")
    strata = (("TOS", ""), ("BOS", ""), ("TOS", "Duplicate 1"), ("BOS", "Duplicate 2"))
    selected: list[RawRecord] = []
    selected_ids: set[str] = set()
    states = ("NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")
    for depth, duplicate_code in strata:
        for state in states:
            match = next(
                (
                    record for record in records
                    if record.source_record_id not in selected_ids
                    and record.fields.get("DEPTH") == depth
                    and record.fields.get("STATE") == state
                    and (
                        record.fields.get("DUPLICATE_CODE") == duplicate_code
                        if duplicate_code
                        else not record.fields.get("DUPLICATE_CODE")
                    )
                ),
                None,
            )
            if match is not None:
                selected.append(match)
                selected_ids.add(match.source_record_id)
    for record in records:
        if len(selected) >= observation_limit:
            break
        if record.source_record_id not in selected_ids:
            selected.append(record)
            selected_ids.add(record.source_record_id)
    if len(selected) != observation_limit:
        raise DemoError(f"NGSA selected {len(selected)} rows, expected {observation_limit}")
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    for record in selected:
        values = record.fields["_target_observations"]["Hg"]
        raw_value = str(values["value"])
        record_id = stable_record_id(
            record.source_id, record.source_record_id, "Hg", raw_value, "ng/g"
        )
        rows.append(
            {
                "record_id": record_id,
                "source_record_id": record.source_record_id,
                "sample_id": str(record.fields.get("SAMPLEID") or ""),
                "element_or_analyte": "Hg",
                "value": raw_value,
                "unit": "ng/g",
                "medium": "sediment",
                "measurement_basis": str(values["measurement_basis"]),
                "value_qualifier": "",
                "detection_limit": "",
                "detection_limit_unit": "",
                "latitude": str(record.fields.get("LATITUDE_GDA94") or ""),
                "longitude": str(record.fields.get("LONGITUDE_GDA94") or ""),
                "source_crs": "EPSG:4326",
                "coordinate_uncertainty_m": "5",
                "geologic_unit": "",
                "analytical_method": str(values["analytical_method"]),
                "digestion_or_extraction": str(values["digestion_or_extraction"]),
                "laboratory": str(values["laboratory"]),
                "license": candidate.license_id,
                "source_tier": "government",
                "source_id": record.source_id,
                "source_locator": record.source_locator,
                "sampled_at": "",
                "sample_depth_min_m": "",
                "sample_depth_max_m": "",
                "grain_fraction": "<75 µm",
            }
        )
        entry = _base_evidence(record, downloaded, candidate, record_id, "Hg")
        entry.update(
            {
                "article_citations": [candidate.registry_entry["citation"]],
                "article_dois": [candidate.registry_entry["publication_doi"]],
                "selection_rule": "48 deterministic rows spanning TOS/BOS, seven states and reported duplicate classes",
                "reported_depth": str(record.fields.get("DEPTH") or ""),
                "state": str(record.fields.get("STATE") or ""),
                "site_id": str(record.fields.get("SITEID") or ""),
                "duplicate_code": str(record.fields.get("DUPLICATE_CODE") or ""),
                "duplicate_site_id": str(record.fields.get("DUPLICATE_SITEID") or ""),
                "sample_date_raw": str(record.fields.get("DATE_SAMPLED") or ""),
                "original_coordinate_crs": "EPSG:4283 (GDA94)",
                "coordinate_transform": "GDA94 geographic values carried numerically for WGS84 regional display with a 5 m uncertainty floor",
                "mass_detection_limit_ng": "0.01",
                "concentration_detection_limit": None,
                "scientific_note": "The 0.01 ng Hg mass LOD is not treated as a 0.01 ng/g concentration threshold.",
            }
        )
        evidence_rows.append(entry)
    return rows, evidence_rows, len(selected)


def gsj_marine_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    analytes = ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")
    if observation_limit % len(analytes) != 0:
        raise DemoError("GSJ marine observation limit must be divisible by seven")
    per_analyte = observation_limit // len(analytes)
    downloaded = files.get("ocean-noudo.csv")
    if downloaded is None:
        raise DemoError("GSJ marine concentration CSV is missing")
    selected_counts: Counter[str] = Counter()
    selected_source_rows: set[str] = set()
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    for record in records:
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            continue
        for analyte in analytes:
            if selected_counts[analyte] >= per_analyte:
                continue
            values = observations.get(analyte)
            if not isinstance(values, Mapping):
                continue
            raw_value = str(values.get("value") or "")
            numeric = _reported_float(raw_value)
            if numeric is None or numeric <= 0:
                continue
            unit = str(values["unit"])
            record_id = stable_record_id(
                record.source_id, record.source_record_id, analyte, raw_value, unit
            )
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": str(record.fields.get("試料番号") or ""),
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": "sediment",
                    "measurement_basis": str(values["measurement_basis"]),
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": str(record.fields.get("緯度") or ""),
                    "longitude": str(record.fields.get("経度") or ""),
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "20",
                    "geologic_unit": "",
                    "analytical_method": "",
                    "digestion_or_extraction": "",
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "government",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": "",
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [candidate.registry_entry["publication_doi"]],
                    "selection_rule": "first positive records per analyte; eight each for As/Cr/Cu/Hg/Ni/Pb/Zn",
                    "cruise": str(record.fields.get("航海") or ""),
                    "region": str(record.fields.get("地域") or ""),
                    "water_depth_m": str(record.fields.get("深度_m_") or ""),
                    "original_coordinate_crs": "GSJ project geographic coordinates; regional display uses a 20 m uncertainty floor",
                    "method_missing_reason": "not_reported_in_concentration_csv",
                    "scientific_note": "Negative Hg remains in the full adapter population but is excluded from the positive map-demo slice.",
                }
            )
            evidence_rows.append(entry)
            selected_counts[analyte] += 1
            selected_source_rows.add(record.source_record_id)
        if all(selected_counts[analyte] >= per_analyte for analyte in analytes):
            break
    if len(rows) != observation_limit:
        raise DemoError(f"GSJ marine produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


def pangaea_arabian_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    analytes = ("As", "Cr", "Cu", "Ni", "Pb", "Zn")
    if observation_limit % len(analytes) != 0:
        raise DemoError("PANGAEA Arabian Sea observation limit must be divisible by six")
    source_row_limit = observation_limit // len(analytes)
    downloaded = files.get("PANGAEA.950139.tab")
    if downloaded is None:
        raise DemoError("PANGAEA Arabian Sea table is missing")
    selected = records[:source_row_limit]
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    for record in selected:
        observations = record.fields["_target_observations"]
        for analyte in analytes:
            values = observations[analyte]
            raw_value = str(values["value"])
            record_id = stable_record_id(
                record.source_id, record.source_record_id, analyte, raw_value, "mg/kg"
            )
            depth = str(record.fields.get("Depth sed [m]") or "")
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": record.source_record_id,
                    "sample_id": str(record.fields.get("Sample label") or ""),
                    "element_or_analyte": analyte,
                    "value": raw_value,
                    "unit": "mg/kg",
                    "medium": "sediment",
                    "measurement_basis": str(values["measurement_basis"]),
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": str(record.fields.get("Latitude") or ""),
                    "longitude": str(record.fields.get("Longitude") or ""),
                    "source_crs": "EPSG:4326",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "",
                    "analytical_method": str(values["analytical_method"]),
                    "digestion_or_extraction": str(values["digestion_or_extraction"]),
                    "laboratory": "",
                    "license": candidate.license_id,
                    "source_tier": "peer_reviewed",
                    "source_id": record.source_id,
                    "source_locator": record.source_locator,
                    "sampled_at": "",
                    "sample_depth_min_m": depth,
                    "sample_depth_max_m": depth,
                    "grain_fraction": "bulk sediment",
                }
            )
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update(
                {
                    "article_citations": [candidate.registry_entry["citation"]],
                    "article_dois": [candidate.dataset_doi],
                    "selection_rule": "first eight source rows; balanced As/Cr/Cu/Ni/Pb/Zn",
                    "event": str(record.fields.get("Event") or ""),
                    "location": str(record.fields.get("Location") or "Arabian Sea"),
                    "water_depth_m": str(record.fields.get("Elevation [m]") or ""),
                    "sediment_depth_m": depth,
                    "method_source_locator": str(values["variable_metadata_locator"]),
                    "scientific_note": "The publisher method phrase is generic; no instrument or digestion is inferred.",
                }
            )
            evidence_rows.append(entry)
    if len(rows) != observation_limit:
        raise DemoError(f"PANGAEA Arabian Sea produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected)


def v4_m6_demo(
    records: Sequence[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int]:
    """Build deterministic balanced slices for the three V4 M6 adapters."""

    source_id = candidate.source_id
    analytes = (
        ("As", "Cr", "Cu", "Ni", "Pb", "Zn")
        if source_id == "georoc-antarctica-intraplate"
        else ("Cr", "Cu", "Ni", "Pb", "Zn")
        if source_id == "tpdc-china-mountain-soil"
        else ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")
    )
    keys = (
        tuple(f"{group}|{analyte}" for group in ("AR", "XRF") for analyte in analytes if not (group == "XRF" and analyte == "Hg"))
        if source_id == "gemas-europe"
        else analytes
    )
    if observation_limit % len(keys) != 0:
        raise DemoError(f"{source_id} observation limit must be divisible by {len(keys)}")
    per_key = observation_limit // len(keys)
    selected = Counter()
    selected_source_rows: set[str] = set()
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    for record in records:
        if all(selected[key] >= per_key for key in keys):
            break
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            continue
        if source_id == "georoc-antarctica-intraplate":
            latitude = _exact_georoc_coordinate(record, "LATITUDE MIN", "LATITUDE MAX")
            longitude = _exact_georoc_coordinate(record, "LONGITUDE MIN", "LONGITUDE MAX")
            sample_id = str(record.fields.get("SAMPLE NAME") or record.fields.get("UNIQUE_ID") or "").strip()
            medium = "rock"; sample_depth_min = sample_depth_max = ""; grain = ""
        elif source_id == "tpdc-china-mountain-soil":
            latitude = str(record.fields.get("Latitude") or ""); longitude = str(record.fields.get("Longitude") or "")
            sample_id = f"{record.fields.get('Sam.No','')}|{record.fields.get('Horizons','')}"
            medium = "soil"; sample_depth_min = sample_depth_max = ""; grain = str(record.fields.get("_grain_fraction") or "")
        else:
            latitude = str(record.fields.get("YCOO") or ""); longitude = str(record.fields.get("XCOO") or "")
            sample_id = str(record.fields.get("_physical_sample_id") or "")
            medium = "soil"
            sample_depth_min, sample_depth_max = (("0", "0.20") if record.fields.get("TYPE_") == "Ap" else ("0", "0.10"))
            grain = str(record.fields.get("_grain_fraction") or "")
        if not sample_id or not latitude or not longitude:
            continue
        downloaded = files.get(str(record.fields.get("_source_file")))
        if downloaded is None:
            raise DemoError(f"{source_id} record references an unknown source file")
        group = str(record.fields.get("_analysis_group") or "")
        for analyte in analytes:
            values = observations.get(analyte)
            if not isinstance(values, Mapping):
                continue
            key = f"{group}|{analyte}" if source_id == "gemas-europe" else analyte
            if selected[key] >= per_key:
                continue
            raw_value = str(values.get("value") or "")
            if _reported_float(raw_value) is None:
                continue
            unit = str(values.get("unit") or "")
            record_id = stable_record_id(record.source_id, record.source_record_id, analyte, raw_value, unit)
            rows.append({
                "record_id": record_id, "source_record_id": record.source_record_id,
                "sample_id": sample_id, "element_or_analyte": analyte,
                "value": raw_value, "unit": unit, "medium": medium,
                "measurement_basis": str(values.get("measurement_basis") or ""),
                "value_qualifier": "", "detection_limit": str(values.get("detection_limit") or ""),
                "detection_limit_unit": unit if values.get("detection_limit") else "",
                "latitude": latitude, "longitude": longitude,
                "source_crs": str(record.fields.get("_source_crs") or ("EPSG:4326" if source_id != "tpdc-china-mountain-soil" else "")),
                "coordinate_uncertainty_m": "", "geologic_unit": str(record.fields.get("LOCATION") or "") if medium == "rock" else "",
                "analytical_method": str(values.get("analytical_method") or ""),
                "digestion_or_extraction": str(values.get("digestion_or_extraction") or ""),
                "laboratory": "", "license": candidate.license_id, "source_tier": "official_curated",
                "source_id": record.source_id, "source_locator": record.source_locator,
                "sampled_at": "", "sample_depth_min_m": sample_depth_min,
                "sample_depth_max_m": sample_depth_max, "grain_fraction": grain,
                "lithology_raw": str(record.fields.get("ROCK NAME") or record.fields.get("Rock Group") or ""),
                "geologic_age_raw": str(record.fields.get("AGE") or ""),
                "tectonic_setting_raw": str(record.fields.get("TECTONIC SETTING") or ""),
            })
            entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
            entry.update({
                "article_citations": [candidate.registry_entry["citation"]],
                "article_dois": [candidate.registry_entry.get("publication_doi") or candidate.dataset_doi] if (candidate.registry_entry.get("publication_doi") or candidate.dataset_doi) else [],
                "selection_rule": f"balanced deterministic M6 slice by {key}",
                "reported_horizon": str(record.fields.get("Horizons") or ""),
                "mountain": str(record.fields.get("Mountain") or ""),
                "site": str(record.fields.get("site") or ""),
                "sample_type": str(record.fields.get("TYPE_") or ""),
                "country_raw": str(record.fields.get("COUNTRY") or ""),
                "analysis_group": group,
                "method_source_locator": str(values.get("variable_metadata_locator") or record.source_locator),
                "below_laboratory_dl": bool(values.get("below_laboratory_dl")),
                "upstream_half_dl_substitution": bool(values.get("upstream_half_dl_substitution")),
            })
            evidence_rows.append(entry)
            selected[key] += 1
            selected_source_rows.add(record.source_record_id)
    if len(rows) != observation_limit:
        raise DemoError(f"{source_id} produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence_rows, len(selected_source_rows)


@contextmanager
def acquired_source(args: argparse.Namespace) -> Iterator[tuple[Any, list[DownloadedFile]]]:
    adapter = get_adapter(args.source)
    candidate = adapter.discover({"sources": [args.source]})[0]
    if args.archive:
        if args.source != "norway-marchem":
            raise DemoError("--archive is currently supported only for norway-marchem")
        with tempfile.TemporaryDirectory(prefix="marchem-fixture-") as temporary:
            files = adapter.files_from_archive(args.archive, Path(temporary) / "members")
            yield candidate, files
    else:
        yield candidate, adapter.download(candidate, args.cache_dir, mode=args.mode)


def _csv_text(rows: Sequence[Mapping[str, str]]) -> str:
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INPUT_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.seek(0)
        return handle.read()


def _jsonl_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)


def generate(args: argparse.Namespace) -> dict[str, Any]:
    output_paths = {
        "demo_input": args.output_dir / "demo_input.csv",
        "sources": args.output_dir / "sources.jsonl",
        "run_manifest": args.output_dir / "run_manifest.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        raise DemoError(f"output files already exist; use --overwrite after review: {existing}")

    with acquired_source(args) as (candidate, downloaded):
        adapter = get_adapter(args.source)
        raw_records: Sequence[RawRecord] | Iterable[RawRecord]
        raw_records = adapter.parse(downloaded) if args.source == "gemstat-open-archive" else list(adapter.parse(downloaded))
        files = {item.path.name: item for item in downloaded}
        if args.source == "georoc-archaean":
            references = {item.path.name: _georoc_reference_map(item.path) for item in downloaded}
            rows, evidence, selected_source_rows = georoc_demo(
                raw_records, files, references, candidate, args.observations
            )
        elif args.source == "usgs-conus-soil":
            rows, evidence, selected_source_rows = usgs_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "norway-marchem":
            rows, evidence, selected_source_rows = marchem_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "geotraces-idp2025":
            rows, evidence, selected_source_rows = geotraces_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "gemstat-open-archive":
            rows, evidence, selected_source_rows = gemstat_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "us-wqp-sacramento-river-arsenic":
            rows, evidence, selected_source_rows = wqp_sacramento_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "pangaea-north-africa-soil":
            rows, evidence, selected_source_rows = pangaea_north_africa_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "japan-gsj-geochemical-map":
            rows, evidence, selected_source_rows = gsj_japan_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source.startswith("foregs-"):
            rows, evidence, selected_source_rows = foregs_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "afsis-phase-i-wet-chemistry":
            rows, evidence, selected_source_rows = afsis_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "australia-ngsa-mercury":
            rows, evidence, selected_source_rows = ngsa_mercury_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "japan-gsj-marine-sediment":
            rows, evidence, selected_source_rows = gsj_marine_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source == "pangaea-arabian-sea-sediment":
            rows, evidence, selected_source_rows = pangaea_arabian_demo(
                raw_records, files, candidate, args.observations
            )
        elif args.source in {"georoc-antarctica-intraplate", "tpdc-china-mountain-soil", "gemas-europe"}:
            rows, evidence, selected_source_rows = v4_m6_demo(
                raw_records, files, candidate, args.observations
            )
        else:
            raise DemoError(f"unsupported source: {args.source}")

    registry = load_source_registry()
    rows = [
        v4_semantics.enrich_row(
            row,
            evidence_row,
            candidate.registry_entry,
            str(registry.get("verified_at") or ""),
        )
        for row, evidence_row in zip(rows, evidence, strict=True)
    ]

    atomic_text(output_paths["demo_input"], _csv_text(rows))
    atomic_text(output_paths["sources"], _jsonl_text(evidence))
    outputs = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
        }
        for key, path in output_paths.items()
        if key != "run_manifest"
    ]
    manifest = {
        "demo_generation_version": DEMO_VERSION,
        "exchange_schema": "d1-v4-exchange-v1",
        "v4_semantics_version": v4_semantics.SEMANTICS_VERSION,
        "data_mode": "fixture",
        "scientific_scope": "pipeline demonstration only",
        "not_for_scientific_interpretation": True,
        "generated_at": args.generated_at,
        "source": {
            "source_id": candidate.source_id,
            "title": candidate.title,
            "dataset_doi": candidate.dataset_doi,
            "dataset_version": candidate.version,
            "license": candidate.license_id,
        },
        "generation_request": {
            "observations": args.observations,
            "analytes": list(
                ("Cu", "Ni", "Zn") if args.source == "geotraces-idp2025"
                else ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn") if args.source == "gemstat-open-archive"
                else ("As",) if args.source == "us-wqp-sacramento-river-arsenic"
                else ("Hg",) if args.source == "australia-ngsa-mercury"
                else ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn") if args.source == "japan-gsj-marine-sediment"
                else ("As", "Cr", "Cu", "Ni", "Pb", "Zn") if args.source == "pangaea-arabian-sea-sediment"
                else ("As", "Cr", "Cu", "Ni", "Pb", "Zn") if args.source == "georoc-antarctica-intraplate"
                else ("Cr", "Cu", "Ni", "Pb", "Zn") if args.source == "tpdc-china-mountain-soil"
                else ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn") if args.source == "gemas-europe"
                else sorted({row["element_or_analyte"] for row in rows})
                if args.source.startswith("foregs-")
                else ANALYTES
            ),
            "mode": args.mode,
        },
        "source_files": [
            {
                "filename": item.path.name,
                "source_url": item.source_url,
                "bytes": item.bytes,
                "retrieved_at": item.retrieved_at,
            }
            for item in downloaded
        ],
        "record_counts": {
            "raw_source_rows": (
                candidate.registry_entry["expected_counts"]["target_observations"]
                if args.source == "gemstat-open-archive"
                else len(raw_records)
            ),
            "selected_source_rows": selected_source_rows,
            "emitted_observations": len(rows),
        },
        "outputs": outputs,
        "warnings": [
            "This is a deterministic demonstration slice, not a statistically representative sample.",
            "Scientific normalization, QC, confidence and anomaly decisions are owned by D2.",
            "V4 sample, method, geography, citation and use-condition fields come only from source evidence or registered constants.",
            *(
                [
                    "FOREGS is a low-density European continental baseline, not continuous or local coverage.",
                    "Total, aqua-regia-leachable, mild-acid-leachable and dissolved measurements remain separate comparison bases.",
                    "The publisher CSV lacks row-level less-than qualifiers; exact half-DL values are flagged only as possible upstream DL/2 substitutions.",
                    "Official coordinates were transformed from national systems for continental-scale presentation; source precision is not local survey accuracy.",
                ]
                if args.source.startswith("foregs-")
                else []
            ),
            *(
                [
                    "MarChem values are dry-weight partial nitric-acid extractions, not total concentrations.",
                    "Accreditation status varies by batch and remains attached to observation evidence.",
                ]
                if args.source == "norway-marchem"
                else []
            ),
            *(
                [
                    "GEMStat v3 seven-element observations come from voluntary contributors and do not form a uniform global freshwater grid.",
                    "Dissolved, extractable, suspended and total operational fractions remain separate; this demo uses only rows with a defined method and Good/Fair source quality.",
                    "Cr-VI is a chemical species rather than interchangeable elemental chromium and is excluded from the Cr target count.",
                    "Censored observations retain their source limits; Pending review, Suspect, negative sentinel and extreme mg/l rows are excluded.",
                ]
                if args.source == "gemstat-open-archive"
                else []
            ),
            *(
                [
                    "This is one USGS river station, not national or global freshwater coverage.",
                    "The retained response contains dissolved arsenic only; unreturned elements from the exact repeated-parameter query are not claimed.",
                    "Preliminary results and field-replicate QC samples remain explicitly labeled and must not be treated as accepted independent routine observations.",
                    "The Not Detected result remains left-censored at its reported 0.10 ug/l limit; no zero is invented.",
                ]
                if args.source == "us-wqp-sacramento-river-arsenic"
                else []
            ),
            *(
                [
                    "The fixture covers 3,024 fine river-sediment samples, not a regular grid or the separate marine/surface-soil products.",
                    "Original coordinates are JGD2000; the display fixture carries values to WGS84 with a conservative 20 m uncertainty floor.",
                    "Hg is ppb while the other registered trace elements are ppm; the CSV pair has no row-level method, detection-limit or QC fields.",
                    "Duplicate sample ID 78013 is preserved by occurrence-order joining and is never overwritten.",
                ]
                if args.source == "japan-gsj-geochemical-map"
                else []
            ),
            *(
                [
                    "This DOI contains 43 discrete North African samples, not continuous regional coverage.",
                    "Values are HF-HNO3-digested deflatable soil fractions and must remain separate from differently prepared bulk-soil surveys.",
                    "Publisher location text is preserved; border samples are not assigned to a country by coordinate inference.",
                ]
                if args.source == "pangaea-north-africa-soil"
                else []
            ),
            *(
                [
                    "AfSIS Phase I contains 2,002 archived samples from 51 LDSF sites and is not a uniform African grid.",
                    "Aqua-regia values are quasi-total and remain separate from total and other soil extraction bases.",
                    "Published negative instrument results and positive values below source-wide DL or QL remain explicit quality flags; this positive demo excludes negative rows.",
                    "One hundred twenty-six source samples have no coordinates; the demo selects only complete-coordinate rows and does not infer missing positions.",
                    "The source does not state a coordinate reference system; latitude/longitude are preserved while source_crs remains blank.",
                    "The variable workbook description conflicts with field As.75 by saying Arsenic-78, and its 2009-2013 sampling period differs from the related paper's 2009-2012; both conflicts stay in evidence.",
                    "Publisher country labels are retained verbatim, with SAfrica and Zimbambwe normalized only in separate evidence fields.",
                ]
                if args.source == "afsis-phase-i-wet-chemistry"
                else []
            ),
            *(
                [
                    "GEOTRACES IDP2025 seawater has no arsenic variable; a separate water source is required for As.",
                    "Values remain in nmol/kg because mass-per-volume conversion requires explicit atomic-mass and seawater-density assumptions.",
                    "Only SeaDataNet QC 1 and 2 values are included in this demo; all source flags remain available in the raw adapter.",
                ]
                if args.source == "geotraces-idp2025"
                else []
            ),
            *(
                [
                    "NGSA provides total Hg only; it does not supply the other target elements.",
                    "TOS and BOS remain separate sample types, and QA/QC duplicates are not independent sites.",
                    "The reported 0.01 ng Hg mass LOD is not treated as a concentration detection limit.",
                ]
                if args.source == "australia-ngsa-mercury"
                else []
            ),
            *(
                [
                    "GSJ marine sediment is a separate product from the national river-sediment table.",
                    "Hg is ppb while the other target elements are ppm; method, detection-limit and QC fields are absent from the concentration CSV.",
                    "Negative Hg source values remain in the full population but are excluded from this positive demo slice.",
                ]
                if args.source == "japan-gsj-marine-sediment"
                else []
            ),
            *(
                [
                    "The PANGAEA DOI contains 27 rows from 26 Arabian Sea events, not continuous regional coverage.",
                    "The publisher method phrase is generic; no instrument or digestion is inferred.",
                    "A repeated sample label is preserved by source-row identity rather than overwritten.",
                ]
                if args.source == "pangaea-arabian-sea-sediment"
                else []
            ),
            *(
                [
                    "This GEOROC member is a literature compilation and is not uniform Antarctica coverage.",
                    "Only exact coordinate pairs enter the point fixture; coordinate ranges remain areas.",
                    "The selected row-level analytical method is absent from the precompiled member and is not inferred.",
                ]
                if args.source == "georoc-antarctica-intraplate" else []
            ),
            *(
                [
                    "TPDC samples cover 30 mountain ecosystems rather than a uniform China soil grid.",
                    "O, A and C horizons remain separate; the undeclared coordinate CRS remains blank.",
                    "Dataset-level ICP-MS/ICP-AES assignments come from the linked article, not row-level workbook fields.",
                ]
                if args.source == "tpdc-china-mountain-soil" else []
            ),
            *(
                [
                    "GEMAS is a low-density European soil survey, not continuous coverage.",
                    "Aqua-regia and XRF measurements remain in separate comparison partitions.",
                    "XRF half-DL substitutions are flagged and never presented as recovered exact detections.",
                ]
                if args.source == "gemas-europe" else []
            ),
        ],
        "failures": [],
    }
    atomic_json(output_paths["run_manifest"], manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        required=True,
        choices=(
            "georoc-archaean", "usgs-conus-soil", "norway-marchem",
            "geotraces-idp2025", "gemstat-open-archive", "pangaea-north-africa-soil",
            "japan-gsj-geochemical-map",
            "foregs-topsoil", "foregs-subsoil", "foregs-humus",
            "foregs-stream-water", "foregs-stream-sediment", "foregs-floodplain-sediment",
            "afsis-phase-i-wet-chemistry",
            "us-wqp-sacramento-river-arsenic",
            "australia-ngsa-mercury",
            "japan-gsj-marine-sediment",
            "pangaea-arabian-sea-sediment",
            "georoc-antarctica-intraplate",
            "tpdc-china-mountain-soil",
            "gemas-europe",
        ),
    )
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument(
        "--archive",
        type=Path,
        help="Explicit local copy of the registered identity-and-statistics MarChem snapshot",
    )
    parser.add_argument("--observations", type=int, default=48)
    parser.add_argument(
        "--generated-at",
        required=True,
        help="Explicit ISO-8601 time retained in the reproducible manifest",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.observations < 12 or args.observations > 1000:
        print("generate_demo_data: --observations must be between 12 and 1000", file=sys.stderr)
        return 2
    try:
        manifest = generate(args)
    except (DemoError, SourceAdapterError, OSError, ValueError) as exc:
        print(f"generate_demo_data: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
