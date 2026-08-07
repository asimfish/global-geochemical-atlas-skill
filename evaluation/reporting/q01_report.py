#!/usr/bin/env python3
"""Q01-Q24 adapter for the unified geochemical evaluation report."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any


FOUR_MEDIA = {"rock", "soil", "sediment", "water"}
STAGES = {
    "D1": {"Q01", "Q02", "Q05", "Q10", "Q17", "Q22"},
    "D2": {
        "Q03",
        "Q04",
        "Q06",
        "Q08",
        "Q09",
        "Q12",
        "Q13",
        "Q14",
        "Q18",
        "Q19",
        "Q21",
        "Q23",
    },
    "D3": {"Q07", "Q11", "Q15", "Q16", "Q20", "Q24"},
}


def load_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(
    path: Path, *, valid: bool, usable: bool, detail: Any = None
) -> dict[str, Any]:
    present = path.is_file() and path.stat().st_size > 0
    return {
        "present": present,
        "valid": bool(present and valid),
        "usable": bool(present and valid and usable),
        "filename": path.name,
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path),
        "detail": detail,
    }


def _logical(manifest: dict[str, Any], key: str) -> Any:
    evidence = (
        manifest.get("benchmark_evidence") if isinstance(manifest, dict) else None
    )
    entry = evidence.get(key) if isinstance(evidence, dict) else None
    if not isinstance(entry, dict):
        return None
    if entry.get("format") == "json":
        return entry.get("value")
    if entry.get("format") in {"csv", "jsonl"}:
        return entry.get("rows")
    if entry.get("format") == "text":
        return entry.get("value")
    return None


def _stage(question: str) -> str:
    return next(
        (stage for stage, questions in STAGES.items() if question in questions),
        "unknown",
    )


def _llm_points(report: dict[str, Any]) -> tuple[int, int]:
    criteria = report.get("criteria") if isinstance(report, dict) else None
    if not isinstance(criteria, list):
        return 0, 0
    return (
        sum(int(item.get("score", 0)) for item in criteria if isinstance(item, dict)),
        sum(int(item.get("max", 0)) for item in criteria if isinstance(item, dict)),
    )


def _task_results(results_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for number in range(1, 25):
        question = f"Q{number:02d}"
        task_root = results_root / question
        score = load_json(task_root / "score.json", {})
        objective = load_json(task_root / "objective_report.json", {})
        llm = load_json(task_root / "llm_grader_report.json", {})
        llm_awarded, llm_possible = _llm_points(llm)
        checks = objective.get("checks") if isinstance(objective, dict) else []
        failed = [
            {"id": item.get("id"), "evidence": item.get("evidence")}
            for item in checks or []
            if isinstance(item, dict) and item.get("passed") is False
        ]
        present = all(
            (task_root / name).is_file()
            for name in (
                "score.json",
                "objective_report.json",
                "llm_grader_report.json",
            )
        )
        results.append(
            {
                "question_id": question,
                "task_id": objective.get("task_id") or score.get("run_id"),
                "stage": _stage(question),
                "present": present,
                "candidate_status": score.get("candidate_status"),
                "score_status": score.get("score_status", "missing"),
                "hard_gate_passed": score.get("hard_gate_passed") is True,
                "descriptive_total_score": score.get("total_score"),
                "machine_awarded": objective.get("evidence_points_awarded"),
                "machine_possible": objective.get("evidence_points_possible"),
                "llm_awarded": llm_awarded,
                "llm_possible": llm_possible,
                "failed_checks": failed,
                "redline_events": objective.get("redline_events", []),
                "human_review_required": llm.get("human_review_required"),
                "grader_uncertainty": llm.get("grader_uncertainty"),
            }
        )
    return results


def _stage_summaries(task_results: list[dict[str, Any]]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for stage in STAGES:
        members = [item for item in task_results if item["stage"] == stage]
        machine_awarded = sum(item["machine_awarded"] or 0 for item in members)
        machine_possible = sum(item["machine_possible"] or 0 for item in members)
        llm_awarded = sum(item["llm_awarded"] for item in members)
        llm_possible = sum(item["llm_possible"] for item in members)
        partial = [
            float(item["descriptive_total_score"])
            for item in members
            if isinstance(item["descriptive_total_score"], (int, float))
        ]
        summaries[stage] = {
            "question_count": len(members),
            "machine_awarded": machine_awarded,
            "machine_possible": machine_possible,
            "machine_rate": round(machine_awarded / machine_possible, 6)
            if machine_possible
            else None,
            "llm_awarded": llm_awarded,
            "llm_possible": llm_possible,
            "llm_rate": round(llm_awarded / llm_possible, 6) if llm_possible else None,
            "descriptive_partial_mean": round(sum(partial) / len(partial), 6)
            if partial
            else None,
            "failed_check_count": sum(len(item["failed_checks"]) for item in members),
        }
    return summaries


def _geojson_metrics(value: Any) -> dict[str, Any]:
    features = value.get("features") if isinstance(value, dict) else None
    if (
        not isinstance(value, dict)
        or value.get("type") != "FeatureCollection"
        or not isinstance(features, list)
    ):
        return {"valid": False, "features": 0, "unique_locations": 0}
    valid = True
    locations: set[tuple[float, float]] = set()
    for feature in features:
        try:
            lon, lat = map(float, feature["geometry"]["coordinates"][:2])
        except (KeyError, TypeError, ValueError, IndexError):
            valid = False
            continue
        if not (
            math.isfinite(lon)
            and math.isfinite(lat)
            and -180 <= lon <= 180
            and -90 <= lat <= 90
        ):
            valid = False
        else:
            locations.add((round(lat, 8), round(lon, 8)))
    return {
        "valid": valid,
        "features": len(features),
        "unique_locations": len(locations),
    }


def _sqlite_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
        return bool(result and result[0] == "ok")
    except sqlite3.Error:
        return False


def _screenshots_verified(audit: dict[str, Any], audit_path: Path | None) -> bool:
    if audit_path is None or not audit_path.is_file():
        return False
    directory = audit.get("screenshot_directory")
    screenshots = audit.get("screenshots")
    if (
        not isinstance(directory, str)
        or Path(directory).name != directory
        or not isinstance(screenshots, list)
        or not screenshots
    ):
        return False
    root = audit_path.parent / directory
    return all(
        isinstance(item, dict)
        and isinstance(item.get("file"), str)
        and Path(item["file"]).name == item["file"]
        and (root / item["file"]).is_file()
        and (root / item["file"]).stat().st_size == item.get("bytes")
        and sha256_file(root / item["file"]) == item.get("sha256")
        for item in screenshots
    )


def build(args: Any) -> dict[str, Any]:
    submissions = args.submission_dir.resolve()
    results_root = args.results_dir.resolve()
    q24 = submissions / "Q24" / "artifacts"
    run_manifest = load_json(q24 / "run_manifest.json", {})
    observations = _logical(run_manifest, "observations.csv")
    observations = observations if isinstance(observations, list) else []
    sources = _logical(run_manifest, "sources.jsonl")
    sources = sources if isinstance(sources, list) else []
    qc = _logical(run_manifest, "qc_report.json")
    qc = qc if isinstance(qc, dict) else {}
    confidence = _logical(run_manifest, "confidence_report.json")
    confidence = confidence if isinstance(confidence, dict) else {}
    map_geojson = _logical(run_manifest, "map.geojson")
    anomaly_geojson = _logical(run_manifest, "anomalies.geojson")
    task_results = _task_results(results_root)
    stage_summaries = _stage_summaries(task_results)
    score_files = sum(item["present"] for item in task_results)
    complete_scores = sum(item["score_status"] == "complete" for item in task_results)
    all_hard_gates = (
        all(item["hard_gate_passed"] for item in task_results if item["present"])
        and score_files == 24
    )
    partial_scores = [
        float(item["descriptive_total_score"])
        for item in task_results
        if isinstance(item["descriptive_total_score"], (int, float))
    ]

    media = Counter(
        str(row.get("medium") or "unknown").casefold()
        for row in observations
        if isinstance(row, dict)
    )
    elements = {
        str(row.get("element"))
        for row in observations
        if isinstance(row, dict) and row.get("element")
    }
    locations: set[tuple[float, float]] = set()
    for row in observations:
        try:
            lat, lon = float(row.get("latitude")), float(row.get("longitude"))
        except (TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            locations.add((round(lat, 8), round(lon, 8)))
    normalized = sum(
        row.get("normalized_value") not in (None, "")
        and bool(row.get("normalized_unit"))
        for row in observations
        if isinstance(row, dict)
    )
    censored = sum(
        str(row.get("censored", "")).casefold() in {"true", "1", "yes"}
        for row in observations
        if isinstance(row, dict)
    )
    provenance = (
        sum(
            bool(row.get("record_id") and row.get("source_id"))
            for row in observations
            if isinstance(row, dict)
        )
        / len(observations)
        if observations
        else 0.0
    )
    map_metrics = _geojson_metrics(map_geojson)
    anomaly_metrics = _geojson_metrics(anomaly_geojson)
    directions = Counter()
    for feature in (
        anomaly_geojson.get("features", []) if isinstance(anomaly_geojson, dict) else []
    ):
        label = str(
            feature.get("properties", {}).get("anomaly_type", "unknown")
        ).casefold()
        directions[
            "high"
            if "enrich" in label or "high" in label
            else "low"
            if "deplet" in label or "low" in label
            else "unknown"
        ] += 1

    browser = load_json(args.browser_audit, {})
    screenshots_bound = _screenshots_verified(browser, args.browser_audit)
    map_html = q24 / "map.html"
    browser_bound = (
        browser.get("generated_by") == "external_evaluation_controller"
        and browser.get("html", {}).get("sha256") == sha256_file(map_html)
        and browser.get("html", {}).get("bytes")
        == (map_html.stat().st_size if map_html.is_file() else 0)
        and screenshots_bound
    )
    browser_pass = browser_bound and browser.get("status") == "pass"
    database_valid = _sqlite_valid(q24 / "geochemical.sqlite") and bool(observations)
    confidence_components = (
        confidence.get("components") if isinstance(confidence, dict) else None
    )
    confidence_valid = (
        isinstance(confidence_components, dict)
        and {
            "source_integrity",
            "normalization",
            "spatial",
            "quality_control",
            "provenance",
        }
        <= set(confidence_components)
        and "not a probability" in str(confidence.get("interpretation", "")).casefold()
    )
    source_valid = len(sources) == 2 and all(
        isinstance(item, dict)
        and item.get("source_id")
        and item.get("integrity_status")
        for item in sources
    )
    anomaly_valid = anomaly_metrics["valid"] and (q24 / "anomaly_results.csv").is_file()
    skill_path = args.skill_document
    skill_present = skill_path is not None and skill_path.is_file()
    reusable_skill = bool(
        skill_present and "name:" in skill_path.read_text(encoding="utf-8")[:1000]
    )
    four_runtime_usable = (
        database_valid
        and source_valid
        and confidence_valid
        and anomaly_valid
        and browser_pass
    )
    experiment_manifest = load_json(args.experiment_manifest, {})
    pair_fingerprint = (
        experiment_manifest.get("pair_fingerprint")
        if isinstance(experiment_manifest, dict)
        else None
    )
    eligible = bool(
        args.independent_session
        and args.blind_bundle
        and pair_fingerprint
        and score_files == 24
        and complete_scores == 24
        and all_hard_gates
        and four_runtime_usable
    )
    observed = (
        round(sum(partial_scores) / len(partial_scores), 6)
        if complete_scores == 24 and len(partial_scores) == 24
        else None
    )

    red_lines: list[dict[str, Any]] = []
    if complete_scores != 24:
        red_lines.append(
            {
                "code": "Q01_SCORE_DIMENSIONS_INCOMPLETE",
                "count": 24 - complete_scores,
                "severity": "error",
            }
        )
    if not browser_pass:
        red_lines.append({"code": "Q24_MAP_NOT_BROWSER_VERIFIED", "severity": "error"})
    if not confidence_valid:
        red_lines.append(
            {"code": "Q24_CONFIDENCE_EVIDENCE_MISSING", "severity": "error"}
        )
    missing_media = sorted(FOUR_MEDIA - set(media))
    if missing_media:
        red_lines.append(
            {
                "code": "Q24_IS_MICRO_FIXTURE_NOT_GLOBAL_COVERAGE",
                "missing": missing_media,
                "severity": "warning",
            }
        )

    return {
        "schema_version": "global-geochemical-evaluation-report-v1",
        "experiment": {
            "runtime": "q01-q24",
            "condition": args.condition,
            "run_id": args.run_id,
            "independent_agent_session": args.independent_session,
            "submission_dir": str(submissions),
            "submission_hashes": {
                name: sha256_file(q24 / name)
                for name in (
                    "observations.csv",
                    "geochemical.sqlite",
                    "map.html",
                    "anomalies.geojson",
                    "run_manifest.json",
                )
            },
            "manifest": experiment_manifest,
        },
        "fairness": {
            "candidate_never_saw_hidden_checker": args.blind_bundle,
            "external_browser_audit_hash_bound": browser_bound,
            "browser_screenshots_hash_bound": screenshots_bound,
            "eligible_run_component": eligible,
            "ineligibility_reasons": [
                reason
                for condition, reason in (
                    (not args.independent_session, "not an independent Agent session"),
                    (
                        not args.blind_bundle,
                        "candidate visibility boundary not attested",
                    ),
                    (not pair_fingerprint, "missing controller pair fingerprint"),
                    (score_files != 24, "not all 24 task reports are present"),
                    (complete_scores != 24, "one or more E1 task scores are partial"),
                    (not all_hard_gates, "one or more hard gates failed"),
                    (
                        not four_runtime_usable,
                        "Q24 final runtime deliverables are not all browser/science usable",
                    ),
                )
                if condition
            ],
            "three_run_requirement": "Aggregated B0/S0 result requires exactly three distinct run IDs per arm.",
        },
        "d1": {
            "measurement_records": len(observations),
            "unique_samples": None,
            "unique_sample_count_status": "not exposed by the Q24 logical observation contract",
            "unique_reported_locations": len(locations),
            "source_count": len(sources),
            "sources": sorted(
                str(item.get("source_id"))
                for item in sources
                if isinstance(item, dict) and item.get("source_id")
            ),
            "discovery_candidate_count": 0,
            "discovery_status_counts": {},
            "searched_platform_count": 0,
            "searched_platforms": [],
            "discovery_stop_reason": "Q24 is a frozen synthetic micro-fixture; it does not test global source discovery.",
            "remaining_candidate_count": 0,
            "media_counts": dict(sorted(media.items())),
            "missing_required_media": missing_media,
            "element_count": len(elements),
            "method_completeness": 0.0,
            "geology_completeness": 0.0,
            "coordinate_evidence_completeness": 0.0,
            "record_provenance_completeness": round(provenance, 6),
            "claim_boundary": "Q01-Q24 are scientific microtasks. Q24 validates a small end-to-end fixture and cannot establish global completeness or representativeness.",
            "coverage_report_artifact": artifact(
                q24 / "coverage_report.json",
                valid=False,
                usable=False,
                detail={"reason": "not required by Q24"},
            ),
        },
        "d2": {
            "input_records": int(qc.get("raw_input_rows", len(observations))),
            "output_records": len(observations),
            "row_preservation": int(qc.get("raw_input_rows", len(observations)))
            == len(observations) + int(qc.get("excluded_integrity_rows", 0)),
            "normalized_records": normalized,
            "normalization_rate": round(normalized / len(observations), 6)
            if observations
            else 0.0,
            "conversion_trace_records": 0,
            "conversion_trace_rate": 0.0,
            "explicit_unit_failure_records": 0,
            "inferred_unit_records": 0,
            "censored_records": censored,
            "canonical_coordinate_records": map_metrics["features"],
            "unique_canonical_locations": map_metrics["unique_locations"],
            "geology_context_records": 0,
            "geology_context_rate": 0.0,
            "provenance_continuity_rate": round(provenance, 6),
            "qc_flag_counts": {},
            "confidence_band_counts": {str(confidence.get("band", "missing")): 1},
            "confidence_interpretation": confidence.get(
                "interpretation", "not_reported"
            ),
            "anomaly_candidates": anomaly_metrics["features"],
            "anomaly_directions": dict(sorted(directions.items())),
            "anomaly_method": "log10 median + 1.4826*MAD; |z|>=3.5",
        },
        "d3": {
            "browser_audit": browser,
            "browser_audit_bound": browser_bound,
            "browser_screenshots_hash_bound": screenshots_bound,
            "browser_usable": browser_pass,
            "map_measurement_features": map_metrics["features"],
            "map_unique_locations": map_metrics["unique_locations"],
            "samples_geojson_valid": map_metrics["valid"],
            "measurement_vs_location_semantics": "Feature and observation counts are analyte determinations; unique locations are reported separately.",
        },
        "deliverables": {
            "interactive_map": artifact(
                map_html,
                valid=map_html.is_file()
                and "<html"
                in map_html.read_text(encoding="utf-8", errors="ignore").casefold(),
                usable=browser_pass,
                detail={
                    "browser_status": browser.get("status", "not_run"),
                    "surface": "Q24 micro-fixture",
                },
            ),
            "standardized_database": artifact(
                q24 / "geochemical.sqlite",
                valid=database_valid,
                usable=database_valid and normalized > 0,
                detail={
                    "records": len(observations),
                    "unique_locations": len(locations),
                },
            ),
            "sources_and_confidence": artifact(
                q24 / "sources.jsonl",
                valid=source_valid and confidence_valid,
                usable=source_valid and confidence_valid,
                detail={
                    "source_rows": len(sources),
                    "confidence_present": bool(confidence),
                    "confidence_valid": confidence_valid,
                },
            ),
            "anomaly_results": artifact(
                q24 / "anomalies.geojson",
                valid=anomaly_valid,
                usable=anomaly_valid,
                detail={
                    "features": anomaly_metrics["features"],
                    "directions": dict(directions),
                },
            ),
            "reusable_skill_document": artifact(
                skill_path or Path("SKILL.md"),
                valid=reusable_skill,
                usable=reusable_skill and skill_path.stat().st_size > 3000
                if skill_present
                else False,
                detail={"condition": args.condition},
            ),
        },
        "score": {
            "observed": observed,
            "maximum": 100,
            "ceiling_saturated": args.condition == "B0"
            and isinstance(observed, (int, float))
            and observed >= 90,
            "source": str(results_root),
            "descriptive_partial_mean": round(
                sum(partial_scores) / len(partial_scores), 6
            )
            if partial_scores
            else None,
            "complete_score_count": complete_scores,
            "task_report_count": score_files,
        },
        "benchmark": {
            "scope": "candidate-visible scientific microtask regression",
            "question_count": 24,
            "task_report_count": score_files,
            "complete_score_count": complete_scores,
            "all_hard_gates_passed": all_hard_gates,
            "stage_summaries": stage_summaries,
            "task_results": task_results,
            "product_question": "Q24",
            "product_gate_usable": four_runtime_usable,
            "claim_boundary": "Partial per-task totals and their mean are descriptive diagnostics, not a formal six-dimension competition score or Skill uplift estimate.",
        },
        "scientific_red_lines": red_lines,
    }
