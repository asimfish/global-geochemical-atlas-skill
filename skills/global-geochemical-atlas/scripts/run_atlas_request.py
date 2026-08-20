#!/usr/bin/env python3
"""Run evidence-aware online acquisition/input filtering, D2 and D3 in one command."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import build_interactive_map as map_builder
import coverage_report
import execution_budget
import skill_snapshot
import source_adapters
import source_router
import spatial_scope
import standardize_geochemistry as standardizer


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
GENERATOR = SCRIPT_DIR / "generate_demo_data.py"
PRODUCTION_FIXTURE = SKILL_DIR / "fixtures" / "production-usgs"
FOUR_MEDIA_FIXTURE = SKILL_DIR / "fixtures" / "four-media" / "combined-v3"
CHINA_FIXTURE = SKILL_DIR / "fixtures" / "china" / "combined-v1"
FULL_PROFILE_ROOT = SKILL_DIR / "assets" / "v4-full-profiles"
DEFAULT_GEOLOGY_GRID = SKILL_DIR / "assets" / "geology" / "pangaea-788537.zip"
DEFAULT_GEOLOGY_SHA256 = (
    "43b4ce3276b155d804db8ff9fb227d620b4c35015a4cf564eac4d06d2b69d88e"
)
PARAMETERIZED_SOURCES = {
    "georoc-archaean",
    "georoc-convergent-margins",
    "usgs-conus-soil",
    "foregs-topsoil",
    "foregs-subsoil",
    "foregs-humus",
    "foregs-stream-water",
    "foregs-stream-sediment",
    "foregs-floodplain-sediment",
    "gemstat-open-archive",
    "geotraces-idp2025",
    "afsis-phase-i-wet-chemistry",
    "australia-ngsa",
    "japan-gsj-geochemical-map",
    "pangaea-amazonas-soil",
    "pangaea-batagay-soil",
    "pangaea-brasol-ne-brazil-soil",
    "figshare-yangtze-basin-soil-heavy-metals",
    "4tu-northern-china-sediment",
}
# These sources support request-element filtering but deliberately do not
# accept a bbox.  In particular, the GSJ marine table keeps its reported
# JGD2000 coordinates non-canonical until a publication-grade transform policy
# is registered; using them as if they were WGS84 for a boundary clip would
# contradict that fail-closed evidence boundary.
ELEMENT_ONLY_PARAMETERIZED_SOURCES = {
    "japan-gsj-marine-sediment",
}
SCALABLE_BALANCED_SOURCES = {
    "gemstat-open-archive",
    "geotraces-idp2025",
    "afsis-phase-i-wet-chemistry",
    "japan-gsj-geochemical-map",
    "pangaea-amazonas-soil",
    "pangaea-batagay-soil",
    "4tu-northern-china-sediment",
}
# These long-form sources have verified but intentionally unequal per-analyte
# populations.  Their capacity is the sum of requested analyte counts, not the
# smallest count multiplied by the number of analytes.
VARIABLE_ANALYTE_CAPACITY_SOURCES = {
    "pangaea-brasol-ne-brazil-soil",
    "figshare-yangtze-basin-soil-heavy-metals",
    "japan-gsj-marine-sediment",
}
DEFAULT_WORKFLOW_RESERVE_SECONDS = 180.0
# Online-acquisition slice sizing. Sources with frozen exact-slice contracts
# keep their checked-in sizes; every other adapter scales with the request and
# is bounded by its registered capacity, the request ceiling and a defensive
# per-source cap.  The cap is intentionally research-sized; tiny fixed slices
# remain explicit adapter contracts rather than the default execution policy.
FIXED_SLICE_OBSERVATIONS = {
    "us-wqp-sacramento-river-arsenic": 48,
    "australia-ngsa-mercury": 48,
}
SLICE_DIVISORS = {
    "australia-ngsa": 4,
    "norway-marchem": 4,
    "pangaea-north-africa-soil": 4,
    "japan-gsj-geochemical-map": 4,
    "japan-gsj-marine-sediment": 7,
    "pangaea-arabian-sea-sediment": 6,
    "pangaea-east-china-sea-clay": 4,
    "pangaea-south-china-sea-sediment": 5,
    "pangaea-barents-c-horizon-soil": 4,
    "georoc-antarctica-intraplate": 6,
    "tpdc-china-mountain-soil": 5,
    "earthchem-dehailonggang-rock": 5,
    "gemas-europe": 13,
    "zenodo-yangtze-yellow-river-sediment": 6,
    "eidc-ningbo-soil": 4,
}
# These adapters expose a verified population whose safe balanced capacity is
# smaller than the registry's raw target-observation total.  The difference is
# scientifically meaningful (for example, the North Africa adapter currently
# exports four registered atlas analytes, while the population profile counts
# six), so the runner must use the adapter contract rather than over-requesting
# and losing the source entirely.
BALANCED_CAPACITY_OVERRIDES = {
    "georoc-antarctica-intraplate": 90,
    "pangaea-north-africa-soil": 172,
}
DEFAULT_PER_ANALYTE_OBSERVATIONS = 512
GENERATOR_MAX_OBSERVATIONS = 200_000
# Source-level prose and publication metadata are commonly repeated verbatim
# on every row by source adapters.  The filtered evidence sidecar keeps one
# hash-bound anchor per acquired file and points later rows to it; record-level
# identity, locator and acquired-file binding remain repeated on every row.
SHARED_SOURCE_EVIDENCE_FIELDS = (
    "article_citations",
    "article_dois",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "evidence_status",
    "evidence_version",
    "generation_version",
    "retrieved_at",
    "scientific_note",
    "selection_rule",
    "source_file_bytes",
)
# A deadline-squeezed fair-share window below this floor cannot complete any
# real acquisition (GEMStat once got 14.6s and burned it on a doomed attempt);
# such sources are deferred to the next round instead of attempted.
MIN_SOURCE_TIMEOUT_SECONDS = 60.0
SPATIAL_CELL_ID_PATTERN = re.compile(r"^([+-]\d+):([+-]\d+)$")


class RequestRunError(RuntimeError):
    """A stable, user-actionable request execution failure."""

    def __init__(
        self,
        status: str,
        message: str,
        *,
        evidence: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.evidence = dict(evidence or {})


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RequestRunError(
            "invalid_input", f"{label} does not exist: {path}"
        ) from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RequestRunError(
            "invalid_input", f"{label} is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise RequestRunError("invalid_input", f"{label} must be a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_static_request_evidence(
    output_dir: Path,
    request: Mapping[str, Any],
    route: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> None:
    """Persist the frozen request and D1 decisions before disposable work starts."""

    request_evidence = output_dir / "request_evidence"
    write_json(request_evidence / "request.json", dict(request))
    write_json(request_evidence / "source_route.json", dict(route))
    write_json(request_evidence / "coverage.json", dict(matrix))
    (request_evidence / "coverage.md").write_text(
        coverage_report.render_markdown(matrix), encoding="utf-8"
    )


def write_execution_progress(
    output_dir: Path,
    source_outcomes: Sequence[Mapping[str, Any]],
    requested_source_ids: Sequence[str],
    acquisition_warnings: Sequence[str],
    *,
    source_order_offset: int = 0,
    priority_source_ids: Sequence[str] = (),
    complete: bool = False,
) -> None:
    """Checkpoint D1 attempts so a controller timeout cannot erase their evidence."""

    write_json(
        output_dir / "request_evidence" / "execution_progress.json",
        {
            "progress_version": "geochemical-request-progress-v2",
            "stage": "source_acquisition",
            "requested_source_ids": list(requested_source_ids),
            "source_order_offset": source_order_offset,
            "priority_source_ids": list(priority_source_ids),
            "source_order_policy": "gap-priority-then-coverage-balanced-round-robin-v2",
            "source_outcomes": [dict(item) for item in source_outcomes],
            "acquisition_warnings": list(acquisition_warnings),
            "complete": complete,
        },
    )


def retain_acquisition_manifests(
    output_dir: Path,
    filtered_acquisition: Path | None,
    source_manifest: Path | None,
    source_child_manifests: Sequence[tuple[str, Path]],
) -> list[dict[str, Any]]:
    """Copy hash-bound manifests out of the temporary directory before D2/D3."""

    if filtered_acquisition is None or source_manifest is None:
        return []
    acquisition_dir = output_dir / "request_evidence" / "acquisition"
    acquisition_dir.mkdir(parents=True, exist_ok=True)
    manifest_specs: list[tuple[str, str | None, Path, str]] = [
        (
            "request_filtered_manifest",
            None,
            filtered_acquisition,
            "request_manifest.json",
        ),
        (
            "parent_source_manifest",
            None,
            source_manifest,
            "parent_manifest.json",
        ),
    ]
    manifest_specs.extend(
        (
            "source_manifest",
            source_id,
            manifest_path,
            f"source-manifest--{source_id}.json",
        )
        for source_id, manifest_path in source_child_manifests
    )
    retained: list[dict[str, Any]] = []
    for role, source_id, source_path, filename in manifest_specs:
        if source_id is not None and not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", source_id
        ):
            raise RequestRunError(
                "conflicting_evidence",
                f"unsafe source ID in acquisition manifest path: {source_id!r}",
            )
        destination = acquisition_dir / filename
        shutil.copyfile(source_path, destination)
        retained.append(
            {
                "role": role,
                "source_id": source_id,
                "path": destination.relative_to(
                    output_dir / "request_evidence"
                ).as_posix(),
                "sha256": sha256_file(destination),
            }
        )
    return retained


def verify_manifest_outputs(manifest_path: Path, paths: Sequence[Path]) -> None:
    """Verify that a parent acquisition manifest actually binds every supplied file."""

    manifest = read_json(manifest_path, "source acquisition manifest")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise RequestRunError(
            "conflicting_evidence", "source manifest has no outputs hash inventory"
        )
    inventory: dict[str, Mapping[str, Any]] = {}
    for item in outputs:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            inventory[Path(item["path"]).name] = item
    for path in paths:
        evidence = inventory.get(path.name)
        if evidence is None:
            raise RequestRunError(
                "conflicting_evidence",
                f"source manifest does not bind supplied file: {path.name}",
            )
        actual_hash = sha256_file(path)
        actual_bytes = path.stat().st_size
        if (
            evidence.get("sha256") != actual_hash
            or evidence.get("bytes") != actual_bytes
        ):
            raise RequestRunError(
                "conflicting_evidence",
                f"source manifest hash/size mismatch for {path.name}",
            )


def _year(value: Any) -> int | None:
    match = re.search(r"(?:^|\D)(\d{4})(?:\D|$)", str(value or ""))
    return int(match.group(1)) if match else None


def _year_bounds(value: Any) -> tuple[int, int] | None:
    years = [
        int(item) for item in re.findall(r"(?<!\d)(\d{4})(?!\d)", str(value or ""))
    ]
    return (min(years), max(years)) if years else None


def _canonical_coordinate_declared(row: Mapping[str, str]) -> bool:
    source_crs = re.sub(r"\s+", "", str(row.get("source_crs") or "")).casefold()
    transform = str(row.get("coordinate_transform_method") or "").strip()
    return source_crs in {"epsg:4326", "wgs84", "wgs1984", "4326", "ogc:crs84"} or bool(
        transform
    )


def _inside_bbox(row: Mapping[str, str], bbox: Sequence[float]) -> bool:
    if not _canonical_coordinate_declared(row):
        return False
    try:
        latitude = float(row.get("latitude") or "")
        longitude = float(row.get("longitude") or "")
    except ValueError:
        return False
    return spatial_scope.coordinate_in_bbox(longitude, latitude, bbox)


def _basis_matches(requested: Sequence[str], actual: str) -> bool:
    return any(source_router.basis_matches(item, actual) for item in requested)


def _normalized_geology(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _geology_labels(
    row: Mapping[str, str],
    match_policy: str,
    geology_grid: standardizer.GlimGrid | None,
) -> set[str]:
    labels: set[str] = set()
    if match_policy in {"reported", "reported_or_matched"}:
        labels.update(
            _normalized_geology(row.get(field))
            for field in ("geologic_unit", "geologic_unit_raw")
            if str(row.get(field) or "").strip()
        )
    if match_policy in {"matched", "reported_or_matched"}:
        existing = _normalized_geology(row.get("matched_geologic_unit"))
        if existing:
            labels.add(existing)
        if geology_grid is not None and _canonical_coordinate_declared(row):
            medium = str(row.get("medium") or "").casefold()
            sediment_context = " ".join(
                str(row.get(field) or "")
                for field in ("material", "sediment_environment")
            ).casefold()
            water_is_marine = (
                medium == "water"
                and spatial_scope.record_spatial_domain(row) == "marine"
            )
            if not water_is_marine and not (
                medium == "sediment" and "marine" in sediment_context
            ):
                try:
                    latitude = float(row.get("latitude") or "")
                    longitude = float(row.get("longitude") or "")
                except ValueError:
                    pass
                else:
                    if -90 <= latitude <= 90 and -180 <= longitude <= 180:
                        match = geology_grid.lookup(latitude, longitude)
                        if match is not None:
                            labels.add(
                                _normalized_geology(f"GLiM:{match[0]}:{match[1]}")
                            )
    return labels


def _load_request_geology_grid(
    request: Mapping[str, Any],
    grid_path: Path,
    expected_sha256: str,
    no_geology: bool,
) -> standardizer.GlimGrid | None:
    if not request.get("geology_units") or request.get("geology_match") == "reported":
        return None
    if no_geology:
        if request.get("geology_match") == "matched":
            raise RequestRunError(
                "unsupported_scope",
                "geology_match=matched requires the frozen geology grid; remove --no-geology",
            )
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256.casefold()):
        raise RequestRunError(
            "invalid_input",
            "geology grid SHA-256 must contain 64 hexadecimal characters",
        )
    if not grid_path.is_file() or sha256_file(grid_path) != expected_sha256.casefold():
        raise RequestRunError(
            "conflicting_evidence",
            "geology grid is missing or its SHA-256 does not match",
        )
    try:
        return standardizer.GlimGrid(grid_path)
    except standardizer.PipelineError as exc:
        raise RequestRunError("conflicting_evidence", str(exc)) from exc


def compact_record_evidence_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate identical source-file metadata without weakening linkage.

    Compaction happens only after request filtering, so every metadata anchor
    necessarily survives in the output.  Only an explicit allowlist of
    source-level fields may be moved to that anchor.  Per-record values and the
    source file name/hash/URL stay on every line for independent verification.
    """

    compacted = [dict(row) for row in rows]
    grouped_indexes: dict[tuple[str, str, str], list[int]] = {}
    for index, row in enumerate(compacted):
        source_id = str(row.get("source_id") or "")
        source_file = str(row.get("source_file") or "")
        source_hash = str(row.get("source_file_sha256") or "")
        if not source_id or not source_file or not source_hash:
            continue
        grouped_indexes.setdefault((source_id, source_file, source_hash), []).append(
            index
        )

    for indexes in grouped_indexes.values():
        if len(indexes) < 2:
            continue
        anchor = compacted[indexes[0]]
        anchor_record_id = str(anchor.get("record_id") or "")
        if not anchor_record_id:
            continue
        shared_fields: list[str] = []
        for field in SHARED_SOURCE_EVIDENCE_FIELDS:
            values = [compacted[index].get(field) for index in indexes]
            if values[0] in (None, "", [], {}) or any(
                value != values[0] for value in values[1:]
            ):
                continue
            shared_fields.append(field)
        if not shared_fields:
            continue
        anchor["shared_source_metadata_fields"] = shared_fields
        for index in indexes[1:]:
            row = compacted[index]
            for field in shared_fields:
                row.pop(field, None)
            row["source_metadata_record_id"] = anchor_record_id
    return compacted


