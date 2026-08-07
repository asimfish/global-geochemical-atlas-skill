#!/usr/bin/env python3
"""Acquire a reviewable GEOTRACES IDP2025 Cu/Ni/Zn seawater export candidate."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import re
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Sequence
from pathlib import Path, PurePosixPath
from typing import Any

EXTRACTOR_URL = (
    "https://geotraces.webodv.awi.de/"
    "IDP2025%3Eseawater%3EGEOTRACES_IDP2025_Seawater/service/DataExtraction/wsODV"
)
DOWNLOAD_URL = (
    "https://geotraces.webodv.awi.de/webodv/data/"
    "IDP2025%3Eseawater%3EGEOTRACES_IDP2025_Seawater/service/Download"
)
DATASET_PATH = "IDP2025>seawater>GEOTRACES_IDP2025_Seawater"
DATASET_DOI = "10.5285/42c92148-8d03-8be6-e063-7086abc09f0c"
MAX_MEMBERS = 500
MAX_UNCOMPRESSED_BYTES = 50_000_000
REQUIRED_COLUMNS = (
    "Cruise",
    "Station",
    "Longitude [degrees_east]",
    "Latitude [degrees_north]",
    "DEPTH [m]",
    "Cu_D_CONC [nmol/kg]",
    "Ni_D_CONC [nmol/kg]",
    "Zn_D_CONC [nmol/kg]",
)


class AcquisitionError(RuntimeError):
    """Raised when the official export cannot be acquired or validated safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_zip_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(member) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def opener() -> urllib.request.OpenerDirector:
    cookies = http.cookiejar.CookieJar()
    context = ssl.create_default_context()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookies),
        urllib.request.HTTPSHandler(context=context),
    )


