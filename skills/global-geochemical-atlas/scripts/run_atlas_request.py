#!/usr/bin/env python3
"""Run request planning, bounded acquisition/input filtering, D2 and D3 in one command."""

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
from pathlib import Path
from typing import Any

import coverage_report
import source_adapters
import source_router


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
GENERATOR = SCRIPT_DIR / "generate_demo_data.py"
PRODUCTION_FIXTURE = SKILL_DIR / "fixtures" / "production-usgs"
FOUR_MEDIA_FIXTURE = SKILL_DIR / "fixtures" / "four-media" / "combined-v3"
DEFAULT_GEOLOGY_GRID = SKILL_DIR / "assets" / "geology" / "pangaea-788537.zip"
DEFAULT_GEOLOGY_SHA256 = "43b4ce3276b155d804db8ff9fb227d620b4c35015a4cf564eac4d06d2b69d88e"
PARAMETERIZED_SOURCES = {"georoc-archaean", "usgs-conus-soil"}


class RequestRunError(RuntimeError):
    """A stable, user-actionable request execution failure."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RequestRunError("invalid_input", f"{label} does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RequestRunError("invalid_input", f"{label} is not valid UTF-8 JSON: {path}") from exc
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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_manifest_outputs(manifest_path: Path, paths: Sequence[Path]) -> None:
    """Verify that a parent acquisition manifest actually binds every supplied file."""

    manifest = read_json(manifest_path, "source acquisition manifest")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise RequestRunError("conflicting_evidence", "source manifest has no outputs hash inventory")
    inventory: dict[str, Mapping[str, Any]] = {}
    for item in outputs:
        if isinstance(item, Mapping) and isinstance(item.get("path"), str):
            inventory[Path(item["path"]).name] = item
    for path in paths:
        evidence = inventory.get(path.name)
        if evidence is None:
            raise RequestRunError(
                "conflicting_evidence", f"source manifest does not bind supplied file: {path.name}"
            )
        actual_hash = sha256_file(path)
        actual_bytes = path.stat().st_size
        if evidence.get("sha256") != actual_hash or evidence.get("bytes") != actual_bytes:
            raise RequestRunError(
                "conflicting_evidence",
                f"source manifest hash/size mismatch for {path.name}",
            )


def _year(value: Any) -> int | None:
    match = re.search(r"(?:^|\D)(\d{4})(?:\D|$)", str(value or ""))
    return int(match.group(1)) if match else None


def _year_bounds(value: Any) -> tuple[int, int] | None:
    years = [int(item) for item in re.findall(r"(?<!\d)(\d{4})(?!\d)", str(value or ""))]
    return (min(years), max(years)) if years else None


def _canonical_coordinate_declared(row: Mapping[str, str]) -> bool:
    source_crs = re.sub(r"\s+", "", str(row.get("source_crs") or "")).casefold()
    transform = str(row.get("coordinate_transform_method") or "").strip()
    return source_crs in {"epsg:4326", "wgs84", "wgs1984", "4326", "ogc:crs84"} or bool(transform)


def _inside_bbox(row: Mapping[str, str], bbox: Sequence[float]) -> bool:
    if not _canonical_coordinate_declared(row):
        return False
    try:
        latitude = float(row.get("latitude") or "")
        longitude = float(row.get("longitude") or "")
    except ValueError:
        return False
    west, south, east, north = bbox
    longitude_inside = west <= longitude <= east if west <= east else longitude >= west or longitude <= east
    return longitude_inside and south <= latitude <= north


def _basis_matches(requested: Sequence[str], actual: str) -> bool:
    return any(source_router.basis_matches(item, actual) for item in requested)


def filter_bundle(
    input_path: Path,
    evidence_path: Path | None,
    request: Mapping[str, Any],
    output_input: Path,
    output_evidence: Path | None,
) -> tuple[int, int, list[str]]:
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [dict(row) for row in reader]
    except (OSError, UnicodeError) as exc:
        raise RequestRunError("invalid_input", f"input CSV is unreadable: {input_path}") from exc
    if not fields or not rows:
        raise RequestRunError("invalid_input", "input CSV must contain a header and at least one record")

    evidence_by_id: dict[str, str] = {}
    if evidence_path is not None:
        try:
            for line in evidence_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = json.loads(line)
                record_id = str(item.get("record_id") or "") if isinstance(item, dict) else ""
                if not record_id or record_id in evidence_by_id:
                    raise RequestRunError("conflicting_evidence", "record evidence has missing or duplicate record_id")
                evidence_by_id[record_id] = line
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RequestRunError("conflicting_evidence", f"record evidence is unreadable: {evidence_path}") from exc

    region = request["region"]
    if isinstance(region, str) and region != "global":
        raise RequestRunError(
            "needs_human_review",
            "named-region execution needs a frozen polygon; use a WGS84 bbox or global scope",
        )
    requested_basis = request.get("measurement_basis")
    requested_time = request.get("time_range")
    requested_sources = request.get("sources")
    start_year = _year(requested_time[0]) if requested_time else None
    end_year = _year(requested_time[1]) if requested_time else None

    selected: list[dict[str, str]] = []
    exclusion_counts: dict[str, int] = {}
    for row in rows:
        reason = None
        if row.get("element_or_analyte") not in request["elements"]:
            reason = "element"
        elif row.get("medium") not in request["media"]:
            reason = "medium"
        elif isinstance(requested_sources, list) and row.get("source_id") not in requested_sources:
            reason = "source"
        elif requested_basis and not _basis_matches(requested_basis, str(row.get("measurement_basis") or "")):
            reason = "measurement_basis"
        elif isinstance(region, dict) and not _canonical_coordinate_declared(row):
            reason = "bbox_unverified_crs"
        elif isinstance(region, dict) and not _inside_bbox(row, region["bbox"]):
            reason = "bbox"
        elif requested_time:
            sample_bounds = _year_bounds(row.get("sampled_at"))
            if (
                sample_bounds is None
                or start_year is None
                or end_year is None
                or start_year > sample_bounds[1]
                or sample_bounds[0] > end_year
            ):
                reason = "time_range"
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
        output_evidence.write_text("".join(evidence_by_id[item] + "\n" for item in ids), encoding="utf-8")
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
        raise RequestRunError("conflicting_evidence", "source manifest has no source_files evidence")
    return {
        "request_run_manifest_version": "geochemical-request-run-v1",
        "data_mode": source.get("data_mode", "fixture"),
        "not_for_scientific_interpretation": bool(source.get("not_for_scientific_interpretation", False)),
        "request": dict(request),
        "filter_counts": {"input": original_count, "selected": selected_count},
        "parent_manifest": {
            "filename": source_manifest_path.name,
            "sha256": sha256_file(source_manifest_path),
        },
        "source_files": source_files,
        "outputs": [
            {"path": input_path.name, "bytes": input_path.stat().st_size, "sha256": sha256_file(input_path)},
            {"path": evidence_path.name, "bytes": evidence_path.stat().st_size, "sha256": sha256_file(evidence_path)},
        ],
        "failures": [],
    }


def acquire_online_source(
    source_id: str,
    request: Mapping[str, Any],
    cache_dir: Path,
    output_dir: Path,
    acquisition_mode: str,
    generated_at: str,
    timeout_seconds: int = 300,
) -> None:
    analytes = [item for item in request["elements"]]
    if source_id == "usgs-conus-soil":
        balance_size = 3 * len(analytes)
        observations = balance_size * 24
    elif source_id == "georoc-archaean":
        balance_size = len(analytes)
        observations = balance_size * 24
    else:
        balance_size = 1
        observations = max(48, len(analytes) * 24)
    observations = min(observations, int(request["max_records"]))
    if balance_size > 1 and observations >= balance_size:
        observations -= observations % balance_size
    command = [
        sys.executable,
        str(GENERATOR),
        "--source", source_id,
        "--cache-dir", str(cache_dir),
        "--output-dir", str(output_dir),
        "--mode", acquisition_mode,
        "--observations", str(observations),
        "--generated-at", generated_at,
    ]
    if source_id in PARAMETERIZED_SOURCES:
        command.extend(["--elements", ",".join(analytes)])
    if source_id == "usgs-conus-soil" and isinstance(request["region"], dict):
        command.extend(["--bbox", ",".join(str(item) for item in request["region"]["bbox"])])
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout_seconds
        )
    except subprocess.TimeoutExpired as exc:
        raise RequestRunError(
            "incomplete_retrieval",
            f"source acquisition timed out after {timeout_seconds}s for {source_id}",
        ) from exc
    if result.returncode:
        raise RequestRunError(
            "incomplete_retrieval",
            f"source acquisition failed for {source_id}: {(result.stderr or result.stdout).strip()}",
        )


def minimum_source_records(source_id: str, analyte_count: int) -> int:
    if source_id == "georoc-archaean":
        return analyte_count
    if source_id == "usgs-conus-soil":
        return 3 * analyte_count
    # The remaining frozen adapters use a 48-observation evidence-balanced
    # slice (some enforce it exactly) before request filtering.
    return 48


def source_budgets(
    source_ids: Sequence[str], maximum_records: int, analyte_count: int = 1
) -> dict[str, int]:
    ordered = list(source_ids)
    if not ordered:
        raise RequestRunError("unsupported_scope", "source route selected no executable source")
    if analyte_count < 1:
        raise RequestRunError("invalid_input", "source budget requires at least one analyte")
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
    quotient, remainder = divmod(maximum_records - required, len(ordered))
    return {
        source_id: minimums[source_id] + quotient + (1 if index < remainder else 0)
        for index, source_id in enumerate(ordered)
    }


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
        source_manifests.append({
            "source_id": source_id,
            "filename": manifest_path.name,
            "sha256": sha256_file(manifest_path),
            "record_count": int(acquisition["record_count"]),
        })
        manifest_files = manifest.get("source_files")
        if not isinstance(manifest_files, list) or not manifest_files:
            raise RequestRunError(
                "conflicting_evidence", f"{source_id} source manifest has no source_files"
            )
        filename_map: dict[str, str] = {}
        for item in manifest_files:
            if not isinstance(item, Mapping) or not isinstance(item.get("filename"), str):
                raise RequestRunError(
                    "conflicting_evidence", f"{source_id} source manifest has invalid source_files"
                )
            original = str(item["filename"])
            namespaced = f"{source_id}--{original}"
            filename_map[original] = namespaced
            source_files.append({**dict(item), "filename": namespaced, "source_id": source_id})

        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            source_headers = list(reader.fieldnames or [])
            if not source_headers:
                raise RequestRunError("conflicting_evidence", f"{source_id} CSV has no header")
            for field in source_headers:
                if field not in headers:
                    headers.append(field)
            for raw in reader:
                row = dict(raw)
                if row.get("source_id") != source_id:
                    raise RequestRunError(
                        "conflicting_evidence", f"{source_id} CSV contains another source_id"
                    )
                record_id = str(row.get("record_id") or "")
                if not record_id or record_id in record_ids:
                    raise RequestRunError(
                        "conflicting_evidence", "multi-source CSV has missing or duplicate record_id"
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
                    "conflicting_evidence", f"{source_id} evidence line {line_number} is invalid"
                ) from exc
            if not isinstance(item, dict) or item.get("source_id") != source_id:
                raise RequestRunError(
                    "conflicting_evidence", f"{source_id} evidence contains another source_id"
                )
            record_id = str(item.get("record_id") or "")
            if not record_id or record_id in evidence_ids:
                raise RequestRunError(
                    "conflicting_evidence", "multi-source evidence has missing or duplicate record_id"
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
            "conflicting_evidence", "merged multi-source CSV and evidence record IDs differ"
        )

    output_input.parent.mkdir(parents=True, exist_ok=True)
    with output_input.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        for row in merged_rows:
            writer.writerow({field: row.get(field, "") for field in headers})
    output_evidence.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
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


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RequestRunError("invalid_input", "output directory must be absent or empty")
    if (args.batch_qc_input is None) != (args.batch_qc_policy is None):
        raise RequestRunError(
            "invalid_input", "--batch-qc-input and --batch-qc-policy must be supplied together"
        )
    if not 1 <= args.source_timeout_seconds <= 900:
        raise RequestRunError(
            "invalid_input", "--source-timeout-seconds must be between 1 and 900"
        )
    catalog = source_router.load_catalog()
    registry = source_adapters.load_source_registry()
    request = source_router.validate_request(read_json(args.request, "request"), catalog)
    route = source_router.route_sources(request, catalog, registry)
    matrix = coverage_report.build_matrix(catalog, request, registry)
    source_outcomes: list[dict[str, Any]] = []
    acquisition_warnings: list[str] = []
    source_child_manifests: list[tuple[str, Path]] = []
    retained_acquisition_manifests: list[dict[str, Any]] = []

    generated_at = args.generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
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
                raise RequestRunError("network_unavailable", "online acquisition cannot run with request offline=true")
            selected_ids = [item["source_id"] for item in route["selected_sources"]]
            if args.online_source == "auto":
                requested_ids = selected_ids
            else:
                requested_ids = [args.online_source]
            unknown = sorted(set(requested_ids) - set(selected_ids))
            if unknown:
                raise RequestRunError(
                    "unsupported_scope",
                    f"source(s) {unknown} are not compatible with the frozen request route",
                )
            budgets = source_budgets(
                requested_ids, int(request["max_records"]), len(request["elements"])
            )
            successful: list[dict[str, Any]] = []
            for source_id in requested_ids:
                acquired = work / "acquired" / source_id
                source_request = dict(request)
                source_request["max_records"] = budgets[source_id]
                try:
                    acquire_online_source(
                        source_id,
                        source_request,
                        args.cache_dir,
                        acquired,
                        args.acquisition_mode,
                        generated_at,
                        timeout_seconds=args.source_timeout_seconds,
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
                            "incomplete_retrieval", f"source acquisition returned zero rows for {source_id}"
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
                    successful.append({
                        "source_id": source_id,
                        "directory": acquired,
                        "record_count": record_count,
                    })
                except (OSError, ValueError, RequestRunError) as exc:
                    source_outcomes.append({
                        "source_id": source_id,
                        "status": "failed",
                        "allocated_max_records": budgets[source_id],
                        "record_count": 0,
                        "manifest_sha256": None,
                        "error": str(exc),
                    })
                    acquisition_warnings.append(f"source {source_id} failed: {exc}")
            failed_ids = [item["source_id"] for item in source_outcomes if item["status"] == "failed"]
            if failed_ids and args.require_all_sources:
                raise RequestRunError(
                    "incomplete_retrieval",
                    f"required source acquisition failed: {failed_ids}",
                )
            if not successful:
                raise RequestRunError(
                    "incomplete_retrieval", "all routed source acquisitions failed"
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
            fixture = PRODUCTION_FIXTURE if args.demo == "production-usgs" else FOUR_MEDIA_FIXTURE
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
        filtered_evidence = work / "request_evidence.jsonl" if source_evidence is not None else None
        original_count, selected_count, warnings = filter_bundle(
            source_input, source_evidence, request, filtered_input, filtered_evidence
        )
        warnings = acquisition_warnings + warnings
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

        command = [
            sys.executable,
            str(WORKFLOW),
            "--input", str(filtered_input),
            "--output-dir", str(args.output_dir),
            "--analysis-profile", args.analysis_profile,
            "--max-records", str(request["max_records"]),
        ]
        if filtered_evidence is not None:
            command.extend(["--evidence-jsonl", str(filtered_evidence)])
        if filtered_acquisition is not None:
            command.extend(["--acquisition-manifest", str(filtered_acquisition)])
        if isinstance(request["region"], dict):
            command.extend(["--region-bbox", ",".join(str(item) for item in request["region"]["bbox"])])
        if not args.no_geology:
            command.extend(
                [
                    "--geology-grid", str(args.geology_grid),
                    "--geology-grid-sha256", args.geology_grid_sha256,
                ]
            )
        if args.batch_qc_input is not None:
            command.extend(
                [
                    "--batch-qc-input", str(args.batch_qc_input),
                    "--batch-qc-policy", str(args.batch_qc_policy),
                ]
            )
        command.extend(
            [
                "--spatial-grid-degrees", str(args.spatial_grid_degrees),
                "--min-spatial-candidates", str(args.min_spatial_candidates),
                "--spatial-fdr-alpha", str(args.spatial_fdr_alpha),
            ]
        )
        if args.min_spatial_samples is not None:
            command.extend(["--min-spatial-samples", str(args.min_spatial_samples)])
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
        if result.returncode:
            raise RequestRunError(
                "incomplete_retrieval",
                f"D2/D3 workflow failed: {(result.stderr or result.stdout).strip()}",
            )

        if filtered_acquisition is not None and source_manifest is not None:
            acquisition_dir = args.output_dir / "request_evidence" / "acquisition"
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
                retained_acquisition_manifests.append(
                    {
                        "role": role,
                        "source_id": source_id,
                        "path": destination.relative_to(
                            args.output_dir / "request_evidence"
                        ).as_posix(),
                        "sha256": sha256_file(destination),
                    }
                )

    request_evidence = args.output_dir / "request_evidence"
    write_json(request_evidence / "request.json", request)
    write_json(request_evidence / "source_route.json", route)
    write_json(request_evidence / "coverage.json", matrix)
    (request_evidence / "coverage.md").write_text(coverage_report.render_markdown(matrix), encoding="utf-8")
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
        or bool(warnings)
    )
    execution = {
        "execution_version": "geochemical-request-execution-v2",
        "status": "partial_success" if execution_partial else "success",
        "mode": mode,
        "analysis_profile": args.analysis_profile,
        "geology_grid": None if args.no_geology else {
            "filename": args.geology_grid.name,
            "sha256": args.geology_grid_sha256,
        },
        "record_counts": {"before_request_filters": original_count, "after_request_filters": selected_count},
        "source_outcomes": source_outcomes,
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
    parser.add_argument("--demo", choices=("production-usgs", "four-media"), default="production-usgs")
    parser.add_argument("--evidence-jsonl", type=Path)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/data"))
    parser.add_argument("--acquisition-mode", choices=("online", "cached"), default="online")
    parser.add_argument(
        "--source-timeout-seconds", type=int, default=300,
        help="Per-source acquisition subprocess timeout (default: 300)",
    )
    parser.add_argument(
        "--require-all-sources", action="store_true",
        help="Fail the request instead of returning partial_success when any routed source fails",
    )
    parser.add_argument("--generated-at", help="ISO-8601 acquisition timestamp; defaults to current UTC")
    parser.add_argument("--analysis-profile", choices=("demo", "production"), default="production")
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
        result = run(args)
    except (OSError, ValueError, source_router.SourceRoutingError, RequestRunError) as exc:
        status = exc.status if isinstance(exc, RequestRunError) else "invalid_input"
        print(json.dumps({"status": status, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
