#!/usr/bin/env python3
"""Shared D1 contracts for versioned scientific data-source adapters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import os
import re
import socket
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import download_data as downloader

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"

DownloadMode = Literal["online", "cached", "fixture"]


class SourceAdapterError(RuntimeError):
    """Raised when a source registry or adapter fails closed."""


@dataclass(frozen=True)
class DatasetCandidate:
    """A versioned dataset selected from the checked-in source registry."""

    source_id: str
    title: str
    adapter: str
    version: str
    dataset_doi: str | None
    license_id: str
    landing_page: str
    registry_entry: Mapping[str, Any]


@dataclass(frozen=True)
class DownloadedFile:
    """One verified local file plus the evidence needed to reuse it safely."""

    source_id: str
    file_id: str
    path: Path
    source_url: str
    sha256: str
    bytes: int
    cache_status: str
    retrieved_at: str | None


@dataclass(frozen=True)
class RawRecord:
    """A source-native record that has not undergone D2 normalization."""

    source_id: str
    source_record_id: str
    source_locator: str
    fields: Mapping[str, Any]


class DataSourceAdapter(ABC):
    """Uniform D1 interface; scientific normalization remains a D2 concern."""

    source_id: str

    @abstractmethod
    def discover(self, request: Mapping[str, Any] | None = None) -> list[DatasetCandidate]:
        """Return only registry-backed candidates compatible with the request."""

    @abstractmethod
    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        """Acquire or reuse files with hash, size and provenance verification."""

    @abstractmethod
    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        """Yield source-native records without changing units or scientific meaning."""

    @abstractmethod
    def provenance(self) -> Mapping[str, Any]:
        """Return the version, citation, license and source limitations."""


def _canonical_hash(namespace: str, values: Sequence[Any]) -> str:
    encoded = json.dumps(
        {"namespace": namespace, "values": list(values)},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def stable_source_record_id(source_id: str, native_id: str | None, source_locator: str) -> str:
    """Build a stable source-row ID without depending on cache or output paths."""

    normalized_source = source_id.strip()
    normalized_locator = source_locator.strip()
    normalized_native = (native_id or "").strip()
    if not normalized_source or not normalized_locator:
        raise SourceAdapterError("source_id and source_locator are required for a stable source record ID")
    return f"src-{_canonical_hash('source-record-v1', (normalized_source, normalized_native, normalized_locator))}"


def stable_record_id(
    source_id: str,
    source_record_id: str,
    analyte_reported: str,
    original_value_raw: str,
    original_unit: str,
    occurrence: int = 0,
) -> str:
    """Build a stable observation ID while preserving repeated source determinations."""

    if occurrence < 0:
        raise SourceAdapterError("occurrence must be non-negative")
    values = tuple(value.strip() for value in (
        source_id,
        source_record_id,
        analyte_reported,
        original_value_raw,
        original_unit,
    ))
    if not all(values[:4]):
        raise SourceAdapterError(
            "source_id, source_record_id, analyte_reported and original_value_raw are required for record IDs"
        )
    return f"rec-{_canonical_hash('observation-v1', (*values, occurrence))}"


def load_source_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    """Load and minimally validate the checked-in D1 source registry."""

    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SourceAdapterError(f"source registry does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SourceAdapterError(f"source registry is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(registry, dict):
        raise SourceAdapterError("source registry must be a JSON object")
    if registry.get("registry_version") != "geochemical-source-registry-v1":
        raise SourceAdapterError("unsupported source registry version")
    sources = registry.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise SourceAdapterError("source registry must contain a non-empty sources object")
    for source_id, entry in sources.items():
        if not isinstance(source_id, str) or not source_id or not isinstance(entry, dict):
            raise SourceAdapterError("source registry contains an invalid source entry")
        required = {"adapter", "title", "dataset_version", "landing_page", "license", "download"}
        missing = sorted(required - set(entry))
        if missing:
            raise SourceAdapterError(f"source {source_id} lacks required registry keys: {', '.join(missing)}")
        license_entry = entry.get("license")
        if not isinstance(license_entry, dict) or not license_entry.get("spdx") or not license_entry.get("url"):
            raise SourceAdapterError(f"source {source_id} has incomplete license metadata")
    return registry


def registry_candidate(source_id: str, path: Path = DEFAULT_REGISTRY) -> DatasetCandidate:
    """Resolve one immutable adapter candidate from the source registry."""

    registry = load_source_registry(path)
    entry = registry["sources"].get(source_id)
    if not isinstance(entry, dict):
        raise SourceAdapterError(f"unknown source_id: {source_id}")
    return DatasetCandidate(
        source_id=source_id,
        title=str(entry["title"]),
        adapter=str(entry["adapter"]),
        version=str(entry["dataset_version"]),
        dataset_doi=str(entry["dataset_doi"]) if entry.get("dataset_doi") else None,
        license_id=str(entry["license"]["spdx"]),
        landing_page=str(entry["landing_page"]),
        registry_entry=entry,
    )


def _md5_file(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_args(
    *,
    url: str,
    output: Path,
    manifest: Path,
    license_id: str,
    expected_sha256: str | None,
    max_bytes: int,
    dataset_doi: str | None,
    dataset_version: str,
    offline: bool,
    required_fields: Sequence[str] = (),
) -> argparse.Namespace:
    return argparse.Namespace(
        url=url,
        output=output,
        manifest=manifest,
        license=license_id,
        expected_sha256=expected_sha256,
        max_bytes=max_bytes,
        timeout=30.0,
        retries=2,
        offline=offline,
        refresh=False,
        dataset_doi=dataset_doi,
        dataset_version=dataset_version,
        extract_dir=None,
        max_extracted_bytes=200_000_000,
        max_members=1000,
        required_member=[],
        required_field=list(required_fields),
    )


def _request_allows(candidate: DatasetCandidate, request: Mapping[str, Any] | None) -> bool:
    if not request:
        return True
    requested_sources = request.get("sources")
    if requested_sources not in (None, "auto"):
        if isinstance(requested_sources, str):
            requested_sources = [requested_sources]
        if candidate.source_id not in requested_sources:
            return False
    requested_media = request.get("media")
    if requested_media:
        if isinstance(requested_media, str):
            requested_media = [requested_media]
        available = set(candidate.registry_entry.get("media", []))
        if not available.intersection(requested_media):
            return False
    return True


class RegistryAdapter(DataSourceAdapter):
    """Base implementation for one immutable registry entry."""

    source_id = ""

    def __init__(self, registry_path: Path = DEFAULT_REGISTRY) -> None:
        self.registry_path = registry_path
        self.candidate = registry_candidate(self.source_id, registry_path)

    def discover(self, request: Mapping[str, Any] | None = None) -> list[DatasetCandidate]:
        return [self.candidate] if _request_allows(self.candidate, request) else []

    def provenance(self) -> Mapping[str, Any]:
        return self.candidate.registry_entry

    def _cache_root(self, cache_dir: Path) -> Path:
        safe_version = re.sub(r"[^A-Za-z0-9._-]+", "-", self.candidate.version).strip("-") or "unknown"
        return cache_dir / self.source_id / safe_version


class UsgsSoilAdapter(RegistryAdapter):
    """USGS Data Series 801 tab-delimited soil tables."""

    source_id = "usgs-conus-soil"

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("USGS adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("source-specific fixture mode is not available until the demo slice is generated")
        root = self._cache_root(cache_dir)
        results: list[DownloadedFile] = []
        download_entry = candidate.registry_entry["download"]
        accepted = set(download_entry["accepted_content_types"])
        for file_entry in download_entry["files"]:
            output = root / file_entry["filename"]
            manifest = root / f"{file_entry['file_id']}.download.json"
            args = _download_args(
                url=file_entry["url"],
                output=output,
                manifest=manifest,
                license_id=candidate.license_id,
                expected_sha256=file_entry["expected_sha256"],
                max_bytes=int(download_entry["max_bytes_per_file"]),
                dataset_doi=candidate.dataset_doi,
                dataset_version=candidate.version,
                offline=mode == "cached",
                required_fields=candidate.registry_entry["required_fields"],
            )
            try:
                result = downloader.run(args)
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"USGS download failed for {file_entry['file_id']}: {exc}") from exc
            content_type = result.get("content_type")
            if content_type and content_type not in accepted:
                raise SourceAdapterError(
                    f"USGS file {file_entry['file_id']} returned unexpected content type: {content_type}"
                )
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=output,
                    source_url=file_entry["url"],
                    sha256=result["sha256"],
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at") or result.get("cache_verified_at"),
                )
            )
        return results

    @staticmethod
    def _rows(path: Path) -> Iterable[tuple[int, dict[str, str], dict[str, str]]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            units: dict[str, str] = {}
            for row in reader:
                stripped = [value.strip() for value in row]
                if header is None:
                    if {"SiteID", "StateID", "Latitude", "Longitude"}.issubset(stripped):
                        header = stripped
                    continue
                if not units:
                    units = {
                        name: value
                        for name, value in zip(header, stripped, strict=False)
                        if name and value
                    }
                    continue
                if not any(stripped):
                    continue
                padded = stripped + [""] * max(0, len(header) - len(stripped))
                values = dict(zip(header, padded, strict=False))
                if not values.get("SiteID"):
                    continue
                yield reader.line_num, values, units

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        registered = {item["file_id"]: item for item in self.candidate.registry_entry["download"]["files"]}
        for downloaded in files:
            file_entry = registered.get(downloaded.file_id)
            if not file_entry:
                raise SourceAdapterError(f"unregistered USGS file_id: {downloaded.file_id}")
            for line_number, values, units in self._rows(downloaded.path):
                source_locator = f"{downloaded.path.name}#row={line_number}"
                native_id = values.get(f"{file_entry['header_prefix']}LabID") or values.get("SiteID")
                source_record_id = stable_source_record_id(self.source_id, native_id, source_locator)
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=source_record_id,
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_units": units,
                        "_soil_layer": downloaded.file_id,
                        "_source_file": downloaded.path.name,
                        "_dataset_version": self.candidate.version,
                    },
                )


class GeorocArchaeanAdapter(RegistryAdapter):
    """GEOROC Dataverse versioned ZIP containing one CSV per craton."""

    source_id = "georoc-archaean"

    def _verified_members(self, extract_dir: Path, cache_status: str, retrieved_at: str | None) -> list[DownloadedFile]:
        members = self.candidate.registry_entry["download"]["members"]
        expected_names = {entry["filename"] for entry in members}
        actual_names = {path.name for path in extract_dir.glob("*.csv") if path.is_file()}
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            unexpected = sorted(actual_names - expected_names)
            raise SourceAdapterError(f"GEOROC member set changed; missing={missing}, unexpected={unexpected}")
        verified: list[DownloadedFile] = []
        for entry in members:
            path = extract_dir / entry["filename"]
            if path.stat().st_size != entry["bytes"]:
                raise SourceAdapterError(f"GEOROC member size changed: {path.name}")
            checksum = entry["publisher_checksum"]
            if checksum["algorithm"] != "md5" or _md5_file(path) != checksum["value"]:
                raise SourceAdapterError(f"GEOROC publisher checksum mismatch: {path.name}")
            downloader._read_delimited_header(path, self.candidate.registry_entry["required_fields"])
            persistent_id = entry["persistent_id"].removeprefix("doi:")
            verified.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=persistent_id.rsplit("/", 1)[-1],
                    path=path,
                    source_url=f"https://doi.org/{persistent_id}",
                    sha256=downloader.sha256_file(path),
                    bytes=path.stat().st_size,
                    cache_status=cache_status,
                    retrieved_at=retrieved_at,
                )
            )
        return verified

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("GEOROC adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("source-specific fixture mode is not available until the demo slice is generated")
        root = self._cache_root(cache_dir)
        archive_path = root / "georoc-archaean-v12.zip"
        manifest_path = root / "dataset.download.json"
        download_entry = candidate.registry_entry["download"]
        args = _download_args(
            url=download_entry["url"],
            output=archive_path,
            manifest=manifest_path,
            license_id=candidate.license_id,
            expected_sha256=download_entry["bundle_sha256"],
            max_bytes=int(download_entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(f"GEOROC dataset download failed: {exc}") from exc
        content_type = result.get("content_type")
        accepted = set(download_entry["accepted_content_types"])
        if content_type and content_type not in accepted:
            raise SourceAdapterError(f"GEOROC returned unexpected content type: {content_type}")

        extract_dir = root / "members"
        if not extract_dir.exists():
            try:
                downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]) + 1,
                    max_extracted_bytes=int(download_entry["expected_uncompressed_bytes"]) + 1_000_000,
                    required_members=[entry["filename"] for entry in download_entry["members"]],
                    required_fields=candidate.registry_entry["required_fields"],
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"GEOROC safe extraction failed: {exc}") from exc
        return self._verified_members(
            extract_dir,
            result["status"],
            result.get("accessed_at") or result.get("cache_verified_at"),
        )

    @staticmethod
    def _rows(path: Path) -> Iterable[tuple[int, dict[str, str]]]:
        with path.open("r", encoding="latin-1", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise SourceAdapterError(f"GEOROC CSV has no header: {path.name}")
            for row in reader:
                first = (row.get("CITATIONS") or "").strip()
                if first.startswith("Abbreviations:"):
                    break
                if not any((value or "").strip() for value in row.values()):
                    break
                if not first:
                    continue
                yield reader.line_num, {key: (value or "").strip() for key, value in row.items() if key}

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        registered_ids = {
            entry["persistent_id"].rsplit("/", 1)[-1]
            for entry in self.candidate.registry_entry["download"]["members"]
        }
        for downloaded in files:
            if downloaded.file_id not in registered_ids:
                raise SourceAdapterError(f"unregistered GEOROC file_id: {downloaded.file_id}")
            for line_number, values in self._rows(downloaded.path):
                source_locator = f"{downloaded.path.name}#row={line_number}"
                native_id = values.get("SAMPLE NAME") or None
                source_record_id = stable_source_record_id(self.source_id, native_id, source_locator)
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=source_record_id,
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_dataset_version": self.candidate.version,
                    },
                )


class MarchemSnapshotAdapter(RegistryAdapter):
    """Content-addressed MarChem ZIP with semicolon data and method tables."""

    source_id = "norway-marchem"
    BATCH_CODE_RE = re.compile(r"\b\d{4}-\d{4}\b")

    @staticmethod
    def _semicolon_rows(path: Path, required_fields: Sequence[str]) -> list[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"MarChem member is unreadable: {path.name}") from exc
        with handle:
            reader = csv.DictReader(handle, delimiter=";")
            fieldnames = [str(value or "").strip() for value in (reader.fieldnames or [])]
            missing = sorted(set(required_fields) - set(fieldnames))
            if missing:
                raise SourceAdapterError(
                    f"MarChem member {path.name} lacks required fields: {', '.join(missing)}"
                )
            rows: list[tuple[int, dict[str, str]]] = []
            for row in reader:
                values = {str(key): str(value or "").strip() for key, value in row.items() if key}
                if any(values.values()):
                    rows.append((reader.line_num, values))
            return rows

    def _verified_members(
        self,
        extract_dir: Path,
        cache_status: str,
        retrieved_at: str | None,
    ) -> list[DownloadedFile]:
        download_entry = self.candidate.registry_entry["download"]
        expected = {item["filename"]: item for item in download_entry["members"]}
        actual = {
            str(path.relative_to(extract_dir))
            for path in extract_dir.rglob("*")
            if path.is_file()
        }
        if actual != set(expected):
            raise SourceAdapterError(
                "MarChem member set changed; "
                f"missing={sorted(set(expected) - actual)}, unexpected={sorted(actual - set(expected))}"
            )
        verified: list[DownloadedFile] = []
        for relative_name, entry in expected.items():
            path = extract_dir / relative_name
            if path.stat().st_size != entry["bytes"]:
                raise SourceAdapterError(f"MarChem member size changed: {relative_name}")
            observed = downloader.sha256_file(path)
            if observed != entry["expected_sha256"]:
                raise SourceAdapterError(f"MarChem member SHA-256 changed: {relative_name}")
            verified.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=entry["file_id"],
                    path=path,
                    source_url=f"{download_entry['url']}#member={relative_name}",
                    sha256=observed,
                    bytes=path.stat().st_size,
                    cache_status=cache_status,
                    retrieved_at=retrieved_at,
                )
            )
        return verified

    def files_from_archive(
        self,
        archive_path: Path,
        extract_dir: Path,
        *,
        cache_status: str = "verified_local_snapshot",
    ) -> list[DownloadedFile]:
        """Verify and safely extract an explicitly supplied copy of the frozen snapshot."""

        download_entry = self.candidate.registry_entry["download"]
        if not archive_path.is_file():
            raise SourceAdapterError(f"MarChem snapshot archive does not exist: {archive_path}")
        if archive_path.stat().st_size != download_entry["expected_bytes"]:
            raise SourceAdapterError("MarChem snapshot archive size does not match the registry")
        if downloader.sha256_file(archive_path) != download_entry["expected_sha256"]:
            raise SourceAdapterError("MarChem snapshot archive SHA-256 does not match the registry")
        try:
            downloader.safe_extract_zip(
                archive_path,
                extract_dir,
                max_members=int(download_entry["expected_member_count"]),
                max_extracted_bytes=int(download_entry["expected_uncompressed_bytes"]),
                required_members=[item["filename"] for item in download_entry["members"]],
                required_fields=(),
            )
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(f"MarChem safe extraction failed: {exc}") from exc
        return self._verified_members(extract_dir, cache_status, "2026-08-05T10:27:11Z")

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("MarChem adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("use a checked-in source-native fixture directly for fixture tests")
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        archive_path = root / download_entry["archive_filename"]
        manifest_path = root / "snapshot.download.json"
        args = _download_args(
            url=download_entry["url"],
            output=archive_path,
            manifest=manifest_path,
            license_id=candidate.license_id,
            expected_sha256=download_entry["expected_sha256"],
            max_bytes=int(download_entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(f"MarChem snapshot download failed: {exc}") from exc
        content_type = result.get("content_type")
        if content_type and content_type not in set(download_entry["accepted_content_types"]):
            raise SourceAdapterError(f"MarChem returned unexpected content type: {content_type}")
        extract_dir = root / "members"
        if not extract_dir.exists():
            try:
                downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]),
                    max_extracted_bytes=int(download_entry["expected_uncompressed_bytes"]),
                    required_members=[item["filename"] for item in download_entry["members"]],
                    required_fields=(),
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"MarChem safe extraction failed: {exc}") from exc
        return self._verified_members(
            extract_dir,
            result["status"],
            result.get("accessed_at") or result.get("cache_verified_at"),
        )

    def _metadata_index(self, metadata_path: Path) -> dict[tuple[str, str], dict[str, str]]:
        rows = self._semicolon_rows(
            metadata_path,
            self.candidate.registry_entry["metadata_required_fields"],
        )
        target_parameters = {
            self._parameter_code(field_name)
            for field_name in self.candidate.registry_entry["target_analytes"].values()
        }
        index: dict[tuple[str, str], dict[str, str]] = {}
        for line_number, values in rows:
            parameter = values.get("Lab_parameter_code", "")
            if not parameter or parameter not in target_parameters:
                continue
            batch_codes = self.BATCH_CODE_RE.findall(values.get("Batch", ""))
            for batch_code in batch_codes:
                key = (batch_code, parameter)
                candidate = {
                    **values,
                    "_metadata_source_locator": f"{metadata_path.name}#row={line_number}",
                    "_metadata_batch_expression": values.get("Batch", ""),
                }
                prior = index.get(key)
                if prior is not None and prior != candidate:
                    raise SourceAdapterError(
                        f"MarChem metadata has conflicting rows for batch={batch_code}, parameter={parameter}"
                    )
                index[key] = candidate
        return index

    @staticmethod
    def _parameter_code(field_name: str) -> str | None:
        match = re.fullmatch(r"(.+)_((?:mg|ug|ng)/kg)", field_name)
        return match.group(1) if match else None

    @staticmethod
    def _accreditation_status(comment: str) -> str:
        normalized = comment.strip().casefold()
        if normalized.startswith("not accredited"):
            return "not_accredited"
        if normalized.startswith("accredited"):
            return "accredited"
        return "unknown"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if set(by_id) != {"data", "metadata", "info"}:
            raise SourceAdapterError(
                f"MarChem adapter requires data, metadata and info members; received={sorted(by_id)}"
            )
        metadata = self._metadata_index(by_id["metadata"].path)
        data_rows = self._semicolon_rows(
            by_id["data"].path,
            self.candidate.registry_entry["required_fields"],
        )
        expected_counts = self.candidate.registry_entry["expected_counts"]
        if len(data_rows) != expected_counts["physical_rows"]:
            raise SourceAdapterError(
                f"MarChem physical-row count changed: {len(data_rows)} != {expected_counts['physical_rows']}"
            )
        target_fields = set(self.candidate.registry_entry["target_analytes"].values())
        records: list[RawRecord] = []
        for line_number, values in data_rows:
            batch_code = values.get("Batch_code", "")
            parameter_metadata: dict[str, dict[str, str]] = {}
            for field_name, raw_value in values.items():
                if not raw_value:
                    continue
                parameter_code = self._parameter_code(field_name)
                if parameter_code is None:
                    continue
                method = metadata.get((batch_code, parameter_code))
                if method is None:
                    if field_name in target_fields:
                        raise SourceAdapterError(
                            f"MarChem target metadata missing at data row {line_number}: "
                            f"batch={batch_code}, parameter={parameter_code}"
                        )
                    continue
                parameter_metadata[field_name] = {
                    **method,
                    "_accreditation_status": self._accreditation_status(method.get("Comment", "")),
                }
            source_locator = f"{by_id['data'].path.name}#row={line_number}"
            native_id = values.get("Sample_code") or None
            source_record_id = stable_source_record_id(
                self.source_id,
                native_id,
                source_locator,
            )
            records.append(
                RawRecord(
                    source_id=self.source_id,
                    source_record_id=source_record_id,
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_lab_parameters": parameter_metadata,
                        "_source_file": by_id["data"].path.name,
                        "_metadata_file": by_id["metadata"].path.name,
                        "_dataset_version": self.candidate.version,
                        "_snapshot_id": self.candidate.version,
                    },
                )
            )
        return records


class GemstatOpenArchiveAdapter(RegistryAdapter):
    """Pinned GEMStat v3 arsenic observations plus station and method metadata."""

    source_id = "gemstat-open-archive"
    FRACTIONS = {"As-Dis": "dissolved", "As-Sus": "suspended", "As-Tot": "total"}

    @staticmethod
    def _csv_rows(path: Path, required_fields: Sequence[str]) -> Iterable[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="cp1252", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"GEMStat member is unreadable: {path.name}") from exc
        with handle:
            reader = csv.DictReader(handle)
            fieldnames = [str(value or "").strip() for value in (reader.fieldnames or [])]
            missing = sorted(set(required_fields) - set(fieldnames))
            if missing:
                raise SourceAdapterError(f"GEMStat member {path.name} lacks fields: {', '.join(missing)}")
            for row in reader:
                yield reader.line_num, {
                    str(key): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("GEMStat adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in GEMStat demo directly for fixture tests")
        root = self._cache_root(cache_dir)
        entries = candidate.registry_entry["download"]["selected_members"]
        if any(not (root / "members" / entry["filename"]).is_file() for entry in entries):
            action = "Run acquire_gemstat_arsenic.py first" if mode == "online" else "Populate the verified cache"
            raise SourceAdapterError(f"{action}; the pinned GEMStat v3 arsenic subset is incomplete at {root}")
        files: list[DownloadedFile] = []
        for entry in entries:
            path = root / "members" / entry["filename"]
            if path.stat().st_size != entry["bytes"] or downloader.sha256_file(path) != entry["expected_sha256"]:
                raise SourceAdapterError(f"GEMStat selected member changed: {entry['filename']}")
            files.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=entry["file_id"],
                    path=path,
                    source_url=candidate.registry_entry["download"]["archive_url"],
                    sha256=entry["expected_sha256"],
                    bytes=entry["bytes"],
                    cache_status="cache_verified",
                    retrieved_at=candidate.registry_entry["download"]["observed_at"],
                )
            )
        return files

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        expected_ids = {"arsenic-observations", "methods", "parameters", "stations", "readme"}
        if set(by_id) != expected_ids:
            raise SourceAdapterError(f"GEMStat adapter requires five selected members; received={sorted(by_id)}")

        station_rows = list(
            self._csv_rows(by_id["stations"].path, self.candidate.registry_entry["station_required_fields"])
        )
        expected_counts = self.candidate.registry_entry["expected_counts"]
        if len(station_rows) != expected_counts["station_metadata_rows"]:
            raise SourceAdapterError("GEMStat station metadata row count changed")
        stations: dict[str, dict[str, Any]] = {}
        duplicate_station_rows = 0
        for line_number, values in station_rows:
            station_id = values.get("GEMS Station Number", "")
            if not station_id:
                raise SourceAdapterError("GEMStat station ID is missing")
            locator = f"{by_id['stations'].path.name}#row={line_number}"
            prior = stations.get(station_id)
            if prior is None:
                stations[station_id] = {**values, "_metadata_source_locators": [locator]}
                continue
            comparable = {key: value for key, value in prior.items() if key != "_metadata_source_locators"}
            if comparable != values:
                raise SourceAdapterError(f"GEMStat station ID has conflicting metadata: {station_id}")
            prior["_metadata_source_locators"].append(locator)
            duplicate_station_rows += 1
        if (
            len(stations) != expected_counts["station_metadata_unique_ids"]
            or duplicate_station_rows != expected_counts["station_metadata_exact_duplicate_rows"]
        ):
            raise SourceAdapterError("GEMStat station duplicate reconciliation changed")

        methods: dict[tuple[str, str, str], dict[str, str]] = {}
        method_rows = list(
            self._csv_rows(by_id["methods"].path, self.candidate.registry_entry["method_required_fields"])
        )
        for line_number, values in method_rows:
            key = (values["Parameter Code"], values["Analysis Method Code"], values["Unit"])
            if key in methods:
                raise SourceAdapterError(f"GEMStat method key is duplicated at row {line_number}: {key}")
            methods[key] = {**values, "_metadata_source_locator": f"{by_id['methods'].path.name}#row={line_number}"}
        if len(methods) != self.candidate.registry_entry["expected_counts"]["method_metadata_rows"]:
            raise SourceAdapterError("GEMStat method metadata row count changed")

        parameter_rows = list(self._csv_rows(by_id["parameters"].path, ("Parameter Code", "Parameter Long Name")))
        if len(parameter_rows) != self.candidate.registry_entry["expected_counts"]["parameter_metadata_rows"]:
            raise SourceAdapterError("GEMStat parameter metadata row count changed")
        parameter_codes = {values["Parameter Code"] for _, values in parameter_rows}
        if set(self.FRACTIONS) - parameter_codes:
            raise SourceAdapterError("GEMStat parameter metadata no longer defines all arsenic fractions")

        emitted = 0
        for line_number, values in self._csv_rows(
            by_id["arsenic-observations"].path,
            self.candidate.registry_entry["required_fields"],
        ):
            parameter_code = values.get("Parameter Code", "")
            if parameter_code not in self.FRACTIONS:
                raise SourceAdapterError(f"unexpected parameter in Arsenic.csv: {parameter_code}")
            station_id = values.get("GEMS Station Number", "")
            station = stations.get(station_id)
            if station is None:
                raise SourceAdapterError(f"GEMStat observation has no station metadata: {station_id}")
            method_key = (parameter_code, values.get("Analysis Method Code", ""), values.get("Unit", ""))
            method = methods.get(method_key)
            if method is None:
                raise SourceAdapterError(f"GEMStat observation has no method metadata: {method_key}")
            source_locator = f"{by_id['arsenic-observations'].path.name}#row={line_number}"
            native_id = "|".join(
                values.get(field, "")
                for field in (
                    "GEMS Station Number",
                    "Sample Date",
                    "Sample Time",
                    "Depth",
                    "Parameter Code",
                    "Analysis Method Code",
                )
            )
            emitted += 1
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(self.source_id, native_id, source_locator),
                source_locator=source_locator,
                fields={
                    **values,
                    "_station_metadata": station,
                    "_method_metadata": method,
                    "_water_fraction": self.FRACTIONS[parameter_code],
                    "_source_file": by_id["arsenic-observations"].path.name,
                    "_dataset_version": self.candidate.version,
                },
            )
        if emitted != self.candidate.registry_entry["expected_counts"]["arsenic_observations"]:
            raise SourceAdapterError(f"GEMStat arsenic row count changed: {emitted}")


class GeotracesIdp2025Adapter(RegistryAdapter):
    """Content-addressed webODV export of the IDP2025 discrete seawater collection."""

    source_id = "geotraces-idp2025"

    def files_from_archive(
        self,
        archive_path: Path,
        extract_dir: Path,
        *,
        cache_status: str = "verified_local_snapshot",
    ) -> list[DownloadedFile]:
        """Verify and safely extract the registered webODV export."""

        download_entry = self.candidate.registry_entry["download"]
        archive_entry = download_entry["files"][0]
        member_entry = download_entry["members"][0]
        if not archive_path.is_file():
            raise SourceAdapterError(f"GEOTRACES export archive does not exist: {archive_path}")
        if archive_path.stat().st_size != archive_entry["bytes"]:
            raise SourceAdapterError("GEOTRACES export archive size does not match the registry")
        if downloader.sha256_file(archive_path) != archive_entry["expected_sha256"]:
            raise SourceAdapterError("GEOTRACES export archive SHA-256 does not match the registry")
        if not extract_dir.exists():
            try:
                downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]),
                    max_extracted_bytes=int(download_entry["expected_uncompressed_bytes"]),
                    required_members=[member_entry["filename"]],
                    required_fields=(),
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"GEOTRACES safe extraction failed: {exc}") from exc
        member_path = extract_dir / member_entry["filename"]
        if member_path.stat().st_size != member_entry["bytes"]:
            raise SourceAdapterError("GEOTRACES export member size does not match the registry")
        observed_sha256 = downloader.sha256_file(member_path)
        if observed_sha256 != member_entry["expected_sha256"]:
            raise SourceAdapterError("GEOTRACES export member SHA-256 does not match the registry")
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=member_entry["file_id"],
                path=member_path,
                source_url=download_entry["exporter_landing_page"],
                sha256=observed_sha256,
                bytes=member_path.stat().st_size,
                cache_status=cache_status,
                retrieved_at=download_entry["observed_at"],
            )
        ]

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("GEOTRACES adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("use a checked-in synthetic ODV fixture directly for fixture tests")
        root = self._cache_root(cache_dir)
        archive_path = root / candidate.registry_entry["download"]["archive_filename"]
        if not archive_path.is_file():
            action = "Run acquire_geotraces_idp2025.py first" if mode == "online" else "Populate the verified cache"
            raise SourceAdapterError(
                f"{action}; the official webODV exporter creates a session-specific URL and the pinned archive "
                f"is not present at {archive_path}"
            )
        return self.files_from_archive(archive_path, root / "members", cache_status="cache_verified")

    def _rows(self, path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
        target_fields: Mapping[str, str] = self.candidate.registry_entry["target_analytes"]
        required = set(self.candidate.registry_entry["required_fields"])
        expected_rows = int(self.candidate.registry_entry["expected_counts"]["physical_rows"])
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"GEOTRACES export is unreadable: {path.name}") from exc
        with handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            indices: dict[str, int] = {}
            target_indices: dict[str, int] = {}
            emitted = 0
            for row in reader:
                if not row or str(row[0]).startswith("//"):
                    continue
                if header is None:
                    header = [str(value).strip() for value in row]
                    missing = sorted(required - set(header))
                    if missing:
                        raise SourceAdapterError(
                            f"GEOTRACES export lacks required fields: {', '.join(missing)}"
                        )
                    indices = {name: header.index(name) for name in required}
                    target_indices = {analyte: header.index(field) for analyte, field in target_fields.items()}
                    continue
                padded = [str(value).strip() for value in row] + [""] * max(0, len(header) - len(row))
                fields: dict[str, Any] = {name: padded[index] for name, index in indices.items()}
                observations: dict[str, dict[str, str]] = {}
                for analyte, value_index in target_indices.items():
                    field_name = target_fields[analyte]
                    observations[analyte] = {
                        "field": field_name,
                        "value": padded[value_index],
                        "standard_deviation": padded[value_index + 1],
                        "quality_flag": padded[value_index + 2],
                        "quality_schema": "SEADATANET",
                        "unit": "nmol/kg",
                    }
                    fields[field_name] = padded[value_index]
                    fields[f"{field_name}_STANDARD_DEV"] = padded[value_index + 1]
                    fields[f"{field_name}_QC"] = padded[value_index + 2]
                fields["_target_observations"] = observations
                fields["_source_file"] = path.name
                fields["_dataset_version"] = self.candidate.version
                emitted += 1
                yield reader.line_num, fields
            if header is None:
                raise SourceAdapterError("GEOTRACES export has no tabular header")
            if emitted != expected_rows:
                raise SourceAdapterError(
                    f"GEOTRACES physical-row count changed: {emitted} != {expected_rows}"
                )

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "seawater-depth-cu-ni-zn":
            raise SourceAdapterError("GEOTRACES adapter requires the registered seawater export member")
        downloaded = files[0]
        for line_number, values in self._rows(downloaded.path):
            source_locator = f"{downloaded.path.name}#row={line_number}"
            native_id = "|".join(
                str(values.get(field) or "")
                for field in ("Cruise", "Station", "yyyy-mm-ddThh:mm:ss.sss", "DEPTH [m]")
            )
            source_record_id = stable_source_record_id(self.source_id, native_id, source_locator)
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=source_record_id,
                source_locator=source_locator,
                fields=values,
            )


class GsjJapanRiverSedimentAdapter(RegistryAdapter):
    """Pinned GSJ national river-sediment sample and concentration tables."""

    source_id = "japan-gsj-geochemical-map"

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("GSJ adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in GSJ demo directly for fixture tests")
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        results: list[DownloadedFile] = []
        for file_entry in download_entry["files"]:
            output = root / file_entry["filename"]
            args = _download_args(
                url=file_entry["url"],
                output=output,
                manifest=root / f"{file_entry['file_id']}.download.json",
                license_id=candidate.license_id,
                expected_sha256=file_entry["expected_sha256"],
                max_bytes=int(download_entry["max_bytes_per_file"]),
                dataset_doi=candidate.dataset_doi,
                dataset_version=candidate.version,
                offline=mode == "cached",
            )
            try:
                result = downloader.run(args)
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"GSJ download failed for {file_entry['file_id']}: {exc}") from exc
            content_type = result.get("content_type")
            if content_type and content_type not in set(download_entry["accepted_content_types"]):
                raise SourceAdapterError(f"GSJ returned unexpected content type: {content_type}")
            if output.stat().st_size != file_entry["bytes"]:
                raise SourceAdapterError(f"GSJ file size changed: {output.name}")
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=output,
                    source_url=file_entry["url"],
                    sha256=result["sha256"],
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at") or result.get("cache_verified_at"),
                )
            )
        return results

    @staticmethod
    def _csv_rows(path: Path, required_fields: Sequence[str]) -> list[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="cp932", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"GSJ file is unreadable: {path.name}") from exc
        with handle:
            reader = csv.DictReader(handle)
            fields = [str(value or "").strip() for value in (reader.fieldnames or [])]
            missing = sorted(set(required_fields) - set(fields))
            if missing:
                raise SourceAdapterError(f"GSJ file {path.name} lacks fields: {', '.join(missing)}")
            rows: list[tuple[int, dict[str, str]]] = []
            for row in reader:
                values = {
                    str(key): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                if any(values.values()):
                    rows.append((reader.line_num, values))
            return rows

    @staticmethod
    def _join_key(raw_id: str, occurrences: dict[str, int]) -> tuple[str, int]:
        try:
            normalized_id = str(int(raw_id.strip()))
        except ValueError as exc:
            raise SourceAdapterError(f"GSJ sample ID is not an integer: {raw_id!r}") from exc
        occurrence = occurrences.get(normalized_id, 0)
        occurrences[normalized_id] = occurrence + 1
        return normalized_id, occurrence

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if set(by_id) != {"samples", "concentrations"}:
            raise SourceAdapterError("GSJ adapter requires samplejoho.csv and noudo.csv")
        samples = self._csv_rows(
            by_id["samples"].path, self.candidate.registry_entry["sample_required_fields"]
        )
        concentrations = self._csv_rows(
            by_id["concentrations"].path,
            self.candidate.registry_entry["concentration_required_fields"],
        )
        expected = self.candidate.registry_entry["expected_counts"]
        if len(samples) != expected["sample_rows"] or len(concentrations) != expected["concentration_rows"]:
            raise SourceAdapterError("GSJ valid source-row counts changed")

        concentration_occurrences: dict[str, int] = {}
        concentration_by_key: dict[tuple[str, int], tuple[int, dict[str, str]]] = {}
        for line_number, values in concentrations:
            key = self._join_key(values["番号2"], concentration_occurrences)
            if key in concentration_by_key:
                raise SourceAdapterError(f"GSJ concentration occurrence key is duplicated: {key}")
            concentration_by_key[key] = (line_number, values)

        sample_occurrences: dict[str, int] = {}
        sample_keys: set[tuple[str, int]] = set()
        for sample_line, sample in samples:
            key = self._join_key(sample["試料番号"], sample_occurrences)
            sample_keys.add(key)
            match = concentration_by_key.get(key)
            if match is None:
                raise SourceAdapterError(f"GSJ sample has no ordinal concentration match: {key}")
            concentration_line, concentration = match
            sample_locator = f"{by_id['samples'].path.name}#row={sample_line}"
            concentration_locator = f"{by_id['concentrations'].path.name}#row={concentration_line}"
            source_locator = f"{sample_locator};{concentration_locator}"
            native_id = f"{key[0]}#{key[1] + 1}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(self.source_id, native_id, source_locator),
                source_locator=source_locator,
                fields={
                    **sample,
                    **concentration,
                    "_normalized_sample_id": key[0],
                    "_sample_id_occurrence": key[1] + 1,
                    "_sample_source_locator": sample_locator,
                    "_concentration_source_locator": concentration_locator,
                    "_sample_source_file": by_id["samples"].path.name,
                    "_concentration_source_file": by_id["concentrations"].path.name,
                    "_dataset_version": self.candidate.version,
                    "_target_units": self.candidate.registry_entry["target_units"],
                },
            )
        if sample_keys != set(concentration_by_key):
            raise SourceAdapterError("GSJ sample and concentration ordinal key sets differ")
        if sample_occurrences.get("78013") != 2 or concentration_occurrences.get("78013") != 2:
            raise SourceAdapterError("GSJ duplicate sample 78013 reconciliation changed")


class PangaeaNorthAfricaSoilAdapter(RegistryAdapter):
    """Pinned PANGAEA tabular dataset of deflatable North African soil fractions."""

    source_id = "pangaea-north-africa-soil"

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("PANGAEA adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in PANGAEA demo directly for fixture tests")
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        file_entry = download_entry["files"][0]
        output = root / file_entry["filename"]
        args = _download_args(
            url=file_entry["url"],
            output=output,
            manifest=root / "dataset.download.json",
            license_id=candidate.license_id,
            expected_sha256=file_entry["expected_sha256"],
            max_bytes=int(download_entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
            required_fields=candidate.registry_entry["required_fields"],
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(f"PANGAEA dataset download failed: {exc}") from exc
        content_type = result.get("content_type")
        if content_type and content_type not in set(download_entry["accepted_content_types"]):
            raise SourceAdapterError(f"PANGAEA returned unexpected content type: {content_type}")
        if output.stat().st_size != file_entry["bytes"]:
            raise SourceAdapterError("PANGAEA file size changed")
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=file_entry["file_id"],
                path=output,
                source_url=file_entry["url"],
                sha256=result["sha256"],
                bytes=result["bytes"],
                cache_status=result["status"],
                retrieved_at=result.get("accessed_at") or result.get("cache_verified_at"),
            )
        ]

    def _rows(self, path: Path) -> Iterable[tuple[int, dict[str, str]]]:
        required = set(self.candidate.registry_entry["required_fields"])
        target_fields = set(self.candidate.registry_entry["target_analytes"].values())
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"PANGAEA file is unreadable: {path.name}") from exc
        with handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            emitted = 0
            nonempty_measurements = 0
            for row in reader:
                if header is None:
                    if row and row[0].strip() == "*/":
                        try:
                            header = [value.strip() for value in next(reader)]
                        except StopIteration as exc:
                            raise SourceAdapterError("PANGAEA file ends before its tabular header") from exc
                        missing = sorted((required | target_fields) - set(header))
                        if missing:
                            raise SourceAdapterError(
                                f"PANGAEA file lacks required fields: {', '.join(missing)}"
                            )
                        element_fields = [field for field in header if field.endswith(" [mg/kg]")]
                        if len(element_fields) != self.candidate.registry_entry["expected_counts"]["element_fields"]:
                            raise SourceAdapterError("PANGAEA elemental field count changed")
                    continue
                if not any(value.strip() for value in row):
                    continue
                padded = [value.strip() for value in row] + [""] * max(0, len(header) - len(row))
                values = dict(zip(header, padded, strict=False))
                if not values.get("Sample ID"):
                    raise SourceAdapterError(f"PANGAEA sample ID is missing at row {reader.line_num}")
                emitted += 1
                nonempty_measurements += sum(
                    bool(values.get(field, ""))
                    for field in element_fields
                )
                yield reader.line_num, values
            if header is None:
                raise SourceAdapterError("PANGAEA file has no DATA DESCRIPTION terminator or table header")
            expected = self.candidate.registry_entry["expected_counts"]
            if emitted != expected["physical_rows"]:
                raise SourceAdapterError(
                    f"PANGAEA physical-row count changed: {emitted} != {expected['physical_rows']}"
                )
            if nonempty_measurements != expected["nonempty_element_measurements"]:
                raise SourceAdapterError("PANGAEA nonempty elemental-measurement count changed")

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "table-s5":
            raise SourceAdapterError("PANGAEA adapter requires the registered Table S5 file")
        downloaded = files[0]
        for line_number, values in self._rows(downloaded.path):
            source_locator = f"{downloaded.path.name}#row={line_number}"
            native_id = values.get("Sample ID") or values.get("Event")
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(self.source_id, native_id, source_locator),
                source_locator=source_locator,
                fields={
                    **values,
                    "_source_file": downloaded.path.name,
                    "_dataset_version": self.candidate.version,
                    "_analytical_method": "Agilent 7900 quadrupole ICP-MS; 2.5% HNO3 eluent",
                    "_digestion_or_extraction": "HF-HNO3 acid digestion",
                },
            )


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Keep the one legacy FOREGS HTTP exception on its registered host and URL."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class ForegsAdapter(RegistryAdapter):
    """Pinned FOREGS CSV members from one official medium-specific ZIP archive."""

    official_host = "weppi.gtk.fi"

    @classmethod
    def _validate_pinned_http_url(cls, url: str) -> None:
        parsed = urllib.parse.urlparse(url)
        if (
            parsed.scheme.casefold() != "http"
            or parsed.hostname != cls.official_host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise SourceAdapterError("FOREGS legacy transport must be the registered public GTK HTTP URL")
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)}
        except socket.gaierror as exc:
            raise SourceAdapterError("FOREGS publisher hostname could not be resolved") from exc
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise SourceAdapterError("FOREGS publisher hostname did not resolve exclusively to public addresses")

    @classmethod
    def _download_once_pinned_http(
        cls,
        url: str,
        output: Path,
        timeout: float,
        max_bytes: int,
        expected_sha256: str | None,
    ) -> dict[str, Any]:
        if not expected_sha256:
            raise SourceAdapterError("FOREGS HTTP transport is allowed only with a pinned SHA-256")
        cls._validate_pinned_http_url(url)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            request = urllib.request.Request(
                url,
                headers={"User-Agent": downloader.USER_AGENT, "Accept": "application/zip"},
            )
            opener = urllib.request.build_opener(_RejectRedirects())
            with opener.open(request, timeout=timeout) as response:
                if response.geturl() != url:
                    raise SourceAdapterError("FOREGS legacy transport redirected away from the pinned URL")
                content_type = response.headers.get_content_type().casefold()
                downloader.validate_response_metadata(
                    content_type,
                    response.headers.get("Content-Length"),
                    max_bytes,
                )
                with tempfile.NamedTemporaryFile(
                    "wb", prefix=f".{output.name}.", suffix=".part", dir=output.parent, delete=False
                ) as handle:
                    temporary = Path(handle.name)
                    total, observed = downloader.copy_response_bounded(response, handle, max_bytes)
                if total == 0 or observed != expected_sha256:
                    raise SourceAdapterError("FOREGS archive is empty or differs from the pinned SHA-256")
                os.replace(temporary, output)
                temporary = None
                return {
                    "status": "downloaded",
                    "source_url": url,
                    "resolved_url": url,
                    "content_type": content_type,
                    "bytes": total,
                    "sha256": observed,
                    "sha256_basis": "expected",
                    "accessed_at": downloader.utc_now(),
                    "http_status": getattr(response, "status", 200),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "transport_security": "publisher_http_with_pinned_sha256_integrity",
                }
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("FOREGS adapter received a candidate for another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in FOREGS demo directly for fixture tests")
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        archive_entry = download_entry["files"][0]
        archive_root = archive_entry["filename"].removesuffix(".zip").replace("-", " ")
        archive_path = root / archive_entry["filename"]
        manifest_path = root / "dataset.download.json"
        if mode == "cached":
            if not archive_path.is_file():
                raise SourceAdapterError(f"FOREGS verified cache is missing: {archive_path}")
            observed = downloader.sha256_file(archive_path)
            if observed != archive_entry["expected_sha256"] or archive_path.stat().st_size != archive_entry["bytes"]:
                raise SourceAdapterError("FOREGS cached archive size or SHA-256 changed")
            original_accessed_at: str | None = None
            if manifest_path.is_file():
                try:
                    cached_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise SourceAdapterError("FOREGS cached acquisition manifest is unreadable") from exc
                if (
                    cached_manifest.get("source_url") == archive_entry["url"]
                    and cached_manifest.get("sha256") == observed
                ):
                    original_accessed_at = cached_manifest.get("accessed_at")
            result: dict[str, Any] = {
                "status": "cache_hit",
                "source_url": archive_entry["url"],
                "sha256": observed,
                "bytes": archive_path.stat().st_size,
                # Do not invent a retrieval time for a manually populated cache. If an
                # online acquisition manifest exists, retain its original timestamp.
                "cache_verified_at": original_accessed_at,
            }
        else:
            try:
                result = downloader.download_with_retries(
                    archive_entry["url"],
                    archive_path,
                    30.0,
                    int(download_entry["max_bytes"]),
                    archive_entry["expected_sha256"],
                    2,
                    downloader=self._download_once_pinned_http,
                )
            except (downloader.DownloadError, SourceAdapterError, OSError) as exc:
                raise SourceAdapterError(f"FOREGS archive download failed: {exc}") from exc
            downloader.atomic_json(
                manifest_path,
                {
                    **result,
                    "dataset_version": candidate.version,
                    "license": candidate.license_id,
                    "transport_exception": (
                        "GTK currently serves the byte-pinned public archive over HTTP; content integrity is "
                        "enforced before publication by the registered SHA-256. Redirects are rejected."
                    ),
                },
            )

        extract_dir = root / "members"
        if not extract_dir.exists():
            try:
                extracted = downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]),
                    max_extracted_bytes=int(download_entry["max_extracted_bytes"]),
                    required_members=[
                        f"{archive_root}/{entry['filename']}" for entry in download_entry["members"]
                    ],
                    required_fields=[],
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"FOREGS archive extraction failed: {exc}") from exc
            if len(extracted) != int(download_entry["expected_member_count"]):
                raise SourceAdapterError("FOREGS archive member count changed")

        verified: list[DownloadedFile] = []
        for member in download_entry["members"]:
            path = extract_dir / archive_root / member["filename"]
            if (
                not path.is_file()
                or path.stat().st_size != member["bytes"]
                or downloader.sha256_file(path) != member["expected_sha256"]
            ):
                raise SourceAdapterError(f"FOREGS member size or SHA-256 changed: {member['filename']}")
            verified.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=member["file_id"],
                    path=path,
                    source_url=f"{archive_entry['url']}#member={urllib.parse.quote(member['filename'])}",
                    sha256=member["expected_sha256"],
                    bytes=member["bytes"],
                    cache_status=str(result["status"]),
                    retrieved_at=result.get("accessed_at") or result.get("cache_verified_at"),
                )
            )
        return verified

    @staticmethod
    def _unique_headers(values: Sequence[str]) -> list[str]:
        occurrences: dict[str, int] = {}
        headers: list[str] = []
        for index, value in enumerate(values, start=1):
            base = value.strip() or f"_unnamed_{index}"
            occurrences[base] = occurrences.get(base, 0) + 1
            headers.append(base if occurrences[base] == 1 else f"{base}__{occurrences[base]}")
        return headers

    @staticmethod
    def _half_detection_limit(raw_value: str, detection_limit: str) -> bool:
        try:
            return float(raw_value) == float(detection_limit) / 2
        except ValueError:
            return False

    def _rows(
        self,
        path: Path,
        member: Mapping[str, Any],
    ) -> Iterable[tuple[int, dict[str, str], dict[str, str], dict[str, str]]]:
        try:
            handle = path.open("r", encoding="latin-1", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"FOREGS member is unreadable: {path.name}") from exc
        with handle:
            reader = csv.reader(handle)
            try:
                headers = self._unique_headers(next(reader))
                units_row = [value.strip() for value in next(reader)]
                detection_row = [value.strip() for value in next(reader)]
            except StopIteration as exc:
                raise SourceAdapterError(f"FOREGS member lacks its three metadata rows: {path.name}") from exc
            folded = {field.casefold(): field for field in headers}
            required = {str(field).casefold() for field in member["required_fields"]}
            if not required.issubset(folded):
                raise SourceAdapterError(f"FOREGS member lacks required fields: {path.name}")
            native_field = folded["gtn"]
            units = dict(zip(headers, units_row, strict=False))
            detection_limits = dict(zip(headers, detection_row, strict=False))
            emitted = 0
            for row in reader:
                stripped = [value.strip() for value in row]
                if not any(stripped):
                    continue
                padded = stripped + [""] * max(0, len(headers) - len(stripped))
                values = dict(zip(headers, padded, strict=False))
                if not values.get(native_field):
                    continue
                emitted += 1
                yield reader.line_num, values, units, detection_limits
            if emitted != int(member["physical_rows"]):
                raise SourceAdapterError(
                    f"FOREGS row count changed for {path.name}: {emitted} != {member['physical_rows']}"
                )

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        registered = {
            entry["file_id"]: entry for entry in self.candidate.registry_entry["download"]["members"]
        }
        if {item.file_id for item in files} != set(registered):
            raise SourceAdapterError("FOREGS adapter requires the exact registered CSV member set")
        total_rows = 0
        for downloaded in files:
            member = registered[downloaded.file_id]
            for line_number, values, units, detection_limits in self._rows(downloaded.path, member):
                total_rows += 1
                folded = {field.casefold(): field for field in values}
                native_id = values[folded["gtn"]]
                source_locator = f"{downloaded.path.name}#row={line_number}"
                observations: dict[str, dict[str, Any]] = {}
                for analyte, field in member.get("target_analytes", {}).items():
                    raw_value = str(values.get(field) or "").strip()
                    unit = str(units.get(field) or "").strip()
                    detection_limit = str(detection_limits.get(field) or "").strip()
                    if raw_value:
                        observations[analyte] = {
                            "value": raw_value,
                            "unit": unit,
                            "detection_limit": detection_limit,
                            "measurement_basis": member["measurement_basis"],
                            "analytical_method": member["analytical_method"],
                            "digestion_or_extraction": member["digestion_or_extraction"],
                            "possible_upstream_dl_over_2_substitution": self._half_detection_limit(
                                raw_value, detection_limit
                            ),
                        }
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(self.source_id, native_id, source_locator),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_units": units,
                        "_detection_limits": detection_limits,
                        "_target_observations": observations,
                        "_source_file": downloaded.path.name,
                        "_medium": self.candidate.registry_entry["media"][0],
                        "_sample_type": self.candidate.registry_entry["sample_type"],
                        "_measurement_basis": member["measurement_basis"],
                        "_analytical_method": member["analytical_method"],
                        "_digestion_or_extraction": member["digestion_or_extraction"],
                        "_sample_depth_min_m": self.candidate.registry_entry["sample_depth_min_m"],
                        "_sample_depth_max_m": self.candidate.registry_entry["sample_depth_max_m"],
                        "_grain_fraction": self.candidate.registry_entry["grain_fraction"],
                        "_dataset_version": self.candidate.version,
                        "_censoring_boundary": (
                            "The published numeric CSV has no row-level less-than qualifier. Values exactly at half "
                            "the table DL are flagged as possible upstream DL/2 substitutions, not asserted as detections."
                        ),
                    },
                )
        expected = int(self.candidate.registry_entry["expected_counts"]["physical_rows"])
        if total_rows != expected:
            raise SourceAdapterError(f"FOREGS total parsed row count changed: {total_rows} != {expected}")


class ForegsTopsoilAdapter(ForegsAdapter):
    source_id = "foregs-topsoil"


class ForegsSubsoilAdapter(ForegsAdapter):
    source_id = "foregs-subsoil"


class ForegsHumusAdapter(ForegsAdapter):
    source_id = "foregs-humus"


class ForegsStreamWaterAdapter(ForegsAdapter):
    source_id = "foregs-stream-water"


class ForegsStreamSedimentAdapter(ForegsAdapter):
    source_id = "foregs-stream-sediment"


class ForegsFloodplainSedimentAdapter(ForegsAdapter):
    source_id = "foregs-floodplain-sediment"


ADAPTERS: Mapping[str, type[RegistryAdapter]] = {
    GeorocArchaeanAdapter.source_id: GeorocArchaeanAdapter,
    UsgsSoilAdapter.source_id: UsgsSoilAdapter,
    MarchemSnapshotAdapter.source_id: MarchemSnapshotAdapter,
    GemstatOpenArchiveAdapter.source_id: GemstatOpenArchiveAdapter,
    GeotracesIdp2025Adapter.source_id: GeotracesIdp2025Adapter,
    GsjJapanRiverSedimentAdapter.source_id: GsjJapanRiverSedimentAdapter,
    PangaeaNorthAfricaSoilAdapter.source_id: PangaeaNorthAfricaSoilAdapter,
    ForegsTopsoilAdapter.source_id: ForegsTopsoilAdapter,
    ForegsSubsoilAdapter.source_id: ForegsSubsoilAdapter,
    ForegsHumusAdapter.source_id: ForegsHumusAdapter,
    ForegsStreamWaterAdapter.source_id: ForegsStreamWaterAdapter,
    ForegsStreamSedimentAdapter.source_id: ForegsStreamSedimentAdapter,
    ForegsFloodplainSedimentAdapter.source_id: ForegsFloodplainSedimentAdapter,
}


def get_adapter(source_id: str, registry_path: Path = DEFAULT_REGISTRY) -> RegistryAdapter:
    """Instantiate a registered adapter without dynamic imports or arbitrary code execution."""

    adapter_type = ADAPTERS.get(source_id)
    if adapter_type is None:
        raise SourceAdapterError(f"no adapter is registered for source_id: {source_id}")
    return adapter_type(registry_path)
