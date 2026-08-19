"""Adversarial audit with canary calibration for atlas output directories.

Implements the referee layer of the builder/skeptic/referee protocol described
in ``references/adversarial-audit.md``:

- ``--mode scripted`` runs a deterministic deep-check suite over a finished
  output directory and writes an ``audit_receipt.json``.
- Calibration (on by default) first plants known defects into a shadow copy
  and requires the same check suite to catch every planted defect before the
  verdict on the real directory becomes admissible. An auditor that cannot
  find planted defects must not acquit real data.
- ``--mode brief`` emits a self-contained audit brief for an independent
  second agent (two-agent adversarial review). The canary ground truth is
  written to a separate referee file that the orchestrator must withhold
  from the auditing agent.
- ``--adjudicate FINDINGS.json`` cross-verifies free-form findings from an
  independent auditor against the deterministic checks and classifies each
  finding as confirmed, unconfirmed or out_of_scope.

The tool only reads the audited directory; every artifact it writes goes to
``--audit-dir`` (default ``<output-dir>_audit``) so byte-identity checks on
the audited delivery are never disturbed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

AUDIT_VERSION = "adversarial-audit-v1"
RECEIPT_SCHEMA = "urn:global-geochemical-atlas:audit-receipt:v1"
Z_SCALE = 0.67448975
Z_TOLERANCE = 1e-6
VALUE_TOLERANCE = 1e-9
COORD_TOLERANCE = 1e-9

CANARY_CLASSES = (
    "unit_flip",
    "value_tamper",
    "hash_corrupt",
    "fabricated_source",
    "coordinate_swap",
    "locator_bounds",
    "censored_impute",
    "anomaly_ztamper",
    "url_swap",
    "evidence_orphan",
)

CONTRACT_FILES = (
    "interactive_map.html",
    "samples.geojson",
    "geochemistry.csv",
    "sources_and_confidence.json",
    "source_manifest.json",
    "record_evidence.jsonl",
    "confidence_report.json",
    "anomalies.geojson",
    "anomaly_report.json",
    "anomaly_regions.geojson",
    "spatial_anomaly_report.json",
    "qc_report.json",
    "batch_acceptance.csv",
    "batch_qc_report.json",
    "iteration_backlog.csv",
    "run_summary.json",
)

# Frozen unit pairs the normalization layer is allowed to produce. The audit
# re-derives normalized values instead of trusting the conversion columns.
SOLID_UNITS = {"mg/kg", "ppm", "wt%", "ug/g", "ng/g", "%"}
WATER_UNITS = {"ug/l", "mg/l", "ng/l"}


class ArtifactError(RuntimeError):
    """Raised when the audited directory cannot be loaded at all."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_artifacts(output_dir: Path) -> dict[str, Any]:
    if not output_dir.is_dir():
        raise ArtifactError(f"output directory not found: {output_dir}")
    missing = [name for name in CONTRACT_FILES if not (output_dir / name).is_file()]
    artifacts: dict[str, Any] = {"missing_contract_files": missing}
    csv_path = output_dir / "geochemistry.csv"
    if csv_path.is_file():
        with csv_path.open(newline="", encoding="utf-8") as handle:
            artifacts["records"] = list(csv.DictReader(handle))
    else:
        artifacts["records"] = []
    evidence_path = output_dir / "record_evidence.jsonl"
    evidence: list[dict[str, Any]] = []
    if evidence_path.is_file():
        with evidence_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    evidence.append(json.loads(line))
    artifacts["evidence"] = evidence
    for name, key in (
        ("source_manifest.json", "source_manifest"),
        ("anomaly_report.json", "anomaly_report"),
        ("samples.geojson", "samples"),
        ("anomalies.geojson", "anomalies"),
        ("run_summary.json", "run_summary"),
        ("sources_and_confidence.json", "sources_and_confidence"),
    ):
        path = output_dir / name
        artifacts[key] = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
        )
    map_path = output_dir / "interactive_map.html"
    artifacts["map_html"] = (
        map_path.read_text(encoding="utf-8") if map_path.is_file() else None
    )
    return artifacts


def _finding(
    check_id: str,
    canary_class: str,
    severity: str,
    detail: str,
    *,
    file: str | None = None,
    record_id: str | None = None,
    suggested_action: str = "trace the record back to its source evidence and re-run the producing stage",
) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "defect_class": canary_class,
        "severity": severity,
        "detail": detail,
        "file": file,
        "record_id": record_id,
        "suggested_action": suggested_action,
    }