def read_response(response: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(1024 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AcquisitionError(f"response exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_export_url(client: urllib.request.OpenerDirector, timeout: float) -> str:
    request = urllib.request.Request(
        EXTRACTOR_URL, headers={"User-Agent": "global-geochemical-atlas-skill/1"}
    )
    with client.open(request, timeout=timeout) as response:
        html = read_response(response, 2_000_000).decode("utf-8")
    match = re.search(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', html)
    if match is None:
        raise AcquisitionError("official extractor page did not expose a CSRF token")
    csrf_token = match.group(1)
    parameters = [
        ("file_format", "txt"),
        ("datasetname", DATASET_PATH),
        ("date1", "01/01/1850"),
        ("date2", "12/31/2026"),
        ("download_private_workspace", "false"),
        ("OutVar[]", "1"),
        ("OutVar[]", "62"),
        ("OutVar[]", "81"),
        ("OutVar[]", "88"),
        ("OutVarEx", "61,80,87"),
        ("use_or_logic", "T"),
        ("treeview_mode", "0"),
        ("coords[]", "-243"),
        ("coords[]", "117"),
        ("coords[]", "-90"),
        ("coords[]", "90"),
        ("pointsize", "0.5"),
    ]
    post = urllib.request.Request(
        DOWNLOAD_URL,
        data=urllib.parse.urlencode(parameters).encode("ascii"),
        headers={
            "User-Agent": "global-geochemical-atlas-skill/1",
            "X-CSRF-TOKEN": csrf_token,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": EXTRACTOR_URL,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with client.open(post, timeout=timeout) as response:
        payload = read_response(response, 100_000)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError(
            "official download endpoint did not return JSON"
        ) from exc
    output_url = value.get("output_file_url") if isinstance(value, dict) else None
    parsed = urllib.parse.urlparse(str(output_url or ""))
    if (
        parsed.scheme != "https"
        or parsed.hostname != "geotraces.webodv.awi.de"
        or not parsed.path.startswith("/downloads/")
    ):
        raise AcquisitionError(
            "official download endpoint returned an unsafe output URL"
        )
    return str(output_url)


def download_archive(
    client: urllib.request.OpenerDirector,
    url: str,
    output: Path,
    *,
    timeout: float,
    max_bytes: int,
    overwrite: bool,
) -> list[dict[str, Any]]:
    if output.exists() and not overwrite:
        raise AcquisitionError(f"output exists; use --overwrite after review: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": "global-geochemical-atlas-skill/1"}
    )
    temporary: Path | None = None
    try:
        with client.open(request, timeout=timeout) as response:
            content_type = (
                str(response.headers.get("Content-Type") or "").split(";", 1)[0].strip()
            )
            if content_type not in {"application/zip", "application/octet-stream"}:
                raise AcquisitionError(
                    f"unexpected archive content type: {content_type or 'missing'}"
                )
            with tempfile.NamedTemporaryFile(
                "wb", dir=output.parent, delete=False
            ) as handle:
                temporary = Path(handle.name)
                total = 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise AcquisitionError(f"archive exceeds {max_bytes} bytes")
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
        members = validate_archive(temporary)
        os.replace(temporary, output)
        temporary = None
        return members
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_archive(path: Path) -> list[dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise AcquisitionError("download is not a valid ZIP archive") from exc
    with archive:
        members = archive.infolist()
        if not members or len(members) > MAX_MEMBERS:
            raise AcquisitionError(
                "archive member count is empty or exceeds the safety limit"
            )
        if any(info.is_dir() or info.file_size < 0 for info in members):
            raise AcquisitionError(
                "archive contains an unsupported directory or invalid member"
            )
        names = [info.filename for info in members]
        if len(names) != len(set(names)):
            raise AcquisitionError("archive contains duplicate member names")
        if any(
            PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or "\\" in name
            for name in names
        ):
            raise AcquisitionError("archive contains an unsafe member path")
        if sum(info.file_size for info in members) > MAX_UNCOMPRESSED_BYTES:
            raise AcquisitionError("archive exceeds the uncompressed-size safety limit")
        data_members = [
            info
            for info in members
            if "/" not in info.filename and info.filename.endswith(".txt")
        ]
        if len(data_members) != 1:
            raise AcquisitionError(
                "archive must contain exactly one top-level ODV text member"
            )
        with archive.open(data_members[0]) as handle:
            header_probe = handle.read(128_000).decode("utf-8")
        header = next(
            (
                line.split("\t")
                for line in header_probe.splitlines()
                if line.startswith("Cruise\t")
            ),
            None,
        )
        missing = sorted(set(REQUIRED_COLUMNS) - set(header or []))
        if missing:
            raise AcquisitionError(
                f"ODV member lacks required columns: {', '.join(missing)}"
            )
        return [
            {
                "name": info.filename,
                "bytes": info.file_size,
                "sha256": sha256_zip_member(archive, info),
            }
            for info in members
        ]


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-bytes", type=int, default=5_000_000)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--accept-fair-use",
        action="store_true",
        help="Record explicit acceptance of the IDP2025 Fair Data Use expectations",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.accept_fair_use:
        print(
            "acquire_geotraces_idp2025: --accept-fair-use is required", file=sys.stderr
        )
        return 2
    if not (1 <= args.timeout <= 300) or not (100_000 <= args.max_bytes <= 50_000_000):
        print(
            "acquire_geotraces_idp2025: timeout or max-bytes is outside the safety range",
            file=sys.stderr,
        )
        return 2
    try:
        client = opener()
        output_url = fetch_export_url(client, args.timeout)
        members = download_archive(
            client,
            output_url,
            args.output,
            timeout=args.timeout,
            max_bytes=args.max_bytes,
            overwrite=args.overwrite,
        )
        manifest = {
            "acquisition_version": "geotraces-idp2025-webodv-acquisition-v1",
            "status": "candidate_requires_registry_review",
            "dataset_doi": DATASET_DOI,
            "dataset_version": "IDP2025",
            "request": {
                "extractor_url": EXTRACTOR_URL,
                "dataset_path": DATASET_PATH,
                "output_variables_one_based": [1, 62, 81, 88],
                "required_variables_zero_based": [61, 80, 87],
                "station_logic": "OR",
            },
            "fair_use_accepted": True,
            "response": {
                "official_session_output_url": output_url,
                "filename": args.output.name,
                "bytes": args.output.stat().st_size,
                "sha256": sha256_file(args.output),
            },
            "archive": {"member_count": len(members), "members": members},
            "next_action": (
                "Run audit_geotraces_snapshot.py, compare counts and parameter inventory, then update the registry only after review."
            ),
        }
        atomic_json(args.manifest, manifest)
        print(
            json.dumps(
                {"status": "PASS", "sha256": manifest["response"]["sha256"]},
                sort_keys=True,
            )
        )
        return 0
    except (AcquisitionError, OSError, urllib.error.URLError) as exc:
        print(f"acquire_geotraces_idp2025: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
