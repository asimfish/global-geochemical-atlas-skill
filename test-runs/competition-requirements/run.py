#!/usr/bin/env python3
"""Independently test the official geochemical-atlas competition contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "global-geochemical-atlas"
SCRIPTS = SKILL / "scripts"
FIXTURE = SKILL / "fixtures" / "four-media" / "combined-v3"
BUILDER = REPO.parent / ".agents" / "skills" / "ai4s-skill-builder" / "scripts"


class CompetitionAcceptanceError(RuntimeError):
    """Raised when one official competition criterion lacks direct evidence."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CompetitionAcceptanceError(f"expected JSON object: {path}")
    return value


def run_command(
    command: list[str],
    *,
    log_path: Path,
    expected_codes: set[int] = {0},
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    write_json(
        log_path,
        {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        },
    )
    if completed.returncode not in expected_codes:
        raise CompetitionAcceptanceError(
            f"command returned {completed.returncode}: {' '.join(command)}"
        )
    return completed


def require(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise CompetitionAcceptanceError(message)
    checks.append(message)


def capture_screenshot(
    root: Path, atlas_dir: Path, checks: list[str]
) -> dict[str, Any]:
    browser = shutil.which("google-chrome") or shutil.which("chromium")
    if browser is None:
        raise CompetitionAcceptanceError(
            "Chrome/Chromium is required for map rendering"
        )
    screenshot = root / "screenshots" / "atlas-overview.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            browser,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--window-size=1800,1200",
            "--virtual-time-budget=5000",
            f"--screenshot={screenshot}",
            (atlas_dir / "interactive_map.html").resolve().as_uri(),
        ],
        log_path=root / "logs" / "browser-screenshot.json",
        timeout=60,
    )
    require(
        screenshot.is_file() and screenshot.stat().st_size > 20_000,
        "the interactive atlas paints in a real headless browser",
        checks,
    )
    return {
        "path": screenshot.relative_to(root).as_posix(),
        "sha256": sha256_file(screenshot),
        "bytes": screenshot.stat().st_size,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = (
        args.output_root if args.output_root.is_absolute() else REPO / args.output_root
    )
    if root.exists():
        raise SystemExit(f"refusing to overwrite existing output root: {root}")
    root.mkdir(parents=True)
    atlas_dir = root / "atlas"
    checks: list[str] = []
    try:
        execution = run_command(
            [
                sys.executable,
                str(SCRIPTS / "run_atlas_request.py"),
                "--request",
                str(FIXTURE / "request.json"),
                "--output-dir",
                str(atlas_dir),
                "--demo",
                "four-media",
                "--analysis-profile",
                "production",
                "--generated-at",
                "2026-08-24T00:00:00Z",
            ],
            log_path=root / "logs" / "run-atlas-request.json",
        )
        execution_report = json.loads(execution.stdout)
        validation = run_command(
            [
                sys.executable,
                str(SCRIPTS / "validate_outputs.py"),
                "--output-dir",
                str(atlas_dir),
            ],
            log_path=root / "logs" / "validate-outputs.json",
        )
        require(
            json.loads(validation.stdout)["status"] == "valid",
            "the complete eighteen-file atlas contract validates",
            checks,
        )

        request = read_json(FIXTURE / "request.json")
        with (atlas_dir / "geochemistry.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        fields = set(rows[0]) if rows else set()
        media_counts = Counter(row["medium"] for row in rows)
        element_counts = Counter(row["element_or_analyte"] for row in rows)
        required_fields = {
            "original_value_raw",
            "original_unit",
            "normalized_value",
            "normalized_unit",
            "latitude",
            "longitude",
            "geologic_unit_raw",
            "matched_geologic_unit",
            "analytical_method",
            "sample_type",
            "source_locator",
            "official_source_url",
            "file_sha256",
        }
        require(
            set(request["media"]) == {"rock", "soil", "sediment", "water"}
            and set(media_counts) == {"rock", "soil", "sediment", "water"},
            "the request and standardized database cover all four required media",
            checks,
        )
        require(
            required_fields.issubset(fields)
            and all(row["source_locator"] and row["file_sha256"] for row in rows),
            "records preserve original/standard values, coordinates, geology, method and provenance",
            checks,
        )
        require(
            any(row["normalized_value"] for row in rows)
            and all(row["original_value_raw"] for row in rows),
            "unit normalization retains every publisher raw value instead of overwriting it",
            checks,
        )

        map_html = (atlas_dir / "interactive_map.html").read_text(encoding="utf-8")
        map_markers = {
            'id="region"',
            'id="element"',
            'id="geology"',
            'id="sampleType"',
            'id="mapMode"',
            'value="heat"',
            'id="combinationView"',
            'id="anomalyView"',
            'id="databaseView"',
            'id="sourceView"',
        }
        require(
            map_markers.issubset(
                {marker for marker in map_markers if marker in map_html}
            ),
            "the map exposes element, region, geology, sample type, heatmap and combination controls",
            checks,
        )
        source_report = read_json(atlas_dir / "sources_and_confidence.json")
        anomaly_report = read_json(atlas_dir / "anomaly_report.json")
        require(
            len(source_report.get("sources", [])) >= 2
            and (atlas_dir / "source_manifest.json").is_file()
            and (atlas_dir / "record_evidence.jsonl").is_file(),
            "source and confidence outputs retain dataset and record-level traceability",
            checks,
        )
        require(
            isinstance(anomaly_report.get("candidate_count"), int)
            and (atlas_dir / "anomalies.geojson").is_file()
            and (atlas_dir / "anomaly_regions.geojson").is_file(),
            "anomaly enrichment/depletion screening emits point and regional artifacts",
            checks,
        )

        skill_dirs = sorted(
            path for path in (REPO / "skills").iterdir() if path.is_dir()
        )
        require(
            skill_dirs == [SKILL] and (SKILL / "SKILL.md").is_file(),
            "the repository contains exactly one complete reusable production Skill",
            checks,
        )
        run_command(
            [
                sys.executable,
                str(BUILDER / "validate_competition_skill.py"),
                str(REPO),
            ],
            log_path=root / "logs" / "validate-competition-skill.json",
        )
        submission = root / "submission.zip"
        run_command(
            [
                sys.executable,
                str(BUILDER / "package_submission.py"),
                str(REPO),
                "--output",
                str(submission),
            ],
            log_path=root / "logs" / "package-submission.json",
            timeout=300,
        )
        with zipfile.ZipFile(submission) as archive:
            entries = archive.infolist()
            skill_documents = [
                item.filename
                for item in entries
                if item.filename.startswith("skills/")
                and item.filename.count("/") == 2
                and item.filename.endswith("/SKILL.md")
            ]
            maximum_file = max((item.file_size for item in entries), default=0)
        require(
            skill_documents == ["skills/global-geochemical-atlas/SKILL.md"]
            # Live submission guide (synmatai.cn/hackathon/submission-guide.md):
            # package <= 50 MB, any single file <= 10 MB.
            and submission.stat().st_size <= 50_000_000
            and maximum_file <= 10_000_000,
            "the submission package contains one Skill and stays within the live 50 MB / 10 MB limits",
            checks,
        )
        screenshot = capture_screenshot(root, atlas_dir, checks)

        deliverables = {
            "interactive_element_distribution_map": "atlas/interactive_map.html",
            "standardized_geochemical_database": "atlas/geochemistry.csv",
            "sources_and_confidence": "atlas/sources_and_confidence.json",
            "anomaly_region_identification": "atlas/anomaly_regions.geojson",
            "reusable_skill_document": "../../skills/global-geochemical-atlas/SKILL.md",
        }
        report = {
            "schema_version": "gga-competition-acceptance-v1",
            "status": "PASS",
            "task_scope": {
                "region": request["region"],
                "requested_elements": request["elements"],
                "requested_media": request["media"],
                "observed_media_counts": dict(sorted(media_counts.items())),
                "observed_element_counts": dict(sorted(element_counts.items())),
                "measurement_record_count": len(rows),
            },
            "workflow_status": execution_report.get("status"),
            "scientific_boundary": (
                "The offline fixture proves the reusable workflow and output contract; "
                "it is not a representative census of global geochemistry."
            ),
            "deliverables": deliverables,
            "submission": {
                "path": submission.relative_to(root).as_posix(),
                "sha256": sha256_file(submission),
                "bytes": submission.stat().st_size,
                "entry_count": len(entries),
                "skill_documents": skill_documents,
                "largest_file_bytes": maximum_file,
            },
            "screenshot": screenshot,
            "checks": checks,
        }
        write_json(root / "COMPETITION-ACCEPTANCE.json", report)
    except Exception as exc:
        write_json(
            root / "COMPETITION-ACCEPTANCE.json",
            {
                "schema_version": "gga-competition-acceptance-v1",
                "status": "FAIL",
                "error": str(exc),
            },
        )
        raise
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
