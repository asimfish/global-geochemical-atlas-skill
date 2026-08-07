#!/usr/bin/env python3
"""Adapt the core plus expanded real fixtures to the public D1 -> D2 CSV contract."""

from __future__ import annotations

import argparse
import csv
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from build_expanded_fixtures import (
    DEFAULT_FIXTURE_DIR as DEFAULT_EXPANDED_FIXTURE_DIR,
)
from build_expanded_fixtures import (
    SOURCE_CONTRACT as EXPANDED_SOURCE_CONTRACT,
)
from build_expanded_fixtures import (
    verify_fixtures as verify_expanded_fixtures,
)
from build_global_fixtures import (
    DEFAULT_FIXTURE_DIR as DEFAULT_CORE_FIXTURE_DIR,
)
from build_global_fixtures import (
    SOURCE_CONTRACT as CORE_SOURCE_CONTRACT,
)
from build_global_fixtures import (
    verify_fixtures as verify_core_fixtures,
)
from global_d1_adapter import (
    AdapterError,
    base_row,
    common_provenance,
    coverage_matrix,
    read_gemas,
    read_gemstat,
    read_georoc,
    read_ngsa,
    resource_by_id,
    write_csv,
)
from lab_common import atomic_write_json, prepare_empty_output_dir, sha256_file

ADAPTER_VERSION = "d1-expanded-global-real-adapter-v1"
TARGET_ELEMENTS = ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")

AFSIS_ELEMENTS = {
    "As.75": "As",
    "Cr": "Cr",
    "Cu": "Cu",
    "Ni": "Ni",
    "Pb": "Pb",
    "Zn": "Zn",
}
AFSIS_DETECTION_LIMITS = {
    "As": "0.60460311943378309",
    "Cr": "0.4273241689678684",
    "Cu": "2.6558349509814212",
    "Ni": "0.23413278214833627",
    "Pb": "30.625179613915122",
    "Zn": "1.8582896635084745",
}
AFSIS_COUNTRY_CORRECTIONS = {"SAfrica": "South Africa", "Zimbambwe": "Zimbabwe"}

FOREGS_COUNTRIES = {
    "AL": "Albania",
    "AT": "Austria",
    "BE": "Belgium",
    "CH": "Switzerland",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LV": "Latvia",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "SE": "Sweden",
    "SK": "Slovakia",
    "SL": "Slovenia",
    "UK": "United Kingdom",
}

FOREGS_CONFIG = (
    {
        "dataset_id": "foregs_topsoil",
        "resource_id": "foregs_topsoil_archive",
        "material": "FOREGS topsoil",
        "medium": "soil",
        "components": (
            (
                "Topsoil/T_AR_data_2v4_8Feb06.csv",
                {
                    "AS_AR": "As",
                    "CR_AR": "Cr",
                    "CU_AR": "Cu",
                    "NI_AR": "Ni",
                    "PB_AR": "Pb",
                    "ZN_AR": "Zn",
                },
                "aqua_regia",
            ),
            ("Topsoil/T_Hg_data_2v4_8Feb06.csv", {"HG": "Hg"}, "mercury"),
        ),
    },
    {
        "dataset_id": "foregs_subsoil",
        "resource_id": "foregs_subsoil_archive",
        "material": "FOREGS subsoil",
        "medium": "soil",
        "components": (
            (
                "Subsoil/C_AR_data_2v5_8Feb06.csv",
                {
                    "AS_AR_C": "As",
                    "CR_AR_C": "Cr",
                    "CU_AR_C": "Cu",
                    "NI_AR_C": "Ni",
                    "PB_AR_C": "Pb",
                    "ZN_AR_C": "Zn",
                },
                "aqua_regia",
            ),
            ("Subsoil/C_Hg_data_2v4_9Feb06.csv", {"HG_C": "Hg"}, "mercury"),
        ),
    },
    {
        "dataset_id": "foregs_humus",
        "resource_id": "foregs_humus_archive",
        "material": "FOREGS humus organic surface layer",
        "medium": "soil",
        "components": (
            (
                "Humus/H_icp_data_2v2_11Mar04.csv",
                {"NI": "Ni", "CU": "Cu", "ZN": "Zn"},
                "source_icp",
            ),
            ("Humus/H_icpadd_data_2v0.csv", {"PB": "Pb"}, "source_icp"),
            ("Humus/H_Hg_data_2v3_7Aug2007.csv", {"HG": "Hg"}, "mercury"),
        ),
    },
    {
        "dataset_id": "foregs_stream_water",
        "resource_id": "foregs_stream_water_archive",
        "material": "FOREGS stream water",
        "medium": "water",
        "components": (
            (
                "Stream Water/W_all_data_2v8_17Sep07.csv",
                {
                    "AS": "As",
                    "CR": "Cr",
                    "CU": "Cu",
                    "NI": "Ni",
                    "PB": "Pb",
                    "ZN": "Zn",
                },
                "stream_water",
            ),
        ),
    },
    {
        "dataset_id": "foregs_stream_sediment",
        "resource_id": "foregs_stream_sediment_archive",
        "material": "FOREGS stream sediment",
        "medium": "sediment",
        "components": (
            (
                "Stream Sediment/S_AR_data_2v5_30Nov2006.csv",
                {
                    "AS": "As",
                    "CR": "Cr",
                    "CU": "Cu",
                    "NI": "Ni",
                    "PB": "Pb",
                    "ZN": "Zn",
                },
                "aqua_regia",
            ),
            ("Stream Sediment/S_Hg_data_2v5_30Nov06.csv", {"HG": "Hg"}, "mercury"),
        ),
    },
    {
        "dataset_id": "foregs_floodplain_sediment",
        "resource_id": "foregs_floodplain_sediment_archive",
        "material": "FOREGS floodplain sediment",
        "medium": "sediment",
        "components": (
            (
                "Floodplain Sediment/F_AR_data_2v6_7Aug07.csv",
                {
                    "AS": "As",
                    "CR": "Cr",
                    "CU": "Cu",
                    "NI": "Ni",
                    "PB": "Pb",
                    "ZN": "Zn",
                },
                "aqua_regia",
            ),
            ("Floodplain Sediment/F_Hg_data_2v3_7Aug2007.csv", {"HG": "Hg"}, "mercury"),
        ),
    },
)


