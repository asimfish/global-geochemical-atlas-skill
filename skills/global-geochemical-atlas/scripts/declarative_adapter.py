"""Execute a declarative adapter spec into a provided-input package.

This is the in-run half of the gap-to-data closure described in
``references/declarative-adapter.md``. A spec (validated against
``references/declarative-adapter.schema.json``) turns a newly discovered
tabular source into the documented provided-input trio:

    <workspace>/demo_input.csv           measurements in the standard long table
    <workspace>/sources.jsonl            one evidence row per measurement
    <workspace>/acquisition_manifest.json  hash-bound acquisition receipt
    <workspace>/adapter_receipt.json     every gate decision, fail-closed

The package is consumed by the documented input contract, for example:

    python scripts/run_atlas_request.py --request REQUEST.json \
        --input WS/demo_input.csv --evidence-jsonl WS/sources.jsonl \
        --acquisition-manifest WS/acquisition_manifest.json --output-dir OUT

Doctrine guarantees (all fail closed):

- the frozen skill snapshot is never modified; specs are hash-bound run
  inputs recorded in the receipt and in every evidence row;
- license must be in the frozen open-license allowlist and carry an
  evidence URL; unknown licenses never pass;
- downloads are HTTPS-only, size-capped, and sha256-pinned (a spec without
  ``expected_sha256`` pins the first fetched hash into receipt + evidence);
- records from this channel are namespaced ``spec-*`` and marked
  ``in_run_adapter`` so they can never impersonate a registered adapter;
- unmapped units, unknown media and unparseable rows are rejected row by
  row with reason codes, never guessed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SPEC_VERSION = "declarative-adapter-spec-v1"
ENGINE_VERSION = "declarative-adapter-engine-v1"
EVIDENCE_VERSION = "in-run-declarative-adapter-v1"

# Frozen open-license allowlist. Extending it is a skill maintenance action,
# not a runtime decision.
LICENSE_ALLOWLIST = {
    "CC0-1.0",
    "CC-BY-4.0",
    "CC-BY-SA-4.0",
    "ODC-By-1.0",
    "ODbL-1.0",
    "LicenseRef-USGS-Public-Domain",
    "LicenseRef-Public-Domain",
    "LicenseRef-Open-Government-Licence-3.0",
}
ALLOWED_MEDIA = {"rock", "soil", "sediment", "water"}
# Units the standardization layer can normalize; anything else is rejected
# per row with a reason code instead of being guessed.
ACCEPTED_UNITS = {
    "mg/kg",
    "ppm",
    "ug/g",
    "ng/g",
    "wt%",
    "%",
    "ug/l",
    "mg/l",
    "ng/l",
    "ppb",
}
MAX_SNIFF_BYTES = 4 << 20

INPUT_COLUMNS = [
    "record_id",
    "source_id",
    "source_record_id",
    "sample_id",
    "element_or_analyte",
    "analyte_reported",
    "value",
    "unit",
    "medium",
    "latitude",
    "longitude",
    "source_crs",
    "analytical_method",
    "method_source_locator",
    "source_locator",
    "license",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_file",
    "source_row",
    "file_sha256",
    "official_source_url",
]


class SpecError(RuntimeError):
    """Raised when the spec itself is invalid; nothing is acquired."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_spec(spec: dict[str, Any], *, allow_auto: bool) -> list[str]:
    problems: list[str] = []
    if spec.get("spec_version") != SPEC_VERSION:
        problems.append(f"spec_version must be {SPEC_VERSION}")
    source_id = str(spec.get("source_id", ""))
    if not re.fullmatch(r"spec-[a-z0-9][a-z0-9-]{2,62}", source_id):
        problems.append("source_id must match ^spec-[a-z0-9-]+$")
    for field in ("title", "official_source_url"):
        if not spec.get(field):
            problems.append(f"missing {field}")
    if not str(spec.get("dataset_version") or "").strip():
        problems.append(
            "dataset_version is required (publisher version or an explicit "
            "'accessed YYYY-MM-DD' statement); versionless evidence chains fail closed"
        )
    if not str(spec.get("official_source_url", "")).startswith("https://"):
        problems.append("official_source_url must be https")
    license_block = spec.get("license") or {}
    license_id = str(license_block.get("id", ""))
    if license_id not in LICENSE_ALLOWLIST:
        problems.append(
            f"license {license_id!r} is not in the frozen open-license allowlist; "
            "fail closed (do not guess licenses)"
        )
    if not str(license_block.get("evidence_url", "")).startswith("https://"):
        problems.append("license.evidence_url must be an https evidence page")
    download = spec.get("download") or {}
    if not str(download.get("url", "")).startswith("https://"):
        problems.append("download.url must be https")
    max_bytes = download.get("max_bytes")
    if not isinstance(max_bytes, int) or max_bytes < 1:
        problems.append("download.max_bytes must be a positive integer")
    if spec.get("format") not in ("csv", "tsv", "json_records"):
        problems.append("format must be csv, tsv or json_records")
    if spec.get("layout") not in ("long", "wide"):
        problems.append("layout must be long or wide")
    medium = spec.get("medium") or {}
    if not medium.get("constant") and not medium.get("column"):
        problems.append("medium requires constant or column")
    if medium.get("constant") and medium["constant"] not in ALLOWED_MEDIA:
        problems.append(f"medium.constant must be one of {sorted(ALLOWED_MEDIA)}")
    mapping = spec.get("mapping") or {}
    if spec.get("layout") == "long" and not mapping.get("long_format"):
        problems.append("layout long requires mapping.long_format")
    if spec.get("layout") == "wide" and not mapping.get("wide_observations"):
        problems.append("layout wide requires mapping.wide_observations")
    coordinate = spec.get("coordinate") or {}
    if coordinate.get("crs_declared") and not coordinate.get("crs_evidence_url"):
        problems.append(
            "coordinate.crs_declared requires crs_evidence_url; publisher-declared "
            "CRS must be evidenced, never assumed"
        )
    approval = spec.get("approval_state")
    if approval == "draft":
        problems.append("spec is a draft; set approval_state after human review")
    elif approval == "auto_candidate_open_license" and not allow_auto:
        problems.append(
            "auto_candidate_open_license requires --allow-auto-approved "
            "from the operator or controlling loop"
        )
    elif approval not in (
        "draft",
        "approved_by_operator",
        "auto_candidate_open_license",
    ):
        problems.append("approval_state invalid")
    return problems


