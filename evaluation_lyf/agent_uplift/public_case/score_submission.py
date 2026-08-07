#!/usr/bin/env python3
"""Public, invariant-based scorer shared by Skill and no-Skill Qwen arms."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


PUBLIC_SOURCE_CONTRACT_SHA256 = "c719c7efc5fabae7b1653c60685cfe4da874bd04c923cf10b6113990269a36e6"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def nonblank(row: dict[str, str], field: str) -> bool:
    return bool((row.get(field) or "").strip())


def case_source_contract(case_dir: Path, public_contract_path: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Return geochemical resources keyed by frozen hash after manifest verification."""
    errors: list[str] = []
    try:
        contract_digest = hashlib.sha256(public_contract_path.read_bytes()).hexdigest()
    except OSError as exc:
        return {}, [f"cannot read public source contract: {exc}"]
    if contract_digest != PUBLIC_SOURCE_CONTRACT_SHA256:
        return {}, [f"public source contract hash mismatch: {contract_digest}"]
    manifest_path = case_dir / "case_manifest.json"
    if not manifest_path.is_file():
        return {}, [f"missing {manifest_path}"]
    try:
        public = load_json(public_contract_path)
        manifest = load_json(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"invalid source contract: {exc}"]
    if manifest.get("case_version") != public.get("case_version"):
        errors.append("case_version mismatch")
    manifest_by_id = {item.get("id"): item for item in manifest.get("resources", [])}
    geochemical: dict[str, dict[str, Any]] = {}
    exact_fields = ("file", "bytes", "sha256", "doi", "url")
    for expected in public.get("resources", []):
        actual = manifest_by_id.get(expected.get("id"))
        if actual is None:
            errors.append(f"manifest missing resource {expected.get('id')}")
            continue
        differing = [field for field in exact_fields if actual.get(field) != expected.get(field)]
        if differing:
            errors.append(f"manifest resource {expected.get('id')} differs: {','.join(differing)}")
            continue
        if expected.get("role") == "geochemistry":
            geochemical[str(expected["sha256"])] = expected
    expected_count = sum(item.get("role") == "geochemistry" for item in public.get("resources", []))
    if len(geochemical) != expected_count:
        errors.append(f"expected {expected_count} verified geochemical resources, got {len(geochemical)}")
    return geochemical, errors


