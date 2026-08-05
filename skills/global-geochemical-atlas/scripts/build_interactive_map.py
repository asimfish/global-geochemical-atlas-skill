#!/usr/bin/env python3
"""Build the D3 self-contained interactive atlas and map-ready GeoJSON."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


MAP_VERSION = "d3-interactive-atlas-v2"
BASEMAP_ASSET_VERSION = "ai4s-natural-earth-land-v1"
MAX_OUTPUT_BYTES = 100_000_000
SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_BASEMAP = SKILL_DIR / "assets" / "natural-earth-110m-land.json"


class MapBuildError(ValueError):
    """Raised when D2 map inputs or the bundled basemap are invalid."""


def optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_json_cell(value: Any, fallback: Any) -> Any:
    if value is None or str(value).strip() == "":
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def parse_bool_cell(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def load_records(path: Path, max_points: int) -> tuple[list[dict[str, Any]], int]:
    """Consume, but never reinterpret, the public D2 canonical CSV."""
    if not path.is_file():
        raise MapBuildError(f"database does not exist: {path}")
    records: list[dict[str, Any]] = []
    total_records = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "record_id",
            "element_or_analyte",
            "medium",
            "normalized_value",
            "normalized_unit",
            "latitude",
            "longitude",
            "qc_flags",
            "operational_confidence",
            "source_id",
            "source_locator",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise MapBuildError(f"database missing map columns: {', '.join(missing)}")
        for row in reader:
            total_records += 1
            latitude = optional_float(row.get("latitude"))
            longitude = optional_float(row.get("longitude"))
            if latitude is None or longitude is None:
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            confidence = parse_json_cell(row.get("operational_confidence"), {})
            qc_flags = parse_json_cell(row.get("qc_flags"), [])
            if not isinstance(confidence, dict):
                confidence = {}
            if not isinstance(qc_flags, list):
                qc_flags = []
            records.append(
                {
                    "record_id": row.get("record_id"),
                    "sample_id": row.get("sample_id") or None,
                    "element": row.get("element_or_analyte"),
                    "analyte_reported": row.get("analyte_reported") or None,
                    "medium": row.get("medium"),
                    "material": row.get("material") or None,
                    "measurement_basis": row.get("measurement_basis") or None,
                    "original_value_raw": row.get("original_value_raw") or None,
                    "original_unit": row.get("original_unit") or None,
                    "source_qualifier_raw": row.get("source_qualifier_raw") or None,
                    "qualifier": row.get("value_qualifier") or None,
                    "censored": parse_bool_cell(row.get("censored")),
                    "censoring_limit": optional_float(row.get("normalized_censoring_limit")),
                    "value": optional_float(row.get("normalized_value")),
                    "unit": row.get("normalized_unit") or None,
                    "latitude": latitude,
                    "longitude": longitude,
                    "lithology": row.get("lithology") or None,
                    "geologic_unit": row.get("geologic_unit") or None,
                    "analytical_method": row.get("analytical_method") or None,
                    "method_family": row.get("method_family") or None,
                    "digestion_or_extraction": row.get("digestion_or_extraction") or None,
                    "source_id": row.get("source_id") or None,
                    "dataset_title": row.get("dataset_title") or None,
                    "dataset_doi": row.get("dataset_doi") or None,
                    "dataset_version": row.get("dataset_version") or None,
                    "source_locator": row.get("source_locator") or None,
                    "license": row.get("license") or None,
                    "confidence_band": confidence.get("band", "unknown"),
                    "confidence_overall": optional_float(confidence.get("overall")),
                    "confidence_components": {
                        key: optional_float(confidence.get(key))
                        for key in ("source", "completeness", "method", "spatial", "qc")
                    },
                    "qc_flags": [str(flag) for flag in qc_flags],
                }
            )
            if len(records) > max_points:
                raise MapBuildError(
                    f"valid map points exceed --max-points ({max_points}); filter the input first"
                )
    return records, total_records


def load_json_object(path: Path | None, label: str) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.is_file():
        raise MapBuildError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MapBuildError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise MapBuildError(f"{label} must be a JSON object")
    return value


def load_anomalies(path: Path) -> dict[str, Any]:
    value = load_json_object(path, "anomalies GeoJSON")
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise MapBuildError("anomalies input must be a GeoJSON FeatureCollection")
    return value


def load_basemap(path: Path) -> dict[str, Any]:
    value = load_json_object(path, "offline basemap")
    rings = value.get("rings")
    if (
        value.get("asset_version") != BASEMAP_ASSET_VERSION
        or value.get("license") != "public domain"
        or not isinstance(rings, list)
        or not rings
        or len(rings) > 1_000
    ):
        raise MapBuildError("offline basemap provenance or structure is invalid")
    point_count = 0
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 3:
            raise MapBuildError("offline basemap contains an invalid polygon ring")
        for point in ring:
            point_count += 1
            if (
                not isinstance(point, list)
                or len(point) != 2
                or optional_float(point[0]) is None
                or optional_float(point[1]) is None
                or not (-180 <= float(point[0]) <= 180)
                or not (-90 <= float(point[1]) <= 90)
            ):
                raise MapBuildError("offline basemap contains an invalid coordinate")
    if point_count > 100_000:
        raise MapBuildError("offline basemap exceeds the point safety limit")
    return {
        "asset_version": value["asset_version"],
        "title": value.get("title", "Natural Earth land"),
        "natural_earth_version": value.get("natural_earth_version"),
        "scale": value.get("scale", "1:110m"),
        "coordinate_reference_system": value.get(
            "coordinate_reference_system", "WGS84 longitude/latitude"
        ),
        "source_page": value.get("source_page"),
        "license": value["license"],
        "archive_sha256": value.get("archive_sha256"),
        "point_count": point_count,
        "rings": rings,
    }


def samples_geojson(
    records: Sequence[Mapping[str, Any]], anomaly_ids: set[str]
) -> dict[str, Any]:
    features = []
    for record in records:
        properties = {
            key: value for key, value in record.items() if key not in {"latitude", "longitude"}
        }
        properties["candidate_anomaly"] = str(record["record_id"]) in anomaly_ids
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [record["longitude"], record["latitude"]],
                },
                "properties": properties,
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "standardized_geochemical_samples",
        "map_version": MAP_VERSION,
        "features": features,
    }


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def safe_embedded_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全球地球化学元素图谱 · D3</title>
<style>
:root{--ink:#102a31;--muted:#6b7e83;--paper:#edf3f2;--card:#fff;--line:#d8e4e3;--deep:#071c26;--teal:#087d83;--cyan:#41e6d3;--mint:#78e6bf;--gold:#f4c15d;--red:#ff667a;--blue:#54a7ff;--shadow:0 20px 55px rgba(6,34,43,.12);font-family:Inter,"Noto Sans SC","PingFang SC",system-ui,sans-serif;color:var(--ink);background:var(--paper)}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 82% 0,#d6eee9 0,transparent 29rem),linear-gradient(180deg,#f6f9f8,#edf3f2 52%,#e8efee)}button,select,input{font:inherit}.hero{background:radial-gradient(circle at 84% -40%,rgba(64,230,211,.24),transparent 31rem),linear-gradient(123deg,#04171f,#07313c 58%,#07545b);color:#fff;padding:36px max(24px,calc((100vw - 1580px)/2));position:relative;overflow:hidden}.hero:before{content:"";position:absolute;inset:0;background-image:linear-gradient(rgba(108,245,224,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(108,245,224,.035) 1px,transparent 1px);background-size:34px 34px;mask-image:linear-gradient(90deg,transparent,black 70%)}.hero:after{content:"";position:absolute;width:430px;height:430px;border:1px solid rgba(93,247,224,.18);border-radius:50%;right:-78px;top:-270px;box-shadow:0 0 0 72px rgba(66,225,209,.045),0 0 0 144px rgba(66,225,209,.018)}.eyebrow{font-size:11px;letter-spacing:.21em;text-transform:uppercase;color:#82f2dc;font-weight:850;position:relative;z-index:1}.hero h1{font-size:clamp(30px,4vw,54px);letter-spacing:-.035em;line-height:1.03;margin:10px 0 12px;max-width:960px;position:relative;z-index:1}.hero p{max-width:980px;color:#d8efed;font-size:14px;line-height:1.72;margin:0;position:relative;z-index:1}.deliverables{display:flex;gap:9px;flex-wrap:wrap;margin-top:20px;position:relative;z-index:2}.deliverables a{color:#effffc;text-decoration:none;border:1px solid rgba(110,245,224,.26);background:rgba(5,28,36,.32);padding:8px 12px;border-radius:999px;font-size:12px;backdrop-filter:blur(7px)}.deliverables a:hover{background:rgba(69,226,209,.17);border-color:rgba(110,245,224,.55)}
.shell{max-width:1580px;margin:0 auto;padding:21px}.tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}.tab{border:1px solid var(--line);background:rgba(255,255,255,.9);color:var(--ink);padding:9px 14px;border-radius:11px;cursor:pointer;font-weight:760;box-shadow:0 6px 18px rgba(8,43,51,.04)}.tab.active{background:linear-gradient(135deg,#092c36,#07525a);color:#fff;border-color:#07525a}.view{display:none}.view.active{display:block}.kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:14px}.kpi{background:linear-gradient(145deg,#fff,#f8fbfa);border:1px solid var(--line);border-radius:16px;padding:14px 16px;box-shadow:0 9px 25px rgba(13,47,45,.055);position:relative;overflow:hidden}.kpi:after{content:"";position:absolute;inset:auto 0 0;height:3px;background:linear-gradient(90deg,#13a7a7,#68e6c6);opacity:.68}.kpi .label{font-size:11px;color:var(--muted);font-weight:780}.kpi strong{display:block;font-size:25px;margin-top:3px;letter-spacing:-.025em}.grid{display:grid;grid-template-columns:minmax(0,2.35fr) minmax(300px,.65fr);gap:14px}.card{background:var(--card);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow);overflow:hidden}.card-head{display:flex;align-items:center;justify-content:space-between;padding:13px 15px;border-bottom:1px solid var(--line)}.card-head h2,.card-head h3{font-size:15px;margin:0}.card-body{padding:15px}.controls{display:flex;gap:8px;flex-wrap:wrap;align-items:end}.control{display:grid;gap:4px;font-size:10px;color:var(--muted);font-weight:760}.control select,.control input{border:1px solid var(--line);background:#fff;border-radius:9px;padding:7px 8px;color:var(--ink);min-width:104px;outline:none}.control input{min-width:170px}.layer-row{display:flex;gap:6px;flex-wrap:wrap}.chip{border:1px solid var(--line);background:#fff;padding:7px 9px;border-radius:999px;cursor:pointer;font-size:10px;font-weight:730}.chip.active{background:#dff7f1;border-color:#73d5c3;color:#075f62}.map-card{border-color:#173f4a;background:#071c26;box-shadow:0 24px 65px rgba(4,27,36,.24)}.map-card .card-head{background:linear-gradient(135deg,#092631,#0a3640);border-color:rgba(111,225,214,.15)}.map-card .control{color:#9cc2c3}.map-card .control select{background:#0c3039;border-color:#27505a;color:#effffc;color-scheme:dark}.map-card .chip{background:#0d303a;border-color:#28505b;color:#bcd5d5}.map-card .chip.active{background:rgba(48,220,198,.14);border-color:#39b9aa;color:#8df4df}.map-wrap{height:590px;position:relative;isolation:isolate;background:#061923;overflow:hidden}.map-wrap:after{content:"";position:absolute;inset:0;pointer-events:none;box-shadow:inset 0 0 70px rgba(0,0,0,.38);z-index:3}#map{width:100%;height:100%;display:block;cursor:grab;position:relative;z-index:1}#map.dragging{cursor:grabbing}.map-note,.map-coordinates,.map-badge{position:absolute;background:rgba(4,23,31,.8);border:1px solid rgba(117,237,220,.22);z-index:5;backdrop-filter:blur(8px);pointer-events:none}.map-note{left:14px;bottom:13px;border-radius:9px;padding:7px 10px;font-size:10px;color:#a9c9c9}.map-coordinates{right:14px;bottom:13px;min-width:205px;text-align:right;border-radius:9px;padding:7px 10px;color:#b7d4d4;font:10px ui-monospace,SFMono-Regular,Menlo,monospace}.map-badge{left:14px;top:13px;display:flex;align-items:center;gap:7px;border-radius:999px;padding:7px 10px;color:#b8d9d7;font-size:10px;letter-spacing:.08em}.map-badge i{width:7px;height:7px;border-radius:50%;background:#4df3d2;box-shadow:0 0 12px #4df3d2}.map-badge b{color:#71f3dc}.map-credit{position:absolute;right:14px;top:13px;color:rgba(187,218,217,.72);font-size:9px;z-index:5;pointer-events:none}.tooltip{position:absolute;display:none;pointer-events:none;background:rgba(4,22,31,.94);color:#f2fffd;padding:9px 11px;border:1px solid rgba(93,231,212,.32);border-radius:9px;font-size:11px;box-shadow:0 16px 34px rgba(0,0,0,.3);max-width:280px;z-index:7}.map-card .card-body{background:linear-gradient(180deg,#091f29,#071b24);border-top:1px solid rgba(111,225,214,.12)}.value-legend{height:10px;border-radius:999px;background:linear-gradient(90deg,#4777ff,#30d7e8,#43efbd,#ffe15c,#ff647e);margin:4px 0;box-shadow:0 0 17px rgba(48,215,232,.14)}.legend-labels{display:flex;justify-content:space-between;gap:10px;font-size:10px;color:#9ebcbd}.legend-labels span:nth-child(2){text-align:center}.category-legend{display:none;gap:9px 15px;flex-wrap:wrap;align-items:center;margin:2px 0;color:#b5cdcd;font-size:10px}.category-legend span{display:flex;align-items:center;gap:6px}.category-legend i{width:9px;height:9px;border-radius:50%;box-shadow:0 0 10px currentColor}.symbol-legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:9px;color:#9dbabb;font-size:10px}.symbol-legend span{display:flex;align-items:center;gap:6px}.symbol-legend i{width:8px;height:8px;border-radius:50%}.symbol-legend .normal{background:#49ebc5}.symbol-legend .censored{background:transparent;border:1.5px solid #cb91ff}.symbol-legend .high{background:#ff637b}.symbol-legend .low{background:#5caeff}.detail-empty{color:var(--muted);line-height:1.7}.record-title{font-weight:850;font-size:16px;overflow-wrap:anywhere}.value{font-size:26px;font-weight:850;color:var(--teal);margin:8px 0}.badges,.flags{display:flex;gap:5px;flex-wrap:wrap}.badge,.flag{font-size:10px;padding:4px 7px;border-radius:999px;background:#edf3ef;color:#3e5c55}.flag{border-radius:5px;background:#f5eee2;color:#80561f}.kv{display:grid;grid-template-columns:104px 1fr;gap:7px 9px;font-size:11px;margin-top:14px}.kv dt{color:var(--muted)}.kv dd{margin:0;overflow-wrap:anywhere}.source-link{display:inline-flex;margin-top:12px;color:#087d83;font-weight:750;text-decoration:none}.section-title{font-size:22px;margin:4px 0 5px}.section-lead{color:var(--muted);line-height:1.7;margin:0 0 14px}.source-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.source-card{background:#fff;border:1px solid var(--line);border-radius:15px;padding:16px}.source-card h3{margin:3px 0 5px;font-size:16px}.source-card p{color:var(--muted);font-size:11px;line-height:1.55}.mini-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0}.mini{background:#f3f7f4;border-radius:9px;padding:8px}.mini b{display:block;font-size:16px}.mini span{font-size:10px;color:var(--muted)}.meter{height:8px;background:#e7eeea;border-radius:999px;overflow:hidden}.meter span{display:block;height:100%;background:linear-gradient(90deg,#16878a,#63e1c3)}.table-wrap{overflow:auto;max-height:650px;border:1px solid var(--line);border-radius:13px;background:#fff}table{width:100%;border-collapse:collapse;font-size:11px}th{position:sticky;top:0;background:#edf4f0;color:#45615a;text-align:left;padding:10px;z-index:1}td{border-top:1px solid #e7ede9;padding:9px 10px}.quality-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.callout{border-left:4px solid var(--gold);background:#fff8e9;padding:13px 15px;border-radius:0 10px 10px 0;color:#70511e;font-size:12px;line-height:1.65}.bar-row{display:grid;grid-template-columns:minmax(170px,1fr) 3fr 80px;align-items:center;gap:9px;font-size:12px;margin:8px 0}.bar{height:10px;background:#edf1ee;border-radius:999px;overflow:hidden}.bar span{height:100%;display:block;background:#5b9f8b}.footer{max-width:1580px;margin:0 auto;padding:4px 22px 30px;color:var(--muted);font-size:11px}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}.muted{color:var(--muted)}
.check{display:flex;align-items:center;gap:5px;color:#bcd5d5;font-size:10px;padding:7px 2px;white-space:nowrap}.check input{accent-color:#43efbd}
@media(max-width:1120px){.grid,.quality-grid{grid-template-columns:1fr}.source-grid{grid-template-columns:1fr}.map-wrap{height:560px}}@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.map-card .card-head{align-items:flex-start;gap:12px;flex-direction:column}.map-wrap{height:480px}.map-credit{display:none}}@media(max-width:560px){.shell{padding:12px}.hero{padding:28px 18px}.kpi strong{font-size:20px}.map-wrap{height:420px}.control{width:100%}.control select,.control input{width:100%}.bar-row{grid-template-columns:1fr}.mini-grid{grid-template-columns:1fr 1fr}.map-coordinates{display:none}.map-note{right:12px}}
</style>
</head>
<body>
<header class="hero"><div class="eyebrow">AI4S · D3 evidence-first visualization</div><h1>全球地球化学元素图谱</h1><p>把 D2 标准化记录、候选异常和质量证据转换为离线可复用地图。默认展示全部数据覆盖；浓度色阶只在元素、介质、basis、方法组和单位均可比较时启用。候选异常不代表污染、矿化或成因。</p><nav class="deliverables"><a href="geochemistry.csv">标准化数据库 ↗</a><a href="source_manifest.json">来源证据 ↗</a><a href="confidence_report.json">置信度说明 ↗</a><a href="anomalies.geojson">候选异常 ↗</a><a href="anomaly_report.json">异常方法报告 ↗</a></nav></header>
<main class="shell">
<nav class="tabs"><button class="tab active" data-view="mapView">元素地图</button><button class="tab" data-view="sourceView">来源与置信度</button><button class="tab" data-view="anomalyView">异常结果</button><button class="tab" data-view="qualityView">质量与边界</button></nav>
<section id="mapView" class="view active">
  <div class="kpis"><div class="kpi"><span class="label">可上图测定记录</span><strong id="kRecords">—</strong></div><div class="kpi"><span class="label">当前地图采样点</span><strong id="kSamples">—</strong></div><div class="kpi"><span class="label">删失记录</span><strong id="kCensored">—</strong></div><div class="kpi"><span class="label">候选异常</span><strong id="kAnomaly">—</strong></div><div class="kpi"><span class="label">总览范围</span><strong id="kScope">—</strong></div></div>
  <div class="grid"><article class="card map-card"><div class="card-head"><div class="controls"><label class="control">元素<select id="element"></select></label><label class="control">介质<select id="medium"></select></label><label class="control">地质单元<select id="geology"></select></label><label class="control">方法组<select id="method"></select></label><label class="control">来源<select id="source"></select></label><label class="control">置信度<select id="confidence"></select></label><label class="check"><input id="anomalyOnly" type="checkbox">仅候选异常</label></div><div class="layer-row"><button class="chip active" data-layer="points">观测点</button><button class="chip" data-layer="density">光晕密度</button><button class="chip active" data-layer="anomalies">异常点</button><button class="chip" id="focus">聚焦数据</button><button class="chip active" id="world">全球视图</button></div></div><div class="map-wrap"><canvas id="map" role="img" aria-label="WGS84 全球地球化学样点地图"></canvas><div id="tooltip" class="tooltip"></div><div class="map-badge"><i></i><span>GEOCHEM ATLAS</span><b id="mapScope">ALL DATA</b></div><div class="map-credit">Natural Earth 1:110m · public domain · WGS84</div><div id="coordinateHud" class="map-coordinates">GLOBAL · 360° × 180°</div><div id="mapNote" class="map-note">全部元素按样品去重显示；颜色表示介质</div></div><div class="card-body"><div id="valueLegend" class="value-legend"></div><div class="legend-labels"><span id="legendMin"></span><span id="legendTitle">介质分类总览</span><span id="legendMax"></span></div><div id="categoryLegend" class="category-legend"></div><div class="symbol-legend"><span><i class="normal"></i>定量观测</span><span><i class="censored"></i>删失值</span><span><i class="high"></i>高值候选</span><span><i class="low"></i>低值候选</span></div></div></article><aside class="card"><div class="card-head"><h2>记录级证据</h2><label class="control">查找 record ID<input id="recordSearch" placeholder="输入后回车"></label></div><div class="card-body" id="detail"><p class="detail-empty">点击地图观测点，查看原值、标准值、方法、限定符、QC、置信度和来源定位。</p></div></aside></div>
</section>
<section id="sourceView" class="view"><h2 class="section-title">来源与工作流置信度</h2><p class="section-lead">卡片统计当前可上图记录；证据等级与许可结论直接消费 D1 manifest。置信度表示工作流可用性，不是科学真实性概率。</p><div id="sourceBoundary" class="callout"></div><div id="sourceGrid" class="source-grid" style="margin-top:13px"></div></section>
<section id="anomalyView" class="view"><h2 class="section-title">候选异常识别结果</h2><p class="section-lead">直接展示 D2 输出，不在 D3 重算阈值或背景组。候选只表示相对声明背景的筛查结果。</p><div id="anomalySummary" class="callout"></div><div class="table-wrap" style="margin-top:13px"><table><thead><tr><th>记录</th><th>元素</th><th>介质</th><th>方向</th><th>标准值</th><th>robust z</th><th>背景组</th><th>来源</th></tr></thead><tbody id="anomalyTable"></tbody></table></div></section>
<section id="qualityView" class="view"><h2 class="section-title">质量、覆盖与解释边界</h2><p class="section-lead">缺失坐标记录仍留在数据库和 QC 报告中；地图不放到零岛、不插值空白区域。</p><div class="quality-grid"><article class="card"><div class="card-head"><h3>QC flags</h3></div><div class="card-body" id="qcBars"></div></article><article class="card"><div class="card-head"><h3>覆盖与失败可见化</h3></div><div class="card-body" id="coverageSummary"></div></article></div></section>
</main>
<footer class="footer">离线、自包含、数据驱动。D3 仅消费公共 D1/D2 产物，不更改标准值、置信度或候选异常判定。</footer>
<script id="samples-data" type="application/json">__SAMPLES_JSON__</script>
<script id="anomalies-data" type="application/json">__ANOMALIES_JSON__</script>
<script id="basemap-data" type="application/json">__BASEMAP_JSON__</script>
<script id="context-data" type="application/json">__CONTEXT_JSON__</script>
<script>
"use strict";
const FC=JSON.parse(document.getElementById("samples-data").textContent);
const AF=JSON.parse(document.getElementById("anomalies-data").textContent);
const BASE=JSON.parse(document.getElementById("basemap-data").textContent);
const CTX=JSON.parse(document.getElementById("context-data").textContent);
const samples=FC.features.map(f=>({...f.properties,longitude:f.geometry.coordinates[0],latitude:f.geometry.coordinates[1]}));
const anomalyFeatures=AF.features||[];
const $=id=>document.getElementById(id),fmt=new Intl.NumberFormat("zh-CN"),esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const MEDIUM_STYLE={rock:["#54a7ff","岩石"],soil:["#ffe15c","土壤"],sediment:["#ff8a65","沉积物"],water:["#43efbd","水体"],mineral:["#c790ff","矿物"],concentrate:["#ff78cf","精矿"]};
const layers={points:true,density:false,anomalies:true};
let W=1,H=1,ready=false,drag=null,view={w:-180,e:180,s:-90,n:90},viewMode="world",currentRows=[],displayRows=[],hitRows=[],valueDomain=[0,1],quantitative=false,hoverFrame=0;

function unique(key){return [...new Set(samples.map(row=>row[key]).filter(value=>value!==null&&value!==undefined&&value!==""))].sort()}
function methodName(row){return row.method_family||row.analytical_method||"unknown"}
function fillSelect(id,values,label){const node=$(id);node.replaceChildren();const all=document.createElement("option");all.value="";all.textContent=label;node.append(all);for(const value of values){const option=document.createElement("option");option.value=value;option.textContent=value;node.append(option)}}
fillSelect("element",unique("element"),"全部");fillSelect("medium",unique("medium"),"全部");fillSelect("geology",unique("geologic_unit"),"全部");fillSelect("method",[...new Set(samples.map(methodName))].sort(),"全部");fillSelect("source",unique("source_id"),"全部");fillSelect("confidence",unique("confidence_band"),"全部");

document.querySelectorAll(".tab").forEach(button=>button.onclick=()=>{document.querySelectorAll(".tab,.view").forEach(node=>node.classList.remove("active"));button.classList.add("active");$(button.dataset.view).classList.add("active");if(button.dataset.view==="mapView")resize()});
document.querySelectorAll("[data-layer]").forEach(button=>button.onclick=()=>{const name=button.dataset.layer;layers[name]=!layers[name];button.classList.toggle("active",layers[name]);render()});
for(const id of["element","medium","geology","method","source","confidence","anomalyOnly"])$(id).onchange=()=>{worldView();render()};

function filteredRows(){return samples.filter(row=>(!$("element").value||row.element===$("element").value)&&(!$("medium").value||row.medium===$("medium").value)&&(!$("geology").value||row.geologic_unit===$("geology").value)&&(!$("method").value||methodName(row)===$("method").value)&&(!$("source").value||row.source_id===$("source").value)&&(!$("confidence").value||row.confidence_band===$("confidence").value)&&(!$("anomalyOnly").checked||row.candidate_anomaly))}
function sampleLevel(rows){if($("element").value)return rows;const grouped=new Map();for(const row of rows){const identity=row.sample_id?`${row.source_id}|${row.sample_id}|${row.medium}|${row.longitude.toFixed(5)}|${row.latitude.toFixed(5)}`:`record|${row.record_id}`;const previous=grouped.get(identity);if(!previous||(previous.censored&&!row.censored))grouped.set(identity,row)}return[...grouped.values()]}
function canUseValueScale(rows){if(!$("element").value)return false;const quantified=rows.filter(row=>row.value>0&&row.unit),media=new Set(rows.map(row=>row.medium||"unknown")),units=new Set(rows.map(row=>row.unit||"unknown")),basis=new Set(rows.map(row=>row.measurement_basis||"unknown")),methods=new Set(rows.map(methodName));return quantified.length>0&&media.size===1&&units.size===1&&!units.has("unknown")&&basis.size===1&&!basis.has("unknown")&&methods.size===1&&!methods.has("unknown")}
function mediumStyle(name){return MEDIUM_STYLE[name]||["#c790ff",name||"未知介质"]}
function valueColor(value){if(!(value>0))return"#8299a0";const[a,b]=valueDomain,t=Math.max(0,Math.min(1,(Math.log10(value)-a)/(b-a||1))),stops=[[71,119,255],[48,215,232],[67,239,189],[255,225,92],[255,100,126]],q=t*(stops.length-1),i=Math.min(stops.length-2,Math.floor(q)),fraction=q-i,color=stops[i].map((channel,index)=>Math.round(channel+(stops[i+1][index]-channel)*fraction));return`rgb(${color.join(",")})`}
function pointColor(row){return quantitative?valueColor(row.value):mediumStyle(row.medium)[0]}

const canvas=$("map"),ctx=canvas.getContext("2d"),tip=$("tooltip"),coordinateHud=$("coordinateHud");
function sx(value){return(value-view.w)/(view.e-view.w)*W}function sy(value){return(view.n-value)/(view.n-view.s)*H}function longitude(px){return view.w+px/W*(view.e-view.w)}function latitude(py){return view.n-py/H*(view.n-view.s)}
function visible(x,y,pad=0){return x>=view.w-pad&&x<=view.e+pad&&y>=view.s-pad&&y<=view.n+pad}
function setBounds(bounds,padding=.06){let{w,e,s,n}=bounds,dx=Math.max(.15,e-w),dy=Math.max(.12,n-s);w-=dx*padding;e+=dx*padding;s-=dy*padding;n+=dy*padding;dx=e-w;dy=n-s;const aspect=Math.max(.4,W/Math.max(H,1));if(dx/dy>aspect){const target=dx/aspect,extra=(target-dy)/2;s-=extra;n+=extra}else{const target=dy*aspect,extra=(target-dx)/2;w-=extra;e+=extra}view={w,e,s,n}}
function worldView(){viewMode="world";setBounds({w:-180,e:180,s:-90,n:90},.018);const all=["element","medium","geology","method","source","confidence"].every(id=>!$(id).value)&&!$("anomalyOnly").checked;$("mapScope").textContent=all?"ALL DATA":"GLOBAL";$("world").classList.add("active")}
function fitData(){const rows=filteredRows();if(!rows.length)return;let w=Infinity,e=-Infinity,s=Infinity,n=-Infinity;for(const row of rows){w=Math.min(w,row.longitude);e=Math.max(e,row.longitude);s=Math.min(s,row.latitude);n=Math.max(n,row.latitude)}viewMode="data";setBounds({w,e,s,n},.1);$("mapScope").textContent="FOCUS";$("world").classList.remove("active")}
function resize(){const rect=canvas.getBoundingClientRect(),dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.max(1,rect.width*dpr);canvas.height=Math.max(1,rect.height*dpr);W=rect.width;H=rect.height;ctx.setTransform(dpr,0,0,dpr,0,0);if(viewMode==="world")worldView();else if(viewMode==="data")fitData();ready=true;render()}
new ResizeObserver(resize).observe(canvas);$("world").onclick=()=>{worldView();render()};$("focus").onclick=()=>{fitData();render()};
canvas.onwheel=event=>{event.preventDefault();const rect=canvas.getBoundingClientRect(),px=event.clientX-rect.left,py=event.clientY-rect.top,cx=longitude(px),cy=latitude(py),factor=event.deltaY>0?1.16:.86,current=view.e-view.w,zoom=current*factor<.2||current*factor>430?1:factor;view={w:cx+(view.w-cx)*zoom,e:cx+(view.e-cx)*zoom,s:cy+(view.s-cy)*zoom,n:cy+(view.n-cy)*zoom};viewMode="manual";$("mapScope").textContent=`ZOOM ${(360/(view.e-view.w)).toFixed(1)}×`;$("world").classList.remove("active");render()};
canvas.onpointerdown=event=>{drag={x:event.clientX,y:event.clientY,v:{...view}};canvas.setPointerCapture(event.pointerId);canvas.classList.add("dragging")};canvas.onpointerup=()=>{drag=null;canvas.classList.remove("dragging")};canvas.onpointercancel=canvas.onpointerup;canvas.onpointerleave=()=>{tip.style.display="none";coordinateHud.textContent=`${$("mapScope").textContent} · ${(view.e-view.w).toFixed(1)}° VIEW`};canvas.onpointermove=event=>{const rect=canvas.getBoundingClientRect(),mx=event.clientX-rect.left,my=event.clientY-rect.top;coordinateHud.textContent=`${latitude(my).toFixed(3)}° ${latitude(my)>=0?"N":"S"} · ${longitude(mx).toFixed(3)}° ${longitude(mx)>=0?"E":"W"} · ${(360/(view.e-view.w)).toFixed(1)}×`;if(drag){const dx=(event.clientX-drag.x)/W*(drag.v.e-drag.v.w),dy=(event.clientY-drag.y)/H*(drag.v.n-drag.v.s);view={w:drag.v.w-dx,e:drag.v.e-dx,s:drag.v.s+dy,n:drag.v.n+dy};viewMode="manual";$("mapScope").textContent="EXPLORE";$("world").classList.remove("active");render();return}cancelAnimationFrame(hoverFrame);hoverFrame=requestAnimationFrame(()=>hover(event))};

function degreeLabel(value,axis){if(value===0)return"0°";const suffix=axis==="x"?(value>0?"E":"W"):(value>0?"N":"S");return`${Math.abs(value)}°${suffix}`}
function traceLand(){ctx.beginPath();for(const ring of BASE.rings){let previous=null,started=false;for(const point of ring){if(previous&&Math.abs(point[0]-previous[0])>180)started=false;if(!started){ctx.moveTo(sx(point[0]),sy(point[1]));started=true}else ctx.lineTo(sx(point[0]),sy(point[1]));previous=point}ctx.closePath()}}
function renderBasemap(){const ocean=ctx.createLinearGradient(0,0,W,H);ocean.addColorStop(0,"#061923");ocean.addColorStop(.52,"#082630");ocean.addColorStop(1,"#0a202b");ctx.fillStyle=ocean;ctx.fillRect(0,0,W,H);const glow=ctx.createRadialGradient(W*.72,H*.22,0,W*.72,H*.22,Math.max(W,H)*.72);glow.addColorStop(0,"rgba(21,108,116,.16)");glow.addColorStop(1,"rgba(4,18,27,0)");ctx.fillStyle=glow;ctx.fillRect(0,0,W,H);const span=view.e-view.w,step=span>260?30:span>120?20:span>55?10:span>20?5:2;ctx.lineWidth=1;ctx.font="9px ui-monospace,SFMono-Regular,Menlo,monospace";ctx.textAlign="center";ctx.textBaseline="top";for(let x=Math.ceil(view.w/step)*step;x<=view.e;x+=step){ctx.strokeStyle=x===0?"rgba(99,229,216,.24)":"rgba(128,181,184,.105)";ctx.beginPath();ctx.moveTo(sx(x),0);ctx.lineTo(sx(x),H);ctx.stroke();if(sx(x)>28&&sx(x)<W-28){ctx.fillStyle="rgba(148,190,191,.5)";ctx.fillText(degreeLabel(x,"x"),sx(x),H-17)}}ctx.textAlign="left";ctx.textBaseline="middle";for(let y=Math.ceil(view.s/step)*step;y<=view.n;y+=step){ctx.strokeStyle=y===0?"rgba(99,229,216,.24)":"rgba(128,181,184,.105)";ctx.beginPath();ctx.moveTo(0,sy(y));ctx.lineTo(W,sy(y));ctx.stroke();if(sy(y)>25&&sy(y)<H-25){ctx.fillStyle="rgba(148,190,191,.5)";ctx.fillText(degreeLabel(y,"y"),7,sy(y))}}traceLand();const land=ctx.createLinearGradient(0,0,0,H);land.addColorStop(0,"#174753");land.addColorStop(.5,"#113a46");land.addColorStop(1,"#0d303c");ctx.fillStyle=land;ctx.shadowColor="rgba(55,218,202,.14)";ctx.shadowBlur=10;ctx.fill("evenodd");ctx.shadowBlur=0;ctx.strokeStyle="rgba(113,204,197,.5)";ctx.lineWidth=span>180?1.05:1.45;ctx.stroke()}
function renderDensity(){const bins=new Map(),dx=Math.max(2,(view.e-view.w)/42),dy=Math.max(2,(view.n-view.s)/26);for(const row of displayRows){if(!visible(row.longitude,row.latitude))continue;const x=Math.floor((row.longitude-view.w)/dx),y=Math.floor((row.latitude-view.s)/dy),key=`${x},${y}`;bins.set(key,(bins.get(key)||0)+1)}const maximum=Math.max(1,...bins.values());ctx.save();ctx.globalCompositeOperation="screen";for(const[key,count]of bins){const[x,y]=key.split(",").map(Number),cx=sx(view.w+(x+.5)*dx),cy=sy(view.s+(y+.5)*dy),radius=Math.max(12,Math.min(54,13+Math.sqrt(count/maximum)*42)),gradient=ctx.createRadialGradient(cx,cy,0,cx,cy,radius);gradient.addColorStop(0,`rgba(51,236,207,${.1+.38*Math.sqrt(count/maximum)})`);gradient.addColorStop(.42,`rgba(34,170,194,${.07+.2*Math.sqrt(count/maximum)})`);gradient.addColorStop(1,"rgba(20,110,150,0)");ctx.fillStyle=gradient;ctx.fillRect(cx-radius,cy-radius,radius*2,radius*2)}ctx.restore()}
function renderPoints(){const span=view.e-view.w,zoom=Math.sqrt(360/Math.max(span,.1)),radius=Math.max(1.75,Math.min(3.4,1.8*zoom)),shown=displayRows.filter(row=>visible(row.longitude,row.latitude,1));hitRows=shown;ctx.save();if(shown.length<9000){ctx.globalCompositeOperation="screen";for(const row of shown){if(row.censored)continue;ctx.beginPath();ctx.arc(sx(row.longitude),sy(row.latitude),radius*2.9,0,Math.PI*2);ctx.fillStyle=pointColor(row);ctx.globalAlpha=.14;ctx.fill()}ctx.globalCompositeOperation="source-over"}for(const row of shown){ctx.beginPath();ctx.arc(sx(row.longitude),sy(row.latitude),row.censored?radius+1:radius,0,Math.PI*2);if(row.censored){ctx.fillStyle="rgba(8,28,38,.92)";ctx.strokeStyle="#d099ff";ctx.lineWidth=1.35;ctx.globalAlpha=.95;ctx.fill();ctx.stroke()}else{ctx.fillStyle=pointColor(row);ctx.strokeStyle="rgba(235,255,252,.66)";ctx.lineWidth=.5;ctx.globalAlpha=.9;ctx.fill();ctx.stroke()}}ctx.restore()}
function directionFor(row){const feature=anomalyFeatures.find(item=>item.properties?.record_id===row.record_id);return feature?.properties?.direction||"high"}
function renderAnomalies(){const span=view.e-view.w,size=Math.max(4.3,Math.min(7,5*Math.sqrt(360/Math.max(span,.1))));ctx.save();for(const row of currentRows.filter(item=>item.candidate_anomaly)){if(!visible(row.longitude,row.latitude,1))continue;const x=sx(row.longitude),y=sy(row.latitude),low=directionFor(row)==="low",color=low?"#59adff":"#ff617b";ctx.strokeStyle=color;ctx.globalAlpha=.35;ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(x,y,size+4,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;ctx.shadowColor=color;ctx.shadowBlur=12;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(x,y-size);ctx.lineTo(x+size*.7,y);ctx.lineTo(x,y+size);ctx.lineTo(x-size*.7,y);ctx.closePath();ctx.fill();ctx.shadowBlur=0;ctx.fillStyle="#f5fffd";ctx.beginPath();ctx.arc(x,y,1.25,0,Math.PI*2);ctx.fill()}ctx.restore()}

function renderLegend(){const valueLegend=$("valueLegend"),categoryLegend=$("categoryLegend");if(quantitative){const values=currentRows.map(row=>row.value).filter(value=>value>0).sort((a,b)=>a-b),lo=values[Math.floor(values.length*.03)],hi=values[Math.floor(values.length*.97)],unit=currentRows.find(row=>row.value>0)?.unit;valueDomain=[Math.log10(Math.max(lo,1e-12)),Math.log10(Math.max(hi,1e-12))];valueLegend.style.display="block";categoryLegend.style.display="none";$("legendMin").textContent=`${lo.toPrecision(3)} ${unit}`;$("legendMax").textContent=`${hi.toPrecision(3)} ${unit}`;$("legendTitle").textContent="同元素 · 同介质 · 同 basis · 同方法组 · 稳健 log 色阶";$("mapNote").textContent="浓度色阶只描述当前可比组；仍需点击记录核对来源、方法与 QC";return}valueLegend.style.display="none";$("legendMin").textContent="";$("legendMax").textContent="";$("legendTitle").textContent="介质分类总览 · 不跨元素、介质或单位比较浓度";const counts=new Map();for(const row of displayRows)counts.set(row.medium,(counts.get(row.medium)||0)+1);categoryLegend.innerHTML=[...counts.entries()].sort().map(([name,count])=>{const[color,label]=mediumStyle(name);return`<span style="color:${color}"><i style="background:${color}"></i>${esc(label)} · ${fmt.format(count)} 点</span>`}).join("");categoryLegend.style.display="flex";$("mapNote").textContent=!$("element").value?`全部元素按样品标识去重显示 ${fmt.format(displayRows.length)} 个采样点（KPI 为测定记录）；颜色表示介质`:`当前筛选不可直接共用浓度色阶；颜色表示介质，请继续收敛 basis/方法组`}
function render(){if(!ready)return;currentRows=filteredRows();displayRows=sampleLevel(currentRows);quantitative=canUseValueScale(currentRows);renderLegend();renderBasemap();if(layers.density)renderDensity();if(layers.points)renderPoints();else hitRows=[];if(layers.anomalies)renderAnomalies();$("kRecords").textContent=fmt.format(currentRows.length);$("kSamples").textContent=fmt.format(displayRows.length);$("kCensored").textContent=fmt.format(currentRows.filter(row=>row.censored).length);$("kAnomaly").textContent=fmt.format(currentRows.filter(row=>row.candidate_anomaly).length);$("kScope").textContent=`${new Set(currentRows.map(row=>row.element)).size} 元素 · ${new Set(currentRows.map(row=>row.medium)).size} 介质`}
function nearest(event){const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;let best=null,distance=14*14;for(const row of hitRows){const candidate=(sx(row.longitude)-x)**2+(sy(row.latitude)-y)**2;if(candidate<distance){best=row;distance=candidate}}return best}
function hover(event){const row=nearest(event);if(!row){tip.style.display="none";return}const rect=canvas.getBoundingClientRect();tip.style.display="block";tip.style.left=`${Math.min(W-260,event.clientX-rect.left+12)}px`;tip.style.top=`${Math.max(8,event.clientY-rect.top-42)}px`;tip.textContent=`${row.element} · ${row.value??row.original_value_raw??"未定量"} ${row.unit||row.original_unit||""} · ${row.record_id}`}
canvas.onclick=event=>{const row=nearest(event);if(row)showRecord(row)};
function showRecord(row){const flags=(row.qc_flags||[]).map(flag=>`<span class="flag">${esc(flag)}</span>`).join(" "),url=row.source_locator&&row.source_locator.startsWith("https://")?`<a class="source-link" href="${esc(row.source_locator)}" target="_blank" rel="noopener">打开原始来源定位 ↗</a>`:"";$("detail").innerHTML=`<div class="record-title mono">${esc(row.record_id)}</div><div class="value">${esc(row.value??"未标准化")} ${esc(row.unit||"")}</div><div class="badges"><span class="badge">${esc(row.confidence_band)} · ${esc(row.confidence_overall??"—")}</span><span class="badge">${esc(row.medium)}</span>${row.censored?'<span class="badge">删失值</span>':''}</div><dl class="kv"><dt>元素 / analyte</dt><dd>${esc(row.element)} / ${esc(row.analyte_reported||"—")}</dd><dt>原始值</dt><dd>${esc(row.original_value_raw??"—")} ${esc(row.original_unit||"")} · ${esc(row.source_qualifier_raw||row.qualifier||"—")}</dd><dt>样品 ID</dt><dd>${esc(row.sample_id||"未提供")}</dd><dt>介质 / basis</dt><dd>${esc(row.medium)} / ${esc(row.measurement_basis||"未提供")}</dd><dt>地质单元</dt><dd>${esc(row.geologic_unit||"未提供")}</dd><dt>分析方法</dt><dd>${esc(row.analytical_method||"未提供")} · ${esc(methodName(row))}</dd><dt>消解 / 提取</dt><dd>${esc(row.digestion_or_extraction||"未提供")}</dd><dt>坐标</dt><dd>${row.latitude.toFixed(5)}, ${row.longitude.toFixed(5)}</dd><dt>来源</dt><dd>${esc(row.source_id||"未提供")}<br>${esc(row.source_locator||"未提供")}</dd><dt>许可</dt><dd>${esc(row.license||"未声明")}</dd><dt>QC</dt><dd>${flags||"无 flag"}</dd></dl>${url}`}
$("recordSearch").onkeydown=event=>{if(event.key!=="Enter")return;const query=event.target.value.trim(),row=samples.find(item=>item.record_id===query);if(row){showRecord(row);viewMode="manual";setBounds({w:row.longitude-3,e:row.longitude+3,s:row.latitude-2,n:row.latitude+2},.04);$("mapScope").textContent="RECORD";$("world").classList.remove("active");render()}else $("detail").innerHTML=`<p class="detail-empty">未在可上图记录中找到 <span class="mono">${esc(query)}</span>；它可能因坐标 QC 仍只保留在标准化数据库中。</p>`};

function median(values){if(!values.length)return null;const sorted=[...values].sort((a,b)=>a-b),middle=Math.floor(sorted.length/2);return sorted.length%2?sorted[middle]:(sorted[middle-1]+sorted[middle])/2}
function renderSources(){const grouped=new Map();for(const row of samples){const key=row.source_id||"unknown",group=grouped.get(key)||[];group.push(row);grouped.set(key,group)}const manifestSources=new Map((CTX.source_manifest.sources||[]).map(source=>[source.source_id,source]));$("sourceBoundary").innerHTML=`<strong>证据边界：</strong>${esc(CTX.source_manifest.claim_boundary||"来源字段来自输入声明；使用前需逐条核对。")}`;$("sourceGrid").innerHTML=[...grouped.entries()].sort().map(([sourceId,rows])=>{const source=manifestSources.get(sourceId)||{},confidence=median(rows.map(row=>row.confidence_overall).filter(value=>value!==null)),sampleCount=sampleLevel(rows).length,methods=[...new Set(rows.map(methodName))].slice(0,5).join(" / ");return`<article class="source-card"><div class="eyebrow" style="color:var(--teal)">${esc(sourceId)}</div><h3>${esc(rows.find(row=>row.dataset_title)?.dataset_title||source.dataset_titles?.[0]||"未提供数据集标题")}</h3><p>版本：${esc(rows.find(row=>row.dataset_version)?.dataset_version||source.dataset_versions?.[0]||"未提供")}<br>许可：${esc((source.licenses||[...new Set(rows.map(row=>row.license).filter(Boolean))]).join(", ")||"未声明")}</p><div class="mini-grid"><div class="mini"><b>${fmt.format(rows.length)}</b><span>可上图测定</span></div><div class="mini"><b>${fmt.format(sampleCount)}</b><span>采样点</span></div><div class="mini"><b>${confidence===null?"—":confidence.toFixed(3)}</b><span>置信度中位数</span></div></div><div class="muted" style="font-size:10px">方法组：${esc(methods||"unknown")}</div><div class="meter" style="margin-top:7px"><span style="width:${Math.max(0,Math.min(100,(confidence||0)*100))}%"></span></div></article>`}).join("")}
function cell(value,className=""){const td=document.createElement("td");td.textContent=value??"—";if(className)td.className=className;return td}
function renderAnomalyTable(){const report=CTX.anomaly_report,features=anomalyFeatures;$("anomalySummary").innerHTML=`D2 输出 <strong>${fmt.format(report.candidate_count??features.length)}</strong> 个候选；方法 <span class="mono">${esc(report.method_version||AF.method_version||"未声明")}</span>，阈值 |z| ≥ ${esc(report.robust_z_threshold??"未声明")}，最小背景组 ${esc(report.minimum_group_size??"未声明")}。${esc(report.caveat||"")}`;const body=$("anomalyTable");body.replaceChildren();for(const feature of features){const p=feature.properties||{},tr=document.createElement("tr");tr.append(cell(p.record_id,"mono"),cell(p.element_or_analyte),cell(p.medium),cell(p.direction),cell(`${p.normalized_value??"—"} ${p.normalized_unit??""}`),cell(p.robust_z),cell(p.group_id,"mono"),cell(p.source_id));body.append(tr)}if(!features.length){const tr=document.createElement("tr"),td=cell("当前运行未产生候选异常");td.colSpan=8;tr.append(td);body.append(tr)}}
function renderQuality(){const qc=CTX.qc_report,flags=Object.entries(qc.flag_counts||{}).sort((a,b)=>b[1]-a[1]),maximum=Math.max(1,...flags.map(item=>item[1]));$("qcBars").innerHTML=flags.length?flags.map(([name,count])=>`<div class="bar-row"><span class="mono">${esc(name)}</span><div class="bar"><span style="width:${count/maximum*100}%"></span></div><b>${fmt.format(count)}</b></div>`).join(""):'<p class="muted">无 QC flag。</p>';const missing=Math.max(0,CTX.total_record_count-CTX.mappable_record_count),confidence=CTX.confidence_report,manifest=CTX.source_manifest;$("coverageSummary").innerHTML=`<div class="mini-grid"><div class="mini"><b>${fmt.format(CTX.total_record_count)}</b><span>数据库记录</span></div><div class="mini"><b>${fmt.format(CTX.mappable_record_count)}</b><span>可上图记录</span></div><div class="mini"><b>${fmt.format(missing)}</b><span>坐标失败记录</span></div><div class="mini"><b>${fmt.format(manifest.source_count||new Set(samples.map(row=>row.source_id)).size)}</b><span>来源</span></div><div class="mini"><b>${((qc.standardization_rate||0)*100).toFixed(1)}%</b><span>标准化率</span></div><div class="mini"><b>${esc(confidence.confidence_version||"—")}</b><span>置信度版本</span></div></div><div class="callout"><strong>解释边界</strong><ul><li>空白区域表示未观测或未纳入，不表示元素不存在。</li><li>密度层只计数样点，不进行空间插值。</li><li>无坐标记录保留在数据库和 QC 报告中，不放到 (0,0)。</li><li>置信度不是概率；异常候选不是污染、矿化或成因结论。</li></ul></div>`}
renderSources();renderAnomalyTable();renderQuality();resize();
</script>
</body></html>'''


def build_map(
    database: Path,
    anomalies_path: Path,
    output_html: Path,
    output_geojson: Path,
    max_points: int = 50_000,
    qc_report_path: Path | None = None,
    confidence_report_path: Path | None = None,
    source_manifest_path: Path | None = None,
    anomaly_report_path: Path | None = None,
    basemap_path: Path = DEFAULT_BASEMAP,
) -> dict[str, Any]:
    if max_points < 1 or max_points > 200_000:
        raise MapBuildError("--max-points must be between 1 and 200000")
    records, total_records = load_records(database, max_points)
    anomalies = load_anomalies(anomalies_path)
    basemap = load_basemap(basemap_path)
    anomaly_ids = {
        str(feature.get("properties", {}).get("record_id"))
        for feature in anomalies["features"]
        if feature.get("properties", {}).get("record_id") is not None
    }
    geojson = samples_geojson(records, anomaly_ids)
    context = {
        "map_version": MAP_VERSION,
        "total_record_count": total_records,
        "mappable_record_count": len(records),
        "qc_report": load_json_object(qc_report_path, "QC report"),
        "confidence_report": load_json_object(confidence_report_path, "confidence report"),
        "source_manifest": load_json_object(source_manifest_path, "source manifest"),
        "anomaly_report": load_json_object(anomaly_report_path, "anomaly report"),
    }
    html = (
        HTML_TEMPLATE.replace("__SAMPLES_JSON__", safe_embedded_json(geojson))
        .replace("__ANOMALIES_JSON__", safe_embedded_json(anomalies))
        .replace("__BASEMAP_JSON__", safe_embedded_json(basemap))
        .replace("__CONTEXT_JSON__", safe_embedded_json(context))
    )
    geojson_text = json.dumps(geojson, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    html_bytes = len(html.encode("utf-8"))
    geojson_bytes = len(geojson_text.encode("utf-8"))
    if html_bytes > MAX_OUTPUT_BYTES or geojson_bytes > MAX_OUTPUT_BYTES:
        raise MapBuildError(
            "map output would exceed the 100 MB single-file limit; filter or split the input"
        )
    atomic_text(output_geojson, geojson_text)
    atomic_text(output_html, html)
    sample_keys = {
        (
            record.get("source_id"),
            record.get("sample_id") or record.get("record_id"),
            record.get("medium"),
            record.get("longitude"),
            record.get("latitude"),
        )
        for record in records
    }
    return {
        "map_version": MAP_VERSION,
        "mapped_record_count": len(records),
        "display_sample_count": len(sample_keys),
        "unmappable_record_count": total_records - len(records),
        "candidate_record_count": sum(
            str(record["record_id"]) in anomaly_ids for record in records
        ),
        "default_view": "all_data_sample_deduplicated",
        "external_assets": 0,
        "interpolation": False,
        "html_bytes": html_bytes,
        "samples_geojson_bytes": geojson_bytes,
        "basemap": {
            "asset_version": basemap["asset_version"],
            "title": basemap["title"],
            "scale": basemap["scale"],
            "license": basemap["license"],
            "archive_sha256": basemap["archive_sha256"],
            "embedded": True,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the self-contained D3 interactive atlas and samples GeoJSON."
    )
    parser.add_argument("--database", required=True, type=Path, help="D2 geochemistry.csv")
    parser.add_argument(
        "--anomalies", required=True, type=Path, help="D2 candidate anomalies GeoJSON"
    )
    parser.add_argument("--output-html", required=True, type=Path, help="Self-contained HTML path")
    parser.add_argument(
        "--output-geojson", required=True, type=Path, help="Map-ready samples GeoJSON path"
    )
    parser.add_argument("--qc-report", type=Path, help="Optional D2 qc_report.json")
    parser.add_argument(
        "--confidence-report", type=Path, help="Optional D2 confidence_report.json"
    )
    parser.add_argument("--source-manifest", type=Path, help="Optional D1 source_manifest.json")
    parser.add_argument("--anomaly-report", type=Path, help="Optional D2 anomaly_report.json")
    parser.add_argument(
        "--basemap", type=Path, default=DEFAULT_BASEMAP, help="Pinned offline basemap asset"
    )
    parser.add_argument(
        "--max-points", type=int, default=50_000, help="Fail if valid coordinate points exceed this"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = build_map(
            args.database,
            args.anomalies,
            args.output_html,
            args.output_geojson,
            args.max_points,
            args.qc_report,
            args.confidence_report,
            args.source_manifest,
            args.anomaly_report,
            args.basemap,
        )
    except (MapBuildError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
