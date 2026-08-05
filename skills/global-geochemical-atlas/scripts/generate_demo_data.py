#!/usr/bin/env python3
"""Generate deterministic, provenance-complete D1 demo slices from verified caches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from source_adapters import DownloadedFile, RawRecord, SourceAdapterError, get_adapter, stable_record_id

DEMO_VERSION = "d1-demo-slice-v2"
DEFAULT_ANALYTES = ("As", "Cu", "Ni", "Zn")
USGS_METADATA_URL = "https://pubs.usgs.gov/ds/801/downloads/Appendix_5_Metadata.pdf"
USGS_METHODS = {
    "As": {
        "analytical_method": "hydride-generation atomic absorption spectrometry (HG-AAS)",
        "method_family": "aas",
        "digestion_or_extraction": "sodium peroxide and sodium hydroxide fusion",
        "measurement_basis": "total concentration in <2 mm soil fraction",
        "metadata_section": "Appendix 5, Data Quality Information / Analytical Methods",
    },
    "Cu": {
        "analytical_method": "inductively coupled plasma-atomic emission spectrometry (ICP-AES)",
        "method_family": "icp_oes",
        "digestion_or_extraction": "near-total HCl-HNO3-HClO4-HF digestion",
        "measurement_basis": "near-total concentration in <2 mm soil fraction",
        "metadata_section": "Appendix 5, Data Quality Information / Analytical Methods",
    },
    "Ni": {
        "analytical_method": "inductively coupled plasma-atomic emission spectrometry (ICP-AES)",
        "method_family": "icp_oes",
        "digestion_or_extraction": "near-total HCl-HNO3-HClO4-HF digestion",
        "measurement_basis": "near-total concentration in <2 mm soil fraction",
        "metadata_section": "Appendix 5, Data Quality Information / Analytical Methods",
    },
    "Zn": {
        "analytical_method": "inductively coupled plasma-atomic emission spectrometry (ICP-AES)",
        "method_family": "icp_oes",
        "digestion_or_extraction": "near-total HCl-HNO3-HClO4-HF digestion",
        "measurement_basis": "near-total concentration in <2 mm soil fraction",
        "metadata_section": "Appendix 5, Data Quality Information / Analytical Methods",
    },
}
INPUT_COLUMNS = (
    "record_id",
    "source_record_id",
    "sample_id",
    "element_or_analyte",
    "analyte_reported",
    "value",
    "unit",
    "medium",
    "material",
    "measurement_basis",
    "value_qualifier",
    "missing_reason",
    "detection_limit",
    "detection_limit_unit",
    "original_latitude_raw",
    "original_longitude_raw",
    "latitude",
    "longitude",
    "source_crs",
    "coordinate_transform_method",
    "coordinate_uncertainty_m",
    "geologic_unit",
    "analytical_method",
    "method_family",
    "digestion_or_extraction",
    "laboratory",
    "license",
    "source_tier",
    "source_id",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_file",
    "source_row",
    "source_locator",
    "file_sha256",
    "sampled_at",
    "sample_depth_min_m",
    "sample_depth_max_m",
    "grain_fraction",
)


class DemoError(RuntimeError):
    """Raised when a deterministic demo cannot be generated safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _parse_analytes(value: str) -> tuple[str, ...]:
    analytes: list[str] = []
    for token in value.split(","):
        text = token.strip()
        if not re.fullmatch(r"[A-Z][a-z]?", text):
            raise argparse.ArgumentTypeError(f"invalid element symbol: {text or '<blank>'}")
        if text not in analytes:
            analytes.append(text)
    if not analytes:
        raise argparse.ArgumentTypeError("at least one element is required")
    return tuple(analytes)


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        west, south, east, north = (float(item.strip()) for item in value.split(","))
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north") from exc
    if not all(math.isfinite(item) for item in (west, south, east, north)):
        raise argparse.ArgumentTypeError("bbox values must be finite")
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox is outside longitude/latitude bounds")
    return west, south, east, north


