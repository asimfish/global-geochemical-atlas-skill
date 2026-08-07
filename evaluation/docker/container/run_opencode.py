#!/usr/bin/env python3
"""Run one non-interactive OpenCode task without persisting credentials."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


EVALUATION_RUNTIME_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVALUATION_RUNTIME_ROOT))

from provider_profiles import load_provider_profile  # noqa: E402


WORKSPACE = Path("/workspace")
PROMPT = Path("/task/prompt.md")
CONFIG = WORKSPACE / "opencode.json"


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"required environment variable is empty: {name}")
    return value


def build_config(
    base_url: str,
    model_id: str,
    temperature: float,
    provider_profile_id: str = "openai-compatible",
) -> dict[str, object]:
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"eval/{model_id}",
        "agent": {"build": {"temperature": temperature}},
        "provider": {
            "eval": {
                "npm": "@ai-sdk/openai-compatible",
                "name": f"Frozen evaluation gateway ({provider_profile_id})",
                "options": {
                    "apiKey": "{env:EVAL_API_KEY}",
                    "baseURL": base_url,
                },
                "models": {model_id: {"name": model_id}},
            }
        },
        "permission": {
            "bash": "allow",
            "edit": "allow",
            "external_directory": "deny",
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "question": "deny",
            "read": "allow",
            "skill": {"*": "allow"},
            "task": "deny",
            "webfetch": "allow",
            "websearch": "deny",
        },
    }


def main() -> int:
    try:
        base_url = required("EVAL_PROVIDER_BASE_URL")
        upstream_base_url = required("EVAL_PROVIDER_UPSTREAM_BASE_URL")
        model_id = required("EVAL_PROVIDER_MODEL_ID")
        profile_id = required("EVAL_PROVIDER_PROFILE_ID")
        if not os.environ.get("EVAL_API_KEY"):
            raise ValueError("EVAL_API_KEY is not set")
        temperature = float(os.environ.get("EVAL_TEMPERATURE", "0"))
        thinking_mode = required("EVAL_THINKING_MODE")
        profile = load_provider_profile(profile_id)
        profile.verify_frozen_hashes(
            registry_sha256=required("EVAL_PROVIDER_REGISTRY_SHA256"),
            profile_sha256=required("EVAL_PROVIDER_PROFILE_SHA256"),
        )
        profile.validate_runtime(
            base_url=upstream_base_url,
            model=model_id,
            temperature=temperature,
            thinking_mode=thinking_mode,
            require_endpoint=True,
        )
        if profile.transport != "openai-compatible":
            raise ValueError(f"unsupported provider transport: {profile.transport}")
        if not PROMPT.is_file():
            raise ValueError(f"prompt is missing: {PROMPT}")
        prompt = PROMPT.read_text(encoding="utf-8")
        if not prompt.strip():
            raise ValueError("prompt is empty")
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        config = build_config(base_url, model_id, temperature, profile.profile_id)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        command = [
            "opencode",
            "run",
            "--pure",
            "--print-logs",
            "--format",
            "json",
            "--model",
            f"eval/{model_id}",
            "--dir",
            str(WORKSPACE),
        ]
        variant = os.environ.get("EVAL_MODEL_VARIANT", "").strip()
        if variant:
            command.extend(["--variant", variant])
        command.append(prompt)
        return subprocess.run(command, check=False).returncode
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "environment_invalid", "error": str(exc)}), file=sys.stderr)
        return 73


if __name__ == "__main__":
    raise SystemExit(main())
