#!/usr/bin/env python3
"""Run request planning, bounded acquisition/input filtering, D2 and D3 in one command."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
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
    result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
    if result.returncode:
        raise RequestRunError(
            "incomplete_retrieval",
            f"source acquisition failed for {source_id}: {(result.stderr or result.stdout).strip()}",
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise RequestRunError("invalid_input", "output directory must be absent or empty")
    catalog = source_router.load_catalog()
    registry = source_adapters.load_source_registry()
    request = source_router.validate_request(read_json(args.request, "request"), catalog)
    route = source_router.route_sources(request, catalog, registry)
    matrix = coverage_report.build_matrix(catalog, request, registry)

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
            selected_ids = {item["source_id"] for item in route["selected_sources"]}
            source_id = args.online_source
            if source_id == "auto":
                if len(selected_ids) != 1:
                    raise RequestRunError(
                        "needs_human_review",
                        f"auto acquisition requires exactly one compatible source; candidates={sorted(selected_ids)}",
                    )
                source_id = next(iter(selected_ids))
            if source_id not in selected_ids:
                raise RequestRunError(
                    "unsupported_scope",
                    f"source {source_id} is not compatible with the frozen request route",
                )
            acquired = work / "acquired"
            acquire_online_source(
                source_id, request, args.cache_dir, acquired, args.acquisition_mode, generated_at
            )
            source_input = acquired / "demo_input.csv"
            source_evidence = acquired / "sources.jsonl"
            source_manifest = acquired / "run_manifest.json"
            mode = f"online_source:{source_id}"
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
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=900)
        if result.returncode:
            raise RequestRunError(
                "incomplete_retrieval",
                f"D2/D3 workflow failed: {(result.stderr or result.stdout).strip()}",
            )

    request_evidence = args.output_dir / "request_evidence"
    write_json(request_evidence / "request.json", request)
    write_json(request_evidence / "source_route.json", route)
    write_json(request_evidence / "coverage.json", matrix)
    (request_evidence / "coverage.md").write_text(coverage_report.render_markdown(matrix), encoding="utf-8")
    execution = {
        "execution_version": "geochemical-request-execution-v1",
        "status": "success",
        "mode": mode,
        "analysis_profile": args.analysis_profile,
        "geology_grid": None if args.no_geology else {
            "filename": args.geology_grid.name,
            "sha256": args.geology_grid_sha256,
        },
        "record_counts": {"before_request_filters": original_count, "after_request_filters": selected_count},
        "route_status": route["status"],
        "coverage_status": matrix["overall_status"],
        "route_resolution": (
            "offline_fixture_hash_verified"
            if mode.startswith("fixture:")
            else "routed_source_evidence_verified"
            if mode.startswith("online_source:")
            else "provided_input_processed"
        ),
        "execution_coverage_status": "partial" if mode.startswith("fixture:") else matrix["overall_status"],
        "warnings": warnings,
    }
    write_json(request_evidence / "execution.json", execution)
    return execution


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--input", type=Path, help="Existing CSV to filter and process")
    mode.add_argument("--online-source", help="One routed source ID, or 'auto' when exactly one is selected")
    parser.add_argument("--demo", choices=("production-usgs", "four-media"), default="production-usgs")
    parser.add_argument("--evidence-jsonl", type=Path)
    parser.add_argument("--acquisition-manifest", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/data"))
    parser.add_argument("--acquisition-mode", choices=("online", "cached"), default="online")
    parser.add_argument("--generated-at", help="ISO-8601 acquisition timestamp; defaults to current UTC")
    parser.add_argument("--analysis-profile", choices=("demo", "production"), default="production")
    parser.add_argument("--geology-grid", type=Path, default=DEFAULT_GEOLOGY_GRID)
    parser.add_argument("--geology-grid-sha256", default=DEFAULT_GEOLOGY_SHA256)
    parser.add_argument("--no-geology", action="store_true")
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
