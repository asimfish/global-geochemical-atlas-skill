#!/usr/bin/env python3
"""Expose evaluation_lyf scientific suites through one stable gate interface."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "stage_benchmark" / "scripts"
REAL_FIXTURES = ROOT / "stage_benchmark" / "real-data" / "fixtures" / "raw"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def command_for(args: argparse.Namespace, suite_output: Path) -> list[str]:
    python = sys.executable
    if args.suite == "all":
        command = [
            python,
            str(SCRIPTS / "run_all.py"),
            "--output-dir",
            str(suite_output),
            "--stress-records",
            str(args.stress_records),
            "--real-max-source-samples",
            str(args.real_max_source_samples),
        ]
        if args.runtime_fixture_dir:
            command.extend(["--real-fixture-dir", str(args.runtime_fixture_dir)])
        return command
    if args.suite == "isolated":
        return [
            python,
            str(SCRIPTS / "run_isolated_suite.py"),
            "--report",
            str(suite_output / "isolated_report.json"),
            "--stress-records",
            str(args.stress_records),
        ]
    if args.suite == "real":
        command = [python, str(SCRIPTS / "run_real_data_suite.py"), "--output-dir", str(suite_output)]
        if args.runtime_fixture_dir:
            command.extend(["--fixture-dir", str(args.runtime_fixture_dir)])
        if args.real_max_source_samples:
            command.extend(["--max-source-samples", str(args.real_max_source_samples)])
        return command
    if args.suite == "global":
        command = [
            python,
            str(SCRIPTS / "run_global_data_suite.py"),
            "--output-dir",
            str(suite_output),
            "--candidate-label",
            args.candidate_label,
        ]
        if args.d2_script:
            command.extend(["--d2-script", str(args.d2_script.resolve())])
        if args.expanded:
            command.append("--expanded")
        return command
    if args.suite == "completion":
        command = [python, str(SCRIPTS / "run_completion_reference.py"), "--output-dir", str(suite_output)]
        if args.refresh_downloads:
            command.append("--refresh-downloads")
        return command
    raise ValueError(f"unsupported suite: {args.suite}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("isolated", "real", "global", "completion", "all"), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--stress-records", type=int, default=10_000)
    parser.add_argument("--real-max-source-samples", type=int, default=20)
    parser.add_argument("--d2-script", type=Path)
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--expanded", action="store_true")
    parser.add_argument("--refresh-downloads", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        parser.error("--output-dir must be new or empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.runtime_fixture_dir = None
    if args.suite in {"real", "all"}:
        args.runtime_fixture_dir = args.output_dir / "fixtures" / "real"
        shutil.copytree(REAL_FIXTURES, args.runtime_fixture_dir)
    suite_output = args.output_dir / "output"
    stdout_path = args.output_dir / "stdout.log"
    stderr_path = args.output_dir / "stderr.log"
    report_path = args.output_dir / "suite_report.json"
    command = command_for(args, suite_output)
    started_at = timestamp()
    start = time.monotonic()
    timed_out = False
    cause_exit_code: int | None = None
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=args.timeout_seconds,
        )
        cause_exit_code = completed.returncode
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_path.write_text(exc.stdout or "", encoding="utf-8")
        stderr_path.write_text(exc.stderr or "", encoding="utf-8")
    duration = round(time.monotonic() - start, 6)
    status = "timed_out" if timed_out else ("pass" if cause_exit_code == 0 else "fail")
    report = {
        "schema_version": "evaluation-lyf-suite-adapter-v1",
        "suite": args.suite,
        "status": status,
        "blocking_gate_passed": status == "pass",
        "started_at": started_at,
        "ended_at": timestamp(),
        "execution_seconds": duration,
        "timeout_seconds": args.timeout_seconds,
        "cause_exit_code": cause_exit_code,
        "command": command,
        "stdout_log": stdout_path.name,
        "stderr_log": stderr_path.name,
        "output": suite_output.name,
        "runtime_fixture_copy": (
            str(args.runtime_fixture_dir.relative_to(args.output_dir)) if args.runtime_fixture_dir else None
        ),
        "claim_boundary": (
            "This is a development scientific gate. It is not an official hidden-task score, "
            "an uplift result, or a substitute for the competition Docker campaign."
        ),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 71 if timed_out else (0 if cause_exit_code == 0 else 2)


if __name__ == "__main__":
    raise SystemExit(main())
