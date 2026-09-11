#!/usr/bin/env python3
"""Generate world and China acceptance evidence for every public pitch promise."""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "global-geochemical-atlas"
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import agent_audit  # noqa: E402
import auto_research  # noqa: E402
import claim_ledger  # noqa: E402
import serve_atlas_research  # noqa: E402
import validate_outputs  # noqa: E402

CASES = {
    "world": {
        "demo": "four-media",
        "fixture": SKILL / "fixtures" / "four-media" / "combined-v3",
        "coordinate_mode": "auto",
        "question": (
            "Which comparable copper cohorts in the frozen world atlas support a "
            "reproducible regional pilot without crossing medium or method boundaries?"
        ),
    },
    "china": {
        "demo": "china",
        "fixture": SKILL / "fixtures" / "china" / "combined-v1",
        "coordinate_mode": "reported",
        "question": (
            "Which method-stratified Cu patterns in the frozen China atlas are suitable "
            "for a pilot while retaining the reported-coordinate datum warning?"
        ),
    },
}


class AcceptanceError(RuntimeError):
    """Raised when an observable pitch acceptance condition fails."""


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
        raise AcceptanceError(f"expected a JSON object: {path}")
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
        raise AcceptanceError(
            f"command returned {completed.returncode}, expected {sorted(expected_codes)}: "
            + " ".join(command)
        )
    return completed


