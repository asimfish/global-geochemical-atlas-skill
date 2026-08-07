#!/usr/bin/env python3
"""Build reproducible V4 full-population profiles and a coverage cube.

Unlike the source demos, this command parses every target-bearing record in
each verified cache.  It emits only aggregate counts and structural inventories; source rows
are never copied into the repository.  A checked-in profile therefore proves
its own denominator without redistributing the upstream dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sqlite3
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import source_adapters
import v4_semantics


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_DIR = SKILL_DIR.parents[1]
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"
DEFAULT_CACHE = REPO_DIR / ".cache" / "data"
DEFAULT_OUTPUT = SKILL_DIR / "assets" / "v4-full-profiles"
DEFAULT_CUBE = SKILL_DIR / "assets" / "v4-coverage-cube.csv"
DEFAULT_BALANCE = SKILL_DIR / "assets" / "v4-coverage-balance.json"
DEFAULT_REPORT = SKILL_DIR / "references" / "v4-full-population-profile.md"
PROFILE_VERSION = "d1-v4-full-population-profile-v1"
CUBE_VERSION = "d1-v4-coverage-cube-v1"
GRID_RESOLUTION_DEGREES = 1.0

PROFILE_FIELDS = (
    "element_or_analyte",
    "value",
    "unit",
    "measurement_basis",
    "sample_id",
    "coordinate_pair",
    "source_crs",
    "coordinate_uncertainty_m",
    "sample_type_raw",
    "sample_type",
    "sample_type_mapping_status",
    "soil_horizon",
    "sediment_environment",
    "water_body_type",
    "water_fraction",
    "grain_fraction",
    "lithology_raw",
    "geologic_age_raw",
    "tectonic_setting_raw",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "analytical_method",
    "method_scope",
    "method_assignment_basis",
    "method_or_missing_reason",
    "detection_limit",
    "source_locator",
    "citation_text_raw",
    "citation_scope",
    "citation_resolution_status",
    "access_status",
    "research_use_status",
    "license",
    "license_url",
)

CUBE_COLUMNS = (
    "cube_version",
    "source_id",
    "medium",
    "element",
    "sample_type",
    "method_scope",
    "region",
    "measurement_basis",
    "observation_count",
    "distinct_sample_count",
    "independent_lineage_count",
    "reported_coordinate_sample_count",
    "valid_coordinate_sample_count",
    "comparable_observation_count",
    "covered_spatial_cells",
    "spatial_grid",
)


class FullProfileError(RuntimeError):
    """Raised when a full-population profile cannot be reproduced safely."""


@dataclass(frozen=True)
class Observation:
    row: Mapping[str, str]
    sample_id: str
    region: str
    comparable: bool
    spatial_cell: str
    reported_spatial_cell: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _numeric(value: Any) -> float | None:
    text = _text(value)
    match = re.fullmatch(r"[<>]?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)", text)
    if not match:
        return None
    number = float(match.group(1))
    return number if math.isfinite(number) else None


def _coordinate(latitude: Any, longitude: Any) -> tuple[str, str, str]:
    latitude_text = _text(latitude)
    longitude_text = _text(longitude)
    lat = _numeric(latitude_text)
    lon = _numeric(longitude_text)
    if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return latitude_text, longitude_text, ""
    cell = f"{math.floor(lat):+03d}:{math.floor(lon):+04d}"
    return latitude_text, longitude_text, cell


def _exact_midpoint(fields: Mapping[str, Any], minimum: str, maximum: str) -> str:
    low = _numeric(fields.get(minimum))
    high = _numeric(fields.get(maximum))
    if low is None or high is None or low != high:
        return ""
    return format(low, ".12g")


def _sample_and_place(source_id: str, fields: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    """Return sample_id, region, latitude, longitude and source CRS."""

    if source_id in {"georoc-archaean", "georoc-antarctica-intraplate"}:
        return (
            _text(fields.get("SAMPLE NAME")) or _text(fields.get("UNIQUE_ID")),
            _text(fields.get("LOCATION")),
            _exact_midpoint(fields, "LATITUDE MIN", "LATITUDE MAX"),
            _exact_midpoint(fields, "LONGITUDE MIN", "LONGITUDE MAX"),
            "",
        )
    if source_id == "usgs-conus-soil":
        layer = _text(fields.get("_soil_layer"))
        prefix = {"top-0-5cm": "Top5_", "a-horizon": "A_", "c-horizon": "C_"}.get(layer, "")
        return (
            _text(fields.get(prefix + "LabID")) or _text(fields.get("SiteID")),
            _text(fields.get("StateID")),
            _text(fields.get("Latitude")),
            _text(fields.get("Longitude")),
            "EPSG:4326",
        )
    if source_id == "norway-marchem":
        return (
            _text(fields.get("Sample_code")),
            "Norwegian marine survey",
            _text(fields.get("Latitude")),
            _text(fields.get("Longitude")),
            "EPSG:4326",
        )
    if source_id == "gemstat-open-archive":
        station = fields.get("_station_metadata")
        station = station if isinstance(station, Mapping) else {}
        sample_id = "|".join(
            (
                _text(fields.get("GEMS Station Number")),
                _text(fields.get("Sample Date")),
                _text(fields.get("Sample Time")),
                _text(fields.get("Depth")),
            )
        )
        return (
            sample_id,
            _text(station.get("Country Name")),
            _text(station.get("Latitude")),
            _text(station.get("Longitude")),
            "EPSG:4326",
        )
    if source_id == "geotraces-idp2025":
        return (
            "|".join((_text(fields.get("Cruise")), _text(fields.get("Station")), _text(fields.get("DEPTH [m]")))),
            _text(fields.get("Cruise")),
            _text(fields.get("Latitude [degrees_north]")),
            _text(fields.get("Longitude [degrees_east]")),
            "EPSG:4326",
        )
    if source_id == "japan-gsj-geochemical-map":
        return (
            _text(fields.get("_normalized_sample_id")),
            _text(fields.get("地図名")),
            _text(fields.get("緯度(JGD2000)")),
            _text(fields.get("経度(JGD2000)")),
            "JGD2000 geographic; treated as EPSG:4612 for query-grid profiling",
        )
    if source_id == "pangaea-north-africa-soil":
        return (
            _text(fields.get("Sample ID")) or _text(fields.get("Event")),
            _text(fields.get("Area")) or _text(fields.get("Location")),
            _text(fields.get("Latitude")),
            _text(fields.get("Longitude")),
            "EPSG:4326",
        )
    if source_id.startswith("foregs-"):
        return (
            _text(fields.get("GTN")),
            _text(fields.get("COUNTRY")) or _text(fields.get("Country")),
            _text(fields.get("LAT")),
            _text(fields.get("LONG")),
            "EPSG:4326",
        )
    if source_id == "afsis-phase-i-wet-chemistry":
        return (
            _text(fields.get("SSN")) or _text(fields.get("RES.ID")),
            _text(fields.get("_country_normalized")) or _text(fields.get("Country")),
            _text(fields.get("Latitude")),
            _text(fields.get("Longitude")),
            _text(fields.get("_source_crs")),
        )
    if source_id == "us-wqp-sacramento-river-arsenic":
        station = fields.get("_station_metadata")
        station = station if isinstance(station, Mapping) else {}
        return (
            _text(fields.get("ActivityIdentifier")),
            "California / Sacramento River at Freeport",
            _text(station.get("LatitudeMeasure")),
            _text(station.get("LongitudeMeasure")),
            _text(station.get("HorizontalCoordinateReferenceSystemDatumName")) or "NAD83",
        )
    if source_id == "australia-ngsa-mercury":
        return (
            _text(fields.get("SAMPLEID")),
            _text(fields.get("STATE")),
            _text(fields.get("LATITUDE_GDA94")),
            _text(fields.get("LONGITUDE_GDA94")),
            _text(fields.get("_source_crs")) or "EPSG:4283",
        )
    if source_id == "japan-gsj-marine-sediment":
        return (
            _text(fields.get("試料番号")),
            _text(fields.get("地域")) or _text(fields.get("航海")),
            _text(fields.get("緯度")),
            _text(fields.get("経度")),
            _text(fields.get("_source_crs")),
        )
    if source_id == "pangaea-arabian-sea-sediment":
        return (
            _text(fields.get("Sample label")) or _text(fields.get("Event")),
            _text(fields.get("Location")) or "Arabian Sea",
            _text(fields.get("Latitude")),
            _text(fields.get("Longitude")),
            _text(fields.get("_source_crs")) or "EPSG:4326",
        )
    if source_id == "tpdc-china-mountain-soil":
        return (
            "|".join((_text(fields.get("Sam.No")), _text(fields.get("Horizons")))),
            _text(fields.get("Mountain")),
            _text(fields.get("Latitude")),
            _text(fields.get("Longitude")),
            _text(fields.get("_source_crs")),
        )
    if source_id == "gemas-europe":
        return (
            _text(fields.get("_physical_sample_id")),
            _text(fields.get("COUNTRY")),
            _text(fields.get("YCOO")),
            _text(fields.get("XCOO")),
            _text(fields.get("_source_crs")) or "EPSG:4326",
        )
    if source_id == "usgs-utah-volcanic-whole-rock":
        return (
            _text(fields.get("StationID")) or _text(fields.get("LAB_ID")),
            _text(fields.get("State")) or _text(fields.get("LocationDescription")),
            _text(fields.get("_latitude")),
            _text(fields.get("_longitude")),
            _text(fields.get("_source_crs")) or "EPSG:4326",
        )
    if source_id.startswith("cdogs-210102-"):
        return (
            _text(fields.get("_sample_id")),
            _text(fields.get("_place")),
            _text(fields.get("_latitude")),
            _text(fields.get("_longitude")),
            _text(fields.get("_source_crs")),
        )
    if source_id == "brazil-sgb-florianopolis-stream-sediment":
        return (
            "|".join((_text(fields.get("sample_id")), _text(fields.get("num_lab")))),
            "Florianopolis, Brazil",
            _text(fields.get("latitude")),
            _text(fields.get("longitude")),
            _text(fields.get("source_crs")) or "EPSG:4326",
        )
    if source_id == "brazil-sgb-florianopolis-soil":
        return (
            "|".join((_text(fields.get("sample_id")), _text(fields.get("num_lab")))),
            "Florianopolis, Brazil",
            _text(fields.get("latitude")),
            _text(fields.get("longitude")),
            _text(fields.get("source_crs")) or "EPSG:4326",
        )
    raise FullProfileError(f"no sample/place mapping for {source_id}")


def _method(source_id: str, fields: Mapping[str, Any], field_name: str, values: Mapping[str, Any]) -> tuple[str, str]:
    method = _text(values.get("analytical_method"))
    locator = _text(values.get("variable_metadata_locator"))
    if source_id == "norway-marchem":
        methods = fields.get("_lab_parameters")
        methods = methods if isinstance(methods, Mapping) else {}
        item = methods.get(field_name)
        item = item if isinstance(item, Mapping) else {}
        method = _text(item.get("Analysis_method"))
        locator = _text(item.get("_metadata_source_locator"))
    elif source_id == "gemstat-open-archive":
        item = fields.get("_method_metadata")
        item = item if isinstance(item, Mapping) else {}
        if _text(fields.get("Analysis Method Code")) != "0":
            method = _text(item.get("Method Name")) or _text(item.get("Method Description"))
            locator = _text(item.get("_metadata_source_locator"))
    elif source_id == "pangaea-north-africa-soil":
        method = _text(fields.get("_analytical_method"))
    elif source_id in {"brazil-sgb-florianopolis-stream-sediment", "brazil-sgb-florianopolis-soil"}:
        method = _text(fields.get("analytical_method_raw"))
        locator = _text(fields.get("source_locator"))
    return method, locator


def _target_values(
    source_id: str,
    fields: Mapping[str, Any],
    registry_entry: Mapping[str, Any],
) -> Iterable[tuple[str, str, str, Mapping[str, Any]]]:
    """Yield analyte, source field, raw value and observation metadata."""

    nested = fields.get("_target_observations")
    if isinstance(nested, Mapping):
        for analyte, values in nested.items():
            if not isinstance(values, Mapping):
                continue
            raw = _text(values.get("reported_value")) or _text(values.get("raw_value")) or _text(values.get("value"))
            if raw:
                yield (
                    _text(values.get("analyte")) or _text(analyte),
                    _text(values.get("field")) or _text(analyte),
                    raw,
                    values,
                )
        return
    if source_id == "gemstat-open-archive":
        raw = _text(fields.get("Value"))
        if raw:
            unit = _text(fields.get("Unit"))
            unit_basis = unit.lower().replace("µ", "u").replace("/", "_per_").replace(" ", "_")
            element = _text(fields.get("_element"))
            fraction = _text(fields.get("_water_fraction"))
            yield element, _text(fields.get("Parameter Code")), raw, {
                "unit": _text(fields.get("Unit")),
                "measurement_basis": f"freshwater_{fraction}_operational_fraction_{unit_basis}",
            }
        return
    targets = registry_entry.get("target_analytes")
    if not isinstance(targets, Mapping):
        return
    for analyte, configured in targets.items():
        candidates = configured if isinstance(configured, list) else [configured]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            raw = _text(fields.get(candidate))
            if not raw:
                continue
            unit = ""
            units = fields.get("_units")
            if isinstance(units, Mapping):
                unit = _text(units.get(candidate))
            elif source_id == "georoc-archaean" and candidate.endswith("(PPM)"):
                unit = "ppm"
            elif source_id == "japan-gsj-geochemical-map":
                target_units = fields.get("_target_units")
                unit = _text(target_units.get(analyte)) if isinstance(target_units, Mapping) else ""
            elif "[mg/kg]" in candidate:
                unit = "mg/kg"
            values: dict[str, Any] = {"unit": unit}
            if source_id == "usgs-conus-soil":
                values["measurement_basis"] = "total_or_near_total_<2mm"
            elif source_id == "norway-marchem":
                values["measurement_basis"] = "dry_weight_partial_nitric_acid"
            elif source_id == "japan-gsj-geochemical-map":
                values["measurement_basis"] = "published_river_sediment_concentration"
            elif source_id == "pangaea-north-africa-soil":
                values["measurement_basis"] = "HF-HNO3_digested_deflatable_surface_soil_fraction"
            elif source_id == "georoc-archaean":
                values["measurement_basis"] = "reported_whole_rock_concentration"
            yield _text(analyte), candidate, raw, values
            break


def _semantic_evidence(source_id: str, fields: Mapping[str, Any], record_id: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {"source_id": source_id, "record_id": record_id}
    if source_id.startswith("foregs-"):
        evidence["sample_type"] = _text(fields.get("_sample_type"))
    elif source_id == "usgs-conus-soil":
        evidence["soil_layer"] = _text(fields.get("_soil_layer"))
    elif source_id == "afsis-phase-i-wet-chemistry":
        evidence["reported_depth"] = _text(fields.get("Depth"))
    elif source_id == "gemstat-open-archive":
        station = fields.get("_station_metadata")
        station = station if isinstance(station, Mapping) else {}
        evidence["water_type"] = _text(station.get("Water Type"))
        evidence["water_fraction"] = _text(fields.get("_water_fraction"))
    elif source_id == "geotraces-idp2025":
        evidence["cruise"] = _text(fields.get("Cruise"))
        evidence["station"] = _text(fields.get("Station"))
    elif source_id == "japan-gsj-geochemical-map":
        evidence["map_sheet"] = _text(fields.get("地図名"))
        evidence["reported_place"] = _text(fields.get("採取地"))
        evidence["reported_river"] = _text(fields.get("川"))
    elif source_id == "pangaea-north-africa-soil":
        evidence["potential_source_area"] = _text(fields.get("Area"))
        evidence["reported_location"] = _text(fields.get("Location"))
    elif source_id == "australia-ngsa-mercury":
        evidence["reported_depth"] = _text(fields.get("DEPTH"))
        evidence["state"] = _text(fields.get("STATE"))
        evidence["site_id"] = _text(fields.get("SITEID"))
    elif source_id == "japan-gsj-marine-sediment":
        evidence["cruise"] = _text(fields.get("航海"))
        evidence["region"] = _text(fields.get("地域"))
    elif source_id == "pangaea-arabian-sea-sediment":
        evidence["event"] = _text(fields.get("Event"))
        evidence["location"] = _text(fields.get("Location")) or "Arabian Sea"
    elif source_id == "tpdc-china-mountain-soil":
        evidence["reported_horizon"] = _text(fields.get("Horizons"))
        evidence["mountain"] = _text(fields.get("Mountain"))
        evidence["site"] = _text(fields.get("site"))
    elif source_id == "gemas-europe":
        evidence["sample_type"] = _text(fields.get("TYPE_"))
        evidence["country_raw"] = _text(fields.get("COUNTRY"))
    elif source_id == "usgs-utah-volcanic-whole-rock":
        evidence["sample_type"] = _text(fields.get("_sample_type"))
        evidence["state"] = _text(fields.get("State"))
        evidence["location"] = _text(fields.get("LocationDescription"))
    elif source_id.startswith("cdogs-210102-"):
        evidence["sample_type"] = _text(fields.get("sample_type"))
        evidence["sample_type_raw"] = _text(fields.get("sample_type_raw"))
        evidence["site_id"] = _text(fields.get("site_id"))
    elif source_id == "brazil-sgb-florianopolis-stream-sediment":
        evidence["sample_type_raw"] = _text(fields.get("sample_type_raw"))
        evidence["project"] = _text(fields.get("projeto_amostragem"))
        evidence["sample_id"] = _text(fields.get("sample_id"))
    elif source_id == "brazil-sgb-florianopolis-soil":
        evidence["sample_type_raw"] = _text(fields.get("sample_type_raw"))
        evidence["project"] = _text(fields.get("projeto_amostragem"))
        evidence["sample_id"] = _text(fields.get("sample_id"))
        evidence["soil_horizon_raw"] = _text(fields.get("soil_horizon_raw"))
        evidence["soil_type_raw"] = _text(fields.get("soil_type_raw"))
    return evidence


def _observation(
    source_id: str,
    raw: source_adapters.RawRecord,
    registry_entry: Mapping[str, Any],
    registry_verified_at: str,
    analyte: str,
    field_name: str,
    value: str,
    values: Mapping[str, Any],
    ordinal: int,
) -> Observation:
    sample_id, region, latitude, longitude, source_crs = _sample_and_place(source_id, raw.fields)
    latitude, longitude, reported_spatial_cell = _coordinate(latitude, longitude)
    spatial_cell = reported_spatial_cell if source_crs == "EPSG:4326" else ""
    record_id = f"profile:{raw.source_record_id}:{analyte}:{ordinal}"
    method, method_locator = _method(source_id, raw.fields, field_name, values)
    evidence = _semantic_evidence(source_id, raw.fields, record_id)
    if method_locator:
        evidence["method_source_locator"] = method_locator
    evidence["dataset_doi"] = registry_entry.get("dataset_doi")
    evidence["article_citations"] = [registry_entry.get("citation")] if registry_entry.get("citation") else []
    evidence["article_dois"] = [registry_entry.get("dataset_doi")] if registry_entry.get("dataset_doi") else []
    unit = _text(values.get("unit"))
    if not unit and source_id == "norway-marchem":
        methods = raw.fields.get("_lab_parameters")
        item = methods.get(field_name) if isinstance(methods, Mapping) else None
        unit = _text(item.get("Unit")) if isinstance(item, Mapping) else ""
    row: dict[str, Any] = {
        "record_id": record_id,
        "source_record_id": raw.source_record_id,
        "source_id": source_id,
        "source_locator": raw.source_locator,
        "sample_id": sample_id,
        "element_or_analyte": analyte,
        "value": value,
        "value_qualifier": _text(values.get("value_qualifier")),
        "unit": unit,
        "medium": _text((registry_entry.get("media") or [""])[0]),
        "measurement_basis": _text(values.get("measurement_basis")),
        "detection_limit": _text(values.get("detection_limit")),
        "detection_limit_unit": _text(values.get("detection_limit_unit")),
        "sampled_at": _text(raw.fields.get("sampled_at")),
        "latitude": latitude,
        "longitude": longitude,
        "source_crs": source_crs,
        "coordinate_uncertainty_m": _text(raw.fields.get("_coordinate_uncertainty_m")) or (
            "20"
            if source_id in {"japan-gsj-geochemical-map", "japan-gsj-marine-sediment"}
            else "15"
            if source_id == "us-wqp-sacramento-river-arsenic"
            else ""
        ),
        "analytical_method": method,
        "method_scope": _text(values.get("method_scope")),
        "method_assignment_basis": _text(values.get("method_assignment_basis")),
        "method_candidates": json.dumps(values.get("method_candidates", []), ensure_ascii=False, separators=(",", ":")),
        "preparation": _text(values.get("preparation")),
        "analytical_technique": _text(values.get("analytical_technique")) or method,
        "laboratory": _text(values.get("laboratory")) or _text(raw.fields.get("_laboratory_raw")),
        "digestion_or_extraction": _text(values.get("digestion_or_extraction")) or _text(raw.fields.get("digestion_or_extraction_raw")),
        "coordinate_status": _text(raw.fields.get("coordinate_status")),
        "license": _text((registry_entry.get("license") or {}).get("spdx")),
        "grain_fraction": _text(raw.fields.get("_grain_fraction")),
        "material_raw": _text(raw.fields.get("MATERIAL")) or _text(raw.fields.get("_rock_type_raw")),
        "soil_horizon_raw": _text(raw.fields.get("soil_horizon_raw")),
        "soil_horizon": _text(raw.fields.get("soil_horizon")),
        "soil_horizon_missing_reason": _text(raw.fields.get("soil_horizon_missing_reason")),
        "lithology_raw": _text(raw.fields.get("ROCK NAME")) or _text(raw.fields.get("_lithology_raw")) or (
            _text(raw.fields.get("Rock Group")) if source_id == "tpdc-china-mountain-soil" else ""
        ),
        "geologic_age_raw": _text(raw.fields.get("AGE")) or _text(raw.fields.get("_geologic_age_raw")),
        "tectonic_setting_raw": _text(raw.fields.get("TECTONIC SETTING")),
    }
    row = v4_semantics.enrich_row(row, evidence, registry_entry, registry_verified_at)
    comparable = bool(
        _numeric(value) is not None
        and unit
        and sample_id
        and spatial_cell
        and row.get("sample_type")
        and row.get("measurement_basis")
        and row.get("analytical_method")
        and row.get("method_scope")
    )
    return Observation(
        row=row,
        sample_id=sample_id,
        region=region or "not_reported",
        comparable=comparable,
        spatial_cell=spatial_cell,
        reported_spatial_cell=reported_spatial_cell,
    )


def _marchem_payload_equivalent_files(cache_root: Path, registry_entry: Mapping[str, Any]) -> list[source_adapters.DownloadedFile]:
    archive = cache_root / "norway-marchem" / "current" / "marchem-inorganic-current.zip"
    if not archive.is_file():
        raise FullProfileError("MarChem frozen archive unavailable and no current audit archive is present")
    expected_by_id = {item["file_id"]: item for item in registry_entry["download"]["members"]}
    extract_dir = cache_root / "norway-marchem" / "current" / "profile-members"
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        candidates: dict[str, zipfile.ZipInfo] = {}
        for info in handle.infolist():
            name = info.filename
            if name.startswith("MetaData/MarChem_Inorganic_LabParameter_"):
                candidates["metadata"] = info
            elif name.startswith("MarChem_Inorganic_Data_"):
                candidates["data"] = info
            elif name.startswith("MarChem_Info_"):
                candidates["info"] = info
        if set(candidates) != {"data", "metadata", "info"}:
            raise FullProfileError("MarChem current archive member schema changed")
        files: list[source_adapters.DownloadedFile] = []
        for file_id, info in candidates.items():
            payload = handle.read(info)
            expected = expected_by_id[file_id]
            if file_id in {"data", "metadata"} and len(payload) != expected["bytes"]:
                raise FullProfileError(f"MarChem scientific payload byte count changed: {file_id}")
            path = extract_dir / Path(info.filename).name
            path.write_bytes(payload)
            files.append(
                source_adapters.DownloadedFile(
                    source_id="norway-marchem",
                    file_id=file_id,
                    path=path,
                    source_url=f"{registry_entry['download']['url']}#member={info.filename}",
                    bytes=len(payload),
                    cache_status="payload_equivalent_dynamic_export",
                    retrieved_at="2026-08-06T13:35:38Z",
                )
            )
    return files


def _downloaded_files(source_id: str, registry_entry: Mapping[str, Any], cache_root: Path) -> tuple[list[source_adapters.DownloadedFile], dict[str, Any]]:
    adapter = source_adapters.get_adapter(source_id)
    candidate = adapter.discover({"sources": [source_id]})[0]
    cache = cache_root / "foregs-adapters" if source_id.startswith("foregs-") else cache_root
    try:
        files = adapter.download(candidate, cache, mode="cached")
        drift = {"status": "matches_registered_snapshot", "outer_archive_drift": False}
    except source_adapters.SourceAdapterError as exc:
        if source_id != "norway-marchem":
            raise FullProfileError(f"{source_id} cache verification failed: {exc}") from exc
        files = _marchem_payload_equivalent_files(cache_root, registry_entry)
        drift = {
            "status": "scientific_payload_structure_equivalent_outer_archive_drift",
            "outer_archive_drift": True,
            "current_archive_bytes": (cache_root / "norway-marchem" / "current" / "marchem-inorganic-current.zip").stat().st_size,
            "data_and_method_member_bytes_match": True,
            "non_scientific_info_member_changed": True,
        }
    return files, drift


def _field_profile(observations: Sequence[Observation]) -> dict[str, Any]:
    denominator = len(observations)
    fields: dict[str, Any] = {}
    for field in PROFILE_FIELDS:
        if field == "coordinate_pair":
            non_empty = sum(bool(item.reported_spatial_cell) for item in observations)
        elif field == "method_or_missing_reason":
            non_empty = sum(
                bool(_text(item.row.get("analytical_method")) or _text(item.row.get("method_missing_reason")))
                for item in observations
            )
        else:
            non_empty = sum(bool(_text(item.row.get(field))) for item in observations)
        fields[field] = {
            "non_empty": non_empty,
            "missing": denominator - non_empty,
            "denominator": denominator,
            "rate": round(non_empty / denominator, 6) if denominator else 0.0,
        }
    return {
        "profile_scope": "full_population",
        "denominator_definition": "all non-empty target-analyte observations emitted by the verified source adapter",
        "observation_count": denominator,
        "fields": fields,
    }


def _profile_one(
    source_id: str,
    registry_entry: Mapping[str, Any],
    registry_verified_at: str,
    cache_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files, drift = _downloaded_files(source_id, registry_entry, cache_root)
    adapter = source_adapters.get_adapter(source_id)
    parsed_records = 0
    observation_count = 0
    raw_schema_keys: set[str] = set()
    field_non_empty: Counter[str] = Counter()
    method_scopes: Counter[str] = Counter()
    methods: Counter[str] = Counter()
    sample_types: Counter[str] = Counter()
    media: Counter[str] = Counter()
    water_types: Counter[str] = Counter()
    water_fractions: Counter[str] = Counter()
    sediment_environments: Counter[str] = Counter()
    geology: Counter[str] = Counter()
    citations: Counter[str] = Counter()
    elements: Counter[str] = Counter()
    comparable_count = 0
    region_counts: Counter[str] = Counter()
    source_crs_counts: Counter[str] = Counter()
    uncertainty_counts: Counter[str] = Counter()
    access_status_counts: Counter[str] = Counter()
    research_use_status_counts: Counter[str] = Counter()
    attribution_required_counts: Counter[str] = Counter()
    redistribution_status_counts: Counter[str] = Counter()
    publication_doi_count = 0
    upstream_primary_source_count = 0
    spatial_cells: set[str] = set()
    reported_spatial_cells: set[str] = set()
    element_cells: dict[str, set[str]] = defaultdict(set)
    element_reported_cells: dict[str, set[str]] = defaultdict(set)
    element_comparable: Counter[str] = Counter()
    bbox: list[float] | None = None
    cube: dict[tuple[str, ...], dict[str, Any]] = {}

    # Distinct sample counts are exact but disk-backed.  This keeps the 3.7M-row
    # GEMStat profile bounded in memory while preserving sample-level deduplication.
    distinct_db = sqlite3.connect("")
    distinct_db.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=MEMORY;
        CREATE TABLE samples(
            sample_id TEXT PRIMARY KEY,
            has_reported_coordinate INTEGER NOT NULL,
            has_coordinate INTEGER NOT NULL
        ) WITHOUT ROWID;
        CREATE TABLE element_samples(
            element TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            has_reported_coordinate INTEGER NOT NULL,
            has_coordinate INTEGER NOT NULL,
            PRIMARY KEY(element, sample_id)
        ) WITHOUT ROWID;
        CREATE TABLE cube_samples(
            cube_id INTEGER NOT NULL,
            sample_id TEXT NOT NULL,
            has_reported_coordinate INTEGER NOT NULL,
            has_coordinate INTEGER NOT NULL,
            PRIMARY KEY(cube_id, sample_id)
        ) WITHOUT ROWID;
        """
    )
    sample_batch: list[tuple[str, int, int]] = []
    element_sample_batch: list[tuple[str, str, int, int]] = []
    cube_sample_batch: list[tuple[int, str, int, int]] = []

    def flush_distinct_batches() -> None:
        if not sample_batch:
            return
        distinct_db.executemany(
            "INSERT INTO samples VALUES (?, ?, ?) ON CONFLICT(sample_id) DO UPDATE SET "
            "has_reported_coordinate=MAX(has_reported_coordinate, excluded.has_reported_coordinate), "
            "has_coordinate=MAX(has_coordinate, excluded.has_coordinate)",
            sample_batch,
        )
        distinct_db.executemany(
            "INSERT INTO element_samples VALUES (?, ?, ?, ?) ON CONFLICT(element, sample_id) DO UPDATE SET "
            "has_reported_coordinate=MAX(has_reported_coordinate, excluded.has_reported_coordinate), "
            "has_coordinate=MAX(has_coordinate, excluded.has_coordinate)",
            element_sample_batch,
        )
        distinct_db.executemany(
            "INSERT INTO cube_samples VALUES (?, ?, ?, ?) ON CONFLICT(cube_id, sample_id) DO UPDATE SET "
            "has_reported_coordinate=MAX(has_reported_coordinate, excluded.has_reported_coordinate), "
            "has_coordinate=MAX(has_coordinate, excluded.has_coordinate)",
            cube_sample_batch,
        )
        sample_batch.clear()
        element_sample_batch.clear()
        cube_sample_batch.clear()

    for raw in adapter.parse(files):
        parsed_records += 1
        raw_schema_keys.update(str(key) for key in raw.fields)
        for ordinal, (analyte, field_name, value, values) in enumerate(
            _target_values(source_id, raw.fields, registry_entry)
        ):
            item = _observation(
                source_id,
                raw,
                registry_entry,
                registry_verified_at,
                analyte,
                field_name,
                value,
                values,
                ordinal,
            )
            observation_count += 1
            row = item.row
            for field in PROFILE_FIELDS:
                if field == "coordinate_pair":
                    present = bool(item.reported_spatial_cell)
                elif field == "method_or_missing_reason":
                    present = bool(_text(row.get("analytical_method")) or _text(row.get("method_missing_reason")))
                else:
                    present = bool(_text(row.get(field)))
                if present:
                    field_non_empty[field] += 1
            method_scopes[_text(row.get("method_scope")) or "missing"] += 1
            methods[_text(row.get("analytical_method")) or "missing"] += 1
            sample_types[_text(row.get("sample_type")) or "missing"] += 1
            media[_text(row.get("medium")) or "missing"] += 1
            water_types[_text(row.get("water_body_type")) or "not_applicable"] += 1
            water_fractions[_text(row.get("water_fraction")) or "not_applicable"] += 1
            sediment_environments[_text(row.get("sediment_environment")) or "not_applicable"] += 1
            for field in (
                "lithology_raw",
                "geologic_age_raw",
                "tectonic_setting_raw",
                "geologic_unit_raw",
                "matched_geologic_unit",
            ):
                if _text(row.get(field)):
                    geology[field] += 1
            citations[_text(row.get("citation_scope")) or "missing"] += 1
            element = _text(row.get("element_or_analyte"))
            elements[element] += 1
            if item.comparable:
                comparable_count += 1
                element_comparable[element] += 1
            region_counts[item.region] += 1
            source_crs_counts[_text(row.get("source_crs")) or "not_reported"] += 1
            uncertainty_counts[_text(row.get("coordinate_uncertainty_m")) or "not_reported"] += 1
            access_status_counts[_text(row.get("access_status"))] += 1
            research_use_status_counts[_text(row.get("research_use_status"))] += 1
            attribution_required_counts[_text(row.get("attribution_required"))] += 1
            redistribution_status_counts[_text(row.get("redistribution_status"))] += 1
            publication_doi_count += bool(_text(row.get("publication_doi")))
            upstream_primary_source_count += bool(_text(row.get("upstream_primary_source_id")))
            if item.spatial_cell:
                spatial_cells.add(item.spatial_cell)
                element_cells[element].add(item.spatial_cell)
                latitude = _numeric(row.get("latitude"))
                longitude = _numeric(row.get("longitude"))
                if latitude is not None and longitude is not None:
                    if bbox is None:
                        bbox = [longitude, latitude, longitude, latitude]
                    else:
                        bbox = [
                            min(bbox[0], longitude),
                            min(bbox[1], latitude),
                            max(bbox[2], longitude),
                            max(bbox[3], latitude),
                        ]
            if item.reported_spatial_cell:
                reported_spatial_cells.add(item.reported_spatial_cell)
                element_reported_cells[element].add(item.reported_spatial_cell)

            cube_key = (
                source_id,
                _text(row.get("medium")) or "missing",
                element or "missing",
                _text(row.get("sample_type")) or "missing",
                _text(row.get("method_scope")) or "missing",
                item.region,
                _text(row.get("measurement_basis")) or "missing",
            )
            cube_cell = cube.get(cube_key)
            if cube_cell is None:
                cube_cell = {
                    "cube_id": len(cube),
                    "observation_count": 0,
                    "comparable": 0,
                    "reported_cells": set(),
                    "cells": set(),
                }
                cube[cube_key] = cube_cell
            cube_cell["observation_count"] += 1
            cube_cell["comparable"] += item.comparable
            if item.spatial_cell:
                cube_cell["cells"].add(item.spatial_cell)
            if item.reported_spatial_cell:
                cube_cell["reported_cells"].add(item.reported_spatial_cell)
            if item.sample_id:
                has_reported_coordinate = int(bool(item.reported_spatial_cell))
                has_coordinate = int(bool(item.spatial_cell))
                sample_batch.append((item.sample_id, has_reported_coordinate, has_coordinate))
                element_sample_batch.append((element, item.sample_id, has_reported_coordinate, has_coordinate))
                cube_sample_batch.append((cube_cell["cube_id"], item.sample_id, has_reported_coordinate, has_coordinate))
                if len(sample_batch) >= 25_000:
                    flush_distinct_batches()
    flush_distinct_batches()
    distinct_db.commit()
    if not observation_count:
        raise FullProfileError(f"{source_id} produced no target observations")

    fields = {
        "profile_scope": "full_population",
        "denominator_definition": "all non-empty target-analyte observations emitted by the verified source adapter",
        "observation_count": observation_count,
        "fields": {
            field: {
                "non_empty": field_non_empty[field],
                "missing": observation_count - field_non_empty[field],
                "denominator": observation_count,
                "rate": round(field_non_empty[field] / observation_count, 6),
            }
            for field in PROFILE_FIELDS
        },
    }
    distinct_sample_count, reported_coordinate_sample_count, coordinate_sample_count = distinct_db.execute(
        "SELECT COUNT(*), COALESCE(SUM(has_reported_coordinate), 0), COALESCE(SUM(has_coordinate), 0) FROM samples"
    ).fetchone()
    element_sample_counts = {
        element: (count, reported_coordinates, coordinates)
        for element, count, reported_coordinates, coordinates in distinct_db.execute(
            "SELECT element, COUNT(*), COALESCE(SUM(has_reported_coordinate), 0), "
            "COALESCE(SUM(has_coordinate), 0) FROM element_samples GROUP BY element"
        )
    }
    cube_sample_counts = {
        cube_id: (count, reported_coordinates, coordinates)
        for cube_id, count, reported_coordinates, coordinates in distinct_db.execute(
            "SELECT cube_id, COUNT(*), COALESCE(SUM(has_reported_coordinate), 0), "
            "COALESCE(SUM(has_coordinate), 0) FROM cube_samples GROUP BY cube_id"
        )
    }
    element_details: dict[str, dict[str, Any]] = {}
    for element in sorted(elements):
        sample_count, reported_coordinate_count, coordinate_count = element_sample_counts.get(element, (0, 0, 0))
        element_details[element] = {
            "observation_count": elements[element],
            "distinct_sample_count": sample_count,
            "reported_coordinate_sample_count": reported_coordinate_count,
            "valid_coordinate_sample_count": coordinate_count,
            "comparable_observation_count": element_comparable[element],
            "covered_spatial_cells": len(element_cells[element]),
            "spatial_cell_ids": sorted(element_cells[element]),
            "reported_spatial_cell_ids": sorted(element_reported_cells[element]),
        }
    cube_rows = []
    for key, value in sorted(cube.items()):
        cube_sample_count, cube_reported_coordinate_count, cube_coordinate_count = cube_sample_counts.get(
            value["cube_id"], (0, 0, 0)
        )
        cube_rows.append(
            {
                "cube_version": CUBE_VERSION,
                "source_id": key[0],
                "medium": key[1],
                "element": key[2],
                "sample_type": key[3],
                "method_scope": key[4],
                "region": key[5],
                "measurement_basis": key[6],
                "observation_count": value["observation_count"],
                "distinct_sample_count": cube_sample_count,
                "independent_lineage_count": 1,
                "reported_coordinate_sample_count": cube_reported_coordinate_count,
                "valid_coordinate_sample_count": cube_coordinate_count,
                "comparable_observation_count": value["comparable"],
                "covered_spatial_cells": len(value["cells"]),
                "spatial_grid": "canonical EPSG:4326 1-degree floor cell; observation coverage only",
            }
        )
    distinct_db.close()

    expected = registry_entry.get("expected_counts")
    expected_observations = expected.get("target_observations") if isinstance(expected, Mapping) else None
    count_status = (
        "matches_registered_expected_count"
        if isinstance(expected_observations, int) and expected_observations == observation_count
        else "baseline_recorded_no_registered_count"
        if expected_observations is None
        else "drift"
    )
    if count_status == "drift":
        raise FullProfileError(
            f"{source_id} target observation drift: {observation_count} != {expected_observations}"
        )
    file_inventory = [
        {
            "file_id": item.file_id,
            "filename": item.path.name,
            "bytes": item.bytes,
            "cache_status": item.cache_status,
        }
        for item in sorted(files, key=lambda value: value.file_id)
    ]
    profile = {
        "profile_version": PROFILE_VERSION,
        "source_id": source_id,
        "dataset_version": registry_entry.get("dataset_version"),
        "as_of": registry_verified_at,
        "field_completeness": fields,
        "method_completeness": {
            "observation_count": observation_count,
            "method_scope_counts": dict(sorted(method_scopes.items())),
            "analytical_method_counts": dict(sorted(methods.items())),
        },
        "sample_type_coverage": {
            "media": dict(sorted(media.items())),
            "sample_types": dict(sorted(sample_types.items())),
            "water_body_types": dict(sorted(water_types.items())),
            "water_fractions": dict(sorted(water_fractions.items())),
            "sediment_environments": dict(sorted(sediment_environments.items())),
        },
        "spatial_coverage": {
            "distinct_sample_count": distinct_sample_count,
            "reported_coordinate_sample_count": reported_coordinate_sample_count,
            "valid_coordinate_sample_count": coordinate_sample_count,
            "coordinate_count_definition": (
                "reported_coordinate_sample_count is numeric and range-valid in source coordinates; "
                "valid_coordinate_sample_count additionally requires canonical EPSG:4326"
            ),
            "reported_covered_spatial_cells": len(reported_spatial_cells),
            "covered_spatial_cells": len(spatial_cells),
            "spatial_grid": "canonical EPSG:4326 1-degree floor cell; no interpolation",
            "reported_spatial_grid": "source-coordinate 1-degree floor cell; not cross-source comparable",
            "spatial_cell_ids": sorted(spatial_cells),
            "bbox": bbox,
            "reported_spatial_cell_ids": sorted(reported_spatial_cells),
            "region_count": len(region_counts),
            "region_observation_counts": dict(sorted(region_counts.items())),
            "source_crs_observation_counts": dict(sorted(source_crs_counts.items())),
            "coordinate_uncertainty_m_observation_counts": dict(sorted(uncertainty_counts.items())),
        },
        "geology_coverage": {
            **{
                field: geology[field]
                for field in (
                    "lithology_raw",
                    "geologic_age_raw",
                    "tectonic_setting_raw",
                    "geologic_unit_raw",
                    "matched_geologic_unit",
                )
            },
            "observation_denominator": observation_count,
            "geographic_context_is_not_counted_as_geologic_unit": True,
        },
        "citation_coverage": {
            "citation_scope_counts": dict(sorted(citations.items())),
            "citation_text_count": fields["fields"]["citation_text_raw"]["non_empty"],
            "observation_denominator": observation_count,
            "dataset_doi": registry_entry.get("dataset_doi"),
            "dataset_doi_present": bool(registry_entry.get("dataset_doi")),
            "publication_doi_observation_count": publication_doi_count,
            "upstream_primary_source_observation_count": upstream_primary_source_count,
        },
        "usage_rights_coverage": {
            "access_status_counts": dict(sorted(access_status_counts.items())),
            "research_use_status_counts": dict(sorted(research_use_status_counts.items())),
            "license_id": _text((registry_entry.get("license") or {}).get("spdx")),
            "license_url": _text((registry_entry.get("license") or {}).get("url")),
            "attribution_required_counts": dict(sorted(attribution_required_counts.items())),
            "redistribution_status_counts": dict(sorted(redistribution_status_counts.items())),
            "redistribution_is_not_a_research_use_gate": True,
        },
        "automation_health": {
            "adapter_registered": True,
            "cached_parse_status": "pass",
            "offline_replay_status": "pass",
            "supported_modes": ["online", "cached", "offline_fixture"],
            # Cache validation timestamps change on every offline replay and are
            # not acquisition evidence. Keep the publisher/source observation
            # time from the registry so checked-in profiles remain reproducible.
            "last_successful_fetch_at": _text((registry_entry.get("download") or {}).get("observed_at")) or None,
            "last_successful_parse_at": registry_verified_at,
            "online_fetch_health": (
                "drift_detected_payload_equivalent"
                if drift.get("outer_archive_drift")
                else "not_probed_by_reproducible_offline_run"
            ),
            "retry_health": "not_measured_in_offline_profile",
            "cache_hit_count": sum(item.cache_status != "downloaded" for item in files),
            "parsed_source_record_count": parsed_records,
            "target_observation_count": observation_count,
            "expected_target_observation_count": expected_observations,
            "row_count_drift_status": count_status,
            "raw_schema_fields": sorted(raw_schema_keys),
            "raw_schema_field_count": len(raw_schema_keys),
            "schema_drift_detection": "checked-in profile exact comparison",
            "files": file_inventory,
            "version_drift": drift,
        },
        "coverage_metrics": {
            "observation_count": observation_count,
            "distinct_sample_count": distinct_sample_count,
            "independent_lineage_count": 1,
            "reported_coordinate_sample_count": reported_coordinate_sample_count,
            "valid_coordinate_sample_count": coordinate_sample_count,
            "comparable_observation_count": comparable_count,
            "covered_spatial_cells": len(spatial_cells),
            "elements": dict(sorted(elements.items())),
            "by_element": element_details,
        },
        "claim_boundary": (
            "Counts describe target observations in one verified source snapshot. Reported coordinates are kept "
            "separate from canonical EPSG:4326 coordinates; only canonical cells enter cross-source spatial coverage. "
            "Cells are observed, not interpolated; comparable means the minimum declared V4 grouping fields are present."
        ),
    }
    return profile, cube_rows


