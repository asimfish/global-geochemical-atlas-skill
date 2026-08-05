#!/usr/bin/env python3
"""Build a self-contained, data-driven SVG map and samples GeoJSON."""

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


class MapBuildError(ValueError):
    """Raised when map inputs are invalid."""


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


def load_records(path: Path, max_points: int) -> list[dict[str, Any]]:
    if not path.is_file():
        raise MapBuildError(f"database does not exist: {path}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {
            "record_id", "element_or_analyte", "medium", "normalized_value", "normalized_unit",
            "latitude", "longitude", "qc_flags", "operational_confidence", "source_id", "source_locator",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise MapBuildError(f"database missing map columns: {', '.join(missing)}")
        for row in reader:
            latitude = optional_float(row.get("latitude"))
            longitude = optional_float(row.get("longitude"))
            if latitude is None or longitude is None:
                continue
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                continue
            confidence = parse_json_cell(row.get("operational_confidence"), {})
            qc_flags = parse_json_cell(row.get("qc_flags"), [])
            records.append(
                {
                    "record_id": row.get("record_id"),
                    "sample_id": row.get("sample_id") or None,
                    "element": row.get("element_or_analyte"),
                    "medium": row.get("medium"),
                    "measurement_basis": row.get("measurement_basis") or None,
                    "value": optional_float(row.get("normalized_value")),
                    "unit": row.get("normalized_unit") or None,
                    "qualifier": row.get("value_qualifier") or None,
                    "censoring_limit": optional_float(row.get("normalized_censoring_limit")),
                    "latitude": latitude,
                    "longitude": longitude,
                    "geologic_unit": row.get("geologic_unit") or None,
                    "analytical_method": row.get("analytical_method") or None,
                    "source_id": row.get("source_id") or None,
                    "source_locator": row.get("source_locator") or None,
                    "license": row.get("license") or None,
                    "confidence_band": confidence.get("band", "unknown") if isinstance(confidence, dict) else "unknown",
                    "confidence_overall": (
                        confidence.get("overall") if isinstance(confidence, dict) else None
                    ),
                    "qc_flags": qc_flags if isinstance(qc_flags, list) else [],
                }
            )
            if len(records) > max_points:
                raise MapBuildError(f"valid map points exceed --max-points ({max_points}); filter the input first")
    return records


def load_anomalies(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MapBuildError(f"anomalies GeoJSON does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MapBuildError("anomalies GeoJSON is invalid JSON") from exc
    if value.get("type") != "FeatureCollection" or not isinstance(value.get("features"), list):
        raise MapBuildError("anomalies input must be a GeoJSON FeatureCollection")
    return value


def samples_geojson(records: Sequence[Mapping[str, Any]], anomaly_ids: set[str]) -> dict[str, Any]:
    features = []
    for record in records:
        properties = {key: value for key, value in record.items() if key not in {"latitude", "longitude"}}
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
        "features": features,
    }


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
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
<title>全球地球化学元素分布图谱</title>
<style>
:root{color-scheme:dark;--bg:#07111f;--panel:#0e1c2d;--line:#28445e;--text:#e8f2f8;--muted:#9ab0c1;--accent:#4fd1c5;--warn:#ffbd59}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 15% 0,#173451 0,#07111f 42%);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--text)}
header{padding:20px 24px 12px}h1{font-size:24px;margin:0 0 4px}header p{color:var(--muted);margin:0;max-width:1000px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:14px;padding:12px 18px 24px}.card{background:rgba(14,28,45,.94);border:1px solid var(--line);border-radius:12px;box-shadow:0 10px 32px #0005}
.controls{display:flex;flex-wrap:wrap;gap:9px;padding:12px;border-bottom:1px solid var(--line);align-items:end}.control{display:grid;gap:4px}.control label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}
select,button{background:#11283d;border:1px solid #35536c;border-radius:7px;color:var(--text);padding:7px 9px}button{cursor:pointer}button:hover{border-color:var(--accent)}
.check{display:flex;gap:6px;align-items:center;padding:7px 4px}.map-wrap{position:relative;min-height:560px;overflow:hidden}svg{display:block;width:100%;height:560px;touch-action:none;background:linear-gradient(#09203a,#0a1726)}
.ocean{fill:#0b2135}.grid{stroke:#36536a;stroke-width:.45;opacity:.55}.equator{stroke:#5c7f95;stroke-width:.75}.point{cursor:pointer;stroke:#06111d;stroke-width:.7;vector-effect:non-scaling-stroke}.candidate{stroke:var(--warn);stroke-width:2.4;vector-effect:non-scaling-stroke}
.tooltip{position:absolute;display:none;pointer-events:none;max-width:330px;background:#06101ddd;border:1px solid #53738b;border-radius:8px;padding:9px 11px;box-shadow:0 8px 24px #0008;font-size:12px}.tooltip strong{color:#fff}.tooltip .muted{color:var(--muted);word-break:break-all}
.map-note{position:absolute;left:10px;bottom:9px;background:#07111fcc;padding:5px 8px;border-radius:6px;color:var(--muted);font-size:11px}.side{display:grid;gap:14px;align-content:start}.section{padding:13px}.section h2{font-size:14px;margin:0 0 9px}.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.metric{padding:9px;background:#0a1726;border-radius:8px}.metric b{display:block;font-size:20px;color:var(--accent)}.metric span{font-size:11px;color:var(--muted)}
.legend{font-size:12px;color:var(--muted);margin-top:9px}.gradient{height:9px;border-radius:5px;background:linear-gradient(90deg,hsl(210 75% 54%),hsl(46 90% 58%),hsl(4 82% 58%));margin:5px 0}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{text-align:left;padding:6px 4px;border-bottom:1px solid #22384c}th{color:var(--muted);font-weight:600}.scroll{max-height:230px;overflow:auto}
.badge{display:inline-block;padding:2px 6px;border-radius:99px;background:#18344a;color:#bcd0dd;font-size:10px}.badge.anom{background:#5b3c12;color:#ffd994}.empty{color:var(--muted);padding:18px;text-align:center}
@media(max-width:900px){.layout{grid-template-columns:1fr}.map-wrap,svg{min-height:460px;height:460px}}
</style>
</head>
<body>
<header><h1>全球地球化学元素分布图谱</h1><p>证据优先的样点视图。颜色仅在相同标准单位组内按 log10 浓度缩放；密度格网不做空间插值。候选异常不代表污染、矿化或成因。</p></header>
<main class="layout">
  <section class="card">
    <div class="controls">
      <div class="control"><label for="element">元素</label><select id="element"></select></div>
      <div class="control"><label for="medium">介质</label><select id="medium"></select></div>
      <div class="control"><label for="confidence">运行级置信度</label><select id="confidence"></select></div>
      <div class="control"><label for="mode">图层</label><select id="mode"><option value="points">浓度样点</option><option value="density">格网样点密度</option></select></div>
      <label class="check"><input id="anomalyOnly" type="checkbox">仅候选异常</label>
      <button id="fitView" type="button">定位数据</button><button id="resetView" type="button">全球视图</button>
    </div>
    <div class="map-wrap" id="mapWrap">
      <svg id="map" viewBox="0 0 1000 500" role="img" aria-label="等距圆柱投影地球化学样点地图">
        <rect class="ocean" x="0" y="0" width="1000" height="500"></rect>
        <g id="graticule"></g><g id="dataLayer"></g>
      </svg>
      <div class="tooltip" id="tooltip"></div>
      <div class="map-note">WGS84 等距圆柱投影 · 示意底图 · 滚轮缩放 / 拖动平移</div>
    </div>
  </section>
  <aside class="side">
    <section class="card section"><h2>当前视图</h2><div class="metric-grid"><div class="metric"><b id="visibleCount">0</b><span>有效坐标样点</span></div><div class="metric"><b id="candidateCount">0</b><span>候选异常</span></div><div class="metric"><b id="sourceCount">0</b><span>来源 ID</span></div><div class="metric"><b id="unitCount">0</b><span>标准单位组</span></div></div><div class="legend"><div class="gradient"></div><span>同单位组：低 → 高（log10）；黄色描边 = 候选异常</span></div></section>
    <section class="card section"><h2>元素组合概览</h2><div class="scroll"><table><thead><tr><th>元素</th><th>单位</th><th>n</th><th>中位数</th></tr></thead><tbody id="comparison"></tbody></table></div></section>
    <section class="card section"><h2>可复查记录</h2><div class="scroll"><table><thead><tr><th>记录</th><th>元素</th><th>值</th></tr></thead><tbody id="records"></tbody></table></div></section>
    <section class="card section"><h2>解释边界</h2><div class="legend">无坐标记录仍保留在数据库/QC 报告中。本图不把它们放到零岛；不对空白区域做插值。点击样点查看 source ID、定位、分析方法和 QC。</div></section>
  </aside>
</main>
<script id="samples-data" type="application/json">__SAMPLES_JSON__</script>
<script>
"use strict";
const fc=JSON.parse(document.getElementById("samples-data").textContent);
const samples=fc.features.map(f=>({...f.properties,longitude:f.geometry.coordinates[0],latitude:f.geometry.coordinates[1]}));
const $=id=>document.getElementById(id), NS="http://www.w3.org/2000/svg", map=$("map"), layer=$("dataLayer"), tip=$("tooltip"), wrap=$("mapWrap");
function unique(key){return [...new Set(samples.map(x=>x[key]).filter(x=>x!==null&&x!==undefined&&x!==""))].sort()}
function fillSelect(id,values,label){const node=$(id);node.replaceChildren();const all=document.createElement("option");all.value="";all.textContent=label;node.append(all);for(const v of values){const o=document.createElement("option");o.value=v;o.textContent=v;node.append(o)}}
fillSelect("element",unique("element"),"全部元素");fillSelect("medium",unique("medium"),"全部介质");fillSelect("confidence",unique("confidence_band"),"全部置信度");
function svgEl(name,attrs={}){const e=document.createElementNS(NS,name);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,String(v));return e}
const grid=$("graticule");for(let lon=-150;lon<=150;lon+=30){grid.append(svgEl("line",{x1:(lon+180)/360*1000,y1:0,x2:(lon+180)/360*1000,y2:500,class:"grid"}))}for(let lat=-60;lat<=60;lat+=30){grid.append(svgEl("line",{x1:0,y1:(90-lat)/180*500,x2:1000,y2:(90-lat)/180*500,class:lat===0?"equator":"grid"}))}
function project(lon,lat){return[(lon+180)/360*1000,(90-lat)/180*500]}
function median(a){if(!a.length)return null;const b=[...a].sort((x,y)=>x-y),m=Math.floor(b.length/2);return b.length%2?b[m]:(b[m-1]+b[m])/2}
function filtered(){return samples.filter(s=>(!$("element").value||s.element===$("element").value)&&(!$("medium").value||s.medium===$("medium").value)&&(!$("confidence").value||s.confidence_band===$("confidence").value)&&(!$("anomalyOnly").checked||s.candidate_anomaly))}
function unitScales(rows){const groups={};for(const r of rows){if(r.value>0&&r.unit){(groups[r.unit]??=[]).push(Math.log10(r.value))}}const out={};for(const[u,a]of Object.entries(groups)){out[u]=[Math.min(...a),Math.max(...a)]}return out}
function color(r,scales){if(!(r.value>0)||!r.unit||!scales[r.unit])return"#7890a2";const[min,max]=scales[r.unit],t=max===min?.55:(Math.log10(r.value)-min)/(max-min);const hue=210-206*Math.max(0,Math.min(1,t));return`hsl(${hue} 82% 58%)`}
function showTip(event,r){tip.replaceChildren();const lines=[`${r.element} · ${r.value??"删失/缺失"} ${r.unit??""}`,`记录: ${r.record_id}`,`样品: ${r.sample_id??"未提供"}`,`介质/basis: ${r.medium} / ${r.measurement_basis??"未提供"}`,`地质单元: ${r.geologic_unit??"未提供"}`,`方法: ${r.analytical_method??"未提供"}`,`置信度: ${r.confidence_band} (${r.confidence_overall??"-"})`,`QC: ${(r.qc_flags||[]).join(", ")||"无 flag"}`,`来源: ${r.source_id??"未提供"}`,`定位: ${r.source_locator??"未提供"}`];lines.forEach((line,i)=>{const d=document.createElement("div");d.textContent=line;if(i===0){const b=document.createElement("strong");b.textContent=line;d.replaceChildren(b)}if(i>=8)d.className="muted";tip.append(d)});tip.style.display="block";const box=wrap.getBoundingClientRect();tip.style.left=Math.min(event.clientX-box.left+12,box.width-340)+"px";tip.style.top=Math.max(8,event.clientY-box.top-20)+"px"}
function hideTip(){tip.style.display="none"}
function renderPoints(rows){const scales=unitScales(rows);for(const r of rows){const[x,y]=project(r.longitude,r.latitude),c=svgEl("circle",{cx:x,cy:y,r:r.candidate_anomaly?5.2:3.4,fill:color(r,scales),class:r.candidate_anomaly?"point candidate":"point",tabindex:0});c.addEventListener("pointerenter",e=>showTip(e,r));c.addEventListener("pointermove",e=>showTip(e,r));c.addEventListener("pointerleave",hideTip);layer.append(c)}}
function renderDensity(rows){const nx=36,ny=18,bins=new Map();for(const r of rows){const[x,y]=project(r.longitude,r.latitude),ix=Math.min(nx-1,Math.floor(x/1000*nx)),iy=Math.min(ny-1,Math.floor(y/500*ny)),k=`${ix},${iy}`;bins.set(k,(bins.get(k)||0)+1)}const max=Math.max(1,...bins.values());for(const[k,count]of bins){const[ix,iy]=k.split(",").map(Number),rect=svgEl("rect",{x:ix*1000/nx,y:iy*500/ny,width:1000/nx,height:500/ny,fill:"#ff7b54",opacity:.15+.8*Math.sqrt(count/max),stroke:"#ffc077",'stroke-width':.35});rect.addEventListener("pointerenter",e=>showTip(e,{element:"格网样点密度",value:count,unit:"records/cell",record_id:k,sample_id:null,medium:"mixed",measurement_basis:null,geologic_unit:null,analytical_method:null,confidence_band:"not_applicable",confidence_overall:null,qc_flags:[],source_id:`${new Set(rows.map(x=>x.source_id).filter(Boolean)).size} source(s)`,source_locator:"不插值，仅计数",candidate_anomaly:false}));rect.addEventListener("pointerleave",hideTip);layer.append(rect)}}
function textCell(value){const td=document.createElement("td");td.textContent=value??"-";return td}
function updateTables(rows){const comp=$("comparison");comp.replaceChildren();const grouped=new Map();for(const r of rows){if(r.value===null||!r.unit)continue;const k=`${r.element}\u0000${r.unit}`;(grouped.get(k)||grouped.set(k,[]).get(k)).push(r.value)}for(const[k,vals]of [...grouped.entries()].sort()){const[element,unit]=k.split("\u0000"),tr=document.createElement("tr");tr.append(textCell(element),textCell(unit),textCell(vals.length),textCell(Number(median(vals).toPrecision(5))));comp.append(tr)}if(!grouped.size){const tr=document.createElement("tr"),td=textCell("当前筛选无可比较数值");td.colSpan=4;tr.append(td);comp.append(tr)}const tbody=$("records");tbody.replaceChildren();for(const r of rows.slice(0,40)){const tr=document.createElement("tr"),id=document.createElement("td"),badge=document.createElement("span");badge.className=r.candidate_anomaly?"badge anom":"badge";badge.textContent=r.record_id;id.append(badge);tr.append(id,textCell(r.element),textCell(r.value===null?`≤${r.censoring_limit??"?"}`:`${r.value} ${r.unit??""}`));tbody.append(tr)}}
function render(){const rows=filtered();layer.replaceChildren();if($("mode").value==="density")renderDensity(rows);else renderPoints(rows);resizePoints();$("visibleCount").textContent=rows.length;$("candidateCount").textContent=rows.filter(x=>x.candidate_anomaly).length;$("sourceCount").textContent=new Set(rows.map(x=>x.source_id).filter(Boolean)).size;$("unitCount").textContent=new Set(rows.map(x=>x.unit).filter(Boolean)).size;updateTables(rows)}
for(const id of["element","medium","confidence","mode","anomalyOnly"])$(id).addEventListener("change",render);
let view=[0,0,1000,500],drag=null;function resizePoints(){for(const c of layer.querySelectorAll("circle.point")){c.setAttribute("r",(c.classList.contains("candidate")?5.2:3.4)*view[2]/1000)}}function setView(){map.setAttribute("viewBox",view.join(" "));resizePoints()}function fitToRows(rows){if(!rows.length){view=[0,0,1000,500];setView();return}const points=rows.map(r=>project(r.longitude,r.latitude)),xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys),width=Math.max(1,(maxX-minX)*1.45,(maxY-minY)*2.9),height=width/2,cx=(minX+maxX)/2,cy=(minY+maxY)/2;view=[Math.max(0,Math.min(1000-width,cx-width/2)),Math.max(0,Math.min(500-height,cy-height/2)),width,height];setView()}$("fitView").addEventListener("click",()=>fitToRows(filtered()));$("resetView").addEventListener("click",()=>{view=[0,0,1000,500];setView()});map.addEventListener("wheel",e=>{e.preventDefault();const rect=map.getBoundingClientRect(),px=view[0]+(e.clientX-rect.left)/rect.width*view[2],py=view[1]+(e.clientY-rect.top)/rect.height*view[3],factor=e.deltaY>0?1.2:.83,nw=Math.max(1,Math.min(1000,view[2]*factor)),nh=nw/2;view=[Math.max(0,Math.min(1000-nw,px-(px-view[0])*nw/view[2])),Math.max(0,Math.min(500-nh,py-(py-view[1])*nh/view[3])),nw,nh];setView()},{passive:false});map.addEventListener("pointerdown",e=>{drag=[e.clientX,e.clientY,...view];map.setPointerCapture(e.pointerId)});map.addEventListener("pointermove",e=>{if(!drag)return;const rect=map.getBoundingClientRect(),dx=(e.clientX-drag[0])/rect.width*drag[4],dy=(e.clientY-drag[1])/rect.height*drag[5];view=[Math.max(0,Math.min(1000-drag[4],drag[2]-dx)),Math.max(0,Math.min(500-drag[5],drag[3]-dy)),drag[4],drag[5]];setView()});map.addEventListener("pointerup",()=>{drag=null});map.addEventListener("pointercancel",()=>{drag=null});
render();fitToRows(samples);
</script>
</body></html>
'''


def build_map(
    database: Path,
    anomalies_path: Path,
    output_html: Path,
    output_geojson: Path,
    max_points: int = 50_000,
) -> dict[str, Any]:
    if max_points < 1 or max_points > 200_000:
        raise MapBuildError("--max-points must be between 1 and 200000")
    records = load_records(database, max_points)
    anomalies = load_anomalies(anomalies_path)
    anomaly_ids = {
        str(feature.get("properties", {}).get("record_id"))
        for feature in anomalies["features"]
        if feature.get("properties", {}).get("record_id") is not None
    }
    geojson = samples_geojson(records, anomaly_ids)
    html = HTML_TEMPLATE.replace("__SAMPLES_JSON__", safe_embedded_json(geojson))
    atomic_text(output_geojson, json.dumps(geojson, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    atomic_text(output_html, html)
    return {
        "map_version": "self-contained-svg-v1",
        "mapped_record_count": len(records),
        "candidate_record_count": sum(str(record["record_id"]) in anomaly_ids for record in records),
        "external_assets": 0,
        "interpolation": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build self-contained interactive HTML and samples GeoJSON.")
    parser.add_argument("--database", required=True, type=Path, help="Standardized geochemistry.csv")
    parser.add_argument("--anomalies", required=True, type=Path, help="Candidate anomalies GeoJSON")
    parser.add_argument("--output-html", required=True, type=Path, help="Self-contained HTML path")
    parser.add_argument("--output-geojson", required=True, type=Path, help="Map-ready samples GeoJSON path")
    parser.add_argument("--max-points", type=int, default=50_000, help="Fail if valid coordinate points exceed this")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = build_map(args.database, args.anomalies, args.output_html, args.output_geojson, args.max_points)
    except (MapBuildError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
