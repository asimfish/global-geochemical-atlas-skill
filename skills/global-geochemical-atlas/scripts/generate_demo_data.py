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
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from source_adapters import DownloadedFile, RawRecord, SourceAdapterError, get_adapter, stable_record_id

DEMO_VERSION = "d1-demo-slice-v1"
ANALYTES = ("As", "Cu", "Ni", "Zn")
MARCHEM_REVIEW_SAMPLE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "candidate-audits"
    / "marchem-inorganic-20260805T102709Z.json"
)
INPUT_COLUMNS = (
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
        raw_records = list(adapter.parse(downloaded))
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
            "analytes": list(ANALYTES),
            "mode": args.mode,
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
            "raw_source_rows": len(raw_records),
            "selected_source_rows": selected_source_rows,
            "emitted_observations": len(rows),
        },
        "outputs": outputs,
        "warnings": [
            "This is a deterministic demonstration slice, not a statistically representative sample.",
            "Scientific normalization, QC, confidence and anomaly decisions are owned by D2.",
            *(
                [
                    "MarChem values are dry-weight partial nitric-acid extractions, not total concentrations.",
                    "Accreditation status varies by batch and remains attached to observation evidence.",
                ]
                if args.source == "norway-marchem"
                else []
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
        choices=("georoc-archaean", "usgs-conus-soil", "norway-marchem"),
    )
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument(
        "--archive",
        type=Path,
        help="Explicit local copy of the registered content-addressed MarChem snapshot",
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