def serialize_record_evidence(rows: Sequence[Mapping[str, Any]]) -> bytes:
    """Serialize record evidence deterministically for hashing and size gates."""

    return "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    ).encode("utf-8")


def filter_bundle(
    input_path: Path,
    evidence_path: Path | None,
    request: Mapping[str, Any],
    output_input: Path,
    output_evidence: Path | None,
    geology_grid: standardizer.GlimGrid | None = None,
    coordinate_mode: str = "canonical",
) -> tuple[int, int, list[str]]:
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except (OSError, UnicodeError) as exc:
        raise RequestRunError(
            "invalid_input", f"input CSV is unreadable: {input_path}"
        ) from exc
    if not fields or not rows:
        raise RequestRunError(
            "invalid_input", "input CSV must contain a header and at least one record"
        )

    evidence_by_id: dict[str, dict[str, Any]] = {}
    if evidence_path is not None:
        try:
            for line in evidence_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                record_id = (
                    str(item.get("record_id") or "") if isinstance(item, dict) else ""
                )
                if not record_id or record_id in evidence_by_id:
                    raise RequestRunError(
                        "conflicting_evidence",
                        "record evidence has missing or duplicate record_id",
                    )
                evidence_by_id[record_id] = item
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RequestRunError(
                "conflicting_evidence",
                f"record evidence is unreadable: {evidence_path}",
            ) from exc

    region = request["region"]
    try:
        resolved_region = spatial_scope.resolve_region(region)
    except spatial_scope.SpatialScopeError as exc:
        raise RequestRunError(
            "needs_human_review",
            str(exc),
        ) from exc
    requested_basis = request.get("measurement_basis")
    requested_geology = {
        _normalized_geology(item) for item in (request.get("geology_units") or [])
    }
    geology_match = str(request.get("geology_match", "reported_or_matched"))
    requested_time = request.get("time_range")
    requested_sources = request.get("sources")
    requested_spatial_domains = request.get("spatial_domains") or ["land"]
    adjacent_marine_distance_km = float(request.get("adjacent_marine_distance_km") or 0)
    start_year = _year(requested_time[0]) if requested_time else None
    end_year = _year(requested_time[1]) if requested_time else None

    selected: list[dict[str, str]] = []
    exclusion_counts: dict[str, int] = {}
    unlocated_kept = 0
    for row in rows:
        reason = None
        if row.get("element_or_analyte") not in request["elements"]:
            reason = "element"
        elif row.get("medium") not in request["media"]:
            reason = "medium"
        elif (
            isinstance(requested_sources, list)
            and row.get("source_id") not in requested_sources
        ):
            reason = "source"
        elif requested_basis and not _basis_matches(
            requested_basis, str(row.get("measurement_basis") or "")
        ):
            reason = "measurement_basis"
        elif resolved_region["key"] != "global" and not _canonical_coordinate_declared(
            row
        ):
            if coordinate_mode != "reported":
                reason = "bbox_unverified_crs"
            else:
                reported_latitude = str(row.get("original_latitude_raw") or "").strip()
                reported_longitude = str(
                    row.get("original_longitude_raw") or ""
                ).strip()
                if not reported_latitude and not reported_longitude:
                    # No coordinates at all: keep for the standardized database;
                    # the map and spatial screening exclude it downstream.
                    unlocated_kept += 1
                else:
                    try:
                        latitude = float(reported_latitude)
                        longitude = float(reported_longitude)
                    except ValueError:
                        reason = "region"
                    else:
                        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                            reason = "region"
                        else:
                            try:
                                inside_region = spatial_scope.coordinate_in_request_scope(
                                    longitude,
                                    latitude,
                                    resolved_region,
                                    spatial_domain=spatial_scope.record_spatial_domain(
                                        row
                                    ),
                                    spatial_domains=requested_spatial_domains,
                                    adjacent_marine_distance_km=adjacent_marine_distance_km,
                                )
                            except spatial_scope.SpatialScopeError as exc:
                                raise RequestRunError(
                                    "conflicting_evidence", str(exc)
                                ) from exc
                            if not inside_region:
                                reason = "region"
        elif resolved_region["key"] != "global":
            try:
                latitude = float(row.get("latitude") or "")
                longitude = float(row.get("longitude") or "")
            except ValueError:
                reason = "region"
            else:
                try:
                    inside_region = spatial_scope.coordinate_in_request_scope(
                        longitude,
                        latitude,
                        resolved_region,
                        spatial_domain=spatial_scope.record_spatial_domain(row),
                        spatial_domains=requested_spatial_domains,
                        adjacent_marine_distance_km=adjacent_marine_distance_km,
                    )
                except spatial_scope.SpatialScopeError as exc:
                    raise RequestRunError("conflicting_evidence", str(exc)) from exc
                if not inside_region:
                    reason = "region"
        if reason is None and requested_time:
            sample_bounds = _year_bounds(row.get("sampled_at"))
            if (
                sample_bounds is None
                or start_year is None
                or end_year is None
                or start_year > sample_bounds[1]
                or sample_bounds[0] > end_year
            ):
                reason = "time_range"
        if (
            reason is None
            and requested_geology
            and not requested_geology.intersection(
                _geology_labels(row, geology_match, geology_grid)
            )
        ):
            reason = "geology_units"
        if reason is not None:
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            continue
        selected.append(row)

    if not selected:
        raise RequestRunError(
            "incomplete_retrieval",
            f"no records remain after deterministic request filters; exclusions={exclusion_counts}",
        )
    original_selected = len(selected)
    selected = selected[: int(request["max_records"])]
    warnings: list[str] = []
    if unlocated_kept:
        warnings.append(
            f"reported coordinate mode retained {unlocated_kept} record(s) that "
            "declare no coordinates; they stay in the standardized database but "
            "cannot be mapped or spatially screened"
        )
    if len(selected) < original_selected:
        warnings.append(
            f"request max_records truncated {original_selected} matching records to {len(selected)}; coverage is incomplete"
        )

    output_input.parent.mkdir(parents=True, exist_ok=True)
    with output_input.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(selected)

    if evidence_path is not None and output_evidence is not None:
        ids = [str(row.get("record_id") or "") for row in selected]
        missing = [record_id for record_id in ids if record_id not in evidence_by_id]
        if missing:
            raise RequestRunError(
                "conflicting_evidence",
                f"record evidence does not cover filtered input IDs: {missing[:5]}",
            )
        selected_evidence = compact_record_evidence_rows(
            [evidence_by_id[item] for item in ids]
        )
        output_evidence.write_bytes(serialize_record_evidence(selected_evidence))
    return len(rows), len(selected), warnings