def _to_float(raw: Any) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def check_contract_files(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for name in artifacts["missing_contract_files"]:
        findings.append(
            _finding(
                "contract_files",
                "contract_gap",
                "error",
                f"required contract file missing: {name}",
                file=name,
                suggested_action="re-run the full workflow; do not hand-write missing artifacts",
            )
        )
    return findings


def check_evidence_join(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    evidence_ids = {row.get("record_id") for row in artifacts["evidence"]}
    manifest = artifacts.get("source_manifest") or {}
    manifest_sources = {
        entry.get("source_id")
        for entry in manifest.get("sources", [])
        if isinstance(entry, dict)
    }
    for row in artifacts["records"]:
        record_id = row.get("record_id")
        if record_id not in evidence_ids:
            findings.append(
                _finding(
                    "evidence_join",
                    "evidence_orphan",
                    "error",
                    "database record has no record_evidence.jsonl row",
                    file="record_evidence.jsonl",
                    record_id=record_id,
                )
            )
    for row in artifacts["evidence"]:
        source_id = row.get("source_id")
        if manifest_sources and source_id not in manifest_sources:
            findings.append(
                _finding(
                    "evidence_join",
                    "fabricated_source",
                    "error",
                    f"evidence row cites source_id absent from source_manifest.json: {source_id}",
                    file="record_evidence.jsonl",
                    record_id=row.get("record_id"),
                )
            )
    return findings


def check_hash_chain(
    artifacts: dict[str, Any], output_dir: Path
) -> list[dict[str, Any]]:
    findings = []
    by_file: dict[tuple[str, str], set[str]] = {}
    for row in artifacts["evidence"]:
        source_file = row.get("source_file")
        sha = row.get("source_file_sha256")
        if source_file and sha:
            by_file.setdefault(
                (str(row.get("source_id")), str(source_file)), set()
            ).add(str(sha))
    for (source_id, source_file), hashes in sorted(by_file.items()):
        if len(hashes) > 1:
            findings.append(
                _finding(
                    "hash_chain",
                    "hash_corrupt",
                    "error",
                    (
                        f"evidence rows disagree on sha256 for {source_id}:{source_file}; "
                        f"{len(hashes)} distinct hashes recorded"
                    ),
                    file="record_evidence.jsonl",
                )
            )
    manifest = artifacts.get("source_manifest") or {}
    manifest_hashes: dict[str, set[str]] = {}
    for entry in manifest.get("sources", []):
        if not isinstance(entry, dict):
            continue
        for item in entry.get("source_files", []) or []:
            if isinstance(item, dict):
                filename = item.get("filename") or item.get("path")
                sha = item.get("sha256")
                if filename and sha:
                    manifest_hashes.setdefault(str(filename), set()).add(str(sha))
    for (source_id, source_file), hashes in sorted(by_file.items()):
        declared = manifest_hashes.get(source_file)
        if declared and not (hashes & declared):
            findings.append(
                _finding(
                    "hash_chain",
                    "hash_corrupt",
                    "error",
                    (
                        f"evidence sha256 for {source_id}:{source_file} does not match "
                        "source_manifest.json declaration"
                    ),
                    file="record_evidence.jsonl",
                )
            )
    acquisition_dir = output_dir / "request_evidence" / "acquisition"
    execution_path = output_dir / "request_evidence" / "execution.json"
    if execution_path.is_file():
        execution = json.loads(execution_path.read_text(encoding="utf-8"))
        for item in execution.get("acquisition_manifests", []) or []:
            rel = item.get("path")
            declared = item.get("sha256")
            if not rel or not declared:
                continue
            path = output_dir / "request_evidence" / rel
            if path.is_file() and sha256_of(path) != declared:
                findings.append(
                    _finding(
                        "hash_chain",
                        "hash_corrupt",
                        "error",
                        f"acquisition manifest bytes drifted from execution.json hash: {rel}",
                        file=str(path.relative_to(output_dir)),
                    )
                )
    elif acquisition_dir.is_dir():
        findings.append(
            _finding(
                "hash_chain",
                "contract_gap",
                "warning",
                "request_evidence/acquisition exists but execution.json is missing",
                file="request_evidence/execution.json",
            )
        )
    return findings


def check_unit_rederive(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for row in artifacts["records"]:
        original = _to_float(row.get("original_value"))
        normalized = _to_float(row.get("normalized_value"))
        factor = _to_float(row.get("conversion_factor"))
        if original is None or normalized is None or factor is None:
            continue
        expected = original * factor
        scale = max(abs(expected), abs(normalized), 1e-12)
        if abs(expected - normalized) / scale > VALUE_TOLERANCE:
            findings.append(
                _finding(
                    "unit_rederive",
                    "value_tamper",
                    "error",
                    (
                        f"normalized_value {normalized!r} != original_value {original!r} * "
                        f"conversion_factor {factor!r}"
                    ),
                    file="geochemistry.csv",
                    record_id=row.get("record_id"),
                )
            )
        original_unit = str(row.get("original_unit") or "").strip().lower()
        normalized_unit = str(row.get("normalized_unit") or "").strip().lower()
        if not original_unit or not normalized_unit:
            continue
        solid = original_unit in SOLID_UNITS
        water = original_unit in WATER_UNITS
        if solid and normalized_unit not in SOLID_UNITS:
            findings.append(
                _finding(
                    "unit_rederive",
                    "unit_flip",
                    "error",
                    (
                        f"solid-phase unit {original_unit!r} normalized into "
                        f"non-solid unit {normalized_unit!r}"
                    ),
                    file="geochemistry.csv",
                    record_id=row.get("record_id"),
                )
            )
        elif water and normalized_unit not in WATER_UNITS:
            findings.append(
                _finding(
                    "unit_rederive",
                    "unit_flip",
                    "error",
                    (
                        f"water-phase unit {original_unit!r} normalized into "
                        f"non-water unit {normalized_unit!r}"
                    ),
                    file="geochemistry.csv",
                    record_id=row.get("record_id"),
                )
            )
    return findings


def check_censored_guard(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    censored_ids = set()
    for row in artifacts["records"]:
        if str(row.get("censored")).strip().lower() == "true":
            censored_ids.add(row.get("record_id"))
            if _to_float(row.get("normalized_value")) is not None:
                findings.append(
                    _finding(
                        "censored_guard",
                        "censored_impute",
                        "error",
                        "censored record carries a numeric normalized_value; "
                        "censored values must not be imputed",
                        file="geochemistry.csv",
                        record_id=row.get("record_id"),
                    )
                )
    anomalies = artifacts.get("anomalies") or {}
    for feature in anomalies.get("features", []) or []:
        properties = feature.get("properties", {})
        if properties.get("record_id") in censored_ids:
            findings.append(
                _finding(
                    "censored_guard",
                    "censored_impute",
                    "error",
                    "censored record appears as anomaly candidate",
                    file="anomalies.geojson",
                    record_id=properties.get("record_id"),
                )
            )
    return findings


def check_coordinate_consistency(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    by_record: dict[str, dict[str, Any]] = {
        str(row.get("record_id")): row for row in artifacts["records"]
    }
    samples = artifacts.get("samples") or {}
    for feature in samples.get("features", []) or []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        properties = feature.get("properties", {})
        record_id = str(properties.get("record_id"))
        if len(coordinates) < 2:
            continue
        lon, lat = coordinates[0], coordinates[1]
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            findings.append(
                _finding(
                    "coordinate_consistency",
                    "coordinate_swap",
                    "error",
                    f"GeoJSON coordinates out of range: [{lon}, {lat}]",
                    file="samples.geojson",
                    record_id=record_id,
                )
            )
            continue
        row = by_record.get(record_id)
        if row is None:
            continue
        row_lat = _to_float(row.get("latitude"))
        row_lon = _to_float(row.get("longitude"))
        if row_lat is None or row_lon is None:
            continue
        if abs(row_lon - lon) > COORD_TOLERANCE or abs(row_lat - lat) > COORD_TOLERANCE:
            swapped = (
                abs(row_lon - lat) <= COORD_TOLERANCE
                and abs(row_lat - lon) <= COORD_TOLERANCE
            )
            findings.append(
                _finding(
                    "coordinate_consistency",
                    "coordinate_swap",
                    "error",
                    (
                        "GeoJSON geometry disagrees with database coordinates"
                        + (" (looks lon/lat swapped)" if swapped else "")
                    ),
                    file="samples.geojson",
                    record_id=record_id,
                )
            )
    return findings


def check_locator_bounds(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for row in artifacts["evidence"]:
        source_row = row.get("source_row")
        if source_row is None:
            continue
        try:
            numeric = int(str(source_row))
        except ValueError:
            continue
        if numeric < 1:
            findings.append(
                _finding(
                    "locator_bounds",
                    "locator_bounds",
                    "error",
                    f"evidence source_row is not a positive row index: {source_row!r}",
                    file="record_evidence.jsonl",
                    record_id=row.get("record_id"),
                )
            )
    return findings


def _group_records(
    artifacts: dict[str, Any], group_by: list[str], group_values: dict[str, Any]
) -> list[float]:
    values = []
    for row in artifacts["records"]:
        if str(row.get("censored")).strip().lower() == "true":
            continue
        matched = True
        for key in group_by:
            expected = group_values.get(key)
            actual = row.get(key)
            if (expected in (None, "") and actual in (None, "")) or str(actual) == str(
                expected
            ):
                continue
            matched = False
            break
        if not matched:
            continue
        value = _to_float(row.get("normalized_value"))
        if value is not None and value > 0:
            values.append(value)
    return values


def check_anomaly_recompute(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    report = artifacts.get("anomaly_report") or {}
    group_by = list(report.get("group_by") or [])
    threshold = _to_float(report.get("robust_z_threshold")) or 3.5
    groups = {
        str(group.get("group_id")): group
        for group in report.get("groups", []) or []
        if isinstance(group, dict)
    }
    anomalies = artifacts.get("anomalies") or {}
    by_record: dict[str, dict[str, Any]] = {
        str(row.get("record_id")): row for row in artifacts["records"]
    }
    for feature in anomalies.get("features", []) or []:
        properties = feature.get("properties", {})
        record_id = str(properties.get("record_id"))
        group = groups.get(str(properties.get("group_id")))
        claimed_z = _to_float(properties.get("robust_z"))
        row = by_record.get(record_id)
        if group is None or claimed_z is None or row is None:
            if row is None:
                findings.append(
                    _finding(
                        "anomaly_recompute",
                        "fabricated_source",
                        "error",
                        "anomaly candidate cites a record absent from geochemistry.csv",
                        file="anomalies.geojson",
                        record_id=record_id,
                    )
                )
            continue
        value = _to_float(row.get("normalized_value"))
        if value is None or value <= 0:
            findings.append(
                _finding(
                    "anomaly_recompute",
                    "censored_impute",
                    "error",
                    "anomaly candidate has no positive quantified normalized_value",
                    file="anomalies.geojson",
                    record_id=record_id,
                )
            )
            continue
        group_values = group.get("group") or {}
        values = _group_records(artifacts, group_by, group_values)
        if len(values) < 2:
            continue
        logs = [math.log10(v) for v in values]
        median = statistics.median(logs)
        mad = statistics.median(abs(x - median) for x in logs)
        if mad <= 0:
            continue
        recomputed = Z_SCALE * (math.log10(value) - median) / mad
        if abs(recomputed - claimed_z) > max(Z_TOLERANCE, abs(recomputed) * 1e-9):
            findings.append(
                _finding(
                    "anomaly_recompute",
                    "anomaly_ztamper",
                    "error",
                    (
                        f"robust_z re-derivation mismatch: claimed {claimed_z}, "
                        f"recomputed {recomputed:.9f}"
                    ),
                    file="anomalies.geojson",
                    record_id=record_id,
                )
            )
        elif abs(recomputed) < threshold:
            findings.append(
                _finding(
                    "anomaly_recompute",
                    "anomaly_ztamper",
                    "error",
                    f"anomaly candidate below threshold |z|>={threshold}: {recomputed:.4f}",
                    file="anomalies.geojson",
                    record_id=record_id,
                )
            )
    return findings


def _registered_domains(artifacts: dict[str, Any]) -> set[str]:
    domains: set[str] = set()
    manifest = artifacts.get("source_manifest") or {}
    for entry in manifest.get("sources", []) or []:
        if not isinstance(entry, dict):
            continue
        for url in entry.get("official_source_urls", []) or []:
            host = urlparse(str(url)).netloc.lower()
            if host:
                domains.add(host)
    for row in artifacts["evidence"]:
        anchor_fields = row.get("shared_source_metadata_fields") or []
        if "official_source_url" in anchor_fields and row.get("official_source_url"):
            host = urlparse(str(row["official_source_url"])).netloc.lower()
            if host:
                domains.add(host)
    return domains


def check_url_domains(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    allowed = _registered_domains(artifacts)
    if not allowed:
        return findings
    for row in artifacts["evidence"]:
        for field in ("official_source_url", "source_file_url"):
            url = row.get(field)
            if not url:
                continue
            host = urlparse(str(url)).netloc.lower()
            if host and host not in allowed:
                findings.append(
                    _finding(
                        "url_domains",
                        "url_swap",
                        "error",
                        f"{field} points to unregistered domain {host!r}",
                        file="record_evidence.jsonl",
                        record_id=row.get("record_id"),
                    )
                )
    return findings


def check_map_embed(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    html = artifacts.get("map_html")
    samples = artifacts.get("samples") or {}
    mappable = len(samples.get("features", []) or [])
    if not html or not mappable:
        return findings
    match = re.search(
        r'<script id="samples-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not match:
        findings.append(
            _finding(
                "map_embed",
                "map_truncation",
                "warning",
                "interactive_map.html has no parseable samples-data payload",
                file="interactive_map.html",
                suggested_action="regenerate the map through render pipeline; do not hand-edit HTML",
            )
        )
        return findings
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        findings.append(
            _finding(
                "map_embed",
                "map_truncation",
                "error",
                "embedded samples-data payload is not valid JSON",
                file="interactive_map.html",
            )
        )
        return findings
    embedded = None
    if isinstance(payload, list):
        embedded = len(payload)
    elif isinstance(payload, dict):
        for key in ("records", "samples", "features", "points"):
            value = payload.get(key)
            if isinstance(value, list):
                embedded = len(value)
                break
        if embedded is None:
            for key in ("record_count", "embedded_records", "count"):
                value = payload.get(key)
                if isinstance(value, int):
                    embedded = value
                    break
    if embedded is not None and embedded < mappable:
        findings.append(
            _finding(
                "map_embed",
                "map_truncation",
                "error",
                (
                    f"map embeds {embedded} records but samples.geojson has {mappable} "
                    "mappable records; silent preview truncation is forbidden"
                ),
                file="interactive_map.html",
            )
        )
    return findings


CHECKS = (
    ("contract_files", lambda artifacts, output_dir: check_contract_files(artifacts)),
    ("evidence_join", lambda artifacts, output_dir: check_evidence_join(artifacts)),
    ("hash_chain", check_hash_chain),
    ("unit_rederive", lambda artifacts, output_dir: check_unit_rederive(artifacts)),
    ("censored_guard", lambda artifacts, output_dir: check_censored_guard(artifacts)),
    (
        "coordinate_consistency",
        lambda artifacts, output_dir: check_coordinate_consistency(artifacts),
    ),
    ("locator_bounds", lambda artifacts, output_dir: check_locator_bounds(artifacts)),
    (
        "anomaly_recompute",
        lambda artifacts, output_dir: check_anomaly_recompute(artifacts),
    ),
    ("url_domains", lambda artifacts, output_dir: check_url_domains(artifacts)),
    ("map_embed", lambda artifacts, output_dir: check_map_embed(artifacts)),
)


def run_checks(output_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    artifacts = load_artifacts(output_dir)
    findings: list[dict[str, Any]] = []
    check_rows: list[dict[str, Any]] = []
    for check_id, runner in CHECKS:
        check_findings = runner(artifacts, output_dir)
        findings.extend(check_findings)
        check_rows.append(
            {
                "check_id": check_id,
                "status": "fail"
                if any(f["severity"] == "error" for f in check_findings)
                else "pass",
                "finding_count": len(check_findings),
            }
        )
    return check_rows, findings


# ---------------------------------------------------------------------------
# Canary planting
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _load_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader), list(reader.fieldnames or [])


def plant_canaries(
    output_dir: Path, shadow_dir: Path, seed: int
) -> list[dict[str, Any]]:
    """Copy ``output_dir`` to ``shadow_dir`` and plant one defect per class."""

    if shadow_dir.exists():
        shutil.rmtree(shadow_dir)
    shutil.copytree(output_dir, shadow_dir)
    rng = random.Random(seed)
    truth: list[dict[str, Any]] = []

    rows, fieldnames = _load_csv(shadow_dir / "geochemistry.csv")
    with (shadow_dir / "record_evidence.jsonl").open(encoding="utf-8") as handle:
        evidence = [json.loads(line) for line in handle if line.strip()]

    quantified = [
        i
        for i, row in enumerate(rows)
        if _to_float(row.get("normalized_value")) is not None
        and _to_float(row.get("conversion_factor")) is not None
    ]
    rng.shuffle(quantified)

    def take_quantified() -> int:
        if not quantified:
            raise ArtifactError("not enough quantified records to plant canaries")
        return quantified.pop()

    # 1. value_tamper
    index = take_quantified()
    rows[index]["normalized_value"] = str(
        _to_float(rows[index]["normalized_value"]) * 1000.0
    )
    truth.append(
        {
            "defect_class": "value_tamper",
            "record_id": rows[index]["record_id"],
            "file": "geochemistry.csv",
        }
    )

    # 2. unit_flip
    index = take_quantified()
    rows[index]["normalized_unit"] = (
        "ug/L"
        if str(rows[index].get("normalized_unit", "")).lower() == "mg/kg"
        else "mg/kg"
    )
    truth.append(
        {
            "defect_class": "unit_flip",
            "record_id": rows[index]["record_id"],
            "file": "geochemistry.csv",
        }
    )

    # 3. censored_impute
    censored = [
        i for i, row in enumerate(rows) if str(row.get("censored")).lower() == "true"
    ]
    if censored:
        index = rng.choice(censored)
    else:
        index = take_quantified()
        rows[index]["censored"] = "true"
    rows[index]["normalized_value"] = "1.2345"
    truth.append(
        {
            "defect_class": "censored_impute",
            "record_id": rows[index]["record_id"],
            "file": "geochemistry.csv",
        }
    )

    # 4. fabricated_source (rides on a copied record + evidence row)
    template_row = dict(rows[rng.randrange(len(rows))])
    template_row["record_id"] = "rec-" + "f" * 60 + "cafe"
    rows.append(template_row)
    fake_evidence = dict(evidence[rng.randrange(len(evidence))])
    fake_evidence["record_id"] = template_row["record_id"]
    fake_evidence["source_id"] = "unregistered-shadow-source"
    evidence.append(fake_evidence)
    truth.append(
        {
            "defect_class": "fabricated_source",
            "record_id": template_row["record_id"],
            "file": "record_evidence.jsonl",
        }
    )

    # 5. evidence_orphan: drop the evidence row of an existing record
    victim = rng.randrange(len(evidence) - 1)
    orphan_record = str(evidence[victim].get("record_id"))
    del evidence[victim]
    truth.append(
        {
            "defect_class": "evidence_orphan",
            "record_id": orphan_record,
            "file": "record_evidence.jsonl",
        }
    )

    # 6. hash_corrupt
    hashed = [i for i, row in enumerate(evidence) if row.get("source_file_sha256")]
    index = rng.choice(hashed)
    sha = str(evidence[index]["source_file_sha256"])
    evidence[index]["source_file_sha256"] = ("0" if sha[0] != "0" else "1") + sha[1:]
    truth.append(
        {
            "defect_class": "hash_corrupt",
            "record_id": evidence[index].get("record_id"),
            "file": "record_evidence.jsonl",
        }
    )

    # 7. locator_bounds
    located = [i for i, row in enumerate(evidence) if row.get("source_row") is not None]
    index = rng.choice(located)
    evidence[index]["source_row"] = -7
    truth.append(
        {
            "defect_class": "locator_bounds",
            "record_id": evidence[index].get("record_id"),
            "file": "record_evidence.jsonl",
        }
    )

    # 8. url_swap
    index = rng.randrange(len(evidence))
    evidence[index]["official_source_url"] = "https://evil-mirror.example.net/dataset"
    truth.append(
        {
            "defect_class": "url_swap",
            "record_id": evidence[index].get("record_id"),
            "file": "record_evidence.jsonl",
        }
    )

    _write_csv(shadow_dir / "geochemistry.csv", rows, fieldnames)
    with (shadow_dir / "record_evidence.jsonl").open("w", encoding="utf-8") as handle:
        for row in evidence:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    # 9. coordinate_swap
    samples = json.loads((shadow_dir / "samples.geojson").read_text(encoding="utf-8"))
    features = samples.get("features", [])
    if features:
        feature = features[rng.randrange(len(features))]
        lon, lat = feature["geometry"]["coordinates"][:2]
        feature["geometry"]["coordinates"][0] = lat
        feature["geometry"]["coordinates"][1] = lon
        (shadow_dir / "samples.geojson").write_text(
            json.dumps(samples, ensure_ascii=False), encoding="utf-8"
        )
        truth.append(
            {
                "defect_class": "coordinate_swap",
                "record_id": feature.get("properties", {}).get("record_id"),
                "file": "samples.geojson",
            }
        )

    # 10. anomaly_ztamper
    anomalies = json.loads(
        (shadow_dir / "anomalies.geojson").read_text(encoding="utf-8")
    )
    anomaly_features = anomalies.get("features", [])
    if anomaly_features:
        feature = anomaly_features[rng.randrange(len(anomaly_features))]
        feature["properties"]["robust_z"] = (
            float(feature["properties"].get("robust_z", 4.0)) + 1.5
        )
        (shadow_dir / "anomalies.geojson").write_text(
            json.dumps(anomalies, ensure_ascii=False), encoding="utf-8"
        )
        truth.append(
            {
                "defect_class": "anomaly_ztamper",
                "record_id": feature.get("properties", {}).get("record_id"),
                "file": "anomalies.geojson",
            }
        )

    return truth


def calibrate(output_dir: Path, audit_dir: Path, seed: int) -> dict[str, Any]:
    shadow_dir = audit_dir / "canary_shadow"
    truth = plant_canaries(output_dir, shadow_dir, seed)
    _, findings = run_checks(shadow_dir)
    caught = []
    missed = []
    for planted in truth:
        matched = any(
            f["defect_class"] == planted["defect_class"]
            and (
                planted.get("record_id") is None
                or f.get("record_id") == planted.get("record_id")
                or f.get("check_id") in ("hash_chain",)
            )
            for f in findings
        )
        (caught if matched else missed).append(planted)
    recall = len(caught) / len(truth) if truth else 0.0
    truth_path = audit_dir / "referee_canary_truth.json"
    truth_path.write_text(
        json.dumps({"seed": seed, "planted": truth}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "seed": seed,
        "planted": len(truth),
        "caught": len(caught),
        "missed": missed,
        "recall": recall,
        "admissible": not missed,
        "shadow_dir": str(shadow_dir),
        "truth_file": str(truth_path),
    }


# ---------------------------------------------------------------------------
# Brief and adjudication (two-agent mode)
# ---------------------------------------------------------------------------

BRIEF_INSTRUCTIONS = """\
# Independent audit brief (skeptic role)

You are an independent auditor. You did NOT build these artifacts and you must
not trust any narrative about them. Work from the artifact bytes only.

Rules of engagement:
1. First run the calibration exam: audit the shadow directory listed in
   audit_brief.json (`exam_dir`). It contains planted defects. Report every
   defect you find in the findings JSON format below. Your verdict on the real
   directory is only admissible if the referee confirms you caught all planted
   defects.
2. Then audit the real directory (`target_dir`). Attack the strongest claims
   first: provenance chain, unit conversions, censored handling, anomaly
   statistics, coordinate integrity, and map completeness.
3. Every finding must carry file-level evidence. Unverifiable suspicions are
   labelled `suspicion`, not `error`.
4. You may run `python scripts/adversarial_audit.py --mode scripted` yourself,
   but you must add at least one check the script does not perform (sampling
   records against source fixture bytes, license wording, terminology drift).
5. Write findings to the path in `findings_file` using this JSON shape:
   {"auditor": "<name>", "findings": [{"check_id": str, "defect_class": str,
    "severity": "error|warning|suspicion", "detail": str, "file": str,
    "record_id": str|null}]}
6. You can drive repairs, but you can never acquit: only the referee
   adjudication plus deterministic checks produce the final verdict.
"""


def write_brief(output_dir: Path, audit_dir: Path, seed: int) -> dict[str, Any]:
    calibration = calibrate(output_dir, audit_dir, seed)
    brief = {
        "brief_version": AUDIT_VERSION,
        "target_dir": str(output_dir),
        "exam_dir": calibration["shadow_dir"],
        "findings_file": str(audit_dir / "independent_findings.json"),
        "exam_findings_file": str(audit_dir / "independent_exam_findings.json"),
        "note": (
            "referee_canary_truth.json must be withheld from the auditing agent "
            "until adjudication"
        ),
    }
    (audit_dir / "audit_brief.json").write_text(
        json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (audit_dir / "AUDIT_INSTRUCTIONS.md").write_text(
        BRIEF_INSTRUCTIONS, encoding="utf-8"
    )
    return brief


def adjudicate(
    output_dir: Path, audit_dir: Path, findings_path: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    submitted = json.loads(findings_path.read_text(encoding="utf-8"))
    agent_findings = submitted.get("findings", [])
    _, deterministic = run_checks(output_dir)
    deterministic_keys = {
        (f["defect_class"], f.get("record_id")) for f in deterministic
    }
    adjudicated = []
    for finding in agent_findings:
        key = (finding.get("defect_class"), finding.get("record_id"))
        if key in deterministic_keys:
            status = "confirmed_deterministic"
        elif finding.get("severity") == "suspicion":
            status = "recorded_suspicion"
        else:
            status = "unconfirmed_requires_evidence"
        adjudicated.append({**finding, "adjudication": status})
    exam_truth_path = audit_dir / "referee_canary_truth.json"
    exam_result = None
    exam_findings_path = audit_dir / "independent_exam_findings.json"
    if exam_truth_path.is_file() and exam_findings_path.is_file():
        truth = json.loads(exam_truth_path.read_text(encoding="utf-8"))["planted"]
        exam = json.loads(exam_findings_path.read_text(encoding="utf-8")).get(
            "findings", []
        )
        exam_keys = {(f.get("defect_class"), f.get("record_id")) for f in exam}
        missed = [
            p
            for p in truth
            if (p["defect_class"], p.get("record_id")) not in exam_keys
            and (p["defect_class"], None) not in exam_keys
        ]
        exam_result = {
            "planted": len(truth),
            "caught": len(truth) - len(missed),
            "missed": missed,
            "admissible": not missed,
        }
    return (
        {
            "adjudication_version": AUDIT_VERSION,
            "agent_finding_count": len(agent_findings),
            "confirmed": sum(
                1 for f in adjudicated if f["adjudication"] == "confirmed_deterministic"
            ),
            "independent_exam": exam_result,
        },
        adjudicated,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--audit-dir", type=Path, default=None)
    parser.add_argument("--mode", choices=("scripted", "brief"), default="scripted")
    parser.add_argument("--adjudicate", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=20260817)
    parser.add_argument(
        "--skip-calibration",
        action="store_true",
        help="debug only; an uncalibrated verdict is never admissible",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    audit_dir: Path = (
        args.audit_dir.resolve()
        if args.audit_dir
        else output_dir.parent / (output_dir.name + "_audit")
    )
    audit_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.mode == "brief":
            brief = write_brief(output_dir, audit_dir, args.seed)
            print(json.dumps({"status": "brief_written", **brief}, ensure_ascii=False))
            return 0

        if args.adjudicate is not None:
            summary, adjudicated = adjudicate(output_dir, audit_dir, args.adjudicate)
            receipt_path = audit_dir / "adjudication_receipt.json"
            receipt_path.write_text(
                json.dumps(
                    {**summary, "findings": adjudicated}, ensure_ascii=False, indent=2
                ),
                encoding="utf-8",
            )
            print(json.dumps(summary, ensure_ascii=False))
            return 0

        calibration = (
            None
            if args.skip_calibration
            else calibrate(output_dir, audit_dir, args.seed)
        )
        check_rows, findings = run_checks(output_dir)
        errors = [f for f in findings if f["severity"] == "error"]
        admissible = bool(calibration and calibration["admissible"])
        if calibration is None:
            verdict = "inadmissible_uncalibrated"
        elif not admissible:
            verdict = "inadmissible_calibration_failed"
        elif errors:
            verdict = "fail"
        else:
            verdict = "pass"
        receipt = {
            "receipt_schema": RECEIPT_SCHEMA,
            "audit_version": AUDIT_VERSION,
            "mode": "scripted",
            "output_dir": str(output_dir),
            "calibration": calibration,
            "checks": check_rows,
            "finding_count": len(findings),
            "error_count": len(errors),
            "findings": findings,
            "verdict": verdict,
            "principle": "the executor can drive repairs but can never acquit itself",
        }
        receipt_path = audit_dir / "audit_receipt.json"
        receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "verdict": verdict,
                    "admissible": admissible,
                    "error_count": len(errors),
                    "finding_count": len(findings),
                    "calibration_recall": calibration["recall"]
                    if calibration
                    else None,
                    "receipt": str(receipt_path),
                },
                ensure_ascii=False,
            )
        )
        if verdict == "pass":
            return 0
        if verdict == "fail":
            return 1
        return 2
    except ArtifactError as exc:
        print(
            json.dumps({"verdict": "artifact_error", "detail": str(exc)}),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
