#!/usr/bin/env python3
"""Shared D1 contracts for versioned scientific data-source adapters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import ipaddress
import io
import json
import math
import os
import re
import shutil
import socket
import struct
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
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
    bytes: int
    cache_status: str
    retrieved_at: str | None
    sha256: str = ""

    def __post_init__(self) -> None:
        """Always bind local bytes even when a publisher did not publish a checksum."""
        if self.sha256:
            return
        digest = hashlib.sha256()
        with self.path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        object.__setattr__(self, "sha256", digest.hexdigest())


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
    def discover(
        self, request: Mapping[str, Any] | None = None
    ) -> list[DatasetCandidate]:
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


def stable_source_record_id(
    source_id: str, native_id: str | None, source_locator: str
) -> str:
    """Build a stable source-row ID without depending on cache or output paths."""

    normalized_source = source_id.strip()
    normalized_locator = source_locator.strip()
    normalized_native = (native_id or "").strip()
    if not normalized_source or not normalized_locator:
        raise SourceAdapterError(
            "source_id and source_locator are required for a stable source record ID"
        )
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
    values = tuple(
        value.strip()
        for value in (
            source_id,
            source_record_id,
            analyte_reported,
            original_value_raw,
            original_unit,
        )
    )
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
        raise SourceAdapterError(
            f"source registry is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(registry, dict):
        raise SourceAdapterError("source registry must be a JSON object")
    if registry.get("registry_version") != "geochemical-source-registry-v1":
        raise SourceAdapterError("unsupported source registry version")
    sources = registry.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise SourceAdapterError(
            "source registry must contain a non-empty sources object"
        )
    for source_id, entry in sources.items():
        if (
            not isinstance(source_id, str)
            or not source_id
            or not isinstance(entry, dict)
        ):
            raise SourceAdapterError("source registry contains an invalid source entry")
        required = {
            "adapter",
            "title",
            "dataset_version",
            "landing_page",
            "license",
            "download",
        }
        missing = sorted(required - set(entry))
        if missing:
            raise SourceAdapterError(
                f"source {source_id} lacks required registry keys: {', '.join(missing)}"
            )
        license_entry = entry.get("license")
        if (
            not isinstance(license_entry, dict)
            or not license_entry.get("spdx")
            or not license_entry.get("url")
        ):
            raise SourceAdapterError(
                f"source {source_id} has incomplete license metadata"
            )
    return registry


def registry_candidate(
    source_id: str, path: Path = DEFAULT_REGISTRY
) -> DatasetCandidate:
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


def source_lineage_id(source_id: str) -> str:
    """Return the upstream project lineage used for coverage independence."""

    if source_id.startswith("georoc-"):
        return "georoc-compilation"
    if source_id.startswith("foregs-"):
        return "foregs-geochemical-atlas-europe-2005"
    return source_id


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


def accepted_content_types_for_file(
    download_entry: Mapping[str, Any], file_entry: Mapping[str, Any]
) -> set[str]:
    """Return an explicit per-file MIME allowlist, falling back to the bundle list."""

    values = file_entry.get(
        "accepted_content_types", download_entry.get("accepted_content_types", ())
    )
    if (
        not isinstance(values, list)
        or not values
        or not all(isinstance(value, str) and value.strip() for value in values)
    ):
        raise SourceAdapterError(
            "download MIME allowlist must be a non-empty string list"
        )
    return {value.casefold().strip() for value in values}


def _request_allows(
    candidate: DatasetCandidate, request: Mapping[str, Any] | None
) -> bool:
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

    def discover(
        self, request: Mapping[str, Any] | None = None
    ) -> list[DatasetCandidate]:
        return [self.candidate] if _request_allows(self.candidate, request) else []

    def provenance(self) -> Mapping[str, Any]:
        return self.candidate.registry_entry

    def _cache_root(self, cache_dir: Path) -> Path:
        safe_version = (
            re.sub(r"[^A-Za-z0-9._-]+", "-", self.candidate.version).strip("-")
            or "unknown"
        )
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
            raise SourceAdapterError(
                "USGS adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "source-specific fixture mode is not available until the demo slice is generated"
            )
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
                raise SourceAdapterError(
                    f"USGS download failed for {file_entry['file_id']}: {exc}"
                ) from exc
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
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at")
                    or result.get("cache_verified_at"),
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
                    if {"SiteID", "StateID", "Latitude", "Longitude"}.issubset(
                        stripped
                    ):
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
        registered = {
            item["file_id"]: item
            for item in self.candidate.registry_entry["download"]["files"]
        }
        for downloaded in files:
            file_entry = registered.get(downloaded.file_id)
            if not file_entry:
                raise SourceAdapterError(
                    f"unregistered USGS file_id: {downloaded.file_id}"
                )
            for line_number, values, units in self._rows(downloaded.path):
                source_locator = f"{downloaded.path.name}#row={line_number}"
                native_id = values.get(
                    f"{file_entry['header_prefix']}LabID"
                ) or values.get("SiteID")
                source_record_id = stable_source_record_id(
                    self.source_id, native_id, source_locator
                )
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

    @staticmethod
    def _member_download_url(persistent_id: str) -> str:
        query = urllib.parse.urlencode(
            {"persistentId": persistent_id, "format": "original"}
        )
        return (
            "https://data.goettingen-research-online.de/api/access/"
            f"datafile/:persistentId/?{query}"
        )

    def _download_verified_members(
        self,
        root: Path,
        mode: DownloadMode,
        archive_error: Exception,
    ) -> list[DownloadedFile]:
        """Fall back from the failing dataset ZIP to the same pinned members.

        GRO.data exposes both a dataset-level archive endpoint and immutable
        member persistent IDs.  The former can fail independently with HTTP
        500 while every member endpoint remains healthy.  Download into a
        private staging directory, then publish only after exact byte count,
        publisher MD5 and required-field checks all pass.  This is an
        availability fallback, not a weaker integrity policy.
        """

        if mode == "cached":
            raise SourceAdapterError(
                "GEOROC cached acquisition has neither a verified extracted member "
                "set nor a reusable dataset archive; online mode is required to "
                "repair the cache"
            ) from archive_error
        root.mkdir(parents=True, exist_ok=True)
        destination = root / "members"
        staging: Path | None = Path(
            tempfile.mkdtemp(prefix=".members.", suffix=".part", dir=root)
        )
        retrieved_at: str | None = None
        try:
            for entry in self.candidate.registry_entry["download"]["members"]:
                persistent_id = str(entry["persistent_id"])
                file_id = persistent_id.rsplit("/", 1)[-1]
                assert staging is not None
                output = staging / str(entry["filename"])
                manifest = staging / f"{file_id}.download.json"
                url = self._member_download_url(persistent_id)
                args = _download_args(
                    url=url,
                    output=output,
                    manifest=manifest,
                    license_id=self.candidate.license_id,
                    expected_sha256=None,
                    max_bytes=int(entry["bytes"]),
                    dataset_doi=self.candidate.dataset_doi,
                    dataset_version=self.candidate.version,
                    offline=False,
                    required_fields=self.candidate.registry_entry["required_fields"],
                )
                try:
                    result = downloader.run(args)
                except (downloader.DownloadError, OSError) as exc:
                    raise SourceAdapterError(
                        f"GEOROC member fallback failed for {file_id}: {exc}; "
                        f"dataset archive failure was: {archive_error}"
                    ) from exc
                content_type = str(result.get("content_type") or "")
                if content_type and content_type not in {
                    "text/csv",
                    "application/octet-stream",
                }:
                    raise SourceAdapterError(
                        "GEOROC member fallback returned unexpected content type "
                        f"for {file_id}: {content_type}"
                    )
                if output.stat().st_size != int(entry["bytes"]):
                    raise SourceAdapterError(
                        f"GEOROC member fallback size changed: {output.name}"
                    )
                checksum = entry["publisher_checksum"]
                if checksum.get("algorithm") != "md5" or _md5_file(
                    output
                ) != checksum.get("value"):
                    raise SourceAdapterError(
                        f"GEOROC member fallback publisher checksum mismatch: {output.name}"
                    )
                retrieved_at = (
                    result.get("accessed_at")
                    or result.get("cache_verified_at")
                    or retrieved_at
                )
            os.replace(staging, destination)
            staging = None
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging)
        return self._verified_members(destination, "downloaded", retrieved_at)

    def _verified_members(
        self, extract_dir: Path, cache_status: str, retrieved_at: str | None
    ) -> list[DownloadedFile]:
        members = self.candidate.registry_entry["download"]["members"]
        expected_names = {entry["filename"] for entry in members}
        actual_names = {
            path.name for path in extract_dir.glob("*.csv") if path.is_file()
        }
        if actual_names != expected_names:
            missing = sorted(expected_names - actual_names)
            unexpected = sorted(actual_names - expected_names)
            raise SourceAdapterError(
                f"GEOROC member set changed; missing={missing}, unexpected={unexpected}"
            )
        verified: list[DownloadedFile] = []
        for entry in members:
            path = extract_dir / entry["filename"]
            if path.stat().st_size != entry["bytes"]:
                raise SourceAdapterError(f"GEOROC member size changed: {path.name}")
            checksum = entry["publisher_checksum"]
            if checksum["algorithm"] != "md5" or _md5_file(path) != checksum["value"]:
                raise SourceAdapterError(
                    f"GEOROC publisher checksum mismatch: {path.name}"
                )
            downloader._read_delimited_header(
                path, self.candidate.registry_entry["required_fields"]
            )
            persistent_id = entry["persistent_id"].removeprefix("doi:")
            verified.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=persistent_id.rsplit("/", 1)[-1],
                    path=path,
                    source_url=f"https://doi.org/{persistent_id}",
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
            raise SourceAdapterError(
                "GEOROC adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "source-specific fixture mode is not available until the demo slice is generated"
            )
        root = self._cache_root(cache_dir)
        extract_dir = root / "members"
        if extract_dir.exists():
            return self._verified_members(extract_dir, "cache_hit", None)
        archive_path = root / (
            f"{self.source_id}-v{candidate.version.split('.', 1)[0]}.zip"
        )
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
            return self._download_verified_members(root, mode, exc)
        content_type = result.get("content_type")
        accepted = set(download_entry["accepted_content_types"])
        if content_type and content_type not in accepted:
            return self._download_verified_members(
                root,
                mode,
                SourceAdapterError(
                    f"GEOROC returned unexpected content type: {content_type}"
                ),
            )

        if not extract_dir.exists():
            try:
                downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]) + 1,
                    max_extracted_bytes=int(
                        download_entry["expected_uncompressed_bytes"]
                    )
                    + 1_000_000,
                    required_members=[
                        entry["filename"] for entry in download_entry["members"]
                    ],
                    required_fields=candidate.registry_entry["required_fields"],
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"GEOROC safe extraction failed: {exc}"
                ) from exc
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
                yield (
                    reader.line_num,
                    {key: (value or "").strip() for key, value in row.items() if key},
                )

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        registered_ids = {
            entry["persistent_id"].rsplit("/", 1)[-1]
            for entry in self.candidate.registry_entry["download"]["members"]
        }
        for downloaded in files:
            if downloaded.file_id not in registered_ids:
                raise SourceAdapterError(
                    f"unregistered GEOROC file_id: {downloaded.file_id}"
                )
            for line_number, values in self._rows(downloaded.path):
                source_locator = f"{downloaded.path.name}#row={line_number}"
                native_id = values.get("SAMPLE NAME") or None
                source_record_id = stable_source_record_id(
                    self.source_id, native_id, source_locator
                )
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


class GeorocConvergentMarginsAdapter(GeorocArchaeanAdapter):
    """GEOROC Dataverse versioned ZIP containing one CSV per convergent margin.

    The download, member-fallback, verification and parse logic is identical to
    the Archaean compilation adapter; only the registered dataset differs.
    """

    source_id = "georoc-convergent-margins"


class MarchemSnapshotAdapter(RegistryAdapter):
    """Semantically pinned MarChem export with immutable scientific members.

    MarChem regenerates the outer ZIP and the human-readable information member
    on every otherwise identical export.  Treating that wrapper hash as the
    scientific version therefore creates false source failures.  Admission is
    instead fail-closed on the registered data and method-member hashes while
    the timestamped information member is checked against the frozen request
    semantics and retained as observed provenance.
    """

    source_id = "norway-marchem"
    BATCH_CODE_RE = re.compile(r"\b\d{4}-\d{4}\b")
    MEMBER_PATTERNS: Mapping[str, re.Pattern[str]] = {
        "metadata": re.compile(
            r"^MetaData/MarChem_Inorganic_LabParameter_\d{8}T\d{6}Z\.csv$"
        ),
        "data": re.compile(r"^MarChem_Inorganic_Data_\d{8}T\d{6}Z\.csv$"),
        "info": re.compile(r"^MarChem_Info_\d{8}T\d{6}Z$"),
    }

    @staticmethod
    def _semicolon_rows(
        path: Path, required_fields: Sequence[str]
    ) -> list[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"MarChem member is unreadable: {path.name}"
            ) from exc
        with handle:
            reader = csv.DictReader(handle, delimiter=";")
            fieldnames = [
                str(value or "").strip() for value in (reader.fieldnames or [])
            ]
            missing = sorted(set(required_fields) - set(fieldnames))
            if missing:
                raise SourceAdapterError(
                    f"MarChem member {path.name} lacks required fields: {', '.join(missing)}"
                )
            rows: list[tuple[int, dict[str, str]]] = []
            for row in reader:
                values = {
                    str(key): str(value or "").strip()
                    for key, value in row.items()
                    if key
                }
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
        expected = {item["file_id"]: item for item in download_entry["members"]}
        actual_paths = sorted(path for path in extract_dir.rglob("*") if path.is_file())
        if len(actual_paths) != len(self.MEMBER_PATTERNS):
            raise SourceAdapterError(
                "MarChem member count changed; "
                f"expected={len(self.MEMBER_PATTERNS)}, observed={len(actual_paths)}"
            )
        actual: dict[str, tuple[str, Path]] = {}
        for path in actual_paths:
            relative_name = path.relative_to(extract_dir).as_posix()
            roles = [
                role
                for role, pattern in self.MEMBER_PATTERNS.items()
                if pattern.fullmatch(relative_name)
            ]
            if len(roles) != 1 or roles[0] in actual:
                raise SourceAdapterError(
                    f"MarChem member cannot be assigned uniquely: {relative_name}"
                )
            actual[roles[0]] = (relative_name, path)
        if set(actual) != set(expected):
            raise SourceAdapterError(
                "MarChem semantic member roles changed; "
                f"missing={sorted(set(expected) - set(actual))}, "
                f"unexpected={sorted(set(actual) - set(expected))}"
            )

        scientific_member_ids = set(
            download_entry.get("scientific_member_ids", ["data", "metadata"])
        )
        if scientific_member_ids != {"data", "metadata"}:
            raise SourceAdapterError(
                "MarChem registry must pin exactly the data and metadata members"
            )
        verified: list[DownloadedFile] = []
        for role in ("metadata", "data", "info"):
            entry = expected[role]
            relative_name, path = actual[role]
            if role in scientific_member_ids:
                if path.stat().st_size != entry["bytes"]:
                    raise SourceAdapterError(
                        f"MarChem scientific member size changed: {role}"
                    )
                observed = downloader.sha256_file(path)
                if observed != entry["expected_sha256"]:
                    raise SourceAdapterError(
                        f"MarChem scientific member SHA-256 changed: {role}"
                    )
            else:
                try:
                    info_text = path.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError) as exc:
                    raise SourceAdapterError(
                        "MarChem information member is not valid UTF-8 text"
                    ) from exc
                if path.stat().st_size > int(
                    download_entry.get("max_information_member_bytes", 20_000)
                ):
                    raise SourceAdapterError(
                        "MarChem information member exceeds the registered bound"
                    )
                missing_semantics = [
                    value
                    for value in download_entry.get(
                        "information_member_required_text", []
                    )
                    if value not in info_text
                ]
                if missing_semantics:
                    raise SourceAdapterError(
                        "MarChem information member no longer proves the frozen "
                        f"request semantics: {missing_semantics}"
                    )
            verified.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=entry["file_id"],
                    path=path,
                    source_url=f"{download_entry['url']}#member={relative_name}",
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
        """Verify a dynamic wrapper against the frozen scientific-member contract."""

        download_entry = self.candidate.registry_entry["download"]
        if not archive_path.is_file():
            raise SourceAdapterError(
                f"MarChem snapshot archive does not exist: {archive_path}"
            )
        if archive_path.stat().st_size > int(download_entry["max_bytes"]):
            raise SourceAdapterError(
                "MarChem snapshot archive exceeds the registered download bound"
            )
        try:
            downloader.safe_extract_zip(
                archive_path,
                extract_dir,
                max_members=int(download_entry["expected_member_count"]),
                max_extracted_bytes=int(
                    download_entry.get("max_uncompressed_bytes", 2_000_000)
                ),
                required_members=[],
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
            raise SourceAdapterError(
                "MarChem adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use a checked-in source-native fixture directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        archive_path = root / download_entry["archive_filename"]
        manifest_path = root / "snapshot.download.json"
        args = _download_args(
            url=download_entry["url"],
            output=archive_path,
            manifest=manifest_path,
            license_id=candidate.license_id,
            # The publisher regenerates the wrapper. Scientific integrity is
            # established below from the independently pinned data and method
            # member hashes, while the observed wrapper hash stays in the
            # download manifest for exact replay.
            expected_sha256=None,
            max_bytes=int(download_entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(
                f"MarChem snapshot download failed: {exc}"
            ) from exc
        content_type = result.get("content_type")
        if content_type and content_type not in set(
            download_entry["accepted_content_types"]
        ):
            raise SourceAdapterError(
                f"MarChem returned unexpected content type: {content_type}"
            )
        observed_archive_sha = str(result.get("sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", observed_archive_sha):
            raise SourceAdapterError(
                "MarChem download manifest lacks the observed wrapper SHA-256"
            )
        extract_dir = root / f"members-{observed_archive_sha[:16]}"
        if not extract_dir.exists():
            try:
                downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]),
                    max_extracted_bytes=int(
                        download_entry.get("max_uncompressed_bytes", 2_000_000)
                    ),
                    required_members=[],
                    required_fields=(),
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"MarChem safe extraction failed: {exc}"
                ) from exc
        return self._verified_members(
            extract_dir,
            result["status"],
            result.get("accessed_at") or result.get("cache_verified_at"),
        )

    def _metadata_index(
        self, metadata_path: Path
    ) -> dict[tuple[str, str], dict[str, str]]:
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
                    "_accreditation_status": self._accreditation_status(
                        method.get("Comment", "")
                    ),
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
    """Pinned GEMStat v3 seven-element observations plus station/method metadata."""

    source_id = "gemstat-open-archive"
    PARAMETER_MAP = {
        "As-Dis": ("As", "dissolved"),
        "As-Sus": ("As", "suspended"),
        "As-Tot": ("As", "total"),
        "Cr-Dis": ("Cr", "dissolved"),
        "Cr-Ext": ("Cr", "extractable"),
        "Cr-Tot": ("Cr", "total"),
        "Cu-Dis": ("Cu", "dissolved"),
        "Cu-Ext": ("Cu", "extractable"),
        "Cu-Sus": ("Cu", "suspended"),
        "Cu-Tot": ("Cu", "total"),
        "Hg-Dis": ("Hg", "dissolved"),
        "Hg-Ext": ("Hg", "extractable"),
        "Hg-Sus": ("Hg", "suspended"),
        "Hg-Tot": ("Hg", "total"),
        "Ni-Dis": ("Ni", "dissolved"),
        "Ni-Ext": ("Ni", "extractable"),
        "Ni-Sus": ("Ni", "suspended"),
        "Ni-Tot": ("Ni", "total"),
        "Pb-Dis": ("Pb", "dissolved"),
        "Pb-Ext": ("Pb", "extractable"),
        "Pb-Sus": ("Pb", "suspended"),
        "Pb-Tot": ("Pb", "total"),
        "Zn-Dis": ("Zn", "dissolved"),
        "Zn-Ext": ("Zn", "extractable"),
        "Zn-Sus": ("Zn", "suspended"),
        "Zn-Tot": ("Zn", "total"),
    }
    OBSERVATION_FILE_IDS = (
        "arsenic-observations",
        "chromium-observations",
        "copper-observations",
        "mercury-observations",
        "nickel-observations",
        "lead-observations",
        "zinc-observations",
    )

    @staticmethod
    def _csv_rows(
        path: Path, required_fields: Sequence[str]
    ) -> Iterable[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="cp1252", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"GEMStat member is unreadable: {path.name}"
            ) from exc
        with handle:
            reader = csv.DictReader(handle)
            fieldnames = [
                str(value or "").strip() for value in (reader.fieldnames or [])
            ]
            missing = sorted(set(required_fields) - set(fieldnames))
            if missing:
                raise SourceAdapterError(
                    f"GEMStat member {path.name} lacks fields: {', '.join(missing)}"
                )
            for row in reader:
                yield (
                    reader.line_num,
                    {
                        str(key): str(value or "").strip()
                        for key, value in row.items()
                        if key is not None
                    },
                )

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                "GEMStat adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in GEMStat demo directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        entries = candidate.registry_entry["download"]["selected_members"]
        if any(
            not (root / "members" / entry["filename"]).is_file() for entry in entries
        ):
            if mode == "online":
                try:
                    import acquire_gemstat_multielement

                    acquire_gemstat_multielement.run(cache_dir, "online", 180.0)
                except (OSError, RuntimeError, ValueError) as exc:
                    raise SourceAdapterError(
                        f"GEMStat online pre-acquisition failed closed: {exc}"
                    ) from exc
            if any(
                not (root / "members" / entry["filename"]).is_file()
                for entry in entries
            ):
                raise SourceAdapterError(
                    f"Populate the verified cache; the pinned GEMStat v3 seven-element subset is incomplete at {root}"
                )
        files: list[DownloadedFile] = []
        for entry in entries:
            path = root / "members" / entry["filename"]
            if (
                path.stat().st_size != entry["bytes"]
                or downloader.sha256_file(path) != entry["expected_sha256"]
            ):
                raise SourceAdapterError(
                    f"GEMStat selected member changed: {entry['filename']}"
                )
            files.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=entry["file_id"],
                    path=path,
                    source_url=candidate.registry_entry["download"]["archive_url"],
                    bytes=entry["bytes"],
                    cache_status="cache_verified",
                    retrieved_at=candidate.registry_entry["download"]["observed_at"],
                )
            )
        return files

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        expected_ids = {
            *self.OBSERVATION_FILE_IDS,
            "methods",
            "parameters",
            "stations",
            "readme",
        }
        if set(by_id) != expected_ids:
            raise SourceAdapterError(
                f"GEMStat adapter requires eleven selected members; received={sorted(by_id)}"
            )

        station_rows = list(
            self._csv_rows(
                by_id["stations"].path,
                self.candidate.registry_entry["station_required_fields"],
            )
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
                stations[station_id] = {
                    **values,
                    "_metadata_source_locators": [locator],
                }
                continue
            comparable = {
                key: value
                for key, value in prior.items()
                if key != "_metadata_source_locators"
            }
            if comparable != values:
                raise SourceAdapterError(
                    f"GEMStat station ID has conflicting metadata: {station_id}"
                )
            prior["_metadata_source_locators"].append(locator)
            duplicate_station_rows += 1
        if (
            len(stations) != expected_counts["station_metadata_unique_ids"]
            or duplicate_station_rows
            != expected_counts["station_metadata_exact_duplicate_rows"]
        ):
            raise SourceAdapterError("GEMStat station duplicate reconciliation changed")

        methods: dict[tuple[str, str, str], dict[str, str]] = {}
        method_rows = list(
            self._csv_rows(
                by_id["methods"].path,
                self.candidate.registry_entry["method_required_fields"],
            )
        )
        for line_number, values in method_rows:
            key = (
                values["Parameter Code"],
                values["Analysis Method Code"],
                values["Unit"],
            )
            if key in methods:
                raise SourceAdapterError(
                    f"GEMStat method key is duplicated at row {line_number}: {key}"
                )
            methods[key] = {
                **values,
                "_metadata_source_locator": f"{by_id['methods'].path.name}#row={line_number}",
            }
        if (
            len(methods)
            != self.candidate.registry_entry["expected_counts"]["method_metadata_rows"]
        ):
            raise SourceAdapterError("GEMStat method metadata row count changed")

        parameter_rows = list(
            self._csv_rows(
                by_id["parameters"].path, ("Parameter Code", "Parameter Long Name")
            )
        )
        if (
            len(parameter_rows)
            != self.candidate.registry_entry["expected_counts"][
                "parameter_metadata_rows"
            ]
        ):
            raise SourceAdapterError("GEMStat parameter metadata row count changed")
        parameter_codes = {values["Parameter Code"] for _, values in parameter_rows}
        if set(self.PARAMETER_MAP) - parameter_codes:
            raise SourceAdapterError(
                "GEMStat parameter metadata no longer defines every registered element fraction"
            )

        emitted = 0
        emitted_by_element: Counter[str] = Counter()
        excluded: Counter[str] = Counter()
        expected_counts = self.candidate.registry_entry["expected_counts"]
        for file_id in self.OBSERVATION_FILE_IDS:
            downloaded = by_id[file_id]
            source_rows = 0
            for line_number, values in self._csv_rows(
                downloaded.path,
                self.candidate.registry_entry["required_fields"],
            ):
                source_rows += 1
                parameter_code = values.get("Parameter Code", "")
                mapping = self.PARAMETER_MAP.get(parameter_code)
                if mapping is None:
                    if parameter_code in expected_counts["excluded_parameter_counts"]:
                        excluded[parameter_code] += 1
                        continue
                    raise SourceAdapterError(
                        f"unexpected parameter in {downloaded.path.name}: {parameter_code}"
                    )
                element, fraction = mapping
                station_id = values.get("GEMS Station Number", "")
                station = stations.get(station_id)
                if station is None:
                    raise SourceAdapterError(
                        f"GEMStat observation has no station metadata: {station_id}"
                    )
                method_key = (
                    parameter_code,
                    values.get("Analysis Method Code", ""),
                    values.get("Unit", ""),
                )
                method = methods.get(method_key)
                if method is None:
                    raise SourceAdapterError(
                        f"GEMStat observation has no method metadata: {method_key}"
                    )
                source_locator = f"{downloaded.path.name}#row={line_number}"
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
                emitted_by_element[element] += 1
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, native_id, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_station_metadata": station,
                        "_method_metadata": method,
                        "_element": element,
                        "_water_fraction": fraction,
                        "_source_file": downloaded.path.name,
                        "_dataset_version": self.candidate.version,
                    },
                )
            if source_rows != expected_counts["source_file_rows"][downloaded.path.name]:
                raise SourceAdapterError(
                    f"GEMStat source row count changed for {downloaded.path.name}: {source_rows}"
                )
        if (
            dict(sorted(emitted_by_element.items()))
            != expected_counts["target_value_counts"]
        ):
            raise SourceAdapterError(
                f"GEMStat element counts changed: {dict(sorted(emitted_by_element.items()))}"
            )
        if (
            dict(sorted(excluded.items()))
            != expected_counts["excluded_parameter_counts"]
        ):
            raise SourceAdapterError(
                f"GEMStat excluded parameter counts changed: {dict(sorted(excluded.items()))}"
            )
        if emitted != expected_counts["target_observations"]:
            raise SourceAdapterError(
                f"GEMStat seven-element target row count changed: {emitted}"
            )


class GeotracesIdp2025Adapter(RegistryAdapter):
    """Content-addressed webODV export of the IDP2025 discrete seawater collection."""

    source_id = "geotraces-idp2025"

    @staticmethod
    def _canonical_payload_identity(
        archive_path: Path, download_entry: Mapping[str, Any]
    ) -> tuple[str, str]:
        """Bind scientific payload while excluding declared webODV session noise."""

        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                names = [item.filename for item in members]
                if (
                    len(members) != int(download_entry["expected_member_count"])
                    or len(names) != len(set(names))
                    or sum(item.file_size for item in members)
                    != int(download_entry["expected_uncompressed_bytes"])
                ):
                    raise SourceAdapterError(
                        "GEOTRACES archive structure differs from the registered payload"
                    )
                if any(
                    item.is_dir()
                    or PurePosixPath(item.filename).is_absolute()
                    or ".." in PurePosixPath(item.filename).parts
                    or "\\" in item.filename
                    for item in members
                ):
                    raise SourceAdapterError(
                        "GEOTRACES archive contains an unsafe member path"
                    )
                data_members = [
                    item
                    for item in members
                    if "/" not in item.filename
                    and re.fullmatch(
                        r"IDP2025_seawater_GEOTRACES_IDP2025_Seawater_[A-Za-z0-9]{8}\.txt",
                        item.filename,
                    )
                ]
                if len(data_members) != 1:
                    raise SourceAdapterError(
                        "GEOTRACES archive lacks one session-scoped ODV data member"
                    )
                data_member = data_members[0]
                stem = data_member.filename.removesuffix(".txt")
                expected_prefix = f"{stem}.misc/infos/"
                if any(
                    item is not data_member
                    and (
                        not item.filename.startswith(expected_prefix)
                        or not item.filename.endswith(".html")
                    )
                    for item in members
                ):
                    raise SourceAdapterError(
                        "GEOTRACES method-member layout differs from the registered export"
                    )
                identities: dict[str, str] = {}
                for item in members:
                    payload = archive.read(item)
                    payload = payload.replace(stem.encode("utf-8"), b"NORMALIZED_STEM")
                    # CreateTime and View change per export session; Creator and
                    # Software embed the webODV worker host and build, which
                    # change per service deployment. All four are session or
                    # deployment noise, not scientific payload.
                    for volatile_tag in (
                        b"CreateTime",
                        b"View",
                        b"Creator",
                        b"Software",
                    ):
                        payload = re.sub(
                            rb"//<" + volatile_tag + rb">[^\r\n]*",
                            b"//<"
                            + volatile_tag
                            + b">NORMALIZED</"
                            + volatile_tag
                            + b">",
                            payload,
                        )
                    key = (
                        "DATA.txt"
                        if item is data_member
                        else item.filename.split(".misc/", 1)[1]
                    )
                    identities[key] = hashlib.sha256(payload).hexdigest()
        except (OSError, zipfile.BadZipFile, KeyError, ValueError) as exc:
            if isinstance(exc, SourceAdapterError):
                raise
            raise SourceAdapterError(
                "GEOTRACES archive cannot be canonicalized safely"
            ) from exc
        aggregate = hashlib.sha256(
            json.dumps(identities, sort_keys=True).encode("utf-8")
        ).hexdigest()
        if aggregate != download_entry["canonical_payload_sha256"]:
            raise SourceAdapterError(
                "GEOTRACES canonical scientific payload differs from the registry"
            )
        return data_member.filename, aggregate

    def _method_index(
        self, data_path: Path
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        info_root = data_path.parent / f"{data_path.stem}.misc" / "infos"
        info_paths = sorted(info_root.glob("*.html"))
        expected = self.candidate.registry_entry["method_metadata"]
        if len(info_paths) != expected["html_member_count"]:
            raise SourceAdapterError(
                f"GEOTRACES contributor/method member count changed: {len(info_paths)}"
            )
        total_bytes = 0
        index: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for path in info_paths:
            try:
                payload = path.read_bytes()
                text = payload.decode("utf-8")
            except (OSError, UnicodeError) as exc:
                raise SourceAdapterError(
                    f"GEOTRACES method metadata is unreadable: {path.name}"
                ) from exc
            relative = path.relative_to(data_path.parent).as_posix()
            total_bytes += len(payload)
            title_match = re.search(r"<h2>(.*?)</h2>", text, flags=re.DOTALL)
            if title_match is None:
                raise SourceAdapterError(
                    f"GEOTRACES method metadata lacks h2 identity: {path.name}"
                )
            title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
            identity = re.fullmatch(r"(Cu|Ni|Zn)_D_CONC @ (.*?) \((.*?)\)", title)
            if identity is None:
                raise SourceAdapterError(f"GEOTRACES method identity changed: {title}")
            element, cruise, operator_cruise = identity.groups()
            originators = [
                {
                    "name": html.unescape(re.sub(r"<[^>]+>", "", name)).strip(),
                    "orcid_url": url,
                }
                for url, name in re.findall(
                    r'<a href="(https://orcid\.org/[^"]+)">(.*?)</a>',
                    text,
                    flags=re.DOTALL,
                )
            ]
            method_urls = re.findall(
                r'href="(https://www\.bodc\.ac\.uk/data/documents/nodb/[^"]+)', text
            )
            publication_urls = re.findall(
                r'href="(https://geotraces-portal\.sedoo\.fr/[^"]+)', text
            )
            if not method_urls or len(publication_urls) != 1 or not originators:
                raise SourceAdapterError(f"GEOTRACES method links changed: {path.name}")
            device_match = re.search(r"_CONC_([A-Z_]+)_\d+\.html$", path.name)
            if device_match is None:
                raise SourceAdapterError(
                    f"GEOTRACES method device identity changed: {path.name}"
                )
            item = {
                "element": element,
                "cruise": cruise,
                "operator_cruise": operator_cruise,
                "sampling_device_class": device_match.group(1).lower(),
                "originators": originators,
                "method_urls": sorted(set(method_urls)),
                "publication_search_url": publication_urls[0],
                "source_locator": f"{data_path.parent.name}/{relative}",
            }
            index.setdefault((cruise, element), []).append(item)
        if total_bytes != expected["html_uncompressed_bytes"]:
            raise SourceAdapterError(
                f"GEOTRACES method metadata byte count changed: {total_bytes}"
            )
        if len(index) != expected["cruise_analyte_groups"]:
            raise SourceAdapterError(
                f"GEOTRACES cruise-analyte method groups changed: {len(index)}"
            )
        return index

    def files_from_archive(
        self,
        archive_path: Path,
        extract_dir: Path,
        *,
        cache_status: str = "verified_local_snapshot",
    ) -> list[DownloadedFile]:
        """Verify and safely extract the registered webODV export."""

        download_entry = self.candidate.registry_entry["download"]
        member_entry = download_entry["members"][0]
        if not archive_path.is_file():
            raise SourceAdapterError(
                f"GEOTRACES export archive does not exist: {archive_path}"
            )
        if not 0 < archive_path.stat().st_size <= int(download_entry["max_bytes"]):
            raise SourceAdapterError(
                "GEOTRACES export archive exceeds the registered byte ceiling"
            )
        member_filename, _ = self._canonical_payload_identity(
            archive_path, download_entry
        )
        if not extract_dir.exists():
            try:
                downloader.safe_extract_zip(
                    archive_path,
                    extract_dir,
                    max_members=int(download_entry["expected_member_count"]),
                    max_extracted_bytes=int(
                        download_entry["expected_uncompressed_bytes"]
                    ),
                    required_members=[member_filename],
                    required_fields=(),
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"GEOTRACES safe extraction failed: {exc}"
                ) from exc
        member_path = extract_dir / member_filename
        if member_path.stat().st_size != member_entry["bytes"]:
            raise SourceAdapterError(
                "GEOTRACES export member size does not match the registry"
            )
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=member_entry["file_id"],
                path=member_path,
                source_url=download_entry["exporter_landing_page"],
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
            raise SourceAdapterError(
                "GEOTRACES adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use a checked-in synthetic ODV fixture directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        archive_path = root / candidate.registry_entry["download"]["archive_filename"]
        expected_hash = candidate.registry_entry["download"]["canonical_payload_sha256"]
        registered_archive_hash = candidate.registry_entry["download"]["files"][0][
            "expected_sha256"
        ]

        def extracted_root(path: Path) -> Path:
            return root / (
                f"members-{expected_hash[:12]}-{downloader.sha256_file(path)[:12]}"
            )

        if archive_path.is_file():
            try:
                archive_status = (
                    "cache_verified"
                    if downloader.sha256_file(archive_path) == registered_archive_hash
                    else "payload_verified_archive_container_variant"
                )
                return self.files_from_archive(
                    archive_path,
                    extracted_root(archive_path),
                    cache_status=archive_status,
                )
            except SourceAdapterError:
                if mode != "online":
                    raise
        if mode == "online":
            try:
                import acquire_geotraces_idp2025

                with tempfile.TemporaryDirectory(
                    prefix="geotraces-online-candidate-"
                ) as temporary:
                    temporary_root = Path(temporary)
                    candidate_archive = temporary_root / archive_path.name
                    client = acquire_geotraces_idp2025.opener()
                    output_url = acquire_geotraces_idp2025.fetch_export_url(
                        client, 180.0
                    )
                    acquire_geotraces_idp2025.download_archive(
                        client,
                        output_url,
                        candidate_archive,
                        timeout=180.0,
                        max_bytes=int(
                            candidate.registry_entry["download"]["max_bytes"]
                        ),
                        overwrite=False,
                    )
                    # The official exporter is session-specific. Promote only a
                    # container whose normalized scientific payload exactly
                    # matches the registered canonical payload.
                    self.files_from_archive(
                        candidate_archive,
                        temporary_root / "members",
                        cache_status="online_candidate_verified",
                    )
                    root.mkdir(parents=True, exist_ok=True)
                    temporary_archive = root / f".{archive_path.name}.verified"
                    shutil.copyfile(candidate_archive, temporary_archive)
                    os.replace(temporary_archive, archive_path)
            except (OSError, RuntimeError, ValueError) as exc:
                raise SourceAdapterError(
                    f"GEOTRACES online exporter attempt did not reproduce the registered snapshot: {exc}"
                ) from exc
        if not archive_path.is_file():
            raise SourceAdapterError(
                "Populate the verified cache; the official webODV exporter creates "
                f"a session-specific URL and the pinned archive is absent at {archive_path}"
            )
        final_status = (
            "cache_verified"
            if downloader.sha256_file(archive_path) == registered_archive_hash
            else "payload_verified_archive_container_variant"
        )
        return self.files_from_archive(
            archive_path,
            extracted_root(archive_path),
            cache_status=final_status,
        )

    def _rows(self, path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
        target_fields: Mapping[str, str] = self.candidate.registry_entry[
            "target_analytes"
        ]
        method_index = self._method_index(path)
        required = set(self.candidate.registry_entry["required_fields"])
        expected_rows = int(
            self.candidate.registry_entry["expected_counts"]["physical_rows"]
        )
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"GEOTRACES export is unreadable: {path.name}"
            ) from exc
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
                    target_indices = {
                        analyte: header.index(field)
                        for analyte, field in target_fields.items()
                    }
                    continue
                padded = [str(value).strip() for value in row] + [""] * max(
                    0, len(header) - len(row)
                )
                fields: dict[str, Any] = {
                    name: padded[index] for name, index in indices.items()
                }
                observations: dict[str, dict[str, str]] = {}
                for analyte, value_index in target_indices.items():
                    field_name = target_fields[analyte]
                    candidates = method_index.get((fields["Cruise"], analyte), [])
                    raw_target_value = padded[value_index]
                    if raw_target_value and not candidates:
                        raise SourceAdapterError(
                            f"GEOTRACES observation has no cruise-analyte method metadata: {fields['Cruise']} {analyte}"
                        )
                    linked_method_urls = sorted(
                        {
                            url
                            for candidate in candidates
                            for url in candidate.get("method_urls", [])
                        }
                    )
                    observation: dict[str, Any] = {
                        "field": field_name,
                        "value": raw_target_value,
                        "standard_deviation": padded[value_index + 1],
                        "quality_flag": padded[value_index + 2],
                        "quality_schema": "SEADATANET",
                        "unit": "nmol/kg",
                        "measurement_basis": "dissolved_seawater_molar_per_mass",
                        "digestion_or_extraction": "dissolved_fraction; contributor-specific protocol",
                        "method_metadata_candidates": candidates,
                        "method_metadata_status": (
                            "single_linked_record"
                            if len(linked_method_urls) == 1
                            else "multiple_linked_records_unresolved"
                        ),
                        "linked_method_urls": linked_method_urls,
                    }
                    if len(linked_method_urls) == 1:
                        method_id = linked_method_urls[0].rstrip("/").rsplit("/", 1)[-1]
                        observation["analytical_method"] = (
                            f"BODC originator and methods record {method_id}"
                        )
                        observation["variable_metadata_locator"] = ";".join(
                            candidate["source_locator"] for candidate in candidates
                        )
                    observations[analyte] = observation
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
            raise SourceAdapterError(
                "GEOTRACES adapter requires the registered seawater export member"
            )
        downloaded = files[0]
        for line_number, values in self._rows(downloaded.path):
            source_locator = f"{downloaded.path.name}#row={line_number}"
            native_id = "|".join(
                str(values.get(field) or "")
                for field in (
                    "Cruise",
                    "Station",
                    "yyyy-mm-ddThh:mm:ss.sss",
                    "DEPTH [m]",
                )
            )
            source_record_id = stable_source_record_id(
                self.source_id, native_id, source_locator
            )
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
            raise SourceAdapterError(
                "GSJ adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in GSJ demo directly for fixture tests"
            )
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
                raise SourceAdapterError(
                    f"GSJ download failed for {file_entry['file_id']}: {exc}"
                ) from exc
            content_type = result.get("content_type")
            if content_type and content_type not in set(
                download_entry["accepted_content_types"]
            ):
                raise SourceAdapterError(
                    f"GSJ returned unexpected content type: {content_type}"
                )
            if output.stat().st_size != file_entry["bytes"]:
                raise SourceAdapterError(f"GSJ file size changed: {output.name}")
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=output,
                    source_url=file_entry["url"],
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at")
                    or result.get("cache_verified_at"),
                )
            )
        return results

    @staticmethod
    def _csv_rows(
        path: Path, required_fields: Sequence[str]
    ) -> list[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="cp932", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"GSJ file is unreadable: {path.name}") from exc
        with handle:
            reader = csv.DictReader(handle)
            fields = [str(value or "").strip() for value in (reader.fieldnames or [])]
            missing = sorted(set(required_fields) - set(fields))
            if missing:
                raise SourceAdapterError(
                    f"GSJ file {path.name} lacks fields: {', '.join(missing)}"
                )
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
            raise SourceAdapterError(
                f"GSJ sample ID is not an integer: {raw_id!r}"
            ) from exc
        occurrence = occurrences.get(normalized_id, 0)
        occurrences[normalized_id] = occurrence + 1
        return normalized_id, occurrence

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if set(by_id) != {"samples", "concentrations"}:
            raise SourceAdapterError(
                "GSJ adapter requires samplejoho.csv and noudo.csv"
            )
        samples = self._csv_rows(
            by_id["samples"].path,
            self.candidate.registry_entry["sample_required_fields"],
        )
        concentrations = self._csv_rows(
            by_id["concentrations"].path,
            self.candidate.registry_entry["concentration_required_fields"],
        )
        expected = self.candidate.registry_entry["expected_counts"]
        if (
            len(samples) != expected["sample_rows"]
            or len(concentrations) != expected["concentration_rows"]
        ):
            raise SourceAdapterError("GSJ valid source-row counts changed")

        concentration_occurrences: dict[str, int] = {}
        concentration_by_key: dict[tuple[str, int], tuple[int, dict[str, str]]] = {}
        target_counts: Counter[str] = Counter()
        for line_number, values in concentrations:
            key = self._join_key(values["番号2"], concentration_occurrences)
            if key in concentration_by_key:
                raise SourceAdapterError(
                    f"GSJ concentration occurrence key is duplicated: {key}"
                )
            for analyte, field_name in self.candidate.registry_entry[
                "target_analytes"
            ].items():
                raw_value = str(values.get(field_name) or "").strip()
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"GSJ {analyte} is not numeric at row {line_number}"
                    ) from exc
                target_counts[analyte] += 1
            concentration_by_key[key] = (line_number, values)

        sample_occurrences: dict[str, int] = {}
        sample_keys: set[tuple[str, int]] = set()
        for sample_line, sample in samples:
            key = self._join_key(sample["試料番号"], sample_occurrences)
            sample_keys.add(key)
            match = concentration_by_key.get(key)
            if match is None:
                raise SourceAdapterError(
                    f"GSJ sample has no ordinal concentration match: {key}"
                )
            concentration_line, concentration = match
            sample_locator = f"{by_id['samples'].path.name}#row={sample_line}"
            concentration_locator = (
                f"{by_id['concentrations'].path.name}#row={concentration_line}"
            )
            source_locator = f"{sample_locator};{concentration_locator}"
            native_id = f"{key[0]}#{key[1] + 1}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, native_id, source_locator
                ),
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
            raise SourceAdapterError(
                "GSJ sample and concentration ordinal key sets differ"
            )
        if (
            sample_occurrences.get("78013") != 2
            or concentration_occurrences.get("78013") != 2
        ):
            raise SourceAdapterError(
                "GSJ duplicate sample 78013 reconciliation changed"
            )
        if dict(sorted(target_counts.items())) != expected["target_value_counts"]:
            raise SourceAdapterError(
                "GSJ registered target-value population changed: "
                f"{dict(sorted(target_counts.items()))!r}"
            )


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
            raise SourceAdapterError(
                "PANGAEA adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in PANGAEA demo directly for fixture tests"
            )
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
        if content_type and content_type not in set(
            download_entry["accepted_content_types"]
        ):
            raise SourceAdapterError(
                f"PANGAEA returned unexpected content type: {content_type}"
            )
        if output.stat().st_size != file_entry["bytes"]:
            raise SourceAdapterError("PANGAEA file size changed")
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=file_entry["file_id"],
                path=output,
                source_url=file_entry["url"],
                bytes=result["bytes"],
                cache_status=result["status"],
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
            )
        ]

    def _rows(self, path: Path) -> Iterable[tuple[int, dict[str, str]]]:
        required = set(self.candidate.registry_entry["required_fields"])
        target_fields = set(self.candidate.registry_entry["target_analytes"].values())
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA file is unreadable: {path.name}"
            ) from exc
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
                            raise SourceAdapterError(
                                "PANGAEA file ends before its tabular header"
                            ) from exc
                        missing = sorted((required | target_fields) - set(header))
                        if missing:
                            raise SourceAdapterError(
                                f"PANGAEA file lacks required fields: {', '.join(missing)}"
                            )
                        element_fields = [
                            field for field in header if field.endswith(" [mg/kg]")
                        ]
                        if (
                            len(element_fields)
                            != self.candidate.registry_entry["expected_counts"][
                                "element_fields"
                            ]
                        ):
                            raise SourceAdapterError(
                                "PANGAEA elemental field count changed"
                            )
                    continue
                if not any(value.strip() for value in row):
                    continue
                padded = [value.strip() for value in row] + [""] * max(
                    0, len(header) - len(row)
                )
                values = dict(zip(header, padded, strict=False))
                if not values.get("Sample ID"):
                    raise SourceAdapterError(
                        f"PANGAEA sample ID is missing at row {reader.line_num}"
                    )
                emitted += 1
                nonempty_measurements += sum(
                    bool(values.get(field, "")) for field in element_fields
                )
                yield reader.line_num, values
            if header is None:
                raise SourceAdapterError(
                    "PANGAEA file has no DATA DESCRIPTION terminator or table header"
                )
            expected = self.candidate.registry_entry["expected_counts"]
            if emitted != expected["physical_rows"]:
                raise SourceAdapterError(
                    f"PANGAEA physical-row count changed: {emitted} != {expected['physical_rows']}"
                )
            if nonempty_measurements != expected["nonempty_element_measurements"]:
                raise SourceAdapterError(
                    "PANGAEA nonempty elemental-measurement count changed"
                )

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "table-s5":
            raise SourceAdapterError(
                "PANGAEA adapter requires the registered Table S5 file"
            )
        downloaded = files[0]
        for line_number, values in self._rows(downloaded.path):
            source_locator = f"{downloaded.path.name}#row={line_number}"
            native_id = values.get("Sample ID") or values.get("Event")
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, native_id, source_locator
                ),
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
    """Reject redirects before a pinned acquisition request reaches another URL."""

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
            raise SourceAdapterError(
                "FOREGS legacy transport must be the registered public GTK HTTP URL"
            )
        try:
            addresses = {
                item[4][0]
                for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)
            }
        except socket.gaierror as exc:
            raise SourceAdapterError(
                "FOREGS publisher hostname could not be resolved"
            ) from exc
        if not addresses or any(
            not ipaddress.ip_address(address).is_global for address in addresses
        ):
            raise SourceAdapterError(
                "FOREGS publisher hostname did not resolve exclusively to public addresses"
            )

    @classmethod
    def _download_once_pinned_http(
        cls,
        url: str,
        output: Path,
        timeout: float,
        max_bytes: int,
        _legacy_expected_sha256: str | None,
    ) -> dict[str, Any]:
        cls._validate_pinned_http_url(url)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": downloader.USER_AGENT,
                    "Accept": "application/zip",
                },
            )
            opener = urllib.request.build_opener(_RejectRedirects())
            with opener.open(request, timeout=timeout) as response:
                if response.geturl() != url:
                    raise SourceAdapterError(
                        "FOREGS legacy transport redirected away from the pinned URL"
                    )
                content_type = response.headers.get_content_type().casefold()
                downloader.validate_response_metadata(
                    content_type,
                    response.headers.get("Content-Length"),
                    max_bytes,
                )
                with tempfile.NamedTemporaryFile(
                    "wb",
                    prefix=f".{output.name}.",
                    suffix=".part",
                    dir=output.parent,
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    total = downloader.copy_response_bounded(
                        response, handle, max_bytes
                    )
                if total == 0:
                    raise SourceAdapterError("FOREGS archive is empty")
                os.replace(temporary, output)
                temporary = None
                return {
                    "status": "downloaded",
                    "source_url": url,
                    "resolved_url": url,
                    "content_type": content_type,
                    "bytes": total,
                    "accessed_at": downloader.utc_now(),
                    "http_status": getattr(response, "status", 200),
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "transport_security": "publisher_http_exact_url_no_redirect",
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
            raise SourceAdapterError(
                "FOREGS adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in FOREGS demo directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        archive_entry = download_entry["files"][0]
        archive_root = archive_entry["filename"].removesuffix(".zip").replace("-", " ")
        archive_path = root / archive_entry["filename"]
        manifest_path = root / "dataset.download.json"
        if mode == "cached":
            if not archive_path.is_file():
                raise SourceAdapterError(
                    f"FOREGS verified cache is missing: {archive_path}"
                )
            if archive_path.stat().st_size != archive_entry["bytes"]:
                raise SourceAdapterError("FOREGS cached archive byte count changed")
            original_accessed_at: str | None = None
            if manifest_path.is_file():
                try:
                    cached_manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    raise SourceAdapterError(
                        "FOREGS cached acquisition manifest is unreadable"
                    ) from exc
                if cached_manifest.get("source_url") == archive_entry["url"]:
                    original_accessed_at = cached_manifest.get("accessed_at")
            result: dict[str, Any] = {
                "status": "cache_hit",
                "source_url": archive_entry["url"],
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
                    None,
                    2,
                    downloader=self._download_once_pinned_http,
                )
            except (downloader.DownloadError, SourceAdapterError, OSError) as exc:
                raise SourceAdapterError(
                    f"FOREGS archive download failed: {exc}"
                ) from exc
            downloader.atomic_json(
                manifest_path,
                {
                    **result,
                    "dataset_version": candidate.version,
                    "license": candidate.license_id,
                    "transport_exception": (
                        "GTK currently serves the public archive over HTTP. The adapter requires the exact "
                        "registered host and path, rejects redirects, and validates byte count, archive members, "
                        "schema and row-count statistics."
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
                        f"{archive_root}/{entry['filename']}"
                        for entry in download_entry["members"]
                    ],
                    required_fields=[],
                )
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"FOREGS archive extraction failed: {exc}"
                ) from exc
            if len(extracted) != int(download_entry["expected_member_count"]):
                raise SourceAdapterError("FOREGS archive member count changed")

        verified: list[DownloadedFile] = []
        for member in download_entry["members"]:
            path = extract_dir / archive_root / member["filename"]
            if not path.is_file() or path.stat().st_size != member["bytes"]:
                raise SourceAdapterError(
                    f"FOREGS member byte count changed: {member['filename']}"
                )
            verified.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=member["file_id"],
                    path=path,
                    source_url=f"{archive_entry['url']}#member={urllib.parse.quote(member['filename'])}",
                    bytes=member["bytes"],
                    cache_status=str(result["status"]),
                    retrieved_at=result.get("accessed_at")
                    or result.get("cache_verified_at"),
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
            headers.append(
                base if occurrences[base] == 1 else f"{base}__{occurrences[base]}"
            )
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
            raise SourceAdapterError(
                f"FOREGS member is unreadable: {path.name}"
            ) from exc
        with handle:
            reader = csv.reader(handle)
            try:
                headers = self._unique_headers(next(reader))
                units_row = [value.strip() for value in next(reader)]
                detection_row = [value.strip() for value in next(reader)]
            except StopIteration as exc:
                raise SourceAdapterError(
                    f"FOREGS member lacks its three metadata rows: {path.name}"
                ) from exc
            folded = {field.casefold(): field for field in headers}
            required = {str(field).casefold() for field in member["required_fields"]}
            if not required.issubset(folded):
                raise SourceAdapterError(
                    f"FOREGS member lacks required fields: {path.name}"
                )
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
            entry["file_id"]: entry
            for entry in self.candidate.registry_entry["download"]["members"]
        }
        if {item.file_id for item in files} != set(registered):
            raise SourceAdapterError(
                "FOREGS adapter requires the exact registered CSV member set"
            )
        total_rows = 0
        for downloaded in files:
            member = registered[downloaded.file_id]
            for line_number, values, units, detection_limits in self._rows(
                downloaded.path, member
            ):
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
                            "digestion_or_extraction": member[
                                "digestion_or_extraction"
                            ],
                            "possible_upstream_dl_over_2_substitution": self._half_detection_limit(
                                raw_value, detection_limit
                            ),
                        }
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, native_id, source_locator
                    ),
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
                        "_sample_depth_min_m": self.candidate.registry_entry[
                            "sample_depth_min_m"
                        ],
                        "_sample_depth_max_m": self.candidate.registry_entry[
                            "sample_depth_max_m"
                        ],
                        "_grain_fraction": self.candidate.registry_entry[
                            "grain_fraction"
                        ],
                        "_dataset_version": self.candidate.version,
                        "_censoring_boundary": (
                            "The published numeric CSV has no row-level less-than qualifier. Values exactly at half "
                            "the table DL are flagged as possible upstream DL/2 substitutions, not asserted as detections."
                        ),
                    },
                )
        expected = int(
            self.candidate.registry_entry["expected_counts"]["physical_rows"]
        )
        if total_rows != expected:
            raise SourceAdapterError(
                f"FOREGS total parsed row count changed: {total_rows} != {expected}"
            )


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


class AfsisPhaseIWetChemistryAdapter(RegistryAdapter):
    """Pinned AfSIS Phase I original CSV plus method and detection-limit workbooks."""

    source_id = "afsis-phase-i-wet-chemistry"
    _xlsx_namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    _country_names = {"SAfrica": "South Africa", "Zimbambwe": "Zimbabwe"}

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                "AfSIS adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in AfSIS demo directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        accepted = set(download_entry["accepted_content_types"])
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
                required_fields=(
                    candidate.registry_entry["required_fields"]
                    if file_entry["file_id"] == "measurements"
                    else ()
                ),
            )
            try:
                result = downloader.run(args)
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"AfSIS download failed for {file_entry['file_id']}: {exc}"
                ) from exc
            content_type = str(result.get("content_type") or "")
            if content_type and content_type not in accepted:
                raise SourceAdapterError(
                    f"AfSIS file {file_entry['file_id']} returned unexpected content type: {content_type}"
                )
            if output.stat().st_size != int(file_entry["bytes"]):
                raise SourceAdapterError(
                    f"AfSIS file size changed: {file_entry['filename']}"
                )
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=output,
                    source_url=file_entry["url"],
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at")
                    or result.get("cache_verified_at"),
                )
            )
        return results

    @staticmethod
    def _column_index(reference: str) -> int:
        match = re.match(r"^([A-Z]+)", reference)
        if not match:
            raise SourceAdapterError(
                f"AfSIS workbook has an invalid cell reference: {reference}"
            )
        value = 0
        for character in match.group(1):
            value = value * 26 + ord(character) - ord("A") + 1
        return value - 1

    @classmethod
    def _xlsx_rows(cls, path: Path) -> list[tuple[int, list[str]]]:
        """Read the one registered worksheet without extracting or trusting arbitrary members."""

        allowed_members = {"xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"}
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if (
                    len(members) > 30
                    or sum(item.file_size for item in members) > 1_000_000
                ):
                    raise SourceAdapterError(
                        f"AfSIS workbook exceeds its safe structural limits: {path.name}"
                    )
                available = {item.filename for item in members}
                if not allowed_members.issubset(available):
                    raise SourceAdapterError(
                        f"AfSIS workbook lacks its registered worksheet XML: {path.name}"
                    )
                strings_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                sheet_root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
            raise SourceAdapterError(
                f"AfSIS workbook is unreadable: {path.name}"
            ) from exc

        namespace = f"{{{cls._xlsx_namespace}}}"
        shared_strings = [
            "".join(node.text or "" for node in item.iter(f"{namespace}t"))
            for item in strings_root.findall(f"{namespace}si")
        ]
        rows: list[tuple[int, list[str]]] = []
        for row in sheet_root.findall(f".//{namespace}sheetData/{namespace}row"):
            indexed: dict[int, str] = {}
            for cell in row.findall(f"{namespace}c"):
                reference = str(cell.get("r") or "")
                index = cls._column_index(reference)
                value_node = cell.find(f"{namespace}v")
                value = "" if value_node is None else str(value_node.text or "")
                if cell.get("t") == "s" and value:
                    try:
                        value = shared_strings[int(value)]
                    except (ValueError, IndexError) as exc:
                        raise SourceAdapterError(
                            f"AfSIS workbook has an invalid shared string: {path.name}"
                        ) from exc
                indexed[index] = value.strip()
            width = max(indexed, default=-1) + 1
            rows.append(
                (
                    int(row.get("r") or len(rows) + 1),
                    [indexed.get(i, "") for i in range(width)],
                )
            )
        return rows

    def _variable_metadata(
        self, downloaded: DownloadedFile
    ) -> dict[str, dict[str, str]]:
        rows = self._xlsx_rows(downloaded.path)
        if not rows:
            raise SourceAdapterError("AfSIS variable workbook is empty")
        headers = rows[0][1]
        required_headers = [
            "variable name",
            "variable description",
            "Units - air dry soil basis",
            "instrument used for analysis",
            "method used",
            "lab where analysis was conducted",
            "date samples were collected",
            "year analysis was conducted",
        ]
        if not set(required_headers).issubset(headers):
            raise SourceAdapterError("AfSIS variable workbook headings changed")
        metadata: dict[str, dict[str, str]] = {}
        for row_number, row in rows[1:]:
            padded = row + [""] * max(0, len(headers) - len(row))
            values = dict(zip(headers, padded, strict=False))
            variable = values.get("variable name", "")
            if variable:
                metadata[variable] = {
                    **values,
                    "source_locator": f"{downloaded.path.name}#sheet1-row={row_number}",
                }
        expected = set(self.candidate.registry_entry["target_analytes"].values())
        if not expected.issubset(metadata):
            raise SourceAdapterError(
                "AfSIS variable workbook lacks target-element metadata"
            )
        return metadata

    def _detection_limits(
        self, downloaded: DownloadedFile
    ) -> dict[str, dict[str, str]]:
        rows = {
            row_number: values
            for row_number, values in self._xlsx_rows(downloaded.path)
        }
        limits: dict[str, dict[str, str]] = {}
        for method, header_row, dl_row, ql_row in (
            ("ICP-OES (Perkin Elmer Optima)", 7, 8, 9),
            ("ICP-MS (Perkin Elmer NexION)", 16, 17, 18),
        ):
            headers = rows.get(header_row, [])
            dl_values = rows.get(dl_row, [])
            ql_values = rows.get(ql_row, [])
            for index, analyte in enumerate(headers):
                if not analyte:
                    continue
                limits[f"{method}|{analyte}"] = {
                    "detection_limit": dl_values[index]
                    if index < len(dl_values)
                    else "",
                    "quantitation_limit": ql_values[index]
                    if index < len(ql_values)
                    else "",
                    "source_locator": (
                        f"{downloaded.path.name}#sheet1-rows={header_row},{dl_row},{ql_row}"
                    ),
                }
        required = {
            "ICP-MS (Perkin Elmer NexION)|As",
            *{
                f"ICP-OES (Perkin Elmer Optima)|{item}"
                for item in ("Cr", "Cu", "Ni", "Pb", "Zn")
            },
        }
        if not required.issubset(limits) or any(
            not limits[key]["detection_limit"] or not limits[key]["quantitation_limit"]
            for key in required
        ):
            raise SourceAdapterError(
                "AfSIS detection-limit workbook lacks registered target limits"
            )
        return limits

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if set(by_id) != {"measurements", "variables", "detection-limits"}:
            raise SourceAdapterError(
                "AfSIS adapter requires the exact three registered original files"
            )
        variables = self._variable_metadata(by_id["variables"])
        limits = self._detection_limits(by_id["detection-limits"])
        target_fields = self.candidate.registry_entry["target_analytes"]
        expected = self.candidate.registry_entry["expected_counts"]
        seen_ssn: set[str] = set()
        seen_res: set[str] = set()
        countries: set[str] = set()
        sites: set[tuple[str, str]] = set()
        coordinate_pairs = 0
        target_counts: dict[str, int] = {analyte: 0 for analyte in target_fields}
        negative_counts: dict[str, int] = {analyte: 0 for analyte in target_fields}
        below_dl_counts: dict[str, int] = {analyte: 0 for analyte in target_fields}
        all_positive_rows = 0
        all_positive_complete_coordinate_rows = 0
        emitted = 0
        try:
            handle = by_id["measurements"].path.open(
                "r", encoding="utf-8-sig", newline=""
            )
        except OSError as exc:
            raise SourceAdapterError("AfSIS measurement CSV is unreadable") from exc
        with handle:
            reader = csv.DictReader(handle)
            required = set(self.candidate.registry_entry["required_fields"]) | set(
                target_fields.values()
            )
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise SourceAdapterError(
                    "AfSIS measurement CSV lacks registered fields"
                )
            for values in reader:
                emitted += 1
                ssn = str(values.get("SSN") or "").strip()
                res_id = str(values.get("RES.ID") or "").strip()
                if not ssn or not res_id or ssn in seen_ssn or res_id in seen_res:
                    raise SourceAdapterError(
                        f"AfSIS sample identifiers are missing or duplicated at row {reader.line_num}"
                    )
                seen_ssn.add(ssn)
                seen_res.add(res_id)
                country = str(values.get("Country") or "").strip()
                site = str(values.get("Site") or "").strip()
                countries.add(country)
                sites.add((country, site))
                latitude = str(values.get("Latitude") or "").strip()
                longitude = str(values.get("Longitude") or "").strip()
                if bool(latitude) != bool(longitude):
                    raise SourceAdapterError(
                        f"AfSIS sample has only one coordinate at row {reader.line_num}"
                    )
                coordinate_pairs += bool(latitude and longitude)
                depth = str(values.get("Depth") or "").strip()
                if depth not in {"Topsoil", "Subsoil"}:
                    raise SourceAdapterError(
                        f"AfSIS sample has an unknown depth class at row {reader.line_num}"
                    )
                observations: dict[str, dict[str, Any]] = {}
                for analyte, field in target_fields.items():
                    raw_value = str(values.get(field) or "").strip()
                    try:
                        numeric = float(raw_value)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"AfSIS {field} is not numeric at row {reader.line_num}"
                        ) from exc
                    variable = variables[field]
                    limit_key = (
                        "ICP-MS (Perkin Elmer NexION)|As"
                        if analyte == "As"
                        else f"ICP-OES (Perkin Elmer Optima)|{analyte}"
                    )
                    threshold = limits[limit_key]
                    detection_limit = float(threshold["detection_limit"])
                    quantitation_limit = float(threshold["quantitation_limit"])
                    target_counts[analyte] += 1
                    negative_counts[analyte] += numeric < 0
                    below_dl_counts[analyte] += 0 <= numeric < detection_limit
                    observations[analyte] = {
                        "value": raw_value,
                        "unit": variable["Units - air dry soil basis"],
                        "detection_limit": threshold["detection_limit"],
                        "quantitation_limit": threshold["quantitation_limit"],
                        "below_detection_limit": 0 <= numeric < detection_limit,
                        "below_quantitation_limit": 0 <= numeric < quantitation_limit,
                        "negative_numeric_result": numeric < 0,
                        "measurement_basis": "aqua_regia_quasi_total_air_dry_soil",
                        "analytical_method": variable[
                            "instrument used for analysis"
                        ].strip(),
                        "digestion_or_extraction": variable["method used"].strip(),
                        "laboratory": variable[
                            "lab where analysis was conducted"
                        ].strip(),
                        "source_variable_description": variable[
                            "variable description"
                        ].strip(),
                        "variable_metadata_locator": variable["source_locator"],
                        "threshold_metadata_locator": threshold["source_locator"],
                    }
                all_positive = all(
                    float(observations[analyte]["value"]) > 0
                    for analyte in target_fields
                )
                all_positive_rows += int(all_positive)
                all_positive_complete_coordinate_rows += int(
                    all_positive and bool(latitude and longitude)
                )
                source_locator = (
                    f"{by_id['measurements'].path.name}#row={reader.line_num}"
                )
                depth_range = ("0", "0.2") if depth == "Topsoil" else ("0.2", "0.5")
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, ssn, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_country_normalized": self._country_names.get(
                            country, country
                        ),
                        "_target_observations": observations,
                        "_source_file": by_id["measurements"].path.name,
                        "_source_crs": "",
                        "_medium": "soil",
                        "_sample_type": depth,
                        "_sample_depth_min_m": depth_range[0],
                        "_sample_depth_max_m": depth_range[1],
                        "_measurement_basis": "aqua_regia_quasi_total_air_dry_soil",
                        "_grain_fraction": "<2 mm",
                        "_dataset_version": self.candidate.version,
                        "_metadata_conflicts": [
                            "As.75 source column is described as Arsenic-78 in the variable workbook; the raw field "
                            "name and description are both retained and the isotope label is not silently repaired.",
                            "The variable workbook reports sampling in 2009-2013 while the related SOIL article "
                            "reports AfSIS field sampling in 2009-2012.",
                        ],
                        "_quality_boundary": (
                            "Published numeric results are retained verbatim. Negative instrument results and positive "
                            "values below the source-wide DL or QL are flagged, not silently removed or promoted to detections."
                        ),
                    },
                )
        reconciled = {
            "physical_rows": emitted,
            "unique_ssn": len(seen_ssn),
            "unique_res_id": len(seen_res),
            "country_labels": len(countries),
            "country_site_pairs": len(sites),
            "complete_coordinate_pairs": coordinate_pairs,
            "target_value_counts": target_counts,
            "negative_value_counts": negative_counts,
            "positive_below_dl_counts": below_dl_counts,
        }
        if reconciled != expected:
            raise SourceAdapterError(
                f"AfSIS reconciliation changed: {reconciled!r} != {expected!r}"
            )
        research_capacity = self.candidate.registry_entry.get("research_slice_capacity")
        expected_capacity = (
            research_capacity.get("per_analyte_observation_count")
            if isinstance(research_capacity, Mapping)
            else None
        )
        if (
            not isinstance(expected_capacity, Mapping)
            or all_positive_rows
            != research_capacity.get("all_registered_positive_sample_rows")
            or all_positive_complete_coordinate_rows
            != research_capacity.get("all_registered_positive_complete_coordinate_rows")
            or set(expected_capacity.values()) != {all_positive_rows}
            or sum(int(value) for value in expected_capacity.values())
            != research_capacity.get("all_registered_observation_count")
        ):
            raise SourceAdapterError(
                "AfSIS research slice capacity changed: "
                f"positive={all_positive_rows}, "
                f"positive_with_coordinates={all_positive_complete_coordinate_rows}"
            )


class WqpSacramentoRiverArsenicAdapter(RegistryAdapter):
    """Content-addressed USGS/NWIS dissolved-As station series from WQP."""

    source_id = "us-wqp-sacramento-river-arsenic"

    @staticmethod
    def _rows(
        path: Path, required_fields: Sequence[str]
    ) -> list[tuple[int, dict[str, str]]]:
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(f"WQP CSV is unreadable: {path.name}") from exc
        with handle:
            reader = csv.DictReader(handle)
            missing = sorted(set(required_fields) - set(reader.fieldnames or []))
            if missing:
                raise SourceAdapterError(
                    f"WQP CSV {path.name} lacks fields: {', '.join(missing)}"
                )
            return [
                (
                    reader.line_num,
                    {
                        str(key): str(value or "").strip()
                        for key, value in row.items()
                        if key is not None
                    },
                )
                for row in reader
            ]

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                "WQP adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in WQP demo directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        entry = candidate.registry_entry["download"]
        results: list[DownloadedFile] = []
        for file_entry in entry["files"]:
            path = root / file_entry["filename"]
            if mode == "online":
                args = _download_args(
                    url=file_entry["url"],
                    output=path,
                    manifest=root / f"{file_entry['file_id']}.download.json",
                    license_id=candidate.license_id,
                    expected_sha256=file_entry["expected_sha256"],
                    max_bytes=int(entry["max_bytes_per_file"]),
                    dataset_doi=candidate.dataset_doi,
                    dataset_version=candidate.version,
                    offline=False,
                )
                try:
                    observed = downloader.run(args)
                except (downloader.DownloadError, OSError) as exc:
                    raise SourceAdapterError(
                        f"WQP download failed for {file_entry['file_id']}: {exc}"
                    ) from exc
                cache_status = observed["status"]
                retrieved_at = observed.get("accessed_at") or observed.get(
                    "cache_verified_at"
                )
            else:
                if not path.is_file():
                    raise SourceAdapterError(f"WQP verified cache is missing: {path}")
                cache_status = "cache_verified"
                retrieved_at = entry["observed_at"]
            if path.stat().st_size != file_entry["bytes"]:
                raise SourceAdapterError(
                    f"WQP snapshot byte count changed: {file_entry['filename']}"
                )
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=path,
                    source_url=file_entry["url"],
                    bytes=path.stat().st_size,
                    cache_status=cache_status,
                    retrieved_at=retrieved_at,
                )
            )
        return results

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if set(by_id) != {"results", "station"}:
            raise SourceAdapterError(
                f"WQP adapter requires result and station CSVs; received={sorted(by_id)}"
            )
        registry = self.candidate.registry_entry
        station_rows = self._rows(
            by_id["station"].path, registry["required_station_fields"]
        )
        if len(station_rows) != 1:
            raise SourceAdapterError(
                f"WQP station query returned {len(station_rows)} rows"
            )
        station_line, station = station_rows[0]
        if (
            station["MonitoringLocationIdentifier"] != "USGS-11447650"
            or station["OrganizationIdentifier"] != "USGS-CA"
            or station["ProviderName"] != "NWIS"
            or station["MonitoringLocationTypeName"] != "Stream"
        ):
            raise SourceAdapterError("WQP station identity changed")
        station["_metadata_source_locator"] = (
            f"{by_id['station'].path.name}#row={station_line}"
        )

        result_rows = self._rows(
            by_id["results"].path, registry["required_result_fields"]
        )
        expected = registry["expected_counts"]
        result_ids: set[str] = set()
        activity_ids: set[str] = set()
        statuses: Counter[str] = Counter()
        activity_types: Counter[str] = Counter()
        method_ids: Counter[str] = Counter()
        numeric_results = 0
        not_detected = 0
        for line_number, values in result_rows:
            if (
                values["MonitoringLocationIdentifier"]
                != station["MonitoringLocationIdentifier"]
                or values["OrganizationIdentifier"] != "USGS-CA"
                or values["ProviderName"] != "NWIS"
                or values["CharacteristicName"] != "Arsenic"
                or values["ResultSampleFractionText"] != "Dissolved"
                or values["ActivityMediaName"] != "Water"
            ):
                raise SourceAdapterError(
                    f"WQP result identity or medium changed at row {line_number}"
                )
            result_id = values["ResultIdentifier"]
            activity_id = values["ActivityIdentifier"]
            if (
                not result_id
                or result_id in result_ids
                or not activity_id
                or activity_id in activity_ids
            ):
                raise SourceAdapterError(
                    f"WQP result/activity identifier is missing or duplicated at row {line_number}"
                )
            result_ids.add(result_id)
            activity_ids.add(activity_id)
            raw_value = values["ResultMeasureValue"]
            unit = values["ResultMeasure/MeasureUnitCode"]
            detection_condition = values["ResultDetectionConditionText"]
            qualifier = ""
            if raw_value:
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"WQP result is not numeric at row {line_number}"
                    ) from exc
                if unit != "ug/l":
                    raise SourceAdapterError(
                        f"WQP result unit changed at row {line_number}: {unit}"
                    )
                numeric_results += 1
            elif detection_condition == "Not Detected":
                raw_value = values["DetectionQuantitationLimitMeasure/MeasureValue"]
                unit = values["DetectionQuantitationLimitMeasure/MeasureUnitCode"]
                qualifier = "<"
                if not raw_value or unit != "ug/l":
                    raise SourceAdapterError(
                        f"WQP censored result lacks a usable limit at row {line_number}"
                    )
                not_detected += 1
            else:
                raise SourceAdapterError(
                    f"WQP result lacks both value and detection condition at row {line_number}"
                )
            method_id = (
                f"{values['ResultAnalyticalMethod/MethodIdentifierContext']}:"
                f"{values['ResultAnalyticalMethod/MethodIdentifier']}"
            )
            method_name = values["ResultAnalyticalMethod/MethodName"]
            if not method_id or not method_name:
                raise SourceAdapterError(
                    f"WQP analytical method is missing at row {line_number}"
                )
            statuses[values["ResultStatusIdentifier"]] += 1
            activity_types[values["ActivityTypeCode"]] += 1
            method_ids[method_id] += 1
            source_locator = f"{by_id['results'].path.name}#row={line_number}"
            method_description = values["ResultAnalyticalMethod/MethodDescriptionText"]
            analytical_method = f"{method_id}: {method_name}"
            if method_description:
                analytical_method += f" ({method_description})"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, result_id, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "_station_metadata": station,
                    "_source_file": by_id["results"].path.name,
                    "_target_observations": {
                        "As": {
                            "field": "ResultMeasureValue",
                            "value": raw_value,
                            "unit": unit,
                            "value_qualifier": qualifier,
                            "detection_limit": values[
                                "DetectionQuantitationLimitMeasure/MeasureValue"
                            ],
                            "detection_limit_unit": values[
                                "DetectionQuantitationLimitMeasure/MeasureUnitCode"
                            ],
                            "detection_limit_type": values[
                                "DetectionQuantitationLimitTypeName"
                            ],
                            "measurement_basis": "dissolved_surface_freshwater_mass_per_volume",
                            "analytical_method": analytical_method,
                            "digestion_or_extraction": "dissolved water; USGS filtered-water method",
                            "laboratory": values["LaboratoryName"],
                            "variable_metadata_locator": source_locator,
                            "source_result_status": values["ResultStatusIdentifier"],
                            "activity_type": values["ActivityTypeCode"],
                        }
                    },
                    "_dataset_version": self.candidate.version,
                },
            )
        reconciled = {
            "physical_rows": len(result_rows),
            "target_observations": len(result_rows),
            "numeric_results": numeric_results,
            "not_detected_results": not_detected,
            "unique_activity_ids": len(activity_ids),
            "unique_result_ids": len(result_ids),
            "accepted_results": statuses["Accepted"],
            "preliminary_results": statuses["Preliminary"],
            "routine_samples": activity_types["Sample-Routine"],
            "field_replicates": activity_types[
                "Quality Control Sample-Field Replicate"
            ],
            "analytical_method_ids": dict(sorted(method_ids.items())),
        }
        if reconciled != expected:
            raise SourceAdapterError(
                f"WQP reconciliation changed: {reconciled!r} != {expected!r}"
            )


class _PinnedSingleFileAdapter(RegistryAdapter):
    """Shared exact-file acquisition for small, immutable sediment products."""

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                f"{self.source_id} adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                f"use the checked-in {self.source_id} demo directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        file_entry = download_entry["files"][0]
        output = root / file_entry["filename"]
        args = _download_args(
            url=file_entry["url"],
            output=output,
            manifest=root / "dataset.download.json",
            license_id=candidate.license_id,
            expected_sha256=file_entry.get("expected_sha256"),
            max_bytes=int(download_entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
            # Parsers validate source fields using each file's registered encoding.
            # The generic downloader's field check assumes UTF-8 and is therefore
            # intentionally disabled for CP1252 and Shift_JIS sources.
            required_fields=(),
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(
                f"{self.source_id} download failed: {exc}"
            ) from exc
        content_type = result.get("content_type")
        if content_type and content_type not in set(
            download_entry["accepted_content_types"]
        ):
            raise SourceAdapterError(
                f"{self.source_id} returned unexpected content type: {content_type}"
            )
        if output.stat().st_size != file_entry["bytes"]:
            raise SourceAdapterError(f"{self.source_id} file size changed")
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=file_entry["file_id"],
                path=output,
                source_url=file_entry["url"],
                bytes=result["bytes"],
                cache_status=result["status"],
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
            )
        ]


_FIGSHARE_SIGNED_QUERY_KEYS = {
    "X-Amz-Algorithm",
    "X-Amz-Credential",
    "X-Amz-Date",
    "X-Amz-Expires",
    "X-Amz-Signature",
    "X-Amz-SignedHeaders",
}


def validate_figshare_storage_redirect(url: str, file_id: str, filename: str) -> str:
    """Validate one ephemeral Figshare storage capability without persisting it."""

    parsed = urllib.parse.urlparse(url)
    redacted = urllib.parse.urlunparse(parsed._replace(query="", fragment=""))
    downloader.validate_public_https_url(redacted)
    expected_path = f"/pfigshare-u-files/{file_id}/{urllib.parse.quote(filename)}"
    if (
        parsed.hostname != "s3-eu-west-1.amazonaws.com"
        or parsed.path != expected_path
        or parsed.fragment
    ):
        raise SourceAdapterError(
            "Figshare redirect left the registered storage host or file path"
        )
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != _FIGSHARE_SIGNED_QUERY_KEYS or any(
        len(values) != 1 or not values[0] for values in query.values()
    ):
        raise SourceAdapterError("Figshare signed redirect envelope changed")
    try:
        expires = int(query["X-Amz-Expires"][0])
    except ValueError as exc:
        raise SourceAdapterError("Figshare redirect expiry is invalid") from exc
    if (
        query["X-Amz-Algorithm"][0] != "AWS4-HMAC-SHA256"
        or not re.fullmatch(r"\d{8}T\d{6}Z", query["X-Amz-Date"][0])
        or not 1 <= expires <= 60
        or query["X-Amz-SignedHeaders"][0] != "host"
        or not re.fullmatch(r"[0-9a-f]{64}", query["X-Amz-Signature"][0])
    ):
        raise SourceAdapterError("Figshare signed redirect policy changed")
    return redacted


class AustraliaNgsaAtlasAdapter(_PinnedSingleFileAdapter):
    """Pinned four-element NGSA catchment-outlet sediment table."""

    source_id = "australia-ngsa"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "atlas-csv":
            raise SourceAdapterError("NGSA atlas adapter requires the registered CSV")
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            handle = downloaded.path.open("r", encoding="cp1252", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"NGSA atlas CSV is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            for _ in range(11):
                next(handle, None)
            reader = csv.DictReader(handle)
            missing = sorted(
                set(registry["required_fields"]) - set(reader.fieldnames or [])
            )
            if missing:
                raise SourceAdapterError(
                    f"NGSA atlas CSV lacks fields: {', '.join(missing)}"
                )
            rows = 0
            samples: set[str] = set()
            sites: set[str] = set()
            selected_grain_rows = 0
            target_counts: Counter[str] = Counter()
            depths: Counter[str] = Counter()
            grains: Counter[str] = Counter()
            duplicate_codes: Counter[str] = Counter()
            coordinate_rows = 0
            independent_complete_rows = 0
            independent_target_counts: Counter[str] = Counter()
            for row in reader:
                values = {
                    str(key): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                if not any(values.values()):
                    continue
                line_number = reader.line_num + 11
                sample_id = values["SAMPLEID"]
                site_id = values["SITEID"]
                if not sample_id or sample_id in samples or not site_id:
                    raise SourceAdapterError(
                        f"NGSA atlas sample/site identity is missing or duplicated at row {line_number}"
                    )
                try:
                    float(values["LATITUDE"])
                    float(values["LONGITUDE"])
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"NGSA atlas coordinate is not numeric at row {line_number}"
                    ) from exc
                if values["DEPTH"] not in {"TOS", "BOS"} or values[
                    "GRAIN SIZE"
                ] not in {"Bulk", "<2 mm", "<75 µm"}:
                    raise SourceAdapterError(
                        f"NGSA atlas grain or depth classification changed at row {line_number}"
                    )
                rows += 1
                samples.add(sample_id)
                sites.add(site_id)
                depths[values["DEPTH"]] += 1
                grains[values["GRAIN SIZE"]] += 1
                duplicate_codes[values["DUPLICATE CODE"]] += 1
                coordinate_rows += 1
                targets: dict[str, dict[str, str]] = {}
                if values["GRAIN SIZE"] == "<75 µm":
                    selected_grain_rows += 1
                    for analyte, field in registry["target_analytes"].items():
                        raw_value = values[field]
                        if not raw_value:
                            continue
                        try:
                            float(raw_value.lstrip("<>").strip())
                        except ValueError as exc:
                            raise SourceAdapterError(
                                f"NGSA atlas {analyte} value is invalid at row {line_number}"
                            ) from exc
                        target_counts[analyte] += 1
                        targets[analyte] = {
                            "field": field,
                            "value": raw_value,
                            "unit": "mg/kg",
                            "measurement_basis": (
                                f"ICP-MS reported concentration in <75 µm catchment-outlet sediment; {values['DEPTH']}"
                            ),
                            "analytical_method": (
                                "inductively coupled plasma mass spectrometry (ICP-MS; publisher header and method key)"
                            ),
                            "digestion_or_extraction": (
                                "publisher classifies ICP-MS in the total analytical "
                                "suite; digestion chemistry is not stated in the CSV"
                            ),
                            "laboratory": "",
                            "laboratory_missing_reason": "publisher_not_reported_in_csv",
                            "method_source_locator": f"{downloaded.path.name}#row=6",
                            "variable_metadata_locator": (
                                f"{downloaded.path.name}#row=12#column={field}"
                            ),
                            "detection_limit": field.rsplit(" ", 1)[-1],
                        }
                    if not values["DUPLICATE CODE"] and len(targets) == len(
                        registry["target_analytes"]
                    ):
                        independent_complete_rows += 1
                        independent_target_counts.update(targets.keys())
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_id, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "EPSG:4283",
                        "_coordinate_transformation": (
                            "gda94-geographic-wgs84-identity-v1"
                        ),
                        "_sample_type": "top outlet sediment"
                        if values["DEPTH"] == "TOS"
                        else "bottom outlet sediment",
                        "_grain_fraction": values["GRAIN SIZE"],
                        "_target_observations": targets,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_samples": len(samples),
            "distinct_sites": len(sites),
            "target_observations": sum(target_counts.values()),
            "selected_grain_rows": selected_grain_rows,
            "target_value_counts": dict(sorted(target_counts.items())),
            "depth_counts": dict(sorted(depths.items())),
            "grain_counts": dict(sorted(grains.items())),
            "duplicate_code_counts": dict(sorted(duplicate_codes.items())),
            "valid_coordinate_rows": coordinate_rows,
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"NGSA atlas reconciliation changed: {observed!r} != {registry['expected_counts']!r}"
            )
        research_capacity = registry.get("research_slice_capacity")
        if not isinstance(research_capacity, Mapping):
            raise SourceAdapterError("NGSA atlas research slice capacity is missing")
        expected_independent = research_capacity.get("independent_complete_sample_rows")
        expected_target_counts = research_capacity.get("per_analyte_observation_count")
        if (
            independent_complete_rows != expected_independent
            or dict(sorted(independent_target_counts.items())) != expected_target_counts
            or independent_complete_rows * len(registry["target_analytes"])
            != research_capacity.get("four_analyte_observation_count")
        ):
            raise SourceAdapterError(
                "NGSA atlas independent research capacity changed: "
                f"rows={independent_complete_rows}, targets={dict(sorted(independent_target_counts.items()))!r}"
            )


class AustraliaNgsaMercuryAdapter(_PinnedSingleFileAdapter):
    """Pinned NGSA top/bottom outlet-sediment total-mercury table."""

    source_id = "australia-ngsa-mercury"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "mercury-csv":
            raise SourceAdapterError("NGSA mercury adapter requires the registered CSV")
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            handle = downloaded.path.open("r", encoding="cp1252", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"NGSA mercury CSV is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            for _ in range(11):
                next(handle, None)
            reader = csv.DictReader(handle)
            missing = sorted(
                set(registry["required_fields"]) - set(reader.fieldnames or [])
            )
            if missing:
                raise SourceAdapterError(
                    f"NGSA mercury CSV lacks fields: {', '.join(missing)}"
                )
            rows = 0
            samples: set[str] = set()
            sites: set[str] = set()
            depths: Counter[str] = Counter()
            states: Counter[str] = Counter()
            duplicate_codes: Counter[str] = Counter()
            for row in reader:
                values = {
                    str(key): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                if not any(values.values()):
                    continue
                line_number = reader.line_num + 11
                sample_id = values["SAMPLEID"]
                site_id = values["SITEID"]
                raw_value = values["Hg_DMA_ng/g_0.01"]
                if not sample_id or sample_id in samples or not site_id:
                    raise SourceAdapterError(
                        f"NGSA sample/site identity is missing or duplicated at row {line_number}"
                    )
                try:
                    float(raw_value)
                    float(values["LATITUDE_GDA94"])
                    float(values["LONGITUDE_GDA94"])
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"NGSA value or coordinate is not numeric at row {line_number}"
                    ) from exc
                if values["GRAIN_SIZE"] != "<75 µm" or values["DEPTH"] not in {
                    "TOS",
                    "BOS",
                }:
                    raise SourceAdapterError(
                        f"NGSA grain or depth classification changed at row {line_number}"
                    )
                rows += 1
                samples.add(sample_id)
                sites.add(site_id)
                depths[values["DEPTH"]] += 1
                states[values["STATE"]] += 1
                duplicate_codes[values["DUPLICATE_CODE"]] += 1
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_id, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        # Preserve the publisher datum. D2/full-profile code may
                        # create canonical WGS84 fields only through the registered
                        # identity-tolerance policy; raw GDA94 values remain intact.
                        "_source_crs": "EPSG:4283",
                        "_coordinate_transformation": (
                            "gda94-geographic-wgs84-identity-v1"
                        ),
                        "_sample_type": "top outlet sediment"
                        if values["DEPTH"] == "TOS"
                        else "bottom outlet sediment",
                        "_grain_fraction": "<75 µm",
                        "_target_observations": {
                            "Hg": {
                                "field": "Hg_DMA_ng/g_0.01",
                                "value": raw_value,
                                "unit": "ng/g",
                                "measurement_basis": "total_mercury_dry_weight_<75um_outlet_sediment",
                                "analytical_method": "USEPA Method 7473; Milestone tri-cell DMA-80 direct mercury analyser",
                                "digestion_or_extraction": "thermal decomposition and direct analysis; no acid digestion",
                                "laboratory": "Geoscience Australia",
                                "variable_metadata_locator": f"{downloaded.path.name}#row=6",
                                "mass_detection_limit_ng": "0.01",
                                "detection_limit": "",
                                "duplicate_code": values["DUPLICATE_CODE"],
                            }
                        },
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_samples": len(samples),
            "distinct_sites": len(sites),
            "target_observations": rows,
            "depth_counts": dict(sorted(depths.items())),
            "state_counts": dict(sorted(states.items())),
            "duplicate_code_counts": dict(sorted(duplicate_codes.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"NGSA mercury reconciliation changed: {observed!r}"
            )


class GsjJapanMarineSedimentAdapter(_PinnedSingleFileAdapter):
    """Pinned GSJ marine-sediment concentration table from 37 cruises."""

    source_id = "japan-gsj-marine-sediment"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "marine-concentrations":
            raise SourceAdapterError("GSJ marine adapter requires ocean-noudo.csv")
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            handle = downloaded.path.open("r", encoding="shift_jis", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"GSJ marine CSV is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            reader = csv.DictReader(handle)
            missing = sorted(
                set(registry["required_fields"]) - set(reader.fieldnames or [])
            )
            if missing:
                raise SourceAdapterError(
                    f"GSJ marine CSV lacks fields: {', '.join(missing)}"
                )
            rows = 0
            samples: set[str] = set()
            cruises: set[str] = set()
            regions: set[str] = set()
            target_counts: Counter[str] = Counter()
            positive_counts: Counter[str] = Counter()
            negative_hg = 0
            missing_depth = 0
            for row in reader:
                values = {
                    str(key): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                if not any(values.values()):
                    continue
                line_number = reader.line_num
                sample_id = values["試料番号"]
                if not sample_id or sample_id in samples:
                    raise SourceAdapterError(
                        f"GSJ marine sample ID is missing or duplicated at row {line_number}"
                    )
                try:
                    float(values["緯度"])
                    float(values["経度"])
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"GSJ marine coordinate is not numeric at row {line_number}"
                    ) from exc
                target_observations: dict[str, dict[str, Any]] = {}
                for analyte, field_name in registry["target_analytes"].items():
                    raw_value = values[field_name]
                    if not raw_value:
                        continue
                    try:
                        number = float(raw_value)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"GSJ marine {analyte} is not numeric at row {line_number}"
                        ) from exc
                    unit = registry["target_units"][analyte]
                    target_counts[analyte] += 1
                    positive_counts[analyte] += int(number > 0)
                    negative_hg += int(analyte == "Hg" and number < 0)
                    target_observations[analyte] = {
                        "field": field_name,
                        "value": raw_value,
                        "unit": unit,
                        "measurement_basis": "published_marine_sediment_concentration",
                        "analytical_method": "",
                        "detection_limit": "",
                    }
                rows += 1
                samples.add(sample_id)
                cruises.add(values["航海"])
                regions.add(values["地域"])
                missing_depth += int(not values["深度_m_"])
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_id, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "JGD2000 geographic; treated as EPSG:4612 for query-grid profiling",
                        "_grain_fraction": "not reported in concentration CSV",
                        "_target_observations": target_observations,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_samples": len(samples),
            "distinct_cruises": len(cruises),
            "distinct_regions": len(regions),
            "missing_water_depth_rows": missing_depth,
            "negative_hg_values": negative_hg,
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(f"GSJ marine reconciliation changed: {observed!r}")
        research_capacity = registry.get("research_slice_capacity")
        expected_positive = (
            research_capacity.get("per_analyte_observation_count")
            if isinstance(research_capacity, Mapping)
            else None
        )
        if (
            not isinstance(expected_positive, Mapping)
            or dict(sorted(positive_counts.items())) != expected_positive
            or sum(positive_counts.values())
            != research_capacity.get("positive_observation_count")
        ):
            raise SourceAdapterError(
                "GSJ marine positive research capacity changed: "
                f"{dict(sorted(positive_counts.items()))!r}"
            )


class PangaeaArabianSeaSedimentAdapter(_PinnedSingleFileAdapter):
    """Pinned PANGAEA modern/glacial Arabian Sea bulk-sediment table."""

    source_id = "pangaea-arabian-sea-sediment"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "dataset-table":
            raise SourceAdapterError(
                "PANGAEA Arabian Sea adapter requires the registered table"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            handle = downloaded.path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA Arabian Sea table is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            rows = 0
            samples: set[str] = set()
            events: set[str] = set()
            target_counts: Counter[str] = Counter()
            for row in reader:
                if header is None:
                    if row and row[0].strip() == "*/":
                        header = [value.strip() for value in next(reader)]
                        missing = sorted(set(registry["required_fields"]) - set(header))
                        if missing:
                            raise SourceAdapterError(
                                f"PANGAEA Arabian Sea table lacks fields: {', '.join(missing)}"
                            )
                        mgkg_fields = [
                            field for field in header if field.endswith(" [mg/kg]")
                        ]
                        if (
                            len(mgkg_fields)
                            != registry["expected_counts"]["mgkg_fields"]
                        ):
                            raise SourceAdapterError(
                                "PANGAEA Arabian Sea mg/kg field count changed"
                            )
                    continue
                if not any(value.strip() for value in row):
                    continue
                padded = [value.strip() for value in row] + [""] * max(
                    0, len(header) - len(row)
                )
                values = dict(zip(header, padded, strict=False))
                line_number = reader.line_num
                sample_label = values["Sample label"]
                event = values["Event"]
                if not sample_label or not event:
                    raise SourceAdapterError(
                        f"PANGAEA Arabian Sea identity is missing at row {line_number}"
                    )
                target_observations: dict[str, dict[str, Any]] = {}
                for analyte, field_name in registry["target_analytes"].items():
                    raw_value = values[field_name]
                    if not raw_value:
                        continue
                    try:
                        float(raw_value)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"PANGAEA Arabian Sea {analyte} is not numeric at row {line_number}"
                        ) from exc
                    target_counts[analyte] += 1
                    target_observations[analyte] = {
                        "field": field_name,
                        "value": raw_value,
                        "unit": "mg/kg",
                        "measurement_basis": "bulk_marine_sediment_geochemical_analysis",
                        "analytical_method": "Geochemical analysis on bulk sediment",
                        "digestion_or_extraction": "not reported in publisher table",
                        "variable_metadata_locator": f"{downloaded.path.name}#parameter={field_name}",
                    }
                rows += 1
                samples.add(sample_label)
                events.add(event)
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_label, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "EPSG:4326",
                        "_sample_type": "marine core sediment",
                        "_target_observations": target_observations,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_sample_labels": len(samples),
            "distinct_events": len(events),
            "mgkg_fields": registry["expected_counts"]["mgkg_fields"],
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"PANGAEA Arabian Sea reconciliation changed: {observed!r}"
            )


class PangaeaEastChinaSeaClayAdapter(_PinnedSingleFileAdapter):
    """Pinned PANGAEA East China Sea, Yangtze and Taiwan river clay table."""

    source_id = "pangaea-east-china-sea-clay"

    _BASIS_BY_SAMPLE_TYPE = {
        "Bulk": "clay_fraction_bulk_sediment_analysis",
        "Residue": "clay_fraction_leach_residue_sediment_analysis",
    }

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "dataset-table":
            raise SourceAdapterError(
                "PANGAEA East China Sea clay adapter requires the registered table"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            handle = downloaded.path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA East China Sea clay table is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            rows = 0
            sample_ids: set[str] = set()
            events: set[str] = set()
            sample_type_rows: Counter[str] = Counter()
            target_counts: Counter[str] = Counter()
            for row in reader:
                if header is None:
                    if row and row[0].strip() == "*/":
                        header = [value.strip() for value in next(reader)]
                        missing = sorted(set(registry["required_fields"]) - set(header))
                        if missing:
                            raise SourceAdapterError(
                                "PANGAEA East China Sea clay table lacks fields: "
                                + ", ".join(missing)
                            )
                        mgkg_fields = [
                            field for field in header if field.endswith(" [mg/kg]")
                        ]
                        if (
                            len(mgkg_fields)
                            != registry["expected_counts"]["mgkg_fields"]
                        ):
                            raise SourceAdapterError(
                                "PANGAEA East China Sea clay mg/kg field count changed"
                            )
                    continue
                if not any(value.strip() for value in row):
                    continue
                padded = [value.strip() for value in row] + [""] * max(
                    0, len(header) - len(row)
                )
                values = dict(zip(header, padded, strict=False))
                line_number = reader.line_num
                event = values["Event"]
                description = values["Description"]
                sample_type = values["Samp type"]
                if not event or not description:
                    raise SourceAdapterError(
                        f"PANGAEA East China Sea clay identity is missing at row {line_number}"
                    )
                basis = self._BASIS_BY_SAMPLE_TYPE.get(sample_type)
                if basis is None:
                    raise SourceAdapterError(
                        f"PANGAEA East China Sea clay sample type is unknown at row {line_number}: {sample_type!r}"
                    )
                try:
                    float(values["Latitude"])
                    float(values["Longitude"])
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"PANGAEA East China Sea clay coordinates are not numeric at row {line_number}"
                    ) from exc
                sample_label = f"{event}|{description}|{sample_type}"
                if sample_label in sample_ids:
                    raise SourceAdapterError(
                        f"PANGAEA East China Sea clay sample id is duplicated at row {line_number}"
                    )
                target_observations: dict[str, dict[str, Any]] = {}
                for analyte, field_name in registry["target_analytes"].items():
                    raw_value = values[field_name]
                    if not raw_value:
                        continue
                    try:
                        float(raw_value)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"PANGAEA East China Sea clay {analyte} is not numeric at row {line_number}"
                        ) from exc
                    target_counts[analyte] += 1
                    target_observations[analyte] = {
                        "field": field_name,
                        "value": raw_value,
                        "unit": "mg/kg",
                        "measurement_basis": basis,
                        "analytical_method": (
                            "X-ray diffraction (XRD) per publisher parameter labels"
                        ),
                        "digestion_or_extraction": (
                            "clay fraction, bulk analysis"
                            if sample_type == "Bulk"
                            else "clay fraction, post-leach residue"
                        ),
                        "variable_metadata_locator": f"{downloaded.path.name}#parameter={field_name}",
                    }
                rows += 1
                sample_ids.add(sample_label)
                events.add(event)
                sample_type_rows[sample_type] += 1
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_label, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "EPSG:4326",
                        "_sample_type": "core sediment clay fraction",
                        "_target_observations": target_observations,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_events": len(events),
            "distinct_sample_ids": len(sample_ids),
            "sample_type_rows": dict(sorted(sample_type_rows.items())),
            "mgkg_fields": registry["expected_counts"]["mgkg_fields"],
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"PANGAEA East China Sea clay reconciliation changed: {observed!r}"
            )


class PangaeaSouthChinaSeaSedimentAdapter(_PinnedSingleFileAdapter):
    """Pinned PANGAEA southern China Sea surface-sediment trace-element table."""

    source_id = "pangaea-south-china-sea-sediment"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "dataset-table":
            raise SourceAdapterError(
                "PANGAEA South China Sea adapter requires the registered table"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            handle = downloaded.path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA South China Sea table is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            rows = 0
            events: set[str] = set()
            target_counts: Counter[str] = Counter()
            for row in reader:
                if header is None:
                    if row and row[0].strip() == "*/":
                        header = [value.strip() for value in next(reader)]
                        missing = sorted(set(registry["required_fields"]) - set(header))
                        if missing:
                            raise SourceAdapterError(
                                "PANGAEA South China Sea table lacks fields: "
                                + ", ".join(missing)
                            )
                        ppm_fields = [
                            field
                            for field in header
                            if field.endswith("(original unit is in ppm)")
                        ]
                        if (
                            len(ppm_fields)
                            != registry["expected_counts"]["ppm_annotated_fields"]
                        ):
                            raise SourceAdapterError(
                                "PANGAEA South China Sea ppm-annotated field count changed"
                            )
                    continue
                if not any(value.strip() for value in row):
                    continue
                padded = [value.strip() for value in row] + [""] * max(
                    0, len(header) - len(row)
                )
                values = dict(zip(header, padded, strict=False))
                line_number = reader.line_num
                event = values["Event"]
                if not event:
                    raise SourceAdapterError(
                        f"PANGAEA South China Sea event is missing at row {line_number}"
                    )
                if event in events:
                    raise SourceAdapterError(
                        f"PANGAEA South China Sea event is duplicated at row {line_number}"
                    )
                try:
                    float(values["Latitude"])
                    float(values["Longitude"])
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"PANGAEA South China Sea coordinates are not numeric at row {line_number}"
                    ) from exc
                target_observations: dict[str, dict[str, Any]] = {}
                for analyte, field_name in registry["target_analytes"].items():
                    raw_value = values[field_name]
                    if not raw_value:
                        continue
                    try:
                        float(raw_value)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"PANGAEA South China Sea {analyte} is not numeric at row {line_number}"
                        ) from exc
                    target_counts[analyte] += 1
                    target_observations[analyte] = {
                        "field": field_name,
                        "value": raw_value,
                        "unit": "mg/kg",
                        "measurement_basis": "bulk_marine_surface_sediment_geochemical_analysis",
                        "analytical_method": "ICP-MS, Perkin-Elmer, Elan 6000",
                        "digestion_or_extraction": "not reported in publisher table",
                        "variable_metadata_locator": f"{downloaded.path.name}#parameter={field_name}",
                    }
                rows += 1
                events.add(event)
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, event, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "EPSG:4326",
                        "_sample_type": "marine surface sediment",
                        "_target_observations": target_observations,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_events": len(events),
            "ppm_annotated_fields": registry["expected_counts"]["ppm_annotated_fields"],
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"PANGAEA South China Sea reconciliation changed: {observed!r}"
            )


class PangaeaBarentsCHorizonSoilAdapter(_PinnedSingleFileAdapter):
    """Pinned Kola Ecogeochemistry C-horizon soil table for the central Barents region."""

    source_id = "pangaea-barents-c-horizon-soil"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "dataset-table":
            raise SourceAdapterError(
                "PANGAEA Barents C-horizon adapter requires the registered table"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        column_map = registry["target_columns"]
        identity = registry["identity_columns"]
        try:
            handle = downloaded.path.open("r", encoding="utf-8-sig", newline="")
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA Barents C-horizon table is unreadable: {downloaded.path.name}"
            ) from exc
        with handle:
            reader = csv.reader(handle, delimiter="\t")
            header: list[str] | None = None
            rows = 0
            labels: set[str] = set()
            target_counts: Counter[str] = Counter()
            censored_counts: Counter[str] = Counter()
            for row in reader:
                if header is None:
                    if row and row[0].strip() == "*/":
                        header = [value.strip() for value in next(reader)]
                        if len(header) != registry["expected_counts"]["table_columns"]:
                            raise SourceAdapterError(
                                "PANGAEA Barents C-horizon column count changed"
                            )
                        # Duplicate publisher column labels force index-pinned
                        # parsing; every pinned index re-verifies its label.
                        for name, spec in {**identity, **column_map}.items():
                            index = int(spec["column"])
                            prefix = str(spec["label_prefix"])
                            if not header[index].startswith(prefix):
                                raise SourceAdapterError(
                                    "PANGAEA Barents C-horizon column moved: "
                                    f"{name} expected {prefix!r} at index {index}, "
                                    f"found {header[index]!r}"
                                )
                    continue
                if not any(value.strip() for value in row):
                    continue
                padded = [value.strip() for value in row] + [""] * max(
                    0, len(header) - len(row)
                )
                line_number = reader.line_num
                sample_label = padded[int(identity["sample_label"]["column"])]
                latitude = padded[int(identity["latitude"]["column"])]
                longitude = padded[int(identity["longitude"]["column"])]
                depth = padded[int(identity["sample_depth"]["column"])]
                description = padded[int(identity["description"]["column"])]
                if not sample_label:
                    raise SourceAdapterError(
                        f"PANGAEA Barents C-horizon identity is missing at row {line_number}"
                    )
                if sample_label in labels:
                    raise SourceAdapterError(
                        f"PANGAEA Barents C-horizon sample is duplicated at row {line_number}"
                    )
                try:
                    float(latitude)
                    float(longitude)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"PANGAEA Barents C-horizon coordinates are not numeric at row {line_number}"
                    ) from exc
                target_observations: dict[str, dict[str, Any]] = {}
                for analyte, spec in column_map.items():
                    raw_value = padded[int(spec["column"])]
                    if not raw_value:
                        continue
                    qualifier = ""
                    numeric_text = raw_value
                    if raw_value.startswith("<"):
                        qualifier = "<"
                        numeric_text = raw_value[1:].strip()
                        censored_counts[analyte] += 1
                    try:
                        float(numeric_text)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"PANGAEA Barents C-horizon {analyte} is not numeric at row {line_number}"
                        ) from exc
                    target_counts[analyte] += 1
                    target_observations[analyte] = {
                        "field": str(spec["label_prefix"]),
                        "value": numeric_text,
                        "unit": "mg/kg",
                        "value_qualifier": qualifier,
                        "detection_limit": str(spec["detection_limit"]),
                        "detection_limit_unit": "mg/kg",
                        "measurement_basis": "aqua_regia_extractable_c_horizon_soil_analysis",
                        "analytical_method": str(spec["analytical_method"]),
                        "digestion_or_extraction": "aqua regia digestion; fraction < 2 mm",
                        "variable_metadata_locator": (
                            f"{downloaded.path.name}#column={int(spec['column'])}"
                        ),
                    }
                rows += 1
                labels.add(sample_label)
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_label, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        "Sample label": sample_label,
                        "Latitude": latitude,
                        "Longitude": longitude,
                        "Depth sed [m]": depth,
                        "Description": description,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "EPSG:4326",
                        "_sample_type": "C-horizon soil",
                        "_target_observations": target_observations,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed = {
            "physical_rows": rows,
            "distinct_sample_labels": len(labels),
            "table_columns": registry["expected_counts"]["table_columns"],
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
            "censored_value_counts": dict(sorted(censored_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"PANGAEA Barents C-horizon reconciliation changed: {observed!r}"
            )


class PangaeaAmazonasSoilAdapter(_PinnedSingleFileAdapter):
    """Pinned multi-element soil chemistry from Amazonas state, Brazil."""

    source_id = "pangaea-amazonas-soil"

    _event_pattern = re.compile(
        r"(?:Event\(s\):\s*)?(?P<event>Amazonas_\d+)\s+\*\s+"
        r"LATITUDE:\s*(?P<latitude>-?\d+(?:\.\d+)?)\s+\*\s+"
        r"LONGITUDE:\s*(?P<longitude>-?\d+(?:\.\d+)?)"
    )

    @classmethod
    def _event_coordinates(cls, lines: Sequence[str]) -> dict[str, tuple[str, str]]:
        coordinates: dict[str, tuple[str, str]] = {}
        for line in lines:
            match = cls._event_pattern.search(line)
            if match is None:
                continue
            event = match.group("event")
            value = (match.group("latitude"), match.group("longitude"))
            if event in coordinates and coordinates[event] != value:
                raise SourceAdapterError(
                    f"PANGAEA Amazonas event coordinate changed within metadata: {event}"
                )
            coordinates[event] = value
        return coordinates

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "dataset-table":
            raise SourceAdapterError(
                "PANGAEA Amazonas adapter requires the registered table"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            lines = downloaded.path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA Amazonas table is unreadable: {downloaded.path.name}"
            ) from exc
        terminators = [
            index for index, line in enumerate(lines) if line.strip() == "*/"
        ]
        if len(terminators) != 1:
            raise SourceAdapterError("PANGAEA Amazonas metadata boundary changed")
        header_index = terminators[0] + 1
        coordinates = self._event_coordinates(lines[:header_index])
        expected_events = int(registry["expected_counts"]["distinct_events"])
        if len(coordinates) != expected_events:
            raise SourceAdapterError(
                f"PANGAEA Amazonas event coordinate count changed: {len(coordinates)}"
            )
        reader = csv.DictReader(lines[header_index:], delimiter="\t")
        missing = sorted(
            set(registry["required_fields"]) - set(reader.fieldnames or [])
        )
        if missing:
            raise SourceAdapterError(
                "PANGAEA Amazonas table lacks fields: " + ", ".join(missing)
            )
        rows = 0
        sample_keys: set[str] = set()
        target_counts: Counter[str] = Counter()
        for values in reader:
            line_number = header_index + reader.line_num
            if not any(str(value or "").strip() for value in values.values()):
                continue
            values = {key: str(value or "").strip() for key, value in values.items()}
            event = values["Event"]
            if event not in coordinates:
                raise SourceAdapterError(
                    f"PANGAEA Amazonas event lacks registered metadata coordinates at row {line_number}"
                )
            sample_key = "|".join(
                (
                    event,
                    values["Date/Time"],
                    values["Depth desc"],
                    values["No (Number of Campaign)"],
                )
            )
            if (
                not event
                or not values["Depth desc"]
                or not values["No (Number of Campaign)"]
                or sample_key in sample_keys
            ):
                raise SourceAdapterError(
                    f"PANGAEA Amazonas sample identity is missing or duplicated at row {line_number}"
                )
            if values["Depth desc"] not in {"TOP", "BOT"}:
                raise SourceAdapterError(
                    f"PANGAEA Amazonas depth class changed at row {line_number}"
                )
            target_observations: dict[str, dict[str, Any]] = {}
            for analyte, field_name in registry["target_analytes"].items():
                raw_value = values[field_name]
                if not raw_value:
                    continue
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"PANGAEA Amazonas {analyte} is not numeric at row {line_number}"
                    ) from exc
                target_counts[analyte] += 1
                is_mercury = analyte == "Hg"
                target_observations[analyte] = {
                    "field": field_name,
                    "value": raw_value,
                    "unit": "mg/kg",
                    "measurement_basis": "gemas_protocol_multi_acid_digest_dry_mineral_soil",
                    "analytical_method": (
                        "Cold vapour atomic absorption spectrometry (CV-AAS)"
                        if is_mercury
                        else "Inductively coupled plasma mass spectrometry (ICP-MS)"
                    ),
                    "digestion_or_extraction": (
                        "GEMAS protocol preparation; publisher parameter metadata assigns CV-AAS Hg determination"
                        if is_mercury
                        else "GEMAS protocol multi-acid digestion"
                    ),
                    "variable_metadata_locator": (
                        f"{downloaded.path.name}#parameter={field_name}"
                    ),
                }
            rows += 1
            sample_keys.add(sample_key)
            latitude, longitude = coordinates[event]
            source_locator = f"{downloaded.path.name}#row={line_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, sample_key, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "Latitude": latitude,
                    "Longitude": longitude,
                    "_source_file": downloaded.path.name,
                    "_source_crs": "EPSG:4326",
                    "_sample_type": (
                        "topsoil 0-20 cm"
                        if values["Depth desc"] == "TOP"
                        else "bottom soil 30-50 cm"
                    ),
                    "_target_observations": target_observations,
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "physical_rows": rows,
            "distinct_sample_keys": len(sample_keys),
            "distinct_events": len(coordinates),
            "table_columns": len(reader.fieldnames or []),
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"PANGAEA Amazonas reconciliation changed: {observed!r}"
            )


class PangaeaBatagaySoilAdapter(_PinnedSingleFileAdapter):
    """Pinned ICP-MS soil and soil-inclusion table from Batagay, Russia."""

    source_id = "pangaea-batagay-soil"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "dataset-table":
            raise SourceAdapterError(
                "PANGAEA Batagay adapter requires the registered table"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        try:
            lines = downloaded.path.read_text(encoding="utf-8-sig").splitlines()
        except OSError as exc:
            raise SourceAdapterError(
                f"PANGAEA Batagay table is unreadable: {downloaded.path.name}"
            ) from exc
        terminators = [
            index for index, line in enumerate(lines) if line.strip() == "*/"
        ]
        if len(terminators) != 1:
            raise SourceAdapterError("PANGAEA Batagay metadata boundary changed")
        header_index = terminators[0] + 1
        metadata = "\n".join(lines[:header_index])
        coordinate = re.search(
            r"Coverage:\s*LATITUDE:\s*(?P<latitude>-?\d+(?:\.\d+)?)\s*\*\s*"
            r"LONGITUDE:\s*(?P<longitude>-?\d+(?:\.\d+)?)",
            metadata,
        )
        if coordinate is None:
            raise SourceAdapterError("PANGAEA Batagay metadata coordinate is missing")
        latitude = coordinate.group("latitude")
        longitude = coordinate.group("longitude")
        reader = csv.DictReader(lines[header_index:], delimiter="\t")
        missing = sorted(
            set(registry["required_fields"]) - set(reader.fieldnames or [])
        )
        if missing:
            raise SourceAdapterError(
                "PANGAEA Batagay table lacks fields: " + ", ".join(missing)
            )
        rows = 0
        sample_keys: set[str] = set()
        sample_ids: set[str] = set()
        target_counts: Counter[str] = Counter()
        sample_type_counts: Counter[str] = Counter()
        for values in reader:
            line_number = header_index + reader.line_num
            if not any(str(value or "").strip() for value in values.values()):
                continue
            values = {key: str(value or "").strip() for key, value in values.items()}
            sample_id = values["Sample ID"]
            if not sample_id:
                # PANGAEA appends one upper-crust reference row whose values are
                # literature comparators, not sampled Batagay observations.
                continue
            sample_key = "|".join(
                (
                    sample_id,
                    values["Sample comment (soil horizon)"],
                    values["Depth sed [m] (mean)"],
                    values["Lab label"],
                )
            )
            if not sample_id or sample_key in sample_keys:
                raise SourceAdapterError(
                    f"PANGAEA Batagay sample identity is missing or duplicated at row {line_number}"
                )
            target_observations: dict[str, dict[str, Any]] = {}
            for analyte, field_name in registry["target_analytes"].items():
                raw_value = values[field_name]
                if not raw_value:
                    continue
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"PANGAEA Batagay {analyte} is not numeric at row {line_number}"
                    ) from exc
                target_counts[analyte] += 1
                target_observations[analyte] = {
                    "field": field_name,
                    "value": raw_value,
                    "unit": "mg/kg",
                    "measurement_basis": "certified_acid_digest_soil_and_soil_inclusions",
                    "analytical_method": (
                        "Inductively Coupled Plasma Mass Spectrometry, Thermo Fisher Scientific, iCap Q ICP-MS"
                    ),
                    "digestion_or_extraction": (
                        "certified NSAM 499-AES/MS (2015) laboratory method; exact digestion reagent not reported in table"
                    ),
                    "variable_metadata_locator": (
                        f"{downloaded.path.name}#parameter={field_name}"
                    ),
                }
            rows += 1
            sample_keys.add(sample_key)
            sample_ids.add(sample_id)
            sample_type_counts[values["Samp type"] or "not_reported"] += 1
            source_locator = f"{downloaded.path.name}#row={line_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, sample_key, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "Latitude": latitude,
                    "Longitude": longitude,
                    "_source_file": downloaded.path.name,
                    "_source_crs": "EPSG:4326",
                    "_sample_type": values["Samp type"] or "not reported",
                    "_target_observations": target_observations,
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "physical_rows": rows,
            "distinct_sample_keys": len(sample_keys),
            "distinct_sample_ids": len(sample_ids),
            "table_columns": len(reader.fieldnames or []),
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
            "sample_type_counts": dict(sorted(sample_type_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"PANGAEA Batagay reconciliation changed: {observed!r}"
            )


class GeorocAntarcticaIntraplateAdapter(RegistryAdapter):
    """Pinned GEOROC Antarctica member from the Intraplate Volcanics compilation."""

    source_id = "georoc-antarctica-intraplate"

    def _root(self, cache_dir: Path) -> Path:
        standard = self._cache_root(cache_dir)
        legacy = cache_dir / "georoc-antarctica" / self.candidate.version
        return standard if standard.exists() or not legacy.exists() else legacy

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                "GEOROC Antarctica adapter received another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in GEOROC Antarctica demo for fixture tests"
            )
        entry = candidate.registry_entry["download"]
        file_entry = entry["files"][0]
        root = self._root(cache_dir)
        output = root / file_entry["filename"]
        args = _download_args(
            url=file_entry["url"],
            output=output,
            manifest=root / "member.download.json",
            license_id=candidate.license_id,
            expected_sha256=file_entry.get("expected_sha256"),
            max_bytes=int(entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
            required_fields=candidate.registry_entry["required_fields"],
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(
                f"GEOROC Antarctica download failed: {exc}"
            ) from exc
        if output.stat().st_size != int(file_entry["bytes"]):
            raise SourceAdapterError("GEOROC Antarctica member byte count changed")
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=file_entry["file_id"],
                path=output,
                source_url=file_entry["url"],
                bytes=output.stat().st_size,
                cache_status=result["status"],
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
            )
        ]

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "UYO5XO":
            raise SourceAdapterError(
                "GEOROC Antarctica requires its registered Dataverse member"
            )
        downloaded = files[0]
        counts = Counter()
        samples: set[str] = set()
        names: set[str] = set()
        for line_number, values in GeorocArchaeanAdapter._rows(downloaded.path):
            native_id = str(values.get("UNIQUE_ID") or "").strip()
            if not native_id or native_id in samples:
                raise SourceAdapterError(
                    f"GEOROC Antarctica UNIQUE_ID missing or duplicated at row {line_number}"
                )
            samples.add(native_id)
            if values.get("SAMPLE NAME"):
                names.add(values["SAMPLE NAME"])
            observations: dict[str, dict[str, Any]] = {}
            for analyte, field in self.candidate.registry_entry[
                "target_analytes"
            ].items():
                raw_value = str(values.get(field) or "").strip()
                if not raw_value:
                    continue
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"GEOROC Antarctica {field} is not numeric at row {line_number}"
                    ) from exc
                counts[analyte] += 1
                observations[analyte] = {
                    "field": field,
                    "value": raw_value,
                    "unit": "ppm",
                    "measurement_basis": "GEOROC_precompiled_selected_value",
                }
            source_locator = f"{downloaded.path.name}#row={line_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, native_id, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "_target_observations": observations,
                    "_source_file": downloaded.path.name,
                    "_dataset_version": self.candidate.version,
                },
            )
        expected = self.candidate.registry_entry["expected_counts"]
        observed = {
            "source_rows": len(samples),
            "unique_ids": len(samples),
            "distinct_sample_names": len(names),
            "target_observations": sum(counts.values()),
            "target_observations_by_analyte": {
                key: counts[key] for key in ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")
            },
        }
        for key, value in observed.items():
            if value != expected[key]:
                raise SourceAdapterError(
                    f"GEOROC Antarctica reconciliation changed for {key}: {value!r}"
                )


class EidcNingboSoilAdapter(RegistryAdapter):
    """Official EIDC Ningbo topsoil dataset with verified CSV/support members."""

    source_id = "eidc-ningbo-soil"

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("EIDC adapter received another source")
        if mode == "fixture":
            raise SourceAdapterError("EIDC has no adapter-level fixture mode")
        entry = candidate.registry_entry["download"]
        root = self._cache_root(cache_dir)
        archive = root / entry["archive_filename"]
        manifest = root / "archive.download.json"
        args = _download_args(
            url=entry["url"],
            output=archive,
            manifest=manifest,
            license_id=candidate.license_id,
            expected_sha256=None,
            max_bytes=int(entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(f"EIDC archive download failed: {exc}") from exc
        try:
            with zipfile.ZipFile(archive) as bundle:
                members = bundle.infolist()
                if (
                    len(members) > 100
                    or sum(item.file_size for item in members) > 5_000_000
                ):
                    raise SourceAdapterError(
                        "EIDC archive exceeds safe structural limits"
                    )
                names = bundle.namelist()
                if names.count(entry["csv_member"]) != 1:
                    raise SourceAdapterError("EIDC CSV member is missing or duplicated")
                if names.count(entry["support_member"]) != 1:
                    raise SourceAdapterError(
                        "EIDC method attachment is missing or duplicated"
                    )
                payload = bundle.read(entry["csv_member"])
                support_payload = bundle.read(entry["support_member"])
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise SourceAdapterError(f"EIDC archive is invalid: {exc}") from exc
        observed = hashlib.sha256(payload).hexdigest()
        if observed != entry["csv_sha256"] or len(payload) != entry["csv_bytes"]:
            raise SourceAdapterError("EIDC CSV content identity changed")
        if (
            hashlib.sha256(support_payload).hexdigest() != entry["support_sha256"]
            or len(support_payload) != entry["support_bytes"]
        ):
            raise SourceAdapterError("EIDC method attachment identity changed")
        output = root / Path(entry["csv_member"]).name
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, output)
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id="measurements",
                path=output,
                source_url=entry["url"],
                bytes=len(payload),
                cache_status=str(result["status"]),
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
                sha256=observed,
            )
        ]

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "measurements":
            raise SourceAdapterError("EIDC adapter requires its verified CSV")
        downloaded = files[0]
        registry = self.candidate.registry_entry
        counts: Counter[str] = Counter()
        samples: set[str] = set()
        with downloaded.path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = sorted(
                set(registry["required_fields"]) - set(reader.fieldnames or [])
            )
            if missing:
                raise SourceAdapterError("EIDC CSV lacks fields: " + ", ".join(missing))
            for values in reader:
                line_number = reader.line_num
                sample_id = str(values["IGFS no."]).strip()
                if not sample_id or sample_id in samples:
                    raise SourceAdapterError(
                        f"EIDC sample identity invalid at row {line_number}"
                    )
                samples.add(sample_id)
                observations: dict[str, dict[str, Any]] = {}
                for analyte, field_name in registry["target_analytes"].items():
                    raw = str(values.get(field_name) or "").strip()
                    if not raw:
                        continue
                    try:
                        float(raw)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"EIDC {analyte} is not numeric at row {line_number}"
                        ) from exc
                    counts[analyte] += 1
                    technique = "ICP-MS" if field_name.endswith("ICP-MS") else "XRF"
                    observations[analyte] = {
                        "field": field_name,
                        "value": raw,
                        "unit": "mg/kg",
                        "measurement_basis": (
                            "nitric_acid_hydrogen_peroxide_extractable_dry_topsoil"
                            if technique == "ICP-MS"
                            else "xrf_total_dry_topsoil"
                        ),
                        "analytical_method": technique,
                        "digestion_or_extraction": (
                            "69% nitric acid and 30% hydrogen peroxide extraction/digestion"
                            if technique == "ICP-MS"
                            else "XRF preparation; details in publisher supporting document"
                        ),
                        "variable_metadata_locator": "ElementalanalysisofsoilinNingboWatershed.rtf#methods",
                    }
                source_locator = f"{downloaded.path.name}#row={line_number}"
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_id, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "_source_file": downloaded.path.name,
                        "_source_crs": "not declared; reported coordinates only",
                        "_sample_type": "composite topsoil 0-20 cm",
                        "_target_observations": observations,
                        "_dataset_version": self.candidate.version,
                    },
                )
        observed_counts = {
            "physical_rows": len(samples),
            "target_observations": sum(counts.values()),
            "target_value_counts": dict(sorted(counts.items())),
        }
        if observed_counts != registry["expected_counts"]:
            raise SourceAdapterError(
                f"EIDC reconciliation changed: {observed_counts!r}"
            )


class TpdcChinaMountainSoilAdapter(RegistryAdapter):
    """TPDC China mountain-soil workbook with article-scoped analytical methods."""

    source_id = "tpdc-china-mountain-soil"
    _xlsx_namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"

    @staticmethod
    def _column_index(reference: str) -> int:
        return AfsisPhaseIWetChemistryAdapter._column_index(reference)

    @classmethod
    def _xlsx_rows(
        cls,
        path: Path,
        sheet_number: int = 1,
        workbook_label: str = "TPDC",
    ) -> list[tuple[int, list[str]]]:
        if sheet_number < 1:
            raise SourceAdapterError("worksheet number must be positive")
        sheet_member = f"xl/worksheets/sheet{sheet_number}.xml"
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                if (
                    len(members) > 100
                    or sum(item.file_size for item in members) > 10_000_000
                ):
                    raise SourceAdapterError(
                        "TPDC workbook exceeds safe structural limits"
                    )
                if sheet_member not in archive.namelist():
                    raise SourceAdapterError(
                        f"{workbook_label} workbook lacks {sheet_member}"
                    )
                namespace = f"{{{cls._xlsx_namespace}}}"
                shared_strings: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared_strings = [
                        "".join(node.text or "" for node in item.iter(f"{namespace}t"))
                        for item in root.findall(f"{namespace}si")
                    ]
                sheet = ET.fromstring(archive.read(sheet_member))
        except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
            raise SourceAdapterError(
                f"{workbook_label} workbook is unreadable: {path.name}"
            ) from exc
        rows: list[tuple[int, list[str]]] = []
        for row in sheet.findall(f".//{namespace}sheetData/{namespace}row"):
            indexed: dict[int, str] = {}
            for cell in row.findall(f"{namespace}c"):
                index = cls._column_index(str(cell.get("r") or ""))
                value_node = cell.find(f"{namespace}v")
                value = "" if value_node is None else str(value_node.text or "")
                if cell.get("t") == "s" and value:
                    try:
                        value = shared_strings[int(value)]
                    except (ValueError, IndexError) as exc:
                        raise SourceAdapterError(
                            f"{workbook_label} workbook shared-string index changed"
                        ) from exc
                elif cell.get("t") == "inlineStr":
                    value = "".join(
                        node.text or "" for node in cell.iter(f"{namespace}t")
                    )
                indexed[index] = value.strip()
            width = max(indexed, default=-1) + 1
            rows.append(
                (
                    int(row.get("r") or len(rows) + 1),
                    [indexed.get(i, "") for i in range(width)],
                )
            )
        return rows

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("TPDC adapter received another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in TPDC demo for fixture tests")
        standard = self._cache_root(cache_dir)
        fallback = SKILL_DIR.parents[1] / ".cache" / "tpdc-profile" / "source"
        registered_files = candidate.registry_entry["download"]["files"]

        def complete(root: Path) -> bool:
            return all(
                (root / entry["filename"]).is_file() for entry in registered_files
            )

        if not complete(standard) and mode == "online":
            try:
                import acquire_tpdc_bundle

                acquire_tpdc_bundle.run(cache_dir, "online", 180.0)
            except (OSError, RuntimeError, ValueError) as exc:
                raise SourceAdapterError(
                    f"TPDC online pre-acquisition failed closed: {exc}"
                ) from exc
        root = standard if complete(standard) else fallback
        retrieved_at = None
        acquisition_path = root / "tpdc-acquisition.json"
        if acquisition_path.is_file():
            try:
                acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
                retrieved_at = (
                    acquisition.get("retrieved_at") or acquisition.get("accessed_at")
                    if isinstance(acquisition, Mapping)
                    else None
                )
            except (OSError, UnicodeError, json.JSONDecodeError):
                retrieved_at = None
        results: list[DownloadedFile] = []
        missing = []
        for entry in registered_files:
            path = root / entry["filename"]
            if not path.exists():
                missing.append(entry["filename"])
                continue
            if path.stat().st_size != int(entry["bytes"]):
                raise SourceAdapterError(
                    f"TPDC cached file byte count changed: {path.name}"
                )
            if downloader.sha256_file(path) != entry["expected_sha256"]:
                raise SourceAdapterError(
                    f"TPDC cached file SHA-256 changed: {path.name}"
                )
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=entry["file_id"],
                    path=path,
                    source_url=entry["url"],
                    bytes=path.stat().st_size,
                    cache_status="verified_cache",
                    retrieved_at=(
                        str(retrieved_at) if isinstance(retrieved_at, str) else None
                    ),
                )
            )
        if missing:
            raise SourceAdapterError(
                "TPDC verified POST bundle is unavailable; missing registered members: "
                + ", ".join(missing)
            )
        return results

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if "soil-dataset" not in by_id:
            raise SourceAdapterError("TPDC main soil workbook is missing")
        downloaded = by_id["soil-dataset"]
        rows = self._xlsx_rows(downloaded.path)
        headers = rows[0][1] if rows else []
        required = set(self.candidate.registry_entry["required_fields"])
        if not required.issubset(headers):
            raise SourceAdapterError(
                f"TPDC workbook schema changed; missing={sorted(required - set(headers))}"
            )
        samples: set[str] = set()
        profiles: set[str] = set()
        sites: set[str] = set()
        mountains: set[str] = set()
        horizons = Counter()
        counts = Counter()
        for row_number, row in rows[1:]:
            padded = row + [""] * max(0, len(headers) - len(row))
            values = dict(zip(headers, padded, strict=False))
            sample = values["Sam.No"].strip()
            horizon = values["Horizons"].strip()
            if not sample or horizon not in {"O", "A", "C"}:
                raise SourceAdapterError(
                    f"TPDC sample identity/horizon changed at row {row_number}"
                )
            key = f"{sample}|{horizon}"
            if key in samples:
                raise SourceAdapterError(
                    f"TPDC sample+horizon duplicated at row {row_number}"
                )
            samples.add(key)
            profiles.add(sample)
            sites.add(values["site"])
            mountains.add(values["Mountain"])
            horizons[horizon] += 1
            observations: dict[str, dict[str, Any]] = {}
            for analyte, field in self.candidate.registry_entry[
                "target_analytes"
            ].items():
                raw_value = values[field].strip()
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"TPDC {field} is not numeric at row {row_number}"
                    ) from exc
                counts[analyte] += 1
                method = (
                    "ICP-AES (PerkinElmer Optima 2000)"
                    if analyte == "Zn"
                    else "ICP-MS (Agilent 7700x)"
                )
                observations[analyte] = {
                    "field": field,
                    "value": raw_value,
                    "unit": "mg/kg",
                    "measurement_basis": "acid_digested_air_dry_soil_<2mm",
                    "analytical_method": method,
                    "digestion_or_extraction": "article-reported acid digestion",
                    "variable_metadata_locator": "doi:10.5194/essd-17-4779-2025",
                }
            source_locator = f"{downloaded.path.name}#sheet1-row={row_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, key, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "_target_observations": observations,
                    "_source_file": downloaded.path.name,
                    "_source_crs": "",
                    "_medium": "soil",
                    "_sample_type": horizon,
                    "_grain_fraction": "<2 mm",
                    "_dataset_version": self.candidate.version,
                },
            )
        expected = self.candidate.registry_entry["expected_counts"]
        observed = {
            "physical_rows": len(samples),
            "distinct_profiles": len(profiles),
            "distinct_sites": len(sites),
            "distinct_mountains": len(mountains),
            "horizon_counts": dict(sorted(horizons.items())),
            "target_observations": sum(counts.values()),
            "target_value_counts": dict(sorted(counts.items())),
        }
        if observed != expected:
            raise SourceAdapterError(
                f"TPDC reconciliation changed: {observed!r} != {expected!r}"
            )


class MendeleyGuangdongFujianGroundwaterAdapter(_PinnedSingleFileAdapter):
    """Pinned Mendeley workbook of reported Guangdong-Fujian well water."""

    source_id = "mendeley-guangdong-fujian-groundwater"

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "table-s1":
            raise SourceAdapterError(
                "Mendeley groundwater adapter requires the verified Table S1 workbook"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        rows = TpdcChinaMountainSoilAdapter._xlsx_rows(
            downloaded.path, workbook_label="Mendeley groundwater"
        )
        if len(rows) < 3:
            raise SourceAdapterError("Mendeley groundwater workbook is empty")
        headers = rows[0][1]
        units = rows[1][1]
        expected_headers = registry["header_fields"]
        if headers != expected_headers:
            raise SourceAdapterError("Mendeley groundwater workbook schema changed")
        if len(units) != len(headers) or any(
            units[headers.index(field)] != "μg/l"
            for field in registry["target_analytes"].values()
        ):
            raise SourceAdapterError(
                "Mendeley groundwater target-analyte unit row changed"
            )

        sample_type_raw = ""
        row_provenance = ""
        samples: set[str] = set()
        coordinates: set[tuple[str, str]] = set()
        provenance_counts: Counter[str] = Counter()
        counts: Counter[str] = Counter()
        data_rows = 0
        for row_number, row in rows[2:]:
            padded = row + [""] * max(0, len(headers) - len(row))
            sample_type_raw = padded[0].strip() or sample_type_raw
            row_provenance = padded[1].strip() or row_provenance
            site = padded[2].strip()
            if not site:
                if any(value.strip() for value in padded[2:]):
                    raise SourceAdapterError(
                        f"Mendeley groundwater row lacks Site at row {row_number}"
                    )
                continue
            if not re.fullmatch(r"W(?:[1-9]|[1-9][0-9]|1[01][0-9]|12[0-4])", site):
                raise SourceAdapterError(
                    f"Mendeley groundwater Site changed at row {row_number}"
                )
            if site in samples:
                raise SourceAdapterError(
                    f"Mendeley groundwater Site duplicated at row {row_number}"
                )
            if sample_type_raw != "well water" or row_provenance not in {
                "This study",
                "Yao B \net al.2024",
            }:
                raise SourceAdapterError(
                    f"Mendeley groundwater row provenance changed at row {row_number}"
                )
            values = {
                header: padded[index] for index, header in enumerate(headers) if header
            }
            longitude = values["Longitude"].strip()
            latitude = values["Latitude"].strip()
            try:
                longitude_value = float(longitude)
                latitude_value = float(latitude)
            except ValueError as exc:
                raise SourceAdapterError(
                    f"Mendeley groundwater coordinate is not numeric at row {row_number}"
                ) from exc
            if (
                not math.isfinite(longitude_value)
                or not math.isfinite(latitude_value)
                or not -180 <= longitude_value <= 180
                or not -90 <= latitude_value <= 90
            ):
                raise SourceAdapterError(
                    f"Mendeley groundwater coordinate is invalid at row {row_number}"
                )

            observations: dict[str, dict[str, Any]] = {}
            for analyte, field_name in registry["target_analytes"].items():
                raw_value = values[field_name].strip()
                if not raw_value or raw_value == "-":
                    continue
                try:
                    numeric = float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"Mendeley groundwater {analyte} is not numeric at row {row_number}"
                    ) from exc
                if not math.isfinite(numeric) or numeric < 0:
                    raise SourceAdapterError(
                        f"Mendeley groundwater {analyte} is invalid at row {row_number}"
                    )
                counts[analyte] += 1
                observations[analyte] = {
                    "field": field_name,
                    "value": raw_value,
                    "unit": "ug/L",
                    "measurement_basis": (
                        "groundwater_reported_mass_per_volume_fraction_unspecified"
                    ),
                    "variable_metadata_locator": "Table S1.xlsx#sheet1-row=2",
                }
            samples.add(site)
            coordinates.add((latitude, longitude))
            provenance_counts[row_provenance] += 1
            data_rows += 1
            source_locator = f"{downloaded.path.name}#sheet1-row={row_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, site, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "_sample_type_raw": sample_type_raw,
                    "_row_provenance": row_provenance,
                    "_reported_latitude": latitude,
                    "_reported_longitude": longitude,
                    "_source_crs": "",
                    "_source_file": downloaded.path.name,
                    "_target_observations": observations,
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "physical_rows": data_rows,
            "distinct_sites": len(samples),
            "distinct_reported_coordinates": len(coordinates),
            "row_provenance_counts": dict(sorted(provenance_counts.items())),
            "target_observations": sum(counts.values()),
            "target_value_counts": dict(sorted(counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"Mendeley groundwater reconciliation changed: {observed!r}"
            )


class EuropePmcPearlRiverDissolvedMetalsAdapter(RegistryAdapter):
    """Pinned workbook member from Europe PMC's generated supplement bundle."""

    source_id = "europe-pmc-pearl-river-dissolved-metals"

    _FOOTER_NOTES = frozenset(
        {
            "NPR, Nanpanjiang River; HSR, Hongshuihe River; QJR, Qianjiang River; XUJ, Xunjiang River; XJR, Xijiang River.",
            "T-NPR, T-BPR, T-HSR, T-QJR, T-XUJ and T-XJR represents the tributaries of Nanpanjiang River, Beipanjiang River, Hongshuihe River, Qianjiang River, Xunjiang River and Xijiang River.",
        }
    )

    @staticmethod
    def _verified_member_payload(
        archive_path: Path, download_entry: Mapping[str, Any]
    ) -> bytes:
        member_entry = download_entry["files"][0]
        target = str(member_entry["archive_member"])
        try:
            with zipfile.ZipFile(archive_path) as archive:
                members = archive.infolist()
                names = [item.filename for item in members]
                if (
                    len(members) > int(download_entry["max_members"])
                    or sum(item.file_size for item in members)
                    > int(download_entry["max_extracted_bytes"])
                    or len(names) != len(set(names))
                    or any(
                        item.is_dir()
                        or PurePosixPath(item.filename).is_absolute()
                        or ".." in PurePosixPath(item.filename).parts
                        or "\\" in item.filename
                        for item in members
                    )
                ):
                    raise SourceAdapterError(
                        "Europe PMC supplement archive violates structural limits"
                    )
                if names.count(target) != 1:
                    raise SourceAdapterError(
                        "Europe PMC supplement archive target member changed"
                    )
                payload = archive.read(target)
        except (OSError, zipfile.BadZipFile, KeyError, RuntimeError) as exc:
            raise SourceAdapterError(
                "Europe PMC supplement archive is unreadable"
            ) from exc
        if (
            len(payload) != int(member_entry["bytes"])
            or hashlib.sha256(payload).hexdigest() != member_entry["expected_sha256"]
        ):
            raise SourceAdapterError("Europe PMC workbook member changed")
        return payload

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("Europe PMC adapter received another source")
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in Europe PMC demo for fixture tests"
            )
        root = self._cache_root(cache_dir)
        root.mkdir(parents=True, exist_ok=True)
        download_entry = candidate.registry_entry["download"]
        member_entry = download_entry["files"][0]
        source_url = str(download_entry["url"])
        output = root / str(member_entry["filename"])
        manifest_path = root / "dataset.download.json"
        result: dict[str, Any] = {}
        try:
            if output.is_file() and manifest_path.is_file():
                result = downloader.existing_verified_cache(
                    output,
                    manifest_path,
                    source_url,
                    str(member_entry["expected_sha256"]),
                    candidate.version,
                )
            elif mode == "cached":
                raise downloader.DownloadError(
                    "offline Europe PMC cache is incomplete",
                    status="network_unavailable",
                )
        except downloader.DownloadError:
            if mode == "cached":
                raise SourceAdapterError(
                    "Europe PMC verified offline cache is unavailable"
                ) from None
            result = {}

        archive_path: Path | None = None
        temporary_output: Path | None = None
        if not result:
            try:
                with tempfile.NamedTemporaryFile(
                    "wb",
                    prefix=".europe-pmc-supplements.",
                    suffix=".zip",
                    dir=root,
                    delete=False,
                ) as handle:
                    archive_path = Path(handle.name)
                container = downloader.download_with_retries(
                    source_url,
                    archive_path,
                    30.0,
                    int(download_entry["max_bytes"]),
                    None,
                    2,
                )
                content_type = str(container.get("content_type") or "")
                if content_type and content_type not in set(
                    download_entry["accepted_content_types"]
                ):
                    raise SourceAdapterError(
                        f"Europe PMC returned unexpected content type: {content_type}"
                    )
                payload = self._verified_member_payload(archive_path, download_entry)
                with tempfile.NamedTemporaryFile(
                    "wb",
                    prefix=f".{output.name}.",
                    suffix=".part",
                    dir=root,
                    delete=False,
                ) as handle:
                    temporary_output = Path(handle.name)
                    handle.write(payload)
                os.replace(temporary_output, output)
                temporary_output = None
                result = {
                    **container,
                    "manifest_version": "geochemical-download-v1",
                    "license": candidate.license_id,
                    "output_filename": output.name,
                    "dataset_doi": candidate.dataset_doi,
                    "dataset_version": candidate.version,
                    "container_sha256": container["sha256"],
                    "container_bytes": container["bytes"],
                    "archive_member": member_entry["archive_member"],
                    "sha256": member_entry["expected_sha256"],
                    "sha256_basis": "publisher_supplement_member_pin",
                    "bytes": len(payload),
                }
                downloader.atomic_json(manifest_path, result)
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"Europe PMC supplement download failed: {exc}"
                ) from exc
            finally:
                if archive_path is not None:
                    archive_path.unlink(missing_ok=True)
                if temporary_output is not None:
                    temporary_output.unlink(missing_ok=True)
        if output.stat().st_size != int(member_entry["bytes"]):
            raise SourceAdapterError("Europe PMC workbook byte count changed")
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=str(member_entry["file_id"]),
                path=output,
                source_url=source_url,
                bytes=output.stat().st_size,
                cache_status=str(result["status"]),
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
            )
        ]

    @staticmethod
    def _reported_coordinates(value: str, row_number: int) -> tuple[str, str]:
        match = re.fullmatch(
            r"N[：:]\s*(\d{1,2})[º°](\d{1,2}(?:\.\d+)?)'\s+"
            r"E[：:]\s*(\d{1,3})[º°](\d{1,2}(?:\.\d+)?)'",
            value.strip(),
        )
        if match is None:
            raise SourceAdapterError(
                f"Pearl River reported coordinate changed at row {row_number}"
            )
        latitude_degrees, latitude_minutes, longitude_degrees, longitude_minutes = (
            float(item) for item in match.groups()
        )
        latitude = latitude_degrees + latitude_minutes / 60
        longitude = longitude_degrees + longitude_minutes / 60
        if (
            latitude_minutes >= 60
            or longitude_minutes >= 60
            or latitude > 90
            or longitude > 180
        ):
            raise SourceAdapterError(
                f"Pearl River reported coordinate is invalid at row {row_number}"
            )
        return (
            format(latitude, ".12g"),
            format(longitude, ".12g"),
        )

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "raw-data-workbook":
            raise SourceAdapterError(
                "Europe PMC Pearl River adapter requires the verified workbook"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        rows = TpdcChinaMountainSoilAdapter._xlsx_rows(
            downloaded.path, workbook_label="Pearl River"
        )
        if len(rows) < 4 or rows[0][1] != registry["header_fields"]:
            raise SourceAdapterError("Pearl River workbook schema changed")
        headers = rows[0][1]
        units = rows[1][1]
        if len(units) != len(headers) or any(
            units[headers.index(field)] != "μg L-1"
            for field in registry["target_analytes"].values()
        ):
            raise SourceAdapterError("Pearl River target-analyte unit row changed")

        season = ""
        samples: set[str] = set()
        sites: set[str] = set()
        dates: set[str] = set()
        season_counts: Counter[str] = Counter()
        counts: Counter[str] = Counter()
        for row_number, row in rows[2:]:
            padded = row + [""] * max(0, len(headers) - len(row))
            first = padded[0].strip()
            if first in {"High flow season", "Low flow season"}:
                season = first
                continue
            if not first.isdigit():
                if first in self._FOOTER_NOTES:
                    continue
                if any(value.strip() for value in padded):
                    raise SourceAdapterError(
                        f"Pearl River workbook has an unexpected row at {row_number}"
                    )
                continue
            if season not in {"High flow season", "Low flow season"}:
                raise SourceAdapterError(
                    f"Pearl River season is missing at row {row_number}"
                )
            values = dict(zip(headers, padded, strict=False))
            site = values["Site number"].strip()
            if not site.isdigit() or not 1 <= int(site) <= 81:
                raise SourceAdapterError(
                    f"Pearl River site identity changed at row {row_number}"
                )
            sampled_raw = values["Date      (m-d-y)"].strip()
            try:
                sampled_at = (
                    datetime.strptime(sampled_raw, "%m/%d/%y").date().isoformat()
                )
            except ValueError as exc:
                raise SourceAdapterError(
                    f"Pearl River sampling date changed at row {row_number}"
                ) from exc
            latitude, longitude = self._reported_coordinates(
                values["Sample location"], row_number
            )
            sample_key = f"{site}|{season}"
            if sample_key in samples:
                raise SourceAdapterError(
                    f"Pearl River site-season duplicated at row {row_number}"
                )
            observations: dict[str, dict[str, Any]] = {}
            for analyte, field_name in registry["target_analytes"].items():
                raw_value = values[field_name].strip()
                try:
                    numeric = float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"Pearl River {analyte} is not numeric at row {row_number}"
                    ) from exc
                if not math.isfinite(numeric) or numeric < 0:
                    raise SourceAdapterError(
                        f"Pearl River {analyte} is invalid at row {row_number}"
                    )
                counts[analyte] += 1
                observations[analyte] = {
                    "field": field_name,
                    "value": raw_value,
                    "unit": "ug/L",
                    "measurement_basis": "dissolved_filtered_river_water_mass_per_volume",
                    "analytical_method": "ICP-MS (PerkinElmer Elan DRC-e)",
                    "digestion_or_extraction": (
                        "0.22 um filtration; HNO3 acidification to pH < 2"
                    ),
                    "variable_metadata_locator": "doi:10.7717/peerj.6578#materials-and-methods",
                }
            samples.add(sample_key)
            sites.add(site)
            dates.add(sampled_at)
            season_counts[season] += 1
            source_locator = f"{downloaded.path.name}#sheet1-row={row_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, f"{site}|{sampled_at}", source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "_season": season,
                    "_sampled_at": sampled_at,
                    "_reported_coordinate_text": values["Sample location"],
                    "_reported_latitude": latitude,
                    "_reported_longitude": longitude,
                    "_source_crs": "",
                    "_sample_type_raw": "0.22 um filtered river water",
                    "_source_file": downloaded.path.name,
                    "_target_observations": observations,
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "physical_rows": len(samples),
            "distinct_sites": len(sites),
            "distinct_sampling_dates": len(dates),
            "season_counts": dict(sorted(season_counts.items())),
            "target_observations": sum(counts.values()),
            "target_value_counts": dict(sorted(counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"Pearl River reconciliation changed: {observed!r}"
            )


class EarthchemDehailonggangRockAdapter(RegistryAdapter):
    """EarthChem Library whole-rock workbook acquired by its fixed public form."""

    source_id = "earthchem-dehailonggang-rock"

    @staticmethod
    def _verify_archive(path: Path, download_entry: Mapping[str, Any]) -> None:
        if path.stat().st_size != int(download_entry["archive_bytes"]):
            raise SourceAdapterError("EarthChem archive byte count changed")
        if downloader.sha256_file(path) != download_entry["archive_sha256"]:
            raise SourceAdapterError("EarthChem archive SHA-256 changed")
        expected = {
            item["filename"]: item for item in download_entry["archive_members"]
        }
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                actual_names = [item.filename for item in members]
                if (
                    len(actual_names) != len(set(actual_names))
                    or set(actual_names) != set(expected)
                    or any(
                        item.is_dir()
                        or PurePosixPath(item.filename).is_absolute()
                        or ".." in PurePosixPath(item.filename).parts
                        or "\\" in item.filename
                        for item in members
                    )
                ):
                    raise SourceAdapterError(
                        "EarthChem archive member set or paths changed"
                    )
                for member in members:
                    registered = expected[member.filename]
                    payload = archive.read(member)
                    if (
                        len(payload) != int(registered["bytes"])
                        or hashlib.sha256(payload).hexdigest() != registered["sha256"]
                    ):
                        raise SourceAdapterError(
                            f"EarthChem archive member changed: {member.filename}"
                        )
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise SourceAdapterError("EarthChem archive is unreadable") from exc

    @classmethod
    def _extract_registered_member(
        cls,
        archive_path: Path,
        output: Path,
        member_entry: Mapping[str, Any],
    ) -> None:
        temporary: Path | None = None
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                payload = archive.read(str(member_entry["filename"]))
            if (
                len(payload) != int(member_entry["bytes"])
                or hashlib.sha256(payload).hexdigest() != member_entry["sha256"]
            ):
                raise SourceAdapterError("EarthChem selected workbook changed")
            with tempfile.NamedTemporaryFile(
                "wb",
                prefix=f".{output.name}.",
                suffix=".part",
                dir=output.parent,
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
            os.replace(temporary, output)
            temporary = None
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise SourceAdapterError(
                "EarthChem selected workbook could not be extracted"
            ) from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _download_form_archive(
        output: Path,
        download_entry: Mapping[str, Any],
    ) -> dict[str, Any]:
        endpoint = str(download_entry["endpoint"])
        downloader.validate_public_https_url(endpoint)
        form = urllib.parse.urlencode(download_entry["form_fields"]).encode("ascii")
        request = urllib.request.Request(
            endpoint,
            data=form,
            headers={
                "User-Agent": downloader.USER_AGENT,
                "Accept": "application/zip, application/octet-stream",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            opener = urllib.request.build_opener(_RejectRedirects())
            with opener.open(request, timeout=30.0) as response:
                if response.geturl() != endpoint:
                    raise SourceAdapterError(
                        "EarthChem form download redirected away from the pinned endpoint"
                    )
                content_type = response.headers.get_content_type().casefold()
                if content_type not in set(download_entry["accepted_content_types"]):
                    raise SourceAdapterError(
                        f"EarthChem returned unexpected content type: {content_type}"
                    )
                downloader.validate_response_metadata(
                    content_type,
                    response.headers.get("Content-Length"),
                    int(download_entry["max_bytes"]),
                )
                with tempfile.NamedTemporaryFile(
                    "wb",
                    prefix=f".{output.name}.",
                    suffix=".part",
                    dir=output.parent,
                    delete=False,
                ) as handle:
                    temporary = Path(handle.name)
                    total, observed = downloader.copy_response_bounded(
                        response, handle, int(download_entry["max_bytes"])
                    )
                if (
                    total != int(download_entry["archive_bytes"])
                    or observed != download_entry["archive_sha256"]
                ):
                    raise SourceAdapterError(
                        "EarthChem form response does not match the pinned archive"
                    )
                os.replace(temporary, output)
                temporary = None
                return {
                    "status": "downloaded",
                    "source_url": endpoint,
                    "resolved_url": endpoint,
                    "content_type": content_type,
                    "bytes": total,
                    "sha256": observed,
                    "sha256_basis": "expected",
                    "accessed_at": downloader.utc_now(),
                    "http_status": getattr(response, "status", 200),
                    "content_disposition": response.headers.get("Content-Disposition"),
                    "request_method": "POST",
                    "form_field_names": sorted(download_entry["form_fields"]),
                }
        except (
            downloader.DownloadError,
            SourceAdapterError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            raise SourceAdapterError("EarthChem form download failed closed") from exc
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
            raise SourceAdapterError("EarthChem adapter received another source")
        if mode == "fixture":
            raise SourceAdapterError(
                "use the checked-in EarthChem demo for fixture tests"
            )
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        endpoint = str(download_entry["endpoint"])
        archive_path = root / str(download_entry["archive_filename"])
        manifest_path = root / "archive.download.json"
        result: dict[str, Any]
        try:
            result = downloader.existing_verified_cache(
                archive_path,
                manifest_path,
                endpoint,
                str(download_entry["archive_sha256"]),
                candidate.version,
            )
            self._verify_archive(archive_path, download_entry)
        except (downloader.DownloadError, SourceAdapterError, OSError):
            if mode == "cached":
                raise SourceAdapterError(
                    "EarthChem cached mode requires the verified POST archive"
                )
            result = self._download_form_archive(archive_path, download_entry)
            self._verify_archive(archive_path, download_entry)
            downloader.atomic_json(
                manifest_path,
                {
                    **result,
                    "manifest_version": "geochemical-download-v1",
                    "license": candidate.license_id,
                    "output_filename": archive_path.name,
                    "offline": False,
                    "dataset_doi": candidate.dataset_doi,
                    "dataset_version": candidate.version,
                },
            )
        member_entry = next(
            item
            for item in download_entry["archive_members"]
            if item["file_id"] == "bulk-rock-workbook"
        )
        workbook_path = root / str(member_entry["filename"])
        if (
            not workbook_path.is_file()
            or workbook_path.stat().st_size != int(member_entry["bytes"])
            or downloader.sha256_file(workbook_path) != member_entry["sha256"]
        ):
            self._extract_registered_member(archive_path, workbook_path, member_entry)
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id="bulk-rock-workbook",
                path=workbook_path,
                source_url=endpoint,
                bytes=workbook_path.stat().st_size,
                cache_status=str(result["status"]),
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
            )
        ]

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "bulk-rock-workbook":
            raise SourceAdapterError(
                "EarthChem adapter requires the registered bulk-rock workbook"
            )
        downloaded = files[0]
        label = "EarthChem Dehailonggang"
        sample_rows = TpdcChinaMountainSoilAdapter._xlsx_rows(downloaded.path, 2, label)
        data_rows = TpdcChinaMountainSoilAdapter._xlsx_rows(downloaded.path, 3, label)
        method_rows = TpdcChinaMountainSoilAdapter._xlsx_rows(downloaded.path, 4, label)
        if len(sample_rows) < 8 or len(data_rows) < 6 or len(method_rows) < 7:
            raise SourceAdapterError("EarthChem workbook structure changed")

        sample_headers = sample_rows[4][1]
        required_sample = {
            "SAMPLE NAME",
            "LATITUDE",
            "LONGITUDE",
            "ELEVATION",
            "LOCATION KEYWORDS",
            "LITHOLOGY",
        }
        if not required_sample.issubset(sample_headers):
            raise SourceAdapterError(
                "EarthChem sample worksheet schema changed; missing="
                + repr(sorted(required_sample - set(sample_headers)))
            )
        samples: dict[str, dict[str, str]] = {}
        for row_number, row in sample_rows[7:]:
            padded = row + [""] * max(0, len(sample_headers) - len(row))
            values = dict(zip(sample_headers, padded, strict=False))
            sample_id = values["SAMPLE NAME"].strip()
            if not sample_id or sample_id in samples:
                raise SourceAdapterError(
                    f"EarthChem sample identity changed at sheet2 row {row_number}"
                )
            samples[sample_id] = values

        methods: dict[str, dict[str, str]] = {}
        method_headers = method_rows[4][1]
        for row_number, row in method_rows[6:]:
            padded = row + [""] * max(0, len(method_headers) - len(row))
            values = dict(zip(method_headers, padded, strict=False))
            parameter = values.get("PARAMETER", "").strip()
            if parameter:
                methods[parameter] = {
                    **values,
                    "_row_number": str(row_number),
                }

        parameters = data_rows[1][1]
        method_codes = data_rows[2][1]
        units = data_rows[3][1]
        index_by_parameter = {
            parameter.strip(): index
            for index, parameter in enumerate(parameters)
            if parameter.strip()
        }
        target_analytes = self.candidate.registry_entry["target_analytes"]
        missing_parameters = set(target_analytes.values()) - set(index_by_parameter)
        if missing_parameters:
            raise SourceAdapterError(
                "EarthChem analytical worksheet schema changed; missing="
                + repr(sorted(missing_parameters))
            )

        counts = Counter()
        coordinate_pairs: set[tuple[str, str]] = set()
        emitted_samples: set[str] = set()
        for row_number, row in data_rows[6:]:
            sample_id = row[0].strip() if row else ""
            if (
                not sample_id
                or sample_id not in samples
                or sample_id in emitted_samples
            ):
                raise SourceAdapterError(
                    f"EarthChem analytical sample changed at sheet3 row {row_number}"
                )
            emitted_samples.add(sample_id)
            sample = samples[sample_id]
            coordinate_pairs.add((sample["LATITUDE"], sample["LONGITUDE"]))
            observations: dict[str, dict[str, Any]] = {}
            for analyte, parameter in target_analytes.items():
                index = index_by_parameter[parameter]
                raw_value = row[index].strip() if index < len(row) else ""
                try:
                    float(raw_value)
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"EarthChem {parameter} is not numeric at sheet3 row {row_number}"
                    ) from exc
                method = methods.get(parameter)
                if (
                    not method
                    or method_codes[index].strip()
                    != method.get("METHOD CODE", "").strip()
                ):
                    raise SourceAdapterError(
                        f"EarthChem method linkage changed for {parameter}"
                    )
                technique = method.get("TECHNIQUE", "").strip()
                instrument = method.get("INSTRUMENT", "").strip()
                laboratory = method.get("LABORATORY", "").strip()
                if not technique or not instrument or not laboratory:
                    raise SourceAdapterError(
                        f"EarthChem method evidence is incomplete for {parameter}"
                    )
                counts[analyte] += 1
                observations[analyte] = {
                    "field": parameter,
                    "value": raw_value,
                    "unit": units[index].strip(),
                    "measurement_basis": "whole_rock_bulk_trace_element",
                    "analytical_method": technique,
                    "instrument": instrument,
                    "laboratory": laboratory,
                    "digestion_or_extraction": "",
                    "variable_metadata_locator": (
                        f"{downloaded.path.name}#sheet4-row={method['_row_number']}"
                    ),
                }
            source_locator = f"{downloaded.path.name}#sheet3-row={row_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, sample_id, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **sample,
                    "_target_observations": observations,
                    "_source_file": downloaded.path.name,
                    "_source_crs": "",
                    "_medium": "rock",
                    "_sample_type": "whole rock",
                    "_grain_fraction": "",
                    "_dataset_version": self.candidate.version,
                    "_official_source_url": self.candidate.landing_page,
                },
            )
        observed = {
            "physical_rows": len(emitted_samples),
            "distinct_coordinate_pairs": len(coordinate_pairs),
            "target_observations": sum(counts.values()),
            "target_value_counts": dict(sorted(counts.items())),
        }
        expected = self.candidate.registry_entry["expected_counts"]
        if observed != expected:
            raise SourceAdapterError(
                f"EarthChem reconciliation changed: {observed!r} != {expected!r}"
            )


