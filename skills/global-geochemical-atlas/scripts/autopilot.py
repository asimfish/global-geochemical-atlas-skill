"""Single-command conductor for constrained or automated executors.

A weak executor cannot be trusted to follow a long document. This entry point
turns the whole SKILL contract into one deterministic command:

    python scripts/autopilot.py --prompt-file TASK_PROMPT.txt --output-dir OUT

and, when the run stops with a repair queue, exactly one follow-up command:

    python scripts/autopilot.py --output-dir OUT --continue

Responsibilities the executor no longer has to remember:

- freeze the natural-language prompt into a schema-valid request with an
  auditable extraction report (``freeze_report.json``);
- route the task through ``task_router.py`` so the external deadline enters
  the command plan;
- invoke the self-correction loop when an hour-scale budget is authorized;
- run every validator, the render gate, and the adversarial audit;
- emit ``executor_compliance_report.json`` with the exact facts the final
  chat answer must copy (``final_answer_facts``) and every detected
  compliance violation.

The conductor never invents data: it only sequences the documented stage
entry points and fails closed with a structured state when frozen inputs are
ambiguous. Machine-readable terminal states on stdout:

    AUTOPILOT_STATE=DONE | CONTINUE_REQUIRED | NEEDS_HUMAN_REVIEW | FAILED
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import execution_budget  # noqa: E402

AUTOPILOT_VERSION = "atlas-autopilot-v1"
PYTHON = sys.executable or "python3"

ELEMENT_SYMBOLS = {
    "Ag",
    "Al",
    "As",
    "Au",
    "B",
    "Ba",
    "Be",
    "Bi",
    "Ca",
    "Cd",
    "Ce",
    "Co",
    "Cr",
    "Cs",
    "Cu",
    "Fe",
    "Ga",
    "Ge",
    "Hf",
    "Hg",
    "In",
    "K",
    "La",
    "Li",
    "Mg",
    "Mn",
    "Mo",
    "Na",
    "Nb",
    "Ni",
    "P",
    "Pb",
    "Rb",
    "S",
    "Sb",
    "Sc",
    "Se",
    "Sn",
    "Sr",
    "Ta",
    "Te",
    "Th",
    "Ti",
    "Tl",
    "U",
    "V",
    "W",
    "Y",
    "Yb",
    "Zn",
    "Zr",
}
# CJK keywords are spelled as unicode escapes to keep this file ASCII-safe.
MEDIA_KEYWORDS = (
    ("rock", ("\u5ca9\u77f3", "rock")),
    ("soil", ("\u571f\u58e4", "soil")),
    ("sediment", ("\u6c89\u79ef\u7269", "sediment")),
    ("water", ("\u6c34\u4f53", "\u6c34\u6837", "water")),
)
GLOBAL_KEYWORDS = (
    "\u5168\u7403",
    "\u5168\u4e16\u754c",
    "\u4e16\u754c",
    "global",
    "worldwide",
)
BREADTH_KEYWORDS = (
    "\u5168\u7403",
    "\u5168\u56fd",
    "\u5c3d\u91cf\u5168\u9762",
    "\u5c3d\u53ef\u80fd\u5168\u9762",
    "maximize",
    "\u5168\u90e8\u533a\u57df",
)
CHINA_KEYWORDS = ("\u4e2d\u56fd", "china", "chn")


class FreezeError(RuntimeError):
    """Raised when the prompt cannot be frozen without human input."""


def _match_spans(text: str, keywords: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [kw for kw in keywords if kw.lower() in lowered]


def freeze_prompt(prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Deterministically freeze a task prompt into a request object."""

    report: dict[str, Any] = {"freeze_version": AUTOPILOT_VERSION, "matches": {}}

    tokens = set(re.findall(r"\b([A-Z][a-z]?)\b", prompt))
    elements = sorted(tokens & ELEMENT_SYMBOLS)
    report["matches"]["elements"] = elements
    if not elements:
        raise FreezeError(
            "no element symbols found in prompt; ask the user for elements"
        )

    media = [key for key, keywords in MEDIA_KEYWORDS if _match_spans(prompt, keywords)]
    report["matches"]["media"] = media
    if not media:
        raise FreezeError("no media keywords found in prompt; ask the user for media")

    region: Any = None
    bbox_match = re.search(
        r"(-?\\d{1,3}(?:\\.\\d+)?)\\s*[\\u2013\\-~]\\s*(-?\\d{1,3}(?:\\.\\d+)?)"
        r"\\s*\\u00b0?\\s*E[,\\uff0c]\\s*"
        r"(-?\\d{1,2}(?:\\.\\d+)?)\\s*[\\u2013\\-~]\\s*(-?\\d{1,2}(?:\\.\\d+)?)"
        r"\\s*\\u00b0?\\s*N",
        prompt,
    )
    if _match_spans(prompt, GLOBAL_KEYWORDS):
        region = "global"
    elif _match_spans(prompt, CHINA_KEYWORDS):
        region = "China"
    elif bbox_match:
        west, east, south, north = (float(bbox_match.group(i)) for i in (1, 2, 3, 4))
        region = {"bbox": [west, south, east, north]}
    report["matches"]["region"] = region
    if region is None:
        raise FreezeError("no region found in prompt; ask the user for the region")

    # "at least N" style floors: a number followed by a CJK measure word
    # (ge/zhong/lei) whose context window names elements or media and carries
    # an explicit floor marker (zhishao "at least" or zhongde "out of").
    minimum_elements = None
    minimum_media = None
    fullwidth = str.maketrans(
        "\uff10\uff11\uff12\uff13\uff14\uff15\uff16\uff17\uff18\uff19", "0123456789"
    )
    for match in re.finditer(r"([0-9\uff10-\uff19]+)\s*([\u4e2a\u79cd\u7c7b])", prompt):
        window = prompt[max(0, match.start() - 30) : match.end() + 10]
        if "\u81f3\u5c11" not in window and "\u4e2d\u7684" not in window:
            continue
        count = int(match.group(1).translate(fullwidth))
        measure = match.group(2)
        if "\u4ecb\u8d28" in window or measure == "\u7c7b":
            minimum_media = count
        elif "\u5143\u7d20" in window or measure in ("\u4e2a", "\u79cd"):
            minimum_elements = count
    lowered = prompt.lower()
    english_elements = re.search(r"at least\s+(\d+)\s+elements?", lowered)
    english_media = re.search(r"at least\s+(\d+)\s+(?:media|medium)", lowered)
    if english_elements:
        minimum_elements = int(english_elements.group(1))
    if english_media:
        minimum_media = int(english_media.group(1))
    report["matches"]["minimum_elements"] = minimum_elements
    report["matches"]["minimum_media"] = minimum_media

    breadth = bool(_match_spans(prompt, BREADTH_KEYWORDS)) or region == "global"
    coverage_mode = "maximize_evidence_breadth" if breadth else "fixed"

    # "finish within N minutes/hours" markers (fenzhong-nei / xiaoshi).
    deadline_seconds: float | None = None
    minute_match = re.search(
        r"([0-9\uff10-\uff19]+)\s*\u5206\u949f\u5185", prompt
    ) or re.search(r"within\s+(\d+)\s+minutes?", lowered)
    hour_match = re.search(
        r"([0-9\uff10-\uff19]+)\s*\u5c0f\u65f6", prompt
    ) or re.search(r"within\s+(\d+)\s+hours?", lowered)
    if minute_match:
        deadline_seconds = float(minute_match.group(1).translate(fullwidth)) * 60.0
    elif hour_match:
        deadline_seconds = float(hour_match.group(1).translate(fullwidth)) * 3600.0
    report["matches"]["deadline_seconds"] = deadline_seconds

    request = {
        "elements": elements,
        "region": region,
        "media": media,
        "coverage_mode": coverage_mode,
        "minimum_elements": minimum_elements,
        "minimum_media": minimum_media,
        "sources": "auto",
        "target_crs": "EPSG:4326",
        "license_policy": "open_only",
        "research_use_policy": "permitted_research",
        "minimum_evidence_tier": "D",
        "minimum_use_mode": "normalized_analysis",
        "max_records": 200000
        if coverage_mode == "maximize_evidence_breadth"
        else 50000,
        "offline": False,
    }
    report["frozen_request"] = request
    return request, report


