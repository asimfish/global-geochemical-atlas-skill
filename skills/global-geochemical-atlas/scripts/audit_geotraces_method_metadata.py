#!/usr/bin/env python3
"""Quantify GEOTRACES cruise-analyte contributor/method connections."""

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


class AuditError(RuntimeError):
    """Raised when contributor/method metadata no longer reconciles."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def audit(cache_dir: Path) -> dict[str, Any]:
    adapter = source_adapters.get_adapter("geotraces-idp2025")
    candidate = adapter.discover({"sources": ["geotraces-idp2025"]})[0]
    downloaded = adapter.download(candidate, cache_dir, mode="cached")
    statuses: Counter[str] = Counter()
    by_element: dict[str, Counter[str]] = {}
    method_urls: set[str] = set()
    originators: set[tuple[str, str]] = set()
    info_locators: set[str] = set()
    cruise_analyte_groups: set[tuple[str, str]] = set()
    observations = 0
    for record in adapter.parse(downloaded):
        targets = record.fields.get("_target_observations")
        if not isinstance(targets, Mapping):
            raise AuditError(f"target metadata missing: {record.source_locator}")
        for element, values in targets.items():
            if not isinstance(values, Mapping) or not str(values.get("value") or "").strip():
                continue
            observations += 1
            status = str(values.get("method_metadata_status") or "missing")
            statuses[status] += 1
            by_element.setdefault(str(element), Counter())[status] += 1
            cruise_analyte_groups.add((str(record.fields.get("Cruise") or ""), str(element)))
            candidates = values.get("method_metadata_candidates")
            if not isinstance(candidates, list) or not candidates:
                raise AuditError(f"method candidates missing: {record.source_locator} {element}")
            for item in candidates:
                if not isinstance(item, Mapping):
                    raise AuditError("invalid method candidate")
                info_locators.add(str(item.get("source_locator") or ""))
                for url in item.get("method_urls", []):
                    method_urls.add(str(url))
                for person in item.get("originators", []):
                    originators.add((str(person.get("name") or ""), str(person.get("orcid_url") or "")))
    expected = candidate.registry_entry["method_metadata"]
    checks = {
        "target_observations_match": observations == candidate.registry_entry["expected_counts"]["target_observations"],
        "all_observations_linked": statuses.get("missing", 0) == 0,
        "single_method_observations_match": statuses["single_linked_record"]
        == expected["observations_with_single_method_record"],
        "multiple_method_observations_match": statuses["multiple_linked_records_unresolved"]
        == expected["observations_with_multiple_method_records"],
        "cruise_analyte_groups_match": len(cruise_analyte_groups) == expected["cruise_analyte_groups"],
        "info_members_match": len(info_locators) == expected["html_member_count"],
        "method_records_match": len(method_urls) == expected["unique_bodc_method_record_count"],
        "originators_match": len(originators) == expected["originator_count"],
    }
    if not all(checks.values()):
        raise AuditError(f"GEOTRACES method reconciliation failed: {checks}")
    return {
        "audit_version": "geotraces-idp2025-method-metadata-v1",
        "source_id": candidate.source_id,
        "dataset_version": candidate.version,
        "status": "PASS",
        "observation_denominator": observations,
        "method_metadata_status_counts": dict(sorted(statuses.items())),
        "by_element": {
            element: dict(sorted(counts.items())) for element, counts in sorted(by_element.items())
        },
        "cruise_analyte_group_count": len(cruise_analyte_groups),
        "exported_info_member_count": len(info_locators),
        "unique_bodc_method_record_count": len(method_urls),
        "originator_count": len(originators),
        "checks": checks,
        "assignment_rule": (
            "Cruise and analyte resolve every target observation to one or more exported WebODV info records. "
            "Only the 22,254 observations whose candidate set resolves to one unique BODC method record receive "
            "an analytical_method at cruise-analyte scope. The remaining 17,073 retain their complete candidate set "
            "and an explicit unresolved reason; no observation-level method is guessed."
        ),
        "claim_boundary": (
            "The linked BODC pages are originator-and-method records. This audit proves the exported connection and "
            "assignment cardinality, not that one protocol can be inferred when several contributors supplied a cruise-analyte."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit(args.cache_dir)
        atomic_json(args.output, report)
        print(json.dumps({"status": "PASS", "observations": report["observation_denominator"]}, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_geotraces_method_metadata: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
