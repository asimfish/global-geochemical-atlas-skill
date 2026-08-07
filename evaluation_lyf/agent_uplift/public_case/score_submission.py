#!/usr/bin/env python3
"""Public invariant scorer for the bounded global uplift case.

The four hash-pinned geochemical files are truth anchors. Additional public
sources are expected and are verified against the candidate's frozen local
acquisition manifest instead of being penalized as unknown anchor records.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


PUBLIC_SOURCE_CONTRACT_SHA256 = (
    "46cb65053353694fcfddd4aba7447bf2b966cf996a3cf0c80fb4e72eed88c005"
)
DISCOVERY_CONTRACT_SHA256 = (
    "12494afbcd05526169dcfbb5c0a2eb1f4ff5c2e31f0313607df2ec53ca66a484"
)
BENCHMARK_CROSSWALK_SHA256 = (
    "eb891eb0ac7ecf7871260549d57fa40a0caecd02343ede4a75c9d1682861eb89"
)
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
LOCATOR_TOKENS = ("row=", "event=", "field=", "element=", "page=", "table=")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_benchmark_crosswalk(path: Path) -> dict[str, Any]:
    if file_sha256(path) != BENCHMARK_CROSSWALK_SHA256:
        raise ValueError("benchmark export crosswalk hash mismatch")
    value = load_json(path)
    if value.get("schema_version") != "qwen-uplift-benchmark-export-crosswalk-v1":
        raise ValueError("benchmark export crosswalk schema mismatch")
    return value


def nonblank(row: dict[str, str], field: str) -> bool:
    return bool((row.get(field) or "").strip())


def is_https_url(value: Any) -> bool:
    parsed = urlsplit(str(value or ""))
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
    )


def safe_case_file(
    case_dir: Path, relative: Any, required_prefix: str | None = None
) -> Path | None:
    text = str(relative or "")
    candidate = Path(text)
    if not text or candidate.is_absolute() or ".." in candidate.parts:
        return None
    if required_prefix and (
        not candidate.parts or candidate.parts[0] != required_prefix
    ):
        return None
    root = case_dir.resolve()
    resolved = (case_dir / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def case_source_contract(
    case_dir: Path,
    public_contract_path: Path,
    discovery_contract_path: Path | None = None,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return hash-pinned geochemical anchors after manifest and byte verification."""
    errors: list[str] = []
    discovery_contract_path = discovery_contract_path or public_contract_path.with_name(
        "discovery_contract.json"
    )
    try:
        contract_digest = hashlib.sha256(public_contract_path.read_bytes()).hexdigest()
        discovery_digest = hashlib.sha256(
            discovery_contract_path.read_bytes()
        ).hexdigest()
    except OSError as exc:
        return {}, [f"cannot read public contracts: {exc}"]
    if contract_digest != PUBLIC_SOURCE_CONTRACT_SHA256:
        return {}, [f"public source contract hash mismatch: {contract_digest}"]
    if discovery_digest != DISCOVERY_CONTRACT_SHA256:
        return {}, [f"discovery contract hash mismatch: {discovery_digest}"]
    manifest_path = case_dir / "case_manifest.json"
    if not manifest_path.is_file():
        return {}, [f"missing {manifest_path}"]
    try:
        public = load_json(public_contract_path)
        discovery = load_json(discovery_contract_path)
        manifest = load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"invalid source contract: {exc}"]
    expected_top = {
        "case_version": public.get("case_version"),
        "resource_semantics": public.get("resource_semantics"),
        "anchor_contract_sha256": contract_digest,
        "discovery_contract_sha256": discovery_digest,
        "discovery_contract_version": discovery.get("schema_version"),
    }
    for field, expected in expected_top.items():
        if manifest.get(field) != expected:
            errors.append(f"case manifest {field} mismatch")
    manifest_by_id = {
        item.get("id"): item
        for item in manifest.get("resources", [])
        if isinstance(item, dict)
    }
    geochemical: dict[str, dict[str, Any]] = {}
    exact_fields = ("file", "bytes", "sha256", "doi", "url", "platform")
    for expected in public.get("resources", []):
        actual = manifest_by_id.get(expected.get("id"))
        if actual is None:
            errors.append(f"manifest missing resource {expected.get('id')}")
            continue
        differing = [
            field for field in exact_fields if actual.get(field) != expected.get(field)
        ]
        if differing:
            errors.append(
                f"manifest resource {expected.get('id')} differs: {','.join(differing)}"
            )
            continue
        local_path = safe_case_file(case_dir, expected.get("file"))
        if local_path is None or not local_path.is_file():
            errors.append(f"anchor file missing or unsafe: {expected.get('file')}")
            continue
        if local_path.stat().st_size != expected.get("bytes") or file_sha256(
            local_path
        ) != expected.get("sha256"):
            errors.append(f"anchor byte identity mismatch: {expected.get('id')}")
            continue
        if expected.get("role") == "geochemistry":
            geochemical[str(expected["sha256"])] = expected
    expected_count = sum(
        item.get("role") == "geochemistry" for item in public.get("resources", [])
    )
    if len(geochemical) != expected_count:
        errors.append(
            f"expected {expected_count} verified geochemical anchors, got {len(geochemical)}"
        )
    return geochemical, errors


