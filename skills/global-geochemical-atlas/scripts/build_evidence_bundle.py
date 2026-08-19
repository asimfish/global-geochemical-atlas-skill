#!/usr/bin/env python3
"""Build the D1 provenance manifest and bind it to the D2 confidence report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MANIFEST_VERSION = "geochemical-source-manifest-v2"
RECORD_EVIDENCE_VERSION = "geochemical-record-evidence-v1"
RECORD_EVIDENCE_FILENAME = "record_evidence.jsonl"
CONFIDENCE_COMPONENTS = {"source", "completeness", "method", "spatial", "qc", "overall"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Research requests may contain up to 200k long-form measurements.  Filtered
# acquisition deduplicates repeated source-file metadata, but a fully auditable
# sidecar can still exceed the competition's *repository* size limit.  Runtime
# products are bounded separately: keep this ceiling aligned with the public
# output validators and never interpret it as permission to check generated
# research products into the <=250 MB submission repository.
MAX_EVIDENCE_BYTES = 600_000_000
REQUIRED_EVIDENCE_FIELDS = {
    "record_id",
    "source_id",
    "source_locator",
    "license",
    "analyte_reported",
}


class EvidenceError(ValueError):
    """Raised when provenance and analytical artifacts cannot be linked safely."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
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
                raise EvidenceError(
                    f"canonical database lacks provenance columns: {', '.join(missing)}"
                )
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


def source_url_is_evidence_safe(value: Any, file_hash: Any) -> bool:
    """Accept HTTPS, or a hash-pinned HTTP locator used by a legacy publisher."""

    if not isinstance(value, str):
        return False
    if value.startswith("https://"):
        return True
    return (
        value.startswith("http://weppi.gtk.fi/")
        and isinstance(file_hash, str)
        and SHA256_RE.fullmatch(file_hash) is not None
    )


def _declared_evidence(
    rows: Sequence[Mapping[str, str]],
) -> tuple[list[dict[str, Any]], bytes]:
    evidence_rows = [
        {
            "record_id": row.get("record_id") or "",
            "source_record_id": row.get("source_record_id") or None,
            "source_id": row.get("source_id") or "unknown",
            "source_locator": row.get("source_locator") or "",
            "license": row.get("license") or "",
            "analyte_reported": row.get("analyte_reported")
            or row.get("element_or_analyte")
            or "",
            "dataset_title": row.get("dataset_title") or None,
            "dataset_doi": row.get("dataset_doi") or None,
            "dataset_version": row.get("dataset_version") or None,
            "source_file": row.get("source_file") or None,
            "source_row": row.get("source_row") or None,
            "source_file_sha256": row.get("file_sha256") or None,
            "source_file_url": row.get("official_source_url") or None,
            "evidence_status": "source_declared_in_input",
            "evidence_version": RECORD_EVIDENCE_VERSION,
        }
        for row in rows
    ]
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in evidence_rows
    ).encode("utf-8")
    return evidence_rows, content