def require(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise AcceptanceError(message)
    checks.append(message)


def source_fact(atlas_dir: Path) -> dict[str, Any]:
    report = read_json(atlas_dir / "sources_and_confidence.json")
    sources = report.get("sources")
    if not isinstance(sources, list) or not sources:
        raise AcceptanceError("sources_and_confidence.json has no source portfolio")
    eligible = [
        item
        for item in sources
        if isinstance(item, dict)
        and item.get("official_links")
        and item.get("dataset_versions")
        and item.get("licenses")
        and item.get("record_provenance", {}).get("file_hashes")
    ]
    if not eligible:
        raise AcceptanceError("no source has the governed facts needed by the audit")
    selected = sorted(eligible, key=lambda item: str(item.get("source_id")))[0]
    official = selected["official_links"][0]["url"]
    locator = (
        "sources_and_confidence.json#$.sources[?(@.source_id=='"
        + str(selected["source_id"])
        + "')]"
    )
    dimensions = {
        "official_identity": True,
        "machine_access": bool(selected.get("source_urls")),
        "research_use_license": all(
            str(item).casefold() not in {"unresolved", "unknown"}
            for item in selected.get("licenses", [])
        ),
        "version_and_integrity": True,
        "region_relevance": True,
        "medium_relevance": bool(selected.get("medium_record_counts")),
        "record_locator": (
            selected.get("record_provenance", {}).get("located_record_count", 0) > 0
        ),
    }
    return {
        "source_id": selected["source_id"],
        "title": (selected.get("dataset_titles") or [selected["source_id"]])[0],
        "official_url": official,
        "dimensions": dimensions,
        "evidence_locators": {key: locator for key in dimensions},
    }


def build_adversarial_evidence(
    case_dir: Path, atlas_dir: Path, checks: list[str]
) -> dict[str, Any]:
    audit_root = case_dir / "evidence" / "adversarial-audit"
    fact = source_fact(atlas_dir)
    gap = {
        "scope": case_dir.name,
        "elements": read_json(atlas_dir / "run_summary.json")
        .get("request", {})
        .get("elements", []),
        "purpose": "protocol acceptance for a current-round governed source candidate",
    }
    selection_a = agent_audit.prepare_audit_round(
        audit_root / "memory-a",
        round_id=f"{case_dir.name}-protocol-round",
        gap=gap,
        source_facts=[fact],
        prior_memory={"previous_verdict": "supplement", "round": 1},
    )
    selection_b = agent_audit.prepare_audit_round(
        audit_root / "memory-b",
        round_id=f"{case_dir.name}-protocol-round",
        gap=gap,
        source_facts=[fact],
        prior_memory={"previous_verdict": "reject", "round": 99},
    )
    require(
        selection_a["prior_memory_sha256"] != selection_b["prior_memory_sha256"]
        and selection_a["role_packet_sha256"] == selection_b["role_packet_sha256"],
        "changed prior memory leaves current scout/challenger packet hashes unchanged",
        checks,
    )
    active = audit_root / "memory-a"
    scout = agent_audit.create_result_envelope(
        active,
        role="scout",
        invocation_id=f"{case_dir.name}-harness-scout-fresh",
        model_family="protocol-harness-family-a",
        payload={
            "candidate_ids": [fact["source_id"]],
            "evidence_requests": [],
            "test_harness": True,
        },
    )
    challenger = agent_audit.create_result_envelope(
        active,
        role="challenger",
        invocation_id=f"{case_dir.name}-harness-challenger-fresh",
        model_family="protocol-harness-family-b",
        payload={
            "challenges": [],
            "unresolved_dimensions": [],
            "test_harness": True,
        },
    )
    judge = agent_audit.deterministic_judge(active)
    require(
        scout["packet_sha256"] != challenger["packet_sha256"]
        and scout["invocation_id"] != challenger["invocation_id"]
        and judge["cross_model_status"] == "cross_family"
        and all(item["admitted"] is False for item in judge["decisions"]),
        "scout, challenger and deterministic judge remain separate and cannot self-admit",
        checks,
    )

    scout_packet = read_json(active / "roles" / "scout" / "input" / "packet.json")
    try:
        agent_audit.validate_packet(scout_packet, expected_role="challenger")
    except agent_audit.AgentAuditError:
        role_substitution_blocked = True
    else:
        role_substitution_blocked = False
    tampered = json.loads(json.dumps(scout))
    tampered["payload"]["candidate_ids"] = []
    try:
        agent_audit.validate_result_envelope(
            tampered, scout_packet, expected_role="scout"
        )
    except agent_audit.AgentAuditError:
        tamper_blocked = True
    else:
        tamper_blocked = False

    reuse_dir = audit_root / "invocation-reuse-negative"
    agent_audit.prepare_audit_round(
        reuse_dir,
        round_id=f"{case_dir.name}-reuse-negative",
        gap=gap,
        source_facts=[fact],
    )
    agent_audit.create_result_envelope(
        reuse_dir,
        role="scout",
        invocation_id=f"{case_dir.name}-shared-invocation",
        model_family="protocol-harness-family-a",
        payload={"candidate_ids": [fact["source_id"]], "evidence_requests": []},
    )
    try:
        agent_audit.create_result_envelope(
            reuse_dir,
            role="challenger",
            invocation_id=f"{case_dir.name}-shared-invocation",
            model_family="protocol-harness-family-b",
            payload={"challenges": [], "unresolved_dimensions": []},
        )
    except agent_audit.AgentAuditError:
        invocation_reuse_blocked = True
    else:
        invocation_reuse_blocked = False
    require(
        role_substitution_blocked and tamper_blocked and invocation_reuse_blocked,
        "wrong role, changed result bytes and reused invocation IDs fail closed",
        checks,
    )
    proof = {
        "schema_version": "gga-pitch-agent-isolation-proof-v1",
        "protocol_payloads_are_test_harness_only": True,
        "production_host_must_start_fresh_sessions": True,
        "memory_a_sha256": selection_a["prior_memory_sha256"],
        "memory_b_sha256": selection_b["prior_memory_sha256"],
        "role_packet_sha256": selection_a["role_packet_sha256"],
        "scout_result_sha256": scout["result_sha256"],
        "challenger_result_sha256": challenger["result_sha256"],
        "judge_receipt_sha256": judge["judge_receipt_sha256"],
        "negative_tests": {
            "role_substitution_blocked": role_substitution_blocked,
            "tampered_result_blocked": tamper_blocked,
            "invocation_reuse_blocked": invocation_reuse_blocked,
        },
    }
    write_json(audit_root / "isolation-proof.json", proof)
    return proof


def start_auto_research(
    case_dir: Path, atlas_dir: Path, question: str, checks: list[str]
) -> dict[str, Any]:
    request = {
        "question": question,
        "output_language": "zh-CN",
        "target_venue": "Applied Geochemistry",
    }
    request_path = case_dir / "auto-research-request.json"
    write_json(request_path, request)
    research_root = case_dir / "auto-research-runs"
    state = auto_research.start_research(atlas_dir, research_root, request)
    run_dir = research_root / state["run_id"]
    required = {
        "atlas_snapshot.json",
        "five-paper-program.json",
        "pilot_contract.json",
        "literature_queue.json",
        "paper_spine.json",
        "figure_contract.json",
        "state.json",
    }
    require(
        state["status"] == "awaiting_agents"
        and state["stage"] == "pilot_and_literature"
        and state["publication_allowed"] is False
        and all((run_dir / name).is_file() for name in required)
        and (run_dir / "agents" / "pilot_analyst" / "packet.json").is_file()
        and (run_dir / "agents" / "literature_researcher" / "packet.json").is_file(),
        "Auto-Research starts from the frozen atlas and materializes real resumable contracts",
        checks,
    )

    token = f"pitch-test-{case_dir.name}-token"
    server = serve_atlas_research.AtlasResearchServer(
        ("127.0.0.1", 0), atlas_dir, research_root, token
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = int(server.server_address[1])
    body = json.dumps(request).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "X-GGA-Research-Token": token,
        "X-GGA-Request-Nonce": f"pitch-{case_dir.name}-nonce-0001",
    }
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connection.request("POST", "/api/v1/research-runs", body=body, headers=headers)
        response = connection.getresponse()
        response_body = json.loads(response.read().decode("utf-8"))
        response_status = response.status
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)
    require(
        response_status == 201 and response_body["run_id"] == state["run_id"],
        "the atlas Auto-Research request crosses the real loopback controller API",
        checks,
    )
    api_proof = {
        "http_status": response_status,
        "response": response_body,
        "controller_stopped_after_smoke_test": True,
    }
    write_json(case_dir / "evidence" / "localhost-api.json", api_proof)
    return {"state": state, "run_dir": run_dir.relative_to(case_dir).as_posix()}


