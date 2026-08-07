#!/usr/bin/env python3
"""Materialize Q24 physical gold artifacts from its logical evidence.

Text and image artifacts are byte deterministic. SQLite records the writer
library version in its file header, so database reproducibility is additionally
bound by a canonical logical hash that is stable across SQLite versions.
"""

from __future__ import annotations

import argparse
import binascii
import csv
import hashlib
import json
import sqlite3
import struct
import zlib
from pathlib import Path
from typing import Any


ARTIFACT_IDS = {
    "observations.csv": "observations",
    "geochemical.sqlite": "database",
    "sources.jsonl": "sources",
    "qc_report.json": "qc",
    "anomaly_results.csv": "anomaly_table",
    "anomalies.geojson": "anomaly_geojson",
    "h3_cells.csv": "h3_cells",
    "map.png": "static_map",
    "map.html": "interactive_map",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def logical_sqlite_sha256(path: Path) -> str:
    """Hash schema and typed rows without SQLite's writer-version header."""

    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        schema = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_schema "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        tables: dict[str, Any] = {}
        for table_name, in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ):
            quoted = '"' + table_name.replace('"', '""') + '"'
            columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted})")]
            rows = connection.execute(f"SELECT * FROM {quoted}").fetchall()
            rows.sort(key=lambda row: json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            tables[table_name] = {"columns": columns, "rows": rows}
        payload = {"schema": schema, "tables": tables}
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    finally:
        connection.close()


def _logical(manifest: dict[str, Any], key: str) -> Any:
    entry = manifest["benchmark_evidence"][key]
    return entry.get("value") if entry["format"] == "json" else entry.get("rows")


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return value


def _write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows({column: _csv_value(row.get(column)) for column in columns} for row in rows)


def _write_sqlite(path: Path, observations: list[dict[str, Any]], sources: list[dict[str, Any]], confidence: dict[str, Any]) -> None:
    path.unlink(missing_ok=True)
    columns = list(observations[0])
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            "CREATE TABLE observations (" + ",".join(f'"{column}" TEXT' for column in columns) + ", PRIMARY KEY(record_id))"
        )
        placeholders = ",".join("?" for _ in columns)
        connection.executemany(
            f"INSERT INTO observations VALUES ({placeholders})",
            [[str(_csv_value(row.get(column))) for column in columns] for row in observations],
        )
        connection.execute(
            "CREATE TABLE sources (source_id TEXT PRIMARY KEY, evidence_json TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO sources VALUES (?, ?)",
            [(str(row["source_id"]), json.dumps(row, sort_keys=True, separators=(",", ":"))) for row in sources],
        )
        connection.execute(
            "CREATE TABLE workflow_confidence (schema_version TEXT, overall_score REAL, band TEXT, interpretation TEXT, evidence_json TEXT)"
        )
        connection.execute(
            "INSERT INTO workflow_confidence VALUES (?, ?, ?, ?, ?)",
            (
                confidence["schema_version"], confidence["overall_score"], confidence["band"],
                confidence["interpretation"], json.dumps(confidence, sort_keys=True, separators=(",", ":")),
            ),
        )
        connection.commit()
        connection.execute("VACUUM")
    finally:
        connection.close()


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def _write_png(path: Path, map_geojson: dict[str, Any], anomaly_geojson: dict[str, Any]) -> None:
    width, height = 900, 450
    pixels = bytearray([248, 250, 252] * width * height)

    def pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = bytes(color)

    def project(lon: float, lat: float) -> tuple[int, int]:
        return round((lon + 180) / 360 * (width - 1)), round((90 - lat) / 180 * (height - 1))

    for lon in range(-180, 181, 30):
        x, _ = project(lon, 0)
        for y in range(height):
            pixel(x, y, (203, 213, 225))
    for lat in range(-90, 91, 30):
        _, y = project(0, lat)
        for x in range(width):
            pixel(x, y, (203, 213, 225))
    for feature in map_geojson["features"]:
        x, y = project(*map(float, feature["geometry"]["coordinates"][:2]))
        for dx in range(-4, 5):
            for dy in range(-4, 5):
                if dx * dx + dy * dy <= 16:
                    pixel(x + dx, y + dy, (37, 99, 235))
    for feature in anomaly_geojson["features"]:
        x, y = project(*map(float, feature["geometry"]["coordinates"][:2]))
        for radius in (7, 8):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if radius * radius - radius <= dx * dx + dy * dy <= radius * radius + radius:
                        pixel(x + dx, y + dy, (220, 38, 38))
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3 : (y + 1) * width * 3]) for y in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(raw, 9))
    png += _chunk(b"IEND", b"")
    path.write_bytes(png)


