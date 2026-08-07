#!/usr/bin/env python3
"""Credential-isolating relay for the frozen OpenAI-compatible provider."""

from __future__ import annotations

import hmac
import http.client
import os
import socketserver
import sys
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
        raise ValueError("EVAL_UPSTREAM_BASE_URL must be an absolute credential-free HTTPS URL")
    return parsed


def upstream_target(base: SplitResult, request_path: str) -> str:
    incoming = urlsplit(request_path)
    if incoming.scheme or incoming.netloc or not incoming.path.startswith("/"):
        raise ValueError("relay request target must be an origin-form path")
    if incoming.path not in ALLOWED_PROVIDER_PATHS:
        raise ValueError("relay path is not an allowed model inference endpoint")
    base_path = base.path.rstrip("/")
    path = f"{base_path}{incoming.path}"
    return urlunsplit((base.scheme, base.netloc, path, incoming.query, ""))


class RelayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "evaluation-provider-relay"
    upstream: SplitResult
    relay_token: str
    upstream_api_key: str

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            self._authorize()
            length = self._content_length()
            body = self.rfile.read(length)
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
        if sum(len(key) + len(value) for key, value in self.headers.items()) > MAX_HEADER_BYTES:
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
        body = f'{status} {message}\n'.encode("utf-8", errors="replace")
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


def main() -> int:
    try:
        RelayHandler.upstream = parse_upstream(required("EVAL_UPSTREAM_BASE_URL"))
        RelayHandler.relay_token = required("EVAL_RELAY_TOKEN")
        RelayHandler.upstream_api_key = required("EVAL_UPSTREAM_API_KEY")
        port = int(os.environ.get("EVAL_RELAY_PORT", "8090"))
        if not 1 <= port <= 65535:
            raise ValueError("EVAL_RELAY_PORT is outside 1..65535")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 73
    with ThreadingRelay(("0.0.0.0", port), RelayHandler) as server:
        print(f"provider relay listening on {port}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