class PangaeaBrasolNeBrazilSoilAdapter(RegistryAdapter):
    """Pinned BraSol workbook with WGS84/GPS and method-specific evidence."""

    source_id = "pangaea-brasol-ne-brazil-soil"

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("BraSol adapter received another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in BraSol demo for fixture tests")
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
                max_bytes=int(download_entry["max_bytes"]),
                dataset_doi=candidate.dataset_doi,
                dataset_version=candidate.version,
                offline=mode == "cached",
                required_fields=(),
            )
            try:
                result = downloader.run(args)
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(f"BraSol download failed: {exc}") from exc
            content_type = result.get("content_type")
            if content_type and content_type not in set(
                download_entry["accepted_content_types"]
            ):
                raise SourceAdapterError(
                    f"BraSol returned unexpected content type: {content_type}"
                )
            if output.stat().st_size != int(file_entry["bytes"]):
                raise SourceAdapterError(
                    f"BraSol file byte count changed: {output.name}"
                )
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=output,
                    source_url=file_entry["url"],
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at")
                    or result.get("cache_verified_at"),
                )
            )
        return results

    @staticmethod
    def _method_name(code: str) -> str:
        return {
            "ICPMS": "ICP-MS (ELAN 9000) after full HF-HNO3 digestion",
            "ICPO": "ICP-OES (PerkinElmer Optima 4300 Dual View) after digestion",
            "GFD": "WD-XRF (Bruker S8 Tiger) on glass fusion disc",
            "PPP": "WD-XRF (Bruker S8 Tiger) on pressed powder pellet",
        }[code]

    @staticmethod
    def _digestion(code: str, layer: str) -> str:
        if code == "ICPMS":
            return "full digestion with HF and HNO3 in Walner equipment"
        if code == "ICPO":
            return (
                "dry ashing of milled organic sample"
                if layer == "ORG"
                else "digestion with 7N HNO3"
            )
        if code == "GFD":
            return "glass fusion disc preparation"
        return "pressed powder pellet; no wet digestion"

    @staticmethod
    def _dms_decimal(raw: str, *, axis: str) -> float | None:
        """Parse a publisher DMS coordinate for independent decimal-field QC.

        The frozen workbook contains both DMS and decimal WGS84 fields.  One
        longitude uses a double quote in the degree position, so that known
        punctuation variant is accepted.  Impossible minute/second values are
        rejected; they are evidence conflicts, not values to repair silently.
        """

        match = re.fullmatch(
            r"\s*(\d{1,3})\s*[°\"]\s*(\d{1,2})\s*['′]\s*"
            r"(\d+(?:\.\d+)?)\s*(?:[\"″]|'')?\s*([NSEW])\s*",
            raw,
            flags=re.IGNORECASE,
        )
        if match is None:
            return None
        degrees, minutes, seconds = (
            float(match.group(1)),
            float(match.group(2)),
            float(match.group(3)),
        )
        hemisphere = match.group(4).upper()
        if minutes >= 60 or seconds >= 60:
            return None
        if axis == "latitude":
            if hemisphere not in {"N", "S"} or degrees > 90:
                return None
        elif axis == "longitude":
            if hemisphere not in {"E", "W"} or degrees > 180:
                return None
        else:  # defensive programming for internal callers
            raise SourceAdapterError(f"unknown DMS axis: {axis}")
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        return -decimal if hemisphere in {"S", "W"} else decimal

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if set(by_id) != {"soil-workbook", "method-metadata"}:
            raise SourceAdapterError(
                "BraSol adapter requires the registered workbook and method metadata"
            )
        workbook = by_id["soil-workbook"]
        metadata = by_id["method-metadata"]
        try:
            metadata_text = metadata.path.read_text(encoding="cp1252")
        except (OSError, UnicodeError) as exc:
            raise SourceAdapterError("BraSol method metadata is unreadable") from exc
        for phrase in (
            "Coordinates (WGS84)",
            "PPP = Pressed powder pellet",
            "GFD = Glas fusion disc",
            "ICPO = Inductively-coupled plasma optical-emission spectrometry",
            "ICPMS = Inductively-coupled plasma quadrupole mass spectrometry",
        ):
            if phrase not in metadata_text:
                raise SourceAdapterError(
                    f"BraSol method metadata contract changed: missing {phrase!r}"
                )
        rows = TpdcChinaMountainSoilAdapter._xlsx_rows(workbook.path)
        headers = rows[0][1] if rows else []
        required = set(self.candidate.registry_entry["required_fields"])
        if not required.issubset(headers):
            raise SourceAdapterError(
                f"BraSol workbook schema changed; missing={sorted(required - set(headers))}"
            )
        order = list(self.candidate.registry_entry["preferred_method_order"])
        method_fields: dict[str, list[tuple[str, str, str]]] = {}
        for analyte in self.candidate.registry_entry["target_analytes"]:
            candidates: list[tuple[str, str, str]] = []
            for method in order:
                value_fields = [
                    field
                    for field in headers
                    if re.fullmatch(f"{analyte}_{method}_mg_kg", field)
                ]
                if not value_fields:
                    continue
                lod_fields = [
                    field
                    for field in headers
                    if field.startswith(f"{analyte}_{method}") and "LOD" in field
                ]
                if len(value_fields) != 1 or len(lod_fields) != 1:
                    raise SourceAdapterError(
                        f"BraSol {analyte}/{method} field mapping changed"
                    )
                candidates.append((method, value_fields[0], lod_fields[0]))
            if not candidates:
                raise SourceAdapterError(f"BraSol has no fields for {analyte}")
            method_fields[analyte] = candidates

        physical_rows = 0
        target_bearing_rows = 0
        sites: set[str] = set()
        sample_keys: set[str] = set()
        layer_counts: Counter[str] = Counter()
        target_counts: Counter[str] = Counter()
        censored_counts: Counter[str] = Counter()
        reported_coordinate_rows = 0
        canonical_coordinate_rows = 0
        coordinate_conflict_rows = 0
        coordinate_conflict_sites: set[str] = set()
        for row_number, row in rows[1:]:
            padded = row + [""] * max(0, len(headers) - len(row))
            values = dict(zip(headers, padded, strict=False))
            site_id = values["Site_ID"].strip()
            layer = values["Lyr_name"].strip()
            sample_key = f"{site_id}|{layer}"
            if not site_id or layer not in {"ORG", "TOP", "BOT"}:
                raise SourceAdapterError(
                    f"BraSol sample identity/layer changed at row {row_number}"
                )
            if sample_key in sample_keys:
                raise SourceAdapterError(
                    f"BraSol sample identity repeats at row {row_number}"
                )
            sample_keys.add(sample_key)
            sites.add(site_id)
            layer_counts[layer] += 1
            physical_rows += 1
            try:
                latitude = float(values["Lat_dec_deg"])
                longitude = float(values["Long_dec_deg"])
                uncertainty = float(values["GPS_res_m"])
            except ValueError as exc:
                raise SourceAdapterError(
                    f"BraSol coordinate/GPS evidence changed at row {row_number}"
                ) from exc
            if (
                not (-90 <= latitude <= 90 and -180 <= longitude <= 180)
                or uncertainty <= 0
            ):
                raise SourceAdapterError(
                    f"BraSol coordinate/GPS evidence is invalid at row {row_number}"
                )
            reported_coordinate_rows += 1
            dms_latitude = self._dms_decimal(values["Lat_WGS84"], axis="latitude")
            dms_longitude = self._dms_decimal(values["Long_WGS84"], axis="longitude")
            coordinate_agrees = bool(
                dms_latitude is not None
                and dms_longitude is not None
                and abs(dms_latitude - latitude) <= 0.000002
                and abs(dms_longitude - longitude) <= 0.000002
            )
            if coordinate_agrees:
                canonical_coordinate_rows += 1
                coordinate_status = "publisher_wgs84_dms_decimal_agree"
            else:
                coordinate_conflict_rows += 1
                coordinate_conflict_sites.add(site_id)
                coordinate_status = "publisher_wgs84_dms_decimal_conflict_fail_closed"
            observations: dict[str, dict[str, Any]] = {}
            for analyte, mappings in method_fields.items():
                for method, value_field, lod_field in mappings:
                    reported = values[value_field].strip()
                    if not reported or reported == "NA":
                        continue
                    lod_raw = values[lod_field].strip()
                    qualifier = ""
                    value = reported
                    detection_limit = ""
                    if reported == "LOD":
                        try:
                            float(lod_raw)
                        except ValueError as exc:
                            raise SourceAdapterError(
                                f"BraSol LOD is missing for {analyte} at row {row_number}"
                            ) from exc
                        qualifier = "<"
                        value = lod_raw
                        detection_limit = lod_raw
                        censored_counts[analyte] += 1
                    else:
                        try:
                            float(reported)
                        except ValueError as exc:
                            raise SourceAdapterError(
                                f"BraSol {analyte} value is invalid at row {row_number}"
                            ) from exc
                        if lod_raw not in {"", "NA"}:
                            try:
                                float(lod_raw)
                            except ValueError as exc:
                                raise SourceAdapterError(
                                    f"BraSol {analyte} LOD is invalid at row {row_number}"
                                ) from exc
                            detection_limit = lod_raw
                    target_counts[analyte] += 1
                    observations[analyte] = {
                        "field": value_field,
                        "value": value,
                        "reported_value_raw": reported,
                        "unit": "mg/kg",
                        "qualifier": qualifier,
                        "detection_limit": detection_limit,
                        "measurement_basis": f"{method.casefold()}_method_specific_total_or_extractable_soil",
                        "analytical_method": self._method_name(method),
                        "digestion_or_extraction": self._digestion(method, layer),
                        "variable_metadata_locator": f"{metadata.path.name}#method={method}",
                    }
                    break
            if observations:
                target_bearing_rows += 1
            source_locator = f"{workbook.path.name}#sheet=Tabelle1&row={row_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, sample_key, source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "Latitude": format(latitude, ".12g"),
                    "Longitude": format(longitude, ".12g"),
                    "_canonical_latitude": (
                        format(latitude, ".12g") if coordinate_agrees else ""
                    ),
                    "_canonical_longitude": (
                        format(longitude, ".12g") if coordinate_agrees else ""
                    ),
                    "_target_observations": observations,
                    "_source_file": workbook.path.name,
                    "_method_metadata_file": metadata.path.name,
                    "_source_crs": "EPSG:4326",
                    "_coordinate_uncertainty_m": format(uncertainty, ".12g"),
                    "_coordinate_evidence_status": coordinate_status,
                    "_coordinate_dms_latitude": (
                        format(dms_latitude, ".12g") if dms_latitude is not None else ""
                    ),
                    "_coordinate_dms_longitude": (
                        format(dms_longitude, ".12g")
                        if dms_longitude is not None
                        else ""
                    ),
                    "_medium": "soil",
                    "_sample_type": layer,
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "physical_rows": physical_rows,
            "target_bearing_rows": target_bearing_rows,
            "distinct_sites": len(sites),
            "layer_counts": dict(sorted(layer_counts.items())),
            "reported_coordinate_rows": reported_coordinate_rows,
            "canonical_coordinate_rows": canonical_coordinate_rows,
            "coordinate_conflict_rows": coordinate_conflict_rows,
            "coordinate_conflict_sites": len(coordinate_conflict_sites),
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
            "censored_lod_counts": dict(sorted(censored_counts.items())),
        }
        if observed != self.candidate.registry_entry["expected_counts"]:
            raise SourceAdapterError(f"BraSol reconciliation changed: {observed!r}")


