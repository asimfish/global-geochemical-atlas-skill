#!/usr/bin/env python3
"""Build the D1 provenance manifest and bind it to the D2 confidence report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MANIFEST_VERSION = "geochemical-source-manifest-v1"
CONFIDENCE_COMPONENTS = {"source", "completeness", "method", "spatial", "qc", "overall"}


class EvidenceError(ValueError):
    """Raised when provenance and analytical artifacts cannot be linked safely."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise EvidenceError(f"canonical database does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = set(reader.fieldnames or [])
            required = {"source_id", "source_locator", "license", "source_tier"}
            missing = sorted(required - headers)
            if missing:
                raise EvidenceError(f"canonical database lacks provenance columns: {', '.join(missing)}")
            rows = list(reader)
    except UnicodeError as exc:
        raise EvidenceError("canonical database is not valid UTF-8") from exc
    if not rows:
        raise EvidenceError("canonical database contains no records")
    return rows


def json_object(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise EvidenceError(f"{label} does not exist: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} must be a JSON object")
    return value


def confidence_binding(confidence_path: Path, input_hash: str) -> dict[str, Any]:
    """Validate linkage only; D1 must not recompute the D2 confidence algorithm."""

    report = json_object(confidence_path, "confidence report")
    if report.get("not_a_probability") is not True:
        raise EvidenceError("confidence report must declare not_a_probability=true")
    version = report.get("confidence_version")
    if not isinstance(version, str) or not version:
        raise EvidenceError("confidence report has no confidence_version")
    run_metadata = report.get("run_metadata")
    if not isinstance(run_metadata, dict):
        raise EvidenceError("confidence report has no run_metadata object")
    if run_metadata.get("input_sha256") != input_hash:
        raise EvidenceError("confidence report input_sha256 does not match the acquired input")
    component_means = report.get("component_means")
    if not isinstance(component_means, dict) or not CONFIDENCE_COMPONENTS.issubset(component_means):
        raise EvidenceError("confidence report is missing required component means")
    return {
        "filename": confidence_path.name,
        "sha256": sha256_file(confidence_path),
        "confidence_version": version,
        "run_id": run_metadata.get("run_id"),
        "input_sha256": input_hash,
        "not_a_probability": True,
        "contract": "D2 computes confidence; D1 validates provenance linkage and packages the report unchanged.",
    }


def build_source_manifest(
    input_path: Path,
    input_hash: str,
    rows: Sequence[Mapping[str, str]],
    confidence: Mapping[str, Any],
) -> tuple[dict[str, Any], bool]:
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        source_id = (row.get("source_id") or "unknown").strip() or "unknown"
        grouped[source_id].append(row)

    sources: list[dict[str, Any]] = []
    synthetic_present = False
    located_records = 0
    licensed_records = 0
    for source_id in sorted(grouped):
        source_rows = grouped[source_id]
        locators = sorted({row.get("source_locator") for row in source_rows if row.get("source_locator")})
        licenses = sorted({row.get("license") for row in source_rows if row.get("license")})
        tiers = sorted({row.get("source_tier") for row in source_rows if row.get("source_tier")})
        is_synthetic = source_id.casefold().startswith("synthetic")
        synthetic_present = synthetic_present or is_synthetic
        located = sum(bool(row.get("source_locator")) for row in source_rows)
        licensed = sum(bool(row.get("license")) for row in source_rows)
        located_records += located
        licensed_records += licensed
        if is_synthetic and "CC0-1.0" in licenses:
            license_review = "demo_cc0"
        elif not licenses or licensed != len(source_rows):
            license_review = "unresolved"
        else:
            license_review = "verify_source_terms"
        sources.append(
            {
                "source_id": source_id,
                "record_count": len(source_rows),
                "source_tiers": tiers,
                "licenses": licenses,
                "located_record_count": located,
                "locator_count": len(locators),
                "example_locators": locators[:5],
                "all_records_located": located == len(source_rows),
                "all_records_license_declared": licensed == len(source_rows),
                "evidence_type": "synthetic_demo" if is_synthetic else "source_declared_in_input",
                "license_review": license_review,
            }
        )

    record_count = len(rows)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "input": {
            "filename": input_path.name,
            "sha256": input_hash,
            "bytes": input_path.stat().st_size,
            "record_count": record_count,
        },
        "source_count": len(sources),
        "coverage": {
            "records_with_source_locator": located_records,
            "records_with_declared_license": licensed_records,
            "source_locator_rate": round(located_records / record_count, 6),
            "declared_license_rate": round(licensed_records / record_count, 6),
        },
        "sources": sources,
        "confidence_report": dict(confidence),
        "synthetic_data_present": synthetic_present,
        "claim_boundary": (
            "Source fields are preserved from the input. A locator is not independently verified unless a download "
            "manifest or source-specific audit says so. Declared licenses still require source-specific review."
        ),
    }
    return manifest, synthetic_present


def package_evidence(
    input_path: Path,
    database_path: Path,
    confidence_path: Path,
    output_path: Path,
) -> tuple[dict[str, Any], bool]:
    if not input_path.is_file():
        raise EvidenceError(f"acquired input does not exist: {input_path}")
    input_hash = sha256_file(input_path)
    rows = canonical_rows(database_path)
    confidence = confidence_binding(confidence_path, input_hash)
    manifest, synthetic_present = build_source_manifest(input_path, input_hash, rows, confidence)
    atomic_json(output_path, manifest)
    return manifest, synthetic_present


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package record-level sources and bind them to a precomputed D2 confidence report."
    )
    parser.add_argument("--input", required=True, type=Path, help="D1 acquired or bundled source CSV")
    parser.add_argument("--database", required=True, type=Path, help="D2 canonical geochemistry.csv")
    parser.add_argument("--confidence-report", required=True, type=Path, help="D2 confidence_report.json")
    parser.add_argument("--output", required=True, type=Path, help="Destination source_manifest.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest, synthetic_present = package_evidence(
            args.input, args.database, args.confidence_report, args.output
        )
    except (EvidenceError, OSError) as exc:
        print(f"build_evidence_bundle: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": "success",
                "output": str(args.output),
                "source_count": manifest["source_count"],
                "synthetic_data_present": synthetic_present,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