def capture_screenshot(
    case_dir: Path, atlas_dir: Path, checks: list[str]
) -> dict[str, Any]:
    browser = shutil.which("google-chrome") or shutil.which("chromium")
    if browser is None:
        raise AcceptanceError(
            "no Chrome/Chromium executable is available for screenshots"
        )
    screenshot = case_dir / "screenshots" / "atlas-overview.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    command = [
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
    ]
    run_command(
        command,
        log_path=case_dir / "logs" / "browser-screenshot.json",
        timeout=60,
    )
    require(
        screenshot.is_file() and screenshot.stat().st_size > 20_000,
        "a real headless browser paints the atlas overview screenshot",
        checks,
    )
    return {
        "path": screenshot.relative_to(case_dir).as_posix(),
        "sha256": sha256_file(screenshot),
        "bytes": screenshot.stat().st_size,
    }


def verify_temporal_embedding(atlas_dir: Path, checks: list[str]) -> dict[str, Any]:
    html = (atlas_dir / "interactive_map.html").read_text(encoding="utf-8")
    temporal = (atlas_dir / "temporal_map.html").read_bytes()
    match = re.search(
        r'<script id="temporal-document" type="application/octet-stream">([^<]+)</script>',
        html,
    )
    navigation = re.search(r'<nav class="tabs".*?</nav>', html, re.DOTALL)
    embedded = base64.b64decode(match.group(1), validate=True) if match else b""
    require(
        'id="temporalView"' in html
        and 'id="autoResearchView"' in html
        and 'id="temporalFrame"' in html
        and "srcdoc" in html
        and '<iframe id="temporalFrame"' in html
        and embedded == temporal
        and navigation is not None
        and not re.search(
            r'<a\b[^>]*href="temporal_map\.html"', navigation.group(0), re.I
        ),
        "the exact temporal app is a top-level in-atlas view, not primary external navigation",
        checks,
    )
    return {
        "embedded_temporal_sha256": hashlib.sha256(embedded).hexdigest(),
        "compatibility_temporal_sha256": hashlib.sha256(temporal).hexdigest(),
        "exact_bytes": embedded == temporal,
        "auto_research_view_present": 'id="autoResearchView"' in html,
    }


