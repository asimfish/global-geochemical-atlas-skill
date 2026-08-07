#!/usr/bin/env python3
"""Build and run paired B0/S0 Docker campaigns against the E1-aligned benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlsplit

from common import atomic_json, hash_tree, sha256_file, utc_now


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVALUATION_ROOT.parent
DOCKER_ROOT = Path(__file__).resolve().parent
ALIGNMENT_PATH = EVALUATION_ROOT / "contracts" / "benchmark-execution-contract.json"
PUBLIC_INTERFACE = EVALUATION_ROOT / "ai_visible_public" / "public_interface.md"
SKILL_DIR = REPO_ROOT / "skills" / "global-geochemical-atlas"
SAFE_NAME = re.compile(r"[^a-z0-9_.-]+")
QWEN_ANTHROPIC_HOST = "token-plan.cn-beijing.maas.aliyuncs.com"
E1_STATUS = {
    0: "success",
    2: "partial_success",
    71: "timed_out",
    72: "resource_exceeded",
    76: "cancelled",
}
E1_CODES = {0, 2, 10, 11, 12, 13, 20, 21, 22, 30, 70, 71, 72, 73, 74, 75, 76}


class CampaignError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeProfile:
    cpus: str = "2"
    memory: str = "4g"
    pids: int = 256
    timeout_seconds: int = 900


@dataclass(frozen=True)
class NetworkHandle:
    mode: str
    internal: str | None = None
    egress: str | None = None
    proxy: str | None = None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def run_checked(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, check=False, capture_output=capture, text=True)
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise CampaignError(f"command failed: {' '.join(command[:4])}: {message}")
    return completed


def docker_available() -> dict[str, Any]:
    completed = run_checked(["docker", "version", "--format", "{{json .}}"])
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CampaignError("docker version did not return JSON") from exc
    if not value.get("Server"):
        raise CampaignError("Docker daemon is not available")
    return value


def image_identity(image: str) -> str:
    return run_checked(["docker", "image", "inspect", image, "--format", "{{.Id}}"]).stdout.strip()


def task_source(question: str) -> tuple[Path, str]:
    if not re.fullmatch(r"Q(?:0[1-9]|1[0-9]|2[0-4])", question):
        raise CampaignError(f"invalid question id: {question}")
    number = int(question[1:])
    if number <= 8:
        return EVALUATION_ROOT / "release" / "public" / question, "public"
    if number <= 16:
        return EVALUATION_ROOT / "evaluator_private" / "shadow" / question, "shadow"
    return EVALUATION_ROOT / "evaluator_private" / "final_holdout" / question, "final_holdout"


def parse_tasks(value: str) -> list[str]:
    if value.strip().casefold() == "all":
        return [f"Q{number:02d}" for number in range(1, 25)]
    tasks = []
    for item in value.split(","):
        question = item.strip().upper()
        task_source(question)
        if question not in tasks:
            tasks.append(question)
    if not tasks:
        raise CampaignError("--tasks selected no questions")
    return tasks


def parse_conditions(value: str) -> list[str]:
    conditions = []
    for raw in value.split(","):
        condition = raw.strip().upper()
        if condition not in {"B0", "S0"}:
            raise CampaignError("conditions must contain only B0 and S0")
        if condition not in conditions:
            conditions.append(condition)
    if not conditions:
        raise CampaignError("--conditions selected no conditions")
    return conditions


def validate_provider_profile(
    provider_profile: str,
    provider_base_url: str,
    model: str,
    temperature: float,
) -> None:
    if provider_profile != "qwen-anthropic":
        return
    parsed_provider = urlsplit(provider_base_url)
    if (
        parsed_provider.scheme != "https"
        or parsed_provider.hostname != QWEN_ANTHROPIC_HOST
        or parsed_provider.username is not None
        or parsed_provider.password is not None
        or parsed_provider.port is not None
        or parsed_provider.path.rstrip("/") != "/apps/anthropic"
        or parsed_provider.query
        or parsed_provider.fragment
    ):
        raise CampaignError(
            "qwen-anthropic requires the approved HTTPS /apps/anthropic SDK base URL"
        )
    if temperature != 0.6:
        raise CampaignError("qwen-anthropic requires --temperature 0.6")
    if model != "qwen3.8-max":
        raise CampaignError("qwen-anthropic primary --model must be qwen3.8-max")


def read_allowlist(path: Path, extra: Sequence[str]) -> tuple[str, ...]:
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip().casefold().rstrip(".")
        if value and value not in rules:
            rules.append(value)
    for raw in extra:
        value = raw.strip().casefold().rstrip(".")
        if value and value not in rules:
            rules.append(value)
    return tuple(rules)


def safe_slug(value: str) -> str:
    slug = SAFE_NAME.sub("-", value.casefold()).strip("-.")
    return slug[:48] or "campaign"


def start_network(image: str, campaign_id: str, rules: tuple[str, ...], mode: str) -> NetworkHandle:
    if mode == "offline":
        return NetworkHandle(mode="offline")
    suffix = f"{safe_slug(campaign_id)}-{uuid.uuid4().hex[:8]}"
    internal = f"gga-internal-{suffix}"
    egress = f"gga-egress-{suffix}"
    proxy = f"gga-proxy-{suffix}"
    run_checked(["docker", "network", "create", "--internal", internal])
    try:
        run_checked(["docker", "network", "create", egress])
        run_checked(
            [
                "docker",
                "run",
                "--detach",
                "--name",
                proxy,
                "--network",
                internal,
                "--network-alias",
                "eval-proxy",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev",
                "--env",
                f"EVAL_ALLOWED_HOSTS={','.join(rules)}",
                image,
                "python",
                "/opt/evaluation/container/allowlist_proxy.py",
            ]
        )
        run_checked(["docker", "network", "connect", egress, proxy])
        time.sleep(0.5)
        running = run_checked(["docker", "inspect", proxy, "--format", "{{.State.Running}}"]).stdout.strip()
        if running != "true":
            raise CampaignError("allowlist proxy failed to start")
        return NetworkHandle(mode="whitelist", internal=internal, egress=egress, proxy=proxy)
    except Exception:
        cleanup_network(NetworkHandle(mode="whitelist", internal=internal, egress=egress, proxy=proxy))
        raise


def cleanup_network(handle: NetworkHandle) -> None:
    if handle.proxy:
        subprocess.run(["docker", "rm", "--force", handle.proxy], check=False, capture_output=True)
    for network in (handle.internal, handle.egress):
        if network:
            subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)


def prepare_task_bundle(question: str, destination: Path) -> tuple[Path, str, str]:
    source, split = task_source(question)
    public_task = EVALUATION_ROOT / "ai_visible_public" / "tasks" / question
    if not source.is_dir() or not public_task.is_dir():
        raise CampaignError(f"task source is missing for {question}")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copy2(PUBLIC_INTERFACE, destination / "public_interface.md")
    for name in ("task.md", "task.json"):
        shutil.copy2(public_task / name, destination / name)
    shutil.copytree(public_task / "inputs", destination / "inputs")
    prompt = """你正在执行一个隔离的文件产物评测任务。请直接完成任务，不要只给方案，也不要询问确认。

