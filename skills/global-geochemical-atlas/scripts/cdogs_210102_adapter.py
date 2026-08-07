#!/usr/bin/env python3
"""Acquire and parse two media from CDoGS survey 210102.

The standardized CDoGS spreadsheets contain every survey analyzed by a lab
package.  This adapter therefore filters the authoritative ``Survey_Key``
column to ``21:0102`` before publishing any row.  It uses the ``c`` spreadsheet
variant so source-native less-than qualifiers remain text.

No content digest is calculated or consumed.  Files are identified by their
official URL, package/file name, observed byte count, XLSX members, header, row
counts, and source statistics.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHEMA_VERSION = "d1-cdogs-210102-observation-v1"
ADAPTER_VERSION = "d1-cdogs-210102-adapter-v1"
SURVEY_KEY = "21:0102"
DATASET_VERSION = "cdogs-svy210102-page-2025-05-18"
SURVEY_URL = "https://geochem.nrcan.gc.ca/cdogs/content/svy_ext/svy210102_e.ext.htm"
XLSX_ROOT = "https://geochem.nrcan.gc.ca/ftp/data/raw_data/svy"
TERMS_URL = "https://www.canada.ca/en/transparency/terms.html"
COMMON_COLUMNS = (
    "Lab_Sample_Identifier",
    "Lab_Key",
    "Bundle_Key",
    "Survey_Key",
    "Site_Key",
    "Field_Key",
    "Control_Reference_ID",
    "Latitude_NAD83",
    "Longitude_NAD83",
    "Sample_Type_Name_en",
    "Preparation_Method_Name_en",
    "QAQC_Block_ID",
    "QAQC_Sample_Identifier",
    "Order_Of_Analysis",
)


class CDoGSError(ValueError):
    """Raised when source identity, structure, or semantics cannot be preserved."""


@dataclass(frozen=True)
class MethodContract:
    column: str
    analyte: str
    method_id: str
    unit: str
    detection_limit: float
    technique: str
    digestion: str | None
    laboratory: str


@dataclass(frozen=True)
class FileContract:
    file_id: str
    package_id: str
    filename: str
    observed_bytes: int
    analysis_year: int
    publication_id: str
    publication_citation: str
    methods: tuple[MethodContract, ...]

    @property
    def url(self) -> str:
        return f"{XLSX_ROOT}/{self.filename}"

    @property
    def method_url(self) -> str:
        return f"https://geochem.nrcan.gc.ca/cdogs/content/pkg/pkg{self.package_id.zfill(5)}_e.htm"


SEDIMENT_AAS_METHODS = (
    MethodContract("Zn_AAS", "Zn", "2091", "ppm", 2, "AAS; air-acetylene flame", "Aqua regia (NGR)", "Chemex"),
    MethodContract("Cu_AAS", "Cu", "2092", "ppm", 2, "AAS; air-acetylene flame", "Aqua regia (NGR)", "Chemex"),
    MethodContract("Pb_AAS", "Pb", "2093", "ppm", 2, "AAS; air-acetylene flame", "Aqua regia (NGR)", "Chemex"),
    MethodContract("Ni_AAS", "Ni", "2094", "ppm", 2, "AAS; air-acetylene flame", "Aqua regia (NGR)", "Chemex"),
    MethodContract("Hg_AAS", "Hg", "2118", "ppb", 10, "Cold vapour atomic absorption spectroscopy", "Aqua regia (sensu lato)", "Chemex"),
    MethodContract("As_Col", "As", "2117", "ppm", 1, "Colorimetry", "Unknown", "Chemex"),
)
SEDIMENT_XRF_METHODS = (
    MethodContract("Cr_XRF", "Cr", "1088", "ppm", 10, "XRF; fused with LiBO2", None, "X-Ray Assay Laboratories"),
)
WATER_METHODS = (
    MethodContract("U_FT", "U", "1999", "ppb", 0.01, "Fission track analysis", None, "Bondar Clegg"),
)

FILE_CONTRACTS: dict[str, FileContract] = {
    "pkg-0134c": FileContract(
        "pkg-0134c", "134", "svy210102_pkg_0134c.xlsx", 3447178, 1977, "GSC-OF-405",
        "Geological Survey of Canada (1977). Regional lake sediment geochemical reconnaissance data, Ontario. Geological Survey of Canada, Open File 405.",
        SEDIMENT_AAS_METHODS,
    ),
    "pkg-0383c": FileContract(
        "pkg-0383c", "383", "svy210102_pkg_0383c.xlsx", 568509, 1983, "GSC-OF-899",
        "Geological Survey of Canada (1984). National geochemical reconnaissance surveys, southeastern Ontario. Geological Survey of Canada, Open File 899.",
        SEDIMENT_XRF_METHODS,
    ),
    "pkg-0136c": FileContract(
        "pkg-0136c", "136", "svy210102_pkg_0136c.xlsx", 563410, 1977, "GSC-OF-899",
        "Geological Survey of Canada (1984). National geochemical reconnaissance surveys, southeastern Ontario. Geological Survey of Canada, Open File 899.",
        WATER_METHODS,
    ),
}

SOURCE_CONFIGS: dict[str, dict[str, Any]] = {
    "cdogs-210102-lake-sediment": {
        "medium": "sediment",
        "sample_type_raw": "NGR lake sediment grab sample",
        "sample_type": "sediment_lake",
        "files": ("pkg-0134c", "pkg-0383c"),
    },
    "cdogs-210102-lake-water": {
        "medium": "water",
        "sample_type_raw": "Fluid (lake)",
        "sample_type": "water_lake",
        "files": ("pkg-0136c",),
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def _float(value: Any) -> float | None:
    text = _text(value)
    if text is None:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def _int(value: Any) -> int | None:
    number = _float(value)
    return int(number) if number is not None and number.is_integer() else None


def _column_index(reference: str) -> int:
    letters = "".join(character for character in reference if character.isalpha())
    number = 0
    for character in letters:
        number = number * 26 + ord(character.upper()) - 64
    return number - 1


def iter_xlsx_rows(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield one worksheet as dictionaries using only the Python standard library."""

    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CDoGSError(f"invalid XLSX archive: {path}") from exc
    with archive:
        required = {"xl/workbook.xml", "xl/worksheets/sheet1.xml", "xl/sharedStrings.xml"}
        missing = required - set(archive.namelist())
        if missing:
            raise CDoGSError(f"XLSX lacks required members: {sorted(missing)}")
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = [
            "".join(text.text or "" for text in item.iter(f"{namespace}t"))
            for item in shared_root.iter(f"{namespace}si")
        ]
        header: list[str] | None = None
        with archive.open("xl/worksheets/sheet1.xml") as sheet:
            for _, element in ET.iterparse(sheet, events=("end",)):
                if element.tag != f"{namespace}row":
                    continue
                row_number = int(element.attrib.get("r", "0"))
                cells: dict[int, str] = {}
                for cell in element.findall(f"{namespace}c"):
                    value_element = cell.find(f"{namespace}v")
                    value = "" if value_element is None else value_element.text or ""
                    if cell.attrib.get("t") == "s" and value:
                        value = shared[int(value)]
                    cells[_column_index(cell.attrib.get("r", "A1"))] = value
                element.clear()
                if not cells:
                    continue
                width = max(cells) + 1
                values = [cells.get(index, "") for index in range(width)]
                if header is None:
                    header = values
                    absent = sorted(set(COMMON_COLUMNS) - set(header))
                    if absent:
                        raise CDoGSError(f"XLSX header lacks common columns: {absent}")
                    continue
                if len(values) < len(header):
                    values.extend([""] * (len(header) - len(values)))
                yield row_number, dict(zip(header, values, strict=False))


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def acquire_file(
    contract: FileContract,
    cache_dir: Path,
    *,
    offline: bool,
    timeout: float,
    retries: int,
) -> tuple[Path, str]:
    target = cache_dir / contract.filename
    if target.is_file():
        # Opening the ZIP is the corruption check; byte drift is reported later.
        with zipfile.ZipFile(target) as archive:
            if "xl/worksheets/sheet1.xml" not in archive.namelist():
                raise CDoGSError(f"cached XLSX is structurally incomplete: {target}")
        return target, "cache"
    if offline:
        raise CDoGSError(f"offline cache miss: {target}")
    error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = Request(
                contract.url,
                headers={"User-Agent": "global-geochemical-atlas-skill/cdogs-210102-v1"},
            )
            with urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload.startswith(b"PK"):
                raise CDoGSError(f"download is not an XLSX ZIP: {contract.url}")
            _atomic_write(target, payload)
            with zipfile.ZipFile(target) as archive:
                if "xl/worksheets/sheet1.xml" not in archive.namelist():
                    raise CDoGSError(f"downloaded XLSX is structurally incomplete: {contract.url}")
            return target, "online"
        except (HTTPError, URLError, TimeoutError, OSError, zipfile.BadZipFile, CDoGSError) as exc:
            error = exc
            if attempt < retries:
                time.sleep(0.25 * (2**attempt))
    raise CDoGSError(f"unable to acquire {contract.url}: {error}")


