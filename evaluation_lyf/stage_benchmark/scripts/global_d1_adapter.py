#!/usr/bin/env python3
"""Adapt the frozen global real-data fixture to the public D1 -> D2 CSV contract."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from build_global_fixtures import DEFAULT_FIXTURE_DIR, SOURCE_CONTRACT, verify_fixtures
from lab_common import atomic_write_json, prepare_empty_output_dir, sha256_file
from real_d1_adapter import OUTPUT_FIELDS as D2_INPUT_FIELDS

ADAPTER_VERSION = "d1-global-real-adapter-v1"
GLOBAL_OUTPUT_FIELDS = (
    *D2_INPUT_FIELDS,
    "replicate_group_id",
    "reference_material",
    "benchmark_continent",
    "benchmark_country",
    "benchmark_region",
)

GEOROC_ELEMENTS = {
    "as_ppm": "As",
    "cr_ppm": "Cr",
    "cu_ppm": "Cu",
    "ni_ppm": "Ni",
    "pb_ppm": "Pb",
    "zn_ppm": "Zn",
}
GEMAS_ELEMENTS = {"AS_": "As", "CU": "Cu", "PB": "Pb", "ZN": "Zn"}

GEMSTAT_CONTINENTS = {
    "Argentina": "South America",
    "Austria": "Europe",
    "Belgium": "Europe",
    "Bosnia and Herzegovina": "Europe",
    "Bulgaria": "Europe",
    "Canada": "North America",
    "Croatia": "Europe",
    "Cyprus": "Asia",
    "Czechia": "Europe",
    "Denmark": "Europe",
    "Estonia": "Europe",
    "Finland": "Europe",
    "France": "Europe",
    "Germany": "Europe",
    "Greece": "Europe",
    "Hungary": "Europe",
    "Iceland": "Europe",
    "India": "Asia",
    "Ireland": "Europe",
    "Italy": "Europe",
    "Latvia": "Europe",
    "Liechtenstein": "Europe",
    "Lithuania": "Europe",
    "Luxembourg": "Europe",
    "Macedonia (the former Yugoslav Republic of)": "Europe",
    "Malta": "Europe",
    "Mexico": "North America",
    "Montenegro": "Europe",
    "Netherlands (-the )": "Europe",
    "Norway": "Europe",
    "Poland": "Europe",
    "Portugal": "Europe",
    "Romania": "Europe",
    "Serbia": "Europe",
    "Slovakia": "Europe",
    "Slovenia": "Europe",
    "Spain": "Europe",
    "Sweden": "Europe",
    "Switzerland": "Europe",
    "Turkey": "Asia",
    "United States of America (the)": "North America",
    "Uruguay": "South America",
}


class AdapterError(RuntimeError):
    """Raised when a frozen source cannot be mapped without unsupported guessing."""


def dataset_by_id(contract: Mapping[str, Any], dataset_id: str) -> Mapping[str, Any]:
    for dataset in contract.get("datasets", []):
        if dataset.get("id") == dataset_id:
            return dataset
    raise AdapterError(f"dataset missing from global source contract: {dataset_id}")


def resource_by_id(contract: Mapping[str, Any], resource_id: str) -> Mapping[str, Any]:
    for resource in contract.get("resources", []):
        if resource.get("id") == resource_id:
            return resource
    raise AdapterError(f"resource missing from global source contract: {resource_id}")


def verified_path(fixture_dir: Path, resource: Mapping[str, Any]) -> Path:
    path = fixture_dir / str(resource["local_file"])
    if not path.is_file():
        raise AdapterError(f"global fixture is missing: {path}")
    if (
        path.stat().st_size != int(resource["bytes"])
        or sha256_file(path) != resource["sha256"]
    ):
        raise AdapterError(f"global fixture contract mismatch: {path}")
    return path


def clean_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"-?\d+\.0", text):
        return text[:-2]
    return text


def midpoint(minimum: str, maximum: str) -> float:
    return (float(minimum) + float(maximum)) / 2


def coordinate_uncertainty(row: Mapping[str, str]) -> str:
    lat_min = float(row["latitude_min"])
    lat_max = float(row["latitude_max"])
    lon_min = float(row["longitude_min"])
    lon_max = float(row["longitude_max"])
    if lat_min == lat_max and lon_min == lon_max:
        return ""
    latitude = (lat_min + lat_max) / 2
    north_south = abs(lat_max - lat_min) * 111_320 / 2
    east_west = (
        abs(lon_max - lon_min) * 111_320 * abs(math.cos(math.radians(latitude))) / 2
    )
    return f"{math.hypot(north_south, east_west):.6f}"


def base_row() -> dict[str, str]:
    return dict.fromkeys(GLOBAL_OUTPUT_FIELDS, "")


def common_provenance(dataset: Mapping[str, Any]) -> dict[str, str]:
    identifier = str(dataset["persistent_identifier"])
    return {
        "dataset_title": str(dataset["title"]),
        "dataset_doi": identifier.removeprefix("doi:"),
        "dataset_version": str(dataset["version"]),
        "license": str(dataset["license"]),
    }


def read_georoc(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    resource = resource_by_id(contract, "georoc_global_rocks_slice")
    path = verified_path(fixture_dir, resource)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for derivative_row, raw in enumerate(csv.DictReader(handle), start=2):
            is_antarctica = raw["continent"] == "Antarctica"
            dataset_id = (
                "georoc_antarctica_intraplate"
                if is_antarctica
                else "georoc_archaean_cratons"
            )
            dataset = dataset_by_id(contract, dataset_id)
            dataset_pid = str(dataset["persistent_identifier"]).removeprefix("doi:")
            latitude = midpoint(raw["latitude_min"], raw["latitude_max"])
            longitude = midpoint(raw["longitude_min"], raw["longitude_max"])
            for field, element in GEOROC_ELEMENTS.items():
                value = raw.get(field, "").strip()
                if not value:
                    continue
                row = base_row()
                source_record_id = f"{raw['unique_id']}:{element}"
                row.update(
                    {
                        "record_id": f"georoc-{dataset_id}-{source_record_id}",
                        "source_record_id": source_record_id,
                        "sample_id": f"georoc-{raw['unique_id']}",
                        "sample_identity_group": f"georoc-{raw['unique_id']}",
                        "element_or_analyte": element,
                        "analyte_reported": element,
                        "value": value,
                        "unit": "ppm",
                        "medium": "rock",
                        "material": raw["material"] or "rock",
                        "measurement_basis": "GEOROC precompiled selected published value; analytical basis varies by citation",
                        "latitude": f"{latitude:.8f}",
                        "longitude": f"{longitude:.8f}",
                        "source_crs": "GEOROC geographic decimal degrees; geodetic datum not declared",
                        "coordinate_transform_method": (
                            "midpoint of published coordinate bounds; identity screening assumption to OGC:CRS84; "
                            "source datum not declared"
                        ),
                        "coordinate_uncertainty_m": coordinate_uncertainty(raw),
                        "lithology": raw["rock_name"],
                        "geologic_unit": raw["region"],
                        "geologic_unit_id": f"{dataset_pid}:{raw['region']}",
                        "geologic_context_source": "GEOROC source-reported tectonic setting and location",
                        "geologic_context_version": "precompiled-2026-06",
                        "geologic_match_method": "source_reported",
                        "geologic_match_confidence": "unknown",
                        "source_id": dataset_id,
                        "source_file": raw["parent_file"],
                        "source_row": raw["parent_row"],
                        "source_locator": (
                            f"https://doi.org/{raw['parent_persistent_id'].removeprefix('doi:')}"
                            f"#row={raw['parent_row']}&unique_id={raw['unique_id']}"
                        ),
                        "file_sha256": raw["parent_sha256"],
                        "source_tier": "institutional_repository",
                        "benchmark_continent": raw["continent"],
                        "benchmark_region": raw["region"],
                        **common_provenance(dataset),
                    }
                )
                yield row


def read_gemas(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "gemas_europe_soil")
    resource = resource_by_id(contract, "gemas_europe_soil")
    path = verified_path(fixture_dir, resource)
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = sorted(
        payload.get("features", []),
        key=lambda item: int(item["properties"]["OBJECTID"]),
    )
    for feature in features:
        properties = feature["properties"]
        object_id = clean_identifier(properties.get("OBJECTID"))
        sample_id = clean_identifier(properties.get("ID")) or object_id
        coordinates = feature.get("geometry", {}).get("coordinates", [])
        if len(coordinates) != 2:
            coordinates = [properties.get("XCOO", ""), properties.get("YCOO", "")]
        country = clean_identifier(properties.get("COUNTRY"))
        for field, element in GEMAS_ELEMENTS.items():
            value = properties.get(field)
            row = base_row()
            row.update(
                {
                    "record_id": f"gemas-{sample_id}-{element}",
                    "source_record_id": f"OBJECTID={object_id}:{element}",
                    "sample_id": f"gemas-{sample_id}",
                    "sample_identity_group": f"gemas-{sample_id}",
                    "element_or_analyte": element,
                    "analyte_reported": element,
                    "value": "" if value is None else str(value),
                    "unit": "mg/kg",
                    "missing_reason": "not_reported" if value is None else "",
                    "medium": "soil",
                    "material": "agricultural land soil",
                    "measurement_basis": "aqua_regia_extractable",
                    "latitude": str(coordinates[1]),
                    "longitude": str(coordinates[0]),
                    "source_crs": "EPSG:4326",
                    "sample_depth_min_m": "0",
                    "sample_depth_max_m": "0.2",
                    "grain_fraction": "source service does not expose grain fraction",
                    "lithology": clean_identifier(properties.get("SOILTYPE")),
                    "analytical_method": "Aqua regia extraction; analytical instrument not exposed by ArcGIS record",
                    "method_family": "source_instrument_unspecified",
                    "digestion_or_extraction": "aqua_regia",
                    "laboratory": "single GEMAS laboratory; name not exposed by ArcGIS record",
                    "source_id": "gemas_europe_soil",
                    "source_file": resource["local_file"],
                    "source_row": object_id,
                    "source_locator": (
                        "https://gsi.geodata.gov.ie/server/rest/services/Geochemistry/"
                        "IE_GSI_GEMAS_Geochemistry_Agricultural_Grazing_Land_Soil_EU_WGS84/"
                        f"MapServer/3/query#OBJECTID={object_id}&field={field}"
                    ),
                    "file_sha256": resource["sha256"],
                    "source_tier": "government",
                    "benchmark_continent": "Europe",
                    "benchmark_country": country,
                    "benchmark_region": "GEMAS Europe agricultural soil",
                    **common_provenance(dataset),
                }
            )
            yield row


def parse_australian_date(value: str) -> str:
    try:
        day, month, year = (int(component) for component in value.strip().split("/"))
        return date(year, month, day).isoformat()
    except (TypeError, ValueError):
        return ""


def read_ngsa(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "ngsa_australia_hg")
    resource = resource_by_id(contract, "ngsa_australia_hg")
    path = verified_path(fixture_dir, resource)
    with path.open("r", encoding="cp1252", newline="") as handle:
        lines = handle.readlines()
    reader = csv.DictReader(lines[11:])
    for parent_row, raw in enumerate(reader, start=13):
        sample_id = raw["SAMPLEID"].strip()
        depth_code = raw["DEPTH"].strip()
        duplicate_site = raw["DUPLICATE_SITEID"].strip()
        measurement_basis = {
            "TOS": "total_Hg_dry_weight_top_outlet_sediment_TOS",
            "BOS": "total_Hg_dry_weight_bottom_outlet_sediment_BOS",
        }.get(depth_code, f"total_Hg_dry_weight_{depth_code or 'depth_unspecified'}")
        row = base_row()
        row.update(
            {
                "record_id": f"ngsa-{sample_id}-Hg",
                "source_record_id": f"{sample_id}:Hg",
                "sample_id": sample_id,
                "sample_identity_group": f"ngsa-site-{raw['SITEID'].strip()}-{depth_code}",
                "replicate_group_id": duplicate_site or raw["SITEID"].strip(),
                "element_or_analyte": "Hg",
                "analyte_reported": "Hg",
                "value": raw["Hg_DMA_ng/g_0.01"].strip(),
                "unit": "ng/g",
                "medium": "sediment",
                "material": f"catchment outlet sediment {depth_code}",
                "measurement_basis": measurement_basis,
                "latitude": raw["LATITUDE_GDA94"].strip(),
                "longitude": raw["LONGITUDE_GDA94"].strip(),
                "source_crs": "GDA94 geographic (EPSG:4283)",
                "coordinate_transform_method": (
                    "identity approximation from GDA94 geographic to OGC:CRS84 for continental screening; "
                    "not a high-accuracy datum transformation"
                ),
                "sampled_at": parse_australian_date(raw["DATE_SAMPLED"]),
                "grain_fraction": raw["GRAIN_SIZE"].strip(),
                "analytical_method": (
                    "Milestone tri-cell DMA-80: thermal decomposition, amalgamation and atomic absorption "
                    "spectrometry; USEPA 7473"
                ),
                "method_family": "direct_mercury_analyzer_atomic_absorption",
                "digestion_or_extraction": "none_direct_analysis",
                "laboratory": "Australian National University",
                "reference_material": "NIST-2706; WQB-1; NIST-1646a",
                "source_id": "ngsa_australia_hg",
                "source_file": resource["local_file"],
                "source_row": str(parent_row),
                "source_locator": f"https://doi.org/10.26186/150328#row={parent_row}&sample={sample_id}",
                "file_sha256": resource["sha256"],
                "source_tier": "government",
                "benchmark_continent": "Oceania",
                "benchmark_country": "Australia",
                "benchmark_region": raw["STATE"].strip(),
                **common_provenance(dataset),
            }
        )
        yield row


def gemstat_measurement_basis(parameter_code: str) -> str:
    folded = parameter_code.casefold()
    if "-dis" in folded:
        return "dissolved"
    if "-tot" in folded:
        return "total"
    if "-part" in folded or "-sus" in folded:
        return "particulate_or_suspended"
    return f"fraction_unspecified:{parameter_code}"


def gemstat_method(raw: Mapping[str, str]) -> str:
    description = raw.get("method_description", "").strip()
    if (
        raw.get("analysis_method_code", "").strip() == "0"
        or "undefined analysis method" in description.casefold()
    ):
        return ""
    parts = [
        raw.get("method_name", "").strip(),
        raw.get("method_type", "").strip(),
        raw.get("method_number", "").strip(),
        raw.get("method_source", "").strip(),
    ]
    return " | ".join(dict.fromkeys(part for part in parts if part))


def valid_depth(value: str) -> str:
    try:
        depth = float(value)
    except ValueError:
        return ""
    return str(depth) if math.isfinite(depth) and depth >= 0 else ""


def read_gemstat(
    fixture_dir: Path, contract: Mapping[str, Any]
) -> Iterable[dict[str, str]]:
    dataset = dataset_by_id(contract, "gemstat_global_freshwater_v3")
    resource = resource_by_id(contract, "gemstat_global_water_slice")
    path = verified_path(fixture_dir, resource)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            country = raw["country"].strip()
            continent = GEMSTAT_CONTINENTS.get(country)
            if continent is None:
                raise AdapterError(
                    f"GEMStat country missing from frozen continent map: {country}"
                )
            element = raw["element"].strip()
            station_id = raw["station_id"].strip()
            parent_member = raw["parent_member"].strip()
            parent_row = raw["parent_row"].strip()
            source_record_id = f"{parent_member}:{parent_row}:{element}"
            depth = valid_depth(raw["depth_m"].strip())
            method = gemstat_method(raw)
            row = base_row()
            row.update(
                {
                    "record_id": f"gemstat-{station_id}-{element}-{parent_row}",
                    "source_record_id": source_record_id,
                    "sample_id": f"gemstat-{station_id}-{raw['sample_date']}-{raw['sample_time']}",
                    "sample_identity_group": f"gemstat-{station_id}-{raw['sample_date']}-{raw['sample_time']}",
                    "element_or_analyte": element,
                    "analyte_reported": raw["parameter_code"].strip(),
                    "value": raw["value"].strip(),
                    "unit": raw["unit"].strip(),
                    "value_qualifier": raw["value_qualifier"].strip(),
                    "source_qualifier_raw": raw["value_qualifier"].strip(),
                    "medium": "water",
                    "material": raw["water_type"].strip(),
                    "measurement_basis": gemstat_measurement_basis(
                        raw["parameter_code"].strip()
                    ),
                    "latitude": raw["latitude"].strip(),
                    "longitude": raw["longitude"].strip(),
                    "source_crs": "WGS84",
                    "sampled_at": raw["sample_date"].strip(),
                    "sample_depth_min_m": depth,
                    "sample_depth_max_m": depth,
                    "geologic_unit": raw["main_basin"].strip(),
                    "geologic_context_source": "GEMStat station metadata main basin",
                    "geologic_context_version": "GFQA v3",
                    "geologic_match_method": "source_reported_station_metadata",
                    "geologic_match_confidence": "unknown",
                    "analytical_method": method,
                    "method_family": ""
                    if not method
                    else "source_reported_water_analysis",
                    "laboratory": "",
                    "source_id": "gemstat_global_freshwater_v3",
                    "source_file": parent_member,
                    "source_row": parent_row,
                    "source_locator": (
                        "https://doi.org/10.5281/zenodo.18459694"
                        f"#member={parent_member}&row={parent_row}&station={station_id}"
                    ),
                    "file_sha256": raw["parent_member_sha256"].strip(),
                    "source_tier": "official_curated",
                    "benchmark_continent": continent,
                    "benchmark_country": country,
                    "benchmark_region": raw["main_basin"].strip()
                    or raw["station_identifier"].strip(),
                    **common_provenance(dataset),
                }
            )
            yield row


def write_csv(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(
            handle, fieldnames=GLOBAL_OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def coverage_matrix(rows: Sequence[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        matrix[row["benchmark_continent"]][row["medium"]] += 1
    return {
        continent: {
            medium: counts.get(medium, 0)
            for medium in ("rock", "soil", "sediment", "water")
        }
        for continent, counts in sorted(matrix.items())
    }


def run_adapter(fixture_dir: Path, output_dir: Path) -> dict[str, Any]:
    prepare_empty_output_dir(output_dir)
    verify_fixtures(fixture_dir)
    contract = json.loads(SOURCE_CONTRACT.read_text(encoding="utf-8"))
    readers = (
        ("georoc", read_georoc),
        ("gemas", read_gemas),
        ("ngsa", read_ngsa),
        ("gemstat", read_gemstat),
    )
    rows: list[dict[str, str]] = []
    adapter_counts: dict[str, int] = {}
    for name, reader in readers:
        selected = list(reader(fixture_dir, contract))
        adapter_counts[name] = len(selected)
        rows.extend(selected)
    if not rows:
        raise AdapterError("global adapters produced no D1 records")

    export_path = output_dir / "d1_global_export.csv"
    write_csv(export_path, rows)
    source_counts = Counter(row["source_id"] for row in rows)
    medium_counts = Counter(row["medium"] for row in rows)
    element_counts = Counter(row["element_or_analyte"] for row in rows)
    continent_counts = Counter(row["benchmark_continent"] for row in rows)
    country_labels = sorted(
        {row["benchmark_country"] for row in rows if row["benchmark_country"]}
    )
    gemstat_countries = sorted(
        {
            row["benchmark_country"]
            for row in rows
            if row["source_id"] == "gemstat_global_freshwater_v3"
        }
    )
    manifest = {
        "manifest_version": "d1-global-real-manifest-v1",
        "adapter_version": ADAPTER_VERSION,
        "status": "success",
        "scientific_scope": "global_coverage_benchmark_slice_not_global_population_estimate",
        "continent_mapping_version": "benchmark-curated-continent-map-v1",
        "record_count": len(rows),
        "adapter_record_counts": adapter_counts,
        "records_by_source": dict(sorted(source_counts.items())),
        "records_by_medium": dict(sorted(medium_counts.items())),
        "records_by_element": dict(sorted(element_counts.items())),
        "records_by_continent": dict(sorted(continent_counts.items())),
        "coverage_matrix": coverage_matrix(rows),
        "explicit_country_label_count": len(country_labels),
        "explicit_country_labels": country_labels,
        "gemstat_country_count": len(gemstat_countries),
        "gemstat_countries": gemstat_countries,
        "declared_blind_spots": contract["coverage_acceptance"]["required_blind_spots"],
        "output": {
            "path": export_path.name,
            "bytes": export_path.stat().st_size,
            "sha256": sha256_file(export_path),
        },
        "interpretation_limits": [
            "Seven-continent coverage means at least one bundled medium is represented, not complete media-by-continent coverage.",
            "Country labels mix source-preserved names and GEMAS codes and must not be treated as a deduplicated sovereign-state count.",
            "GEOROC method and geodetic-datum omissions are preserved; no analytical method was inferred.",
            "GEMStat selection is deterministic and value-independent but is not a temporal or national statistical sample.",
        ],
    }
    manifest_path = output_dir / "d1_global_manifest.json"
    atomic_write_json(manifest_path, manifest)
    return {"exchange": export_path, "manifest": manifest_path, "summary": manifest}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Adapt frozen global real sources to the D2 canonical input CSV."
    )
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_adapter(args.fixture_dir, args.output_dir)
    except (AdapterError, OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": "success",
                "exchange": str(result["exchange"]),
                "manifest": str(result["manifest"]),
                "record_count": result["summary"]["record_count"],
                "continents": sorted(result["summary"]["records_by_continent"]),
                "media": sorted(result["summary"]["records_by_medium"]),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
