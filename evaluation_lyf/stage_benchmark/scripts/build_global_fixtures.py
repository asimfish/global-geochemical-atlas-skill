#!/usr/bin/env python3
"""Build or verify the small, frozen global real-data benchmark fixtures.

The checked-in fixture is a deterministic derivative of much larger official
sources.  Parent downloads are kept outside the repository.  Offline mode is
the normal evaluator path; refresh mode is only for benchmark maintainers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_common import (
    CONTRACT_ROOT,
    LAB_ROOT,
    atomic_write_json,
    load_json,
    sha256_file,
)

BUILDER_VERSION = "global-fixture-builder-v1"
SOURCE_CONTRACT = CONTRACT_ROOT / "global-sources.json"
DEFAULT_FIXTURE_DIR = LAB_ROOT / "global-data" / "fixtures" / "raw"
DEFAULT_CACHE_DIR = Path(tempfile.gettempdir()) / "global-geochemical-benchmark-cache"

GEOROC_ARCHAEAN_METADATA_URL = (
    "https://data.goettingen-research-online.de/api/datasets/:persistentId/"
    "?persistentId=doi:10.25625/1KRR1P"
)
GEOROC_ANTARCTICA_METADATA_URL = (
    "https://data.goettingen-research-online.de/api/datasets/:persistentId/"
    "?persistentId=doi:10.25625/RZZ9VM"
)
GEOROC_FILE_URL = (
    "https://data.goettingen-research-online.de/api/access/datafile/:persistentId"
)
GEMSTAT_RECORD_URL = "https://zenodo.org/api/records/13881899"
GEMAS_SERVICE = (
    "https://gsi.geodata.gov.ie/server/rest/services/Geochemistry/"
    "IE_GSI_GEMAS_Geochemistry_Agricultural_Grazing_Land_Soil_EU_WGS84/MapServer"
)
GEMAS_LAYER_METADATA_URL = f"{GEMAS_SERVICE}/3?f=pjson"
GEMAS_QUERY_PARAMETERS = (
    ("where", "1=1"),
    (
        "outFields",
        "OBJECTID,ID,COUNTRY,TYPE_,TYPE2,XCOO,YCOO,ALT,SOILTYPE,SOILCLASS,AS_,CU,PB,ZN",
    ),
    ("returnGeometry", "true"),
    ("outSR", "4326"),
    ("resultRecordCount", "2200"),
    ("orderByFields", "OBJECTID ASC"),
    ("f", "geojson"),
)
GEMAS_QUERY_URL = (
    f"{GEMAS_SERVICE}/3/query?{urllib.parse.urlencode(GEMAS_QUERY_PARAMETERS)}"
)
NGSA_CSV_URL = "https://d28rz98at9flks.cloudfront.net/150328/150328_00_1.CSV"
NGSA_METADATA_URL = (
    "https://data.gov.au/data/api/3/action/package_show"
    "?id=d0a5af8b-48a4-425c-809f-eae6f7701542"
)

TARGET_ELEMENTS = {
    "AS(PPM)": "as_ppm",
    "CR(PPM)": "cr_ppm",
    "CU(PPM)": "cu_ppm",
    "NI(PPM)": "ni_ppm",
    "PB(PPM)": "pb_ppm",
    "ZN(PPM)": "zn_ppm",
}

GEOROC_CONTINENTS = {
    "2026-06-1KRR1P_ALDAN_SHIELD_ARCHEAN.csv": "Asia",
    "2026-06-1KRR1P_AMAZONIAN_CRATON.csv": "South America",
    "2026-06-1KRR1P_BALTIC_SHIELD_ARCHEAN.csv": "Europe",
    "2026-06-1KRR1P_BASTAR_CRATON.csv": "Asia",
    "2026-06-1KRR1P_BUNDELKHAND_CRATON.csv": "Asia",
    "2026-06-1KRR1P_CHURCHILL_PROVINCE_ARCHEAN.csv": "North America",
    "2026-06-1KRR1P_CONGO_CRATON.csv": "Africa",
    "2026-06-1KRR1P_DHARWAR_CRATON_ARCHEAN.csv": "Asia",
    "2026-06-1KRR1P_EAST_EUROPEAN_CRATON.csv": "Europe",
    "2026-06-1KRR1P_GAWLER_CRATON.csv": "Oceania",
    "2026-06-1KRR1P_KAAPVAAL_CRATON_ARCHEAN.csv": "Africa",
    "2026-06-1KRR1P_LIMPOPO_BELT.csv": "Africa",
    "2026-06-1KRR1P_NORTH_ATLANTIC_CRATON_ARCHEAN.csv": "North America",
    "2026-06-1KRR1P_NORTH_CHINA_CRATON.csv": "Asia",
    "2026-06-1KRR1P_OKHOTSK-OMOLON_CRATON.csv": "Asia",
    "2026-06-1KRR1P_RAE_CRATON.csv": "North America",
    "2026-06-1KRR1P_SAO_FRANCISCO_CRATON_ARCHEAN.csv": "South America",
    "2026-06-1KRR1P_SARMATIAN_CRATON.csv": "Europe",
    "2026-06-1KRR1P_SIBERIAN_CRATON_ARCHEAN.csv": "Asia",
    "2026-06-1KRR1P_SINGHBHUM_CRATON_ARCHEAN.csv": "Asia",
    "2026-06-1KRR1P_SLAVE_PROVINCE_ARCHEAN.csv": "North America",
    "2026-06-1KRR1P_SUPERIOR_PROVINCE_ARCHEAN.csv": "North America",
    "2026-06-1KRR1P_TANZANIA_CRATON_ARCHEAN.csv": "Africa",
    "2026-06-1KRR1P_WEST_AFRICAN_CRATON.csv": "Africa",
    "2026-06-1KRR1P_WEST_AUSTRALIAN_CRATON.csv": "Oceania",
    "2026-06-1KRR1P_WYOMING_PROVINCE.csv": "North America",
    "2026-06-1KRR1P_YANGTZE_BLOCK.csv": "Asia",
    "2026-06-1KRR1P_ZIMBABWE_CRATON_ARCHEAN.csv": "Africa",
    "2026-06-RZZ9VM_ANTARCTICA.csv": "Antarctica",
}

GEOROC_OUTPUT_FIELDS = (
    "parent_file",
    "parent_persistent_id",
    "parent_sha256",
    "parent_row",
    "continent",
    "region",
    "citations",
    "tectonic_setting",
    "location",
    "latitude_min",
    "latitude_max",
    "longitude_min",
    "longitude_max",
    "sample_name",
    "rock_name",
    "material",
    "unique_id",
    "as_ppm",
    "cr_ppm",
    "cu_ppm",
    "ni_ppm",
    "pb_ppm",
    "zn_ppm",
)

GEMSTAT_OUTPUT_FIELDS = (
    "parent_member",
    "parent_member_sha256",
    "parent_row",
    "element",
    "station_id",
    "country",
    "water_type",
    "station_identifier",
    "water_body_name",
    "main_basin",
    "responsible_agency",
    "latitude",
    "longitude",
    "sample_date",
    "sample_time",
    "depth_m",
    "parameter_code",
    "analysis_method_code",
    "value_qualifier",
    "value",
    "unit",
    "data_quality",
    "remark",
    "license_information",
    "method_name",
    "method_type",
    "method_number",
    "method_source",
    "method_description",
)


class FixtureError(RuntimeError):
    """Raised when an upstream or frozen fixture violates its contract."""


def md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_if_missing(url: str, destination: Path, max_bytes: int) -> Path:
    if destination.is_file():
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": f"{BUILDER_VERSION} (+offline-benchmark)"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            raise FixtureError(
                f"source exceeds byte limit ({length} > {max_bytes}): {url}"
            )
        with tempfile.NamedTemporaryFile(
            "wb", dir=destination.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    handle.close()
                    temporary.unlink(missing_ok=True)
                    raise FixtureError(
                        f"download exceeds byte limit ({total} > {max_bytes}): {url}"
                    )
                handle.write(chunk)
    os.replace(temporary, destination)
    return destination


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb", dir=destination.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        with source.open("rb") as source_handle:
            shutil.copyfileobj(source_handle, handle)
    os.replace(temporary, destination)


def json_data(path: Path) -> Mapping[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise FixtureError(f"expected JSON object: {path}")
    return payload


def dataverse_files(metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        files = metadata["data"]["latestVersion"]["files"]
    except (KeyError, TypeError) as exc:
        raise FixtureError(
            "GEOROC Dataverse metadata has no latestVersion.files"
        ) from exc
    result: list[dict[str, Any]] = []
    for item in files:
        data_file = item.get("dataFile", {})
        filename = str(data_file.get("filename") or item.get("label") or "")
        if not filename.endswith(".csv"):
            continue
        result.append(
            {
                "filename": filename,
                "persistent_id": str(data_file.get("persistentId") or ""),
                "bytes": int(data_file.get("filesize") or 0),
                "md5": str(
                    (data_file.get("checksum") or {}).get("value") or ""
                ).lower(),
            }
        )
    return result


def persistent_file_url(persistent_id: str) -> str:
    return (
        f"{GEOROC_FILE_URL}?{urllib.parse.urlencode({'persistentId': persistent_id})}"
    )


def verify_parent(path: Path, metadata: Mapping[str, Any]) -> None:
    if path.stat().st_size != int(metadata["bytes"]):
        raise FixtureError(f"parent byte mismatch: {path}")
    if md5_file(path) != metadata["md5"]:
        raise FixtureError(f"parent MD5 mismatch: {path}")


def optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(str(value).strip())
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def valid_georoc_coordinates(row: Mapping[str, str]) -> bool:
    bounds = [
        optional_float(row.get("LATITUDE MIN")),
        optional_float(row.get("LATITUDE MAX")),
        optional_float(row.get("LONGITUDE MIN")),
        optional_float(row.get("LONGITUDE MAX")),
    ]
    if any(value is None for value in bounds):
        return False
    lat_min, lat_max, lon_min, lon_max = (float(value) for value in bounds)
    return -90 <= lat_min <= lat_max <= 90 and -180 <= lon_min <= lon_max <= 180


def select_evenly(rows: Sequence[dict[str, Any]], maximum: int) -> list[dict[str, Any]]:
    if maximum <= 0 or len(rows) <= maximum:
        return list(rows)
    indices = [
        min(len(rows) - 1, math.floor((index + 0.5) * len(rows) / maximum))
        for index in range(maximum)
    ]
    return [rows[index] for index in indices]


def georoc_region(filename: str) -> str:
    name = filename.removeprefix("2026-06-1KRR1P_").removeprefix("2026-06-RZZ9VM_")
    return name.removesuffix(".csv").replace("_", " ").title()


def georoc_rows(
    parents: Sequence[tuple[Mapping[str, Any], Path]], maximum_per_region: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    parent_evidence: list[dict[str, Any]] = []
    for parent, path in sorted(parents, key=lambda item: str(item[0]["filename"])):
        filename = str(parent["filename"])
        if filename not in GEOROC_CONTINENTS:
            continue
        parent_sha256 = sha256_file(path)
        parent_evidence.append({**dict(parent), "sha256": parent_sha256})
        eligible: list[dict[str, Any]] = []
        with path.open("r", encoding="latin-1", newline="") as handle:
            reader = csv.DictReader(handle)
            for source_row, row in enumerate(reader, start=2):
                if not (
                    row.get("UNIQUE_ID") or ""
                ).strip() or not valid_georoc_coordinates(row):
                    continue
                if not any(
                    (row.get(source_field) or "").strip()
                    for source_field in TARGET_ELEMENTS
                ):
                    continue
                record: dict[str, Any] = {
                    "parent_file": filename,
                    "parent_persistent_id": parent["persistent_id"],
                    "parent_sha256": parent_sha256,
                    "parent_row": source_row,
                    "continent": GEOROC_CONTINENTS[filename],
                    "region": georoc_region(filename),
                    "citations": (row.get("CITATIONS") or "").strip(),
                    "tectonic_setting": (row.get("TECTONIC SETTING") or "").strip(),
                    "location": (row.get("LOCATION") or "").strip(),
                    "latitude_min": (row.get("LATITUDE MIN") or "").strip(),
                    "latitude_max": (row.get("LATITUDE MAX") or "").strip(),
                    "longitude_min": (row.get("LONGITUDE MIN") or "").strip(),
                    "longitude_max": (row.get("LONGITUDE MAX") or "").strip(),
                    "sample_name": (row.get("SAMPLE NAME") or "").strip(),
                    "rock_name": (row.get("ROCK NAME") or "").strip(),
                    "material": (row.get("MATERIAL") or "").strip(),
                    "unique_id": (row.get("UNIQUE_ID") or "").strip(),
                }
                for source_field, output_field in TARGET_ELEMENTS.items():
                    record[output_field] = (row.get(source_field) or "").strip()
                eligible.append(record)
        eligible.sort(key=lambda row: (str(row["unique_id"]), int(row["parent_row"])))
        output.extend(select_evenly(eligible, maximum_per_region))
    return output, parent_evidence


def write_csv(
    path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, Any]]
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        count = 0
        for row in rows:
            writer.writerow(row)
            count += 1
    os.replace(temporary, path)
    return count


def zip_member_to_cache(
    archive: zipfile.ZipFile, member: str, destination: Path
) -> Path:
    if (
        destination.is_file()
        and destination.stat().st_size == archive.getinfo(member).file_size
    ):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        archive.open(member) as source,
        tempfile.NamedTemporaryFile(
            "wb", dir=destination.parent, delete=False
        ) as handle,
    ):
        temporary = Path(handle.name)
        shutil.copyfileobj(source, handle)
    os.replace(temporary, destination)
    return destination


def read_csv_cp1252(path: Path) -> Iterable[tuple[int, dict[str, str]]]:
    with path.open("r", encoding="cp1252", newline="") as handle:
        yield from enumerate(csv.DictReader(handle), start=2)


def supported_water_unit(value: str) -> bool:
    canonical = (
        value.strip().casefold().replace("µ", "u").replace("μ", "u").replace(" ", "")
    )
    return canonical in {"mg/l", "ug/l", "ng/l", "g/l"}


def gemstat_rows(
    archive_path: Path, cache_dir: Path, maximum_per_country_element: int
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    required = {
        "station": "GEMStat_station_metadata.csv",
        "method": "GEMStat_methods_metadata.csv",
        "readme": "README_output_format.txt",
        "As": "Arsenic.csv",
        "Cu": "Copper.csv",
        "Pb": "Lead.csv",
        "Zn": "Zinc.csv",
    }
    extracted: dict[str, Path] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for key, member in required.items():
            extracted[key] = zip_member_to_cache(
                archive, member, cache_dir / "gemstat" / member
            )

    stations: dict[str, dict[str, str]] = {}
    for _, row in read_csv_cp1252(extracted["station"]):
        lat = optional_float(row.get("Latitude"))
        lon = optional_float(row.get("Longitude"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        stations[row["GEMS Station Number"]] = row

    methods: dict[tuple[str, str, str], dict[str, str]] = {}
    methods_fallback: dict[tuple[str, str], dict[str, str]] = {}
    for _, row in read_csv_cp1252(extracted["method"]):
        exact = (row["Parameter Code"], row["Analysis Method Code"], row["Unit"])
        methods.setdefault(exact, row)
        methods_fallback.setdefault(exact[:2], row)

    output: list[dict[str, Any]] = []
    member_hashes = {path.name: sha256_file(path) for path in extracted.values()}
    for element in ("As", "Cu", "Pb", "Zn"):
        path = extracted[element]
        first_by_station: dict[str, tuple[tuple[str, ...], int, dict[str, str]]] = {}
        for parent_row, row in read_csv_cp1252(path):
            station_id = row.get("GEMS Station Number", "")
            station = stations.get(station_id)
            value = optional_float(row.get("Value"))
            qualifier = (row.get("Value Flags") or "").strip()
            if (
                station is None
                or value is None
                or value < 0
                or qualifier not in {"", "<", ">"}
            ):
                continue
            if not supported_water_unit(row.get("Unit", "")):
                continue
            order = (
                row.get("Sample Date", ""),
                row.get("Sample Time", ""),
                row.get("Parameter Code", ""),
                row.get("Analysis Method Code", ""),
                row.get("Unit", ""),
                qualifier,
                row.get("Value", ""),
                f"{parent_row:012d}",
            )
            current = first_by_station.get(station_id)
            if current is None or order < current[0]:
                first_by_station[station_id] = (order, parent_row, row)

        grouped: dict[str, list[tuple[str, int, dict[str, str]]]] = defaultdict(list)
        for station_id, (_, parent_row, row) in first_by_station.items():
            grouped[stations[station_id].get("Country Name", "unknown")].append(
                (station_id, parent_row, row)
            )
        for country in sorted(grouped):
            candidates = sorted(grouped[country], key=lambda item: item[0])
            selected = select_evenly(
                [
                    {"station_id": station_id, "parent_row": parent_row, "row": row}
                    for station_id, parent_row, row in candidates
                ],
                maximum_per_country_element,
            )
            for item in selected:
                station_id = str(item["station_id"])
                parent_row = int(item["parent_row"])
                row = item["row"]
                station = stations[station_id]
                method = methods.get(
                    (row["Parameter Code"], row["Analysis Method Code"], row["Unit"])
                ) or methods_fallback.get(
                    (row["Parameter Code"], row["Analysis Method Code"]), {}
                )
                output.append(
                    {
                        "parent_member": path.name,
                        "parent_member_sha256": member_hashes[path.name],
                        "parent_row": parent_row,
                        "element": element,
                        "station_id": station_id,
                        "country": country,
                        "water_type": station.get("Water Type", ""),
                        "station_identifier": station.get("Station Identifier", ""),
                        "water_body_name": station.get("Water Body Name", ""),
                        "main_basin": station.get("Main Basin", ""),
                        "responsible_agency": station.get(
                            "Responsible Collection Agency", ""
                        ),
                        "latitude": station.get("Latitude", ""),
                        "longitude": station.get("Longitude", ""),
                        "sample_date": row.get("Sample Date", ""),
                        "sample_time": row.get("Sample Time", ""),
                        "depth_m": row.get("Depth", ""),
                        "parameter_code": row.get("Parameter Code", ""),
                        "analysis_method_code": row.get("Analysis Method Code", ""),
                        "value_qualifier": row.get("Value Flags", ""),
                        "value": row.get("Value", ""),
                        "unit": row.get("Unit", ""),
                        "data_quality": row.get("Data Quality", ""),
                        "remark": row.get("Remark", ""),
                        "license_information": row.get("License Information", ""),
                        "method_name": method.get("Method Name", ""),
                        "method_type": method.get("Method Type", ""),
                        "method_number": method.get("Method Number", ""),
                        "method_source": method.get("Method Source", ""),
                        "method_description": method.get("Method Description", ""),
                    }
                )
    output.sort(
        key=lambda row: (
            str(row["element"]),
            str(row["country"]),
            str(row["station_id"]),
        )
    )
    return output, member_hashes


def fixture_entry(path: Path, record_count: int | None = None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "local_file": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if record_count is not None:
        entry["record_count"] = record_count
    return entry


def refresh_fixtures(
    fixture_dir: Path,
    cache_dir: Path,
    maximum_georoc_per_region: int,
    maximum_gemstat_per_country_element: int,
) -> dict[str, Any]:
    if fixture_dir.exists() and any(fixture_dir.iterdir()):
        raise FixtureError(f"refresh target must be absent or empty: {fixture_dir}")
    fixture_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    metadata_specs = {
        "georoc_archaean_metadata.json": (GEOROC_ARCHAEAN_METADATA_URL, 2_000_000),
        "georoc_antarctica_metadata.json": (GEOROC_ANTARCTICA_METADATA_URL, 2_000_000),
        "gemstat_record_metadata.json": (GEMSTAT_RECORD_URL, 2_000_000),
        "gemas_layer3_metadata.json": (GEMAS_LAYER_METADATA_URL, 2_000_000),
        "ngsa_catalog_metadata.json": (NGSA_METADATA_URL, 2_000_000),
    }
    metadata_paths: dict[str, Path] = {}
    for filename, (url, limit) in metadata_specs.items():
        cached = download_if_missing(url, cache_dir / filename, limit)
        copy_file(cached, fixture_dir / filename)
        metadata_paths[filename] = cached

    archaean = dataverse_files(
        json_data(metadata_paths["georoc_archaean_metadata.json"])
    )
    antarctica_files = dataverse_files(
        json_data(metadata_paths["georoc_antarctica_metadata.json"])
    )
    antarctica = [
        item
        for item in antarctica_files
        if item["filename"] == "2026-06-RZZ9VM_ANTARCTICA.csv"
    ]
    if len(archaean) != 28 or len(antarctica) != 1:
        raise FixtureError(
            f"unexpected GEOROC source inventory: archaean={len(archaean)}, antarctica={len(antarctica)}"
        )
    georoc_parents: list[tuple[Mapping[str, Any], Path]] = []
    for parent in [*archaean, *antarctica]:
        path = download_if_missing(
            persistent_file_url(str(parent["persistent_id"])),
            cache_dir / "georoc" / str(parent["filename"]),
            10_000_000,
        )
        verify_parent(path, parent)
        georoc_parents.append((parent, path))
    rocks, georoc_parent_evidence = georoc_rows(
        georoc_parents, maximum_georoc_per_region
    )
    rock_count = write_csv(
        fixture_dir / "georoc_global_rocks.csv", GEOROC_OUTPUT_FIELDS, rocks
    )

    gemas_path = download_if_missing(
        GEMAS_QUERY_URL, cache_dir / "gemas_ap.geojson", 10_000_000
    )
    gemas_payload = json_data(gemas_path)
    gemas_count = len(gemas_payload.get("features", []))
    if gemas_count != 2113 or gemas_payload.get("type") != "FeatureCollection":
        raise FixtureError(f"unexpected GEMAS response: {gemas_count} features")
    copy_file(gemas_path, fixture_dir / "gemas_europe_soil.geojson")

    ngsa_path = download_if_missing(NGSA_CSV_URL, cache_dir / "ngsa_hg.csv", 2_000_000)
    copy_file(ngsa_path, fixture_dir / "ngsa_australia_hg.csv")
    with ngsa_path.open("r", encoding="cp1252", newline="") as handle:
        ngsa_count = sum(1 for _ in csv.DictReader(handle.readlines()[11:]))
    if ngsa_count < 2300:
        raise FixtureError(f"NGSA source is unexpectedly small: {ngsa_count}")

    gemstat_record = json_data(metadata_paths["gemstat_record_metadata.json"])
    files = gemstat_record.get("files", [])
    if len(files) != 1:
        raise FixtureError("GEMStat Zenodo record does not contain exactly one archive")
    archive_metadata = files[0]
    archive_url = str((archive_metadata.get("links") or {}).get("self") or "")
    archive_bytes = int(archive_metadata.get("size") or 0)
    archive_md5 = str(archive_metadata.get("checksum") or "").removeprefix("md5:")
    archive_path = download_if_missing(
        archive_url, cache_dir / "GFQA_v3.zip", 250_000_000
    )
    if (
        archive_path.stat().st_size != archive_bytes
        or md5_file(archive_path) != archive_md5
    ):
        raise FixtureError("GEMStat archive does not match the Zenodo record")
    waters, member_hashes = gemstat_rows(
        archive_path, cache_dir, maximum_gemstat_per_country_element
    )
    water_count = write_csv(
        fixture_dir / "gemstat_global_water.csv", GEMSTAT_OUTPUT_FIELDS, waters
    )
    readme_path = cache_dir / "gemstat" / "README_output_format.txt"
    copy_file(readme_path, fixture_dir / "gemstat_readme.txt")

    resource_counts = {
        "georoc_global_rocks.csv": rock_count,
        "gemas_europe_soil.geojson": gemas_count,
        "ngsa_australia_hg.csv": ngsa_count,
        "gemstat_global_water.csv": water_count,
    }
    fixture_resources = [
        fixture_entry(path, resource_counts.get(path.name))
        for path in sorted(fixture_dir.iterdir())
        if path.name != "source_manifest.json"
    ]
    manifest = {
        "manifest_version": "global-fixture-manifest-v1",
        "builder_version": BUILDER_VERSION,
        "scientific_scope": "global_coverage_benchmark_slice_not_a_complete_global_atlas",
        "selection": {
            "georoc": {
                "rule": "valid coordinate and at least one target analyte; sort by UNIQUE_ID; evenly select without using concentration magnitude",
                "maximum_samples_per_named_region": maximum_georoc_per_region,
                "target_elements": ["As", "Cr", "Cu", "Ni", "Pb", "Zn"],
            },
            "gemstat": {
                "rule": "earliest supported aqueous result per station; sort station IDs; evenly select without using concentration magnitude",
                "maximum_stations_per_country_element": maximum_gemstat_per_country_element,
                "target_elements": ["As", "Cu", "Pb", "Zn"],
            },
            "gemas": "all 2,113 agricultural-soil points returned by the pinned layer-3 query",
            "ngsa": "all source CSV records, including declared duplicates and both TOS/BOS depths",
        },
        "parents": {
            "georoc": georoc_parent_evidence,
            "gemstat": {
                "record_id": gemstat_record.get("id"),
                "doi": gemstat_record.get("doi"),
                "concept_doi": gemstat_record.get("conceptdoi"),
                "archive_file": archive_path.name,
                "archive_bytes": archive_path.stat().st_size,
                "archive_md5": md5_file(archive_path),
                "archive_sha256": sha256_file(archive_path),
                "member_sha256": dict(sorted(member_hashes.items())),
            },
            "gemas": {
                "query_url": GEMAS_QUERY_URL,
                "source_sha256": sha256_file(gemas_path),
            },
            "ngsa": {
                "download_url": NGSA_CSV_URL,
                "source_sha256": sha256_file(ngsa_path),
            },
        },
        "record_counts": resource_counts,
        "fixture_resources": fixture_resources,
        "total_fixture_bytes_excluding_manifest": sum(
            item["bytes"] for item in fixture_resources
        ),
    }
    atomic_write_json(fixture_dir / "source_manifest.json", manifest)
    return manifest


def verify_tokens(path: Path, tokens: Sequence[str]) -> list[str]:
    if not tokens:
        return []
    content = path.read_bytes()
    return [token for token in tokens if token.encode("utf-8") not in content]


def verify_fixtures(fixture_dir: Path) -> dict[str, Any]:
    if not SOURCE_CONTRACT.is_file():
        raise FixtureError(f"global source contract is missing: {SOURCE_CONTRACT}")
    contract = load_json(SOURCE_CONTRACT)
    failures: list[dict[str, Any]] = []
    total_bytes = 0
    for resource in contract.get("resources", []):
        path = fixture_dir / str(resource["local_file"])
        if not path.is_file():
            failures.append({"resource": resource["id"], "reason": "missing"})
            continue
        total_bytes += path.stat().st_size
        actual_sha = sha256_file(path)
        missing_tokens = verify_tokens(path, resource.get("required_tokens", []))
        if (
            path.stat().st_size != resource["bytes"]
            or actual_sha != resource["sha256"]
            or missing_tokens
        ):
            failures.append(
                {
                    "resource": resource["id"],
                    "reason": "contract_mismatch",
                    "actual_bytes": path.stat().st_size,
                    "actual_sha256": actual_sha,
                    "missing_tokens": missing_tokens,
                }
            )
    if failures:
        raise FixtureError(
            json.dumps(
                {"fixture_failures": failures}, ensure_ascii=False, sort_keys=True
            )
        )
    return {
        "status": "pass",
        "offline": True,
        "builder_version": BUILDER_VERSION,
        "resource_count": len(contract.get("resources", [])),
        "total_bytes": total_bytes,
        "fixture_dir": str(fixture_dir),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build or verify frozen global geochemical benchmark fixtures."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline",
        action="store_true",
        help="Verify checked-in files without network access (default)",
    )
    mode.add_argument(
        "--refresh",
        action="store_true",
        help="Download parents into an external cache and rebuild an empty fixture directory",
    )
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--max-georoc-per-region", type=int, default=80)
    parser.add_argument("--max-gemstat-per-country-element", type=int, default=5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.refresh:
            manifest = refresh_fixtures(
                args.fixture_dir,
                args.cache_dir,
                args.max_georoc_per_region,
                args.max_gemstat_per_country_element,
            )
            payload = {
                "status": "built_unpinned",
                "fixture_dir": str(args.fixture_dir),
                "manifest": str(args.fixture_dir / "source_manifest.json"),
                "record_counts": manifest["record_counts"],
                "total_bytes": manifest["total_fixture_bytes_excluding_manifest"],
            }
        else:
            payload = verify_fixtures(args.fixture_dir)
    except (FixtureError, OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