class FigshareYangtzeBasinSoilHeavyMetalsAdapter(_PinnedSingleFileAdapter):
    """Pinned Yangtze River Basin literature-compilation workbook."""

    source_id = "figshare-yangtze-basin-soil-heavy-metals"

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        """Fetch fixed Figshare files without persisting signed redirects."""

        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                f"{self.source_id} adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                f"use the checked-in {self.source_id} demo directly for fixture tests"
            )
        root = self._cache_root(cache_dir)
        download_entry = candidate.registry_entry["download"]
        file_entries = download_entry["files"]
        return [
            self._download_registered_file(
                candidate,
                root,
                mode,
                download_entry,
                file_entry,
                single_file=len(file_entries) == 1,
            )
            for file_entry in file_entries
        ]

    def _download_registered_file(
        self,
        candidate: DatasetCandidate,
        root: Path,
        mode: DownloadMode,
        download_entry: Mapping[str, Any],
        file_entry: Mapping[str, Any],
        *,
        single_file: bool,
    ) -> DownloadedFile:
        """Download and verify one registered member of a Figshare bundle."""

        output = root / file_entry["filename"]
        manifest_path = root / (
            "dataset.download.json"
            if single_file
            else f"{file_entry['file_id']}.download.json"
        )
        expected_sha256 = str(file_entry["expected_sha256"])
        public_url = str(file_entry["url"])

        if mode == "cached":
            result = downloader.existing_verified_cache(
                output,
                manifest_path,
                public_url,
                expected_sha256,
                candidate.version,
            )
        else:
            result: dict[str, Any] = {}
            if output.is_file() and manifest_path.is_file():
                try:
                    result = downloader.existing_verified_cache(
                        output,
                        manifest_path,
                        public_url,
                        expected_sha256,
                        candidate.version,
                    )
                except downloader.DownloadError:
                    result = {}
            if not result:
                file_id = str(file_entry["figshare_file_id"])
                filename = str(file_entry["filename"])

                class FigshareRedirectHandler(urllib.request.HTTPRedirectHandler):
                    def redirect_request(
                        self,
                        req: urllib.request.Request,
                        fp: Any,
                        code: int,
                        msg: str,
                        headers: Any,
                        newurl: str,
                    ) -> urllib.request.Request | None:
                        if (
                            urllib.parse.urlparse(req.full_url).hostname
                            != "ndownloader.figshare.com"
                        ):
                            raise SourceAdapterError(
                                "Figshare attempted an unexpected redirect chain"
                            )
                        validate_figshare_storage_redirect(newurl, file_id, filename)
                        return super().redirect_request(
                            req, fp, code, msg, headers, newurl
                        )

                downloader.validate_public_https_url(public_url)
                opener = urllib.request.build_opener(FigshareRedirectHandler())
                request = urllib.request.Request(
                    public_url,
                    headers={"User-Agent": downloader.USER_AGENT, "Accept": "*/*"},
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                temporary_path: Path | None = None
                try:
                    with opener.open(request, timeout=30.0) as response:
                        resolved_url = response.geturl()
                        # Some controlled egress proxies consume Figshare's
                        # signed S3 redirect and stream the response under the
                        # original public URL. That path carries no ephemeral
                        # capability and is safe to record. A visible redirect
                        # must still satisfy the strict host/path/query policy.
                        redacted_storage_url = (
                            public_url
                            if resolved_url == public_url
                            else validate_figshare_storage_redirect(
                                resolved_url, file_id, filename
                            )
                        )
                        content_type = response.headers.get_content_type().casefold()
                        downloader.validate_response_metadata(
                            content_type,
                            response.headers.get("Content-Length"),
                            int(download_entry["max_bytes"]),
                        )
                        with tempfile.NamedTemporaryFile(
                            "wb",
                            prefix=f".{output.name}.",
                            suffix=".part",
                            dir=output.parent,
                            delete=False,
                        ) as handle:
                            temporary_path = Path(handle.name)
                            total, observed = downloader.copy_response_bounded(
                                response, handle, int(download_entry["max_bytes"])
                            )
                        if total == 0 or observed != expected_sha256:
                            raise SourceAdapterError(
                                f"Figshare file {file_entry['file_id']} bytes do not match the pinned SHA-256"
                            )
                        os.replace(temporary_path, output)
                        temporary_path = None
                        result = {
                            "status": "downloaded",
                            "source_url": public_url,
                            "resolved_url": public_url,
                            "resolved_storage_url_redacted": redacted_storage_url,
                            "signed_redirect_persisted": False,
                            "content_type": content_type,
                            "bytes": total,
                            "sha256": observed,
                            "sha256_basis": "expected",
                            "accessed_at": downloader.utc_now(),
                            "http_status": getattr(response, "status", 200),
                            "etag": response.headers.get("ETag"),
                            "last_modified": response.headers.get("Last-Modified"),
                            "content_disposition": response.headers.get(
                                "Content-Disposition"
                            ),
                        }
                except (
                    downloader.DownloadError,
                    SourceAdapterError,
                    urllib.error.HTTPError,
                    urllib.error.URLError,
                    TimeoutError,
                    OSError,
                ) as exc:
                    raise SourceAdapterError(
                        f"{self.source_id} Figshare download failed without persisting "
                        "the ephemeral storage capability"
                    ) from exc
                finally:
                    if temporary_path is not None:
                        temporary_path.unlink(missing_ok=True)
                result.update(
                    {
                        "manifest_version": "geochemical-download-v1",
                        "file_id": file_entry["file_id"],
                        "license": candidate.license_id,
                        "output_filename": output.name,
                        "offline": False,
                        "dataset_doi": candidate.dataset_doi,
                        "dataset_version": candidate.version,
                    }
                )
                downloader.atomic_json(manifest_path, result)

        content_type = result.get("content_type")
        if content_type and content_type not in set(
            download_entry["accepted_content_types"]
        ):
            raise SourceAdapterError(
                f"{self.source_id} returned unexpected content type: {content_type}"
            )
        if output.stat().st_size != int(file_entry["bytes"]):
            raise SourceAdapterError(
                f"{self.source_id} file {file_entry['file_id']} byte count changed"
            )
        return DownloadedFile(
            source_id=self.source_id,
            file_id=str(file_entry["file_id"]),
            path=output,
            source_url=public_url,
            bytes=int(result["bytes"]),
            cache_status=str(result["status"]),
            retrieved_at=result.get("accessed_at") or result.get("cache_verified_at"),
        )

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "records-workbook":
            raise SourceAdapterError(
                "Yangtze basin adapter requires the registered workbook"
            )
        downloaded = files[0]
        rows = TpdcChinaMountainSoilAdapter._xlsx_rows(downloaded.path)
        headers = rows[0][1] if rows else []
        required = set(self.candidate.registry_entry["required_fields"])
        if not required.issubset(headers):
            raise SourceAdapterError(
                f"Yangtze basin workbook schema changed; missing={sorted(required - set(headers))}"
            )
        supported = set(self.candidate.registry_entry["target_analytes"])
        source_rows = 0
        fids: set[str] = set()
        target_counts: Counter[str] = Counter()
        location_levels: Counter[str] = Counter()
        coordinate_pairs: set[tuple[str, str]] = set()
        for row_number, row in rows[1:]:
            padded = row + [""] * max(0, len(headers) - len(row))
            values = dict(zip(headers, padded, strict=False))
            fid = values["FID"].strip()
            analyte = values["HM_cat_abbre"].strip()
            source_rows += 1
            if not fid or fid in fids:
                raise SourceAdapterError(
                    f"Yangtze basin FID is missing or repeated at row {row_number}"
                )
            fids.add(fid)
            if analyte not in supported:
                continue
            try:
                latitude = float(values["lat"])
                longitude = float(values["lon"])
                concentration = float(values["HM_conc_mean"])
            except ValueError as exc:
                raise SourceAdapterError(
                    f"Yangtze basin numeric field changed at row {row_number}"
                ) from exc
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise SourceAdapterError(
                    f"Yangtze basin coordinate is invalid at row {row_number}"
                )
            location_level = values["loc_level"].strip()
            if location_level not in {"1", "2", "3", "4"}:
                raise SourceAdapterError(
                    f"Yangtze basin location level changed at row {row_number}"
                )
            target_counts[analyte] += 1
            location_levels[location_level] += 1
            coordinate_pairs.add((values["lon"], values["lat"]))
            source_locator = f"{downloaded.path.name}#sheet=Records&row={row_number}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, f"{fid}|{analyte}", source_locator
                ),
                source_locator=source_locator,
                fields={
                    **values,
                    "Latitude": format(latitude, ".12g"),
                    "Longitude": format(longitude, ".12g"),
                    "_target_observations": {
                        analyte: {
                            "field": "HM_conc_mean",
                            "value": format(concentration, ".12g"),
                            "unit": "mg/kg",
                            "measurement_basis": "publisher_compiled_soil_concentration_mean",
                            "analytical_method": "",
                            "digestion_or_extraction": "",
                            "method_missing_reason": "publisher_compilation_omits_row_method",
                            "variable_metadata_locator": "doi:10.1002/gdj3.280",
                        }
                    },
                    "_source_file": downloaded.path.name,
                    "_source_crs": "",
                    "_medium": "soil",
                    "_sample_type": "literature-compiled soil occurrence",
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "source_rows": source_rows,
            "target_observations": sum(target_counts.values()),
            "distinct_coordinate_pairs": len(coordinate_pairs),
            "target_value_counts": dict(sorted(target_counts.items())),
            "location_level_counts": dict(sorted(location_levels.items())),
        }
        if observed != self.candidate.registry_entry["expected_counts"]:
            raise SourceAdapterError(
                f"Yangtze basin reconciliation changed: {observed!r}"
            )


