#!/usr/bin/env python3
"""Small dependency-free client for an OpenAI-compatible Chat Completions API."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class ChatApiError(RuntimeError):
    """A transport, HTTP, or response-shape failure from the model endpoint."""

    message: str
    status_code: int | None = None
    response_body: str | None = None

    def __str__(self) -> str:
        status = f" (HTTP {self.status_code})" if self.status_code is not None else ""
        return f"{self.message}{status}"


def chat_completions_url(base_url: str) -> str:
    """Normalize either an API base URL or a full Chat Completions URL."""

    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


class OpenAICompatibleChatClient:
    """Call Chat Completions without adding an SDK dependency to the benchmark."""

    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: int = 180) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.endpoint = chat_completions_url(base_url)
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ChatApiError("model API rejected the request", exc.code, raw[:4000]) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ChatApiError(f"model API transport failed: {exc}") from exc

        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChatApiError("model API returned non-JSON", response_body=raw[:4000]) from exc
        if not isinstance(decoded, dict):
            raise ChatApiError("model API response must be a JSON object", response_body=raw[:4000])
        if "error" in decoded:
            raise ChatApiError("model API returned an error object", response_body=json.dumps(decoded["error"], ensure_ascii=False)[:4000])
        choices = decoded.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ChatApiError("model API response has no choices[0]", response_body=raw[:4000])
        if not isinstance(choices[0].get("message"), dict):
            raise ChatApiError("model API response has no choices[0].message", response_body=raw[:4000])
        return decoded


def assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields accepted when an assistant message is sent back to the API."""

    result: dict[str, Any] = {"role": "assistant", "content": message.get("content")}
    # Qwen3.8-Max requires complete reasoning_content history when
    # preserve_thinking is enabled during multi-step tool use.
    reasoning_content = message.get("reasoning_content")
    if isinstance(reasoning_content, str):
        result["reasoning_content"] = reasoning_content
    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        result["tool_calls"] = tool_calls
    return result
