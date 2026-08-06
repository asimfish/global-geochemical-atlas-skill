#!/usr/bin/env python3
"""Validate a standalone profile-driven D3 visualization bundle."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import build_interactive_map as map_builder
import render_visualization as renderer
import validate_outputs as workflow_validator


MAX_OUTPUT_BYTES = 100_000_000


def validate_dir(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required_names = (*renderer.REQUIRED_INPUTS, *renderer.GENERATED_OUTPUTS)
    paths = {name: output_dir / name for name in required_names}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"missing required D3 output: {name}")
        elif path.stat().st_size == 0:
            errors.append(f"required D3 output is empty: {name}")
        elif path.stat().st_size > MAX_OUTPUT_BYTES:
            errors.append(f"D3 output exceeds the 100 MB runtime safety limit: {name}")
    if errors:
        return {"status": "invalid", "errors": errors, "warnings": warnings, "metrics": {}}

    database_metrics = workflow_validator.validate_database(
        paths["geochemistry.csv"], errors, warnings
    )
    canonical_ids = set(workflow_validator.database_evidence_index(paths["geochemistry.csv"]))
    iteration_count = workflow_validator.validate_iteration_backlog(
        paths["iteration_backlog.csv"], canonical_ids, errors
    )
    parsed: dict[str, Any] = {}
    for name in (
        "anomalies.geojson",
        "samples.geojson",
        "confidence_report.json",
        "source_manifest.json",
        "anomaly_report.json",
        "visualization_profile.json",
        "visualization_report.json",
    ):
        try:
            parsed[name] = workflow_validator.strict_json(paths[name])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{name} is invalid JSON: {exc}")

    anomaly_count = 0
    sample_count = 0
    sample_record_ids: set[str] = set()
    if "anomalies.geojson" in parsed:
        anomaly_count = workflow_validator.validate_feature_collection(
            parsed["anomalies.geojson"],
            "anomalies.geojson",
            errors,
            allow_null_geometry=True,
            require_candidate_status=True,
        )
    if "samples.geojson" in parsed:
        sample_count = workflow_validator.validate_feature_collection(
            parsed["samples.geojson"],
            "samples.geojson",
            errors,
            allow_null_geometry=False,
        )
        sample_record_ids = {
            str(feature.get("properties", {}).get("record_id"))
            for feature in parsed["samples.geojson"].get("features", [])
            if feature.get("properties", {}).get("record_id") is not None
        }
    scoped_anomaly_count = 0
    if "anomalies.geojson" in parsed:
        scoped_anomaly_count = sum(
            str(feature.get("properties", {}).get("record_id")) in sample_record_ids
            for feature in parsed["anomalies.geojson"].get("features", [])
            if feature.get("properties", {}).get("record_id") is not None
        )
    if sample_count > database_metrics["record_count"]:
        errors.append("samples.geojson contains more features than geochemistry.csv records")
    workflow_validator.validate_html(paths["interactive_map.html"], errors)

    profile = parsed.get("visualization_profile.json")
    if isinstance(profile, dict):
        try:
            validated_profile = map_builder.load_visualization_profile(
                paths["visualization_profile.json"]
            )
        except map_builder.MapBuildError as exc:
            errors.append(f"visualization_profile.json violates the D3 profile contract: {exc}")
        else:
            if validated_profile != profile:
                errors.append("visualization_profile.json is not in canonical D3 form")
    else:
        errors.append("visualization_profile.json must contain an object")

    report = parsed.get("visualization_report.json")
    if not isinstance(report, dict):
        errors.append("visualization_report.json must contain an object")
    else:
        if report.get("interface_version") != renderer.INTERFACE_VERSION:
            errors.append("visualization_report.json has an unsupported interface_version")
        if report.get("status") != "success":
            errors.append("visualization_report.json does not report success")
        if report.get("profile") != profile:
            errors.append("visualization_report.json profile differs from visualization_profile.json")
        if not isinstance(report.get("profile_warnings"), list):
            errors.append("visualization_report.json profile_warnings must be an array")
        expected_outputs = {
            "interactive_map": "interactive_map.html",
            "samples": "samples.geojson",
            "profile": "visualization_profile.json",
            "iteration_backlog": "iteration_backlog.csv",
        }
        if report.get("outputs") != expected_outputs:
            errors.append("visualization_report.json outputs do not match the D3 contract")
        for name, expected_hash in report.get("inputs", {}).items():
            if name not in renderer.REQUIRED_INPUTS:
                errors.append(f"visualization_report.json contains an unknown input hash: {name}")
            elif expected_hash != workflow_validator.sha256_file(paths[name]):
                errors.append(f"visualization_report.json input hash differs for {name}")
        if set(report.get("inputs", {})) != set(renderer.REQUIRED_INPUTS):
            errors.append("visualization_report.json does not hash every required D1/D2 input")
        output_hashes = report.get("output_sha256")
        if not isinstance(output_hashes, dict):
            errors.append("visualization_report.json output_sha256 must be an object")
        else:
            for name in expected_outputs.values():
                if output_hashes.get(name) != workflow_validator.sha256_file(paths[name]):
                    errors.append(f"visualization_report.json output hash differs for {name}")
        map_report = report.get("map_report")
        if not isinstance(map_report, dict):
            errors.append("visualization_report.json map_report must be an object")
        else:
            if map_report.get("map_version") != "d3-interactive-atlas-v3":
                errors.append("visualization map_version is unsupported")
            if map_report.get("ui_hierarchy_version") != "task-first-progressive-disclosure-v2":
                errors.append("visualization UI hierarchy contract is unsupported")
            question_contract = map_report.get("visual_question_contract")
            expected_views = {"map", "database", "combination", "sources", "anomalies", "quality"}
            if not isinstance(question_contract, dict) or question_contract.get("schema_version") != "d3-visual-question-contract-v1":
                errors.append("visualization visual-question contract is missing or unsupported")
            elif set(question_contract.get("views", {})) != expected_views:
                errors.append("visualization visual-question contract does not cover every primary view")
            else:
                for view_name, view_contract in question_contract["views"].items():
                    if not isinstance(view_contract, dict) or set(view_contract) != {
                        "question", "comparison_baseline", "encoding", "boundary"
                    }:
                        errors.append(f"visualization question contract is malformed for {view_name}")
                    elif not view_contract["question"] or not view_contract["comparison_baseline"] or not view_contract["encoding"] or not view_contract["boundary"]:
                        errors.append(f"visualization question contract is incomplete for {view_name}")
            if map_report.get("external_assets") != 0 or map_report.get("interpolation") is not False:
                errors.append("visualization report violates the offline/no-interpolation boundary")
            if map_report.get("mapped_record_count") != sample_count:
                errors.append("visualization mapped_record_count differs from samples.geojson")
            if map_report.get("candidate_record_count") != scoped_anomaly_count:
                errors.append(
                    "visualization candidate_record_count differs from the anomalies linked "
                    "to scoped samples.geojson records"
                )
            if map_report.get("visualization_profile") != profile:
                errors.append("map_report profile differs from visualization_profile.json")
            if map_report.get("visualization_profile_warnings") != report.get("profile_warnings"):
                errors.append("map_report warnings differ from visualization_report.json")

    evidence_path = output_dir / "record_evidence.jsonl"
    evidence_count = 0
    if evidence_path.is_file():
        evidence_count = workflow_validator.validate_record_evidence(
            evidence_path,
            workflow_validator.database_evidence_index(paths["geochemistry.csv"]),
            errors,
        )
    else:
        warnings.append("record_evidence.jsonl was not present in the D1/D2 input and was not carried into D3")

    return {
        "status": "valid" if not errors else "invalid",
        "errors": errors,
        "warnings": warnings,
        "metrics": {
            **database_metrics,
            "record_evidence_count": evidence_count,
            "sample_feature_count": sample_count,
            "source_candidate_feature_count": anomaly_count,
            "scoped_candidate_feature_count": scoped_anomaly_count,
            "iteration_backlog_count": iteration_count,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="Standalone D3 bundle")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_dir(args.output_dir)
    except OSError as exc:
        report = {"status": "invalid", "errors": [str(exc)], "warnings": [], "metrics": {}}
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
