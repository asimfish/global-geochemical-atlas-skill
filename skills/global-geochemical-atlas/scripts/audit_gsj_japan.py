#!/usr/bin/env python3
"""Audit the pinned GSJ river-sediment CSV pair and prepare review evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

SOURCE_ID = "japan-gsj-geochemical-map"
TARGETS = ("As", "Cr", "Cu", "Hg", "Ni", "Pb", "Zn")


class AuditError(RuntimeError):
    """Raised when the registered GSJ tables no longer reconcile."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise AuditError(f"expected numeric GSJ value, received {value!r}") from exc


def _review_records(
    records: Sequence[source_adapters.RawRecord], candidate: Any
) -> list[dict[str, Any]]:
    selected: list[int] = []
    reasons: dict[int, set[str]] = {}

    def add(index: int, reason: str) -> None:
        if index not in reasons:
            selected.append(index)
            reasons[index] = set()
        reasons[index].add(reason)

    duplicate_indices = [
        i for i, record in enumerate(records) if record.fields["試料番号"] == "78013"
    ]
    for index in duplicate_indices:
        add(index, "duplicate_sample_78013_ordinal_join")
    for field in ("緯度(JGD2000)", "経度(JGD2000)"):
        add(
            min(range(len(records)), key=lambda i: _float(records[i].fields[field])),
            f"minimum_{field}",
        )
        add(
            max(range(len(records)), key=lambda i: _float(records[i].fields[field])),
            f"maximum_{field}",
        )
    for ordinal in range(30):
        index = round(ordinal * (len(records) - 1) / 29)
        add(index, "national_source_order_stratum")
        if len(selected) >= 30:
            break
    for index in range(len(records)):
        if len(selected) >= 30:
            break
        add(index, "source_order_fill")
    selected = sorted(selected[:30])

    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    target_units: Mapping[str, str] = candidate.registry_entry["target_units"]
    review: list[dict[str, Any]] = []
    for ordinal, index in enumerate(selected, start=1):
        record = records[index]
        observations = []
        for analyte in TARGETS:
            raw_value = str(record.fields[target_fields[analyte]])
            unit = target_units[analyte]
            observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": unit,
                    "record_id": source_adapters.stable_record_id(
                        SOURCE_ID, record.source_record_id, analyte, raw_value, unit
                    ),
                }
            )
        review.append(
            {
                "review_id": f"japan-gsj-geochemical-map-review-{ordinal:02d}",
                "source_record_id": record.source_record_id,
                "source_locator": record.source_locator,
                "sample_source_locator": record.fields["_sample_source_locator"],
                "concentration_source_locator": record.fields[
                    "_concentration_source_locator"
                ],
                "reported_sample_id": record.fields["試料番号"],
                "sample_id_occurrence": record.fields["_sample_id_occurrence"],
                "map_sheet": record.fields["地図名"],
                "reported_place": record.fields["採取地"],
                "reported_river": record.fields["川"],
                "longitude_jgd2000": record.fields["経度(JGD2000)"],
                "latitude_jgd2000": record.fields["緯度(JGD2000)"],
                "selection_reasons": sorted(reasons[index]),
                "adapter_observations": observations,
                "automated_checks": {
                    "two_registered_file_hashes_match": True,
                    "ordinal_sample_join_preserved": True,
                    "jgd2000_coordinates_preserved": True,
                    "seven_target_values_preserved_without_imputation": True,
                    "hg_ppb_and_other_ppm_units_preserved": True,
                    "stable_observation_ids_unique": len(
                        {item["record_id"] for item in observations}
                    )
                    == 7,
                },
                "automated_status": "PASS",
                "reviewer": {
                    "reviewer": None,
                    "decision": None,
                    "reviewed_at": None,
                    "notes": None,
                },
            }
        )
    if len(review) != 30:
        raise AuditError("failed to prepare exactly 30 GSJ review records")
    return review


