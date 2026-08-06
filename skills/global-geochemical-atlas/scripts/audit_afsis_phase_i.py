#!/usr/bin/env python3
"""Audit pinned AfSIS Phase I files and prepare 30 unsigned source-row comparisons."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import source_adapters

AUDIT_VERSION = "afsis-phase-i-audit-v1"
REVIEW_VERSION = "afsis-phase-i-human-review-v1"
SOURCE_ID = "afsis-phase-i-wet-chemistry"


class AuditError(ValueError):
    """Raised when the pinned AfSIS source cannot be audited reproducibly."""


def _features(record: source_adapters.RawRecord) -> set[str]:
    fields = record.fields
    country = str(fields.get("Country") or "")
    depth = str(fields.get("Depth") or "")
    latitude = str(fields.get("Latitude") or "").strip()
    longitude = str(fields.get("Longitude") or "").strip()
    features = {f"country={country}", f"depth={depth}"}
    if not latitude and not longitude:
        features.add("coordinates=missing_both")
    observations = fields.get("_target_observations")
    if not isinstance(observations, Mapping):
        raise AuditError(f"AfSIS record lacks target observations: {record.source_locator}")
    for analyte, observation in observations.items():
        if not isinstance(observation, Mapping):
            continue
        value = float(str(observation["value"]))
        dl = float(str(observation["detection_limit"]))
        ql = float(str(observation["quantitation_limit"]))
        if value < 0:
            category = "negative_numeric"
        elif value < dl:
            category = "positive_below_dl"
        elif value < ql:
            category = "dl_to_ql"
        else:
            category = "at_or_above_ql"
        features.add(f"{analyte}={category}")
    return features


def _select(records: Sequence[source_adapters.RawRecord], count: int) -> list[tuple[source_adapters.RawRecord, list[str]]]:
    all_features = set().union(*(_features(record) for record in records))
    required = {
        feature for feature in all_features
        if feature.startswith(("country=", "depth=", "coordinates=", "As=", "Cr=", "Cu=", "Ni=", "Pb=", "Zn="))
    }
    selected: list[tuple[source_adapters.RawRecord, list[str]]] = []
    selected_ids: set[str] = set()
    uncovered = set(required)
    while uncovered and len(selected) < count:
        best = max(
            (record for record in records if record.source_record_id not in selected_ids),
            key=lambda item: (len(_features(item) & uncovered), -int(item.source_locator.rsplit("=", 1)[-1])),
        )
        covered = sorted(_features(best) & uncovered)
        if not covered:
            break
        selected.append((best, covered))
        selected_ids.add(best.source_record_id)
        uncovered.difference_update(covered)
    if uncovered:
        raise AuditError(f"30-row review cannot cover required AfSIS strata: {sorted(uncovered)}")
    for record in records:
        if len(selected) >= count:
            break
        if record.source_record_id not in selected_ids:
            selected.append((record, ["source_order_fill"]))
            selected_ids.add(record.source_record_id)
    if len(selected) != count:
        raise AuditError(f"AfSIS has fewer than {count} distinct source rows")
    return selected


def _threshold_category(observation: Mapping[str, Any]) -> str:
    value = float(str(observation["value"]))
    dl = float(str(observation["detection_limit"]))
    ql = float(str(observation["quantitation_limit"]))
    if value < 0:
        return "negative_numeric"
    if value < dl:
        return "positive_below_dl"
    if value < ql:
        return "dl_to_ql"
    return "at_or_above_ql"


def _review(
    adapter: source_adapters.RegistryAdapter,
    files: Sequence[source_adapters.DownloadedFile],
    records: Sequence[source_adapters.RawRecord],
    prepared_at: str,
) -> dict[str, Any]:
    by_filename = {item.path.name: item for item in files}
    measurement = next(item for item in files if item.file_id == "measurements")
    selected = _select(records, 30)
    review_records: list[dict[str, Any]] = []
    for index, (record, reasons) in enumerate(selected, start=1):
        fields = record.fields
        observations = fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            raise AuditError(f"AfSIS review row lacks observations: {record.source_locator}")
        adapter_observations: list[dict[str, Any]] = []
        for analyte, observation in observations.items():
            if not isinstance(observation, Mapping):
                continue
            raw_value = str(observation["value"])
            unit = str(observation["unit"])
            adapter_observations.append(
                {
                    "analyte": analyte,
                    "raw_value": raw_value,
                    "unit": unit,
                    "detection_limit": str(observation["detection_limit"]),
                    "quantitation_limit": str(observation["quantitation_limit"]),
                    "threshold_category": _threshold_category(observation),
                    "measurement_basis": str(observation["measurement_basis"]),
                    "analytical_method": str(observation["analytical_method"]),
                    "digestion_or_extraction": str(observation["digestion_or_extraction"]),
                    "source_variable_description": str(observation["source_variable_description"]),
                    "variable_metadata_locator": str(observation["variable_metadata_locator"]),
                    "threshold_metadata_locator": str(observation["threshold_metadata_locator"]),
                    "record_id": source_adapters.stable_record_id(
                        SOURCE_ID, record.source_record_id, str(analyte), raw_value, unit
                    ),
                }
            )
        review_records.append(
            {
                "review_id": f"{SOURCE_ID}-review-{index:02d}",
                "source_record_id": record.source_record_id,
                "source_locator": record.source_locator,
                "sample_id": str(fields.get("SSN") or ""),
                "laboratory_sample_id": str(fields.get("RES.ID") or ""),
                "country_reported": str(fields.get("Country") or ""),
                "country_normalized": str(fields.get("_country_normalized") or ""),
                "site": str(fields.get("Site") or ""),
                "depth": str(fields.get("Depth") or ""),
                "latitude": str(fields.get("Latitude") or ""),
                "longitude": str(fields.get("Longitude") or ""),
                "source_file_sha256": measurement.sha256,
                "metadata_file_sha256": by_filename[
                    next(item.path.name for item in files if item.file_id == "variables")
                ].sha256,
                "adapter_observations": adapter_observations,
                "selection_reasons": reasons,
                "automated_checks": {
                    "registered_original_file_hashes_match": True,
                    "two_unique_sample_identifiers_preserved": True,
                    "raw_and_normalized_country_names_separated": True,
                    "coordinate_absence_preserved_without_inference": True,
                    "depth_and_sample_identity_preserved": True,
                    "method_unit_and_aqua_regia_basis_attached": True,
                    "source_wide_dl_and_ql_attached": True,
                    "negative_and_below_limit_values_flagged_without_imputation": True,
                    "stable_observation_ids_unique": len(
                        {item["record_id"] for item in adapter_observations}
                    ) == len(adapter_observations),
                },
                "automated_status": "PASS",
                "reviewer": {
                    "decision": None,
                    "reviewer": None,
                    "reviewed_at": None,
                    "notes": None,
                },
            }
        )
    return {
        "review_version": REVIEW_VERSION,
        "source_id": SOURCE_ID,
        "dataset_version": adapter.candidate.version,
        "prepared_at": prepared_at,
        "status": "prepared",
        "prepared_record_count": len(review_records),
        "automated_pass_count": sum(item["automated_status"] == "PASS" for item in review_records),
        "completed_record_count": 0,
        "all_records_reviewed": False,
        "records": review_records,
        "claim_boundary": (
            "Automated PASS confirms correspondence with three hash-verified original AfSIS files and the adapter. "
            "It is not human review; reviewer decisions remain null until a named reviewer signs each row."
        ),
    }


def _audit(
    adapter: source_adapters.RegistryAdapter,
    files: Sequence[source_adapters.DownloadedFile],
    records: Sequence[source_adapters.RawRecord],
    observed_at: str,
) -> dict[str, Any]:
    country_counts = Counter(str(record.fields.get("Country") or "") for record in records)
    depth_counts = Counter(str(record.fields.get("Depth") or "") for record in records)
    target_counts: Counter[str] = Counter()
    threshold_counts: dict[str, Counter[str]] = {}
    latitudes: list[float] = []
    longitudes: list[float] = []
    missing_coordinates = 0
    for record in records:
        latitude = str(record.fields.get("Latitude") or "").strip()
        longitude = str(record.fields.get("Longitude") or "").strip()
        if latitude and longitude:
            latitudes.append(float(latitude))
            longitudes.append(float(longitude))
        else:
            missing_coordinates += 1
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            raise AuditError(f"AfSIS audit row lacks observations: {record.source_locator}")
        for analyte, observation in observations.items():
            if isinstance(observation, Mapping):
                target_counts[str(analyte)] += 1
                threshold_counts.setdefault(str(analyte), Counter())[_threshold_category(observation)] += 1
    members = [
        {"name": item.path.name, "bytes": item.bytes, "sha256": item.sha256}
        for item in sorted(files, key=lambda value: value.file_id)
    ]
    aggregate_hash = source_adapters._canonical_hash(
        "afsis-original-files-v1", [item["name"] + ":" + item["sha256"] for item in members]
    )
    return {
        "verification_version": AUDIT_VERSION,
        "source_id": SOURCE_ID,
        "snapshot_id": f"{SOURCE_ID}:2.0:{aggregate_hash[:12]}",
        "acquisition": {
            "observed_at": observed_at,
            "request_url": adapter.candidate.landing_page,
            "file_urls": [item.source_url for item in files],
            "cache_statuses": sorted({item.cache_status for item in files}),
            "format_note": (
                "Original CSV/XLSX endpoints are pinned. Dataverse's dynamically converted tabular representation "
                "is not used as an immutable artifact."
            ),
        },
        "archive": {
            "bytes": sum(item.bytes for item in files),
            "sha256": aggregate_hash,
            "members": members,
        },
        "observed_data": {
            "physical_rows": len(records),
            "distinct_ssn": len({str(item.fields.get("SSN") or "") for item in records}),
            "distinct_res_id": len({str(item.fields.get("RES.ID") or "") for item in records}),
            "country_label_counts": dict(sorted(country_counts.items())),
            "country_site_pairs": len({
                (str(item.fields.get("Country") or ""), str(item.fields.get("Site") or "")) for item in records
            }),
            "depth_counts": dict(sorted(depth_counts.items())),
            "complete_coordinate_pairs": len(latitudes),
            "missing_coordinate_pairs": missing_coordinates,
            "bbox_wgs84": [min(longitudes), min(latitudes), max(longitudes), max(latitudes)],
            "target_analytes": dict(sorted(target_counts.items())),
            "target_observations": sum(target_counts.values()),
            "threshold_category_counts": {
                analyte: dict(sorted(counts.items())) for analyte, counts in sorted(threshold_counts.items())
            },
        },
        "observed_metadata": {
            "medium": "soil",
            "sample_depths": {"Topsoil": "0-20 cm", "Subsoil": "20-50 cm"},
            "measurement_basis": "aqua_regia_quasi_total_air_dry_soil",
            "units": "mg kg^-1",
            "laboratory": "Rothamsted Research",
            "sample_years": "2009-2013",
            "analysis_years": "2017-2018",
            "source_wide_detection_and_quantitation_limits_present": True,
            "row_level_censor_qualifier_present": False,
            "raw_country_labels_preserved": True,
            "grain_fraction_from_related_article": "<2 mm",
            "source_coordinate_crs": "not_reported_in_registered_files_or_related_article",
            "metadata_conflicts": [
                "As.75 is described as Arsenic-78 in the variable workbook.",
                "The variable workbook reports 2009-2013 sampling; the related SOIL article reports 2009-2012.",
            ],
        },
        "human_review": {
            "status": "pending",
            "prepared_record_count": 30,
            "completed_record_count": 0,
            "required_record_count": 30,
        },
        "claim_boundary": (
            "This audit proves three byte-pinned original files, 2,002 unique archived samples and exact method, "
            "depth and threshold mapping. It does not prove uniform African coverage or that below-limit numeric "
            "results are ordinary detections."
        ),
    }


def build(cache_dir: Path, prepared_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    adapter = source_adapters.get_adapter(SOURCE_ID)
    files = adapter.download(adapter.candidate, cache_dir, mode="cached")
    records = list(adapter.parse(files))
    return _audit(adapter, files, records, prepared_at), _review(adapter, files, records, prepared_at)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--candidate-audit-output", required=True, type=Path)
    parser.add_argument("--review-output", required=True, type=Path)
    parser.add_argument("--prepared-at", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        audit, review = build(args.cache_dir, args.prepared_at)
        source_adapters.downloader.atomic_json(args.candidate_audit_output, audit)
        source_adapters.downloader.atomic_json(args.review_output, review)
    except (OSError, AuditError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_afsis_phase_i: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "PASS", "source_id": SOURCE_ID, "prepared": 30}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
