"""Deterministic offline regression suite for the skill_more layer.

Covers the three additions on top of the frozen v16 snapshot:

1. adversarial audit: canary calibration, clean pass, tampered fail;
2. autopilot: prompt freezing and single-command fixture conduction;
3. declarative adapter channel: proposal drafting, fail-closed gates, and
   end-to-end provided-input delivery through the main workflow.

Run:  python scripts/component_test_more.py
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
PYTHON = sys.executable or "python3"

sys.path.insert(0, str(SCRIPT_DIR))

from autopilot import freeze_prompt  # noqa: E402

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
    else:
        FAILED.append(f"{name}: {detail}")
        print(f"FAIL {name}: {detail}")


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False, **kwargs)


CANDIDATE_CSV = """station,lat,lon,As_ppm,Cu_ppm,Pb_ppm,Zn_ppm,method
ST-001,52.31,104.28,4.2,18.5,12.1,54.0,ICP-MS
ST-002,53.10,105.90,3.8,22.4,15.7,61.2,ICP-MS
ST-003,51.75,103.66,5.1,17.2,11.3,48.9,ICP-MS
ST-004,54.02,106.44,6.7,25.8,18.2,72.5,ICP-MS
ST-005,52.88,107.12,2.9,14.6,9.8,41.7,ICP-MS
ST-006,53.55,104.95,4.5,20.1,13.5,58.3,ICP-MS
ST-007,51.20,105.33,3.3,16.8,10.9,45.6,ICP-MS
ST-008,54.46,103.88,7.2,28.3,21.4,79.8,ICP-MS
ST-009,52.05,106.77,4.9,19.7,14.1,55.2,ICP-MS
ST-010,53.91,107.58,5.6,23.5,16.8,66.4,ICP-MS
ST-011,51.48,104.62,3.6,15.9,10.2,43.8,ICP-MS
ST-012,52.66,105.51,4.1,18.0,12.7,52.1,ICP-MS
ST-013,53.29,106.09,5.4,21.9,15.2,63.7,ICP-MS
ST-014,54.18,105.24,6.1,24.7,17.6,69.9,ICP-MS
ST-015,51.93,103.41,3.1,15.2,9.5,40.3,ICP-MS
ST-016,52.44,107.86,4.7,19.3,13.9,56.8,ICP-MS
ST-017,53.72,104.17,5.8,22.8,16.1,65.0,ICP-MS
ST-018,51.62,106.35,3.9,17.5,11.8,49.4,ICP-MS
ST-019,54.33,106.92,6.5,26.4,19.3,74.6,ICP-MS
ST-020,52.19,105.08,4.4,18.9,13.2,53.9,ICP-MS
ST-021,53.06,103.95,5.0,20.6,14.6,60.1,ICP-MS
ST-022,51.37,107.29,3.4,16.1,10.5,44.7,ICP-MS
ST-023,54.09,104.73,6.9,27.1,20.2,77.3,ICP-MS
ST-024,52.77,106.58,4.6,19.0,13.7,57.5,ICP-MS
ST-025,53.48,105.82,5.3,21.4,15.5,62.9,ICP-MS
"""

CANONICAL_PROMPT = (
    "\u8bf7\u4f7f\u7528 Global Geochemical Atlas Skill \u81ea\u4e3b\u6784\u5efa"
    "\u5168\u7403\u5730\u7403\u5316\u5b66\u5143\u7d20\u5206\u5e03\u56fe\u8c31\u3002"
    "\u8981\u6c42\uff1a\u81f3\u5c11\u8986\u76d6 As\u3001Cr\u3001Cu\u3001Hg\u3001Ni\u3001"
    "Pb\u3001Zn \u4e2d\u7684 3 \u4e2a\u5143\u7d20\uff0c\u81f3\u5c11\u8986\u76d6"
    "\u5ca9\u77f3\u3001\u571f\u58e4\u3001\u6c89\u79ef\u7269\u3001\u6c34\u4f53"
    "\u4e2d\u7684 2 \u7c7b\u4ecb\u8d28\uff0c\u5c3d\u91cf\u5168\u9762\u6269\u5927"
    "\u533a\u57df\u4e0e\u6765\u6e90\u8986\u76d6\u3002"
    "\u8bf7\u5c3d\u91cf\u5728 15 \u5206\u949f\u5185\u5b8c\u6210\u3002"
)


def build_approved_spec(workdir: Path) -> tuple[Path, Path]:
    workdir.mkdir(parents=True, exist_ok=True)
    candidate = workdir / "candidate.csv"
    candidate.write_text(CANDIDATE_CSV, encoding="utf-8")
    spec = {
        "spec_version": "declarative-adapter-spec-v1",
        "source_id": "spec-synthetic-regression-slice",
        "title": "Synthetic regression test slice",
        "official_source_url": "https://example.org/synthetic",
        "dataset_doi": None,
        "dataset_version": "synthetic regression v1, accessed 2026-08-18",
        "license": {
            "id": "CC0-1.0",
            "evidence_url": "https://example.org/synthetic/license",
        },
        "download": {
            "url": "https://example.org/synthetic/candidate.csv",
            "max_bytes": 1048576,
            "expected_sha256": None,
        },
        "format": "csv",
        "layout": "wide",
        "medium": {"constant": "soil"},
        "mapping": {
            "wide_observations": [
                {"analyte": "As", "value_column": "As_ppm", "unit_constant": "ppm"},
                {"analyte": "Cu", "value_column": "Cu_ppm", "unit_constant": "ppm"},
                {"analyte": "Pb", "value_column": "Pb_ppm", "unit_constant": "ppm"},
                {"analyte": "Zn", "value_column": "Zn_ppm", "unit_constant": "ppm"},
            ],
            "latitude_column": "lat",
            "longitude_column": "lon",
            "sample_id_column": "station",
            "method_column": "method",
        },
        "coordinate": {
            "crs_declared": "EPSG:4326",
            "crs_evidence_url": "https://example.org/synthetic/metadata",
        },
        "row_filters": [],
        "target_gap": None,
        "approval_state": "approved_by_operator",
        "notes": None,
    }
    spec_path = workdir / "spec-approved.json"
    spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec_path, candidate


def test_freeze_prompt() -> None:
    request, report = freeze_prompt(CANONICAL_PROMPT)
    check(
        "freeze.full_candidate_set",
        request["elements"] == ["As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn"],
        f"elements={request['elements']}",
    )
    check(
        "freeze.all_media",
        request["media"] == ["rock", "soil", "sediment", "water"],
        f"media={request['media']}",
    )
    check("freeze.region_global", request["region"] == "global")
    check(
        "freeze.breadth_mode",
        request["coverage_mode"] == "maximize_evidence_breadth"
        and request["max_records"] == 200000,
    )
    check(
        "freeze.floors_are_floors",
        request["minimum_elements"] == 3 and request["minimum_media"] == 2,
        f"{request['minimum_elements']}/{request['minimum_media']}",
    )
    check(
        "freeze.deadline_minutes",
        report["matches"]["deadline_seconds"] == 900.0,
        str(report["matches"]["deadline_seconds"]),
    )


def test_fixture_pipeline(tmp: Path) -> Path:
    out_dir = tmp / "fixture-out"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "run_atlas_request.py"),
            "--request",
            str(SKILL_DIR / "fixtures" / "production-usgs" / "request.json"),
            "--demo",
            "production-usgs",
            "--analysis-profile",
            "production",
            "--generated-at",
            "2026-08-17T00:00:00Z",
            "--output-dir",
            str(out_dir),
        ]
    )
    check("fixture.run", result.returncode == 0, result.stderr[-300:])
    return out_dir


def test_audit_clean(tmp: Path, out_dir: Path) -> None:
    audit_dir = tmp / "audit-clean"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "adversarial_audit.py"),
            "--output-dir",
            str(out_dir),
            "--audit-dir",
            str(audit_dir),
        ]
    )
    check("audit.clean_pass", result.returncode == 0, result.stdout[-300:])
    receipt = json.loads((audit_dir / "audit_receipt.json").read_text(encoding="utf-8"))
    check("audit.verdict_pass", receipt["verdict"] == "pass", receipt["verdict"])
    check(
        "audit.calibration_full_recall",
        receipt["calibration"]["recall"] == 1.0
        and receipt["calibration"]["planted"] >= 9,
        json.dumps(receipt["calibration"].get("missed", [])),
    )
    check(
        "audit.no_skip_acquittal",
        json.loads(
            run(
                [
                    PYTHON,
                    str(SCRIPT_DIR / "adversarial_audit.py"),
                    "--output-dir",
                    str(out_dir),
                    "--audit-dir",
                    str(tmp / "audit-uncalibrated"),
                    "--skip-calibration",
                ]
            ).stdout.splitlines()[-1]
        )["verdict"]
        == "inadmissible_uncalibrated",
    )


def test_audit_tampered(tmp: Path, out_dir: Path) -> None:
    tampered = tmp / "tampered"
    shutil.copytree(out_dir, tampered)
    csv_path = tampered / "geochemistry.csv"
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = list(reader.fieldnames or [])
    for row in rows:
        if row["normalized_value"] and row["conversion_factor"]:
            row["normalized_value"] = str(float(row["normalized_value"]) * 50)
            break
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "adversarial_audit.py"),
            "--output-dir",
            str(tampered),
            "--audit-dir",
            str(tmp / "audit-tampered"),
        ]
    )
    check("audit.tampered_fails", result.returncode == 1, result.stdout[-300:])
    summary = json.loads(result.stdout.splitlines()[-1])
    check(
        "audit.tampered_verdict",
        summary["verdict"] == "fail" and summary["error_count"] >= 1,
        json.dumps(summary),
    )


def test_autopilot_fixture(tmp: Path) -> None:
    out_dir = tmp / "autopilot-out"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "autopilot.py"),
            "--request",
            str(SKILL_DIR / "fixtures" / "production-usgs" / "request.json"),
            "--demo",
            "production-usgs",
            "--output-dir",
            str(out_dir),
        ]
    )
    check("autopilot.done", result.returncode == 0, result.stdout[-300:])
    check("autopilot.state_line", "AUTOPILOT_STATE=DONE" in result.stdout)
    report_path = tmp / "autopilot-out_autopilot" / "executor_compliance_report.json"
    check("autopilot.compliance_report", report_path.is_file())
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        check(
            "autopilot.no_violations",
            report["violations"] == [],
            str(report["violations"]),
        )
        check(
            "autopilot.audit_wired",
            report["audit"].get("verdict") == "pass",
            json.dumps(report.get("audit")),
        )
        check(
            "autopilot.final_facts",
            report["final_answer_facts"].get("status") is not None,
        )


def test_declarative_gates(tmp: Path) -> None:
    spec_path, candidate = build_approved_spec(tmp / "decl")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    def run_engine(spec_obj: dict, name: str) -> subprocess.CompletedProcess[str]:
        path = tmp / "decl" / name
        path.write_text(json.dumps(spec_obj), encoding="utf-8")
        return run(
            [
                PYTHON,
                str(SCRIPT_DIR / "declarative_adapter.py"),
                "--spec",
                str(path),
                "--workspace",
                str(tmp / "decl" / (name + ".ws")),
                "--local-file",
                str(candidate),
            ]
        )

    draft = dict(spec, approval_state="draft")
    check("decl.draft_rejected", run_engine(draft, "spec-draft.json").returncode == 1)

    bad_license = dict(
        spec, license={"id": "Proprietary-EULA", "evidence_url": "https://x.example/l"}
    )
    check(
        "decl.license_fail_closed",
        run_engine(bad_license, "spec-license.json").returncode == 1,
    )

    bad_hash = dict(spec)
    bad_hash["download"] = dict(spec["download"], expected_sha256="0" * 64)
    check(
        "decl.hash_fail_closed", run_engine(bad_hash, "spec-hash.json").returncode == 1
    )

    no_version = dict(spec, dataset_version="")
    check(
        "decl.version_required",
        run_engine(no_version, "spec-version.json").returncode == 1,
    )

    auto = dict(spec, approval_state="auto_candidate_open_license")
    check(
        "decl.auto_requires_flag",
        run_engine(auto, "spec-auto.json").returncode == 1,
    )


def test_declarative_end_to_end(tmp: Path) -> None:
    spec_path, candidate = build_approved_spec(tmp / "decl-e2e")
    workspace = tmp / "decl-e2e" / "ws"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "declarative_adapter.py"),
            "--spec",
            str(spec_path),
            "--workspace",
            str(workspace),
            "--local-file",
            str(candidate),
        ]
    )
    check("decl.acquire", result.returncode == 0, result.stdout[-300:])
    receipt = json.loads(
        (workspace / "adapter_receipt.json").read_text(encoding="utf-8")
    )
    check(
        "decl.receipt_gates",
        receipt["license"]["allowlist_gate"] == "passed"
        and receipt["download"]["hash_pinned_at_acquisition"] is True
        and receipt["counts"]["accepted_measurements"] == 100,
        json.dumps(receipt["counts"]),
    )
    request = {
        "elements": ["As", "Cu", "Pb", "Zn"],
        "region": {"bbox": [103.0, 51.0, 108.0, 55.0]},
        "media": ["soil"],
        "coverage_mode": "fixed",
        "sources": "auto",
        "target_crs": "EPSG:4326",
        "license_policy": "open_only",
        "research_use_policy": "permitted_research",
        "minimum_evidence_tier": "D",
        "minimum_use_mode": "normalized_analysis",
        "max_records": 50000,
        "offline": False,
    }
    request_path = tmp / "decl-e2e" / "REQUEST.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    out_dir = tmp / "decl-e2e" / "out"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "run_atlas_request.py"),
            "--request",
            str(request_path),
            "--input",
            str(workspace / "demo_input.csv"),
            "--evidence-jsonl",
            str(workspace / "sources.jsonl"),
            "--acquisition-manifest",
            str(workspace / "acquisition_manifest.json"),
            "--output-dir",
            str(out_dir),
        ]
    )
    check(
        "decl.workflow", result.returncode == 0, (result.stdout + result.stderr)[-300:]
    )
    summary = json.loads(result.stdout.splitlines()[-1])
    check(
        "decl.coverage_complete",
        (summary.get("request_coverage") or {}).get("status") == "complete",
        json.dumps(summary.get("request_coverage")),
    )
    validate = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "validate_outputs.py"),
            "--output-dir",
            str(out_dir),
        ]
    )
    check("decl.validate_outputs", validate.returncode == 0, validate.stdout[-300:])
    audit = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "adversarial_audit.py"),
            "--output-dir",
            str(out_dir),
            "--audit-dir",
            str(tmp / "decl-e2e" / "audit"),
        ]
    )
    check("decl.audit_pass", audit.returncode == 0, audit.stdout[-300:])


def test_proposer(tmp: Path) -> None:
    workdir = tmp / "proposer"
    workdir.mkdir(parents=True, exist_ok=True)
    candidate = workdir / "candidate.csv"
    candidate.write_text(CANDIDATE_CSV, encoding="utf-8")
    output = workdir / "spec-draft.json"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "propose_adapter_spec.py"),
            "--title",
            "Synthetic proposer slice",
            "--candidate-url",
            "https://example.org/synthetic/candidate.csv",
            "--medium",
            "soil",
            "--sniff",
            "--local-file",
            str(candidate),
            "--output",
            str(output),
        ]
    )
    check("proposer.runs", result.returncode == 0, result.stderr[-300:])
    draft = json.loads(output.read_text(encoding="utf-8"))
    observations = draft["mapping"]["wide_observations"]
    check(
        "proposer.columns_recognized",
        {item["analyte"] for item in observations} == {"As", "Cu", "Pb", "Zn"}
        and draft["mapping"]["latitude_column"] == "lat"
        and draft["mapping"]["longitude_column"] == "lon",
        json.dumps(draft["mapping"]),
    )
    check("proposer.stays_draft", draft["approval_state"] == "draft")
    summary = json.loads(result.stdout.splitlines()[-1])
    check(
        "proposer.unresolved_listed",
        any("license.id" in item for item in summary["unresolved"]),
        json.dumps(summary["unresolved"]),
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="skill-more-tests.") as tmp_name:
        tmp = Path(tmp_name)
        test_freeze_prompt()
        out_dir = test_fixture_pipeline(tmp)
        if out_dir.is_dir():
            test_audit_clean(tmp, out_dir)
            test_audit_tampered(tmp, out_dir)
        test_autopilot_fixture(tmp)
        test_declarative_gates(tmp)
        test_declarative_end_to_end(tmp)
        test_proposer(tmp)
    total = PASSED + len(FAILED)
    print(f"component_test_more: {PASSED}/{total} checks passed")
    if FAILED:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
