#!/usr/bin/env python3
"""Download one explicit public scientific data file with bounded, auditable behavior."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import os
import shutil
import socket
import stat
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

USER_AGENT = "GlobalGeochemicalAtlasSkill/1.0 (public scientific data retrieval)"
SENSITIVE_QUERY_TERMS = ("token", "key", "auth", "signature", "credential", "password", "secret")
RETRYABLE_HTTP_STATUS = {429, 502, 503, 504}


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
    output: Path,
    manifest_path: Path,
    url: str,
    expected_sha256: str | None,
    dataset_version: str | None = None,
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
        if dataset_version and prior_manifest.get("dataset_version") != dataset_version:
            raise DownloadError("offline manifest dataset version does not match the requested version")
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
            with tempfile.NamedTemporaryFile(
                "wb",
                prefix=f".{output.name}.",
                suffix=".part",
                dir=output.parent,
                delete=False,
            ) as handle:
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
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "content_disposition": response.headers.get("Content-Disposition"),
            }
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _safe_member_name(name: str) -> PurePosixPath:
    if "\x00" in name:
        raise DownloadError("ZIP member contains a NUL byte")
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise DownloadError(f"unsafe ZIP member path: {name}")
    return normalized


def _validate_zip_members(
    archive: zipfile.ZipFile,
    max_members: int,
    max_extracted_bytes: int,
    required_members: Sequence[str],
) -> list[zipfile.ZipInfo]:
    members = [info for info in archive.infolist() if not info.is_dir()]
    if not members:
        raise DownloadError("ZIP archive contains no files")
    if len(members) > max_members:
        raise DownloadError("ZIP member count exceeds --max-members")
    total = sum(info.file_size for info in members)
    if total > max_extracted_bytes:
        raise DownloadError("ZIP expanded size exceeds --max-extracted-bytes")
    available: set[str] = set()
    for info in members:
        normalized = _safe_member_name(info.filename)
        available.add(str(normalized))
        unix_mode = info.external_attr >> 16
        if unix_mode and stat.S_ISLNK(unix_mode):
            raise DownloadError(f"ZIP symlink members are rejected: {info.filename}")
    missing = sorted(set(required_members) - available)
    if missing:
        raise DownloadError(f"ZIP archive lacks required members: {', '.join(missing)}")
    return members


def _read_delimited_header(path: Path, required_fields: Sequence[str]) -> None:
    if not required_fields:
        return
    delimiter = "\t" if path.suffix.casefold() in {".txt", ".tsv"} else ","
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                reader = csv.reader(handle, delimiter=delimiter)
                for index, row in enumerate(reader):
                    fields = {value.strip() for value in row}
                    if set(required_fields).issubset(fields):
                        return
                    if index >= 49:
                        break
        except (UnicodeError, csv.Error, OSError) as exc:
            last_error = exc
            continue
    suffix = f": {last_error}" if last_error else ""
    raise DownloadError(f"required delimited fields not found in {path.name}{suffix}")


def safe_extract_zip(
    archive_path: Path,
    destination: Path,
    max_members: int,
    max_extracted_bytes: int,
    required_members: Sequence[str],
    required_fields: Sequence[str],
) -> list[dict[str, Any]]:
    """Extract to a temporary sibling directory and publish only after validation."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise DownloadError(f"extract destination already exists: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent))
    extracted: list[Path] = []
    try:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = _validate_zip_members(
                    archive,
                    max_members=max_members,
                    max_extracted_bytes=max_extracted_bytes,
                    required_members=required_members,
                )
                total = 0
                for info in members:
                    relative = _safe_member_name(info.filename)
                    target = temporary.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as output:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            total += len(chunk)
                            if total > max_extracted_bytes:
                                raise DownloadError("ZIP extraction exceeded --max-extracted-bytes")
                            output.write(chunk)
                    extracted.append(target)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise DownloadError("downloaded file is not a valid ZIP archive") from exc

        data_files = [path for path in extracted if path.suffix.casefold() in {".csv", ".txt", ".tsv"}]
        if required_fields and not data_files:
            raise DownloadError("ZIP archive has no delimited data file for required-field validation")
        for path in data_files:
            if path.name.casefold().startswith("manifest"):
                continue
            _read_delimited_header(path, required_fields)

        records = [
            {
                "path": str(path.relative_to(temporary)),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sorted(extracted)
        ]
        os.replace(temporary, destination)
        return records
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


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

    if args.max_extracted_bytes < 1 or args.max_extracted_bytes > 2_000_000_000:
        raise DownloadError("--max-extracted-bytes must be between 1 and 2000000000")
    if args.max_members < 1 or args.max_members > 10000:
        raise DownloadError("--max-members must be between 1 and 10000")

    if args.offline:
        result = existing_verified_cache(
            args.output,
            args.manifest,
            args.url,
            expected_sha256,
            args.dataset_version,
        )
    else:
        result: dict[str, Any] = {}
        if not args.refresh and args.output.is_file() and args.manifest.is_file():
            try:
                result = existing_verified_cache(
                    args.output,
                    args.manifest,
                    args.url,
                    expected_sha256,
                    args.dataset_version,
                )
            except DownloadError:
                result = {}
        if not result:
            last_error: Exception | None = None
            for attempt in range(args.retries + 1):
                try:
                    result = download_once(args.url, args.output, args.timeout, args.max_bytes, expected_sha256)
                    result["attempts"] = attempt + 1
                    break
                except (DownloadError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                    last_error = exc
                    retryable = isinstance(exc, (urllib.error.URLError, TimeoutError, OSError))
                    if isinstance(exc, urllib.error.HTTPError):
                        retryable = exc.code in RETRYABLE_HTTP_STATUS
                    if isinstance(exc, DownloadError):
                        retryable = False
                    if attempt >= args.retries or not retryable:
                        raise DownloadError(str(exc)) from exc
                    time.sleep(min(2**attempt, 4))
            if not result:
                raise DownloadError(str(last_error or "download failed"))

    if args.required_field and args.output.suffix.casefold() != ".zip":
        _read_delimited_header(args.output, args.required_field)
    if args.extract_dir:
        if args.output.suffix.casefold() != ".zip":
            raise DownloadError("--extract-dir requires a .zip output file")
        result["extracted_files"] = safe_extract_zip(
            args.output,
            args.extract_dir,
            max_members=args.max_members,
            max_extracted_bytes=args.max_extracted_bytes,
            required_members=args.required_member,
            required_fields=args.required_field,
        )
        result["extract_dir"] = args.extract_dir.name

    result.update(
        {
            "manifest_version": "geochemical-download-v1",
            "license": args.license.strip(),
            "output_filename": args.output.name,
            "offline": bool(args.offline),
            "dataset_doi": args.dataset_doi,
            "dataset_version": args.dataset_version,
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
    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Bounded retries for 429/502/503/504 and transient network errors (max: 3)",
    )
    parser.add_argument("--offline", action="store_true", help="Use only a hash-verified existing cache file")
    parser.add_argument("--refresh", action="store_true", help="Ignore a valid online cache and download again")
    parser.add_argument("--dataset-doi", help="Stable dataset DOI to record in the download manifest")
    parser.add_argument("--dataset-version", help="Dataset version to bind to cache reuse")
    parser.add_argument("--extract-dir", type=Path, help="Optional destination for safe ZIP extraction")
    parser.add_argument(
        "--max-extracted-bytes",
        type=int,
        default=200_000_000,
        help="Hard expanded ZIP limit (default: 200 MB)",
    )
    parser.add_argument("--max-members", type=int, default=1000, help="Hard ZIP member-count limit")
    parser.add_argument(
        "--required-member",
        action="append",
        default=[],
        help="Required ZIP member path; repeat for multiple members",
    )
    parser.add_argument(
        "--required-field",
        action="append",
        default=[],
        help="Required delimited-file header field; repeat for multiple fields",
    )
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