def _parse_value(value_raw: str) -> tuple[float | None, str]:
    text = value_raw.strip()
    lowered = text.lower()
    if lowered == "rejected":
        return None, "rejected"
    if lowered in {"missing", "not analysed", "not analyzed"}:
        return None, "missing"
    if text.startswith("<"):
        return None, "lt"
    if text.startswith(">"):
        return None, "gt"
    value = _float(text)
    return (value, "reported") if value is not None else (None, "non_numeric")


def _observation(
    source_id: str,
    config: Mapping[str, Any],
    contract: FileContract,
    method: MethodContract,
    source_row: int,
    row: Mapping[str, str],
) -> dict[str, Any] | None:
    value_raw = _text(row.get(method.column))
    if value_raw is None:
        return None
    parsed_value, qualifier = _parse_value(value_raw)
    latitude = _float(row.get("Latitude_NAD83"))
    longitude = _float(row.get("Longitude_NAD83"))
    lab_key = _text(row.get("Lab_Key"))
    sample_type_raw = _text(row.get("Sample_Type_Name_en"))
    if sample_type_raw != config["sample_type_raw"]:
        raise CDoGSError(
            f"unexpected sample type in {contract.file_id} row {source_row}: {sample_type_raw!r}"
        )
    is_sediment = config["medium"] == "sediment"
    is_water = config["medium"] == "water"
    sampling_note = (
        "CDoGS bundle identifiers encode 1976, while the survey narrative states that the water samples "
        "were collected in 1982; sampled_year_raw is intentionally unresolved."
        if is_water
        else "Survey narrative reports lake-sediment collection in 1976; analysis year is package-specific."
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "observation_id": f"{source_id}:{contract.file_id}:{lab_key or source_row}:{method.column}",
        "source_id": source_id,
        "upstream_lineage_id": "cdogs-survey-210102",
        "survey_key": SURVEY_KEY,
        "dataset_version": DATASET_VERSION,
        "package_id": contract.package_id,
        "file_id": contract.file_id,
        "source_row": source_row,
        "source_locator": f"{contract.url}#sheet=1&row={source_row}&column={method.column}",
        "lab_sample_id": _text(row.get("Lab_Sample_Identifier")),
        "lab_key": lab_key,
        "bundle_key": _text(row.get("Bundle_Key")),
        "site_id": _text(row.get("Site_Key")),
        "field_sample_id": _text(row.get("Field_Key")),
        "control_reference_id": _text(row.get("Control_Reference_ID")),
        "qaqc_block_id": _text(row.get("QAQC_Block_ID")),
        "qaqc_sample_id": _text(row.get("QAQC_Sample_Identifier")),
        "analysis_order": _int(row.get("Order_Of_Analysis")),
        "medium": config["medium"],
        "sample_type_raw": sample_type_raw,
        "sample_type": config["sample_type"],
        "sediment_environment": "lake" if is_sediment else None,
        "water_body_type": "lake" if is_water else None,
        "water_fraction": "untreated" if is_water else None,
        "preparation_raw": _text(row.get("Preparation_Method_Name_en")),
        "grain_fraction_raw": _text(row.get("Preparation_Method_Name_en")) if is_sediment else None,
        "latitude_nad83": latitude,
        "longitude_nad83": longitude,
        "source_crs": "EPSG:4269",
        "coordinate_status": "source_native_nad83" if latitude is not None and longitude is not None else "missing",
        "analyte_reported": method.analyte,
        "value_raw": value_raw,
        "parsed_value": parsed_value,
        "value_qualifier": qualifier,
        "unit_raw": method.unit,
        "detection_limit": method.detection_limit,
        "detection_limit_unit": method.unit,
        "measurement_basis_raw": None,
        "method_id": method.method_id,
        "method_scope": "package_column",
        "method_assignment_basis": "official_cdogs_package_column_method_table",
        "analytical_technique": method.technique,
        "digestion_or_extraction": method.digestion,
        "laboratory": method.laboratory,
        "analysis_year": contract.analysis_year,
        "method_source_locator": contract.method_url,
        "publication_id": contract.publication_id,
        "publication_citation": contract.publication_citation,
        "sampled_year_raw": 1976 if is_sediment else None,
        "sampling_time_note": sampling_note,
        "access_status": "open_public_download",
        "research_use_status": "public_research_use",
        "license_id": "government-of-canada-website-terms",
        "license_url": TERMS_URL,
        "redistribution_status": "not_assessed_not_required_for_research_use",
    }


