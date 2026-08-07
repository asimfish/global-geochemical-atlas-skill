#!/usr/bin/env python3
"""Run one non-interactive OpenCode task without persisting credentials."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


WORKSPACE = Path("/workspace")
PROMPT = Path("/task/prompt.md")
CONFIG = WORKSPACE / "opencode.json"
SAFE_ID = re.compile(r"^[A-Za-z0-9._:/-]+$")
QWEN_ANTHROPIC_HOST = "token-plan.cn-beijing.maas.aliyuncs.com"
QWEN_ANTHROPIC_MODELS = {"qwen3.8-max", "qwen3-vl-plus", "glm-5.2"}


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"required environment variable is empty: {name}")
    return value


def provider_sdk_base_url(base_url: str, provider_profile: str) -> str:
    if provider_profile != "qwen-anthropic":
        return base_url
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != QWEN_ANTHROPIC_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path.rstrip("/") != "/apps/anthropic"
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "qwen-anthropic requires the approved HTTPS /apps/anthropic SDK base URL"
        )
    return base_url.rstrip("/") + "/v1"


def build_config(
    base_url: str,
    model_id: str,
    temperature: float,
    provider_profile: str = "openai-compatible",
) -> dict[str, object]:
    if provider_profile == "openai-compatible":
        provider_id = "eval"
        provider = {
            "npm": "@ai-sdk/openai-compatible",
            "name": "Frozen evaluation gateway",
            "options": {
                "apiKey": "{env:EVAL_API_KEY}",
                "baseURL": base_url,
            },
            "models": {model_id: {"name": model_id}},
        }
        agent = {"temperature": temperature}
    elif provider_profile == "qwen-anthropic":
        provider_id = "eval-anthropic"
        provider = {
            "npm": "@ai-sdk/anthropic",
            "name": "Frozen Qwen Anthropic-compatible gateway",
            "options": {
                "apiKey": "{env:EVAL_API_KEY}",
                # AI SDK appends /messages, while the competition URL is the
                # SDK base without the version segment.
                "baseURL": provider_sdk_base_url(base_url, provider_profile),
            },
            "models": {
                model_id: {
                    "name": model_id,
                    "options": {"thinking": {"type": "disabled"}},
                }
            },
        }
        agent = {
            "temperature": temperature,
            "thinking": {"type": "disabled"},
        }
    else:
        raise ValueError(f"unsupported provider profile: {provider_profile}")
    return {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{provider_id}/{model_id}",
        "agent": {"build": agent},
        "provider": {provider_id: provider},
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
        model_id = required("EVAL_PROVIDER_MODEL_ID")
        provider_profile = os.environ.get(
            "EVAL_PROVIDER_PROFILE", "openai-compatible"
        ).strip()
        if not os.environ.get("EVAL_API_KEY"):
            raise ValueError("EVAL_API_KEY is not set")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("EVAL_PROVIDER_BASE_URL must be an absolute HTTPS URL")
        if not SAFE_ID.fullmatch(model_id):
            raise ValueError("EVAL_PROVIDER_MODEL_ID contains unsafe characters")
        temperature = float(os.environ.get("EVAL_TEMPERATURE", "0"))
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("EVAL_TEMPERATURE must be between 0 and 2")
        if not PROMPT.is_file():
            raise ValueError(f"prompt is missing: {PROMPT}")
        prompt = PROMPT.read_text(encoding="utf-8")
        if not prompt.strip():
            raise ValueError("prompt is empty")
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        if provider_profile == "qwen-anthropic":
            provider_sdk_base_url(base_url, provider_profile)
            if model_id not in QWEN_ANTHROPIC_MODELS:
                raise ValueError("qwen-anthropic received an unsupported conversation model")
            if temperature != 0.6:
                raise ValueError("qwen-anthropic requires temperature=0.6")
        config = build_config(base_url, model_id, temperature, provider_profile)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        provider_id = "eval-anthropic" if provider_profile == "qwen-anthropic" else "eval"
        command = [
            "opencode",
            "run",
            "--pure",
            "--print-logs",
            "--format",
            "json",
            "--model",
            f"{provider_id}/{model_id}",
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
