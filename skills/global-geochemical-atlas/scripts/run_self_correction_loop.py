#!/usr/bin/env python3
"""Deterministic self-correction loop controller for the atlas workflow.

The controller wraps ``run_atlas_request.py`` with an auditable
detect -> repair -> re-run -> compare loop:

- Early gates catch dead work before a full round is spent: online routing
  viability, minimum input columns, and frozen-request drift are checked
  first, and every round is classified immediately after it exits.
- After each round it harvests machine-readable issues from the execution
  receipt, ``validate_outputs.py``, ``iteration_backlog.csv`` and
  ``anomaly_report.json``, then splits them into autonomously repairable
  and manual work.
- The only autonomous repair is re-running for transient source or network
  failures. Schema, license, coordinate and method issues are routed to an
  explicit manual repair plan; censored values and other scientific limits
  are never treated as repairable defects.
- The loop stops honestly: ``converged``, ``no_autonomous_repair``,
  ``no_progress`` (two rounds with an identical actionable signature),
  round budget, time budget, or ``needs_human_review``.

Every round writes into its own ``rounds/round-NN`` directory; canonical
artifacts are never edited in place. The cumulative ``loop_report.json``
follows ``references/loop-report.schema.json``. Re-invoking the controller
on the same output directory appends rounds (agent-in-the-loop manual
repairs between invocations), refuses to continue if the frozen request
changed, and runs at most one explicit probe round when the caller resumes
after a manual-repair stop.

Exit codes: 0 success/partial_success, 1 needs_human_review, 2 failed/usage.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPORT_VERSION = "self-correction-loop-report-v1"
REPORT_FILENAME = "loop_report.json"
DEFAULT_MAX_ROUNDS = 3
MAX_ROUNDS_CAP = 20
DEFAULT_ROUND_TIMEOUT_SECONDS = 900.0
REQUIRED_INPUT_COLUMNS = ("element_or_analyte", "value", "unit", "medium")
MANUAL_PLAN_GROUP_CAP = 50

RETRYABLE_RUN_STATUSES = frozenset({"network_unavailable", "round_timeout"})
ONLINE_RETRYABLE_RUN_STATUSES = frozenset({"incomplete_retrieval"})
RETRYABLE_SOURCE_MARKERS = (
    "timeout",
    "timed out",
    "network",
    "connection",
    "unavailable",
    "temporarily",
    "budget",
    "http 5",
    "http error 5",
)
NON_RETRYABLE_SOURCE_MARKERS = (
    "source_not_accessible",
    "research use",
    "license",
    "conflicting_evidence",
    "unsupported",
    "invalid",
    "schema",
    "allocation",
)
GATE_STOP_REASONS = {
    "routing_viability": "unsupported_scope",
    "input_header": "invalid_input",
}
CLAIM_BOUNDARY = (
    "本报告只记录工程修复循环的证据与停机原因。自主修复仅限重试瞬态获取失败；"
    "scientific_limit（如删失观测）不是缺陷，不计入修复率；needs_human_review 是"
    "正常门禁结果，不是失败。任何轮次都不修改冻结请求或已生成的证据。"
)


class LoopUsageError(RuntimeError):
    """Raised for controller-level misuse that must abort before any round."""


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


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_last_json_line(text: str) -> dict[str, Any] | None:
    for raw_line in reversed(text.strip().splitlines()):
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def is_gate_round(record: dict[str, Any]) -> bool:
    return not record.get("command")


def source_failure_retryable(error: str) -> bool:
    """Classify one per-source acquisition error string.

    Conservative default: unknown errors are NOT retryable, so the loop never
    burns rounds on failures it cannot reason about, and non-retryable markers
    (license, schema, accessibility) always win over transient markers.
    """
    lowered = error.casefold()
    if any(marker in lowered for marker in NON_RETRYABLE_SOURCE_MARKERS):
        return False
    return any(marker in lowered for marker in RETRYABLE_SOURCE_MARKERS)


def run_failure_retryable(status: str | None, mode: str) -> bool:
    if status is None:
        return False
    if status in RETRYABLE_RUN_STATUSES:
        return True
    return mode == "online" and status in ONLINE_RETRYABLE_RUN_STATUSES


def read_backlog(path: Path) -> dict[str, Any]:
    """Harvest iteration_backlog.csv into status counts and manual groups."""
    status_counts: Counter[str] = Counter()
    issue_codes: Counter[str] = Counter()
    auto_recheck = 0
    manual_groups: dict[tuple[str, str], dict[str, Any]] = {}
    if not path.is_file():
        return {
            "available": False,
            "status_counts": {},
            "issue_codes": {},
            "auto_recheck": None,
            "manual_groups": [],
        }
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            status = (row.get("status") or "").strip()
            status_counts[status] += 1
            if (row.get("auto_recheck") or "").strip().casefold() == "true":
                auto_recheck += 1
            if status != "action_required":
                continue
            code = (row.get("issue_code") or "UNSPECIFIED").strip()
            issue_codes[code] += 1
            key = ((row.get("stage_owner") or "unknown").strip(), code)
            group = manual_groups.setdefault(
                key,
                {
                    "stage_owner": key[0],
                    "issue_code": key[1],
                    "count": 0,
                    "recommended_action": (row.get("recommended_action") or "").strip(),
                },
            )
            group["count"] += 1
    ordered = sorted(
        manual_groups.values(),
        key=lambda item: (-item["count"], item["stage_owner"], item["issue_code"]),
    )
    return {
        "available": True,
        "status_counts": dict(status_counts),
        "issue_codes": dict(issue_codes),
        "auto_recheck": auto_recheck,
        "manual_groups": ordered[:MANUAL_PLAN_GROUP_CAP],
    }


def read_anomaly_groups(path: Path) -> tuple[int | None, int | None, int | None]:
    if not path.is_file():
        return None, None, None
    try:
        report = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None, None, None
    groups = report.get("groups")
    if not isinstance(groups, list):
        return None, None, report.get("candidate_count")
    analyzed = sum(1 for group in groups if group.get("status") == "analyzed")
    insufficient = sum(
        1 for group in groups if str(group.get("status", "")).startswith("insufficient")
    )
    return analyzed, insufficient, report.get("candidate_count")


def actionable_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    """Stable signature used to detect a round that changed nothing."""
    fingerprints = record.get("input_fingerprints", {})
    return (
        record.get("execution_status"),
        record.get("counts", {}).get("action_required"),
        tuple(sorted(item["source_id"] for item in record.get("failed_sources", []))),
        fingerprints.get("input_sha256"),
        fingerprints.get("evidence_sha256"),
    )


def build_repair_plan(record: dict[str, Any]) -> dict[str, Any]:
    autonomous: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = list(record.get("manual_groups", []))
    retryable_ids = sorted(
        item["source_id"]
        for item in record.get("failed_sources", [])
        if item.get("retryable")
    )
    if retryable_ids:
        autonomous.append(
            {
                "action": "retry_failed_sources",
                "detail": "重试瞬态获取失败的来源；成功来源命中缓存，不重复下载。",
                "source_ids": retryable_ids,
            }
        )
    if record.get("run_failure_retryable"):
        autonomous.append(
            {
                "action": "retry_run",
                "detail": f"整轮失败状态 {record.get('execution_status')} 判定为瞬态，重试一轮。",
                "source_ids": [],
            }
        )
    for item in record.get("failed_sources", []):
        if item.get("retryable"):
            continue
        manual.append(
            {
                "stage_owner": "D1",
                "issue_code": "SOURCE_ACQUISITION_FAILED",
                "count": 1,
                "recommended_action": (
                    f"来源 {item['source_id']} 非瞬态失败（{item['error'][:160]}）；"
                    "核对来源准入、许可与接口后重跑，或从请求中移除该来源。"
                ),
            }
        )
    return {"autonomous": autonomous, "manual": manual[:MANUAL_PLAN_GROUP_CAP]}


def decide_next(
    rounds: list[dict[str, Any]],
    max_rounds: int,
    elapsed_seconds: float,
    time_budget_seconds: float | None,
) -> tuple[str, str]:
    """Return ("continue" | "stop", stop_reason). Pure function, unit-tested."""
    last = rounds[-1]
    if last.get("gate_stop_reason"):
        return "stop", str(last["gate_stop_reason"])
    execution_status = last.get("execution_status")
    run_failed = last.get("exit_code") != 0
    if run_failed and not last.get("run_failure_retryable"):
        if execution_status == "needs_human_review":
            return "stop", "needs_human_review"
        return "stop", "run_failed"
    if not run_failed and last.get("validation_status") == "invalid":
        return "stop", "contract_validation_failed"
    plan = build_repair_plan(last)
    has_autonomous = bool(plan["autonomous"])
    action_required = last.get("counts", {}).get("action_required")
    open_failures = bool(last.get("failed_sources"))
    if not run_failed and not open_failures and action_required in (0, None):
        return "stop", "converged"
    if not has_autonomous:
        return "stop", "no_autonomous_repair"
    previous = rounds[-2] if len(rounds) >= 2 else None
    if previous is not None and actionable_signature(previous) == actionable_signature(
        last
    ):
        return "stop", "no_progress"
    if len(rounds) >= max_rounds:
        return "stop", "round_budget_exhausted"
    if time_budget_seconds is not None and elapsed_seconds >= time_budget_seconds:
        return "stop", "time_budget_exhausted"
    return "continue", ""


def final_status(stop_reason: str, last: dict[str, Any] | None) -> str:
    if stop_reason == "converged" and last is not None:
        return (
            "success"
            if last.get("execution_status") == "success"
            else "partial_success"
        )
    if (
        stop_reason in ("round_budget_exhausted", "time_budget_exhausted")
        and last is not None
    ):
        if last.get("validation_status") == "valid":
            return "partial_success"
        return "needs_human_review"
    if stop_reason in ("run_failed", "invalid_input"):
        return "failed"
    return "needs_human_review"


def next_step_text(stop_reason: str, plan: dict[str, Any]) -> str:
    manual_count = sum(item.get("count", 1) for item in plan.get("manual", []))
    mapping = {
        "converged": "无 action_required 项与失败来源；按 SKILL.md 第 9 节输出最终回复。",
        "no_autonomous_repair": (
            f"存在 {manual_count} 项需证据或人工判断的问题；按 repair_plan.manual 逐组处理"
            "（补充来源证据、显式 schema map 或人工复核）后，在同一输出目录重新运行控制器追加轮次。"
        ),
        "no_progress": "连续两轮问题签名相同；停止自动重试，按 repair_plan.manual 人工介入后再续跑。",
        "round_budget_exhausted": "轮次预算用尽；如任务预算允许，提高 --max-rounds 在同一目录续跑。",
        "time_budget_exhausted": "时间预算用尽；如任务预算允许，重新调用控制器续跑。",
        "needs_human_review": "流水线返回 needs_human_review；按 run_summary.json 与失败矩阵处理后续跑。",
        "contract_validation_failed": (
            "产物违反十五文件契约；这是工程缺陷，勿盲目重试，检查 validate_outputs 输出并修复代码或输入。"
        ),
        "run_failed": "非瞬态运行失败；按 stderr 状态码与 SKILL.md 第 8 节失败矩阵处理。",
        "unsupported_scope": "路由无任何候选来源；调整请求（元素/介质/区域/许可政策）或改用 --input 提供数据。",
        "invalid_input": "输入缺少最低必需列；按 D2 契约修正输入文件后重跑。",
        "in_progress": "循环在本轮后中断；在同一输出目录重新调用控制器续跑。",
    }
    return mapping.get(
        stop_reason, "查看 loop_report.json 与最后一轮 run_summary.json。"
    )


def build_run_command(args: argparse.Namespace, round_dir: Path) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "run_atlas_request.py"),
        "--request",
        str(args.request),
        "--output-dir",
        str(round_dir),
        "--analysis-profile",
        args.analysis_profile,
    ]
    if args.mode == "input":
        command.extend(["--input", str(args.input)])
        if args.evidence_jsonl:
            command.extend(["--evidence-jsonl", str(args.evidence_jsonl)])
        if args.acquisition_manifest:
            command.extend(["--acquisition-manifest", str(args.acquisition_manifest)])
    elif args.mode == "online":
        command.extend(
            [
                "--online-source",
                args.online_source,
                "--cache-dir",
                str(args.cache_dir),
                "--acquisition-mode",
                args.acquisition_mode,
            ]
        )
    else:
        command.extend(["--demo", args.demo])
    if args.generated_at:
        command.extend(["--generated-at", args.generated_at])
    if args.batch_qc_input:
        command.extend(["--batch-qc-input", str(args.batch_qc_input)])
    if args.batch_qc_policy:
        command.extend(["--batch-qc-policy", str(args.batch_qc_policy)])
    if args.no_geology:
        command.append("--no-geology")
    if args.require_all_sources:
        command.append("--require-all-sources")
    return command


def run_pre_gates(args: argparse.Namespace, round_index: int) -> dict[str, Any] | None:
    """Run cheap viability gates before spending a full round.

    Returns a terminal gate-round record on failure, or None when execution
    may proceed. Gates are conservative: uncertainty defers to the pipeline.
    """
    if args.mode == "online":
        viable, detail = gate_routing(args.request)
        if not viable:
            return make_gate_round(
                round_index,
                args,
                "routing_viability",
                detail,
                GATE_STOP_REASONS["routing_viability"],
            )
    elif args.mode == "input":
        viable, detail = gate_input_header(args.input)
        if not viable:
            return make_gate_round(
                round_index,
                args,
                "input_header",
                detail,
                GATE_STOP_REASONS["input_header"],
            )
    return None


def gate_routing(request: Path) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        route_path = Path(tmp) / "route.json"
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "source_router.py"),
                "--request",
                str(request),
                "--output",
                str(route_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 or not route_path.is_file():
            return True, "router unavailable; deferring to the pipeline's own routing"
        try:
            route = read_json(route_path)
        except (OSError, json.JSONDecodeError):
            return True, "route result unreadable; deferring to the pipeline"
    selected = len(route.get("selected_sources") or [])
    review = len(route.get("review_sources") or [])
    if selected == 0 and review == 0:
        return (
            False,
            "router selected 0 sources and 0 review candidates for this request",
        )
    return True, f"router found {selected} selected and {review} review-tier sources"


def gate_input_header(input_path: Path) -> tuple[bool, str]:
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle), [])
    except OSError as exc:
        return False, f"input unreadable: {exc}"
    missing = [column for column in REQUIRED_INPUT_COLUMNS if column not in header]
    if missing:
        return False, f"input is missing required columns: {missing}"
    return True, "minimum D2 columns present"


def execute_round(
    args: argparse.Namespace, round_index: int, loop_root: Path
) -> dict[str, Any]:
    round_dir = loop_root / "rounds" / f"round-{round_index:02d}"
    command = build_run_command(args, round_dir)
    gate_events: list[dict[str, str]] = []
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=args.round_timeout_seconds,
            check=False,
        )
        exit_code: int | None = proc.returncode
        stdout, stderr = proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = None

        def _decode(stream: Any) -> str:
            if isinstance(stream, bytes):
                return stream.decode("utf-8", "replace")
            return stream or ""

        stdout, stderr = _decode(exc.stdout), _decode(exc.stderr)
    duration = round(time.monotonic() - started, 1)

    execution_status: str | None = None
    route_status: str | None = None
    records: int | None = None
    failed_sources: list[dict[str, Any]] = []
    if exit_code == 0:
        receipt = parse_last_json_line(stdout) or {}
        execution_status = receipt.get("status")
        route_status = receipt.get("route_status")
        records = (receipt.get("record_counts") or {}).get("after_request_filters")
        for outcome in receipt.get("source_outcomes") or []:
            if outcome.get("status") != "failed":
                continue
            error = str(outcome.get("error") or "")
            failed_sources.append(
                {
                    "source_id": str(outcome.get("source_id")),
                    "error": error,
                    "retryable": source_failure_retryable(error),
                }
            )
        gate_events.append(
            {
                "gate": "run_exit",
                "status": "pass",
                "detail": f"exit 0, status {execution_status}",
            }
        )
    elif exit_code is None:
        execution_status = "round_timeout"
        gate_events.append(
            {
                "gate": "run_exit",
                "status": "info",
                "detail": (
                    f"round killed after {args.round_timeout_seconds:.0f}s; classified retryable"
                ),
            }
        )
    else:
        failure = parse_last_json_line(stderr) or {}
        execution_status = str(failure.get("status") or "invalid_input")
        gate_events.append(
            {
                "gate": "run_exit",
                "status": "info",
                "detail": (
                    f"exit {exit_code}, status {execution_status}: "
                    f"{str(failure.get('error') or '')[:200]}"
                ),
            }
        )

    validation_status = "not_run"
    validation_warnings: int | None = None
    if exit_code == 0:
        validation = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "validate_outputs.py"),
                "--output-dir",
                str(round_dir),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        validation_report = parse_last_json_line(validation.stdout) or {}
        validation_status = "valid" if validation.returncode == 0 else "invalid"
        warnings = validation_report.get("warnings")
        validation_warnings = len(warnings) if isinstance(warnings, list) else None
        gate_events.append(
            {
                "gate": "output_validation",
                "status": "pass" if validation_status == "valid" else "stop",
                "detail": f"validate_outputs: {validation_status}",
            }
        )

    backlog = read_backlog(round_dir / "iteration_backlog.csv")
    analyzed_groups, insufficient_groups, candidates = read_anomaly_groups(
        round_dir / "anomaly_report.json"
    )
    gate_events.append(
        {
            "gate": "issue_harvest",
            "status": "info",
            "detail": (
                f"action_required={backlog['status_counts'].get('action_required', 0)}, "
                f"failed_sources={len(failed_sources)}, "
                f"insufficient_background_groups={insufficient_groups}"
            ),
        }
    )

    return {
        "round": round_index,
        "output_dir": str(round_dir),
        "command": [Path(command[0]).name] + command[1:],
        "exit_code": exit_code,
        "execution_status": execution_status,
        "route_status": route_status,
        "validation_status": validation_status,
        "duration_seconds": duration,
        "input_fingerprints": {
            "request_sha256": args.request_sha256,
            "input_sha256": sha256_file(args.input) if args.mode == "input" else None,
            "evidence_sha256": (
                sha256_file(args.evidence_jsonl)
                if args.mode == "input" and args.evidence_jsonl
                else None
            ),
        },
        "counts": {
            "records": records,
            "action_required": (
                backlog["status_counts"].get("action_required", 0)
                if backlog["available"]
                else None
            ),
            "review_required": (
                backlog["status_counts"].get("review_required", 0)
                if backlog["available"]
                else None
            ),
            "scientific_limit": (
                backlog["status_counts"].get("scientific_limit", 0)
                if backlog["available"]
                else None
            ),
            "auto_recheck": backlog["auto_recheck"],
            "failed_sources": len(failed_sources),
            "insufficient_background_groups": insufficient_groups,
            "analyzed_background_groups": analyzed_groups,
            "candidate_anomalies": candidates,
            "validation_warnings": validation_warnings,
        },
        "issue_codes": backlog["issue_codes"],
        "failed_sources": failed_sources,
        "gate_events": gate_events,
        "delta_vs_previous": None,
        # Controller-internal fields, stripped by public_round() before writing:
        "manual_groups": backlog["manual_groups"],
        "run_failure_retryable": exit_code != 0
        and run_failure_retryable(execution_status, args.mode),
        "gate_stop_reason": None,
    }


def make_gate_round(
    round_index: int, args: argparse.Namespace, gate: str, detail: str, stop_reason: str
) -> dict[str, Any]:
    return {
        "round": round_index,
        "output_dir": "",
        "command": [],
        "exit_code": None,
        "execution_status": None,
        "route_status": None,
        "validation_status": "not_run",
        "duration_seconds": 0.0,
        "input_fingerprints": {
            "request_sha256": args.request_sha256,
            "input_sha256": None,
            "evidence_sha256": None,
        },
        "counts": {
            "records": None,
            "action_required": None,
            "review_required": None,
            "scientific_limit": None,
            "auto_recheck": None,
            "failed_sources": 0,
            "insufficient_background_groups": None,
            "analyzed_background_groups": None,
            "candidate_anomalies": None,
            "validation_warnings": None,
        },
        "issue_codes": {},
        "failed_sources": [],
        "gate_events": [{"gate": gate, "status": "stop", "detail": detail}],
        "delta_vs_previous": None,
        "manual_groups": [],
        "run_failure_retryable": False,
        "gate_stop_reason": stop_reason,
    }


def public_round(record: dict[str, Any]) -> dict[str, Any]:
    """Strip controller-internal fields before writing the schema-bound report."""
    internal = ("manual_groups", "run_failure_retryable", "gate_stop_reason")
    return {key: value for key, value in record.items() if key not in internal}


def rehydrate_round(record: dict[str, Any], mode: str) -> dict[str, Any]:
    """Rebuild controller-internal fields for rounds loaded from a report."""
    hydrated = dict(record)
    hydrated["run_failure_retryable"] = record.get(
        "exit_code"
    ) != 0 and run_failure_retryable(record.get("execution_status"), mode)
    hydrated["gate_stop_reason"] = None
    if is_gate_round(record):
        for event in record.get("gate_events", []):
            if event.get("status") == "stop" and event.get("gate") in GATE_STOP_REASONS:
                hydrated["gate_stop_reason"] = GATE_STOP_REASONS[str(event.get("gate"))]
    output_dir = record.get("output_dir") or ""
    backlog_path = Path(output_dir) / "iteration_backlog.csv" if output_dir else None
    if backlog_path is not None and backlog_path.is_file():
        hydrated["manual_groups"] = read_backlog(backlog_path)["manual_groups"]
    else:
        hydrated["manual_groups"] = []
    return hydrated


def compute_delta(rounds: list[dict[str, Any]]) -> None:
    if len(rounds) < 2:
        return
    current, previous = rounds[-1], rounds[-2]
    if is_gate_round(current):
        return
    current_counts = current.get("counts", {})
    previous_counts = previous.get("counts", {})

    def diff(key: str) -> int | None:
        now, before = current_counts.get(key), previous_counts.get(key)
        if isinstance(now, int) and isinstance(before, int):
            return now - before
        return None

    current["delta_vs_previous"] = {
        "action_required": diff("action_required"),
        "failed_sources": diff("failed_sources"),
    }


def assemble_report(
    args: argparse.Namespace, rounds: list[dict[str, Any]], stop_reason: str
) -> dict[str, Any]:
    executed = [item for item in rounds if not is_gate_round(item)]
    last = executed[-1] if executed else None
    plan = build_repair_plan(last) if last else {"autonomous": [], "manual": []}
    return {
        "schema_version": REPORT_VERSION,
        "request_path": str(args.request),
        "request_sha256": args.request_sha256,
        "mode": args.mode,
        "analysis_profile": args.analysis_profile,
        "max_rounds": args.max_rounds,
        "time_budget_seconds": args.time_budget_seconds,
        "rounds": [public_round(item) for item in rounds],
        "repair_plan": plan,
        "stop_reason": stop_reason,
        "status": final_status(stop_reason, last),
        "next_step": next_step_text(stop_reason, plan),
        "claim_boundary": CLAIM_BOUNDARY,
    }


def load_previous_rounds(loop_root: Path, request_sha256: str) -> list[dict[str, Any]]:
    report_path = loop_root / REPORT_FILENAME
    if not report_path.is_file():
        return []
    previous = read_json(report_path)
    if previous.get("request_sha256") != request_sha256:
        raise LoopUsageError(
            "frozen request changed between invocations; start a new output directory"
        )
    rounds = previous.get("rounds")
    if not isinstance(rounds, list):
        return []
    mode = str(previous.get("mode") or "demo")
    return [rehydrate_round(item, mode) for item in rounds]


def run_loop(args: argparse.Namespace) -> dict[str, Any]:
    loop_root = args.output_dir
    loop_root.mkdir(parents=True, exist_ok=True)
    rounds = load_previous_rounds(loop_root, args.request_sha256)
    resumed = bool(rounds)
    started = time.monotonic()

    force_execute = False
    if not resumed:
        gate_failure = run_pre_gates(args, 1)
        if gate_failure is not None:
            rounds.append(gate_failure)
    elif is_gate_round(rounds[-1]):
        gate_failure = run_pre_gates(args, len(rounds) + 1)
        if gate_failure is not None:
            rounds.append(gate_failure)
        else:
            force_execute = True

    probe_used = False
    stop_reason = "in_progress"
    while True:
        if rounds and not force_execute:
            action, stop_reason = decide_next(
                rounds,
                args.max_rounds,
                time.monotonic() - started,
                args.time_budget_seconds,
            )
            if action == "stop":
                allow_probe = (
                    resumed
                    and not probe_used
                    and stop_reason in ("no_autonomous_repair", "no_progress")
                    and len(rounds) < args.max_rounds
                    and not is_gate_round(rounds[-1])
                )
                if not allow_probe:
                    break
                probe_used = True
        force_execute = False
        if len(rounds) >= args.max_rounds:
            stop_reason = "round_budget_exhausted"
            break
        record = execute_round(args, len(rounds) + 1, loop_root)
        rounds.append(record)
        compute_delta(rounds)
        write_json(
            loop_root / REPORT_FILENAME, assemble_report(args, rounds, "in_progress")
        )

    report = assemble_report(args, rounds, stop_reason)
    write_json(loop_root / REPORT_FILENAME, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic self-correction loop around run_atlas_request.py: "
            "early gates, safe autonomous retries, honest convergence. "
            "Exit codes: 0 success/partial_success, 1 needs_human_review, 2 failed/usage."
        )
    )
    parser.add_argument(
        "--request", type=Path, help="Frozen request JSON (required unless --self-test)"
    )
    parser.add_argument(
        "--output-dir", type=Path, help="Loop root; rounds live in rounds/round-NN"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--input", type=Path, help="Existing D1 CSV to process")
    mode.add_argument("--online-source", help="Routed source ID or 'auto'")
    parser.add_argument(
        "--demo", choices=("production-usgs", "four-media"), default="production-usgs"
    )
    parser.add_argument("--evidence-jsonl", type=Path)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/data"))
    parser.add_argument(
        "--acquisition-mode", choices=("online", "cached"), default="online"
    )
    parser.add_argument(
        "--analysis-profile", choices=("demo", "production"), default="production"
    )
    parser.add_argument(
        "--generated-at", help="ISO-8601 acquisition timestamp passthrough"
    )
    parser.add_argument("--batch-qc-input", type=Path)
    parser.add_argument("--batch-qc-policy", type=Path)
    parser.add_argument("--no-geology", action="store_true")
    parser.add_argument("--require-all-sources", action="store_true")
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=DEFAULT_MAX_ROUNDS,
        help=(
            f"Total rounds recorded in this loop directory "
            f"(default {DEFAULT_MAX_ROUNDS}, cap {MAX_ROUNDS_CAP}); "
            "pass a higher value when resuming to append rounds"
        ),
    )
    parser.add_argument(
        "--time-budget-seconds",
        type=float,
        default=None,
        help="Optional wall-clock budget for this invocation; unset = bounded by --max-rounds",
    )
    parser.add_argument(
        "--round-timeout-seconds",
        type=float,
        default=DEFAULT_ROUND_TIMEOUT_SECONDS,
        help="Hard per-round subprocess timeout (default 900; the run's internal budget stays 840)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run embedded decision-logic tests and exit",
    )
    return parser


def _self_test() -> int:
    checks = 0

    def check(condition: bool, label: str) -> None:
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    # 1. Source-error classification is conservative.
    check(
        source_failure_retryable("HTTP Error 503: connection timed out"),
        "transient retryable",
    )
    check(
        not source_failure_retryable("research use conditions unclear"),
        "license manual",
    )
    check(not source_failure_retryable("mystery failure"), "unknown defaults to manual")
    check(
        not source_failure_retryable("network schema drift detected"),
        "non-retryable marker wins over retryable marker",
    )
    # 2. Run-level classification.
    check(
        run_failure_retryable("network_unavailable", "demo"),
        "network retryable in any mode",
    )
    check(
        run_failure_retryable("incomplete_retrieval", "online"),
        "incomplete retryable online",
    )
    check(
        not run_failure_retryable("incomplete_retrieval", "input"),
        "incomplete manual offline",
    )
    check(
        not run_failure_retryable("needs_human_review", "online"),
        "human review never retried",
    )

    def stub_round(
        *,
        exit_code: int | None = 0,
        execution_status: str = "partial_success",
        validation: str = "valid",
        action_required: int = 0,
        failed: list[dict[str, Any]] | None = None,
        retry_run: bool = False,
        input_sha: str | None = None,
    ) -> dict[str, Any]:
        return {
            "round": 1,
            "command": ["python"],
            "exit_code": exit_code,
            "execution_status": execution_status,
            "validation_status": validation,
            "counts": {
                "action_required": action_required,
                "failed_sources": len(failed or []),
            },
            "failed_sources": failed or [],
            "manual_groups": [],
            "run_failure_retryable": retry_run,
            "gate_stop_reason": None,
            "input_fingerprints": {"input_sha256": input_sha, "evidence_sha256": None},
        }

    # 3. Convergence: clean round stops as converged.
    check(
        decide_next([stub_round()], 3, 0.0, None) == ("stop", "converged"),
        "clean converges",
    )
    # 4. Retryable source failure continues; identical repeat stops as no_progress.
    failing = stub_round(
        failed=[{"source_id": "s1", "error": "timeout", "retryable": True}]
    )
    check(decide_next([failing], 3, 0.0, None)[0] == "continue", "retryable continues")
    check(
        decide_next([failing, failing], 3, 0.0, None) == ("stop", "no_progress"),
        "identical signature stops",
    )
    improving = stub_round(
        failed=[{"source_id": "s2", "error": "timeout", "retryable": True}]
    )
    check(
        decide_next([failing, improving], 2, 0.0, None)
        == ("stop", "round_budget_exhausted"),
        "round budget enforced",
    )
    # 5. Manual-only issues stop immediately with a grouped plan.
    manual_only = stub_round(action_required=5)
    manual_only["manual_groups"] = [
        {
            "stage_owner": "D2",
            "issue_code": "MISSING_UNIT",
            "count": 5,
            "recommended_action": "补显式 schema map",
        }
    ]
    check(
        decide_next([manual_only], 3, 0.0, None) == ("stop", "no_autonomous_repair"),
        "manual issues stop the loop",
    )
    plan = build_repair_plan(manual_only)
    check(
        plan["autonomous"] == [] and plan["manual"][0]["count"] == 5,
        "manual plan built",
    )
    # 6. Non-retryable source failure joins the manual plan.
    hard_fail = stub_round(
        failed=[{"source_id": "s9", "error": "license unclear", "retryable": False}]
    )
    plan = build_repair_plan(hard_fail)
    check(
        plan["autonomous"] == []
        and plan["manual"][0]["issue_code"] == "SOURCE_ACQUISITION_FAILED",
        "hard source failure routed to manual",
    )
    check(
        decide_next([hard_fail], 3, 0.0, None) == ("stop", "no_autonomous_repair"),
        "hard source failure stops",
    )
    # 7. Changed input fingerprint (agent repaired data) defeats no_progress.
    round_a = stub_round(
        action_required=5,
        failed=[{"source_id": "s1", "error": "timeout", "retryable": True}],
        input_sha="a" * 64,
    )
    round_b = stub_round(
        action_required=5,
        failed=[{"source_id": "s1", "error": "timeout", "retryable": True}],
        input_sha="b" * 64,
    )
    check(
        actionable_signature(round_a) != actionable_signature(round_b),
        "input change changes signature",
    )
    # 8. Validation failure is terminal; run-failure classification is honored.
    check(
        decide_next([stub_round(validation="invalid")], 3, 0.0, None)
        == ("stop", "contract_validation_failed"),
        "invalid contract stops",
    )
    check(
        decide_next(
            [stub_round(exit_code=2, execution_status="invalid_input")], 3, 0.0, None
        )
        == ("stop", "run_failed"),
        "hard failure stops",
    )
    check(
        decide_next(
            [stub_round(exit_code=2, execution_status="needs_human_review")],
            3,
            0.0,
            None,
        )
        == ("stop", "needs_human_review"),
        "human review stops",
    )
    check(
        decide_next(
            [
                stub_round(
                    exit_code=2, execution_status="network_unavailable", retry_run=True
                )
            ],
            3,
            0.0,
            None,
        )[0]
        == "continue",
        "transient run failure retries",
    )
    # 9. Time budget stops a loop that would otherwise continue.
    check(
        decide_next([failing], 5, 100.0, 50.0) == ("stop", "time_budget_exhausted"),
        "time budget enforced",
    )
    # 10. Final status mapping.
    check(
        final_status("converged", {"execution_status": "success"}) == "success",
        "success maps",
    )
    check(
        final_status("converged", {"execution_status": "partial_success"})
        == "partial_success",
        "partial maps",
    )
    check(
        final_status("no_autonomous_repair", {}) == "needs_human_review",
        "manual maps to review",
    )
    check(final_status("run_failed", {}) == "failed", "run_failed maps to failed")
    # 11. Backlog harvesting, gate-round rehydration and frozen-request enforcement.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        backlog = tmp_path / "iteration_backlog.csv"
        backlog.write_text(
            "item_id,record_id,source_id,stage_owner,severity,status,issue_code,field,"
            "observed_value,detail,recommended_action,auto_recheck\n"
            "I1,r1,s1,D2,info,scientific_limit,CENSORED_OBSERVATION,censored,<,d,keep,false\n"
            "I2,r2,s1,D1,warn,action_required,MISSING_LICENSE,license,,d,confirm use,true\n"
            "I3,r3,s1,D1,warn,action_required,MISSING_LICENSE,license,,d,confirm use,false\n",
            encoding="utf-8",
        )
        harvested = read_backlog(backlog)
        check(
            harvested["status_counts"]["action_required"] == 2, "backlog action count"
        )
        check(
            harvested["status_counts"]["scientific_limit"] == 1,
            "scientific limit separate",
        )
        check(harvested["auto_recheck"] == 1, "auto_recheck counted")
        check(harvested["manual_groups"][0]["count"] == 2, "manual grouping")
        gate_public = {
            "round": 1,
            "command": [],
            "exit_code": None,
            "execution_status": None,
            "output_dir": "",
            "gate_events": [
                {"gate": "input_header", "status": "stop", "detail": "missing columns"}
            ],
        }
        hydrated = rehydrate_round(gate_public, "input")
        check(hydrated["gate_stop_reason"] == "invalid_input", "gate round rehydrated")
        check(
            decide_next([hydrated], 3, 0.0, None) == ("stop", "invalid_input"),
            "rehydrated gate stops with original reason",
        )
        request = tmp_path / "request.json"
        request.write_text("{}\n", encoding="utf-8")
        digest = sha256_file(request)
        write_json(
            tmp_path / REPORT_FILENAME,
            {"request_sha256": digest, "mode": "demo", "rounds": [gate_public]},
        )
        check(len(load_previous_rounds(tmp_path, digest)) == 1, "resume loads rounds")
        try:
            load_previous_rounds(tmp_path, "0" * 64)
            check(False, "freeze violation must raise")
        except LoopUsageError:
            check(True, "freeze violation raises")
    print(json.dumps({"status": "PASS", "tests": checks}, ensure_ascii=False))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
    try:
        if not args.request or not args.output_dir:
            raise LoopUsageError(
                "--request and --output-dir are required unless --self-test"
            )
        if not args.request.is_file():
            raise LoopUsageError(f"request file not found: {args.request}")
        if args.input is not None:
            args.mode = "input"
            if not args.input.is_file():
                raise LoopUsageError(f"input file not found: {args.input}")
        elif args.online_source:
            args.mode = "online"
        else:
            args.mode = "demo"
        if not 1 <= args.max_rounds <= MAX_ROUNDS_CAP:
            raise LoopUsageError(f"--max-rounds must be within 1..{MAX_ROUNDS_CAP}")
        args.request_sha256 = sha256_file(args.request)
        report = run_loop(args)
    except LoopUsageError as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if report["status"] in ("success", "partial_success"):
        return 0
    if report["status"] == "needs_human_review":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
