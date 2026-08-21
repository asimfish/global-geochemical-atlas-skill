#!/usr/bin/env python3
"""Run the minimal D1/D2/D3 collaboration contracts against the bundled demo."""

from __future__ import annotations

import argparse
import binascii
import copy
import csv
import hashlib
import io
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import acquire_gemstat_arsenic as gemstat_acquisition
import benchmark_workflow
import build_china_demo
import build_evidence_bundle as evidence_builder
import build_four_media_demo
import build_interactive_map as map_builder
import build_temporal_map as temporal_map_builder
import build_element_comparison as comparison_builder
import build_index as index_builder
import benchmark_index
import cache_control
import coverage_report
import download_data as downloader
import evaluate_batch_qc as batch_qc
import execution_budget
import generate_demo_data as demo_generator
import skill_snapshot
import source_adapters as source_contracts
import standardize_geochemistry as standardizer
import source_audit
import score_source_evidence
import snapshot_source
import source_router
import spatial_scope
import spatial_sufficiency
import task_router
import query_source
import export_archive_exchange
import migrate_v4_source_demos
import profile_source_completeness
import reconcile_v4_coordinate_claims
import run_atlas_request as request_runner
import sampling_time
import classify_anomaly_provenance as provenance_classifier
import validate_acquisition as acquisition_validator
import validate_outputs as output_validator
import validate_human_review as human_review_validator
import validate_research_delivery as research_delivery_validator
import validate_visualization as visualization_validator
import verify_marchem_candidate
import v4_semantics

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
DEMO_INPUT = SKILL_DIR / "fixtures" / "demo_input.csv"
SOURCE_DEMOS = SKILL_DIR / "fixtures" / "source-demos"
COMBINED_DEMO = SKILL_DIR / "fixtures" / "four-media" / "combined-v3"
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
REQUEST_RUNNER = SCRIPT_DIR / "run_atlas_request.py"
DOWNLOADER = SCRIPT_DIR / "download_data.py"
GENERATOR = SCRIPT_DIR / "generate_demo_data.py"
VISUALIZATION_RENDERER = SCRIPT_DIR / "render_visualization.py"
VISUALIZATION_PROFILE_CREATOR = SCRIPT_DIR / "create_visualization_profile.py"
BASEMAP = SKILL_DIR / "assets" / "natural-earth-110m-land.json"
COUNTRY_BOUNDARIES = SKILL_DIR / "assets" / "natural-earth-110m-admin0.json"
VISUALIZATION_PROFILE = SKILL_DIR / "assets" / "visualization-profile.template.json"
REGIONAL_VISUALIZATION_PROFILE = (
    SKILL_DIR / "assets" / "visualization-profile.regional.template.json"
)
REGIONAL_COMPARISON_PROFILE = (
    SKILL_DIR / "assets" / "visualization-profile.comparison-regional.template.json"
)
VISUALIZATION_PROFILE_SCHEMA = (
    SKILL_DIR / "references" / "visualization-profile.schema.json"
)
VISUALIZATION_REPORT_SCHEMA = (
    SKILL_DIR / "references" / "visualization-report.schema.json"
)
PRODUCTION_REQUEST = SKILL_DIR / "fixtures" / "production-usgs" / "request.json"


class ContractError(AssertionError):
    """Raised when a component breaks a shared interface."""