def _inside_bbox(latitude: str, longitude: str, bbox: tuple[float, float, float, float] | None) -> bool:
    if bbox is None:
        return True
    lat = _reported_float(latitude)
    lon = _reported_float(longitude)
    if lat is None or lon is None:
        return False
    west, south, east, north = bbox
    longitude_inside = west <= lon <= east if west <= east else lon >= west or lon <= east
    return longitude_inside and south <= lat <= north


def _validate_generated_at(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("generated-at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("generated-at must include a timezone")
    return candidate


def _source_row(record: RawRecord) -> tuple[str, str]:
    file_locator, separator, row_text = record.source_locator.partition("#row=")
    if not separator or not row_text.isdigit():
        raise DemoError(f"source locator has no numeric row fragment: {record.source_locator}")
    return file_locator, row_text


def _provenance_fields(
    record: RawRecord,
    downloaded: DownloadedFile,
    candidate: Any,
    analyte: str,
) -> dict[str, str]:
    source_file, source_row = _source_row(record)
    return {
        "analyte_reported": analyte,
        "source_id": record.source_id,
        "dataset_title": candidate.title,
        "dataset_doi": candidate.dataset_doi or "",
        "dataset_version": candidate.version,
        "source_file": source_file,
        "source_row": source_row,
        "source_locator": record.source_locator,
        "file_sha256": downloaded.sha256,
        "license": candidate.license_id,
    }


def _reported_measurement(value: Any) -> tuple[str, str, str, str] | None:
    """Return raw value, canonical qualifier, limit and missing reason without imputation."""

    raw = str(value or "").strip()
    if not raw:
        return None
    compact = raw.replace(",", "").replace("−", "-")
    match = re.fullmatch(r"(<=|>=|<|>)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)", compact)
    if match:
        number = _reported_float(match.group(2))
        if number is None:
            return None
        qualifier = match.group(1) or ""
        limit = format(number, ".12g") if qualifier in {"<", "<=", ">", ">="} else ""
        return raw, qualifier, limit, ""
    missing = {
        "INS": "insufficient_sample",
        "N.S.": "not_sampled",
        "NS": "not_sampled",
        "N.D.": "not_detected",
        "ND": "not_detected",
        "NA": "not_reported",
    }.get(compact.upper())
    if missing:
        return raw, "", "", missing
    return None


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
        "source_file_sha256": downloaded.sha256,
        "source_file_bytes": downloaded.bytes,
        "source_file_url": downloaded.source_url,
        "dataset_title": candidate.title,
        "dataset_doi": candidate.dataset_doi,
        "dataset_version": candidate.version,
        "retrieved_at": downloaded.retrieved_at,
        "license": candidate.license_id,
        "analyte_reported": analyte,
        "generation_version": DEMO_VERSION,
        "evidence_version": "geochemical-record-evidence-v1",
        "evidence_status": "verified_source_file_and_row",
    }


def georoc_demo(
    records: Iterable[RawRecord],
    files: Mapping[str, DownloadedFile],
    references: Mapping[str, Mapping[str, str]],
    candidate: Any,
    observation_limit: int,
    analytes: Sequence[str],
    bbox: tuple[float, float, float, float] | None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int, int]:
    if observation_limit % len(analytes) != 0:
        raise DemoError("GEOROC observation limit must be divisible by the element count")
    per_analyte_limit = observation_limit // len(analytes)
    selected_per_analyte: Counter[str] = Counter()
    rows: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    raw_source_rows = 0
    for record in records:
        raw_source_rows += 1
        if all(selected_per_analyte[item] >= per_analyte_limit for item in analytes):
            continue
        material = _strip_citation_suffix(record.fields.get("MATERIAL")).upper()
        if material != "WR":
            continue
        reported_latitude = _exact_georoc_coordinate(record, "LATITUDE MIN", "LATITUDE MAX")
        reported_longitude = _exact_georoc_coordinate(record, "LONGITUDE MIN", "LONGITUDE MAX")
        if not reported_latitude or not reported_longitude:
            continue
        if not _inside_bbox(reported_latitude, reported_longitude, bbox):
            continue
        sample_id = str(record.fields.get("SAMPLE NAME") or "").strip()
        if not sample_id:
            continue
        downloaded = files.get(str(record.fields.get("_source_file")))
        if downloaded is None:
            raise DemoError(f"GEOROC record references an unknown member: {record.source_locator}")
        for analyte in analytes:
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
                    "analyte_reported": analyte,
                    "value": original_value,
                    "unit": "ppm",
                    "medium": "rock",
                    "material": "whole rock",
                    "measurement_basis": "GEOROC_precompiled_selected_value",
                    "value_qualifier": "",
                    "missing_reason": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "original_latitude_raw": reported_latitude,
                    "original_longitude_raw": reported_longitude,
                    "latitude": "",
                    "longitude": "",
                    "source_crs": "",
                    "coordinate_transform_method": "",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": str(record.fields.get("LOCATION") or "").strip(),
                    "analytical_method": "",
                    "method_family": "",
                    "digestion_or_extraction": "",
                    "laboratory": "",
                    "source_tier": "official_curated",
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": "",
                    **_provenance_fields(record, downloaded, candidate, analyte),
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
                    "selection_rule": (
                        f"whole-rock; exact reported point coordinates; balanced {','.join(analytes)}; source order"
                    ),
                    "scientific_note": "GEOROC precompiled selected value; not every replicate determination.",
                    "coordinate_evidence": {
                        "reported_latitude": reported_latitude,
                        "reported_longitude": reported_longitude,
                        "datum_status": "not_declared_in_reviewed_public_metadata",
                        "canonicalization_status": "withheld_pending_datum_verification",
                        "claim_boundary": "Coordinates are retained as reported and are not asserted to be WGS 84.",
                    },
                }
            )
            evidence.append(entry)
            selected_source_rows.add(record.source_record_id)
            selected_per_analyte[analyte] += 1
    if len(rows) != observation_limit:
        raise DemoError(f"GEOROC produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence, len(selected_source_rows), raw_source_rows


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
    records: Iterable[RawRecord],
    files: Mapping[str, DownloadedFile],
    candidate: Any,
    observation_limit: int,
    analytes: Sequence[str],
    bbox: tuple[float, float, float, float] | None,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], int, int]:
    layers = ("top-0-5cm", "a-horizon", "c-horizon")
    unsupported = sorted(set(analytes) - set(USGS_METHODS))
    if unsupported:
        raise DemoError(
            "USGS method metadata has not been encoded for requested elements: " + ", ".join(unsupported)
        )
    if observation_limit % (len(layers) * len(analytes)) != 0:
        raise DemoError("USGS observation limit must be divisible by layer count times element count")
    site_limit = observation_limit // (len(layers) * len(analytes))
    candidates: dict[str, list[tuple[RawRecord, DownloadedFile, list[tuple[str, str, str, str, str]]]]] = {
        layer: [] for layer in layers
    }
    first_censored: dict[
        str, tuple[RawRecord, DownloadedFile, list[tuple[str, str, str, str, str]]] | None
    ] = {layer: None for layer in layers}
    raw_source_rows = 0
    for record in records:
        raw_source_rows += 1
        layer = str(record.fields.get("_soil_layer") or "")
        if layer not in layers:
            continue
        latitude = str(record.fields.get("Latitude") or "").strip()
        longitude = str(record.fields.get("Longitude") or "").strip()
        if _reported_float(latitude) is None or _reported_float(longitude) is None:
            continue
        if not _inside_bbox(latitude, longitude, bbox):
            continue
        prefix = {"top-0-5cm": "Top5_", "a-horizon": "A_", "c-horizon": "C_"}[layer]
        downloaded = files.get(str(record.fields.get("_source_file")))
        if downloaded is None:
            raise DemoError(f"USGS record references an unknown file: {record.source_locator}")
        units = record.fields.get("_units")
        if not isinstance(units, Mapping):
            raise DemoError("USGS record has no units mapping")
        measurements: list[tuple[str, str, str, str, str]] = []
        for analyte in analytes:
            field = f"{prefix}{analyte}"
            parsed = _reported_measurement(record.fields.get(field))
            unit = str(units.get(field) or "").strip()
            if parsed is None or parsed[3] or not unit:
                break
            raw, qualifier, detection_limit, _ = parsed
            measurements.append((analyte, raw, unit, qualifier, detection_limit))
        if len(measurements) != len(analytes):
            continue
        item = (record, downloaded, measurements)
        if len(candidates[layer]) < site_limit:
            candidates[layer].append(item)
        if first_censored[layer] is None and any(value[3] for value in measurements):
            first_censored[layer] = item

    # Exercise the censored-value path when the source offers a suitable row, without inventing a limit.
    for layer in layers:
        if len(candidates[layer]) != site_limit:
            raise DemoError(f"USGS produced only {len(candidates[layer])} usable sites for {layer}")
        if not any(any(value[3] for value in item[2]) for item in candidates[layer]):
            replacement = first_censored[layer]
            if replacement is not None and all(replacement[0].source_record_id != item[0].source_record_id for item in candidates[layer]):
                candidates[layer][-1] = replacement

    rows: list[dict[str, str]] = []
    evidence: list[dict[str, Any]] = []
    selected_source_rows: set[str] = set()
    for layer in layers:
        prefix = {"top-0-5cm": "Top5_", "a-horizon": "A_", "c-horizon": "C_"}[layer]
        for record, downloaded, analyte_values in candidates[layer]:
            latitude = str(record.fields.get("Latitude") or "").strip()
            longitude = str(record.fields.get("Longitude") or "").strip()
            depth_min, depth_max = _depth_m(record)
            sample_id = str(record.fields.get(f"{prefix}LabID") or record.fields.get("SiteID") or "").strip()
            for analyte, original_value, unit, qualifier, detection_limit in analyte_values:
                method = USGS_METHODS[analyte]
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
                        "analyte_reported": analyte,
                        "value": original_value,
                        "unit": unit,
                        "medium": "soil",
                        "material": f"soil:{layer}",
                        "measurement_basis": method["measurement_basis"],
                        "value_qualifier": qualifier,
                        "missing_reason": "",
                        "detection_limit": detection_limit,
                        "detection_limit_unit": unit if detection_limit else "",
                        "original_latitude_raw": latitude,
                        "original_longitude_raw": longitude,
                        "latitude": latitude,
                        "longitude": longitude,
                        "source_crs": "EPSG:4326",
                        "coordinate_transform_method": "identity; source metadata declares WGS 84",
                        "coordinate_uncertainty_m": "",
                        "geologic_unit": "",
                        "analytical_method": method["analytical_method"],
                        "method_family": method["method_family"],
                        "digestion_or_extraction": method["digestion_or_extraction"],
                        "laboratory": "",
                        "source_tier": "government",
                        "sampled_at": str(record.fields.get("CollDate") or "").strip(),
                        "sample_depth_min_m": depth_min,
                        "sample_depth_max_m": depth_max,
                        "grain_fraction": "<2 mm",
                        **_provenance_fields(record, downloaded, candidate, analyte),
                    }
                )
                entry = _base_evidence(record, downloaded, candidate, record_id, analyte)
                entry.update(
                    {
                        "article_citations": [candidate.registry_entry["citation"]],
                        "article_dois": [candidate.dataset_doi],
                        "selection_rule": (
                            f"balanced source rows per layer; analytes {','.join(analytes)}; source order; "
                            "include a reported censored value when available"
                        ),
                        "soil_layer": layer,
                        "reported_value": original_value,
                        "reported_qualifier": qualifier or None,
                        "reported_detection_limit": detection_limit or None,
                        "measurement_evidence": {
                            **method,
                            "metadata_url": USGS_METADATA_URL,
                        },
                        "coordinate_evidence": {
                            "source_crs": "EPSG:4326",
                            "metadata_url": USGS_METADATA_URL,
                            "metadata_section": "Appendix 5, Spatial Reference Information",
                        },
                    },
                )
                evidence.append(entry)
                selected_source_rows.add(record.source_record_id)
    if len(rows) != observation_limit:
        raise DemoError(f"USGS produced {len(rows)} observations, expected {observation_limit}")
    return rows, evidence, len(selected_source_rows), raw_source_rows


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
    if args.source == "georoc-archaean" and args.bbox is not None:
        raise DemoError(
            "GEOROC bbox filtering is disabled because the reviewed public metadata does not declare a datum"
        )
    output_paths = {
        "demo_input": args.output_dir / "demo_input.csv",
        "sources": args.output_dir / "sources.jsonl",
        "run_manifest": args.output_dir / "run_manifest.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing and not args.overwrite:
        raise DemoError(f"output files already exist; use --overwrite after review: {existing}")

    adapter = get_adapter(args.source)
    request = {
        "sources": [args.source],
        "elements": list(args.elements),
        "region": {"bbox": list(args.bbox)} if args.bbox else None,
    }
    candidate = adapter.discover(request)[0]
    downloaded = adapter.download(candidate, args.cache_dir, mode=args.mode)
    files = {item.path.name: item for item in downloaded}
    if args.source == "georoc-archaean":
        references = {item.path.name: _georoc_reference_map(item.path) for item in downloaded}
        rows, evidence, selected_source_rows, raw_source_rows = georoc_demo(
            adapter.parse(downloaded), files, references, candidate, args.observations, args.elements, args.bbox
        )
    elif args.source == "usgs-conus-soil":
        rows, evidence, selected_source_rows, raw_source_rows = usgs_demo(
            adapter.parse(downloaded), files, candidate, args.observations, args.elements, args.bbox
        )
    else:
        raise DemoError(f"unsupported source: {args.source}")

    atomic_text(output_paths["demo_input"], _csv_text(rows))
    atomic_text(output_paths["sources"], _jsonl_text(evidence))
    outputs = [
        {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for key, path in output_paths.items()
        if key != "run_manifest"
    ]
    manifest = {
        "demo_generation_version": DEMO_VERSION,
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
            "analytes": list(args.elements),
            "bbox": list(args.bbox) if args.bbox else None,
            "mode": args.mode,
            "filter_execution": "local deterministic filtering after verified source parsing",
        },
        "source_files": [
            {
                "filename": item.path.name,
                "source_url": item.source_url,
                "bytes": item.bytes,
                "sha256": item.sha256,
                "retrieved_at": item.retrieved_at,
            }
            for item in downloaded
        ],
        "record_counts": {
            "raw_source_rows": raw_source_rows,
            "selected_source_rows": selected_source_rows,
            "emitted_observations": len(rows),
        },
        "outputs": outputs,
        "warnings": [
            "This is a deterministic demonstration slice, not a statistically representative sample.",
            "Scientific normalization, QC, confidence and anomaly decisions are owned by D2.",
            (
                "GEOROC coordinates remain non-canonical until their datum is verified."
                if args.source == "georoc-archaean"
                else "USGS methods, WGS 84 CRS and qualifiers are decoded from Appendix 5 metadata."
            ),
        ],
        "failures": [],
    }
    atomic_json(output_paths["run_manifest"], manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=("georoc-archaean", "usgs-conus-soil"))
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--observations", type=int, default=48)
    parser.add_argument(
        "--elements",
        type=_parse_analytes,
        default=DEFAULT_ANALYTES,
        help="Comma-separated element symbols; default: As,Cu,Ni,Zn",
    )
    parser.add_argument(
        "--bbox",
        type=_parse_bbox,
        help="Optional west,south,east,north filter; antimeridian crossing is supported",
    )
    parser.add_argument(
        "--generated-at",
        required=True,
        type=_validate_generated_at,
        help="Explicit ISO-8601 time retained in the reproducible manifest",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    minimum = len(args.elements) * (3 if args.source == "usgs-conus-soil" else 1)
    if args.observations < minimum or args.observations > 1000:
        print(
            f"generate_demo_data: --observations must be between {minimum} and 1000 for this request",
            file=sys.stderr,
        )
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
