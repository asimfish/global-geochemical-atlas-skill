#!/usr/bin/env python3
"""Reconcile the frozen MarChem snapshot against its canonical D1 adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_SNAPSHOT_MANIFEST = (
    SKILL_DIR
    / "fixtures"
    / "four-media"
    / "sediment"
    / "norway-marchem"
    / "snapshot_manifest.json"
)
RECONCILIATION_VERSION = "marchem-adapter-reconciliation-v1"


class ReconciliationError(RuntimeError):
    """Raised when the snapshot and adapter do not reconcile exactly."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _snapshot(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReconciliationError(f"snapshot manifest is unreadable: {path}") from exc
    if not isinstance(value, dict) or value.get("source_id") != "norway-marchem":
        raise ReconciliationError("snapshot manifest is not the registered MarChem snapshot")
    return value


def reconcile(archive: Path, snapshot_manifest: Path = DEFAULT_SNAPSHOT_MANIFEST) -> dict[str, Any]:
    adapter = source_adapters.get_adapter("norway-marchem")
    if not isinstance(adapter, source_adapters.MarchemSnapshotAdapter):
        raise ReconciliationError("norway-marchem does not resolve to the canonical adapter")
    snapshot = _snapshot(snapshot_manifest)
    with tempfile.TemporaryDirectory(prefix="marchem-adapter-") as temporary:
        members = adapter.files_from_archive(archive, Path(temporary) / "members")
        records = list(adapter.parse(members))

    target_fields: Mapping[str, str] = adapter.candidate.registry_entry["target_analytes"]
    expected: Mapping[str, int] = adapter.candidate.registry_entry["expected_counts"]
    sample_counts = Counter(str(record.fields.get("Sample_code") or "") for record in records)
    target_rows = [
        record
        for record in records
        if any(str(record.fields.get(field) or "").strip() for field in target_fields.values())
    ]
    target_value_counts = {
        analyte: sum(bool(str(record.fields.get(field) or "").strip()) for record in records)
        for analyte, field in target_fields.items()
    }
    censored_counts = {
        analyte: sum(str(record.fields.get(field) or "").strip().startswith("<") for record in records)
        for analyte, field in target_fields.items()
    }
    method_records: list[Mapping[str, str]] = []
    missing_method_links: list[str] = []
    for record in target_rows:
        methods = record.fields.get("_lab_parameters")
        if not isinstance(methods, Mapping):
            raise ReconciliationError(f"record has no method mapping: {record.source_locator}")
        for analyte, field in target_fields.items():
            if not str(record.fields.get(field) or "").strip():
                continue
            method = methods.get(field)
            if not isinstance(method, Mapping):
                missing_method_links.append(f"{record.source_locator}:{analyte}")
            else:
                method_records.append(method)

    accreditation_counts = Counter(str(item.get("_accreditation_status") or "unknown") for item in method_records)
    units = sorted({str(item.get("Unit") or "") for item in method_records})
    weight_bases = sorted({str(item.get("Wet_or_dry_weight") or "") for item in method_records})
    llq_values = {
        analyte: sorted(
            {
                str(record.fields["_lab_parameters"][field].get("LLQ") or "")
                for record in target_rows
                if str(record.fields.get(field) or "").strip()
            }
        )
        for analyte, field in target_fields.items()
    }
    partial_digestion_count = sum(
        "parti" in str(item.get("Comment") or "").casefold()
        and "total" in str(item.get("Comment") or "").casefold()
        for item in method_records
    )
    actual = {
        "physical_rows": len(records),
        "distinct_samples": len(sample_counts),
        "duplicate_sample_codes": sum(count > 1 for count in sample_counts.values()),
        "duplicate_extra_rows": sum(count - 1 for count in sample_counts.values()),
        "target_bearing_rows": len(target_rows),
        "non_target_rows": len(records) - len(target_rows),
        "target_observations": sum(target_value_counts.values()),
        "target_value_counts": target_value_counts,
        "target_censored_counts": censored_counts,
        "target_method_links": len(method_records),
        "missing_target_method_links": len(missing_method_links),
    }
    exact_counts = all(
        actual[name] == expected[name]
        for name in (
            "physical_rows",
            "distinct_samples",
            "duplicate_sample_codes",
            "target_bearing_rows",
            "target_observations",
        )
    )
    semantics_ok = (
        units == ["mg/kg"]
        and weight_bases == ["Dry weight"]
        and partial_digestion_count == len(method_records)
        and not missing_method_links
        and set(accreditation_counts) == {"accredited", "not_accredited"}
    )
    status = "PASS" if exact_counts and semantics_ok else "FAIL"
    report = {
        "reconciliation_version": RECONCILIATION_VERSION,
        "status": status,
        "source_id": adapter.source_id,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_response_sha256": snapshot["response"]["sha256"],
        "adapter": adapter.candidate.adapter,
        "adapter_dataset_version": adapter.candidate.version,
        "counts": actual,
        "expected_counts": dict(expected),
        "measurement_semantics": {
            "units": units,
            "weight_bases": weight_bases,
            "digestion_scope": "partial_nitric_acid",
            "partial_digestion_method_link_count": partial_digestion_count,
            "target_llq_values_mg_per_kg": llq_values,
            "accreditation_observation_counts": dict(sorted(accreditation_counts.items())),
        },
        "checks": {
            "archive_and_members_match_registry": True,
            "physical_and_relationship_counts_match_snapshot": exact_counts,
            "every_target_observation_has_batch_method_metadata": not missing_method_links,
            "dry_weight_mg_per_kg_preserved": units == ["mg/kg"] and weight_bases == ["Dry weight"],
            "partial_digestion_boundary_preserved": partial_digestion_count == len(method_records),
            "accreditation_variation_preserved": set(accreditation_counts) == {"accredited", "not_accredited"},
        },
        "failures": missing_method_links[:20],
        "claim_boundary": (
            "PASS means that the adapter exactly reconciles this content-addressed snapshot and preserves its "
            "method semantics. It does not mean that Norway is globally representative or that human review is complete."
        ),
    }
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--snapshot-manifest", type=Path, default=DEFAULT_SNAPSHOT_MANIFEST)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = reconcile(args.archive, args.snapshot_manifest)
        if args.output:
            atomic_json(args.output, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError, ReconciliationError, source_adapters.SourceAdapterError) as exc:
        print(f"reconcile_marchem_adapter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
