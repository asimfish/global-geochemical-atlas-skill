#!/usr/bin/env python3
"""Build and verify report claims against exact content-addressed artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

LEDGER_VERSION = "atlas-report-claim-ledger-v1"
CLAIM_VERSION = "atlas-report-claim-v1"


class ClaimLedgerError(RuntimeError):
    """Raised when a claim cannot be recomputed from its declared artifact."""


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ClaimLedgerError("geochemistry.csv has no header")
            required = {
                "element_or_analyte",
                "medium",
                "source_id",
                "value_qualifier",
                "latitude",
                "longitude",
            }
            missing = sorted(required - set(reader.fieldnames))
            if missing:
                raise ClaimLedgerError(
                    "geochemistry.csv lacks claim fields: " + ", ".join(missing)
                )
            rows = [dict(row) for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ClaimLedgerError(f"cannot read geochemistry.csv: {exc}") from exc
    if len(rows) > 200_000:
        raise ClaimLedgerError("claim ledger refuses more than 200000 CSV rows")
    return rows


def _read_feature_count(path: Path) -> int:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClaimLedgerError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, Mapping) or value.get("type") != "FeatureCollection":
        raise ClaimLedgerError(f"{path.name} must be a GeoJSON FeatureCollection")
    features = value.get("features")
    if not isinstance(features, list):
        raise ClaimLedgerError(f"{path.name}.features must be an array")
    return len(features)


def _claim(
    *,
    claim_id: str,
    value: Any,
    value_type: str,
    unit: str,
    statement_boundary: str,
    artifact: Path,
    locator: str,
    recompute_method: str,
) -> dict[str, Any]:
    body = {
        "schema_version": CLAIM_VERSION,
        "claim_id": claim_id,
        "value": value,
        "value_type": value_type,
        "unit": unit,
        "statement_boundary": statement_boundary,
        "evidence": {
            "artifact": artifact.name,
            "artifact_sha256": sha256_file(artifact),
            "locator": locator,
            "recompute_method": recompute_method,
        },
        "verification_status": "recomputed",
    }
    return {**body, "claim_sha256": sha256_bytes(canonical_json_bytes(body))}


def build_claim_ledger(output_dir: Path) -> dict[str, Any]:
    """Return the fixed, independently recomputable claim set for one atlas."""

    database = output_dir / "geochemistry.csv"
    anomalies = output_dir / "anomalies.geojson"
    regions = output_dir / "anomaly_regions.geojson"
    rows = _read_rows(database)
    elements = sorted(
        {str(row.get("element_or_analyte") or "").strip() for row in rows} - {""}
    )
    media = sorted({str(row.get("medium") or "").strip() for row in rows} - {""})
    sources = sorted({str(row.get("source_id") or "").strip() for row in rows} - {""})
    censored = sum(
        str(row.get("value_qualifier") or "").strip().casefold()
        in {"lt", "le", "gt", "ge"}
        for row in rows
    )
    coordinate_pairs = sum(
        bool(str(row.get("latitude") or "").strip())
        and bool(str(row.get("longitude") or "").strip())
        for row in rows
    )
    coordinate_rate = round(coordinate_pairs / len(rows), 12) if rows else 0.0
    claims = [
        _claim(
            claim_id="standardized_measurement_record_count",
            value=len(rows),
            value_type="integer",
            unit="measurement_records",
            statement_boundary="CSV data rows, excluding the header; not physical samples.",
            artifact=database,
            locator="all data rows",
            recompute_method="csv_data_row_count_v1",
        ),
        _claim(
            claim_id="covered_element_symbols",
            value=elements,
            value_type="sorted_string_array",
            unit="element_symbols",
            statement_boundary="Distinct non-empty element_or_analyte values in the CSV.",
            artifact=database,
            locator="column:element_or_analyte",
            recompute_method="csv_distinct_nonempty_sorted_v1",
        ),
        _claim(
            claim_id="covered_media",
            value=media,
            value_type="sorted_string_array",
            unit="controlled_media",
            statement_boundary="Distinct non-empty medium values; not equal coverage.",
            artifact=database,
            locator="column:medium",
            recompute_method="csv_distinct_nonempty_sorted_v1",
        ),
        _claim(
            claim_id="adopted_source_count",
            value=len(sources),
            value_type="integer",
            unit="source_ids",
            statement_boundary="Distinct non-empty source_id values represented by CSV rows.",
            artifact=database,
            locator="column:source_id",
            recompute_method="csv_distinct_nonempty_count_v1",
        ),
        _claim(
            claim_id="censored_measurement_record_count",
            value=censored,
            value_type="integer",
            unit="measurement_records",
            statement_boundary="Rows whose controlled value_qualifier is lt/le/gt/ge; retained, not deleted.",
            artifact=database,
            locator="column:value_qualifier",
            recompute_method="csv_controlled_censor_qualifier_count_v1",
        ),
        _claim(
            claim_id="nonempty_coordinate_pair_count",
            value=coordinate_pairs,
            value_type="integer",
            unit="measurement_records",
            statement_boundary="Rows with both coordinate text fields non-empty; this does not prove datum validity.",
            artifact=database,
            locator="columns:latitude,longitude",
            recompute_method="csv_nonempty_coordinate_pair_count_v1",
        ),
        _claim(
            claim_id="nonempty_coordinate_pair_rate",
            value=coordinate_rate,
            value_type="number",
            unit="fraction_of_measurement_records",
            statement_boundary="Non-empty coordinate pairs divided by CSV rows; not positional accuracy.",
            artifact=database,
            locator="columns:latitude,longitude; all data rows",
            recompute_method="csv_nonempty_coordinate_pair_rate_v1",
        ),
        _claim(
            claim_id="candidate_anomaly_feature_count",
            value=_read_feature_count(anomalies),
            value_type="integer",
            unit="geojson_features",
            statement_boundary="Record-level statistical screening candidates; not causal conclusions.",
            artifact=anomalies,
            locator="$.features",
            recompute_method="geojson_feature_count_v1",
        ),
        _claim(
            claim_id="fdr_screened_anomaly_region_count",
            value=_read_feature_count(regions),
            value_type="integer",
            unit="geojson_features",
            statement_boundary="Regions passing the declared spatial screening gate; not pollution or ore claims.",
            artifact=regions,
            locator="$.features",
            recompute_method="geojson_feature_count_v1",
        ),
    ]
    body = {
        "schema_version": LEDGER_VERSION,
        "algorithm": "canonical-json-sha256-v1",
        "claims": claims,
        "claim_count": len(claims),
        "claim_boundary": (
            "SHA-256 proves byte identity and the declared claim-to-artifact binding. "
            "It does not prove publisher accuracy, representativeness, causality or scientific truth."
        ),
    }
    return {**body, "ledger_sha256": sha256_bytes(canonical_json_bytes(body))}


def validate_claim_ledger(output_dir: Path, ledger: Any) -> list[str]:
    """Return exact mismatch messages after independently rebuilding the ledger."""

    if not isinstance(ledger, Mapping):
        return ["receipt claim_ledger must be an object"]
    try:
        expected = build_claim_ledger(output_dir)
    except ClaimLedgerError as exc:
        return [f"cannot recompute claim ledger: {exc}"]
    errors: list[str] = []
    if ledger.get("schema_version") != LEDGER_VERSION:
        errors.append("unsupported claim ledger version")
    supplied_claims = ledger.get("claims")
    expected_claims = expected["claims"]
    if not isinstance(supplied_claims, list):
        return errors + ["claim ledger claims must be an array"]
    supplied_by_id = {
        item.get("claim_id"): item
        for item in supplied_claims
        if isinstance(item, Mapping) and isinstance(item.get("claim_id"), str)
    }
    expected_by_id = {item["claim_id"]: item for item in expected_claims}
    if set(supplied_by_id) != set(expected_by_id):
        errors.append("claim ledger fixed claim IDs differ from recomputed claims")
    for claim_id in sorted(set(supplied_by_id) & set(expected_by_id)):
        supplied = supplied_by_id[claim_id]
        recomputed = expected_by_id[claim_id]
        if canonical_json_bytes(supplied) != canonical_json_bytes(recomputed):
            errors.append(f"claim mismatch for {claim_id}")
    if ledger.get("claim_count") != len(supplied_claims):
        errors.append("claim ledger claim_count does not match claims")
    if not isinstance(ledger.get("ledger_sha256"), str):
        errors.append("claim ledger lacks ledger_sha256")
    else:
        unsigned = dict(ledger)
        supplied_hash = unsigned.pop("ledger_sha256")
        if supplied_hash != sha256_bytes(canonical_json_bytes(unsigned)):
            errors.append("claim ledger self-hash mismatch")
        if supplied_hash != expected["ledger_sha256"]:
            errors.append("claim ledger hash differs from recomputed artifacts")
    return errors


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        ledger = build_claim_ledger(args.output_dir)
    except ClaimLedgerError as exc:
        parser.error(str(exc))
    print(json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