def source_truth_metrics(
    rows: list[dict[str, str]], resources_by_hash: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Measure exact record-level preservation of the public authority contract."""
    if not rows:
        return {
            "hash_rate": 0.0,
            "metadata_rate": 0.0,
            "locator_rate": 0.0,
            "covered_resource_ids": [],
            "expected_resource_ids": sorted(item["id"] for item in resources_by_hash.values()),
            "source_truth_score": 0.0,
        }
    hash_ok = metadata_ok = locator_ok = 0
    covered: set[str] = set()
    for row in rows:
        expected = resources_by_hash.get((row.get("file_sha256") or "").strip())
        if expected is None:
            continue
        hash_ok += 1
        covered.add(str(expected["id"]))
        exact = {
            "source_id": expected["source_id"],
            "dataset_title": expected["dataset_title"],
            "dataset_doi": expected["doi"],
            "dataset_version": expected["dataset_version"],
            "license": expected["license"],
            "medium": expected["medium"],
        }
        if all((row.get(field) or "").strip() == str(value) for field, value in exact.items()):
            metadata_ok += 1
        locator = (row.get("source_locator") or "").strip()
        if locator.startswith(str(expected["locator_prefix"])) and any(
            token in locator for token in ("row=", "event=", "field=", "element=")
        ):
            locator_ok += 1
    denominator = len(rows)
    rates = {
        "hash_rate": hash_ok / denominator,
        "metadata_rate": metadata_ok / denominator,
        "locator_rate": locator_ok / denominator,
        "covered_resource_ids": sorted(covered),
        "expected_resource_ids": sorted(item["id"] for item in resources_by_hash.values()),
    }
    rates["source_truth_score"] = round(
        100 * (rates["hash_rate"] + rates["metadata_rate"] + rates["locator_rate"]) / 3, 4
    )
    return rates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.submission_dir
    checks: list[dict[str, Any]] = []

    def check(name: str, points: float, passed: bool, actual: Any = None, note: str = "") -> None:
        checks.append({"name": name, "points": points, "earned": points if passed else 0, "passed": passed, "actual": actual, "note": note})

    required = [
        "d1_raw.csv", "geochemistry.csv", "qc_report.json", "confidence_report.json",
        "geology_report.json", "anomalies.geojson", "anomaly_report.json", "interactive_map.html",
        "source_confidence.json", "run.sh", "agent_report.md", "agent_report.json",
    ]
    missing = [name for name in required if not (root / name).is_file()]
    check("required_outputs", 0, not missing, missing, "blocking prerequisite")
    if missing:
        report = {"score": sum(item["earned"] for item in checks), "checks": checks, "status": "incomplete"}
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 1

    with (root / "d1_raw.csv").open(encoding="utf-8-sig", newline="") as handle:
        d1 = list(csv.DictReader(handle))
    required_d1 = {
        "record_id", "sample_id", "element_or_analyte", "value", "unit", "medium", "latitude", "longitude",
        "analytical_method", "analytical_method_status", "geologic_context_status", "coordinate_uncertainty_status",
        "source_id", "dataset_title", "dataset_doi", "dataset_version", "source_locator", "file_sha256", "license",
    }
    headers = set(d1[0]) if d1 else set()
    check("d1_schema", 4, required_d1 <= headers, sorted(required_d1 - headers))
    check("d1_real_scale", 2, len(d1) >= 1000, len(d1))
    resources_by_hash, contract_errors = case_source_contract(
        args.case_dir, Path(__file__).with_name("sources.json")
    )
    truth = source_truth_metrics(d1, resources_by_hash)
    check("d1_source_contract_available", 2, not contract_errors, contract_errors)
    check(
        "d1_source_coverage_exact",
        3,
        truth["covered_resource_ids"] == truth["expected_resource_ids"],
        {"covered": truth["covered_resource_ids"], "expected": truth["expected_resource_ids"]},
    )
    check("d1_file_hash_exact", 4, truth["hash_rate"] == 1, truth["hash_rate"])
    check("d1_authority_metadata_exact", 4, truth["metadata_rate"] == 1, truth["metadata_rate"])
    check("d1_source_locator_exact", 3, truth["locator_rate"] == 1, truth["locator_rate"])
    cells = {(row.get("benchmark_continent"), row.get("medium")) for row in d1}
    expected_cells = {("Africa", "water"), ("Africa", "sediment"), ("Antarctica", "sediment"), ("Oceania", "soil")}
    check("d1_continent_medium_cells", 3, expected_cells <= cells, sorted(cells))
    status_fields = ("analytical_method_status", "geologic_context_status", "coordinate_uncertainty_status")
    status_rate = min((sum(nonblank(row, field) for row in d1) / len(d1) for field in status_fields), default=0)
    check("d1_explicit_statuses", 3, status_rate == 1, status_rate)
    provenance_rate = sum(all(nonblank(row, field) for field in ("source_id", "source_locator", "file_sha256", "license")) for row in d1) / len(d1) if d1 else 0
    check("d1_record_provenance", 1, provenance_rate >= 0.99, provenance_rate)
    method_rate = sum(nonblank(row, "analytical_method") for row in d1) / len(d1) if d1 else 0
    check("d1_method_evidence", 1, method_rate >= 0.95, method_rate)

    with (root / "geochemistry.csv").open(encoding="utf-8-sig", newline="") as handle:
        d2 = list(csv.DictReader(handle))
    check("d2_row_preservation", 5, len(d2) == len(d1), {"d1": len(d1), "d2": len(d2)})
    d2_headers = set(d2[0]) if d2 else set()
    needed_d2 = {"original_value_raw", "original_unit", "normalized_value", "normalized_unit", "value_qualifier", "qc_flags", "operational_confidence", "spatial_geology_status", "spatial_geology_version"}
    check("d2_schema", 5, needed_d2 <= d2_headers, sorted(needed_d2 - d2_headers))
    molar = [row for row in d2 if (row.get("original_unit") or "").casefold() in {"nmol/l", "nmol l-1"} and nonblank(row, "normalized_value")]
    molar_ok = bool(molar) and all((row.get("normalized_unit") or "").casefold() in {"ug/l", "µg/l"} for row in molar[:100])
    check("d2_molar_to_mass", 6, molar_ok, len(molar))
    molar_spot = next((row for row in d2 if row.get("element_or_analyte") == "Ni" and row.get("original_value_raw") == "20.814" and "947275" in (row.get("source_locator") or "")), None)
    molar_value = float(molar_spot["normalized_value"]) if molar_spot and nonblank(molar_spot, "normalized_value") else math.nan
    check("d2_atomic_weight_spot", 4, math.isfinite(molar_value) and abs(molar_value - 1.2216444276) < 1e-9, molar_value)
    qc = load_json(root / "qc_report.json")
    unsupported = (qc.get("flag_counts") or {}).get("UNSUPPORTED_UNIT", 0)
    check("d2_units_supported", 3, unsupported == 0, unsupported)
    geology = load_json(root / "geology_report.json")
    check("d2_geology_disposition", 4, geology.get("disposition_coverage") == 1, geology.get("disposition_coverage"))
    check("d2_no_land_unit_on_water", 4, geology.get("water_records_with_assigned_land_unit") == 0, geology.get("water_records_with_assigned_land_unit"))
    check("d2_versioned_geology", 2, "788537" in json.dumps(geology) and geology.get("matched_record_count", 0) > 0, geology.get("matched_record_count"))
    anomaly_text = (root / "anomaly_report.json").read_text(encoding="utf-8").casefold()
    noncausal = any(token in anomaly_text for token in ("no causal", "不构成因果", "不证明污染", "screening"))
    check("d2_anomaly_boundary", 2, noncausal, None)

    html = (root / "interactive_map.html").read_text(encoding="utf-8", errors="replace")
    remote_assets = bool(re.search(r"<(?:script|link)[^>]+(?:src|href)=[\"']https?://", html, re.I))
    check("d3_offline_map", 5, not remote_assets and len(html) > 10_000, {"bytes": len(html), "remote_assets": remote_assets})
    concepts = ["element", "medium", "geolog", "source", "confidence"]
    folded = html.casefold()
    check("d3_filters", 5, all(token in folded for token in concepts), [token for token in concepts if token in folded])
    source_confidence = load_json(root / "source_confidence.json")
    sc_text = json.dumps(source_confidence).casefold()
    check("d3_source_confidence", 5, "not_a_probability" in sc_text or "非概率" in sc_text, None)
    anomaly_geo = load_json(root / "anomalies.geojson")
    check("d3_anomaly_geojson", 5, anomaly_geo.get("type") == "FeatureCollection", len(anomaly_geo.get("features", [])))

    run_text = (root / "run.sh").read_text(encoding="utf-8")
    check("repro_entrypoint", 5, len(run_text.strip()) > 20, None)
    agent_report = load_json(root / "agent_report.json")
    report_fields = {"model", "skill_used", "commit", "commands", "limitations", "failures"}
    check("agent_report_schema", 5, report_fields <= set(agent_report), sorted(report_fields - set(agent_report)))
    limits = json.dumps(agent_report.get("limitations", []), ensure_ascii=False) + (root / "agent_report.md").read_text(encoding="utf-8")
    check("reported_failure_boundaries", 5, len(limits) >= 100, len(limits))

    score = round(sum(item["earned"] for item in checks), 2)
    report = {
        "score": score,
        "maximum": 100,
        "status": "pass" if score >= 70 else "fail",
        "source_truth": truth,
        "source_truth_claim_boundary": (
            "Exact match to the hash-pinned public authority contract; not proof of publisher correctness, "
            "regional representativeness, or anomaly causation."
        ),
        "checks": checks,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"score": score, "status": report["status"]}, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