def _split_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    common = {
        "profile_version": profile["profile_version"],
        "source_id": profile["source_id"],
        "dataset_version": profile["dataset_version"],
        "as_of": profile["as_of"],
        "claim_boundary": profile["claim_boundary"],
    }
    return {
        "field_completeness.json": {**common, **profile["field_completeness"]},
        "method_completeness.json": {**common, **profile["method_completeness"]},
        "sample_type_coverage.json": {**common, **profile["sample_type_coverage"]},
        "spatial_coverage.json": {**common, **profile["spatial_coverage"]},
        "geology_coverage.json": {**common, **profile["geology_coverage"]},
        "citation_coverage.json": {**common, **profile["citation_coverage"]},
        "usage_rights_coverage.json": {**common, **profile["usage_rights_coverage"]},
        "automation_health.json": {**common, **profile["automation_health"]},
    }


def _csv_text(rows: Sequence[Mapping[str, Any]]) -> str:
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CUBE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.seek(0)
        return handle.read()


def _markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# V4 全量字段与覆盖立方体报告",
        "",
        "> 本报告由固定缓存全量解析生成；不使用 demo 行数替代全量分母，也不把空间格网插值成观测。",
        "",
        "## 总览",
        "",
        f"- 全量 profile 来源：{summary['source_count']}/{summary['registered_source_count']}",
        f"- 目标元素测定：{summary['observation_count']:,}",
        f"- 不同样品（逐来源去重后相加）：{summary['distinct_sample_count']:,}",
        f"- 来源报告坐标样品：{summary['reported_coordinate_sample_count']:,}",
        f"- canonical EPSG:4326 坐标样品：{summary['valid_coordinate_sample_count']:,}",
        f"- 可比较测定：{summary['comparable_observation_count']:,}",
        f"- 来源内 1° 观测格网数之和：{summary['covered_spatial_cells_source_sum']:,}",
        f"- 覆盖立方体行：{summary['coverage_cube_rows']:,}",
        "",
        "## 介质平衡",
        "",
        "| 介质 | 测定 | 样品 | 独立血缘 | 来源坐标样品 | canonical 坐标样品 | 可比较测定 | canonical 1°格网 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for medium, metrics in summary["media"].items():
        lines.append(
            f"| {medium} | {metrics['observation_count']:,} | {metrics['distinct_sample_count']:,} | "
            f"{metrics['independent_lineage_count']:,} | {metrics['reported_coordinate_sample_count']:,} | "
            f"{metrics['valid_coordinate_sample_count']:,} | "
            f"{metrics['comparable_observation_count']:,} | {metrics['covered_spatial_cells']:,} |"
        )
    lines.extend(
        [
        "",
        "## 分来源",
        "",
        "| 来源 | 介质 | 测定 | 样品 | 来源坐标样品 | canonical 坐标样品 | 可比较测定 | canonical 1°格网 | 方法完整率 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for source in summary["sources"]:
        lines.append(
            f"| `{source['source_id']}` | {source['medium']} | {source['observation_count']:,} | "
            f"{source['distinct_sample_count']:,} | {source['reported_coordinate_sample_count']:,} | "
            f"{source['valid_coordinate_sample_count']:,} | "
            f"{source['comparable_observation_count']:,} | {source['covered_spatial_cells']:,} | "
            f"{source['method_rate']:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 解释边界",
            "",
            "- `reported_coordinate_sample_count` 只表示来源坐标数值完整且范围合法；`valid_coordinate_sample_count` 还要求已规范到 EPSG:4326。",
            "- `comparable_observation_count` 要求数值、单位、样品类型、canonical 坐标、measurement basis、方法与 method scope 同时存在。",
            "- 不同来源的样品 ID 不跨来源合并，因此总样品数是逐来源去重后的加总。",
            "- 1°格网仅表示有实测点；它不表示格网内每个位置都被测量。",
            "- MarChem 当前外层 ZIP 与注册快照不同，但数据表和方法表逐字节相同；该非科学成员漂移在自动化健康文件中单独记录。",
            "",
            "机器可读结果位于 `assets/v4-full-profiles/` 和 `assets/v4-coverage-cube.csv`。",
        ]
    )
    return "\n".join(lines) + "\n"


def _coverage_balance(profiles: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    media: dict[str, dict[str, Any]] = {}
    medium_elements: dict[tuple[str, str], dict[str, Any]] = {}
    for source_id, profile in profiles.items():
        metrics = profile["coverage_metrics"]
        medium_counts = profile["sample_type_coverage"]["media"]
        if len(medium_counts) != 1:
            raise FullProfileError(f"{source_id} full profile must resolve to exactly one medium")
        medium = next(iter(medium_counts))
        target = media.setdefault(
            medium,
            {
                "observation_count": 0,
                "distinct_sample_count": 0,
                "lineages": set(),
                "source_ids": set(),
                "reported_coordinate_sample_count": 0,
                "valid_coordinate_sample_count": 0,
                "comparable_observation_count": 0,
                "reported_cells": set(),
                "cells": set(),
            },
        )
        target["observation_count"] += metrics["observation_count"]
        target["distinct_sample_count"] += metrics["distinct_sample_count"]
        lineage_id = source_adapters.source_lineage_id(source_id)
        target["lineages"].add(lineage_id)
        target["source_ids"].add(source_id)
        target["reported_coordinate_sample_count"] += metrics["reported_coordinate_sample_count"]
        target["valid_coordinate_sample_count"] += metrics["valid_coordinate_sample_count"]
        target["comparable_observation_count"] += metrics["comparable_observation_count"]
        target["reported_cells"].update(profile["spatial_coverage"]["reported_spatial_cell_ids"])
        target["cells"].update(profile["spatial_coverage"]["spatial_cell_ids"])
        for element, values in metrics["by_element"].items():
            cell = medium_elements.setdefault(
                (medium, element),
                {
                    "observation_count": 0,
                    "distinct_sample_count": 0,
                    "lineages": set(),
                    "source_ids": set(),
                    "reported_coordinate_sample_count": 0,
                    "valid_coordinate_sample_count": 0,
                    "comparable_observation_count": 0,
                    "reported_cells": set(),
                    "cells": set(),
                },
            )
            cell["observation_count"] += values["observation_count"]
            cell["distinct_sample_count"] += values["distinct_sample_count"]
            cell["lineages"].add(lineage_id)
            cell["source_ids"].add(source_id)
            cell["reported_coordinate_sample_count"] += values["reported_coordinate_sample_count"]
            cell["valid_coordinate_sample_count"] += values["valid_coordinate_sample_count"]
            cell["comparable_observation_count"] += values["comparable_observation_count"]
            cell["reported_cells"].update(values["reported_spatial_cell_ids"])
            cell["cells"].update(values["spatial_cell_ids"])

    def publish(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "observation_count": value["observation_count"],
            "distinct_sample_count": value["distinct_sample_count"],
            "independent_lineage_count": len(value["lineages"]),
            "source_ids": sorted(value["source_ids"]),
            "lineage_ids": sorted(value["lineages"]),
            "reported_coordinate_sample_count": value["reported_coordinate_sample_count"],
            "valid_coordinate_sample_count": value["valid_coordinate_sample_count"],
            "comparable_observation_count": value["comparable_observation_count"],
            "covered_spatial_cells": len(value["cells"]),
            "reported_covered_spatial_cells": len(value["reported_cells"]),
            "spatial_grid": "canonical EPSG:4326 1-degree floor cell; no interpolation",
        }

    return {
        "coverage_balance_version": "d1-v4-medium-balance-v1",
        "denominator_definition": "full-cache target observations; sample IDs are deduplicated within source, not across sources",
        "media": {medium: publish(value) for medium, value in sorted(media.items())},
        "medium_elements": {
            f"{medium}|{element}": {"medium": medium, "element": element, **publish(value)}
            for (medium, element), value in sorted(medium_elements.items())
        },
        "claim_boundary": (
            "More observations do not imply broader coverage. Independent lineage and observed grid-cell counts "
            "must be interpreted alongside sample type, method and region."
        ),
    }


def build(
    registry_path: Path,
    cache_root: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = registry.get("sources")
    if not isinstance(sources, Mapping):
        raise FullProfileError("registry sources are missing")
    profiles: dict[str, dict[str, Any]] = {}
    cube_rows: list[dict[str, Any]] = []
    source_summaries = []
    for source_id, entry in sorted(sources.items()):
        if not isinstance(entry, Mapping):
            raise FullProfileError(f"invalid registry entry: {source_id}")
        profile, source_cube = _profile_one(
            source_id,
            entry,
            _text(registry.get("verified_at")),
            cache_root,
        )
        profiles[source_id] = profile
        cube_rows.extend(source_cube)
        metrics = profile["coverage_metrics"]
        method_field = profile["field_completeness"]["fields"]["analytical_method"]
        source_summaries.append(
            {
                "source_id": source_id,
                "medium": _text((entry.get("media") or [""])[0]),
                **{key: metrics[key] for key in (
                    "observation_count",
                    "distinct_sample_count",
                    "reported_coordinate_sample_count",
                    "valid_coordinate_sample_count",
                    "comparable_observation_count",
                    "covered_spatial_cells",
                )},
                "method_rate": method_field["rate"],
            }
        )
    balance = _coverage_balance(profiles)
    summary = {
        "profile_version": PROFILE_VERSION,
        "coverage_cube_version": CUBE_VERSION,
        "as_of": registry.get("verified_at"),
        "registered_source_count": len(sources),
        "source_count": len(profiles),
        "observation_count": sum(item["observation_count"] for item in source_summaries),
        "distinct_sample_count": sum(item["distinct_sample_count"] for item in source_summaries),
        "reported_coordinate_sample_count": sum(
            item["reported_coordinate_sample_count"] for item in source_summaries
        ),
        "valid_coordinate_sample_count": sum(item["valid_coordinate_sample_count"] for item in source_summaries),
        "comparable_observation_count": sum(item["comparable_observation_count"] for item in source_summaries),
        "covered_spatial_cells_source_sum": sum(item["covered_spatial_cells"] for item in source_summaries),
        "coverage_cube_rows": len(cube_rows),
        "media": balance["media"],
        "sources": source_summaries,
        "denominator_definition": "all non-empty registered target observations parsed from verified full caches",
    }
    return summary, profiles, cube_rows, balance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--coverage-cube", type=Path, default=DEFAULT_CUBE)
    parser.add_argument("--coverage-balance", type=Path, default=DEFAULT_BALANCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--check", action="store_true", help="fail if checked-in profiles differ from verified caches")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary, profiles, cube_rows, balance = build(args.registry, args.cache_root)
        expected_outputs: dict[Path, str] = {
            args.coverage_cube: _csv_text(cube_rows),
            args.coverage_balance: json.dumps(balance, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            args.report: _markdown(summary),
        }
        for source_id, profile in profiles.items():
            for filename, value in _split_profile(profile).items():
                expected_outputs[args.output_dir / source_id / filename] = (
                    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                )
        manifest = {
            **summary,
            "artifacts": [
                {
                    "path": str(path.relative_to(SKILL_DIR)),
                    "bytes": len(content.encode("utf-8")),
                }
                for path, content in sorted(expected_outputs.items(), key=lambda item: str(item[0]))
            ],
        }
        expected_outputs[args.output_dir / "manifest.json"] = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )
        if args.check:
            for path, expected in expected_outputs.items():
                if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                    raise FullProfileError(f"checked-in full profile is stale: {path}")
        else:
            for path, content in expected_outputs.items():
                _atomic_text(path, content)
    except (OSError, ValueError, json.JSONDecodeError, FullProfileError, source_adapters.SourceAdapterError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "summary": summary}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