只允许读取：/task
只允许将最终交卷写入：/submission
工作目录：/workspace

先读取 /task/public_interface.md、/task/task.md、/task/task.json 和 /task/inputs/。
如环境中发现与任务相关的 Agent Skill，应按其 description 判断并按需加载；若没有可用 Skill，则依靠当前模型完成同一任务。
严格生成 task.json.required_outputs 声明的十个 artifacts/ 文件。题目专用逻辑证据写入
/submission/artifacts/run_manifest.json 的 benchmark_evidence，不创建额外交卷文件。
不得读取其他任务、评分器、gold、rubric、历史结果或 /task 之外的外部目录；不得编造来源未报告的科学事实。
"""
    (destination / "prompt.md").write_text(prompt, encoding="utf-8")
    return source, split, hash_tree(destination)


def pair_fingerprint(
    *,
    task_hash: str,
    image_id: str,
    model: str,
    model_variant: str,
    temperature: float,
    provider_profile: str = "openai-compatible",
    repeat: int,
    profile: RuntimeProfile,
    network: str,
) -> str:
    payload = {
        "image_id": image_id,
        "model": model,
        "model_variant": model_variant,
        "temperature": temperature,
        "provider_profile": provider_profile,
        "network": network,
        "repeat": repeat,
        "resources": profile.__dict__,
        "task_hash": task_hash,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def artifact_inventory(submission: Path, required_paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    artifacts = []
    missing = []
    for relative in required_paths:
        path = submission / relative
        if not path.is_file() or path.is_symlink():
            missing.append(relative)
        else:
            artifacts.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    return artifacts, missing


def redact_file(path: Path, secrets: Sequence[str]) -> bool:
    if not path.is_file():
        return False
    value = path.read_text(encoding="utf-8", errors="replace")
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED_EVAL_SECRET]")
    if redacted != value:
        path.write_text(redacted, encoding="utf-8")
        return True
    return False


def redact_tree(root: Path, secrets: Sequence[str]) -> list[str]:
    patterns = [secret.encode("utf-8") for secret in secrets if secret]
    redacted_files: list[str] = []
    if not patterns:
        return redacted_files
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            continue
        changed = False
        with path.open("r+b") as handle:
            with mmap.mmap(handle.fileno(), 0) as mapped:
                for pattern in patterns:
                    start = 0
                    replacement = b"*" * len(pattern)
                    while (position := mapped.find(pattern, start)) != -1:
                        mapped[position : position + len(pattern)] = replacement
                        start = position + len(pattern)
                        changed = True
                if changed:
                    mapped.flush()
        if changed:
            redacted_files.append(path.relative_to(root).as_posix())
    return redacted_files


def execute_container(
    *,
    name: str,
    image: str,
    command: list[str],
    task_dir: Path,
    workspace: Path,
    submission: Path,
    condition: str,
    network: NetworkHandle,
    profile: RuntimeProfile,
    environment_names: list[str],
    environment_values: dict[str, str],
    host_environment: dict[str, str],
    stdout_path: Path,
    stderr_path: Path,
) -> tuple[int, bool, float]:
    uid_gid = f"{os.getuid()}:{os.getgid()}"
    docker_command = [
        "docker",
        "run",
        "--name",
        name,
        "--rm",
        "--user",
        uid_gid,
        "--cpus",
        profile.cpus,
        "--memory",
        profile.memory,
        "--memory-swap",
        profile.memory,
        "--pids-limit",
        str(profile.pids),
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=1g",
        "--volume",
        f"{task_dir.resolve()}:/task:ro",
        "--volume",
        f"{workspace.resolve()}:/workspace:rw",
        "--volume",
        f"{submission.resolve()}:/submission:rw",
        "--workdir",
        "/workspace",
        "--env",
        "NVIDIA_VISIBLE_DEVICES=none",
    ]
    if network.mode == "offline":
        docker_command.extend(["--network", "none"])
    else:
        if not network.internal:
            raise CampaignError("whitelist network has no internal network")
        docker_command.extend(["--network", network.internal])
        for key, value in {
            "HTTP_PROXY": "http://eval-proxy:8080",
            "HTTPS_PROXY": "http://eval-proxy:8080",
            "http_proxy": "http://eval-proxy:8080",
            "https_proxy": "http://eval-proxy:8080",
            "NO_PROXY": "localhost,127.0.0.1",
        }.items():
            docker_command.extend(["--env", f"{key}={value}"])
    for name_ in environment_names:
        docker_command.extend(["--env", name_])
    for key, value in sorted(environment_values.items()):
        docker_command.extend(["--env", f"{key}={value}"])
    if condition == "S0":
        docker_command.extend(
            ["--volume", f"{SKILL_DIR.resolve()}:/workspace/.opencode/skills/global-geochemical-atlas:ro"]
        )
    docker_command.append(image)
    docker_command.extend(command)
    child_env = os.environ.copy()
    child_env.update(host_environment)
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        process = subprocess.Popen(docker_command, stdout=stdout, stderr=stderr, text=True, env=child_env)
        try:
            raw_exit = process.wait(timeout=profile.timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            subprocess.run(["docker", "kill", name], check=False, capture_output=True)
            raw_exit = process.wait(timeout=30)
    return raw_exit, timed_out, round(time.monotonic() - started, 6)


def candidate_status(raw_exit: int, timed_out: bool, missing: list[str]) -> tuple[int, str]:
    if timed_out:
        return 71, "timed_out"
    if raw_exit in {137, 143}:
        return 72, "resource_exceeded"
    if raw_exit != 0:
        return (raw_exit if raw_exit in E1_CODES else 70), E1_STATUS.get(raw_exit, "failed")
    if missing:
        return 74, "failed"
    return 0, "success"


def ineligible_score(run_id: str, status: str, rubric: Path, reason_path: str) -> dict[str, Any]:
    alignment = load_json(ALIGNMENT_PATH)
    return {
        "schema_version": "1.0.0",
        "eval_version": alignment["e1_eval_version"],
        "contract_sha256": alignment["e1_contract_sha256"],
        "run_id": run_id,
        "scorer_version": "6.0.0",
        "rubric_sha256": sha256_file(rubric),
        "candidate_status": status,
        "score_status": "ineligible",
        "hard_gate_passed": False,
        "dimensions": [],
        "total_score": None,
        "checks_path": reason_path,
        "evidence": [reason_path],
        "computed_at": utc_now(),
    }


def validate_review(path: Path, label: str) -> None:
    if not path.is_file():
        raise CampaignError(f"{label} does not exist: {path}")
    try:
        value = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise CampaignError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"{label} must contain a JSON object: {path}")


def locate_llm_report(
    directory: Path | None,
    run_id: str,
    group: str,
    question: str,
    condition: str,
    repeat: int,
) -> Path | None:
    if directory is None:
        return None
    candidates = (
        directory / f"{run_id}.json",
        directory / group / question / condition / f"repeat-{repeat}.json",
        directory / f"{group}-{question}-{condition}-r{repeat}.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CampaignError(
        "LLM grader report is missing; expected one of: " + ", ".join(str(path) for path in candidates)
    )


def grade_run(
    source: Path,
    run_dir: Path,
    run_id: str,
    status: str,
    score_path: Path,
    *,
    llm_report: Path | None,
    static_review: Path | None,
) -> tuple[dict[str, Any], str | None, str | None, bool]:
    objective = run_dir / "objective_report.json"
    rubric = source / "rubric.json"
    if status not in {"success", "partial_success"}:
        score = ineligible_score(run_id, status, rubric, "runner_metadata.json")
        atomic_json(score_path, score)
        (run_dir / "grader.stdout").write_text("", encoding="utf-8")
        (run_dir / "grader.stderr").write_text("candidate was ineligible; grader not run\n", encoding="utf-8")
        return score, None, None, False
    grade = subprocess.run(
        [sys.executable, str(EVALUATION_ROOT / "tools" / "grade_task.py"), str(source), str(run_dir / "submission"), "--output", str(objective)],
        check=False,
        capture_output=True,
        text=True,
    )
    (run_dir / "grader.stdout").write_text(grade.stdout, encoding="utf-8")
    (run_dir / "grader.stderr").write_text(grade.stderr, encoding="utf-8")
    if grade.returncode != 0 or not objective.is_file():
        score = ineligible_score(run_id, "failed", rubric, "runner_metadata.json")
        atomic_json(score_path, score)
        return score, None, None, True
    finalize_command = [
        sys.executable,
        str(EVALUATION_ROOT / "tools" / "finalize_score.py"),
        "--objective-report",
        str(objective),
        "--rubric",
        str(rubric),
        "--run-id",
        run_id,
        "--candidate-status",
        status,
        "--objective-evidence",
        "objective_report.json",
    ]
    llm_name = None
    if llm_report is not None:
        validate_review(llm_report, "LLM grader report")
        llm_name = "llm_grader_report.json"
        shutil.copy2(llm_report, run_dir / llm_name)
        finalize_command.extend(["--llm-report", str(run_dir / llm_name), "--llm-evidence", llm_name])
    static_name = None
    if static_review is not None:
        validate_review(static_review, "static review")
        static_name = "static_review.json"
        shutil.copy2(static_review, run_dir / static_name)
        finalize_command.extend(["--static-review", str(run_dir / static_name), "--static-evidence", static_name])
    finalize_command.extend(["--output", str(score_path)])
    finalize = subprocess.run(
        finalize_command,
        check=False,
        capture_output=True,
        text=True,
    )
    (run_dir / "finalize.stdout").write_text(finalize.stdout, encoding="utf-8")
    (run_dir / "finalize.stderr").write_text(finalize.stderr, encoding="utf-8")
    if finalize.returncode != 0 or not score_path.is_file():
        score = ineligible_score(run_id, "failed", rubric, "runner_metadata.json")
        atomic_json(score_path, score)
        return score, llm_name, static_name, True
    return load_json(score_path), llm_name, static_name, False


def run_one(
    *,
    campaign_root: Path,
    group: str,
    campaign_id: str,
    question: str,
    condition: str,
    repeat: int,
    image: str,
    image_id: str,
    model: str,
    model_variant: str,
    temperature: float,
    provider_profile: str,
    api_key_env: str,
    provider_base_url: str,
    agent_command: list[str],
    network: NetworkHandle,
    profile: RuntimeProfile,
    required_paths: list[str],
    llm_report_dir: Path | None,
    static_review: Path | None,
) -> dict[str, Any]:
    run_id = f"{safe_slug(campaign_id)}-{question.casefold()}-{condition.casefold()}-r{repeat}"
    run_dir = campaign_root / group / question / condition / f"repeat-{repeat}"
    if run_dir.exists():
        raise CampaignError(f"run directory already exists: {run_dir}")
    task_dir = run_dir / "task"
    source, split, task_hash = prepare_task_bundle(question, task_dir)
    workspace = run_dir / "workspace"
    submission = run_dir / "submission"
    workspace.mkdir()
    (submission / "artifacts").mkdir(parents=True)
    stdout_path = run_dir / "candidate.stdout"
    stderr_path = run_dir / "candidate.stderr"
    fingerprint = pair_fingerprint(
        task_hash=task_hash,
        image_id=image_id,
        model=model,
        model_variant=model_variant,
        temperature=temperature,
        provider_profile=provider_profile,
        repeat=repeat,
        profile=profile,
        network=network.mode,
    )
    environment_names = []
    environment_values: dict[str, str] = {}
    host_environment: dict[str, str] = {}
    if "/run_opencode.py" in " ".join(agent_command):
        if not os.environ.get(api_key_env):
            raise CampaignError(f"host environment variable is empty: {api_key_env}")
        environment_names.append("EVAL_API_KEY")
        host_environment["EVAL_API_KEY"] = os.environ[api_key_env]
        environment_values.update(
            {
                "EVAL_PROVIDER_BASE_URL": provider_base_url,
                "EVAL_PROVIDER_MODEL_ID": model,
                "EVAL_PROVIDER_PROFILE": provider_profile,
                "EVAL_MODEL_VARIANT": model_variant,
                "EVAL_TEMPERATURE": str(temperature),
            }
        )
    container_name = f"gga-{safe_slug(run_id)}-{uuid.uuid4().hex[:6]}"
    started_at = utc_now()
    raw_exit, timed_out, duration = execute_container(
        name=container_name,
        image=image,
        command=agent_command,
        task_dir=task_dir,
        workspace=workspace,
        submission=submission,
        condition=condition,
        network=network,
        profile=profile,
        environment_names=environment_names,
        environment_values=environment_values,
        host_environment=host_environment,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )
    log_secret_redacted = any(
        [redact_file(path, host_environment.values()) for path in (stdout_path, stderr_path)]
    )
    secret_redaction_files = redact_tree(submission, host_environment.values())
    artifacts, missing = artifact_inventory(submission, required_paths)
    exit_code, status = candidate_status(raw_exit, timed_out, missing)
    if secret_redaction_files:
        exit_code, status = 74, "failed"
    metadata = {
        "schema_version": "ai4s-docker-runner-metadata-v1",
        "run_id": run_id,
        "condition": condition,
        "repeat": repeat,
        "pair_fingerprint": fingerprint,
        "task": question,
        "task_bundle_sha256": task_hash,
        "image": image,
        "image_id": image_id,
        "model": model,
        "model_variant": model_variant or None,
        "temperature": temperature,
        "provider_profile": provider_profile,
        "thinking": "disabled" if provider_profile == "qwen-anthropic" else None,
        "network_mode": network.mode,
        "resources": profile.__dict__,
        "skill_mounted": condition == "S0",
        "skill_sha256": hash_tree(SKILL_DIR) if condition == "S0" else None,
        "started_at": started_at,
        "ended_at": utc_now(),
        "execution_seconds": duration,
        "download_seconds": 0.0,
        "cause_exit_code": raw_exit,
        "exit_code": exit_code,
        "status": status,
        "artifacts": artifacts,
        "missing_artifacts": missing,
        "secret_redaction_files": secret_redaction_files,
        "log_secret_redacted": log_secret_redacted,
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
        "provider_host": urlsplit(provider_base_url).hostname if provider_base_url else None,
        "secret_policy": "API keys are inherited by name or injected in process environment and are never serialized.",
    }
    atomic_json(run_dir / "runner_metadata.json", metadata)
    score_path = run_dir / "score.json"
    llm_source = locate_llm_report(llm_report_dir, run_id, group, question, condition, repeat)
    score, llm_name, static_name, scorer_failed = grade_run(
        source,
        run_dir,
        run_id,
        status,
        score_path,
        llm_report=llm_source,
        static_review=static_review,
    )
    effective_exit_code = 75 if scorer_failed else exit_code
    effective_status = "failed" if scorer_failed else status
    metadata["candidate_exit_code"] = exit_code
    metadata["candidate_status"] = status
    metadata["scorer_failed"] = scorer_failed
    metadata["exit_code"] = effective_exit_code
    metadata["status"] = effective_status
    atomic_json(run_dir / "runner_metadata.json", metadata)
    record = {
        "run_id": run_id,
        "task_id": question,
        "split": split,
        "variant": condition,
        "repeat": repeat,
        "pair_fingerprint": fingerprint,
        "model": model,
        "model_parameters": {
            "variant": model_variant or None,
            "temperature": temperature,
            "thinking": "disabled" if provider_profile == "qwen-anthropic" else None,
        },
        "skill_version": metadata["skill_sha256"],
        "benchmark_version": load_json(ALIGNMENT_PATH)["benchmark_version"],
        "started_at": metadata["started_at"],
        "ended_at": metadata["ended_at"],
        "status": effective_status,
        "exit_code": effective_exit_code,
        "cause_exit_code": raw_exit,
        "sandbox_image": image_id,
        "artifact_dir": str((run_dir / "submission").relative_to(campaign_root)),
        "stdout_log": str(stdout_path.relative_to(campaign_root)),
        "stderr_log": str(stderr_path.relative_to(campaign_root)),
        "objective_report": str((run_dir / "objective_report.json").relative_to(campaign_root)),
        "llm_grader_prompt": None,
        "llm_grader_raw": None,
        "llm_grader_report": (
            str((run_dir / llm_name).relative_to(campaign_root)) if llm_name is not None else None
        ),
        "static_review": (
            str((run_dir / static_name).relative_to(campaign_root)) if static_name is not None else None
        ),
        "score_path": str(score_path.relative_to(campaign_root)),
        "score": score,
        "redline_events": (
            [{"id": "secret_material_in_submission", "consequence": "acceptance_fail"}]
            if secret_redaction_files
            else []
        ),
        "notes": ["local competition-proxy task; current Q01-Q24 are not a strict hidden set"],
    }
    atomic_json(run_dir / "run_record.json", record)
    return record


def build_image(args: argparse.Namespace) -> int:
    docker_available()
    command = [
        "docker",
        "build",
        "--build-arg",
        f"OPENCODE_VERSION={args.opencode_version}",
        "--build-arg",
        f"PYTHON_IMAGE={args.python_image}",
        "--tag",
        args.image,
        str(DOCKER_ROOT),
    ]
    if not args.no_pull:
        command.insert(2, "--pull")
    if args.no_cache:
        command.insert(2, "--no-cache")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        return 73
    print(json.dumps({"status": "PASS", "image": args.image, "image_id": image_identity(args.image)}))
    return 0


def run_stage(args: argparse.Namespace) -> int:
    if args.refresh_downloads and args.network != "whitelist" and not args.host:
        raise CampaignError("--refresh-downloads requires --network whitelist in Docker mode")
    adapter_command = [
        sys.executable,
        str(REPO_ROOT / "evaluation_lyf" / "suite_adapter.py"),
        "--suite",
        args.suite,
        "--output-dir",
        str(args.output_dir),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--stress-records",
        str(args.stress_records),
        "--real-max-source-samples",
        str(args.real_max_source_samples),
    ]
    if args.d2_script:
        adapter_command.extend(["--d2-script", str(args.d2_script)])
    if args.expanded:
        adapter_command.append("--expanded")
    if args.refresh_downloads:
        adapter_command.append("--refresh-downloads")
    if args.host:
        return subprocess.run(adapter_command, check=False).returncode

    docker_available()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise CampaignError("--output-dir must be new or empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    container_adapter = [
        "python",
        "/repo/evaluation_lyf/suite_adapter.py",
        "--suite",
        args.suite,
        "--output-dir",
        "/results",
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--stress-records",
        str(args.stress_records),
        "--real-max-source-samples",
        str(args.real_max_source_samples),
    ]
    candidate_mount = None
    if args.d2_script:
        candidate = args.d2_script.resolve()
        if not candidate.is_file():
            raise CampaignError(f"--d2-script does not exist: {candidate}")
        candidate_mount = candidate
        container_adapter.extend(["--d2-script", "/candidate/candidate_d2.py"])
    if args.expanded:
        container_adapter.append("--expanded")
    if args.refresh_downloads:
        container_adapter.append("--refresh-downloads")

    rules = read_allowlist(args.allowlist, args.allow_host)
    network = start_network(args.image, f"stage-{args.suite}", rules, args.network)
    container_name = f"gga-stage-{safe_slug(args.suite)}-{uuid.uuid4().hex[:8]}"
    docker_command = [
        "docker",
        "run",
        "--rm",
        "--name",
        container_name,
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cpus",
        "2",
        "--memory",
        "4g",
        "--memory-swap",
        "4g",
        "--pids-limit",
        "256",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,size=1g",
        "--volume",
        f"{REPO_ROOT.resolve()}:/repo:ro",
        "--volume",
        f"{args.output_dir.resolve()}:/results:rw",
        "--workdir",
        "/repo",
    ]
    if candidate_mount:
        docker_command.extend(["--volume", f"{candidate_mount}:/candidate/candidate_d2.py:ro"])
    if network.mode == "offline":
        docker_command.extend(["--network", "none"])
    else:
        docker_command.extend(
            [
                "--network",
                str(network.internal),
                "--env",
                "HTTP_PROXY=http://eval-proxy:8080",
                "--env",
                "HTTPS_PROXY=http://eval-proxy:8080",
                "--env",
                "http_proxy=http://eval-proxy:8080",
                "--env",
                "https_proxy=http://eval-proxy:8080",
            ]
        )
    docker_command.append(args.image)
    docker_command.extend(container_adapter)
    try:
        try:
            completed = subprocess.run(docker_command, check=False, timeout=args.timeout_seconds + 60)
            cause_exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", container_name], check=False, capture_output=True)
            cause_exit_code = 71
    finally:
        cleanup_network(network)
    status = cause_exit_code if cause_exit_code in {0, 2, 71} else 73
    atomic_json(
        args.output_dir / "docker_runner.json",
        {
            "schema_version": "evaluation-lyf-docker-runner-v1",
            "image": args.image,
            "image_id": image_identity(args.image),
            "network": args.network,
            "resources": RuntimeProfile(timeout_seconds=args.timeout_seconds).__dict__,
            "exit_code": status,
            "cause_exit_code": cause_exit_code,
            "completed_at": utc_now(),
        },
    )
    return status


def run_campaign(args: argparse.Namespace) -> int:
    alignment = load_json(ALIGNMENT_PATH)
    required_paths = [item["path"] for item in alignment["submission"]["required_artifacts"]]
    tasks = parse_tasks(args.tasks)
    conditions = parse_conditions(args.conditions)
    if not 1 <= args.repeats <= 3:
        raise CampaignError("--repeats must be between 1 and 3")
    if not 0.0 <= args.temperature <= 2.0:
        raise CampaignError("--temperature must be between 0 and 2")
    validate_provider_profile(
        args.provider_profile,
        args.provider_base_url,
        args.model,
        args.temperature,
    )
    if args.static_review:
        validate_review(args.static_review, "static review")
    if args.llm_report_dir and not args.llm_report_dir.is_dir():
        raise CampaignError(f"--llm-report-dir is not a directory: {args.llm_report_dir}")
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise CampaignError("--output-dir must be new or empty")
    docker_available()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    image_id = image_identity(args.image)
    provider_host = urlsplit(args.provider_base_url).hostname if args.provider_base_url else None
    if args.agent == "opencode":
        if not provider_host or urlsplit(args.provider_base_url).scheme != "https":
            raise CampaignError("OpenCode runs require an absolute HTTPS --provider-base-url")
        agent_command = ["python", "/opt/evaluation/container/run_opencode.py"]
        if args.network == "offline":
            raise CampaignError("OpenCode model calls require --network whitelist")
    else:
        agent_command = ["python", "/opt/evaluation/container/mock_agent.py"]
    extra_hosts = list(args.allow_host)
    if provider_host:
        extra_hosts.append(provider_host)
    rules = read_allowlist(args.allowlist, extra_hosts)
    profile = RuntimeProfile(timeout_seconds=args.timeout_seconds)
    campaign_id = args.campaign_id or f"campaign-{int(time.time())}"
    plan = {
        "schema_version": "ai4s-docker-campaign-plan-v1",
        "campaign_id": campaign_id,
        "tasks": tasks,
        "conditions": conditions,
        "repeats": args.repeats,
        "model": args.model,
        "model_variant": args.model_variant or None,
        "temperature": args.temperature,
        "provider_profile": args.provider_profile,
        "thinking": "disabled" if args.provider_profile == "qwen-anthropic" else None,
        "supplemental_model": args.supplemental_model or None,
        "supplemental_model_variant": args.supplemental_model_variant or None,
        "image": args.image,
        "image_id": image_id,
        "network": args.network,
        "allowlist": rules,
        "resources": profile.__dict__,
        "official_claim_boundary": (
            "The local tasks reproduce the public execution contract but are not the organizer's hidden set. "
            "The exact official anti-cheat rules and final uplift synthesis are not public."
        ),
    }
    atomic_json(args.output_dir / "campaign_plan.json", plan)
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    network = start_network(args.image, campaign_id, rules, args.network)
    records: list[dict[str, Any]] = []
    supplemental_records: list[dict[str, Any]] = []
    try:
        for question in tasks:
            for repeat in range(1, args.repeats + 1):
                for condition in conditions:
                    record = run_one(
                        campaign_root=args.output_dir,
                        group="main",
                        campaign_id=campaign_id,
                        question=question,
                        condition=condition,
                        repeat=repeat,
                        image=args.image,
                        image_id=image_id,
                        model=args.model,
                        model_variant=args.model_variant,
                        temperature=args.temperature,
                        provider_profile=args.provider_profile,
                        api_key_env=args.api_key_env,
                        provider_base_url=args.provider_base_url,
                        agent_command=agent_command,
                        network=network,
                        profile=profile,
                        required_paths=required_paths,
                        llm_report_dir=args.llm_report_dir,
                        static_review=args.static_review,
                    )
                    records.append(record)
        if args.supplemental_model:
            supplemental_campaign_id = f"{campaign_id}-supplemental"
            for question in tasks:
                for condition in conditions:
                    record = run_one(
                        campaign_root=args.output_dir,
                        group="supplemental",
                        campaign_id=supplemental_campaign_id,
                        question=question,
                        condition=condition,
                        repeat=1,
                        image=args.image,
                        image_id=image_id,
                        model=args.supplemental_model,
                        model_variant=args.supplemental_model_variant,
                        temperature=args.temperature,
                        provider_profile=args.provider_profile,
                        api_key_env=args.api_key_env,
                        provider_base_url=args.provider_base_url,
                        agent_command=agent_command,
                        network=network,
                        profile=profile,
                        required_paths=required_paths,
                        llm_report_dir=args.llm_report_dir,
                        static_review=args.static_review,
                    )
                    supplemental_records.append(record)
    finally:
        cleanup_network(network)
    raw_path = args.output_dir / "runs.jsonl"
    raw_path.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records), encoding="utf-8")
    supplemental_path = None
    if supplemental_records:
        supplemental_path = args.output_dir / "supplemental_runs.jsonl"
        supplemental_path.write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in supplemental_records),
            encoding="utf-8",
        )
    aggregate_status = "not_requested"
    if set(conditions) == {"B0", "S0"} and args.repeats == 3:
        aggregate = subprocess.run(
            [
                sys.executable,
                str(EVALUATION_ROOT / "tools" / "aggregate_runs.py"),
                str(raw_path),
                "--csv-output",
                str(args.output_dir / "summary.csv"),
                "--json-output",
                str(args.output_dir / "summary.json"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        (args.output_dir / "aggregate.stdout").write_text(aggregate.stdout, encoding="utf-8")
        (args.output_dir / "aggregate.stderr").write_text(aggregate.stderr, encoding="utf-8")
        aggregate_status = "pass" if aggregate.returncode == 0 else "fail"
    summary = {
        "schema_version": "ai4s-docker-campaign-result-v1",
        "campaign_id": campaign_id,
        "runs": len(records),
        "successful_runs": sum(item["status"] == "success" for item in records),
        "supplemental_runs": len(supplemental_records),
        "successful_supplemental_runs": sum(item["status"] == "success" for item in supplemental_records),
        "aggregate_status": aggregate_status,
        "completed_at": utc_now(),
        "records": raw_path.name,
        "supplemental_records": supplemental_path.name if supplemental_path else None,
    }
    atomic_json(args.output_dir / "campaign_result.json", summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    all_records = records + supplemental_records
    return 0 if all(item["status"] == "success" for item in all_records) and aggregate_status != "fail" else 2


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build-image", help="build the frozen OpenCode sandbox image")
    build.add_argument("--image", default="global-geochemical-eval:local")
    build.add_argument("--opencode-version", default="1.18.14")
    build.add_argument("--python-image", default="python:3.11.9-slim-bookworm")
    build.add_argument("--no-cache", action="store_true")
    build.add_argument("--no-pull", action="store_true", help="use only locally available base images")
    build.set_defaults(func=build_image)

    stage = sub.add_parser("stage", help="run an evaluation_lyf scientific gate")
    stage.add_argument("--image", default="global-geochemical-eval:local")
    stage.add_argument(
        "--suite",
        choices=("source-truth", "isolated", "real", "global", "completion", "all"),
        required=True,
    )
    stage.add_argument("--output-dir", type=Path, required=True)
    stage.add_argument("--timeout-seconds", type=int, default=900)
    stage.add_argument("--stress-records", type=int, default=10_000)
    stage.add_argument("--real-max-source-samples", type=int, default=20)
    stage.add_argument("--d2-script", type=Path)
    stage.add_argument("--expanded", action="store_true")
    stage.add_argument("--refresh-downloads", action="store_true")
    stage.add_argument("--network", choices=("offline", "whitelist"), default="offline")
    stage.add_argument("--allowlist", type=Path, default=DOCKER_ROOT / "allowlist.txt")
    stage.add_argument("--allow-host", action="append", default=[])
    stage.add_argument("--host", action="store_true", help="diagnostic fallback: bypass Docker isolation")
    stage.set_defaults(func=run_stage)

    campaign = sub.add_parser("run", help="run an isolated competition-proxy campaign")
    campaign.add_argument("--image", default="global-geochemical-eval:local")
    campaign.add_argument("--campaign-id")
    campaign.add_argument("--tasks", default="Q01")
    campaign.add_argument("--conditions", default="B0,S0")
    campaign.add_argument("--repeats", type=int, default=3)
    campaign.add_argument("--model", default="qwen3.8-max")
    campaign.add_argument("--model-variant", default="")
    campaign.add_argument("--temperature", type=float, default=0.0)
    campaign.add_argument("--supplemental-model", default="", help="optional second model; each selected B0/S0 task runs once")
    campaign.add_argument("--supplemental-model-variant", default="")
    campaign.add_argument("--provider-base-url", default="")
    campaign.add_argument(
        "--provider-profile",
        choices=("openai-compatible", "qwen-anthropic"),
        default="openai-compatible",
        help="freeze the OpenCode transport and model options for the selected gateway",
    )
    campaign.add_argument("--api-key-env", default="EVAL_API_KEY")
    campaign.add_argument("--agent", choices=("opencode", "mock"), default="opencode")
    campaign.add_argument("--network", choices=("offline", "whitelist"), default="whitelist")
    campaign.add_argument("--allowlist", type=Path, default=DOCKER_ROOT / "allowlist.txt")
    campaign.add_argument("--allow-host", action="append", default=[])
    campaign.add_argument("--llm-report-dir", type=Path, help="optional independent per-run grader reports")
    campaign.add_argument("--static-review", type=Path, help="optional frozen static review JSON")
    campaign.add_argument("--timeout-seconds", type=int, default=900)
    campaign.add_argument("--output-dir", type=Path, required=True)
    campaign.add_argument("--dry-run", action="store_true")
    campaign.set_defaults(func=run_campaign)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.func(args)
    except (CampaignError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "environment_invalid", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 73


if __name__ == "__main__":
    raise SystemExit(main())
