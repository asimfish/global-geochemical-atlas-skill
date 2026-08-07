#!/usr/bin/env python3
"""Run the offline-capable global geochemical atlas MVP end to end."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import build_evidence_bundle as evidence_builder
import build_interactive_map as map_builder
import build_iteration_backlog as backlog_builder
import standardize_geochemistry as standardizer
import validate_outputs as output_validator

SUMMARY_VERSION = "global-geochemical-atlas-result-v1"
MAX_INPUT_BYTES = 200_000_000


class WorkflowError(RuntimeError):
    """Raised with a stable failure status."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def count_input_rows(path: Path, max_records: int) -> int:
    if not path.is_file():
        raise WorkflowError("invalid_input", f"input CSV does not exist: {path}")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise WorkflowError("unsupported_scope", f"input exceeds {MAX_INPUT_BYTES} byte safety limit")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            if not header:
                raise WorkflowError("invalid_input", "input CSV has no header")
            count = 0
            for _ in reader:
                count += 1
                if count > max_records:
                    raise WorkflowError(
                        "unsupported_scope",
                        f"input has more than --max-records ({max_records}); filter or split the request",
                    )
    except UnicodeError as exc:
        raise WorkflowError("invalid_input", "input CSV is not valid UTF-8") from exc
    if count == 0:
        raise WorkflowError("invalid_input", "input CSV has no data rows")
    return count


