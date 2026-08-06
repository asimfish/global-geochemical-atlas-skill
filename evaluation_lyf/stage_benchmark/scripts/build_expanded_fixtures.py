#!/usr/bin/env python3
"""Refresh or verify the frozen China/Africa/Europe/Japan benchmark fixtures."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tempfile
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lab_common import CONTRACT_ROOT, LAB_ROOT, sha256_file

BUILDER_VERSION = "expanded-fixture-builder-v1"
SOURCE_CONTRACT = CONTRACT_ROOT / "expanded-sources.json"
DEFAULT_FIXTURE_DIR = LAB_ROOT / "expanded-data" / "fixtures" / "raw"
TPDC_METADATA_ID = "2f4c2f30-166c-4a76-9b4a-74c98b4ca3b1"
MAX_DOWNLOAD_BYTES = 12_000_000


class FixtureError(RuntimeError):
    """Raised when an upstream or frozen fixture violates its evidence contract."""


def load_contract() -> dict[str, Any]:
    payload = json.loads(SOURCE_CONTRACT.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FixtureError("expanded source contract must be a JSON object")
    return payload


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resource_by_id(contract: Mapping[str, Any], resource_id: str) -> Mapping[str, Any]:
    for resource in contract.get("resources", []):
        if resource.get("id") == resource_id:
            return resource
    raise FixtureError(f"resource missing from expanded source contract: {resource_id}")


def decode_text(data: bytes) -> str:
    variants: list[str] = []
    for encoding in ("utf-8-sig", "shift_jis", "cp1252"):
        try:
            decoded = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded not in variants:
            variants.append(decoded)
    return "\n".join(variants) if variants else data.decode("utf-8", errors="replace")


def searchable_text(data: bytes, format_name: str) -> str:
    if format_name in {"zip", "xlsx", "docx"}:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            chunks = []
            for member in archive.namelist():
                if member.endswith("/"):
                    continue
                try:
                    member_data = archive.read(member)
                except (KeyError, RuntimeError):
                    continue
                if member.lower().endswith((".xml", ".rels", ".csv", ".txt", ".tab", ".html")):
                    chunks.append(decode_text(member_data))
            return "\n".join(chunks)
    return decode_text(data)


def verify_required_tokens(data: bytes, format_name: str, required_tokens: Sequence[str], label: str) -> None:
    if not required_tokens:
        return
    haystack = searchable_text(data, format_name)
    missing = [token for token in required_tokens if token not in haystack]
    if missing:
        raise FixtureError(f"required evidence tokens missing from {label}: {missing}")


def verify_blob(data: bytes, resource: Mapping[str, Any], label: str) -> None:
    expected_bytes = int(resource["bytes"])
    expected_hash = str(resource["sha256"])
    if len(data) != expected_bytes:
        raise FixtureError(f"byte mismatch for {label}: {len(data)} != {expected_bytes}")
    actual_hash = sha256_bytes(data)
    if actual_hash != expected_hash:
        raise FixtureError(f"SHA-256 mismatch for {label}: {actual_hash} != {expected_hash}")
    verify_required_tokens(
        data,
        str(resource.get("format", "")),
        [str(token) for token in resource.get("required_tokens", [])],
        label,
    )


def verify_archive_members(path: Path, resource: Mapping[str, Any]) -> list[dict[str, Any]]:
    verified: list[dict[str, Any]] = []
    members = resource.get("members", [])
    if not members:
        return verified
    with zipfile.ZipFile(path) as archive:
        for member in members:
            member_path = str(member["path"])
            try:
                data = archive.read(member_path)
            except KeyError as exc:
                raise FixtureError(f"archive member missing: {path.name}:{member_path}") from exc
            verify_blob(data, member, f"{path.name}:{member_path}")
            verified.append(
                {
                    "archive": str(resource["local_file"]),
                    "path": member_path,
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                }
            )
    return verified


def verify_fixtures(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    contract = load_contract()
    resources: list[dict[str, Any]] = []
    archive_members: list[dict[str, Any]] = []
    total_bytes = 0
    for resource in contract.get("resources", []):
        path = fixture_dir / str(resource["local_file"])
        if not path.is_file():
            raise FixtureError(f"expanded fixture missing: {path}")
        data = path.read_bytes()
        verify_blob(data, resource, str(resource["local_file"]))
        archive_members.extend(verify_archive_members(path, resource))
        total_bytes += len(data)
        resources.append(
            {
                "id": resource["id"],
                "path": str(path),
                "bytes": len(data),
                "sha256": sha256_file(path),
            }
        )
    return {
        "status": "success",
        "builder_version": BUILDER_VERSION,
        "mode": "offline_verify",
        "contract": str(SOURCE_CONTRACT),
        "fixture_dir": str(fixture_dir),
        "resource_count": len(resources),
        "archive_member_count": len(archive_members),
        "total_bytes": total_bytes,
        "resources": resources,
        "archive_members": archive_members,
    }


def request_bytes(url: str, *, method: str = "GET", json_body: Mapping[str, Any] | None = None) -> bytes:
    body = None
    headers = {"User-Agent": f"{BUILDER_VERSION} (+reproducible-scientific-fixture)"}
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=120) as response:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > MAX_DOWNLOAD_BYTES:
            raise FixtureError(f"upstream resource exceeds {MAX_DOWNLOAD_BYTES} bytes: {url}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise FixtureError(f"upstream resource exceeds {MAX_DOWNLOAD_BYTES} bytes: {url}")
            chunks.append(chunk)
    return b"".join(chunks)


def atomic_replace_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    os.replace(temporary, path)


def verified_replace(fixture_dir: Path, resource: Mapping[str, Any], data: bytes) -> None:
    verify_blob(data, resource, str(resource["local_file"]))
    if resource.get("members"):
        with tempfile.NamedTemporaryFile("wb", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
        try:
            verify_archive_members(temporary, resource)
        finally:
            temporary.unlink(missing_ok=True)
    atomic_replace_bytes(fixture_dir / str(resource["local_file"]), data)


def extract_tpdc_payload(wrapper: bytes) -> tuple[bytes, bytes]:
    with zipfile.ZipFile(io.BytesIO(wrapper)) as outer:
        candidates = [name for name in outer.namelist() if name.lower().endswith(".zip")]
        if len(candidates) != 1:
            raise FixtureError(f"TPDC wrapper should contain one inner zip, found {candidates}")
        inner_data = outer.read(candidates[0])
    with zipfile.ZipFile(io.BytesIO(inner_data)) as inner:
        xlsx_names = [name for name in inner.namelist() if name.endswith("Soil dataset.xlsx")]
        docx_names = [name for name in inner.namelist() if name.endswith("Description of the dataset.docx")]
        if len(xlsx_names) != 1 or len(docx_names) != 1:
            raise FixtureError("TPDC archive is missing the expected data workbook or description")
        return inner.read(xlsx_names[0]), inner.read(docx_names[0])


def refresh_fixtures(fixture_dir: Path = DEFAULT_FIXTURE_DIR) -> dict[str, Any]:
    contract = load_contract()

    metadata = request_bytes(
        "https://data.tpdc.ac.cn/view/metadataView/detail/",
        method="POST",
        json_body={"userId": "", "metadataId": TPDC_METADATA_ID},
    )
    verified_replace(fixture_dir, resource_by_id(contract, "tpdc_china_metadata"), metadata)
    wrapper = request_bytes(
        f"https://data.tpdc.ac.cn/file/file/batchDownloadFile?metadataId={TPDC_METADATA_ID}",
        method="POST",
        json_body={"noToken": True},
    )
    workbook, description = extract_tpdc_payload(wrapper)
    verified_replace(fixture_dir, resource_by_id(contract, "tpdc_china_soil_data"), workbook)
    verified_replace(fixture_dir, resource_by_id(contract, "tpdc_china_soil_description"), description)

    for resource in contract.get("resources", []):
        if str(resource["id"]).startswith("tpdc_"):
            continue
        url = resource.get("url")
        if not url:
            continue
        data = request_bytes(str(url))
        verified_replace(fixture_dir, resource, data)

    result = verify_fixtures(fixture_dir)
    result["mode"] = "online_refresh_then_verify"
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh or offline-verify the expanded China/Africa/Europe/Japan fixtures."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="verify bundled files without network")
    mode.add_argument("--refresh", action="store_true", help="redownload official files and require frozen hashes")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = refresh_fixtures(args.fixture_dir) if args.refresh else verify_fixtures(args.fixture_dir)
    except (FixtureError, OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
