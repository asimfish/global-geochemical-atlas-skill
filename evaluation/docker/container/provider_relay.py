#!/usr/bin/env python3
"""Credential-isolating relay for the frozen OpenAI-compatible provider."""

from __future__ import annotations

import hmac
import http.client
import json
import math
import os
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import SplitResult, urlsplit, urlunsplit


MAX_REQUEST_BYTES = 16 * 1024 * 1024
MAX_HEADER_BYTES = 64 * 1024
UPSTREAM_TIMEOUT_SECONDS = 300
RESPONSE_HEADERS = {
    "cache-control",
    "content-encoding",
    "content-length",
    "content-type",
    "date",
    "etag",
    "retry-after",
    "x-request-id",
}
ALLOWED_PROVIDER_PATHS = {"/chat/completions", "/responses"}
THINKING_OVERRIDE_KEYS = {
    "enable_thinking",
    "reasoning",
    "reasoning_effort",
    "thinking",
}
DEFAULT_MAX_REQUESTS = 512
DEFAULT_MAX_SECONDS = 900


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"required environment variable is empty: {name}")
    return value


def parse_upstream(value: str) -> SplitResult:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "EVAL_UPSTREAM_BASE_URL must be an absolute credential-free HTTPS URL"
        )
    return parsed


def upstream_target(base: SplitResult, request_path: str) -> str:
    incoming = urlsplit(request_path)
    if incoming.scheme or incoming.netloc or not incoming.path.startswith("/"):
        raise ValueError("relay request target must be an origin-form path")
    if incoming.query:
        raise ValueError("relay request query parameters are not allowed")
    if incoming.path not in ALLOWED_PROVIDER_PATHS:
        raise ValueError("relay path is not an allowed model inference endpoint")
    base_path = base.path.rstrip("/")
    path = f"{base_path}{incoming.path}"
    return urlunsplit((base.scheme, base.netloc, path, "", ""))


def _json_object_no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"request JSON contains duplicate key: {key}")
        value[key] = item
    return value


def validate_payload(
    body: bytes,
    *,
    expected_model: str,
    expected_temperature: float,
    thinking_mode: str,
) -> dict[str, object]:
    try:
        payload = json.loads(
            body.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object_no_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("provider request body must be one UTF-8 JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("provider request body must be a JSON object")
    if payload.get("model") != expected_model:
        raise ValueError("provider request model does not match the frozen model")
    temperature = payload.get("temperature")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(float(temperature))
        or float(temperature) != expected_temperature
    ):
        raise ValueError(
            "provider request temperature does not match the frozen temperature"
        )
    if thinking_mode == "not_configured":
        overrides = sorted(
            THINKING_OVERRIDE_KEYS & {str(key).casefold() for key in payload}
        )
        if overrides:
            raise ValueError(
                "provider request contains a thinking override forbidden by the frozen profile: "
                + ", ".join(overrides)
            )
    else:
        raise ValueError(
            f"relay does not implement frozen thinking mode: {thinking_mode}"
        )
    return payload


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "evaluation-provider-relay"
    upstream: SplitResult
    relay_token: str
    upstream_api_key: str
    expected_model: str
    expected_temperature: float
    thinking_mode: str

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            self._authorize()
            length = self._content_length()
            body = self.rfile.read(length)
            self.server.consume_request()  # type: ignore[attr-defined]
            validate_payload(
                body,
                expected_model=self.expected_model,
                expected_temperature=self.expected_temperature,
                thinking_mode=self.thinking_mode,
            )
            self._forward(body)
        except ValueError as exc:
            self._error(400, str(exc))
        except (OSError, http.client.HTTPException) as exc:
            self._error(502, f"upstream request failed: {type(exc).__name__}")

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        self._error(405, "only POST is allowed")

    def _authorize(self) -> None:
        expected = f"Bearer {self.relay_token}"
        supplied = self.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, expected):
            raise ValueError("invalid relay authorization")

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise ValueError("Content-Length is required")
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("invalid Content-Length") from exc
        if value < 0 or value > MAX_REQUEST_BYTES:
            raise ValueError(f"request body exceeds {MAX_REQUEST_BYTES} bytes")
        if (
            sum(len(key) + len(value) for key, value in self.headers.items())
            > MAX_HEADER_BYTES
        ):
            raise ValueError("request headers are too large")
        return value

    def _forward(self, body: bytes) -> None:
        target = upstream_target(self.upstream, self.path)
        parsed = urlsplit(target)
        connection = http.client.HTTPSConnection(
            parsed.hostname,
            parsed.port or 443,
            timeout=UPSTREAM_TIMEOUT_SECONDS,
        )
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        headers = {
            "Accept": self.headers.get("Accept", "application/json"),
            "Authorization": f"Bearer {self.upstream_api_key}",
            "Content-Type": self.headers.get("Content-Type", "application/json"),
            "User-Agent": "global-geochemical-evaluation-relay/1",
        }
        try:
            connection.request("POST", path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.casefold() in RESPONSE_HEADERS:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            while chunk := response.read(64 * 1024):
                self.wfile.write(chunk)
            self.wfile.flush()
        finally:
            connection.close()

    def _error(self, status: int, message: str) -> None:
        body = f"{status} {message}\n".encode("utf-8", errors="replace")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_: str, *args: object) -> None:
        print(f"provider-relay {self.address_string()} {format_ % args}", flush=True)