def _map_html(map_geojson: dict[str, Any], anomaly_geojson: dict[str, Any]) -> str:
    points = json.dumps(map_geojson, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    anomalies = json.dumps(anomaly_geojson, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Q24 interactive geochemical map</title>
<style>body{{font:14px system-ui;margin:16px;color:#172033}}canvas{{border:1px solid #94a3b8;background:#f8fafc}}button,label{{margin:0 6px 8px 0}}pre{{max-width:900px;background:#f1f5f9;padding:8px;min-height:48px}}</style></head>
<body><h1>Q24 端到端小型地球化学图谱</h1>
<p>合成微型基准；统计异常仅为相对富集/亏损筛查，不建立成因。</p>
<div><button onclick="zoomBy(1.3)">放大 +</button><button onclick="zoomBy(0.77)">缩小 −</button>
<button onclick="pan(-20,0)">←</button><button onclick="pan(20,0)">→</button><button onclick="resetView()">重置</button>
<label><input id="showAnom" type="checkbox" checked onchange="draw()">候选异常</label></div>
<canvas id="stage" width="900" height="450" tabindex="0"></canvas><div id="status"></div><pre id="detail">点击样点查看 record_id 与 source_id</pre>
<script>var POINTS={points};var ANOMALIES={anomalies};var W=900,H=450,scale=1,cx=0,cy=0;
var canvas=document.getElementById('stage'),ctx=canvas.getContext('2d');
function proj(lon,lat){{return [W/2+(lon-cx)*W/360*scale,H/2-(lat-cy)*H/180*scale]}}
function draw(){{ctx.fillStyle='#f8fafc';ctx.fillRect(0,0,W,H);ctx.strokeStyle='#cbd5e1';ctx.lineWidth=1;
for(let lon=-180;lon<=180;lon+=30){{let a=proj(lon,-90),b=proj(lon,90);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}}
for(let lat=-90;lat<=90;lat+=30){{let a=proj(-180,lat),b=proj(180,lat);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.stroke()}}
ctx.fillStyle='#2563eb';for(const f of POINTS.features){{let p=proj(...f.geometry.coordinates);ctx.beginPath();ctx.arc(...p,4,0,Math.PI*2);ctx.fill()}}
if(document.getElementById('showAnom').checked){{ctx.strokeStyle='#dc2626';ctx.lineWidth=2;for(const f of ANOMALIES.features){{let p=proj(...f.geometry.coordinates);ctx.beginPath();ctx.arc(...p,9,0,Math.PI*2);ctx.stroke()}}}}
document.getElementById('status').textContent=`mapped_features=${{POINTS.features.length}} · anomalies=${{ANOMALIES.features.length}} · scale=${{scale.toFixed(2)}}`;}}
function zoomBy(v){{scale=Math.max(.5,Math.min(50,scale*v));draw()}}function pan(x,y){{cx+=x/scale;cy+=y/scale;draw()}}function resetView(){{scale=1;cx=0;cy=0;draw()}}
canvas.addEventListener('wheel',e=>{{e.preventDefault();zoomBy(e.deltaY<0?1.15:.87)}});
canvas.addEventListener('click',e=>{{let r=canvas.getBoundingClientRect(),best=null,dist=14;for(const f of POINTS.features){{let p=proj(...f.geometry.coordinates),d=Math.hypot(p[0]-(e.clientX-r.left),p[1]-(e.clientY-r.top));if(d<dist){{best=f;dist=d}}}}document.getElementById('detail').textContent=best?JSON.stringify(best.properties,null,2):'未命中样点';}});draw();</script></body></html>\n"""


def build(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    observations_entry = manifest["benchmark_evidence"]["observations.csv"]
    observations = observations_entry["rows"]
    sources = _logical(manifest, "sources.jsonl")
    qc = _logical(manifest, "qc_report.json")
    confidence = _logical(manifest, "confidence_report.json")
    map_geojson = _logical(manifest, "map.geojson")
    anomaly_geojson = _logical(manifest, "anomalies.geojson")
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "observations.csv", observations_entry["columns"], observations)
    _write_sqlite(output / "geochemical.sqlite", observations, sources, confidence)
    (output / "sources.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in sources),
        encoding="utf-8",
    )
    (output / "qc_report.json").write_text(json.dumps(qc, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "anomalies.geojson").write_text(json.dumps(anomaly_geojson, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    anomaly_rows = [
        {**feature.get("properties", {}), "record_id": feature.get("properties", {}).get("record_id") or feature.get("id")}
        for feature in anomaly_geojson["features"]
    ]
    anomaly_columns = ["record_id", "source_id", "group_id", "anomaly_type", "robust_z", "center_log10", "scale_log10", "n"]
    _write_csv(output / "anomaly_results.csv", anomaly_columns, anomaly_rows)
    _write_csv(output / "h3_cells.csv", ["h3_index", "resolution", "element", "medium", "measurement_count"], [])
    _write_png(output / "map.png", map_geojson, anomaly_geojson)
    (output / "map.html").write_text(_map_html(map_geojson, anomaly_geojson), encoding="utf-8")

    manifest["artifacts"] = []
    for name, artifact_id in ARTIFACT_IDS.items():
        artifact = {"artifact_id": artifact_id, "sha256": sha256_file(output / name)}
        if name == "geochemical.sqlite":
            artifact["logical_sha256"] = logical_sqlite_sha256(output / name)
        manifest["artifacts"].append(artifact)
    manifest["physical_artifact_profile"] = {
        "profile_version": "q24-physical-product-v1",
        "source": "benchmark_evidence",
        "interactive_map_requirements": ["zoom_or_pan", "anomaly_toggle", "record_source_drilldown"],
    }
    (output / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"status": "PASS", "artifacts": {name: sha256_file(output / name) for name in [*ARTIFACT_IDS, "run_manifest.json"]}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build(args.manifest, args.output)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