class FourTuNorthernChinaSedimentAdapter(FigshareYangtzeBasinSoilHeavyMetalsAdapter):
    """Pinned 4TU workbook covering northern/western China sediments."""

    source_id = "4tu-northern-china-sediment"

    _METHODS: Mapping[str, Mapping[str, str]] = {
        "As": {
            "analytical_method": "hydride generation atomic fluorescence spectrometry (HG-AFS)",
            "digestion_or_extraction": "aqua regia digestion",
        },
        "Cr": {
            "analytical_method": "X-ray fluorescence spectrometry (XRF)",
            "digestion_or_extraction": "fused pellet preparation",
        },
        "Cu": {
            "analytical_method": "inductively coupled plasma mass spectrometry (ICP-MS)",
            "digestion_or_extraction": "four-acid digestion (HF+HNO3+HClO4+aqua regia)",
        },
        "Ni": {
            "analytical_method": "inductively coupled plasma mass spectrometry (ICP-MS)",
            "digestion_or_extraction": "four-acid digestion (HF+HNO3+HClO4+aqua regia)",
        },
        "Pb": {
            "analytical_method": "inductively coupled plasma mass spectrometry (ICP-MS)",
            "digestion_or_extraction": "four-acid digestion (HF+HNO3+HClO4+aqua regia)",
        },
        "Zn": {
            "analytical_method": "inductively coupled plasma mass spectrometry (ICP-MS)",
            "digestion_or_extraction": "four-acid digestion (HF+HNO3+HClO4+aqua regia)",
        },
        "Hg": {
            "analytical_method": "",
            "digestion_or_extraction": "",
            "method_missing_reason": "publisher_readme_does_not_map_hg_method",
        },
    }

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        required_files = {
            "northern-china-workbook",
            "methods-and-qc-readme",
            "observed-regions-kml",
        }
        if set(by_id) != required_files:
            raise SourceAdapterError(
                "4TU northern-China adapter requires the registered workbook, "
                "methods/QC README and observed-regions KML"
            )
        downloaded = by_id["northern-china-workbook"]
        method_evidence = by_id["methods-and-qc-readme"]
        region_evidence = by_id["observed-regions-kml"]
        registry = self.candidate.registry_entry
        expected_units = registry["target_units"]
        sample_keys: set[str] = set()
        coordinate_pairs: set[tuple[str, str]] = set()
        sheet_counts: Counter[str] = Counter()
        region_counts: Counter[str] = Counter()
        target_counts: Counter[str] = Counter()

        for contract in registry["sheet_contracts"]:
            sheet_number = int(contract["sheet_number"])
            sheet_label = str(contract["sheet_label"])
            rows = TpdcChinaMountainSoilAdapter._xlsx_rows(
                downloaded.path, sheet_number, "4TU northern China"
            )
            if len(rows) < 3:
                raise SourceAdapterError(
                    f"4TU worksheet {sheet_label} has no data population"
                )
            headers = rows[0][1]
            units = rows[1][1]
            required = set(registry["required_fields"])
            if not required.issubset(headers):
                raise SourceAdapterError(
                    f"4TU worksheet {sheet_label} schema changed; "
                    f"missing={sorted(required - set(headers))}"
                )
            unit_by_field = dict(
                zip(
                    headers,
                    units + [""] * max(0, len(headers) - len(units)),
                    strict=False,
                )
            )
            if any(
                unit_by_field.get(field) != expected_units[analyte]
                for analyte, field in registry["target_analytes"].items()
            ):
                raise SourceAdapterError(
                    f"4TU worksheet {sheet_label} target units changed"
                )
            for row_number, row in rows[2:]:
                padded = row + [""] * max(0, len(headers) - len(row))
                values = dict(zip(headers, padded, strict=False))
                native_id = values["No."].strip()
                sample_key = f"{sheet_label}|{native_id}"
                if not native_id or sample_key in sample_keys:
                    raise SourceAdapterError(
                        f"4TU sample identity invalid at {sheet_label} row {row_number}"
                    )
                try:
                    longitude = float(values["Longitude"])
                    latitude = float(values["Latitude"])
                except ValueError as exc:
                    raise SourceAdapterError(
                        f"4TU coordinate is not numeric at {sheet_label} row {row_number}"
                    ) from exc
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise SourceAdapterError(
                        f"4TU coordinate is outside valid bounds at {sheet_label} row {row_number}"
                    )
                category = (
                    values.get("Category", "").strip()
                    if sheet_number == 1
                    else "Chinese Loess Plateau"
                )
                if not category:
                    raise SourceAdapterError(
                        f"4TU surface-sediment region is missing at row {row_number}"
                    )
                observations: dict[str, dict[str, Any]] = {}
                for analyte, field in registry["target_analytes"].items():
                    raw_value = values[field].strip()
                    try:
                        float(raw_value)
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"4TU {analyte} is not numeric at {sheet_label} row {row_number}"
                        ) from exc
                    method = self._METHODS[analyte]
                    observations[analyte] = {
                        "field": field,
                        "value": raw_value,
                        "unit": expected_units[analyte],
                        "measurement_basis": "air_dried_homogenized_<75um_sediment_multi_method",
                        "analytical_method": method.get("analytical_method", ""),
                        "digestion_or_extraction": method.get(
                            "digestion_or_extraction", ""
                        ),
                        "method_missing_reason": method.get(
                            "method_missing_reason", ""
                        ),
                        "variable_metadata_locator": (
                            "README.pdf#multi-method-analytical-scheme-and-quality-control"
                        ),
                    }
                    target_counts[analyte] += 1
                source_locator = (
                    f"{downloaded.path.name}#sheet={sheet_label}&row={row_number}"
                )
                sample_keys.add(sample_key)
                coordinate_pairs.add((values["Longitude"], values["Latitude"]))
                sheet_counts[sheet_label] += 1
                if sheet_number == 1:
                    region_counts[category] += 1
                yield RawRecord(
                    source_id=self.source_id,
                    source_record_id=stable_source_record_id(
                        self.source_id, sample_key, source_locator
                    ),
                    source_locator=source_locator,
                    fields={
                        **values,
                        "Latitude": format(latitude, ".12g"),
                        "Longitude": format(longitude, ".12g"),
                        "_physical_sample_id": sample_key,
                        "_target_observations": observations,
                        "_source_file": downloaded.path.name,
                        "_official_source_url": self.candidate.landing_page,
                        "_source_crs": "",
                        "_medium": "sediment",
                        "_sample_type": str(contract["sample_type"]),
                        "_sediment_environment": str(contract["sediment_environment"]),
                        "_survey_area": category,
                        "_grain_fraction": "<75 µm",
                        "_preparation": "air-dried, homogenized and sieved through a stainless-steel screen",
                        "_reference_materials": (
                            "GSS-1; GSS-2; GSS-17; GSS-19; GSS-25; GSS-26; GSS-27; "
                            "GAu2a; GAu2b; GAu9a; GAu9b; GAu10a; GAu10b; "
                            "GAu11a; GAu11b; GPt-1; GPt-2; GPt-7; GPt-8"
                        ),
                        "_dataset_qc_scope": (
                            "3% field duplicates, blind laboratory replicates and SRMs; "
                            "row-level QC assignments and acceptance results not published"
                        ),
                        "_method_evidence_file": method_evidence.path.name,
                        "_method_evidence_url": method_evidence.source_url,
                        "_method_evidence_sha256": method_evidence.sha256,
                        "_region_evidence_file": region_evidence.path.name,
                        "_region_evidence_url": region_evidence.source_url,
                        "_region_evidence_sha256": region_evidence.sha256,
                        "_dataset_version": self.candidate.version,
                    },
                )

        observed = {
            "physical_rows": len(sample_keys),
            "sheet_row_counts": dict(sorted(sheet_counts.items())),
            "surface_region_counts": dict(sorted(region_counts.items())),
            "distinct_coordinate_pairs": len(coordinate_pairs),
            "target_observations": sum(target_counts.values()),
            "target_value_counts": dict(sorted(target_counts.items())),
        }
        if observed != registry["expected_counts"]:
            raise SourceAdapterError(
                f"4TU northern-China reconciliation changed: {observed!r}"
            )


