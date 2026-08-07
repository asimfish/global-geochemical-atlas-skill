#!/usr/bin/env python3
"""Controller-side Chromium audit for the Q24 interactive map artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "geochemical-q24-browser-audit-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def run_audit(html: Path, output: Path, screenshots: Path) -> dict[str, Any]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.support.ui import WebDriverWait
    except ModuleNotFoundError as exc:
        raise RuntimeError("Q24 browser audit requires Selenium and Chromium/ChromeDriver") from exc
    if not html.is_file():
        raise RuntimeError(f"Q24 map HTML does not exist: {html}")
    if screenshots.resolve().parent != output.resolve().parent:
        raise RuntimeError("screenshots must be a direct sibling directory of the audit JSON")
    screenshots.mkdir(parents=True, exist_ok=True)

    options = Options()
    for argument in (
        "--headless=new", "--no-sandbox", "--disable-dev-shm-usage",
        "--allow-file-access-from-files", "--window-size=1280,900",
    ):
        options.add_argument(argument)
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    driver_path = shutil.which("chromedriver")
    if not driver_path:
        raise RuntimeError("Q24 browser audit requires chromedriver on PATH")
    driver = webdriver.Chrome(service=Service(executable_path=driver_path), options=options)
    shots: list[dict[str, Any]] = []

    def screenshot(name: str) -> None:
        path = screenshots / f"{name}.png"
        driver.save_screenshot(str(path))
        shots.append({"name": name, "file": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})

    def state() -> dict[str, Any]:
        return driver.execute_script(
            """
            function canvasState(canvas){
              const ctx=canvas.getContext && canvas.getContext('2d');
              if(!ctx)return {colors:0,opaque:0,signature:'no-2d'};
              const data=ctx.getImageData(0,0,canvas.width,canvas.height).data;
              const colors=new Set();let opaque=0,hash=2166136261;
              const stride=Math.max(4,Math.floor(data.length/50000/4)*4);
              for(let i=0;i<data.length;i+=stride){
                if(data[i+3])opaque++;
                colors.add(`${data[i]},${data[i+1]},${data[i+2]},${data[i+3]}`);
                hash^=data[i];hash=Math.imul(hash,16777619);hash^=data[i+1];hash=Math.imul(hash,16777619);
              }
              return {colors:colors.size,opaque,signature:String(hash>>>0)};
            }
            const canvas=document.querySelector('canvas');
            const svg=document.querySelector('svg');
            const leaflet=document.querySelector('.leaflet-container');
            const surface=canvas||svg||leaflet;
            const rect=surface?surface.getBoundingClientRect():{width:0,height:0};
            const cs=canvas?canvasState(canvas):{colors:svg?new Set([...svg.querySelectorAll('*')].map(n=>getComputedStyle(n).fill+getComputedStyle(n).stroke)).size:0,opaque:surface?1:0,signature:svg?svg.innerHTML.length.toString():'none'};
            return {
              ready:document.readyState,
              kind:canvas?'canvas':svg?'svg':leaflet?'leaflet':'none',
              width:rect.width,height:rect.height,unique_colors:cs.colors,
              opaque_samples:cs.opaque,render_signature:cs.signature,
              point_count:(typeof POINTS!=='undefined'&&POINTS.features)?POINTS.features.length:
                document.querySelectorAll('svg circle,.leaflet-marker-icon,.leaflet-interactive').length,
              anomaly_count:(typeof ANOMALIES!=='undefined'&&ANOMALIES.features)?ANOMALIES.features.length:null,
              buttons:document.querySelectorAll('button').length,
              checkboxes:document.querySelectorAll('input[type=checkbox]').length,
              detail_text:(document.querySelector('#detail,[data-role=detail],.feature-detail')?.textContent||'').trim(),
              status_text:(document.querySelector('#status,[data-role=status],.map-status')?.textContent||'').trim()
            };
            """
        )

    interactions: dict[str, Any] = {}
    try:
        driver.get(html.resolve().as_uri())
        WebDriverWait(driver, 20).until(lambda current: current.execute_script("return document.readyState") == "complete")
        time.sleep(0.4)
        initial = state()
        screenshot("overview")

        zoom = driver.execute_script(
            r"""
            const candidates=[...document.querySelectorAll('button')];
            const button=candidates.find(n=>/放大|zoom|\+/.test((n.textContent||'').toLowerCase()) || /zoom/i.test(n.getAttribute('onclick')||''));
            if(!button)return {available:false}; button.click(); return {available:true,label:(button.textContent||'').trim()};
            """
        )
        time.sleep(0.25)
        zoomed = state()
        interactions["zoom_or_pan"] = {
            "passed": bool(zoom.get("available") and (zoomed["render_signature"] != initial["render_signature"] or zoomed["status_text"] != initial["status_text"])),
            "evidence": {"control": zoom, "before": initial["render_signature"], "after": zoomed["render_signature"]},
        }
        screenshot("zoomed")

        toggle = driver.execute_script(
            """
            const boxes=[...document.querySelectorAll('input[type=checkbox]')];
            const box=boxes.find(n=>/anom|异常/i.test(n.id+' '+(n.parentElement?.textContent||'')))||boxes[0];
            if(!box)return {available:false}; const before=box.checked; box.click(); return {available:true,before,after:box.checked,id:box.id};
            """
        )
        time.sleep(0.25)
        toggled = state()
        interactions["anomaly_toggle"] = {
            "passed": bool(toggle.get("available") and toggle.get("before") != toggle.get("after") and toggled["render_signature"] != zoomed["render_signature"]),
            "evidence": toggle,
        }
        screenshot("anomaly_toggled")

        drill = driver.execute_script(
            """
            const canvas=document.querySelector('canvas');
            if(canvas && typeof POINTS!=='undefined' && POINTS.features?.length && typeof proj==='function'){
              const c=POINTS.features[0].geometry.coordinates,p=proj(c[0],c[1]),r=canvas.getBoundingClientRect();
              canvas.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:r.left+p[0],clientY:r.top+p[1]}));
              return {available:true,kind:'canvas'};
            }
            const point=document.querySelector('svg circle,.leaflet-marker-icon,.leaflet-interactive');
            if(point){point.dispatchEvent(new MouseEvent('click',{bubbles:true}));return {available:true,kind:'dom-point'};}
            return {available:false};
            """
        )
        time.sleep(0.2)
        drilled = state()
        interactions["record_source_drilldown"] = {
            "passed": bool(drill.get("available") and drilled["detail_text"] and "source" in drilled["detail_text"].casefold() and "record" in drilled["detail_text"].casefold()),
            "evidence": {"control": drill, "detail": drilled["detail_text"][:500]},
        }
        screenshot("record_detail")

        severe = [
            {"level": item.get("level"), "message": item.get("message")}
            for item in driver.get_log("browser") if item.get("level") == "SEVERE"
        ]
        loaded = initial["kind"] != "none" and initial["width"] >= 300 and initial["height"] >= 180
        rendered = loaded and initial["point_count"] > 0 and initial["unique_colors"] >= 3
        passed = loaded and rendered and not severe and all(item["passed"] for item in interactions.values())
        report = {
            "schema_version": SCHEMA_VERSION,
            "status": "pass" if passed else "fail",
            "generated_by": "external_evaluation_controller",
            "profile": "q24-interactive-map",
            "html": {"filename": html.name, "bytes": html.stat().st_size, "sha256": sha256_file(html)},
            "browser": {"name": "chromium", "version": driver.capabilities.get("browserVersion"), "headless": True, "network": "offline_file"},
            "loaded": loaded,
            "rendered_product": rendered,
            "javascript_errors": severe,
            "metrics": initial,
            "interactions": interactions,
            "screenshot_directory": screenshots.name,
            "screenshots": shots,
            "claim_boundary": "Browser rendering and interaction are verified for Q24 bytes; scientific correctness and global coverage are evaluated separately.",
        }
        atomic_json(output, report)
        return report
    finally:
        driver.quit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_audit(args.html, args.output, args.screenshots)
    except Exception as exc:
        report = {
            "schema_version": SCHEMA_VERSION, "status": "error",
            "generated_by": "external_evaluation_controller", "profile": "q24-interactive-map",
            "html": {"filename": args.html.name, "bytes": args.html.stat().st_size if args.html.is_file() else 0, "sha256": sha256_file(args.html) if args.html.is_file() else None},
            "error": str(exc), "loaded": False, "rendered_product": False,
            "javascript_errors": [], "metrics": {}, "interactions": {}, "screenshots": [],
        }
        atomic_json(args.output, report)
    print(json.dumps({"status": report["status"]}, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