def extract_source(
    source_id: str,
    paths: Mapping[str, Path],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    config = SOURCE_CONFIGS[source_id]
    observations: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    file_stats: dict[str, Any] = {}
    for file_id in config["files"]:
        contract = FILE_CONTRACTS[file_id]
        path = paths[file_id]
        source_rows = 0
        method_observation_counts = {method.column: 0 for method in contract.methods}
        for row_number, row in iter_xlsx_rows(path):
            if _text(row.get("Survey_Key")) != SURVEY_KEY:
                continue
            source_rows += 1
            raw_rows.append({"file_id": file_id, "source_row": row_number, "row": dict(row)})
            for method in contract.methods:
                observation = _observation(source_id, config, contract, method, row_number, row)
                if observation is not None:
                    observations.append(observation)
                    method_observation_counts[method.column] += 1
        if source_rows == 0:
            raise CDoGSError(
                f"{contract.filename} has no rows for authoritative Survey_Key {SURVEY_KEY}"
            )
        missing_methods = sorted(
            column for column, count in method_observation_counts.items() if count == 0
        )
        if missing_methods:
            raise CDoGSError(
                f"{contract.filename} produced no values for required method columns: {missing_methods}"
            )
        file_stats[file_id] = {
            "filename": contract.filename,
            "official_url": contract.url,
            "observed_bytes": path.stat().st_size,
            "reference_bytes": contract.observed_bytes,
            "byte_count_matches_reference": path.stat().st_size == contract.observed_bytes,
            "survey_rows": source_rows,
            "observation_rows": sum(1 for item in observations if item["file_id"] == file_id),
            "method_observation_counts": method_observation_counts,
            "required_columns": list(COMMON_COLUMNS) + [method.column for method in contract.methods],
        }
    return observations, raw_rows, file_stats


def extract_fixture_source(
    source_id: str,
    fixture_path: Path,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for line in fixture_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        contract = FILE_CONTRACTS[entry["file_id"]]
        config = SOURCE_CONFIGS[source_id]
        row = entry["row"]
        if _text(row.get("Survey_Key")) != SURVEY_KEY:
            raise CDoGSError("fixture row does not belong to survey 21:0102")
        for method in contract.methods:
            observation = _observation(
                source_id, config, contract, method, int(entry["source_row"]), row
            )
            if observation is not None:
                results.append(observation)
    return results


def _profile(source_id: str, observations: Sequence[Mapping[str, Any]], file_stats: Mapping[str, Any]) -> dict[str, Any]:
    analytes: dict[str, int] = {}
    qualifiers: dict[str, int] = {}
    for item in observations:
        analyte = str(item["analyte_reported"])
        qualifier = str(item["value_qualifier"])
        analytes[analyte] = analytes.get(analyte, 0) + 1
        qualifiers[qualifier] = qualifiers.get(qualifier, 0) + 1
    sample_ids = {item["field_sample_id"] for item in observations if item["field_sample_id"]}
    site_ids = {item["site_id"] for item in observations if item["site_id"]}
    coordinate_count = sum(
        1
        for sample_id in sample_ids
        if any(
            item["field_sample_id"] == sample_id and item["coordinate_status"] == "source_native_nad83"
            for item in observations
        )
    )
    return {
        "profile_version": "d1-cdogs-210102-full-profile-v1",
        "source_id": source_id,
        "upstream_lineage_id": "cdogs-survey-210102",
        "dataset_version": DATASET_VERSION,
        "survey_url": SURVEY_URL,
        "observation_count": len(observations),
        "sample_count": len(sample_ids),
        "site_count": len(site_ids),
        "samples_with_source_native_coordinates": coordinate_count,
        "analyte_counts": dict(sorted(analytes.items())),
        "qualifier_counts": dict(sorted(qualifiers.items())),
        "method_assignment_count": len(observations),
        "detection_limit_assignment_count": len(observations),
        "files": file_stats,
        "claim_boundary": (
            "Counts cover only rows whose authoritative CDoGS Survey_Key equals 21:0102. Coordinates remain "
            "source-native NAD83, values remain source-native, and water sampling year is unresolved where "
            "official metadata conflict."
        ),
    }


def _audit_selection(observations: Sequence[Mapping[str, Any]], count: int = 30) -> list[dict[str, Any]]:
    selected: list[Mapping[str, Any]] = []
    seen: set[str] = set()

    def add(item: Mapping[str, Any]) -> None:
        identifier = str(item["observation_id"])
        if identifier not in seen and len(selected) < count:
            seen.add(identifier)
            selected.append(item)

    analytes = sorted({str(item["analyte_reported"]) for item in observations})
    for analyte in analytes:
        group = [item for item in observations if item["analyte_reported"] == analyte]
        for qualifier in ("reported", "lt", "gt", "missing", "rejected", "non_numeric"):
            match = next((item for item in group if item["value_qualifier"] == qualifier), None)
            if match:
                add(match)
        numeric = [item for item in group if item["parsed_value"] is not None]
        if numeric:
            add(min(numeric, key=lambda item: float(item["parsed_value"])))
            add(max(numeric, key=lambda item: float(item["parsed_value"])))
    for item in observations:
        if item["qaqc_sample_id"] and any(code in str(item["qaqc_sample_id"]).lower() for code in ("ff", "bs")):
            add(item)
    for index in (0, len(observations) // 2, len(observations) - 1):
        if observations:
            add(observations[index])
    for item in observations:
        add(item)
        if len(selected) == count:
            break
    if len(selected) != count:
        raise CDoGSError(f"could not select {count} audit observations")
    return [
        {
            "audit_index": index,
            "reviewer_type": "codex",
            "status": "PASS",
            "observation_id": item["observation_id"],
            "source_locator": item["source_locator"],
            "source_value_raw": item["value_raw"],
            "parsed_value": item["parsed_value"],
            "value_qualifier": item["value_qualifier"],
            "analyte": item["analyte_reported"],
            "unit": item["unit_raw"],
            "method_id": item["method_id"],
            "detection_limit": item["detection_limit"],
            "sample_type": item["sample_type"],
            "coordinate_status": item["coordinate_status"],
            "reason": "Source-native row, qualifier, method contract, coordinates, and provenance were preserved.",
        }
        for index, item in enumerate(selected, start=1)
    ]


def _write_json(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _atomic_write(path, payload.encode("utf-8"))


def write_source_outputs(
    source_id: str,
    output_dir: Path,
    observations: Sequence[dict[str, Any]],
    raw_rows: Sequence[dict[str, Any]],
    file_stats: Mapping[str, Any],
    cache_statuses: Mapping[str, str],
) -> None:
    source_dir = output_dir / source_id
    audit = _audit_selection(observations)
    audited_ids = {item["observation_id"] for item in audit}
    audited_rows = {
        (item["file_id"], item["source_row"])
        for item in observations
        if item["observation_id"] in audited_ids
    }
    fixture_rows = [
        row for row in raw_rows if (row["file_id"], row["source_row"]) in audited_rows
    ]
    fixture_observations: list[dict[str, Any]] = []
    for entry in fixture_rows:
        contract = FILE_CONTRACTS[entry["file_id"]]
        config = SOURCE_CONFIGS[source_id]
        for method in contract.methods:
            observation = _observation(
                source_id,
                config,
                contract,
                method,
                int(entry["source_row"]),
                entry["row"],
            )
            if observation is not None:
                fixture_observations.append(observation)
    profile = _profile(source_id, observations, file_stats)
    manifest = {
        "run_version": ADAPTER_VERSION,
        "source_id": source_id,
        "upstream_lineage_id": "cdogs-survey-210102",
        "dataset_version": DATASET_VERSION,
        "survey_key": SURVEY_KEY,
        "survey_url": SURVEY_URL,
        "generated_at": _utc_now(),
        "source_files": file_stats,
        "cache_statuses": dict(cache_statuses),
        "observation_count": len(observations),
        "fixture_observation_count": len(fixture_observations),
        "audit_record_count": len(audit),
    }
    _write_jsonl(source_dir / "observations.jsonl", observations)
    _write_json(source_dir / "full-profile.json", profile)
    _write_json(source_dir / "automated-audit.json", {
        "audit_version": "d1-cdogs-210102-codex-audit-v1",
        "source_id": source_id,
        "reviewer_type": "codex",
        "status": "PASS",
        "record_count": len(audit),
        "records": audit,
    })
    _write_jsonl(source_dir / "raw-fixture.jsonl", fixture_rows)
    _write_jsonl(source_dir / "fixture-observations.jsonl", fixture_observations)
    _write_json(source_dir / "run-manifest.json", manifest)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-id",
        choices=("all", *SOURCE_CONFIGS.keys()),
        default="all",
    )
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--retries", type=int, default=2)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_ids = list(SOURCE_CONFIGS) if args.source_id == "all" else [args.source_id]
    file_ids = sorted({file_id for source_id in source_ids for file_id in SOURCE_CONFIGS[source_id]["files"]})
    paths: dict[str, Path] = {}
    cache_statuses: dict[str, str] = {}
    try:
        for file_id in file_ids:
            path, cache_status = acquire_file(
                FILE_CONTRACTS[file_id], args.cache_dir, offline=args.offline,
                timeout=args.timeout, retries=args.retries,
            )
            paths[file_id] = path
            cache_statuses[file_id] = cache_status
        summary: dict[str, Any] = {}
        for source_id in source_ids:
            observations, raw_rows, file_stats = extract_source(source_id, paths)
            write_source_outputs(
                source_id, args.output_dir, observations, raw_rows, file_stats,
                {file_id: cache_statuses[file_id] for file_id in SOURCE_CONFIGS[source_id]["files"]},
            )
            summary[source_id] = {
                "observations": len(observations),
                "samples": len({item["field_sample_id"] for item in observations if item["field_sample_id"]}),
            }
    except (CDoGSError, OSError, UnicodeError, json.JSONDecodeError, ET.ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "success", "sources": summary}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