class ZenodoYangtzeYellowRiverSedimentAdapter(_PinnedSingleFileAdapter):
    """Pinned Zenodo Data Set S2 leach-residual river-sediment workbook."""

    source_id = "zenodo-yangtze-yellow-river-sediment"

    _label_re = re.compile(
        r"^(?P<leach>HCl|AC)-residual (?P<sample>HH-\d+|CJ-\d+|CJ Sand-\d+)\s*"
        r"(?P<fraction>.*)$"
    )
    _numeric_re = re.compile(r"^-?\d+(\.\d+)?([eE][+-]?\d+)?$")
    # Certified reference values (ug/g) used to verify the undeclared workbook
    # unit. GeoReM/USGS preferred values as published in the workbook QC block.
    _qc_preferred = {
        ("BHVO-2", "Cr"): 299.0,
        ("BHVO-2", "Cu"): 127.0,
        ("BHVO-2", "Ni"): 126.0,
        ("BHVO-2", "Zn"): 103.0,
        ("BHVO-2", "Pb"): 1.6,
        ("AGV-2", "Cr"): 17.0,
        ("AGV-2", "Cu"): 53.0,
        ("AGV-2", "Ni"): 20.0,
        ("AGV-2", "Zn"): 86.0,
        ("AGV-2", "Pb"): 13.2,
    }
    _qc_tolerance = 0.20

    @classmethod
    def verified_samples(
        cls, path: Path, registry_entry: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        """Return one entry per verified sample row with all target values.

        Shared with the checked-in China fixture builder so the pinned fixture
        and the online acquisition path can never diverge structurally.
        """

        target_analytes = tuple(registry_entry["target_analytes"])
        expected = registry_entry["expected_counts"]
        rows = TpdcChinaMountainSoilAdapter._xlsx_rows(path)
        by_row = {number: row for number, row in rows}
        for required in (1, 6, 12):
            if required not in by_row:
                raise SourceAdapterError(
                    f"Zenodo S2 structure changed: row {required} missing"
                )
        if by_row[1][:1] != ["Preferred values"] or by_row[6][:1] != [
            "Measured values"
        ]:
            raise SourceAdapterError("Zenodo S2 QC block headers changed")
        headers = by_row[12]
        if (
            headers[:1] != [""]
            or by_row[1][1:] != headers[1:]
            or by_row[6][1:] != headers[1:]
        ):
            raise SourceAdapterError("Zenodo S2 element headers changed between blocks")
        missing = [item for item in target_analytes if item not in headers]
        if missing:
            raise SourceAdapterError(
                f"Zenodo S2 lacks target analyte columns: {missing}"
            )
        columns = {analyte: headers.index(analyte) for analyte in target_analytes}

        qc_rows = {
            block: {by_row[number][0]: by_row[number] for number in numbers}
            for block, numbers in (
                ("preferred", (2, 3, 4, 5)),
                ("measured", (7, 8, 9, 10)),
            )
        }
        for block, table in qc_rows.items():
            if set(table) != {"BHVO-2", "AGV-2", "W-2", "GSP-2"}:
                raise SourceAdapterError(
                    f"Zenodo S2 QC {block} standards changed: {sorted(table)}"
                )
        checks = 0
        for (standard, analyte), certified in cls._qc_preferred.items():
            index = columns[analyte]
            preferred = float(qc_rows["preferred"][standard][index])
            measured = float(qc_rows["measured"][standard][index])
            for label, value in (("preferred", preferred), ("measured", measured)):
                if abs(value - certified) > cls._qc_tolerance * certified:
                    raise SourceAdapterError(
                        f"Zenodo S2 unit verification failed: {standard} {analyte} "
                        f"{label} value {value} is outside {cls._qc_tolerance:.0%} "
                        f"of the certified ug/g value {certified}"
                    )
            checks += 1
        if checks != len(cls._qc_preferred):
            raise SourceAdapterError(
                "Zenodo S2 QC alignment did not run for every standard"
            )

        samples: list[dict[str, Any]] = []
        seen_labels: set[str] = set()
        for number, row in rows:
            if number < 13:
                continue
            if not any(cell.strip() for cell in row):
                continue
            label = row[0].strip()
            match = cls._label_re.match(label)
            if match is None:
                raise SourceAdapterError(
                    f"Zenodo S2 sample label changed at row {number}: {label!r}"
                )
            if label in seen_labels:
                raise SourceAdapterError(
                    f"Zenodo S2 sample label duplicated at row {number}: {label!r}"
                )
            seen_labels.add(label)
            values: dict[str, str] = {}
            for analyte, index in columns.items():
                raw = row[index].strip() if index < len(row) else ""
                if not cls._numeric_re.match(raw):
                    raise SourceAdapterError(
                        f"Zenodo S2 {analyte} is not numeric at row {number}: {raw!r}"
                    )
                values[analyte] = raw
            samples.append(
                {
                    "row": number,
                    "label": label,
                    "leach": match.group("leach"),
                    "sample": match.group("sample"),
                    "fraction": match.group("fraction").strip(),
                    "values": values,
                }
            )
        if len(samples) != int(expected["sample_rows"]):
            raise SourceAdapterError(
                f"Zenodo S2 sample count changed: expected {expected['sample_rows']}, found {len(samples)}"
            )
        return samples

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if len(files) != 1 or files[0].file_id != "data-set-s2":
            raise SourceAdapterError(
                "Zenodo S2 adapter requires the registered workbook"
            )
        downloaded = files[0]
        registry = self.candidate.registry_entry
        samples = self.verified_samples(downloaded.path, registry)
        target_analytes = tuple(registry["target_analytes"])
        counts: Counter[str] = Counter()
        leach_counts: Counter[str] = Counter()
        for sample in samples:
            observations: dict[str, dict[str, Any]] = {}
            for analyte in target_analytes:
                counts[analyte] += 1
                leach_counts[sample["leach"]] += 1
                observations[analyte] = {
                    "field": analyte,
                    "value": sample["values"][analyte],
                    "unit": "ug/g",
                }
            source_locator = f"{downloaded.path.name}#sheet1-row={sample['row']}"
            yield RawRecord(
                source_id=self.source_id,
                source_record_id=stable_source_record_id(
                    self.source_id, sample["label"], source_locator
                ),
                source_locator=source_locator,
                fields={
                    "_source_file": downloaded.path.name,
                    "_target_observations": observations,
                    "_sample_label": sample["label"],
                    "_river_sample": sample["sample"],
                    "_leach_group": sample["leach"],
                    "_size_fraction": sample["fraction"],
                    "_sheet_row": sample["row"],
                    "_dataset_version": self.candidate.version,
                },
            )
        observed = {
            "sample_rows": len(samples),
            "target_observations": sum(counts.values()),
            "target_value_counts": dict(sorted(counts.items())),
            "leach_groups": dict(sorted(leach_counts.items())),
        }
        expected = {
            "sample_rows": int(registry["expected_counts"]["sample_rows"]),
            "target_observations": int(
                registry["expected_counts"]["target_observations"]
            ),
            "target_value_counts": dict(
                sorted(registry["expected_counts"]["target_value_counts"].items())
            ),
            "leach_groups": dict(
                sorted(registry["expected_counts"]["leach_groups"].items())
            ),
        }
        if observed != expected:
            raise SourceAdapterError(
                f"Zenodo S2 reconciliation changed: {observed!r} != {expected!r}"
            )


class ZenodoGardWholeRockAdapter(RegistryAdapter):
    """Pinned Gard/Hasterok/Halpin 2019 global whole-rock compilation.

    The Zenodo v1.1.0 record is immutable, so both files are exact-pinned.
    ``complete.zip`` carries the joined analysis table (1,022,092 rows) and
    ``reference.csv`` resolves ``ref_id`` to the original article citation.
    Roughly 68 percent of the citations come from GEOROC, so this source is
    a literature compilation overlapping the georoc-* lineage and never
    counts as an independent replication of those archives.
    """

    source_id = "zenodo-gard-whole-rock"

    _KEPT_FIELDS = (
        "sample_id",
        "sample_name",
        "latitude",
        "longitude",
        "loc_prec",
        "rock_name",
        "rock_type",
        "rock_group",
        "rock_origin",
        "rock_facies",
        "sample_description",
        "country",
        "ref_id",
        "method",
        "age",
        "as_ppm",
        "cr_ppm",
        "cu_ppm",
        "ni_ppm",
        "pb_ppm",
        "zn_ppm",
    )

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError(
                f"{self.source_id} adapter received a candidate for another source"
            )
        if mode == "fixture":
            raise SourceAdapterError(
                f"use the checked-in {self.source_id} demo directly for fixture tests"
            )
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
                expected_sha256=file_entry.get("expected_sha256"),
                max_bytes=int(download_entry["max_bytes"]),
                dataset_doi=candidate.dataset_doi,
                dataset_version=candidate.version,
                offline=mode == "cached",
                required_fields=(),
            )
            try:
                result = downloader.run(args)
            except (downloader.DownloadError, OSError) as exc:
                raise SourceAdapterError(
                    f"{self.source_id} download failed: {exc}"
                ) from exc
            content_type = result.get("content_type")
            if content_type and content_type.casefold() not in (
                accepted_content_types_for_file(download_entry, file_entry)
            ):
                raise SourceAdapterError(
                    f"{self.source_id} returned unexpected content type: {content_type}"
                )
            if output.stat().st_size != file_entry["bytes"]:
                raise SourceAdapterError(f"{self.source_id} file size changed")
            results.append(
                DownloadedFile(
                    source_id=self.source_id,
                    file_id=file_entry["file_id"],
                    path=output,
                    source_url=file_entry["url"],
                    bytes=result["bytes"],
                    cache_status=result["status"],
                    retrieved_at=result.get("accessed_at")
                    or result.get("cache_verified_at"),
                )
            )
        return results

    def reference_map(
        self, files: Sequence[DownloadedFile]
    ) -> dict[str, dict[str, str]]:
        """Return ref_id -> citation fields from the pinned reference table."""
        by_id = {item.file_id: item for item in files}
        reference_file = by_id.get("reference-csv")
        if reference_file is None:
            raise SourceAdapterError(
                f"{self.source_id} requires the pinned reference.csv"
            )
        references: dict[str, dict[str, str]] = {}
        with reference_file.path.open(encoding="utf-8", errors="replace") as handle:
            for row in csv.DictReader(handle):
                ref_id = str(row.get("ref_id") or "").strip()
                if ref_id:
                    references[ref_id] = {
                        "author": str(row.get("author") or "").strip(),
                        "title": str(row.get("title") or "").strip(),
                        "journal": str(row.get("journal") or "").strip(),
                        "year": str(row.get("year") or "").strip(),
                        "doi": str(row.get("doi") or "").strip(),
                        "data_source": str(row.get("data_source") or "").strip(),
                    }
        return references

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        archive = by_id.get("complete-zip")
        if archive is None or "reference-csv" not in by_id:
            raise SourceAdapterError(
                f"{self.source_id} requires complete.zip and reference.csv"
            )
        expected = self.candidate.registry_entry["expected_counts"]
        total = 0
        with zipfile.ZipFile(archive.path) as bundle:
            with bundle.open("complete.csv") as raw:
                text_stream = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                reader = csv.DictReader(text_stream)
                fieldnames = set(reader.fieldnames or [])
                missing = [
                    field for field in self._KEPT_FIELDS if field not in fieldnames
                ]
                if missing:
                    raise SourceAdapterError(
                        f"{self.source_id} table structure changed; missing: {missing}"
                    )
                for row in reader:
                    total += 1
                    line = reader.line_num
                    fields = {
                        field: str(row.get(field) or "").strip()
                        for field in self._KEPT_FIELDS
                    }
                    fields["_source_file"] = archive.path.name
                    sample_id = fields["sample_id"]
                    if not sample_id:
                        raise SourceAdapterError(
                            f"{self.source_id} row {line} lacks the sample_id key"
                        )
                    source_locator = f"complete.csv#row={line}"
                    yield RawRecord(
                        source_id=self.source_id,
                        source_record_id=stable_source_record_id(
                            self.source_id, sample_id, source_locator
                        ),
                        source_locator=source_locator,
                        fields=fields,
                    )
        if total != int(expected["total_rows"]):
            raise SourceAdapterError(
                f"{self.source_id} row count changed: expected "
                f"{expected['total_rows']}, found {total}"
            )