def discovered_source_contract(
    case_dir: Path, discovery_contract_path: Path
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Verify candidate-acquired bytes and metadata frozen before offline processing."""
    errors: list[str] = []
    try:
        contract = load_json(discovery_contract_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"invalid discovery contract: {exc}"]
    manifest_path = case_dir / str(contract["acquisition"]["manifest"])
    if not manifest_path.is_file():
        return {}, [f"missing {manifest_path}"]
    try:
        manifest = load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"invalid discovered manifest: {exc}"]
    expected_schema = contract["acquisition"]["manifest_schema_version"]
    if manifest.get("schema_version") != expected_schema:
        errors.append("discovered manifest schema_version mismatch")
    resources = manifest.get("resources")
    if not isinstance(resources, list):
        return {}, errors + ["discovered manifest resources must be an array"]
    required = set(contract["required_discovered_resource_fields"])
    maximum_bytes = int(contract["acquisition"]["maximum_single_file_bytes"])
    maximum_total_bytes = int(contract["acquisition"]["maximum_total_discovered_bytes"])
    data_directory = str(contract["acquisition"]["data_directory"])
    by_hash: dict[str, dict[str, Any]] = {}
    source_ids: set[str] = set()
    total_bytes = 0
    for index, item in enumerate(resources):
        label = f"discovered resources[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = sorted(
            field for field in required if item.get(field) in (None, "", [])
        )
        if missing:
            errors.append(f"{label} missing fields: {','.join(missing)}")
            continue
        source_id = str(item["source_id"])
        digest = str(item["sha256"])
        media = item.get("media")
        if not SAFE_SOURCE_ID.fullmatch(source_id):
            errors.append(f"{label} has unsafe source_id")
        if source_id in source_ids:
            errors.append(f"duplicate discovered source_id: {source_id}")
        source_ids.add(source_id)
        if not HEX_SHA256.fullmatch(digest):
            errors.append(f"{label} has invalid sha256")
            continue
        if digest in by_hash:
            errors.append(f"duplicate discovered file hash: {digest}")
            continue
        if (
            not isinstance(media, list)
            or not media
            or any(
                value not in {"rock", "soil", "sediment", "water"} for value in media
            )
        ):
            errors.append(f"{label} has invalid media")
            continue
        if not all(
            is_https_url(item.get(field))
            for field in ("authority_url", "download_url", "locator_prefix")
        ):
            errors.append(f"{label} has invalid public HTTPS evidence URLs")
            continue
        local_path = safe_case_file(
            case_dir, item.get("file"), required_prefix=data_directory
        )
        if local_path is None or not local_path.is_file():
            errors.append(f"{label} file is missing or outside {data_directory}/")
            continue
        expected_bytes = item.get("bytes")
        if (
            isinstance(expected_bytes, bool)
            or not isinstance(expected_bytes, int)
            or not 0 < expected_bytes <= maximum_bytes
        ):
            errors.append(f"{label} has invalid bytes")
            continue
        total_bytes += expected_bytes
        if (
            local_path.stat().st_size != expected_bytes
            or file_sha256(local_path) != digest
        ):
            errors.append(f"{label} byte identity mismatch")
            continue
        by_hash[digest] = item
    if total_bytes > maximum_total_bytes:
        errors.append(
            f"discovered files exceed total byte cap: {total_bytes} > {maximum_total_bytes}"
        )
    return by_hash, errors


def expected_medium_matches(expected: dict[str, Any], actual: str) -> bool:
    media = expected.get("media")
    return (
        actual in media
        if isinstance(media, list)
        else actual == str(expected.get("medium") or "")
    )


def source_truth_metrics(
    rows: list[dict[str, str]], resources_by_hash: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Measure exact record-level preservation for anchors or discovered resources."""
    expected_ids = sorted(
        str(item["id"] if "id" in item else item["source_id"])
        for item in resources_by_hash.values()
    )
    if not rows:
        return {
            "hash_rate": 0.0,
            "metadata_rate": 0.0,
            "locator_rate": 0.0,
            "covered_resource_ids": [],
            "expected_resource_ids": expected_ids,
            "unmatched_record_count": 0,
            "source_truth_score": 0.0,
        }
    hash_ok = metadata_ok = locator_ok = 0
    covered: set[str] = set()
    for row in rows:
        expected = resources_by_hash.get((row.get("file_sha256") or "").strip())
        if expected is None:
            continue
        hash_ok += 1
        covered.add(str(expected.get("id") or expected["source_id"]))
        exact = {
            "source_id": expected["source_id"],
            "dataset_title": expected["dataset_title"],
            "dataset_doi": expected.get("doi", expected.get("dataset_doi")),
            "dataset_version": expected["dataset_version"],
            "license": expected["license"],
        }
        if all(
            (row.get(field) or "").strip() == str(value)
            for field, value in exact.items()
        ) and expected_medium_matches(expected, (row.get("medium") or "").strip()):
            metadata_ok += 1
        locator = (row.get("source_locator") or "").strip()
        if locator.startswith(str(expected["locator_prefix"])) and any(
            token in locator for token in LOCATOR_TOKENS
        ):
            locator_ok += 1
    denominator = len(rows)
    rates = {
        "hash_rate": hash_ok / denominator,
        "metadata_rate": metadata_ok / denominator,
        "locator_rate": locator_ok / denominator,
        "covered_resource_ids": sorted(covered),
        "expected_resource_ids": expected_ids,
        "unmatched_record_count": denominator - hash_ok,
    }
    rates["source_truth_score"] = round(
        100 * (rates["hash_rate"] + rates["metadata_rate"] + rates["locator_rate"]) / 3,
        4,
    )
    return rates


def discovery_report_metrics(
    report: Any, contract: dict[str, Any], selected_ids: set[str]
) -> dict[str, Any]:
    allowed_statuses = set(contract["candidate_statuses"])
    candidates = report.get("candidates") if isinstance(report, dict) else None
    required_report_fields = set(contract["required_discovery_report_fields"])
    continuation = contract["continuation_policy"]
    active_seconds = (
        report.get("active_discovery_seconds") if isinstance(report, dict) else None
    )
    valid = (
        isinstance(report, dict)
        and report.get("schema_version") == "qwen-uplift-discovery-report-v1"
        and report.get("request") == contract.get("request")
        and isinstance(candidates, list)
        and required_report_fields <= set(report)
        and all(
            report.get(field) not in (None, "")
            for field in required_report_fields - {"remaining_candidates"}
        )
        and isinstance(report.get("remaining_candidates"), list)
        and isinstance(active_seconds, (int, float))
        and not isinstance(active_seconds, bool)
        and 0
        <= active_seconds
        <= contract["acquisition"]["discovery_planning_budget_seconds"]
        and report.get("stop_reason") in continuation["allowed_stop_reasons"]
        and report.get("selection_policy") == continuation["maximum_records_selection"]
    )
    candidate_ids: set[str] = set()
    platforms: set[str] = set()
    selected_report_ids: set[str] = set()
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                valid = False
                continue
            required = (
                "source_id",
                "platform",
                "status",
                "authority_url",
                "query",
                "reason",
            )
            if any(item.get(field) in (None, "") for field in required):
                valid = False
                continue
            source_id = str(item["source_id"])
            if (
                source_id in candidate_ids
                or item["status"] not in allowed_statuses
                or not is_https_url(item["authority_url"])
            ):
                valid = False
            candidate_ids.add(source_id)
            platforms.add(str(item["platform"]))
            if item["status"] == "selected":
                selected_report_ids.add(source_id)
                if item.get("marginal_contribution") in (None, "", []):
                    valid = False
    boundary = (
        str(report.get("claim_boundary") or "") if isinstance(report, dict) else ""
    )
    boundary_ok = any(
        token in boundary.casefold()
        for token in (
            "not exhaustive",
            "not complete",
            "非穷尽",
            "不代表完整",
            "覆盖空洞",
        )
    )
    valid = valid and selected_ids == selected_report_ids and boundary_ok
    return {
        "valid": valid,
        "candidate_source_count": len(candidate_ids),
        "searched_platform_count": len(platforms),
        "selected_source_ids": sorted(selected_report_ids),
        "claim_boundary_ok": boundary_ok,
        "active_discovery_seconds": active_seconds,
        "stop_reason": report.get("stop_reason") if isinstance(report, dict) else None,
    }


def coverage_report_valid(report: Any, rows: list[dict[str, str]]) -> bool:
    if (
        not isinstance(report, dict)
        or report.get("schema_version") != "qwen-uplift-coverage-report-v1"
    ):
        return False
    samples = {
        (row.get("source_id"), row.get("sample_id"))
        for row in rows
        if nonblank(row, "sample_id")
    }
    media_counts: dict[str, int] = {}
    element_counts: dict[str, int] = {}
    coordinates: set[tuple[str, str]] = set()
    for row in rows:
        medium = (row.get("medium") or "").strip()
        element = (row.get("element_or_analyte") or "").strip()
        media_counts[medium] = media_counts.get(medium, 0) + 1
        element_counts[element] = element_counts.get(element, 0) + 1
        if nonblank(row, "latitude") and nonblank(row, "longitude"):
            coordinates.add((row["latitude"].strip(), row["longitude"].strip()))
    boundary = str(report.get("claim_boundary") or "").casefold()
    return (
        report.get("record_count") == len(rows)
        and report.get("unique_sample_count") == len(samples)
        and report.get("unique_reported_coordinate_count") == len(coordinates)
        and report.get("by_medium") == dict(sorted(media_counts.items()))
        and report.get("by_element") == dict(sorted(element_counts.items()))
        and isinstance(report.get("gaps"), list)
        and bool(report.get("gaps"))
        and any(
            token in boundary
            for token in (
                "not exhaustive",
                "not complete",
                "非穷尽",
                "不代表完整",
                "覆盖空洞",
            )
        )
    )


def qc_tokens(row: dict[str, str]) -> set[str]:
    raw = row.get("qc_flags") or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = re.split(r"[|;,]", raw)
    return (
        {str(value).strip().upper() for value in parsed if str(value).strip()}
        if isinstance(parsed, list)
        else set()
    )


def explicit_unit_disposition(row: dict[str, str]) -> bool:
    flags = qc_tokens(row)
    if any(
        any(
            token in flag for token in ("UNIT_INFERRED", "UNIT_GUESSED", "ASSUMED_UNIT")
        )
        for flag in flags
    ):
        return False
    if nonblank(row, "normalized_value") and nonblank(row, "normalized_unit"):
        return True
    censored = str(row.get("censored") or "").strip().casefold() in {"1", "true", "yes"}
    if censored or (row.get("value_qualifier") or "").strip().casefold() in {
        "<",
        ">",
        "nd",
        "bdl",
        "trace",
    }:
        return True
    allowed = (
        "UNSUPPORTED",
        "AMBIGUOUS",
        "MISSING_UNIT",
        "CENSORED",
        "NONDETECT",
        "TRACE",
    )
    return any(any(token in flag for token in allowed) for flag in flags)


def valid_samples_geojson(value: Any) -> tuple[bool, int, int]:
    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        return False, 0, 0
    coordinates: set[tuple[float, float]] = set()
    features = value.get("features")
    if not isinstance(features, list) or not features:
        return False, 0, 0
    for feature in features:
        try:
            lon, lat = feature["geometry"]["coordinates"]
            lon, lat = float(lon), float(lat)
        except (KeyError, TypeError, ValueError):
            return False, len(features), len(coordinates)
        if (
            not math.isfinite(lon)
            or not math.isfinite(lat)
            or not (-180 <= lon <= 180 and -90 <= lat <= 90)
        ):
            return False, len(features), len(coordinates)
        coordinates.add((lon, lat))
    return True, len(features), len(coordinates)


def browser_audit_metrics(path: Path | None, html: Path) -> tuple[bool, dict[str, Any]]:
    if path is None or not path.is_file():
        return False, {"status": "not_supplied"}
    try:
        audit = load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, {"status": "invalid", "error": str(exc)}
    interactions = audit.get("interactions") if isinstance(audit, dict) else None
    required = {
        "filter_changes_result",
        "heatmap",
        "concentration_encoding",
        "global_globe",
        "database_visuals",
        "element_combination",
        "source_drilldown",
        "anomaly_view",
    }
    interaction_pass = (
        isinstance(interactions, dict)
        and required <= set(interactions)
        and all(interactions[name].get("passed") is True for name in required)
    )
    metrics = audit.get("metrics") if isinstance(audit, dict) else {}
    screenshots = audit.get("screenshots") if isinstance(audit, dict) else []
    screenshot_directory = (
        audit.get("screenshot_directory") if isinstance(audit, dict) else None
    )
    screenshot_files_ok = False
    if (
        isinstance(screenshot_directory, str)
        and screenshot_directory
        and Path(screenshot_directory).name == screenshot_directory
        and isinstance(screenshots, list)
    ):
        screenshot_root = path.parent / screenshot_directory
        screenshot_files_ok = len(screenshots) >= 8
        for item in screenshots:
            filename = item.get("file") if isinstance(item, dict) else None
            candidate = screenshot_root / str(filename or "")
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not candidate.is_file()
                or candidate.stat().st_size != item.get("bytes")
                or file_sha256(candidate) != item.get("sha256")
            ):
                screenshot_files_ok = False
                break
    bound = (
        isinstance(audit, dict)
        and audit.get("schema_version") == "geochemical-browser-audit-v1"
        and audit.get("generated_by") == "external_evaluation_controller"
        and audit.get("html", {}).get("sha256") == file_sha256(html)
        and audit.get("html", {}).get("bytes") == html.stat().st_size
    )
    browser_ok = bool(
        bound
        and audit.get("status") == "pass"
        and audit.get("loaded") is True
        and audit.get("rendered_product") is True
        and audit.get("javascript_errors") == []
        and isinstance(metrics, dict)
        and (metrics.get("embedded_measurements") or 0) > 0
        and (metrics.get("visible_symbols") or 0) > 0
        and (metrics.get("basemap_shapes") or 0) > 0
        and (metrics.get("country_boundaries") or 0) > 0
        and isinstance(screenshots, list)
        and len(screenshots) >= 5
        and all(
            HEX_SHA256.fullmatch(str(item.get("sha256") or "")) for item in screenshots
        )
        and screenshot_files_ok
    )
    return browser_ok and interaction_pass, {
        "status": audit.get("status") if isinstance(audit, dict) else "invalid",
        "hash_bound": bound,
        "browser_ok": browser_ok,
        "interaction_pass": interaction_pass,
        "metrics": metrics,
        "screenshot_count": len(screenshots) if isinstance(screenshots, list) else 0,
        "screenshots_hash_verified": screenshot_files_ok,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--browser-audit",
        type=Path,
        help="Controller-generated browser_audit.json outside the candidate submission",
    )
    args = parser.parse_args()
    root = args.submission_dir
    checks: list[dict[str, Any]] = []

    def check(
        name: str, points: float, passed: bool, actual: Any = None, note: str = ""
    ) -> None:
        checks.append(
            {
                "name": name,
                "points": points,
                "earned": points if passed else 0,
                "passed": passed,
                "actual": actual,
                "note": note,
            }
        )

    required = [
        "d1_raw.csv",
        "discovery_report.json",
        "coverage_report.json",
        "source_manifest.json",
        "record_evidence.jsonl",
        "geochemistry.csv",
        "qc_report.json",
        "confidence_report.json",
        "geology_report.json",
        "anomalies.geojson",
        "anomaly_report.json",
        "interactive_map.html",
        "samples.geojson",
        "source_confidence.json",
        "run.sh",
        "agent_report.md",
        "agent_report.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    check("required_outputs", 0, not missing, missing, "blocking prerequisite")
    if missing:
        report = {"score": 0, "maximum": 100, "checks": checks, "status": "incomplete"}
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 1

    public_case = Path(__file__).parent
    try:
        benchmark_crosswalk = load_benchmark_crosswalk(
            public_case / "benchmark_export_crosswalk.json"
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        report = {
            "score": 0,
            "maximum": 100,
            "checks": checks,
            "status": "invalid_evaluator",
            "error": str(exc),
        }
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 1
    discovery_contract_path = public_case / "discovery_contract.json"
    discovery_contract = load_json(discovery_contract_path)
    with (root / "d1_raw.csv").open(encoding="utf-8-sig", newline="") as handle:
        d1 = list(csv.DictReader(handle))
    required_d1 = {
        "record_id",
        "sample_id",
        "element_or_analyte",
        "value",
        "unit",
        "medium",
        "latitude",
        "longitude",
        "analytical_method",
        "analytical_method_status",
        "geologic_context_status",
        "coordinate_uncertainty_status",
        "source_id",
        "dataset_title",
        "dataset_doi",
        "dataset_version",
        "source_locator",
        "file_sha256",
        "license",
    }
    headers = set(d1[0]) if d1 else set()
    check("d1_schema", 3, required_d1 <= headers, sorted(required_d1 - headers))
    check("d1_real_scale", 1, len(d1) >= 1000, len(d1))

    anchor_resources, anchor_errors = case_source_contract(
        args.case_dir, public_case / "sources.json", discovery_contract_path
    )
    discovered_resources, discovered_errors = discovered_source_contract(
        args.case_dir, discovery_contract_path
    )
    anchor_rows = [
        row for row in d1 if (row.get("file_sha256") or "").strip() in anchor_resources
    ]
    discovered_rows = [
        row
        for row in d1
        if (row.get("file_sha256") or "").strip() in discovered_resources
    ]
    anchor_truth = source_truth_metrics(anchor_rows, anchor_resources)
    discovered_truth = source_truth_metrics(discovered_rows, discovered_resources)
    all_resources = {**anchor_resources, **discovered_resources}
    overall_truth = source_truth_metrics(d1, all_resources)
    check("d1_anchor_contract_available", 1, not anchor_errors, anchor_errors)
    check(
        "d1_anchor_coverage_exact",
        2,
        anchor_truth["covered_resource_ids"] == anchor_truth["expected_resource_ids"],
        {
            "covered": anchor_truth["covered_resource_ids"],
            "expected": anchor_truth["expected_resource_ids"],
        },
    )
    check(
        "d1_anchor_file_hash_exact",
        2,
        anchor_truth["hash_rate"] == 1,
        anchor_truth["hash_rate"],
    )
    check(
        "d1_anchor_authority_metadata_exact",
        2,
        anchor_truth["metadata_rate"] == 1,
        anchor_truth["metadata_rate"],
    )
    check(
        "d1_anchor_source_locator_exact",
        2,
        anchor_truth["locator_rate"] == 1,
        anchor_truth["locator_rate"],
    )
    check("d1_discovered_manifest_valid", 3, not discovered_errors, discovered_errors)

    discovery_report = load_json(root / "discovery_report.json")
    selected_ids = {str(item["source_id"]) for item in discovered_resources.values()}
    discovery_metrics = discovery_report_metrics(
        discovery_report, discovery_contract, selected_ids
    )
    targets = discovery_contract["minimum_public_development_targets"]
    covered_discovered_ids = set(discovered_truth["covered_resource_ids"])
    covered_anchor_ids = set(anchor_truth["covered_resource_ids"])
    covered_discovered_resources = [
        item
        for item in discovered_resources.values()
        if item["source_id"] in covered_discovered_ids
    ]
    platforms = {
        str(item["platform"])
        for item in anchor_resources.values()
        if str(item.get("id")) in covered_anchor_ids
    }
    platforms.update(str(item["platform"]) for item in covered_discovered_resources)
    discovered_samples = {
        (row.get("source_id"), row.get("sample_id"))
        for row in discovered_rows
        if nonblank(row, "sample_id")
    }
    breadth_actual = {
        "candidate_source_count": discovery_metrics["candidate_source_count"],
        "searched_platform_count": discovery_metrics["searched_platform_count"],
        "verified_geochemical_source_count": len(covered_anchor_ids)
        + len(covered_discovered_ids),
        "verified_additional_source_count": len(covered_discovered_ids),
        "verified_platform_count": len(platforms),
        "additional_observation_count": len(discovered_rows),
        "additional_unique_sample_count": len(discovered_samples),
    }
    breadth_ok = discovery_metrics["valid"] and all(
        breadth_actual[field] >= targets[field] for field in breadth_actual
    )
    check("d1_bounded_discovery_breadth", 3, breadth_ok, breadth_actual)
    actual_media = {(row.get("medium") or "").strip() for row in d1}
    actual_elements = {(row.get("element_or_analyte") or "").strip() for row in d1}
    discovered_media = {(row.get("medium") or "").strip() for row in discovered_rows}
    coverage_ok = (
        set(targets["required_media"]) <= actual_media
        and set(targets["required_elements"]) <= actual_elements
        and set(targets["required_additional_media"]) <= discovered_media
    )
    check(
        "d1_requested_media_element_coverage",
        2,
        coverage_ok,
        {
            "media": sorted(actual_media),
            "elements": sorted(actual_elements),
            "additional_media": sorted(discovered_media),
        },
    )
    provenance_rate = (
        sum(
            all(
                nonblank(row, field)
                for field in ("source_id", "source_locator", "file_sha256", "license")
            )
            for row in d1
        )
        / len(d1)
        if d1
        else 0
    )
    evidence_ids: set[str] = set()
    evidence_valid = True
    with (root / "record_evidence.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                evidence_valid = False
                continue
            record_id = str(item.get("record_id") or "")
            if not record_id or record_id in evidence_ids:
                evidence_valid = False
            evidence_ids.add(record_id)
    d1_ids = {str(row.get("record_id") or "") for row in d1}
    check(
        "d1_record_provenance",
        2,
        provenance_rate == 1 and evidence_valid and evidence_ids == d1_ids,
        {
            "provenance_rate": provenance_rate,
            "evidence_records": len(evidence_ids),
            "d1_records": len(d1_ids),
        },
    )
    status_fields = (
        "analytical_method_status",
        "geologic_context_status",
        "coordinate_uncertainty_status",
    )
    status_rate = min(
        (sum(nonblank(row, field) for row in d1) / len(d1) for field in status_fields),
        default=0,
    )
    check("d1_explicit_statuses", 2, status_rate == 1, status_rate)
    check("d1_discovery_report", 2, discovery_metrics["valid"], discovery_metrics)
    coverage_report = load_json(root / "coverage_report.json")
    check("d1_coverage_report", 2, coverage_report_valid(coverage_report, d1), None)
    check(
        "d1_all_source_truth",
        1,
        overall_truth["source_truth_score"] == 100,
        overall_truth,
    )

    with (root / "geochemistry.csv").open(encoding="utf-8-sig", newline="") as handle:
        d2 = list(csv.DictReader(handle))
    check("d2_row_preservation", 5, len(d2) == len(d1), {"d1": len(d1), "d2": len(d2)})
    d2_headers = set(d2[0]) if d2 else set()
    core_d2 = {
        "original_value_raw",
        "original_unit",
        "normalized_value",
        "normalized_unit",
        "value_qualifier",
        "qc_flags",
        "operational_confidence",
    }
    geology_field_sets = (
        set(benchmark_crosswalk["legacy_read_only_aliases"]),
        {
            benchmark_crosswalk["canonical_contract"][field]
            for field in ("matched_unit", "map_source", "map_version", "match_method")
        },
    )
    schema_ok = core_d2 <= d2_headers and any(
        fields <= d2_headers for fields in geology_field_sets
    )
    check(
        "d2_schema",
        5,
        schema_ok,
        {
            "missing_core": sorted(core_d2 - d2_headers),
            "geology_contract_present": schema_ok,
        },
    )
    molar = [
        row
        for row in d2
        if (row.get("original_unit") or "").casefold() in {"nmol/l", "nmol l-1"}
        and nonblank(row, "normalized_value")
    ]
    molar_ok = bool(molar) and all(
        (row.get("normalized_unit") or "").casefold() in {"ug/l", "µg/l"}
        for row in molar
    )
    check("d2_molar_to_mass", 5, molar_ok, len(molar))
    molar_spot = next(
        (
            row
            for row in d2
            if row.get("element_or_analyte") == "Ni"
            and row.get("original_value_raw") == "20.814"
            and "947275" in (row.get("source_locator") or "")
        ),
        None,
    )
    molar_value = (
        float(molar_spot["normalized_value"])
        if molar_spot and nonblank(molar_spot, "normalized_value")
        else math.nan
    )
    check(
        "d2_atomic_weight_spot",
        3,
        math.isfinite(molar_value) and abs(molar_value - 1.2216444276) < 1e-9,
        molar_value,
    )
    disposition_rate = (
        sum(explicit_unit_disposition(row) for row in d2) / len(d2) if d2 else 0
    )
    check(
        "d2_units_have_explicit_disposition",
        4,
        disposition_rate == 1,
        disposition_rate,
        "Unknown units may fail closed; guessed units do not receive credit merely for avoiding UNSUPPORTED_UNIT.",
    )
    geology = load_json(root / "geology_report.json")
    check(
        "d2_geology_disposition",
        4,
        geology.get("disposition_coverage") == 1,
        geology.get("disposition_coverage"),
    )
    check(
        "d2_no_land_unit_on_water",
        4,
        geology.get("water_records_with_assigned_land_unit") == 0,
        geology.get("water_records_with_assigned_land_unit"),
    )
    check(
        "d2_versioned_geology",
        2,
        "788537" in json.dumps(geology) and geology.get("matched_record_count", 0) > 0,
        geology.get("matched_record_count"),
    )
    anomaly_text = (root / "anomaly_report.json").read_text(encoding="utf-8").casefold()
    noncausal = any(
        token in anomaly_text
        for token in ("no causal", "不构成因果", "不证明污染", "screening")
    )
    check("d2_anomaly_boundary", 3, noncausal, None)

    html = (root / "interactive_map.html").read_text(encoding="utf-8", errors="replace")
    remote_assets = bool(
        re.search(r"<(?:script|link)[^>]+(?:src|href)=[\"']https?://", html, re.I)
    )
    browser_ok, browser_metrics = browser_audit_metrics(
        args.browser_audit, root / "interactive_map.html"
    )
    check(
        "d3_offline_map",
        4,
        not remote_assets
        and len(html) > 10_000
        and browser_metrics.get("browser_ok") is True,
        {
            "bytes": len(html),
            "remote_assets": remote_assets,
            "browser": browser_metrics,
        },
        "Full credit requires an external hash-bound Chromium render; static HTML tokens are insufficient.",
    )
    folded = html.casefold()
    concepts = [
        "element",
        "medium",
        "geolog",
        "source",
        "confidence",
        "region",
        "sample",
        "heat",
        "comparison",
    ]
    check(
        "d3_research_controls",
        4,
        all(token in folded for token in concepts)
        and browser_metrics.get("interaction_pass") is True,
        {
            "static_concepts": [token for token in concepts if token in folded],
            "browser": browser_metrics,
        },
        "Filters, heatmap, combination, source drilldown and anomaly view must change or render state in Chromium.",
    )
    source_confidence = load_json(root / "source_confidence.json")
    sc_text = json.dumps(source_confidence).casefold()
    check(
        "d3_source_confidence",
        3,
        "not_a_probability" in sc_text or "非概率" in sc_text,
        None,
    )
    anomaly_geo = load_json(root / "anomalies.geojson")
    anomaly_features = (
        anomaly_geo.get("features", []) if isinstance(anomaly_geo, dict) else []
    )
    directions = {
        str(item.get("properties", {}).get("direction") or "").casefold()
        for item in anomaly_features
        if isinstance(item, dict)
    }
    check(
        "d3_anomaly_geojson",
        3,
        anomaly_geo.get("type") == "FeatureCollection"
        and bool(anomaly_features)
        and bool(directions & {"high", "low"}),
        {"features": len(anomaly_features), "directions": sorted(directions)},
    )
    samples_ok, sample_features, unique_sites = valid_samples_geojson(
        load_json(root / "samples.geojson")
    )
    browser_observations = browser_metrics.get("metrics", {}).get(
        "embedded_measurements"
    )
    check(
        "d3_mappable_observations",
        3,
        samples_ok and browser_ok and browser_observations == sample_features,
        {
            "features": sample_features,
            "unique_sites": unique_sites,
            "browser_embedded_measurements": browser_observations,
        },
    )
    disclosure_ok = any(
        token in folded
        for token in ("coverage gap", "unsampled", "未覆盖", "覆盖空白", "空白不")
    )
    check(
        "d3_coverage_disclosure",
        3,
        disclosure_ok and str(unique_sites) in html,
        {"unique_sites": unique_sites, "boundary": disclosure_ok},
    )

    run_text = (root / "run.sh").read_text(encoding="utf-8")
    check(
        "repro_entrypoint",
        5,
        len(run_text.strip()) > 20 and "case_data" in run_text,
        None,
    )
    agent_report = load_json(root / "agent_report.json")
    report_fields = {
        "model",
        "skill_used",
        "commit",
        "commands",
        "limitations",
        "failures",
    }
    check(
        "agent_report_schema",
        5,
        report_fields <= set(agent_report),
        sorted(report_fields - set(agent_report)),
    )
    limits = json.dumps(agent_report.get("limitations", []), ensure_ascii=False) + (
        root / "agent_report.md"
    ).read_text(encoding="utf-8")
    check(
        "reported_failure_boundaries",
        5,
        len(limits) >= 100
        and any(
            token in limits.casefold()
            for token in ("not exhaustive", "不完整", "覆盖空洞", "partial_success")
        ),
        len(limits),
    )

    score = round(sum(item["earned"] for item in checks), 2)
    report = {
        "score": score,
        "maximum": 100,
        "status": "pass" if score >= 70 else "fail",
        "source_truth": {
            "anchors": anchor_truth,
            "discovered": discovered_truth,
            "overall": overall_truth,
        },
        "discovery": {**discovery_metrics, **breadth_actual},
        "browser_audit": browser_metrics,
        "source_truth_claim_boundary": (
            "Anchor truth is exact against the hash-pinned public authority contract. Discovered-source truth is exact "
            "against candidate-frozen local bytes and metadata; formal authority and breadth claims still require the "
            "private registry and online audit. Neither score proves publisher correctness, global completeness, "
            "regional representativeness, or anomaly causation."
        ),
        "checks": checks,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"score": score, "status": report["status"]}, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
