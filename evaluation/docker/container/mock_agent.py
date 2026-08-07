#!/usr/bin/env python3
"""Create a deterministic ten-artifact submission for Docker smoke tests only."""

from __future__ import annotations

import base64
import csv
import json
import sqlite3
from pathlib import Path


ROOT = Path("/submission/artifacts")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "observations.csv").write_text("record_id,element_or_analyte,value,unit,medium\n", encoding="utf-8")
    with sqlite3.connect(ROOT / "geochemical.sqlite") as connection:
        connection.execute("CREATE TABLE observations(record_id TEXT PRIMARY KEY)")
    (ROOT / "sources.jsonl").write_text("", encoding="utf-8")
    (ROOT / "qc_report.json").write_text(
        json.dumps({"status": "smoke_only", "record_count": 0}, sort_keys=True) + "\n", encoding="utf-8"
    )
    for name, fields in (
        ("anomaly_results.csv", ["record_id", "direction", "robust_z"]),
        ("h3_cells.csv", ["cell_id", "observation_count"]),
    ):
        with (ROOT / name).open("w", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(fields)
    empty_geojson = {"type": "FeatureCollection", "features": []}
    (ROOT / "anomalies.geojson").write_text(json.dumps(empty_geojson, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "map.png").write_bytes(PNG)
    (ROOT / "map.html").write_text("<!doctype html><meta charset=utf-8><title>Docker smoke</title>\n", encoding="utf-8")
    skill = Path("/workspace/.opencode/skills/global-geochemical-atlas/SKILL.md")
    manifest = {
        "status": "smoke_only",
        "benchmark_evidence": {"mock_agent": True, "skill_visible": skill.is_file()},
    }
    (ROOT / "run_manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "success", "skill_visible": skill.is_file()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