def artifact_manifest(atlas_dir: Path) -> dict[str, Any]:
    artifacts = {
        filename: {
            "sha256": sha256_file(atlas_dir / filename),
            "bytes": (atlas_dir / filename).stat().st_size,
        }
        for filename in validate_outputs.REQUIRED_FILES.values()
    }
    body = {
        "schema_version": "gga-pitch-artifact-manifest-v1",
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    return {
        **body,
        "manifest_sha256": hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }


def run_case(name: str, config: dict[str, Any], root: Path) -> dict[str, Any]:
    case_dir = root / name
    case_dir.mkdir()
    atlas_dir = case_dir / "atlas"
    checks: list[str] = []
    loop_command = [
        sys.executable,
        str(SCRIPTS / "run_self_correction_loop.py"),
        "--request",
        str(config["fixture"] / "request.json"),
        "--output-dir",
        str(atlas_dir),
        "--demo",
        config["demo"],
        "--coordinate-mode",
        config["coordinate_mode"],
        "--analysis-profile",
        "production",
        "--generated-at",
        "2026-08-24T00:00:00Z",
        "--max-rounds",
        "2",
        "--time-budget-seconds",
        "1800",
        "--round-timeout-seconds",
        "300",
        "--run-timeout-seconds",
        "240",
        "--source-timeout-seconds",
        "60",
    ]
    run_command(
        loop_command,
        log_path=case_dir / "logs" / "loop-round-01.json",
        expected_codes={0, 1},
    )
    run_command(
        loop_command,
        log_path=case_dir / "logs" / "loop-resume-round-02.json",
        expected_codes={0, 1},
    )
    validation = run_command(
        [
            sys.executable,
            str(SCRIPTS / "validate_outputs.py"),
            "--output-dir",
            str(atlas_dir),
        ],
        log_path=case_dir / "logs" / "validate-outputs.json",
    )
    validation_report = json.loads(validation.stdout)
    require(
        validation_report["status"] == "valid",
        "all eighteen atlas artifacts pass the public output validator",
        checks,
    )
    loop_report = read_json(atlas_dir / "loop_report.json")
    queue = read_json(atlas_dir / "d1_repair_queue.json")
    receipt = read_json(atlas_dir / "research_delivery_receipt.json")
    require(
        len(loop_report.get("rounds", [])) == 2
        and (atlas_dir / "rounds" / "round-01").is_dir()
        and (atlas_dir / "rounds" / "round-02").is_dir()
        and queue.get("action_group_count", 0) > 0
        and receipt.get("delivery_ready") is False,
        "Loop preserves two immutable attempts, emits grouped repairs and refuses a false complete delivery",
        checks,
    )
    ledger = claim_ledger.build_claim_ledger(atlas_dir)
    require(
        claim_ledger.validate_claim_ledger(atlas_dir, ledger) == []
        and ledger["claim_count"] == 9,
        "nine report claims recompute and bind one-to-one to exact artifact SHA-256 values",
        checks,
    )
    write_json(case_dir / "evidence" / "claim-ledger.json", ledger)
    manifest = artifact_manifest(atlas_dir)
    require(
        manifest["artifact_count"] == 18,
        "the case records a content-addressed manifest for all eighteen core files",
        checks,
    )
    write_json(case_dir / "evidence" / "artifact-manifest.json", manifest)
    agent_proof = build_adversarial_evidence(case_dir, atlas_dir, checks)
    temporal_proof = verify_temporal_embedding(atlas_dir, checks)
    auto_proof = start_auto_research(
        case_dir, atlas_dir, str(config["question"]), checks
    )
    screenshot = capture_screenshot(case_dir, atlas_dir, checks)
    result = {
        "schema_version": "gga-pitch-full-flow-case-v1",
        "status": "PASS",
        "case": name,
        "fixture": config["fixture"].relative_to(REPO).as_posix(),
        "atlas": "atlas/interactive_map.html",
        "screenshot": screenshot,
        "checks": checks,
        "loop": {
            "status": loop_report.get("status"),
            "stop_reason": loop_report.get("stop_reason"),
            "round_count": len(loop_report.get("rounds", [])),
            "published_round": loop_report.get("published_round"),
            "repair_action_group_count": queue.get("action_group_count"),
            "scientific_delivery_ready": receipt.get("delivery_ready"),
            "expected_boundary": (
                "Frozen fixtures demonstrate the complete control loop but do not satisfy "
                "formal online global/regional sufficiency."
            ),
        },
        "agent_isolation": agent_proof,
        "claim_ledger": {
            "claim_count": ledger["claim_count"],
            "ledger_sha256": ledger["ledger_sha256"],
        },
        "temporal_view": temporal_proof,
        "auto_research": auto_proof,
        "artifact_manifest_sha256": manifest["manifest_sha256"],
    }
    write_json(case_dir / "acceptance.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_root = args.output_root
    if not output_root.is_absolute():
        output_root = REPO / output_root
    if output_root.exists():
        raise SystemExit(f"refusing to overwrite existing output root: {output_root}")
    output_root.mkdir(parents=True)
    try:
        loop_self_test = run_command(
            [
                sys.executable,
                str(SCRIPTS / "run_self_correction_loop.py"),
                "--self-test",
            ],
            log_path=output_root / "shared" / "loop-self-test.json",
        )
        d3_test = run_command(
            [
                sys.executable,
                str(SCRIPTS / "component_test.py"),
                "--component",
                "d3",
            ],
            log_path=output_root / "shared" / "d3-component-test.json",
            timeout=300,
        )
        results = {
            name: run_case(name, config, output_root) for name, config in CASES.items()
        }
        report = {
            "schema_version": "gga-pitch-full-flow-acceptance-v1",
            "status": "PASS",
            "loop_protocol_self_test": json.loads(loop_self_test.stdout),
            "d3_protocol_regression": {
                key: value
                for key, value in json.loads(d3_test.stdout).items()
                if key != "components"
            },
            "cases": results,
            "human_actions": [
                "Open each atlas/interactive_map.html and inspect the map.",
                "Click 时间演变与成因归因 inside that same HTML.",
                "Start serve_atlas_research.py and submit the Auto-Research form.",
                "Use a production agent host that actually honors fresh_session_required.",
                "Do not call a fixture a formally sufficient online scientific delivery.",
            ],
        }
        write_json(output_root / "ACCEPTANCE.json", report)
    except Exception as exc:
        write_json(
            output_root / "ACCEPTANCE.json",
            {
                "schema_version": "gga-pitch-full-flow-acceptance-v1",
                "status": "FAIL",
                "error": str(exc),
            },
        )
        raise
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
