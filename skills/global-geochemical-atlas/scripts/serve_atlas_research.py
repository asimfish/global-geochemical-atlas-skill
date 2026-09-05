#!/usr/bin/env python3
"""Serve one frozen atlas and its Auto-Research controller on loopback only."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import sys
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import auto_research

MAX_BODY_BYTES = 16_384
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{16,160}$")
RUN_ID_PATTERN = re.compile(r"^run-[0-9a-f]{20}$")


class ResearchServerError(RuntimeError):
    """Raised when the fixed server boundary is unsafe."""


def valid_host(value: str, port: int) -> bool:
    return value.casefold() in {f"127.0.0.1:{port}", f"localhost:{port}"}


def valid_origin(value: str | None, port: int) -> bool:
    if value is None:
        return True
    return value.casefold() in {
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    }


def safe_static_path(root: Path, request_path: str) -> Path | None:
    """Resolve a URL path below one fixed root without symlink traversal."""

    try:
        decoded = unquote(urlsplit(request_path).path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    relative = decoded.lstrip("/") or "interactive_map.html"
    if "\x00" in relative or Path(relative).is_absolute():
        return None
    candidate = root / relative
    try:
        resolved_root = root.resolve(strict=True)
        cursor = root.absolute()
        lexical_relative = candidate.absolute().relative_to(root.absolute())
        for part in lexical_relative.parts:
            cursor /= part
            if cursor.is_symlink():
                return None
        resolved = candidate.resolve(strict=True)
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(resolved_root):
        return None
    if not resolved.is_file():
        return None
    return resolved


class AtlasResearchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        atlas_dir: Path,
        research_root: Path,
        token: str,
    ) -> None:
        self.atlas_dir = atlas_dir.resolve(strict=True)
        self.research_root = research_root.resolve(strict=True)
        self.token = token
        self.used_nonces: set[str] = set()
        super().__init__(address, AtlasResearchHandler)


class AtlasResearchHandler(BaseHTTPRequestHandler):
    server: AtlasResearchServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Do not log request headers, tokens, bodies or fragment-bearing URLs.
        print(
            f"atlas-research: {self.command} {urlsplit(self.path).path}",
            file=sys.stderr,
        )

    def _json(self, status: HTTPStatus, value: MappingLike) -> None:
        body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self, *, mutating: bool) -> bool:
        port = int(self.server.server_address[1])
        if not valid_host(self.headers.get("Host", ""), port):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_host"})
            return False
        if not valid_origin(self.headers.get("Origin"), port):
            self._json(HTTPStatus.FORBIDDEN, {"error": "invalid_origin"})
            return False
        token = self.headers.get("X-GGA-Research-Token", "")
        if not secrets.compare_digest(token, self.server.token):
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "invalid_token"})
            return False
        if mutating:
            nonce = self.headers.get("X-GGA-Request-Nonce", "")
            if NONCE_PATTERN.fullmatch(nonce) is None:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_nonce"})
                return False
            if nonce in self.server.used_nonces:
                self._json(HTTPStatus.CONFLICT, {"error": "replayed_nonce"})
                return False
            if len(self.server.used_nonces) >= 10_000:
                self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": "nonce_capacity"})
                return False
            self.server.used_nonces.add(nonce)
        return True

    def _read_json(self) -> dict[str, Any] | None:
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "json_required"})
            return None
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._json(HTTPStatus.LENGTH_REQUIRED, {"error": "content_length_required"})
            return None
        if length < 2 or length > MAX_BODY_BYTES:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body_size"})
            return None
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json"})
            return None
        if not isinstance(value, dict):
            self._json(HTTPStatus.BAD_REQUEST, {"error": "json_object_required"})
            return None
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path.startswith("/api/v1/research-runs/"):
            if not self._authorized(mutating=False):
                return
            run_id = path.removeprefix("/api/v1/research-runs/")
            if RUN_ID_PATTERN.fullmatch(run_id) is None:
                self._json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                return
            run_dir = self.server.research_root / run_id
            if run_dir.is_symlink() or not run_dir.is_dir():
                self._json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                return
            state_path = run_dir / "state.json"
            if not state_path.is_file() or state_path.is_symlink():
                self._json(HTTPStatus.NOT_FOUND, {"error": "run_not_found"})
                return
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "state_unreadable"}
                )
                return
            self._json(HTTPStatus.OK, public_state(state))
            return
        static_path = safe_static_path(self.server.atlas_dir, self.path)
        if static_path is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        body = static_path.read_bytes()
        content_type = (
            mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
        )
        if static_path.suffix.casefold() in {".html", ".json", ".geojson", ".csv"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        selection_match = re.fullmatch(
            r"/api/v1/research-runs/(run-[0-9a-f]{20})/selection", path
        )
        if path != "/api/v1/research-runs" and selection_match is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        if not self._authorized(mutating=True):
            return
        request = self._read_json()
        if request is None:
            return
        try:
            if selection_match is None:
                state = auto_research.start_research(
                    self.server.atlas_dir, self.server.research_root, request
                )
            else:
                unknown = sorted(set(request) - {"candidate_id", "question"})
                if unknown:
                    raise auto_research.AutoResearchError(
                        "unknown selection fields: " + ", ".join(unknown)
                    )
                state = auto_research.select_research_direction(
                    self.server.research_root / selection_match.group(1),
                    candidate_id=request.get("candidate_id"),
                    question=request.get("question"),
                )
        except (auto_research.AutoResearchError, OSError, ValueError) as exc:
            self._json(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                {"error": "research_start_failed", "detail": str(exc)},
            )
            return
        self._json(HTTPStatus.CREATED, public_state(state))

    def do_PUT(self) -> None:  # noqa: N802
        self._json(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method_not_allowed"})

    do_DELETE = do_PUT
    do_PATCH = do_PUT


MappingLike = Mapping[str, Any] | dict[str, Any]


def public_state(state: MappingLike) -> dict[str, Any]:
    allowed = {
        "schema_version",
        "run_id",
        "status",
        "stage",
        "required_roles",
        "completed_roles",
        "active_cycle",
        "revision_count",
        "attempt",
        "selected_candidate_id",
        "human_approval_required",
        "publication_allowed",
        "updated_at",
    }
    return {key: state.get(key) for key in sorted(allowed)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas-dir", type=Path, required=True)
    parser.add_argument("--research-root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port < 0 or args.port > 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        atlas_dir = args.atlas_dir.resolve(strict=True)
        if not atlas_dir.is_dir() or atlas_dir.is_symlink():
            raise ResearchServerError("atlas-dir must be a regular directory")
        args.research_root.mkdir(parents=True, exist_ok=True)
        research_root = args.research_root.resolve(strict=True)
        if not research_root.is_dir() or args.research_root.is_symlink():
            raise ResearchServerError("research-root must be a regular directory")
        if research_root == atlas_dir or research_root.is_relative_to(atlas_dir):
            raise ResearchServerError(
                "research-root must be separate from the frozen atlas"
            )
        token = secrets.token_urlsafe(32)
        server = AtlasResearchServer(
            ("127.0.0.1", args.port), atlas_dir, research_root, token
        )
    except (OSError, ResearchServerError) as exc:
        parser.error(str(exc))
    port = int(server.server_address[1])
    print(
        json.dumps(
            {
                "status": "serving",
                "url": f"http://127.0.0.1:{port}/interactive_map.html#research_token={token}",
                "bind": "127.0.0.1",
                "research_root": str(research_root),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
