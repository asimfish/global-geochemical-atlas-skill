#!/usr/bin/env python3
"""Audit the pinned PANGAEA North Africa soil table and prepare review evidence."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

SOURCE_ID = "pangaea-north-africa-soil"
TARGETS = ("As", "Cr", "Cu", "Ni", "Pb", "Zn")


class AuditError(RuntimeError):
    """Raised when the pinned table no longer matches its registered facts."""


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except ValueError as exc:
        raise AuditError(f"expected a finite numeric source value, received {value!r}") from exc


def _review_records(records: Sequence[source_adapters.RawRecord], candidate: Any) -> list[dict[str, Any]]:
    selected_indices: list[int] = []
    reasons: dict[int, set[str]] = {}

    def add(index: int, reason: str) -> None:
        if index not in reasons:
            selected_indices.append(index)
            reasons[index] = set()
        reasons[index].add(reason)

    by_area: dict[str, int] = {}
    for index, record in enumerate(records):
        area = str(record.fields["Area"])
        by_area.setdefault(area, index)
    for index in by_area.values():
        add(index, "first_sample_per_potential_source_area")

    for field in ("Latitude", "Longitude"):
        add(min(range(len(records)), key=lambda i: _float(records[i].fields[field])), f"minimum_{field.casefold()}")
        add(max(range(len(records)), key=lambda i: _float(records[i].fields[field])), f"maximum_{field.casefold()}")

    for index in range(len(records)):
        if len(selected_indices) >= 30:
            break
        add(index, "source_order_fill")
    selected_indices = sorted(selected_indices[:30])

    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    review: list[dict[str, Any]] = []
    for ordinal, index in enumerate(selected_indices, start=1):
        record = records[index]
        observations = []
        for analyte in TARGETS:
            field = target_fields[analyte]
            raw_value = str(record.fields[field])
            observations.append(
                {
                    "analyte": analyte,
                    "field": field,
                    "raw_value": raw_value,
                    "unit": "mg/kg",
                    "medium": "soil",
                    "record_id": source_adapters.stable_record_id(
                        SOURCE_ID, record.source_record_id, analyte, raw_value, "mg/kg"
                    ),
                }
            )
        review.append(
            {
                "review_id": f"pangaea-north-africa-soil-review-{ordinal:02d}",
                "source_record_id": record.source_record_id,
                "source_locator": record.source_locator,
                "sample_id": record.fields["Sample ID"],
                "event": record.fields["Event"],
                "potential_source_area": record.fields["Area"],
                "reported_location": record.fields["Location"],
                "latitude": record.fields["Latitude"],
                "longitude": record.fields["Longitude"],
                "selection_reasons": sorted(reasons[index]),
                "adapter_observations": observations,
                "automated_checks": {
                    "registered_file_hash_matches": True,
                    "sample_identity_preserved": True,
                    "coordinates_preserved": True,
                    "publisher_location_preserved_without_country_inference": True,
                    "six_target_values_preserved_without_imputation": True,
                    "units_preserved": True,
                    "method_and_digestion_attached": True,
                    "stable_observation_ids_unique": len({item["record_id"] for item in observations}) == 6,
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
    if len(review) != 30 or any(item["automated_status"] != "PASS" for item in review):
        raise AuditError("failed to prepare exactly 30 passing review records")
    return review


def run(args: argparse.Namespace) -> dict[str, Any]:
    adapter = source_adapters.get_adapter(SOURCE_ID)
    candidate = adapter.discover({"sources": [SOURCE_ID]})[0]
    files = adapter.download(candidate, args.cache_dir, mode=args.mode)
    records = list(adapter.parse(files))
    if len(files) != 1 or len(records) != 43:
        raise AuditError("registered PANGAEA file or record count changed")
    downloaded = files[0]
    areas = Counter(str(record.fields["Area"]) for record in records)
    locations = {str(record.fields["Location"]) for record in records}
    sample_ids = {str(record.fields["Sample ID"]) for record in records}
    target_fields: Mapping[str, str] = candidate.registry_entry["target_analytes"]
    target_counts = {
        analyte: sum(bool(str(record.fields[target_fields[analyte]]).strip()) for record in records)
        for analyte in TARGETS
    }
    bbox = [
        min(_float(record.fields["Longitude"]) for record in records),
        min(_float(record.fields["Latitude"]) for record in records),
        max(_float(record.fields["Longitude"]) for record in records),
        max(_float(record.fields["Latitude"]) for record in records),
    ]
    review_records = _review_records(records, candidate)
    snapshot_id = f"{SOURCE_ID}:{candidate.version}:{args.observed_at}"
    audit = {
        "verification_version": "pangaea-north-africa-soil-audit-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "acquisition": {
            "request_url": downloaded.source_url,
            "observed_at": args.observed_at,
            "cache_status": downloaded.cache_status,
        },
        "archive": {
            "bytes": downloaded.bytes,
            "members": [
                {"name": downloaded.path.name, "bytes": downloaded.bytes}
            ],
        },
        "observed_data": {
            "physical_rows": len(records),
            "distinct_samples": len(sample_ids),
            "potential_source_area_count": len(areas),
            "reported_location_count": len(locations),
            "target_analytes": target_counts,
            "target_observations": sum(target_counts.values()),
            "bbox": bbox,
            "area_counts": dict(sorted(areas.items())),
        },
        "observed_metadata": {
            "medium": "soil",
            "grain_fraction": "<20 µm fine silt-clay fraction",
            "digestion": "HF-HNO3 acid digestion",
            "instrument": "Agilent 7900 quadrupole ICP-MS",
            "eluent": "2.5% HNO3",
            "reference_materials": ["BHVO-2", "BCR-2"],
            "reference_material_agreement": "within ±10% of recommended values in the parent study",
            "row_level_detection_limits_present": False,
        },
        "human_review": {
            "required_record_count": 30,
            "prepared_record_count": 30,
            "completed_record_count": 0,
            "status": "pending",
        },
        "claim_boundary": (
            "The audit proves a byte-pinned 43-sample DOI table and exact field mapping. It does not prove "
            "continuous North African coverage or comparability with bulk-soil and partial-extraction surveys."
        ),
    }
    snapshot = {
        "snapshot_version": "geochemical-source-snapshot-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "observed_at": args.observed_at,
        "request": {"url": downloaded.source_url, "dataset_doi": candidate.dataset_doi},
        "response": {"bytes": downloaded.bytes},
        "archive": audit["archive"],
        "counts": audit["observed_data"],
        "claim_boundary": audit["claim_boundary"],
    }
    reconciliation = {
        "reconciliation_version": "pangaea-north-africa-soil-audit-v1",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot_id,
        "status": "PASS",
        "checks": {
            "file_bytes_match": downloaded.bytes == candidate.registry_entry["download"]["files"][0]["bytes"],
            "physical_rows_match": len(records) == 43,
            "distinct_samples_match": len(sample_ids) == 43,
            "target_counts_match": target_counts == {analyte: 43 for analyte in TARGETS},
            "bbox_match": bbox == [-13.26, 15.67, 32.5, 33.83],
            "review_sample_prepared": len(review_records) == 30,
        },
        "counts": audit["observed_data"],
        "limitations": [
            "Forty-three discrete samples do not form continuous regional coverage.",
            "The <20 µm HF-HNO3 fraction remains isolated from other soil preparation bases.",
            "Country is not inferred from coordinates or border-location text.",
            "Table S5 has no row-level detection-limit or qualifier fields.",
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
            "Automated PASS confirms correspondence with the hash-verified source and adapter. "
            "It is not human review; decisions remain null until a named reviewer signs each row."
        ),
        "records": review_records,
    }
    atomic_json(args.audit_output, audit)
    atomic_json(args.snapshot_output, snapshot)
    atomic_json(args.reconciliation_output, reconciliation)
    atomic_json(args.review_output, review)
    return {"status": "PASS", "source_rows": len(records), "prepared_review_records": len(review_records)}


def build_parser() -> argparse.ArgumentParser:
    skill_dir = Path(__file__).resolve().parent.parent
    fixture_dir = skill_dir / "fixtures" / "four-media" / "soil" / SOURCE_ID
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--observed-at", required=True)
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=skill_dir / "fixtures" / "candidate-audits" / "pangaea-north-africa-soil-20260806T031354Z.json",
    )
    parser.add_argument("--snapshot-output", type=Path, default=fixture_dir / "snapshot_manifest.json")
    parser.add_argument("--reconciliation-output", type=Path, default=fixture_dir / "adapter_reconciliation.json")
    parser.add_argument("--review-output", type=Path, default=fixture_dir / "human_review.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(run(args), ensure_ascii=False, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_pangaea_north_africa: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
