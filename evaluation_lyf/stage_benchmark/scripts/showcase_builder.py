#!/usr/bin/env python3
"""Build polished, dependency-free evaluation deliverables from public D2 outputs.

The showcase is deliberately a consumer rather than a second scientific
pipeline.  It preserves D2 point-level decisions, aggregates candidate points
into explicitly labelled screening grids, and never presents operational
confidence as probability or grid cells as geological boundaries.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_common import LAB_ROOT, atomic_write_json, atomic_write_text, load_json, sha256_file

SHOWCASE_VERSION = "d3-evaluation-showcase-v3"
ANOMALY_REGION_VERSION = "d3-fixed-grid-screening-v1"
GRID_DEGREES = 2.0
MINIMUM_REGION_ANOMALIES = 3
MINIMUM_REGION_OBSERVATIONS = 10
BASEMAP_PATH = LAB_ROOT / "assets" / "natural-earth-110m-land.json"
BASEMAP_ASSET_VERSION = "ai4s-natural-earth-land-v1"


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).replace(
        "</", "<\\/"
    )


def optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def rounded(value: float | None, digits: int = 6) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def basemap_payload() -> dict[str, Any]:
    payload = load_json(BASEMAP_PATH)
    if (
        payload.get("asset_version") != BASEMAP_ASSET_VERSION
        or payload.get("license") != "public domain"
        or not payload.get("rings")
    ):
        raise ValueError(f"invalid offline basemap asset: {BASEMAP_PATH}")
    return {
        "asset_version": payload["asset_version"],
        "title": payload["title"],
        "natural_earth_version": payload["natural_earth_version"],
        "scale": payload["scale"],
        "coordinate_reference_system": payload["coordinate_reference_system"],
        "source_page": payload["source_page"],
        "license": payload["license"],
        "archive_sha256": payload["archive_sha256"],
        "rings": payload["rings"],
    }


def source_confidence_summary(
    database: Sequence[Mapping[str, Any]],
    confidence_report: Mapping[str, Any],
    qc_report: Mapping[str, Any],
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in database:
        grouped[str(row.get("source_id") or "unknown")].append(row)

    sources: list[dict[str, Any]] = []
    for source_id, rows in sorted(grouped.items()):
        confidence_rows = [
            row.get("operational_confidence")
            for row in rows
            if isinstance(row.get("operational_confidence"), dict)
        ]
        overall_values = [
            float(item["overall"])
            for item in confidence_rows
            if optional_float(item.get("overall")) is not None
        ]
        components: dict[str, float | None] = {}
        for name in ("source", "completeness", "method", "spatial", "qc"):
            values = [
                float(item[name])
                for item in confidence_rows
                if optional_float(item.get(name)) is not None
            ]
            components[name] = rounded(mean(values))

        flag_counts: Counter[str] = Counter()
        for row in rows:
            flags = row.get("qc_flags")
            if isinstance(flags, list):
                flag_counts.update(str(flag) for flag in flags)
        band_counts = Counter(
            str(item.get("band") or "unknown") for item in confidence_rows
        )
        source_files: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row.get("source_file") or ""), str(row.get("file_sha256") or ""))
            if key not in source_files:
                source_files[key] = {
                    "source_file": key[0] or None,
                    "sha256": key[1] or None,
                    "example_locator": row.get("source_locator"),
                }

        first = rows[0]
        sources.append(
            {
                "source_id": source_id,
                "dataset_title": first.get("dataset_title"),
                "dataset_doi": first.get("dataset_doi"),
                "dataset_version": first.get("dataset_version"),
                "license": first.get("license"),
                "source_tier": first.get("source_tier"),
                "media": sorted({str(row.get("medium")) for row in rows if row.get("medium")}),
                "record_count": len(rows),
                "normalized_count": sum(row.get("normalized_value") is not None for row in rows),
                "censored_count": sum(bool(row.get("censored")) for row in rows),
                "mappable_count": sum(
                    row.get("latitude") is not None and row.get("longitude") is not None
                    for row in rows
                ),
                "analytical_method_coverage": rounded(
                    sum(bool(row.get("analytical_method")) for row in rows) / len(rows)
                ),
                "digestion_coverage": rounded(
                    sum(bool(row.get("digestion_or_extraction")) for row in rows) / len(rows)
                ),
                "geologic_context_coverage": rounded(
                    sum(bool(row.get("geologic_unit")) for row in rows) / len(rows)
                ),
                "spatial_geology_match_coverage": rounded(
                    sum(row.get("spatial_geology_status") == "matched" for row in rows) / len(rows)
                ),
                "confidence": {
                    "median_overall": rounded(statistics.median(overall_values))
                    if overall_values
                    else None,
                    "mean_overall": rounded(mean(overall_values)),
                    "band_counts": dict(sorted(band_counts.items())),
                    "component_means": components,
                },
                "top_qc_flags": [
                    {"flag": flag, "count": count} for flag, count in flag_counts.most_common(8)
                ],
                "source_files": sorted(
                    source_files.values(), key=lambda item: str(item["source_file"])
                ),
            }
        )

    total = len(database)
    return {
        "report_version": "d3-source-confidence-v1",
        "showcase_version": SHOWCASE_VERSION,
        "scientific_status": "workflow_evidence_summary",
        "record_count": total,
        "source_count": len(sources),
        "sources": sources,
        "global_confidence": {
            "version": confidence_report.get("confidence_version"),
            "meaning": confidence_report.get("meaning"),
            "not_a_probability": confidence_report.get("not_a_probability"),
            "weights": confidence_report.get("weights"),
            "band_thresholds": confidence_report.get("band_thresholds"),
            "gates": confidence_report.get("gates"),
            "component_means": confidence_report.get("component_means"),
            "band_counts": confidence_report.get("band_counts"),
        },
        "quality": {
            "normalized_fraction": rounded(
                sum(row.get("normalized_value") is not None for row in database) / total
            )
            if total
            else None,
            "mappable_fraction": rounded(
                sum(
                    row.get("latitude") is not None and row.get("longitude") is not None
                    for row in database
                )
                / total
            )
            if total
            else None,
            "qc_flag_counts": qc_report.get("flag_counts", {}),
        },
        "interpretation_limits": [
            "Operational confidence measures workflow usability, not truth probability or analytical accuracy.",
            "Source-level means summarize this frozen evaluation slice and are not global data-quality rankings.",
            "Missing coordinates remain in the standardized database and are excluded from map geometry.",
        ],
    }


def grid_key(longitude: float, latitude: float, element: str, medium: str) -> tuple[Any, ...]:
    west = math.floor(longitude / GRID_DEGREES) * GRID_DEGREES
    south = math.floor(latitude / GRID_DEGREES) * GRID_DEGREES
    return element, medium, west, south


def anomaly_region_outputs(
    sample_features: Sequence[Mapping[str, Any]], anomaly_features: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    observation_counts: Counter[tuple[Any, ...]] = Counter()
    for feature in sample_features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        properties = feature.get("properties") or {}
        if len(coordinates) != 2:
            continue
        longitude = optional_float(coordinates[0])
        latitude = optional_float(coordinates[1])
        if longitude is None or latitude is None:
            continue
        observation_counts[
            grid_key(
                longitude,
                latitude,
                str(properties.get("element_or_analyte") or "unknown"),
                str(properties.get("medium") or "unknown"),
            )
        ] += 1

    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    unmappable_candidate_record_ids: list[str] = []
    for feature in anomaly_features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        properties = feature.get("properties") or {}
        if len(coordinates) != 2:
            record_id = properties.get("record_id")
            if record_id:
                unmappable_candidate_record_ids.append(str(record_id))
            continue
        longitude = optional_float(coordinates[0])
        latitude = optional_float(coordinates[1])
        if longitude is None or latitude is None:
            record_id = properties.get("record_id")
            if record_id:
                unmappable_candidate_record_ids.append(str(record_id))
            continue
        grouped[
            grid_key(
                longitude,
                latitude,
                str(properties.get("element_or_analyte") or "unknown"),
                str(properties.get("medium") or "unknown"),
            )
        ].append(feature)

    features: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for key, candidates in sorted(grouped.items(), key=lambda item: item[0]):
        element, medium, west, south = key
        east = west + GRID_DEGREES
        north = south + GRID_DEGREES
        observation_count = observation_counts[key]
        anomaly_count = len(candidates)
        status = (
            "candidate_cluster"
            if anomaly_count >= MINIMUM_REGION_ANOMALIES
            and observation_count >= MINIMUM_REGION_OBSERVATIONS
            else "isolated_candidate_cell"
        )
        status_counts[status] += 1
        properties = [feature.get("properties") or {} for feature in candidates]
        robust_z_values = [
            float(value)
            for value in (optional_float(item.get("robust_z")) for item in properties)
            if value is not None
        ]
        directions = Counter(str(item.get("direction") or "unknown") for item in properties)
        region_payload = f"{element}|{medium}|{west:.6f}|{south:.6f}"
        region_id = "region-" + hashlib.sha256(region_payload.encode()).hexdigest()[:12]
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]
                    ],
                },
                "properties": {
                    "region_id": region_id,
                    "status": status,
                    "element_or_analyte": element,
                    "medium": medium,
                    "grid_degrees": GRID_DEGREES,
                    "anomaly_count": anomaly_count,
                    "observation_count": observation_count,
                    "anomaly_fraction": rounded(anomaly_count / observation_count)
                    if observation_count
                    else None,
                    "direction_counts": dict(sorted(directions.items())),
                    "median_robust_z": rounded(statistics.median(robust_z_values))
                    if robust_z_values
                    else None,
                    "max_abs_robust_z": rounded(max(map(abs, robust_z_values)))
                    if robust_z_values
                    else None,
                    "source_ids": sorted(
                        {str(item.get("source_id")) for item in properties if item.get("source_id")}
                    ),
                    "group_ids": sorted(
                        {str(item.get("group_id")) for item in properties if item.get("group_id")}
                    ),
                    "record_ids": sorted(
                        {str(item.get("record_id")) for item in properties if item.get("record_id")}
                    ),
                    "method_version": properties[0].get("method_version") if properties else None,
                    "interpretation_limit": (
                        "Fixed-grid screening aggregation of candidate anomaly points; the polygon is not "
                        "a geological boundary and makes no causal, pollution, or mineralization claim."
                    ),
                },
            }
        )

    geojson = {
        "type": "FeatureCollection",
        "name": "candidate_anomaly_screening_regions",
        "showcase_version": SHOWCASE_VERSION,
        "method_version": ANOMALY_REGION_VERSION,
        "features": features,
    }
    report = {
        "report_version": "d3-anomaly-region-report-v1",
        "method_version": ANOMALY_REGION_VERSION,
        "scientific_status": "screening_only",
        "configuration": {
            "grid_degrees": GRID_DEGREES,
            "minimum_region_anomalies": MINIMUM_REGION_ANOMALIES,
            "minimum_region_observations": MINIMUM_REGION_OBSERVATIONS,
            "aggregation": "candidate points grouped by element, medium and fixed lon/lat grid",
        },
        "candidate_point_count": len(anomaly_features),
        "mappable_candidate_point_count": (
            len(anomaly_features) - len(unmappable_candidate_record_ids)
        ),
        "unmappable_candidate_point_count": len(unmappable_candidate_record_ids),
        "unmappable_candidate_record_ids": sorted(unmappable_candidate_record_ids),
        "region_cell_count": len(features),
        "status_counts": dict(sorted(status_counts.items())),
        "interpretation_limits": [
            "Cells are screening units, not geological or administrative regions.",
            "A candidate cluster is relative to the D2 background group and fixed thresholds only.",
            "Sampling density, source coverage and missing coordinates constrain apparent spatial patterns.",
            "No region establishes cause, contamination, mineralization or resource potential.",
        ],
    }
    return geojson, report


class StringPools:
    def __init__(self) -> None:
        self.values: dict[str, list[str]] = defaultdict(list)
        self.indices: dict[str, dict[str, int]] = defaultdict(dict)

    def index(self, name: str, value: Any) -> int:
        text = "" if value is None else str(value)
        existing = self.indices[name].get(text)
        if existing is not None:
            return existing
        index = len(self.values[name])
        self.values[name].append(text)
        self.indices[name][text] = index
        return index


def compact_map_payload(
    sample_features: Sequence[Mapping[str, Any]],
    anomaly_features: Sequence[Mapping[str, Any]],
    anomaly_regions: Mapping[str, Any],
    anomaly_region_report: Mapping[str, Any],
    source_summary: Mapping[str, Any],
    qc_report: Mapping[str, Any],
    anomaly_report: Mapping[str, Any],
    database: Sequence[Mapping[str, Any]],
    disclaimers: Sequence[str],
) -> dict[str, Any]:
    pools = StringPools()
    points: list[list[Any]] = []
    for feature in sample_features:
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        properties = feature.get("properties") or {}
        if len(coordinates) != 2:
            continue
        confidence = properties.get("operational_confidence") or {}
        flags = properties.get("qc_flags") or []
        points.append(
            [
                coordinates[0],
                coordinates[1],
                pools.index("element", properties.get("element_or_analyte")),
                pools.index("medium", properties.get("medium")),
                properties.get("normalized_value"),
                pools.index("unit", properties.get("normalized_unit")),
                1 if properties.get("censored") else 0,
                pools.index("band", confidence.get("band")),
                confidence.get("overall"),
                str(properties.get("record_id") or ""),
                str(properties.get("sample_id") or ""),
                pools.index("source", properties.get("source_id")),
                str(properties.get("source_locator") or ""),
                pools.index("qualifier", properties.get("value_qualifier")),
                [pools.index("flag", flag) for flag in flags],
                pools.index("method", properties.get("method_family")),
                pools.index("basis", properties.get("measurement_basis")),
                str(properties.get("original_value_raw") or ""),
                pools.index("original_unit", properties.get("original_unit")),
                pools.index(
                    "geology",
                    properties.get("spatial_geologic_unit") or properties.get("geologic_unit"),
                ),
                pools.index("geology_status", properties.get("spatial_geology_status")),
            ]
        )

    anomalies: list[list[Any]] = []
    for feature in anomaly_features:
        coordinates = (feature.get("geometry") or {}).get("coordinates") or []
        properties = feature.get("properties") or {}
        if len(coordinates) != 2:
            continue
        anomalies.append(
            [
                coordinates[0],
                coordinates[1],
                pools.index("element", properties.get("element_or_analyte")),
                pools.index("medium", properties.get("medium")),
                properties.get("normalized_value"),
                pools.index("unit", properties.get("normalized_unit")),
                properties.get("robust_z"),
                pools.index("direction", properties.get("direction")),
                str(properties.get("record_id") or ""),
                str(properties.get("sample_id") or ""),
                pools.index("source", properties.get("source_id")),
                str(properties.get("source_locator") or ""),
                pools.index("band", properties.get("operational_confidence_band")),
                str(properties.get("group_id") or ""),
                pools.index(
                    "geology",
                    properties.get("spatial_geologic_unit") or properties.get("geologic_unit"),
                ),
            ]
        )

    missing_rows = [
        row for row in database if row.get("latitude") is None or row.get("longitude") is None
    ]
    missing_by_source = Counter(str(row.get("source_id") or "unknown") for row in missing_rows)
    missing_by_medium = Counter(str(row.get("medium") or "unknown") for row in missing_rows)
    missing_examples = [
        {
            "record_id": row.get("record_id"),
            "source_id": row.get("source_id"),
            "medium": row.get("medium"),
            "element": row.get("element_or_analyte"),
            "original_value": row.get("original_value_raw"),
            "original_unit": row.get("original_unit"),
            "qc_flags": row.get("qc_flags"),
            "source_locator": row.get("source_locator"),
        }
        for row in missing_rows[:100]
    ]
    return {
        "version": SHOWCASE_VERSION,
        "basemap": basemap_payload(),
        "pools": dict(pools.values),
        "points": points,
        "anomalies": anomalies,
        "regions": anomaly_regions.get("features", []),
        "region_report": anomaly_region_report,
        "sources": source_summary,
        "quality": {
            "qc": qc_report,
            "anomaly": {
                "candidate_count": anomaly_report.get("candidate_count"),
                "group_by": anomaly_report.get("group_by"),
                "caveat": anomaly_report.get("caveat"),
                "groups": anomaly_report.get("groups", []),
            },
            "missing_coordinates": {
                "count": len(missing_rows),
                "by_source": dict(sorted(missing_by_source.items())),
                "by_medium": dict(sorted(missing_by_medium.items())),
                "examples": missing_examples,
                "examples_truncated": len(missing_rows) > len(missing_examples),
            },
        },
        "disclaimers": list(disclaimers),
    }


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全球地球化学元素图谱 · 真实数据评测</title>
<style>
:root{--ink:#102a31;--muted:#6b7e83;--paper:#edf3f2;--card:#fff;--line:#d8e4e3;--deep:#071c26;--teal:#087d83;--cyan:#41e6d3;--mint:#78e6bf;--gold:#f4c15d;--red:#ff667a;--blue:#54a7ff;--shadow:0 20px 55px rgba(6,34,43,.12);font-family:Inter,"Noto Sans SC","PingFang SC",system-ui,sans-serif;color:var(--ink);background:var(--paper)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 82% 0,#d6eee9 0,transparent 29rem),linear-gradient(180deg,#f6f9f8,#edf3f2 52%,#e8efee)}button,select,input{font:inherit}.hero{background:radial-gradient(circle at 84% -40%,rgba(64,230,211,.24),transparent 31rem),linear-gradient(123deg,#04171f,#07313c 58%,#07545b);color:#fff;padding:38px max(24px,calc((100vw - 1580px)/2));position:relative;overflow:hidden}.hero:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(108,245,224,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(108,245,224,.035) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(90deg,transparent,black 70%)}.hero:after{content:"";position:absolute;width:430px;height:430px;border:1px solid rgba(93,247,224,.18);border-radius:50%;right:-78px;top:-270px;box-shadow:0 0 0 72px rgba(66,225,209,.045),0 0 0 144px rgba(66,225,209,.018)}.eyebrow{font-size:12px;letter-spacing:.21em;text-transform:uppercase;color:#82f2dc;font-weight:850;position:relative;z-index:1}.hero h1{font-size:clamp(31px,4vw,56px);letter-spacing:-.035em;line-height:1.02;margin:11px 0 13px;max-width:960px;position:relative;z-index:1;text-shadow:0 10px 35px rgba(0,0,0,.18)}.hero p{max-width:950px;color:#d8efed;font-size:15px;line-height:1.75;margin:0;position:relative;z-index:1}.deliverables{display:flex;gap:10px;flex-wrap:wrap;margin-top:23px;position:relative;z-index:2}.deliverables a{color:#effffc;text-decoration:none;border:1px solid rgba(110,245,224,.26);background:rgba(5,28,36,.32);padding:9px 13px;border-radius:999px;font-size:13px;backdrop-filter:blur(7px);transition:.18s ease}.deliverables a:hover{background:rgba(69,226,209,.17);border-color:rgba(110,245,224,.55);transform:translateY(-1px)}
.shell{max-width:1580px;margin:0 auto;padding:22px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 15px}.tab{border:1px solid var(--line);background:rgba(255,255,255,.9);color:var(--ink);padding:10px 15px;border-radius:11px;cursor:pointer;font-weight:750;box-shadow:0 6px 18px rgba(8,43,51,.04);transition:.18s ease}.tab:hover{border-color:#9bcac6;transform:translateY(-1px)}.tab.active{background:linear-gradient(135deg,#092c36,#07525a);color:#fff;border-color:#07525a;box-shadow:0 8px 22px rgba(5,80,88,.18)}.view{display:none}.view.active{display:block}.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:14px}.kpi{background:linear-gradient(145deg,#fff,#f8fbfa);border:1px solid var(--line);border-radius:16px;padding:15px 16px;box-shadow:0 9px 25px rgba(13,47,45,.055);position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;inset:auto 0 0;height:3px;background:linear-gradient(90deg,#13a7a7,#68e6c6);opacity:.68}.kpi .label{font-size:11px;color:var(--muted);font-weight:780;letter-spacing:.02em}.kpi strong{display:block;font-size:26px;margin-top:4px;letter-spacing:-.025em}.grid{display:grid;grid-template-columns:minmax(0,2.35fr) minmax(300px,.65fr);gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);overflow:hidden}.card-head{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid var(--line)}.card-head h2,.card-head h3{font-size:15px;margin:0}.card-body{padding:16px}.controls{display:flex;gap:9px;flex-wrap:wrap;align-items:end}.control{display:grid;gap:5px;font-size:11px;color:var(--muted);font-weight:760}.control select,.control input{border:1px solid var(--line);background:#fff;border-radius:9px;padding:8px 9px;color:var(--ink);min-width:115px;outline:none}.control select:focus,.control input:focus{border-color:#39b8ad;box-shadow:0 0 0 3px rgba(57,184,173,.12)}.layer-row{display:flex;gap:7px;flex-wrap:wrap}.chip{border:1px solid var(--line);background:#fff;padding:7px 10px;border-radius:999px;cursor:pointer;font-size:11px;font-weight:720;transition:.16s ease}.chip:hover{transform:translateY(-1px)}.chip.active{background:#dff7f1;border-color:#73d5c3;color:#075f62}.map-card{border-color:#173f4a;background:#071c26;box-shadow:0 24px 65px rgba(4,27,36,.24)}.map-card .card-head{background:linear-gradient(135deg,#092631,#0a3640);border-color:rgba(111,225,214,.15)}.map-card .control{color:#9cc2c3}.map-card .control select{background:#0c3039;border-color:#27505a;color:#effffc;color-scheme:dark}.map-card .chip{background:#0d303a;border-color:#28505b;color:#bcd5d5}.map-card .chip.active{background:rgba(48,220,198,.14);border-color:#39b9aa;color:#8df4df;box-shadow:0 0 15px rgba(48,220,198,.08)}.map-wrap{height:590px;position:relative;isolation:isolate;background:#061923;overflow:hidden}.map-wrap:after{content:"";position:absolute;inset:0;pointer-events:none;box-shadow:inset 0 0 70px rgba(0,0,0,.38);z-index:3}#map{width:100%;height:100%;display:block;cursor:grab;position:relative;z-index:1}#map.dragging{cursor:grabbing}.map-note{position:absolute;left:14px;bottom:13px;background:rgba(5,24,33,.82);border:1px solid rgba(116,229,215,.22);border-radius:9px;padding:7px 10px;font-size:10px;color:#a9c9c9;pointer-events:none;z-index:5;backdrop-filter:blur(8px)}.map-badge{position:absolute;left:14px;top:13px;display:flex;align-items:center;gap:7px;background:rgba(4,23,31,.78);border:1px solid rgba(117,237,220,.24);border-radius:999px;padding:7px 10px;color:#b8d9d7;font-size:10px;letter-spacing:.08em;z-index:5;backdrop-filter:blur(8px);pointer-events:none}.map-badge i{width:7px;height:7px;border-radius:50%;background:#4df3d2;box-shadow:0 0 12px #4df3d2}.map-badge b{color:#71f3dc}.map-coordinates{position:absolute;right:14px;bottom:13px;min-width:205px;text-align:right;background:rgba(4,23,31,.78);border:1px solid rgba(117,237,220,.2);border-radius:9px;padding:7px 10px;color:#b7d4d4;font:10px ui-monospace,SFMono-Regular,Menlo,monospace;z-index:5;backdrop-filter:blur(8px);pointer-events:none}.map-credit{position:absolute;right:14px;top:13px;color:rgba(187,218,217,.72);font-size:9px;letter-spacing:.04em;z-index:5;pointer-events:none}.compass{position:absolute;right:16px;top:39px;width:34px;height:34px;border:1px solid rgba(124,231,219,.24);border-radius:50%;display:grid;place-items:center;color:#80ead8;font-size:10px;font-weight:850;z-index:5;pointer-events:none;background:rgba(4,23,31,.55);box-shadow:0 0 20px rgba(50,218,199,.08)}.compass:after{content:"";position:absolute;top:5px;width:2px;height:11px;background:#71f3dc;clip-path:polygon(50% 0,100% 100%,0 100%)}.tooltip{position:absolute;display:none;pointer-events:none;background:rgba(4,22,31,.94);color:#f2fffd;padding:9px 11px;border:1px solid rgba(93,231,212,.32);border-radius:9px;font-size:11px;box-shadow:0 16px 34px rgba(0,0,0,.3),0 0 24px rgba(55,220,199,.08);max-width:270px;z-index:7;backdrop-filter:blur(8px)}.map-card .card-body{background:linear-gradient(180deg,#091f29,#071b24);border-top:1px solid rgba(111,225,214,.12)}.legend{height:10px;border-radius:999px;background:linear-gradient(90deg,#4777ff,#30d7e8,#43efbd,#ffe15c,#ff647e);margin:5px 0 4px;box-shadow:0 0 17px rgba(48,215,232,.14)}.legend-labels{display:flex;justify-content:space-between;font-size:10px;color:#9ebcbd}.symbol-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;color:#9dbabb;font-size:10px}.symbol-legend span{display:flex;align-items:center;gap:6px}.symbol-legend i{width:8px;height:8px;border-radius:50%;display:inline-block}.symbol-legend .normal{background:#49ebc5;box-shadow:0 0 8px #49ebc5}.symbol-legend .censored{background:transparent;border:1.5px solid #cb91ff}.symbol-legend .high-anomaly{background:#ff637b;box-shadow:0 0 9px #ff637b}.symbol-legend .low-anomaly{background:#5caeff;box-shadow:0 0 9px #5caeff}.detail-empty{color:var(--muted);line-height:1.7}.record-title{font-weight:850;font-size:17px;overflow-wrap:anywhere}.value{font-size:28px;font-weight:850;color:var(--teal);margin:8px 0}.badges{display:flex;gap:6px;flex-wrap:wrap}.badge{font-size:10px;padding:4px 7px;border-radius:999px;background:#edf3ef;color:#3e5c55}.badge.high{background:#d9f2e5;color:#126246}.badge.low{background:#fde7e2;color:#9d3f35}.kv{display:grid;grid-template-columns:100px 1fr;gap:7px 9px;font-size:12px;margin-top:14px}.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}.source-link{display:inline-flex;margin-top:13px;color:#087d83;font-weight:750;text-decoration:none}.source-link:hover{text-decoration:underline}.hist{display:flex;height:78px;align-items:end;gap:3px;padding-top:12px}.hist i{display:block;flex:1;background:linear-gradient(#52e9c8,#12858c);border-radius:3px 3px 0 0;min-height:2px;box-shadow:0 0 6px rgba(69,230,197,.12)}.section-title{font-size:22px;margin:4px 0 5px}.section-lead{color:var(--muted);line-height:1.7;margin:0 0 15px}.source-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.source-card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:16px}.source-card h3{margin:0 0 5px;font-size:16px}.source-card p{color:var(--muted);font-size:12px;line-height:1.55;min-height:38px}.meter{height:8px;background:#e7eeea;border-radius:999px;overflow:hidden}.meter span{display:block;height:100%;background:linear-gradient(90deg,#16878a,#63e1c3);border-radius:999px}.mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:13px 0}.mini{background:#f3f7f4;border-radius:9px;padding:8px}.mini b{display:block;font-size:16px}.mini span{font-size:10px;color:var(--muted)}.flags{display:flex;gap:5px;flex-wrap:wrap}.flag{font-size:10px;background:#f5eee2;color:#80561f;border-radius:5px;padding:4px 6px}.table-wrap{overflow:auto;max-height:650px;border:1px solid var(--line);border-radius:13px;background:#fff}table{width:100%;border-collapse:collapse;font-size:12px}th{position:sticky;top:0;background:#edf4f0;color:#45615a;text-align:left;padding:10px;z-index:1}td{border-top:1px solid #e7ede9;padding:9px 10px}tr[data-region]{cursor:pointer}tr[data-region]:hover{background:#f0f7f3}.status{font-size:10px;border-radius:999px;padding:4px 7px}.status.cluster{background:#fee1dc;color:#9d352c}.status.isolated{background:#edf0f4;color:#53616d}.quality-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.callout{border-left:4px solid var(--gold);background:#fff8e9;padding:13px 15px;border-radius:0 10px 10px 0;color:#70511e;font-size:12px;line-height:1.65}.bar-row{display:grid;grid-template-columns:minmax(170px,1fr) 3fr 80px;align-items:center;gap:9px;font-size:12px;margin:8px 0}.bar{height:10px;background:#edf1ee;border-radius:999px;overflow:hidden}.bar span{height:100%;display:block;background:#5b9f8b}.missing-list{font-size:11px;max-height:380px;overflow:auto}.missing-item{padding:8px 0;border-top:1px solid var(--line);overflow-wrap:anywhere}.footer{max-width:1580px;margin:0 auto;padding:5px 22px 30px;color:var(--muted);font-size:11px;line-height:1.6}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.muted{color:var(--muted)}
@media(max-width:1120px){.grid,.quality-grid{grid-template-columns:1fr}.source-grid{grid-template-columns:1fr}.map-wrap{height:560px}}@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.map-card .card-head{align-items:flex-start;gap:12px;flex-direction:column}.map-wrap{height:480px}.map-credit,.compass{display:none}}@media(max-width:560px){.shell{padding:12px}.hero{padding:28px 18px}.kpis{grid-template-columns:1fr 1fr}.kpi strong{font-size:20px}.map-wrap{height:420px}.control{width:100%}.control select,.control input{width:100%}.bar-row{grid-template-columns:1fr}.mini-grid{grid-template-columns:1fr 1fr}.map-coordinates{display:none}.map-note{right:12px}.symbol-legend{gap:9px}}
.legend-labels{gap:12px}.legend-labels span:nth-child(2){text-align:center}.category-legend{display:none;gap:9px 15px;flex-wrap:wrap;align-items:center;margin:3px 0 2px;color:#b5cdcd;font-size:10px}.category-legend span{display:flex;align-items:center;gap:6px}.category-legend i{width:9px;height:9px;border-radius:50%;display:inline-block;box-shadow:0 0 10px currentColor}
</style>
</head>
<body>
<header class="hero"><div class="eyebrow">AI4S · Evidence-first evaluation</div><h1>全球地球化学元素图谱</h1><p>用真实公开数据检验标准化、来源追溯、置信度、异常筛查与地图消费接口。当前地图只绘制经过 WGS84 验证的记录；其他记录仍保留在数据库与质量面板中。</p><nav class="deliverables"><a href="../d2/geochemistry.csv">标准化地球化学数据库 ↗</a><a href="source_confidence.json">来源与置信度说明 ↗</a><a href="anomaly_regions.geojson">异常区域 GeoJSON ↗</a><a href="../d2/anomalies.geojson">候选异常点 ↗</a></nav></header>
<main class="shell">
<nav class="tabs"><button class="tab active" data-view="mapView">元素地图</button><button class="tab" data-view="sourceView">来源与置信度</button><button class="tab" data-view="regionView">异常区域</button><button class="tab" data-view="qualityView">质量与覆盖</button></nav>
<section id="mapView" class="view active"><div class="kpis"><div class="kpi"><span class="label">当前可见记录</span><strong id="kVisible">—</strong></div><div class="kpi"><span class="label">成功标准化</span><strong id="kQuantified">—</strong></div><div class="kpi"><span class="label">删失记录</span><strong id="kCensored">—</strong></div><div class="kpi"><span class="label">候选异常</span><strong id="kAnomaly">—</strong></div><div class="kpi"><span class="label">当前中位数</span><strong id="kMedian">—</strong></div></div><div class="grid"><article class="card map-card"><div class="card-head"><div class="controls"><label class="control">元素<select id="element"></select></label><label class="control">介质<select id="medium"></select></label><label class="control">地质单元<select id="geology"></select></label><label class="control">来源<select id="source"></select></label><label class="control">置信度<select id="confidence"></select></label></div><div class="layer-row"><button class="chip active" data-layer="points">观测点</button><button class="chip" data-layer="coverage">光晕密度</button><button class="chip active" data-layer="regions">异常区域</button><button class="chip active" data-layer="anomalies">异常点</button><button class="chip" id="focus">聚焦数据</button><button class="chip active" id="world">全球视图</button></div></div><div class="map-wrap"><canvas id="map"></canvas><div id="tooltip" class="tooltip"></div><div class="map-badge"><i></i><span>GEOCHEM ATLAS</span><b id="mapScope">GLOBAL</b></div><div class="map-credit">Natural Earth 1:110m · WGS84</div><div class="compass">N</div><div id="coordinateHud" class="map-coordinates">GLOBAL · 360° × 180°</div><div class="map-note">滚轮缩放 · 拖动平移 · 点击追溯；色阶为当前筛选记录的稳健对数域</div></div><div class="card-body"><div class="legend"></div><div class="legend-labels"><span id="legendMin">低</span><span>标准化值 · log scale</span><span id="legendMax">高</span></div><div class="symbol-legend"><span><i class="normal"></i>定量观测</span><span><i class="censored"></i>删失值</span><span><i class="high-anomaly"></i>高值候选</span><span><i class="low-anomaly"></i>低值候选</span></div><div id="hist" class="hist"></div></div></article><aside class="card"><div class="card-head"><h2>记录级证据</h2><label class="control">查找 record ID<input id="recordSearch" placeholder="输入后回车"></label></div><div class="card-body" id="detail"><p class="detail-empty">点击地图中的观测点或异常点，查看原值、标准值、方法、限定符、QC、置信度和来源定位。</p></div></aside></div></section>
<section id="sourceView" class="view"><h2 class="section-title">数据来源与工作流置信度</h2><p class="section-lead">来源、版本、许可、方法完整性与空间可用性分开呈现。置信度表示本工作流中的可用性，不是科学真实性概率。</p><div id="sourceGrid" class="source-grid"></div></section>
<section id="regionView" class="view"><h2 class="section-title">异常区域识别结果</h2><p class="section-lead">将 D2 候选异常点按元素、介质和 2° 固定网格聚合。网格只是筛查单元，不是地质边界；默认至少 3 个异常且网格内至少 10 条观测才称为候选聚集区。</p><div class="callout" id="regionSummary"></div><div class="table-wrap" style="margin-top:13px"><table><thead><tr><th>区域</th><th>元素</th><th>介质</th><th>状态</th><th>异常/观测</th><th>比例</th><th>最大 |robust z|</th><th>方向</th></tr></thead><tbody id="regionTable"></tbody></table></div></section>
<section id="qualityView" class="view"><h2 class="section-title">质量控制、覆盖空洞与科学边界</h2><p class="section-lead">测试不仅检查成功输出，也要求失败和缺口可见。坐标缺失或 CRS 未转换的记录保留在数据库，但不放到地图上的 (0,0)。</p><div class="quality-grid"><article class="card"><div class="card-head"><h3>QC 标志分布</h3></div><div class="card-body" id="qcBars"></div></article><article class="card"><div class="card-head"><h3>无法上图的记录</h3><strong id="missingCount"></strong></div><div class="card-body"><div id="missingSummary"></div><div id="missingList" class="missing-list"></div></div></article></div><article class="card" id="coverageCard" style="display:none;margin-top:14px"><div class="card-head"><h3>全球覆盖矩阵（记录数）</h3></div><div class="card-body" id="coverageMatrix"></div></article><div class="callout" style="margin-top:14px"><strong>解释边界</strong><ul id="disclaimers"></ul></div></section>
</main><footer class="footer">离线、自包含的评测可视化 · 所有统计均绑定 D2 公共输出及其 SHA-256 运行清单 · 候选异常不证明污染、矿化、资源潜力或地质成因。</footer>
<script id="atlasData" type="application/json">__ATLAS_PAYLOAD__</script>
<script>
"use strict";
const D=JSON.parse(document.getElementById("atlasData").textContent),P=D.pools,fmt=new Intl.NumberFormat("zh-CN"),layers={points:true,coverage:false,regions:true,anomalies:true};
const $=id=>document.getElementById(id), pool=(n,i)=>P[n]?.[i]??"", esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
document.querySelectorAll(".tab").forEach(b=>b.onclick=()=>{document.querySelectorAll(".tab,.view").forEach(x=>x.classList.remove("active"));b.classList.add("active");$(b.dataset.view).classList.add("active");if(b.dataset.view==="mapView")resize()});
document.querySelectorAll("[data-layer]").forEach(b=>b.onclick=()=>{const n=b.dataset.layer;layers[n]=!layers[n];b.classList.toggle("active",layers[n]);render()});
function setOptions(el,items,all=true){el.replaceChildren();for(const [v,t] of (all?[["*","全部"],...items]:items)){const o=document.createElement("option");o.value=v;o.textContent=t;el.append(o)}}
setOptions($("element"),P.element.map((x,i)=>[i,x]).filter(x=>x[1]));setOptions($("medium"),P.medium.map((x,i)=>[i,x]).filter(x=>x[1]));setOptions($("geology"),P.geology.map((x,i)=>[i,x||"未匹配/来源未报告"]));setOptions($("source"),P.source.map((x,i)=>[i,x]).filter(x=>x[1]));setOptions($("confidence"),P.band.map((x,i)=>[i,x||"unknown"]).filter(x=>x[1]));
for(const id of ["element","medium","geology","source","confidence"])$(id).onchange=()=>{viewMode="world";worldView();render()};
const canvas=$("map"),ctx=canvas.getContext("2d"),tip=$("tooltip"),coordinateHud=$("coordinateHud");
const valueLegend=document.querySelector(".legend"),legendTitle=document.querySelector(".legend-labels span:nth-child(2)"),mapNote=document.querySelector(".map-note"),kMedianLabel=$("kMedian").previousElementSibling,categoryLegend=document.createElement("div");categoryLegend.id="categoryLegend";categoryLegend.className="category-legend";document.querySelector(".legend-labels").after(categoryLegend);
$("kVisible").previousElementSibling.textContent="可上图测定记录";
const WORLD_BOUNDS={w:-180,e:180,s:-90,n:90},CONTINENT_LABELS=[[-105,48,"北美洲"],[-61,-19,"南美洲"],[18,8,"非洲"],[18,53,"欧洲"],[92,47,"亚洲"],[135,-27,"大洋洲"],[15,-78,"南极洲"]];
let W=1,H=1,view={w:-180,e:180,s:-105,n:105},drag=null,currentPoints=[],currentDisplayPoints=[],currentAnomalies=[],valueDomain=[0,1],viewMode="world",ready=false;
function selections(){return {e:$("element").value,m:$("medium").value,g:$("geology").value,s:$("source").value,b:$("confidence").value}}
function matchPoint(p){const f=selections();return(f.e==="*"||+f.e===p[2])&&(f.m==="*"||+f.m===p[3])&&(f.g==="*"||+f.g===p[19])&&(f.s==="*"||+f.s===p[11])&&(f.b==="*"||+f.b===p[7])}
function matchAnomaly(a){const f=selections();return(f.e==="*"||+f.e===a[2])&&(f.m==="*"||+f.m===a[3])&&(f.g==="*"||+f.g===a[14])&&(f.s==="*"||+f.s===a[10])&&(f.b==="*"||+f.b===a[12])}
function sx(x){return(x-view.w)/(view.e-view.w)*W}function sy(y){return(view.n-y)/(view.n-view.s)*H}function lon(px){return view.w+px/W*(view.e-view.w)}function lat(py){return view.n-py/H*(view.n-view.s)}
function setBounds(bounds,padding=.06){let w=bounds.w,e=bounds.e,s=bounds.s,n=bounds.n,dx=Math.max(.15,e-w),dy=Math.max(.12,n-s);w-=dx*padding;e+=dx*padding;s-=dy*padding;n+=dy*padding;dx=e-w;dy=n-s;const aspect=Math.max(.4,W/Math.max(H,1));if(dx/dy>aspect){const target=dx/aspect,extra=(target-dy)/2;s-=extra;n+=extra}else{const target=dy*aspect,extra=(target-dx)/2;w-=extra;e+=extra}view={w,e,s,n}}
function worldView(){viewMode="world";setBounds(WORLD_BOUNDS,.018);const f=selections();$("mapScope").textContent=Object.values(f).every(v=>v==="*")?"ALL DATA":"GLOBAL";$("world").classList.add("active")}
function fitData(){const pts=D.points.filter(matchPoint);if(!pts.length)return;let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;for(const p of pts){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1])}viewMode="data";setBounds({w:minX,e:maxX,s:minY,n:maxY},.09);$("mapScope").textContent="FOCUS";$("world").classList.remove("active")}
function resize(){const r=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.max(1,r.width*dpr);canvas.height=Math.max(1,r.height*dpr);W=r.width;H=r.height;ctx.setTransform(dpr,0,0,dpr,0,0);if(viewMode==="world")worldView();else if(viewMode==="data")fitData();ready=true;render()}
new ResizeObserver(resize).observe(canvas);$("world").onclick=()=>{worldView();render()};$("focus").onclick=()=>{fitData();render()};
canvas.onwheel=e=>{e.preventDefault();const r=canvas.getBoundingClientRect(),px=e.clientX-r.left,py=e.clientY-r.top,cx=lon(px),cy=lat(py),requested=e.deltaY>0?1.16:.86,current=view.e-view.w,z=(current*requested<.2||current*requested>430)?1:requested;view={w:cx+(view.w-cx)*z,e:cx+(view.e-cx)*z,s:cy+(view.s-cy)*z,n:cy+(view.n-cy)*z};viewMode="manual";$("mapScope").textContent=`ZOOM ${(360/(view.e-view.w)).toFixed(1)}×`;$("world").classList.remove("active");render()};
canvas.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,v:{...view}};canvas.setPointerCapture(e.pointerId);canvas.classList.add("dragging")};canvas.onpointerup=()=>{drag=null;canvas.classList.remove("dragging")};canvas.onpointerleave=()=>{tip.style.display="none";coordinateHud.textContent=`${$("mapScope").textContent} · ${(view.e-view.w).toFixed(1)}° VIEW`};canvas.onpointermove=e=>{const r=canvas.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;coordinateHud.textContent=`${lat(my).toFixed(3)}° ${lat(my)>=0?"N":"S"}  ·  ${lon(mx).toFixed(3)}° ${lon(mx)>=0?"E":"W"}  ·  ${(360/(view.e-view.w)).toFixed(1)}×`;if(drag){const dx=(e.clientX-drag.x)/W*(drag.v.e-drag.v.w),dy=(e.clientY-drag.y)/H*(drag.v.n-drag.v.s);view={w:drag.v.w-dx,e:drag.v.e-dx,s:drag.v.s+dy,n:drag.v.n+dy};viewMode="manual";$("mapScope").textContent="EXPLORE";$("world").classList.remove("active");render();return}hover(e)};
function color(v){if(v==null)return"#8299a0";const [a,b]=valueDomain,t=Math.max(0,Math.min(1,(Math.log10(Math.max(v,1e-12))-a)/(b-a||1))),stops=[[71,119,255],[48,215,232],[67,239,189],[255,225,92],[255,100,126]],q=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(q)),f=q-i,c=stops[i].map((x,j)=>Math.round(x+(stops[i+1][j]-x)*f));return`rgb(${c.join(",")})`}
const MEDIUM_STYLE={rock:["#54a7ff","岩石"],soil:["#ffe15c","土壤"],sediment:["#ff8a65","沉积物"],water:["#43efbd","水体"]};
function mediumStyle(name){return MEDIUM_STYLE[name]||["#c790ff",name||"未知介质"]}
function quantitativeView(){if(selections().e==="*")return false;const rows=currentPoints.filter(p=>p[4]!=null&&p[4]>0),media=new Set(rows.map(p=>p[3])),units=new Set(rows.map(p=>p[5]));return rows.length>0&&media.size===1&&units.size===1}
function overviewPoints(rows){if(selections().e!=="*")return rows;const grouped=new Map();for(const p of rows){const key=`${p[11]}|${p[10]}|${p[3]}|${p[0].toFixed(5)}|${p[1].toFixed(5)}`,previous=grouped.get(key);if(!previous||(previous[6]&&!p[6]))grouped.set(key,p)}return[...grouped.values()]}
function pointColor(p,quantitative){return quantitative?color(p[4]):mediumStyle(pool("medium",p[3]))[0]}
function visible(x,y,pad=0){return x>=view.w-pad&&x<=view.e+pad&&y>=view.s-pad&&y<=view.n+pad}
function degreeLabel(value,axis){if(value===0)return"0°";const suffix=axis==="x"?(value>0?"E":"W"):(value>0?"N":"S");return`${Math.abs(value)}°${suffix}`}
function traceLand(){ctx.beginPath();for(const ring of D.basemap.rings){let previous=null,started=false;for(const point of ring){if(previous&&Math.abs(point[0]-previous[0])>180){started=false}if(!started){ctx.moveTo(sx(point[0]),sy(point[1]));started=true}else ctx.lineTo(sx(point[0]),sy(point[1]));previous=point}ctx.closePath()}}
function renderBasemap(){const ocean=ctx.createLinearGradient(0,0,W,H);ocean.addColorStop(0,"#061923");ocean.addColorStop(.52,"#082630");ocean.addColorStop(1,"#0a202b");ctx.fillStyle=ocean;ctx.fillRect(0,0,W,H);const glow=ctx.createRadialGradient(W*.72,H*.22,0,W*.72,H*.22,Math.max(W,H)*.72);glow.addColorStop(0,"rgba(21,108,116,.16)");glow.addColorStop(1,"rgba(4,18,27,0)");ctx.fillStyle=glow;ctx.fillRect(0,0,W,H);
const span=view.e-view.w,step=span>260?30:span>120?20:span>55?10:span>20?5:2;ctx.lineWidth=1;ctx.font="9px ui-monospace,SFMono-Regular,Menlo,monospace";ctx.textAlign="center";ctx.textBaseline="top";for(let x=Math.ceil(view.w/step)*step;x<=view.e;x+=step){ctx.strokeStyle=x===0?"rgba(99,229,216,.24)":"rgba(128,181,184,.105)";ctx.beginPath();ctx.moveTo(sx(x),0);ctx.lineTo(sx(x),H);ctx.stroke();if(sx(x)>28&&sx(x)<W-28){ctx.fillStyle="rgba(148,190,191,.5)";ctx.fillText(degreeLabel(x,"x"),sx(x),H-17)}}ctx.textAlign="left";ctx.textBaseline="middle";for(let y=Math.ceil(view.s/step)*step;y<=view.n;y+=step){ctx.strokeStyle=y===0?"rgba(99,229,216,.24)":"rgba(128,181,184,.105)";ctx.beginPath();ctx.moveTo(0,sy(y));ctx.lineTo(W,sy(y));ctx.stroke();if(sy(y)>25&&sy(y)<H-25){ctx.fillStyle="rgba(148,190,191,.5)";ctx.fillText(degreeLabel(y,"y"),7,sy(y))}}
traceLand();const land=ctx.createLinearGradient(0,0,0,H);land.addColorStop(0,"#174753");land.addColorStop(.5,"#113a46");land.addColorStop(1,"#0d303c");ctx.fillStyle=land;ctx.shadowColor="rgba(55,218,202,.14)";ctx.shadowBlur=10;ctx.fill("evenodd");ctx.shadowBlur=0;ctx.strokeStyle="rgba(113,204,197,.5)";ctx.lineWidth=span>180?1.05:1.45;ctx.stroke();
if(span>210){ctx.textAlign="center";ctx.textBaseline="middle";ctx.font="700 10px system-ui";ctx.fillStyle="rgba(164,210,207,.34)";ctx.shadowColor="rgba(0,0,0,.65)";ctx.shadowBlur=5;for(const [x,y,label] of CONTINENT_LABELS)if(visible(x,y))ctx.fillText(label,sx(x),sy(y));ctx.shadowBlur=0}}
function renderCoverage(){const bins=new Map(),dx=Math.max(2,(view.e-view.w)/42),dy=Math.max(2,(view.n-view.s)/26);for(const p of currentDisplayPoints){if(!visible(p[0],p[1]))continue;const x=Math.floor((p[0]-view.w)/dx),y=Math.floor((p[1]-view.s)/dy),k=`${x},${y}`;bins.set(k,(bins.get(k)||0)+1)}const mx=Math.max(1,...bins.values());ctx.save();ctx.globalCompositeOperation="screen";for(const[k,n]of bins){const[x,y]=k.split(",").map(Number),cx=sx(view.w+(x+.5)*dx),cy=sy(view.s+(y+.5)*dy),radius=Math.max(12,Math.min(54,13+Math.sqrt(n/mx)*42)),g=ctx.createRadialGradient(cx,cy,0,cx,cy,radius);g.addColorStop(0,`rgba(51,236,207,${.1+.38*Math.sqrt(n/mx)})`);g.addColorStop(.42,`rgba(34,170,194,${.07+.2*Math.sqrt(n/mx)})`);g.addColorStop(1,"rgba(20,110,150,0)");ctx.fillStyle=g;ctx.fillRect(cx-radius,cy-radius,radius*2,radius*2)}ctx.restore()}
function filteredRegions(){const f=selections();return D.regions.filter(r=>{const p=r.properties;return(f.e==="*"||pool("element",+f.e)===p.element_or_analyte)&&(f.m==="*"||pool("medium",+f.m)===p.medium)})}
function renderRegionsLayer(){ctx.save();for(const r of filteredRegions()){const ring=r.geometry.coordinates[0],p=r.properties,cluster=p.status==="candidate_cluster";ctx.beginPath();ring.forEach((q,i)=>(i?ctx.lineTo(sx(q[0]),sy(q[1])):ctx.moveTo(sx(q[0]),sy(q[1]))));ctx.closePath();ctx.fillStyle=cluster?"rgba(255,89,116,.18)":"rgba(247,194,87,.08)";ctx.strokeStyle=cluster?"rgba(255,104,130,.9)":"rgba(247,194,87,.48)";ctx.lineWidth=cluster?1.8:1;ctx.setLineDash(cluster?[]:[3,3]);ctx.shadowColor=cluster?"rgba(255,82,112,.65)":"transparent";ctx.shadowBlur=cluster?9:0;ctx.fill();ctx.stroke()}ctx.restore()}
function renderPointsLayer(quantitative){const span=view.e-view.w,zoom=Math.sqrt(360/Math.max(span,.1)),radius=Math.max(1.75,Math.min(3.4,1.8*zoom)),shown=currentDisplayPoints.filter(p=>visible(p[0],p[1],1));ctx.save();if(shown.length<9000){ctx.globalCompositeOperation="screen";for(const p of shown){if(p[6])continue;ctx.beginPath();ctx.arc(sx(p[0]),sy(p[1]),radius*2.9,0,Math.PI*2);ctx.fillStyle=pointColor(p,quantitative);ctx.globalAlpha=.14;ctx.fill()}ctx.globalCompositeOperation="source-over"}for(const p of shown){ctx.beginPath();ctx.arc(sx(p[0]),sy(p[1]),p[6]?radius+1:radius,0,Math.PI*2);if(p[6]){ctx.fillStyle="rgba(8,28,38,.92)";ctx.strokeStyle="#d099ff";ctx.lineWidth=1.35;ctx.globalAlpha=.95;ctx.fill();ctx.stroke()}else{ctx.fillStyle=pointColor(p,quantitative);ctx.strokeStyle="rgba(235,255,252,.66)";ctx.lineWidth=.5;ctx.globalAlpha=.9;ctx.fill();ctx.stroke()}}ctx.restore()}
function renderAnomaliesLayer(){const span=view.e-view.w,size=Math.max(4.3,Math.min(7,5*Math.sqrt(360/Math.max(span,.1))));ctx.save();for(const a of currentAnomalies){if(!visible(a[0],a[1],1))continue;const x=sx(a[0]),y=sy(a[1]),low=pool("direction",a[7])==="low",c=low?"#59adff":"#ff617b";ctx.strokeStyle=c;ctx.globalAlpha=.35;ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(x,y,size+4,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;ctx.shadowColor=c;ctx.shadowBlur=12;ctx.fillStyle=c;ctx.beginPath();ctx.moveTo(x,y-size);ctx.lineTo(x+size*.7,y);ctx.lineTo(x,y+size);ctx.lineTo(x-size*.7,y);ctx.closePath();ctx.fill();ctx.shadowBlur=0;ctx.fillStyle="#f5fffd";ctx.beginPath();ctx.arc(x,y,1.25,0,Math.PI*2);ctx.fill()}ctx.restore()}
function renderLegend(quantitative,vals){if(quantitative){const lo=vals[Math.floor(vals.length*.03)],hi=vals[Math.floor(vals.length*.97)],unit=pool("unit",currentPoints.find(p=>p[4]!=null)?.[5]);valueDomain=[Math.log10(Math.max(lo,1e-12)),Math.log10(Math.max(hi,1e-12))];valueLegend.style.display="block";categoryLegend.style.display="none";$("legendMin").textContent=`${lo.toPrecision(3)} ${unit}`;$("legendMax").textContent=`${hi.toPrecision(3)} ${unit}`;legendTitle.textContent="同元素 · 同介质 · 稳健 log 色阶";$("hist").style.display="flex";mapNote.textContent="色阶限于同元素、同介质、同单位；分析方法差异仍需在记录级证据中复核";return}valueLegend.style.display="none";$("legendMin").textContent="";$("legendMax").textContent="";legendTitle.textContent="介质分类总览 · 不跨元素或介质比较浓度";const counts=new Map();for(const p of currentDisplayPoints){const medium=pool("medium",p[3])||"unknown";counts.set(medium,(counts.get(medium)||0)+1)}categoryLegend.innerHTML=Object.entries(MEDIUM_STYLE).filter(([name])=>counts.has(name)).map(([name,[color,label]])=>`<span style="color:${color}"><i style="background:${color}"></i>${label} · ${fmt.format(counts.get(name))} 点</span>`).join("")+[...counts].filter(([name])=>!MEDIUM_STYLE[name]).map(([name,count])=>`<span style="color:#c790ff"><i style="background:#c790ff"></i>${esc(name)} · ${fmt.format(count)} 点</span>`).join("");categoryLegend.style.display="flex";$("hist").style.display="none";mapNote.textContent=selections().e==="*"?`全部元素按样品去重显示 ${fmt.format(currentDisplayPoints.length)} 个采样点（上方 KPI 为测定记录）；颜色表示介质`:`当前筛选包含不可直接比较的介质或单位；颜色表示介质，选择单一介质后启用浓度色阶`}
function render(){if(!ready)return;currentPoints=D.points.filter(matchPoint);currentDisplayPoints=overviewPoints(currentPoints);currentAnomalies=D.anomalies.filter(matchAnomaly);const vals=currentPoints.map(p=>p[4]).filter(v=>v!=null&&v>0).sort((a,b)=>a-b),quantitative=quantitativeView();renderLegend(quantitative,vals);renderBasemap();if(layers.coverage)renderCoverage();if(layers.regions)renderRegionsLayer();if(layers.points)renderPointsLayer(quantitative);if(layers.anomalies)renderAnomaliesLayer();updateStats(vals,quantitative)}
function updateStats(vals,quantitative){$("kVisible").textContent=fmt.format(currentPoints.length);$("kQuantified").textContent=fmt.format(currentPoints.filter(p=>p[4]!=null).length);$("kCensored").textContent=fmt.format(currentPoints.filter(p=>p[6]).length);$("kAnomaly").textContent=fmt.format(currentAnomalies.length);if(quantitative){const med=vals.length?vals[Math.floor(vals.length/2)]:null,u=currentPoints.length?pool("unit",currentPoints.find(p=>p[4]!=null)?.[5]):"";kMedianLabel.textContent="当前中位数";$("kMedian").textContent=med==null?"—":`${med.toPrecision(3)} ${u}`;const bins=Array(24).fill(0),a=valueDomain[0],b=valueDomain[1];for(const v of vals){const i=Math.max(0,Math.min(23,Math.floor((Math.log10(v)-a)/(b-a||1)*24)));bins[i]++}const mx=Math.max(1,...bins);$("hist").innerHTML=bins.map(n=>`<i style="height:${Math.max(2,n/mx*100)}%"></i>`).join("")}else{const elements=new Set(currentPoints.map(p=>p[2])),media=new Set(currentPoints.map(p=>p[3]));kMedianLabel.textContent="总览范围";$("kMedian").textContent=`${elements.size} 元素 · ${media.size} 介质`;$("hist").innerHTML=""}}
function nearest(e){const r=canvas.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;let best=null,bd=14*14;for(const p of currentDisplayPoints){const d=(sx(p[0])-x)**2+(sy(p[1])-y)**2;if(d<bd){best=p;bd=d}}return best}
function hover(e){const p=nearest(e);if(!p){tip.style.display="none";return}const r=canvas.getBoundingClientRect();tip.style.display="block";tip.style.left=`${Math.min(W-230,e.clientX-r.left+12)}px`;tip.style.top=`${Math.max(8,e.clientY-r.top-42)}px`;tip.textContent=`${pool("element",p[2])} · ${p[4]??p[17]} ${pool("unit",p[5])||pool("original_unit",p[18])} · ${p[9]}`}
canvas.onclick=e=>{const p=nearest(e);if(p)showPoint(p)};
function showPoint(p){const flags=p[14].map(i=>pool("flag",i));const url=p[12]&&p[12].startsWith("https://")?`<a class="source-link" href="${esc(p[12])}" target="_blank" rel="noopener">打开原始来源定位 ↗</a>`:"";$("detail").innerHTML=`<div class="record-title mono">${esc(p[9])}</div><div class="value">${esc(p[4]??"未标准化")} ${esc(pool("unit",p[5]))}</div><div class="badges"><span class="badge ${esc(pool("band",p[7]))}">${esc(pool("band",p[7]))} · ${esc(p[8])}</span><span class="badge">${esc(pool("medium",p[3]))}</span>${p[6]?'<span class="badge">删失值</span>':''}</div><dl class="kv"><dt>元素</dt><dd>${esc(pool("element",p[2]))}</dd><dt>原始值</dt><dd>${esc(p[17])} ${esc(pool("original_unit",p[18]))} · ${esc(pool("qualifier",p[13]))}</dd><dt>样品 ID</dt><dd>${esc(p[10])}</dd><dt>来源</dt><dd>${esc(pool("source",p[11]))}</dd><dt>地质单元</dt><dd>${esc(pool("geology",p[19])||"未匹配")} · ${esc(pool("geology_status",p[20]))}</dd><dt>分析方法族</dt><dd>${esc(pool("method",p[15]))}</dd><dt>测量基准</dt><dd>${esc(pool("basis",p[16]))}</dd><dt>坐标</dt><dd>${p[1].toFixed(5)}, ${p[0].toFixed(5)}</dd><dt>QC</dt><dd>${flags.length?flags.map(x=>`<span class="flag">${esc(x)}</span>`).join(" "):"无"}</dd></dl>${url}`}
$("recordSearch").onkeydown=e=>{if(e.key!=="Enter")return;const q=e.target.value.trim(),p=D.points.find(x=>x[9]===q);if(p){showPoint(p);viewMode="manual";setBounds({w:p[0]-3,e:p[0]+3,s:p[1]-2,n:p[1]+2},.04);$("mapScope").textContent="RECORD";$("world").classList.remove("active");render()}else $("detail").innerHTML=`<p class="detail-empty">未在可上图记录中找到 <span class="mono">${esc(q)}</span>；它可能因坐标 QC 被保留在标准化数据库而未上图。</p>`};
function renderSources(){const s=D.sources.sources;$("sourceGrid").innerHTML=s.map(x=>{const c=x.confidence.median_overall??0,flags=x.top_qc_flags.slice(0,4).map(f=>`<span class="flag">${esc(f.flag)} · ${fmt.format(f.count)}</span>`).join("");return`<article class="source-card"><div class="eyebrow" style="color:var(--teal)">${esc(x.source_id)}</div><h3>${esc(x.dataset_title)}</h3><p>${esc(x.dataset_version)}<br>DOI：${esc(x.dataset_doi||"未提供")}</p><div class="mini-grid"><div class="mini"><b>${fmt.format(x.record_count)}</b><span>记录</span></div><div class="mini"><b>${(x.mappable_count/x.record_count*100).toFixed(1)}%</b><span>可上图</span></div><div class="mini"><b>${(x.analytical_method_coverage*100).toFixed(1)}%</b><span>方法完整</span></div></div><div class="muted" style="font-size:11px;margin-bottom:5px">工作流置信度中位数 ${c.toFixed(3)}（非概率）</div><div class="meter"><span style="width:${c*100}%"></span></div><div class="flags" style="margin-top:12px">${flags}</div><p style="min-height:0;margin-bottom:0">许可：${esc(x.license)}</p></article>`}).join("")}
function renderRegions(){const rows=[...D.regions].sort((a,b)=>(b.properties.status==="candidate_cluster")-(a.properties.status==="candidate_cluster")||b.properties.anomaly_count-a.properties.anomaly_count),clusters=rows.filter(r=>r.properties.status==="candidate_cluster").length,rr=D.region_report;$("regionSummary").innerHTML=`D2 共输出 <strong>${fmt.format(rr.candidate_point_count)}</strong> 个候选异常点；其中 <strong>${fmt.format(rr.mappable_candidate_point_count)}</strong> 个具有合格坐标并聚合为 <strong>${fmt.format(rows.length)}</strong> 个元素—介质网格，<strong>${fmt.format(clusters)}</strong> 个达到候选聚集区门槛。另有 <strong>${fmt.format(rr.unmappable_candidate_point_count)}</strong> 个因坐标 QC 未聚合，完整 ID 见异常区域报告。仅作筛查，必须结合采样密度、地质背景和方法可比性复核。`;$("regionTable").innerHTML=rows.map(r=>{const p=r.properties,d=Object.entries(p.direction_counts).map(x=>`${x[0]} ${x[1]}`).join(" / ");return`<tr data-region="${esc(p.region_id)}"><td class="mono">${esc(p.region_id)}</td><td>${esc(p.element_or_analyte)}</td><td>${esc(p.medium)}</td><td><span class="status ${p.status==="candidate_cluster"?"cluster":"isolated"}">${p.status==="candidate_cluster"?"候选聚集":"孤立单元"}</span></td><td>${p.anomaly_count} / ${p.observation_count}</td><td>${((p.anomaly_fraction||0)*100).toFixed(1)}%</td><td>${p.max_abs_robust_z??"—"}</td><td>${esc(d)}</td></tr>`}).join("");$("regionTable").querySelectorAll("tr").forEach((tr,i)=>tr.onclick=()=>{const ring=rows[i].geometry.coordinates[0],xs=ring.map(q=>q[0]),ys=ring.map(q=>q[1]);viewMode="manual";setBounds({w:Math.min(...xs),e:Math.max(...xs),s:Math.min(...ys),n:Math.max(...ys)},.35);$("mapScope").textContent="REGION";$("world").classList.remove("active");document.querySelector('[data-view="mapView"]').click();render()})}
function renderQuality(){const flags=Object.entries(D.quality.qc.flag_counts||{}).sort((a,b)=>b[1]-a[1]),mx=Math.max(1,...flags.map(x=>x[1]));$("qcBars").innerHTML=flags.map(([n,v])=>`<div class="bar-row"><span class="mono">${esc(n)}</span><div class="bar"><span style="width:${v/mx*100}%"></span></div><b>${fmt.format(v)}</b></div>`).join("");const m=D.quality.missing_coordinates;$("missingCount").textContent=fmt.format(m.count);$("missingSummary").innerHTML=`<div class="mini-grid">${Object.entries(m.by_medium).map(([k,v])=>`<div class="mini"><b>${fmt.format(v)}</b><span>${esc(k)}</span></div>`).join("")}</div><p class="muted">以下仅展示前 ${m.examples.length} 条；完整记录仍在标准化数据库中。</p>`;$("missingList").innerHTML=m.examples.map(x=>`<div class="missing-item"><b class="mono">${esc(x.record_id)}</b><br>${esc(x.medium)} · ${esc(x.element)} · ${esc(x.original_value)} ${esc(x.original_unit)}<br><span class="muted">${esc((x.qc_flags||[]).join(", "))}</span></div>`).join("");const g=D.sources.geographic_coverage;if(g){$("coverageCard").style.display="block";const media=["rock","soil","sediment","water"],rows=Object.entries(g.coverage_matrix||{});$("coverageMatrix").innerHTML=`<div class="table-wrap" style="max-height:none"><table><thead><tr><th>洲</th>${media.map(x=>`<th>${esc(x)}</th>`).join("")}<th>合计</th></tr></thead><tbody>${rows.map(([c,v])=>`<tr><td><b>${esc(c)}</b></td>${media.map(x=>`<td>${fmt.format(v[x]||0)}</td>`).join("")}<td>${fmt.format(media.reduce((n,x)=>n+(v[x]||0),0))}</td></tr>`).join("")}</tbody></table></div><p class="muted">GEMStat 明确国家数：${fmt.format(g.gemstat_country_count||0)}。七洲仅表示至少一种介质有记录，不表示 7×4 单元完整。</p><div class="callout"><strong>已知空洞</strong><ul>${(g.declared_blind_spots||[]).map(x=>`<li>${esc(x)}</li>`).join("")}</ul></div>`}$("disclaimers").innerHTML=[...D.disclaimers,...(g?.interpretation_limits||[])].map(x=>`<li>${esc(x)}</li>`).join("")}
renderSources();renderRegions();renderQuality();resize();
</script>
</body></html>'''


def build_showcase(
    *,
    database: Sequence[Mapping[str, Any]],
    samples: Mapping[str, Any],
    anomalies: Mapping[str, Any],
    qc_report: Mapping[str, Any],
    confidence_report: Mapping[str, Any],
    anomaly_report: Mapping[str, Any],
    disclaimers: Sequence[str],
    d2_output_dir: Path,
    output_dir: Path,
    coverage_context: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    source_summary = source_confidence_summary(database, confidence_report, qc_report)
    if coverage_context is not None:
        source_summary["geographic_coverage"] = {
            "scientific_scope": coverage_context.get("scientific_scope"),
            "continent_mapping_version": coverage_context.get("continent_mapping_version"),
            "records_by_continent": coverage_context.get("records_by_continent", {}),
            "coverage_matrix": coverage_context.get("coverage_matrix", {}),
            "explicit_country_label_count": coverage_context.get("explicit_country_label_count"),
            "gemstat_country_count": coverage_context.get("gemstat_country_count"),
            "declared_blind_spots": coverage_context.get("declared_blind_spots", []),
            "interpretation_limits": coverage_context.get("interpretation_limits", []),
        }
    anomaly_regions, region_report = anomaly_region_outputs(
        list(samples.get("features", [])), list(anomalies.get("features", []))
    )

    source_path = output_dir / "source_confidence.json"
    region_path = output_dir / "anomaly_regions.geojson"
    region_report_path = output_dir / "anomaly_region_report.json"
    atomic_write_json(source_path, source_summary)
    atomic_write_json(region_path, anomaly_regions)
    atomic_write_json(region_report_path, region_report)

    payload = compact_map_payload(
        list(samples.get("features", [])),
        list(anomalies.get("features", [])),
        anomaly_regions,
        region_report,
        source_summary,
        qc_report,
        anomaly_report,
        database,
        disclaimers,
    )
    atlas_path = output_dir / "atlas.html"
    atomic_write_text(atlas_path, HTML_TEMPLATE.replace("__ATLAS_PAYLOAD__", compact_json(payload)))

    standardized_database = d2_output_dir / "geochemistry.csv"
    deliverables = {
        "interactive_element_map": {
            "path": atlas_path.name,
            "sha256": sha256_file(atlas_path),
            "media_type": "text/html",
            "offline": True,
        },
        "standardized_geochemical_database": {
            "path": "../d2/geochemistry.csv",
            "sha256": sha256_file(standardized_database),
            "media_type": "text/csv",
            "record_count": len(database),
        },
        "source_and_confidence_explanation": {
            "path": source_path.name,
            "sha256": sha256_file(source_path),
            "media_type": "application/json",
        },
        "anomaly_region_results": {
            "path": region_path.name,
            "sha256": sha256_file(region_path),
            "media_type": "application/geo+json",
            "feature_count": len(anomaly_regions["features"]),
        },
    }
    manifest = {
        "manifest_version": "d3-showcase-manifest-v1",
        "showcase_version": SHOWCASE_VERSION,
        "scientific_status": "evaluation_deliverables",
        "map_provenance": {
            "title": payload["basemap"]["title"],
            "version": payload["basemap"]["natural_earth_version"],
            "scale": payload["basemap"]["scale"],
            "source_page": payload["basemap"]["source_page"],
            "license": payload["basemap"]["license"],
            "archive_sha256": payload["basemap"]["archive_sha256"],
            "embedded_offline": True,
        },
        "deliverables": deliverables,
        "supporting_outputs": {
            "candidate_anomaly_points": {
                "path": "../d2/anomalies.geojson",
                "sha256": sha256_file(d2_output_dir / "anomalies.geojson"),
            },
            "anomaly_region_report": {
                "path": region_report_path.name,
                "sha256": sha256_file(region_report_path),
            },
        },
        "interpretation_limits": region_report["interpretation_limits"],
    }
    manifest_path = output_dir / "showcase_manifest.json"
    atomic_write_json(manifest_path, manifest)
    paths = {
        "html": atlas_path,
        "source_confidence": source_path,
        "anomaly_regions": region_path,
        "anomaly_region_report": region_report_path,
        "showcase_manifest": manifest_path,
    }
    metrics = {
        "showcase_version": SHOWCASE_VERSION,
        "source_count": source_summary["source_count"],
        "anomaly_region_count": len(anomaly_regions["features"]),
        "candidate_cluster_count": region_report["status_counts"].get("candidate_cluster", 0),
        "atlas_bytes": atlas_path.stat().st_size,
        "deliverables": deliverables,
    }
    return paths, metrics