class GemasEuropeAdapter(RegistryAdapter):
    """GSI's official GEMAS Ap/Gr DBF republication with method-separated analyses."""

    source_id = "gemas-europe"

    @staticmethod
    def _dbf_rows(payload: bytes) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
        if len(payload) < 33:
            raise SourceAdapterError("GEMAS DBF is truncated")
        record_count = struct.unpack("<I", payload[4:8])[0]
        header_length = struct.unpack("<H", payload[8:10])[0]
        record_length = struct.unpack("<H", payload[10:12])[0]
        descriptors = payload[32 : header_length - 1]
        fields: list[tuple[str, int]] = []
        for offset in range(0, len(descriptors), 32):
            item = descriptors[offset : offset + 32]
            if len(item) < 32 or item[0] == 0x0D:
                break
            name = item[:11].split(b"\0", 1)[0].decode("ascii").strip()
            fields.append((name, item[16]))
        rows: list[tuple[int, dict[str, str]]] = []
        for index in range(record_count):
            start = header_length + index * record_length
            record = payload[start : start + record_length]
            if len(record) != record_length:
                raise SourceAdapterError("GEMAS DBF record area is truncated")
            if record[:1] == b"*":
                continue
            cursor = 1
            values: dict[str, str] = {}
            for name, width in fields:
                values[name] = (
                    record[cursor : cursor + width]
                    .decode("utf-8", errors="replace")
                    .strip()
                )
                cursor += width
            rows.append((index + 1, values))
        return [name for name, _ in fields], rows

    def _root(self, cache_dir: Path) -> Path:
        standard = self._cache_root(cache_dir)
        fallback = cache_dir / "gemas-v4" / "gsi-arcgis-2024"
        return standard if standard.exists() or not fallback.exists() else fallback

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != self.source_id:
            raise SourceAdapterError("GEMAS adapter received another source")
        if mode == "fixture":
            raise SourceAdapterError("use the checked-in GEMAS demo for fixture tests")
        entry = candidate.registry_entry["download"]
        file_entry = entry["files"][0]
        root = self._root(cache_dir)
        output = root / file_entry["filename"]
        args = _download_args(
            url=file_entry["url"],
            output=output,
            manifest=root / "gemas.download.json",
            license_id=candidate.license_id,
            expected_sha256=file_entry.get("expected_sha256"),
            max_bytes=int(entry["max_bytes"]),
            dataset_doi=candidate.dataset_doi,
            dataset_version=candidate.version,
            offline=mode == "cached",
        )
        try:
            result = downloader.run(args)
        except (downloader.DownloadError, OSError) as exc:
            raise SourceAdapterError(f"GEMAS download failed: {exc}") from exc
        if output.stat().st_size != int(file_entry["bytes"]):
            raise SourceAdapterError("GEMAS ZIP byte count changed")
        try:
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                missing = set(file_entry["required_members"]) - names
                if missing:
                    raise SourceAdapterError(
                        f"GEMAS ZIP member inventory changed: {sorted(missing)}"
                    )
        except zipfile.BadZipFile as exc:
            raise SourceAdapterError("GEMAS ZIP is unreadable") from exc
        return [
            DownloadedFile(
                source_id=self.source_id,
                file_id=file_entry["file_id"],
                path=output,
                source_url=file_entry["url"],
                bytes=output.stat().st_size,
                cache_status=result["status"],
                retrieved_at=result.get("accessed_at")
                or result.get("cache_verified_at"),
            )
        ]

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        if (
            len(files) != 1
            or files[0].file_id != "1725dd24-1b2f-46d5-bf24-ad2db5ee176e"
        ):
            raise SourceAdapterError("GEMAS requires its registered GSI resource")
        downloaded = files[0]
        expected = self.candidate.registry_entry["expected_counts"]
        samples: set[str] = set()
        countries: set[str] = set()
        counts = Counter()
        group_counts = Counter()
        with zipfile.ZipFile(downloaded.path) as archive:
            for member in self.candidate.registry_entry["download"]["files"][0][
                "member_contracts"
            ]:
                field_names, rows = self._dbf_rows(archive.read(member["filename"]))
                if len(field_names) != int(member["field_count"]) or len(rows) != int(
                    member["record_count"]
                ):
                    raise SourceAdapterError(
                        f"GEMAS DBF structure changed: {member['filename']}"
                    )
                for record_number, values in rows:
                    sample_type = values.get("TYPE_", "")
                    if sample_type != member["sample_type"]:
                        continue
                    country = values.get("COUNTRY", "")
                    try:
                        sample_number = int(float(values.get("ID", "")))
                        longitude = float(values.get("XCOO", ""))
                        latitude = float(values.get("YCOO", ""))
                    except ValueError as exc:
                        raise SourceAdapterError(
                            f"GEMAS sample identity/coordinate changed at record {record_number}"
                        ) from exc
                    if not country or not (
                        -180 <= longitude <= 180 and -90 <= latitude <= 90
                    ):
                        raise SourceAdapterError(
                            f"GEMAS invalid production row at record {record_number}"
                        )
                    sample_key = f"GEMAS:{sample_type}:{sample_number}"
                    if sample_key in samples:
                        raise SourceAdapterError(
                            f"GEMAS sample duplicated: {sample_key}"
                        )
                    samples.add(sample_key)
                    countries.add(country)
                    for analysis_group in ("AR", "XRF"):
                        observations: dict[str, dict[str, Any]] = {}
                        fields = self.candidate.registry_entry["analysis_groups"][
                            analysis_group
                        ]
                        for analyte, field in fields["target_analytes"].items():
                            raw_value = values.get(field, "")
                            if not raw_value:
                                raise SourceAdapterError(
                                    f"GEMAS {field} missing for {sample_key}"
                                )
                            numeric = float(raw_value)
                            dl = float(fields["detection_limits"][analyte])
                            counts[analyte] += 1
                            group_counts[analysis_group] += 1
                            observations[analyte] = {
                                "field": field,
                                "value": raw_value,
                                "unit": "mg/kg",
                                "measurement_basis": fields["measurement_basis"],
                                "analytical_method": fields["analytical_method"],
                                "digestion_or_extraction": fields[
                                    "digestion_or_extraction"
                                ],
                                "detection_limit": str(
                                    fields["detection_limits"][analyte]
                                ),
                                "below_laboratory_dl": numeric < dl,
                                "upstream_half_dl_substitution": analysis_group == "XRF"
                                and numeric == dl / 2,
                            }
                        source_locator = f"{downloaded.path.name}!{member['filename']}#record={record_number}"
                        native_id = f"{sample_key}:{analysis_group}"
                        yield RawRecord(
                            source_id=self.source_id,
                            source_record_id=stable_source_record_id(
                                self.source_id, native_id, source_locator
                            ),
                            source_locator=source_locator,
                            fields={
                                **values,
                                "_physical_sample_id": sample_key,
                                "_analysis_group": analysis_group,
                                "_target_observations": observations,
                                "_source_file": downloaded.path.name,
                                "_source_crs": "EPSG:4326",
                                "_sample_type": sample_type,
                                "_grain_fraction": fields["grain_fraction"],
                                "_dataset_version": self.candidate.version,
                            },
                        )
        observed = {
            "physical_samples": len(samples),
            "analysis_records": len(samples) * 2,
            "country_labels": len(countries),
            "target_observations": sum(counts.values()),
            "analysis_group_observations": dict(sorted(group_counts.items())),
            "target_value_counts": dict(sorted(counts.items())),
        }
        if observed != expected:
            raise SourceAdapterError(
                f"GEMAS reconciliation changed: {observed!r} != {expected!r}"
            )