def require(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise ContractError(message)
    checks.append(message)


def json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def visualization_status_ok(report: dict[str, Any]) -> bool:
    """Accept a valid bundle; tolerate only an explicit no-browser render skip."""

    if report.get("status") == "valid":
        return True
    return (
        report.get("status") == "needs_render_confirmation"
        and report.get("render_smoke", {}).get("status") == "skipped_no_browser"
    )


def run_command(
    arguments: list[str], expected_code: int = 0
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments, capture_output=True, text=True, check=False, timeout=60
    )
    if result.returncode != expected_code:
        raise ContractError(
            f"unexpected exit {result.returncode}, expected {expected_code}: {' '.join(arguments)}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def check_d1(output_dir: Path) -> list[str]:
    checks: list[str] = []
    manifest_path = output_dir / "source_manifest.json"
    confidence_path = output_dir / "confidence_report.json"
    manifest = json_value(manifest_path)
    input_hash = sha256_file(DEMO_INPUT)
    require(
        manifest.get("manifest_version") == "geochemical-source-manifest-v2",
        "D1 manifest version is stable",
        checks,
    )
    require(
        manifest.get("input", {}).get("sha256") == input_hash,
        "D1 manifest binds the acquired input hash",
        checks,
    )
    require(
        manifest.get("input", {}).get("record_count") == 19,
        "D1 manifest preserves the record count",
        checks,
    )
    coverage = manifest.get("coverage", {})
    require(
        coverage.get("source_locator_rate") == 1.0,
        "D1 demo provenance coverage is complete",
        checks,
    )
    require(
        coverage.get("declared_license_rate") == 1.0,
        "D1 demo license declarations are complete",
        checks,
    )
    require(
        coverage.get("verified_evidence_rate") == 0.0,
        "D1 does not overstate verification when no acquisition manifest is supplied",
        checks,
    )
    require(
        manifest.get("record_evidence", {}).get("exact_record_id_match") is True,
        "D1 emits a record-linked evidence sidecar even for direct input",
        checks,
    )
    sources = manifest.get("sources", [])
    require(
        len(sources) == 1 and sources[0].get("license_review") == "demo_cc0",
        "D1 demo source is explicitly synthetic CC0",
        checks,
    )
    binding = manifest.get("confidence_report", {})
    require(
        binding.get("sha256") == sha256_file(confidence_path),
        "D1 packages the unchanged D2 confidence hash",
        checks,
    )
    require(
        binding.get("not_a_probability") is True,
        "D1 preserves the confidence interpretation boundary",
        checks,
    )

    distinct_url_canonical = [
        {
            "record_id": "distinct-url-record",
            "source_record_id": "source-row-1",
            "source_id": "earthchem-dehailonggang-rock",
            "source_locator": "workbook.xlsx#sheet3-row=7",
            "license": "CC-BY-SA-4.0",
            "analyte_reported": "Cr",
            "official_source_url": "https://ecl.earthchem.org/view.php?id=3338",
            "file_sha256": "0" * 64,
        }
    ]
    distinct_url_evidence = [
        {
            "record_id": "distinct-url-record",
            "source_record_id": "source-row-1",
            "source_id": "earthchem-dehailonggang-rock",
            "source_locator": "workbook.xlsx#sheet3-row=7",
            "license": "CC-BY-SA-4.0",
            "analyte_reported": "Cr",
            "source_file_sha256": "0" * 64,
            "source_file_url": "https://ecl.earthchem.org/dl_multi.php",
            "official_source_url": "https://ecl.earthchem.org/view.php?id=3338",
        }
    ]
    evidence_builder.validate_record_linkage(
        distinct_url_canonical, distinct_url_evidence
    )
    tampered_distinct_url = copy.deepcopy(distinct_url_evidence)
    tampered_distinct_url[0]["official_source_url"] = (
        "https://example.invalid/unbound-source"
    )
    try:
        evidence_builder.validate_record_linkage(
            distinct_url_canonical, tampered_distinct_url
        )
    except evidence_builder.EvidenceError as exc:
        distinct_url_rejected = "does not bind canonical official_source_url" in str(
            exc
        )
    else:
        distinct_url_rejected = False
    require(
        distinct_url_rejected,
        "D1 evidence keeps acquisition and official URLs distinct while rejecting an unbound official URL",
        checks,
    )

    registry = source_contracts.load_source_registry()
    require(
        set(registry["sources"])
        == {
            "georoc-archaean",
            "georoc-convergent-margins",
            "usgs-conus-soil",
            "norway-marchem",
            "geotraces-idp2025",
            "gemstat-open-archive",
            "japan-gsj-geochemical-map",
            "pangaea-north-africa-soil",
            "foregs-topsoil",
            "foregs-subsoil",
            "foregs-humus",
            "foregs-stream-water",
            "foregs-stream-sediment",
            "foregs-floodplain-sediment",
            "afsis-phase-i-wet-chemistry",
            "us-wqp-sacramento-river-arsenic",
            "australia-ngsa",
            "australia-ngsa-mercury",
            "japan-gsj-marine-sediment",
            "pangaea-arabian-sea-sediment",
            "georoc-antarctica-intraplate",
            "tpdc-china-mountain-soil",
            "gemas-europe",
            "zenodo-yangtze-yellow-river-sediment",
            "pangaea-east-china-sea-clay",
            "pangaea-south-china-sea-sediment",
            "pangaea-barents-c-horizon-soil",
            "pangaea-amazonas-soil",
            "pangaea-batagay-soil",
            "eidc-ningbo-soil",
            "pangaea-brasol-ne-brazil-soil",
            "figshare-yangtze-basin-soil-heavy-metals",
            "earthchem-dehailonggang-rock",
            "4tu-northern-china-sediment",
            "zenodo-gard-whole-rock",
        },
        "D1 registry freezes thirty-five executable datasets across the four required media",
        checks,
    )
    with tempfile.TemporaryDirectory(prefix="georoc-member-fallback-") as temporary:
        fallback_root = Path(temporary)
        fallback_registry = fallback_root / "source-registry.json"
        member_payload = b"CITATIONS,SAMPLE NAME\nreference,sample-1\n"
        member_md5 = hashlib.md5(member_payload, usedforsecurity=False).hexdigest()
        fallback_registry.write_text(
            json.dumps(
                {
                    "registry_version": "geochemical-source-registry-v1",
                    "verified_at": "2026-08-15T00:00:00Z",
                    "sources": {
                        "georoc-archaean": {
                            "adapter": "georoc_dataverse",
                            "title": "GEOROC fallback contract fixture",
                            "dataset_doi": "10.1234/georoc-test",
                            "dataset_version": "test-v1",
                            "landing_page": "https://example.invalid/georoc",
                            "media": ["rock"],
                            "download": {
                                "mode": "versioned-dataverse-zip",
                                "url": "https://example.invalid/georoc.zip",
                                "accepted_content_types": ["application/zip"],
                                "max_bytes": 1000,
                                "expected_member_count": 1,
                                "expected_uncompressed_bytes": len(member_payload),
                                "bundle_sha256": None,
                                "members": [
                                    {
                                        "filename": "member.csv",
                                        "bytes": len(member_payload),
                                        "persistent_id": "doi:10.1234/georoc-test/FILE1",
                                        "publisher_checksum": {
                                            "algorithm": "md5",
                                            "value": member_md5,
                                        },
                                    }
                                ],
                            },
                            "required_fields": ["CITATIONS", "SAMPLE NAME"],
                            "license": {
                                "spdx": "CC-BY-SA-4.0",
                                "name": "CC BY-SA 4.0",
                                "url": "https://creativecommons.org/licenses/by-sa/4.0/",
                            },
                            "citation": "Synthetic fallback contract fixture",
                            "redistribution": "test fixture",
                            "scientific_notes": [],
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        fallback_adapter = source_contracts.GeorocArchaeanAdapter(fallback_registry)
        original_download_run = source_contracts.downloader.run
        fallback_calls: list[str] = []

        def fake_georoc_download(args: argparse.Namespace) -> dict[str, Any]:
            fallback_calls.append(args.url)
            if args.output.suffix == ".zip":
                raise downloader.DownloadError("HTTP 500 from dataset archive")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(member_payload)
            return {
                "status": "downloaded",
                "content_type": "text/csv",
                "bytes": len(member_payload),
                "accessed_at": "2026-08-15T00:00:00Z",
            }

        source_contracts.downloader.run = fake_georoc_download
        try:
            fallback_files = fallback_adapter.download(
                fallback_adapter.candidate, fallback_root / "cache", "online"
            )
        finally:
            source_contracts.downloader.run = original_download_run
        require(
            len(fallback_files) == 1
            and fallback_files[0].path.read_bytes() == member_payload
            and fallback_files[0].file_id == "FILE1"
            and len(fallback_calls) == 2
            and "api/access/datafile/:persistentId/" in fallback_calls[1]
            and "persistentId=doi%3A10.1234%2Fgeoroc-test%2FFILE1" in fallback_calls[1],
            "D1 GEOROC falls back from the failing dataset ZIP to the same publisher-pinned member persistent IDs",
            checks,
        )

        bad_cache = fallback_root / "bad-cache"

        def fake_bad_georoc_download(args: argparse.Namespace) -> dict[str, Any]:
            if args.output.suffix == ".zip":
                raise downloader.DownloadError("HTTP 500 from dataset archive")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(member_payload.replace(b"sample-1", b"sample-X"))
            return {
                "status": "downloaded",
                "content_type": "text/csv",
                "bytes": len(member_payload),
                "accessed_at": "2026-08-15T00:00:00Z",
            }

        source_contracts.downloader.run = fake_bad_georoc_download
        try:
            try:
                fallback_adapter.download(
                    fallback_adapter.candidate, bad_cache, "online"
                )
            except source_contracts.SourceAdapterError as exc:
                checksum_failed_closed = "checksum mismatch" in str(exc)
            else:
                checksum_failed_closed = False
        finally:
            source_contracts.downloader.run = original_download_run
        require(
            checksum_failed_closed and not list(bad_cache.rglob(".members.*.part")),
            "D1 GEOROC member fallback publishes nothing when publisher checksum verification fails",
            checks,
        )

        synthetic_files: dict[str, source_contracts.DownloadedFile] = {}
        synthetic_records: list[source_contracts.RawRecord] = []
        for member_index, member_name in enumerate(("member-a.csv", "member-b.csv")):
            member_path = fallback_root / member_name
            member_path.write_text("fixture\n", encoding="utf-8")
            synthetic_files[member_name] = source_contracts.DownloadedFile(
                source_id="georoc-archaean",
                file_id=f"FILE-{member_index}",
                path=member_path,
                source_url=f"https://example.invalid/{member_name}",
                bytes=member_path.stat().st_size,
                cache_status="fixture",
                retrieved_at=None,
            )
            for row_index in range(2):
                locator = f"{member_name}#row={row_index + 2}"
                synthetic_records.append(
                    source_contracts.RawRecord(
                        source_id="georoc-archaean",
                        source_record_id=source_contracts.stable_source_record_id(
                            "georoc-archaean",
                            f"sample-{member_index}-{row_index}",
                            locator,
                        ),
                        source_locator=locator,
                        fields={
                            "_source_file": member_name,
                            "CITATIONS": "fixture reference",
                            "SAMPLE NAME": f"sample-{member_index}-{row_index}",
                            "MATERIAL": "WR",
                            "LATITUDE MIN": str(10 + member_index),
                            "LATITUDE MAX": str(10 + member_index),
                            "LONGITUDE MIN": str(20 + member_index),
                            "LONGITUDE MAX": str(20 + member_index),
                            "AS(PPM)": str(1 + row_index),
                            "CU(PPM)": str(2 + row_index),
                            "NI(PPM)": str(3 + row_index),
                            "ZN(PPM)": str(4 + row_index),
                            "ROCK NAME": "granite",
                        },
                    )
                )
        balanced_rows, balanced_evidence, _, _ = demo_generator.georoc_demo(
            synthetic_records,
            synthetic_files,
            {name: {} for name in synthetic_files},
            fallback_adapter.candidate,
            8,
            ("As", "Cu", "Ni", "Zn"),
            None,
            "research",
        )
        require(
            len(balanced_rows) == len(balanced_evidence) == 8
            and {row["source_file"] for row in balanced_rows}
            == {"member-a.csv", "member-b.csv"}
            and {item["selection_rule"] for item in balanced_evidence}
            == {
                "whole-rock; exact reported point coordinates; balanced "
                "As,Cu,Ni,Zn; round-robin publisher craton members"
            },
            "D1 GEOROC research slices interleave publisher craton members instead of taking a geographically biased archive prefix",
            checks,
        )
        bbox_rows, bbox_evidence, _, _ = demo_generator.georoc_demo(
            synthetic_records,
            synthetic_files,
            {name: {} for name in synthetic_files},
            fallback_adapter.candidate,
            4,
            ("As", "Cu", "Ni", "Zn"),
            (19.5, 9.5, 20.5, 10.5),
            "research",
        )
        require(
            len(bbox_rows) == len(bbox_evidence) == 4
            and {row["source_file"] for row in bbox_rows} == {"member-a.csv"}
            and all(not row["latitude"] and not row["longitude"] for row in bbox_rows)
            and {
                item["coordinate_evidence"]["canonicalization_status"]
                for item in bbox_evidence
            }
            == {"withheld_pending_datum_verification"}
            and all(
                "reported-coordinate retrieval filter" in item["selection_rule"]
                for item in bbox_evidence
            ),
            "D1 may use exact source-reported GEOROC coordinates for an auditable retrieval filter without relabeling them as canonical WGS84",
            checks,
        )
        sparse_records: list[source_contracts.RawRecord] = []
        for index, record in enumerate(synthetic_records[:2]):
            fields = dict(record.fields)
            if index == 1:
                fields["AS(PPM)"] = ""
            sparse_records.append(
                source_contracts.RawRecord(
                    source_id=record.source_id,
                    source_record_id=record.source_record_id,
                    source_locator=record.source_locator,
                    fields=fields,
                )
            )
        sparse_rows, sparse_evidence, _, _ = demo_generator.georoc_demo(
            sparse_records,
            synthetic_files,
            {name: {} for name in synthetic_files},
            fallback_adapter.candidate,
            4,
            ("As", "Cu"),
            None,
            "research",
        )
        require(
            len(sparse_rows) == len(sparse_evidence) == 3
            and Counter(row["element_or_analyte"] for row in sparse_rows)
            == {"As": 1, "Cu": 2},
            "D1 GEOROC keeps all verified observations up to each analyte quota instead of dropping the source when one requested element is naturally sparse",
            checks,
        )
    require(
        set(registry["sources"]["pangaea-amazonas-soil"]["target_analytes"])
        == {"As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"}
        and registry["sources"]["pangaea-amazonas-soil"]["expected_counts"][
            "target_observations"
        ]
        == 1181
        and set(registry["sources"]["eidc-ningbo-soil"]["target_analytes"])
        == {"As", "Cr", "Cu", "Ni", "Pb", "Zn"}
        and registry["sources"]["eidc-ningbo-soil"]["expected_counts"][
            "target_observations"
        ]
        == 480
        and set(registry["sources"]["pangaea-batagay-soil"]["target_analytes"])
        == {"Cu", "Pb", "Zn"}
        and registry["sources"]["pangaea-brasol-ne-brazil-soil"]["expected_counts"][
            "target_observations"
        ]
        == 1614
        and registry["sources"]["pangaea-brasol-ne-brazil-soil"]["expected_counts"][
            "coordinate_conflict_rows"
        ]
        == 6
        and registry["sources"]["figshare-yangtze-basin-soil-heavy-metals"][
            "expected_counts"
        ]["target_observations"]
        == 6625,
        "D1 breadth sources expose audited element vocabularies without silently changing a frozen request",
        checks,
    )
    figshare_file = registry["sources"]["figshare-yangtze-basin-soil-heavy-metals"][
        "download"
    ]["files"][0]
    signed_query = urllib.parse.urlencode(
        {
            "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
            "X-Amz-Credential": "TEST/scope",
            "X-Amz-Date": "20260814T000000Z",
            "X-Amz-Expires": "10",
            "X-Amz-SignedHeaders": "host",
            "X-Amz-Signature": "a" * 64,
        }
    )
    signed_storage_url = (
        "https://s3-eu-west-1.amazonaws.com/"
        "pfigshare-u-files/40503701/Records.xlsx?" + signed_query
    )
    redacted_storage_url = source_contracts.validate_figshare_storage_redirect(
        signed_storage_url, "40503701", "Records.xlsx"
    )
    denied_redirects = 0
    for unsafe_url in (
        signed_storage_url.replace("s3-eu-west-1.amazonaws.com", "127.0.0.1"),
        signed_storage_url.replace("/40503701/", "/999/"),
        signed_storage_url.replace("X-Amz-Expires=10", "X-Amz-Expires=600"),
    ):
        try:
            source_contracts.validate_figshare_storage_redirect(
                unsafe_url, "40503701", "Records.xlsx"
            )
        except (source_contracts.SourceAdapterError, downloader.DownloadError):
            denied_redirects += 1
    require(
        figshare_file["figshare_file_id"] == "40503701"
        and figshare_file["url"] == "https://ndownloader.figshare.com/files/40503701"
        and redacted_storage_url
        == "https://s3-eu-west-1.amazonaws.com/pfigshare-u-files/40503701/Records.xlsx"
        and "X-Amz" not in redacted_storage_url
        and denied_redirects == 3,
        "D1 Figshare acquisition accepts only its fixed ephemeral storage redirect and never persists the signed capability",
        checks,
    )
    zenodo_china = source_contracts.registry_candidate(
        "zenodo-yangtze-yellow-river-sediment"
    )
    require(
        zenodo_china.version == "zenodo-record-7098563-rev2-2022-09-21"
        and zenodo_china.license_id == "CC-BY-4.0"
        and set(zenodo_china.registry_entry["target_analytes"])
        == {"As", "Cr", "Cu", "Ni", "Pb", "Zn"}
        and zenodo_china.registry_entry["expected_counts"]["sample_rows"] == 93
        and zenodo_china.registry_entry["expected_counts"]["target_observations"] == 558
        and zenodo_china.registry_entry["expected_counts"]["leach_groups"]
        == {"AC": 78, "HCl": 480},
        "D1 Zenodo river-sediment candidate pins the verified workbook, six targets and leach groups",
        checks,
    )
    ecs_clay = source_contracts.registry_candidate("pangaea-east-china-sea-clay")
    require(
        ecs_clay.version == "2016-01-11"
        and ecs_clay.license_id == "CC-BY-3.0"
        and set(ecs_clay.registry_entry["target_analytes"]) == {"Cr", "Cu", "Pb", "Zn"}
        and ecs_clay.registry_entry["expected_counts"]["physical_rows"] == 98
        and ecs_clay.registry_entry["expected_counts"]["distinct_events"] == 28
        and ecs_clay.registry_entry["expected_counts"]["target_observations"] == 392
        and ecs_clay.registry_entry["expected_counts"]["sample_type_rows"]
        == {"Bulk": 49, "Residue": 49},
        "D1 PANGAEA East China Sea clay candidate pins the verified table, four targets and the fraction split",
        checks,
    )
    scs_sediment = source_contracts.registry_candidate(
        "pangaea-south-china-sea-sediment"
    )
    require(
        scs_sediment.version == "2015-11-23"
        and scs_sediment.license_id == "CC-BY-3.0"
        and set(scs_sediment.registry_entry["target_analytes"])
        == {"Cr", "Cu", "Ni", "Pb", "Zn"}
        and scs_sediment.registry_entry["expected_counts"]["physical_rows"] == 44
        and scs_sediment.registry_entry["expected_counts"]["distinct_events"] == 44
        and scs_sediment.registry_entry["expected_counts"]["target_observations"]
        == 220,
        "D1 PANGAEA South China Sea candidate pins the verified marine table and five targets",
        checks,
    )
    barents_soil = source_contracts.registry_candidate("pangaea-barents-c-horizon-soil")
    require(
        barents_soil.version == "1998-01-01"
        and barents_soil.license_id == "CC-BY-3.0"
        and set(barents_soil.registry_entry["target_analytes"])
        == {"As", "Cu", "Pb", "Zn"}
        and barents_soil.registry_entry["expected_counts"]["physical_rows"] == 606
        and barents_soil.registry_entry["expected_counts"]["target_observations"]
        == 2419
        and barents_soil.registry_entry["expected_counts"]["censored_value_counts"]
        == {"As": 10}
        and {
            (name, spec["column"])
            for name, spec in barents_soil.registry_entry["target_columns"].items()
        }
        == {("As", 69), ("Cu", 20), ("Pb", 95), ("Zn", 55)},
        "D1 Barents C-horizon candidate pins the index-mapped aqua-regia suite and censored counts",
        checks,
    )
    china_online_route = source_router.route_sources(
        {
            "elements": ["As", "Cr", "Cu", "Ni", "Pb", "Zn"],
            "region": {"bbox": [73.0, 18.0, 135.0, 54.0]},
            "media": ["soil", "sediment"],
            "sources": "auto",
            "license_policy": "open_only",
            "research_use_policy": "permitted_research",
            "minimum_evidence_tier": "D",
            "minimum_use_mode": "normalized_analysis",
            "max_records": 50000,
            "offline": False,
        }
    )
    require(
        {entry["source_id"] for entry in china_online_route["selected_sources"]}
        == {
            "tpdc-china-mountain-soil",
            "zenodo-yangtze-yellow-river-sediment",
            "pangaea-east-china-sea-clay",
            "pangaea-south-china-sea-sediment",
            "eidc-ningbo-soil",
            "figshare-yangtze-basin-soil-heavy-metals",
            "4tu-northern-china-sediment",
        },
        "D1 router gives an online China soil+sediment request seven independent lineages including the western/northern source",
        checks,
    )
    china_water_route = source_router.route_sources(
        {
            "elements": ["As", "Cu", "Pb", "Zn"],
            "region": "China",
            "media": ["water"],
            "sources": "auto",
            "license_policy": "open_only",
            "research_use_policy": "permitted_research",
            "minimum_evidence_tier": "D",
            "minimum_use_mode": "normalized_analysis",
            "max_records": 50000,
            "offline": False,
        }
    )
    china_water_selected = {
        entry["source_id"] for entry in china_water_route["selected_sources"]
    }
    china_water_review = {
        entry["source_id"]: entry for entry in china_water_route["review_sources"]
    }
    require(
        "geotraces-idp2025" in china_water_selected
        and "gemstat-open-archive" not in china_water_selected
        and (
            china_water_review["gemstat-open-archive"]["request_compatibility"][
                "region"
            ]["reason_code"]
            == "profile_country_absent"
        )
        and (
            next(
                item
                for item in china_water_route["selected_sources"]
                if item["source_id"] == "geotraces-idp2025"
            )["request_compatibility"]["region"]["reason_code"]
            == "adjacent_marine_domain_requested"
        ),
        "D1 country preflight keeps an audited adjacent-marine source while rejecting an absent inland-water country index",
        checks,
    )
    global_water_route = source_router.route_sources(
        {
            "elements": ["Cu", "Zn"],
            "region": "global",
            "media": ["water"],
            "sources": ["gemstat-open-archive", "geotraces-idp2025"],
            "license_policy": "open_only",
            "research_use_policy": "permitted_research",
            "minimum_evidence_tier": "D",
            "minimum_use_mode": "normalized_analysis",
            "max_records": 50000,
            "offline": False,
        }
    )
    require(
        {entry["source_id"] for entry in global_water_route["selected_sources"]}
        == {"gemstat-open-archive", "geotraces-idp2025"},
        "D1 country applicability gates do not suppress valid global water routing",
        checks,
    )
    georoc = source_contracts.registry_candidate("georoc-archaean")
    require(
        georoc.version == "12.0"
        and georoc.license_id == "CC-BY-SA-4.0"
        and georoc.registry_entry["region_applicability"]["country_index_status"]
        == "positive_evidence_only"
        and georoc.registry_entry["region_applicability"]["country_iso_a3_codes"]
        == ["CHN"],
        "D1 GEOROC candidate binds the verified version, license and publisher-member China evidence",
        checks,
    )
    china_rock_route = source_router.route_sources(
        {
            "elements": ["As", "Cu", "Ni", "Zn"],
            "region": "China",
            "media": ["rock"],
            "sources": "auto",
            "license_policy": "open_only",
            "research_use_policy": "permitted_research",
            "minimum_evidence_tier": "D",
            "minimum_use_mode": "normalized_analysis",
            "max_records": 200000,
            "offline": False,
        }
    )
    china_rock_selected = {
        entry["source_id"]: entry for entry in china_rock_route["selected_sources"]
    }
    require(
        {"earthchem-dehailonggang-rock", "georoc-archaean"} <= set(china_rock_selected)
        and china_rock_selected["georoc-archaean"]["request_compatibility"]["region"][
            "reason_code"
        ]
        == "profile_country_positive_evidence"
        and china_rock_selected["georoc-archaean"]["request_compatibility"]["region"][
            "status"
        ]
        == "compatible_reported_only",
        "D1 China rock routing consumes positive immutable-member evidence without relabeling GEOROC coordinates as WGS84",
        checks,
    )
    gemstat = source_contracts.registry_candidate("gemstat-open-archive")
    require(
        gemstat.version == "v3"
        and set(gemstat.registry_entry["target_analytes"])
        == {"As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"}
        and gemstat.registry_entry["expected_counts"]["target_observations"] == 3739180
        and len(gemstat.registry_entry["download"]["selected_members"]) == 11,
        "D1 GEMStat candidate pins the official v3 seven-element and metadata member subset",
        checks,
    )
    usgs = source_contracts.registry_candidate("usgs-conus-soil")
    require(
        len(usgs.registry_entry["download"]["files"]) == 3,
        "D1 USGS candidate keeps the three soil layers distinct",
        checks,
    )
    geotraces = source_contracts.registry_candidate("geotraces-idp2025")
    require(
        geotraces.version == "IDP2025"
        and set(geotraces.registry_entry["target_analytes"]) == {"Cu", "Ni", "Zn"}
        and geotraces.registry_entry["expected_counts"]["target_observations"] == 39327,
        "D1 GEOTRACES candidate pins the seawater export and its explicit arsenic gap",
        checks,
    )
    gemstat_spatial_profile = json_value(
        SKILL_DIR
        / "assets"
        / "v4-full-profiles"
        / "gemstat-open-archive"
        / "spatial_coverage.json"
    )
    geotraces_spatial_profile = json_value(
        SKILL_DIR
        / "assets"
        / "v4-full-profiles"
        / "geotraces-idp2025"
        / "spatial_coverage.json"
    )
    require(
        gemstat_spatial_profile["region_applicability"]["spatial_domain"]
        == "inland_water"
        and gemstat_spatial_profile["region_applicability"]["country_index_status"]
        == "complete_for_snapshot"
        and len(gemstat_spatial_profile["region_applicability"]["country_iso_a3_codes"])
        == gemstat_spatial_profile["region_count"]
        and "CHN"
        not in gemstat_spatial_profile["region_applicability"]["country_iso_a3_codes"]
        and geotraces_spatial_profile["region_applicability"]["spatial_domain"]
        == "marine",
        "D1 full profiles expose audited country-index and land/marine applicability semantics",
        checks,
    )
    pangaea = source_contracts.registry_candidate("pangaea-north-africa-soil")
    require(
        pangaea.version == "2022-10-25"
        and pangaea.license_id == "CC-BY-4.0"
        and set(pangaea.registry_entry["target_analytes"])
        == {"As", "Cr", "Cu", "Ni", "Pb", "Zn"}
        and pangaea.registry_entry["expected_counts"]["physical_rows"] == 43
        and pangaea.registry_entry["expected_counts"]["target_observations"] == 258,
        "D1 PANGAEA candidate pins the concrete DOI table, six targets and exact row counts",
        checks,
    )
    gsj = source_contracts.registry_candidate("japan-gsj-geochemical-map")
    require(
        gsj.version == "sample-2024-02-20_concentration-2007-01-10"
        and set(gsj.registry_entry["target_analytes"])
        == {"As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"}
        and gsj.registry_entry["target_units"]["Hg"] == "ppb"
        and gsj.registry_entry["expected_counts"]["ordinal_joined_rows"] == 3024
        and gsj.registry_entry["expected_counts"]["duplicate_sample_id"] == "78013"
        and gsj.registry_entry["research_slice_capacity"][
            "all_registered_observation_count"
        ]
        == 21168,
        "D1 GSJ candidate pins both CSV versions, seven targets and occurrence-order duplicate handling",
        checks,
    )
    foregs = source_contracts.ForegsTopsoilAdapter()
    with tempfile.TemporaryDirectory(prefix="foregs-contract-") as temporary_directory:
        foregs_contract = Path(temporary_directory) / "synthetic.csv"
        foregs_contract.write_text(
            "GTN,As,As,Cu\nidentifier,mg/kg,mg/kg,mg/kg\ndetection limit,2,4,1\nX-1,1,2,0.5\n",
            encoding="latin-1",
        )
        parsed_foregs = list(
            foregs._rows(
                foregs_contract,
                {"required_fields": ["GTN", "As", "Cu"], "physical_rows": 1},
            )
        )
    foregs_line, foregs_values, foregs_units, foregs_limits = parsed_foregs[0]
    require(
        foregs_line == 4
        and foregs_values == {"GTN": "X-1", "As": "1", "As__2": "2", "Cu": "0.5"}
        and foregs_units["As__2"] == "mg/kg"
        and foregs_limits["Cu"] == "1"
        and foregs._half_detection_limit(foregs_values["As"], foregs_limits["As"])
        and foregs._half_detection_limit(foregs_values["Cu"], foregs_limits["Cu"]),
        "D1 FOREGS parser preserves three metadata rows, duplicate headers and possible half-DL flags",
        checks,
    )
    afsis = source_contracts.registry_candidate("afsis-phase-i-wet-chemistry")
    require(
        afsis.version == "2.0"
        and afsis.license_id == "CC-BY-4.0"
        and set(afsis.registry_entry["target_analytes"])
        == {"As", "Cr", "Cu", "Ni", "Pb", "Zn"}
        and afsis.registry_entry["expected_counts"]["physical_rows"] == 2002
        and afsis.registry_entry["expected_counts"]["complete_coordinate_pairs"] == 1876
        and afsis.registry_entry["expected_counts"]["positive_below_dl_counts"]["Pb"]
        == 1969,
        "D1 AfSIS candidate pins version 2.0, six analytes and its coordinate and detection-limit boundaries",
        checks,
    )
    require(
        afsis.registry_entry["research_slice_capacity"][
            "all_registered_positive_sample_rows"
        ]
        == 1941
        and afsis.registry_entry["research_slice_capacity"][
            "all_registered_positive_complete_coordinate_rows"
        ]
        == 1821,
        "D1 AfSIS separates full-source audit counts from its positive research-slice capacity",
        checks,
    )
    with tempfile.TemporaryDirectory(
        prefix="afsis-xlsx-contract-"
    ) as temporary_directory:
        workbook = Path(temporary_directory) / "synthetic.xlsx"
        with zipfile.ZipFile(workbook, "w") as archive:
            archive.writestr(
                "xl/sharedStrings.xml",
                '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<si><t>variable name</t></si><si><t>As.75</t></si></sst>",
            )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheetData><row r="1"><c r="B1" t="s"><v>0</v></c></row>'
                '<row r="2"><c r="B2" t="s"><v>1</v></c><c r="D2"><v>2.5</v></c></row>'
                "</sheetData></worksheet>",
            )
        parsed_xlsx = source_contracts.AfsisPhaseIWetChemistryAdapter._xlsx_rows(
            workbook
        )
    require(
        parsed_xlsx == [(1, ["", "variable name"]), (2, ["", "As.75", "", "2.5"])],
        "D1 AfSIS workbook reader preserves sparse columns without extracting untrusted members",
        checks,
    )
    catalog = source_router.load_catalog()
    request_schema = json_value(SKILL_DIR / "references" / "request.schema.json")
    region_branches = request_schema["properties"]["region"]["oneOf"]
    require(
        len(region_branches) == 2
        and {branch.get("type") for branch in region_branches} == {"string", "object"},
        "D1 request Schema keeps global/named regions disjoint from bbox objects",
        checks,
    )
    valid_request = {
        "elements": ["As"],
        "region": "global",
        "media": ["soil"],
    }
    invalid_request_overrides = [
        {"elements": ["As", "As"]},
        {"measurement_basis": "dry weight"},
        {"measurement_basis": []},
        {"geology_units": "basalt"},
        {"geology_units": []},
        {"geology_match": "fuzzy"},
        {"time_range": ["2020"]},
        {"time_range": ["unknown", "2020"]},
        {"time_range": ["2021", "2020"]},
        {"sources": ["usgs-conus-soil", "usgs-conus-soil"]},
        {"output_formats": ["csv", "parquet"]},
        {"target_crs": "EPSG:3857"},
        {"max_records": True},
        {"max_records": 200001},
        {"offline": "false"},
        {"coverage_mode": "minimum_only"},
        {"minimum_elements": True},
        {"minimum_elements": 2},
        {"minimum_media": 2},
        {"spatial_domains": []},
        {"spatial_domains": ["land", "land"]},
        {"spatial_domains": ["land", "atmosphere"]},
        {"adjacent_marine_distance_km": True},
        {"adjacent_marine_distance_km": 1001},
        {"spatial_domains": ["land"], "adjacent_marine_distance_km": 10},
    ]
    rejected_invalid_requests = 0
    for override in invalid_request_overrides:
        invalid_request = dict(valid_request)
        invalid_request.update(override)
        try:
            source_router.validate_request(invalid_request, catalog)
        except source_router.SourceRoutingError:
            rejected_invalid_requests += 1
    require(
        rejected_invalid_requests == len(invalid_request_overrides),
        "D1 router enforces every shared request field instead of bypassing its JSON Schema",
        checks,
    )
    require(
        source_router.basis_matches("total", "near_total_acid_digest")
        and source_router.basis_matches("dissolved", "filtered_water")
        and not source_router.basis_matches("dissolved", "unfiltered_total_water"),
        "D1 measurement-basis matching uses token boundaries and never treats unfiltered as filtered",
        checks,
    )
    require(
        request_runner._year_bounds("2009/2013") == (2009, 2013),
        "D1 request filtering treats reported sampling ranges as intervals instead of one arbitrary year",
        checks,
    )
    require(
        request_runner._inside_bbox(
            {"latitude": "35", "longitude": "103", "source_crs": "EPSG:4326"},
            [100, 30, 110, 40],
        )
        and not request_runner._inside_bbox(
            {"latitude": "35", "longitude": "103", "source_crs": ""},
            [100, 30, 110, 40],
        ),
        "D1 request filtering never treats unverified source coordinates as WGS84 bbox coordinates",
        checks,
    )
    japan_scope = spatial_scope.resolve_region("日本")
    fiji_scope = spatial_scope.resolve_region("Fiji")
    require(
        japan_scope["country_code"] == "JPN"
        and japan_scope["clip_method"] == "country_polygon_and_bbox"
        and fiji_scope["bbox"][0] > fiji_scope["bbox"][2]
        and spatial_scope.coordinate_in_bbox(179, -17, [170, -20, -170, 20])
        and spatial_scope.coordinate_in_bbox(-179, -17, [170, -20, -170, 20])
        and not spatial_scope.coordinate_in_bbox(0, -17, [170, -20, -170, 20]),
        "D1 resolves frozen English/Chinese/ISO country scopes and preserves antimeridian intervals",
        checks,
    )
    china_scope = spatial_scope.resolve_region("China")
    china_mainland_scope = spatial_scope.resolve_region("中国大陆")
    require(
        china_scope["country_code"] == "CHN"
        and china_scope["analysis_country_codes"] == ["CHN", "TWN"]
        and china_scope["clip_method"] == "analysis_country_union_and_bbox"
        and china_scope["cartographic_reference"]["review_number"] == "GS(2023)2767号"
        and china_mainland_scope["analysis_country_codes"] == ["CHN"]
        and spatial_scope.coordinate_in_request_scope(
            121.0,
            23.7,
            china_scope,
            spatial_domain="land",
            spatial_domains=["land"],
            adjacent_marine_distance_km=0,
        )
        and not spatial_scope.coordinate_in_request_scope(
            121.0,
            23.7,
            china_mainland_scope,
            spatial_domain="land",
            spatial_domains=["land"],
            adjacent_marine_distance_km=0,
        )
        and spatial_scope.record_spatial_domain(
            {"medium": "sediment", "sediment_environment": "marine"}
        )
        == "marine"
        and spatial_scope.record_spatial_domain(
            {"medium": "water", "water_body_type": "stream"}
        )
        == "inland_water"
        and spatial_scope.coordinate_in_request_scope(
            108.0833,
            20.6,
            china_scope,
            spatial_domain="marine",
            spatial_domains=["land", "inland_water", "marine"],
            adjacent_marine_distance_km=600,
        )
        and not spatial_scope.coordinate_in_request_scope(
            121.0,
            10.0,
            china_scope,
            spatial_domain="marine",
            spatial_domains=["land", "inland_water", "marine"],
            adjacent_marine_distance_km=600,
        )
        and not spatial_scope.coordinate_in_request_scope(
            139.6917,
            35.6895,
            china_scope,
            spatial_domain="land",
            spatial_domains=["land", "inland_water", "marine"],
            adjacent_marine_distance_km=600,
        ),
        "D1 China analysis scope includes the separately encoded Taiwan geometry, preserves a mainland-only alias and admits only bounded adjacent marine samples",
        checks,
    )
    frozen_china_marine_counts: dict[str, int] = {}
    for source_id in (
        "pangaea-east-china-sea-clay",
        "pangaea-south-china-sea-sediment",
        "geotraces-idp2025",
    ):
        frozen_china_marine_counts[source_id] = sum(
            1
            for row in csv_rows(SOURCE_DEMOS / source_id / "demo_input.csv")
            if row.get("latitude")
            and row.get("longitude")
            and spatial_scope.coordinate_in_request_scope(
                float(row["longitude"]),
                float(row["latitude"]),
                china_scope,
                spatial_domain=spatial_scope.record_spatial_domain(row),
                spatial_domains=["land", "inland_water", "marine"],
                adjacent_marine_distance_km=600,
            )
        )
    require(
        frozen_china_marine_counts
        == {
            "pangaea-east-china-sea-clay": 32,
            "pangaea-south-china-sea-sediment": 40,
            "geotraces-idp2025": 0,
        },
        "D1 frozen real-source controls admit East/South China Sea records while rejecting a disjoint ocean slice",
        checks,
    )
    try:
        spatial_scope.resolve_region("not-a-frozen-region")
    except spatial_scope.SpatialScopeError:
        unknown_region_rejected = True
    else:
        unknown_region_rejected = False
    require(
        unknown_region_rejected,
        "D1 named-region resolution fails closed instead of guessing an unfrozen boundary",
        checks,
    )
    fake_now = [100.0]
    budget = execution_budget.ExecutionBudget(10, clock=lambda: fake_now[0])
    initial_child_timeout = budget.child_timeout("test", reserve_seconds=2)
    fake_now[0] = 109.5
    try:
        budget.child_timeout("test", reserve_seconds=1)
    except execution_budget.ExecutionBudgetError:
        expired_budget_rejected = True
    else:
        expired_budget_rejected = False
    require(
        initial_child_timeout == 8.0 and expired_budget_rejected,
        "D1 orchestration uses one monotonic deadline and never spends the downstream reserve",
        checks,
    )
    require(
        execution_budget.OFFICIAL_TASK_LIMIT_SECONDS == 900.0
        and execution_budget.OFFICIAL_HARNESS_RESERVE_SECONDS == 180.0
        and execution_budget.DEFAULT_INTERNAL_BUDGET_SECONDS == 1800.0
        and execution_budget.EXTENDED_RESEARCH_LIMIT_SECONDS == 43200.0
        and execution_budget.MAX_INTERNAL_BUDGET_SECONDS == 43200.0,
        "D1 distinguishes the official 900-second envelope from explicit extended research",
        checks,
    )
    with tempfile.TemporaryDirectory(prefix="request-scope-contract-") as scope_temp:
        scope_root = Path(scope_temp)
        scope_input = scope_root / "input.csv"
        scope_input.write_text(
            "record_id,element_or_analyte,medium,sediment_environment,latitude,longitude,source_crs,geologic_unit\n"
            "beijing,Cu,soil,,39.9042,116.4074,EPSG:4326,Unit A\n"
            "tokyo,Cu,soil,,35.6895,139.6917,EPSG:4326,Unit A\n"
            "hainan-sea,Cu,sediment,marine,20.6,108.0833,EPSG:4326,Unit A\n"
            "far-sea,Cu,sediment,marine,10,121,EPSG:4326,Unit A\n"
            "east,Cu,soil,,0,179,EPSG:4326,Unit A\n"
            "west,Cu,soil,,0,-179,EPSG:4326,Unit A\n"
            "greenwich,Cu,soil,,0,0,EPSG:4326,Unit A\n",
            encoding="utf-8",
        )
        china_output = scope_root / "china.csv"
        _, china_count, _ = request_runner.filter_bundle(
            scope_input,
            None,
            {
                **source_router.validate_request(
                    {
                        "elements": ["Cu"],
                        "region": "China",
                        "media": ["soil", "sediment"],
                        "spatial_domains": ["land", "inland_water", "marine"],
                        "adjacent_marine_distance_km": 600,
                        "geology_units": ["Unit A"],
                    },
                    catalog,
                ),
                "max_records": 50,
            },
            china_output,
            None,
        )
        dateline_output = scope_root / "dateline.csv"
        _, dateline_count, _ = request_runner.filter_bundle(
            scope_input,
            None,
            {
                **source_router.validate_request(
                    {
                        "elements": ["Cu"],
                        "region": {"bbox": [170, -20, -170, 20]},
                        "media": ["soil"],
                    },
                    catalog,
                ),
                "max_records": 50,
            },
            dateline_output,
            None,
        )
        require(
            china_count == 2
            and {row["record_id"] for row in csv_rows(china_output)}
            == {"beijing", "hainan-sea"}
            and dateline_count == 2
            and {row["record_id"] for row in csv_rows(dateline_output)}
            == {"east", "west"},
            "D1 request execution applies strict land polygons, bounded adjacent-marine domains, geology labels, and wrapped bbox filters",
            checks,
        )
    normalized_request = source_router.validate_request(valid_request, catalog)
    require(
        normalized_request
        == {
            "elements": ["As"],
            "region": "global",
            "media": ["soil"],
            "coverage_mode": "fixed",
            "minimum_elements": None,
            "minimum_media": None,
            "spatial_domains": ["land"],
            "adjacent_marine_distance_km": 0,
            "measurement_basis": None,
            "geology_units": None,
            "geology_match": "reported_or_matched",
            "time_range": None,
            "sources": "auto",
            "output_formats": ["csv", "json", "geojson", "html_map"],
            "target_crs": "EPSG:4326",
            "license_policy": "open_only",
            "research_use_policy": "permitted_research",
            "minimum_evidence_tier": "D",
            "minimum_use_mode": "normalized_analysis",
            "max_records": 50000,
            "offline": False,
        },
        "D1 router freezes and echoes every documented optional request default",
        checks,
    )
    with tempfile.TemporaryDirectory() as coverage_temp:
        coverage_input = Path(coverage_temp) / "filtered.csv"
        coverage_input.write_text(
            "element_or_analyte,medium,sediment_environment\n"
            "As,soil,\nCu,sediment,marine\n",
            encoding="utf-8",
        )
        request_coverage, request_warnings = request_runner.request_dimension_coverage(
            coverage_input,
            {
                "elements": ["As", "Cu"],
                "media": ["soil", "sediment", "water"],
                "spatial_domains": ["land", "inland_water", "marine"],
            },
        )
    require(
        request_coverage["status"] == "partial"
        and request_coverage["dimensions"]["media"]["missing"] == ["water"]
        and request_coverage["dimensions"]["spatial_domains"]["observed"]
        == ["land", "marine"]
        and request_coverage["dimensions"]["spatial_domains"]["missing"]
        == ["inland_water"]
        and len(request_warnings) == 2,
        "D1 request execution reports every requested element, medium and spatial domain absent from the result",
        checks,
    )
    geology_route = source_router.route_sources(
        {
            "elements": ["Cu"],
            "region": "global",
            "media": ["soil"],
            "geology_units": ["GLiM:2:sc"],
            "geology_match": "matched",
        },
        catalog,
    )
    require(
        geology_route["route_version"] == "geochemical-source-route-v5"
        and geology_route["selected_sources"]
        and all(
            item["request_compatibility"]["geology"]["status"] == "enforced_downstream"
            for item in geology_route["selected_sources"]
        ),
        "D1 route carries geological-unit intent to the deterministic downstream matcher",
        checks,
    )
    breadth_route = source_router.route_sources(
        {
            "elements": ["As", "Cu", "Pb", "Zn"],
            "region": "China",
            "media": ["rock", "soil", "sediment", "water"],
            "coverage_mode": "maximize_evidence_breadth",
            "minimum_elements": 3,
            "minimum_media": 2,
        },
        catalog,
    )
    require(
        breadth_route["breadth_audit"]["elements"]["audited_candidates"]
        == ["As", "Cu", "Pb", "Zn"]
        and breadth_route["breadth_audit"]["elements"]["minimum_required"] == 3
        and breadth_route["breadth_audit"]["media"]["audited_candidates"]
        == ["rock", "soil", "sediment", "water"]
        and breadth_route["breadth_audit"]["media"]["minimum_required"] == 2
        and breadth_route["breadth_audit"]["media"]["items"]["rock"]["status"]
        == "selected"
        and breadth_route["breadth_audit"]["media"]["items"]["rock"]["selected_sources"]
        == [
            "earthchem-dehailonggang-rock",
            "georoc-archaean",
            "georoc-convergent-margins",
            "zenodo-gard-whole-rock",
        ],
        "D1 breadth audit preserves every at-least candidate and exposes both local and compilation-backed China-rock evidence",
        checks,
    )
    breadth_grid = spatial_sufficiency.build_scope_coverage_grid(
        spatial_scope.resolve_region("global"),
        spatial_sufficiency.load_policy(),
    )
    three_region_cells: list[str] = []
    for region in ("Asia", "Europe", "North America"):
        three_region_cells.extend(breadth_grid["coverage_zone_cells"][region][:35])
    three_region_samples = [
        {
            "source_id": "source-a",
            "sample_identity": f"sample-{index}",
            "canonical_point": list(
                spatial_scope.coverage_grid_cell_center(
                    cell_id, breadth_grid["cell_degrees"]
                )
            ),
            "display_point": list(
                spatial_scope.coverage_grid_cell_center(
                    cell_id, breadth_grid["cell_degrees"]
                )
            ),
            "elements": ["As"],
            "media": ["soil"],
            "element_medium": ["As|soil"],
        }
        for index, cell_id in enumerate(three_region_cells)
    ]
    breadth_spatial_audit = spatial_sufficiency.audit_spatial_views(
        three_region_samples,
        {
            "elements": ["As"],
            "media": ["soil"],
            "region": "global",
            "coverage_mode": "maximize_evidence_breadth",
        },
    )
    breadth_soil_view = next(
        view
        for view in breadth_spatial_audit["views"]
        if view["view_id"] == "medium:soil"
    )
    require(
        breadth_soil_view["status"] == "gap"
        and breadth_soil_view["minimum_land_macroregions"] == 6
        and breadth_soil_view["missing_land_macroregions"]
        == ["Africa", "Oceania", "South America"]
        and "land_macroregion_coverage_debt" in breadth_soil_view["reason_codes"],
        "D1 breadth mode keeps every missing land macroregion as repair debt even after the legacy three-zone floor passes",
        checks,
    )
    breadth_targets = spatial_sufficiency.rank_global_country_targets(breadth_soil_view)
    breadth_macroregions = spatial_scope.load_macroregion_registry()
    require(
        [
            breadth_macroregions[code]
            for code in breadth_targets[
                : len(breadth_soil_view["missing_land_macroregions"])
            ]
        ]
        == breadth_soil_view["missing_land_macroregions"],
        "D1 global repair ranking routes one country from every declared missing land macroregion before filling lower-priority holes",
        checks,
    )
    core_country = breadth_grid["core_country_codes"][0]
    core_bands = breadth_grid["country_longitude_bands"][core_country]
    retained_band = core_bands[-1]
    globally_broad_samples = []
    for index, cell_id in enumerate(breadth_grid["reference_land_cell_ids"]):
        band_id = breadth_grid["country_longitude_band_by_cell"].get(cell_id)
        if band_id in set(core_bands) - {retained_band}:
            continue
        point = list(
            spatial_scope.coverage_grid_cell_center(
                cell_id, breadth_grid["cell_degrees"]
            )
        )
        globally_broad_samples.append(
            {
                "source_id": "source-a",
                "sample_identity": f"global-{index}",
                "canonical_point": point,
                "display_point": point,
                "elements": ["As"],
                "media": ["soil"],
                "spatial_domains": ["land"],
                "element_medium": ["As|soil"],
            }
        )
    country_concentrated_audit = spatial_sufficiency.audit_spatial_views(
        globally_broad_samples,
        {
            "elements": ["As"],
            "media": ["soil"],
            "region": "global",
            "coverage_mode": "maximize_evidence_breadth",
        },
    )
    country_concentrated_view = next(
        view
        for view in country_concentrated_audit["views"]
        if view["view_id"] == "overall"
    )
    require(
        country_concentrated_view["status"] == "gap"
        and "core_country_longitude_band_coverage_debt"
        in country_concentrated_view["reason_codes"]
        and {
            target["band_id"]
            for target in country_concentrated_view["country_longitude_band_targets"]
            if target["country_iso_a3"] == core_country
        }
        == set(core_bands) - {retained_band}
        and spatial_sufficiency.rank_global_country_targets(country_concentrated_view)[
            0
        ]
        == core_country,
        "D1 global audit rejects a large-country one-sided cluster and emits exact generic longitude-band repair bboxes",
        checks,
    )
    offline_route = source_router.route_sources(
        {
            "elements": ["As"],
            "region": "global",
            "media": ["rock", "soil"],
            "offline": True,
        },
        catalog,
    )
    require(
        offline_route["status"] == "needs_human_review"
        and not offline_route["selected_sources"]
        and {item["source_id"] for item in offline_route["review_sources"]}
        >= {"georoc-archaean", "usgs-conus-soil"}
        and all(
            "offline_cache_not_verified" in item["reason"]
            for item in offline_route["review_sources"]
            if item["source_id"] in {"georoc-archaean", "usgs-conus-soil"}
        ),
        "D1 offline routing fails closed until a versioned hash-verified cache is checked",
        checks,
    )
    china_online_route = source_router.route_sources(
        {
            "elements": ["As", "Cu", "Pb", "Zn"],
            "region": {"bbox": [73.0, 18.0, 135.0, 54.0]},
            "media": ["soil", "sediment"],
            "offline": False,
        },
        catalog,
    )
    tpdc_route = next(
        item
        for item in china_online_route["selected_sources"]
        if item["source_id"] == "tpdc-china-mountain-soil"
    )
    require(
        tpdc_route["request_compatibility"]["region"]["status"]
        == "compatible_reported_only"
        and "CRS" in tpdc_route["request_compatibility"]["region"]["note"],
        "D1 may acquire a catalog-declared China source while keeping its coordinates reported-only",
        checks,
    )
    require(
        "production_eligible=true" not in offline_route["claim_boundary"]
        and "V4 automatic selection" in offline_route["claim_boundary"],
        "D1 route claim boundary describes V4 evidence and use gates instead of the legacy binary flag",
        checks,
    )
    catalog_schema = json_value(SKILL_DIR / "references" / "source-catalog.schema.json")
    allowed_identifier_fields = set(
        catalog_schema["$defs"]["source"]["properties"]["identifiers"]["properties"]
    )
    observed_identifier_fields = {
        field for entry in catalog["sources"].values() for field in entry["identifiers"]
    }
    require(
        observed_identifier_fields <= allowed_identifier_fields,
        "D1 catalog identifier fields remain aligned with its published JSON Schema",
        checks,
    )
    interface_schema_fields = set(
        catalog_schema["$defs"]["source"]["properties"]["interfaces"]["items"][
            "properties"
        ]
    )
    observed_interface_fields = {
        field
        for entry in catalog["sources"].values()
        for interface in entry["interfaces"]
        for field in interface
    }
    require(
        observed_interface_fields <= interface_schema_fields
        and all(
            interface.get("method") in {None, "GET", "POST"}
            for entry in catalog["sources"].values()
            for interface in entry["interfaces"]
        ),
        "D1 catalog interface fields and HTTP methods remain aligned with the published Schema",
        checks,
    )
    require(
        set(
            catalog["sources"][source_id]["status"]
            for source_id in ("georoc-archaean", "usgs-conus-soil")
        )
        == {"approved"}
        and {
            source_id
            for source_id, entry in catalog["sources"].items()
            if entry["production_eligible"]
        }
        == {"georoc-archaean", "usgs-conus-soil"},
        "D1 catalog preserves the two legacy production sources while V3 status is computed separately",
        checks,
    )
    require(
        {"rock", "soil", "sediment", "water"}
        <= {
            medium for entry in catalog["sources"].values() for medium in entry["media"]
        },
        "D1 catalog has initial discovery coverage for all four required media",
        checks,
    )
    route = source_router.route_sources(
        {
            "elements": ["As", "Cu", "Ni", "Zn"],
            "region": "global",
            "media": ["rock", "soil", "sediment", "water"],
            "sources": "auto",
            "license_policy": "open_only",
        },
        catalog,
    )
    require(
        {entry["source_id"] for entry in route["selected_sources"]}
        == {
            "georoc-archaean",
            "georoc-convergent-margins",
            "usgs-conus-soil",
            "norway-marchem",
            "geotraces-idp2025",
            "gemstat-open-archive",
            "japan-gsj-geochemical-map",
            "pangaea-north-africa-soil",
            "foregs-topsoil",
            "foregs-subsoil",
            "foregs-humus",
            "foregs-stream-water",
            "foregs-stream-sediment",
            "foregs-floodplain-sediment",
            "afsis-phase-i-wet-chemistry",
            "us-wqp-sacramento-river-arsenic",
            "australia-ngsa",
            "japan-gsj-marine-sediment",
            "pangaea-arabian-sea-sediment",
            "georoc-antarctica-intraplate",
            "tpdc-china-mountain-soil",
            "gemas-europe",
            "zenodo-yangtze-yellow-river-sediment",
            "pangaea-east-china-sea-clay",
            "pangaea-south-china-sea-sediment",
            "pangaea-barents-c-horizon-soil",
            "pangaea-amazonas-soil",
            "pangaea-batagay-soil",
            "eidc-ningbo-soil",
            "pangaea-brasol-ne-brazil-soil",
            "figshare-yangtze-basin-soil-heavy-metals",
            "earthchem-dehailonggang-rock",
            "4tu-northern-china-sediment",
            "zenodo-gard-whole-rock",
        },
        "D1 V4 router selects the thirty-four analyte-compatible normalized-analysis datasets across all media",
        checks,
    )
    require(
        route["coverage"]["rock"]["status"] == "partial"
        and route["coverage"]["soil"]["status"] == "partial"
        and route["coverage"]["sediment"]["status"] == "partial"
        and route["coverage"]["water"]["status"] == "partial",
        "D1 router does not overclaim incomplete coverage below the requested use mode",
        checks,
    )
    require(
        request_runner.effective_coordinate_mode("auto", "china", {}) == "reported"
        and request_runner.effective_coordinate_mode(
            "auto",
            None,
            {
                "selected_sources": [
                    {
                        "request_compatibility": {
                            "region": {"status": "compatible_reported_only"}
                        }
                    }
                ]
            },
        )
        == "reported"
        and request_runner.effective_coordinate_mode(
            "auto",
            None,
            {"selected_sources": [{"source_id": "tpdc-china-mountain-soil"}]},
        )
        == "reported"
        and request_runner.effective_coordinate_mode("auto", None, {}) == "canonical"
        and request_runner.effective_coordinate_mode("canonical", "china", {})
        == "canonical",
        "D1-to-D3 auto coordinates preserve canonical defaults and visibly include registered reported-only sources in regional or global routes",
        checks,
    )
    require(
        "usgs-ngdb" in {entry["source_id"] for entry in route["review_sources"]}
        and "gemstat-open-archive"
        not in {entry["source_id"] for entry in route["review_sources"]},
        "D1 router exposes relevant candidates and their review blockers",
        checks,
    )
    arsenic_water_route = source_router.route_sources(
        {"elements": ["As"], "region": "global", "media": ["water"]}, catalog, registry
    )
    require(
        {entry["source_id"] for entry in arsenic_water_route["selected_sources"]}
        == {
            "foregs-stream-water",
            "gemstat-open-archive",
            "us-wqp-sacramento-river-arsenic",
        }
        and "geotraces-idp2025"
        in {entry["source_id"] for entry in arsenic_water_route["review_sources"]}
        and next(
            entry
            for entry in arsenic_water_route["review_sources"]
            if entry["source_id"] == "geotraces-idp2025"
        )["request_compatibility"]["analytes"]["status"]
        == "incompatible",
        "D1 router applies registered analyte availability before source selection",
        checks,
    )
    explicit_mismatch_route = source_router.route_sources(
        {
            "elements": ["As"],
            "region": "global",
            "media": ["water"],
            "sources": ["georoc-archaean"],
        },
        catalog,
        registry,
    )
    explicit_mismatch = explicit_mismatch_route["review_sources"][0]
    require(
        not explicit_mismatch_route["selected_sources"]
        and explicit_mismatch["source_id"] == "georoc-archaean"
        and explicit_mismatch["matching_media"] == []
        and explicit_mismatch["request_compatibility"]["media"]["status"]
        == "incompatible"
        and "media=incompatible" in explicit_mismatch["reason"],
        "D1 audits explicitly named sources and records incompatible media instead of silently dropping them",
        checks,
    )
    incompatible_route = source_router.route_sources(
        {
            "elements": ["Au"],
            "region": {"bbox": [-30, -85, 30, -75]},
            "media": ["water"],
            "measurement_basis": ["total"],
            "time_range": ["1950", "1960"],
            "max_records": 1,
        },
        catalog,
        registry,
    )
    require(
        not incompatible_route["selected_sources"]
        and all(
            entry["request_compatibility"]["analytes"]["status"] != "compatible"
            for entry in incompatible_route["review_sources"]
            if entry["source_id"] in registry["sources"]
        )
        and all(
            entry["request_compatibility"]["max_records"]
            == {"status": "enforced_downstream", "requested": 1}
            for entry in incompatible_route["review_sources"]
        ),
        "D1 router does not reuse a global arsenic route for incompatible element, bbox, basis and time requests",
        checks,
    )
    raw_sediment_route = source_router.route_sources(
        {
            "elements": ["As", "Cu", "Ni", "Zn"],
            "region": "global",
            "media": ["sediment"],
            "minimum_evidence_tier": "C",
            "minimum_use_mode": "raw_observation",
        },
        catalog,
    )
    require(
        {entry["source_id"] for entry in raw_sediment_route["selected_sources"]}
        == {
            "australia-ngsa",
            "norway-marchem",
            "japan-gsj-geochemical-map",
            "foregs-stream-sediment",
            "foregs-floodplain-sediment",
            "japan-gsj-marine-sediment",
            "pangaea-arabian-sea-sediment",
            "pangaea-east-china-sea-clay",
            "pangaea-south-china-sea-sediment",
            "zenodo-yangtze-yellow-river-sediment",
            "4tu-northern-china-sediment",
        },
        "D1 V4 router selects all eleven analyte-compatible normalized sediment sources for a raw-observation request",
        checks,
    )
    benchmark_route = source_router.route_sources(
        {
            "elements": ["As"],
            "region": "global",
            "media": ["rock", "soil"],
            "minimum_evidence_tier": "A",
            "minimum_use_mode": "benchmark_ready",
        },
        catalog,
    )
    require(
        not benchmark_route["selected_sources"]
        and {entry["source_id"] for entry in benchmark_route["review_sources"]}
        >= {"georoc-archaean", "usgs-conus-soil", "pangaea-north-africa-soil"},
        "D1 keeps A-tier rock and soil datasets below benchmark_ready until human review is complete",
        checks,
    )
    candidate_evidence = score_source_evidence.load_candidate_evidence()
    evidence = score_source_evidence.score_catalog(
        catalog, registry, candidate_evidence
    )
    require(
        evidence == json_value(SKILL_DIR / "assets" / "source_evidence_scores.json"),
        "D1 checked-in V3 evidence report is reproducible from catalog, registry and candidate evidence",
        checks,
    )
    require(
        evidence["summary"]
        == {
            "evidence_tiers": {
                "A": 34,
                "B": 1,
                "C": 0,
                "D": len(catalog["sources"]) - 35,
                "U": 0,
            },
            "use_modes": {
                "benchmark_ready": 0,
                "normalized_analysis": 35,
                "raw_observation": 0,
                "discovery": len(catalog["sources"]) - 35,
            },
        },
        "D1 V3 evidence scoring keeps all catalog sources while separating their current use modes",
        checks,
    )
    require(
        evidence["sources"]["georoc-archaean"]["source_evidence_score"] == 85
        and evidence["sources"]["georoc-archaean"]["evidence_tier"] == "A"
        and evidence["sources"]["georoc-archaean"]["use_mode"] == "normalized_analysis"
        and evidence["sources"]["georoc-archaean"]["source_evidence_dimensions"][
            "human_review"
        ]["status"]
        == "missing",
        "D1 scores GEOROC highly without falsely marking the pending human review complete",
        checks,
    )
    require(
        evidence["sources"]["gemstat-open-archive"]["source_evidence_score"] == 85
        and evidence["sources"]["gemstat-open-archive"]["evidence_tier"] == "A"
        and evidence["sources"]["gemstat-open-archive"]["use_mode"]
        == "normalized_analysis"
        and evidence["sources"]["gemstat-open-archive"]["source_evidence_dimensions"][
            "human_review"
        ]["status"]
        == "missing",
        "D1 credits the range-verified GEMStat adapter without treating unsigned review as a hard rejection",
        checks,
    )
    decoded_fixture = b"station,value\nA,1\n"
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed_fixture = compressor.compress(decoded_fixture) + compressor.flush()
    member_name = b"test.csv"
    fixture_crc = binascii.crc32(decoded_fixture) & 0xFFFFFFFF
    range_fixture = (
        struct.pack(
            "<IHHHHHIIIHH",
            0x04034B50,
            0,
            0,
            8,
            0,
            0,
            fixture_crc,
            len(compressed_fixture),
            len(decoded_fixture),
            len(member_name),
            0,
        )
        + member_name
        + compressed_fixture
    )
    range_specification = {
        "name": "test.csv",
        "range_start": 0,
        "range_end": len(range_fixture) - 1,
        "range_sha256": hashlib.sha256(range_fixture).hexdigest(),
        "compressed_bytes": len(compressed_fixture),
        "uncompressed_bytes": len(decoded_fixture),
        "crc32": f"{fixture_crc:08x}",
        "sha256": hashlib.sha256(decoded_fixture).hexdigest(),
    }
    original_fetch = gemstat_acquisition.fetch
    original_sleep = gemstat_acquisition.time.sleep
    partial_then_complete = iter((range_fixture[:-2], range_fixture))
    gemstat_acquisition.fetch = lambda *args, **kwargs: next(partial_then_complete)
    gemstat_acquisition.time.sleep = lambda _: None
    try:
        fetched_range, decoded_range = gemstat_acquisition.fetch_verified_range(
            range_specification, timeout=1, retries=2
        )
    finally:
        gemstat_acquisition.fetch = original_fetch
        gemstat_acquisition.time.sleep = original_sleep
    require(
        fetched_range == range_fixture and decoded_range == decoded_fixture,
        "D1 GEMStat acquisition retries a truncated HTTP range until content verification passes",
        checks,
    )
    require(
        evidence["sources"]["norway-marchem"]["source_evidence_score"] == 85
        and evidence["sources"]["norway-marchem"]["evidence_tier"] == "A"
        and evidence["sources"]["norway-marchem"]["use_mode"] == "normalized_analysis"
        and evidence["sources"]["norway-marchem"]["source_evidence_dimensions"][
            "version_snapshot"
        ]["status"]
        == "verified",
        "D1 credits the frozen MarChem adapter while retaining its pending human-review limitation",
        checks,
    )
    require(
        evidence["sources"]["geotraces-idp2025"]["source_evidence_score"] == 85
        and evidence["sources"]["geotraces-idp2025"]["evidence_tier"] == "A"
        and evidence["sources"]["geotraces-idp2025"]["use_mode"]
        == "normalized_analysis"
        and evidence["sources"]["geotraces-idp2025"]["source_evidence_dimensions"][
            "human_review"
        ]["status"]
        == "missing",
        "D1 credits the pinned GEOTRACES adapter without pretending the prepared review is signed",
        checks,
    )
    require(
        evidence["sources"]["afsis-phase-i-wet-chemistry"]["source_evidence_score"]
        == 85
        and evidence["sources"]["afsis-phase-i-wet-chemistry"]["evidence_tier"] == "A"
        and evidence["sources"]["afsis-phase-i-wet-chemistry"]["use_mode"]
        == "normalized_analysis"
        and evidence["sources"]["afsis-phase-i-wet-chemistry"][
            "source_evidence_dimensions"
        ]["human_review"]["status"]
        == "missing",
        "D1 credits the pinned AfSIS files and adapter while retaining pending human review",
        checks,
    )
    tpdc_evidence = candidate_evidence["tpdc-china-mountain-soil"]
    require(
        tpdc_evidence["archive"]["bytes"] == 1828683
        and tpdc_evidence["archive"]["sha256"]
        == "8cf3189b44aad64b65cd213c0fd015d30df5f1c59676823846292f83baa1a84a"
        and len(tpdc_evidence["archive"]["members"]) == 3
        and tpdc_evidence["observed_data"]["counts"]["physical_rows"] == 1314
        and tpdc_evidence["observed_data"]["counts"]["target_observations"] == 6570
        and set(tpdc_evidence["observed_data"]["target_analytes"])
        == {"Cr", "Cu", "Ni", "Pb", "Zn"}
        and tpdc_evidence["observed_metadata"]["dataset_doi"]
        == "10.11888/Terre.tpdc.302620",
        "D1 TPDC candidate pins the content-addressed official bundle contract and five targets",
        checks,
    )
    require(
        evidence["sources"]["tpdc-china-mountain-soil"]["source_evidence_score"] == 85
        and evidence["sources"]["tpdc-china-mountain-soil"]["evidence_tier"] == "A"
        and evidence["sources"]["tpdc-china-mountain-soil"]["use_mode"]
        == "normalized_analysis"
        and evidence["sources"]["tpdc-china-mountain-soil"][
            "source_evidence_dimensions"
        ]["file_record_integrity"]["status"]
        == "verified"
        and evidence["sources"]["tpdc-china-mountain-soil"][
            "source_evidence_dimensions"
        ]["adapter_reproducibility"]["status"]
        == "verified",
        "D1 exposes TPDC as a content-addressed normalized-analysis source",
        checks,
    )
    audit = source_audit.audit_catalog(catalog, registry, candidate_evidence)
    require(
        audit["status"] == "PASS"
        and audit["summary"]["evidence_tiers"] == evidence["summary"]["evidence_tiers"]
        and audit["sources"]["gemstat-open-archive"]["operational_status"]
        == "available"
        and audit["sources"]["gemstat-open-archive"]["evidence_tier"] == "A",
        "D1 audit separates operational research-use restrictions from progressive evidence tier",
        checks,
    )
    tampered_catalog = copy.deepcopy(catalog)
    tampered_catalog["sources"]["georoc-archaean"]["license"]["status"] = "unresolved"
    tampered_audit = source_audit.audit_catalog(
        tampered_catalog, registry, candidate_evidence
    )
    require(
        tampered_audit["status"] == "PASS"
        and tampered_audit["sources"]["georoc-archaean"]["research_use_status"]
        == "unknown"
        and tampered_audit["sources"]["georoc-archaean"]["operational_status"]
        == "restricted"
        and tampered_audit["sources"]["georoc-archaean"]["source_evidence_score"] == 85,
        "D1 separates unresolved research-use conditions from unchanged scientific evidence completeness",
        checks,
    )
    tampered_catalog["sources"]["georoc-archaean"]["license"]["status"] = "open"
    tampered_catalog["sources"]["georoc-archaean"]["version"]["value"] = (
        "unreviewed-new-version"
    )
    tampered_route = source_router.route_sources(
        {"elements": ["As"], "region": "global", "media": ["rock"]},
        tampered_catalog,
        registry,
    )
    require(
        "georoc-archaean"
        not in {entry["source_id"] for entry in tampered_route["selected_sources"]}
        and "conflict=adapter_reproducibility"
        in next(
            entry["reason"]
            for entry in tampered_route["review_sources"]
            if entry["source_id"] == "georoc-archaean"
        ),
        "D1 router automatically limits a source when its frozen version conflicts",
        checks,
    )
    discovery_records = [
        json.loads(line)
        for line in (SKILL_DIR / "assets" / "source_discovery_log.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        {record["source_id"] for record in discovery_records} == set(catalog["sources"])
        and all(
            isinstance(record["round"], int)
            and 1 <= record["round"] <= catalog["discovery_state"]["round"]
            and record["evidence_url"].startswith("https://")
            for record in discovery_records
        )
        and max(record["round"] for record in discovery_records)
        == catalog["discovery_state"]["round"],
        "D1 discovery log accounts for every catalog source through the current official-evidence round",
        checks,
    )
    discovery_scope = json_value(SKILL_DIR / "assets" / "source_discovery_scope.json")
    scoped_source_ids = {
        source_id
        for area in discovery_scope["areas"].values()
        for source_id in area["catalogued_sources"]
    }
    require(
        discovery_scope["round"] == catalog["discovery_state"]["round"]
        and discovery_scope["as_of"] == catalog["reviewed_at"]
        and discovery_scope["saturated"] is False
        and scoped_source_ids == set(catalog["sources"])
        and {
            "africa",
            "asia",
            "europe",
            "north-america",
            "south-america",
            "oceania",
            "marine-lacustrine-and-polar",
        }
        <= set(discovery_scope["areas"]),
        "D1 discovery scope tracks regional and marine search gaps without claiming saturation",
        checks,
    )
    marchem_verification = json_value(
        SKILL_DIR
        / "fixtures"
        / "candidate-audits"
        / "marchem-inorganic-20260805T102709Z.json"
    )
    marchem_data = marchem_verification["observed_data"]
    require(
        marchem_verification["verification_version"]
        == "marchem-candidate-verification-v1"
        and marchem_verification["source_id"] == "norway-marchem"
        and marchem_verification["archive"]["sha256"]
        == "be888784ee2eafd45ab43c036eefbae9e760057d25f64fbc323993e8809ca6c6"
        and len(marchem_verification["archive"]["members"]) == 3,
        "D1 MarChem candidate evidence pins the observed dynamic archive and member inventory",
        checks,
    )
    require(
        marchem_data["data_record_count"] == 1070
        and marchem_data["distinct_sample_code_count"] == 880
        and marchem_data["duplicate_sample_code_count"] == 190
        and marchem_data["target_bearing_row_count"] == 880
        and marchem_data["sample_codes_with_target_count"] == 880
        and marchem_data["sample_codes_without_target_count"] == 0
        and marchem_data["sample_codes_with_multiple_target_rows_count"] == 0,
        "D1 MarChem verification distinguishes export rows, repeated sample codes and target-bearing rows",
        checks,
    )
    require(
        all(
            profile["record_count"] == 1070
            and profile["present_count"] == 880
            and profile["present_count"] + profile["missing_count"]
            == profile["record_count"]
            and profile["invalid_count"] == 0
            and profile["reported_unit"] == "mg/kg"
            and profile["weight_basis"] == "dry"
            for profile in marchem_data["target_analytes"].values()
        )
        and marchem_verification["observed_metadata"]["partial_digestion_disclosed"]
        is True
        and marchem_verification["observed_metadata"]["not_total_content_disclosed"]
        is True
        and marchem_verification["observed_metadata"]["accreditation_rows"][
            "not_accredited"
        ]
        > 0,
        "D1 MarChem evidence preserves target units, censoring context, partial digestion and accreditation limits",
        checks,
    )
    require(
        len(marchem_verification["prepared_human_review_sample"]) == 30
        and marchem_verification["human_review"]
        == {
            "required_record_count": 30,
            "prepared_record_count": 30,
            "status": "pending",
        }
        and verify_marchem_candidate.parse_value("<2.0") == ("censored_lt", 2.0),
        "D1 prepares but does not falsely mark the required MarChem human review as complete",
        checks,
    )
    marchem_snapshot_path = (
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "sediment"
        / "norway-marchem"
        / "snapshot_manifest.json"
    )
    marchem_snapshot = snapshot_source.build_snapshot_from_paths(
        SKILL_DIR
        / "fixtures"
        / "candidate-audits"
        / "marchem-inorganic-20260805T102709Z.json"
    )
    require(
        marchem_snapshot == json_value(marchem_snapshot_path)
        and marchem_snapshot["snapshot_id"]
        == "norway-marchem:2026-08-05T10:27:11Z:be888784ee2e"
        and marchem_snapshot["request"]["canonical_request_sha256"]
        == "ae8fd044ad9a43c0fba34d18fdcbf677311f77da1cdb76094c6054c447eb3445"
        and marchem_snapshot["counts"]["raw_records"] == 1070
        and marchem_snapshot["counts"]["distinct_samples"] == 880,
        "D1 builds the checked-in MarChem snapshot deterministically from exact request and content evidence",
        checks,
    )
    require(
        marchem_snapshot["response"]["http_status"] is None
        and marchem_snapshot["response"]["http_status_evidence"]
        == "missing_from_original_acquisition_manifest"
        and marchem_snapshot["evidence"]["publisher_checksum_status"] == "missing",
        "D1 snapshot preserves missing HTTP-status and publisher-checksum evidence instead of inventing it",
        checks,
    )
    identical_snapshot_diff = snapshot_source.diff_snapshots(
        marchem_snapshot, copy.deepcopy(marchem_snapshot)
    )
    require(
        identical_snapshot_diff["status"] == "identical"
        and identical_snapshot_diff["requires_rescore"] is False,
        "D1 snapshot diff recognizes an identical manifest without forcing rescore",
        checks,
    )
    changed_snapshot = copy.deepcopy(marchem_snapshot)
    changed_snapshot["response"]["sha256"] = "0" * 64
    changed_snapshot_diff = snapshot_source.diff_snapshots(
        marchem_snapshot, changed_snapshot
    )
    require(
        changed_snapshot_diff["status"] == "changed"
        and changed_snapshot_diff["requires_rescore"] is True
        and changed_snapshot_diff["comparisons"]["response_changed"] is True,
        "D1 snapshot diff forces rescore when a dynamic response hash changes",
        checks,
    )
    marchem_reconciliation = json_value(
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "sediment"
        / "norway-marchem"
        / "adapter_reconciliation.json"
    )
    require(
        marchem_reconciliation["status"] == "PASS"
        and marchem_reconciliation["snapshot_id"] == marchem_snapshot["snapshot_id"]
        and marchem_reconciliation["snapshot_response_sha256"]
        == marchem_snapshot["response"]["sha256"]
        and marchem_reconciliation["counts"]["physical_rows"] == 1070
        and marchem_reconciliation["counts"]["distinct_samples"] == 880
        and marchem_reconciliation["counts"]["target_observations"] == 3520
        and marchem_reconciliation["counts"]["missing_target_method_links"] == 0,
        "D1 MarChem adapter reconciles every snapshot row, sample and target method link",
        checks,
    )
    require(
        marchem_reconciliation["counts"]["target_censored_counts"]
        == {"As": 20, "Cu": 18, "Ni": 2, "Zn": 5}
        and marchem_reconciliation["measurement_semantics"]["units"] == ["mg/kg"]
        and marchem_reconciliation["measurement_semantics"]["weight_bases"]
        == ["Dry weight"]
        and marchem_reconciliation["checks"]["partial_digestion_boundary_preserved"]
        is True
        and marchem_reconciliation["checks"]["accreditation_variation_preserved"]
        is True,
        "D1 MarChem reconciliation preserves censoring, dry weight, partial digestion and accreditation",
        checks,
    )
    marchem_human_review = json_value(
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "sediment"
        / "norway-marchem"
        / "human_review.json"
    )
    require(
        marchem_human_review["review_version"] == "geochemical-human-review-v1"
        and marchem_human_review["status"] == "prepared"
        and marchem_human_review["prepared_record_count"] == 30
        and marchem_human_review["automated_pass_count"] == 30
        and marchem_human_review["completed_record_count"] == 0
        and all(
            record["automated_status"] == "PASS"
            for record in marchem_human_review["records"]
        ),
        "D1 prepares 30 passing MarChem comparisons without claiming human completion",
        checks,
    )
    require(
        all(
            record["reviewer"]
            == {"decision": None, "reviewer": None, "reviewed_at": None, "notes": None}
            for record in marchem_human_review["records"]
        )
        and any(
            not record["adapter_observations"]
            for record in marchem_human_review["records"]
        )
        and any(
            any(
                str(value).startswith("<")
                for value in record["published_target_raw_values"].values()
            )
            for record in marchem_human_review["records"]
        ),
        "D1 review sheet awaits a named reviewer and includes missing and censored edge cases",
        checks,
    )
    with tempfile.TemporaryDirectory(prefix="marchem-semantic-pin-") as marchem_temp:
        marchem_root = Path(marchem_temp)
        synthetic_registry = copy.deepcopy(registry)
        synthetic_download = synthetic_registry["sources"]["norway-marchem"]["download"]
        synthetic_members = {
            "metadata": b"Batch;Lab_parameter_code\nA;As\n",
            "data": b"Sample_code;Longitude;Latitude\nS1;10;60\n",
            "info": (
                b"MarChem - The Marine Chemistry database for Norwegian waters\n"
                b"CC-BY 4.0\nfrom year 2003 to 2024\n"
                b"from latitude 57.0 to 85.0 and from longitude -5.0 to 38.0\n"
            ),
        }
        for member in synthetic_download["members"]:
            payload = synthetic_members[member["file_id"]]
            member["bytes"] = len(payload)
            member["expected_sha256"] = hashlib.sha256(payload).hexdigest()
        registry_path = marchem_root / "source_manifest.json"
        registry_path.write_text(
            json.dumps(synthetic_registry, ensure_ascii=False), encoding="utf-8"
        )

        def write_marchem_wrapper(path: Path, data_payload: bytes) -> None:
            with zipfile.ZipFile(
                path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr(
                    "MetaData/MarChem_Inorganic_LabParameter_20990101T010203Z.csv",
                    synthetic_members["metadata"],
                )
                archive.writestr(
                    "MarChem_Inorganic_Data_20990101T010203Z.csv", data_payload
                )
                archive.writestr(
                    "MarChem_Info_20990101T010203Z", synthetic_members["info"]
                )

        dynamic_archive = marchem_root / "dynamic.zip"
        write_marchem_wrapper(dynamic_archive, synthetic_members["data"])
        semantic_adapter = source_contracts.MarchemSnapshotAdapter(registry_path)
        admitted = semantic_adapter.files_from_archive(
            dynamic_archive, marchem_root / "admitted-members"
        )
        tampered_archive = marchem_root / "tampered.zip"
        write_marchem_wrapper(
            tampered_archive, synthetic_members["data"] + b"S2;11;61\n"
        )
        tamper_failed_closed = False
        try:
            semantic_adapter.files_from_archive(
                tampered_archive, marchem_root / "tampered-members"
            )
        except source_contracts.SourceAdapterError as exc:
            tamper_failed_closed = "scientific member" in str(exc)
        require(
            [item.file_id for item in admitted] == ["metadata", "data", "info"]
            and tamper_failed_closed,
            "D1 MarChem accepts timestamp-only wrapper drift but fails closed on scientific-member drift",
            checks,
        )
        full_candidate = source_contracts.registry_candidate("norway-marchem")
        target_fields = full_candidate.registry_entry["target_analytes"]
        synthetic_data_path = marchem_root / "research-data.csv"
        synthetic_data_path.write_text(
            "verified-member-placeholder\n", encoding="utf-8"
        )
        synthetic_download = source_contracts.DownloadedFile(
            source_id="norway-marchem",
            file_id="data",
            path=synthetic_data_path,
            source_url="https://marchem-api.hi.no/test#member=data",
            bytes=synthetic_data_path.stat().st_size,
            cache_status="verified_test",
            retrieved_at="2026-08-14T00:00:00Z",
        )
        research_records = []
        for index in range(29):
            methods = {
                field_name: {
                    "Unit": "mg/kg",
                    "Analysis_method": "ICP-OES",
                    "LLQ": "0.1",
                    "Sample_preparation_method": "partial nitric acid",
                    "Laboratory": "publisher laboratory",
                    "Batch": "2024-0001",
                    "Lab_parameter_code": field_name,
                    "Wet_or_dry_weight": "Dry weight",
                    "_metadata_source_locator": "metadata.csv#row=2",
                    "_metadata_batch_expression": "2024-0001",
                    "_accreditation_status": "not_reported",
                }
                for field_name in target_fields.values()
            }
            research_records.append(
                source_contracts.RawRecord(
                    source_id="norway-marchem",
                    source_record_id=f"synthetic-marchem-{index}",
                    source_locator=f"data.csv#row={10000 + index}",
                    fields={
                        "Sample_code": f"S-{index}",
                        "Cruise_year": "2024",
                        "Station_event_code": f"E-{index}",
                        "Longitude": str(10 + index / 100),
                        "Latitude": str(60 + index / 100),
                        "Batch_code": "2024-0001",
                        **{field_name: "1.0" for field_name in target_fields.values()},
                        "_lab_parameters": methods,
                    },
                )
            )
        research_rows, research_evidence, research_samples = (
            demo_generator.marchem_demo(
                research_records,
                {synthetic_data_path.name: synthetic_download},
                full_candidate,
                116,
                ("As", "Cu", "Ni", "Zn"),
                "research",
            )
        )
        require(
            len(research_rows) == len(research_evidence) == 116
            and research_samples == 29
            and {item["human_review_status"] for item in research_evidence}
            == {"prepared_unsigned"}
            and all(
                "complete verified target-bearing" in item["selection_rule"]
                for item in research_evidence
            ),
            "D1 MarChem research mode uses the verified population beyond the 28-row demo cap without inventing signed review",
            checks,
        )
    prepared_reference_reviews = {
        "georoc-archaean": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "rock"
            / "georoc-archaean"
            / "human_review.json"
        ),
        "usgs-conus-soil": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "soil"
            / "usgs-conus-soil"
            / "human_review.json"
        ),
        "geotraces-idp2025": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "water"
            / "geotraces-idp2025"
            / "human_review.json"
        ),
        "gemstat-open-archive": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "water"
            / "gemstat-open-archive"
            / "human_review.json"
        ),
        "pangaea-north-africa-soil": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "soil"
            / "pangaea-north-africa-soil"
            / "human_review.json"
        ),
        "japan-gsj-geochemical-map": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "sediment"
            / "japan-gsj-geochemical-map"
            / "human_review.json"
        ),
        "foregs-topsoil": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "soil"
            / "foregs-topsoil"
            / "human_review.json"
        ),
        "foregs-subsoil": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "soil"
            / "foregs-subsoil"
            / "human_review.json"
        ),
        "foregs-humus": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "soil"
            / "foregs-humus"
            / "human_review.json"
        ),
        "foregs-stream-water": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "water"
            / "foregs-stream-water"
            / "human_review.json"
        ),
        "foregs-stream-sediment": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "sediment"
            / "foregs-stream-sediment"
            / "human_review.json"
        ),
        "foregs-floodplain-sediment": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "sediment"
            / "foregs-floodplain-sediment"
            / "human_review.json"
        ),
        "afsis-phase-i-wet-chemistry": json_value(
            SKILL_DIR
            / "fixtures"
            / "four-media"
            / "soil"
            / "afsis-phase-i-wet-chemistry"
            / "human_review.json"
        ),
    }
    human_review_schema = json_value(
        SKILL_DIR / "references" / "human-review.schema.json"
    )
    allowed_review_fields = set(human_review_schema["properties"])
    required_review_fields = set(human_review_schema["required"])
    allowed_review_record_fields = set(
        human_review_schema["properties"]["records"]["items"]["properties"]
    )
    required_review_record_fields = set(
        human_review_schema["properties"]["records"]["items"]["required"]
    )
    all_prepared_reviews = {
        **prepared_reference_reviews,
        "norway-marchem": marchem_human_review,
    }
    require(
        all(
            required_review_fields <= set(review) <= allowed_review_fields
            and human_review_validator.validate_document(review)["status"] == "pending"
            and all(
                required_review_record_fields
                <= set(record)
                <= allowed_review_record_fields
                for record in review["records"]
            )
            for review in all_prepared_reviews.values()
        ),
        "D1 prepared human-review artifacts align with the published field contract",
        checks,
    )
    require(
        all(
            review["status"] == "prepared"
            and review["prepared_record_count"] == 30
            and review["automated_pass_count"] == 30
            and review["completed_record_count"] == 0
            and all(
                record["automated_status"] == "PASS" for record in review["records"]
            )
            for review in prepared_reference_reviews.values()
        ),
        "D1 prepares 30 passing reference comparisons without auto-signing them",
        checks,
    )
    review_validation = human_review_validator.validate(
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "soil"
        / "usgs-conus-soil"
        / "human_review.json"
    )
    require(
        review_validation["status"] == "pending"
        and review_validation["benchmark_ready_review"] is False
        and not review_validation["errors"],
        "D1 human-review gate validates prepared sheets without inventing benchmark readiness",
        checks,
    )
    forged_candidate = copy.deepcopy(candidate_evidence["usgs-conus-soil"])
    forged_review = forged_candidate["human_review"]
    forged_review["completed_record_count"] = 30
    forged_review["status"] = "passed"
    forged_review["all_records_reviewed"] = True
    forged_score = score_source_evidence.score_source(
        "usgs-conus-soil",
        catalog["sources"]["usgs-conus-soil"],
        registry["sources"]["usgs-conus-soil"],
        forged_candidate,
    )
    require(
        forged_score["source_evidence_dimensions"]["human_review"]["status"]
        == "conflict"
        and forged_score["use_mode"] != "benchmark_ready",
        "D1 rejects aggregate-only review promotion without signed record decisions",
        checks,
    )
    signed_candidate = copy.deepcopy(candidate_evidence["usgs-conus-soil"])
    signed_review = signed_candidate["human_review"]
    for record in signed_review["records"]:
        record["reviewer"] = {
            "decision": "pass",
            "reviewer": "independent-reviewer",
            "reviewed_at": "2026-08-08T00:00:00Z",
            "notes": "Compared source evidence and adapter output; no discrepancy found.",
        }
    signed_review["completed_record_count"] = len(signed_review["records"])
    signed_review["status"] = "passed"
    signed_review["all_records_reviewed"] = True
    signed_score = score_source_evidence.score_source(
        "usgs-conus-soil",
        catalog["sources"]["usgs-conus-soil"],
        registry["sources"]["usgs-conus-soil"],
        signed_candidate,
    )
    require(
        signed_score["source_evidence_dimensions"]["human_review"]["status"]
        == "verified"
        and signed_score["use_mode"] == "benchmark_ready",
        "D1 promotes only a complete set of signed passing review decisions",
        checks,
    )
    require(
        len(
            {
                record["source_locator"].split("#", 1)[0]
                for record in prepared_reference_reviews["georoc-archaean"]["records"]
            }
        )
        == 27
        and {
            reason
            for record in prepared_reference_reviews["usgs-conus-soil"]["records"]
            for reason in record["selection_reasons"]
            if reason.startswith("soil_layer=")
        }
        == {"soil_layer=top-0-5cm", "soil_layer=a-horizon", "soil_layer=c-horizon"}
        and sum(
            not all(record["published_target_raw_values"].values())
            for record in prepared_reference_reviews["georoc-archaean"]["records"]
        )
        > 0
        and {
            item["quality_flag"]
            for record in prepared_reference_reviews["geotraces-idp2025"]["records"]
            for item in record["adapter_observations"]
        }
        == {"1", "2", "3", "4", "5", "6"}
        and {
            item["water_fraction"]
            for record in prepared_reference_reviews["gemstat-open-archive"]["records"]
            for item in record["adapter_observations"]
        }
        == {"dissolved", "extractable", "suspended", "total"}
        and {
            item["data_quality"]
            for record in prepared_reference_reviews["gemstat-open-archive"]["records"]
            for item in record["adapter_observations"]
        }
        == {"Fair", "Good", "Pending review", "Suspect"}
        and {
            item["analyte"]
            for record in prepared_reference_reviews["pangaea-north-africa-soil"][
                "records"
            ]
            for item in record["adapter_observations"]
        }
        == {"As", "Cr", "Cu", "Ni", "Pb", "Zn"}
        and all(
            record["automated_checks"][
                "publisher_location_preserved_without_country_inference"
            ]
            for record in prepared_reference_reviews["pangaea-north-africa-soil"][
                "records"
            ]
        )
        and [
            (record["reported_sample_id"], record["sample_id_occurrence"])
            for record in prepared_reference_reviews["japan-gsj-geochemical-map"][
                "records"
            ]
            if record["reported_sample_id"] == "78013"
        ]
        == [("78013", 1), ("78013", 2)]
        and {
            item["unit"]
            for record in prepared_reference_reviews["japan-gsj-geochemical-map"][
                "records"
            ]
            for item in record["adapter_observations"]
        }
        == {"ppm", "ppb"},
        "D1 review selection spans source members, layers, missing values, QC, fractions, locations and GSJ duplicate/unit edges",
        checks,
    )
    afsis_review = prepared_reference_reviews["afsis-phase-i-wet-chemistry"]
    afsis_reasons = {
        reason
        for record in afsis_review["records"]
        for reason in record["selection_reasons"]
    }
    require(
        {
            reason.removeprefix("country=")
            for reason in afsis_reasons
            if reason.startswith("country=")
        }
        == {
            "Angola",
            "Botswana",
            "Burkina Faso",
            "Cameroon",
            "Ethiopia",
            "Ghana",
            "Guinea",
            "Kenya",
            "Madagascar",
            "Mali",
            "Mozambique",
            "Niger",
            "Nigeria",
            "SAfrica",
            "Tanzania",
            "Uganda",
            "Zambia",
            "Zimbambwe",
        }
        and {"depth=Topsoil", "depth=Subsoil", "coordinates=missing_both"}
        <= afsis_reasons
        and {"As=negative_numeric", "Cu=negative_numeric", "Pb=negative_numeric"}
        <= afsis_reasons
        and all(
            record["automated_checks"][
                "negative_and_below_limit_values_flagged_without_imputation"
            ]
            for record in afsis_review["records"]
        ),
        "D1 AfSIS review spans all country labels, depths, missing coordinates and negative instrument results",
        checks,
    )
    require(
        all(
            evidence["sources"][source_id]["source_evidence_score"] == 85.0
            and evidence["sources"][source_id]["source_evidence_dimensions"][
                "human_review"
            ]["status"]
            == "missing"
            and "30-record review sample is prepared"
            in evidence["sources"][source_id]["source_evidence_dimensions"][
                "human_review"
            ]["note"]
            for source_id in prepared_reference_reviews
        ),
        "D1 records all prepared reviews without granting unsigned evidence points",
        checks,
    )
    coverage_request = json_value(
        SOURCE_DEMOS.parent / "source-routing" / "global-all-media-request.json"
    )
    matrix = coverage_report.build_matrix(catalog, coverage_request, registry)
    require(
        matrix == json_value(SKILL_DIR / "assets" / "coverage_matrix.json"),
        "D1 checked-in coverage matrix is reproducible from the catalog and request",
        checks,
    )
    completeness_profile = profile_source_completeness.build_profile(
        SKILL_DIR / "assets" / "source_manifest.json",
        SKILL_DIR / "fixtures" / "candidate-audits",
        SOURCE_DEMOS,
    )
    require(
        completeness_profile
        == json_value(SKILL_DIR / "assets" / "v4-source-completeness.json")
        and completeness_profile["summary"]
        == {
            "executable_source_count": 35,
            "sources_with_full_audit": 23,
            "sources_with_target_observation_denominator": 35,
            "sources_without_full_audit": 12,
            "demo_record_count": 1820,
            "uniform_full_field_profiles": 35,
        }
        and completeness_profile["sources"]["georoc-archaean"]["full_population"][
            "audit_status"
        ]
        == "uniform_full_profile"
        and completeness_profile["sources"]["georoc-archaean"]["candidate_audit"][
            "audit_status"
        ]
        == "not_measured"
        and completeness_profile["sources"]["gemstat-open-archive"]["full_population"][
            "target_observation_count"
        ]
        == 3739180,
        "D1 V4 completeness profile separates full-cache profiles, candidate audits and checked-in demo rows",
        checks,
    )
    full_profile_root = SKILL_DIR / "assets" / "v4-full-profiles"
    full_manifest = json_value(full_profile_root / "manifest.json")
    coverage_balance = json_value(SKILL_DIR / "assets" / "v4-coverage-balance.json")
    cube_rows = csv_rows(SKILL_DIR / "assets" / "v4-coverage-cube.csv")
    source_field_profiles = {
        source_id: json_value(full_profile_root / source_id / "field_completeness.json")
        for source_id in registry["sources"]
    }
    marchem_health = json_value(
        full_profile_root / "norway-marchem" / "automation_health.json"
    )
    require(
        full_manifest["source_count"] == full_manifest["registered_source_count"] == 35
        and full_manifest["observation_count"] == 6989258
        and full_manifest["distinct_sample_count"] == 1551170
        and full_manifest["reported_coordinate_sample_count"] == 1522285
        and full_manifest["valid_coordinate_sample_count"] == 737757
        and full_manifest["comparable_observation_count"] == 424267
        and full_manifest["coverage_cube_rows"] == len(cube_rows) == 28304
        and sum(int(row["observation_count"]) for row in cube_rows) == 6989258
        and sum(int(row["comparable_observation_count"]) for row in cube_rows) == 424267
        and all(
            profile["profile_scope"] == "full_population"
            and profile["observation_count"] > 0
            and all(
                item["non_empty"] + item["missing"]
                == item["denominator"]
                == profile["observation_count"]
                for item in profile["fields"].values()
            )
            for profile in source_field_profiles.values()
        )
        and marchem_health["version_drift"]["outer_archive_drift"] is False
        and marchem_health["version_drift"]["status"] == "matches_registered_snapshot"
        and set(coverage_balance["media"]) == {"rock", "soil", "sediment", "water"}
        and coverage_balance["media"]["water"]["observation_count"] == 3783544
        and coverage_balance["media"]["water"]["independent_lineage_count"] == 4
        and coverage_balance["media"]["sediment"]["independent_lineage_count"] == 11
        and coverage_balance["media"]["rock"]["reported_coordinate_sample_count"]
        == 765644
        and coverage_balance["media"]["rock"]["independent_lineage_count"] == 3
        and coverage_balance["media"]["rock"]["valid_coordinate_sample_count"] == 0
        and coverage_balance["media"]["soil"]["valid_coordinate_sample_count"] == 21673
        and coverage_balance["media"]["sediment"]["valid_coordinate_sample_count"]
        == 7668
        and all(
            int(metrics[field]) >= 0
            for metrics in [
                *coverage_balance["media"].values(),
                *coverage_balance["medium_elements"].values(),
            ]
            for field in (
                "observation_count",
                "distinct_sample_count",
                "independent_lineage_count",
                "reported_coordinate_sample_count",
                "valid_coordinate_sample_count",
                "comparable_observation_count",
                "reported_covered_spatial_cells",
                "covered_spatial_cells",
            )
        )
        and all(
            coverage_balance["medium_elements"][f"rock|{element}"][
                "valid_coordinate_sample_count"
            ]
            == 0
            and coverage_balance["medium_elements"][f"rock|{element}"][
                "covered_spatial_cells"
            ]
            == 0
            for element in ("As", "Cr", "Cu", "Ni", "Pb", "Zn")
        )
        and all(
            int(row["valid_coordinate_sample_count"]) == 0
            and int(row["covered_spatial_cells"]) == 0
            for row in cube_rows
            if row["source_id"]
            in {
                "georoc-archaean",
                "georoc-convergent-margins",
                "georoc-antarctica-intraplate",
                "afsis-phase-i-wet-chemistry",
                "japan-gsj-geochemical-map",
                "japan-gsj-marine-sediment",
                "tpdc-china-mountain-soil",
                "us-wqp-sacramento-river-arsenic",
                "zenodo-yangtze-yellow-river-sediment",
                "figshare-yangtze-basin-soil-heavy-metals",
                "earthchem-dehailonggang-rock",
                "4tu-northern-china-sediment",
            }
        )
        and all(
            json_value(full_profile_root / source_id / "spatial_coverage.json")[
                "coordinate_canonicalization_status"
            ]
            == "not_canonicalized"
            for source_id in {
                "figshare-yangtze-basin-soil-heavy-metals",
                "zenodo-yangtze-yellow-river-sediment",
            }
        )
        and all(
            path.is_file() and path.read_text(encoding="utf-8") == content
            for path, content in reconcile_v4_coordinate_claims.expected_outputs().items()
        )
        and all(
            (SKILL_DIR / item["path"]).is_file()
            and (SKILL_DIR / item["path"]).stat().st_size == item["bytes"]
            and sha256_file(SKILL_DIR / item["path"]) == item["sha256"]
            for item in full_manifest["artifacts"]
        ),
        "D1 V4 full profiles prove thirty-five full-cache denominators and all coverage-cube metrics",
        checks,
    )
    require(
        completeness_profile["sources"]["afsis-phase-i-wet-chemistry"]["demo_fixture"][
            "field_completeness"
        ]["sample_type"]["rate"]
        == 1.0
        and completeness_profile["sources"]["gemstat-open-archive"]["demo_fixture"][
            "field_completeness"
        ]["water_fraction"]["rate"]
        == 1.0
        and completeness_profile["sources"]["georoc-archaean"]["demo_fixture"][
            "field_completeness"
        ]["method_scope"]["rate"]
        == 0.0,
        "D1 V4 demo profile reports populated semantics and preserves explicit missing method scope",
        checks,
    )
    require(
        matrix["overall_status"] == "partial"
        and matrix["cells"]["rock"]["source_independence"]
        == "multiple_sources_but_single_source_per_analyte"
        and matrix["cells"]["rock"]["independent_lineage_count"] == 3
        and matrix["cells"]["rock"]["selected_sources"]
        == [
            "earthchem-dehailonggang-rock",
            "georoc-antarctica-intraplate",
            "georoc-archaean",
            "georoc-convergent-margins",
            "zenodo-gard-whole-rock",
        ]
        and matrix["cells"]["rock"]["analyte_source_counts"]
        == {"As": 4, "Cr": 3, "Cu": 5, "Hg": 1, "Ni": 5, "Pb": 3, "Zn": 5}
        and matrix["cells"]["rock"]["analyte_coverage"]
        == "complete_for_registered_targets"
        and matrix["cells"]["soil"]["selected_sources"]
        == [
            "afsis-phase-i-wet-chemistry",
            "eidc-ningbo-soil",
            "figshare-yangtze-basin-soil-heavy-metals",
            "foregs-humus",
            "foregs-subsoil",
            "foregs-topsoil",
            "gemas-europe",
            "pangaea-amazonas-soil",
            "pangaea-barents-c-horizon-soil",
            "pangaea-batagay-soil",
            "pangaea-brasol-ne-brazil-soil",
            "pangaea-north-africa-soil",
            "tpdc-china-mountain-soil",
            "usgs-conus-soil",
        ]
        and matrix["cells"]["soil"]["analyte_source_counts"]
        == {"As": 11, "Cr": 10, "Cu": 14, "Hg": 6, "Ni": 12, "Pb": 13, "Zn": 14}
        and matrix["cells"]["sediment"]["selected_sources"]
        == [
            "4tu-northern-china-sediment",
            "australia-ngsa",
            "australia-ngsa-mercury",
            "foregs-floodplain-sediment",
            "foregs-stream-sediment",
            "japan-gsj-geochemical-map",
            "japan-gsj-marine-sediment",
            "norway-marchem",
            "pangaea-arabian-sea-sediment",
            "pangaea-east-china-sea-clay",
            "pangaea-south-china-sea-sediment",
            "zenodo-yangtze-yellow-river-sediment",
        ]
        and matrix["cells"]["sediment"]["analyte_source_counts"]
        == {"As": 9, "Cr": 9, "Cu": 11, "Hg": 6, "Ni": 9, "Pb": 10, "Zn": 11}
        and matrix["cells"]["water"]["analyte_coverage"]
        == "complete_for_registered_targets"
        and matrix["cells"]["water"]["missing_analytes"] == []
        and matrix["cells"]["water"]["source_independence"]
        == "multiple_sources_but_single_source_per_analyte"
        and matrix["cells"]["water"]["analyte_source_counts"]
        == {"As": 3, "Cr": 2, "Cu": 3, "Hg": 1, "Ni": 3, "Pb": 2, "Zn": 3},
        "D1 coverage matrix keeps rock, soil, sediment and water source independence explicit",
        checks,
    )
    archive_bundle = json_value(
        SKILL_DIR / "fixtures" / "schema-v1" / "archive-bundle.json"
    )
    archive_validation = acquisition_validator.validate_bundle(archive_bundle)
    require(
        archive_validation["status"] == "PASS"
        and archive_validation["entity_counts"]["observations"] == 3
        and archive_validation["entity_counts"]["methods"] == 2,
        "D1 archive schema fixture preserves entities and passes relation validation",
        checks,
    )
    censored_observation = next(
        item
        for item in archive_bundle["observations"]
        if item["observation_id"] == "observation-as-lt"
    )
    require(
        censored_observation["value_raw"] == "<5"
        and censored_observation["parsed_value"] == 5.0
        and censored_observation["value_qualifier"] == "lt",
        "D1 archive schema preserves a censored raw value without imputing it",
        checks,
    )
    broken_bundle = copy.deepcopy(archive_bundle)
    broken_bundle["observations"][0]["sample_id"] = "missing-sample"
    broken_validation = acquisition_validator.validate_bundle(broken_bundle)
    require(
        broken_validation["status"] == "FAIL"
        and any("missing-sample" in error for error in broken_validation["errors"]),
        "D1 archive validation fails on a broken observation relationship",
        checks,
    )
    schema_invalid_bundle = copy.deepcopy(archive_bundle)
    del schema_invalid_bundle["datasets"][0]["title"]
    schema_invalid_validation = acquisition_validator.validate_bundle(
        schema_invalid_bundle
    )
    require(
        schema_invalid_validation["status"] == "FAIL"
        and any(
            "missing required field: title" in error
            for error in schema_invalid_validation["errors"]
        ),
        "D1 archive validation enforces entity JSON Schemas before indexing",
        checks,
    )
    v4_archive_path = SKILL_DIR / "fixtures" / "schema-v2" / "archive-bundle.json"
    v4_archive = json_value(v4_archive_path)
    v4_validation = acquisition_validator.validate_bundle(v4_archive)
    require(
        v4_validation["status"] == "PASS"
        and v4_validation["entity_counts"]["samples"] == 1
        and v4_validation["entity_counts"]["methods"] == 1,
        "D1 V4 archive validates explicit sample type, geology and method-scope contracts",
        checks,
    )
    v4_exchange = export_archive_exchange.export_rows(v4_archive)
    require(
        len(v4_exchange) == 1
        and v4_exchange[0]["sample_type_raw"] == "Topsoil"
        and v4_exchange[0]["sample_type"] == "soil_topsoil"
        and v4_exchange[0]["sample_type_mapping_status"] == "exact"
        and v4_exchange[0]["geographic_context_raw"] == "Synthetic survey block"
        and v4_exchange[0]["geologic_unit"] == ""
        and v4_exchange[0]["geologic_unit_raw"] == "Synthetic Granite"
        and v4_exchange[0]["method_scope"] == "observation"
        and v4_exchange[0]["citation_scope"] == "method",
        "D1 V4 export preserves raw/mapped semantics and never promotes geography into legacy geology",
        checks,
    )
    v4_standardized = standardizer.process_rows(v4_exchange)
    require(
        v4_standardized[0]["sample_type"] == "soil_topsoil"
        and v4_standardized[0]["geologic_unit"] is None
        and v4_standardized[0]["geologic_unit_raw"] == "Synthetic Granite"
        and v4_standardized[0]["soil_horizon"] == "A"
        and v4_standardized[0]["method_scope"] == "observation",
        "D1-to-D2 V4 exchange fields survive standardization without inference",
        checks,
    )
    legacy_without_sample_type = standardizer.normalize_row(
        {"element_or_analyte": "As", "value": "1", "unit": "mg/kg", "medium": "soil"}, 2
    )
    require(
        legacy_without_sample_type["sample_type"] is None,
        "D1 V4 never infers sample_type from analyte, unit or medium",
        checks,
    )
    ecs_contract = v4_semantics.SOURCE_CONTRACTS["pangaea-east-china-sea-clay"]
    ecs_marine = v4_semantics._sample_semantics(
        "pangaea-east-china-sea-clay",
        {"sample_fraction": "Bulk", "event": "331-C0013C"},
        ecs_contract,
    )
    ecs_river = v4_semantics._sample_semantics(
        "pangaea-east-china-sea-clay",
        {"sample_fraction": "Residue", "event": "CJ-01"},
        ecs_contract,
    )
    require(
        ecs_marine["sediment_environment"] == "marine"
        and ecs_river["sediment_environment"] == "river",
        "D1 classifies mixed East China Sea publisher events as marine or river without guessing from coordinates",
        checks,
    )
    with tempfile.TemporaryDirectory(prefix="d1-sqlite-contract-") as index_temp:
        index_root = Path(index_temp)
        first_index = index_root / "first.sqlite"
        second_index = index_root / "second.sqlite"
        archive_path = SKILL_DIR / "fixtures" / "schema-v1" / "archive-bundle.json"
        first_build = index_builder.build_index(archive_path, first_index)
        second_build = index_builder.build_index(archive_path, second_index)
        require(
            first_build["status"] == "PASS"
            and first_build["counts"]["observations"] == 3
            and first_build["counts"]["dataset_files"] == 1
            and first_build["sha256"] == second_build["sha256"],
            "D1 builds a deterministic integrity-checked SQLite index from the archive bundle",
            checks,
        )
        try:
            index_builder.build_index(archive_path, first_index)
        except ValueError as exc:
            require(
                "refusing to overwrite" in str(exc),
                "D1 index creation refuses implicit overwrite",
                checks,
            )
        else:
            raise ContractError("D1 index builder must refuse implicit overwrite")

        arsenic = query_source.query_index(
            first_index,
            analytes=["As"],
            media=["soil"],
            source_ids=["fixture-source"],
            license_ids=["CC0-1.0"],
            bbox=[-106, 38, -104, 40],
            text="Synthetic",
        )
        require(
            arsenic["record_count"] == 1
            and arsenic["records"][0]["value_raw"] == "<5"
            and arsenic["records"][0]["value_qualifier"] == "lt",
            "D1 indexed query combines analyte, medium, source, license, RTree bbox and FTS filters",
            checks,
        )
        require(
            query_source.query_index(first_index, bbox=[0, 0, 1, 1])["record_count"]
            == 0,
            "D1 RTree query excludes observations outside the requested bbox",
            checks,
        )
        require(
            query_source.query_index(first_index, methods=["XRF"])["record_count"] == 1,
            "D1 indexed query filters exact source-native analytical techniques",
            checks,
        )
        v4_index = index_root / "v4.sqlite"
        v4_build = index_builder.build_index(v4_archive_path, v4_index)
        v4_query = query_source.query_index(
            v4_index,
            sample_types=["soil_topsoil"],
            soil_horizons=["A"],
            geologic_units=["Synthetic Granite"],
            methods=["ICP-MS"],
            method_scopes=["observation"],
        )
        require(
            v4_build["status"] == "PASS"
            and v4_query["record_count"] == 1
            and v4_query["records"][0]["geographic_context_raw"]
            == "Synthetic survey block",
            "D1 V4 SQLite query filters sample type, horizon, source geology and method scope",
            checks,
        )
        with sqlite3.connect(first_index) as connection:
            trace = connection.execute(
                "SELECT source_file, source_row, adapter_version, acquisition_run_id "
                "FROM provenance_trace WHERE observation_id = ?",
                ("observation-as-lt",),
            ).fetchone()
            view_counts = {
                view: connection.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
                for view in (
                    "observation_search",
                    "sample_summary",
                    "source_coverage",
                    "provenance_trace",
                )
            }
        require(
            trace == ("fixture.csv", 2, "1.0.0", "run-fixture-v1"),
            "D1 provenance view traces an observation to source row, adapter and acquisition run",
            checks,
        )
        require(
            view_counts
            == {
                "observation_search": 3,
                "sample_summary": 2,
                "source_coverage": 3,
                "provenance_trace": 3,
            },
            "D1 SQLite contract exposes four populated query views",
            checks,
        )

        request_one = {"media": ["soil"], "elements": ["As", "Cu"], "region": "global"}
        request_reordered = {
            "region": "global",
            "elements": ["As", "Cu"],
            "media": ["soil"],
        }
        request_changed = {"region": "global", "elements": ["Zn"], "media": ["soil"]}
        key_one = cache_control.stable_request_cache_key(
            "fixture-source", "1.0.0", request_one
        )
        require(
            key_one
            == cache_control.stable_request_cache_key(
                "fixture-source", "1.0.0", request_reordered
            )
            and key_one
            != cache_control.stable_request_cache_key(
                "fixture-source", "1.0.0", request_changed
            ),
            "D1 derived-cache key is stable under JSON key order and changes with request parameters",
            checks,
        )
        cache_root = index_root / "cache"
        version_root = cache_root / "fixture-source" / "1.0.0"
        version_root.mkdir(parents=True)
        cached_data = version_root / "fixture.csv"
        cached_data.write_text("a,b\n1,2\n", encoding="utf-8")
        (version_root / "fixture.download.json").write_text(
            json.dumps(
                {
                    "output_filename": cached_data.name,
                    "sha256": sha256_file(cached_data),
                    "dataset_version": "1.0.0",
                }
            ),
            encoding="utf-8",
        )
        cache_status = cache_control.inspect_cache(
            cache_root, "fixture-source", "1.0.0", request_one
        )
        require(
            cache_status["status"] == "present"
            and cache_status["verified_manifest_count"] == 1
            and cache_status["request_cache_key"] == key_one,
            "D1 cache status command verifies versioned files and reports the request key",
            checks,
        )
        try:
            cache_control.delete_cache(cache_root, "fixture-source", "1.0.0", "wrong")
        except ValueError as exc:
            require(
                "confirmation must exactly equal" in str(exc),
                "D1 cache deletion requires an exact source@version confirmation",
                checks,
            )
        else:
            raise ContractError(
                "D1 cache deletion must reject an incorrect confirmation"
            )
        deleted = cache_control.delete_cache(
            cache_root, "fixture-source", "1.0.0", "fixture-source@1.0.0"
        )
        require(
            deleted["status"] == "deleted" and not version_root.exists(),
            "D1 cache deletion affects only the explicitly named source version",
            checks,
        )

    performance = benchmark_index.benchmark(100_000)
    require(
        performance["status"] == "PASS"
        and performance["record_count"] == 100_000
        and performance["combined_seconds"] < performance["target_seconds"],
        "D1 synthetic 100k parse/index/filter benchmark stays below the 10-second target",
        checks,
    )
    vocabulary_registry = json_value(SKILL_DIR / "assets" / "vocabulary_registry.json")
    require(
        vocabulary_registry["registry_version"] == "geochemical-vocabulary-registry-v1"
        and vocabulary_registry["vocabularies"]["earthchem-unit"]["version"] is None
        and vocabulary_registry["vocabularies"]["d1-missing-reason-v1"]["status"]
        == "internal_frozen",
        "D1 vocabulary registry distinguishes external references from frozen internal terms",
        checks,
    )
    source_record_id = source_contracts.stable_source_record_id(
        "usgs-conus-soil",
        "CO-123",
        "Appendix_2b_Top5_18Sept2013.txt#row=42",
    )
    require(
        source_record_id
        == source_contracts.stable_source_record_id(
            "usgs-conus-soil",
            "CO-123",
            "Appendix_2b_Top5_18Sept2013.txt#row=42",
        ),
        "D1 source record IDs are deterministic",
        checks,
    )
    record_id = source_contracts.stable_record_id(
        "usgs-conus-soil", source_record_id, "As", "8.0", "mg/kg"
    )
    require(
        record_id
        != source_contracts.stable_record_id(
            "usgs-conus-soil", source_record_id, "As", "8.0", "mg/kg", occurrence=1
        ),
        "D1 observation IDs preserve repeated determinations",
        checks,
    )

    expected_demo_counts = {
        "georoc-archaean": 48,
        "usgs-conus-soil": 108,
        "norway-marchem": 112,
        "geotraces-idp2025": 48,
        "gemstat-open-archive": 56,
        "japan-gsj-geochemical-map": 48,
        "pangaea-north-africa-soil": 48,
        "foregs-topsoil": 48,
        "foregs-subsoil": 48,
        "foregs-humus": 48,
        "foregs-stream-water": 48,
        "foregs-stream-sediment": 48,
        "foregs-floodplain-sediment": 48,
        "afsis-phase-i-wet-chemistry": 48,
        "us-wqp-sacramento-river-arsenic": 48,
        "australia-ngsa": 48,
        "australia-ngsa-mercury": 48,
        "japan-gsj-marine-sediment": 56,
        "pangaea-arabian-sea-sediment": 48,
        "pangaea-east-china-sea-clay": 32,
        "pangaea-south-china-sea-sediment": 40,
        "pangaea-barents-c-horizon-soil": 32,
        "georoc-antarctica-intraplate": 48,
        "tpdc-china-mountain-soil": 40,
        "gemas-europe": 52,
        "zenodo-yangtze-yellow-river-sediment": 48,
    }
    expected_demo_analyte_counts = {
        "geotraces-idp2025": {"Cu": 16, "Ni": 16, "Zn": 16},
        "foregs-humus": {"Cu": 16, "Ni": 16, "Zn": 16},
        "gemstat-open-archive": {
            "As": 8,
            "Cr": 8,
            "Cu": 8,
            "Hg": 8,
            "Ni": 8,
            "Pb": 8,
            "Zn": 8,
        },
        "us-wqp-sacramento-river-arsenic": {"As": 48},
        "australia-ngsa": {"As": 12, "Cu": 12, "Pb": 12, "Zn": 12},
        "australia-ngsa-mercury": {"Hg": 48},
        "japan-gsj-marine-sediment": {
            "As": 8,
            "Cr": 8,
            "Cu": 8,
            "Hg": 8,
            "Ni": 8,
            "Pb": 8,
            "Zn": 8,
        },
        "pangaea-arabian-sea-sediment": {
            "As": 8,
            "Cr": 8,
            "Cu": 8,
            "Ni": 8,
            "Pb": 8,
            "Zn": 8,
        },
        "pangaea-east-china-sea-clay": {"Cr": 8, "Cu": 8, "Pb": 8, "Zn": 8},
        "pangaea-south-china-sea-sediment": {
            "Cr": 8,
            "Cu": 8,
            "Ni": 8,
            "Pb": 8,
            "Zn": 8,
        },
        "pangaea-barents-c-horizon-soil": {"As": 8, "Cu": 8, "Pb": 8, "Zn": 8},
        "georoc-antarctica-intraplate": {
            "As": 8,
            "Cr": 8,
            "Cu": 8,
            "Ni": 8,
            "Pb": 8,
            "Zn": 8,
        },
        "tpdc-china-mountain-soil": {"Cr": 8, "Cu": 8, "Ni": 8, "Pb": 8, "Zn": 8},
        "gemas-europe": {"As": 8, "Cr": 8, "Cu": 8, "Hg": 4, "Ni": 8, "Pb": 8, "Zn": 8},
        "zenodo-yangtze-yellow-river-sediment": {
            "As": 8,
            "Cr": 8,
            "Cu": 8,
            "Ni": 8,
            "Pb": 8,
            "Zn": 8,
        },
        "norway-marchem": {"As": 28, "Cu": 28, "Ni": 28, "Zn": 28},
        "usgs-conus-soil": {"As": 27, "Cu": 27, "Ni": 27, "Zn": 27},
    }
    expected_demo_versions = {
        source_id: (
            "d1-demo-slice-v2"
            if source_id in {"georoc-archaean", "usgs-conus-soil"}
            else "d1-demo-slice-v1"
        )
        for source_id in expected_demo_counts
    }
    for source_id, expected_demo_count in expected_demo_counts.items():
        demo_dir = SOURCE_DEMOS / source_id
        demo_input = demo_dir / "demo_input.csv"
        sources_path = demo_dir / "sources.jsonl"
        generation_manifest = json_value(demo_dir / "run_manifest.json")
        demo_rows = csv_rows(demo_input)
        evidence_rows = [
            json.loads(line)
            for line in sources_path.read_text(encoding="utf-8").splitlines()
        ]
        require(
            len(demo_rows) == expected_demo_count
            and len(evidence_rows) == expected_demo_count,
            f"D1 {source_id} fixture has one evidence record per observation",
            checks,
        )
        require(
            generation_manifest.get("data_mode") == "fixture"
            and generation_manifest.get("not_for_scientific_interpretation") is True,
            f"D1 {source_id} fixture declares the scientific claim boundary",
            checks,
        )
        expected_hashes = {
            item["path"]: item["sha256"] for item in generation_manifest["outputs"]
        }
        require(
            expected_hashes
            == {
                "demo_input.csv": sha256_file(demo_input),
                "sources.jsonl": sha256_file(sources_path),
            },
            f"D1 {source_id} fixture manifest binds deterministic output hashes",
            checks,
        )
        require(
            {row["record_id"] for row in demo_rows}
            == {row["record_id"] for row in evidence_rows}
            and {row["source_id"] for row in demo_rows} == {source_id},
            f"D1 {source_id} fixture preserves record-level evidence linkage",
            checks,
        )
        expected_analyte_counts = expected_demo_analyte_counts.get(
            source_id, {"As": 12, "Cu": 12, "Ni": 12, "Zn": 12}
        )
        require(
            Counter(row["element_or_analyte"] for row in demo_rows)
            == Counter(expected_analyte_counts),
            f"D1 {source_id} fixture keeps its registered analytes balanced",
            checks,
        )
        require(
            generation_manifest.get("demo_generation_version")
            == expected_demo_versions[source_id]
            and {item.get("generation_version") for item in evidence_rows}
            == {expected_demo_versions[source_id]},
            f"D1 {source_id} fixture pins its evidence-complete generator contract",
            checks,
        )
    with tempfile.TemporaryDirectory(prefix="multi-source-contract-") as temporary:
        merge_root = Path(temporary)
        acquisitions = [
            {
                "source_id": source_id,
                "directory": SOURCE_DEMOS / source_id,
                "record_count": expected_demo_counts[source_id],
            }
            for source_id in ("georoc-archaean", "usgs-conus-soil")
        ]
        merged_input = merge_root / "multi_source_input.csv"
        merged_evidence = merge_root / "multi_source_evidence.jsonl"
        merged_manifest = merge_root / "multi_source_manifest.json"
        merged_count, manifest = request_runner.merge_acquired_sources(
            acquisitions,
            merged_input,
            merged_evidence,
            merged_manifest,
            {"elements": ["As"], "media": ["rock", "soil"], "region": "global"},
            "2026-08-07T00:00:00Z",
            "cached",
        )
        request_runner.verify_manifest_outputs(
            merged_manifest, [merged_input, merged_evidence]
        )
        merged_rows = csv_rows(merged_input)
        merged_evidence_rows = [
            json.loads(line)
            for line in merged_evidence.read_text(encoding="utf-8").splitlines()
        ]
        require(
            request_runner.source_budgets(["georoc-archaean", "usgs-conus-soil"], 5)
            == {"georoc-archaean": 1, "usgs-conus-soil": 4}
            and merged_count == 156
            and len(merged_rows) == len(merged_evidence_rows) == 156,
            "D1 multi-source auto mode allocates a deterministic bounded budget and preserves every record",
            checks,
        )
        require(
            request_runner.source_budgets(
                ["gemas-europe", "afsis-phase-i-wet-chemistry"],
                50000,
                4,
                per_analyte_observations=10000,
                elements=["As", "Cu", "Pb", "Zn"],
            )
            == {"gemas-europe": 28912, "afsis-phase-i-wet-chemistry": 7764}
            and request_runner.source_budgets(
                ["gemas-europe", "tpdc-china-mountain-soil"],
                10000,
                4,
                per_analyte_observations=10000,
                elements=["As", "Cu", "Pb", "Zn"],
            )
            == {"gemas-europe": 3430, "tpdc-china-mountain-soil": 6570},
            "D1 record budgets complete a finite regional survey before spending the remaining ceiling on a larger survey",
            checks,
        )
        breadth_budgets = request_runner.source_budgets(
            [
                "gemstat-open-archive",
                "australia-ngsa",
                "pangaea-amazonas-soil",
                "pangaea-north-africa-soil",
                "pangaea-barents-c-horizon-soil",
                "tpdc-china-mountain-soil",
                "afsis-phase-i-wet-chemistry",
            ],
            40_000,
            4,
            per_analyte_observations=50_000,
            elements=["As", "Cu", "Pb", "Zn"],
        )
        require(
            sum(breadth_budgets.values()) == 40_000
            and breadth_budgets["australia-ngsa"] == 8524
            and breadth_budgets["pangaea-amazonas-soil"] == 668
            and breadth_budgets["pangaea-north-africa-soil"] == 172
            and breadth_budgets["pangaea-barents-c-horizon-soil"] == 2416
            and breadth_budgets["tpdc-china-mountain-soil"] == 6570
            and breadth_budgets["afsis-phase-i-wet-chemistry"] == 7764,
            "D1 breadth budgeting fills verified finite regional capacities before an open-ended global archive consumes the ceiling",
            checks,
        )
        verbose_evidence = [
            {
                "record_id": f"rec-{index}",
                "source_record_id": f"src-{index}",
                "source_id": "fixture-source",
                "source_locator": f"fixture.csv#row={index + 2}",
                "license": "CC-BY-4.0",
                "analyte_reported": "Cu",
                "source_file": "fixture.csv",
                "source_row": index + 2,
                "source_file_sha256": "a" * 64,
                "source_file_url": "https://example.org/fixture.csv",
                "dataset_title": "A deliberately verbose audited source title",
                "dataset_doi": "10.0000/example",
                "dataset_version": "v1",
                "article_citations": ["A deliberately repeated primary citation"],
                "article_dois": ["10.0000/example"],
                "retrieved_at": "2026-08-14T00:00:00Z",
                "generation_version": "fixture-generator-v1",
                "selection_rule": "The same deterministic selection rule is repeated for every row.",
                "scientific_note": "The same scientific boundary is repeated for every row.",
                "sample_specific_field": f"sample-{index}",
            }
            for index in range(3)
        ]
        compact_evidence = request_runner.compact_record_evidence_rows(verbose_evidence)
        verbose_size = len(
            "".join(
                json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                for item in verbose_evidence
            ).encode("utf-8")
        )
        compact_size = len(request_runner.serialize_record_evidence(compact_evidence))
        require(
            len(compact_evidence) == len(verbose_evidence)
            and compact_evidence[1]["source_metadata_record_id"] == "rec-0"
            and "dataset_title" not in compact_evidence[1]
            and compact_evidence[1]["sample_specific_field"] == "sample-1"
            and compact_evidence[1]["source_file"] == "fixture.csv"
            and compact_evidence[1]["source_file_sha256"] == "a" * 64
            and compact_size < verbose_size * 0.75,
            "D1 filtered evidence deduplicates only identical source metadata while preserving row identity, source-file binding and sample-specific evidence",
            checks,
        )
        require(
            request_runner.planned_slice_observations(
                "gemstat-open-archive",
                4,
                200_000,
                per_analyte_observations=50_000,
                analytes=["As", "Cu", "Pb", "Zn"],
            )
            == request_runner.GENERATOR_MAX_OBSERVATIONS
            == 200_000,
            "D1 GEMStat planning can consume the full four-element research ceiling instead of stopping at the former 50k cap",
            checks,
        )
        require(
            request_runner.declared_slice_capacity(
                "australia-ngsa", ["As", "Cu", "Pb", "Zn"]
            )
            == 8524
            and request_runner.planned_slice_observations(
                "australia-ngsa",
                4,
                200_000,
                per_analyte_observations=50_000,
                analytes=["As", "Cu", "Pb", "Zn"],
            )
            == 8524,
            "D1 NGSA research planning excludes QA/QC duplicates without shrinking the full-source audit denominator",
            checks,
        )
        routed_global = source_router.route_sources(
            {
                "elements": ["As", "Cu", "Pb", "Zn"],
                "region": "global",
                "media": ["soil", "sediment", "water"],
                "sources": "auto",
                "max_records": 200000,
                "offline": False,
            }
        )
        balanced_ids, _ = request_runner.plan_auto_sources(
            routed_global["selected_sources"], 200000, 4
        )
        rotated_once = request_runner.rotate_source_order(balanced_ids, 1)
        rotated_full_cycle = request_runner.rotate_source_order(
            balanced_ids, len(balanced_ids)
        )
        balanced_lineages = [
            source_contracts.source_lineage_id(source_id) for source_id in balanced_ids
        ]
        foregs_positions = [
            index
            for index, lineage in enumerate(balanced_lineages)
            if lineage == "foregs-geochemical-atlas-europe-2005"
        ]
        early_ids = balanced_ids[:15]
        require(
            balanced_ids[0] == "geotraces-idp2025"
            and {
                "usgs-conus-soil",
                "pangaea-brasol-ne-brazil-soil",
                "pangaea-east-china-sea-clay",
                "pangaea-north-africa-soil",
                "figshare-yangtze-basin-soil-heavy-metals",
            }.issubset(early_ids)
            and len(set(balanced_lineages[:15])) >= 14
            and foregs_positions[0] < 15
            and foregs_positions[1] >= 15,
            "D1 global acquisition order prioritizes new spatial/media evidence and independent lineages before sibling atlas tables",
            checks,
        )
        require(
            rotated_once == balanced_ids[1:] + balanced_ids[:1]
            and rotated_full_cycle == balanced_ids
            and set(rotated_once) == set(balanced_ids),
            "D1 later rounds rotate the complete source queue without dropping evidence",
            checks,
        )
        priority_candidates = [balanced_ids[-1], balanced_ids[2], balanced_ids[-1]]
        prioritized_ids, missing_priority_ids = request_runner.prioritize_source_order(
            rotated_once,
            [*priority_candidates, "not-in-this-frozen-route"],
        )
        require(
            prioritized_ids[:2] == [balanced_ids[-1], balanced_ids[2]]
            and set(prioritized_ids) == set(balanced_ids)
            and len(prioritized_ids) == len(balanced_ids)
            and missing_priority_ids == ["not-in-this-frozen-route"],
            "D1 machine-audited gap priorities move routed sources forward without changing route membership",
            checks,
        )
        constrained_ids, constrained_skipped = request_runner.plan_auto_sources(
            routed_global["selected_sources"], 128, 4
        )
        constrained_entries = {
            str(item["source_id"]): item for item in routed_global["selected_sources"]
        }
        require(
            {
                medium
                for source_id in constrained_ids
                for medium in constrained_entries[source_id]["matching_media"]
            }
            == {"soil", "sediment", "water"}
            and len(
                {
                    source_contracts.source_lineage_id(source_id)
                    for source_id in constrained_ids
                }
            )
            == len(constrained_ids)
            and constrained_skipped,
            "D1 record-constrained source selection preserves requested media and independent spatial lineages",
            checks,
        )
        require(
            {row["record_id"] for row in merged_rows}
            == {row["record_id"] for row in merged_evidence_rows}
            and all(
                row["source_file"].startswith(f"{row['source_id']}--")
                for row in merged_rows + merged_evidence_rows
            )
            and len(manifest["source_manifests"]) == 2
            and all(
                item["filename"].startswith(f"{item['source_id']}--")
                for item in manifest["source_files"]
            ),
            "D1 multi-source merge verifies manifests, namespaces source files and preserves record-evidence bijection",
            checks,
        )
    georoc_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "georoc-archaean" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    georoc_demo_rows = csv_rows(SOURCE_DEMOS / "georoc-archaean" / "demo_input.csv")
    require(
        all(item.get("article_citations") for item in georoc_evidence)
        and not any(
            "unresolved" in citation
            for item in georoc_evidence
            for citation in item["article_citations"]
        ),
        "D1 GEOROC fixture resolves every selected citation ID to original reference text",
        checks,
    )
    georoc_rows = csv_rows(SOURCE_DEMOS / "georoc-archaean" / "demo_input.csv")
    require(
        all(
            row["original_latitude_raw"]
            and row["original_longitude_raw"]
            and not row["latitude"]
            and not row["longitude"]
            and not row["source_crs"]
            for row in georoc_rows
        )
        and all(
            item.get("coordinate_evidence", {}).get("canonicalization_status")
            == "withheld_pending_datum_verification"
            for item in georoc_evidence
        )
        and all(
            row["lithology_raw"]
            and row["geologic_age_raw"]
            and row["tectonic_setting_raw"]
            for row in georoc_demo_rows
        )
        and all(
            not row["geologic_unit_raw"] and not row["matched_geologic_unit"]
            for row in georoc_demo_rows
        ),
        "D1 GEOROC fixture preserves source geology and reported coordinates without inventing units or WGS84",
        checks,
    )
    gemstat_demo_rows = csv_rows(
        SOURCE_DEMOS / "gemstat-open-archive" / "demo_input.csv"
    )
    gemstat_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "gemstat-open-archive" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        Counter(row["water_fraction"] for row in gemstat_demo_rows)
        == Counter(
            {
                "dissolved": 16,
                "extractable": 12,
                "suspended": 12,
                "total": 16,
            }
        )
        and {row["unit"] for row in gemstat_demo_rows} == {"mg/l", "µg/l", "µg/g"}
        and {row["value_qualifier"] for row in gemstat_demo_rows} == {"", "<"}
        and {item["source_data_quality"] for item in gemstat_evidence}
        <= {"Good", "Fair"}
        and all(item["analysis_method_code"] != "0" for item in gemstat_evidence),
        "D1 GEMStat demo balances fractions while excluding undefined-method and low-quality records",
        checks,
    )
    usgs_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "usgs-conus-soil" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        {item.get("soil_layer") for item in usgs_evidence}
        == {"top-0-5cm", "a-horizon", "c-horizon"},
        "D1 USGS fixture keeps all three soil layers distinct",
        checks,
    )
    usgs_rows = csv_rows(SOURCE_DEMOS / "usgs-conus-soil" / "demo_input.csv")
    require(
        all(
            row["analytical_method"]
            and row["method_family"]
            and row["digestion_or_extraction"]
            for row in usgs_rows
        ),
        "D1 USGS fixture decodes analyte-specific method and digestion metadata",
        checks,
    )
    require(
        sum(bool(row["value_qualifier"]) for row in usgs_rows) == 3
        and all(row["detection_limit"] for row in usgs_rows if row["value_qualifier"]),
        "D1 USGS fixture exercises source-reported censored values and limits",
        checks,
    )
    require(
        {row["material"] for row in usgs_rows}
        == {"soil:top-0-5cm", "soil:a-horizon", "soil:c-horizon"}
        and Counter(row["material"] for row in usgs_rows)
        == Counter({"soil:top-0-5cm": 36, "soil:a-horizon": 36, "soil:c-horizon": 36}),
        "D1 USGS fixture makes soil horizons explicit for D2 background grouping",
        checks,
    )
    marchem_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "norway-marchem" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        {item.get("digestion_scope") for item in marchem_evidence} == {"partial"}
        and {item.get("wet_or_dry_weight") for item in marchem_evidence}
        == {"Dry weight"}
        and {item.get("accreditation_status") for item in marchem_evidence}
        == {"accredited", "not_accredited"}
        and all(item.get("metadata_source_locator") for item in marchem_evidence),
        "D1 MarChem fixture retains per-observation method and accreditation evidence",
        checks,
    )
    geotraces_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "geotraces-idp2025" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        {item.get("seadatanet_quality_flag") for item in geotraces_evidence}
        <= {"1", "2"}
        and {item.get("water_fraction") for item in geotraces_evidence} == {"dissolved"}
        and all(item.get("sample_depth_m") for item in geotraces_evidence),
        "D1 GEOTRACES fixture retains dissolved fraction, depth and accepted source QC",
        checks,
    )
    pangaea_demo_rows = csv_rows(
        SOURCE_DEMOS / "pangaea-north-africa-soil" / "demo_input.csv"
    )
    pangaea_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "pangaea-north-africa-soil" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        {row["measurement_basis"] for row in pangaea_demo_rows}
        == {"deflatable_soil_fraction_total_acid_digest"}
        and {row["grain_fraction"] for row in pangaea_demo_rows}
        == {"<20 µm fine silt-clay fraction"}
        and {row["digestion_or_extraction"] for row in pangaea_demo_rows}
        == {"HF-HNO3 acid digestion"}
        and {row["source_crs"] for row in pangaea_demo_rows} == {""}
        and {row["coordinate_evidence_scope"] for row in pangaea_demo_rows}
        == {"platform_policy_declared"}
        and {row["coordinate_policy_id"] for row in pangaea_demo_rows}
        == {"pangaea-geocode-wgs84-v1"}
        and {row["coordinate_latitude_field"] for row in pangaea_demo_rows}
        == {"Latitude"}
        and {row["coordinate_longitude_field"] for row in pangaea_demo_rows}
        == {"Longitude"}
        and all(item["reported_location"] for item in pangaea_evidence),
        "D1 PANGAEA fixture retains fine-fraction, digestion, location and platform-policy coordinate evidence",
        checks,
    )
    gsj_demo_rows = csv_rows(
        SOURCE_DEMOS / "japan-gsj-geochemical-map" / "demo_input.csv"
    )
    gsj_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "japan-gsj-geochemical-map" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        {row["measurement_basis"] for row in gsj_demo_rows}
        == {"river_sediment_<180um_national_geochemical_map"}
        and {row["grain_fraction"] for row in gsj_demo_rows}
        == {"<180 µm fine stream sediment"}
        and {row["coordinate_uncertainty_m"] for row in gsj_demo_rows} == {"20"}
        and all(
            item["original_coordinate_crs"] == "EPSG:4612 (JGD2000)"
            for item in gsj_evidence
        )
        and all(
            item["sample_file_sha256"]
            == "9fdb58d86ad48eae564291421a0dad2b6f8a4f243d3e89d90016f3c61b0b521c"
            for item in gsj_evidence
        ),
        "D1 GSJ fixture retains fine-sediment, JGD2000 and two-file evidence semantics",
        checks,
    )
    afsis_demo_rows = csv_rows(
        SOURCE_DEMOS / "afsis-phase-i-wet-chemistry" / "demo_input.csv"
    )
    afsis_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "afsis-phase-i-wet-chemistry" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        len(afsis_demo_rows) == len(afsis_evidence) == 48
        and {row["measurement_basis"] for row in afsis_demo_rows}
        == {"aqua_regia_quasi_total_air_dry_soil"}
        and {row["unit"] for row in afsis_demo_rows} == {"mg kg^-1"}
        and {row["grain_fraction"] for row in afsis_demo_rows} == {"<2 mm"}
        and {row["source_crs"] for row in afsis_demo_rows} == {""}
        and {item["reported_country"] for item in afsis_evidence}
        >= {"SAfrica", "Zimbambwe"}
        and {
            item["normalized_country"]
            for item in afsis_evidence
            if item["reported_country"] == "SAfrica"
        }
        == {"South Africa"}
        and all(item["negative_numeric_result"] is False for item in afsis_evidence)
        and any(item["below_detection_limit"] for item in afsis_evidence),
        "D1 AfSIS fixture retains aqua-regia basis, raw country labels, missing CRS and below-limit evidence",
        checks,
    )
    ngsa_atlas_rows = csv_rows(SOURCE_DEMOS / "australia-ngsa" / "demo_input.csv")
    ngsa_mercury_rows = csv_rows(
        SOURCE_DEMOS / "australia-ngsa-mercury" / "demo_input.csv"
    )
    require(
        all(
            not row["source_crs"]
            and not row["coordinate_uncertainty_m"]
            and row["coordinate_evidence_scope"] == "platform_policy_declared"
            and row["coordinate_policy_id"] == "gda94-geographic-wgs84-identity-v1"
            and row["original_latitude_raw"]
            and row["original_longitude_raw"]
            for row in [*ngsa_atlas_rows, *ngsa_mercury_rows]
        )
        and {row["coordinate_latitude_field"] for row in ngsa_atlas_rows}
        == {"LATITUDE"}
        and {row["coordinate_longitude_field"] for row in ngsa_atlas_rows}
        == {"LONGITUDE"}
        and {row["coordinate_latitude_field"] for row in ngsa_mercury_rows}
        == {"LATITUDE_GDA94"}
        and {row["coordinate_longitude_field"] for row in ngsa_mercury_rows}
        == {"LONGITUDE_GDA94"},
        "D1 NGSA fixtures preserve raw GDA94 and require the registered policy without inventing positional accuracy",
        checks,
    )

    brasol_rows = csv_rows(
        SOURCE_DEMOS / "pangaea-brasol-ne-brazil-soil" / "demo_input.csv"
    )
    brasol_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "pangaea-brasol-ne-brazil-soil" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    yangtze_rows = csv_rows(
        SOURCE_DEMOS / "figshare-yangtze-basin-soil-heavy-metals" / "demo_input.csv"
    )
    require(
        len(brasol_rows) == len(brasol_evidence) == 48
        and Counter(row["element_or_analyte"] for row in brasol_rows)
        == {element: 8 for element in ("As", "Cr", "Cu", "Ni", "Pb", "Zn")}
        and all(
            row["source_crs"] == "EPSG:4326"
            and row["coordinate_uncertainty_m"]
            and row["analytical_method"]
            and row["official_source_url"].startswith("https://")
            for row in brasol_rows
        )
        and all(
            item["coordinate_evidence"]["coordinate_evidence_status"]
            == "publisher_wgs84_dms_decimal_agree"
            for item in brasol_evidence
        )
        and source_contracts.PangaeaBrasolNeBrazilSoilAdapter._dms_decimal(
            '036"00\'04.0"W', axis="longitude"
        )
        == -36.00111111111111
        and source_contracts.PangaeaBrasolNeBrazilSoilAdapter._dms_decimal(
            "037°18'301\"W", axis="longitude"
        )
        is None,
        "D1 BraSol slice balances all six elements and independently gates conflicting publisher coordinate fields",
        checks,
    )
    require(
        len(yangtze_rows) == 56
        and Counter(row["element_or_analyte"] for row in yangtze_rows)
        == {element: 8 for element in ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")}
        and all(
            not row["source_crs"]
            and not row["analytical_method"]
            and row["method_missing_reason"] == "publisher_compilation_omits_row_method"
            and row["official_source_url"].startswith("https://")
            for row in yangtze_rows
        ),
        "D1 Yangtze slice balances all seven elements while preserving missing method and datum evidence",
        checks,
    )

    earthchem_rows = csv_rows(
        SOURCE_DEMOS / "earthchem-dehailonggang-rock" / "demo_input.csv"
    )
    earthchem_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "earthchem-dehailonggang-rock" / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        len(earthchem_rows) == len(earthchem_evidence) == 75
        and len({row["sample_id"] for row in earthchem_rows}) == 15
        and Counter(row["element_or_analyte"] for row in earthchem_rows)
        == {element: 15 for element in ("Cr", "Cu", "Ni", "Pb", "Zn")}
        and all(
            row["medium"] == "rock"
            and row["sample_type"] == "rock_whole_rock"
            and row["analytical_method"] == "ICPMS"
            and row["instrument"] == "Agilent 7700e"
            and row["laboratory"]
            and row["official_source_url"]
            == "https://ecl.earthchem.org/view.php?id=3338"
            and not row["source_crs"]
            and not row["coordinate_uncertainty_m"]
            for row in earthchem_rows
        )
        and source_contracts._RejectRedirects().redirect_request(
            urllib.request.Request("https://ecl.earthchem.org/dl_multi.php"),
            None,
            302,
            "Found",
            {},
            "https://example.org/unregistered.zip",
        )
        is None
        and all(
            item["evidence_status"] == "verified_source_file_and_row"
            and item["dataset_doi"] == "10.60520/IEDA/113338"
            and item["source_file_sha256"]
            == "ccdc26ee169919144f7d1c8726eb8075c99b4d9cba30d249906f79c045a12ca7"
            for item in earthchem_evidence
        ),
        "D1 EarthChem China-rock slice preserves publisher methods and fails closed on unreported CRS and precision",
        checks,
    )

    four_tu_demo = SOURCE_DEMOS / "4tu-northern-china-sediment"
    four_tu_rows = csv_rows(four_tu_demo / "demo_input.csv")
    four_tu_evidence = [
        json.loads(line)
        for line in (four_tu_demo / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    four_tu_manifest = json_value(four_tu_demo / "run_manifest.json")
    four_tu_profile = json_value(
        full_profile_root / "4tu-northern-china-sediment" / "field_completeness.json"
    )
    four_tu_population = next(
        item
        for item in full_manifest["sources"]
        if item["source_id"] == "4tu-northern-china-sediment"
    )
    require(
        len(four_tu_rows) == len(four_tu_evidence) == 56
        and len({row["sample_id"] for row in four_tu_rows}) == 8
        and Counter(row["element_or_analyte"] for row in four_tu_rows)
        == {element: 8 for element in ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")}
        and len({row["survey_area"] for row in four_tu_rows}) == 8
        and all(
            row["medium"] == "sediment"
            and row["dataset_doi"]
            == "10.4121/uuid:6cb0bf79-7467-4e78-a531-cc91655d9fd0"
            and row["license"] == "CC0-1.0"
            and row["source_locator"]
            and row["official_source_url"].startswith("https://data.4tu.nl/")
            and not row["source_crs"]
            and not row["coordinate_uncertainty_m"]
            for row in four_tu_rows
        )
        and all(
            bool(row["analytical_method"]) == (row["element_or_analyte"] != "Hg")
            and (
                row["method_missing_reason"] == "not_reported"
                if row["element_or_analyte"] == "Hg"
                else bool(row["method_source_locator"])
            )
            for row in four_tu_rows
        )
        and {
            (item["filename"], item["sha256"], item["bytes"])
            for item in four_tu_manifest["source_files"]
        }
        == {
            (
                "Dataset of Geochemical Compositions of Surface Sediments in northern China.xlsx",
                "6b06695e359986bf0a50c6d0febda08ffa25a61028c00cdadd60cc8426001232",
                693878,
            ),
            (
                "README.pdf",
                "ef1bfdf082c86529682bfbc0446b1f571db16935c4ea16ee3a2813726778fd76",
                95467,
            ),
            (
                "Observed regions in 'Raw data of Geochemical Compositions of Surface Sediments in Northern China'.kml",
                "3633ceb7c8ddc639c1a646c0c5acc0f6264daa09f58f4c4121b8c5a64950678c",
                2479,
            ),
        }
        and all(
            item["source_file_sha256"]
            == "6b06695e359986bf0a50c6d0febda08ffa25a61028c00cdadd60cc8426001232"
            and item["method_evidence_file"]["filename"] == "README.pdf"
            and item["method_evidence_file"]["sha256"]
            == "ef1bfdf082c86529682bfbc0446b1f571db16935c4ea16ee3a2813726778fd76"
            and item["region_evidence_file"]["filename"].endswith(".kml")
            and item["region_evidence_file"]["sha256"]
            == "3633ceb7c8ddc639c1a646c0c5acc0f6264daa09f58f4c4121b8c5a64950678c"
            for item in four_tu_evidence
        )
        and four_tu_profile["observation_count"] == 6069
        and four_tu_population["distinct_sample_count"] == 867
        and four_tu_profile["fields"]["analytical_method"]["rate"] == 0.857143,
        "D1 4TU northern-China source binds seven elements, eight western/northern regions, methods, QC and three-file provenance",
        checks,
    )

    migration_check = migrate_v4_source_demos.migrate(SOURCE_DEMOS, check=True)
    require(
        migration_check["status"] == "PASS" and migration_check["source_count"] == 35,
        "D1 V4 source-demo migration is byte-stable across all thirty-five sources",
        checks,
    )

    unbound_evidence_sources: list[str] = []
    for demo_dir in sorted(path for path in SOURCE_DEMOS.iterdir() if path.is_dir()):
        demo_manifest = json_value(demo_dir / "run_manifest.json")
        acquired_by_name = {
            str(item["filename"]): (
                str(item.get("sha256") or ""),
                str(item.get("source_url") or ""),
            )
            for item in demo_manifest["source_files"]
        }
        for line in (
            (demo_dir / "sources.jsonl").read_text(encoding="utf-8").splitlines()
        ):
            item = json.loads(line)
            bound = acquired_by_name.get(str(item.get("source_file")))
            if (
                bound is None
                or bound[0] != str(item.get("source_file_sha256") or "")
                or (
                    item.get("source_file_url")
                    and bound[1] != str(item.get("source_file_url"))
                )
            ):
                unbound_evidence_sources.append(demo_dir.name)
                break
    require(
        not unbound_evidence_sources,
        "D1 source-demo evidence names the acquired manifest file it hashes, including archive and multi-file sources",
        checks,
    )

    combined_manifest = json_value(COMBINED_DEMO / "run_manifest.json")
    combined_rows = csv_rows(COMBINED_DEMO / "demo_input.csv")
    combined_evidence = [
        json.loads(line)
        for line in (COMBINED_DEMO / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    require(
        combined_manifest["record_counts"]["total"]
        == len(combined_rows)
        == len(combined_evidence)
        == 1144
        and combined_manifest["record_counts"]["by_medium"]
        == {"rock": 96, "sediment": 408, "soil": 440, "water": 200}
        and combined_manifest["record_counts"]["by_source"]
        == {
            "gemstat-open-archive": 56,
            "georoc-archaean": 48,
            "geotraces-idp2025": 48,
            "japan-gsj-geochemical-map": 48,
            "norway-marchem": 112,
            "pangaea-north-africa-soil": 48,
            "usgs-conus-soil": 108,
            "foregs-topsoil": 48,
            "foregs-subsoil": 48,
            "foregs-humus": 48,
            "foregs-stream-water": 48,
            "foregs-stream-sediment": 48,
            "foregs-floodplain-sediment": 48,
            "afsis-phase-i-wet-chemistry": 48,
            "us-wqp-sacramento-river-arsenic": 48,
            "australia-ngsa-mercury": 48,
            "japan-gsj-marine-sediment": 56,
            "pangaea-arabian-sea-sediment": 48,
            "georoc-antarctica-intraplate": 48,
            "tpdc-china-mountain-soil": 40,
            "gemas-europe": 52,
        },
        "D1 combined fixture binds its twenty-one frozen global datasets to one 1,144-observation four-media request",
        checks,
    )
    combined_source_confidence = json_value(
        COMBINED_DEMO / "expected-output" / "sources_and_confidence.json"
    )
    require(
        combined_source_confidence["metadata_completeness"]["official_source_link"][
            "rate"
        ]
        == 1.0
        and all(
            source["record_provenance"]["official_linked_record_count"]
            == source["record_count"]
            and source["official_links"]
            for source in combined_source_confidence["sources"]
        ),
        "D1 real-source fixture carries a clickable official URL or DOI on every record while synthetic input remains exempt",
        checks,
    )
    require(
        combined_manifest["route"]["status"] == "offline_fixtures_verified"
        and combined_manifest["route"]["source_router_status"] == "needs_human_review"
        and combined_manifest["route"]["selection_context"]
        == "checked_in_fixtures_hash_verified"
        and set(combined_manifest["route"]["selected_sources"])
        == set(combined_manifest["record_counts"]["by_source"]),
        "D1 combined fixture promotes offline routes only after local manifest and SHA-256 verification",
        checks,
    )
    require(
        combined_manifest["comparison_isolation"]["group_fields"]
        == list(standardizer.DEFAULT_GROUP_BY)
        and combined_manifest["comparison_isolation"]["raw_input_partition_count"]
        == 156
        and combined_manifest["comparison_isolation"]["partition_count"] == 156
        and combined_manifest["comparison_isolation"]["water_partition_count"] == 36,
        "D1 combined fixture freezes the exact D2 comparison partitions and water boundaries",
        checks,
    )
    require(
        all(
            row["sample_type_raw"]
            and row["sample_type"]
            and row["sample_type_mapping_status"] in {"exact", "dataset_constant"}
            for row in combined_rows
        )
        and all(not row["geologic_unit"] for row in combined_rows)
        and sum(bool(row["geographic_context_raw"]) for row in combined_rows) == 484,
        "D1 V4 classifies every demo sample and removes geography from legacy geologic_unit",
        checks,
    )
    require(
        all(
            (
                row["analytical_method"]
                and row["method_scope"]
                and not row["method_missing_reason"]
            )
            or (
                not row["analytical_method"]
                and not row["method_scope"]
                and row["method_missing_reason"]
            )
            for row in combined_rows
        )
        and sum(bool(row["method_scope"]) for row in combined_rows) == 896
        and sum(bool(row["method_missing_reason"]) for row in combined_rows) == 248,
        "D1 V4 gives every present method a scope and every absent method a reason",
        checks,
    )
    method_rich_sources = (
        "gemas-europe",
        "pangaea-barents-c-horizon-soil",
        "pangaea-east-china-sea-clay",
    )
    method_absent_sources = {
        "geotraces-idp2025": "multiple_linked_method_records_unresolved_to_observation",
        "japan-gsj-geochemical-map": "not_reported",
        "japan-gsj-marine-sediment": "not_reported_in_concentration_csv",
    }
    method_pipeline_rows = {
        source_id: (
            source_rows,
            standardizer.process_rows(source_rows),
        )
        for source_id in (*method_rich_sources, *method_absent_sources)
        for source_rows in [csv_rows(SOURCE_DEMOS / source_id / "demo_input.csv")]
    }
    require(
        all(
            len(source_rows) == len(standardized_rows)
            and all(
                standardized["record_id"] == source["record_id"]
                and standardized["analytical_method"] == source["analytical_method"]
                and standardized["method_scope"] == source["method_scope"]
                and standardized["method_source_locator"]
                == source["method_source_locator"]
                and standardized["method_missing_reason"] is None
                for source, standardized in zip(source_rows, standardized_rows)
            )
            for source_id in method_rich_sources
            for source_rows, standardized_rows in [method_pipeline_rows[source_id]]
        ),
        "D2 preserves every publisher-reported method, scope and locator from GEMAS and two PANGAEA controls",
        checks,
    )
    require(
        all(
            len(source_rows) == len(standardized_rows)
            and all(
                not standardized["analytical_method"]
                and not standardized["method_scope"]
                and standardized["method_missing_reason"] == reason
                for standardized in standardized_rows
            )
            for source_id, reason in method_absent_sources.items()
            for source_rows, standardized_rows in [method_pipeline_rows[source_id]]
        )
        and {
            source_id: {
                standardized["coordinate_accuracy_evidence_status"]
                for standardized in method_pipeline_rows[source_id][1]
            }
            for source_id in method_absent_sources
        }
        == {
            "geotraces-idp2025": {"not_reported"},
            "japan-gsj-geochemical-map": {"source_reported_uncertainty"},
            "japan-gsj-marine-sediment": {"not_applicable_no_canonical_coordinate"},
        },
        "D2 retains publisher method-absence reasons and distinguishes reported, unreported and inapplicable coordinate accuracy",
        checks,
    )
    combined_source_accounting = {
        source["source_id"]: source["metadata_absence_accounting"]
        for source in combined_source_confidence["sources"]
    }
    require(
        combined_source_confidence["metadata_absence_accounting"]["analytical_method"][
            "accounted_count"
        ]
        == 248
        and combined_source_confidence["metadata_absence_accounting"][
            "analytical_method"
        ]["accounted_rate"]
        == 1.0
        and combined_source_confidence["metadata_absence_accounting"][
            "coordinate_accuracy"
        ]["accounted_count"]
        == 1144
        and combined_source_confidence["metadata_absence_accounting"][
            "coordinate_accuracy"
        ]["accounted_rate"]
        == 1.0
        and combined_source_confidence["metadata_absence_accounting"][
            "coordinate_reference"
        ]["accounted_count"]
        == 1144
        and combined_source_confidence["metadata_absence_accounting"][
            "coordinate_reference"
        ]["accounted_rate"]
        == 1.0
        and combined_source_confidence["metadata_absence_accounting"][
            "coordinate_reference"
        ]["counts"]
        == {
            "canonical_crs_evidenced": 856,
            "coordinate_not_canonicalized_under_policy": 48,
            "publisher_datum_not_declared": 240,
        }
        and combined_source_accounting["geotraces-idp2025"]["analytical_method"][
            "counts"
        ]
        == {"multiple_linked_method_records_unresolved_to_observation": 48}
        and combined_source_accounting["japan-gsj-geochemical-map"][
            "analytical_method"
        ]["counts"]
        == {"not_reported": 48}
        and combined_source_accounting["japan-gsj-marine-sediment"][
            "analytical_method"
        ]["counts"]
        == {"not_reported_in_concentration_csv": 56},
        "D2 confidence output accounts for every absent method, coordinate-reference and coordinate-accuracy state without relabeling them as source quality",
        checks,
    )
    require(
        all(row["official_source_url"] for row in combined_rows)
        and all(
            (not row["analytical_method"] and not row["method_source_locator"])
            or row["method_source_locator"]
            for row in combined_rows
        ),
        "D1 V4 preserves per-record official links and binds every reported method to its source locator",
        checks,
    )
    water_rows = [row for row in combined_rows if row["medium"] == "water"]
    sediment_rows = [row for row in combined_rows if row["medium"] == "sediment"]
    require(
        len(water_rows) == 200
        and all(row["water_body_type"] and row["water_fraction"] for row in water_rows)
        and len(sediment_rows) == 408
        and all(row["sediment_environment"] for row in sediment_rows)
        and {row["water_fraction"] for row in water_rows}
        == {"dissolved", "extractable", "suspended", "total"},
        "D1 V4 carries water type/fraction and sediment environment into the exchange rows",
        checks,
    )
    require(
        all(
            row["citation_scope"]
            and row["citation_resolution_status"] == "resolved"
            and row["access_status"] == "public_download"
            and row["research_use_status"] == "permitted_research"
            and row["license_url"]
            for row in combined_rows
        )
        and {row["citation_scope"] for row in combined_rows}
        == {"dataset", "observation"},
        "D1 V4 keeps citation scope, access, research use and license evidence distinct",
        checks,
    )
    combined_output = COMBINED_DEMO / "expected-output"
    combined_summary = json_value(combined_output / "run_summary.json")
    combined_qc = json_value(combined_output / "qc_report.json")
    combined_anomaly = json_value(combined_output / "anomaly_report.json")
    combined_database = csv_rows(combined_output / "geochemistry.csv")
    combined_output_manifest = json_value(combined_output / "source_manifest.json")
    combined_evidence_index = output_validator.database_evidence_index(
        combined_output / "geochemistry.csv"
    )
    combined_pangaea = [
        row
        for row in combined_database
        if row["source_id"] == "pangaea-north-africa-soil"
    ]
    combined_ngsa = [
        row for row in combined_database if row["source_id"] == "australia-ngsa-mercury"
    ]
    grouped_sources: dict[tuple[str, ...], set[str]] = {}
    for row in combined_database:
        key = tuple(
            str(row.get(field) or "") for field in standardizer.DEFAULT_GROUP_BY
        )
        grouped_sources.setdefault(key, set()).add(row["source_id"])
    require(
        output_validator.validate_dir(combined_output)["status"] == "valid"
        and combined_summary["status"] == "partial_success"
        and combined_summary["metrics"]["record_count"] == 1144
        and combined_summary["metrics"]["standardized_record_count"] == 1136
        and combined_summary["metrics"]["valid_coordinate_count"] == 856
        and combined_summary["metrics"]["censored_record_count"] == 60
        and combined_summary["metrics"]["candidate_anomaly_count"] == 27
        and "UNKNOWN_SOURCE_TIER" not in combined_qc["flag_counts"]
        and combined_anomaly["group_by"] == list(standardizer.DEFAULT_GROUP_BY)
        and len(combined_anomaly["groups"])
        == combined_manifest["comparison_isolation"]["partition_count"]
        and all(
            len(sources) == 1
            or sources == {"georoc-archaean", "georoc-antarctica-intraplate"}
            for sources in grouped_sources.values()
        ),
        "D1 combined workflow standardizes and maps all records without crossing independent source lineages",
        checks,
    )
    source_binding_errors: list[str] = []
    output_validator.validate_database_source_bindings(
        combined_evidence_index, combined_output_manifest, source_binding_errors
    )
    tampered_binding_index = copy.deepcopy(combined_evidence_index)
    first_record_id = sorted(tampered_binding_index)[0]
    tampered_binding_index[first_record_id]["dataset_title"] = "wrong dataset"
    tampered_binding_errors: list[str] = []
    output_validator.validate_database_source_bindings(
        tampered_binding_index,
        combined_output_manifest,
        tampered_binding_errors,
    )
    tampered_file_binding_index = copy.deepcopy(combined_evidence_index)
    tampered_file_binding_index[first_record_id]["file_sha256"] = "f" * 64
    tampered_file_binding_errors: list[str] = []
    output_validator.validate_database_source_bindings(
        tampered_file_binding_index,
        combined_output_manifest,
        tampered_file_binding_errors,
    )
    tampered_url_binding_index = copy.deepcopy(combined_evidence_index)
    tampered_url_binding_index[first_record_id]["official_source_url"] = (
        "https://example.invalid/unbound-source"
    )
    tampered_url_binding_errors: list[str] = []
    output_validator.validate_database_source_bindings(
        tampered_url_binding_index,
        combined_output_manifest,
        tampered_url_binding_errors,
    )
    require(
        not source_binding_errors
        and any("dataset_title_mismatch" in error for error in tampered_binding_errors)
        and any(
            "source_file_sha256_mismatch" in error
            for error in tampered_file_binding_errors
        )
        and any(
            "official_source_url_mismatch" in error
            for error in tampered_url_binding_errors
        ),
        "D1/D2 validator rejects record metadata, file hashes and official URLs that do not match the source manifest",
        checks,
    )
    require(
        output_validator.canonical_binding_url(
            "https://doi.org/10.1130/0091-7613(1987)15<1147:UFGKFT>2.0.CO;2"
        )
        == output_validator.canonical_binding_url(
            "https://doi.org/10.1130/0091-7613(1987)15%3C1147:UFGKFT%3E2.0.CO;2"
        )
        and output_validator.canonical_binding_url("https://example.org/a%2Fb")
        != output_validator.canonical_binding_url("https://example.org/a/b"),
        "D1/D2 treats percent-encoded and literal DOI paths as the same bound identifier without weakening non-DOI URL matching",
        checks,
    )
    require(
        len(combined_pangaea) == 48
        and {row["source_crs"] for row in combined_pangaea} == {"EPSG:4326"}
        and {row["coordinate_evidence_scope"] for row in combined_pangaea}
        == {"platform_policy_declared"}
        and {row["coordinate_policy_id"] for row in combined_pangaea}
        == {"pangaea-geocode-wgs84-v1"}
        and {row["coordinate_policy_sha256"] for row in combined_pangaea}
        == {"48a3e043e5a82a99e23dbde4fd9b97b012846a45ba47e46a5faf2f2ce0649a1b"},
        "D2 applies the DOI-and-field-scoped PANGAEA CRS policy with its pinned evidence hash",
        checks,
    )
    require(
        len(combined_ngsa) == 48
        and {row["source_crs"] for row in combined_ngsa} == {"EPSG:4326"}
        and {row["coordinate_evidence_scope"] for row in combined_ngsa}
        == {"platform_policy_declared"}
        and {row["coordinate_policy_id"] for row in combined_ngsa}
        == {"gda94-geographic-wgs84-identity-v1"}
        and {row["coordinate_policy_sha256"] for row in combined_ngsa}
        == {"337daefc4e7f9e3e7ed3910fb9f007c89404fcbddcd5763e7adb17c067e91fa1"}
        and {row["coordinate_uncertainty_m"] for row in combined_ngsa} == {""}
        and {row["coordinate_accuracy_evidence_status"] for row in combined_ngsa}
        == {"not_reported"}
        and all(
            row["official_source_url"] and row["source_locator"]
            for row in combined_ngsa
        ),
        "D2 applies the registered GDA94 identity policy while preserving publisher-unreported accuracy and links",
        checks,
    )
    with tempfile.TemporaryDirectory() as combined_temp:
        temporary_root = Path(combined_temp)
        rebuilt_dir = temporary_root / "combined"
        build_four_media_demo.build(
            COMBINED_DEMO / "request.json",
            SOURCE_DEMOS,
            rebuilt_dir,
            combined_manifest["generated_at"],
            False,
        )
        require(
            all(
                (rebuilt_dir / filename).read_bytes()
                == (COMBINED_DEMO / filename).read_bytes()
                for filename in ("demo_input.csv", "sources.jsonl", "run_manifest.json")
            ),
            "D1 combined fixture rebuilds byte-for-byte from its twenty-one frozen source demos",
            checks,
        )
        rebuilt_output = temporary_root / "output"
        run_command(
            [
                sys.executable,
                str(WORKFLOW),
                "--input",
                str(rebuilt_dir / "demo_input.csv"),
                "--evidence-jsonl",
                str(rebuilt_dir / "sources.jsonl"),
                "--acquisition-manifest",
                str(rebuilt_dir / "run_manifest.json"),
                "--output-dir",
                str(rebuilt_output),
            ]
        )
        require(
            all(
                (rebuilt_output / filename).read_bytes()
                == (combined_output / filename).read_bytes()
                for filename in output_validator.REQUIRED_FILES.values()
            ),
            "D1 combined stable output package rebuilds byte-for-byte",
            checks,
        )

        strict_research_errors: list[str] = []
        output_validator.enforce_research_evidence_contract(
            "online",
            {
                "source_locator_missing": 0,
                "official_source_url_missing": 1,
                "method_evidence_unaccounted": 1,
                "method_source_locator_missing": 1,
                "coordinate_accuracy_evidence_unaccounted": 1,
            },
            strict_research_errors,
        )
        require(
            len(strict_research_errors) == 4
            and any("official source URL" in error for error in strict_research_errors)
            and any("analytical method" in error for error in strict_research_errors)
            and any("coordinate" in error for error in strict_research_errors),
            "D1/D2 public validator fails closed on incomplete research provenance and metadata accounting",
            checks,
        )
        real_fixture_errors: list[str] = []
        output_validator.enforce_research_evidence_contract(
            "fixture",
            {
                "source_locator_missing": 0,
                "official_source_url_missing": 1,
                "method_evidence_unaccounted": 0,
                "method_source_locator_missing": 0,
                "coordinate_accuracy_evidence_unaccounted": 0,
            },
            real_fixture_errors,
            synthetic_data_present=False,
        )
        synthetic_fixture_errors: list[str] = []
        output_validator.enforce_research_evidence_contract(
            "synthetic_fixture",
            {
                "source_locator_missing": 1,
                "official_source_url_missing": 1,
                "method_evidence_unaccounted": 1,
                "method_source_locator_missing": 1,
                "coordinate_accuracy_evidence_unaccounted": 1,
            },
            synthetic_fixture_errors,
            synthetic_data_present=True,
        )
        require(
            len(real_fixture_errors) == 1
            and "official source URL" in real_fixture_errors[0]
            and not synthetic_fixture_errors,
            "D1/D2 reserves the missing-link exemption for explicitly synthetic fixtures only",
            checks,
        )

    with tempfile.TemporaryDirectory() as evidence_temp:
        require(
            evidence_builder.MAX_EVIDENCE_BYTES == 600_000_000
            and visualization_validator.MAX_OUTPUT_BYTES
            == evidence_builder.MAX_EVIDENCE_BYTES,
            "D1 evidence packaging uses the bounded 200k-record runtime ceiling, not the 250 MB repository limit",
            checks,
        )
        standalone = Path(evidence_temp) / "source_manifest.json"
        evidence_builder.package_evidence(
            DEMO_INPUT, output_dir / "geochemistry.csv", confidence_path, standalone
        )
        require(
            standalone.read_bytes() == manifest_path.read_bytes(),
            "D1 standalone packaging matches D3 integration",
            checks,
        )

        verified_output = Path(evidence_temp) / "verified-source-workflow"
        usgs_demo = SOURCE_DEMOS / "usgs-conus-soil"
        run_command(
            [
                sys.executable,
                str(WORKFLOW),
                "--input",
                str(usgs_demo / "demo_input.csv"),
                "--evidence-jsonl",
                str(usgs_demo / "sources.jsonl"),
                "--acquisition-manifest",
                str(usgs_demo / "run_manifest.json"),
                "--output-dir",
                str(verified_output),
            ]
        )
        verified_manifest = json_value(verified_output / "source_manifest.json")
        require(
            verified_manifest["coverage"]["verified_evidence_rate"] == 1.0
            and verified_manifest["record_evidence"]["evidence_level"]
            == "verified_record_evidence",
            "D1 final manifest consumes and hash-binds the acquisition evidence sidecar",
            checks,
        )
        verified_summary = json_value(verified_output / "run_summary.json")
        require(
            verified_summary["input"]["not_for_scientific_interpretation"] is True
            and "not for scientific interpretation"
            in verified_summary["limitations"][0],
            "D3 propagates the fixture claim boundary into the final result",
            checks,
        )

        tampered_evidence_rows = [
            json.loads(line)
            for line in (usgs_demo / "sources.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        tampered_evidence_rows[0]["record_id"] = "rec-not-in-canonical-database"
        tampered_evidence = Path(evidence_temp) / "tampered-record-ids.jsonl"
        tampered_evidence.write_text(
            "".join(
                json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
                for item in tampered_evidence_rows
            ),
            encoding="utf-8",
        )
        try:
            evidence_builder.package_evidence(
                usgs_demo / "demo_input.csv",
                verified_output / "geochemistry.csv",
                verified_output / "confidence_report.json",
                Path(evidence_temp) / "must-not-package-record-ids.json",
                tampered_evidence,
                usgs_demo / "run_manifest.json",
            )
        except evidence_builder.EvidenceError:
            pass
        else:
            raise ContractError(
                "D1 must reject sidecar record IDs that differ from the canonical database"
            )
        checks.append(
            "D1 rejects record-evidence additions, removals and record-ID substitutions"
        )

        tampered_acquisition = json_value(usgs_demo / "run_manifest.json")
        tampered_acquisition["source_files"][0]["sha256"] = "0" * 64
        tampered_acquisition_path = Path(evidence_temp) / "tampered-acquisition.json"
        tampered_acquisition_path.write_text(
            json.dumps(tampered_acquisition), encoding="utf-8"
        )
        try:
            evidence_builder.package_evidence(
                usgs_demo / "demo_input.csv",
                verified_output / "geochemistry.csv",
                verified_output / "confidence_report.json",
                Path(evidence_temp) / "must-not-package-source-hash.json",
                usgs_demo / "sources.jsonl",
                tampered_acquisition_path,
            )
        except evidence_builder.EvidenceError:
            pass
        else:
            raise ContractError(
                "D1 must reject source-file hashes not present in the acquisition manifest"
            )
        checks.append(
            "D1 cross-checks every record source-file hash against acquired files"
        )

        tampered_official_url_rows = [dict(item) for item in tampered_evidence_rows]
        tampered_official_url_rows[0]["record_id"] = json.loads(
            (usgs_demo / "sources.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )["record_id"]
        tampered_official_url_rows[0]["source_file_url"] = (
            "https://example.invalid/unbound-source"
        )
        tampered_official_url = Path(evidence_temp) / "tampered-official-url.jsonl"
        tampered_official_url.write_text(
            "".join(
                json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n"
                for item in tampered_official_url_rows
            ),
            encoding="utf-8",
        )
        try:
            evidence_builder.package_evidence(
                usgs_demo / "demo_input.csv",
                verified_output / "geochemistry.csv",
                verified_output / "confidence_report.json",
                Path(evidence_temp) / "must-not-package-official-url.json",
                tampered_official_url,
                usgs_demo / "run_manifest.json",
            )
        except evidence_builder.EvidenceError:
            pass
        else:
            raise ContractError(
                "D1 must reject an official source URL outside the acquired manifest"
            )
        checks.append(
            "D1 cross-checks every clickable official source URL against acquired-file evidence"
        )

        tampered_report = json_value(confidence_path)
        tampered_report["run_metadata"]["input_sha256"] = "0" * 64
        tampered_path = Path(evidence_temp) / "tampered-confidence.json"
        tampered_path.write_text(json.dumps(tampered_report), encoding="utf-8")
        try:
            evidence_builder.package_evidence(
                DEMO_INPUT,
                output_dir / "geochemistry.csv",
                tampered_path,
                Path(evidence_temp) / "must-not-exist.json",
            )
        except evidence_builder.EvidenceError:
            pass
        else:
            raise ContractError(
                "D1 must reject a confidence report linked to a different input"
            )
        checks.append("D1 rejects a mismatched D2 confidence input hash")

        unsafe_output = Path(evidence_temp) / "unsafe.csv"
        unsafe_manifest = Path(evidence_temp) / "unsafe-download.json"
        run_command(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                "http://127.0.0.1/private.csv",
                "--output",
                str(unsafe_output),
                "--manifest",
                str(unsafe_manifest),
                "--license",
                "unresolved",
                "--retries",
                "0",
            ],
            expected_code=2,
        )
        require(
            not unsafe_output.exists(),
            "D1 downloader fails closed on unsafe URLs",
            checks,
        )
        require(
            json_value(unsafe_manifest).get("status") == "invalid_input",
            "D1 downloader returns a structured invalid_input status",
            checks,
        )

        cached_file = Path(evidence_temp) / "cached.csv"
        cached_file.write_text(
            "SiteID\tLatitude\tLongitude\nA\t1\t2\n", encoding="utf-8"
        )
        cached_url = "https://example.org/public/cached.csv"
        cached_hash = sha256_file(cached_file)
        cached_manifest = Path(evidence_temp) / "cached-download.json"
        cached_manifest.write_text(
            json.dumps(
                {
                    "source_url": cached_url,
                    "sha256": cached_hash,
                    "dataset_version": "v1",
                }
            ),
            encoding="utf-8",
        )
        cache_result = downloader.existing_verified_cache(
            cached_file,
            cached_manifest,
            cached_url,
            cached_hash,
            "v1",
        )
        require(
            cache_result["status"] == "cache_hit",
            "D1 reuses only a hash-verified versioned cache",
            checks,
        )

        offline_manifest = Path(evidence_temp) / "offline-miss.json"
        run_command(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                "https://example.org/public/missing.csv",
                "--output",
                str(Path(evidence_temp) / "missing.csv"),
                "--manifest",
                str(offline_manifest),
                "--license",
                "unresolved",
                "--offline",
            ],
            expected_code=2,
        )
        require(
            json_value(offline_manifest).get("status") == "network_unavailable",
            "D1 offline cache miss returns a structured network_unavailable status",
            checks,
        )

        for expected_hash, version, expected_message in (
            ("0" * 64, "v1", "SHA-256 mismatch"),
            (cached_hash, "v2", "dataset version"),
        ):
            try:
                downloader.existing_verified_cache(
                    cached_file,
                    cached_manifest,
                    cached_url,
                    expected_hash,
                    version,
                )
            except downloader.DownloadError as exc:
                require(
                    expected_message in str(exc),
                    f"D1 rejects cached data on {expected_message}",
                    checks,
                )
            else:
                raise ContractError(f"D1 must reject cached data on {expected_message}")

        for content_type, declared_length, expected_message in (
            ("text/html; charset=utf-8", None, "HTML"),
            ("text/plain", "1001", "Content-Length"),
        ):
            try:
                downloader.validate_response_metadata(
                    content_type, declared_length, max_bytes=1000
                )
            except downloader.DownloadError as exc:
                require(
                    expected_message in str(exc),
                    f"D1 rejects {expected_message} response metadata",
                    checks,
                )
            else:
                raise ContractError(
                    f"D1 must reject {expected_message} response metadata"
                )

        try:
            downloader.copy_response_bounded(
                io.BytesIO(b"x" * 1001), io.BytesIO(), max_bytes=1000
            )
        except downloader.DownloadError as exc:
            require(
                "download exceeded" in str(exc),
                "D1 enforces the streaming size limit without trusting Content-Length",
                checks,
            )
        else:
            raise ContractError("D1 must enforce the streaming response size limit")

        proxy_env_keys = ("https_proxy", "HTTPS_PROXY", "no_proxy", "NO_PROXY")
        saved_proxy_env = {key: os.environ.get(key) for key in proxy_env_keys}
        try:
            for key in proxy_env_keys:
                os.environ.pop(key, None)
            try:
                downloader.validate_public_https_url(
                    "https://unresolvable.invalid/data.csv"
                )
            except downloader.DownloadError as exc:
                require(
                    exc.status == "network_unavailable",
                    "D1 direct egress still requires hostname resolution",
                    checks,
                )
            else:
                raise ContractError("D1 must fail hostname preflight without a proxy")
            os.environ["https_proxy"] = "http://127.0.0.1:3128"
            downloader.validate_public_https_url(
                "https://unresolvable.invalid/data.csv"
            )
            require(
                downloader.configured_proxy(
                    urllib.parse.urlparse("https://unresolvable.invalid/data.csv")
                )
                == "http://127.0.0.1:3128",
                "D1 skips the direct DNS preflight only under an operator-configured proxy for the URL scheme",
                checks,
            )
        finally:
            for key, value in saved_proxy_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        attempts: list[int] = []
        delays: list[float] = []

        def transient_download(*_args: Any) -> dict[str, Any]:
            attempts.append(len(attempts) + 1)
            if len(attempts) < 3:
                raise TimeoutError("injected timeout")
            return {"status": "downloaded"}

        retry_result = downloader.download_with_retries(
            cached_url,
            Path(evidence_temp) / "retry.csv",
            1,
            1000,
            None,
            2,
            downloader=transient_download,
            sleeper=delays.append,
        )
        require(
            retry_result.get("attempts") == 3
            and attempts == [1, 2, 3]
            and delays == [1, 2],
            "D1 retries transient timeouts only within the configured bound",
            checks,
        )

        forbidden_attempts: list[int] = []

        def forbidden_download(*_args: Any) -> dict[str, Any]:
            forbidden_attempts.append(1)
            raise urllib.error.HTTPError(cached_url, 403, "Forbidden", None, None)

        try:
            downloader.download_with_retries(
                cached_url,
                Path(evidence_temp) / "forbidden.csv",
                1,
                1000,
                None,
                3,
                downloader=forbidden_download,
                sleeper=delays.append,
            )
        except downloader.DownloadError as exc:
            require(
                exc.status == "source_not_accessible" and len(forbidden_attempts) == 1,
                "D1 stops on HTTP 403 without retry or access-control bypass",
                checks,
            )
        else:
            raise ContractError("D1 must stop on HTTP 403")
        require(
            downloader.is_retryable_error(
                urllib.error.HTTPError(cached_url, 502, "Bad Gateway", None, None)
            )
            and not downloader.is_retryable_error(
                urllib.error.HTTPError(cached_url, 500, "Error", None, None)
            ),
            "D1 HTTP retry policy is limited to the declared transient statuses",
            checks,
        )

        valid_zip = Path(evidence_temp) / "valid.zip"
        with zipfile.ZipFile(valid_zip, "w") as archive:
            archive.writestr("dataset/data.csv", "SiteID,Latitude,Longitude\nA,1,2\n")
        extract_dir = Path(evidence_temp) / "extracted"
        extracted = downloader.safe_extract_zip(
            valid_zip,
            extract_dir,
            max_members=5,
            max_extracted_bytes=1000,
            required_members=["dataset/data.csv"],
            required_fields=["SiteID", "Latitude", "Longitude"],
        )
        require(
            len(extracted) == 1 and (extract_dir / "dataset" / "data.csv").is_file(),
            "D1 validates required ZIP members and fields before publishing extraction",
            checks,
        )

        missing_member_zip = Path(evidence_temp) / "missing-member.zip"
        with zipfile.ZipFile(missing_member_zip, "w") as archive:
            archive.writestr("dataset/other.csv", "SiteID,Latitude,Longitude\nA,1,2\n")
        try:
            downloader.safe_extract_zip(
                missing_member_zip,
                Path(evidence_temp) / "must-not-publish-missing-member",
                max_members=5,
                max_extracted_bytes=1000,
                required_members=["dataset/data.csv"],
                required_fields=[],
            )
        except downloader.DownloadError as exc:
            require(
                "lacks required members" in str(exc),
                "D1 rejects archives with missing required members",
                checks,
            )
        else:
            raise ContractError("D1 must reject archives with missing required members")

        missing_field_file = Path(evidence_temp) / "missing-fields.csv"
        missing_field_file.write_text("SiteID,Value\nA,1\n", encoding="utf-8")
        try:
            downloader._read_delimited_header(
                missing_field_file, ["Latitude", "Longitude"]
            )
        except downloader.DownloadError as exc:
            require(
                "required delimited fields not found" in str(exc),
                "D1 reports missing required source fields",
                checks,
            )
        else:
            raise ContractError("D1 must reject files with missing required fields")

        corrupt_zip = Path(evidence_temp) / "corrupt.zip"
        corrupt_zip.write_bytes(b"not-a-zip")
        try:
            downloader.safe_extract_zip(
                corrupt_zip,
                Path(evidence_temp) / "must-not-publish-corrupt",
                max_members=5,
                max_extracted_bytes=1000,
                required_members=[],
                required_fields=[],
            )
        except downloader.DownloadError as exc:
            require(
                "not a valid ZIP archive" in str(exc),
                "D1 rejects corrupt ZIP archives",
                checks,
            )
        else:
            raise ContractError("D1 must reject corrupt ZIP archives")

        unsafe_zip = Path(evidence_temp) / "unsafe.zip"
        with zipfile.ZipFile(unsafe_zip, "w") as archive:
            archive.writestr("../escape.csv", "value\n1\n")
        try:
            downloader.safe_extract_zip(
                unsafe_zip,
                Path(evidence_temp) / "must-not-extract",
                max_members=5,
                max_extracted_bytes=1000,
                required_members=[],
                required_fields=[],
            )
        except downloader.DownloadError:
            pass
        else:
            raise ContractError("D1 must reject ZIP path traversal")
        require(
            not (Path(evidence_temp) / "escape.csv").exists(),
            "D1 rejects ZIP path traversal",
            checks,
        )

        usgs_native = Path(evidence_temp) / "Appendix_2b_Top5_18Sept2013.txt"
        usgs_native.write_text(
            "USGS synthetic parser fixture\n\n"
            "Top5_LabID\tSiteID\tStateID\tLatitude\tLongitude\tTop5_As\n"
            "\t\t\tDegrees\tDegrees\tmg/kg\n"
            "LAB-1\tSITE-1\tCO\t39.0\t-105.0\t8.2\n",
            encoding="utf-8",
        )
        usgs_adapter = source_contracts.UsgsSoilAdapter()
        usgs_records = list(
            usgs_adapter.parse(
                [
                    source_contracts.DownloadedFile(
                        source_id="usgs-conus-soil",
                        file_id="top-0-5cm",
                        path=usgs_native,
                        source_url="https://example.org/usgs.txt",
                        sha256=sha256_file(usgs_native),
                        bytes=usgs_native.stat().st_size,
                        cache_status="fixture",
                        retrieved_at=None,
                    )
                ]
            )
        )
        require(
            len(usgs_records) == 1
            and usgs_records[0].fields["_soil_layer"] == "top-0-5cm"
            and usgs_records[0].fields["_units"]["Top5_As"] == "mg/kg",
            "D1 USGS adapter preserves source fields, layer and units",
            checks,
        )

        georoc_native = Path(evidence_temp) / "2026-06-1KRR1P_ALDAN_SHIELD_ARCHEAN.csv"
        georoc_native.write_text(
            "CITATIONS,SAMPLE NAME,LOCATION,MATERIAL,NI(PPM)\r"
            "[1],SAMPLE-1,Aldan,WR,42\r"
            "\r"
            "Abbreviations: WR: WHOLE ROCK\r",
            encoding="latin-1",
        )
        georoc_adapter = source_contracts.GeorocArchaeanAdapter()
        georoc_records = list(
            georoc_adapter.parse(
                [
                    source_contracts.DownloadedFile(
                        source_id="georoc-archaean",
                        file_id="OHZY0O",
                        path=georoc_native,
                        source_url="https://example.org/georoc.csv",
                        sha256=sha256_file(georoc_native),
                        bytes=georoc_native.stat().st_size,
                        cache_status="fixture",
                        retrieved_at=None,
                    )
                ]
            )
        )
        require(
            len(georoc_records) == 1
            and georoc_records[0].fields["SAMPLE NAME"] == "SAMPLE-1"
            and georoc_records[0].fields["NI(PPM)"] == "42",
            "D1 GEOROC adapter handles CR-delimited CSV and stops before reference text",
            checks,
        )
    china_fixture = SKILL_DIR / "fixtures" / "china" / "combined-v1"
    china_manifest = json_value(china_fixture / "run_manifest.json")
    china_rows = csv_rows(china_fixture / "demo_input.csv")
    china_evidence = [
        json.loads(line)
        for line in (china_fixture / "sources.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    require(
        {item["path"]: item["sha256"] for item in china_manifest["outputs"]}
        == {
            "demo_input.csv": sha256_file(china_fixture / "demo_input.csv"),
            "sources.jsonl": sha256_file(china_fixture / "sources.jsonl"),
        }
        and china_manifest["record_counts"]["total"] == 2958
        and china_manifest["record_counts"]["by_source"]
        == {
            "tpdc-china-mountain-soil": 2400,
            "zenodo-yangtze-yellow-river-sediment": 558,
        }
        and len(china_rows) == 2958
        and len(china_evidence) == 2958
        and all(row.get("official_source_url") for row in china_rows)
        and {row["record_id"] for row in china_rows}
        == {str(row.get("record_id") or "") for row in china_evidence},
        "D1 China combined fixture matches its pinned hashes with one-to-one evidence",
        checks,
    )
    china_zenodo = [
        row
        for row in china_rows
        if row["source_id"] == "zenodo-yangtze-yellow-river-sediment"
    ]
    china_tpdc = [
        row for row in china_rows if row["source_id"] == "tpdc-china-mountain-soil"
    ]
    require(
        len(china_zenodo) == 558
        and {row["unit"] for row in china_zenodo} == {"ug/g"}
        and {row["medium"] for row in china_zenodo} == {"sediment"}
        and {row["license"] for row in china_zenodo} == {"CC-BY-4.0"}
        and {row["dataset_doi"] for row in china_zenodo} == {"10.5281/zenodo.7098563"}
        and {row["file_sha256"] for row in china_zenodo}
        == {"413f54f6544967d1d96b9eacfbeae41ba410a8c4b0375bdfaabc1293fd6fadd2"}
        and not any(
            row["latitude"]
            or row["longitude"]
            or row["original_latitude_raw"]
            or row["original_longitude_raw"]
            for row in china_zenodo
        )
        and {row["method_missing_reason"] for row in china_zenodo}
        == {"workbook_reports_no_analytical_method"}
        and {row["sample_type"] for row in china_zenodo} == {"sediment_river_fraction"}
        and {row["measurement_basis"] for row in china_zenodo}
        == {"HCl_residual_size_fraction", "AC_residual_size_fraction"},
        "D1 Zenodo river-sediment slice stays database-only with dataset-scoped provenance",
        checks,
    )
    require(
        len(china_tpdc) == 2400
        and all(
            row["original_latitude_raw"] and row["original_longitude_raw"]
            for row in china_tpdc
        )
        and not any(row["latitude"] or row["longitude"] for row in china_tpdc)
        and {row["file_sha256"] for row in china_tpdc}
        == {"923da5a896c0f403d227799cb04d565f75d641d5c81290889fcaddaa42ff593d"},
        "D1 TPDC demo slice keeps reported-only coordinates fail-closed at fixture scope",
        checks,
    )
    generated_arguments: list[argparse.Namespace] = []
    original_china_generate = build_china_demo.demos.generate
    try:
        build_china_demo.demos.generate = lambda arguments: (
            generated_arguments.append(arguments)
            or {
                "record_counts": {
                    "emitted_observations": build_china_demo.TPDC_DEMO_OBSERVATIONS
                }
            }
        )
        build_china_demo.build_tpdc_demo(
            Path("CACHE"), Path("OUTPUT"), "2026-08-08T00:00:00Z", False
        )
    finally:
        build_china_demo.demos.generate = original_china_generate
    require(
        len(generated_arguments) == 1
        and generated_arguments[0].purpose == "demo"
        and generated_arguments[0].observations == 2400,
        "D1 China fixture builder passes the current generator purpose contract in a clean rebuild",
        checks,
    )
    west_negative_usa = [-171.7911, 18.9162, -66.9647, 71.3578]
    west_negative_europe = [-25.0, 34.0, 45.0, 72.0]
    bbox_probe_common = [
        "--source",
        "usgs-conus-soil",
        "--cache-dir",
        "CACHE",
        "--output-dir",
        "OUTPUT",
        "--generated-at",
        "2026-08-21T00:00:00Z",
    ]
    require(
        request_runner.generator_bbox_argument(west_negative_usa)
        == "--bbox=-171.7911,18.9162,-66.9647,71.3578"
        and demo_generator.build_parser()
        .parse_args(
            [
                *bbox_probe_common,
                request_runner.generator_bbox_argument(west_negative_usa),
            ]
        )
        .bbox
        == tuple(west_negative_usa)
        and demo_generator.build_parser()
        .parse_args(
            [
                *bbox_probe_common,
                request_runner.generator_bbox_argument(west_negative_europe),
            ]
        )
        .bbox
        == tuple(west_negative_europe),
        "D1 generator bbox flag stays one --bbox=value token so west-negative"
        " scopes (United States, Europe frame) survive argparse",
        checks,
    )
    china_bbox_region = spatial_scope.resolve_region(
        {"bbox": [73.0, 18.0, 135.0, 54.0]}
    )
    china_named_region = spatial_scope.resolve_region("China")
    europe_bbox_region = spatial_scope.resolve_region(
        {"bbox": [-25.0, 34.0, 45.0, 72.0]}
    )
    require(
        request_runner._declared_coverage_inside_region(
            "zenodo-yangtze-yellow-river-sediment", china_bbox_region
        )
        and request_runner._declared_coverage_inside_region(
            "zenodo-yangtze-yellow-river-sediment", china_named_region
        )
        and not request_runner._declared_coverage_inside_region(
            "zenodo-yangtze-yellow-river-sediment", europe_bbox_region
        )
        and not request_runner._declared_coverage_inside_region(
            "georoc-convergent-margins", china_bbox_region
        )
        and not request_runner._declared_coverage_inside_region(
            "georoc-convergent-margins", china_named_region
        ),
        "D1 coordinate-less records survive a regional request only when the"
        " publisher-declared country coverage is provably inside the region",
        checks,
    )
    truncate_input = (
        [{"medium": "soil", "row": f"s{i}"} for i in range(6)]
        + [{"medium": "rock", "row": f"r{i}"} for i in range(2)]
        + [{"medium": "water", "row": f"w{i}"} for i in range(4)]
    )
    truncate_balanced = request_runner._capacity_truncate_balanced(
        list(truncate_input), 6
    )
    truncate_counts = Counter(row["medium"] for row in truncate_balanced)
    require(
        truncate_counts == {"soil": 2, "rock": 2, "water": 2}
        and [row["row"] for row in truncate_balanced]
        == ["s0", "s1", "r0", "r1", "w0", "w1"]
        and request_runner._capacity_truncate_balanced(list(truncate_input), 12)
        == truncate_input
        and request_runner._capacity_truncate_balanced(list(truncate_input), 0) == []
        and Counter(
            row["medium"]
            for row in request_runner._capacity_truncate_balanced(
                list(truncate_input), 9
            )
        )
        == {"soil": 4, "rock": 2, "water": 3},
        "D1 record-cap truncation water-fills capacity across media so scarce"
        " media are not evicted by routing order",
        checks,
    )
    require(
        request_runner.planned_slice_observations("gemstat-open-archive", 4, 50000)
        == 2048
        and request_runner.planned_slice_observations(
            "us-wqp-sacramento-river-arsenic", 1, 50000
        )
        == 48
        and request_runner.planned_slice_observations(
            "afsis-phase-i-wet-chemistry", 4, 50000
        )
        == 2048
        and request_runner.planned_slice_observations("geotraces-idp2025", 3, 50000)
        == 1536
        and request_runner.planned_slice_observations("australia-ngsa", 4, 50000)
        == 2048
        and request_runner.planned_slice_observations(
            "australia-ngsa-mercury", 1, 50000
        )
        == 48
        and request_runner.planned_slice_observations("foregs-topsoil", 4, 50000)
        == 4096
        and request_runner.planned_slice_observations("foregs-subsoil", 4, 50000)
        == 4096
        and request_runner.planned_slice_observations("foregs-humus", 4, 50000) == 1101
        and request_runner.planned_slice_observations("usgs-conus-soil", 4, 50000)
        == 6144
        and request_runner.planned_slice_observations("georoc-archaean", 4, 50000)
        == 2048
        and request_runner.planned_slice_observations(
            "georoc-antarctica-intraplate", 4, 50000
        )
        == 90
        and request_runner.planned_slice_observations(
            "tpdc-china-mountain-soil", 4, 50000
        )
        == 2560
        and request_runner.planned_slice_observations(
            "pangaea-arabian-sea-sediment", 4, 50000
        )
        == 162
        and request_runner.planned_slice_observations(
            "pangaea-north-africa-soil", 4, 50000
        )
        == 172
        and request_runner.planned_slice_observations("gemas-europe", 4, 50000) == 6656
        and request_runner.planned_slice_observations(
            "japan-gsj-marine-sediment", 4, 50000
        )
        == 2048
        and request_runner.planned_slice_observations("usgs-conus-soil", 4, 100) == 96
        and all(
            request_runner.planned_slice_observations(source_id, 4, 50000)
            <= request_runner.GENERATOR_MAX_OBSERVATIONS
            for source_id in (
                *request_runner.SLICE_DIVISORS,
                *request_runner.FIXED_SLICE_OBSERVATIONS,
                *request_runner.SCALABLE_BALANCED_SOURCES,
                "usgs-conus-soil",
                "georoc-archaean",
                "foregs-topsoil",
            )
        ),
        "D1 online slice planner scales to complete analyte/basis balance classes without the former 1000-row mismatch",
        checks,
    )
    require(
        request_runner.supported_request_analytes(
            "usgs-conus-soil", ["As", "Cu", "Pb", "Zn"]
        )
        == ["As", "Cu", "Zn"]
        and request_runner.supported_request_analytes(
            "foregs-humus", ["As", "Cu", "Pb", "Zn"]
        )
        == ["Cu", "Pb", "Zn"]
        and request_runner.supported_request_analytes(
            "us-wqp-sacramento-river-arsenic", ["As", "Cu", "Pb", "Zn"]
        )
        == ["As"]
        and request_runner.supported_request_analytes(
            "gemas-europe", ["As", "Cu", "Pb", "Zn"]
        )
        == ["As", "Cu", "Pb", "Zn"],
        "D1 online acquisition requests only registered analytes so one unencoded element cannot zero out a source",
        checks,
    )
    require(
        request_runner.planned_slice_observations(
            "tpdc-china-mountain-soil", 3, 50000, 10000, ["Cu", "Pb", "Zn"]
        )
        == 6570
        and request_runner.planned_slice_observations(
            "zenodo-yangtze-yellow-river-sediment",
            4,
            50000,
            10000,
            ["As", "Cu", "Pb", "Zn"],
        )
        == 558
        and request_runner.planned_slice_observations(
            "japan-gsj-marine-sediment", 4, 50000, 10000, ["As", "Cu", "Pb", "Zn"]
        )
        == 19571
        and request_runner.planned_slice_observations(
            "japan-gsj-geochemical-map",
            7,
            50000,
            10000,
            ["As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"],
        )
        == 21168
        and request_runner.planned_slice_observations(
            "afsis-phase-i-wet-chemistry",
            6,
            50000,
            10000,
            ["As", "Cr", "Cu", "Ni", "Pb", "Zn"],
        )
        == 11646,
        "D1 high-capacity planning uses audited emittable populations instead of raw source totals",
        checks,
    )
    with tempfile.TemporaryDirectory(prefix="request-failure-evidence-") as temporary:
        failure_output = Path(temporary) / "output"
        failed = subprocess.run(
            [
                sys.executable,
                str(REQUEST_RUNNER),
                "--request",
                str(SKILL_DIR / "fixtures" / "china" / "combined-v1" / "request.json"),
                "--output-dir",
                str(failure_output),
                "--input",
                str(
                    SOURCE_DEMOS
                    / "zenodo-yangtze-yellow-river-sediment"
                    / "demo_input.csv"
                ),
                "--evidence-jsonl",
                str(
                    SOURCE_DEMOS
                    / "zenodo-yangtze-yellow-river-sediment"
                    / "sources.jsonl"
                ),
                "--acquisition-manifest",
                str(
                    SOURCE_DEMOS
                    / "zenodo-yangtze-yellow-river-sediment"
                    / "run_manifest.json"
                ),
                "--analysis-profile",
                "production",
                "--coordinate-mode",
                "reported",
                "--no-geology",
                "--total-timeout-seconds",
                "120",
                "--workflow-reserve-seconds",
                "10",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        failure = json_value(
            failure_output / "request_evidence" / "execution_failure.json"
        )
        evidence = failure.get("evidence") or {}
        require(
            failed.returncode == 2
            and failure.get("status") == "incomplete_retrieval"
            and evidence.get("stage") == "d2_d3_workflow"
            and evidence.get("record_counts", {}).get("after_request_filters") == 48
            and len(evidence.get("acquisition_manifests") or []) == 2
            and (failure_output / "request_evidence" / "source_route.json").is_file(),
            "D1 request evidence and acquisition attempts survive a downstream D2/D3 failure",
            checks,
        )
    return checks


def check_d2(output_dir: Path) -> list[str]:
    checks: list[str] = []
    expected = {
        "geochemistry.csv",
        "qc_report.json",
        "confidence_report.json",
        "anomalies.geojson",
        "anomaly_report.json",
        "batch_acceptance.csv",
        "batch_qc_report.json",
        "anomaly_regions.geojson",
        "spatial_anomaly_report.json",
    }
    require(
        all((output_dir / name).is_file() for name in expected),
        "D2 publishes point, spatial and laboratory-QC analytical artifacts",
        checks,
    )
    require(
        set(sampling_time.SOURCE_SAMPLING_TIME)
        == set(json_value(SKILL_DIR / "assets" / "source_manifest.json")["sources"])
        | {"synthetic-demo-v1"}
        and all(
            ("raw_format" in entry) != ("reason" in entry)
            and (
                entry["raw_format"] in sampling_time._PARSERS
                if "raw_format" in entry
                else entry["reason"]
                in {
                    sampling_time.REASON_PUBLICATION_YEAR,
                    sampling_time.REASON_NOT_IN_ARCHIVE,
                }
            )
            for entry in sampling_time.SOURCE_SAMPLING_TIME.values()
        ),
        "D2 sampling-time contract covers every executable source with a declared format or a controlled missing reason",
        checks,
    )
    sampling_parse_cases = (
        ("geotraces-idp2025", "2011-11-20T17:06:54", "2011-11-20T17:06:54", "second"),
        ("gemstat-open-archive", "1976-02-18T11:00", "1976-02-18T11:00", "minute"),
        ("australia-ngsa", "2/04/2008", "2008-04-02", "day"),
        ("australia-ngsa-mercury", "8/09/2008", "2008-09-08", "day"),
        ("usgs-conus-soil", "02/16/09", "2009-02-16", "day"),
        ("pangaea-brasol-ne-brazil-soil", "25.07.08", "2008-07-25", "day"),
        ("pangaea-brasol-ne-brazil-soil", "39650", "2008-07-21", "day"),
        ("norway-marchem", "2015", "2015", "year"),
        ("afsis-phase-i-wet-chemistry", "2009/2013", "2009/2013", "year_range"),
        ("pangaea-amazonas-soil", "2016-03-01", "2016-03-01", "day"),
    )
    require(
        all(
            sampling_time.normalize_sampling_time(source_id, raw)
            == {
                "sampling_time": normalized,
                "sampling_time_precision": precision,
                "sampling_time_status": "publisher_reported",
            }
            for source_id, raw, normalized, precision in sampling_parse_cases
        )
        and sampling_time.normalize_sampling_time("georoc-archaean", "")[
            "sampling_time_status"
        ]
        == "publisher_not_reported"
        and sampling_time.normalize_sampling_time("australia-ngsa", "99/99/2008")[
            "sampling_time_status"
        ]
        == "unparseable_raw_value"
        and sampling_time.normalize_sampling_time("georoc-archaean", "1987")[
            "sampling_time_status"
        ]
        == "unparseable_raw_value",
        "D2 normalizes sampling dates per declared source format and never lets publication years pose as sampling times",
        checks,
    )
    require(
        standardizer.SCHEMA_COLUMNS[
            standardizer.SCHEMA_COLUMNS.index(
                "sampled_at"
            ) : standardizer.SCHEMA_COLUMNS.index("sampled_at") + 4
        ]
        == (
            "sampled_at",
            "sampling_time",
            "sampling_time_precision",
            "sampling_time_status",
        ),
        "D2 database schema keeps the normalized sampling-time columns beside the raw publisher value",
        checks,
    )
    with (
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "combined-v3"
        / "expected-output"
        / "geochemistry.csv"
    ).open(newline="", encoding="utf-8") as handle:
        combined_time_rows = list(csv.DictReader(handle))
    require(
        {row["sampling_time_status"] for row in combined_time_rows}
        == {"publisher_reported", "publisher_not_reported"}
        and {
            row["source_id"]
            for row in combined_time_rows
            if row["sampling_time_status"] == "publisher_reported"
        }
        == {
            "afsis-phase-i-wet-chemistry",
            "australia-ngsa-mercury",
            "gemstat-open-archive",
            "geotraces-idp2025",
            "norway-marchem",
            "us-wqp-sacramento-river-arsenic",
            "usgs-conus-soil",
        }
        and all(
            (row["sampling_time"] != "")
            == (row["sampling_time_status"] == "publisher_reported")
            for row in combined_time_rows
        )
        and {
            row["sampling_time_precision"]
            for row in combined_time_rows
            if row["sampling_time"]
        }
        == {"second", "minute", "day", "year", "year_range"},
        "D2 combined fixture dates the seven sampling-time sources without any unparseable values",
        checks,
    )
    combined_confidence = json_value(
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "combined-v3"
        / "expected-output"
        / "sources_and_confidence.json"
    )
    combined_time_coverage = combined_confidence.get("sampling_time_coverage") or {}
    geotraces_confidence = next(
        item
        for item in combined_confidence["sources"]
        if item["source_id"] == "geotraces-idp2025"
    )
    require(
        combined_time_coverage.get("contract") == "atlas-sampling-time-v1"
        and combined_time_coverage.get("dated_record_count") == 468
        and combined_time_coverage.get("status_record_counts", {}).get(
            "publisher_not_reported"
        )
        == 676
        and geotraces_confidence["sampling_time"]["earliest"] == "2011-11-20T17:06:54"
        and geotraces_confidence["sampling_time"]["latest"] == "2014-05-24T23:03:50",
        "D2 confidence report accounts for sampling-time coverage per source and in total",
        checks,
    )
    combined_provenance = json_value(
        SKILL_DIR
        / "fixtures"
        / "four-media"
        / "combined-v3"
        / "expected-output"
        / "anomaly_provenance.json"
    )
    require(
        combined_provenance["contract"] == "anomaly-provenance-v1"
        and combined_provenance["candidate_count"] == 27
        and combined_provenance["classification_counts"]
        == {"insufficient_evidence": 10, "not_applicable_depletion": 17}
        and output_validator.REQUIRED_FILES["anomaly_provenance"]
        == "anomaly_provenance.json"
        and all(
            item["plain_language"]
            and item["classification"] in provenance_classifier.CLASS_LABELS_ZH
            and item["classification_label_zh"]
            == provenance_classifier.CLASS_LABELS_ZH[item["classification"]]
            for item in combined_provenance["anomalies"]
        )
        and all(
            set(item["evidence_lines"])
            == {"lithology", "spatial", "association", "temporal"}
            for item in combined_provenance["anomalies"]
            if item["direction"] == "high"
        ),
        "D2 anomaly provenance report classifies every candidate with plain-language evidence lines",
        checks,
    )
    rising_series = [(2000.0, 10.0), (2005.0, 18.0), (2010.0, 30.0)]
    flat_series = [(2000.0, 10.0), (2005.0, 10.4), (2010.0, 9.8)]
    require(
        provenance_classifier._temporal_line(rising_series)[0]
        == provenance_classifier.SUPPORTS_ANTHROPOGENIC
        and provenance_classifier._temporal_line(flat_series)[0]
        == provenance_classifier.SUPPORTS_GEOGENIC
        and provenance_classifier._temporal_line(rising_series[:2])[0]
        == provenance_classifier.UNAVAILABLE
        and provenance_classifier._classify(
            {
                "lithology": (provenance_classifier.SUPPORTS_GEOGENIC, ""),
                "spatial": (provenance_classifier.SUPPORTS_GEOGENIC, ""),
                "association": (provenance_classifier.NEUTRAL, ""),
                "temporal": (provenance_classifier.UNAVAILABLE, ""),
            }
        )[0]
        == provenance_classifier.CLASS_GEOGENIC
        and provenance_classifier._classify(
            {
                "lithology": (provenance_classifier.SUPPORTS_GEOGENIC, ""),
                "spatial": (provenance_classifier.SUPPORTS_ANTHROPOGENIC, ""),
                "association": (provenance_classifier.NEUTRAL, ""),
                "temporal": (provenance_classifier.UNAVAILABLE, ""),
            }
        )[0]
        == provenance_classifier.CLASS_MIXED
        and provenance_classifier._classify(
            {
                "lithology": (provenance_classifier.UNAVAILABLE, ""),
                "spatial": (provenance_classifier.SUPPORTS_ANTHROPOGENIC, ""),
                "association": (provenance_classifier.UNAVAILABLE, ""),
                "temporal": (provenance_classifier.UNAVAILABLE, ""),
            }
        )[0]
        == provenance_classifier.CLASS_INSUFFICIENT,
        "D2 provenance rules need two agreeing evidence lines and degrade honestly to insufficient evidence",
        checks,
    )
    source_confidence = json_value(output_dir / "sources_and_confidence.json")
    require(
        source_confidence.get("report_version") == "sources-and-confidence-v3"
        and source_confidence.get("single_quality_label_prohibited") is True
        and source_confidence.get("metadata_completeness", {}).get("record_count") == 19
        and source_confidence.get("overall_workflow_confidence", {}).get(
            "not_a_probability"
        )
        is True
        and source_confidence.get("overall_workflow_confidence", {}).get("record_count")
        == 19
        and set(source_confidence.get("overall_dimension_score_means") or {})
        == {
            "source_evidence",
            "analytical_readiness",
            "spatial_usability",
            "workflow_usability",
        }
        and set(source_confidence.get("overall_dimension_band_counts") or {})
        == {
            "source_evidence",
            "analytical_readiness",
            "spatial_usability",
            "workflow_usability",
        },
        "D2 publishes a source/confidence explanation that cannot relabel low spatial usability as low source quality",
        checks,
    )
    template_html = (SKILL_DIR / "assets" / "interactive-atlas-v3.html").read_text(
        encoding="utf-8"
    )
    require(
        "来源证据画像（不是空间工作流评分）" in template_html
        and 'id="qualityDimension"' in template_html
        and "confidence_source_evidence_band" in template_html
        and "confidence_analytical_readiness_band" in template_html
        and "空间工作流复核（不等于数据质量）" in template_html,
        "D3 presents source/measurement evidence separately from strict spatial-workflow review instead of showing one ambiguous low-quality label",
        checks,
    )
    require(
        all(
            marker in template_html
            for marker in (
                "发布方元数据未报告",
                "删失值与科学限制",
                "已应用可追溯规则",
                "需处理或人工复核",
                "数据缺口与处理状态",
                "数据缺口与处理标记（保留原始代码）",
                "工作流 QC 状态",
                "不是 D2 处理失败",
                "MISSING_SOURCE_CRS",
                'id="evidenceLayer"',
                "严格科学可用",
                "完整，可定位到官方文件与记录",
                "已执行，存在已分类的证据缺口或复核项",
            )
        ),
        "D3 classifies publisher metadata gaps separately from processing failures while preserving raw QC codes",
        checks,
    )
    require(
        all(
            source["record_provenance"]["official_linked_record_count"] == 0
            and source["metadata_completeness"]["official_source_link"]["rate"] == 0.0
            and not source["official_links"]
            and source["metadata_completeness"]["exact_record_locator"]["rate"] == 1.0
            for source in source_confidence["sources"]
        ),
        "D2 source explanation keeps a synthetic local locator distinct from a nonexistent official URL instead of inventing one",
        checks,
    )
    rows = csv_rows(output_dir / "geochemistry.csv")
    require(len(rows) == 19, "D2 canonical database preserves all demo records", checks)
    require(
        {
            "source_record_id",
            "analyte_reported",
            "species_or_oxide",
            "source_qualifier_raw",
            "censored",
            "missing_reason",
            "method_family",
            "file_sha256",
            "coordinate_representation_resolution_m",
            "coordinate_representation_resolution_basis",
            "coordinate_accuracy_evidence_status",
            "official_source_url",
            "method_missing_reason",
            "method_source_locator",
        }.issubset(rows[0]),
        "D2 v2 database exposes provenance, censoring and method-family fields",
        checks,
    )
    indexed = {row["record_id"]: row for row in rows}
    require(
        all(not row["official_source_url"] for row in rows),
        "D2 canonical database leaves synthetic official-source URLs null instead of fabricating external provenance",
        checks,
    )
    require(
        indexed["soil-as-001"]["coordinate_accuracy_evidence_status"]
        == "source_reported_uncertainty"
        and indexed["soil-as-001"]["coordinate_representation_resolution_basis"]
        == "derived_from_source_decimal_places"
        and float(indexed["soil-as-001"]["coordinate_representation_resolution_m"])
        > 1000,
        "D2 separates source-reported coordinate uncertainty from derived numeric representation resolution",
        checks,
    )
    require(
        float(indexed["rock-fe-001"]["normalized_value"]) == 25_000,
        "D2 solid unit conversion is stable",
        checks,
    )
    molar_flags: list[str] = []
    require(
        standardizer.conversion_for("water", "nmol/kg", molar_flags) == (1.0, "nmol/kg")
        and not molar_flags,
        "D2 preserves seawater molar-per-mass values without an unstated density conversion",
        checks,
    )
    molar_volume = standardizer.normalize_row(
        {
            "record_id": "molar-ni",
            "sample_id": "molar-ni",
            "element_or_analyte": "Ni",
            "value": "20.814",
            "unit": "nmol/L",
            "medium": "water",
        },
        2,
    )
    unknown_molar = standardizer.normalize_row(
        {
            "record_id": "molar-unknown",
            "sample_id": "molar-unknown",
            "element_or_analyte": "Xx",
            "value": "20.814",
            "unit": "nmol/L",
            "medium": "water",
        },
        3,
    )
    require(
        abs(float(molar_volume["normalized_value"]) - 1.2216444276) < 1e-12
        and molar_volume["normalized_unit"] == "ug/L"
        and "atomic_weight(Ni)/1000" in molar_volume["conversion_formula"]
        and "d2-ciaaw-abridged-2024-v1" in molar_volume["conversion_formula"]
        and unknown_molar["normalized_value"] is None
        and "UNSUPPORTED_MOLAR_MASS" in unknown_molar["qc_flags"],
        "D2 converts evidence-supported nmol/L with frozen atomic weights and fails closed otherwise",
        checks,
    )
    require(
        indexed["soil-as-013"]["normalized_value"] == "",
        "D2 censored values are not imputed",
        checks,
    )
    require(
        indexed["soil-as-013"]["censored"] == "true",
        "D2 serializes censoring state explicitly",
        checks,
    )
    lod = standardizer.normalize_row(
        {
            "element_or_analyte": "As",
            "value": "<LOD",
            "unit": "mg/kg",
            "medium": "soil",
            "detection_limit": "0.2",
            "detection_limit_unit": "mg/kg",
        },
        2,
    )
    loq = standardizer.normalize_row(
        {
            "element_or_analyte": "As",
            "value": "<LOQ",
            "unit": "mg/kg",
            "medium": "soil",
            "quantitation_limit": "0.4",
            "quantitation_limit_unit": "mg/kg",
        },
        3,
    )
    require(
        lod["value_qualifier"] == "bdl"
        and lod["normalized_value"] is None
        and lod["normalized_censoring_limit"] == 0.2
        and loq["value_qualifier"] == "loq"
        and loq["normalized_value"] is None
        and loq["normalized_censoring_limit"] == 0.4,
        "D2 preserves literal LOD and LOQ censoring without zero imputation",
        checks,
    )
    require(
        indexed["soil-as-001"]["method_family"] == "icp_ms",
        "D2 normalizes analytical method families",
        checks,
    )
    require(
        "AMBIGUOUS_AQUEOUS_RATIO_UNIT" in indexed["water-as-ambiguous"]["qc_flags"],
        "D2 ambiguous aqueous units fail closed",
        checks,
    )
    require(
        indexed["swap-coord-001"]["latitude"] == ""
        and indexed["swap-coord-001"]["longitude"] == "",
        "D2 does not silently swap coordinates",
        checks,
    )
    duplicates = [row for row in rows if "DUPLICATE_CANDIDATE" in row["qc_flags"]]
    require(len(duplicates) == 2, "D2 retains and flags duplicate candidates", checks)
    fallback_duplicates = standardizer.process_rows(
        [
            {
                "record_id": "fallback-a",
                "source_record_id": "row-a",
                "sample_id": "",
                "element_or_analyte": "As",
                "value": "10",
                "unit": "mg/kg",
                "medium": "soil",
                "latitude": "35",
                "longitude": "103",
                "source_crs": "EPSG:4326",
            },
            {
                "record_id": "fallback-b",
                "source_record_id": "row-b",
                "sample_id": "",
                "element_or_analyte": "As",
                "value": "10",
                "unit": "mg/kg",
                "medium": "soil",
                "latitude": "35",
                "longitude": "103",
                "source_crs": "EPSG:4326",
            },
        ]
    )
    require(
        all(
            "DUPLICATE_CANDIDATE" in record["qc_flags"]
            for record in fallback_duplicates
        ),
        "D2 source-row IDs do not mask duplicates when sample IDs are absent",
        checks,
    )
    priority_records = [
        standardizer.normalize_row(
            {
                "record_id": f"priority-{index}",
                "sample_id": f"priority-sample-{index}",
                "element_or_analyte": "As",
                "value": value,
                "unit": "mg/kg",
                "medium": "soil",
            },
            index + 2,
        )
        for index, value in enumerate(("10", "<1", "ND", "trace"))
    ]
    _, priority_report = standardizer.detect_anomalies(
        priority_records, min_group_size=8, min_quantified_fraction=0.70
    )
    require(
        priority_report["groups"][0]["status"] == "insufficient_group_size"
        and priority_report["gate_evaluation_order"][:2]
        == ["independent_record_count", "quantified_fraction"],
        "D2 anomaly eligibility checks total sample size before quantified fraction",
        checks,
    )
    batch_fixture_root = SKILL_DIR / "fixtures" / "batch-qc"
    batch_rows, batch_report = batch_qc.evaluate(
        batch_fixture_root / "batch_qc.csv", batch_fixture_root / "qc_policy.json"
    )
    require(
        batch_report["passed_batch_count"] == 1
        and batch_rows[0]["crm_recovery_percent"] == 105.0
        and abs(batch_rows[0]["duplicate_rpd_percent"] - 9.523809523809524) < 1e-12
        and batch_rows[1]["batch_pass"] is False
        and batch_rows[1]["disposition"] == "exclude_batch_and_investigate",
        "D2 recomputes CRM recovery, blank and duplicate RPD and requires every check to pass",
        checks,
    )
    gated_records = []
    for index, (batch_id, value) in enumerate(
        [
            ("LAB-A", "10"),
            ("LAB-A", "11"),
            ("LAB-A", "12"),
            ("LAB-B", "100"),
            ("LAB-B", "110"),
            ("LAB-B", "120"),
        ]
    ):
        gated_records.append(
            standardizer.normalize_row(
                {
                    "record_id": f"batch-gate-{index}",
                    "sample_id": f"batch-sample-{index}",
                    "analysis_batch_id": batch_id,
                    "element_or_analyte": "As",
                    "value": value,
                    "unit": "mg/kg",
                    "medium": "soil",
                },
                index + 2,
            )
        )
    gate_summary = standardizer.apply_batch_acceptance(gated_records, batch_rows)
    _, gated_report = standardizer.detect_anomalies(
        gated_records,
        min_group_size=3,
        min_quantified_fraction=0.70,
        batch_qc_gate_applied=True,
    )
    require(
        gate_summary["record_status_counts"] == {"fail": 3, "pass": 3}
        and gated_report["groups"][0]["exclusion_reasons"]["batch_qc_failed"] == 3
        and gated_report["groups"][0]["records_used"] == 3
        and all(
            "BATCH_QC_FAILED" in record["qc_flags"]
            for record in gated_records
            if record["analysis_batch_id"] == "LAB-B"
        ),
        "D2 retains failed batches in the database while excluding them from anomaly backgrounds",
        checks,
    )
    spatial_records = []
    for index in range(40):
        inside = index < 20
        spatial_records.append(
            standardizer.normalize_row(
                {
                    "record_id": f"spatial-{index}",
                    "sample_id": f"spatial-sample-{index}",
                    "element_or_analyte": "As",
                    "value": str(10 + index / 100),
                    "unit": "mg/kg",
                    "medium": "soil",
                    "latitude": "0.25" if inside else "10.25",
                    "longitude": "0.25" if inside else "10.25",
                    "source_crs": "EPSG:4326",
                },
                index + 2,
            )
        )
    spatial_key = tuple(
        spatial_records[0].get(field) for field in standardizer.DEFAULT_GROUP_BY
    )
    spatial_group_id = standardizer.group_identifier(
        standardizer.DEFAULT_GROUP_BY, spatial_key
    )
    synthetic_points = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [0.25, 0.25]},
                "properties": {"record_id": f"spatial-{index}", "direction": "high"},
            }
            for index in range(5)
        ],
    }
    regions, region_report = standardizer.detect_spatial_anomaly_regions(
        spatial_records,
        synthetic_points,
        {"groups": [{"group_id": spatial_group_id, "status": "analyzed"}]},
        standardizer.DEFAULT_GROUP_BY,
        grid_degrees=2,
        minimum_spatial_samples=5,
        minimum_spatial_candidates=2,
        fdr_alpha=0.10,
    )
    require(
        region_report["hypothesis_count"] == 2
        and region_report["candidate_region_count"] == 1
        and regions["features"][0]["properties"]["status"] == "candidate_anomaly_region"
        and 0 < regions["features"][0]["properties"]["fdr_q_value"] < 0.10
        and region_report["method_version"] == "d2-spatial-hypergeometric-fdr-v1"
        and regions["features"][0]["properties"]["boundary_model"]
        == "fixed_wgs84_grid_cell_not_geologic_boundary",
        "D2 spatial regions require mapped background, exact enrichment and BH-FDR control",
        checks,
    )
    try:
        standardizer.run_pipeline(
            DEMO_INPUT,
            output_dir / "invalid-production",
            analysis_profile="production",
            min_group_size=8,
        )
    except standardizer.PipelineError:
        checks.append(
            "D2 production profile enforces at least twenty usable records per group"
        )
    else:
        raise ContractError(
            "D2 production profile accepted --min-group-size below twenty"
        )
    confidence = json_value(output_dir / "confidence_report.json")
    require(
        confidence.get("confidence_version") == "d2-confidence-v3",
        "D2 confidence version is explicit",
        checks,
    )
    require(
        set(confidence.get("weights", {}))
        == {"source", "completeness", "method", "spatial", "qc"},
        "D2 confidence component contract is complete",
        checks,
    )
    require(
        set(confidence.get("component_definitions", {}))
        == {"source", "completeness", "method", "spatial", "qc", "overall"}
        and confidence.get("source_scoring", {}).get("evidence_boundary"),
        "D2 confidence report explains every component and the D1 verification boundary",
        checks,
    )
    require(
        abs(sum(confidence["weights"].values()) - 1.0) < 1e-12,
        "D2 confidence weights sum to one",
        checks,
    )
    require(
        "missing_coordinate_uncertainty_medium_cap" in confidence["gates"]
        and confidence["gate_counts"].get("error_qc_low_cap", 0) > 0,
        "D2 confidence declares critical-field gates and applies error gates to the boundary fixture",
        checks,
    )
    synthetic_record = standardizer.normalize_row(
        {
            "record_id": "synthetic-confidence",
            "sample_id": "synthetic-sample",
            "element_or_analyte": "As",
            "value": "10",
            "unit": "mg/kg",
            "medium": "soil",
            "measurement_basis": "dry_total",
            "latitude": "35",
            "longitude": "103",
            "source_crs": "EPSG:4326",
            "coordinate_uncertainty_m": "10",
            "geologic_unit": "synthetic granite",
            "analytical_method": "ICP-MS",
            "method_family": "ICP-MS",
            "digestion_or_extraction": "four acid",
            "license": "CC0-1.0",
            "source_tier": "official_curated",
            "source_id": "synthetic-demo-v1",
            "source_locator": "local:fixture",
        },
        2,
    )
    require(
        synthetic_record["operational_confidence"]["band"] == "low"
        and "synthetic_fixture_low_cap"
        in synthetic_record["operational_confidence"]["gates_applied"],
        "D2 synthetic fixtures cannot receive high real-world operational confidence",
        checks,
    )
    synthetic_dimensions = synthetic_record["operational_confidence"][
        "quality_dimensions"
    ]
    require(
        synthetic_dimensions["source_evidence"]["band"] == "high"
        and synthetic_dimensions["workflow_usability"]["band"] == "low"
        and set(synthetic_dimensions)
        == {
            "source_evidence",
            "analytical_readiness",
            "spatial_usability",
            "workflow_usability",
        },
        "D2 separates source evidence, analytical readiness, spatial usability and combined workflow usability",
        checks,
    )
    production_dir = output_dir / "production-request"
    run_command(
        [
            sys.executable,
            str(REQUEST_RUNNER),
            "--request",
            str(PRODUCTION_REQUEST),
            "--output-dir",
            str(production_dir),
            "--demo",
            "production-usgs",
            "--analysis-profile",
            "production",
            "--generated-at",
            "2026-08-07T00:00:00Z",
        ]
    )
    production_summary = json_value(production_dir / "run_summary.json")
    production_anomaly = json_value(production_dir / "anomaly_report.json")
    production_confidence = json_value(production_dir / "confidence_report.json")
    production_execution = json_value(
        production_dir / "request_evidence" / "execution.json"
    )
    production_source_manifest = json_value(production_dir / "source_manifest.json")
    production_rows = csv_rows(production_dir / "geochemistry.csv")
    require(
        production_summary["metrics"]["record_count"] == 996
        and production_summary["metrics"]["valid_coordinate_count"] == 996
        and all(row["official_source_url"] for row in production_rows)
        and all(
            row["matched_geologic_unit"].startswith("GLiM:") for row in production_rows
        ),
        "D2 production demo performs pinned GLiM matching for every real USGS record",
        checks,
    )
    require(
        production_anomaly["minimum_group_size"] == 20
        and sum(group["status"] == "analyzed" for group in production_anomaly["groups"])
        == 12
        and production_anomaly["candidate_count"] == 6,
        "D2 production demo analyzes real comparable groups without lowering the twenty-record gate",
        checks,
    )
    require(
        production_confidence["confidence_version"] == "d2-confidence-v3"
        and production_confidence["band_counts"] == {"high": 0, "medium": 996, "low": 0}
        and production_confidence["gate_counts"]
        == {"missing_coordinate_uncertainty_medium_cap": 996},
        "D2 production demo keeps missing coordinate uncertainty visible through confidence gates",
        checks,
    )
    execution_schema = json_value(
        SKILL_DIR / "references" / "request-execution.schema.json"
    )
    acquisition_entries = production_execution["acquisition_manifests"]
    require(
        set(production_execution) == set(execution_schema["properties"])
        and set(execution_schema["required"]) <= set(production_execution)
        and production_execution["route_resolution"] == "offline_fixture_hash_verified"
        and production_execution["execution_coverage_status"] == "partial"
        and production_execution["acquisition_scheduler"]
        == {
            "policy": "gap-priority-then-coverage-balanced-round-robin-v2",
            "source_order_offset": 0,
            "priority_source_ids": [],
            "effective_source_ids": [],
        },
        "D1-to-D3 request execution explains offline hash verification without overstating coverage",
        checks,
    )
    require(
        production_execution["execution_version"] == "geochemical-request-execution-v6"
        and production_execution["timing"]["official_task_limit_seconds"] == 900.0
        and production_execution["timing"]["internal_budget_seconds"] == 900.0
        and production_execution["timing"]["workflow_reserve_seconds"] == 180.0
        and production_execution["timing"]["completed_within_internal_budget"] is True
        and production_execution["timing"]["elapsed_seconds"]
        < production_execution["timing"]["internal_budget_seconds"],
        "D1-to-D3 execution evidence records the official 900-second default budget",
        checks,
    )
    require(
        production_execution["skill_snapshot"]["algorithm"] == "skill-tree-sha256-v1"
        and production_execution["skill_snapshot"]["stable_during_execution"] is True
        and production_execution["skill_snapshot"]["start_sha256"]
        == production_execution["skill_snapshot"]["end_sha256"]
        and production_execution["skill_snapshot"]["stability_verification"]
        == "path-and-stat-identity-v1"
        and production_execution["skill_snapshot"]["file_count"] > 500,
        "D1-to-D3 execution binds the exact stable Skill tree used for the run",
        checks,
    )
    require(
        [item["role"] for item in acquisition_entries]
        == ["request_filtered_manifest", "parent_source_manifest"]
        and all(
            (production_dir / "request_evidence" / item["path"]).is_file()
            and sha256_file(production_dir / "request_evidence" / item["path"])
            == item["sha256"]
            for item in acquisition_entries
        )
        and production_source_manifest["record_evidence"]["acquisition_manifest"][
            "sha256"
        ]
        == acquisition_entries[0]["sha256"],
        "D1 request evidence retains every manifest byte needed to audit the post-run hash chain",
        checks,
    )
    mismatched_request = json_value(PRODUCTION_REQUEST)
    mismatched_request["sources"] = ["georoc-archaean"]
    with tempfile.TemporaryDirectory() as mismatch_temp:
        mismatched_path = Path(mismatch_temp) / "mismatched-source-request.json"
        mismatched_path.write_text(json.dumps(mismatched_request), encoding="utf-8")
        mismatch_result = run_command(
            [
                sys.executable,
                str(REQUEST_RUNNER),
                "--request",
                str(mismatched_path),
                "--output-dir",
                str(Path(mismatch_temp) / "mismatched-source-output"),
                "--demo",
                "production-usgs",
            ],
            expected_code=2,
        )
        mismatch_summary = json_value(
            Path(mismatch_temp) / "mismatched-source-output" / "run_summary.json"
        )
    require(
        '"status": "incomplete_retrieval"' in mismatch_result.stderr
        and "'source': 996" in mismatch_result.stderr
        and mismatch_summary["status"] == "incomplete_retrieval"
        and mismatch_summary["quality_status"] == "not_evaluated",
        "Request runner never substitutes an excluded source and always emits a structured failure summary",
        checks,
    )
    with tempfile.TemporaryDirectory() as tamper_temp:
        tampered_input = Path(tamper_temp) / "demo_input.csv"
        production_fixture = SKILL_DIR / "fixtures" / "production-usgs"
        tampered_input.write_bytes(
            (production_fixture / "demo_input.csv").read_bytes() + b"\n"
        )
        try:
            request_runner.verify_manifest_outputs(
                production_fixture / "run_manifest.json",
                [tampered_input, production_fixture / "sources.jsonl"],
            )
        except request_runner.RequestRunError as exc:
            require(
                exc.status == "conflicting_evidence"
                and "hash/size mismatch" in str(exc),
                "Request runner rejects a fixture whose bytes no longer match its parent manifest",
                checks,
            )
        else:
            raise ContractError("Request runner accepted tampered fixture bytes")
    anomaly_report = json_value(output_dir / "anomaly_report.json")
    anomalies = json_value(output_dir / "anomalies.geojson")
    require(
        anomaly_report.get("interface_version") == "d2-interface-v2"
        and anomalies.get("interface_version") == "d2-interface-v2",
        "D2 anomaly outputs expose the stable interface version",
        checks,
    )
    require(
        anomaly_report.get("method_version") == "d2-robust-mad-v2"
        and anomalies.get("method_version") == "d2-robust-mad-v2"
        and all(
            feature.get("properties", {}).get("method_version") == "d2-robust-mad-v2"
            for feature in anomalies.get("features", [])
        ),
        "D2 anomaly outputs expose one validated method version",
        checks,
    )
    require(
        anomaly_report.get("scientific_status") == "screening_baseline_only",
        "D2 anomaly boundary is explicit",
        checks,
    )
    require(
        anomaly_report.get("minimum_quantified_fraction") == 0.70,
        "D2 anomaly screening declares the quantified-fraction gate",
        checks,
    )
    require(
        anomaly_report.get("candidate_count") == 1,
        "D2 demo anomaly result is stable",
        checks,
    )
    require(
        anomalies["features"][0]["properties"].get("status") == "candidate_anomaly",
        "D2 does not turn a screening candidate into a causal conclusion",
        checks,
    )
    schema_map = json_value(SKILL_DIR / "references" / "schema-map.schema.json")
    require(
        set(schema_map["propertyNames"]["enum"]) == standardizer.INPUT_FIELDS,
        "D1-to-D2 schema-map fields match the executable interface",
        checks,
    )
    crosswalk_schema = json_value(
        SKILL_DIR / "references" / "platform-field-crosswalk.schema.json"
    )
    require(
        crosswalk_schema.get("$schema")
        == "https://json-schema.org/draft/2020-12/schema",
        "D2 professional-platform crosswalk has a versioned JSON Schema",
        checks,
    )
    record_schema = json_value(
        SKILL_DIR / "references" / "geochemistry-record.schema.json"
    )
    crosswalk = json_value(SKILL_DIR / "references" / "platform-field-crosswalk.json")
    require(
        crosswalk.get("status") == "semantic_alignment_not_conformance_claim"
        and crosswalk.get("canonical_schema", {}).get("schema_id")
        == record_schema.get("$id"),
        "D2 crosswalk declares semantic alignment without a false conformance claim",
        checks,
    )
    mapped_fields = [item["canonical_field"] for item in crosswalk["field_mappings"]]
    non_core_fields = [
        field for group in crosswalk["non_core_fields"] for field in group["fields"]
    ]
    canonical_fields = set(record_schema["properties"])
    require(
        len(mapped_fields) == len(set(mapped_fields))
        and len(non_core_fields) == len(set(non_core_fields))
        and set(mapped_fields).isdisjoint(non_core_fields),
        "D2 crosswalk field partitions are unique and disjoint",
        checks,
    )
    require(
        set(mapped_fields) | set(non_core_fields) == canonical_fields,
        "D2 crosswalk accounts for every canonical database field",
        checks,
    )
    scope = crosswalk["scope"]
    require(
        scope.get("canonical_field_count") == len(canonical_fields)
        and scope.get("crosswalked_field_count") == len(mapped_fields)
        and scope.get("non_core_field_count") == len(non_core_fields),
        "D2 crosswalk coverage counts match the executable record Schema",
        checks,
    )
    evidence_ids = [item["id"] for item in crosswalk["evidence_sources"]]
    platform_ids = [item["id"] for item in crosswalk["platforms"]]
    require(
        len(evidence_ids) == len(set(evidence_ids))
        and len(platform_ids) == len(set(platform_ids))
        and set(platform_ids)
        == {"earthchem_ecl", "usgs_agdb2", "odm2", "igsn_datacite"},
        "D2 crosswalk platform and evidence registries are unique and explicit",
        checks,
    )
    evidence_set = set(evidence_ids)
    platform_set = set(platform_ids)
    valid_mapping_types = {
        "exact",
        "renamed",
        "transformed",
        "composite",
        "no_direct_equivalent",
    }
    mapping_rows = [
        mapping
        for field_mapping in crosswalk["field_mappings"]
        for mapping in field_mapping["platform_mappings"]
    ]
    require(
        all(
            mapping["platform_id"] in platform_set
            and mapping["mapping_type"] in valid_mapping_types
            and set(mapping["evidence_ids"]) <= evidence_set
            and (
                (
                    mapping["mapping_type"] == "no_direct_equivalent"
                    and not mapping["external_path"]
                )
                or (
                    mapping["mapping_type"] != "no_direct_equivalent"
                    and bool(mapping["external_path"])
                )
            )
            for mapping in mapping_rows
        )
        and all(
            len(
                {
                    mapping["platform_id"]
                    for mapping in field_mapping["platform_mappings"]
                }
            )
            == len(field_mapping["platform_mappings"])
            for field_mapping in crosswalk["field_mappings"]
        )
        and all(
            set(platform["evidence_ids"]) <= evidence_set
            for platform in crosswalk["platforms"]
        ),
        "D2 crosswalk mappings reference valid platforms, evidence and absence semantics",
        checks,
    )
    return checks


def check_d3(output_dir: Path) -> list[str]:
    checks: list[str] = []
    geological_context = map_builder.geological_context_display(
        {
            "geographic_context_raw": "Upper Yangtze catchment",
            "soil_horizon": "0-20 cm topsoil",
            "lithology_raw": "carbonate-bearing parent material",
            "geology_missing_reason": "invalid_or_missing_canonical_coordinate",
        },
        spatial_domain="land",
    )
    require(
        geological_context["formal_geologic_unit"] is None
        and geological_context["geological_context_status"]
        == "publisher_context_reported"
        and "Upper Yangtze catchment"
        in geological_context["publisher_geological_background"]
        and "0-20 cm topsoil" in geological_context["publisher_geological_background"],
        "D3 distinguishes a formal spatially matched geologic unit from source-reported geological and depositional background",
        checks,
    )
    publisher_gap_row = {
        "source_id": "figshare-yangtze-basin-soil-heavy-metals",
        "source_record_id": "src-" + "a" * 64,
        "source_file": "Records.xlsx",
        "source_locator": "Records.xlsx#sheet=Records&row=3754",
        "dataset_title": "A dataset of heavy metal concentrations in soils across the Yangtze River basin",
        "dataset_version": "figshare-file-2023-05-31",
        "official_source_url": "https://ndownloader.figshare.com/files/40503701",
        "file_sha256": "b" * 64,
        "license": "CC-BY-4.0",
        "normalized_value": "3715",
        "normalized_unit": "mg/kg",
        "analytical_method": "",
        "method_family": "",
        "geology_missing_reason": "invalid_or_missing_canonical_coordinate",
        "qc_flags": (
            '["MISSING_ANALYTICAL_METHOD","MISSING_DIGESTION_OR_EXTRACTION",'
            '"MISSING_SOURCE_CRS","COORDINATE_NOT_CANONICALIZED"]'
        ),
    }
    publisher_gap_classification = map_builder.record_evidence_classification(
        publisher_gap_row,
        coordinate_basis=map_builder.COORDINATE_BASIS_REPORTED,
        spatial_domain="land",
        qc_flags=[
            "MISSING_ANALYTICAL_METHOD",
            "MISSING_DIGESTION_OR_EXTRACTION",
            "MISSING_SOURCE_CRS",
            "COORDINATE_NOT_CANONICALIZED",
        ],
    )
    require(
        publisher_gap_classification["evidence_layer"] == "traceable_screening_only"
        and publisher_gap_classification["provenance_status"] == "strict_complete"
        and publisher_gap_classification["quality_control_status"]
        == "completed_with_flags"
        and publisher_gap_classification["missing_provenance_fields"] == []
        and publisher_gap_classification["blocking_qc_flags"] == []
        and set(publisher_gap_classification["scientific_readiness_reasons"])
        == {
            "canonical_wgs84_coordinate_missing",
            "analytical_method_missing",
            "geological_context_missing",
        },
        "D3 distinguishes complete provenance and executed QC from publisher metadata gaps on the reported Figshare row",
        checks,
    )
    with tempfile.TemporaryDirectory(prefix="d3-map-availability-") as summary_temp:
        summary_input = Path(summary_temp) / "geochemistry.csv"
        summary_input.write_text(
            "element_or_analyte,medium,latitude,longitude,original_latitude_raw,original_longitude_raw,normalized_value,normalized_unit,measurement_basis,method_family,censored,source_id,source_locator,qc_flags\n"
            "As,sediment,,,,,2,mg/kg,total,icp_ms,false,source-a,https://example.test/as,[]\n"
            "Cu,soil,35,105,35,105,3,mg/kg,total,icp_ms,false,source-b,https://example.test/cu,[]\n",
            encoding="utf-8",
        )
        availability = map_builder.database_visual_summary(summary_input)[
            "map_availability"
        ]
    require(
        availability["elements"]["As"]
        == {
            "database_records": 1,
            "canonical_coordinate_records": 0,
            "reported_only_coordinate_records": 0,
            "unplottable_records": 1,
        }
        and availability["elements"]["Cu"]["canonical_coordinate_records"] == 1,
        "D3 preserves database-only elements and reports why they cannot appear on the map",
        checks,
    )
    benchmark = benchmark_workflow.run_benchmark(warmups=0, runs=2)
    require(
        benchmark["schema_version"] == "geochemical-workflow-benchmark-v1"
        and benchmark["protocol"]["measured_runs"] == 2
        and len(benchmark["timing_seconds"]["samples"]) == 2
        and benchmark["result_consistency"]["distinct_result_signatures"] == 1
        and benchmark["result_consistency"]["runner_status_counts"]
        == {"partial_success": 2}
        and benchmark["result_consistency"]["validation_metrics"]["record_count"]
        == 996,
        "D3 repeated workflow benchmark validates every run and reports stable statistics",
        checks,
    )
    source_plan = task_router.plan_task(
        {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "source_discovery",
            "request": "REQUEST.json",
            "output_dir": "OUTPUT",
        }
    )
    task_contract_schema = json_value(
        SKILL_DIR / "references" / "task-contract.schema.json"
    )
    full_plan = task_router.plan_task(
        {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "full_atlas",
            "request": "REQUEST.json",
            "input": "INPUT.csv",
            "output_dir": "OUTPUT",
            "acquisition_mode": "provided_input",
        }
    )
    online_full_plan = task_router.plan_task(
        {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "full_atlas",
            "request": "REQUEST.json",
            "output_dir": "OUTPUT",
        }
    )
    extended_online_plan = task_router.plan_task(
        {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "full_atlas",
            "request": "REQUEST.json",
            "output_dir": "OUTPUT",
            "deadline_seconds": 43200,
        }
    )
    short_online_plan = task_router.plan_task(
        {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "full_atlas",
            "request": "REQUEST.json",
            "output_dir": "OUTPUT",
            "deadline_seconds": 3600,
        }
    )
    checkpoint_online_plan = task_router.plan_task(
        {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "full_atlas",
            "request": "REQUEST.json",
            "output_dir": "OUTPUT",
            "deadline_seconds": 600,
        }
    )
    try:
        task_router.plan_task(
            {
                "contract_version": "atlas-task-contract-v1",
                "task_type": "source_discovery",
                "request": "REQUEST.json",
                "output_dir": "OUTPUT",
                "required_outputs": ["interactive_map.html"],
            }
        )
    except task_router.TaskRoutingError:
        mismatched_task_output_rejected = True
    else:
        mismatched_task_output_rejected = False
    require(
        [Path(command[1]).name for command in source_plan["commands"]]
        == ["source_router.py", "coverage_report.py"]
        and all(command[0] == "python3" for command in source_plan["commands"])
        and source_plan["required_outputs"]
        == ["source_route.json", "coverage.json", "coverage.md"]
        and Path(full_plan["commands"][0][1]).name == "run_atlas_request.py"
        and full_plan["commands"][0][0] == "python3"
        and "--total-timeout-seconds" in full_plan["commands"][0]
        and Path(online_full_plan["commands"][0][1]).name
        == "run_self_correction_loop.py"
        and "--online-source" in online_full_plan["commands"][0]
        and "--time-budget-seconds" in online_full_plan["commands"][0]
        and online_full_plan["deadline_seconds"] == 900.0
        and online_full_plan["commands"][0][
            online_full_plan["commands"][0].index("--time-budget-seconds") + 1
        ]
        == "720.0"
        and "--checkpoint-only" in online_full_plan["commands"][0]
        and extended_online_plan["deadline_seconds"] == 43200.0
        and "--checkpoint-only" not in extended_online_plan["commands"][0]
        and "--checkpoint-only" not in short_online_plan["commands"][0]
        and "--checkpoint-only" in checkpoint_online_plan["commands"][0]
        and execution_budget.OFFICIAL_TASK_LIMIT_SECONDS == 900.0
        and full_plan["validators"]
        and mismatched_task_output_rejected,
        "D3 deterministic TaskContract selects the minimum stable entry point and exact acceptance outputs",
        checks,
    )
    require(
        task_contract_schema["properties"]["deadline_seconds"]["default"] == 900,
        "D3 task contract defaults to the official 900-second external sandbox envelope",
        checks,
    )
    skill_dirs = [
        path
        for path in (REPO_ROOT / "skills").iterdir()
        if path.is_dir() and not path.name.startswith(".")
    ]
    require(
        len(skill_dirs) == 1 and skill_dirs[0] == SKILL_DIR,
        "D3 keeps exactly one production Skill",
        checks,
    )
    activation = json_value(SKILL_DIR / "evals" / "activation.json")
    activation_cases = activation.get("cases", [])
    openai_contract = (SKILL_DIR / "agents" / "openai.yaml").read_text(encoding="utf-8")
    skill_card = (SKILL_DIR / "skill-card.md").read_text(encoding="utf-8")
    require(
        (SKILL_DIR / "SKILL.md").is_file()
        and (SKILL_DIR / "BENCHMARK.md").is_file()
        and activation.get("schema_version") == "skill-activation-eval-v1"
        and activation.get("skill") == "global-geochemical-atlas"
        and sum(case.get("should_activate") is True for case in activation_cases) >= 2
        and sum(case.get("should_activate") is False for case in activation_cases) >= 2
        and {
            "discoverability",
            "correctness",
            "security",
            "effectiveness",
            "efficiency",
        }.issubset(activation.get("rubrics", {}))
        and "allow_implicit_invocation: true" in openai_contract
        and "## Effective capabilities" in skill_card
        and "## Trust boundaries and controls" in skill_card
        and "## Static scanner verification" in skill_card,
        "D3 publishes governed Skill metadata, capability controls and balanced activation cases",
        checks,
    )
    temporal_html = (output_dir / "temporal_map.html").read_text(encoding="utf-8")
    combined_expected_dir = (
        SKILL_DIR / "fixtures" / "four-media" / "combined-v3" / "expected-output"
    )
    temporal_payload = temporal_map_builder.build_payload(
        combined_expected_dir / "geochemistry.csv",
        combined_expected_dir / "anomaly_provenance.json",
    )
    temporal_stats = temporal_payload["stats"]
    require(
        output_validator.REQUIRED_FILES["temporal_map"] == "temporal_map.html"
        and '<script id="temporal-payload" type="application/json">' in temporal_html
        and '"schema_version":"temporal-atlas-payload-v1"' in temporal_html
        and '<script id="basemap-data" type="application/json">' in temporal_html
        and "\u533a\u57df\u5bf9\u6bd4" in temporal_html
        and "\u91c7\u6837\u53f2\u56de\u653e" in temporal_html
        and "\u7ad9\u70b9\u6f14\u53d8" in temporal_html
        and "异常成因" in temporal_html
        and 'id="modeCompare"' in temporal_html
        and 'id="modeProvenance"' in temporal_html
        and 'id="colorConc"' in temporal_html
        and "<script src=" not in temporal_html
        and "https://" not in temporal_html.split("<style>")[0],
        "D3 temporal map ships both replay and station modes as one offline HTML",
        checks,
    )
    require(
        temporal_stats["total_records"] == 1144
        and temporal_stats["dated_records"] == 468
        and temporal_stats["status_counts"]
        == {"publisher_not_reported": 676, "publisher_reported": 468}
        and temporal_stats["time_parse_failed"] == 0
        and temporal_stats["stations_mode_b"] == 6
        and temporal_stats["year_min"] == 1976
        and temporal_stats["year_max"] == 2024
        and temporal_stats["precision_counts"]
        == {"day": 156, "minute": 56, "second": 96, "year": 112, "year_range": 48}
        and any(
            station["label"] == "nwisca.01" and station["timepoints"] == 48
            for station in temporal_payload["stations"]
        )
        and all(
            station["timepoints"] >= temporal_map_builder.STATION_MIN_TIMEPOINTS
            for station in temporal_payload["stations"]
        ),
        "D3 temporal map payload keeps honest dated/undated accounting on the combined fixture",
        checks,
    )
    temporal_prov = temporal_payload["anomaly_provenance"]
    combined_prov_report = json_value(combined_expected_dir / "anomaly_provenance.json")
    require(
        temporal_prov is not None
        and temporal_prov["contract"] == "anomaly-provenance-v1"
        and temporal_prov["candidate_count"] == 27
        and temporal_prov["mapped"] + temporal_prov["unmapped"] == 27
        and temporal_prov["class_counts"]
        == combined_prov_report["classification_counts"]
        and all(
            entry["classification"] in temporal_prov["labels_zh"]
            and len(entry["lines"]) in (0, 4)
            for entry in temporal_prov["entries"]
        )
        and temporal_map_builder.build_payload(
            combined_expected_dir / "geochemistry.csv"
        )["anomaly_provenance"]
        is None,
        "D3 temporal map embeds geogenic-vs-anthropogenic verdicts with evidence lines and stays optional",
        checks,
    )
    require(
        temporal_map_builder.parse_sampling_time("2009/2013", "year_range")
        == (2011.5, 2009.0, 2014.0)
        and temporal_map_builder.parse_sampling_time("2011-11-20T17:06:54", "second")
        is not None
        and temporal_map_builder.parse_sampling_time("not-a-date", "day") is None
        and temporal_map_builder.classify_trend(2.0, 10.0, [10.0, 12.0, 30.0])
        == "rising"
        and temporal_map_builder.classify_trend(-2.0, 10.0, [30.0, 12.0, 10.0])
        == "falling"
        and temporal_map_builder.classify_trend(0.01, 2.0, [100.0, 101.0]) == "stable",
        "D3 temporal parser keeps year ranges as intervals and trend classes need a material relative slope",
        checks,
    )
    temporal_region_payload = temporal_map_builder.build_payload(
        combined_expected_dir / "geochemistry.csv",
        region={
            "label": "中国（含台湾）",
            "bounds": {"w": 73.0, "s": 18.0, "e": 135.0, "n": 54.0},
            "clip_method": "country",
        },
    )
    require(
        temporal_region_payload["region"]
        == {
            "label": "中国（含台湾）",
            "bounds": {"w": 73.0, "s": 18.0, "e": 135.0, "n": 54.0},
            "clip_method": "country",
        }
        and temporal_payload["region"] is None
        and "fitRegionView" in temporal_html
        and 'id="pageTitle"' in temporal_html,
        "D3 temporal map payload carries the frozen request region and the"
        " template frames its initial view on it",
        checks,
    )
    good_temporal_errors: list[str] = []
    output_validator.validate_temporal_html(
        output_dir / "temporal_map.html", good_temporal_errors
    )
    with tempfile.TemporaryDirectory() as temporal_temp:
        bad_temporal_path = Path(temporal_temp) / "temporal_map.html"
        bad_temporal_path.write_text(
            temporal_html.replace("publisher_not_reported", "redacted"),
            encoding="utf-8",
        )
        bad_temporal_errors: list[str] = []
        output_validator.validate_temporal_html(bad_temporal_path, bad_temporal_errors)
    require(
        not good_temporal_errors
        and any(
            "honest sampling-time coverage" in message
            for message in bad_temporal_errors
        ),
        "D3 temporal map validator rejects copies that hide the honest time-coverage statement",
        checks,
    )
    required_outputs = set(output_validator.REQUIRED_FILES.values())
    actual_outputs = {path.name for path in output_dir.iterdir() if path.is_file()}
    require(
        actual_outputs == required_outputs, "D3 publishes the stable output set", checks
    )
    validation = output_validator.validate_dir(output_dir)
    require(
        validation.get("status") == "valid",
        "D3 integrated outputs pass the public validator",
        checks,
    )
    research_validation = research_delivery_validator.validate_delivery(output_dir)
    require(
        research_validation.get("status") == "invalid"
        and "missing loop_report.json" in research_validation.get("errors", [])
        and "missing research_delivery_receipt.json"
        in research_validation.get("errors", []),
        "D3 core-file success cannot masquerade as a sufficient online research delivery",
        checks,
    )
    with tempfile.TemporaryDirectory() as checkpoint_temp:
        checkpoint_dir = Path(checkpoint_temp)
        checkpoint_round_dir = checkpoint_dir / "rounds" / "round-01"
        checkpoint_round_dir.mkdir(parents=True)
        for filename in output_validator.REQUIRED_FILES.values():
            shutil.copy2(output_dir / filename, checkpoint_dir / filename)
            shutil.copy2(output_dir / filename, checkpoint_round_dir / filename)
        request_hash = "a" * 64
        current_snapshot = skill_snapshot.fingerprint_skill_tree(SKILL_DIR)
        execution_snapshot = {
            "algorithm": current_snapshot["algorithm"],
            "start_sha256": current_snapshot["sha256"],
            "end_sha256": current_snapshot["sha256"],
            "stable_during_execution": True,
            "file_count": current_snapshot["file_count"],
            "total_bytes": current_snapshot["total_bytes"],
            "stability_verification": "path-and-stat-identity-v1",
        }
        execution = {
            "execution_version": "geochemical-request-execution-v6",
            "mode": "online_multi_source",
            "skill_snapshot": execution_snapshot,
        }
        execution_path = checkpoint_dir / "request_evidence" / "execution.json"
        execution_path.parent.mkdir()
        execution_path.write_text(
            json.dumps(execution, sort_keys=True) + "\n", encoding="utf-8"
        )
        loop = {
            "schema_version": "self-correction-loop-report-v7",
            "request_sha256": request_hash,
            "checkpoint_only": True,
            "stop_reason": "insufficient_data",
            "status": "needs_human_review",
            "published_round": 1,
            "rounds": [
                {
                    "round": 1,
                    "validation_status": "valid",
                    "sufficiency": {"status": "insufficient"},
                }
            ],
        }
        queue = {
            "queue_version": "d1-repair-queue-v3",
            "request_sha256": request_hash,
            "status": "pending",
            "task_count": 1,
            "action_group_count": 1,
            "unattempted_action_group_count": 1,
            "operator_continuation_required": True,
            "tasks": [{"task_id": "pending-test"}],
            "action_groups": [
                {
                    "action_group_id": "pending-group",
                    "member_task_ids": ["pending-test"],
                }
            ],
        }
        loop_path = checkpoint_dir / "loop_report.json"
        queue_path = checkpoint_dir / "d1_repair_queue.json"
        loop_path.write_text(json.dumps(loop, sort_keys=True) + "\n", encoding="utf-8")
        queue_path.write_text(
            json.dumps(queue, sort_keys=True) + "\n", encoding="utf-8"
        )
        artifacts = {
            filename: {
                "root_sha256": sha256_file(checkpoint_dir / filename),
                "round_sha256": sha256_file(checkpoint_dir / filename),
            }
            for filename in output_validator.REQUIRED_FILES.values()
        }
        receipt = {
            "schema_version": "atlas-research-delivery-receipt-v3",
            "request_sha256": request_hash,
            "published_round": 1,
            "published_round_dir": "rounds/round-01",
            "loop_status": "needs_human_review",
            "loop_stop_reason": "insufficient_data",
            "sufficiency_status": "insufficient",
            "execution_mode": "online_multi_source",
            "checkpoint_only": True,
            "d1_repair_queue_status": "pending",
            "control_files": {
                "loop_report_sha256": sha256_file(loop_path),
                "d1_repair_queue_sha256": sha256_file(queue_path),
                "execution_sha256": sha256_file(execution_path),
            },
            "skill_snapshot": {
                "algorithm": current_snapshot["algorithm"],
                "execution_sha256": current_snapshot["sha256"],
                "current_sha256": current_snapshot["sha256"],
                "matches_execution": True,
                "file_count": current_snapshot["file_count"],
                "total_bytes": current_snapshot["total_bytes"],
            },
            "delivery_ready": False,
            "artifacts": artifacts,
            "claim_boundary": "checkpoint test",
        }
        receipt_path = checkpoint_dir / "research_delivery_receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
        )
        strict_checkpoint = research_delivery_validator.validate_delivery(
            checkpoint_dir
        )
        auditable_checkpoint = research_delivery_validator.validate_delivery(
            checkpoint_dir, allow_insufficient_checkpoint=True
        )
        require(
            strict_checkpoint["status"] == "invalid"
            and auditable_checkpoint["status"] == "valid"
            and auditable_checkpoint["delivery_ready"] is False
            and "formal research delivery has pending D1 repair tasks"
            in auditable_checkpoint["warnings"],
            "D3 formal delivery fails pending repairs while explicit checkpoint audit preserves evidence validity",
            checks,
        )
        round_map = checkpoint_round_dir / "interactive_map.html"
        original_round_map = round_map.read_bytes()
        round_map.write_bytes(original_round_map + b"\n")
        tampered_round = research_delivery_validator.validate_delivery(
            checkpoint_dir, allow_insufficient_checkpoint=True
        )
        require(
            tampered_round["status"] == "invalid"
            and "immutable round hash mismatch for interactive_map.html"
            in tampered_round["errors"],
            "D3 delivery validator rehashes immutable round bytes instead of trusting a self-consistent receipt",
            checks,
        )
        round_map.write_bytes(original_round_map)
        execution["skill_snapshot"]["end_sha256"] = "b" * 64
        execution_path.write_text(
            json.dumps(execution, sort_keys=True) + "\n", encoding="utf-8"
        )
        receipt["control_files"]["execution_sha256"] = sha256_file(execution_path)
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8"
        )
        tampered_checkpoint = research_delivery_validator.validate_delivery(
            checkpoint_dir, allow_insufficient_checkpoint=True
        )
        require(
            tampered_checkpoint["status"] == "invalid"
            and "execution start/end Skill hashes differ"
            in tampered_checkpoint["errors"],
            "D3 checkpoint audit never relaxes executable Skill provenance",
            checks,
        )
    html = (output_dir / "interactive_map.html").read_text(encoding="utf-8")
    require(
        "<script src=" not in html.casefold(),
        "D3 map is self-contained without external scripts",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'id="element"',
                'id="medium"',
                'id="sampleType"',
                'id="methodScope"',
                'id="confidence"',
                'id="anomalyOnly"',
                "completeDimensionValues",
                "selectedDatabaseGap",
                "地图 0（",
            )
        ),
        "D3 map exposes element, medium, sample type, method scope, confidence and anomaly filters",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'id="region"',
                'id="customBounds"',
                'id="mapMode"',
                'id="colorMode"',
                'id="basis"',
                'id="anomalyGrid"',
            )
        ),
        "D3 map exposes region, bbox, distribution/heat and color-mode controls",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'id="comboX"',
                'id="comboY"',
                'id="comboRegionSelect"',
                'id="comboCustomBounds"',
                'id="applyComboBounds"',
                'id="exportComparisonProfile"',
                "comparisonProfile",
                "导出可复现配置",
                "applyCustomBounds",
                'id="comboMatrix"',
                'id="comboUniverse"',
                'id="openAnomalyRegions"',
                "d3-domain-confidence-atlas-v5",
                'id="projectionMode"',
                'id="globe"',
                "drawGlobe",
                "polarClosure=dateLineJump",
                'id="databaseDistributionCanvas"',
                'id="databaseCoverageMatrix"',
                'id="databaseBoxCanvas"',
                "d3-database-visual-summary-v1",
                'id="anomalyDensityCanvas"',
                "drawAnomalyDensity",
                "gridLocations",
                'section.style.display=statisticalRegionFeatures.length?"block":"none"',
                "样点密度热力图",
                "showAnomalyRegion",
                "returnToAnomalyRegion",
                "focusAnomalyRegion",
                "zoom-adaptive-anomaly-bubbles-v1",
                "layoutAnomalyBubbles",
                "conic-gradient",
                'id="taskContext"',
                "atlas-progressive-disclosure-v2",
                "d3-visual-question-contract-v1",
                "competition-geochemistry-v1",
                "可交互元素分布地图",
                "标准化地球化学数据库",
                "元素组合对比",
                "数据来源与置信度说明",
                "异常区域识别结果",
                'id="zoomIn"',
                "comboQuadrants",
                "d3-visualization-profile-v2",
                'id="boundaries-data"',
                "pointInCountry",
                "发布方未报告分析方法",
                "来源声明坐标不确定度",
                "坐标表达分辨率（非位置精度）",
                "官方来源 / DOI",
                "记录级文件定位",
                "officialSourceLinks",
                "CTX.sources_and_confidence?.sources",
                "完整数据库测定",
                "逐记录官方链接 / DOI",
                "该结果比较同类样品的统计背景",
                "renderPoints(true)",
                'id="modeExplainer"',
                "map_preview_sampling",
                "覆盖保持预览",
                'id="admin1-boundaries-data"',
                "中国省级参考线",
                "Natural Earth 1:50m Admin‑1",
                "renderAdmin1Boundaries",
                "zoom-aware-pixel-lod-v1",
                "数据缺口与处理状态",
                "标准化样品类型（Skill 控制词）",
                "发布方样品描述",
                "record ID（点击展开）",
                "综合工作流可用性（非概率）",
                "空间匹配地质单元",
                "发布方地质 / 沉积背景",
                "地质 / 环境背景",
            )
        ),
        "D3 implements element combinations, density heatmap and zoom-adaptive clickable anomaly regions",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'const PLANAR_WORLD_POLICY="single-world-no-repeat-v1"',
                "function clampPlanarView()",
                "clampPlanarView();renderBasemap()",
                "world_wrap_policy:REGIONAL_SCOPE?null:PLANAR_WORLD_POLICY",
                'activeRegionKey==="global"?0',
            )
        )
        and "current*factor>maxSpan?1:factor" in html,
        "D3 planar world map clamps zoom and pan to one non-repeating world",
        checks,
    )
    require(
        'id="storyPreset"' not in html
        and html.count('class="tabs"') == 1
        and html.count('class="deliverable-center"') == 1,
        "D3 keeps one primary navigation and no duplicate task selector",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'id="geology"',
                'id="method"',
                'id="source"',
                "GEOCHEM ATLAS",
                "ALL DATA",
            )
        ),
        "D3 map exposes global, geological, method and source exploration controls",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'id="deliverableCenter"',
                'id="databaseView"',
                'id="databaseSearch"',
                'id="databaseTableBody"',
                'id="confidenceSummary"',
                'id="sourcePortfolioSummary"',
                'id="confidenceComponents"',
                'id="confidenceGateReasons"',
                "renderDatabase",
                "renderConfidence",
                'href="geochemistry.csv"',
                'href="confidence_report.json"',
                'href="sources_and_confidence.json"',
                'href="source_manifest.json"',
                'id="databaseDistributionCanvas"',
                'id="databaseCoverageMatrix"',
                'id="databaseBoxCanvas"',
                "不是正确概率",
            )
        ),
        "D3 exposes the standardized database and confidence explanation as first-class deliverables",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                "来源证据画像（不是空间工作流评分）",
                "工作流可用性 / 复核级别",
                "当前工作流需补证",
                "发布方未声明 datum / CRS；D2 按证据边界不推测（非处理错误）",
                "发布方未报告位置不确定度；不代表坐标无效或处理失败",
            )
        )
        and "全数据库整体工作流分布" not in html,
        "D3 publishes explicit overall workflow confidence without relabeling it as database quality",
        checks,
    )
    require(
        all(
            marker in html
            for marker in (
                'id="backView"',
                "rememberView",
                "canvas.onpointerdown=event=>{drag=",
                "basisLabel",
                "全部测量基准",
                'id="databaseEditor"',
                "geochemistry-research-patch-v1",
                'id="sourceTableBody"',
                'id="anomalyInspector"',
                "anomaly-contrast",
                "comboConclusion",
            )
        ),
        "D3 exposes recoverable navigation and research-grade database, evidence, anomaly and combination workbenches",
        checks,
    )
    iteration_rows = csv_rows(output_dir / "iteration_backlog.csv")
    require(
        bool(iteration_rows)
        and all(row["stage_owner"] in {"D1", "D2"} for row in iteration_rows)
        and all(
            row["status"] in {"action_required", "review_required", "scientific_limit"}
            for row in iteration_rows
        )
        and any(
            row["issue_code"] == "CENSORED_OBSERVATION"
            and row["status"] == "scientific_limit"
            and row["auto_recheck"] == "false"
            for row in iteration_rows
        ),
        "D3 iteration backlog routes D1/D2 gaps and keeps censored observations as non-imputed scientific limits",
        checks,
    )
    require(
        "选择单个元素后显示可比浓度色带" in html and "灰色：其他方法或测量基准" in html,
        "D3 defaults to a scientifically valid all-data sample overview",
        checks,
    )
    require(
        "Natural Earth 1:110m" in html
        and "ai4s-natural-earth-land-v1" in html
        and "ai4s-natural-earth-admin0-v1" in html
        and "ai4s-natural-earth-admin1-china-visual-v1" in html
        and "public domain" in html,
        "D3 embeds pinned offline land, country and optional China Admin-1 visual boundaries with visible provenance",
        checks,
    )
    require(
        "候选异常不代表污染" in html,
        "D3 map communicates the scientific interpretation boundary",
        checks,
    )
    summary = json_value(output_dir / "run_summary.json")
    require(
        summary.get("status") == "partial_success",
        "D3 run summary exposes incomplete map/background coverage instead of overstating success",
        checks,
    )
    require(
        set(summary.get("outputs", {}).values())
        == required_outputs - {"run_summary.json"},
        "D3 summary names every reusable artifact",
        checks,
    )
    map_report = summary.get("map_report", {})
    preview_input = [
        {
            "record_id": f"preview-{sample_index}-{element}",
            "sample_id": f"preview-sample-{sample_index}",
            "source_id": f"source-{sample_index % 3}",
            "medium": "soil" if sample_index % 2 == 0 else "sediment",
            "element": element,
            "longitude": -175.0 + (sample_index % 70) * 5.0,
            "latitude": -70.0 + (sample_index % 28) * 5.0,
        }
        for sample_index in range(120)
        for element in ("As", "Cu")
    ]
    preview_anomalies = {"preview-7-As", "preview-83-Cu"}
    preview_rows, preview_report = map_builder.coverage_preserving_map_preview(
        preview_input, preview_anomalies, 60
    )
    repeated_preview_rows, repeated_preview_report = (
        map_builder.coverage_preserving_map_preview(
            preview_input, preview_anomalies, 60
        )
    )
    preview_ids = {str(row["record_id"]) for row in preview_rows}
    preview_sample_counts = Counter(row["sample_id"] for row in preview_rows)
    require(
        preview_report["applied"] is True
        and len(preview_rows) <= 60
        and preview_report == repeated_preview_report
        and [row["record_id"] for row in preview_rows]
        == [row["record_id"] for row in repeated_preview_rows]
        and preview_anomalies.issubset(preview_ids)
        and set(preview_sample_counts.values()) == {2}
        and {(row["source_id"], row["medium"], row["element"]) for row in preview_rows}
        == {(row["source_id"], row["medium"], row["element"]) for row in preview_input},
        "D3 large-atlas preview is deterministic, bounded, anomaly-preserving, dimension-stratified and never splits a physical sample",
        checks,
    )
    require(
        map_report.get("map_version") == "d3-interactive-atlas-v3"
        and map_report.get("map_preview_sampling", {}).get("policy_version")
        == "d3-coverage-preserving-preview-v1"
        and map_report.get("scope_mappable_record_count")
        == map_report.get("mapped_record_count")
        and map_report.get("default_view") == "all_data_sample_deduplicated"
        and map_report.get("embedded_payload_schema") == "d3-compact-payload-v1"
        and map_report.get("anomaly_region_render_mode")
        == "zoom-adaptive-anomaly-bubbles-v1"
        and map_report.get("visualization_profile", {}).get("schema_version")
        == "d3-visualization-profile-v2"
        and map_report.get("spatial_scope", {}).get("mode") == "global"
        and map_report.get("spatial_scope", {}).get("output_clipped") is False
        and map_report.get("scope_excluded_mappable_record_count") == 0
        and isinstance(map_report.get("visualization_profile_warnings"), list)
        and {
            "distribution_points",
            "sample_density_heatmap",
            "element_pair_comparison",
            "candidate_anomaly_region_aggregation",
            "fdr_screened_candidate_anomaly_regions",
            "interactive_orthographic_globe",
            "classified_concentration_points",
            "database_concentration_histogram",
            "database_element_medium_coverage_matrix",
            "database_field_completeness",
            "anomaly_candidate_density_surface",
        }.issubset(set(map_report.get("visualization_modes", [])))
        and map_report.get("external_assets") == 0
        and map_report.get("interpolation") is False
        and map_builder.DEFAULT_MAX_EMBEDDED_RECORDS == 200_000
        and map_report.get("admin1_boundary_asset", {}).get("asset_version")
        == "ai4s-natural-earth-admin1-china-visual-v1"
        and map_report.get("admin1_boundary_asset", {}).get("boundary_count") == 31
        and map_report.get("admin1_boundary_asset", {}).get("license")
        == "public domain"
        and all(
            map_report.get("capability_matrix", {})
            .get("filter_dimensions", {})
            .values()
        )
        and all(map_report.get("capability_matrix", {}).get("outputs", {}).values())
        and all(
            map_report.get("capability_matrix", {}).get("deliverables", {}).values()
        )
        and map_report.get("ui_hierarchy_version") == "atlas-progressive-disclosure-v2"
        and map_report.get("template_contract_version")
        == "d3-domain-confidence-atlas-v5"
        and map_report.get("template_variant") == "global_globe"
        and map_report.get("database_visual_summary_schema")
        == "d3-database-visual-summary-v1"
        and map_report.get("template_sha256")
        == sha256_file(SKILL_DIR / "assets" / "interactive-atlas-v3.html")
        and map_report.get("terminology_contract") == "competition-geochemistry-v1"
        and map_report.get("visual_question_contract", {}).get("schema_version")
        == "d3-visual-question-contract-v1"
        and set(map_report.get("visual_question_contract", {}).get("views", {}))
        == {"map", "database", "combination", "sources", "anomalies", "quality"}
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("single_primary_navigation")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("professional_navigation_labels")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("combination_region_selector")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("combination_custom_bbox")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("regional_combination_scope_lock_supported")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("comparison_profile_export")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("formal_comparison_requires_profile_rerender")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("single_world_no_repeat_planar_navigation")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("advanced_filters_progressive_disclosure")
        is True
        and map_report.get("capability_matrix", {})
        .get("interaction_design", {})
        .get("duplicate_story_selector")
        is False
        and map_report.get("capability_matrix", {})
        .get("scientific_semantics", {})
        .get("heatmap_interpolates_concentration")
        is False
        and map_report.get("data_coverage_diagnostics", {}).get("sample_type_field")
        == "medium"
        and sum(
            map_report.get("data_coverage_diagnostics", {})
            .get("evidence_layer_counts", {})
            .values()
        )
        == map_report.get("scope_mappable_record_count"),
        "D3 run summary declares the reusable map contract and default view",
        checks,
    )
    require(
        0 < map_report.get("html_bytes", 0) <= 100_000_000
        and 0 < map_report.get("samples_geojson_bytes", 0) <= 100_000_000,
        "D3 reports and enforces the runtime map-output safety ceiling",
        checks,
    )
    coverage = map_report.get("region_coverage", {})
    require(
        coverage.get("global", {}).get("record_count")
        == map_report.get("mapped_record_count")
        and coverage.get("global", {}).get("sample_count")
        == map_report.get("display_sample_count")
        and all(
            coverage.get(key, {}).get("administrative_clip") is True
            for key in ("china", "usa", "usa48", "australia")
        )
        and all(
            coverage.get(key, {}).get("administrative_clip") is False
            for key in ("global", "shanghai", "europe")
        ),
        "D3 region coverage reconciles totals and distinguishes strict country clips from bbox scopes",
        checks,
    )
    basemap = json_value(BASEMAP)
    require(
        basemap.get("license") == "public domain"
        and basemap.get("archive_sha256")
        == "1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de"
        and basemap.get("point_count") == 5_133,
        "D3 basemap provenance, source archive hash and geometry count are pinned",
        checks,
    )
    boundaries = json_value(COUNTRY_BOUNDARIES)
    require(
        boundaries.get("asset_version") == "ai4s-natural-earth-admin0-v1"
        and boundaries.get("license") == "public domain"
        and boundaries.get("source_sha256")
        == "6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f"
        and boundaries.get("country_count") == 177
        and boundaries.get("point_count") == 10_654,
        "D3 country boundary provenance and geometry counts are pinned",
        checks,
    )
    loaded_boundaries = map_builder.load_country_boundaries(COUNTRY_BOUNDARIES)
    country_index = {
        country["iso_a3"]: country for country in loaded_boundaries["countries"]
    }
    require(
        map_builder.point_in_country(116.4074, 39.9042, country_index["CHN"])
        and not map_builder.point_in_country(139.6917, 35.6895, country_index["CHN"]),
        "D3 strict China polygon includes Beijing and excludes Tokyo",
        checks,
    )
    profile = json_value(VISUALIZATION_PROFILE)
    regional_profile = json_value(REGIONAL_VISUALIZATION_PROFILE)
    regional_comparison_profile = json_value(REGIONAL_COMPARISON_PROFILE)
    profile_schema = json_value(VISUALIZATION_PROFILE_SCHEMA)
    visualization_report_schema = json_value(VISUALIZATION_REPORT_SCHEMA)
    require(
        profile.get("schema_version") == "d3-visualization-profile-v2"
        and profile.get("spatial_scope") == "global"
        and profile_schema.get("properties", {}).get("schema_version", {}).get("const")
        == "d3-visualization-profile-v2"
        and set(
            profile_schema.get("properties", {})
            .get("spatial_scope", {})
            .get("enum", [])
        )
        == {"global", "regional"}
        and set(profile_schema.get("properties", {}).get("story", {}).get("enum", []))
        == {"overview", "coverage", "anomaly", "comparison", "database", "evidence"}
        and visualization_report_schema.get("properties", {})
        .get("interface_version", {})
        .get("const")
        == "d3-visualization-interface-v1",
        "D3 publishes a versioned task profile template and Schema",
        checks,
    )
    require(
        regional_profile.get("schema_version") == "d3-visualization-profile-v2"
        and regional_profile.get("spatial_scope") == "regional"
        and regional_profile.get("default_region") == "shanghai"
        and regional_profile.get("custom_region") is None,
        "D3 publishes a distinct city-ready regional product template",
        checks,
    )
    require(
        map_builder.load_visualization_profile(REGIONAL_COMPARISON_PROFILE)
        == regional_comparison_profile
        and regional_comparison_profile.get("story") == "comparison"
        and regional_comparison_profile.get("spatial_scope") == "regional"
        and regional_comparison_profile.get("default_region") == "china"
        and regional_comparison_profile.get("comparison")
        == {"x": "Cu", "y": "Pb", "medium": "soil"},
        "D3 publishes a validated regional element-comparison template",
        checks,
    )
    with tempfile.TemporaryDirectory() as question_matrix_temp:
        question_root = Path(question_matrix_temp)
        question_cases = (
            ("global-overview", "overview", ["--story", "overview"]),
            (
                "filtered-coverage",
                "coverage",
                [
                    "--story",
                    "coverage",
                    "--element",
                    "Cu",
                    "--medium",
                    "soil",
                    "--sample-type",
                    "soil_topsoil",
                    "--method-scope",
                    "observation",
                ],
            ),
            (
                "custom-region-anomaly",
                "anomaly",
                [
                    "--story",
                    "anomaly",
                    "--spatial-scope",
                    "regional",
                    "--region",
                    "custom",
                    "--bbox",
                    "-75",
                    "-56",
                    "-66",
                    "-17",
                    "--region-label",
                    "智利研究框",
                    "--element",
                    "Cu",
                    "--geology",
                    "Andes",
                ],
            ),
            (
                "element-comparison",
                "comparison",
                [
                    "--story",
                    "comparison",
                    "--comparison-x",
                    "As",
                    "--comparison-y",
                    "Pb",
                    "--comparison-medium",
                    "soil",
                ],
            ),
            (
                "custom-region-comparison",
                "comparison",
                [
                    "--story",
                    "comparison",
                    "--spatial-scope",
                    "regional",
                    "--region",
                    "custom",
                    "--bbox",
                    "100",
                    "30",
                    "110",
                    "40",
                    "--region-label",
                    "西北研究框",
                    "--comparison-x",
                    "As",
                    "--comparison-y",
                    "Pb",
                    "--comparison-medium",
                    "soil",
                ],
            ),
            ("database-audit", "database", ["--story", "database"]),
            (
                "source-evidence",
                "evidence",
                ["--story", "evidence", "--source", "demo-source"],
            ),
            (
                "named-country-overview",
                "overview",
                [
                    "--story",
                    "overview",
                    "--spatial-scope",
                    "regional",
                    "--region",
                    "Japan",
                ],
            ),
            (
                "antimeridian-coverage",
                "coverage",
                [
                    "--story",
                    "coverage",
                    "--spatial-scope",
                    "regional",
                    "--region",
                    "custom",
                    "--bbox",
                    "170",
                    "-20",
                    "-170",
                    "20",
                    "--region-label",
                    "日期变更线研究框",
                ],
            ),
        )
        generated_profiles = []
        for case_name, expected_story, case_args in question_cases:
            profile_path = question_root / f"{case_name}.json"
            run_command(
                [
                    sys.executable,
                    str(VISUALIZATION_PROFILE_CREATOR),
                    "--output",
                    str(profile_path),
                    *case_args,
                ]
            )
            generated_profile = map_builder.load_visualization_profile(profile_path)
            bundle = question_root / f"{case_name}-bundle"
            run_command(
                [
                    sys.executable,
                    str(VISUALIZATION_RENDERER),
                    "--input-dir",
                    str(output_dir),
                    "--profile",
                    str(profile_path),
                    "--output-dir",
                    str(bundle),
                ]
            )
            generated_report = json_value(bundle / "visualization_report.json")
            require(
                generated_profile.get("story") == expected_story
                and generated_profile.get("title", "").endswith("地球化学元素图谱")
                and generated_report.get("profile") == generated_profile
                and visualization_status_ok(
                    visualization_validator.validate_dir(bundle)
                ),
                f"D3 question profile reproduces the {case_name} task without HTML edits",
                checks,
            )
            if expected_story == "comparison":
                comparison_report = json_value(bundle / "element_comparison.json")
                require(
                    comparison_report.get("comparison_version")
                    == "d3-element-comparison-v1"
                    and comparison_report.get("elements")
                    == {
                        "x": generated_profile["comparison"]["x"],
                        "y": generated_profile["comparison"]["y"],
                    }
                    and comparison_report.get("input_sha256")
                    == sha256_file(output_dir / "geochemistry.csv")
                    and generated_report.get("element_comparison") == comparison_report
                    and generated_report.get("outputs", {}).get("element_comparison")
                    == "element_comparison.json",
                    f"D3 {case_name} emits a hash-bound structured same-sample comparison report",
                    checks,
                )
            if generated_profile.get("filters", {}).get("element"):
                concentration_grid = json_value(bundle / "concentration_grid.geojson")
                grid_features = concentration_grid.get("features", [])
                require(
                    concentration_grid.get("grid_version")
                    == "d3-observed-concentration-grid-v1"
                    and concentration_grid.get("element")
                    == generated_profile["filters"]["element"]
                    and concentration_grid.get("interpolation") is False
                    and concentration_grid.get("feature_count") == len(grid_features)
                    and all(
                        feature.get("properties", {}).get("aggregation")
                        == "observed_records_only_no_interpolation"
                        and "censored_fraction" in feature.get("properties", {})
                        and "physical_sample_count" in feature.get("properties", {})
                        for feature in grid_features
                    )
                    and generated_report.get("outputs", {}).get("concentration_grid")
                    == "concentration_grid.geojson",
                    f"D3 {case_name} emits a non-interpolated observed-cell concentration grid",
                    checks,
                )
                if grid_features:
                    grid_path = bundle / "concentration_grid.geojson"
                    original_grid = grid_path.read_text(encoding="utf-8")
                    tampered_grid = copy.deepcopy(concentration_grid)
                    tampered_grid["features"][0]["properties"]["quantified_count"] = (
                        True
                    )
                    try:
                        grid_path.write_text(
                            json.dumps(tampered_grid, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        tampered_validation = visualization_validator.validate_dir(
                            bundle
                        )
                    finally:
                        grid_path.write_text(original_grid, encoding="utf-8")
                    require(
                        tampered_validation["status"] == "invalid"
                        and "concentration grid feature counts do not reconcile"
                        in tampered_validation["errors"],
                        "D3 rejects boolean values in concentration-grid count fields",
                        checks,
                    )
            generated_profiles.append(generated_profile)
        custom_profile = generated_profiles[2]
        custom_comparison_profile = generated_profiles[4]
        require(
            comparison_builder._spearman([1.0] * 7, [1.0] * 7) is None,
            "D3 element comparison withholds Spearman below eight comparable pairs",
            checks,
        )
        stale_bundle = question_root / "element-comparison-bundle"
        run_command(
            [
                sys.executable,
                str(VISUALIZATION_RENDERER),
                "--input-dir",
                str(output_dir),
                "--profile",
                str(question_root / "global-overview.json"),
                "--output-dir",
                str(stale_bundle),
                "--force",
            ]
        )
        require(
            not (stale_bundle / "element_comparison.json").exists()
            and not (stale_bundle / "concentration_grid.geojson").exists()
            and visualization_status_ok(
                visualization_validator.validate_dir(stale_bundle)
            ),
            "D3 force rerender removes structured artifacts not triggered by the new profile",
            checks,
        )
        require(
            generated_profiles[1].get("filters", {}).get("sample_type")
            == "soil_topsoil"
            and generated_profiles[1].get("filters", {}).get("method_scope")
            == "observation"
            and custom_profile.get("default_region") == "custom"
            and custom_profile.get("custom_region", {}).get("label") == "智利研究框"
            and custom_profile.get("custom_region", {}).get("bounds")
            == {"w": -75.0, "s": -56.0, "e": -66.0, "n": -17.0}
            and custom_comparison_profile.get("spatial_scope") == "regional"
            and custom_comparison_profile.get("default_region") == "custom"
            and custom_comparison_profile.get("custom_region", {}).get("bounds")
            == {"w": 100.0, "s": 30.0, "e": 110.0, "n": 40.0}
            and custom_comparison_profile.get("comparison")
            == {"x": "As", "y": "Pb", "medium": "soil"}
            and {profile_value.get("story") for profile_value in generated_profiles}
            == {
                "overview",
                "coverage",
                "anomaly",
                "comparison",
                "database",
                "evidence",
            },
            "D3 question matrix covers six stories and reproducible arbitrary regional comparison profiles",
            checks,
        )
        require(
            generated_profiles[-2].get("custom_region", {}).get("country_code") == "JPN"
            and generated_profiles[-2].get("default_region") == "custom"
            and generated_profiles[-1].get("custom_region", {}).get("bounds")
            == {"w": 170.0, "s": -20.0, "e": -170.0, "n": 20.0}
            and map_builder.coordinate_in_bounds(
                179.0, 0.0, generated_profiles[-1]["custom_region"]["bounds"]
            )
            and map_builder.coordinate_in_bounds(
                -179.0, 0.0, generated_profiles[-1]["custom_region"]["bounds"]
            )
            and not map_builder.coordinate_in_bounds(
                0.0, 0.0, generated_profiles[-1]["custom_region"]["bounds"]
            ),
            "D3 profiles support every frozen country and wrapped antimeridian clipping",
            checks,
        )
        invalid_question_profile = question_root / "invalid-question.json"
        run_command(
            [
                sys.executable,
                str(VISUALIZATION_PROFILE_CREATOR),
                "--output",
                str(invalid_question_profile),
                "--story",
                "comparison",
                "--comparison-x",
                "As",
            ],
            expected_code=2,
        )
        require(
            not invalid_question_profile.exists(),
            "D3 profile creator fails closed on an incomplete comparison question",
            checks,
        )
    with tempfile.TemporaryDirectory() as visualization_temp:
        visualization_root = Path(visualization_temp)
        task_profile = dict(profile)
        task_profile["title"] = "中国 As 土壤候选异常任务视图"
        task_profile["story"] = "anomaly"
        task_profile["spatial_scope"] = "regional"
        task_profile["default_region"] = "china"
        task_profile["filters"] = {
            **profile["filters"],
            "element": "As",
            "medium": "soil",
        }
        task_profile_path = visualization_root / "task-profile.json"
        task_profile_path.write_text(
            json.dumps(task_profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        visualization_output = visualization_root / "bundle"
        run_command(
            [
                sys.executable,
                str(VISUALIZATION_RENDERER),
                "--input-dir",
                str(output_dir),
                "--profile",
                str(task_profile_path),
                "--output-dir",
                str(visualization_output),
            ]
        )
        visualization_report = json_value(
            visualization_output / "visualization_report.json"
        )
        configured_html = (visualization_output / "interactive_map.html").read_text(
            encoding="utf-8"
        )
        scoped_geojson = json_value(visualization_output / "samples.geojson")
        scoped_features = scoped_geojson.get("features", [])
        scoped_report = visualization_report.get("map_report", {}).get(
            "spatial_scope", {}
        )
        require(
            visualization_report.get("status") == "success"
            and visualization_report.get("interface_version")
            == "d3-visualization-interface-v1"
            and visualization_report.get("profile", {}).get("story") == "anomaly"
            and visualization_report.get("profile", {})
            .get("filters", {})
            .get("element")
            == "As"
            and visualization_report.get("profile", {}).get("spatial_scope")
            == "regional"
            and visualization_report.get("map_report", {}).get("default_view")
            == "regional_scope_task_view"
            and scoped_report.get("region_key") == "china"
            and scoped_report.get("country_code") == "CHN"
            and scoped_report.get("clip_method") == "country_polygon_and_bbox"
            and scoped_report.get("output_clipped") is True
            and "中国 As 土壤候选异常任务视图" in configured_html
            and "REGIONAL OUTPUT" in configured_html,
            "D3 Agent entry point renders a locked regional task map without editing HTML",
            checks,
        )
        require(
            len(scoped_features)
            == visualization_report.get("map_report", {}).get("mapped_record_count")
            and scoped_geojson.get("spatial_scope", {}).get("mode") == "regional"
            and scoped_geojson.get("spatial_scope", {}).get("output_clipped") is True
            and all(
                map_builder.point_in_country(
                    feature["geometry"]["coordinates"][0],
                    feature["geometry"]["coordinates"][1],
                    country_index["CHN"],
                )
                for feature in scoped_features
            ),
            "D3 regional GeoJSON contains only records inside the configured country polygon",
            checks,
        )
        city_output = visualization_root / "city-bundle"
        run_command(
            [
                sys.executable,
                str(VISUALIZATION_RENDERER),
                "--input-dir",
                str(output_dir),
                "--profile",
                str(REGIONAL_VISUALIZATION_PROFILE),
                "--output-dir",
                str(city_output),
            ]
        )
        city_report = json_value(city_output / "visualization_report.json")
        city_geojson = json_value(city_output / "samples.geojson")
        require(
            city_report.get("map_report", {}).get("spatial_scope", {}).get("region_key")
            == "shanghai"
            and city_report.get("map_report", {}).get("mapped_record_count") == 0
            and city_report.get("map_report", {}).get(
                "scope_excluded_mappable_record_count"
            )
            == city_report.get("map_report", {}).get("source_mappable_record_count")
            and city_geojson.get("features") == []
            and any(
                "覆盖缺口" in warning
                for warning in city_report.get("profile_warnings", [])
            ),
            "D3 city template keeps an empty regional result instead of falling back to a world map",
            checks,
        )
        invalid_profile = dict(profile)
        invalid_profile["spatial_scope"] = "regional"
        invalid_profile_path = visualization_root / "invalid-profile.json"
        invalid_profile_path.write_text(
            json.dumps(invalid_profile, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        invalid_output = visualization_root / "invalid-bundle"
        run_command(
            [
                sys.executable,
                str(VISUALIZATION_RENDERER),
                "--input-dir",
                str(output_dir),
                "--profile",
                str(invalid_profile_path),
                "--output-dir",
                str(invalid_output),
            ],
            expected_code=2,
        )
        require(
            json_value(invalid_output / "visualization_report.json").get("status")
            == "invalid_input",
            "D3 fails closed when regional scope is paired with the global region",
            checks,
        )
        require(
            all(
                visualization_status_ok(visualization_validator.validate_dir(path))
                for path in (visualization_output, city_output)
            ),
            "D3 global and regional standalone bundles pass the dedicated public validator",
            checks,
        )
    with tempfile.TemporaryDirectory(prefix="country-geology-request-") as request_temp:
        request_root = Path(request_temp)
        bounded_request = json_value(PRODUCTION_REQUEST)
        bounded_request["region"] = "USA"
        bounded_request["geology_units"] = ["GLiM:1:su"]
        bounded_request["geology_match"] = "matched"
        bounded_request_path = request_root / "request.json"
        bounded_request_path.write_text(
            json.dumps(bounded_request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        bounded_output = request_root / "output"
        run_command(
            [
                sys.executable,
                str(REQUEST_RUNNER),
                "--request",
                str(bounded_request_path),
                "--demo",
                "production-usgs",
                "--analysis-profile",
                "production",
                "--generated-at",
                "2026-08-07T00:00:00Z",
                "--output-dir",
                str(bounded_output),
            ]
        )
        bounded_rows = csv_rows(bounded_output / "geochemistry.csv")
        bounded_samples = json_value(bounded_output / "samples.geojson")
        bounded_execution = json_value(
            bounded_output / "request_evidence" / "execution.json"
        )
        require(
            bool(bounded_rows)
            and {row["matched_geologic_unit"] for row in bounded_rows} == {"GLiM:1:su"}
            and len(bounded_samples["features"]) == len(bounded_rows)
            and all(
                map_builder.point_in_country(
                    feature["geometry"]["coordinates"][0],
                    feature["geometry"]["coordinates"][1],
                    country_index["USA"],
                )
                for feature in bounded_samples["features"]
            )
            and bounded_execution["record_counts"]["after_request_filters"]
            == len(bounded_rows)
            and output_validator.validate_dir(bounded_output)["status"] == "valid",
            "D3 public runner completes a named-country plus matched-geology request with consistent outputs",
            checks,
        )
    with tempfile.TemporaryDirectory(prefix="china-request-") as china_temp:
        china_root = Path(china_temp)
        china_fixture = SKILL_DIR / "fixtures" / "china" / "combined-v1"
        china_output = china_root / "output"
        run_command(
            [
                sys.executable,
                str(REQUEST_RUNNER),
                "--request",
                str(china_fixture / "request.json"),
                "--demo",
                "china",
                "--coordinate-mode",
                "reported",
                "--analysis-profile",
                "production",
                "--generated-at",
                "2026-08-08T00:00:00Z",
                "--output-dir",
                str(china_output),
            ]
        )
        china_summary = json_value(china_output / "run_summary.json")
        china_statistics = china_summary["map_report"]["coordinate_statistics"]
        china_html = (china_output / "interactive_map.html").read_text(encoding="utf-8")
        require(
            china_summary["status"] == "partial_success"
            and china_statistics["mapped_reported_fallback_records"] == 2400
            and china_statistics["mapped_canonical_records"] == 0
            and china_statistics["records_without_plottable_coordinates"] == 558
            and map_builder.REPORTED_BANNER_PHRASE in china_html
            and any("unverified datum" in item for item in china_summary["limitations"])
            and output_validator.validate_dir(china_output)["status"] == "valid",
            "D3 China fixture request maps reported coordinates with the warning banner and full artifacts",
            checks,
        )
        china_fixture_files = [
            china_fixture / "demo_input.csv",
            china_fixture / "sources.jsonl",
        ]
        require(
            all(path.stat().st_size <= 5_000_000 for path in china_fixture_files),
            "D3 bundled China demo keeps every data fixture within the 5 MB submission-safe target",
            checks,
        )
        validator_script = SCRIPT_DIR / "validate_visualization.py"
        no_browser_environment = {**os.environ, "GGA_HEADLESS_BROWSER": ""}
        no_browser = subprocess.run(
            [
                sys.executable,
                str(validator_script),
                "--html",
                str(china_output / "interactive_map.html"),
            ],
            capture_output=True,
            text=True,
            check=False,
            env=no_browser_environment,
        )
        no_browser_report = json.loads(no_browser.stdout)
        require(
            no_browser.returncode == 3
            and no_browser_report["status"] == "needs_render_confirmation"
            and no_browser_report["render_smoke"]["status"] == "skipped_no_browser",
            "D3 render smoke reports an explicit skip and exit code 3 without a browser",
            checks,
        )
        if visualization_validator.find_headless_browser():
            reported_gate = subprocess.run(
                [
                    sys.executable,
                    str(validator_script),
                    "--html",
                    str(china_output / "interactive_map.html"),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            reported_report = json.loads(reported_gate.stdout)
            reported_smoke = reported_report["render_smoke"]
            require(
                reported_gate.returncode == 0
                and reported_smoke["status"] == "pass"
                and reported_smoke["dom"]["banner_present"] is True
                and not reported_smoke["console_uncaught_errors"]
                and reported_smoke["dom"]["render_attest"].get("spatial_scope")
                == "regional"
                and reported_smoke["dom"]["render_attest"].get(
                    "planar_navigation_policy"
                )
                == "regional-bounded-antimeridian-v1"
                and (
                    reported_smoke["dom"]["svg_graphic_elements"] > 0
                    or (
                        reported_smoke["dom"]["canvas_elements"] > 0
                        and reported_smoke["dom"]["render_attest"].get("symbols", 0) > 0
                    )
                ),
                "D3 render smoke passes on the China reported-mode map in a real headless browser",
                checks,
            )
            broken_html = china_root / "broken.html"
            broken_html.write_text(
                "<!doctype html><html><head><script>throw new TypeError("
                "\"Cannot read properties of undefined (reading 'type')\");"
                "</script></head><body><svg></svg></body></html>",
                encoding="utf-8",
            )
            broken_gate = subprocess.run(
                [
                    sys.executable,
                    str(validator_script),
                    "--html",
                    str(broken_html),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            require(
                broken_gate.returncode == 1
                and json.loads(broken_gate.stdout)["render_smoke"]["status"] == "fail",
                "D3 render smoke fails closed on a blank map with an uncaught console error",
                checks,
            )
    return checks


CHECKERS: dict[str, Callable[[Path], list[str]]] = {
    "d1": check_d1,
    "d2": check_d2,
    "d3": check_d3,
}


def run_suite(component: str) -> dict[str, Any]:
    selected = tuple(CHECKERS) if component == "all" else (component,)
    with tempfile.TemporaryDirectory() as output_temp:
        output_dir = Path(output_temp)
        run_command(
            [
                sys.executable,
                str(WORKFLOW),
                "--input",
                str(DEMO_INPUT),
                "--output-dir",
                str(output_dir),
            ]
        )
        components: dict[str, Any] = {}
        for name in selected:
            checks = CHECKERS[name](output_dir)
            components[name.upper()] = {
                "status": "PASS",
                "checks": len(checks),
                "details": checks,
            }
    return {
        "status": "PASS",
        "selected": component,
        "total_checks": sum(item["checks"] for item in components.values()),
        "components": components,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("d1", "d2", "d3", "all"), default="all")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_suite(args.component)
    except (ContractError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {"status": "FAIL", "component": args.component, "error": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
