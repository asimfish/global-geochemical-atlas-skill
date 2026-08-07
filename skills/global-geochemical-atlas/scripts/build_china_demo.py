#!/usr/bin/env python3
"""Build the hash-pinned China regional fixture (TPDC soil + Zenodo river sediment).

The builder produces ``fixtures/china/combined-v1`` from two verified originals:

1. TPDC China mountain-soil workbook (DOI 10.11888/Terre.tpdc.302620) parsed by
   the registered adapter into the full 6,570-observation slice (1,314 samples
   x Cr/Cu/Ni/Pb/Zn).
2. Zenodo record 7098563 ``Data Set S2.xlsx`` (DOI 10.5281/zenodo.7098563)
   parsed here into the full 558-observation slice (93 residual-fraction
   sediment samples x As/Cr/Cu/Ni/Pb/Zn).

Both inputs are refused unless their bytes and SHA-256 match the registered
values, so the emitted fixture is reproducible byte-for-byte. Zenodo S2 does
not publish sampling coordinates: its records stay database-only and are never
mapped. TPDC reports GPS coordinates without a declared datum: canonical
coordinates stay empty and mapping requires ``--coordinate-mode reported``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import generate_demo_data as demos
import source_adapters
import standardize_geochemistry as standardizer
import v4_semantics

COMBINED_VERSION = "d1-china-combined-v1"
ZENODO_GENERATION_VERSION = "d1-china-zenodo-s2-v1"
ZENODO_SOURCE_ID = "zenodo-yangtze-yellow-river-sediment"
TPDC_SOURCE_ID = "tpdc-china-mountain-soil"
CHINA_SOURCE_ORDER = (TPDC_SOURCE_ID, ZENODO_SOURCE_ID)
EXPECTED_MEDIA = {TPDC_SOURCE_ID: "soil", ZENODO_SOURCE_ID: "sediment"}
TPDC_FULL_OBSERVATIONS = 6570

ZENODO_S2_FILENAME = "Data Set S2.xlsx"
ZENODO_S2_BYTES = 76596
ZENODO_S2_SHA256 = "413f54f6544967d1d96b9eacfbeae41ba410a8c4b0375bdfaabc1293fd6fadd2"
ZENODO_S2_MD5 = "md5:f71702e1fc28c92ad4fcc139ce77b934"
ZENODO_S2_URL = (
    "https://zenodo.org/api/records/7098563/files/Data%20Set%20S2.xlsx/content"
)
ZENODO_TERMS_VERIFIED_AT = "2026-08-08T00:00:00Z"
ZENODO_TARGET_ANALYTES = ("As", "Cr", "Cu", "Ni", "Pb", "Zn")
ZENODO_EXPECTED_SAMPLE_ROWS = 93
ZENODO_EXPECTED_OBSERVATIONS = len(ZENODO_TARGET_ANALYTES) * ZENODO_EXPECTED_SAMPLE_ROWS

ZENODO_REGISTRY_ENTRY: dict[str, Any] = {
    "source_id": ZENODO_SOURCE_ID,
    "title": (
        "Evaluation of Grain size, Amorphous Fe-Mn Oxides, and Chemical "
        "Weathering Effects on Geochemical Identification of the Yangtze "
        "River and Yellow River Sediments"
    ),
    "publisher": (
        "Zenodo deposit by Chao Wu, State Key Laboratory of Isotope "
        "Geochemistry, Guangzhou Institute of Geochemistry, Chinese Academy "
        "of Sciences"
    ),
    "dataset_doi": "10.5281/zenodo.7098563",
    "dataset_version": "zenodo-record-7098563-rev2-2022-09-21",
    "landing_page": "https://zenodo.org/records/7098563",
    "citation": (
        "Wu, Chao (2022). Evaluation of Grain size, Amorphous Fe-Mn Oxides, "
        "and Chemical Weathering Effects on Geochemical Identification of the "
        "Yangtze River and Yellow River Sediments [Data set]. Zenodo. "
        "https://doi.org/10.5281/zenodo.7098563"
    ),
    "license": {
        "spdx": "CC-BY-4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "evidence": "Zenodo record metadata declares license id cc-by-4.0",
    },
    "media": ["sediment"],
    "target_analytes": {analyte: analyte for analyte in ZENODO_TARGET_ANALYTES},
    "download": {
        "files": [
            {
                "file_id": "data-set-s2",
                "filename": ZENODO_S2_FILENAME,
                "url": ZENODO_S2_URL,
                "bytes": ZENODO_S2_BYTES,
                "expected_sha256": ZENODO_S2_SHA256,
                "publisher_checksum": ZENODO_S2_MD5,
            }
        ]
    },
    "unit_evidence": (
        "The workbook declares no unit row. The concentration unit ug/g is "
        "verified at build time by aligning the embedded BHVO-2/AGV-2/W-2/"
        "GSP-2 'Preferred values' rows with certified ug/g reference values "
        "and their 'Measured values' rows within tolerance."
    ),
    "coordinate_evidence": (
        "Data Set S2 publishes no sampling coordinates; records remain "
        "database-only and are excluded from every map layer (fail closed)."
    ),
    "expected_counts": {
        "sample_rows": ZENODO_EXPECTED_SAMPLE_ROWS,
        "target_observations": ZENODO_EXPECTED_OBSERVATIONS,
        "target_value_counts": {
            analyte: ZENODO_EXPECTED_SAMPLE_ROWS for analyte in ZENODO_TARGET_ANALYTES
        },
        "leach_groups": {"HCl": 480, "AC": 78},
    },
}

# Certified reference values (ug/g) used to verify the undeclared workbook
# unit. GeoReM/USGS preferred values as published in the workbook QC block.
ZENODO_QC_PREFERRED = {
    ("BHVO-2", "Cr"): 299.0,
    ("BHVO-2", "Cu"): 127.0,
    ("BHVO-2", "Ni"): 126.0,
    ("BHVO-2", "Zn"): 103.0,
    ("BHVO-2", "Pb"): 1.6,
    ("AGV-2", "Cr"): 17.0,
    ("AGV-2", "Cu"): 53.0,
    ("AGV-2", "Ni"): 20.0,
    ("AGV-2", "Zn"): 86.0,
    ("AGV-2", "Pb"): 13.2,
}
ZENODO_QC_TOLERANCE = 0.20

ZENODO_LABEL_RE = re.compile(
    r"^(?P<leach>HCl|AC)-residual (?P<sample>HH-\d+|CJ-\d+|CJ Sand-\d+)\s*"
    r"(?P<fraction>.*)$"
)
NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")

CHINA_REQUEST: dict[str, Any] = {
    "elements": ["As", "Cr", "Cu", "Ni", "Pb", "Zn"],
    "region": {"bbox": [73.0, 18.0, 135.0, 54.0]},
    "media": ["soil", "sediment"],
    "sources": "auto",
    "license_policy": "open_only",
    "research_use_policy": "permitted_research",
    "minimum_evidence_tier": "D",
    "minimum_use_mode": "normalized_analysis",
    "max_records": 50000,
    "offline": True,
    "output_formats": ["csv", "json", "geojson", "html_map"],
}


class ChinaDemoError(RuntimeError):
    """Raised when the pinned China fixture cannot be built exactly."""


def river_system(sample: str) -> str:
    return (
        "Yellow River (Huanghe)"
        if sample.startswith("HH")
        else "Yangtze River (Changjiang)"
    )


def verify_zenodo_file(path: Path) -> None:
    if not path.exists():
        raise ChinaDemoError(f"Zenodo S2 workbook is missing: {path}")
    size = path.stat().st_size
    if size != ZENODO_S2_BYTES:
        raise ChinaDemoError(
            f"Zenodo S2 byte count changed: expected {ZENODO_S2_BYTES}, found {size}"
        )
    observed = demos.sha256_file(path)
    if observed != ZENODO_S2_SHA256:
        raise ChinaDemoError(
            f"Zenodo S2 SHA-256 changed: expected {ZENODO_S2_SHA256}, found {observed}"
        )


def parse_zenodo_s2(path: Path) -> list[dict[str, Any]]:
    """Return one entry per verified sample row with all target values."""

    rows = source_adapters.TpdcChinaMountainSoilAdapter._xlsx_rows(path)
    by_row = {number: row for number, row in rows}
    for required in (1, 6, 12):
        if required not in by_row:
            raise ChinaDemoError(f"Zenodo S2 structure changed: row {required} missing")
    if by_row[1][:1] != ["Preferred values"] or by_row[6][:1] != ["Measured values"]:
        raise ChinaDemoError("Zenodo S2 QC block headers changed")
    headers = by_row[12]
    if (
        headers[:1] != [""]
        or by_row[1][1:] != headers[1:]
        or by_row[6][1:] != headers[1:]
    ):
        raise ChinaDemoError("Zenodo S2 element headers changed between blocks")
    missing = [item for item in ZENODO_TARGET_ANALYTES if item not in headers]
    if missing:
        raise ChinaDemoError(f"Zenodo S2 lacks target analyte columns: {missing}")
    columns = {analyte: headers.index(analyte) for analyte in ZENODO_TARGET_ANALYTES}

    qc_rows = {
        block: {by_row[number][0]: by_row[number] for number in numbers}
        for block, numbers in (("preferred", (2, 3, 4, 5)), ("measured", (7, 8, 9, 10)))
    }
    for block, table in qc_rows.items():
        if set(table) != {"BHVO-2", "AGV-2", "W-2", "GSP-2"}:
            raise ChinaDemoError(
                f"Zenodo S2 QC {block} standards changed: {sorted(table)}"
            )
    checks = 0
    for (standard, analyte), certified in ZENODO_QC_PREFERRED.items():
        index = columns[analyte]
        preferred = float(qc_rows["preferred"][standard][index])
        measured = float(qc_rows["measured"][standard][index])
        for label, value in (("preferred", preferred), ("measured", measured)):
            if abs(value - certified) > ZENODO_QC_TOLERANCE * certified:
                raise ChinaDemoError(
                    f"Zenodo S2 unit verification failed: {standard} {analyte} "
                    f"{label} value {value} is outside {ZENODO_QC_TOLERANCE:.0%} "
                    f"of the certified ug/g value {certified}"
                )
        checks += 1
    if checks != len(ZENODO_QC_PREFERRED):
        raise ChinaDemoError("Zenodo S2 QC alignment did not run for every standard")

    samples: list[dict[str, Any]] = []
    seen_labels: set[str] = set()
    for number, row in rows:
        if number < 13:
            continue
        if not any(cell.strip() for cell in row):
            continue
        label = row[0].strip()
        match = ZENODO_LABEL_RE.match(label)
        if match is None:
            raise ChinaDemoError(
                f"Zenodo S2 sample label changed at row {number}: {label!r}"
            )
        if label in seen_labels:
            raise ChinaDemoError(
                f"Zenodo S2 sample label duplicated at row {number}: {label!r}"
            )
        seen_labels.add(label)
        values: dict[str, str] = {}
        for analyte, index in columns.items():
            raw = row[index].strip() if index < len(row) else ""
            if not NUMERIC_RE.match(raw):
                raise ChinaDemoError(
                    f"Zenodo S2 {analyte} is not numeric at row {number}: {raw!r}"
                )
            values[analyte] = raw
        samples.append(
            {
                "row": number,
                "label": label,
                "leach": match.group("leach"),
                "sample": match.group("sample"),
                "fraction": match.group("fraction").strip(),
                "values": values,
            }
        )
    if len(samples) != ZENODO_EXPECTED_SAMPLE_ROWS:
        raise ChinaDemoError(
            f"Zenodo S2 sample count changed: expected {ZENODO_EXPECTED_SAMPLE_ROWS}, "
            f"found {len(samples)}"
        )
    return samples


def build_zenodo_demo(
    zenodo_file: Path, output_dir: Path, generated_at: str, overwrite: bool
) -> dict[str, Any]:
    output_paths = {
        "demo_input": output_dir / "demo_input.csv",
        "sources": output_dir / "sources.jsonl",
        "run_manifest": output_dir / "run_manifest.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing and not overwrite:
        raise ChinaDemoError(
            f"output files already exist; use --overwrite after review: {existing}"
        )
    verify_zenodo_file(zenodo_file)
    samples = parse_zenodo_s2(zenodo_file)

    entry = ZENODO_REGISTRY_ENTRY
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    leach_counts: Counter[str] = Counter()
    for sample in samples:
        locator = f"{ZENODO_S2_FILENAME}#sheet1-row={sample['row']}"
        source_record_id = source_adapters.stable_source_record_id(
            ZENODO_SOURCE_ID, sample["label"], locator
        )
        basis = f"{sample['leach']}_residual_size_fraction"
        extraction = (
            f"{sample['leach']}-leach residual component "
            "(dataset-described size-differentiated separate)"
        )
        for analyte in ZENODO_TARGET_ANALYTES:
            raw_value = sample["values"][analyte]
            record_id = source_adapters.stable_record_id(
                ZENODO_SOURCE_ID, source_record_id, analyte, raw_value, "ug/g"
            )
            leach_counts[sample["leach"]] += 1
            rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": source_record_id,
                    "sample_id": sample["label"],
                    "element_or_analyte": analyte,
                    "analyte_reported": analyte,
                    "value": raw_value,
                    "unit": "ug/g",
                    "medium": "sediment",
                    "measurement_basis": basis,
                    "value_qualifier": "",
                    "detection_limit": "",
                    "detection_limit_unit": "",
                    "latitude": "",
                    "longitude": "",
                    "original_latitude_raw": "",
                    "original_longitude_raw": "",
                    "source_crs": "",
                    "coordinate_uncertainty_m": "",
                    "geologic_unit": "",
                    "analytical_method": "",
                    "digestion_or_extraction": extraction,
                    "laboratory": "",
                    "license": entry["license"]["spdx"],
                    "source_tier": "author_supplement",
                    "source_id": ZENODO_SOURCE_ID,
                    "dataset_title": entry["title"],
                    "dataset_doi": entry["dataset_doi"],
                    "dataset_version": entry["dataset_version"],
                    "source_file": ZENODO_S2_FILENAME,
                    "source_row": str(sample["row"]),
                    "source_locator": locator,
                    "file_sha256": ZENODO_S2_SHA256,
                    "sampled_at": "",
                    "sample_depth_min_m": "",
                    "sample_depth_max_m": "",
                    "grain_fraction": sample["fraction"],
                }
            )
            evidence_rows.append(
                {
                    "record_id": record_id,
                    "source_record_id": source_record_id,
                    "source_id": ZENODO_SOURCE_ID,
                    "source_locator": locator,
                    "source_file": ZENODO_S2_FILENAME,
                    "source_row": sample["row"],
                    "source_file_bytes": ZENODO_S2_BYTES,
                    "source_file_sha256": ZENODO_S2_SHA256,
                    "source_file_url": ZENODO_S2_URL,
                    "publisher_checksum": ZENODO_S2_MD5,
                    "dataset_title": entry["title"],
                    "dataset_doi": entry["dataset_doi"],
                    "dataset_version": entry["dataset_version"],
                    "retrieved_at": None,
                    "license": entry["license"]["spdx"],
                    "analyte_reported": analyte,
                    "generation_version": ZENODO_GENERATION_VERSION,
                    "evidence_version": "geochemical-record-evidence-v1",
                    "evidence_status": "verified_source_file_and_row",
                    "article_citations": [entry["citation"]],
                    "article_dois": [],
                    "selection_rule": (
                        "full verified Data Set S2 slice: every sample row and "
                        "registered target analyte"
                    ),
                    "sample_label": sample["label"],
                    "river_system": river_system(sample["sample"]),
                    "leach_group": f"{sample['leach']}-residual",
                    "size_fraction_raw": sample["fraction"],
                    "unit_evidence": entry["unit_evidence"],
                    "coordinate_evidence": entry["coordinate_evidence"],
                    "method_source_locator": "",
                    "below_laboratory_dl": False,
                    "upstream_half_dl_substitution": False,
                }
            )
    if len(rows) != ZENODO_EXPECTED_OBSERVATIONS:
        raise ChinaDemoError(
            f"Zenodo slice produced {len(rows)} observations, expected "
            f"{ZENODO_EXPECTED_OBSERVATIONS}"
        )
    if dict(leach_counts) != entry["expected_counts"]["leach_groups"]:
        raise ChinaDemoError(
            f"Zenodo leach-group reconciliation changed: {dict(leach_counts)}"
        )

    rows = [
        v4_semantics.enrich_row(row, evidence, entry, ZENODO_TERMS_VERIFIED_AT)
        for row, evidence in zip(rows, evidence_rows, strict=True)
    ]

    demos.atomic_text(output_paths["demo_input"], demos._csv_text(rows))
    demos.atomic_text(output_paths["sources"], demos._jsonl_text(evidence_rows))
    manifest = {
        "data_mode": "fixture",
        "demo_generation_version": ZENODO_GENERATION_VERSION,
        "exchange_schema": "d1-v4-exchange-v1",
        "failures": [],
        "generated_at": generated_at,
        "generation_request": {
            "analytes": list(ZENODO_TARGET_ANALYTES),
            "bbox": None,
            "filter_execution": "full verified sample slice after structural QC gates",
            "mode": "cached",
            "observations": ZENODO_EXPECTED_OBSERVATIONS,
        },
        "not_for_scientific_interpretation": True,
        "outputs": [
            {
                "path": path.name,
                "bytes": path.stat().st_size,
                "sha256": demos.sha256_file(path),
            }
            for key, path in output_paths.items()
            if key != "run_manifest"
        ],
        "record_counts": {
            "emitted_observations": len(rows),
            "raw_source_rows": ZENODO_EXPECTED_SAMPLE_ROWS,
            "selected_source_rows": ZENODO_EXPECTED_SAMPLE_ROWS,
        },
        "scientific_scope": "pipeline demonstration only",
        "source": {
            "dataset_doi": entry["dataset_doi"],
            "dataset_version": entry["dataset_version"],
            "license": entry["license"]["spdx"],
            "source_id": ZENODO_SOURCE_ID,
            "title": entry["title"],
        },
        "source_files": [
            {
                "bytes": ZENODO_S2_BYTES,
                "filename": ZENODO_S2_FILENAME,
                "retrieved_at": None,
                "sha256": ZENODO_S2_SHA256,
                "publisher_checksum": ZENODO_S2_MD5,
                "source_url": ZENODO_S2_URL,
            }
        ],
        "unit_verification": {
            "declared_unit": "none (workbook publishes no unit row)",
            "assigned_unit": "ug/g",
            "method": entry["unit_evidence"],
            "standards_checked": sorted(
                {standard for standard, _ in ZENODO_QC_PREFERRED}
            ),
            "tolerance": ZENODO_QC_TOLERANCE,
        },
        "v4_semantics_version": "d1-v4-source-semantics-v1",
        "warnings": [
            "This is a deterministic demonstration slice, not a statistically representative sample.",
            "Scientific normalization, QC, confidence and anomaly decisions are owned by D2.",
            "Data Set S2 publishes no sampling coordinates; records are database-only and never mapped.",
            "HCl-residual and AC-residual leach schemes and size fractions remain separate comparison groups.",
            "The workbook declares no per-row analytical method; method fields stay empty with an explicit missing reason.",
        ],
    }
    demos.atomic_json(output_paths["run_manifest"], manifest)
    return manifest


def build_tpdc_full_demo(
    cache_dir: Path, output_dir: Path, generated_at: str, overwrite: bool
) -> dict[str, Any]:
    arguments = argparse.Namespace(
        source=TPDC_SOURCE_ID,
        cache_dir=cache_dir,
        output_dir=output_dir,
        mode="cached",
        archive=None,
        observations=TPDC_FULL_OBSERVATIONS,
        elements=demos.DEFAULT_ANALYTES,
        bbox=None,
        generated_at=generated_at,
        overwrite=overwrite,
    )
    manifest = demos.generate(arguments)
    emitted = manifest["record_counts"]["emitted_observations"]
    if emitted != TPDC_FULL_OBSERVATIONS:
        raise ChinaDemoError(
            f"TPDC full slice emitted {emitted} observations, expected "
            f"{TPDC_FULL_OBSERVATIONS}"
        )
    return manifest


def comparison_key(row: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in standardizer.DEFAULT_GROUP_BY)


def combine(
    source_demos: Path, output_dir: Path, generated_at: str, overwrite: bool
) -> dict[str, Any]:
    output_paths = {
        "input": output_dir / "demo_input.csv",
        "sources": output_dir / "sources.jsonl",
        "manifest": output_dir / "run_manifest.json",
        "request": output_dir / "request.json",
    }
    existing = [str(path) for path in output_paths.values() if path.exists()]
    if existing and not overwrite:
        raise ChinaDemoError(
            f"outputs already exist; use --overwrite after review: {existing}"
        )

    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    fixture_inputs: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    for source_id in CHINA_SOURCE_ORDER:
        fixture_dir = source_demos / source_id
        input_path = fixture_dir / "demo_input.csv"
        evidence_path = fixture_dir / "sources.jsonl"
        manifest_path = fixture_dir / "run_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChinaDemoError(f"{source_id} demo manifest is unreadable") from exc
        expected_hashes = {
            item["path"]: item["sha256"] for item in manifest.get("outputs", [])
        }
        if expected_hashes != {
            "demo_input.csv": demos.sha256_file(input_path),
            "sources.jsonl": demos.sha256_file(evidence_path),
        }:
            raise ChinaDemoError(
                f"{source_id} fixture hashes no longer match its manifest"
            )
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            source_rows = [dict(row) for row in csv.DictReader(handle)]
        source_evidence = [
            json.loads(line)
            for line in evidence_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(source_rows) != len(source_evidence) or not source_rows:
            raise ChinaDemoError(
                f"{source_id} fixture lacks one-to-one observation evidence"
            )
        row_ids = {row.get("record_id", "") for row in source_rows}
        evidence_ids = {
            str(row.get("record_id") or "")
            for row in source_evidence
            if isinstance(row, Mapping)
        }
        if row_ids != evidence_ids or "" in row_ids or record_ids.intersection(row_ids):
            raise ChinaDemoError(
                f"{source_id} fixture record IDs are missing, mismatched or duplicated"
            )
        if {row.get("source_id") for row in source_rows} != {source_id}:
            raise ChinaDemoError(f"{source_id} fixture source IDs changed")
        if {row.get("medium") for row in source_rows} != {EXPECTED_MEDIA[source_id]}:
            raise ChinaDemoError(f"{source_id} fixture medium changed")
        record_ids.update(row_ids)
        rows.extend(source_rows)
        evidence_rows.extend(source_evidence)
        fixture_inputs.append(
            {
                "source_id": source_id,
                "input_sha256": demos.sha256_file(input_path),
                "evidence_sha256": demos.sha256_file(evidence_path),
                "record_count": len(source_rows),
                "generation_manifest": {
                    key: manifest.get(key)
                    for key in (
                        "demo_generation_version",
                        "generated_at",
                        "generation_request",
                        "source",
                    )
                },
            }
        )

    atomic = demos.atomic_text
    atomic(output_paths["input"], demos._csv_text(rows))
    atomic(output_paths["sources"], demos._jsonl_text(evidence_rows))
    demos.atomic_json(output_paths["request"], CHINA_REQUEST)
    raw_input_partitions = Counter(comparison_key(row) for row in rows)
    normalized_records = standardizer.process_rows(rows)
    partitions = Counter(comparison_key(row) for row in normalized_records)
    source_counts = Counter(row["source_id"] for row in rows)
    medium_counts = Counter(row["medium"] for row in rows)
    analyte_counts = Counter(row["element_or_analyte"] for row in rows)
    source_files: dict[str, dict[str, Any]] = {}
    for item in evidence_rows:
        filename = str(item.get("source_file") or "")
        entry = {
            "filename": filename,
            "sha256": str(item.get("source_file_sha256") or ""),
            "source_url": str(item.get("source_file_url") or ""),
            "bytes": item.get("source_file_bytes"),
        }
        if not filename or not entry["sha256"] or not entry["source_url"]:
            raise ChinaDemoError("combined evidence lacks source-file hash binding")
        previous = source_files.setdefault(filename, entry)
        if previous != entry:
            raise ChinaDemoError(f"conflicting source-file evidence for {filename}")

    manifest = {
        "combined_demo_version": COMBINED_VERSION,
        "generated_at": generated_at,
        "data_mode": "fixture",
        "scientific_scope": (
            "two verified China-region source slices combined to exercise one "
            "soil+sediment regional workflow inside the execution budget"
        ),
        "not_for_scientific_interpretation": True,
        "request": CHINA_REQUEST,
        "route": {
            "status": "offline_fixtures_verified",
            "selection_context": "pinned_china_regional_fixture_route",
            "selected_sources": list(CHINA_SOURCE_ORDER),
            "notes": (
                "The route is pinned to the two verified China sources instead "
                "of the online source router: TPDC is catalogued as "
                "needs_human_review (undeclared datum) and the Zenodo deposit "
                "is registered only for this fixture. Live re-download remains "
                "an optional verification path via the registered URLs."
            ),
        },
        "coordinate_policy": {
            TPDC_SOURCE_ID: (
                "GPS coordinates are reported without a declared datum; "
                "canonical WGS84 stays empty and mapping requires "
                "--coordinate-mode reported with the injected warning banner."
            ),
            ZENODO_SOURCE_ID: (
                "No sampling coordinates are published; records stay "
                "database-only and are excluded from every map layer."
            ),
        },
        "fixture_inputs": fixture_inputs,
        "source_files": [source_files[name] for name in sorted(source_files)],
        "record_counts": {
            "total": len(rows),
            "by_source": dict(sorted(source_counts.items())),
            "by_medium": dict(sorted(medium_counts.items())),
            "by_analyte": dict(sorted(analyte_counts.items())),
        },
        "comparison_isolation": {
            "group_fields": list(standardizer.DEFAULT_GROUP_BY),
            "raw_input_partition_count": len(raw_input_partitions),
            "partition_count": len(partitions),
            "explicit_boundaries": [
                "TPDC O, A and C soil horizons remain separate comparison groups.",
                "Zenodo HCl-residual and AC-residual leach schemes remain separate comparison groups.",
                "Zenodo size fractions remain separate through grain_fraction and are never averaged.",
                "TPDC reported GPS coordinates carry no declared datum; canonical coordinates stay empty.",
                "Zenodo river-sediment records carry no coordinates and never reach a map layer.",
            ],
        },
        "outputs": [
            {
                "path": output_paths[key].name,
                "bytes": output_paths[key].stat().st_size,
                "sha256": demos.sha256_file(output_paths[key]),
            }
            for key in ("input", "sources")
        ],
        "warnings": [
            "This combined fixture proves interface compatibility and budget compliance, not representative China-wide coverage.",
            "TPDC covers 30 mountain ecosystems and the Zenodo slice covers two river systems; neither is a national grid.",
            "Anomalies produced from fixture groups are pipeline candidates only and cannot support pollution or depletion claims.",
        ],
        "failures": [],
        "claim_boundary": (
            "The combined package binds two verified slices (6,570 TPDC soil "
            "observations and 558 Zenodo river-sediment observations) to one "
            "request and evidence chain. It does not increase their "
            "geographic representativeness."
        ),
    }
    demos.atomic_json(output_paths["manifest"], manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    skill_dir = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tpdc-cache-dir",
        required=True,
        type=Path,
        help=(
            "Cache root that contains tpdc-china-mountain-soil/"
            "tpdc-file-2025-07-23/ with the three verified workbook members"
        ),
    )
    parser.add_argument(
        "--zenodo-file",
        required=True,
        type=Path,
        help="Local verified copy of Zenodo 7098563 'Data Set S2.xlsx'",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=skill_dir / "fixtures" / "china" / "combined-v1",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Keep per-source intermediate demos here instead of a temp dir",
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def build(args: argparse.Namespace) -> dict[str, Any]:
    if args.work_dir is not None:
        args.work_dir.mkdir(parents=True, exist_ok=True)
        work = args.work_dir
        build_tpdc_full_demo(
            args.tpdc_cache_dir, work / TPDC_SOURCE_ID, args.generated_at, True
        )
        build_zenodo_demo(
            args.zenodo_file, work / ZENODO_SOURCE_ID, args.generated_at, True
        )
        return combine(work, args.output_dir, args.generated_at, args.overwrite)
    with tempfile.TemporaryDirectory(prefix="china-demo-") as temporary:
        work = Path(temporary)
        build_tpdc_full_demo(
            args.tpdc_cache_dir, work / TPDC_SOURCE_ID, args.generated_at, True
        )
        build_zenodo_demo(
            args.zenodo_file, work / ZENODO_SOURCE_ID, args.generated_at, True
        )
        return combine(work, args.output_dir, args.generated_at, args.overwrite)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = build(args)
    except (
        ChinaDemoError,
        demos.DemoError,
        source_adapters.SourceAdapterError,
        v4_semantics.SemanticError,
        OSError,
        ValueError,
    ) as exc:
        print(f"build_china_demo: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "PASS",
                "record_count": manifest["record_counts"]["total"],
                "by_source": manifest["record_counts"]["by_source"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
