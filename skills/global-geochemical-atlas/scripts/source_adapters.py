#!/usr/bin/env python3
"""Shared D1 contracts for versioned scientific data-source adapters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
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


ADAPTERS: Mapping[str, type[RegistryAdapter]] = {
    GeorocArchaeanAdapter.source_id: GeorocArchaeanAdapter,
    UsgsSoilAdapter.source_id: UsgsSoilAdapter,
    MarchemSnapshotAdapter.source_id: MarchemSnapshotAdapter,
    GeotracesIdp2025Adapter.source_id: GeotracesIdp2025Adapter,
}


def get_adapter(source_id: str, registry_path: Path = DEFAULT_REGISTRY) -> RegistryAdapter:
    """Instantiate a registered adapter without dynamic imports or arbitrary code execution."""

    adapter_type = ADAPTERS.get(source_id)
    if adapter_type is None:
        raise SourceAdapterError(f"no adapter is registered for source_id: {source_id}")
    return adapter_type(registry_path)