def dataset_by_id(contract: Mapping[str, Any], dataset_id: str) -> Mapping[str, Any]:
    for dataset in contract.get("datasets", []):
        if dataset.get("id") == dataset_id:
            return dataset
    raise AdapterError(f"dataset missing from expanded source contract: {dataset_id}")


def expanded_verified_path(
    fixture_dir: Path, contract: Mapping[str, Any], resource_id: str
) -> tuple[Path, Mapping[str, Any]]:
    resource = resource_by_id(contract, resource_id)
    path = fixture_dir / str(resource["local_file"])
    if not path.is_file():
        raise AdapterError(f"expanded fixture is missing: {path}")
    if (
        path.stat().st_size != int(resource["bytes"])
        or sha256_file(path) != resource["sha256"]
    ):
        raise AdapterError(f"expanded fixture contract mismatch: {path}")
    return path, resource


def archive_member(resource: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    for member in resource.get("members", []):
        if member.get("path") == path:
            return member
    raise AdapterError(f"archive member missing from contract: {resource['id']}:{path}")


def column_letters(reference: str) -> str:
    match = re.match(r"[A-Z]+", reference)
    if match is None:
        raise AdapterError(f"invalid spreadsheet cell reference: {reference}")
    return match.group(0)


def read_first_xlsx_sheet(path: Path) -> list[tuple[int, dict[str, str]]]:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall(f"{namespace}si"):
                shared.append(
                    "".join(node.text or "" for node in item.iter(f"{namespace}t"))
                )
        worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    physical_rows: list[tuple[int, dict[str, str]]] = []
    for row_node in worksheet.iter(f"{namespace}row"):
        physical_row = int(row_node.attrib.get("r", len(physical_rows) + 1))
        cells: dict[str, str] = {}
        for cell in row_node.findall(f"{namespace}c"):
            column = column_letters(cell.attrib["r"])
            value_node = cell.find(f"{namespace}v")
            value = "" if value_node is None else (value_node.text or "")
            if cell.attrib.get("t") == "s" and value:
                value = shared[int(value)]
            elif cell.attrib.get("t") == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{namespace}t"))
            cells[column] = value.strip()
        physical_rows.append((physical_row, cells))
    if not physical_rows:
        raise AdapterError(f"spreadsheet contains no rows: {path}")
    header_by_column = physical_rows[0][1]
    result: list[tuple[int, dict[str, str]]] = []
    for physical_row, cells in physical_rows[1:]:
        result.append(
            (
                physical_row,
                {
                    header: cells.get(column, "")
                    for column, header in header_by_column.items()
                },
            )
        )
    return result


def read_china(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "tpdc_china_mountain_soil")
    path, resource = expanded_verified_path(
        fixture_dir, contract, "tpdc_china_soil_data"
    )
    for source_row, raw in read_first_xlsx_sheet(path):
        sample_number = raw["Sam.No"]
        horizon = raw["Horizons"]
        sample_key = f"{sample_number}-{horizon}-row{source_row}"
        for element in ("Cr", "Cu", "Ni", "Pb", "Zn"):
            value = raw.get(element, "")
            row = base_row()
            row.update(
                {
                    "record_id": f"tpdc-cn-{sample_key}-{element}",
                    "source_record_id": f"dataset!row={source_row}:{element}",
                    "sample_id": f"tpdc-cn-{sample_key}",
                    "sample_identity_group": f"tpdc-cn-{sample_number}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": value,
                    "unit": "mg/kg",
                    "missing_reason": "not_reported" if not value else "",
                    "medium": "soil",
                    "material": f"mountain soil horizon {horizon}",
                    "measurement_basis": "near_total_HNO3_HF_HClO4_digest",
                    "latitude": raw["Latitude"],
                    "longitude": raw["Longitude"],
                    "source_crs": "geographic decimal degrees; datum not declared in workbook",
                    "coordinate_transform_method": "identity screening assumption to OGC:CRS84; source datum not declared",
                    "grain_fraction": "not reported in workbook",
                    "lithology": raw["Rock Class"],
                    "geologic_unit": raw["Rock Group"],
                    "geologic_unit_id": f"tpdc-cn-parent-rock:{raw['Rock Class']}:{raw['Rock Group']}",
                    "geologic_context_source": "source-reported parent rock class and group",
                    "geologic_context_version": "TPDC v1",
                    "geologic_match_method": "source_reported",
                    "geologic_match_confidence": "unknown",
                    "analytical_method": "HNO3-HF-HClO4 digestion; major elements by ICP-AES and trace elements by ICP-MS; CRM GBW-07405",
                    "method_family": "icp_ms_trace_element",
                    "digestion_or_extraction": "HNO3_HF_HClO4",
                    "reference_material": "GBW-07405",
                    "source_id": "tpdc_china_mountain_soil",
                    "source_file": str(resource["local_file"]),
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.11888/Terre.tpdc.302620#sheet=dataset&row={source_row}&element={element}",
                    "file_sha256": str(resource["sha256"]),
                    "source_tier": "institutional_repository",
                    "benchmark_continent": "Asia",
                    "benchmark_country": "China",
                    "benchmark_region": f"{raw['Mountain']} | site {raw['site']} | horizon {horizon}",
                    **common_provenance(dataset),
                }
            )
            yield row


def read_afsis(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "afsis_phase1_wet_chemistry")
    path, resource = expanded_verified_path(
        fixture_dir, contract, "afsis_wet_chemistry"
    )
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        indexed = [
            (source_row, raw)
            for source_row, raw in enumerate(
                csv.DictReader(handle, delimiter="\t"), start=2
            )
        ]
    grouped: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for source_row, raw in indexed:
        grouped[(raw["Country"].strip(), raw["Depth"].strip())].append(
            (source_row, raw)
        )
    selected: list[tuple[int, dict[str, str]]] = []
    for key in sorted(grouped):
        selected.extend(sorted(grouped[key], key=lambda item: item[1]["SSN"])[:40])
    for source_row, raw in selected:
        ssn = raw["SSN"].strip()
        raw_country = raw["Country"].strip()
        country = AFSIS_COUNTRY_CORRECTIONS.get(raw_country, raw_country)
        depth = raw["Depth"].strip()
        depth_min, depth_max = ("0", "0.2") if depth == "Topsoil" else ("0.2", "0.5")
        for field, element in AFSIS_ELEMENTS.items():
            is_arsenic = element == "As"
            row = base_row()
            row.update(
                {
                    "record_id": f"afsis-{ssn}-{element}",
                    "source_record_id": f"row={source_row}:{field}",
                    "sample_id": f"afsis-{ssn}",
                    "sample_identity_group": f"afsis-{ssn}",
                    "element_or_analyte": element,
                    "analyte_reported": field,
                    "value": raw[field].strip(),
                    "unit": "mg/kg",
                    "medium": "soil",
                    "material": f"AfSIS {depth}",
                    "measurement_basis": "aqua_regia_extractable_dry_matter",
                    "latitude": raw["Latitude"].strip(),
                    "longitude": raw["Longitude"].strip(),
                    "source_crs": "geographic decimal degrees; datum not declared in data table",
                    "coordinate_transform_method": "identity screening assumption to OGC:CRS84; source datum not declared",
                    "sample_depth_min_m": depth_min,
                    "sample_depth_max_m": depth_max,
                    "analytical_method": "Aqua-regia soil digest; Perkin Elmer NexION ICP-MS"
                    if is_arsenic
                    else "Aqua-regia soil digest; Perkin Elmer Optima ICP-OES",
                    "method_family": "icp_ms" if is_arsenic else "icp_oes",
                    "digestion_or_extraction": "aqua_regia",
                    "detection_limit": AFSIS_DETECTION_LIMITS[element],
                    "detection_limit_unit": "mg/kg",
                    "source_id": "afsis_phase1_wet_chemistry",
                    "source_file": str(resource["local_file"]),
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.34725/DVN/66BFOB#row={source_row}&SSN={ssn}&source-country={raw_country}",
                    "file_sha256": str(resource["sha256"]),
                    "source_tier": "institutional_repository",
                    "benchmark_continent": "Africa",
                    "benchmark_country": country,
                    "benchmark_region": f"{raw['Site'].strip()} | cluster {raw['Cluster'].strip()} | plot {raw['Plot'].strip()} | {depth}",
                    **common_provenance(dataset),
                }
            )
            yield row


def normalized_foregs_row(raw: Mapping[str, str]) -> dict[str, str]:
    return {
        str(key).strip().upper(): (value or "").strip()
        for key, value in raw.items()
        if key is not None
    }


def foregs_component_rows(
    data: bytes,
) -> tuple[dict[str, str], dict[str, str], list[tuple[int, dict[str, str]]]]:
    lines = data.decode("cp1252").splitlines()
    if len(lines) < 4:
        raise AdapterError("FOREGS component has fewer than four rows")
    headers = next(csv.reader([lines[0]]))
    units = next(csv.reader([lines[1]]))
    limits = next(csv.reader([lines[2]]))
    unit_by_field = {
        headers[index].strip().upper(): units[index].strip()
        if index < len(units)
        else ""
        for index in range(len(headers))
    }
    limit_by_field = {
        headers[index].strip().upper(): limits[index].strip()
        if index < len(limits)
        else ""
        for index in range(len(headers))
    }
    reader = csv.DictReader(lines[3:], fieldnames=headers)
    rows = [
        (source_row, normalized_foregs_row(raw))
        for source_row, raw in enumerate(reader, start=4)
    ]
    return unit_by_field, limit_by_field, rows


def foregs_method(method_kind: str) -> tuple[str, str, str, str]:
    if method_kind == "aqua_regia":
        return (
            "FOREGS aqua-regia extraction; analytical instrument varies by analyte and is documented in the atlas",
            "foregs_aqua_regia_source_method",
            "aqua_regia",
            "aqua_regia_extractable; upstream below-DL values may already equal DL/2",
        )
    if method_kind == "mercury":
        return (
            "FOREGS mercury source file; instrument detail is in the atlas method documentation, not the CSV",
            "source_atlas_mercury_method",
            "",
            "source_reported_mercury_basis; upstream below-DL values may already equal DL/2",
        )
    if method_kind == "source_icp":
        return (
            "FOREGS ICP source file; detailed instrument and preparation are not repeated in the CSV",
            "source_icp_unspecified_variant",
            "",
            "source_reported_icp_basis; upstream below-DL values may already equal DL/2",
        )
    return (
        "FOREGS harmonized stream-water analytical program; per-analyte method is not exposed in the CSV",
        "source_method_unspecified",
        "",
        "source_reported_stream_water_fraction_unspecified; upstream below-DL values may already equal DL/2",
    )


def read_foregs(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    for config in FOREGS_CONFIG:
        dataset_id = str(config["dataset_id"])
        dataset = dataset_by_id(contract, dataset_id)
        path, resource = expanded_verified_path(
            fixture_dir, contract, str(config["resource_id"])
        )
        parsed_components: list[
            tuple[
                str,
                Mapping[str, str],
                str,
                Mapping[str, str],
                Mapping[str, str],
                list[tuple[int, dict[str, str]]],
            ]
        ] = []
        sites_by_country: dict[str, set[str]] = defaultdict(set)
        with zipfile.ZipFile(path) as archive:
            for member_path, elements, method_kind in config["components"]:
                member = archive_member(resource, member_path)
                data = archive.read(member_path)
                unit_by_field, limit_by_field, rows = foregs_component_rows(data)
                parsed_components.append(
                    (
                        member_path,
                        elements,
                        method_kind,
                        member,
                        unit_by_field,
                        limit_by_field,
                        rows,
                    )
                )
                for _, raw in rows:
                    country_code = raw.get("COUNTRY", "")
                    site_id = raw.get("GTN", "")
                    if country_code and site_id:
                        sites_by_country[country_code].add(site_id)
        selected_sites = {
            site
            for country_code in sorted(sites_by_country)
            for site in sorted(sites_by_country[country_code])[:12]
        }
        for (
            member_path,
            elements,
            method_kind,
            member,
            unit_by_field,
            limit_by_field,
            rows,
        ) in parsed_components:
            analytical_method, method_family, extraction, basis = foregs_method(
                method_kind
            )
            for source_row, raw in rows:
                site_id = raw.get("GTN", "")
                if site_id not in selected_sites:
                    continue
                country_code = raw.get("COUNTRY", "")
                country = FOREGS_COUNTRIES.get(country_code, country_code)
                for source_field, element in elements.items():
                    field = source_field.upper()
                    raw_value = raw.get(field, "")
                    missing = raw_value in {"", "-1", "-1.0"}
                    source_unit = unit_by_field.get(field, "")
                    unit = "ug/L" if str(config["medium"]) == "water" else source_unit
                    row = base_row()
                    row.update(
                        {
                            "record_id": f"{dataset_id}-{site_id}-{element}-row{source_row}",
                            "source_record_id": f"{member_path}:row={source_row}:{field}",
                            "sample_id": f"{dataset_id}-{site_id}",
                            "sample_identity_group": f"foregs-{site_id}-{config['material']}",
                            "element_or_analyte": element,
                            "analyte_reported": source_field,
                            "value": "" if missing else raw_value,
                            "unit": unit,
                            "source_qualifier_raw": "source_missing_sentinel_-1"
                            if missing
                            else "source_dataset_may_encode_below_DL_as_DL_over_2",
                            "missing_reason": "not_reported" if missing else "",
                            "medium": str(config["medium"]),
                            "material": str(config["material"]),
                            "measurement_basis": basis,
                            "latitude": raw.get("LAT", ""),
                            "longitude": raw.get("LONG", ""),
                            "source_crs": "EPSG:4326",
                            "analytical_method": analytical_method,
                            "method_family": method_family,
                            "digestion_or_extraction": extraction,
                            "detection_limit": limit_by_field.get(field, ""),
                            "detection_limit_unit": unit,
                            "source_id": dataset_id,
                            "source_file": member_path,
                            "source_row": str(source_row),
                            "source_locator": f"https://www.globalgeochemicalbaselines.eu/content/47/resultsdatabase-/#archive={resource['local_file']}&member={member_path}&row={source_row}&GTN={site_id}",
                            "file_sha256": str(member["sha256"]),
                            "source_tier": "official_curated",
                            "benchmark_continent": "Europe",
                            "benchmark_country": country,
                            "benchmark_region": f"FOREGS {config['material']} | {country_code}",
                            **common_provenance(dataset),
                        }
                    )
                    yield row


def normalized_numeric_id(value: str) -> str:
    text = value.strip()
    return str(int(text)) if text.isdigit() else text


def with_occurrence(
    rows: Sequence[tuple[int, dict[str, str]]], id_field: str
) -> dict[str, list[tuple[int, dict[str, str]]]]:
    grouped: dict[str, list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for source_row, raw in rows:
        native_id = normalized_numeric_id(raw.get(id_field, ""))
        if native_id:
            grouped[native_id].append((source_row, raw))
    return grouped


def even_indices(size: int, count: int) -> list[int]:
    if size <= count:
        return list(range(size))
    return sorted({round(index * (size - 1) / (count - 1)) for index in range(count)})


def read_gsj(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "gsj_japan_river_sediment")
    sample_path, sample_resource = expanded_verified_path(
        fixture_dir, contract, "gsj_japan_sample_information"
    )
    chemistry_path, chemistry_resource = expanded_verified_path(
        fixture_dir, contract, "gsj_japan_concentrations"
    )
    with sample_path.open("r", encoding="shift_jis", newline="") as handle:
        sample_rows = [
            (row_number, raw)
            for row_number, raw in enumerate(csv.DictReader(handle), start=2)
        ]
    with chemistry_path.open("r", encoding="shift_jis", newline="") as handle:
        chemistry_rows = [
            (row_number, raw)
            for row_number, raw in enumerate(csv.DictReader(handle), start=2)
        ]
    samples = with_occurrence(sample_rows, "試料番号")
    chemistry = with_occurrence(chemistry_rows, "番号2")
    paired: list[tuple[str, int, int, dict[str, str], int, dict[str, str]]] = []
    for native_id in sorted(
        set(samples) & set(chemistry),
        key=lambda value: (
            not value.isdigit(),
            int(value) if value.isdigit() else value,
        ),
    ):
        for occurrence, (sample_item, chemistry_item) in enumerate(
            zip(samples[native_id], chemistry[native_id], strict=True), start=1
        ):
            paired.append(
                (
                    native_id,
                    occurrence,
                    sample_item[0],
                    sample_item[1],
                    chemistry_item[0],
                    chemistry_item[1],
                )
            )
    if len(paired) != 3024:
        raise AdapterError(
            f"GSJ occurrence-aware join expected 3024 samples, found {len(paired)}"
        )
    for selected_index in even_indices(len(paired), 600):
        native_id, occurrence, sample_row, sample, chemistry_row, chemistry_values = (
            paired[selected_index]
        )
        occurrence_key = f"{native_id}-occ{occurrence}"
        for element in TARGET_ELEMENTS:
            unit = "ppb" if element == "Hg" else "ppm"
            value = chemistry_values.get(element, "").strip()
            row = base_row()
            row.update(
                {
                    "record_id": f"gsj-japan-{occurrence_key}-{element}",
                    "source_record_id": f"concentration-row={chemistry_row}:{element}",
                    "sample_id": f"gsj-japan-{occurrence_key}",
                    "sample_identity_group": f"gsj-japan-{occurrence_key}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": value,
                    "unit": unit,
                    "missing_reason": "not_reported" if not value else "",
                    "medium": "sediment",
                    "material": "nationwide river sediment",
                    "measurement_basis": "GSJ published river-sediment concentration; per-analyte digestion is not repeated in the CSV",
                    "latitude": sample["緯度(JGD2000)"].strip(),
                    "longitude": sample["経度(JGD2000)"].strip(),
                    "source_crs": "JGD2000 geographic (EPSG:4612)",
                    "coordinate_transform_method": "identity approximation to OGC:CRS84 for national screening; not a high-accuracy datum transformation",
                    "geologic_unit": sample["地図名"].strip(),
                    "geologic_context_source": "source map-sheet name only; no point geology joined",
                    "geologic_context_version": "GSJ sample information updated 2024-02-20",
                    "geologic_match_method": "source_reported_map_sheet",
                    "geologic_match_confidence": "unknown",
                    "analytical_method": "Geochemical Map of Japan nationwide river-sediment program; element-specific details are documented in the atlas, not repeated in the concentration CSV",
                    "method_family": "source_atlas_method_unspecified_per_row",
                    "source_id": "gsj_japan_river_sediment",
                    "source_file": str(chemistry_resource["local_file"]),
                    "source_row": str(chemistry_row),
                    "source_locator": f"https://gbank.gsj.jp/geochemmap/data/data.htm#sample-id={native_id}&occurrence={occurrence}&sample-row={sample_row}&concentration-row={chemistry_row}&sample-file-sha256={sample_resource['sha256']}",
                    "file_sha256": str(chemistry_resource["sha256"]),
                    "source_tier": "government",
                    "benchmark_continent": "Asia",
                    "benchmark_country": "Japan",
                    "benchmark_region": f"{sample['採取地'].strip()} | {sample['川'].strip()}",
                    **common_provenance(dataset),
                }
            )
            yield row


def pangaea_country(location: str) -> str:
    rules = (
        ("Libya", "Libya"),
        ("Algeria South East", "Algeria"),
        ("Central Algeria", "Algeria"),
        ("Mali Center", "Mali"),
        ("Egypt", "Egypt"),
        ("Chad", "Chad"),
        ("Niger", "Niger"),
        ("Morocco", "Morocco"),
        ("Senegal", "Senegal"),
        ("Mauritania", "Mauritania"),
        ("Tunisia", "Tunisia"),
    )
    for prefix, country in rules:
        if location.startswith(prefix):
            return country
    return ""


def read_pangaea(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "pangaea_north_africa_soils")
    path, resource = expanded_verified_path(
        fixture_dir, contract, "pangaea_north_africa_archive"
    )
    member = archive_member(resource, "datasets/Table_S5.tab")
    with zipfile.ZipFile(path) as archive:
        lines = archive.read("datasets/Table_S5.tab").decode("utf-8").splitlines()
    header_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("Event\tArea\tLocation\tLatitude\tLongitude\t")
    )
    reader = csv.DictReader(lines[header_index:], delimiter="\t")
    element_fields = {
        f"{element} [mg/kg]": element
        for element in ("As", "Cr", "Cu", "Ni", "Pb", "Zn")
    }
    for offset, raw in enumerate(reader, start=1):
        source_row = header_index + 1 + offset
        sample_id = raw["Sample ID"].strip()
        location = raw["Location"].strip()
        for field, element in element_fields.items():
            row = base_row()
            row.update(
                {
                    "record_id": f"pangaea-na-{sample_id}-{element}",
                    "source_record_id": f"Table_S5.tab:row={source_row}:{field}",
                    "sample_id": f"pangaea-na-{sample_id}",
                    "sample_identity_group": f"pangaea-na-{sample_id}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": raw[field].strip(),
                    "unit": "mg/kg",
                    "medium": "soil",
                    "material": "deflatable fine soil fraction",
                    "measurement_basis": "near_total_HF_HNO3_digest_fine_fraction",
                    "latitude": raw["Latitude"].strip(),
                    "longitude": raw["Longitude"].strip(),
                    "source_crs": "geographic decimal degrees; datum not declared in Table S5",
                    "coordinate_transform_method": "identity screening assumption to OGC:CRS84; source datum not declared",
                    "grain_fraction": "<20 µm fine silt-clay fraction",
                    "analytical_method": "HF-HNO3 acid digestion; Agilent 7900 quadrupole ICP-MS with 2.5% HNO3 eluent",
                    "method_family": "icp_ms",
                    "digestion_or_extraction": "HF_HNO3",
                    "reference_material": "BHVO-2; BCR-2 (reported within ±10%)",
                    "source_id": "pangaea_north_africa_soils",
                    "source_file": "datasets/Table_S5.tab",
                    "source_row": str(source_row),
                    "source_locator": f"https://doi.org/10.1594/PANGAEA.949903#Table_S5&row={source_row}&sample={sample_id}",
                    "file_sha256": str(member["sha256"]),
                    "source_tier": "institutional_repository",
                    "benchmark_continent": "Africa",
                    "benchmark_country": pangaea_country(location),
                    "benchmark_region": f"{raw['Area'].strip()} | {location}",
                    **common_provenance(dataset),
                }
            )
            yield row


def run_adapter(
    core_fixture_dir: Path,
    expanded_fixture_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    prepare_empty_output_dir(output_dir)
    verify_core_fixtures(core_fixture_dir)
    verify_expanded_fixtures(expanded_fixture_dir)
    core_contract = json.loads(CORE_SOURCE_CONTRACT.read_text(encoding="utf-8"))
    expanded_contract = json.loads(EXPANDED_SOURCE_CONTRACT.read_text(encoding="utf-8"))
    readers = (
        ("georoc", read_georoc, core_fixture_dir, core_contract),
        ("gemas", read_gemas, core_fixture_dir, core_contract),
        ("ngsa", read_ngsa, core_fixture_dir, core_contract),
        ("gemstat", read_gemstat, core_fixture_dir, core_contract),
        ("china", read_china, expanded_fixture_dir, expanded_contract),
        ("afsis", read_afsis, expanded_fixture_dir, expanded_contract),
        ("foregs", read_foregs, expanded_fixture_dir, expanded_contract),
        ("gsj", read_gsj, expanded_fixture_dir, expanded_contract),
        ("pangaea", read_pangaea, expanded_fixture_dir, expanded_contract),
    )
    rows: list[dict[str, str]] = []
    adapter_counts: dict[str, int] = {}
    for name, reader, fixture_dir, contract in readers:
        selected = list(reader(fixture_dir, contract))
        adapter_counts[name] = len(selected)
        rows.extend(selected)
    if not rows:
        raise AdapterError("expanded global adapters produced no D1 records")
    record_ids = [row["record_id"] for row in rows]
    duplicate_ids = [
        record_id for record_id, count in Counter(record_ids).items() if count > 1
    ]
    if duplicate_ids:
        raise AdapterError(
            f"expanded adapters produced duplicate record ids: {duplicate_ids[:10]}"
        )

    export_path = output_dir / "d1_global_export.csv"
    write_csv(export_path, rows)
    source_counts = Counter(row["source_id"] for row in rows)
    medium_counts = Counter(row["medium"] for row in rows)
    element_counts = Counter(row["element_or_analyte"] for row in rows)
    continent_counts = Counter(row["benchmark_continent"] for row in rows)
    country_counts = Counter(
        row["benchmark_country"] for row in rows if row["benchmark_country"]
    )
    countries_by_source: dict[str, list[str]] = {}
    for source_id in sorted(source_counts):
        countries_by_source[source_id] = sorted(
            {
                row["benchmark_country"]
                for row in rows
                if row["source_id"] == source_id and row["benchmark_country"]
            }
        )
    gemstat_countries = countries_by_source.get("gemstat_global_freshwater_v3", [])
    manifest = {
        "manifest_version": "d1-expanded-global-real-manifest-v1",
        "adapter_version": ADAPTER_VERSION,
        "status": "success",
        "profile": "expanded",
        "scientific_scope": "expanded_global_coverage_benchmark_slice_not_global_population_estimate",
        "record_count": len(rows),
        "source_dataset_count": len(source_counts),
        "adapter_record_counts": adapter_counts,
        "records_by_source": dict(sorted(source_counts.items())),
        "records_by_medium": dict(sorted(medium_counts.items())),
        "records_by_element": dict(sorted(element_counts.items())),
        "records_by_continent": dict(sorted(continent_counts.items())),
        "records_by_explicit_country": dict(sorted(country_counts.items())),
        "coverage_matrix": coverage_matrix(rows),
        "explicit_country_label_count": len(country_counts),
        "explicit_country_labels": sorted(country_counts),
        "countries_by_source": countries_by_source,
        "gemstat_country_count": len(gemstat_countries),
        "gemstat_countries": gemstat_countries,
        "selection_is_value_independent": True,
        "selection_policies": expanded_contract["fixture_build"],
        "declared_blind_spots": expanded_contract["coverage_acceptance"][
            "required_blind_spots"
        ],
        "output": {
            "path": export_path.name,
            "bytes": export_path.stat().st_size,
            "sha256": sha256_file(export_path),
        },
        "interpretation_limits": [
            "Presence in a country is an adapter and visualization coverage check, not evidence of national representativeness.",
            "The benchmark combines total, near-total, aqua-regia-extractable and source-unspecified measurement bases; D2 must keep them separate.",
            "FOREGS below-detection values were replaced upstream by DL/2 and must not be relabeled as exact uncensored observations.",
            "Small-country groups are retained completely only within each selected source; no claim is made that every country has an open target-element survey.",
            "Anomalies remain screening candidates and are not causal claims of contamination or mineralization.",
        ],
    }
    manifest_path = output_dir / "d1_global_manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {"exchange": export_path, "manifest": manifest_path, "summary": manifest}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Adapt core plus expanded frozen real sources to the D2 input CSV."
    )
    parser.add_argument(
        "--core-fixture-dir", type=Path, default=DEFAULT_CORE_FIXTURE_DIR
    )
    parser.add_argument(
        "--expanded-fixture-dir", type=Path, default=DEFAULT_EXPANDED_FIXTURE_DIR
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_adapter(
            args.core_fixture_dir, args.expanded_fixture_dir, args.output_dir
        )
    except (
        AdapterError,
        OSError,
        ValueError,
        csv.Error,
        zipfile.BadZipFile,
        json.JSONDecodeError,
        ET.ParseError,
    ) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": "success",
                "exchange": str(result["exchange"]),
                "manifest": str(result["manifest"]),
                "record_count": result["summary"]["record_count"],
                "source_dataset_count": result["summary"]["source_dataset_count"],
                "explicit_country_label_count": result["summary"][
                    "explicit_country_label_count"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
