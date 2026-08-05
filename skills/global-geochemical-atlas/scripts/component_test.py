#!/usr/bin/env python3
"""Run the minimal D1/D2/D3 collaboration contracts against the bundled demo."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import urllib.error
import zipfile
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import build_evidence_bundle as evidence_builder
import download_data as downloader
import source_adapters as source_contracts
import standardize_geochemistry as standardizer
import validate_outputs as output_validator

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
DEMO_INPUT = SKILL_DIR / "fixtures" / "demo_input.csv"
SOURCE_DEMOS = SKILL_DIR / "fixtures" / "source-demos"
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
DOWNLOADER = SCRIPT_DIR / "download_data.py"
GENERATOR = SCRIPT_DIR / "generate_demo_data.py"


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


def run_command(arguments: list[str], expected_code: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=60)
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
    require(manifest.get("manifest_version") == "geochemical-source-manifest-v2", "D1 manifest version is stable", checks)
    require(manifest.get("input", {}).get("sha256") == input_hash, "D1 manifest binds the acquired input hash", checks)
    require(manifest.get("input", {}).get("record_count") == 19, "D1 manifest preserves the record count", checks)
    coverage = manifest.get("coverage", {})
    require(coverage.get("source_locator_rate") == 1.0, "D1 demo provenance coverage is complete", checks)
    require(coverage.get("declared_license_rate") == 1.0, "D1 demo license declarations are complete", checks)
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
    require(binding.get("sha256") == sha256_file(confidence_path), "D1 packages the unchanged D2 confidence hash", checks)
    require(binding.get("not_a_probability") is True, "D1 preserves the confidence interpretation boundary", checks)

    registry = source_contracts.load_source_registry()
    require(
        set(registry["sources"]) == {"georoc-archaean", "usgs-conus-soil"},
        "D1 registry freezes the two MVP public sources",
        checks,
    )
    georoc = source_contracts.registry_candidate("georoc-archaean")
    require(
        georoc.version == "12.0" and georoc.license_id == "CC-BY-SA-4.0",
        "D1 GEOROC candidate binds the verified version and license",
        checks,
    )
    usgs = source_contracts.registry_candidate("usgs-conus-soil")
    require(
        len(usgs.registry_entry["download"]["files"]) == 3,
        "D1 USGS candidate keeps the three soil layers distinct",
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

    for source_id in ("georoc-archaean", "usgs-conus-soil"):
        demo_dir = SOURCE_DEMOS / source_id
        demo_input = demo_dir / "demo_input.csv"
        sources_path = demo_dir / "sources.jsonl"
        generation_manifest = json_value(demo_dir / "run_manifest.json")
        demo_rows = csv_rows(demo_input)
        evidence_rows = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines()]
        expected_observations = 48 if source_id == "georoc-archaean" else 108
        expected_per_analyte = expected_observations // 4
        require(
            len(demo_rows) == expected_observations and len(evidence_rows) == expected_observations,
            f"D1 {source_id} fixture has one evidence record per observation",
            checks,
        )
        require(
            generation_manifest.get("data_mode") == "fixture"
            and generation_manifest.get("not_for_scientific_interpretation") is True,
            f"D1 {source_id} fixture declares the scientific claim boundary",
            checks,
        )
        expected_hashes = {item["path"]: item["sha256"] for item in generation_manifest["outputs"]}
        require(
            expected_hashes == {
                "demo_input.csv": sha256_file(demo_input),
                "sources.jsonl": sha256_file(sources_path),
            },
            f"D1 {source_id} fixture manifest binds deterministic output hashes",
            checks,
        )
        require(
            {row["record_id"] for row in demo_rows} == {row["record_id"] for row in evidence_rows}
            and {row["source_id"] for row in demo_rows} == {source_id},
            f"D1 {source_id} fixture preserves record-level evidence linkage",
            checks,
        )
        require(
            Counter(row["element_or_analyte"] for row in demo_rows)
            == Counter({item: expected_per_analyte for item in ("As", "Cu", "Ni", "Zn")}),
            f"D1 {source_id} fixture keeps the four analytes balanced",
            checks,
        )
        require(
            generation_manifest.get("demo_generation_version") == "d1-demo-slice-v2",
            f"D1 {source_id} fixture uses the evidence-complete generator contract",
            checks,
        )
    georoc_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "georoc-archaean" / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    ]
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
        ),
        "D1 GEOROC fixture retains reported coordinates without inventing WGS84",
        checks,
    )
    usgs_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "usgs-conus-soil" / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    require(
        {item.get("soil_layer") for item in usgs_evidence}
        == {"top-0-5cm", "a-horizon", "c-horizon"},
        "D1 USGS fixture keeps all three soil layers distinct",
        checks,
    )
    usgs_rows = csv_rows(SOURCE_DEMOS / "usgs-conus-soil" / "demo_input.csv")
    require(
        all(row["analytical_method"] and row["method_family"] and row["digestion_or_extraction"] for row in usgs_rows),
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

    with tempfile.TemporaryDirectory() as evidence_temp:
        bbox_result = run_command(
            [
                sys.executable,
                str(GENERATOR),
                "--source",
                "georoc-archaean",
                "--cache-dir",
                str(Path(evidence_temp) / "unused-cache"),
                "--output-dir",
                str(Path(evidence_temp) / "must-not-filter-georoc"),
                "--mode",
                "cached",
                "--bbox",
                "100,-10,120,10",
                "--generated-at",
                "2026-08-05T06:25:00Z",
            ],
            expected_code=2,
        )
        require(
            "does not declare a datum" in bbox_result.stderr,
            "D1 refuses WGS84 bbox filtering for GEOROC without datum evidence",
            checks,
        )

        standalone = Path(evidence_temp) / "source_manifest.json"
        evidence_builder.package_evidence(
            DEMO_INPUT, output_dir / "geochemistry.csv", confidence_path, standalone
        )
        require(standalone.read_bytes() == manifest_path.read_bytes(), "D1 standalone packaging matches D3 integration", checks)

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
            and verified_manifest["record_evidence"]["evidence_level"] == "verified_record_evidence",
            "D1 final manifest consumes and hash-binds the acquisition evidence sidecar",
            checks,
        )
        verified_summary = json_value(verified_output / "run_summary.json")
        require(
            verified_summary["input"]["not_for_scientific_interpretation"] is True
            and "not for scientific interpretation" in verified_summary["limitations"][0],
            "D3 propagates the fixture claim boundary into the final result",
            checks,
        )

        tampered_evidence_rows = [
            json.loads(line) for line in (usgs_demo / "sources.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        tampered_evidence_rows[0]["record_id"] = "rec-not-in-canonical-database"
        tampered_evidence = Path(evidence_temp) / "tampered-record-ids.jsonl"
        tampered_evidence.write_text(
            "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in tampered_evidence_rows),
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
            raise ContractError("D1 must reject sidecar record IDs that differ from the canonical database")
        checks.append("D1 rejects record-evidence additions, removals and record-ID substitutions")

        tampered_acquisition = json_value(usgs_demo / "run_manifest.json")
        tampered_acquisition["source_files"][0]["sha256"] = "0" * 64
        tampered_acquisition_path = Path(evidence_temp) / "tampered-acquisition.json"
        tampered_acquisition_path.write_text(json.dumps(tampered_acquisition), encoding="utf-8")
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
            raise ContractError("D1 must reject source-file hashes not present in the acquisition manifest")
        checks.append("D1 cross-checks every record source-file hash against acquired files")

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
            raise ContractError("D1 must reject a confidence report linked to a different input")
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
        require(not unsafe_output.exists(), "D1 downloader fails closed on unsafe URLs", checks)
        require(
            json_value(unsafe_manifest).get("status") == "invalid_input",
            "D1 downloader returns a structured invalid_input status",
            checks,
        )

        cached_file = Path(evidence_temp) / "cached.csv"
        cached_file.write_text("SiteID\tLatitude\tLongitude\nA\t1\t2\n", encoding="utf-8")
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
        require(cache_result["status"] == "cache_hit", "D1 reuses only a hash-verified versioned cache", checks)

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
                downloader.validate_response_metadata(content_type, declared_length, max_bytes=1000)
            except downloader.DownloadError as exc:
                require(
                    expected_message in str(exc),
                    f"D1 rejects {expected_message} response metadata",
                    checks,
                )
            else:
                raise ContractError(f"D1 must reject {expected_message} response metadata")

        try:
            downloader.copy_response_bounded(io.BytesIO(b"x" * 1001), io.BytesIO(), max_bytes=1000)
        except downloader.DownloadError as exc:
            require(
                "download exceeded" in str(exc),
                "D1 enforces the streaming size limit without trusting Content-Length",
                checks,
            )
        else:
            raise ContractError("D1 must enforce the streaming response size limit")

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
            retry_result.get("attempts") == 3 and attempts == [1, 2, 3] and delays == [1, 2],
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
            downloader.is_retryable_error(urllib.error.HTTPError(cached_url, 502, "Bad Gateway", None, None))
            and not downloader.is_retryable_error(urllib.error.HTTPError(cached_url, 500, "Error", None, None)),
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
            downloader._read_delimited_header(missing_field_file, ["Latitude", "Longitude"])
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
        require(not (Path(evidence_temp) / "escape.csv").exists(), "D1 rejects ZIP path traversal", checks)

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
    return checks


def check_d2(output_dir: Path) -> list[str]:
    checks: list[str] = []
    expected = {
        "geochemistry.csv",
        "qc_report.json",
        "confidence_report.json",
        "anomalies.geojson",
        "anomaly_report.json",
    }
    require(all((output_dir / name).is_file() for name in expected), "D2 publishes all five analytical artifacts", checks)
    rows = csv_rows(output_dir / "geochemistry.csv")
    require(len(rows) == 19, "D2 canonical database preserves all demo records", checks)
    require(
        {
            "source_record_id", "analyte_reported", "species_or_oxide", "source_qualifier_raw",
            "censored", "missing_reason", "method_family", "file_sha256",
        }
        .issubset(rows[0]),
        "D2 v2 database exposes provenance, censoring and method-family fields",
        checks,
    )
    indexed = {row["record_id"]: row for row in rows}
    require(float(indexed["rock-fe-001"]["normalized_value"]) == 25_000, "D2 solid unit conversion is stable", checks)
    require(indexed["soil-as-013"]["normalized_value"] == "", "D2 censored values are not imputed", checks)
    require(indexed["soil-as-013"]["censored"] == "true", "D2 serializes censoring state explicitly", checks)
    require(indexed["soil-as-001"]["method_family"] == "icp_ms", "D2 normalizes analytical method families", checks)
    require(
        "AMBIGUOUS_AQUEOUS_RATIO_UNIT" in indexed["water-as-ambiguous"]["qc_flags"],
        "D2 ambiguous aqueous units fail closed",
        checks,
    )
    require(
        indexed["swap-coord-001"]["latitude"] == "" and indexed["swap-coord-001"]["longitude"] == "",
        "D2 does not silently swap coordinates",
        checks,
    )
    duplicates = [row for row in rows if "DUPLICATE_CANDIDATE" in row["qc_flags"]]
    require(len(duplicates) == 2, "D2 retains and flags duplicate candidates", checks)
    confidence = json_value(output_dir / "confidence_report.json")
    require(confidence.get("confidence_version") == "d2-confidence-v2", "D2 confidence version is explicit", checks)
    require(
        set(confidence.get("weights", {})) == {"source", "completeness", "method", "spatial", "qc"},
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
    require(abs(sum(confidence["weights"].values()) - 1.0) < 1e-12, "D2 confidence weights sum to one", checks)
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
    require(anomaly_report.get("scientific_status") == "screening_baseline_only", "D2 anomaly boundary is explicit", checks)
    require(
        anomaly_report.get("minimum_quantified_fraction") == 0.70,
        "D2 anomaly screening declares the quantified-fraction gate",
        checks,
    )
    require(anomaly_report.get("candidate_count") == 1, "D2 demo anomaly result is stable", checks)
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
    crosswalk_schema = json_value(SKILL_DIR / "references" / "platform-field-crosswalk.schema.json")
    require(
        crosswalk_schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema",
        "D2 professional-platform crosswalk has a versioned JSON Schema",
        checks,
    )
    record_schema = json_value(SKILL_DIR / "references" / "geochemistry-record.schema.json")
    crosswalk = json_value(SKILL_DIR / "references" / "platform-field-crosswalk.json")
    require(
        crosswalk.get("status") == "semantic_alignment_not_conformance_claim"
        and crosswalk.get("canonical_schema", {}).get("schema_id") == record_schema.get("$id"),
        "D2 crosswalk declares semantic alignment without a false conformance claim",
        checks,
    )
    mapped_fields = [item["canonical_field"] for item in crosswalk["field_mappings"]]
    non_core_fields = [
        field
        for group in crosswalk["non_core_fields"]
        for field in group["fields"]
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
        and set(platform_ids) == {"earthchem_ecl", "usgs_agdb2", "odm2", "igsn_datacite"},
        "D2 crosswalk platform and evidence registries are unique and explicit",
        checks,
    )
    evidence_set = set(evidence_ids)
    platform_set = set(platform_ids)
    valid_mapping_types = {"exact", "renamed", "transformed", "composite", "no_direct_equivalent"}
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
                (mapping["mapping_type"] == "no_direct_equivalent" and not mapping["external_path"])
                or (mapping["mapping_type"] != "no_direct_equivalent" and bool(mapping["external_path"]))
            )
            for mapping in mapping_rows
        )
        and all(
            len({mapping["platform_id"] for mapping in field_mapping["platform_mappings"]})
            == len(field_mapping["platform_mappings"])
            for field_mapping in crosswalk["field_mappings"]
        )
        and all(set(platform["evidence_ids"]) <= evidence_set for platform in crosswalk["platforms"]),
        "D2 crosswalk mappings reference valid platforms, evidence and absence semantics",
        checks,
    )
    return checks


def check_d3(output_dir: Path) -> list[str]:
    checks: list[str] = []
    skill_dirs = [path for path in (REPO_ROOT / "skills").iterdir() if path.is_dir() and not path.name.startswith(".")]
    require(len(skill_dirs) == 1 and skill_dirs[0] == SKILL_DIR, "D3 keeps exactly one production Skill", checks)
    required_outputs = set(output_validator.REQUIRED_FILES.values())
    actual_outputs = {path.name for path in output_dir.iterdir() if path.is_file()}
    require(actual_outputs == required_outputs, "D3 publishes the stable ten-file output set", checks)
    validation = output_validator.validate_dir(output_dir)
    require(validation.get("status") == "valid", "D3 integrated outputs pass the public validator", checks)
    html = (output_dir / "interactive_map.html").read_text(encoding="utf-8")
    require("<script src=" not in html.casefold(), "D3 map is self-contained without external scripts", checks)
    require(
        all(marker in html for marker in ('id="element"', 'id="medium"', 'id="confidence"', 'id="anomalyOnly"')),
        "D3 map exposes element, medium, confidence and anomaly filters",
        checks,
    )
    require("候选异常不代表污染" in html, "D3 map communicates the scientific interpretation boundary", checks)
    summary = json_value(output_dir / "run_summary.json")
    require(summary.get("status") == "success", "D3 run summary reports successful integration", checks)
    require(set(summary.get("outputs", {}).values()) == required_outputs - {"run_summary.json"}, "D3 summary names every reusable artifact", checks)
    return checks


CHECKERS: dict[str, Callable[[Path], list[str]]] = {"d1": check_d1, "d2": check_d2, "d3": check_d3}


def run_suite(component: str) -> dict[str, Any]:
    selected = tuple(CHECKERS) if component == "all" else (component,)
    with tempfile.TemporaryDirectory() as output_temp:
        output_dir = Path(output_temp)
        run_command(
            [sys.executable, str(WORKFLOW), "--input", str(DEMO_INPUT), "--output-dir", str(output_dir)]
        )
        components: dict[str, Any] = {}
        for name in selected:
            checks = CHECKERS[name](output_dir)
            components[name.upper()] = {"status": "PASS", "checks": len(checks), "details": checks}
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
        print(json.dumps({"status": "FAIL", "component": args.component, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