def filtered_manifest(
    source_manifest_path: Path,
    input_path: Path,
    evidence_path: Path,
    request: Mapping[str, Any],
    original_count: int,
    selected_count: int,
) -> dict[str, Any]:
    source = read_json(source_manifest_path, "source acquisition manifest")
    source_files = source.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise RequestRunError(
            "conflicting_evidence", "source manifest has no source_files evidence"
        )
    return {
        "request_run_manifest_version": "geochemical-request-run-v1",
        "data_mode": source.get("data_mode", "fixture"),
        "not_for_scientific_interpretation": bool(
            source.get("not_for_scientific_interpretation", False)
        ),
        "request": dict(request),
        "filter_counts": {"input": original_count, "selected": selected_count},
        "parent_manifest": {
            "filename": source_manifest_path.name,
            "sha256": sha256_file(source_manifest_path),
        },
        "source_files": source_files,
        "outputs": [
            {
                "path": input_path.name,
                "bytes": input_path.stat().st_size,
                "sha256": sha256_file(input_path),
            },
            {
                "path": evidence_path.name,
                "bytes": evidence_path.stat().st_size,
                "sha256": sha256_file(evidence_path),
            },
        ],
        "failures": [],
    }


def request_dimension_coverage(
    filtered_input: Path, request: Mapping[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Report requested element/media dimensions that survived deterministic filtering."""

    try:
        with filtered_input.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, UnicodeError) as exc:
        raise RequestRunError(
            "incomplete_retrieval",
            f"cannot audit filtered request dimensions: {filtered_input}",
        ) from exc
    dimensions: dict[str, Any] = {}
    warnings: list[str] = []
    for field, request_key, label in (
        ("element_or_analyte", "elements", "element"),
        ("medium", "media", "medium"),
    ):
        requested = sorted(str(item) for item in request[request_key])
        observed = sorted(
            {str(row.get(field) or "") for row in rows if str(row.get(field) or "")}
        )
        missing = sorted(set(requested) - set(observed))
        dimensions[request_key] = {
            "requested": requested,
            "observed": observed,
            "missing": missing,
            "status": "complete" if not missing else "partial",
        }
        if missing:
            warnings.append(f"request {label} coverage missing: {', '.join(missing)}")
    requested_domains = sorted(
        str(item) for item in request.get("spatial_domains") or []
    )
    if requested_domains:
        observed_domains = sorted(
            {spatial_scope.record_spatial_domain(row) for row in rows}
        )
        missing_domains = sorted(set(requested_domains) - set(observed_domains))
        dimensions["spatial_domains"] = {
            "requested": requested_domains,
            "observed": observed_domains,
            "missing": missing_domains,
            "status": "complete" if not missing_domains else "partial",
        }
        if missing_domains:
            warnings.append(
                "request spatial-domain coverage missing: " + ", ".join(missing_domains)
            )
    return {
        "status": (
            "complete"
            if all(item["status"] == "complete" for item in dimensions.values())
            else "partial"
        ),
        "dimensions": dimensions,
    }, warnings


def request_failure_summary(
    status: str,
    message: str,
    args: argparse.Namespace,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    input_path = args.input if isinstance(args.input, Path) else None
    return {
        "schema_version": "global-geochemical-atlas-result-v1",
        "status": status,
        "quality_status": "not_evaluated",
        "request_summary": {
            "region_bbox": None,
            "max_records": 0,
            "group_by": list(standardizer.DEFAULT_GROUP_BY),
            "minimum_group_size": 20 if args.analysis_profile == "production" else 8,
            "robust_z_threshold": 3.5,
        },
        "input": {
            "filename": input_path.name if input_path is not None else str(args.demo),
            "sha256": sha256_file(input_path)
            if input_path is not None and input_path.is_file()
            else "0" * 64,
            "record_count": 0,
            "synthetic_demo": False,
            "data_mode": "not_evaluated",
            "not_for_scientific_interpretation": False,
        },
        "outputs": {},
        "metrics": {
            "record_count": 0,
            "standardized_record_count": 0,
            "valid_coordinate_count": 0,
            "censored_record_count": 0,
            "candidate_anomaly_count": 0,
            "batch_qc_failed_or_incomplete_count": 0,
            "candidate_anomaly_region_count": 0,
            "iteration_action_required_count": 0,
            "iteration_review_required_count": 0,
        },
        "coverage": {
            "elements": [],
            "media": [],
            "coordinate_rate": 0.0,
            "standardization_rate": 0.0,
            "bbox": None,
            "interpolation": False,
        },
        "limitations": [message],
        "failure_evidence": dict(evidence or {}),
        "next_actions": [
            "Correct the reported request failure and rerun; do not infer missing scientific fields."
        ],
    }


def declared_slice_capacity(
    source_id: str, analytes: Sequence[str] | None = None
) -> int | None:
    """Return a safe balanced-slice ceiling from the registered source counts."""

    if source_id in BALANCED_CAPACITY_OVERRIDES:
        return BALANCED_CAPACITY_OVERRIDES[source_id]
    try:
        entry = source_adapters.load_source_registry()["sources"][source_id]
    except (KeyError, source_adapters.SourceAdapterError):
        return None
    counts = entry.get("expected_counts")
    if not isinstance(counts, Mapping):
        return None
    research_capacity = entry.get("research_slice_capacity")
    if isinstance(research_capacity, Mapping):
        capacity_counts = research_capacity.get("per_analyte_observation_count")
        if isinstance(capacity_counts, Mapping) and capacity_counts:
            selected_analytes = (
                [str(analyte) for analyte in analytes]
                if analytes is not None
                else [str(analyte) for analyte in capacity_counts]
            )
            try:
                selected_counts = [
                    int(capacity_counts[analyte]) for analyte in selected_analytes
                ]
            except (KeyError, TypeError, ValueError):
                return None
            return (
                min(selected_counts) * len(selected_counts) if selected_counts else None
            )
    per_analyte = counts.get("target_value_counts")
    if isinstance(per_analyte, Mapping) and per_analyte:
        try:
            capacity_analytes = (
                set(analytes or ("As", "Cu", "Ni", "Zn"))
                if source_id.startswith("foregs-")
                else set(analytes)
                if analytes is not None
                else None
            )
            selected_counts = [
                int(count)
                for analyte, count in per_analyte.items()
                if capacity_analytes is None or analyte in capacity_analytes
            ]
            if selected_counts:
                return min(selected_counts) * len(selected_counts)
            return None
        except (TypeError, ValueError):
            return None
    total = counts.get("target_observations")
    return int(total) if isinstance(total, int) else None


def declared_variable_analyte_capacity(
    source_id: str, analytes: Sequence[str] | None
) -> int | None:
    """Return a verified unequal-analyte population total when registered."""

    if source_id not in VARIABLE_ANALYTE_CAPACITY_SOURCES:
        return None
    try:
        entry = source_adapters.load_source_registry()["sources"][source_id]
    except (KeyError, TypeError, source_adapters.SourceAdapterError):
        return None
    research_capacity = entry.get("research_slice_capacity")
    counts = (
        research_capacity.get("per_analyte_observation_count")
        if isinstance(research_capacity, Mapping)
        else None
    )
    if not isinstance(counts, Mapping):
        counts = entry.get("expected_counts", {}).get("target_value_counts")
    if not isinstance(counts, Mapping):
        return None
    selected = list(analytes) if analytes is not None else list(counts)
    try:
        values = [int(counts[analyte]) for analyte in selected]
    except (KeyError, TypeError, ValueError):
        return None
    return sum(values) if values else None


def foregs_balance_size(
    source_id: str, analytes: Sequence[str] | None = None
) -> int | None:
    """Return the registered FOREGS analyte × basis class count."""

    if not source_id.startswith("foregs-"):
        return None
    try:
        entry = source_adapters.load_source_registry()["sources"][source_id]
        members = entry["download"]["members"]
    except (KeyError, TypeError, source_adapters.SourceAdapterError):
        return None
    selected_analytes = set(analytes or ("As", "Cu", "Ni", "Zn"))
    classes = {
        (str(analyte), str(member.get("measurement_basis") or ""))
        for member in members
        if isinstance(member, Mapping)
        for analyte in (member.get("target_analytes") or {})
        if analyte in selected_analytes
    }
    return len(classes) or None


def planned_slice_observations(
    source_id: str,
    analyte_count: int,
    max_records: int,
    per_analyte_observations: int = DEFAULT_PER_ANALYTE_OBSERVATIONS,
    analytes: Sequence[str] | None = None,
) -> int:
    """Return the balanced-slice size requested from the demo generator."""

    if source_id in VARIABLE_ANALYTE_CAPACITY_SOURCES:
        balance_size = 1
        observations = max(analyte_count, analyte_count * per_analyte_observations)
        capacity = declared_variable_analyte_capacity(source_id, analytes)
        if capacity is not None:
            observations = min(observations, capacity)
    elif source_id in SCALABLE_BALANCED_SOURCES:
        balance_size = analyte_count
        observations = max(balance_size, balance_size * per_analyte_observations)
        capacity = declared_slice_capacity(source_id, analytes)
        if capacity is not None:
            observations = min(observations, capacity)
    elif source_id in FIXED_SLICE_OBSERVATIONS:
        balance_size = 1
        observations = FIXED_SLICE_OBSERVATIONS[source_id]
    elif source_id == "usgs-conus-soil":
        balance_size = 3 * analyte_count
        observations = balance_size * per_analyte_observations
    elif source_id in {"georoc-archaean", "georoc-convergent-margins"}:
        balance_size = analyte_count
        observations = balance_size * per_analyte_observations
    elif source_id in SLICE_DIVISORS:
        # Fixed-set generators emit every one of their registered analyte
        # classes for each selected sample; observations, capacity and the
        # per-source budget are all generator-emission units here. Bounding
        # them by a requested-element subset would silently truncate samples
        # (a Cu/Pb/Zn request once cut TPDC to 788 of 1,314 samples), so the
        # capacity ceiling is always the full balanced population and the
        # request-element filter runs after the merge.
        balance_size = SLICE_DIVISORS[source_id]
        observations = max(48, balance_size * per_analyte_observations)
        capacity = declared_slice_capacity(source_id, None)
        if capacity is not None:
            observations = min(observations, capacity)
    else:
        divisor = foregs_balance_size(source_id, analytes)
        if divisor is None:
            # Frozen 48-observation contract for adapters without a registered
            # expansion divisor (FOREGS members register 1-4 analyte classes
            # and 48 divides all of them).
            balance_size = 1
            observations = 48
        else:
            balance_size = divisor
            observations = max(48, divisor * per_analyte_observations)
            capacity = declared_slice_capacity(source_id, analytes)
            if capacity is not None:
                observations = min(observations, capacity)
    observations = min(observations, max_records, GENERATOR_MAX_OBSERVATIONS)
    if balance_size > 1 and observations >= balance_size:
        observations -= observations % balance_size
    return observations


def supported_request_analytes(source_id: str, elements: Sequence[str]) -> list[str]:
    """Return the requested elements this source registers, in request order.

    One element the source never registered (for example Pb against
    usgs-conus-soil's As/Cu/Ni/Zn methods) must shrink the slice, not fail the
    whole source. A source without a registered analyte list passes the
    request through unchanged so its generator can decide.
    """
    registered = {
        str(item)
        for item in (
            source_adapters.load_source_registry()["sources"]
            .get(source_id, {})
            .get("target_analytes", {})
        )
    }
    if not registered:
        return [str(item) for item in elements]
    return [str(item) for item in elements if str(item) in registered]


def generator_bbox_argument(region_bbox: Sequence[float]) -> str:
    """Return the generator --bbox flag as a single --bbox=value token.

    A west-negative scope such as the United States (-171.79...) or the Europe
    frame (-25.0...) starts the value with a dash. Passed as a separate argv
    token, argparse reads it as an option name and aborts with 'expected one
    argument', which kills every parameterized online source for that request.
    """
    return "--bbox=" + ",".join(str(item) for item in region_bbox)


def acquire_online_source(
    source_id: str,
    request: Mapping[str, Any],
    cache_dir: Path,
    output_dir: Path,
    acquisition_mode: str,
    generated_at: str,
    timeout_seconds: float = 300.0,
    per_analyte_observations: int = DEFAULT_PER_ANALYTE_OBSERVATIONS,
    region_bbox: Sequence[float] | None = None,
) -> None:
    analytes = supported_request_analytes(source_id, request["elements"])
    if not analytes:
        raise RequestRunError(
            "incomplete_retrieval",
            f"{source_id} registers none of the requested analytes; the router should not have selected it",
        )
    observations = planned_slice_observations(
        source_id,
        len(analytes),
        int(request["max_records"]),
        per_analyte_observations,
        analytes,
    )
    command = [
        sys.executable,
        str(GENERATOR),
        "--source",
        source_id,
        "--cache-dir",
        str(cache_dir),
        "--output-dir",
        str(output_dir),
        "--mode",
        acquisition_mode,
        "--observations",
        str(observations),
        "--generated-at",
        generated_at,
        "--purpose",
        "research",
    ]
    element_parameterized = (
        source_id in PARAMETERIZED_SOURCES
        or source_id in ELEMENT_ONLY_PARAMETERIZED_SOURCES
    )
    if element_parameterized:
        command.extend(["--elements", ",".join(analytes)])
    if source_id in PARAMETERIZED_SOURCES and region_bbox is not None:
        command.append(generator_bbox_argument(region_bbox))
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RequestRunError(
            "incomplete_retrieval",
            f"source acquisition timed out after {timeout_seconds:.3f}s for {source_id}",
        ) from exc
    if result.returncode:
        raise RequestRunError(
            "incomplete_retrieval",
            f"source acquisition failed for {source_id}: {(result.stderr or result.stdout).strip()}",
        )


def minimum_source_records(source_id: str, analyte_count: int) -> int:
    if source_id in {"georoc-archaean", "georoc-convergent-margins"}:
        return analyte_count
    if source_id == "usgs-conus-soil":
        return 3 * analyte_count
    if source_id in SCALABLE_BALANCED_SOURCES or source_id == "australia-ngsa":
        return analyte_count
    # The remaining frozen adapters use a 48-observation evidence-balanced
    # slice (some enforce it exactly) before request filtering.
    return 48


def _ocean_sector(longitude: float) -> str:
    sector = min(5, max(0, int((longitude + 180.0) // 60.0)))
    west = -180 + sector * 60
    return f"Open ocean longitude sector {west:+d}..{west + 60:+d}"


def _cell_coverage_zone(cell_id: str) -> str | None:
    match = SPATIAL_CELL_ID_PATTERN.fullmatch(cell_id)
    if match is None:
        return None
    latitude = int(match.group(1)) + 0.5
    longitude = int(match.group(2)) + 0.5
    try:
        macroregion = spatial_scope.coordinate_macroregion(longitude, latitude)
    except spatial_scope.SpatialScopeError:
        return None
    return (
        _ocean_sector(longitude)
        if macroregion == "Open ocean / unassigned"
        else macroregion
    )


@lru_cache(maxsize=None)
def source_coverage_zones(source_id: str) -> tuple[str, ...]:
    """Return audited acquisition-priority zones for one source profile.

    Canonical cells are preferred. Reported-only cells or an explicit complete
    country index remain useful for acquisition ordering, but their ``reported``
    prefix prevents this scheduling hint from masquerading as canonical spatial
    sufficiency evidence.
    """

    path = FULL_PROFILE_ROOT / source_id / "spatial_coverage.json"
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ()
    if not isinstance(profile, Mapping):
        return ()

    def zones_from_cells(key: str, prefix: str) -> set[str]:
        raw_cells = profile.get(key)
        if not isinstance(raw_cells, list):
            return set()
        zones: set[str] = set()
        for raw_cell in raw_cells:
            zone = _cell_coverage_zone(str(raw_cell))
            if zone:
                zones.add(f"{prefix}:{zone}")
        return zones

    canonical = zones_from_cells("spatial_cell_ids", "canonical")
    if canonical:
        return tuple(sorted(canonical))
    reported = zones_from_cells("reported_spatial_cell_ids", "reported")
    if reported:
        return tuple(sorted(reported))

    applicability = profile.get("region_applicability")
    if isinstance(applicability, Mapping):
        raw_codes = applicability.get("country_iso_a3_codes")
        if isinstance(raw_codes, list):
            try:
                macroregions = spatial_scope.load_macroregion_registry()
            except spatial_scope.SpatialScopeError:
                macroregions = {}
            reported.update(
                f"reported:{macroregions[code]}"
                for code in sorted({str(item) for item in raw_codes})
                if code in macroregions
            )
    return tuple(sorted(reported))


def coverage_balanced_source_order(
    route_entries: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Order acquisitions by marginal spatial/media evidence, then lineage.

    The router decides compatibility; this scheduler only decides who gets the
    earliest share of a finite round. It retains every routed source and never
    deletes dense regions. Greedy marginal gain prevents an alphabetical block
    of sibling FOREGS tables from consuming the front of a deadline before
    independent African, Asian, American or ocean lineages are attempted.
    """

    remaining = [dict(entry) for entry in route_entries]
    ordered: list[dict[str, Any]] = []
    covered_pairs: set[tuple[str, str]] = set()
    covered_zones: set[str] = set()
    covered_media: set[str] = set()
    seen_lineages: set[str] = set()
    while remaining:

        def rank(entry: Mapping[str, Any]) -> tuple[Any, ...]:
            source_id = str(entry["source_id"])
            audited_zones = set(source_coverage_zones(source_id))
            zones = {item.partition(":")[2] for item in audited_zones}
            canonical_zones = {
                item.partition(":")[2]
                for item in audited_zones
                if item.startswith("canonical:")
            }
            media = {str(item) for item in entry.get("matching_media", [])}
            pairs = {(zone, medium) for zone in zones for medium in media}
            lineage = source_adapters.source_lineage_id(source_id)
            return (
                -(bool(zones) and lineage not in seen_lineages),
                -len(pairs - covered_pairs),
                -len(zones - covered_zones),
                -len(canonical_zones),
                -(lineage not in seen_lineages),
                -len(media - covered_media),
                -float(entry.get("source_evidence_score", 0.0)),
                source_id,
            )

        remaining.sort(key=rank)
        chosen = remaining.pop(0)
        source_id = str(chosen["source_id"])
        zones = {item.partition(":")[2] for item in source_coverage_zones(source_id)}
        media = {str(item) for item in chosen.get("matching_media", [])}
        covered_pairs.update((zone, medium) for zone in zones for medium in media)
        covered_zones.update(zones)
        covered_media.update(media)
        seen_lineages.add(source_adapters.source_lineage_id(source_id))
        ordered.append(chosen)
    return ordered


def source_budgets(
    source_ids: Sequence[str],
    maximum_records: int,
    analyte_count: int = 1,
    per_analyte_observations: int = DEFAULT_PER_ANALYTE_OBSERVATIONS,
    elements: Sequence[str] | None = None,
) -> dict[str, int]:
    """Divide the record ceiling by what each source would actually take.

    An even or proportional split starves finite regional surveys whenever a
    few open-ended global archives dominate demand.  Each source first receives
    its executable minimum.  Verified finite surveys are then completed from
    smallest to largest, maximizing fully represented independent datasets;
    only the remaining ceiling is distributed proportionally across open-ended
    sources.  No source can receive more than its current-round demand.
    """

    ordered = list(source_ids)
    if not ordered:
        raise RequestRunError(
            "unsupported_scope", "source route selected no executable source"
        )
    if analyte_count < 1:
        raise RequestRunError(
            "invalid_input", "source budget requires at least one analyte"
        )
    minimums = {
        source_id: minimum_source_records(source_id, analyte_count)
        for source_id in ordered
    }
    required = sum(minimums.values())
    if maximum_records < required:
        raise RequestRunError(
            "unsupported_scope",
            f"max_records={maximum_records} is below the {required}-record executable minimum "
            f"for {len(ordered)} selected sources",
        )
    demands: dict[str, int] = {}
    for source_id in ordered:
        matched = (
            supported_request_analytes(source_id, elements)
            if elements is not None
            else None
        )
        demand = planned_slice_observations(
            source_id,
            len(matched) if matched else analyte_count,
            GENERATOR_MAX_OBSERVATIONS,
            per_analyte_observations,
            matched,
        )
        demands[source_id] = max(int(demand), minimums[source_id])
    total_demand = sum(demands.values())
    if total_demand <= maximum_records:
        return demands
    budgets = dict(minimums)
    remaining = maximum_records - required

    def finite_round_source(source_id: str) -> bool:
        matched = (
            supported_request_analytes(source_id, elements)
            if elements is not None
            else None
        )
        capacity = declared_slice_capacity(source_id, matched)
        return (
            source_id in FIXED_SLICE_OBSERVATIONS
            or source_id in SLICE_DIVISORS
            or source_id in VARIABLE_ANALYTE_CAPACITY_SOURCES
            or (capacity is not None and capacity < GENERATOR_MAX_OBSERVATIONS)
        )

    finite_sources = sorted(
        (source_id for source_id in ordered if finite_round_source(source_id)),
        key=lambda source_id: (demands[source_id], source_id),
    )
    for source_id in finite_sources:
        extra = demands[source_id] - budgets[source_id]
        allocation = min(extra, remaining)
        budgets[source_id] += allocation
        remaining -= allocation
        if remaining <= 0:
            return budgets

    open_sources = [
        source_id for source_id in ordered if source_id not in set(finite_sources)
    ]
    open_surplus = sum(demands[item] - budgets[item] for item in open_sources)
    if remaining and open_surplus:
        for source_id in open_sources:
            extra = demands[source_id] - budgets[source_id]
            budgets[source_id] += extra * remaining // open_surplus
        leftover = maximum_records - sum(budgets.values())
        for source_id in sorted(
            open_sources, key=lambda item: (budgets[item] - demands[item], item)
        ):
            if leftover <= 0:
                break
            if budgets[source_id] < demands[source_id]:
                budgets[source_id] += 1
                leftover -= 1
    return budgets


def plan_auto_sources(
    route_entries: Sequence[Mapping[str, Any]],
    maximum_records: int,
    analyte_count: int,
) -> tuple[list[str], list[str]]:
    """Choose the broadest evidence-ranked executable subset within a record ceiling."""

    entries = coverage_balanced_source_order(route_entries)
    source_ids = [str(entry["source_id"]) for entry in entries]
    minimums = {
        source_id: minimum_source_records(source_id, analyte_count)
        for source_id in source_ids
    }
    if sum(minimums.values()) <= maximum_records:
        return source_ids, []
    selected: list[str] = []
    covered_pairs: set[tuple[str, str]] = set()
    covered_zones: set[str] = set()
    covered_media: set[str] = set()
    seen_lineages: set[str] = set()
    requested_media = {
        str(medium) for entry in entries for medium in entry.get("matching_media", [])
    }
    remaining = list(entries)
    capacity = maximum_records
    while remaining:
        affordable = [
            entry
            for entry in remaining
            if minimums[str(entry["source_id"])] <= capacity
        ]
        if not affordable:
            break
        missing_media = requested_media - covered_media

        def subset_rank(entry: Mapping[str, Any]) -> tuple[Any, ...]:
            source_id = str(entry["source_id"])
            zones = {
                item.partition(":")[2] for item in source_coverage_zones(source_id)
            }
            media = {str(item) for item in entry.get("matching_media", [])}
            pairs = {(zone, medium) for zone in zones for medium in media}
            lineage = source_adapters.source_lineage_id(source_id)
            return (
                -len(media & missing_media),
                -len(pairs - covered_pairs),
                -len(zones - covered_zones),
                -(lineage not in seen_lineages),
                -float(entry.get("source_evidence_score", 0.0)),
                minimums[source_id],
                source_id,
            )

        affordable.sort(key=subset_rank)
        chosen = affordable[0]
        source_id = str(chosen["source_id"])
        selected.append(source_id)
        capacity -= minimums[source_id]
        zones = {item.partition(":")[2] for item in source_coverage_zones(source_id)}
        media = {str(item) for item in chosen.get("matching_media", [])}
        covered_pairs.update((zone, medium) for zone in zones for medium in media)
        covered_zones.update(zones)
        covered_media.update(media)
        seen_lineages.add(source_adapters.source_lineage_id(source_id))
        remaining = [entry for entry in remaining if entry["source_id"] != source_id]
    if not selected:
        minimum = min(minimums.values()) if minimums else 1
        raise RequestRunError(
            "unsupported_scope",
            f"max_records={maximum_records} cannot fund the smallest routed source minimum ({minimum})",
        )
    skipped = [source_id for source_id in source_ids if source_id not in set(selected)]
    return selected, skipped


def rotate_source_order(source_ids: Sequence[str], offset: int) -> list[str]:
    """Rotate a complete acquisition queue without dropping any source.

    Coverage balancing chooses the first-round order. Later controller rounds
    rotate that same order so a finite fair-share deadline cannot starve the
    same tail sources repeatedly. Execution progress persists the effective
    order and the requested offset for audit.
    """

    ordered = [str(source_id) for source_id in source_ids]
    if offset < 0:
        raise RequestRunError(
            "invalid_input", "--source-order-offset must be a non-negative integer"
        )
    if not ordered:
        return []
    normalized_offset = offset % len(ordered)
    return ordered[normalized_offset:] + ordered[:normalized_offset]


def prioritize_source_order(
    source_ids: Sequence[str], priority_source_ids: Sequence[str]
) -> tuple[list[str], list[str]]:
    """Move routed gap-repair sources to the front without changing membership.

    The self-correction controller derives ``priority_source_ids`` from the
    preceding round's machine-audited repair plan.  Keeping this operation
    separate from routing is important: a gap target may change scheduling,
    but it cannot make an incompatible or unregistered source executable.
    Missing priority IDs are returned for explicit audit rather than silently
    ignored.
    """

    ordered = list(dict.fromkeys(str(source_id) for source_id in source_ids))
    priorities = list(
        dict.fromkeys(str(source_id) for source_id in priority_source_ids if source_id)
    )
    available = set(ordered)
    applied = [source_id for source_id in priorities if source_id in available]
    missing = [source_id for source_id in priorities if source_id not in available]
    applied_set = set(applied)
    return applied + [item for item in ordered if item not in applied_set], missing


def request_visualization_profile(
    request: Mapping[str, Any], resolved_region: Mapping[str, Any]
) -> dict[str, Any]:
    """Translate the frozen public request into the D3 profile used by the full workflow."""

    profile = read_json(
        SKILL_DIR / "assets" / "visualization-profile.template.json",
        "default visualization profile",
    )
    if resolved_region["key"] != "global":
        spatial_domains = request.get("spatial_domains") or ["land"]
        analysis_bbox = spatial_scope.request_analysis_bbox(
            resolved_region,
            spatial_domains,
            float(request.get("adjacent_marine_distance_km") or 0),
        )
        west, south, east, north = analysis_bbox
        adjacent_marine = bool(
            resolved_region.get("country_code") and "marine" in spatial_domains
        )
        analysis_country_codes = list(
            resolved_region.get("analysis_country_codes") or []
        )
        multi_country_analysis = len(analysis_country_codes) > 1
        profile["spatial_scope"] = "regional"
        profile["default_region"] = "custom"
        profile["custom_region"] = {
            "label": (
                f"{resolved_region['label']}陆地与邻近海洋分析域"
                if adjacent_marine
                else str(resolved_region["label"])
            ),
            "bounds": {"w": west, "s": south, "e": east, "n": north},
            # D1 already performed the domain-aware polygon/distance gate. A
            # second strict Admin-0 clip in D3 would erase accepted sea rows.
            "country_code": (
                None
                if adjacent_marine or multi_country_analysis
                else resolved_region.get("country_code")
            ),
        }
        profile["title"] = f"{resolved_region['label']}地球化学元素图谱"
        if adjacent_marine:
            profile["subtitle"] = (
                f"范围 = 冻结 Admin-0 陆地边界 + 距其边界不超过 "
                f"{request.get('adjacent_marine_distance_km')} km 的来源明确标注海洋观测；"
                "该分析缓冲区不表示领海、EEZ 或主权边界。"
            )
        if resolved_region.get("cartographic_reference"):
            reference = resolved_region["cartographic_reference"]
            profile["subtitle"] = (
                f"{profile.get('subtitle', '')} 科学点位筛选包含 "
                f"{','.join(analysis_country_codes)} 分析单元；这不是法定或主权边界。"
                f"中国完整制图以自然资源部标准地图 {reference['review_number']} 为准。"
            ).strip()
    if len(request["elements"]) == 1:
        profile["filters"]["element"] = request["elements"][0]
    if len(request["media"]) == 1:
        profile["filters"]["medium"] = request["media"][0]
    if len(request.get("geology_units") or []) == 1:
        profile["filters"]["geology"] = request["geology_units"][0]
    return profile


def merge_acquired_sources(
    acquisitions: Sequence[Mapping[str, Any]],
    output_input: Path,
    output_evidence: Path,
    output_manifest: Path,
    request: Mapping[str, Any],
    generated_at: str,
    acquisition_mode: str,
) -> tuple[int, dict[str, Any]]:
    """Merge verified source bundles without losing per-source manifests or hashes."""

    headers: list[str] = []
    merged_rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    record_ids: set[str] = set()
    evidence_ids: set[str] = set()
    source_files: list[dict[str, Any]] = []
    source_manifests: list[dict[str, Any]] = []
    not_for_science = False
    for acquisition in acquisitions:
        source_id = str(acquisition["source_id"])
        root = Path(acquisition["directory"])
        input_path = root / "demo_input.csv"
        evidence_path = root / "sources.jsonl"
        manifest_path = root / "run_manifest.json"
        verify_manifest_outputs(manifest_path, [input_path, evidence_path])
        manifest = read_json(manifest_path, f"{source_id} source manifest")
        not_for_science = not_for_science or bool(
            manifest.get("not_for_scientific_interpretation", False)
        )
        source_manifests.append(
            {
                "source_id": source_id,
                "filename": manifest_path.name,
                "sha256": sha256_file(manifest_path),
                "record_count": int(acquisition["record_count"]),
            }
        )
        manifest_files = manifest.get("source_files")
        if not isinstance(manifest_files, list) or not manifest_files:
            raise RequestRunError(
                "conflicting_evidence",
                f"{source_id} source manifest has no source_files",
            )
        filename_map: dict[str, str] = {}
        for item in manifest_files:
            if not isinstance(item, Mapping) or not isinstance(
                item.get("filename"), str
            ):
                raise RequestRunError(
                    "conflicting_evidence",
                    f"{source_id} source manifest has invalid source_files",
                )
            original = str(item["filename"])
            namespaced = f"{source_id}--{original}"
            filename_map[original] = namespaced
            source_files.append(
                {**dict(item), "filename": namespaced, "source_id": source_id}
            )

        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            source_headers = list(reader.fieldnames or [])
            if not source_headers:
                raise RequestRunError(
                    "conflicting_evidence", f"{source_id} CSV has no header"
                )
            for field in source_headers:
                if field not in headers:
                    headers.append(field)
            for raw in reader:
                row = dict(raw)
                if row.get("source_id") != source_id:
                    raise RequestRunError(
                        "conflicting_evidence",
                        f"{source_id} CSV contains another source_id",
                    )
                record_id = str(row.get("record_id") or "")
                if not record_id or record_id in record_ids:
                    raise RequestRunError(
                        "conflicting_evidence",
                        "multi-source CSV has missing or duplicate record_id",
                    )
                record_ids.add(record_id)
                source_file = str(row.get("source_file") or "")
                if source_file and source_file not in filename_map:
                    raise RequestRunError(
                        "conflicting_evidence",
                        f"{source_id} CSV references source_file absent from its manifest",
                    )
                if source_file:
                    row["source_file"] = filename_map[source_file]
                merged_rows.append(row)

        try:
            lines = evidence_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise RequestRunError(
                "conflicting_evidence", f"{source_id} evidence JSONL is unreadable"
            ) from exc
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RequestRunError(
                    "conflicting_evidence",
                    f"{source_id} evidence line {line_number} is invalid",
                ) from exc
            if not isinstance(item, dict) or item.get("source_id") != source_id:
                raise RequestRunError(
                    "conflicting_evidence",
                    f"{source_id} evidence contains another source_id",
                )
            record_id = str(item.get("record_id") or "")
            if not record_id or record_id in evidence_ids:
                raise RequestRunError(
                    "conflicting_evidence",
                    "multi-source evidence has missing or duplicate record_id",
                )
            evidence_ids.add(record_id)
            source_file = str(item.get("source_file") or "")
            if source_file and source_file not in filename_map:
                raise RequestRunError(
                    "conflicting_evidence",
                    f"{source_id} evidence references source_file absent from its manifest",
                )
            if source_file:
                item["source_file"] = filename_map[source_file]
            evidence_rows.append(item)
    if record_ids != evidence_ids:
        raise RequestRunError(
            "conflicting_evidence",
            "merged multi-source CSV and evidence record IDs differ",
        )

    output_input.parent.mkdir(parents=True, exist_ok=True)
    with output_input.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for row in merged_rows:
            writer.writerow({field: row.get(field, "") for field in headers})
    output_evidence.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for item in evidence_rows
        ),
        encoding="utf-8",
    )
    manifest = {
        "request_multi_source_manifest_version": "geochemical-multi-source-acquisition-v1",
        "generated_at": generated_at,
        "data_mode": acquisition_mode,
        "not_for_scientific_interpretation": not_for_science,
        "request": dict(request),
        "source_manifests": source_manifests,
        "source_files": source_files,
        "outputs": [
            {
                "path": output_input.name,
                "bytes": output_input.stat().st_size,
                "sha256": sha256_file(output_input),
            },
            {
                "path": output_evidence.name,
                "bytes": output_evidence.stat().st_size,
                "sha256": sha256_file(output_evidence),
            },
        ],
        "failures": [],
    }
    write_json(output_manifest, manifest)
    return len(merged_rows), manifest


def effective_coordinate_mode(
    requested_mode: str, demo: str | None, route: Mapping[str, Any]
) -> str:
    """Resolve auto without promoting reported coordinates to canonical WGS84."""

    if requested_mode != "auto":
        return requested_mode
    selected = route.get("selected_sources", [])
    has_reported_only_profile = False
    for item in selected:
        source_id = str(item.get("source_id") or "")
        if not source_id:
            continue
        profile_path = (
            SKILL_DIR
            / "assets"
            / "v4-full-profiles"
            / source_id
            / "spatial_coverage.json"
        )
        try:
            profile = read_json(profile_path, f"{source_id} spatial profile")
            reported = int(profile.get("reported_coordinate_sample_count") or 0)
            canonical = int(profile.get("valid_coordinate_sample_count") or 0)
        except (RequestRunError, TypeError, ValueError):
            continue
        if reported > 0 and canonical == 0:
            has_reported_only_profile = True
            break
    if (
        demo == "china"
        or has_reported_only_profile
        or any(
            ((item.get("request_compatibility") or {}).get("region") or {}).get(
                "status"
            )
            == "compatible_reported_only"
            for item in selected
        )
    ):
        return "reported"
    return "canonical"


def run(args: argparse.Namespace) -> dict[str, Any]:
    skill_tree_capture = skill_snapshot.capture_skill_tree(SKILL_DIR)
    skill_snapshot_start = skill_tree_capture.snapshot
    if args.input is None and args.online_source is None and args.demo is None:
        # Research requests acquire real source data by default.  A fixture is
        # only selected by an explicit --demo flag.
        args.online_source = "auto"
    if (
        args.online_source is not None
        and args.analysis_profile == "production"
        and not args.controller_round
        and not args.allow_single_round_partial
    ):
        raise RequestRunError(
            "invalid_input",
            "production online atlas requests must run through "
            "run_self_correction_loop.py; pass --allow-single-round-partial only "
            "when the caller explicitly accepts an insufficient one-round result",
        )
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RequestRunError(
            "invalid_input", "output directory must be absent or empty"
        )
    if (args.batch_qc_input is None) != (args.batch_qc_policy is None):
        raise RequestRunError(
            "invalid_input",
            "--batch-qc-input and --batch-qc-policy must be supplied together",
        )
    if (
        not 1
        <= args.source_timeout_seconds
        <= execution_budget.MAX_INTERNAL_BUDGET_SECONDS
    ):
        raise RequestRunError(
            "invalid_input",
            f"--source-timeout-seconds must be between 1 and {execution_budget.MAX_INTERNAL_BUDGET_SECONDS:g}",
        )
    if args.source_order_offset < 0:
        raise RequestRunError(
            "invalid_input", "--source-order-offset must be a non-negative integer"
        )
    try:
        deadline = execution_budget.ExecutionBudget(args.total_timeout_seconds)
    except execution_budget.ExecutionBudgetError as exc:
        raise RequestRunError("invalid_input", str(exc)) from exc
    if not 5 <= args.workflow_reserve_seconds < deadline.total_seconds:
        raise RequestRunError(
            "invalid_input",
            "--workflow-reserve-seconds must be at least 5 and below the total timeout",
        )
    catalog = source_router.load_catalog()
    registry = source_adapters.load_source_registry()
    request = source_router.validate_request(
        read_json(args.request, "request"), catalog
    )
    try:
        resolved_region = spatial_scope.resolve_region(request["region"])
    except spatial_scope.SpatialScopeError as exc:
        raise RequestRunError("needs_human_review", str(exc)) from exc
    route = source_router.route_sources(request, catalog, registry)
    coordinate_mode = effective_coordinate_mode(args.coordinate_mode, args.demo, route)
    matrix = coverage_report.build_matrix(catalog, request, registry)
    write_static_request_evidence(args.output_dir, request, route, matrix)
    source_outcomes: list[dict[str, Any]] = []
    acquisition_warnings: list[str] = []
    source_child_manifests: list[tuple[str, Path]] = []
    retained_acquisition_manifests: list[dict[str, Any]] = []
    requested_ids: list[str] = []
    geology_filter_grid = _load_request_geology_grid(
        request,
        args.geology_grid,
        args.geology_grid_sha256,
        args.no_geology,
    )

    generated_at = args.generated_at or datetime.now(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")
    with tempfile.TemporaryDirectory(prefix="geochemical-request-") as temporary:
        work = Path(temporary)
        source_input: Path
        source_evidence: Path | None
        source_manifest: Path | None
        mode: str
        if args.input is not None:
            source_input = args.input
            source_evidence = args.evidence_jsonl
            source_manifest = args.acquisition_manifest
            mode = "provided_input"
        elif args.online_source is not None:
            if request["offline"]:
                raise RequestRunError(
                    "network_unavailable",
                    "online acquisition cannot run with request offline=true",
                )
            selected_ids = [item["source_id"] for item in route["selected_sources"]]
            if args.online_source == "auto":
                requested_ids, skipped_ids = plan_auto_sources(
                    route["selected_sources"],
                    int(request["max_records"]),
                    len(request["elements"]),
                )
                if skipped_ids:
                    acquisition_warnings.append(
                        "record budget omitted routed sources: "
                        + ", ".join(skipped_ids)
                    )
                requested_ids = rotate_source_order(
                    requested_ids, args.source_order_offset
                )
                if args.source_order_offset:
                    acquisition_warnings.append(
                        "coverage-balanced acquisition order rotated by "
                        f"{args.source_order_offset} position(s) before modulo "
                        "normalization so deferred tail sources receive an early "
                        "attempt in later controller rounds"
                    )
                requested_ids, missing_priority_ids = prioritize_source_order(
                    requested_ids, args.priority_source_id
                )
                if args.priority_source_id:
                    acquisition_warnings.append(
                        "previous-round gap repair moved routed sources to the front: "
                        + ", ".join(
                            source_id
                            for source_id in args.priority_source_id
                            if source_id in set(requested_ids)
                        )
                    )
                if missing_priority_ids:
                    acquisition_warnings.append(
                        "gap-priority sources were not executable in this frozen route or "
                        "were omitted by its record ceiling: "
                        + ", ".join(missing_priority_ids)
                    )
            else:
                requested_ids = [args.online_source]
            unknown = sorted(set(requested_ids) - set(selected_ids))
            if unknown:
                raise RequestRunError(
                    "unsupported_scope",
                    f"source(s) {unknown} are not compatible with the frozen request route",
                )
            budgets = source_budgets(
                requested_ids,
                int(request["max_records"]),
                len(request["elements"]),
                per_analyte_observations=args.per_analyte_observations,
                elements=request["elements"],
            )
            successful: list[dict[str, Any]] = []
            for source_index, source_id in enumerate(requested_ids):
                acquired = work / "acquired" / source_id
                source_request = dict(request)
                source_request["max_records"] = budgets[source_id]
                try:
                    remaining_source_count = len(requested_ids) - source_index
                    acquisition_window = deadline.child_timeout(
                        f"source acquisition {source_id}",
                        reserve_seconds=args.workflow_reserve_seconds,
                        minimum_seconds=1.0,
                    )
                    source_timeout = min(
                        float(args.source_timeout_seconds),
                        acquisition_window / remaining_source_count,
                    )
                    if source_timeout < MIN_SOURCE_TIMEOUT_SECONDS:
                        if acquisition_window >= MIN_SOURCE_TIMEOUT_SECONDS:
                            # Borrow from later sources' shares rather than
                            # launching a doomed sub-minute attempt.
                            source_timeout = min(
                                float(args.source_timeout_seconds),
                                MIN_SOURCE_TIMEOUT_SECONDS,
                            )
                        else:
                            raise RequestRunError(
                                "incomplete_retrieval",
                                f"deferred: remaining acquisition window "
                                f"{acquisition_window:.1f}s is below the "
                                f"{MIN_SOURCE_TIMEOUT_SECONDS:.0f}s per-source "
                                "budget floor; retry in the next round",
                            )
                    if source_timeout < float(args.source_timeout_seconds):
                        acquisition_warnings.append(
                            f"global deadline capped {source_id} acquisition at {source_timeout:.3f}s"
                        )
                    acquire_online_source(
                        source_id,
                        source_request,
                        args.cache_dir,
                        acquired,
                        args.acquisition_mode,
                        generated_at,
                        timeout_seconds=source_timeout,
                        per_analyte_observations=args.per_analyte_observations,
                        region_bbox=(
                            spatial_scope.request_analysis_bbox(
                                resolved_region,
                                request.get("spatial_domains"),
                                float(request.get("adjacent_marine_distance_km") or 0),
                            )
                            if resolved_region["key"] != "global"
                            else None
                        ),
                    )
                    verify_manifest_outputs(
                        acquired / "run_manifest.json",
                        [acquired / "demo_input.csv", acquired / "sources.jsonl"],
                    )
                    with (acquired / "demo_input.csv").open(
                        "r", encoding="utf-8-sig", newline=""
                    ) as handle:
                        record_count = sum(1 for _ in csv.DictReader(handle))
                    if record_count == 0:
                        raise RequestRunError(
                            "incomplete_retrieval",
                            f"source acquisition returned zero rows for {source_id}",
                        )
                    if record_count > budgets[source_id]:
                        raise RequestRunError(
                            "conflicting_evidence",
                            f"source acquisition exceeded its {budgets[source_id]}-record allocation for {source_id}",
                        )
                    outcome = {
                        "source_id": source_id,
                        "status": "success",
                        "allocated_max_records": budgets[source_id],
                        "record_count": record_count,
                        "manifest_sha256": sha256_file(acquired / "run_manifest.json"),
                        "error": None,
                    }
                    source_outcomes.append(outcome)
                    source_child_manifests.append(
                        (source_id, acquired / "run_manifest.json")
                    )
                    successful.append(
                        {
                            "source_id": source_id,
                            "directory": acquired,
                            "record_count": record_count,
                        }
                    )
                    write_execution_progress(
                        args.output_dir,
                        source_outcomes,
                        requested_ids,
                        acquisition_warnings,
                        source_order_offset=args.source_order_offset,
                        priority_source_ids=args.priority_source_id,
                    )
                except (
                    OSError,
                    ValueError,
                    RequestRunError,
                    execution_budget.ExecutionBudgetError,
                ) as exc:
                    source_outcomes.append(
                        {
                            "source_id": source_id,
                            "status": "failed",
                            "allocated_max_records": budgets[source_id],
                            "record_count": 0,
                            "manifest_sha256": None,
                            "error": str(exc),
                        }
                    )
                    acquisition_warnings.append(f"source {source_id} failed: {exc}")
                    write_execution_progress(
                        args.output_dir,
                        source_outcomes,
                        requested_ids,
                        acquisition_warnings,
                        source_order_offset=args.source_order_offset,
                        priority_source_ids=args.priority_source_id,
                    )
            failed_ids = [
                item["source_id"]
                for item in source_outcomes
                if item["status"] == "failed"
            ]
            if failed_ids and args.require_all_sources:
                raise RequestRunError(
                    "incomplete_retrieval",
                    f"required source acquisition failed: {failed_ids}",
                    evidence={
                        "source_outcomes": source_outcomes,
                        "requested_source_ids": requested_ids,
                        "acquisition_warnings": acquisition_warnings,
                    },
                )
            if not successful:
                raise RequestRunError(
                    "incomplete_retrieval",
                    "all routed source acquisitions failed",
                    evidence={
                        "source_outcomes": source_outcomes,
                        "requested_source_ids": requested_ids,
                        "acquisition_warnings": acquisition_warnings,
                    },
                )
            source_input = work / "merged" / "multi_source_input.csv"
            source_evidence = work / "merged" / "multi_source_evidence.jsonl"
            source_manifest = work / "merged" / "multi_source_manifest.json"
            merge_acquired_sources(
                successful,
                source_input,
                source_evidence,
                source_manifest,
                request,
                generated_at,
                args.acquisition_mode,
            )
            mode = (
                "online_sources:auto"
                if args.online_source == "auto"
                else f"online_source:{args.online_source}"
            )
        else:
            fixture = {
                "production-usgs": PRODUCTION_FIXTURE,
                "four-media": FOUR_MEDIA_FIXTURE,
                "china": CHINA_FIXTURE,
            }[args.demo]
            source_input = fixture / "demo_input.csv"
            source_evidence = fixture / "sources.jsonl"
            source_manifest = fixture / "run_manifest.json"
            mode = f"fixture:{args.demo}"

        if source_manifest is not None:
            bound_paths = [source_input]
            if source_evidence is not None:
                bound_paths.append(source_evidence)
            verify_manifest_outputs(source_manifest, bound_paths)

        filtered_input = work / "request_input.csv"
        filtered_evidence = (
            work / "request_evidence.jsonl" if source_evidence is not None else None
        )
        original_count, selected_count, warnings = filter_bundle(
            source_input,
            source_evidence,
            request,
            filtered_input,
            filtered_evidence,
            geology_grid=geology_filter_grid,
            coordinate_mode=coordinate_mode,
        )
        warnings = acquisition_warnings + warnings
        request_coverage, coverage_warnings = request_dimension_coverage(
            filtered_input, request
        )
        warnings.extend(coverage_warnings)
        filtered_acquisition: Path | None = None
        if source_manifest is not None and filtered_evidence is not None:
            filtered_acquisition = work / "request_manifest.json"
            write_json(
                filtered_acquisition,
                filtered_manifest(
                    source_manifest,
                    filtered_input,
                    filtered_evidence,
                    request,
                    original_count,
                    selected_count,
                ),
            )

        retained_acquisition_manifests = retain_acquisition_manifests(
            args.output_dir,
            filtered_acquisition,
            source_manifest,
            source_child_manifests,
        )
        failure_evidence = {
            "failure_evidence_version": "geochemical-request-failure-evidence-v1",
            "stage": "d2_d3_workflow",
            "mode": mode,
            "requested_source_ids": requested_ids,
            "source_outcomes": source_outcomes,
            "acquisition_warnings": warnings,
            "acquisition_manifests": retained_acquisition_manifests,
            "route_status": route.get("status"),
            "coverage_status": matrix.get("overall_status"),
            "request_coverage": request_coverage,
            "coordinate_mode": {
                "requested": args.coordinate_mode,
                "effective": coordinate_mode,
            },
            "record_counts": {
                "before_request_filters": original_count,
                "after_request_filters": selected_count,
            },
        }

        command = [
            sys.executable,
            str(WORKFLOW),
            "--input",
            str(filtered_input),
            "--output-dir",
            str(args.output_dir),
            "--analysis-profile",
            args.analysis_profile,
            "--max-records",
            str(request["max_records"]),
            "--coordinate-mode",
            coordinate_mode,
        ]
        if filtered_evidence is not None:
            command.extend(["--evidence-jsonl", str(filtered_evidence)])
        if filtered_acquisition is not None:
            command.extend(["--acquisition-manifest", str(filtered_acquisition)])
        command.extend(
            [
                "--source-route",
                str(args.output_dir / "request_evidence" / "source_route.json"),
            ]
        )
        if isinstance(request["region"], dict):
            command.append(
                "--region-bbox="
                + ",".join(
                    str(item)
                    for item in spatial_scope.request_analysis_bbox(
                        resolved_region,
                        request.get("spatial_domains"),
                        float(request.get("adjacent_marine_distance_km") or 0),
                    )
                )
            )
        elif resolved_region["key"] != "global":
            command.append(
                "--region-bbox="
                + ",".join(
                    str(item)
                    for item in spatial_scope.request_analysis_bbox(
                        resolved_region,
                        request.get("spatial_domains"),
                        float(request.get("adjacent_marine_distance_km") or 0),
                    )
                )
            )
        visualization_profile = work / "visualization-profile.json"
        write_json(
            visualization_profile,
            request_visualization_profile(request, resolved_region),
        )
        command.extend(["--visualization-profile", str(visualization_profile)])
        if not args.no_geology:
            command.extend(
                [
                    "--geology-grid",
                    str(args.geology_grid),
                    "--geology-grid-sha256",
                    args.geology_grid_sha256,
                ]
            )
        if args.batch_qc_input is not None:
            command.extend(
                [
                    "--batch-qc-input",
                    str(args.batch_qc_input),
                    "--batch-qc-policy",
                    str(args.batch_qc_policy),
                ]
            )
        command.extend(
            [
                "--spatial-grid-degrees",
                str(args.spatial_grid_degrees),
                "--min-spatial-candidates",
                str(args.min_spatial_candidates),
                "--spatial-fdr-alpha",
                str(args.spatial_fdr_alpha),
            ]
        )
        if args.min_spatial_samples is not None:
            command.extend(["--min-spatial-samples", str(args.min_spatial_samples)])
        try:
            workflow_timeout = deadline.child_timeout(
                "D2/D3 workflow",
                reserve_seconds=5.0,
                minimum_seconds=1.0,
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=workflow_timeout,
            )
        except execution_budget.ExecutionBudgetError as exc:
            raise RequestRunError(
                "incomplete_retrieval", str(exc), evidence=failure_evidence
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RequestRunError(
                "incomplete_retrieval",
                f"D2/D3 workflow exhausted the global execution deadline after {workflow_timeout:.3f}s",
                evidence={
                    **failure_evidence,
                    "workflow_timeout_seconds": workflow_timeout,
                },
            ) from exc
        if result.returncode:
            raise RequestRunError(
                "incomplete_retrieval",
                f"D2/D3 workflow failed: {(result.stderr or result.stdout).strip()}",
                evidence={
                    **failure_evidence,
                    "workflow_exit_code": result.returncode,
                    "workflow_stderr_tail": (result.stderr or "")[-4000:],
                    "workflow_stdout_tail": (result.stdout or "")[-4000:],
                },
            )
    request_evidence = args.output_dir / "request_evidence"
    workflow_summary_path = args.output_dir / "run_summary.json"
    workflow_summary = read_json(workflow_summary_path, "workflow run summary")
    execution_coverage_status = (
        "partial"
        if mode.startswith("fixture:")
        or any(item.get("status") == "failed" for item in source_outcomes)
        else matrix["overall_status"]
    )
    execution_partial = (
        workflow_summary.get("status") == "partial_success"
        or route["status"] != "ready"
        or execution_coverage_status != "covered"
        or request_coverage["status"] != "complete"
        or bool(warnings)
    )
    if deadline.remaining_seconds <= 0:
        raise RequestRunError(
            "incomplete_retrieval",
            "global execution budget was exhausted during final evidence packaging",
        )
    skill_snapshot_verification = skill_snapshot.verify_skill_tree_unchanged(
        SKILL_DIR, skill_tree_capture
    )
    skill_snapshot_end = skill_snapshot_verification["snapshot"]
    skill_snapshot_stable = skill_snapshot_verification["stable"]
    if not skill_snapshot_stable:
        raise RequestRunError(
            "conflicting_evidence",
            "Skill files changed during request execution; discard this round and rerun from a stable snapshot",
            evidence={
                "skill_snapshot_start": skill_snapshot_start,
                "skill_snapshot_end": skill_snapshot_end,
                "changed_paths": skill_snapshot_verification["changed_paths"],
            },
        )
    execution = {
        "execution_version": "geochemical-request-execution-v6",
        "status": "partial_success" if execution_partial else "success",
        "mode": mode,
        "analysis_profile": args.analysis_profile,
        "coordinate_mode": {
            "requested": args.coordinate_mode,
            "effective": coordinate_mode,
        },
        "timing": {
            "official_task_limit_seconds": execution_budget.OFFICIAL_TASK_LIMIT_SECONDS,
            "internal_budget_seconds": deadline.total_seconds,
            "workflow_reserve_seconds": float(args.workflow_reserve_seconds),
            "elapsed_seconds": round(deadline.elapsed_seconds, 3),
            "completed_within_internal_budget": deadline.remaining_seconds > 0,
            "deadline_policy": "single_monotonic_deadline_v1",
        },
        "skill_snapshot": {
            "algorithm": skill_snapshot_start["algorithm"],
            "start_sha256": skill_snapshot_start["sha256"],
            "end_sha256": skill_snapshot_end["sha256"],
            "stable_during_execution": skill_snapshot_stable,
            "file_count": skill_snapshot_start["file_count"],
            "total_bytes": skill_snapshot_start["total_bytes"],
            "stability_verification": skill_snapshot_verification["verification"],
        },
        "geology_grid": None
        if args.no_geology
        else {
            "filename": args.geology_grid.name,
            "sha256": args.geology_grid_sha256,
        },
        "record_counts": {
            "before_request_filters": original_count,
            "after_request_filters": selected_count,
        },
        "source_outcomes": source_outcomes,
        "acquisition_scheduler": {
            "policy": "gap-priority-then-coverage-balanced-round-robin-v2",
            "source_order_offset": args.source_order_offset,
            "priority_source_ids": list(args.priority_source_id),
            "effective_source_ids": requested_ids,
        },
        "acquisition_manifests": retained_acquisition_manifests,
        "route_status": route["status"],
        "coverage_status": matrix["overall_status"],
        "route_resolution": (
            "offline_fixture_hash_verified"
            if mode.startswith("fixture:")
            else "routed_multi_source_evidence_verified"
            if mode == "online_sources:auto"
            else "routed_source_evidence_verified"
            if mode.startswith("online_source:")
            else "provided_input_processed"
        ),
        "execution_coverage_status": execution_coverage_status,
        "request_coverage": request_coverage,
        "warnings": warnings,
    }
    if execution_partial and workflow_summary.get("status") == "success":
        workflow_summary["status"] = "partial_success"
        limitations = workflow_summary.setdefault("limitations", [])
        limitations.append(
            "Request execution was partial because route, source acquisition, coverage, or filtering "
            "did not satisfy the full frozen request; inspect request_evidence/execution.json."
        )
        write_json(workflow_summary_path, workflow_summary)
    write_json(request_evidence / "execution.json", execution)
    if args.online_source is not None:
        write_execution_progress(
            args.output_dir,
            source_outcomes,
            requested_ids,
            acquisition_warnings,
            source_order_offset=args.source_order_offset,
            priority_source_ids=args.priority_source_id,
            complete=True,
        )
    return execution


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--input", type=Path, help="Existing CSV to filter and process")
    mode.add_argument(
        "--online-source",
        help="One routed source ID, or 'auto' to acquire and merge every compatible routed source",
    )
    mode.add_argument(
        "--demo",
        choices=("production-usgs", "four-media", "china"),
        help="Explicit deterministic demonstration fixture; never selected by default",
    )
    parser.add_argument("--evidence-jsonl", type=Path)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument(
        "--coordinate-mode",
        choices=("auto", *map_builder.COORDINATE_MODES),
        default="auto",
        help=(
            "auto (default) keeps canonical WGS84 unless a routed regional source is "
            "compatible only by its declared geographic scope; reported additionally "
            "maps reported-only coordinates with an unverified datum and a prominent warning"
        ),
    )
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/data"))
    parser.add_argument(
        "--acquisition-mode", choices=("online", "cached"), default="online"
    )
    parser.add_argument(
        "--per-analyte-observations",
        type=int,
        default=DEFAULT_PER_ANALYTE_OBSERVATIONS,
        help=(
            "Balanced-slice observations requested per analyte for expandable "
            "online sources; bounded by each source's registered capacity, "
            "max_records and the generator limit"
        ),
    )
    parser.add_argument(
        "--source-timeout-seconds",
        type=float,
        default=600.0,
        help="Per-source timeout cap inside the shared request budget (default: 600)",
    )
    parser.add_argument(
        "--source-order-offset",
        type=int,
        default=0,
        help=(
            "Rotate the coverage-balanced auto-source queue by this many positions; "
            "the self-correction loop sets it to prevent tail-source starvation"
        ),
    )
    parser.add_argument(
        "--priority-source-id",
        action="append",
        default=[],
        help=(
            "Move one routed source to the front of this round's acquisition queue; "
            "repeat for multiple machine-audited gap-repair candidates. This changes "
            "scheduling only and never bypasses source routing or the record ceiling."
        ),
    )
    parser.add_argument(
        "--total-timeout-seconds",
        type=float,
        default=execution_budget.OFFICIAL_TASK_LIMIT_SECONDS,
        help=(
            "Monotonic budget for one acquisition/workflow round "
            "(default 900 competition envelope; maximum 43200 only when "
            "explicitly authorized)"
        ),
    )
    parser.add_argument(
        "--workflow-reserve-seconds",
        type=float,
        default=DEFAULT_WORKFLOW_RESERVE_SECONDS,
        help="Capacity protected from online acquisition for D2/D3 and validation (default: 180)",
    )
    parser.add_argument(
        "--require-all-sources",
        action="store_true",
        help="Fail the request instead of returning partial_success when any routed source fails",
    )
    parser.add_argument(
        "--controller-round",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--allow-single-round-partial",
        action="store_true",
        help=(
            "Allow a direct production online round. The result is a partial research "
            "checkpoint and must not replace the self-correction-loop delivery."
        ),
    )
    parser.add_argument(
        "--generated-at", help="ISO-8601 acquisition timestamp; defaults to current UTC"
    )
    parser.add_argument(
        "--analysis-profile", choices=("demo", "production"), default="production"
    )
    parser.add_argument("--geology-grid", type=Path, default=DEFAULT_GEOLOGY_GRID)
    parser.add_argument("--geology-grid-sha256", default=DEFAULT_GEOLOGY_SHA256)
    parser.add_argument("--no-geology", action="store_true")
    parser.add_argument("--batch-qc-input", type=Path)
    parser.add_argument("--batch-qc-policy", type=Path)
    parser.add_argument("--spatial-grid-degrees", type=float, default=2.0)
    parser.add_argument("--min-spatial-samples", type=int)
    parser.add_argument("--min-spatial-candidates", type=int, default=2)
    parser.add_argument("--spatial-fdr-alpha", type=float, default=0.10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output_owned = not args.output_dir.exists() or (
            args.output_dir.is_dir() and not any(args.output_dir.iterdir())
        )
    except OSError:
        output_owned = False
    try:
        result = run(args)
    except (
        OSError,
        ValueError,
        source_router.SourceRoutingError,
        RequestRunError,
    ) as exc:
        status = exc.status if isinstance(exc, RequestRunError) else "invalid_input"
        if output_owned:
            try:
                args.output_dir.mkdir(parents=True, exist_ok=True)
                write_json(
                    args.output_dir / "run_summary.json",
                    request_failure_summary(
                        status,
                        str(exc),
                        args,
                        exc.evidence if isinstance(exc, RequestRunError) else None,
                    ),
                )
                write_json(
                    args.output_dir / "request_evidence" / "execution_failure.json",
                    {
                        "execution_failure_version": "geochemical-request-execution-failure-v1",
                        "status": status,
                        "error": str(exc),
                        "evidence": (
                            exc.evidence if isinstance(exc, RequestRunError) else {}
                        ),
                    },
                )
            except OSError:
                pass
        failure = {"status": status, "error": str(exc)}
        if isinstance(exc, RequestRunError) and exc.evidence:
            failure["evidence"] = exc.evidence
            failure["source_outcomes"] = exc.evidence.get("source_outcomes", [])
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
