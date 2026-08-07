#!/usr/bin/env python3
"""Minimal, auditable adapters from four frozen real sources to the D2 input contract."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from lab_common import (
    CONTRACT_ROOT,
    LAB_ROOT,
    atomic_write_json,
    load_json,
    prepare_empty_output_dir,
    sha256_file,
)

SOURCE_CONTRACT = CONTRACT_ROOT / "real-sources.json"
DEFAULT_FIXTURE_DIR = LAB_ROOT / "real-data" / "fixtures" / "raw"
ADAPTER_VERSION = "d1-real-adapter-v2"

OUTPUT_FIELDS = (
    "record_id",
    "source_record_id",
    "sample_id",
    "sample_identity_group",
    "element_or_analyte",
    "analyte_reported",
    "value",
    "unit",
    "value_qualifier",
    "source_qualifier_raw",
    "missing_reason",
    "medium",
    "material",
    "measurement_basis",
    "latitude",
    "longitude",
    "source_crs",
    "coordinate_transform_method",
    "coordinate_uncertainty_m",
    "coordinate_uncertainty_status",
    "coordinate_uncertainty_basis",
    "coordinate_resolution_m",
    "coordinate_resolution_basis",
    "measurement_uncertainty",
    "measurement_uncertainty_unit",
    "measurement_uncertainty_basis",
    "sampled_at",
    "sample_depth_min_m",
    "sample_depth_max_m",
    "grain_fraction",
    "lithology",
    "geologic_unit",
    "geologic_unit_id",
    "geologic_context_source",
    "geologic_context_version",
    "geologic_match_method",
    "distance_to_geologic_boundary_m",
    "geologic_match_confidence",
    "geologic_context_status",
    "analytical_method",
    "analytical_method_status",
    "method_family",
    "digestion_or_extraction",
    "laboratory",
    "detection_limit",
    "detection_limit_unit",
    "source_id",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_file",
    "source_row",
    "source_locator",
    "file_sha256",
    "license",
    "source_tier",
)

DS801_METHODS = {
    "As": {
        "method": "Hydride-generation atomic absorption spectrometry (HG-AAS)",
        "family": "hg_aas",
        "digestion": "sodium peroxide and sodium hydroxide fusion",
        "basis": "total_after_fusion",
    },
    "Cd": {
        "method": "Inductively coupled plasma-mass spectrometry (ICP-MS)",
        "family": "icp_ms",
        "digestion": "near-total HCl-HNO3-HClO4-HF digestion",
        "basis": "near_total_four_acid",
    },
    "Cu": {
        "method": "Inductively coupled plasma-atomic emission spectrometry (ICP-AES)",
        "family": "icp_aes",
        "digestion": "near-total HCl-HNO3-HClO4-HF digestion",
        "basis": "near_total_four_acid",
    },
    "Fe": {
        "method": "Inductively coupled plasma-atomic emission spectrometry (ICP-AES)",
        "family": "icp_aes",
        "digestion": "near-total HCl-HNO3-HClO4-HF digestion",
        "basis": "near_total_four_acid",
    },
    "Hg": {
        "method": "Cold-vapor atomic absorption spectrometry (CVAAS)",
        "family": "cv_aas",
        "digestion": "HNO3-HCl digestion",
        "basis": "acid_digest",
    },
    "Pb": {
        "method": "Inductively coupled plasma-mass spectrometry (ICP-MS)",
        "family": "icp_ms",
        "digestion": "near-total HCl-HNO3-HClO4-HF digestion",
        "basis": "near_total_four_acid",
    },
    "Zn": {
        "method": "Inductively coupled plasma-atomic emission spectrometry (ICP-AES)",
        "family": "icp_aes",
        "digestion": "near-total HCl-HNO3-HClO4-HF digestion",
        "basis": "near_total_four_acid",
    },
}

RASS_ELEMENTS = ("As", "Cu", "Pb", "Zn")

TAYLOR_ROCK_ELEMENTS = {
    "Fe": ("Fe_ICP55\n%", "wt%"),
    "Cr": ("Cr_ICP55\nppm", "ppm"),
    "Cu": ("Cu_ICP55\nppm", "ppm"),
    "Ni": ("Ni_ICP55\nppm", "ppm"),
    "Pb": ("Pb_ICP55\nppm", "ppm"),
    "Zn": ("Zn_ICP55\nppm", "ppm"),
}


class AdapterError(ValueError):
    """Raised when a frozen fixture cannot be mapped without guessing."""


def dataset_by_id(contract: Mapping[str, Any], dataset_id: str) -> dict[str, Any]:
    for dataset in contract.get("datasets", []):
        if dataset.get("id") == dataset_id:
            return dict(dataset)
    raise AdapterError(f"dataset missing from source contract: {dataset_id}")


def resource_by_id(contract: Mapping[str, Any], resource_id: str) -> dict[str, Any]:
    for resource in contract.get("resources", []):
        if resource.get("id") == resource_id:
            return dict(resource)
    raise AdapterError(f"resource missing from source contract: {resource_id}")


def verified_path(fixture_dir: Path, resource: Mapping[str, Any]) -> Path:
    path = fixture_dir / str(resource["local_file"])
    if not path.is_file():
        raise AdapterError(
            f"frozen fixture is missing; run fetch_real_fixtures.py first: {path}"
        )
    actual = sha256_file(path)
    if actual != resource["sha256"]:
        raise AdapterError(f"frozen fixture hash mismatch for {path.name}: {actual}")
    return path


def iso_us_date(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%m/%d/%y").date().isoformat()
    except ValueError:
        return ""


def iso_legacy_yymmdd(value: str) -> str:
    text = value.strip()
    if len(text) != 6 or not text.isdigit():
        return ""
    try:
        # RASS metadata bounds the source to 1966-1988, avoiding ambiguous pivot-year parsing.
        return datetime.strptime(f"19{text}", "%Y%m%d").date().isoformat()
    except ValueError:
        return ""


def ds801_measurement(raw: str) -> tuple[str, str, str, str]:
    value = raw.strip()
    folded = value.casefold()
    if value.startswith(("<", ">")):
        return value, value[0], value[0], ""
    if folded in {"n.d.", "nd"}:
        return "", "nd", value, ""
    if folded == "ins":
        return "", "", value, "insufficient_sample"
    if folded in {"n.s.", "ns"}:
        return "", "", value, "not_analyzed"
    if not value:
        return "", "", "", "not_reported"
    return value, "", "", ""


def rass_measurement(raw_value: str, raw_qualifier: str) -> tuple[str, str, str, str]:
    value = raw_value.strip()
    qualifier = raw_qualifier.strip().upper()
    if qualifier == "N":
        return "", "nd", value, ""
    if qualifier == "L":
        return value, "trace", value, ""
    if qualifier == "G":
        return value, "gt", "", ""
    if qualifier == "H":
        return "", "", "", "invalid_value"
    if qualifier == "B":
        return "", "", "", "not_analyzed"
    if qualifier:
        return value, qualifier, "", ""
    if not value:
        return "", "", "", "not_reported"
    return value, "", "", ""


def wqp_measurement(row: Mapping[str, str]) -> tuple[str, str, str, str, str]:
    value = (row.get("ResultMeasureValue") or "").strip()
    detection_condition = (row.get("ResultDetectionConditionText") or "").strip()
    measure_qualifier = (row.get("MeasureQualifierCode") or "").strip()
    raw_qualifier = " | ".join(
        item for item in (detection_condition, measure_qualifier) if item
    )
    limit = (row.get("DetectionQuantitationLimitMeasure/MeasureValue") or "").strip()
    if detection_condition.casefold() == "not detected":
        return "", "nd", raw_qualifier, limit, ""
    if detection_condition:
        return value, "trace", raw_qualifier, limit, ""
    if measure_qualifier:
        return value, measure_qualifier, raw_qualifier, limit, ""
    if not value:
        return "", "", raw_qualifier, limit, "not_reported"
    return value, "", raw_qualifier, limit, ""


def common_provenance(
    dataset: Mapping[str, Any], resource: Mapping[str, Any]
) -> dict[str, str]:
    return {
        "source_id": str(dataset["id"]),
        "dataset_title": str(dataset["title"]),
        "dataset_doi": str(dataset["doi"]),
        "dataset_version": str(dataset["version"]),
        "source_file": str(resource["local_file"]),
        "file_sha256": str(resource["sha256"]),
        "license": str(dataset["license"]),
        "source_tier": "government",
    }


def read_ds801(
    fixture_dir: Path, contract: Mapping[str, Any], max_samples: int
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "usgs_ds801")
    resource = resource_by_id(contract, "usgs_ds801_top5")
    path = verified_path(fixture_dir, resource)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        lines = handle.readlines()
    try:
        header_index = next(
            index for index, line in enumerate(lines) if line.startswith("Top5_LabID\t")
        )
    except StopIteration as exc:
        raise AdapterError("DS801 Top5 header was not found") from exc
    reader = csv.reader(lines[header_index:], delimiter="\t")
    headers = next(reader)
    units = next(reader)
    unit_by_column = dict(zip(headers, units, strict=True))
    sampled = 0
    for offset, values in enumerate(reader, start=header_index + 3):
        if not any(value.strip() for value in values):
            continue
        if len(values) != len(headers):
            raise AdapterError(
                f"DS801 row {offset} has {len(values)} fields; expected {len(headers)}"
            )
        if max_samples and sampled >= max_samples:
            break
        sampled += 1
        raw = dict(zip(headers, values, strict=True))
        lab_id = raw["Top5_LabID"].strip()
        if not lab_id:
            raise AdapterError(f"DS801 row {offset} has no Top5_LabID")
        site_id = raw["SiteID"].strip()
        # DS801 uses the literal N.S. for sites where no sample was available;
        # it occurs more than once and therefore cannot serve as an identifier.
        sample_key = (
            lab_id if lab_id.casefold() != "n.s." else f"site-{site_id}-no-sample"
        )
        for element, method in DS801_METHODS.items():
            source_column = f"Top5_{element}"
            value, qualifier, raw_qualifier, missing_reason = ds801_measurement(
                raw[source_column]
            )
            row = {
                "record_id": f"usgs-ds801-top5:{sample_key}:{element}",
                "source_record_id": f"DS801:Top5:{sample_key}:{element}",
                "sample_id": sample_key,
                "sample_identity_group": f"DS801:site:{site_id}:top5",
                "element_or_analyte": element,
                "analyte_reported": element,
                "value": value,
                "unit": unit_by_column[source_column].strip(),
                "value_qualifier": qualifier,
                "source_qualifier_raw": raw_qualifier,
                "missing_reason": missing_reason,
                "medium": "soil",
                "material": "surface soil, 0-5 cm, <2 mm fraction",
                "measurement_basis": method["basis"],
                "latitude": raw["Latitude"].strip(),
                "longitude": raw["Longitude"].strip(),
                "source_crs": "WGS84",
                "coordinate_transform_method": "",
                "coordinate_uncertainty_m": "",
                "sampled_at": iso_us_date(raw["CollDate"]),
                "sample_depth_min_m": "0",
                "sample_depth_max_m": "0.05",
                "grain_fraction": "<2 mm",
                "analytical_method": method["method"],
                "method_family": method["family"],
                "digestion_or_extraction": method["digestion"],
                "laboratory": "",
                "detection_limit": "",
                "detection_limit_unit": "",
                "source_row": str(offset),
                "source_locator": f"{resource['url']}#row={offset}&column={source_column}",
                **common_provenance(dataset, resource),
            }
            yield row


def read_rass(
    fixture_dir: Path, contract: Mapping[str, Any], max_samples: int
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "usgs_rass_circle")
    resource = resource_by_id(contract, "usgs_rass_circle_sediment")
    path = verified_path(fixture_dir, resource)
    selected = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for logical_row, raw in enumerate(reader, start=2):
            if (
                not (raw.get("DESCRIPT1") or "").startswith("SD(")
                or (raw.get("DESCRIPT2") or "").strip()
            ):
                continue
            if max_samples and selected >= max_samples:
                break
            selected += 1
            tag = (raw.get("TAGNUMBER") or "").strip()
            if not tag:
                raise AdapterError(
                    f"RASS logical CSV row {logical_row} has no TAGNUMBER"
                )
            for element in RASS_ELEMENTS:
                source_value_column = f"S_{element.upper()}_PPM"
                source_qualifier_column = f"S_{element.upper()}_Q"
                source_value = raw.get(source_value_column) or ""
                source_qualifier = raw.get(source_qualifier_column) or ""
                value, qualifier, detection_limit, missing_reason = rass_measurement(
                    source_value, source_qualifier
                )
                yield {
                    "record_id": f"usgs-rass-circle:{tag}:{element}",
                    "source_record_id": f"RASS:Circle:{tag}:S_{element.upper()}",
                    "sample_id": tag,
                    "sample_identity_group": f"RASS:Circle:{tag}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": value,
                    "unit": "ppm",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": source_qualifier.strip(),
                    "missing_reason": missing_reason,
                    "medium": "sediment",
                    "material": "stream sediment",
                    "measurement_basis": "semiquantitative_total_solid",
                    "latitude": (raw.get("LATITUDE") or "").strip(),
                    "longitude": (raw.get("LONGITUDE") or "").strip(),
                    "source_crs": "NAD27",
                    "coordinate_transform_method": "",
                    "coordinate_uncertainty_m": "",
                    "sampled_at": iso_legacy_yymmdd(raw.get("SUBDATE") or ""),
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": (raw.get("MESH_SIZE") or "").strip(),
                    "analytical_method": "Semiquantitative direct-current arc emission spectrography",
                    "method_family": "emission_spectrography",
                    "digestion_or_extraction": "none; prepared solid analyzed directly",
                    "laboratory": "U.S. Geological Survey analytical laboratories",
                    "detection_limit": detection_limit,
                    "detection_limit_unit": "ppm" if detection_limit else "",
                    "source_row": str(logical_row),
                    "source_locator": (
                        f"{resource['url']}#record={logical_row - 1}&field={source_value_column}"
                    ),
                    **common_provenance(dataset, resource),
                }


def read_taylor_rock(
    fixture_dir: Path, contract: Mapping[str, Any], max_samples: int
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "usgs_taylor_mountains_rock")
    resource = resource_by_id(contract, "usgs_taylor_mountains_rock")
    metadata_resource = resource_by_id(contract, "usgs_taylor_mountains_metadata")
    path = verified_path(fixture_dir, resource)
    selected = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = set(
            column for column, _unit in TAYLOR_ROCK_ELEMENTS.values()
        ) - set(reader.fieldnames or [])
        if missing_columns:
            raise AdapterError(
                f"Taylor Mountains rock columns are missing: {sorted(missing_columns)}"
            )
        for logical_row, raw in enumerate(reader, start=2):
            if max_samples and selected >= max_samples:
                break
            selected += 1
            lab_id = (raw.get("Lab_No.") or "").strip()
            field_id = (raw.get("Field_No.\n(USGS)") or "").strip()
            if not lab_id or not field_id:
                raise AdapterError(
                    f"Taylor Mountains logical CSV row {logical_row} lacks Lab_No. or Field_No."
                )
            rock_type = (raw.get("RockType") or "").strip()
            sample_source = (raw.get("Sample Source") or "").strip()
            geologic_age = (raw.get("Geologic Age") or "").strip()
            material_parts = ["rock"]
            if rock_type:
                material_parts.append(f"type={rock_type}")
            if sample_source:
                material_parts.append(f"source={sample_source}")
            if geologic_age:
                material_parts.append(f"age={geologic_age}")
            geologic_unit = (raw.get("Rock Formation") or "").strip()
            for element, (source_column, unit) in TAYLOR_ROCK_ELEMENTS.items():
                value, qualifier, raw_qualifier, missing_reason = ds801_measurement(
                    raw.get(source_column) or ""
                )
                yield {
                    "record_id": f"usgs-taylor-rock:{lab_id}:{element}",
                    "source_record_id": f"OFR2007-1196:Table03:{lab_id}:{element}",
                    "sample_id": field_id,
                    "sample_identity_group": f"OFR2007-1196:Table03:{field_id}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": value,
                    "unit": unit,
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing_reason,
                    "medium": "rock",
                    "material": "; ".join(material_parts),
                    "measurement_basis": "sodium_peroxide_sinter",
                    "latitude": (raw.get("Latitude\nDec. Deg.") or "").strip(),
                    "longitude": (raw.get("Longitude\nDec. Deg.") or "").strip(),
                    "source_crs": "NAD27",
                    "coordinate_transform_method": "",
                    "coordinate_uncertainty_m": "6.1",
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": "",
                    "lithology": (raw.get("RockName") or "").strip(),
                    "geologic_unit": geologic_unit,
                    "geologic_unit_id": "",
                    "geologic_context_source": (
                        f"{metadata_resource['url']}#attribute=Rock%20Formation"
                        if geologic_unit
                        else ""
                    ),
                    "geologic_context_version": (
                        "OFR 2007-1196 v1.1 (2010-05-21)" if geologic_unit else ""
                    ),
                    "geologic_match_method": "source_table_reported"
                    if geologic_unit
                    else "",
                    "distance_to_geologic_boundary_m": "",
                    "geologic_match_confidence": "unknown" if geologic_unit else "",
                    "analytical_method": (
                        "ICP-AES or ICP-MS following sodium peroxide sinter at 450 degrees Celsius"
                    ),
                    "method_family": "icp_aes_ms",
                    "digestion_or_extraction": "sodium peroxide sinter at 450 degrees Celsius",
                    "laboratory": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "source_row": str(logical_row),
                    "source_locator": (
                        f"{resource['url']}#logical-record={logical_row - 1}&element={element}"
                    ),
                    **common_provenance(dataset, resource),
                }


def horizontal_uncertainty_m(station: Mapping[str, str]) -> str:
    raw = (station.get("HorizontalAccuracyMeasure/MeasureValue") or "").strip()
    unit = (
        (station.get("HorizontalAccuracyMeasure/MeasureUnitCode") or "")
        .strip()
        .casefold()
    )
    try:
        value = float(raw)
    except ValueError:
        return ""
    if not math.isfinite(value) or value < 0:
        return ""
    if unit in {"second", "seconds", "arc-second", "arc-seconds"}:
        return f"{value * 31.0:g}"
    if unit in {"m", "meter", "meters"}:
        return f"{value:g}"
    return ""


def read_wqp(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "wqp_usgs_01594440_arsenic")
    result_resource = resource_by_id(contract, "wqp_usgs_01594440_arsenic")
    station_resource = resource_by_id(contract, "wqp_usgs_01594440_station")
    result_path = verified_path(fixture_dir, result_resource)
    station_path = verified_path(fixture_dir, station_resource)
    with station_path.open("r", encoding="utf-8-sig", newline="") as handle:
        station_rows = list(csv.DictReader(handle))
    stations = {row["MonitoringLocationIdentifier"]: row for row in station_rows}
    with result_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for logical_row, raw in enumerate(csv.DictReader(handle), start=2):
            location_id = (raw.get("MonitoringLocationIdentifier") or "").strip()
            station = stations.get(location_id)
            if station is None:
                raise AdapterError(
                    f"WQP result row {logical_row} has no station metadata: {location_id}"
                )
            result_id = (raw.get("ResultIdentifier") or "").strip()
            if not result_id:
                raise AdapterError(
                    f"WQP result row {logical_row} has no ResultIdentifier"
                )
            value, qualifier, raw_qualifier, detection_limit, missing_reason = (
                wqp_measurement(raw)
            )
            fraction = (
                (raw.get("ResultSampleFractionText") or "unspecified")
                .strip()
                .casefold()
            )
            method = (raw.get("ResultAnalyticalMethod/MethodName") or "").strip()
            yield {
                "record_id": f"wqp:{result_id}",
                "source_record_id": result_id,
                "sample_id": (raw.get("ActivityIdentifier") or "").strip(),
                "sample_identity_group": (
                    f"WQP:{location_id}:{(raw.get('ActivityIdentifier') or '').strip()}"
                ),
                "element_or_analyte": "As",
                "analyte_reported": (raw.get("CharacteristicName") or "").strip(),
                "value": value,
                "unit": (raw.get("ResultMeasure/MeasureUnitCode") or "ug/l").strip()
                or "ug/l",
                "value_qualifier": qualifier,
                "source_qualifier_raw": raw_qualifier,
                "missing_reason": missing_reason,
                "medium": "water",
                "material": (
                    raw.get("ActivityMediaSubdivisionName") or "water"
                ).strip(),
                "measurement_basis": f"aqueous_{fraction.replace(' ', '_')}",
                "latitude": (station.get("LatitudeMeasure") or "").strip(),
                "longitude": (station.get("LongitudeMeasure") or "").strip(),
                "source_crs": (
                    station.get("HorizontalCoordinateReferenceSystemDatumName") or ""
                ).strip(),
                "coordinate_transform_method": "",
                "coordinate_uncertainty_m": horizontal_uncertainty_m(station),
                "sampled_at": (raw.get("ActivityStartDate") or "").strip(),
                "sample_depth_min_m": "",
                "sample_depth_max_m": "",
                "grain_fraction": "",
                "analytical_method": method,
                "method_family": "",
                "digestion_or_extraction": "",
                "laboratory": (raw.get("LaboratoryName") or "").strip(),
                "detection_limit": detection_limit,
                "detection_limit_unit": (
                    raw.get("DetectionQuantitationLimitMeasure/MeasureUnitCode") or ""
                ).strip(),
                "source_row": str(logical_row),
                "source_locator": f"{result_resource['url']}#ResultIdentifier={result_id}",
                **common_provenance(dataset, result_resource),
            }


def atomic_write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})
            count += 1
    os.replace(temporary, path)
    return count


def adapt_sources(
    fixture_dir: Path, output_dir: Path, max_source_samples: int
) -> dict[str, Path]:
    prepare_empty_output_dir(output_dir)
    contract = load_json(SOURCE_CONTRACT)
    raw_manifest_path = fixture_dir / "source_manifest.json"
    if not raw_manifest_path.is_file():
        raise AdapterError(
            "source_manifest.json is missing; verify fixtures before adapting"
        )
    raw_manifest = load_json(raw_manifest_path)
    if raw_manifest.get("source_contract_sha256") != sha256_file(SOURCE_CONTRACT):
        raise AdapterError(
            "fixture manifest does not bind the current real source contract"
        )

    rows = [
        *read_ds801(fixture_dir, contract, max_source_samples),
        *read_rass(fixture_dir, contract, max_source_samples),
        *read_taylor_rock(fixture_dir, contract, max_source_samples),
        *read_wqp(fixture_dir, contract),
    ]
    export_path = output_dir / "d1_real_export.csv"
    record_count = atomic_write_csv(export_path, rows)
    source_counts = Counter(row["source_id"] for row in rows)
    medium_counts = Counter(row["medium"] for row in rows)
    raw_qualifier_counts = Counter(
        f"{row['source_id']}:{row['source_qualifier_raw']}"
        for row in rows
        if row["source_qualifier_raw"]
    )
    manifest = {
        "manifest_version": "d1-real-manifest-v2",
        "adapter_version": ADAPTER_VERSION,
        "source_contract": SOURCE_CONTRACT.name,
        "source_contract_sha256": sha256_file(SOURCE_CONTRACT),
        "fixture_manifest": raw_manifest_path.name,
        "fixture_manifest_sha256": sha256_file(raw_manifest_path),
        "configuration": {
            "max_source_samples": max_source_samples,
            "selected_ds801_elements": list(DS801_METHODS),
            "selected_rass_elements": list(RASS_ELEMENTS),
            "selected_taylor_rock_elements": list(TAYLOR_ROCK_ELEMENTS),
            "wqp_result_policy": "retain all 90 frozen query rows",
        },
        "export": {
            "path": export_path.name,
            "sha256": sha256_file(export_path),
            "record_count": record_count,
            "source_counts": dict(sorted(source_counts.items())),
            "medium_counts": dict(sorted(medium_counts.items())),
            "raw_qualifier_counts": dict(sorted(raw_qualifier_counts.items())),
        },
        "mapping_decisions": [
            "DS801 values keep published prefixes such as <; wt.% and mg/kg are not normalized in D1.",
            "RASS N maps to nd with its companion value as detection limit; L maps to trace, never to nondetect.",
            "RASS NAD27 and WQP NAD83 coordinates are passed with their source CRS and no claimed transformation.",
            "Taylor Mountains rock coordinates remain NAD27; published lithology and formation fields are retained without upgrading uncertain labels.",
            "WQP station metadata is joined by MonitoringLocationIdentifier; no missing method is invented.",
            "DS801 literal N.S. laboratory IDs are replaced by site-scoped no-sample IDs to prevent collisions.",
            "source_qualifier_raw is retained beside the canonical qualifier through d2-interface-v2.",
        ],
        "scientific_scope": "Adapter and validation input only; no global coverage or causal interpretation.",
    }
    manifest_path = output_dir / "d1_real_manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {"export": export_path, "manifest": manifest_path}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Adapt frozen real USGS/WQP data into the D2 canonical input CSV."
    )
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--max-source-samples",
        type=int,
        default=0,
        help="Cap DS801, RASS and Taylor rock sample rows for smoke tests; 0 uses all. The 90-row WQP query stays whole.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_source_samples < 0:
        parser.error("--max-source-samples must be nonnegative")
    try:
        outputs = adapt_sources(
            args.fixture_dir, args.output_dir, args.max_source_samples
        )
    except (AdapterError, OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {name: str(path) for name, path in outputs.items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