def fetch_bytes(spec: dict[str, Any], *, local_file: Path | None) -> tuple[bytes, str]:
    download = spec["download"]
    if local_file is not None:
        data = local_file.read_bytes()
        origin = f"file://{local_file}"
    else:
        request = urllib.request.Request(
            download["url"],
            headers={"User-Agent": "global-geochemical-atlas-declarative-adapter/1"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(int(download["max_bytes"]) + 1)
        origin = download["url"]
    if len(data) > int(download["max_bytes"]):
        raise SpecError(
            f"download exceeds max_bytes={download['max_bytes']}; refusing oversized payload"
        )
    digest = sha256_bytes(data)
    expected = download.get("expected_sha256")
    if expected and digest != expected:
        raise SpecError(
            f"sha256 mismatch: expected {expected}, fetched {digest}; fail closed"
        )
    spec["_fetched_from"] = origin
    return data, digest


def parse_table(spec: dict[str, Any], data: bytes) -> list[dict[str, Any]]:
    encoding = spec.get("encoding") or "utf-8"
    text = data.decode(encoding, errors="strict")
    fmt = spec["format"]
    if fmt in ("csv", "tsv"):
        delimiter = "," if fmt == "csv" else "\t"
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [dict(row) for row in reader]
    records = json.loads(text)
    if not isinstance(records, list):
        raise SpecError("json_records payload must be a top-level JSON array")
    return [dict(row) for row in records if isinstance(row, dict)]


def passes_filters(row: dict[str, Any], spec: dict[str, Any]) -> bool:
    for rule in spec.get("row_filters") or []:
        raw = row.get(rule["column"])
        if rule["op"] == "not_null":
            if raw is None or str(raw).strip() == "":
                return False
        elif rule["op"] == "equals":
            if str(raw) != str(rule["value"]):
                return False
        elif rule["op"] == "in":
            if str(raw) not in [str(v) for v in rule["value"]]:
                return False
    return True


def resolve_medium(row: dict[str, Any], spec: dict[str, Any]) -> str | None:
    medium = spec["medium"]
    if medium.get("constant"):
        return str(medium["constant"])
    raw = str(row.get(medium["column"], "")).strip()
    value_map = medium.get("value_map") or {}
    mapped = value_map.get(raw, raw.lower())
    return mapped if mapped in ALLOWED_MEDIA else None


def numeric_or_none(raw: Any) -> float | None:
    text = str(raw).strip() if raw is not None else ""
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def extract_observations(
    row: dict[str, Any], spec: dict[str, Any]
) -> list[tuple[str, str, str]]:
    """Yield (analyte, raw_value, unit) tuples for one source row."""

    mapping = spec["mapping"]
    observations: list[tuple[str, str, str]] = []
    if spec["layout"] == "long":
        block = mapping["long_format"]
        analyte = str(row.get(block["analyte_column"], "")).strip()
        raw_value = str(row.get(block["value_column"], "")).strip()
        if block.get("unit_column"):
            unit = str(row.get(block["unit_column"], "")).strip()
        else:
            unit = str(block.get("unit_constant", "")).strip()
        if analyte and raw_value:
            observations.append((analyte, raw_value, unit))
    else:
        for block in mapping["wide_observations"]:
            raw_value = str(row.get(block["value_column"], "")).strip()
            if raw_value:
                observations.append(
                    (str(block["analyte"]), raw_value, str(block["unit_constant"]))
                )
    return observations


def run_spec(
    spec_path: Path,
    workspace: Path,
    *,
    allow_auto: bool,
    local_file: Path | None,
) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_sha = sha256_bytes(spec_path.read_bytes())
    problems = validate_spec(spec, allow_auto=allow_auto)
    if problems:
        raise SpecError("; ".join(problems))

    data, digest = fetch_bytes(spec, local_file=local_file)
    workspace.mkdir(parents=True, exist_ok=True)
    raw_name = (
        f"{spec['source_id']}-raw.{spec['format'].replace('json_records', 'json')}"
    )
    (workspace / raw_name).write_bytes(data)

    rows = parse_table(spec, data)
    mapping = spec["mapping"]
    coordinate = spec.get("coordinate") or {}
    crs = coordinate.get("crs_declared")
    source_id = spec["source_id"]
    license_id = spec["license"]["id"]

    measurements: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    rejections: dict[str, int] = {}

    def reject(reason: str) -> None:
        rejections[reason] = rejections.get(reason, 0) + 1

    for index, row in enumerate(
        rows, start=2 if spec["format"] != "json_records" else 1
    ):
        if not passes_filters(row, spec):
            reject("row_filtered_out")
            continue
        medium = resolve_medium(row, spec)
        if medium is None:
            reject("medium_unmapped")
            continue
        latitude = longitude = None
        if mapping.get("latitude_column") and mapping.get("longitude_column"):
            latitude = numeric_or_none(row.get(mapping["latitude_column"]))
            longitude = numeric_or_none(row.get(mapping["longitude_column"]))
            if latitude is None or longitude is None:
                reject("coordinates_unparseable")
                latitude = longitude = None
            elif not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
                reject("coordinates_out_of_range")
                latitude = longitude = None
        sample_id = None
        if mapping.get("sample_id_column"):
            sample_id = str(row.get(mapping["sample_id_column"], "")).strip() or None
        # A method claim needs its own evidence locator: row-level methods
        # point at the row; spec constants point at the publisher page the
        # spec author read (recorded in official_source_url).
        method = None
        method_locator = None
        if mapping.get("method_column"):
            method = str(row.get(mapping["method_column"], "")).strip() or None
            if method:
                method_locator = "same_row"
        elif mapping.get("method_constant"):
            method = str(mapping["method_constant"])
            method_locator = spec["official_source_url"]
        for analyte, raw_value, unit in extract_observations(row, spec):
            if unit.lower() not in ACCEPTED_UNITS:
                reject(f"unit_not_accepted:{unit or 'empty'}")
                continue
            source_record_id = f"{source_id}:{index}:{analyte}"
            record_id = (
                "rec-"
                + hashlib.sha256(
                    f"{source_id}|{index}|{analyte}|{raw_value}".encode()
                ).hexdigest()
            )
            locator = f"file:{raw_name}:row:{index}"
            measurements.append(
                {
                    "record_id": record_id,
                    "source_id": source_id,
                    "source_record_id": source_record_id,
                    "sample_id": sample_id or f"{source_id}-row-{index}",
                    "element_or_analyte": analyte,
                    "analyte_reported": analyte,
                    "value": raw_value,
                    "unit": unit,
                    "medium": medium,
                    "latitude": "" if latitude is None else latitude,
                    "longitude": "" if longitude is None else longitude,
                    "source_crs": crs or "",
                    "analytical_method": method or "",
                    "method_source_locator": (
                        locator
                        if method_locator == "same_row"
                        else (method_locator or "")
                    )
                    if method
                    else "",
                    "source_locator": locator,
                    "license": license_id,
                    "dataset_title": spec["title"],
                    "dataset_doi": spec.get("dataset_doi") or "",
                    "dataset_version": spec.get("dataset_version") or "",
                    "source_file": raw_name,
                    "source_row": index,
                    "file_sha256": digest,
                    "official_source_url": spec["official_source_url"],
                }
            )
            evidence.append(
                {
                    "record_id": record_id,
                    "source_record_id": source_record_id,
                    "source_id": source_id,
                    "source_locator": f"file:{raw_name}:row:{index}",
                    "license": license_id,
                    "analyte_reported": analyte,
                    "dataset_title": spec["title"],
                    "dataset_doi": spec.get("dataset_doi"),
                    "dataset_version": spec.get("dataset_version"),
                    "source_file": raw_name,
                    "source_row": index,
                    "source_file_sha256": digest,
                    "source_file_url": spec["download"]["url"],
                    "official_source_url": spec["official_source_url"],
                    "evidence_version": EVIDENCE_VERSION,
                    "evidence_status": "in_run_declarative_adapter",
                    "in_run_adapter": True,
                    "adapter_spec_sha256": spec_sha,
                    "license_evidence_url": spec["license"]["evidence_url"],
                }
            )

    if not measurements:
        raise SpecError(
            "spec produced zero accepted measurements; inspect adapter_receipt.json rejections"
        )

    input_path = workspace / "demo_input.csv"
    with input_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=INPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(measurements)
    evidence_path = workspace / "sources.jsonl"
    with evidence_path.open("w", encoding="utf-8") as handle:
        for row in evidence:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "demo_generation_version": "d1-research-slice-v1",
        "data_mode": "online" if local_file is None else "cached",
        "scientific_scope": (
            f"declarative in-run adapter acquisition for {source_id}; "
            "screening-tier supplementary evidence"
        ),
        "not_for_scientific_interpretation": True,
        "generated_at": utc_now(),
        "source": {
            "source_id": source_id,
            "title": spec["title"],
            "official_source_url": spec["official_source_url"],
            "license": license_id,
            "adapter_spec_sha256": spec_sha,
            "engine_version": ENGINE_VERSION,
            "fetched_from": spec.get("_fetched_from"),
        },
        "generation_request": {"spec_path": str(spec_path)},
        "source_files": [
            {
                "filename": raw_name,
                "source_url": spec["download"]["url"],
                "bytes": len(data),
                "sha256": digest,
                "retrieved_at": utc_now(),
            }
        ],
        "record_counts": {
            "source_rows": len(rows),
            "accepted_measurements": len(measurements),
        },
        "outputs": [
            {
                "path": "demo_input.csv",
                "bytes": input_path.stat().st_size,
                "sha256": sha256_bytes(input_path.read_bytes()),
            },
            {
                "path": "sources.jsonl",
                "bytes": evidence_path.stat().st_size,
                "sha256": sha256_bytes(evidence_path.read_bytes()),
            },
        ],
        "warnings": [],
        "failures": [],
    }
    (workspace / "acquisition_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    receipt = {
        "engine_version": ENGINE_VERSION,
        "spec_path": str(spec_path),
        "spec_sha256": spec_sha,
        "source_id": source_id,
        "approval_state": spec["approval_state"],
        "license": {
            "id": license_id,
            "evidence_url": spec["license"]["evidence_url"],
            "allowlist_gate": "passed",
        },
        "download": {
            "url": spec["download"]["url"],
            "bytes": len(data),
            "sha256": digest,
            "expected_sha256": spec["download"].get("expected_sha256"),
            "hash_pinned_at_acquisition": spec["download"].get("expected_sha256")
            is None,
            "local_file_test_mode": local_file is not None,
        },
        "coordinate_policy": {
            "crs_declared": crs,
            "crs_evidence_url": coordinate.get("crs_evidence_url"),
            "disposition": "canonical_candidate" if crs else "reported_only",
        },
        "counts": {
            "source_rows": len(rows),
            "accepted_measurements": len(measurements),
            "rejections": rejections,
        },
        "target_gap": spec.get("target_gap"),
        "claim_boundary": (
            "records from this channel are supplementary screening evidence from an "
            "in-run declarative adapter; they are namespaced spec-* and never "
            "impersonate a registered adapter or upgrade evidence tiers"
        ),
        "next_command": (
            "python scripts/run_atlas_request.py --request REQUEST.json "
            f"--input {input_path} --evidence-jsonl {evidence_path} "
            f"--acquisition-manifest {workspace / 'acquisition_manifest.json'} "
            "--output-dir SUPPLEMENTARY_OUTPUT_DIR"
        ),
    }
    (workspace / "adapter_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument(
        "--allow-auto-approved",
        action="store_true",
        help="permit approval_state=auto_candidate_open_license specs",
    )
    parser.add_argument(
        "--local-file",
        type=Path,
        default=None,
        help="test/fixture mode: read payload bytes from a local file instead of the network",
    )
    args = parser.parse_args()
    try:
        receipt = run_spec(
            args.spec.resolve(),
            args.workspace.resolve(),
            allow_auto=args.allow_auto_approved,
            local_file=args.local_file.resolve() if args.local_file else None,
        )
    except SpecError as exc:
        print(
            json.dumps(
                {"status": "fail_closed", "reason": str(exc)}, ensure_ascii=False
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "acquired",
                "source_id": receipt["source_id"],
                "accepted_measurements": receipt["counts"]["accepted_measurements"],
                "rejections": receipt["counts"]["rejections"],
                "workspace": str(args.workspace.resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
