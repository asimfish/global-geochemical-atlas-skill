#!/usr/bin/env python3
"""Run the minimal D1/D2/D3 collaboration contracts against the bundled demo."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import build_evidence_bundle as evidence_builder
import standardize_geochemistry as standardizer
import validate_outputs as output_validator

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
DEMO_INPUT = SKILL_DIR / "fixtures" / "demo_input.csv"
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
        run_command(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                "http://127.0.0.1/private.csv",
                "--output",
                str(unsafe_output),
                "--manifest",
                str(Path(evidence_temp) / "unsafe-download.json"),
                "--license",
                "unresolved",
                "--retries",
                "0",
            ],
            expected_code=2,
        )
        require(not unsafe_output.exists(), "D1 downloader fails closed on unsafe URLs", checks)
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
        {"source_record_id", "analyte_reported", "species_or_oxide", "censored", "missing_reason", "method_family", "file_sha256"}
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
    require(abs(sum(confidence["weights"].values()) - 1.0) < 1e-12, "D2 confidence weights sum to one", checks)
    anomaly_report = json_value(output_dir / "anomaly_report.json")
    anomalies = json_value(output_dir / "anomalies.geojson")
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
