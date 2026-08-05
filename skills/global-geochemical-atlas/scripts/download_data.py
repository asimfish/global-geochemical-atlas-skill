#!/usr/bin/env python3
"""Download one explicit public scientific data file with bounded, auditable behavior."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

USER_AGENT = "GlobalGeochemicalAtlasSkill/1.0 (public scientific data retrieval)"
SENSITIVE_QUERY_TERMS = ("token", "key", "auth", "signature", "credential", "password", "secret")


class DownloadError(RuntimeError):
    """Raised when a download cannot be completed safely."""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_sha256(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.casefold().strip()
    if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
        raise DownloadError("--expected-sha256 must contain exactly 64 hexadecimal characters")
    return normalized


def validate_public_https_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.casefold() != "https":
        raise DownloadError("only explicit HTTPS data URLs are accepted")
    if not parsed.hostname or parsed.username or parsed.password:
        raise DownloadError("URL must contain a public hostname and no embedded credentials")
    query_names = [name.casefold() for name, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)]
    if any(term in name for name in query_names for term in SENSITIVE_QUERY_TERMS):
        raise DownloadError("URL query appears to contain a credential or signed secret; do not persist it")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise DownloadError(f"hostname resolution failed for {parsed.hostname}") from exc
    if not addresses:
        raise DownloadError("hostname did not resolve to an address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise DownloadError("private, loopback, link-local, multicast, and reserved destinations are rejected")


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        validate_public_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def existing_verified_cache(
    output: Path, manifest_path: Path, url: str, expected_sha256: str | None
) -> dict[str, Any]:
    if not output.is_file():
        raise DownloadError("offline cache file does not exist")
    recorded_hash = expected_sha256
    prior_manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DownloadError("offline manifest is unreadable") from exc
        if prior_manifest.get("source_url") != url:
            raise DownloadError("offline manifest source URL does not match the requested URL")
        recorded_hash = recorded_hash or prior_manifest.get("sha256")
    if not recorded_hash:
        raise DownloadError("offline mode requires --expected-sha256 or a prior manifest hash")
    observed = sha256_file(output)
    if observed != recorded_hash:
        raise DownloadError("offline cache SHA-256 mismatch")
    return {
        **prior_manifest,
        "status": "cache_hit",
        "source_url": url,
        "resolved_url": prior_manifest.get("resolved_url", url),
        "sha256": observed,
        "sha256_basis": "expected" if expected_sha256 else "prior_manifest",
        "bytes": output.stat().st_size,
        "cache_verified_at": utc_now(),
    }


def download_once(
    url: str,
    output: Path,
    timeout: float,
    max_bytes: int,
    expected_sha256: str | None,
) -> dict[str, Any]:
    validate_public_https_url(url)
    opener = urllib.request.build_opener(SafeRedirectHandler())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with opener.open(request, timeout=timeout) as response:
            resolved_url = response.geturl()
            validate_public_https_url(resolved_url)
            content_type = response.headers.get_content_type().casefold()
            if content_type in {"text/html", "application/xhtml+xml"}:
                raise DownloadError("server returned HTML rather than a data file")
            declared_length = response.headers.get("Content-Length")
            if declared_length:
                try:
                    declared_bytes = int(declared_length)
                except ValueError:
                    declared_bytes = None
                if declared_bytes is not None and declared_bytes > max_bytes:
                    raise DownloadError("declared Content-Length exceeds --max-bytes")

            digest = hashlib.sha256()
            total = 0
            with tempfile.NamedTemporaryFile("wb", dir=output.parent, delete=False) as handle:
                temporary_path = Path(handle.name)
                while True:
                    chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise DownloadError("download exceeded --max-bytes")
                    digest.update(chunk)
                    handle.write(chunk)
            if total == 0:
                raise DownloadError("server returned an empty file")
            observed = digest.hexdigest()
            if expected_sha256 and observed != expected_sha256:
                raise DownloadError("downloaded file SHA-256 does not match --expected-sha256")
            os.replace(temporary_path, output)
            temporary_path = None
            return {
                "status": "downloaded",
                "source_url": url,
                "resolved_url": resolved_url,
                "content_type": content_type,
                "bytes": total,
                "sha256": observed,
                "sha256_basis": "expected" if expected_sha256 else "observed_not_publisher_verified",
                "accessed_at": utc_now(),
                "http_status": getattr(response, "status", 200),
            }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    expected_sha256 = validate_sha256(args.expected_sha256)
    if args.max_bytes < 1 or args.max_bytes > 500_000_000:
        raise DownloadError("--max-bytes must be between 1 and 500000000")
    if args.timeout <= 0 or args.timeout > 120:
        raise DownloadError("--timeout must be greater than 0 and at most 120 seconds")
    if args.retries < 0 or args.retries > 3:
        raise DownloadError("--retries must be between 0 and 3")
    if not args.license.strip():
        raise DownloadError("--license is required; use 'unresolved' only when manual review is explicit")

    if args.offline:
        result = existing_verified_cache(args.output, args.manifest, args.url, expected_sha256)
    else:
        last_error: Exception | None = None
        result = {}
        for attempt in range(args.retries + 1):
            try:
                result = download_once(args.url, args.output, args.timeout, args.max_bytes, expected_sha256)
                result["attempts"] = attempt + 1
                break
            except (DownloadError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                retryable = not isinstance(exc, DownloadError)
                if isinstance(exc, urllib.error.HTTPError):
                    retryable = exc.code == 429 or 500 <= exc.code <= 599
                if attempt >= args.retries or not retryable:
                    raise DownloadError(str(exc)) from exc
                time.sleep(min(2**attempt, 4))
        if not result:
            raise DownloadError(str(last_error or "download failed"))

    result.update(
        {
            "manifest_version": "geochemical-download-v1",
            "license": args.license.strip(),
            "output_filename": args.output.name,
            "offline": bool(args.offline),
        }
    )
    atomic_json(args.manifest, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download one explicit public HTTPS scientific data file with size, hash, timeout and cache checks."
    )
    parser.add_argument("--url", required=True, help="Direct HTTPS data-file URL; interactive/search pages are rejected")
    parser.add_argument("--output", required=True, type=Path, help="Destination data file")
    parser.add_argument("--manifest", required=True, type=Path, help="JSON provenance manifest path")
    parser.add_argument("--license", required=True, help="Source license or 'unresolved' for explicit manual review")
    parser.add_argument("--expected-sha256", help="Publisher or previously verified SHA-256")
    parser.add_argument("--max-bytes", type=int, default=50_000_000, help="Hard response limit (default: 50 MB)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout in seconds (max: 120)")
    parser.add_argument("--retries", type=int, default=2, help="Bounded retries for 429/5xx/network errors (max: 3)")
    parser.add_argument("--offline", action="store_true", help="Use only a hash-verified existing cache file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except DownloadError as exc:
        failure = {
            "manifest_version": "geochemical-download-v1",
            "status": "network_unavailable" if not args.offline else "incomplete_retrieval",
            "source_url": args.url,
            "output_filename": args.output.name,
            "license": args.license,
            "offline": bool(args.offline),
            "error": str(exc),
        }
        try:
            atomic_json(args.manifest, failure)
        except OSError:
            pass
        print(f"download_data: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