ADAPTERS: Mapping[str, type[RegistryAdapter]] = {
    ZenodoYangtzeYellowRiverSedimentAdapter.source_id: (
        ZenodoYangtzeYellowRiverSedimentAdapter
    ),
    GeorocArchaeanAdapter.source_id: GeorocArchaeanAdapter,
    GeorocConvergentMarginsAdapter.source_id: GeorocConvergentMarginsAdapter,
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
    AfsisPhaseIWetChemistryAdapter.source_id: AfsisPhaseIWetChemistryAdapter,
    WqpSacramentoRiverArsenicAdapter.source_id: WqpSacramentoRiverArsenicAdapter,
    AustraliaNgsaAtlasAdapter.source_id: AustraliaNgsaAtlasAdapter,
    AustraliaNgsaMercuryAdapter.source_id: AustraliaNgsaMercuryAdapter,
    GsjJapanMarineSedimentAdapter.source_id: GsjJapanMarineSedimentAdapter,
    PangaeaArabianSeaSedimentAdapter.source_id: PangaeaArabianSeaSedimentAdapter,
    PangaeaEastChinaSeaClayAdapter.source_id: PangaeaEastChinaSeaClayAdapter,
    PangaeaSouthChinaSeaSedimentAdapter.source_id: (
        PangaeaSouthChinaSeaSedimentAdapter
    ),
    PangaeaBarentsCHorizonSoilAdapter.source_id: PangaeaBarentsCHorizonSoilAdapter,
    PangaeaAmazonasSoilAdapter.source_id: PangaeaAmazonasSoilAdapter,
    PangaeaBatagaySoilAdapter.source_id: PangaeaBatagaySoilAdapter,
    GeorocAntarcticaIntraplateAdapter.source_id: GeorocAntarcticaIntraplateAdapter,
    EidcNingboSoilAdapter.source_id: EidcNingboSoilAdapter,
    TpdcChinaMountainSoilAdapter.source_id: TpdcChinaMountainSoilAdapter,
    MendeleyGuangdongFujianGroundwaterAdapter.source_id: (
        MendeleyGuangdongFujianGroundwaterAdapter
    ),
    EuropePmcPearlRiverDissolvedMetalsAdapter.source_id: (
        EuropePmcPearlRiverDissolvedMetalsAdapter
    ),
    EarthchemDehailonggangRockAdapter.source_id: EarthchemDehailonggangRockAdapter,
    FourTuNorthernChinaSedimentAdapter.source_id: FourTuNorthernChinaSedimentAdapter,
    PangaeaBrasolNeBrazilSoilAdapter.source_id: PangaeaBrasolNeBrazilSoilAdapter,
    FigshareYangtzeBasinSoilHeavyMetalsAdapter.source_id: (
        FigshareYangtzeBasinSoilHeavyMetalsAdapter
    ),
    GemasEuropeAdapter.source_id: GemasEuropeAdapter,
    ZenodoGardWholeRockAdapter.source_id: ZenodoGardWholeRockAdapter,
}


def get_adapter(
    source_id: str, registry_path: Path = DEFAULT_REGISTRY
) -> RegistryAdapter:
    """Instantiate a registered adapter without dynamic imports or arbitrary code execution."""

    adapter_type = ADAPTERS.get(source_id)
    if adapter_type is None:
        raise SourceAdapterError(f"no adapter is registered for source_id: {source_id}")
    return adapter_type(registry_path)
