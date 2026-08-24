"""Deterministic offline regression suite for the skill_more layer.

Covers the additions on top of the acquisition-coverage baseline:

1. adversarial audit: canary calibration, clean pass, tampered fail, and
   graded verdicts (pass_scope_narrowed with scope notes);
2. autopilot: prompt freezing and single-command fixture conduction;
3. declarative adapter channel: proposal drafting, fail-closed gates, and
   end-to-end provided-input delivery through the main workflow;
4. claim ledger: evidence-bound claims, phantom-number and missing-scope
   detection in draft answers;
5. cross-run acquisition memory: harvest, proven-source priorities, banlist
   and the loop's round-1 seeding hook.

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


def test_claim_ledger(tmp: Path, out_dir: Path) -> None:
    ledger_path = tmp / "ledger" / "claim_ledger.json"
    result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "claim_ledger.py"),
            "--run-dir",
            str(out_dir),
            "--ledger",
            str(ledger_path),
        ]
    )
    check("ledger.builds", result.returncode == 0, result.stdout[-300:])
    if not ledger_path.is_file():
        check("ledger.file", False, "claim_ledger.json not written")
        return
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    check(
        "ledger.no_unsupported",
        ledger["summary"]["fail_unsupported"] == 0,
        json.dumps(ledger["summary"]),
    )
    check(
        "ledger.records_recomputed",
        any(
            c["claim_id"] == "records" and (c.get("recompute") or {}).get("match")
            for c in ledger["claims"]
        ),
    )
    check(
        "ledger.scoped_claims_present",
        any(c["integrity"] == "warn_scope" and c["scope"] for c in ledger["claims"]),
    )

    run_summary = json.loads((out_dir / "run_summary.json").read_text(encoding="utf-8"))
    records = run_summary["metrics"]["standardized_record_count"]
    anomalies = run_summary["metrics"]["candidate_anomaly_count"]
    good = tmp / "ledger" / "draft_good.md"
    good.write_text(
        f"standardized {records} records; {anomalies} statistical candidate "
        "anomalies (robust-z screen, not confirmed).",
        encoding="utf-8",
    )
    bad = tmp / "ledger" / "draft_bad.md"
    bad.write_text(
        f"acquired 999999 high-quality records and found {anomalies} anomalies.",
        encoding="utf-8",
    )
    good_result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "claim_ledger.py"),
            "--run-dir",
            str(out_dir),
            "--ledger",
            str(ledger_path),
            "--check-answer",
            str(good),
        ]
    )
    check(
        "ledger.good_answer_bound",
        good_result.returncode == 0 and "answer_bound" in good_result.stdout,
        good_result.stdout[-300:],
    )
    bad_result = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "claim_ledger.py"),
            "--run-dir",
            str(out_dir),
            "--ledger",
            str(ledger_path),
            "--check-answer",
            str(bad),
        ]
    )
    bad_payload = json.loads(bad_result.stdout.splitlines()[-1])
    check(
        "ledger.phantom_caught",
        bad_result.returncode == 1 and bad_payload["phantom_count"] >= 1,
        bad_result.stdout[-300:],
    )
    check(
        "ledger.scope_violation_caught",
        bad_payload["scope_violation_count"] >= 1,
        bad_result.stdout[-300:],
    )


def test_acquisition_memory(tmp: Path, out_dir: Path) -> None:
    memory_path = tmp / "memory" / "memory.json"
    update = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "acquisition_memory.py"),
            "update",
            "--memory-file",
            str(memory_path),
            "--run-dir",
            str(out_dir),
        ]
    )
    check("memory.updates", update.returncode == 0, update.stderr[-300:])
    memory = json.loads(memory_path.read_text(encoding="utf-8"))
    check(
        "memory.sources_harvested",
        memory["runs_recorded"] == 1 and len(memory["sources"]) >= 1,
        json.dumps(memory)[:200],
    )
    # A repeat offender enters the banlist; one success clears the streak.
    memory["sources"]["dead-source"] = {
        "ok_runs": 0,
        "fail_runs": 3,
        "fail_streak": 3,
        "total_records": 0,
        "media": ["soil"],
        "last_outcome": "error:source_not_accessible",
        "last_seen": memory["updated_at"],
    }
    memory_path.write_text(json.dumps(memory), encoding="utf-8")
    request_path = out_dir / "request_evidence" / "request.json"
    advise = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "acquisition_memory.py"),
            "advise",
            "--memory-file",
            str(memory_path),
            "--request",
            str(request_path),
        ]
    )
    check("memory.advises", advise.returncode == 0, advise.stderr[-300:])
    advice = json.loads(advise.stdout.splitlines()[-1])
    check(
        "memory.proven_prioritized",
        len(advice["priority_source_ids"]) >= 1
        and "dead-source" not in advice["priority_source_ids"],
        json.dumps(advice),
    )
    check(
        "memory.banlist",
        any(item["source_id"] == "dead-source" for item in advice["banlist"]),
        json.dumps(advice["banlist"]),
    )
    seed_help = run(
        [PYTHON, str(SCRIPT_DIR / "run_self_correction_loop.py"), "--help"]
    )
    check(
        "memory.loop_seed_arg",
        "--seed-priority-source-id" in seed_help.stdout,
    )


def test_discovery_duel(tmp: Path, out_dir: Path) -> None:
    duel_dir = tmp / "duel"
    brief = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "discovery_duel.py"),
            "--output-dir",
            str(out_dir),
            "--duel-dir",
            str(duel_dir),
            "--mode",
            "brief",
            "--gap",
            "medium=soil;country=Mongolia;elements=As,Cd",
        ]
    )
    check("duel.briefs", brief.returncode == 0, brief.stdout[-200:])
    check(
        "duel.brief_files",
        (duel_dir / "scout_brief.json").is_file()
        and (duel_dir / "skeptic_brief.json").is_file(),
    )
    candidates = tmp / "duel_candidates.json"
    candidates.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "gap_id": "manual-0",
                        "title": "Open national soil geochemistry",
                        "source_url": "https://data.example.gov/soil.csv",
                        "license_hint": "CC-BY 4.0",
                        "dataset_doi": "10.5281/zenodo.111",
                        "medium": "soil",
                        "region_hint": "Mongolia",
                    },
                    {
                        "gap_id": "manual-0",
                        "title": "Paywalled supplement",
                        "source_url": "https://pub.example.com/supp.xlsx",
                        "license_hint": "all rights reserved",
                        "medium": "soil",
                        "region_hint": "Mongolia",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    objections = tmp / "duel_objections.json"
    objections.write_text(
        json.dumps(
            {
                "objections": [
                    {
                        "candidate_index": 1,
                        "class": "paywalled",
                        "detail": "requires subscription",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    adjudicated = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "discovery_duel.py"),
            "--output-dir",
            str(out_dir),
            "--duel-dir",
            str(duel_dir),
            "--mode",
            "adjudicate",
            "--candidates",
            str(candidates),
            "--objections",
            str(objections),
            "--gap",
            "medium=soil;country=Mongolia;elements=As,Cd",
        ]
    )
    check("duel.adjudicates", adjudicated.returncode == 0, adjudicated.stdout[-200:])
    verdict = json.loads(
        (duel_dir / "duel_verdict_round1.json").read_text(encoding="utf-8")
    )
    by_title = {r["title"]: r for r in verdict["results"]}
    good = by_title["Open national soil geochemistry"]
    bad = by_title["Paywalled supplement"]
    check(
        "duel.good_admitted",
        good["verdict"] == "admit_to_spec_draft"
        and "propose_adapter_spec" in good.get("next_command", ""),
        json.dumps(good),
    )
    check(
        "duel.bad_blocked",
        bad["verdict"] in ("revise", "reject") and bad["action_items"],
        json.dumps(bad),
    )
    check(
        "duel.stop_reason",
        verdict["stop_reason"] == "threshold_met",
        str(verdict["stop_reason"]),
    )


def test_discovery_duel_rounds(tmp: Path, out_dir: Path) -> None:
    """Round 1 revise -> objections answered -> round 2 admit -> spec draft."""
    duel_dir = tmp / "duel_rounds"
    base = {
        "gap_id": "manual-0",
        "title": "Mongolia soil geochemistry portal",
        "source_url": "https://portal.example.mn/soil.csv",
        "dataset_doi": "10.5281/zenodo.999",
        "medium": "soil",
        "region_hint": "Mongolia",
    }
    round1_candidates = tmp / "duel_r1_cand.json"
    round1_candidates.write_text(json.dumps({"candidates": [base]}), encoding="utf-8")
    round1_objections = tmp / "duel_r1_obj.json"
    round1_objections.write_text(
        json.dumps(
            {
                "objections": [
                    {
                        "candidate_index": 0,
                        "class": "license_unclear",
                        "detail": "portal page does not state a license",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    gap = "medium=soil;country=Mongolia"
    round1 = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "discovery_duel.py"),
            "--output-dir",
            str(out_dir),
            "--duel-dir",
            str(duel_dir),
            "--mode",
            "adjudicate",
            "--candidates",
            str(round1_candidates),
            "--objections",
            str(round1_objections),
            "--gap",
            gap,
        ]
    )
    verdict1 = json.loads(
        (duel_dir / "duel_verdict_round1.json").read_text(encoding="utf-8")
    )
    check(
        "duel.round1_revise",
        round1.returncode == 1
        and verdict1["results"][0]["verdict"] == "revise"
        and verdict1["results"][0]["action_items"],
        json.dumps(verdict1["results"][0]),
    )
    revised = dict(base)
    revised["license_hint"] = "CC0 1.0 (stated on data page)"
    revised["resolved_objections"] = ["license_unclear"]
    round2_candidates = tmp / "duel_r2_cand.json"
    round2_candidates.write_text(json.dumps({"candidates": [revised]}), encoding="utf-8")
    round2 = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "discovery_duel.py"),
            "--output-dir",
            str(out_dir),
            "--duel-dir",
            str(duel_dir),
            "--mode",
            "adjudicate",
            "--candidates",
            str(round2_candidates),
            "--gap",
            gap,
        ]
    )
    verdict2 = json.loads(
        (duel_dir / "duel_verdict_round2.json").read_text(encoding="utf-8")
    )
    check(
        "duel.round2_admit",
        round2.returncode == 0
        and verdict2["results"][0]["verdict"] == "admit_to_spec_draft"
        and verdict2["stop_reason"] == "threshold_met",
        json.dumps(verdict2["results"][0]),
    )
    state = json.loads((duel_dir / "duel_state.json").read_text(encoding="utf-8"))
    check(
        "duel.state_two_rounds",
        [r["round"] for r in state["rounds"]] == [1, 2],
        json.dumps(state),
    )
    check(
        "duel.handoff_command",
        "propose_adapter_spec.py" in verdict2["results"][0].get("next_command", ""),
        verdict2["results"][0].get("next_command", ""),
    )
    sample = tmp / "duel_sample.csv"
    sample.write_text(
        "element,value,unit,medium,latitude,longitude\n"
        "As,5.2,mg/kg,soil,47.9,106.9\n",
        encoding="utf-8",
    )
    spec_out = tmp / "duel_spec.json"
    drafted = run(
        [
            PYTHON,
            str(SCRIPT_DIR / "propose_adapter_spec.py"),
            "--candidate-url",
            "https://portal.example.mn/soil.csv",
            "--title",
            "Mongolia soil geochemistry portal",
            "--medium",
            "soil",
            "--local-file",
            str(sample),
            "--output",
            str(spec_out),
        ]
    )
    spec = json.loads(spec_out.read_text(encoding="utf-8")) if spec_out.is_file() else {}
    check(
        "duel.spec_drafted_not_approved",
        drafted.returncode == 0 and spec.get("approval_state") == "draft",
        json.dumps({"rc": drafted.returncode, "approval_state": spec.get("approval_state")}),
    )


def test_graded_verdict_schema() -> None:
    schema = json.loads(
        (SKILL_DIR / "references" / "audit-receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    check(
        "audit.graded_verdict_in_schema",
        "pass_scope_narrowed" in schema["properties"]["verdict"]["enum"],
    )
    check(
        "audit.scope_notes_in_schema",
        "scope_notes" in schema["properties"],
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="skill-more-tests.") as tmp_name:
        tmp = Path(tmp_name)
        test_freeze_prompt()
        out_dir = test_fixture_pipeline(tmp)
        if out_dir.is_dir():
            test_audit_clean(tmp, out_dir)
            test_audit_tampered(tmp, out_dir)
            test_claim_ledger(tmp, out_dir)
            test_acquisition_memory(tmp, out_dir)
            test_discovery_duel(tmp, out_dir)
            test_discovery_duel_rounds(tmp, out_dir)
        test_graded_verdict_schema()
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
