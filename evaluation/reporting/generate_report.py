#!/usr/bin/env python3
"""Generate one deterministic report shape for every evaluation surface."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "global-geochemical-evaluation-report-v1"
FOUR_MEDIA = {"rock", "soil", "sediment", "water"}


def load_json(path: Path | None, default: Any) -> Any:
    if path is None or not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nonblank(row: dict[str, str], field: str) -> bool:
    return bool((row.get(field) or "").strip())


def rate(rows: list[dict[str, str]], fields: Iterable[str]) -> float:
    fields = tuple(fields)
    if not rows or not fields:
        return 0.0
    return round(
        sum(all(nonblank(row, field) for field in fields) for row in rows) / len(rows), 6
    )


def any_field_rate(rows: list[dict[str, str]], fields: Iterable[str]) -> float:
    fields = tuple(fields)
    if not rows or not fields:
        return 0.0
    return round(
        sum(any(nonblank(row, field) for field in fields) for row in rows) / len(rows), 6
    )


def json_cell(value: str, expected: type) -> Any:
    try:
        parsed = json.loads(value or "null")
    except json.JSONDecodeError:
        return expected()
    return parsed if isinstance(parsed, expected) else expected()


def coordinate(row: dict[str, str], original: bool = False) -> tuple[float, float] | None:
    lat_field = "original_latitude_raw" if original else "latitude"
    lon_field = "original_longitude_raw" if original else "longitude"
    try:
        lat, lon = float(row[lat_field]), float(row[lon_field])
    except (KeyError, TypeError, ValueError):
        return None
    if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
        return round(lat, 8), round(lon, 8)
    return None


def reported_coordinate(row: dict[str, str]) -> tuple[float, float] | None:
    """Prefer preserved source coordinates, falling back to legacy D1 latitude/longitude columns."""
    return coordinate(row, original=True) or coordinate(row, original=False)


def geojson_metrics(path: Path) -> dict[str, Any]:
    value = load_json(path, {})
    features = value.get("features") if isinstance(value, dict) else None
    if value.get("type") != "FeatureCollection" or not isinstance(features, list):
        return {"valid": False, "measurement_features": 0, "unique_locations": 0}
    locations: set[tuple[float, float]] = set()
    valid = True
    for feature in features:
        try:
            coordinates = feature["geometry"]["coordinates"]
            lon, lat = round(float(coordinates[0]), 8), round(float(coordinates[1]), 8)
        except (KeyError, TypeError, ValueError, IndexError):
            valid = False
            continue
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            valid = False
        else:
            locations.add((lat, lon))
    return {
        "valid": valid,
        "measurement_features": len(features),
        "unique_locations": len(locations),
    }


def artifact(path: Path, *, valid: bool, usable: bool, detail: Any = None) -> dict[str, Any]:
    return {
        "present": path.is_file() and path.stat().st_size > 0,
        "valid": bool(valid),
        "usable": bool(usable),
        "filename": path.name,
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path),
        "detail": detail,
    }


def browser_screenshots_verified(audit: dict[str, Any], audit_path: Path | None) -> bool:
    if audit_path is None or not audit_path.is_file():
        return False
    directory = audit.get("screenshot_directory")
    screenshots = audit.get("screenshots")
    if (
        not isinstance(directory, str)
        or Path(directory).name != directory
        or not isinstance(screenshots, list)
        or len(screenshots) < 5
    ):
        return False
    root = audit_path.parent / directory
    for item in screenshots:
        if not isinstance(item, dict):
            return False
        filename = item.get("file")
        path = root / str(filename or "")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not path.is_file()
            or path.stat().st_size != item.get("bytes")
            or sha256_file(path) != item.get("sha256")
        ):
            return False
    return True


def anomaly_direction(value: Any) -> str:
    folded = str(value or "unknown").casefold()
    if "high" in folded or "enrich" in folded or "富集" in folded:
        return "high"
    if "low" in folded or "deplet" in folded or "亏损" in folded:
        return "low"
    return folded


def build(args: argparse.Namespace) -> dict[str, Any]:
    root = args.submission_dir
    d1 = read_csv(root / "d1_raw.csv")
    d2 = read_csv(root / "geochemistry.csv")
    qc = load_json(root / "qc_report.json", {})
    confidence = load_json(root / "confidence_report.json", {})
    source_manifest = load_json(root / "source_manifest.json", {})
    discovery = load_json(root / "discovery_report.json", {})
    coverage_report = load_json(root / "coverage_report.json", {})
    anomaly = load_json(root / "anomalies.geojson", {})
    anomaly_report = load_json(root / "anomaly_report.json", {})
    score_data = load_json(args.score, {})
    browser = load_json(args.browser_audit, {})
    experiment_manifest = load_json(args.experiment_manifest, {})
    sample_metrics = geojson_metrics(root / "samples.geojson")

    d1_media = Counter((row.get("medium") or "unknown").strip() for row in d1)
    d1_elements = Counter((row.get("element_or_analyte") or "unknown").strip() for row in d1)
    source_ids = {(row.get("source_id") or "").strip() for row in d1 if nonblank(row, "source_id")}
    samples = {
        ((row.get("source_id") or "").strip(), (row.get("sample_id") or "").strip())
        for row in d1 if nonblank(row, "sample_id")
    }
    reported_locations = {value for row in d1 if (value := reported_coordinate(row))}
    discovery_candidates = discovery.get("candidates") if isinstance(discovery, dict) else []
    discovery_candidates = discovery_candidates if isinstance(discovery_candidates, list) else []
    discovery_status = Counter(
        str(item.get("status") or "unknown").casefold()
        for item in discovery_candidates if isinstance(item, dict)
    )
    discovery_platforms = {
        str(item.get("platform") or "").strip()
        for item in discovery_candidates
        if isinstance(item, dict) and str(item.get("platform") or "").strip()
    }

    flag_counts: Counter[str] = Counter()
    confidence_bands: Counter[str] = Counter()
    inferred_units = 0
    explicit_failures = 0
    censored = 0
    for row in d2:
        flags = {str(value) for value in json_cell(row.get("qc_flags", ""), list)}
        flag_counts.update(flags)
        inferred_units += any("INFER" in flag.upper() and "UNIT" in flag.upper() for flag in flags)
        explicit_failures += any(
            token in flag.upper() for flag in flags
            for token in ("UNSUPPORTED_UNIT", "AMBIGUOUS_AQUEOUS", "UNSUPPORTED_MOLAR")
        )
        censored += (row.get("censored") or "").strip().casefold() in {"true", "1", "yes"}
        operational = json_cell(row.get("operational_confidence", ""), dict)
        confidence_bands[str(operational.get("band") or "unknown")] += 1

    canonical_locations = {value for row in d2 if (value := coordinate(row))}
    normalized = sum(nonblank(row, "normalized_value") and nonblank(row, "normalized_unit") for row in d2)
    conversion_trace = sum(
        nonblank(row, "conversion_factor") and nonblank(row, "conversion_formula")
        for row in d2 if nonblank(row, "normalized_value")
    )
    geology = sum(
        any(nonblank(row, field) for field in ("matched_geologic_unit", "geologic_unit", "geologic_unit_raw"))
        for row in d2
    )
    provenance = rate(d2, ("source_id", "source_locator", "file_sha256"))
    directions = Counter(
        anomaly_direction(item.get("properties", {}).get("direction"))
        for item in anomaly.get("features", []) if isinstance(item, dict)
    ) if isinstance(anomaly, dict) else Counter()

    screenshot_evidence_bound = browser_screenshots_verified(browser, args.browser_audit)
    browser_bound = (
        browser.get("schema_version") == "geochemical-browser-audit-v1"
        and browser.get("generated_by") == "external_evaluation_controller"
        and browser.get("html", {}).get("sha256") == sha256_file(root / "interactive_map.html")
        and browser.get("html", {}).get("bytes")
        == ((root / "interactive_map.html").stat().st_size if (root / "interactive_map.html").is_file() else 0)
        and screenshot_evidence_bound
    )
    browser_pass = browser_bound and browser.get("status") == "pass"
    score = score_data.get("score") if isinstance(score_data, dict) else None
    red_lines: list[dict[str, Any]] = []
    if inferred_units:
        red_lines.append({"code": "UNIT_INFERENCE", "count": inferred_units, "severity": "error"})
    missing_media = sorted(FOUR_MEDIA - set(d1_media))
    if missing_media:
        red_lines.append({"code": "FOUR_MEDIA_INCOMPLETE", "missing": missing_media, "severity": "error"})
    if not browser_pass:
        red_lines.append({"code": "D3_NOT_BROWSER_VERIFIED", "severity": "error"})
    if canonical_locations and len(canonical_locations) < 100:
        red_lines.append({"code": "SPARSE_UNIQUE_MAP_LOCATIONS", "count": len(canonical_locations), "severity": "warning"})

    database_valid = bool(d2) and len({row.get("record_id") for row in d2}) == len(d2)
    source_valid = (
        (root / "source_manifest.json").is_file()
        and isinstance(source_manifest, dict) and isinstance(source_manifest.get("sources"), list)
        and isinstance(confidence, dict) and bool(confidence)
        and provenance == 1.0
    )
    anomaly_valid = (
        isinstance(anomaly, dict) and anomaly.get("type") == "FeatureCollection"
        and isinstance(anomaly.get("features"), list)
        and isinstance(anomaly_report, dict)
    )
    skill_path = args.skill_document
    skill_present = skill_path is not None and skill_path.is_file()

    return {
        "schema_version": SCHEMA_VERSION,
        "experiment": {
            "runtime": args.runtime,
            "condition": args.condition,
            "run_id": args.run_id,
            "independent_agent_session": args.independent_session,
            "submission_dir": str(root.resolve()),
            "submission_hashes": {
                name: sha256_file(root / name)
                for name in ("d1_raw.csv", "geochemistry.csv", "interactive_map.html")
            },
            "manifest": experiment_manifest,
        },
        "fairness": {
            "candidate_never_saw_hidden_checker": args.blind_bundle,
            "external_browser_audit_hash_bound": browser_bound,
            "browser_screenshots_hash_bound": screenshot_evidence_bound,
            "eligible_run_component": bool(
                args.independent_session and args.blind_bundle and browser_bound
            ),
            "three_run_requirement": "Aggregated B0/S0 result requires exactly three distinct run IDs per arm.",
        },
        "d1": {
            "measurement_records": len(d1),
            "unique_samples": len(samples),
            "unique_reported_locations": len(reported_locations),
            "source_count": len(source_ids),
            "sources": sorted(source_ids),
            "discovery_candidate_count": len(discovery_candidates),
            "discovery_status_counts": dict(sorted(discovery_status.items())),
            "searched_platform_count": len(discovery_platforms),
            "searched_platforms": sorted(discovery_platforms),
            "discovery_stop_reason": discovery.get("stop_reason") if isinstance(discovery, dict) else None,
            "remaining_candidate_count": len(discovery.get("remaining_candidates", []))
            if isinstance(discovery, dict) and isinstance(discovery.get("remaining_candidates"), list) else 0,
            "media_counts": dict(sorted(d1_media.items())),
            "missing_required_media": missing_media,
            "element_count": len(d1_elements),
            "method_completeness": any_field_rate(
                d1, ("analytical_method", "analytical_technique", "method_family")
            ),
            "geology_completeness": any_field_rate(
                d1, ("geologic_unit_raw", "geologic_unit", "matched_geologic_unit", "lithology_raw")
            ),
            "coordinate_evidence_completeness": any_field_rate(
                d1, ("source_crs", "coordinate_evidence_scope", "coordinate_policy_id")
            ),
            "record_provenance_completeness": rate(
                d1, ("source_id", "source_locator", "file_sha256", "license")
            ),
            "claim_boundary": "Counts measure observed inputs, not global completeness or representativeness.",
            "coverage_report_artifact": artifact(
                root / "coverage_report.json",
                valid=isinstance(coverage_report, dict) and bool(coverage_report),
                usable=isinstance(coverage_report, dict)
                and any(key in coverage_report for key in ("coverage_gaps", "by_region", "by_source")),
                detail={
                    "declared_gap_count": len(coverage_report.get("coverage_gaps", []))
                    if isinstance(coverage_report, dict)
                    and isinstance(coverage_report.get("coverage_gaps"), list) else None,
                },
            ),
        },
        "d2": {
            "input_records": len(d1),
            "output_records": len(d2),
            "row_preservation": len(d1) == len(d2) and bool(d2),
            "normalized_records": normalized,
            "normalization_rate": round(normalized / len(d2), 6) if d2 else 0.0,
            "conversion_trace_records": conversion_trace,
            "conversion_trace_rate": round(conversion_trace / normalized, 6) if normalized else 0.0,
            "explicit_unit_failure_records": explicit_failures,
            "inferred_unit_records": inferred_units,
            "censored_records": censored,
            "canonical_coordinate_records": sum(coordinate(row) is not None for row in d2),
            "unique_canonical_locations": len(canonical_locations),
            "geology_context_records": geology,
            "geology_context_rate": round(geology / len(d2), 6) if d2 else 0.0,
            "provenance_continuity_rate": provenance,
            "qc_flag_counts": dict(sorted(flag_counts.items())),
            "confidence_band_counts": dict(sorted(confidence_bands.items())),
            "confidence_interpretation": confidence.get("interpretation")
            or confidence.get("not_a_probability")
            or "not_reported",
            "anomaly_candidates": sum(directions.values()),
            "anomaly_directions": dict(sorted(directions.items())),
            "anomaly_method": anomaly_report.get("method_version"),
        },
        "d3": {
            "browser_audit": browser,
            "browser_audit_bound": browser_bound,
            "browser_screenshots_hash_bound": screenshot_evidence_bound,
            "browser_usable": browser_pass,
            "map_measurement_features": sample_metrics["measurement_features"],
            "map_unique_locations": sample_metrics["unique_locations"],
            "samples_geojson_valid": sample_metrics["valid"],
            "measurement_vs_location_semantics": (
                "Feature and database row counts are analyte determinations; unique locations are reported separately."
            ),
        },
        "deliverables": {
            "interactive_map": artifact(
                root / "interactive_map.html", valid=browser_bound and browser.get("loaded") is True,
                usable=browser_pass, detail={"browser_status": browser.get("status", "not_run")},
            ),
            "standardized_database": artifact(
                root / "geochemistry.csv", valid=database_valid,
                usable=database_valid and normalized > 0,
                detail={"records": len(d2), "unique_locations": len(canonical_locations)},
            ),
            "sources_and_confidence": artifact(
                root / "source_manifest.json", valid=source_valid,
                usable=source_valid and bool(confidence), detail={"provenance_rate": provenance},
            ),
            "anomaly_results": artifact(
                root / "anomalies.geojson", valid=anomaly_valid,
                usable=anomaly_valid and "screen" in json.dumps(anomaly_report).casefold(),
                detail={"directions": dict(directions)},
            ),
            "reusable_skill_document": artifact(
                skill_path or Path("SKILL.md"), valid=skill_present and "name:" in skill_path.read_text(encoding="utf-8")[:1000] if skill_present else False,
                usable=skill_present and skill_path.stat().st_size > 3000 if skill_present else False,
            ),
        },
        "score": {
            "observed": score,
            "maximum": score_data.get("maximum", 100) if isinstance(score_data, dict) else 100,
            "ceiling_saturated": (
                args.condition == "B0" and isinstance(score, (int, float)) and score >= 90
            ),
            "source": str(args.score) if args.score else None,
        },
        "scientific_red_lines": red_lines,
    }


def render(report: dict[str, Any]) -> str:
    exp, d1, d2, d3 = report["experiment"], report["d1"], report["d2"], report["d3"]
    lines = [
        "# 全球地球化学图谱统一评测报告", "",
        f"- 运行：`{exp['runtime']}` / `{exp['condition']}` / `{exp['run_id']}`",
        f"- 独立 Agent 会话：`{str(exp['independent_agent_session']).lower()}`",
        f"- 观测分：`{report['score']['observed']}`；天花板饱和：`{str(report['score']['ceiling_saturated']).lower()}`",
        "", "## D1 采集与覆盖", "",
        "| 测定记录 | 唯一样品 | 唯一坐标 | 来源 | 元素 | 四介质缺口 |",
        "|---:|---:|---:|---:|---:|---|",
        f"| {d1['measurement_records']} | {d1['unique_samples']} | {d1['unique_reported_locations']} | {d1['source_count']} | {d1['element_count']} | {', '.join(d1['missing_required_media']) or '无'} |",
        f"- 来源发现：候选 `{d1['discovery_candidate_count']}`，平台 `{d1['searched_platform_count']}`，状态 `{d1['discovery_status_counts']}`，停止原因 `{d1['discovery_stop_reason']}`。",
        f"- 字段完整率：方法 `{d1['method_completeness']:.1%}`，地质背景 `{d1['geology_completeness']:.1%}`，坐标证据 `{d1['coordinate_evidence_completeness']:.1%}`，记录级来源 `{d1['record_provenance_completeness']:.1%}`。",
        "", "## D2 标准化与科学处理", "",
        "| 输入/输出 | 标准化 | 单位推断 | 显式失败 | canonical 坐标 | 唯一位置 | 地质覆盖 | 异常 high/low |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
        f"| {d2['input_records']}/{d2['output_records']} | {d2['normalized_records']} | {d2['inferred_unit_records']} | {d2['explicit_unit_failure_records']} | {d2['canonical_coordinate_records']} | {d2['unique_canonical_locations']} | {d2['geology_context_records']} | {d2['anomaly_directions']} |",
        "", "## D3 浏览器实测", "",
        f"- 浏览器验收：`{d3['browser_audit'].get('status', 'not_run')}`（哈希绑定：`{str(d3['browser_audit_bound']).lower()}`）",
        f"- 上图测定 feature：`{d3['map_measurement_features']}`；唯一地图位置：`{d3['map_unique_locations']}`",
        "", "## 五项产物", "",
        "| 产物 | present | valid | usable |",
        "|---|---:|---:|---:|",
    ]
    labels = {
        "interactive_map": "可交互元素分布地图",
        "standardized_database": "标准化地球化学数据库",
        "sources_and_confidence": "数据来源与置信度说明",
        "anomaly_results": "异常区域识别结果",
        "reusable_skill_document": "可复用 Skill 文档",
    }
    for key, label in labels.items():
        item = report["deliverables"][key]
        lines.append(f"| {label} | {item['present']} | {item['valid']} | {item['usable']} |")
    lines.extend(["", "## 科学红线", ""])
    if report["scientific_red_lines"]:
        lines.extend(f"- `{item['code']}`：{item}" for item in report["scientific_red_lines"])
    else:
        lines.append("- 未触发机器可见红线；这不替代领域专家复核。")
    lines.extend([
        "", "> 本报告把测定记录、物理样品和唯一地图位置分开统计；记录多不等于全球覆盖完整。", "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate unified machine and Markdown evaluation reports.")
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--runtime", choices=("q01-q24", "host-uplift", "docker-uplift"), required=True)
    parser.add_argument("--condition", choices=("B0", "S0"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--independent-session", action="store_true")
    parser.add_argument("--blind-bundle", action="store_true")
    parser.add_argument("--score", type=Path)
    parser.add_argument("--browser-audit", type=Path)
    parser.add_argument("--experiment-manifest", type=Path)
    parser.add_argument("--skill-document", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()
    report = build(args)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.output_md.write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": "generated", "red_lines": len(report["scientific_red_lines"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
