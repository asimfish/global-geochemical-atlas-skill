#!/usr/bin/env python3
"""Run one isolated Public benchmark task through a Qwen3.8-Max tool-calling API."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai_compatible_api import ChatApiError, OpenAICompatibleChatClient, assistant_message_for_history


RUNNER_VERSION = "qwen3.8-max-benchmark-runner.v1"
HERE = Path(__file__).resolve().parent
EVALUATION_ROOT = HERE.parents[1]
PUBLIC_ROOT = EVALUATION_ROOT / "release" / "public"
REQUIRED_QUESTIONS = tuple(f"Q{index:02d}" for index in range(1, 9))
MAX_COMMAND_CHARS = 100_000
MAX_TOOL_OUTPUT_CHARS = 16_000


class RunnerFailure(RuntimeError):
    def __init__(self, message: str, exit_code: int = 70) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_tree(root: Path) -> str:
    """Match the frozen E1 tree hash: relative path, size and content."""

    root = root.resolve(strict=True)
    digest = hashlib.sha256()
    files: list[Path] = []
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in sorted(directories):
            path = current_path / name
            if path.is_symlink():
                raise RunnerFailure(f"Skill tree contains a symlink: {path}", 73)
        for name in sorted(filenames):
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise RunnerFailure(f"Skill tree contains an unsafe entry: {path}", 73)
            files.append(path)
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(path.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def pair_fingerprint(model_input: Path, model: str, parameters: dict[str, Any], seed: int) -> str:
    input_hashes = {
        path.relative_to(model_input).as_posix(): sha256_file(path)
        for path in sorted(item for item in model_input.rglob("*") if item.is_file())
    }
    frozen = {
        "runner_version": RUNNER_VERSION,
        "model": model,
        "model_parameters": parameters,
        "seed": seed,
        "inputs": input_hashes,
        "sandbox": "bubblewrap-no-network-readonly-input-v1",
    }
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def limit_child_resources(cpu_seconds: int, memory_mib: int, file_mib: int) -> None:
    memory_bytes = memory_mib * 1024 * 1024
    file_bytes = file_mib * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))


class BubblewrapSandbox:
    def __init__(
        self,
        *,
        model_input: Path,
        submission: Path,
        skill_dir: Path | None,
        command_timeout: int,
        cpu_seconds: int,
        memory_mib: int,
        file_mib: int,
    ) -> None:
        executable = shutil.which("bwrap")
        if not executable:
            raise RunnerFailure("bubblewrap (bwrap) is required for filesystem isolation", 73)
        self.executable = executable
        self.model_input = model_input.resolve()
        self.submission = submission.resolve()
        self.skill_dir = skill_dir.resolve() if skill_dir else None
        self.command_timeout = command_timeout
        self.cpu_seconds = cpu_seconds
        self.memory_mib = memory_mib
        self.file_mib = file_mib

    def execute(self, command: str) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            return {"exit_code": 2, "stdout": "", "stderr": "command must be a non-empty string", "timed_out": False}
        if len(command) > MAX_COMMAND_CHARS:
            return {"exit_code": 2, "stdout": "", "stderr": f"command exceeds {MAX_COMMAND_CHARS} characters", "timed_out": False}
        args = [
            self.executable,
            "--unshare-net",
            "--unshare-pid",
            "--unshare-ipc",
            "--unshare-uts",
            "--die-with-parent",
            "--new-session",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/lib64", "/lib64",
            "--dir", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--ro-bind", str(self.model_input), "/model_input",
            "--bind", str(self.submission), "/submission",
            "--chdir", "/submission",
            "--setenv", "HOME", "/tmp",
            "--setenv", "PATH", "/usr/bin:/bin",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        ]
        if self.skill_dir:
            args.extend(["--ro-bind", str(self.skill_dir), "/skill"])
        args.extend(["/bin/bash", "-lc", command])
        started = time.monotonic()
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.command_timeout,
                preexec_fn=lambda: limit_child_resources(self.cpu_seconds, self.memory_mib, self.file_mib),
                check=False,
            )
            return {
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-MAX_TOOL_OUTPUT_CHARS:],
                "stderr": completed.stderr[-MAX_TOOL_OUTPUT_CHARS:],
                "timed_out": False,
                "duration_seconds": round(time.monotonic() - started, 3),
            }
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            return {
                "exit_code": 124,
                "stdout": stdout[-MAX_TOOL_OUTPUT_CHARS:],
                "stderr": (stderr + "\ncommand timed out")[-MAX_TOOL_OUTPUT_CHARS:],
                "timed_out": True,
                "duration_seconds": round(time.monotonic() - started, 3),
            }


def tool_definition(skill_enabled: bool) -> list[dict[str, Any]]:
    skill_note = " A frozen Skill is available read-only at /skill." if skill_enabled else " No Skill is mounted."
    return [
        {
            "type": "function",
            "function": {
                "name": "run_in_benchmark_sandbox",
                "description": (
                    "Run one Bash command in an isolated, network-disabled sandbox. /model_input is read-only; "
                    "/submission is writable; use /tmp for helper files." + skill_note
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Bash command. Inspect inputs and create or validate files under /submission/artifacts.",
                        }
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        }
    ]


def initial_messages(skill_enabled: bool) -> list[dict[str, Any]]:
    skill_instruction = (
        "The frozen Skill is mounted read-only at /skill. Read /skill/SKILL.md and relevant referenced files before solving the task."
        if skill_enabled
        else "This is the B0 baseline. No Skill is mounted or available."
    )
    return [
        {
            "role": "system",
            "content": (
                "You are the candidate Agent in an isolated file-artifact benchmark. Use the sandbox tool to inspect and solve the task. "
                "Never claim that files were created unless you verified them. Do not ask the user questions."
            ),
        },
        {
            "role": "user",
            "content": (
                "Read /model_input/task.md, /model_input/task.json, and /model_input/inputs/. "
                "Write exactly the ten required files under /submission/artifacts and no other submission files. "
                "Put temporary scripts in /tmp. The network is disabled and the frozen inputs are authoritative. "
                "Use Python standard-library modules such as csv, json, sqlite3, statistics, and base64 when useful. "
                "Before finishing, validate JSON/JSONL/CSV, SQLite, PNG, and list every submission file. "
                f"{skill_instruction}"
            ),
        },
    ]


def run_agent(
    *,
    client: OpenAICompatibleChatClient,
    sandbox: BubblewrapSandbox,
    model: str,
    parameters: dict[str, Any],
    seed: int,
    max_tool_calls: int,
    skill_enabled: bool,
) -> tuple[list[dict[str, Any]], str | None, list[dict[str, Any]]]:
    messages = initial_messages(skill_enabled)
    transcript: list[dict[str, Any]] = []
    tools = tool_definition(skill_enabled)
    tool_call_count = 0
    final_content: str | None = None
    while tool_call_count < max_tool_calls:
        payload = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "seed": seed,
            **parameters,
        }
        response = client.create(payload)
        message = response["choices"][0]["message"]
        history_message = assistant_message_for_history(message)
        messages.append(history_message)
        transcript.append(
            {
                "type": "assistant",
                "request_id": response.get("id"),
                "finish_reason": response["choices"][0].get("finish_reason"),
                "message": history_message,
                "usage": response.get("usage"),
            }
        )
        calls = message.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            content = message.get("content")
            final_content = content if isinstance(content, str) else None
            break
        for call in calls:
            if tool_call_count >= max_tool_calls:
                break
            tool_call_count += 1
            arguments: Any = None
            call_id = call.get("id") if isinstance(call, dict) else None
            function = call.get("function", {}) if isinstance(call, dict) else {}
            name = function.get("name")
            raw_arguments = function.get("arguments")
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            except json.JSONDecodeError as exc:
                result = {"exit_code": 2, "stderr": f"invalid tool arguments JSON: {exc}", "stdout": "", "timed_out": False}
            else:
                if name != "run_in_benchmark_sandbox" or not isinstance(arguments, dict):
                    result = {"exit_code": 2, "stderr": f"unsupported tool call: {name}", "stdout": "", "timed_out": False}
                else:
                    result = sandbox.execute(arguments.get("command"))
            tool_message = {
                "role": "tool",
                "tool_call_id": call_id or f"missing-id-{tool_call_count}",
                "content": json.dumps(result, ensure_ascii=False),
            }
            messages.append(tool_message)
            transcript.append({"type": "tool", "name": name, "arguments": arguments, "result": result})
    return transcript, final_content, messages


def validate_submission(submission: Path, required_outputs: list[str]) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    required = set(required_outputs)
    actual = {
        path.relative_to(submission).as_posix()
        for path in submission.rglob("*")
        if path.is_file()
    }
    missing = sorted(required - actual)
    unexpected = sorted(actual - required)
    if missing:
        errors.append(f"missing required files: {missing}")
    if unexpected:
        errors.append(f"unexpected submission files: {unexpected}")

    for relative in sorted(required & actual):
        path = submission / relative
        if path.stat().st_size == 0:
            errors.append(f"empty file: {relative}")
    for relative in ("artifacts/qc_report.json", "artifacts/anomalies.geojson", "artifacts/run_manifest.json"):
        path = submission / relative
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if relative.endswith("run_manifest.json") and not isinstance(value.get("benchmark_evidence"), dict):
                    errors.append("artifacts/run_manifest.json lacks a benchmark_evidence object")
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as exc:
                errors.append(f"invalid JSON {relative}: {exc}")
    jsonl = submission / "artifacts/sources.jsonl"
    if jsonl.is_file():
        try:
            lines = [line for line in jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                errors.append("artifacts/sources.jsonl has no records")
            for line in lines:
                json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSONL artifacts/sources.jsonl: {exc}")
    for relative in ("artifacts/observations.csv", "artifacts/anomaly_results.csv", "artifacts/h3_cells.csv"):
        path = submission / relative
        if path.is_file():
            try:
                with path.open(encoding="utf-8", newline="") as handle:
                    if not csv.DictReader(handle).fieldnames:
                        errors.append(f"CSV has no header: {relative}")
            except UnicodeDecodeError as exc:
                errors.append(f"invalid UTF-8 CSV {relative}: {exc}")
    sqlite_path = submission / "artifacts/geochemical.sqlite"
    if sqlite_path.is_file() and not sqlite_path.read_bytes().startswith(b"SQLite format 3\x00"):
        errors.append("artifacts/geochemical.sqlite has no SQLite 3 header")
    png_path = submission / "artifacts/map.png"
    if png_path.is_file() and not png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        errors.append("artifacts/map.png has no PNG signature")
    return not errors, errors, sorted(actual)


def run_command(args: list[str], stdout_path: Path, stderr_path: Path) -> int:
    completed = subprocess.run(args, capture_output=True, text=True, errors="replace", check=False)
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    return completed.returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", choices=REQUIRED_QUESTIONS, required=True)
    parser.add_argument("--variant", choices=("B0", "S0"), required=True)
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--base-url", default=os.getenv("QWEN_BASE_URL"))
    parser.add_argument("--model", default=os.getenv("QWEN_MODEL", "qwen3.8-max"))
    parser.add_argument("--api-key-env", default="QWEN_API_KEY")
    parser.add_argument("--skill-dir", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--top-p", type=float, help="Optional; Qwen recommends changing temperature or top_p, not both")
    parser.add_argument("--max-completion-tokens", type=int, default=16384)
    parser.add_argument("--reasoning-effort", choices=("low", "medium", "xhigh"), default="xhigh")
    parser.add_argument("--max-tool-calls", type=int, default=24)
    parser.add_argument("--api-timeout", type=int, default=600)
    parser.add_argument("--command-timeout", type=int, default=45)
    parser.add_argument("--cpu-seconds", type=int, default=45)
    parser.add_argument("--memory-mib", type=int, default=2048)
    parser.add_argument("--file-mib", type=int, default=128)
    parser.add_argument("--llm-report", type=Path)
    parser.add_argument("--static-review", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.base_url:
        print("error: set QWEN_BASE_URL or pass --base-url", file=sys.stderr)
        return 73
    if not args.base_url.startswith(("http://", "https://")):
        print("error: --base-url must start with http:// or https://", file=sys.stderr)
        return 73
    if not 0 <= args.seed <= 2**31 - 1:
        print("error: --seed must be between 0 and 2^31-1", file=sys.stderr)
        return 73
    if not 0.6 <= args.temperature < 2:
        print("error: Qwen3.8-Max --temperature must be in [0.6, 2)", file=sys.stderr)
        return 73
    if args.top_p is not None and not 0 < args.top_p <= 1:
        print("error: --top-p must be in (0, 1]", file=sys.stderr)
        return 73
    positive_limits = (
        args.max_completion_tokens,
        args.max_tool_calls,
        args.api_timeout,
        args.command_timeout,
        args.cpu_seconds,
        args.memory_mib,
        args.file_mib,
    )
    if any(value <= 0 for value in positive_limits):
        print("error: token, call, timeout, CPU, memory, and file limits must be positive", file=sys.stderr)
        return 73
    if args.run_id is not None and not re.fullmatch(r"[A-Za-z0-9._-]+", args.run_id):
        print("error: --run-id may contain only letters, numbers, dot, underscore, and hyphen", file=sys.stderr)
        return 73
    if args.variant == "S0" and args.skill_dir is None:
        print("error: S0 requires --skill-dir pointing to the frozen Skill", file=sys.stderr)
        return 73
    if args.skill_dir is not None and (not args.skill_dir.is_dir() or not (args.skill_dir / "SKILL.md").is_file()):
        print("error: --skill-dir must contain SKILL.md", file=sys.stderr)
        return 73
    if args.variant == "B0" and args.skill_dir is not None:
        print("error: B0 must not receive --skill-dir", file=sys.stderr)
        return 73
    api_key = os.getenv(args.api_key_env, "")
    if not api_key and not args.base_url.startswith(("http://127.0.0.1", "http://localhost")):
        print(f"error: cloud endpoint requires {args.api_key_env}", file=sys.stderr)
        return 73
    if not api_key:
        api_key = "EMPTY"
    task_dir = PUBLIC_ROOT / args.question
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    required_outputs = task["required_outputs"]
    generated_id = f"qwen3.8-max-{args.question.lower()}-{args.variant.lower()}-r{args.repeat}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    run_id = args.run_id or generated_id
    run_root = (args.run_root or Path("/tmp/gga-qwen3.8-max-runs") / run_id).resolve()
    if run_root.exists():
        print(f"error: run root already exists: {run_root}", file=sys.stderr)
        return 73

    model_input = run_root / "model_input"
    submission = run_root / "submission"
    artifacts = submission / "artifacts"
    model_input.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    shutil.copy2(task_dir / "task.md", model_input / "task.md")
    shutil.copy2(task_dir / "task.json", model_input / "task.json")
    shutil.copytree(task_dir / "inputs", model_input / "inputs")

    parameters = {
        "temperature": args.temperature,
        "max_completion_tokens": args.max_completion_tokens,
        "reasoning_effort": args.reasoning_effort,
        "preserve_thinking": True,
    }
    if args.top_p is not None:
        parameters["top_p"] = args.top_p
    fingerprint = pair_fingerprint(model_input, args.model, parameters, args.seed)
    started_at = timestamp()
    transcript_path = run_root / "agent_transcript.json"
    stdout_path = run_root / "agent_stdout.log"
    stderr_path = run_root / "agent_stderr.log"
    objective_path = run_root / "objective_report.json"
    score_path = run_root / "score.json"
    runner_errors: list[str] = []
    final_content: str | None = None
    transcript: list[dict[str, Any]] = []
    exit_code = 70

    try:
        client = OpenAICompatibleChatClient(base_url=args.base_url, api_key=api_key, timeout_seconds=args.api_timeout)
        sandbox = BubblewrapSandbox(
            model_input=model_input,
            submission=submission,
            skill_dir=args.skill_dir if args.variant == "S0" else None,
            command_timeout=args.command_timeout,
            cpu_seconds=args.cpu_seconds,
            memory_mib=args.memory_mib,
            file_mib=args.file_mib,
        )
        transcript, final_content, _ = run_agent(
            client=client,
            sandbox=sandbox,
            model=args.model,
            parameters=parameters,
            seed=args.seed,
            max_tool_calls=args.max_tool_calls,
            skill_enabled=args.variant == "S0",
        )
        valid, validation_errors, actual_files = validate_submission(submission, required_outputs)
        runner_errors.extend(validation_errors)
        exit_code = 0 if valid else 74
    except ChatApiError as exc:
        actual_files = sorted(path.relative_to(submission).as_posix() for path in submission.rglob("*") if path.is_file())
        runner_errors.append(str(exc))
        if exc.response_body:
            runner_errors.append(f"API response excerpt: {exc.response_body}")
        exit_code = 70
    except RunnerFailure as exc:
        actual_files = sorted(path.relative_to(submission).as_posix() for path in submission.rglob("*") if path.is_file())
        runner_errors.append(str(exc))
        exit_code = exc.exit_code
    except Exception as exc:  # keep a run record for unexpected runner failures
        actual_files = sorted(path.relative_to(submission).as_posix() for path in submission.rglob("*") if path.is_file())
        runner_errors.append(f"unexpected runner error: {exc.__class__.__name__}: {exc}")
        exit_code = 70

    atomic_json(transcript_path, {"runner_version": RUNNER_VERSION, "events": transcript, "final_content": final_content})
    stdout_path.write_text((final_content or "") + "\n", encoding="utf-8")
    stderr_path.write_text("\n".join(runner_errors) + ("\n" if runner_errors else ""), encoding="utf-8")

    grader_stdout = run_root / "grader_stdout.log"
    grader_stderr = run_root / "grader_stderr.log"
    grader_code = run_command(
        [sys.executable, str(EVALUATION_ROOT / "tools" / "grade_task.py"), str(task_dir), str(submission), "--output", str(objective_path)],
        grader_stdout,
        grader_stderr,
    )
    if grader_code != 0:
        exit_code = 75
        runner_errors.append(f"grade_task.py failed with {grader_code}")

    status = {0: "success", 2: "partial_success", 71: "timed_out", 72: "resource_exceeded", 76: "cancelled"}.get(exit_code, "failed")
    if objective_path.is_file():
        finalize_stdout = run_root / "finalize_stdout.log"
        finalize_stderr = run_root / "finalize_stderr.log"
        finalize_args = [
            sys.executable,
            str(EVALUATION_ROOT / "tools" / "finalize_score.py"),
            "--objective-report", str(objective_path),
            "--rubric", str(task_dir / "rubric.json"),
            "--run-id", run_id,
            "--candidate-status", status,
            "--output", str(score_path),
        ]
        if args.llm_report:
            finalize_args.extend(["--llm-report", str(args.llm_report)])
        if args.static_review:
            finalize_args.extend(["--static-review", str(args.static_review)])
        finalize_code = run_command(finalize_args, finalize_stdout, finalize_stderr)
        if finalize_code != 0:
            exit_code = 75
            status = "failed"
            runner_errors.append(f"finalize_score.py failed with {finalize_code}")

    skill_version = sha256_tree(args.skill_dir.resolve()) if args.variant == "S0" and args.skill_dir else None
    score = json.loads(score_path.read_text(encoding="utf-8")) if score_path.is_file() else None
    ended_at = timestamp()
    record = {
        "run_id": run_id,
        "task_id": task["task_id"],
        "question_id": args.question,
        "split": "public",
        "variant": args.variant,
        "repeat": args.repeat,
        "pair_fingerprint": fingerprint,
        "model": args.model,
        "model_parameters": {**parameters, "seed": args.seed},
        "skill_version": skill_version,
        "benchmark_version": task["gold_version"],
        "runner_version": RUNNER_VERSION,
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "exit_code": exit_code,
        "cause_exit_code": None,
        "sandbox_image": "bubblewrap-no-network-readonly-input-v1",
        "artifact_dir": str(artifacts),
        "actual_submission_files": actual_files,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "transcript": str(transcript_path),
        "objective_report": str(objective_path),
        "llm_grader_report": str(args.llm_report.resolve()) if args.llm_report else None,
        "static_review": str(args.static_review.resolve()) if args.static_review else None,
        "score_path": str(score_path),
        "score": score,
        "redline_events": json.loads(objective_path.read_text(encoding="utf-8")).get("redline_events", []) if objective_path.is_file() else [],
        "notes": runner_errors,
        "api": {"base_url": args.base_url, "api_key_source": args.api_key_env, "api_key_recorded": False},
    }
    stderr_path.write_text("\n".join(runner_errors) + ("\n" if runner_errors else ""), encoding="utf-8")
    record_path = run_root / "run_record.json"
    atomic_json(record_path, record)
    print(json.dumps({"run_id": run_id, "status": status, "exit_code": exit_code, "run_root": str(run_root), "record": str(record_path)}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
