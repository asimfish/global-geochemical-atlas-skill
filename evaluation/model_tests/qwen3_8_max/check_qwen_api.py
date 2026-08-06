#!/usr/bin/env python3
"""Verify Qwen3.8-Max Chat Completions and native tool-calling behavior."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai_compatible_api import ChatApiError, OpenAICompatibleChatClient


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("QWEN_BASE_URL"))
    parser.add_argument("--model", default=os.getenv("QWEN_MODEL", "qwen3.8-max"))
    parser.add_argument("--api-key-env", default="QWEN_API_KEY", help="Environment variable containing the key; never pass the key as an argument")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--chat-only", action="store_true", help="Only test text chat; formal benchmark runs require tool calls")
    parser.add_argument("--output", type=Path, default=Path("/tmp/qwen3.8-max-api-smoke.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.base_url:
        print("error: set QWEN_BASE_URL or pass --base-url", file=sys.stderr)
        return 73
    if not args.base_url.startswith(("http://", "https://")) or args.timeout <= 0:
        print("error: base URL or timeout is invalid", file=sys.stderr)
        return 73
    api_key = os.getenv(args.api_key_env, "")
    if not api_key and not args.base_url.startswith(("http://127.0.0.1", "http://localhost")):
        print(f"error: cloud endpoint requires {args.api_key_env}", file=sys.stderr)
        return 73
    if not api_key:
        api_key = "EMPTY"

    client = OpenAICompatibleChatClient(base_url=args.base_url, api_key=api_key, timeout_seconds=args.timeout)
    messages = [
        {"role": "system", "content": "You are an API conformance probe. Follow the requested output exactly."},
        {"role": "user", "content": "Reply with the single token QWEN_API_OK."},
    ]
    payload: dict[str, Any] = {
        "model": args.model,
        "messages": messages,
        "temperature": 0.6,
        "max_completion_tokens": 512,
        "reasoning_effort": "low",
        "preserve_thinking": True,
    }
    if not args.chat_only:
        messages[-1]["content"] = "Call benchmark_api_probe exactly once with value QWEN_TOOL_OK. Do not answer without calling the tool."
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "benchmark_api_probe",
                    "description": "Confirm that the endpoint returns a native OpenAI-compatible tool call.",
                    "parameters": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": False,
                    },
                },
            }
        ]
        payload["tool_choice"] = "auto"

    started_at = timestamp()
    start = time.monotonic()
    report: dict[str, Any] = {
        "schema_version": "qwen-api-smoke.v1",
        "started_at": started_at,
        "base_url": args.base_url,
        "model": args.model,
        "mode": "chat_only" if args.chat_only else "chat_and_tool_call",
        "api_key_source": args.api_key_env,
        "api_key_recorded": False,
    }
    try:
        response = client.create(payload)
        message = response["choices"][0]["message"]
        report["request_id"] = response.get("id")
        report["usage"] = response.get("usage")
        if args.chat_only:
            content = message.get("content")
            passed = isinstance(content, str) and "QWEN_API_OK" in content
            report["observed_content"] = content[:500] if isinstance(content, str) else None
        else:
            tool_calls = message.get("tool_calls")
            passed = False
            observed = []
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    arguments = function.get("arguments")
                    try:
                        decoded_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except json.JSONDecodeError:
                        decoded_arguments = None
                    observed.append({"name": function.get("name"), "arguments": decoded_arguments})
                    if function.get("name") == "benchmark_api_probe" and isinstance(decoded_arguments, dict) and decoded_arguments.get("value") == "QWEN_TOOL_OK":
                        passed = True
            report["observed_tool_calls"] = observed
        report["status"] = "pass" if passed else "fail"
        report["latency_seconds"] = round(time.monotonic() - start, 3)
        report["ended_at"] = timestamp()
        atomic_json(args.output, report)
        print(json.dumps({"status": report["status"], "report": str(args.output), "model": args.model}, ensure_ascii=False))
        return 0 if passed else 74
    except ChatApiError as exc:
        report.update(
            {
                "status": "error",
                "latency_seconds": round(time.monotonic() - start, 3),
                "ended_at": timestamp(),
                "error": str(exc),
                "http_status": exc.status_code,
                "response_excerpt": exc.response_body,
            }
        )
        atomic_json(args.output, report)
        print(f"API check failed: {exc}; report={args.output}", file=sys.stderr)
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