def run_step(
    name: str,
    argv: list[str],
    steps: list[dict[str, Any]],
    *,
    required: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str] | None:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code: int | None = completed.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        completed = None
        exit_code = None
        timed_out = True
    steps.append(
        {
            "step": name,
            "argv": argv,
            "required": required,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    )
    return completed


def load_json(path: Path) -> Any:
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def collect_final_answer_facts(output_dir: Path, audit_dir: Path) -> dict[str, Any]:
    """Extract the numbers the final chat answer must copy verbatim."""

    facts: dict[str, Any] = {}
    run_summary = load_json(output_dir / "run_summary.json") or {}
    facts["status"] = run_summary.get("status")
    metrics = run_summary.get("metrics") or {}
    facts["metrics"] = metrics
    coverage = run_summary.get("coverage") or {}
    facts["coverage"] = coverage
    facts["limitations"] = run_summary.get("limitations")
    sc = load_json(output_dir / "sources_and_confidence.json") or {}
    facts["overall_workflow_confidence"] = sc.get("overall_workflow_confidence")
    facts["overall_dimension_band_counts"] = sc.get("overall_dimension_band_counts")
    portfolio = sc.get("source_portfolio")
    if isinstance(portfolio, dict):
        facts["source_portfolio"] = {
            key: portfolio.get(key)
            for key in ("candidate_count", "routed_count", "adopted_count")
            if key in portfolio
        }
    loop_report = load_json(output_dir / "loop_report.json")
    if isinstance(loop_report, dict):
        facts["loop"] = {
            "rounds": loop_report.get("round_count")
            or loop_report.get("rounds_completed"),
            "stop_reason": loop_report.get("stop_reason"),
        }
    queue = load_json(output_dir / "d1_repair_queue.json")
    if isinstance(queue, dict):
        facts["repair_queue"] = {
            "status": queue.get("status"),
            "task_count": queue.get("task_count"),
            "unattempted_action_group_count": queue.get(
                "unattempted_action_group_count"
            ),
            "operator_continuation_required": queue.get(
                "operator_continuation_required"
            ),
        }
    ledger = load_json(audit_dir / "claim_ledger.json")
    if isinstance(ledger, dict):
        facts["claims"] = {
            "ledger": str(audit_dir / "claim_ledger.json"),
            "summary": ledger.get("summary"),
            "scoped_claims": [
                {"claim_id": c.get("claim_id"), "scope": c.get("scope")}
                for c in ledger.get("claims", [])
                if c.get("integrity") == "warn_scope"
            ],
        }
    audit = load_json(audit_dir / "audit_receipt.json")
    if isinstance(audit, dict) and audit.get("scope_notes"):
        facts["required_scope_notes"] = audit["scope_notes"]
    facts["instruction"] = (
        "copy these numbers verbatim into the final reply; do not restate from "
        "memory. Scoped claims may only be quoted together with their scope "
        "sentence. Before sending, cross-check the draft with "
        "claim_ledger.py --check-answer."
    )
    return facts


def evaluate_compliance(
    steps: list[dict[str, Any]],
    output_dir: Path,
    audit_dir: Path,
    *,
    loop_authorized: bool,
    loop_invoked: bool,
) -> tuple[list[str], dict[str, Any]]:
    violations: list[str] = []
    for step in steps:
        if step["required"] and step["exit_code"] not in (0, 1):
            if step["timed_out"]:
                violations.append(f"required step timed out: {step['step']}")
            elif step["exit_code"] not in (0,):
                violations.append(
                    f"required step failed: {step['step']} (exit {step['exit_code']})"
                )
    if loop_authorized and not loop_invoked:
        violations.append(
            "hour-scale budget authorized but self-correction loop was not invoked"
        )
    queue = load_json(output_dir / "d1_repair_queue.json")
    if (
        isinstance(queue, dict)
        and queue.get("operator_continuation_required")
        and queue.get("unattempted_action_group_count", 0) > 0
    ):
        violations.append(
            "repair queue has unattempted action groups; the run must be continued, "
            "not summarized as finished"
        )
    ledger = load_json(audit_dir / "claim_ledger.json")
    if isinstance(ledger, dict):
        unsupported = (ledger.get("summary") or {}).get("fail_unsupported", 0)
        if unsupported:
            violations.append(
                f"claim ledger has {unsupported} unsupported claim(s); "
                "the affected numbers must not appear in the final answer"
            )
    else:
        violations.append("claim ledger missing")
    audit = load_json(audit_dir / "audit_receipt.json")
    audit_summary: dict[str, Any] = {}
    if isinstance(audit, dict):
        audit_summary = {
            "verdict": audit.get("verdict"),
            "error_count": audit.get("error_count"),
            "warning_count": audit.get("warning_count"),
            "scope_notes": audit.get("scope_notes"),
            "calibration_recall": (audit.get("calibration") or {}).get("recall"),
        }
        # pass_scope_narrowed is a pass whose claims must carry scope notes;
        # the notes travel via final_answer_facts.required_scope_notes.
        if audit.get("verdict") not in ("pass", "pass_scope_narrowed"):
            violations.append(f"adversarial audit verdict: {audit.get('verdict')}")
    else:
        violations.append("adversarial audit receipt missing")
    return violations, audit_summary


def determine_state(violations: list[str], output_dir: Path) -> str:
    queue = load_json(output_dir / "d1_repair_queue.json")
    if isinstance(queue, dict) and queue.get("operator_continuation_required"):
        classes = queue.get("execution_class_counts") or {}
        continuable = (
            classes.get("controller_rerun_current_skill", 0)
            + classes.get("data_action_current_skill", 0)
            + classes.get("evidence_audit_current_skill", 0)
        )
        if continuable > 0:
            return "CONTINUE_REQUIRED"
        if classes.get("skill_maintenance_new_run", 0) > 0:
            return "NEEDS_HUMAN_REVIEW"
    hard = [v for v in violations if "audit" in v or "failed" in v or "timed out" in v]
    if hard:
        return "FAILED"
    if violations:
        return "NEEDS_HUMAN_REVIEW"
    return "DONE"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/data"))
    parser.add_argument("--deadline-seconds", type=float, default=None)
    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=None,
        help="explicit hour-scale authorization; enables the self-correction loop",
    )
    parser.add_argument("--demo", help="fixture demo id for offline regression runs")
    parser.add_argument("--input", type=Path, help="existing measurements CSV")
    parser.add_argument("--analysis-profile", default="production")
    parser.add_argument(
        "--continue",
        dest="continue_run",
        action="store_true",
        help="consume the repair queue of an existing output directory",
    )
    parser.add_argument("--skip-audit", action="store_true")
    parser.add_argument("--audit-seed", type=int, default=20260817)
    parser.add_argument(
        "--memory-file",
        type=Path,
        default=None,
        help=(
            "cross-run acquisition memory JSON; proven sources seed round-1 "
            "priorities and this run's outcomes are harvested back afterwards"
        ),
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    audit_dir = output_dir.parent / (output_dir.name + "_audit")
    control_dir = output_dir.parent / (output_dir.name + "_autopilot")
    control_dir.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Freeze the request
    # ------------------------------------------------------------------
    request_path = control_dir / "REQUEST.json"
    prompt_deadline: float | None = None
    if args.continue_run:
        if not request_path.is_file():
            print("AUTOPILOT_STATE=FAILED")
            print(
                json.dumps({"error": "continue requested but no frozen request found"})
            )
            return 2
    elif args.request:
        request_path = args.request.resolve()
    elif args.prompt_file:
        prompt = args.prompt_file.read_text(encoding="utf-8")
        try:
            request, freeze_report = freeze_prompt(prompt)
        except FreezeError as exc:
            (control_dir / "freeze_report.json").write_text(
                json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print("AUTOPILOT_STATE=NEEDS_HUMAN_REVIEW")
            print(json.dumps({"needs_human_review": str(exc)}, ensure_ascii=False))
            return 4
        prompt_deadline = freeze_report["matches"].get("deadline_seconds")
        request_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (control_dir / "freeze_report.json").write_text(
            json.dumps(freeze_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        parser.error("one of --prompt-file, --request or --continue is required")

    deadline = (
        args.deadline_seconds
        or prompt_deadline
        or (execution_budget.OFFICIAL_TASK_LIMIT_SECONDS)
    )
    loop_authorized = (
        bool(args.time_budget_seconds and args.time_budget_seconds > deadline)
        or deadline > 2 * execution_budget.OFFICIAL_TASK_LIMIT_SECONDS
    )
    loop_budget = args.time_budget_seconds or (
        deadline
        if deadline > 2 * execution_budget.OFFICIAL_TASK_LIMIT_SECONDS
        else None
    )
    loop_invoked = False

    # ------------------------------------------------------------------
    # Cross-run acquisition memory: consult before running
    # ------------------------------------------------------------------
    memory_advice: dict[str, Any] | None = None
    if args.memory_file is not None and args.memory_file.is_file():
        advice_path = control_dir / "memory_advice.json"
        run_step(
            "memory_advise",
            [
                PYTHON,
                str(SCRIPT_DIR / "acquisition_memory.py"),
                "advise",
                "--memory-file",
                str(args.memory_file.resolve()),
                "--request",
                str(request_path),
                "--output",
                str(advice_path),
            ],
            steps,
            required=False,
        )
        memory_advice = load_json(advice_path)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    if args.demo:
        run_step(
            "fixture_demo_run",
            [
                PYTHON,
                str(SCRIPT_DIR / "run_atlas_request.py"),
                "--request",
                str(request_path),
                "--demo",
                args.demo,
                "--analysis-profile",
                args.analysis_profile,
                "--generated-at",
                "2026-08-17T00:00:00Z",
                "--output-dir",
                str(output_dir),
            ],
            steps,
        )
    elif loop_authorized or args.continue_run:
        loop_argv = [
            PYTHON,
            str(SCRIPT_DIR / "run_self_correction_loop.py"),
            "--request",
            str(request_path),
            "--online-source",
            "auto",
            "--cache-dir",
            str(args.cache_dir),
            "--analysis-profile",
            args.analysis_profile,
            "--output-dir",
            str(output_dir),
        ]
        if loop_budget:
            loop_argv.extend(["--time-budget-seconds", str(int(loop_budget))])
        if memory_advice:
            for source_id in memory_advice.get("priority_source_ids", []):
                loop_argv.extend(["--seed-priority-source-id", str(source_id)])
        run_step("self_correction_loop", loop_argv, steps)
        loop_invoked = True
    else:
        contract = {
            "contract_version": "atlas-task-contract-v1",
            "task_type": "full_atlas",
            "request": str(request_path),
            "output_dir": str(output_dir),
            "acquisition_mode": "provided_input" if args.input else "online_auto",
            "deadline_seconds": float(deadline),
        }
        if args.input:
            contract["input"] = str(args.input.resolve())
        contract_path = control_dir / "TASK.json"
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        plan_path = control_dir / "TASK_PLAN.json"
        run_step(
            "task_router",
            [
                PYTHON,
                str(SCRIPT_DIR / "task_router.py"),
                "--contract",
                str(contract_path),
                "--output",
                str(plan_path),
            ],
            steps,
        )
        plan = load_json(plan_path) or {}

        def _pin_interpreter(argv: list[str]) -> list[str]:
            # The plan hardcodes "python3"; run it with the interpreter that
            # started autopilot so version drift cannot change behaviour.
            if argv and Path(argv[0]).name in ("python", "python3"):
                return [PYTHON, *argv[1:]]
            return list(argv)

        for index, argv in enumerate(plan.get("commands", [])):
            run_step(f"plan_command_{index}", _pin_interpreter(list(argv)), steps)
        for index, argv in enumerate(plan.get("validators", [])):
            run_step(f"plan_validator_{index}", _pin_interpreter(list(argv)), steps)

    # ------------------------------------------------------------------
    # Validate + audit
    # ------------------------------------------------------------------
    run_step(
        "validate_outputs",
        [
            PYTHON,
            str(SCRIPT_DIR / "validate_outputs.py"),
            "--output-dir",
            str(output_dir),
        ],
        steps,
    )
    map_path = output_dir / "interactive_map.html"
    if map_path.is_file():
        run_step(
            "render_gate",
            [
                PYTHON,
                str(SCRIPT_DIR / "validate_visualization.py"),
                "--html",
                str(map_path),
            ],
            steps,
            required=False,
        )
    if not args.skip_audit:
        run_step(
            "adversarial_audit",
            [
                PYTHON,
                str(SCRIPT_DIR / "adversarial_audit.py"),
                "--output-dir",
                str(output_dir),
                "--audit-dir",
                str(audit_dir),
                "--seed",
                str(args.audit_seed),
            ],
            steps,
        )
    # Result-to-claim ledger: bind every reportable number to evidence so the
    # final answer can be cross-checked instead of trusted.
    run_step(
        "claim_ledger",
        [
            PYTHON,
            str(SCRIPT_DIR / "claim_ledger.py"),
            "--run-dir",
            str(output_dir),
            "--ledger",
            str(audit_dir / "claim_ledger.json"),
        ],
        steps,
    )
    # Harvest this run's source outcomes back into cross-run memory.
    if args.memory_file is not None:
        run_step(
            "memory_update",
            [
                PYTHON,
                str(SCRIPT_DIR / "acquisition_memory.py"),
                "update",
                "--memory-file",
                str(args.memory_file.resolve()),
                "--run-dir",
                str(output_dir),
            ],
            steps,
            required=False,
        )

    # ------------------------------------------------------------------
    # Compliance report
    # ------------------------------------------------------------------
    violations, audit_summary = evaluate_compliance(
        steps,
        output_dir,
        audit_dir,
        loop_authorized=loop_authorized or args.continue_run,
        loop_invoked=loop_invoked,
    )
    if args.skip_audit:
        violations = [v for v in violations if "audit receipt missing" not in v]
    state = determine_state(violations, output_dir)
    report = {
        "autopilot_version": AUTOPILOT_VERSION,
        "state": state,
        "request": str(request_path),
        "output_dir": str(output_dir),
        "deadline_seconds": deadline,
        "loop": {
            "authorized": loop_authorized,
            "invoked": loop_invoked,
            "budget_seconds": loop_budget,
        },
        "steps": steps,
        "violations": violations,
        "audit": audit_summary,
        "memory": memory_advice,
        "final_answer_facts": collect_final_answer_facts(output_dir, audit_dir),
        "next_command": (
            f"{PYTHON} scripts/autopilot.py --output-dir {output_dir} --continue"
            if state == "CONTINUE_REQUIRED"
            else None
        ),
    }
    (control_dir / "executor_compliance_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"AUTOPILOT_STATE={state}")
    print(
        json.dumps(
            {
                "state": state,
                "violations": violations,
                "audit": audit_summary,
                "compliance_report": str(
                    control_dir / "executor_compliance_report.json"
                ),
                "next_command": report["next_command"],
            },
            ensure_ascii=False,
        )
    )
    return {"DONE": 0, "CONTINUE_REQUIRED": 10, "NEEDS_HUMAN_REVIEW": 4}.get(state, 2)


if __name__ == "__main__":
    raise SystemExit(main())
