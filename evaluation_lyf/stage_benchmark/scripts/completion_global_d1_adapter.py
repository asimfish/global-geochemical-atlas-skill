#!/usr/bin/env python3
"""Build the stage-v2 D1 reference exchange from hash-pinned real sources.

The adapter closes structural continent/medium cells while preserving qualifiers,
method evidence and explicit unknown states. It does not claim globally
representative sampling.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import tempfile
import zipfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from expanded_global_d1_adapter import (
    DEFAULT_CORE_FIXTURE_DIR,
    DEFAULT_EXPANDED_FIXTURE_DIR,
    run_adapter as run_expanded_adapter,
)
from global_d1_adapter import GLOBAL_OUTPUT_FIELDS, base_row, coverage_matrix, write_csv
from lab_common import (
    CONTRACT_ROOT,
    LAB_ROOT,
    atomic_write_json,
    prepare_empty_output_dir,
    sha256_file,
)
from real_d1_adapter import DEFAULT_FIXTURE_DIR as DEFAULT_REAL_FIXTURE_DIR
from real_d1_adapter import adapt_sources as adapt_real_sources

CONTRACT = CONTRACT_ROOT / "completion-sources.json"
DEFAULT_COMPLETION_FIXTURE_DIR = LAB_ROOT / "completion-data" / "fixtures" / "raw"
ADAPTER_VERSION = "d1-stage-completion-v2"
TARGET_ELEMENTS = ("As", "Cr", "Cu", "Ni", "Pb", "Zn")
STATUS_FIELDS = (
    "analytical_method_status",
    "geologic_context_status",
    "coordinate_uncertainty_status",
)


class AdapterError(RuntimeError):
    pass


def resource(contract: Mapping[str, Any], resource_id: str) -> Mapping[str, Any]:
    for item in contract["resources"]:
        if item["id"] == resource_id:
            return item
    raise AdapterError(f"resource not declared: {resource_id}")


def verified_path(root: Path, item: Mapping[str, Any]) -> Path:
    path = root / str(item["local_file"])
    if (
        not path.is_file()
        or path.stat().st_size != int(item["bytes"])
        or sha256_file(path) != item["sha256"]
    ):
        raise AdapterError(f"completion fixture contract mismatch: {path}")
    return path


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def pangaea_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        split = lines.index("*/")
    except ValueError as exc:
        raise AdapterError(
            f"PANGAEA textfile lacks metadata terminator: {path}"
        ) from exc
    return lines[:split], list(csv.DictReader(lines[split + 1 :], delimiter="\t"))


def source_common(item: Mapping[str, Any], title: str) -> dict[str, str]:
    return {
        "source_id": str(item["dataset_id"]),
        "dataset_title": title,
        "dataset_doi": str(item["landing_page"]).removeprefix("https://doi.org/"),
        "dataset_version": str(item["version"]),
        "source_file": str(item["local_file"]),
        "file_sha256": str(item["sha256"]),
        "license": str(item["license"]),
        "source_tier": "official_curated",
    }


def clean_measurement(value: Any) -> tuple[str, str, str, str]:
    text = str(value if value is not None else "").strip().replace(",", ".")
    if not text:
        return "", "", "", "not_reported"
    folded = text.casefold()
    if folded in {"nd", "n.d.", "na", "n.a.", "nan", "-"}:
        return (
            "",
            "nd" if folded.startswith("n") and "d" in folded else "",
            text,
            "not_reported",
        )
    if text[0] in "<>":
        return text[1:].strip(), "lt" if text[0] == "<" else "gt", text[0], ""
    try:
        float(text)
    except ValueError:
        return "", "unknown", text, "invalid_value"
    return text, "", "", ""


def iso_date(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return (
            value.date().isoformat()
            if isinstance(value, datetime)
            else value.isoformat()
        )
    return str(value or "").strip()


def depth_interval_cm(value: Any) -> tuple[str, str]:
    if value is None or str(value).strip() == "":
        return "", ""
    text = str(value).strip()
    if text.casefold() == "surface":
        return "0", "0"
    match = re.fullmatch(r"([0-9.]+)\s*-\s*([0-9.]+)", text)
    if match:
        return str(float(match.group(1)) / 100), str(float(match.group(2)) / 100)
    depth = str(float(text) / 100)
    return depth, depth


def row_resolution_m(latitude: str, longitude: str) -> str:
    """Return coordinate text resolution, explicitly not positional accuracy."""
    try:
        lat_places = len(latitude.partition(".")[2]) if "." in latitude else 0
        lon_places = len(longitude.partition(".")[2]) if "." in longitude else 0
        lat = float(latitude)
    except ValueError:
        return ""
    north = 111_320 * 10 ** (-lat_places)
    east = 111_320 * abs(math.cos(math.radians(lat))) * 10 ** (-lon_places)
    return f"{math.hypot(north, east):.6f}"


def finalize_status(row: dict[str, str]) -> dict[str, str]:
    method = row.get("analytical_method", "").strip()
    partial_markers = (
        "not exposed",
        "not repeated",
        "unspecified",
        "varies by analyte",
    )
    if not row.get("analytical_method_status"):
        if not method:
            row["analytical_method_status"] = "unknown_not_reported_by_source"
        elif any(marker in method.casefold() for marker in partial_markers):
            row["analytical_method_status"] = "dataset_documentation_partial"
        else:
            row["analytical_method_status"] = "source_or_dataset_documented_specific"
    if not row.get("geologic_context_status"):
        has_context = any(
            row.get(field, "").strip()
            for field in (
                "lithology",
                "geologic_unit",
                "geologic_unit_id",
                "geologic_context_source",
            )
        )
        row["geologic_context_status"] = (
            "source_reported" if has_context else "unknown_not_reported_by_source"
        )
    if not row.get("coordinate_uncertainty_status"):
        row["coordinate_uncertainty_status"] = (
            "source_or_metadata_reported"
            if row.get("coordinate_uncertainty_m", "").strip()
            else "unknown_not_reported_by_source"
        )
    if row.get("coordinate_uncertainty_m") and not row.get(
        "coordinate_uncertainty_basis"
    ):
        if row.get("source_id") == "usgs_taylor_mountains_rock":
            row["coordinate_uncertainty_basis"] = (
                "dataset metadata: approximately 20 feet"
            )
        else:
            row["coordinate_uncertainty_basis"] = (
                "source metadata field; see source locator"
            )
    if not row.get("coordinate_resolution_m"):
        row["coordinate_resolution_m"] = row_resolution_m(
            row.get("latitude", ""), row.get("longitude", "")
        )
    if row.get("coordinate_resolution_m") and not row.get(
        "coordinate_resolution_basis"
    ):
        row["coordinate_resolution_basis"] = (
            "derived from displayed decimal precision; not positional accuracy"
        )
    return {field: str(row.get(field, "") or "") for field in GLOBAL_OUTPUT_FIELDS}


def event_positions(metadata: Sequence[str]) -> dict[str, tuple[str, str]]:
    positions: dict[str, tuple[str, str]] = {}
    event_re = re.compile(
        r"^(?:Event\(s\):\s*|\t)(.+?) \* LATITUDE: ([+-]?\d+(?:\.\d+)?) \* LONGITUDE: ([+-]?\d+(?:\.\d+)?)"
    )
    for line in metadata:
        match = event_re.match(line)
        if not match:
            continue
        label, latitude, longitude = match.groups()
        positions[label] = (latitude, longitude)
        positions[label.split(" (", 1)[0]] = (latitude, longitude)
        alias = re.search(r"\((GeoB[^)]+)\)", label)
        if alias:
            positions[alias.group(1)] = (latitude, longitude)
    return positions


def read_africa_sediment(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "africa_sediment")
    metadata, source_rows = pangaea_table(verified_path(root, item))
    positions = event_positions(metadata)
    fields = {element: f"{element} [mg/kg]" for element in ("Cr", "Cu", "Ni", "Zn")}
    common = source_common(
        item, "Inorganic geochemistry of surface sediment samples from southeast Africa"
    )
    for source_row, raw in enumerate(source_rows, start=90):
        event = raw["Event"]
        if event not in positions:
            raise AdapterError(f"no event position for PANGAEA.880617 event {event}")
        latitude, longitude = positions[event]
        for element, field in fields.items():
            value, qualifier, raw_qualifier, missing = clean_measurement(raw[field])
            row = base_row()
            row.update(
                {
                    "record_id": f"pangaea-880617:{event}:row{source_row}:{element}",
                    "source_record_id": f"row={source_row}:{field}",
                    "sample_id": raw["Sample ID"] or event,
                    "sample_identity_group": f"pangaea-880617:{event}:{raw['Sample ID']}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": value,
                    "unit": "mg/kg",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing,
                    "medium": "sediment",
                    "material": "surface river or marine sediment",
                    "measurement_basis": "bulk_elemental_composition",
                    "latitude": latitude,
                    "longitude": longitude,
                    "source_crs": "EPSG:4326",
                    "sample_depth_min_m": raw["Depth sed [m]"],
                    "sample_depth_max_m": raw["Depth sed [m]"],
                    "analytical_method": "bulk sediment X-ray fluorescence (PANalytical Epsilon3-XL); method documented in associated article 10.1029/2017GC007228",
                    "analytical_method_status": "dataset_documented_specific",
                    "method_family": "xrf",
                    "digestion_or_extraction": "none for bulk XRF",
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.1594/PANGAEA.880617#event={event}&field={element}",
                    "benchmark_continent": "Africa",
                    "benchmark_country": "South Africa / Mozambique",
                    "benchmark_region": "southeast African margin and river systems",
                    **common,
                }
            )
            yield row


def read_pangaea_water(
    root: Path, contract: Mapping[str, Any], resource_id: str, continent: str
) -> Iterable[dict[str, str]]:
    item = resource(contract, resource_id)
    _metadata, rows = pangaea_table(verified_path(root, item))
    mapping = {
        "Ni": ("Ni diss [nmol/l] (dNi)", "Std dev [±] (dNi)", "QF (dNi)"),
        "Cu": ("Cu diss [nmol/l] (dCu)", "Std dev [±] (dCu)", "QF (dCu)"),
        "Zn": ("Zn diss [nmol/l] (dZn)", "Std dev [±] (dZn)", "QF (dZn)"),
        "Pb": ("Pb [nmol/l] (dPb)", "Std dev [±] (dPb)", "QF (dPb)"),
    }
    title = "Dissolved trace metals in seawater of the tropical Northeast Atlantic oxygen minimum zone"
    common = source_common(item, title)
    for source_row, raw in enumerate(rows, start=107):
        sample = raw.get("Sample label", "") or raw.get("Event", "")
        for element, (field, std_field, flag_field) in mapping.items():
            value, qualifier, raw_qualifier, missing = clean_measurement(
                raw.get(field, "")
            )
            qf = raw.get(flag_field, "").strip()
            row = base_row()
            row.update(
                {
                    "record_id": f"pangaea-947275:{sample}:{source_row}:{element}",
                    "source_record_id": f"row={source_row}:{field}",
                    "sample_id": sample,
                    "sample_identity_group": f"pangaea-947275:{raw.get('Event', '')}:{sample}",
                    "element_or_analyte": element,
                    "analyte_reported": field,
                    "value": value,
                    "unit": "nmol/L",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": " | ".join(
                        part
                        for part in (raw_qualifier, f"GEOTRACES_QF={qf}" if qf else "")
                        if part
                    ),
                    "missing_reason": missing,
                    "medium": "water",
                    "material": "filtered seawater; dissolved fraction",
                    "measurement_basis": "dissolved_trace_metal",
                    "latitude": raw["Latitude"],
                    "longitude": raw["Longitude"],
                    "source_crs": "EPSG:4326",
                    "sampled_at": raw["Date/Time"],
                    "sample_depth_min_m": raw["Depth water [m]"],
                    "sample_depth_max_m": raw["Depth water [m]"],
                    "measurement_uncertainty": raw.get(std_field, ""),
                    "measurement_uncertainty_unit": "nmol/L (source standard deviation)",
                    "measurement_uncertainty_basis": "source-reported standard deviation",
                    "analytical_method": "preconcentration followed by ICP-MS; dataset-documented dissolved trace-metal method",
                    "analytical_method_status": "dataset_documented_specific",
                    "method_family": "preconcentration_icp_ms",
                    "digestion_or_extraction": "dissolved fraction preconcentration",
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.1594/PANGAEA.947275#row={source_row}&field={element}",
                    "benchmark_continent": continent,
                    "benchmark_country": "international Atlantic waters",
                    "benchmark_region": "tropical Northeast Atlantic",
                    **common,
                }
            )
            yield row


def read_brazil_sediment(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "brazil_sediment")
    path = verified_path(root, item)
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb["Sedimento de corrente"]
    rows = ws.iter_rows(values_only=True)
    headers = [str(value or "") for value in next(rows)]
    common = source_common(
        item, "Geochemical stream-sediment data, Folha Avelino Lopes"
    )
    for source_row, values in enumerate(rows, start=2):
        raw = dict(zip(headers, values, strict=True))
        sample = str(raw["NÚMERO_DE_CAMPO"])
        for element in TARGET_ELEMENTS:
            value, qualifier, raw_qualifier, missing = clean_measurement(
                raw[f"{element}_ppm"]
            )
            row = base_row()
            row.update(
                {
                    "record_id": f"sgb-avelino:{sample}:{element}",
                    "source_record_id": f"row={source_row}:{element}_ppm",
                    "sample_id": sample,
                    "sample_identity_group": f"sgb-avelino:{sample}",
                    "element_or_analyte": element,
                    "analyte_reported": f"{element}_ppm",
                    "value": value,
                    "unit": "ppm",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing,
                    "medium": "sediment",
                    "material": str(raw["CLASSE"]),
                    "measurement_basis": "aqua_regia_extractable",
                    "latitude": str(raw["LATITUDE"]),
                    "longitude": str(raw["LONGITUDE"]),
                    "source_crs": "geographic coordinates; source workbook does not repeat datum",
                    "coordinate_transform_method": "identity screening assumption; source datum not repeated",
                    "sampled_at": iso_date(raw["DATA_DE_ANÁLISE"]),
                    "analytical_method": f"{raw['MÉTODO']}; {raw['ABERTURA']}; {raw['LEITURA']}",
                    "analytical_method_status": "source_reported",
                    "method_family": "icp_ms",
                    "digestion_or_extraction": "aqua_regia",
                    "laboratory": str(raw["LABORATÓRIO"]),
                    "source_row": str(source_row),
                    "source_locator": f"https://rigeo.sgb.gov.br/handle/doc/11268#sheet=Sedimento%20de%20corrente&row={source_row}&field={element}_ppm",
                    "benchmark_continent": "South America",
                    "benchmark_country": "Brazil",
                    "benchmark_region": "Folha Avelino Lopes",
                    **common,
                }
            )
            yield row


def read_brazil_soil(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    chemistry_item = resource(contract, "brazil_soil_chemistry")
    location_item = resource(contract, "brazil_soil_locations")
    archive_path = verified_path(root, chemistry_item)
    location_path = verified_path(root, location_item)
    locations_raw = json.loads(location_path.read_text(encoding="utf-8"))
    locations = {
        f["attributes"]["NUM_CAMPO"].strip(): f for f in locations_raw["features"]
    }
    with zipfile.ZipFile(archive_path) as archive:
        member = next(
            name for name in archive.namelist() if name.endswith("Geoq_Solo.xlsx")
        )
        with tempfile.NamedTemporaryFile(suffix=".xlsx") as handle:
            handle.write(archive.read(member))
            handle.flush()
            wb = load_workbook(handle.name, read_only=True, data_only=True)
            ws = wb["Analise_Solo"]
            rows = ws.iter_rows(values_only=True)
            headers = [str(value or "") for value in next(rows)]
            chemistry_rows = [
                (source_row, dict(zip(headers, values, strict=True)))
                for source_row, values in enumerate(rows, start=2)
            ]
    common = source_common(chemistry_item, "Área L - BE soil geochemistry")
    for source_row, raw in chemistry_rows:
        sample = str(raw["num_campo"]).strip()
        feature = locations.get(sample)
        if feature is None:
            raise AdapterError(f"SGB soil location join failed for {sample}")
        attrs, geometry = feature["attributes"], feature["geometry"]
        for element in TARGET_ELEMENTS:
            value, qualifier, raw_qualifier, missing = clean_measurement(
                raw[f"{element}_ppm"]
            )
            row = base_row()
            row.update(
                {
                    "record_id": f"sgb-area-l-be:{sample}:{element}",
                    "source_record_id": f"{member}:row={source_row}:{element}_ppm",
                    "sample_id": sample,
                    "sample_identity_group": f"sgb-area-l-be:{sample}",
                    "element_or_analyte": element,
                    "analyte_reported": f"{element}_ppm",
                    "value": value,
                    "unit": "ppm",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing,
                    "medium": "soil",
                    "material": str(raw["classe"]),
                    "measurement_basis": "direct_solid_emission_spectrography",
                    "latitude": str(geometry["y"]),
                    "longitude": str(geometry["x"]),
                    "source_crs": "EPSG:4326",
                    "coordinate_transform_method": "official SGB FeatureServer point joined on NUM_CAMPO",
                    "sampled_at": iso_date(raw["data_visita"]),
                    "lithology": str(attrs.get("DESCROCHA") or "").strip(),
                    "geologic_unit": str(attrs.get("ROCHMATRIZ") or "").strip(),
                    "geologic_context_source": str(location_item["landing_page"]),
                    "geologic_context_version": str(location_item["version"]),
                    "geologic_match_method": "official_feature_attribute_join_by_sample_id",
                    "analytical_method": str(raw["leitura"]),
                    "analytical_method_status": "source_reported",
                    "method_family": "emission_spectrography",
                    "digestion_or_extraction": str(
                        raw["abertura"]
                        or "none reported; solid optical emission method"
                    ),
                    "source_row": str(source_row),
                    "source_locator": f"https://rigeo.sgb.gov.br/handle/doc/11157#member={member}&row={source_row}&NUM_CAMPO={sample}&field={element}_ppm",
                    "benchmark_continent": "South America",
                    "benchmark_country": "Brazil",
                    "benchmark_region": "Área L - BE",
                    **common,
                }
            )
            yield row


def read_australia_water(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "australia_water")
    path = verified_path(root, item)
    # Normal mode makes repeated access to the seven-row metadata header O(1).
    # Read-only ``ws.cell`` reparses the XML for every call and is quadratic here.
    wb = load_workbook(path, read_only=False, data_only=True)
    common = source_common(
        item, "Northern Australia Hydrogeochemical Survey final data release"
    )
    for ws in wb.worksheets:
        if ws.title == "Abbreviations and Acronyms":
            continue
        analytes = {
            str(ws.cell(1, col).value): col
            for col in range(29, ws.max_column + 1)
            if ws.cell(1, col).value
        }
        for source_row in range(8, ws.max_row + 1):
            sample = str(ws.cell(source_row, 1).value or "").strip()
            if not sample:
                continue
            latitude, longitude = (
                str(ws.cell(source_row, 3).value),
                str(ws.cell(source_row, 2).value),
            )
            for element in (*TARGET_ELEMENTS, "Hg"):
                col = analytes[element]
                value, qualifier, raw_qualifier, missing = clean_measurement(
                    ws.cell(source_row, col).value
                )
                filtration = ws.cell(7, col).value
                row = base_row()
                row.update(
                    {
                        "record_id": f"ga-133388:{sample}:{element}",
                        "source_record_id": f"sheet={ws.title}:row={source_row}:column={col}",
                        "sample_id": sample,
                        "sample_identity_group": f"ga-133388:{sample}",
                        "element_or_analyte": element,
                        "analyte_reported": element,
                        "value": value,
                        "unit": str(ws.cell(3, col).value),
                        "value_qualifier": qualifier,
                        "source_qualifier_raw": raw_qualifier,
                        "missing_reason": missing,
                        "medium": "water",
                        "material": f"groundwater; filtration={filtration}",
                        "measurement_basis": "dissolved_0.45um"
                        if filtration == 0.45
                        else "source_reported_unfiltered",
                        "latitude": latitude,
                        "longitude": longitude,
                        "source_crs": str(ws.cell(source_row, 4).value),
                        "sampled_at": iso_date(ws.cell(source_row, 25).value),
                        "sample_depth_min_m": str(ws.cell(source_row, 18).value or ""),
                        "sample_depth_max_m": str(ws.cell(source_row, 19).value or ""),
                        "analytical_method": str(ws.cell(5, col).value),
                        "analytical_method_status": "source_reported",
                        "method_family": "icp_ms"
                        if str(ws.cell(5, col).value).upper() == "ICP-MS"
                        else "sorbent_collection",
                        "digestion_or_extraction": f"filtration={filtration}",
                        "laboratory": str(ws.cell(4, col).value),
                        "detection_limit": str(ws.cell(6, col).value or ""),
                        "detection_limit_unit": str(ws.cell(3, col).value),
                        "source_row": str(source_row),
                        "source_locator": f"https://doi.org/10.11636/Record.2020.015#sheet={ws.title}&row={source_row}&element={element}",
                        "benchmark_continent": "Oceania",
                        "benchmark_country": "Australia",
                        "benchmark_region": ws.title.replace("_", " "),
                        **common,
                    }
                )
                yield row


def read_oceania_soil(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "oceania_soil")
    _metadata, rows = pangaea_table(verified_path(root, item))
    common = source_common(
        item, "Geochemistry of soil, sediment and street dust in Western Australia"
    )
    for source_row, raw in enumerate(rows, start=148):
        if raw["Samp type"] != "Soil":
            continue
        for element in TARGET_ELEMENTS:
            field = next(
                field for field in raw if field.startswith(f"{element} [mg/kg]")
            )
            value, qualifier, raw_qualifier, missing = clean_measurement(raw[field])
            sample = raw["Sample ID"]
            row = base_row()
            row.update(
                {
                    "record_id": f"pangaea-935591:{raw['Event']}:row{source_row}:{element}",
                    "source_record_id": f"row={source_row}:{field}",
                    "sample_id": sample,
                    "sample_identity_group": f"pangaea-935591:{sample}",
                    "element_or_analyte": element,
                    "analyte_reported": field,
                    "value": value,
                    "unit": "mg/kg",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing,
                    "medium": "soil",
                    "material": "surface soil",
                    "measurement_basis": "aqua_regia_extractable",
                    "latitude": raw["Latitude"],
                    "longitude": raw["Longitude"],
                    "source_crs": "WGS84 (source provides UTM and geographic coordinates)",
                    "sample_depth_min_m": raw["Depth sed [m] (Min)"],
                    "sample_depth_max_m": raw["Depth sed [m] (Max)"],
                    "analytical_method": "concentrated HNO3-HCl aqua-regia digestion followed by ICP-OES",
                    "analytical_method_status": "dataset_documented_specific",
                    "method_family": "icp_oes",
                    "digestion_or_extraction": "aqua_regia",
                    "reference_material": "dataset-reported standard reference material",
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.1594/PANGAEA.935591#row={source_row}&field={element}",
                    "benchmark_continent": "Oceania",
                    "benchmark_country": "Australia",
                    "benchmark_region": raw["Location"],
                    **common,
                }
            )
            yield row


def read_antarctica_soil(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "antarctica_soil")
    _metadata, rows = pangaea_table(verified_path(root, item))
    fields = {
        "Ca": "Ca2+ [mg/kg]",
        "Mg": "Mg2+ [mg/kg]",
        "Na": "Na [mg/kg]",
        "K": "K [mg/kg]",
    }
    common = source_common(item, "Chemical properties of Antarctic soils")
    for source_row, raw in enumerate(rows, start=34):
        sample = f"{raw['Event']}:{raw['Profile ID']}:{raw['Soil hori']}"
        for element, field in fields.items():
            value, qualifier, raw_qualifier, missing = clean_measurement(raw[field])
            row = base_row()
            row.update(
                {
                    "record_id": f"pangaea-816759:{sample}:{element}",
                    "source_record_id": f"row={source_row}:{field}",
                    "sample_id": sample,
                    "sample_identity_group": f"pangaea-816759:{sample}",
                    "element_or_analyte": element,
                    "analyte_reported": field,
                    "value": value,
                    "unit": "mg/kg",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing,
                    "medium": "soil",
                    "material": f"soil horizon {raw['Soil hori']}",
                    "measurement_basis": "one_to_five_soil_water_extract",
                    "latitude": raw["Latitude"],
                    "longitude": raw["Longitude"],
                    "source_crs": "EPSG:4326",
                    "sample_depth_min_m": raw["Depth top [m]"],
                    "sample_depth_max_m": raw["Depth bot [m]"],
                    "analytical_method": "1:5 soil-water extract; Ca, Mg, Na and K measured by flame atomic absorption spectrometry",
                    "analytical_method_status": "dataset_documented_specific",
                    "method_family": "flame_aas",
                    "digestion_or_extraction": "1:5 soil-water extraction",
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.1594/PANGAEA.816759#row={source_row}&field={element}",
                    "benchmark_continent": "Antarctica",
                    "benchmark_country": "Antarctica",
                    "benchmark_region": raw["Event"],
                    **common,
                }
            )
            yield row


def read_antarctica_sediment(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "antarctica_sediment")
    wb = load_workbook(verified_path(root, item), read_only=True, data_only=True)
    ws = wb["Appendix Table 1"]
    headers = [str(ws.cell(4, col).value or "") for col in range(1, ws.max_column + 1)]
    common = source_common(item, "West Antarctic sediment geochemistry compilation")
    for source_row, values in enumerate(
        ws.iter_rows(min_row=5, values_only=True), start=5
    ):
        raw = dict(zip(headers, values, strict=True))
        if raw["Number"] is None:
            continue
        sample = str(raw["Site"])
        depth_min, depth_max = depth_interval_cm(raw["Core depth [cm]"])
        for element in ("Cr", "Ni", "Cu", "Zn"):
            value, qualifier, raw_qualifier, missing = clean_measurement(raw[element])
            row = base_row()
            row.update(
                {
                    "record_id": f"mendeley-cfnhps54h7:{raw['Number']}:{element}",
                    "source_record_id": f"Appendix Table 1:row={source_row}:{element}",
                    "sample_id": sample,
                    "sample_identity_group": f"mendeley-cfnhps54h7:{raw['Number']}:{sample}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": value,
                    "unit": "mg/kg",
                    "value_qualifier": qualifier,
                    "source_qualifier_raw": raw_qualifier,
                    "missing_reason": missing,
                    "medium": "sediment",
                    "material": "marine sediment <63 µm fine fraction",
                    "measurement_basis": "leached_fine_fraction_total_digest",
                    "latitude": str(raw["Latitude"]),
                    "longitude": str(raw["Longitude"]),
                    "source_crs": "geographic coordinates; datum not repeated in workbook",
                    "coordinate_transform_method": "identity screening assumption; source datum not repeated",
                    "sample_depth_min_m": depth_min,
                    "sample_depth_max_m": depth_max,
                    "grain_fraction": "<63 µm",
                    "analytical_method": "<63 µm fraction leached, digested, and analyzed by Agilent 8800 ICP-QQQ; associated article 10.1016/j.chemgeo.2020.119649",
                    "analytical_method_status": "dataset_documented_specific",
                    "method_family": "icp_qqq_ms",
                    "digestion_or_extraction": "leaching followed by total digestion",
                    "measurement_uncertainty_basis": "associated article reports trace-element precision <5% and accuracy <10%; not converted to per-record uncertainty",
                    "source_row": str(source_row),
                    "source_locator": f"https://data.mendeley.com/datasets/cfnhps54h7/1#AppendixTable1&row={source_row}&element={element}",
                    "benchmark_continent": "Antarctica",
                    "benchmark_country": "Antarctica",
                    "benchmark_region": str(raw["Geographical area"]),
                    **common,
                }
            )
            yield row


def read_antarctica_water(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    item = resource(contract, "antarctica_water")
    path = verified_path(root, item)
    common = source_common(
        item, "Total dissolved trace metals in Amundsen and Ross Sea waters"
    )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for source_row, raw in enumerate(csv.DictReader(handle), start=2):
            for element in ("Ni", "Cu", "Zn"):
                field, flag_field = (
                    f"{element}_D_CONC_BOTTLE",
                    f"{element}_D_CONC_BOTTLE_FLAG",
                )
                value, qualifier, raw_qualifier, missing = clean_measurement(raw[field])
                sample = raw["Bottle"]
                row = base_row()
                row.update(
                    {
                        "record_id": f"bco-dmo-877466:{sample}:{element}",
                        "source_record_id": f"row={source_row}:{field}",
                        "sample_id": sample,
                        "sample_identity_group": f"bco-dmo-877466:{raw['Station']}:{sample}",
                        "element_or_analyte": element,
                        "analyte_reported": field,
                        "value": value,
                        "unit": "nmol/L",
                        "value_qualifier": qualifier,
                        "source_qualifier_raw": " | ".join(
                            part
                            for part in (
                                raw_qualifier,
                                f"GEOTRACES_QF={raw[flag_field]}"
                                if raw[flag_field]
                                else "",
                            )
                            if part
                        ),
                        "missing_reason": missing,
                        "medium": "water",
                        "material": "seawater; total dissolved metal",
                        "measurement_basis": "total_dissolved_trace_metal",
                        "latitude": raw["Lat_deg_N"],
                        "longitude": raw["Lon_deg_E"],
                        "source_crs": "EPSG:4326",
                        "sampled_at": raw["Collection_datetime"],
                        "sample_depth_min_m": raw["Depth_m"],
                        "sample_depth_max_m": raw["Depth_m"],
                        "analytical_method": "isotope dilution with seaFAST preconcentration and iCAP-Q ICP-MS; GEOTRACES quality flags retained",
                        "analytical_method_status": "dataset_documented_specific",
                        "method_family": "seafast_icp_ms_isotope_dilution",
                        "digestion_or_extraction": "seaFAST preconcentration",
                        "source_row": str(source_row),
                        "source_locator": f"https://www.bco-dmo.org/dataset/877466#row={source_row}&field={element}",
                        "benchmark_continent": "Antarctica",
                        "benchmark_country": "Antarctica",
                        "benchmark_region": "Amundsen and Ross Seas",
                        **common,
                    }
                )
                yield row


def completion_readers(
    root: Path, contract: Mapping[str, Any]
) -> Iterable[tuple[str, Iterable[dict[str, str]]]]:
    return (
        ("africa_sediment", read_africa_sediment(root, contract)),
        ("africa_water", read_pangaea_water(root, contract, "africa_water", "Africa")),
        ("brazil_sediment", read_brazil_sediment(root, contract)),
        ("brazil_soil", read_brazil_soil(root, contract)),
        ("australia_water", read_australia_water(root, contract)),
        ("oceania_soil", read_oceania_soil(root, contract)),
        ("antarctica_soil", read_antarctica_soil(root, contract)),
        ("antarctica_sediment", read_antarctica_sediment(root, contract)),
        ("antarctica_water", read_antarctica_water(root, contract)),
    )


def status_metrics(rows: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    count = len(rows)
    method_specific = sum(
        row["analytical_method_status"]
        in {
            "source_reported",
            "dataset_documented_specific",
            "source_or_dataset_documented_specific",
        }
        for row in rows
    )
    geology_source = sum(
        row["geologic_context_status"] == "source_reported" for row in rows
    )
    uncertainty_numeric = sum(bool(row["coordinate_uncertainty_m"]) for row in rows)
    resolution_numeric = sum(bool(row["coordinate_resolution_m"]) for row in rows)
    return {
        "analytical_method_nonblank_coverage": round(
            sum(bool(row["analytical_method"]) for row in rows) / count, 6
        ),
        "analytical_method_specific_value_coverage": round(method_specific / count, 6),
        "source_geologic_context_value_coverage": round(geology_source / count, 6),
        "coordinate_uncertainty_numeric_coverage": round(
            uncertainty_numeric / count, 6
        ),
        "coordinate_resolution_numeric_coverage": round(resolution_numeric / count, 6),
        "explicit_status_coverage": {
            field: round(sum(bool(row[field]) for row in rows) / count, 6)
            for field in STATUS_FIELDS
        },
    }


def run_adapter(
    core_fixture_dir: Path,
    expanded_fixture_dir: Path,
    real_fixture_dir: Path,
    completion_fixture_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    prepare_empty_output_dir(output_dir)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    manifest_path = completion_fixture_dir / "source_manifest.json"
    if not manifest_path.is_file():
        raise AdapterError(
            "completion source_manifest.json missing; run build_completion_fixtures.py"
        )
    with tempfile.TemporaryDirectory() as temporary_name:
        temporary = Path(temporary_name)
        expanded = run_expanded_adapter(
            core_fixture_dir, expanded_fixture_dir, temporary / "expanded"
        )
        real = adapt_real_sources(real_fixture_dir, temporary / "real", 0)
        rows = read_csv_rows(expanded["exchange"])
        real_rows = read_csv_rows(real["export"])
    for row in real_rows:
        row.update(
            {
                "benchmark_continent": "Antarctica"
                if row["source_id"] == "usgs_taylor_mountains_rock"
                else "North America",
                "benchmark_country": "Antarctica"
                if row["source_id"] == "usgs_taylor_mountains_rock"
                else "United States",
                "benchmark_region": row["source_id"],
            }
        )
    rows.extend(real_rows)
    adapter_counts: dict[str, int] = {
        "expanded_reference": len(rows) - len(real_rows),
        "north_america_real": len(real_rows),
    }
    for name, generated in completion_readers(completion_fixture_dir, contract):
        selected = list(generated)
        adapter_counts[name] = len(selected)
        rows.extend(selected)
    finalized = [finalize_status(dict(row)) for row in rows]
    ids = Counter(row["record_id"] for row in finalized)
    duplicates = [key for key, value in ids.items() if value > 1]
    if duplicates:
        raise AdapterError(f"duplicate record IDs: {duplicates[:10]}")
    matrix = coverage_matrix(finalized)
    continents = (
        "Africa",
        "Antarctica",
        "Asia",
        "Europe",
        "North America",
        "Oceania",
        "South America",
    )
    media = ("rock", "soil", "sediment", "water")
    nonempty = sum(
        matrix.get(continent, {}).get(medium, 0) > 0
        for continent in continents
        for medium in media
    )
    if nonempty != 28:
        raise AdapterError(
            f"structural continent-medium coverage is {nonempty}/28, expected 28/28"
        )
    export = output_dir / "d1_completion_export.csv"
    write_csv(export, finalized)
    source_counts = Counter(row["source_id"] for row in finalized)
    water_continents = sorted(
        {row["benchmark_continent"] for row in finalized if row["medium"] == "water"}
    )
    summary = {
        "manifest_version": "d1-stage-completion-manifest-v2",
        "adapter_version": ADAPTER_VERSION,
        "status": "success",
        "scientific_scope": "structural_stage_benchmark_not_global_population_estimate",
        "record_count": len(finalized),
        "source_dataset_count": len(source_counts),
        "adapter_record_counts": adapter_counts,
        "records_by_source": dict(sorted(source_counts.items())),
        "coverage_matrix": matrix,
        "nonempty_continent_medium_cells": nonempty,
        "water_continent_coverage": water_continents,
        "water_continent_count": len(water_continents),
        "field_coverage": status_metrics(finalized),
        "completion_contract_sha256": sha256_file(CONTRACT),
        "fixture_manifest_sha256": sha256_file(manifest_path),
        "output": {
            "path": export.name,
            "bytes": export.stat().st_size,
            "sha256": sha256_file(export),
        },
        "interpretation_limits": contract["scientific_limits"],
    }
    manifest = output_dir / "d1_completion_manifest.json"
    atomic_write_json(manifest, summary)
    return {"exchange": export, "manifest": manifest, "summary": summary}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--core-fixture-dir", type=Path, default=DEFAULT_CORE_FIXTURE_DIR
    )
    parser.add_argument(
        "--expanded-fixture-dir", type=Path, default=DEFAULT_EXPANDED_FIXTURE_DIR
    )
    parser.add_argument(
        "--real-fixture-dir", type=Path, default=DEFAULT_REAL_FIXTURE_DIR
    )
    parser.add_argument(
        "--completion-fixture-dir", type=Path, default=DEFAULT_COMPLETION_FIXTURE_DIR
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_adapter(
            args.core_fixture_dir,
            args.expanded_fixture_dir,
            args.real_fixture_dir,
            args.completion_fixture_dir,
            args.output_dir,
        )
    except (
        AdapterError,
        OSError,
        ValueError,
        KeyError,
        csv.Error,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
