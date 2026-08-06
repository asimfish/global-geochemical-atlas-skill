#!/usr/bin/env python3
"""Consume only the public D2 files and build a dependency-free interactive test atlas."""

from __future__ import annotations

import argparse
import csv
import html
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from lab_common import CheckBook, atomic_write_json, load_json, prepare_empty_output_dir, sha256_file
from showcase_builder import build_showcase

D3_VERSION = "d3-validation-consumer-v2"
REQUIRED_D2_FILES = {
    "geochemistry.csv",
    "samples.geojson",
    "anomalies.geojson",
    "qc_report.json",
    "confidence_report.json",
    "anomaly_report.json",
    "map_spec.json",
    "run_manifest.json",
}


def optional_float(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_database(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for field in (
            "normalized_value",
            "normalized_censoring_limit",
            "latitude",
            "longitude",
        ):
            row[field] = optional_float(row.get(field))
        row["censored"] = str(row.get("censored", "")).casefold() == "true"
        for field in ("qc_flags", "operational_confidence"):
            try:
                row[field] = json.loads(row.get(field, ""))
            except json.JSONDecodeError:
                row[field] = None
    return rows


def nested_value(value: dict[str, Any], dotted_path: str) -> tuple[bool, Any]:
    current: Any = value
    for component in dotted_path.split("."):
        if not isinstance(current, dict) or component not in current:
            return False, None
        current = current[component]
    return True, current


def javascript_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).replace("</", "<\\/")


def build_html(
    samples: dict[str, Any], anomalies: dict[str, Any], missing_coordinate_rows: list[dict[str, Any]], disclaimers: list[str]
) -> str:
    samples_json = javascript_json(samples.get("features", []))
    anomalies_json = javascript_json(anomalies.get("features", []))
    missing_json = javascript_json(
        [
            {
                "record_id": row.get("record_id"),
                "element": row.get("element_or_analyte"),
                "original_value": row.get("original_value_raw"),
                "unit": row.get("original_unit"),
                "qc_flags": row.get("qc_flags"),
                "source_locator": row.get("source_locator"),
            }
            for row in missing_coordinate_rows
        ]
    )
    disclaimer_html = "".join(f"<li>{html.escape(item)}</li>" for item in disclaimers)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>D2 全流程验证地图</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; }}
