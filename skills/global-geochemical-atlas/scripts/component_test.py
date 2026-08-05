#!/usr/bin/env python3
"""Run the minimal D1/D2/D3 collaboration contracts against the bundled demo."""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import sqlite3
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
import build_index as index_builder
import benchmark_index
import cache_control
import coverage_report
import download_data as downloader
import source_adapters as source_contracts
import source_audit
import score_source_evidence
import snapshot_source
import source_router
import query_source
import validate_acquisition as acquisition_validator
import validate_outputs as output_validator
import verify_marchem_candidate

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
DEMO_INPUT = SKILL_DIR / "fixtures" / "demo_input.csv"
SOURCE_DEMOS = SKILL_DIR / "fixtures" / "source-demos"
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
DOWNLOADER = SCRIPT_DIR / "download_data.py"


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
    require(manifest.get("manifest_version") == "geochemical-source-manifest-v1", "D1 manifest version is stable", checks)
    require(manifest.get("input", {}).get("sha256") == input_hash, "D1 manifest binds the acquired input hash", checks)
    require(manifest.get("input", {}).get("record_count") == 19, "D1 manifest preserves the record count", checks)
    coverage = manifest.get("coverage", {})
    require(coverage.get("source_locator_rate") == 1.0, "D1 demo provenance coverage is complete", checks)
    require(coverage.get("declared_license_rate") == 1.0, "D1 demo license declarations are complete", checks)
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
        set(registry["sources"]) == {"georoc-archaean", "usgs-conus-soil", "norway-marchem"},
        "D1 registry freezes the rock, soil and sediment reference sources",
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
    catalog = source_router.load_catalog()
    require(
        set(catalog["sources"][source_id]["status"] for source_id in ("georoc-archaean", "usgs-conus-soil"))
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
        <= {medium for entry in catalog["sources"].values() for medium in entry["media"]},
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
        == {"georoc-archaean", "usgs-conus-soil", "norway-marchem"},
        "D1 V3 router selects the three sources that currently support normalized analysis",
        checks,
    )
    require(
        route["coverage"]["rock"]["status"] == "partial"
        and route["coverage"]["soil"]["status"] == "partial"
        and route["coverage"]["sediment"]["status"] == "partial"
        and route["coverage"]["water"]["status"] == "unknown",
        "D1 router does not overclaim incomplete coverage below the requested use mode",
        checks,
    )
    require(
        {"gemstat-open-archive", "usgs-ngdb"}
        <= {entry["source_id"] for entry in route["review_sources"]},
        "D1 router exposes relevant candidates and their review blockers",
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
        == {"norway-marchem"},
        "D1 V3 router can select the normalized MarChem snapshot for a raw-observation request",
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
        >= {"georoc-archaean", "usgs-conus-soil"},
        "D1 keeps both A-tier sources below benchmark_ready until human review is complete",
        checks,
    )
    candidate_evidence = score_source_evidence.load_candidate_evidence()
    evidence = score_source_evidence.score_catalog(catalog, registry, candidate_evidence)
    require(
        evidence == json_value(SKILL_DIR / "assets" / "source_evidence_scores.json"),
        "D1 checked-in V3 evidence report is reproducible from catalog, registry and candidate evidence",
        checks,
    )
    require(
        evidence["summary"]
        == {
            "evidence_tiers": {"A": 3, "B": 0, "C": 0, "D": len(catalog["sources"]) - 3, "U": 0},
            "use_modes": {
                "benchmark_ready": 0,
                "normalized_analysis": 3,
                "raw_observation": 0,
                "discovery": len(catalog["sources"]) - 3,
            },
        },
        "D1 V3 evidence scoring keeps all catalog sources while separating their current use modes",
        checks,
    )
    require(
        evidence["sources"]["georoc-archaean"]["source_evidence_score"] == 85
        and evidence["sources"]["georoc-archaean"]["evidence_tier"] == "A"
        and evidence["sources"]["georoc-archaean"]["use_mode"] == "normalized_analysis"
        and evidence["sources"]["georoc-archaean"]["source_evidence_dimensions"]["human_review"]["status"]
        == "missing",
        "D1 scores GEOROC highly without falsely marking the pending human review complete",
        checks,
    )
    require(
        evidence["sources"]["norway-marchem"]["source_evidence_score"] == 85
        and evidence["sources"]["norway-marchem"]["evidence_tier"] == "A"
        and evidence["sources"]["norway-marchem"]["use_mode"] == "normalized_analysis"
        and evidence["sources"]["norway-marchem"]["source_evidence_dimensions"]["version_snapshot"]["status"]
        == "verified",
        "D1 credits the frozen MarChem adapter while retaining its pending human-review limitation",
        checks,
    )
    audit = source_audit.audit_catalog(catalog, registry, candidate_evidence)
    require(
        audit["status"] == "PASS"
        and audit["summary"]["evidence_tiers"] == evidence["summary"]["evidence_tiers"]
        and audit["sources"]["gemstat-open-archive"]["operational_status"] == "restricted"
        and audit["sources"]["gemstat-open-archive"]["evidence_tier"] == "D",
        "D1 audit separates operational research-use restrictions from progressive evidence tier",
        checks,
    )
    tampered_catalog = copy.deepcopy(catalog)
    tampered_catalog["sources"]["georoc-archaean"]["license"]["status"] = "unresolved"
    tampered_audit = source_audit.audit_catalog(tampered_catalog, registry, candidate_evidence)
    require(
        tampered_audit["status"] == "PASS"
        and tampered_audit["sources"]["georoc-archaean"]["research_use_status"] == "unknown"
        and tampered_audit["sources"]["georoc-archaean"]["operational_status"] == "restricted"
        and tampered_audit["sources"]["georoc-archaean"]["source_evidence_score"] == 85,
        "D1 separates unresolved research-use conditions from unchanged scientific evidence completeness",
        checks,
    )
    tampered_catalog["sources"]["georoc-archaean"]["license"]["status"] = "open"
    tampered_catalog["sources"]["georoc-archaean"]["version"]["value"] = "unreviewed-new-version"
    tampered_route = source_router.route_sources(
        {"elements": ["As"], "region": "global", "media": ["rock"]},
        tampered_catalog,
        registry,
    )
    require(
        "georoc-archaean" not in {entry["source_id"] for entry in tampered_route["selected_sources"]}
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
        and max(record["round"] for record in discovery_records) == catalog["discovery_state"]["round"],
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
        marchem_verification["verification_version"] == "marchem-candidate-verification-v1"
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
            and profile["present_count"] + profile["missing_count"] == profile["record_count"]
            and profile["invalid_count"] == 0
            and profile["reported_unit"] == "mg/kg"
            and profile["weight_basis"] == "dry"
            for profile in marchem_data["target_analytes"].values()
        )
        and marchem_verification["observed_metadata"]["partial_digestion_disclosed"] is True
        and marchem_verification["observed_metadata"]["not_total_content_disclosed"] is True
        and marchem_verification["observed_metadata"]["accreditation_rows"]["not_accredited"] > 0,
        "D1 MarChem evidence preserves target units, censoring context, partial digestion and accreditation limits",
        checks,
    )
    require(
        len(marchem_verification["prepared_human_review_sample"]) == 30
        and marchem_verification["human_review"]
        == {"required_record_count": 30, "prepared_record_count": 30, "status": "pending"}
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
    identical_snapshot_diff = snapshot_source.diff_snapshots(marchem_snapshot, copy.deepcopy(marchem_snapshot))
    require(
        identical_snapshot_diff["status"] == "identical"
        and identical_snapshot_diff["requires_rescore"] is False,
        "D1 snapshot diff recognizes an identical manifest without forcing rescore",
        checks,
    )
    changed_snapshot = copy.deepcopy(marchem_snapshot)
    changed_snapshot["response"]["sha256"] = "0" * 64
    changed_snapshot_diff = snapshot_source.diff_snapshots(marchem_snapshot, changed_snapshot)
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
        and marchem_reconciliation["snapshot_response_sha256"] == marchem_snapshot["response"]["sha256"]
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
        and marchem_reconciliation["measurement_semantics"]["weight_bases"] == ["Dry weight"]
        and marchem_reconciliation["checks"]["partial_digestion_boundary_preserved"] is True
        and marchem_reconciliation["checks"]["accreditation_variation_preserved"] is True,
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
        and all(record["automated_status"] == "PASS" for record in marchem_human_review["records"]),
        "D1 prepares 30 passing MarChem comparisons without claiming human completion",
        checks,
    )
    require(
        all(
            record["reviewer"]
            == {"decision": None, "reviewer": None, "reviewed_at": None, "notes": None}
            for record in marchem_human_review["records"]
        )
        and any(not record["adapter_observations"] for record in marchem_human_review["records"])
        and any(
            any(str(value).startswith("<") for value in record["published_target_raw_values"].values())
            for record in marchem_human_review["records"]
        ),
        "D1 review sheet awaits a named reviewer and includes missing and censored edge cases",
        checks,
    )
    prepared_reference_reviews = {
        "georoc-archaean": json_value(
            SKILL_DIR / "fixtures" / "four-media" / "rock" / "georoc-archaean" / "human_review.json"
        ),
        "usgs-conus-soil": json_value(
            SKILL_DIR / "fixtures" / "four-media" / "soil" / "usgs-conus-soil" / "human_review.json"
        ),
    }
    require(
        all(
            review["status"] == "prepared"
            and review["prepared_record_count"] == 30
            and review["automated_pass_count"] == 30
            and review["completed_record_count"] == 0
            and all(record["automated_status"] == "PASS" for record in review["records"])
            for review in prepared_reference_reviews.values()
        ),
        "D1 prepares 30 passing GEOROC and USGS comparisons without auto-signing either source",
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
        > 0,
        "D1 review selection spans 27 GEOROC members, all soil layers and GEOROC missing-value cases",
        checks,
    )
    require(
        all(
            evidence["sources"][source_id]["source_evidence_score"] == 85.0
            and evidence["sources"][source_id]["source_evidence_dimensions"]["human_review"]["status"] == "missing"
            and "30-record review sample is prepared"
            in evidence["sources"][source_id]["source_evidence_dimensions"]["human_review"]["note"]
            for source_id in prepared_reference_reviews
        ),
        "D1 records prepared GEOROC and USGS reviews without granting unsigned evidence points",
        checks,
    )
    coverage_request = json_value(SOURCE_DEMOS.parent / "source-routing" / "global-all-media-request.json")
    matrix = coverage_report.build_matrix(catalog, coverage_request, registry)
    require(
        matrix == json_value(SKILL_DIR / "assets" / "coverage_matrix.json"),
        "D1 checked-in coverage matrix is reproducible from the catalog and request",
        checks,
    )
    require(
        matrix["overall_status"] == "partial"
        and matrix["cells"]["rock"]["source_independence"] == "single_source_dependency"
        and matrix["cells"]["water"]["analyte_coverage"] == "unknown",
        "D1 coverage matrix reports partial, single-source and unaudited dimensions conservatively",
        checks,
    )
    archive_bundle = json_value(SKILL_DIR / "fixtures" / "schema-v1" / "archive-bundle.json")
    archive_validation = acquisition_validator.validate_bundle(archive_bundle)
    require(
        archive_validation["status"] == "PASS"
        and archive_validation["entity_counts"]["observations"] == 3
        and archive_validation["entity_counts"]["methods"] == 2,
        "D1 archive schema fixture preserves entities and passes relation validation",
        checks,
    )
    censored_observation = next(
        item for item in archive_bundle["observations"] if item["observation_id"] == "observation-as-lt"
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
            require("refusing to overwrite" in str(exc), "D1 index creation refuses implicit overwrite", checks)
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
            query_source.query_index(first_index, bbox=[0, 0, 1, 1])["record_count"] == 0,
            "D1 RTree query excludes observations outside the requested bbox",
            checks,
        )
        require(
            query_source.query_index(first_index, methods=["XRF"])["record_count"] == 1,
            "D1 indexed query filters exact source-native analytical techniques",
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
                for view in ("observation_search", "sample_summary", "source_coverage", "provenance_trace")
            }
        require(
            trace == ("fixture.csv", 2, "1.0.0", "run-fixture-v1"),
            "D1 provenance view traces an observation to source row, adapter and acquisition run",
            checks,
        )
        require(
            view_counts == {
                "observation_search": 3,
                "sample_summary": 2,
                "source_coverage": 3,
                "provenance_trace": 3,
            },
            "D1 SQLite contract exposes four populated query views",
            checks,
        )

        request_one = {"media": ["soil"], "elements": ["As", "Cu"], "region": "global"}
        request_reordered = {"region": "global", "elements": ["As", "Cu"], "media": ["soil"]}
        request_changed = {"region": "global", "elements": ["Zn"], "media": ["soil"]}
        key_one = cache_control.stable_request_cache_key("fixture-source", "1.0.0", request_one)
        require(
            key_one
            == cache_control.stable_request_cache_key("fixture-source", "1.0.0", request_reordered)
            and key_one != cache_control.stable_request_cache_key("fixture-source", "1.0.0", request_changed),
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
            require("confirmation must exactly equal" in str(exc), "D1 cache deletion requires an exact source@version confirmation", checks)
        else:
            raise ContractError("D1 cache deletion must reject an incorrect confirmation")
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
        and vocabulary_registry["vocabularies"]["d1-missing-reason-v1"]["status"] == "internal_frozen",
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
        "usgs-conus-soil": 48,
        "norway-marchem": 112,
    }
    for source_id, expected_demo_count in expected_demo_counts.items():
        demo_dir = SOURCE_DEMOS / source_id
        demo_input = demo_dir / "demo_input.csv"
        sources_path = demo_dir / "sources.jsonl"
        generation_manifest = json_value(demo_dir / "run_manifest.json")
        demo_rows = csv_rows(demo_input)
        evidence_rows = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines()]
        require(
            len(demo_rows) == expected_demo_count and len(evidence_rows) == expected_demo_count,
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
        per_analyte_count = expected_demo_count // 4
        require(
            Counter(row["element_or_analyte"] for row in demo_rows)
            == Counter(
                {
                    "As": per_analyte_count,
                    "Cu": per_analyte_count,
                    "Ni": per_analyte_count,
                    "Zn": per_analyte_count,
                }
            ),
            f"D1 {source_id} fixture keeps the four analytes balanced",
            checks,
        )
    georoc_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "georoc-archaean" / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    require(
        all(item.get("article_citations") for item in georoc_evidence),
        "D1 GEOROC fixture resolves citation IDs to original reference text",
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
    marchem_evidence = [
        json.loads(line)
        for line in (SOURCE_DEMOS / "norway-marchem" / "sources.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    require(
        {item.get("digestion_scope") for item in marchem_evidence} == {"partial"}
        and {item.get("wet_or_dry_weight") for item in marchem_evidence} == {"Dry weight"}
        and {item.get("accreditation_status") for item in marchem_evidence}
        == {"accredited", "not_accredited"}
        and all(item.get("metadata_source_locator") for item in marchem_evidence),
        "D1 MarChem fixture retains per-observation method and accreditation evidence",
        checks,
    )

    with tempfile.TemporaryDirectory() as evidence_temp:
        standalone = Path(evidence_temp) / "source_manifest.json"
        evidence_builder.package_evidence(
            DEMO_INPUT, output_dir / "geochemistry.csv", confidence_path, standalone
        )
        require(standalone.read_bytes() == manifest_path.read_bytes(), "D1 standalone packaging matches D3 integration", checks)

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
    indexed = {row["record_id"]: row for row in rows}
    require(float(indexed["rock-fe-001"]["normalized_value"]) == 25_000, "D2 solid unit conversion is stable", checks)
    require(indexed["soil-as-013"]["normalized_value"] == "", "D2 censored values are not imputed", checks)
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
    require(confidence.get("confidence_version") == "d2-confidence-v1", "D2 confidence version is explicit", checks)
    require(
        set(confidence.get("weights", {})) == {"source", "completeness", "method", "spatial", "qc"},
        "D2 confidence component contract is complete",
        checks,
    )
    require(abs(sum(confidence["weights"].values()) - 1.0) < 1e-12, "D2 confidence weights sum to one", checks)
    anomaly_report = json_value(output_dir / "anomaly_report.json")
    anomalies = json_value(output_dir / "anomalies.geojson")
    require(anomaly_report.get("scientific_status") == "screening_baseline_only", "D2 anomaly boundary is explicit", checks)
    require(anomaly_report.get("candidate_count") == 1, "D2 demo anomaly result is stable", checks)
    require(
        anomalies["features"][0]["properties"].get("status") == "candidate_anomaly",
        "D2 does not turn a screening candidate into a causal conclusion",
        checks,
    )
    return checks


def check_d3(output_dir: Path) -> list[str]:
    checks: list[str] = []
    skill_dirs = [path for path in (REPO_ROOT / "skills").iterdir() if path.is_dir() and not path.name.startswith(".")]
    require(len(skill_dirs) == 1 and skill_dirs[0] == SKILL_DIR, "D3 keeps exactly one production Skill", checks)
    required_outputs = set(output_validator.REQUIRED_FILES.values())
    actual_outputs = {path.name for path in output_dir.iterdir() if path.is_file()}
    require(actual_outputs == required_outputs, "D3 publishes the stable nine-file output set", checks)
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