class ThreadingRelay(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        max_requests: int,
        max_seconds: int,
    ) -> None:
        super().__init__(server_address, handler)
        self._request_limit = max_requests
        self._request_count = 0
        self._deadline = time.monotonic() + max_seconds
        self._request_lock = threading.Lock()

    def consume_request(self) -> None:
        with self._request_lock:
            if time.monotonic() > self._deadline:
                raise ValueError("provider relay capability has expired")
            if self._request_count >= self._request_limit:
                raise ValueError("provider relay request limit is exhausted")
            self._request_count += 1


def main() -> int:
    try:
        RelayHandler.upstream = parse_upstream(required("EVAL_UPSTREAM_BASE_URL"))
        RelayHandler.relay_token = required("EVAL_RELAY_TOKEN")
        RelayHandler.upstream_api_key = required("EVAL_UPSTREAM_API_KEY")
        RelayHandler.expected_model = required("EVAL_UPSTREAM_MODEL_ID")
        RelayHandler.expected_temperature = float(required("EVAL_UPSTREAM_TEMPERATURE"))
        if not math.isfinite(RelayHandler.expected_temperature):
            raise ValueError("EVAL_UPSTREAM_TEMPERATURE must be finite")
        RelayHandler.thinking_mode = required("EVAL_UPSTREAM_THINKING_MODE")
        port = int(os.environ.get("EVAL_RELAY_PORT", "8090"))
        if not 1 <= port <= 65535:
            raise ValueError("EVAL_RELAY_PORT is outside 1..65535")
        max_requests = int(
            os.environ.get("EVAL_RELAY_MAX_REQUESTS", str(DEFAULT_MAX_REQUESTS))
        )
        max_seconds = int(
            os.environ.get("EVAL_RELAY_MAX_SECONDS", str(DEFAULT_MAX_SECONDS))
        )
        if not 1 <= max_requests <= 10_000:
            raise ValueError("EVAL_RELAY_MAX_REQUESTS is outside 1..10000")
        if not 1 <= max_seconds <= DEFAULT_MAX_SECONDS:
            raise ValueError(
                f"EVAL_RELAY_MAX_SECONDS is outside 1..{DEFAULT_MAX_SECONDS}"
            )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 73
    with ThreadingRelay(
        ("0.0.0.0", port),
        RelayHandler,
        max_requests=max_requests,
        max_seconds=max_seconds,
    ) as server:
        print(f"provider relay listening on {port}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