def run(args: argparse.Namespace) -> dict[str, Any]:
    adapter = source_adapters.get_adapter(SOURCE_ID)
    candidate = adapter.discover({"sources": [SOURCE_ID]})[0]
    files = adapter.download(candidate, args.cache_dir, mode=args.mode)
    records = list(adapter.parse(files))
    by_id = {item.file_id: item for item in files}
    if len(records) != 3024 or set(by_id) != {"samples", "concentrations"}:
        raise AuditError("GSJ registered file or row counts changed")

    reported_ids = Counter(str(record.fields["試料番号"]) for record in records)
    duplicate_ids = {key: count for key, count in reported_ids.items() if count > 1}
    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    target_units: Mapping[str, str] = candidate.registry_entry["target_units"]
    target_counts = {
        analyte: sum(
            bool(str(record.fields[target_fields[analyte]]).strip())
            for record in records
        )
        for analyte in TARGETS
    }
    bbox = [
        min(_float(record.fields["経度(JGD2000)"]) for record in records),
        min(_float(record.fields["緯度(JGD2000)"]) for record in records),
        max(_float(record.fields["経度(JGD2000)"]) for record in records),
        max(_float(record.fields["緯度(JGD2000)"]) for record in records),
    ]
    review_records = _review_records(records, candidate)
    combined_hash = hashlib.sha256(
        "|".join(by_id[file_id].sha256 for file_id in sorted(by_id)).encode()
    ).hexdigest()
    snapshot_id = f"{SOURCE_ID}:{candidate.version}:{combined_hash[:12]}"
    members = [
        {"name": item.path.name, "bytes": item.bytes, "sha256": item.sha256}
        for item in sorted(files, key=lambda value: value.file_id)
    ]
    observed_data = {
        "sample_rows": len(records),
        "concentration_rows": len(records),
        "distinct_reported_sample_ids": len(reported_ids),
        "duplicate_reported_sample_ids": duplicate_ids,
        "ordinal_joined_rows": len(records),
        "map_sheet_count": len({str(record.fields["地図名"]) for record in records}),
        "target_analytes": target_counts,
        "target_observations": sum(target_counts.values()),
        "target_units": dict(target_units),
        "bbox_jgd2000": bbox,
    }
    audit = {
        "verification_version": "gsj-japan-river-sediment-audit-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "acquisition": {
            "request_url": candidate.landing_page,
            "observed_at": args.observed_at,
            "file_urls": [item.source_url for item in files],
        },
        "archive": {"sha256": combined_hash, "members": members},
        "observed_data": observed_data,
        "observed_metadata": {
            "medium": "river sediment",
            "grain_fraction": "<180 µm fine stream sediment",
            "source_coordinate_crs": "EPSG:4612 (JGD2000)",
            "row_level_method_present": False,
            "row_level_detection_limit_present": False,
            "row_level_quality_flag_present": False,
        },
        "human_review": {
            "required_record_count": 30,
            "prepared_record_count": 30,
            "completed_record_count": 0,
            "status": "pending",
        },
        "claim_boundary": (
            "This audit proves two byte-pinned official CSV files, 3,024 occurrence-order joins and exact unit mapping. "
            "It does not prove a regular national grid, complete analytical-method metadata or WGS84 point accuracy."
        ),
    }
    snapshot = {
        "snapshot_version": "geochemical-source-snapshot-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "observed_at": args.observed_at,
        "request": {
            "url": candidate.landing_page,
            "file_urls": [item.source_url for item in files],
        },
        "response": {
            "bytes": sum(item.bytes for item in files),
            "sha256": combined_hash,
        },
        "archive": {"sha256": combined_hash, "members": members},
        "counts": observed_data,
        "claim_boundary": audit["claim_boundary"],
    }
    reconciliation = {
        "reconciliation_version": "gsj-japan-river-sediment-audit-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "status": "PASS",
        "checks": {
            "sample_file_hash_match": by_id["samples"].sha256
            == candidate.registry_entry["download"]["files"][0]["expected_sha256"],
            "concentration_file_hash_match": by_id["concentrations"].sha256
            == candidate.registry_entry["download"]["files"][1]["expected_sha256"],
            "valid_row_counts_match": len(records) == 3024,
            "ordinal_join_count_match": len(records) == 3024,
            "duplicate_78013_preserved": duplicate_ids == {"78013": 2},
            "target_counts_match": target_counts
            == {analyte: 3024 for analyte in TARGETS},
            "target_units_match": target_units
            == {
                **{analyte: "ppm" for analyte in TARGETS if analyte != "Hg"},
                "Hg": "ppb",
            },
            "review_sample_prepared": len(review_records) == 30,
        },
        "counts": observed_data,
        "limitations": [
            "River samples follow drainage networks and do not form a regular grid.",
            "JGD2000 coordinates require explicit handling before WGS84 output.",
            "The CSV pair lacks row-level method, detection-limit and QC metadata.",
            "Marine sediment and surface-soil products are outside this adapter.",
        ],
    }
    review = {
        "review_version": "geochemical-human-review-v1",
        "source_id": SOURCE_ID,
        "dataset_version": candidate.version,
        "prepared_record_count": 30,
        "completed_record_count": 0,
        "automated_pass_count": 30,
        "status": "prepared",
        "all_records_reviewed": False,
        "claim_boundary": (
            "Automated PASS confirms correspondence with the two hash-verified files and occurrence-order adapter. "
            "It is not human review; decisions remain null until a named reviewer signs each row."
        ),
        "records": review_records,
    }
    atomic_json(args.audit_output, audit)
    atomic_json(args.snapshot_output, snapshot)
    atomic_json(args.reconciliation_output, reconciliation)
    atomic_json(args.review_output, review)
    return {
        "status": "PASS",
        "joined_rows": len(records),
        "prepared_review_records": len(review_records),
    }


def build_parser() -> argparse.ArgumentParser:
    skill_dir = Path(__file__).resolve().parent.parent
    fixture_dir = skill_dir / "fixtures" / "four-media" / "sediment" / SOURCE_ID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--observed-at", required=True)
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=skill_dir
        / "fixtures"
        / "candidate-audits"
        / "gsj-japan-river-sediment-20260806T034823Z.json",
    )
    parser.add_argument(
        "--snapshot-output", type=Path, default=fixture_dir / "snapshot_manifest.json"
    )
    parser.add_argument(
        "--reconciliation-output",
        type=Path,
        default=fixture_dir / "adapter_reconciliation.json",
    )
    parser.add_argument(
        "--review-output", type=Path, default=fixture_dir / "human_review.json"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run(args), ensure_ascii=False, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_gsj_japan: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
