#!/usr/bin/env python3
"""Externally audit the rendered atlas in a real Chromium browser.

This controller-side artifact is hash-bound to the submitted HTML.  Candidate
agents must not generate or edit it during formal evaluation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "geochemical-browser-audit-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def run_audit(html: Path, output: Path, screenshots: Path) -> dict[str, Any]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.support.ui import WebDriverWait
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "browser audit requires selenium==4.46.0 and a compatible Chromium/driver"
        ) from exc

    if not html.is_file():
        raise RuntimeError(f"interactive HTML does not exist: {html}")
    output_parent = output.resolve().parent
    screenshot_root = screenshots.resolve()
    if screenshot_root.parent != output_parent:
        raise RuntimeError(
            "screenshots must be one direct child directory beside browser_audit.json"
        )
    screenshots = screenshot_root
    screenshots.mkdir(parents=True, exist_ok=True)
    options = Options()
    for argument in (
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--allow-file-access-from-files", "--window-size=1440,1100",
    ):
        options.add_argument(argument)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    driver = webdriver.Chrome(options=options)
    interactions: dict[str, dict[str, Any]] = {}
    shot_records: list[dict[str, Any]] = []

    def screenshot(name: str) -> None:
        path = screenshots / f"{name}.png"
        driver.save_screenshot(str(path))
        shot_records.append(
            {"name": name, "file": path.name, "bytes": path.stat().st_size,
             "sha256": sha256_file(path)}
        )

    def state() -> dict[str, Any]:
        return driver.execute_script(
            """
            const canvas=document.getElementById('map');
            const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
            const colors=new Set(); let opaque=0;
            const stride=Math.max(4,Math.floor(data.length/80000/4)*4);
            for(let i=0;i<data.length;i+=stride){
              if(data[i+3]) opaque++;
              colors.add(`${data[i]},${data[i+1]},${data[i+2]},${data[i+3]}`);
              if(colors.size>500) break;
            }
            return {
              title:document.title,
              canvas_width:canvas.width, canvas_height:canvas.height,
              sampled_opaque_pixels:opaque, sampled_unique_colors:colors.size,
              embedded_measurements:(typeof samples==='undefined'?null:samples.length),
              current_measurements:(typeof currentRows==='undefined'?null:currentRows.length),
              physical_sites:(typeof physicalRows==='undefined'?null:physicalRows.length),
              visible_symbols:(typeof displayRows==='undefined'?null:displayRows.length),
              candidate_measurements:(typeof currentCandidates==='undefined'?null:currentCandidates.length),
              basemap_shapes:(typeof BASE==='undefined'?null:(BASE.rings||[]).length),
              country_boundaries:(typeof BOUNDARIES==='undefined'?null:(BOUNDARIES.countries||[]).length),
              map_empty:document.getElementById('mapEmpty')
                ? getComputedStyle(document.getElementById('mapEmpty')).display!=='none' : null
            };
            """
        )

    def activate(view: str) -> bool:
        activated = driver.execute_script(
            "const n=document.querySelector('.tab[data-view=\"'+arguments[0]+'\"]');"
            "if(n)n.click();return Boolean(n)", view
        )
        time.sleep(0.2)
        return bool(activated)

    try:
        driver.get(html.resolve().as_uri())
        WebDriverWait(driver, 20).until(
            lambda current: current.execute_script(
                "return document.readyState==='complete' && "
                "document.getElementById('map').width>200"
            )
        )
        time.sleep(0.5)
        initial = state()
        screenshot("overview")

        filter_result = driver.execute_script(
            """
            if(typeof currentRows==='undefined')return {tested:false,reason:'no_currentRows'};
            const before=currentRows.length;
            for(const id of ['element','medium','sampleType','geology']){
              const node=document.getElementById(id);
              if(!node)continue;
              for(const option of [...node.options]){
                if(option.value){
                  node.value=option.value;
                  node.dispatchEvent(new Event('change',{bubbles:true}));
                  if(currentRows.length!==before)
                    return {tested:true,id,value:option.value,before,after:currentRows.length};
                }
              }
              node.value=''; node.dispatchEvent(new Event('change',{bubbles:true}));
            }
            return {tested:false,before,after:currentRows.length};
            """
        )
        interactions["filter_changes_result"] = {
            "passed": bool(filter_result.get("tested")), "evidence": filter_result
        }
        screenshot("filtered")
        heat_control = driver.execute_script(
            "const n=document.getElementById('mapMode');if(!n)return false;n.value='heat';"
            "n.dispatchEvent(new Event('change',{bubbles:true}));return true;"
        )
        time.sleep(0.2)
        heat_text = driver.execute_script(
            "return document.getElementById('legendTitle')?.innerText||''"
        )
        interactions["heatmap"] = {
            "passed": bool(heat_control and "密度" in heat_text),
            "evidence": {"legend": heat_text, **state()},
        }
        screenshot("heatmap")

        combination_tab = activate("combinationView")
        combination = driver.execute_script(
            """
            return {x:document.getElementById('comboX')?.value||'',
                    y:document.getElementById('comboY')?.value||'',
                    summary:document.getElementById('comboSummary')?.innerText||'',
                    matrix_rows:document.querySelectorAll('#comboMatrix tbody tr').length,
                    canvas_width:document.getElementById('comboCanvas')?.width||0};
            """
        )
        interactions["element_combination"] = {
            "passed": bool(combination_tab and combination["x"] and combination["y"]
                           and combination["x"] != combination["y"]
                           and combination["matrix_rows"] > 0
                           and combination["canvas_width"] > 100),
            "evidence": combination,
        }
        screenshot("combination")

        source_tab = activate("sourceView")
        source_rows = len(driver.find_elements("css selector", "#sourceTableBody tr"))
        source_detail = driver.execute_script(
            "return document.getElementById('sourceDetail')?.innerText||''"
        )
        interactions["source_drilldown"] = {
            "passed": source_tab and source_rows > 0 and bool(source_detail.strip()),
            "evidence": {"source_rows": source_rows, "detail_chars": len(source_detail)},
        }
        screenshot("sources")

        anomaly_tab = activate("anomalyView")
        anomaly_rows = len(driver.find_elements("css selector", "#anomalyTable tr"))
        anomaly_summary = driver.execute_script(
            "return document.getElementById('anomalySummary')?.innerText||''"
        )
        candidate_count = initial.get("candidate_measurements") or 0
        interactions["anomaly_view"] = {
            "passed": anomaly_tab and bool(anomaly_summary.strip()) and anomaly_rows > 0,
            "applicable_candidate_count": candidate_count,
            "evidence": {"table_rows": anomaly_rows, "summary_chars": len(anomaly_summary)},
        }
        screenshot("anomalies")

        logs = driver.get_log("browser")
        severe = [
            {"level": item.get("level"), "message": item.get("message")}
            for item in logs if item.get("level") == "SEVERE"
        ]
        required_interactions = (
            "filter_changes_result", "heatmap", "element_combination",
            "source_drilldown", "anomaly_view",
        )
        loaded = initial["canvas_width"] > 200 and initial["canvas_height"] > 150
        rendered = (
            initial["sampled_opaque_pixels"] > 100
            and initial["sampled_unique_colors"] > 20
            and (initial["embedded_measurements"] or 0) > 0
            and (initial["visible_symbols"] or 0) > 0
            and (initial["country_boundaries"] or 0) > 0
        )
        passed = loaded and rendered and not severe and all(
            interactions[name]["passed"] for name in required_interactions
        )
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "pass" if passed else "fail",
            "generated_by": "external_evaluation_controller",
            "html": {
                "filename": html.name,
                "bytes": html.stat().st_size,
                "sha256": sha256_file(html),
            },
            "browser": {
                "name": "chromium",
                "version": driver.capabilities.get("browserVersion"),
                "driver_version": driver.capabilities.get("chrome", {}).get("chromedriverVersion"),
                "headless": True,
                "network": "offline_file",
            },
            "loaded": loaded,
            "rendered_product": rendered,
            "javascript_errors": severe,
            "metrics": initial,
            "interactions": interactions,
            "screenshot_directory": screenshots.name,
            "screenshots": shot_records,
            "claim_boundary": (
                "This verifies browser rendering and interactions for the submitted bytes; "
                "it does not verify scientific correctness or geographic representativeness."
            ),
        }
        atomic_json(output, report)
        return report
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit an interactive atlas in Chromium.")
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_audit(args.html, args.output, args.screenshots)
    except Exception as exc:  # controller must emit a machine-readable failure
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "error",
            "generated_by": "external_evaluation_controller",
            "html": {
                "filename": args.html.name,
                "bytes": args.html.stat().st_size if args.html.is_file() else 0,
                "sha256": sha256_file(args.html) if args.html.is_file() else None,
            },
            "error": str(exc),
            "loaded": False,
            "rendered_product": False,
            "javascript_errors": [],
            "metrics": {},
            "interactions": {},
            "screenshots": [],
        }
        atomic_json(args.output, report)
    print(json.dumps({"status": report["status"]}, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