def json_file(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise WorkflowError("incomplete_retrieval", f"expected JSON object in {path.name}")
    return value


def coverage_from_rows(rows: Sequence[Mapping[str, str]], qc_report: Mapping[str, Any]) -> dict[str, Any]:
    elements = sorted({row.get("element_or_analyte") for row in rows if row.get("element_or_analyte")})
    media = sorted({row.get("medium") for row in rows if row.get("medium")})
    coordinates: list[tuple[float, float]] = []
    for row in rows:
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.isfinite(latitude) and math.isfinite(longitude):
            coordinates.append((longitude, latitude))
    bbox = None
    if coordinates:
        bbox = [
            min(point[0] for point in coordinates),
            min(point[1] for point in coordinates),
            max(point[0] for point in coordinates),
            max(point[1] for point in coordinates),
        ]
    record_count = int(qc_report.get("record_count", 0))
    valid_coordinate_count = int(qc_report.get("valid_coordinate_count", 0))
    return {
        "elements": elements,
        "media": media,
        "coordinate_rate": round(valid_coordinate_count / record_count, 6) if record_count else 0.0,
        "standardization_rate": float(qc_report.get("standardization_rate", 0.0)),
        "bbox": bbox,
        "interpolation": False,
        "coverage_claim": "Observed sample locations only; blank regions are not inferred as absence.",
    }


def summary_outputs() -> dict[str, str]:
    return {
        "database": "geochemistry.csv",
        "source_manifest": "source_manifest.json",
        "record_evidence": "record_evidence.jsonl",
        "qc_report": "qc_report.json",
        "confidence_report": "confidence_report.json",
        "anomalies": "anomalies.geojson",
        "anomaly_report": "anomaly_report.json",
        "batch_acceptance": "batch_acceptance.csv",
        "batch_qc_report": "batch_qc_report.json",
        "anomaly_regions": "anomaly_regions.geojson",
        "spatial_anomaly_report": "spatial_anomaly_report.json",
        "samples": "samples.geojson",
        "interactive_map": "interactive_map.html",
        "iteration_backlog": "iteration_backlog.csv",
    }


def resolved_minimum_group_size(args: argparse.Namespace) -> int:
    if args.min_group_size is not None:
        return int(args.min_group_size)
    return 20 if args.analysis_profile == "production" else 8


def failure_summary(status: str, message: str, input_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SUMMARY_VERSION,
        "status": status,
        "quality_status": "not_evaluated",
        "request_summary": {
            "region_bbox": list(args.region_bbox) if args.region_bbox else None,
            "max_records": args.max_records,
            "group_by": [field.strip() for field in args.group_by.split(",") if field.strip()],
            "minimum_group_size": resolved_minimum_group_size(args),
            "robust_z_threshold": args.robust_z_threshold,
        },
        "input": {
            "filename": input_path.name,
            "sha256": evidence_builder.sha256_file(input_path) if input_path.is_file() else "0" * 64,
            "record_count": 0,
            "synthetic_demo": False,
            "data_mode": "not_evaluated",
            "not_for_scientific_interpretation": False,
        },
        "outputs": {},
        "metrics": {
            "record_count": 0,
            "standardized_record_count": 0,
            "valid_coordinate_count": 0,
            "censored_record_count": 0,
            "candidate_anomaly_count": 0,
            "batch_qc_failed_or_incomplete_count": 0,
            "candidate_anomaly_region_count": 0,
            "iteration_action_required_count": 0,
            "iteration_review_required_count": 0,
        },
        "coverage": {
            "elements": [],
            "media": [],
            "coordinate_rate": 0.0,
            "standardization_rate": 0.0,
            "bbox": None,
            "interpolation": False,
        },
        "limitations": [message],
        "next_actions": ["Correct the reported failure and rerun; do not infer missing scientific fields."],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.max_records < 1 or args.max_records > 200_000:
        raise WorkflowError("unsupported_scope", "--max-records must be between 1 and 200000")
    count_input_rows(args.input, args.max_records)
    group_by = tuple(field.strip() for field in args.group_by.split(",") if field.strip())
    if not group_by:
        raise WorkflowError("invalid_input", "--group-by must contain at least one canonical field")
    minimum_group_size = resolved_minimum_group_size(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    try:
        outputs = standardizer.run_pipeline(
            args.input,
            args.output_dir,
            group_by=group_by,
            min_group_size=minimum_group_size,
            robust_z_threshold=args.robust_z_threshold,
            region_bbox=args.region_bbox,
            analysis_profile=args.analysis_profile,
            geology_grid_path=args.geology_grid,
            geology_grid_sha256=args.geology_grid_sha256,
            batch_qc_input_path=args.batch_qc_input,
            batch_qc_policy_path=args.batch_qc_policy,
            spatial_grid_degrees=args.spatial_grid_degrees,
            min_spatial_samples=args.min_spatial_samples,
            min_spatial_candidates=args.min_spatial_candidates,
            spatial_fdr_alpha=args.spatial_fdr_alpha,
        )
    except standardizer.PipelineError as exc:
        raise WorkflowError("invalid_input", str(exc)) from exc
    except OSError as exc:
        raise WorkflowError("incomplete_retrieval", str(exc)) from exc

    rows = evidence_builder.canonical_rows(outputs["database"])
    input_hash = evidence_builder.sha256_file(args.input)
    source_manifest_path = args.output_dir / "source_manifest.json"
    try:
        source_manifest, synthetic_present = evidence_builder.package_evidence(
            args.input,
            outputs["database"],
            outputs["confidence_report"],
            source_manifest_path,
            args.evidence_jsonl,
            args.acquisition_manifest,
        )
    except evidence_builder.EvidenceError as exc:
        raise WorkflowError("conflicting_evidence", f"evidence packaging failed: {exc}") from exc

    samples_path = args.output_dir / "samples.geojson"
    map_path = args.output_dir / "interactive_map.html"
    backlog_path = args.output_dir / "iteration_backlog.csv"
    backlog_report = backlog_builder.build(outputs["database"], backlog_path)
    try:
        map_report = map_builder.build_map(
            outputs["database"],
            outputs["anomalies"],
            map_path,
            samples_path,
            max_points=args.max_records,
            qc_report_path=outputs["qc_report"],
            confidence_report_path=outputs["confidence_report"],
            source_manifest_path=source_manifest_path,
            anomaly_report_path=outputs["anomaly_report"],
            anomaly_regions_path=outputs["anomaly_regions"],
            spatial_anomaly_report_path=outputs["spatial_anomaly_report"],
            iteration_backlog_path=backlog_path,
        )
    except (map_builder.MapBuildError, OSError) as exc:
        raise WorkflowError("incomplete_retrieval", f"map generation failed: {exc}") from exc

    qc_report = json_file(outputs["qc_report"])
    anomaly_report = json_file(outputs["anomaly_report"])
    batch_qc_report = json_file(outputs["batch_qc_report"])
    spatial_anomaly_report = json_file(outputs["spatial_anomaly_report"])
    coverage = coverage_from_rows(rows, qc_report)
    severity_counts = qc_report.get("severity_counts", {})
    quality_status = "issues_detected" if sum(int(value) for value in severity_counts.values()) else "no_flags"
    limitations = [
        "Candidate anomalies are screening results relative to declared background groups, not causal conclusions.",
        "Map density uses observed points only; no interpolation is performed across unsampled areas.",
    ]
    if synthetic_present:
        limitations.insert(0, "The bundled demo is synthetic CC0 validation data and supports no real-world claim.")
    elif source_manifest.get("not_for_scientific_interpretation") is True:
        limitations.insert(
            0,
            "This is a deterministic real-source fixture for pipeline demonstration, not a representative "
            "scientific sample and not for scientific interpretation.",
        )
    if int(severity_counts.get("error", 0)):
        limitations.append("Some records have error-level QC flags and are capped at low operational confidence.")
    if args.geology_grid is not None:
        limitations.append(
            "GLiM 0.5 degree dominant surface lithology is coarse screening context, not site-scale geology."
        )
    failed_or_incomplete_batches = int(
        batch_qc_report.get("failed_or_incomplete_batch_count", 0)
    )
    if batch_qc_report.get("status") == "evaluated" and failed_or_incomplete_batches:
        limitations.append(
            f"{failed_or_incomplete_batches} laboratory batch(es) failed or were incomplete; "
            "their analytical records remain in the database but were excluded from anomaly backgrounds."
        )
    failed_groups = sum(group.get("status") != "analyzed" for group in anomaly_report.get("groups", []))
    if failed_groups:
        limitations.append(f"{failed_groups} anomaly background group(s) were not analyzed due to explicit failure states.")

    metrics = {
        "record_count": int(qc_report.get("record_count", 0)),
        "standardized_record_count": int(qc_report.get("standardized_record_count", 0)),
        "valid_coordinate_count": int(qc_report.get("valid_coordinate_count", 0)),
        "censored_record_count": int(qc_report.get("censored_record_count", 0)),
        "candidate_anomaly_count": int(anomaly_report.get("candidate_count", 0)),
        "batch_qc_failed_or_incomplete_count": failed_or_incomplete_batches,
        "candidate_anomaly_region_count": int(
            spatial_anomaly_report.get("candidate_region_count", 0)
        ),
        "iteration_action_required_count": int(
            backlog_report.get("status_counts", {}).get("action_required", 0)
        ),
        "iteration_review_required_count": int(
            backlog_report.get("status_counts", {}).get("review_required", 0)
        ),
    }
    partial_reasons: list[str] = []
    if failed_groups:
        partial_reasons.append("one_or_more_anomaly_background_groups_not_analyzed")
    if failed_or_incomplete_batches:
        partial_reasons.append("one_or_more_laboratory_batches_excluded")
    if metrics["valid_coordinate_count"] < metrics["record_count"]:
        partial_reasons.append("one_or_more_records_not_map_eligible")
    if (
        metrics["candidate_anomaly_count"]
        and spatial_anomaly_report.get("status") == "insufficient_spatial_background"
    ):
        partial_reasons.append("spatial_candidate_region_background_insufficient")
    summary = {
        "schema_version": SUMMARY_VERSION,
        "status": "partial_success" if partial_reasons else "success",
        "quality_status": quality_status,
        "request_summary": {
            "region_bbox": list(args.region_bbox) if args.region_bbox else None,
            "max_records": args.max_records,
            "group_by": list(group_by),
            "minimum_group_size": minimum_group_size,
            "robust_z_threshold": args.robust_z_threshold,
        },
        "input": {
            "filename": args.input.name,
            "sha256": input_hash,
            "record_count": len(rows),
            "synthetic_demo": synthetic_present,
            "data_mode": source_manifest.get("data_mode", "input"),
            "not_for_scientific_interpretation": source_manifest.get(
                "not_for_scientific_interpretation", False
            ),
        },
        "outputs": summary_outputs(),
        "metrics": metrics,
        "coverage": coverage,
        "limitations": limitations,
        "next_actions": [
            "Inspect source_manifest.json and record-level source locators before scientific reuse.",
            "Review low-confidence records and failed anomaly groups with a geochemist.",
            "Add source-specific field mappings rather than guessing legacy qualifier semantics.",
        ],
        "map_report": map_report,
    }
    if partial_reasons:
        summary["limitations"].append(
            "Partial-success reasons: " + ", ".join(partial_reasons) + "."
        )
    summary_path = args.output_dir / "run_summary.json"
    atomic_json(summary_path, summary)

    validation = output_validator.validate_dir(args.output_dir)
    if validation["status"] != "valid":
        summary["status"] = "incomplete_retrieval"
        summary["limitations"].append("Output validation failed: " + "; ".join(validation["errors"]))
        atomic_json(summary_path, summary)
        raise WorkflowError("incomplete_retrieval", "output validation failed")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standardize geochemical CSV data, screen candidate anomalies, and build auditable map outputs."
    )
    parser.add_argument("--input", required=True, type=Path, help="UTF-8 CSV; one row per sample-analyte determination")
    parser.add_argument("--output-dir", required=True, type=Path, help="Destination directory for stable outputs")
    parser.add_argument(
        "--evidence-jsonl",
        type=Path,
        help="Optional D1 record evidence sidecar; copied and hash-bound as record_evidence.jsonl",
    )
    parser.add_argument(
        "--acquisition-manifest",
        type=Path,
        help="Optional D1 run manifest that binds the input CSV and --evidence-jsonl hashes",
    )
    parser.add_argument(
        "--batch-qc-input",
        type=Path,
        help="Optional normalized CRM/blank/duplicate CSV; requires --batch-qc-policy",
    )
    parser.add_argument(
        "--batch-qc-policy",
        type=Path,
        help="Explicit batch acceptance policy; requires --batch-qc-input",
    )
    parser.add_argument(
        "--geology-grid", type=Path,
        help="Optional official PANGAEA.788537 GLiM 0.5 degree ZIP for D2 screening spatial matching",
    )
    parser.add_argument(
        "--geology-grid-sha256",
        help="Required SHA-256 pin when --geology-grid is supplied",
    )
    parser.add_argument(
        "--analysis-profile", choices=("demo", "production"), default="demo",
        help="Production enforces at least 20 usable records per anomaly background group",
    )
    parser.add_argument(
        "--region-bbox", type=standardizer.parse_bbox, metavar="W,S,E,N",
        help="Optional WGS84 requested region, used for coordinate QC (dateline crossing supported)",
    )
    parser.add_argument("--max-records", type=int, default=50_000, help="Fail closed above this input count")
    parser.add_argument(
        "--group-by", default=",".join(standardizer.DEFAULT_GROUP_BY),
        help="Comma-separated comparable background fields for anomaly screening",
    )
    parser.add_argument(
        "--min-group-size", type=int,
        help="Minimum usable records per anomaly group (default: demo=8, production=20)",
    )
    parser.add_argument("--robust-z-threshold", type=float, default=3.5, help="Absolute modified z-score threshold")
    parser.add_argument(
        "--spatial-grid-degrees", type=float, default=2.0,
        help="Fixed WGS84 cell size for candidate-region testing (default: 2)",
    )
    parser.add_argument(
        "--min-spatial-samples", type=int,
        help="Minimum mapped usable records inside and outside each tested cell",
    )
    parser.add_argument(
        "--min-spatial-candidates", type=int, default=2,
        help="Minimum D2 point candidates required in a reported cell",
    )
    parser.add_argument(
        "--spatial-fdr-alpha", type=float, default=0.10,
        help="Benjamini-Hochberg FDR threshold for candidate regions",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = run(args)
    except WorkflowError as exc:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        summary = failure_summary(exc.status, str(exc), args.input, args)
        atomic_json(args.output_dir / "run_summary.json", summary)
        print(f"run_workflow: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": summary["status"], "output_dir": str(args.output_dir), "metrics": summary["metrics"]},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