body {{ margin: 0; background: #f4f6f8; color: #18212b; }}
header, main {{ max-width: 1100px; margin: auto; padding: 16px; }}
.panel {{ background: white; border: 1px solid #d9e0e7; border-radius: 10px; padding: 14px; margin-bottom: 12px; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }}
label {{ display: grid; gap: 4px; font-size: 13px; }}
select, input {{ padding: 6px; }}
svg {{ width: 100%; height: auto; background: #eef5fa; border: 1px solid #b7c7d6; }}
.grid {{ stroke: #cad6df; stroke-width: .6; }}
.sample {{ fill: #2078b4; stroke: white; stroke-width: 1; opacity: .8; cursor: pointer; }}
.censored {{ fill: white; stroke: #7b4ab5; stroke-width: 2; }}
.anomaly {{ fill: #d73b32; stroke: #641611; stroke-width: 1.5; cursor: pointer; }}
pre {{ white-space: pre-wrap; overflow-wrap: anywhere; min-height: 5em; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #e5e9ed; padding: 6px; text-align: left; }}
.warning {{ color: #7a3900; }}
</style>
</head>
<body>
<header>
  <h1>D2 消费者验证地图</h1>
  <p>这是 D2 公共输出的离线 SVG 消费器；数据范围以运行清单为准，不构成因果或全球覆盖结论。</p>
</header>
<main>
  <section class="panel controls">
    <label>元素<select id="element"></select></label>
    <label>介质<select id="medium"></select></label>
    <label><span>显示删失值</span><input id="showCensored" type="checkbox" checked></label>
    <label><span>显示候选异常</span><input id="showAnomalies" type="checkbox" checked></label>
    <strong id="count"></strong>
  </section>
  <section class="panel">
    <svg id="map" viewBox="0 0 900 450" role="img" aria-label="等距圆柱投影测试点图"></svg>
  </section>
  <section class="panel"><h2>点击记录</h2><pre id="detail">点击地图点查看 D2 字段和来源。</pre></section>
  <section class="panel"><h2>无有效坐标记录</h2><table><thead><tr><th>ID</th><th>元素</th><th>原值</th><th>QC</th></tr></thead><tbody id="missing"></tbody></table></section>
  <section class="panel warning"><h2>必须展示的边界</h2><ul>{disclaimer_html}</ul></section>
</main>
<script>
"use strict";
const sampleFeatures={samples_json};
const anomalyFeatures={anomalies_json};
const missingRows={missing_json};
const svg=document.getElementById("map");
const elementSelect=document.getElementById("element");
const mediumSelect=document.getElementById("medium");
const detail=document.getElementById("detail");
function options(select, values) {{
  select.replaceChildren();
  for (const value of ["全部", ...values]) {{ const o=document.createElement("option"); o.value=value; o.textContent=value; select.append(o); }}
}}
options(elementSelect, [...new Set(sampleFeatures.map(f=>f.properties.element_or_analyte))].sort());
options(mediumSelect, [...new Set(sampleFeatures.map(f=>f.properties.medium))].sort());
for (let lon=-180; lon<=180; lon+=30) {{ const l=document.createElementNS("http://www.w3.org/2000/svg","line"); l.setAttribute("x1",(lon+180)*2.5); l.setAttribute("x2",(lon+180)*2.5); l.setAttribute("y1",0); l.setAttribute("y2",450); l.setAttribute("class","grid"); svg.append(l); }}
for (let lat=-90; lat<=90; lat+=30) {{ const l=document.createElementNS("http://www.w3.org/2000/svg","line"); l.setAttribute("x1",0); l.setAttribute("x2",900); l.setAttribute("y1",(90-lat)*2.5); l.setAttribute("y2",(90-lat)*2.5); l.setAttribute("class","grid"); svg.append(l); }}
function show(item) {{ detail.textContent=JSON.stringify(item,null,2); }}
function point(feature, css, radius) {{
  const [lon,lat]=feature.geometry.coordinates;
  const c=document.createElementNS("http://www.w3.org/2000/svg","circle");
  c.setAttribute("cx",(lon+180)*2.5); c.setAttribute("cy",(90-lat)*2.5); c.setAttribute("r",radius); c.setAttribute("class",css);
  c.addEventListener("click",()=>show(feature.properties)); svg.append(c);
}}
function render() {{
  svg.querySelectorAll("circle").forEach(node=>node.remove());
  const e=elementSelect.value, m=mediumSelect.value, showC=document.getElementById("showCensored").checked;
  const visible=sampleFeatures.filter(f=>(e==="全部"||f.properties.element_or_analyte===e)&&(m==="全部"||f.properties.medium===m)&&(!f.properties.censored||showC));
  for (const feature of visible) point(feature, feature.properties.censored?"censored":"sample", feature.properties.censored?5:4);
  if (document.getElementById("showAnomalies").checked) {{
    for (const feature of anomalyFeatures.filter(f=>f.geometry&&(e==="全部"||f.properties.element_or_analyte===e)&&(m==="全部"||f.properties.medium===m))) point(feature,"anomaly",7);
  }}
  document.getElementById("count").textContent=`可见样点 ${{visible.length}} / ${{sampleFeatures.length}}`;
}}
for (const id of ["element","medium","showCensored","showAnomalies"]) document.getElementById(id).addEventListener("change",render);
for (const row of missingRows) {{ const tr=document.createElement("tr"); for (const value of [row.record_id,row.element,`${{row.original_value??""}} ${{row.unit??""}}`,(row.qc_flags||[]).join(", ")]) {{ const td=document.createElement("td"); td.textContent=value; tr.append(td); }} tr.addEventListener("click",()=>show(row)); document.getElementById("missing").append(tr); }}
render();
</script>
</body>
</html>
"""


def build_d3_package(
    d2_output_dir: Path,
    output_dir: Path,
    coverage_context_path: Path | None = None,
) -> tuple[dict[str, Path], dict[str, Any]]:
    prepare_empty_output_dir(output_dir)
    checks = CheckBook()
    present_names = {path.name for path in d2_output_dir.iterdir()} if d2_output_dir.is_dir() else set()
    missing_files = sorted(REQUIRED_D2_FILES - present_names)
    checks.add(
        "all_eight_d2_files_exist",
        not missing_files,
        category="interface",
        expected=sorted(REQUIRED_D2_FILES),
        actual=sorted(present_names & REQUIRED_D2_FILES),
    )
    if missing_files:
        report = {
            "suite_version": D3_VERSION,
            "status": "fail",
            "missing_files": missing_files,
            **checks.summary(),
        }
        report_path = output_dir / "d3_consumer_report.json"
        atomic_write_json(report_path, report)
        return {"report": report_path}, report

    database = parse_database(d2_output_dir / "geochemistry.csv")
    samples = load_json(d2_output_dir / "samples.geojson")
    anomalies = load_json(d2_output_dir / "anomalies.geojson")
    qc_report = load_json(d2_output_dir / "qc_report.json")
    confidence_report = load_json(d2_output_dir / "confidence_report.json")
    anomaly_report = load_json(d2_output_dir / "anomaly_report.json")
    map_spec = load_json(d2_output_dir / "map_spec.json")
    manifest = load_json(d2_output_dir / "run_manifest.json")

    manifest_mismatches = []
    for entry in manifest.get("outputs", []):
        path = d2_output_dir / str(entry.get("path", ""))
        if not path.is_file() or sha256_file(path) != entry.get("sha256"):
            manifest_mismatches.append(str(entry.get("path")))
    checks.add(
        "manifest_hashes_match_consumed_files",
        not manifest_mismatches,
        category="evidence_chain",
        actual=manifest_mismatches,
    )

    data_references = map_spec.get("data", {})
    missing_references = sorted(
        str(name) for name in data_references.values() if not (d2_output_dir / str(name)).is_file()
    )
    checks.add(
        "map_spec_references_existing_files",
        not missing_references,
        category="interface",
        actual=missing_references,
    )

    sample_features = samples.get("features", [])
    anomaly_features = anomalies.get("features", [])
    valid_rows = [row for row in database if row["latitude"] is not None and row["longitude"] is not None]
    missing_coordinate_rows = [
        row for row in database if row["latitude"] is None or row["longitude"] is None
    ]
    checks.add(
        "sample_geojson_matches_valid_database_coordinates",
        len(sample_features) == len(valid_rows),
        category="map_semantics",
        expected=len(valid_rows),
        actual=len(sample_features),
    )
    checks.add(
        "missing_coordinates_remain_in_database",
        len(database) == int(qc_report.get("record_count", -1)) and bool(missing_coordinate_rows),
        category="map_semantics",
        expected=qc_report.get("record_count"),
        actual=len(database),
    )

    invalid_geometries = []
    for feature in sample_features:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates", [])
        if (
            geometry.get("type") != "Point"
            or len(coordinates) != 2
            or not -180 <= coordinates[0] <= 180
            or not -90 <= coordinates[1] <= 90
        ):
            invalid_geometries.append(feature.get("properties", {}).get("record_id"))
    checks.add(
        "all_rendered_geometries_are_valid_points",
        not invalid_geometries,
        category="map_semantics",
        actual=invalid_geometries,
    )

    color_values = [
        feature.get("properties", {}).get("normalized_value")
        for feature in sample_features
        if feature.get("properties", {}).get("normalized_value") is not None
        and not feature.get("properties", {}).get("censored", False)
    ]
    checks.add(
        "null_and_censored_values_excluded_from_color_domain",
        all(isinstance(value, (int, float)) for value in color_values),
        category="map_semantics",
        actual={"numeric_color_values": len(color_values)},
    )

    censored_point_count = sum(bool(feature.get("properties", {}).get("censored")) for feature in sample_features)
    checks.add(
        "censored_points_have_distinct_layer_contract",
        censored_point_count > 0 and "censored_observations" in {layer.get("id") for layer in map_spec.get("layers", [])},
        category="map_semantics",
        actual=censored_point_count,
    )

    checks.add(
        "anomaly_count_matches_report",
        len(anomaly_features) == int(anomaly_report.get("candidate_count", -1)),
        category="anomaly",
        expected=anomaly_report.get("candidate_count"),
        actual=len(anomaly_features),
    )
    database_ids = {row.get("record_id") for row in database}
    orphan_anomalies = [
        feature.get("properties", {}).get("record_id")
        for feature in anomaly_features
        if feature.get("properties", {}).get("record_id") not in database_ids
    ]
    checks.add(
        "anomalies_resolve_to_database_records",
        not orphan_anomalies,
        category="evidence_chain",
        actual=orphan_anomalies,
    )

    untraceable_points = [
        feature.get("properties", {}).get("record_id")
        for feature in sample_features
        if not feature.get("properties", {}).get("source_locator")
    ]
    checks.add(
        "rendered_points_have_source_locator",
        not untraceable_points,
        category="evidence_chain",
        actual=untraceable_points,
    )

    unsupported_filters = []
    for filter_name in map_spec.get("filters", []):
        if sample_features and not nested_value(sample_features[0].get("properties", {}), str(filter_name))[0]:
            unsupported_filters.append(filter_name)
    checks.add(
        "map_filters_exist_on_sample_properties",
        not unsupported_filters,
        category="interface",
        actual=unsupported_filters,
    )
    disclaimers = map_spec.get("required_disclaimers", [])
    checks.add(
        "scientific_disclaimers_are_available",
        len(disclaimers) >= 3,
        category="scientific_boundary",
        expected=">=3",
        actual=len(disclaimers),
    )
    checks.add(
        "confidence_is_labeled_not_probability",
        confidence_report.get("not_a_probability") is True,
        category="scientific_boundary",
        expected=True,
        actual=confidence_report.get("not_a_probability"),
    )

    coverage_context = load_json(coverage_context_path) if coverage_context_path is not None else None
    showcase_paths, showcase_metrics = build_showcase(
        database=database,
        samples=samples,
        anomalies=anomalies,
        qc_report=qc_report,
        confidence_report=confidence_report,
        anomaly_report=anomaly_report,
        disclaimers=list(map(str, disclaimers)),
        d2_output_dir=d2_output_dir,
        output_dir=output_dir,
        coverage_context=coverage_context,
    )
    html_path = showcase_paths["html"]
    html_document = html_path.read_text(encoding="utf-8")
    remote_asset_tags = "<script src=" in html_document.casefold() or "<link href=\"http" in html_document.casefold()
    checks.add(
        "html_has_no_remote_runtime_assets",
        not remote_asset_tags,
        category="offline_demo",
        expected=False,
        actual=remote_asset_tags,
    )
    source_confidence = load_json(showcase_paths["source_confidence"])
    anomaly_regions = load_json(showcase_paths["anomaly_regions"])
    anomaly_region_report = load_json(showcase_paths["anomaly_region_report"])
    showcase_manifest = load_json(showcase_paths["showcase_manifest"])
    checks.add(
        "showcase_emits_all_four_competition_deliverables",
        set(showcase_manifest.get("deliverables", {}))
        == {
            "interactive_element_map",
            "standardized_geochemical_database",
            "source_and_confidence_explanation",
            "anomaly_region_results",
        },
        category="product_deliverables",
        actual=sorted(showcase_manifest.get("deliverables", {})),
    )
    checks.add(
        "source_confidence_is_decomposed_and_not_probability",
        source_confidence.get("global_confidence", {}).get("not_a_probability") is True
        and source_confidence.get("source_count", 0) > 0
        and all(
            source.get("confidence", {}).get("component_means")
            for source in source_confidence.get("sources", [])
        ),
        category="product_deliverables",
        actual={
            "source_count": source_confidence.get("source_count"),
            "not_a_probability": source_confidence.get("global_confidence", {}).get(
                "not_a_probability"
            ),
        },
    )
    region_features = anomaly_regions.get("features", [])
    region_record_ids = {
        record_id
        for feature in region_features
        for record_id in feature.get("properties", {}).get("record_ids", [])
    }
    mappable_anomaly_record_ids = {
        feature.get("properties", {}).get("record_id")
        for feature in anomaly_features
        if feature.get("geometry") is not None
    }
    checks.add(
        "anomaly_regions_cover_all_mappable_candidates_and_report_unmappable_candidates",
        region_record_ids == mappable_anomaly_record_ids
        and (bool(region_features) or not mappable_anomaly_record_ids)
        and anomaly_region_report.get("unmappable_candidate_point_count")
        == len(anomaly_features) - len(mappable_anomaly_record_ids)
        and all(
            "not a geological boundary"
            in feature.get("properties", {}).get("interpretation_limit", "")
            for feature in region_features
        ),
        category="product_deliverables",
        expected=len(mappable_anomaly_record_ids),
        actual={
            "region_record_ids": len(region_record_ids),
            "regions": len(region_features),
            "unmappable_candidates": anomaly_region_report.get(
                "unmappable_candidate_point_count"
            ),
        },
    )

    summary = checks.summary()
    report = {
        "suite_version": D3_VERSION,
        "interface_version": map_spec.get("interface_version"),
        "consumer": "public D2 files only; no D2 Python imports",
        "status": summary["status"],
        "metrics": {
            "database_records": len(database),
            "rendered_sample_points": len(sample_features),
            "missing_coordinate_records": len(missing_coordinate_rows),
            "censored_sample_points": censored_point_count,
            "candidate_anomalies": len(anomaly_features),
            "color_domain_values": len(color_values),
        },
        "consumed_sha256": {
            name: sha256_file(d2_output_dir / name) for name in sorted(REQUIRED_D2_FILES)
        },
        "atlas": {"path": html_path.name, "sha256": sha256_file(html_path), "offline": True},
        "showcase": showcase_metrics,
        **summary,
    }
    report_path = output_dir / "d3_consumer_report.json"
    atomic_write_json(report_path, report)
    return {**showcase_paths, "report": report_path}, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build polished offline D3 evaluation deliverables from D2 public outputs."
    )
    parser.add_argument("--d2-output-dir", type=Path, required=True, help="Directory containing all eight D2 outputs")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty D3 output directory")
    parser.add_argument(
        "--coverage-context",
        type=Path,
        help="Optional D1 coverage manifest embedded in the source/confidence output and atlas",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        outputs, report = build_d3_package(
            args.d2_output_dir,
            args.output_dir,
            coverage_context_path=args.coverage_context,
        )
    except (OSError, ValueError, csv.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({key: str(path) for key, path in outputs.items()}, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