def load_record_evidence(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    if not path.is_file():
        raise EvidenceError(f"record evidence does not exist: {path}")
    if path.stat().st_size > MAX_EVIDENCE_BYTES:
        raise EvidenceError(
            f"record evidence exceeds {MAX_EVIDENCE_BYTES} byte safety limit"
        )
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError("record evidence is not valid UTF-8") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(
                f"record evidence line {line_number} is invalid JSON"
            ) from exc
        if not isinstance(value, dict):
            raise EvidenceError(f"record evidence line {line_number} must be an object")
        missing = sorted(
            field
            for field in REQUIRED_EVIDENCE_FIELDS
            if value.get(field) in (None, "")
        )
        if missing:
            raise EvidenceError(
                f"record evidence line {line_number} lacks required fields: {', '.join(missing)}"
            )
        file_hash = value.get("source_file_sha256")
        if file_hash is not None and (
            not isinstance(file_hash, str) or not SHA256_RE.fullmatch(file_hash)
        ):
            raise EvidenceError(
                f"record evidence line {line_number} has invalid source_file_sha256"
            )
        source_file = value.get("source_file")
        if source_file is not None and (
            not isinstance(source_file, str)
            or Path(source_file).name != source_file
            or source_file in {".", ".."}
        ):
            raise EvidenceError(
                f"record evidence line {line_number} has unsafe source_file"
            )
        source_url = value.get("source_file_url")
        if source_url is not None and not source_url_is_evidence_safe(
            source_url, file_hash
        ):
            raise EvidenceError(
                f"record evidence line {line_number} has an unsafe source_file_url; "
                "the allowlisted legacy HTTP publisher requires a pinned SHA-256"
            )
        for list_field in ("article_citations", "article_dois"):
            items = value.get(list_field)
            if items is not None and (
                not isinstance(items, list)
                or len(items) > 100
                or any(not isinstance(item, str) or not item for item in items)
            ):
                raise EvidenceError(
                    f"record evidence line {line_number} has invalid {list_field}"
                )
        rows.append(value)
    if not rows:
        raise EvidenceError("record evidence contains no records")
    rows_by_id = {str(item["record_id"]): item for item in rows}
    for item in rows:
        anchor_id = item.get("source_metadata_record_id")
        if anchor_id in (None, ""):
            continue
        if not isinstance(anchor_id, str):
            raise EvidenceError(
                "record evidence source_metadata_record_id must be a string"
            )
        anchor = rows_by_id.get(anchor_id)
        shared_fields = anchor.get("shared_source_metadata_fields") if anchor else None
        if (
            anchor is None
            or not isinstance(shared_fields, list)
            or not shared_fields
            or any(
                not isinstance(field, str) or field not in anchor or field in item
                for field in shared_fields
            )
            or any(
                item.get(field) != anchor.get(field)
                for field in ("source_id", "source_file", "source_file_sha256")
            )
        ):
            raise EvidenceError(
                f"record evidence {item.get('record_id')} has an invalid source metadata anchor"
            )
    return rows, raw


def validate_record_linkage(
    canonical: Sequence[Mapping[str, str]], evidence: Sequence[Mapping[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    canonical_by_id: dict[str, Mapping[str, str]] = {}
    for row in canonical:
        record_id = (row.get("record_id") or "").strip()
        if not record_id or record_id in canonical_by_id:
            raise EvidenceError(
                "canonical database record_id values must be non-empty and unique"
            )
        canonical_by_id[record_id] = row
    evidence_by_id: dict[str, Mapping[str, Any]] = {}
    for item in evidence:
        record_id = str(item.get("record_id") or "").strip()
        if record_id in evidence_by_id:
            raise EvidenceError(f"record evidence repeats record_id: {record_id}")
        evidence_by_id[record_id] = item
    missing = sorted(set(canonical_by_id) - set(evidence_by_id))
    unexpected = sorted(set(evidence_by_id) - set(canonical_by_id))
    if missing or unexpected:
        raise EvidenceError(
            f"record evidence IDs do not exactly match the canonical database; "
            f"missing={missing[:5]}, unexpected={unexpected[:5]}"
        )
    comparable_fields = {
        "source_record_id": "source_record_id",
        "source_id": "source_id",
        "source_locator": "source_locator",
        "license": "license",
        "analyte_reported": "analyte_reported",
        "dataset_title": "dataset_title",
        "dataset_doi": "dataset_doi",
        "dataset_version": "dataset_version",
        "source_file": "source_file",
        "source_row": "source_row",
        "source_file_sha256": "file_sha256",
    }
    required_comparable = {"source_id", "source_locator", "license", "analyte_reported"}
    for record_id, item in evidence_by_id.items():
        canonical_row = canonical_by_id[record_id]
        source_file_url = item.get("source_file_url")
        if source_file_url not in (None, "") and not source_url_is_evidence_safe(
            source_file_url, item.get("source_file_sha256")
        ):
            raise EvidenceError(
                f"record evidence {record_id} has an unsafe official source URL"
            )
        for evidence_field, canonical_field in comparable_fields.items():
            evidence_value = item.get(evidence_field)
            canonical_value = canonical_row.get(canonical_field)
            if evidence_field in required_comparable:
                if (
                    canonical_value in (None, "")
                    or str(evidence_value).strip() != str(canonical_value).strip()
                ):
                    raise EvidenceError(
                        f"record evidence {record_id} conflicts on required {evidence_field}: "
                        f"{evidence_value!r} != {canonical_value!r}"
                    )
                continue
            if evidence_value in (None, "") or canonical_value in (None, ""):
                continue
            if str(evidence_value).strip() != str(canonical_value).strip():
                raise EvidenceError(
                    f"record evidence {record_id} conflicts on {evidence_field}: "
                    f"{evidence_value!r} != {canonical_value!r}"
                )
        # Acquisition endpoints and clickable official landing pages are
        # distinct for POST-backed sources. Bind both roles independently.
        canonical_official_url = canonical_row.get("official_source_url")
        evidence_official_url = item.get("official_source_url") or source_file_url
        if canonical_official_url not in (None, ""):
            if (
                evidence_official_url in (None, "")
                or str(evidence_official_url).strip()
                != str(canonical_official_url).strip()
            ):
                raise EvidenceError(
                    f"record evidence {record_id} does not bind canonical official_source_url"
                )
            if not source_url_is_evidence_safe(
                evidence_official_url, item.get("source_file_sha256")
            ):
                raise EvidenceError(
                    f"record evidence {record_id} has an unsafe official source URL"
                )
    return evidence_by_id


def acquisition_binding(
    path: Path | None,
    input_path: Path,
    evidence_path: Path | None,
    evidence_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, str, bool]:
    if path is None:
        return None, "input", False
    manifest = json_object(path, "acquisition manifest")
    if manifest.get("data_mode") not in {"fixture", "online", "cached"}:
        raise EvidenceError("acquisition manifest has an unsupported data_mode")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise EvidenceError("acquisition manifest must contain an outputs array")
    output_entries = [
        item
        for item in outputs
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    if len(output_entries) != len(outputs) or len(
        {item["path"] for item in output_entries}
    ) != len(output_entries):
        raise EvidenceError(
            "acquisition manifest has invalid or duplicate output paths"
        )
    hashes = {item["path"]: item.get("sha256") for item in output_entries}
    if hashes.get(input_path.name) != sha256_file(input_path):
        raise EvidenceError("acquisition manifest does not bind the input CSV hash")
    if evidence_path is None or hashes.get(evidence_path.name) != sha256_file(
        evidence_path
    ):
        raise EvidenceError(
            "acquisition manifest does not bind the record evidence hash"
        )
    source_files = manifest.get("source_files")
    if not isinstance(source_files, list) or not source_files:
        raise EvidenceError("acquisition manifest must contain source_files")
    acquired_files: dict[str, tuple[str, str]] = {}
    for entry in source_files:
        if not isinstance(entry, dict):
            raise EvidenceError("acquisition manifest contains an invalid source file")
        filename = entry.get("filename")
        file_hash = entry.get("sha256")
        source_url = entry.get("source_url")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or filename in acquired_files
            or not isinstance(file_hash, str)
            or not SHA256_RE.fullmatch(file_hash)
            or not source_url_is_evidence_safe(source_url, file_hash)
        ):
            raise EvidenceError(
                "acquisition manifest contains unsafe or incomplete source-file evidence"
            )
        acquired_files[filename] = (file_hash, source_url)
    for item in evidence_rows:
        filename = item.get("source_file")
        file_hash = item.get("source_file_sha256")
        source_url = item.get("source_file_url")
        if not isinstance(filename, str) or not isinstance(file_hash, str):
            raise EvidenceError(
                "verified record evidence requires source_file and source_file_sha256"
            )
        acquired = acquired_files.get(filename)
        if (
            acquired is None
            or acquired[0] != file_hash
            or (source_url is not None and acquired[1] != source_url)
        ):
            raise EvidenceError(
                f"record evidence is not bound to acquired source file: {filename}"
            )
    failures = manifest.get("failures")
    if not isinstance(failures, list) or failures:
        raise EvidenceError("acquisition manifest must declare an empty failures array")
    if not isinstance(manifest.get("not_for_scientific_interpretation"), bool):
        raise EvidenceError(
            "acquisition manifest has no boolean scientific-interpretation boundary"
        )
    not_for_science = manifest.get("not_for_scientific_interpretation") is True
    return (
        {
            "filename": path.name,
            "sha256": sha256_file(path),
            "data_mode": manifest["data_mode"],
            "generation_version": manifest.get("demo_generation_version"),
            "not_for_scientific_interpretation": not_for_science,
        },
        str(manifest["data_mode"]),
        not_for_science,
    )


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
        raise EvidenceError(
            "confidence report input_sha256 does not match the acquired input"
        )
    component_means = report.get("component_means")
    if not isinstance(component_means, dict) or not CONFIDENCE_COMPONENTS.issubset(
        component_means
    ):
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
    evidence_rows: Sequence[Mapping[str, Any]],
    evidence_hash: str,
    evidence_level: str,
    acquisition: Mapping[str, Any] | None,
    data_mode: str,
    not_for_scientific_interpretation: bool,
) -> tuple[dict[str, Any], bool]:
    evidence_by_id = {str(item["record_id"]): item for item in evidence_rows}
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        source_id = (row.get("source_id") or "unknown").strip() or "unknown"
        grouped[source_id].append(row)

    sources: list[dict[str, Any]] = []
    synthetic_present = False
    located_records = 0
    licensed_records = 0
    verified_records = 0
    for source_id in sorted(grouped):
        source_rows = grouped[source_id]
        source_evidence = [evidence_by_id[row["record_id"]] for row in source_rows]
        locators = sorted(
            {
                row.get("source_locator")
                for row in source_rows
                if row.get("source_locator")
            }
        )
        licenses = sorted(
            {row.get("license") for row in source_rows if row.get("license")}
        )
        tiers = sorted(
            {row.get("source_tier") for row in source_rows if row.get("source_tier")}
        )
        dataset_titles = sorted(
            {
                str(item["dataset_title"])
                for item in source_evidence
                if item.get("dataset_title")
            }
        )
        dataset_dois = sorted(
            {
                str(item["dataset_doi"])
                for item in source_evidence
                if item.get("dataset_doi")
            }
        )
        dataset_versions = sorted(
            {
                str(item["dataset_version"])
                for item in source_evidence
                if item.get("dataset_version")
            }
        )
        source_files = sorted(
            {
                (
                    str(item.get("source_file") or ""),
                    str(item.get("source_file_sha256") or ""),
                    str(item.get("source_file_url") or ""),
                )
                for item in source_evidence
                if item.get("source_file")
            }
        )
        official_source_urls = sorted(
            {
                str(item.get("official_source_url") or item.get("source_file_url"))
                for item in source_evidence
                if item.get("official_source_url") or item.get("source_file_url")
            }
        )
        article_citations = sorted(
            {
                str(citation)
                for item in source_evidence
                for citation in item.get("article_citations", [])
                if citation
            }
        )
        article_dois = sorted(
            {
                str(doi)
                for item in source_evidence
                for doi in item.get("article_dois", [])
                if doi
            }
        )
        is_synthetic = source_id.casefold().startswith("synthetic")
        synthetic_present = synthetic_present or is_synthetic
        located = sum(bool(row.get("source_locator")) for row in source_rows)
        licensed = sum(bool(row.get("license")) for row in source_rows)
        located_records += located
        licensed_records += licensed
        source_verified = (
            len(source_rows) if evidence_level == "verified_record_evidence" else 0
        )
        verified_records += source_verified
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
                "verified_record_count": source_verified,
                "dataset_titles": dataset_titles,
                "dataset_dois": dataset_dois,
                "dataset_versions": dataset_versions,
                "source_files": [
                    {
                        "filename": filename,
                        "sha256": file_hash or None,
                        "url": url or None,
                    }
                    for filename, file_hash, url in source_files
                ],
                "official_source_urls": official_source_urls,
                "article_citations": article_citations,
                "article_dois": article_dois,
                "evidence_type": "synthetic_demo" if is_synthetic else evidence_level,
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
            "records_with_verified_evidence": verified_records,
            "verified_evidence_rate": round(verified_records / record_count, 6),
        },
        "sources": sources,
        "record_evidence": {
            "filename": RECORD_EVIDENCE_FILENAME,
            "sha256": evidence_hash,
            "schema_version": RECORD_EVIDENCE_VERSION,
            "record_count": len(evidence_rows),
            "exact_record_id_match": True,
            "evidence_level": evidence_level,
            "acquisition_manifest": dict(acquisition)
            if acquisition is not None
            else None,
        },
        "confidence_report": dict(confidence),
        "data_mode": data_mode,
        "not_for_scientific_interpretation": not_for_scientific_interpretation,
        "synthetic_data_present": synthetic_present,
        "claim_boundary": (
            "Record evidence is hash-bound and record-ID matched when evidence_level is verified_record_evidence. "
            "A verified chain proves provenance linkage, not measurement truth or method comparability. "
            "Declared licenses still require source-specific review."
        ),
    }
    return manifest, synthetic_present


def package_evidence(
    input_path: Path,
    database_path: Path,
    confidence_path: Path,
    output_path: Path,
    evidence_path: Path | None = None,
    acquisition_manifest_path: Path | None = None,
) -> tuple[dict[str, Any], bool]:
    if not input_path.is_file():
        raise EvidenceError(f"acquired input does not exist: {input_path}")
    input_hash = sha256_file(input_path)
    rows = canonical_rows(database_path)
    confidence = confidence_binding(confidence_path, input_hash)
    if evidence_path is None:
        evidence_rows, evidence_content = _declared_evidence(rows)
        evidence_level = "source_declared_in_input"
    else:
        evidence_rows, evidence_content = load_record_evidence(evidence_path)
        evidence_level = "validated_record_evidence"
    validate_record_linkage(rows, evidence_rows)
    acquisition, data_mode, not_for_science = acquisition_binding(
        acquisition_manifest_path, input_path, evidence_path, evidence_rows
    )
    if acquisition is not None:
        evidence_level = "verified_record_evidence"
    synthetic_present = any(
        str(row.get("source_id") or "").casefold().startswith("synthetic")
        for row in rows
    )
    if synthetic_present:
        data_mode = "synthetic_fixture"
        not_for_science = True
    evidence_output = output_path.with_name(RECORD_EVIDENCE_FILENAME)
    evidence_hash = hashlib.sha256(evidence_content).hexdigest()
    manifest, synthetic_present = build_source_manifest(
        input_path,
        input_hash,
        rows,
        confidence,
        evidence_rows,
        evidence_hash,
        evidence_level,
        acquisition,
        data_mode,
        not_for_science,
    )
    atomic_bytes(evidence_output, evidence_content)
    atomic_json(output_path, manifest)
    return manifest, synthetic_present


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package record-level sources and bind them to a precomputed D2 confidence report."
    )
    parser.add_argument(
        "--input", required=True, type=Path, help="D1 acquired or bundled source CSV"
    )
    parser.add_argument(
        "--database", required=True, type=Path, help="D2 canonical geochemistry.csv"
    )
    parser.add_argument(
        "--confidence-report",
        required=True,
        type=Path,
        help="D2 confidence_report.json",
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Destination source_manifest.json"
    )
    parser.add_argument(
        "--evidence-jsonl", type=Path, help="Optional D1 record-level evidence sidecar"
    )
    parser.add_argument(
        "--acquisition-manifest",
        type=Path,
        help="Optional D1 run manifest that hash-binds the input and evidence sidecar",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest, synthetic_present = package_evidence(
            args.input,
            args.database,
            args.confidence_report,
            args.output,
            args.evidence_jsonl,
            args.acquisition_manifest,
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
