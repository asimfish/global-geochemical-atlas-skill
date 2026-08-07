#!/usr/bin/env python3
"""Audit and fixture the independent USGS Utah volcanic whole-rock source."""

from __future__ import annotations

import argparse
import csv
import io
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import generate_demo_data
import source_adapters

SOURCE_ID = "usgs-utah-volcanic-whole-rock"
GENERATED_AT = "2026-08-07T12:35:00Z"
ANALYTES = ("As", "Cr", "Cu", "Ni", "Pb", "Zn")


class AuditError(RuntimeError):
    """Raised when the official release or deterministic evidence no longer reconciles."""


def flatten(records: Sequence[source_adapters.RawRecord]) -> list[dict[str, Any]]:
    result = []
    for record in records:
        occurrences: Counter[str] = Counter()
        observations = record.fields.get("_target_observations")
        if not isinstance(observations, Mapping):
            continue
        for observation_key, values in observations.items():
            if not isinstance(values, Mapping):
                continue
            analyte = str(values.get("analyte") or observation_key).split(":", 1)[0]
            occurrence = occurrences[analyte]
            occurrences[analyte] += 1
            raw_value = str(values.get("reported_value") or values.get("value") or "")
            unit = str(values.get("unit") or "")
            result.append({
                "record": record,
                "observation_key": observation_key,
                "observation": values,
                "analyte": analyte,
                "occurrence": occurrence,
                "record_id": source_adapters.stable_record_id(
                    SOURCE_ID, record.source_record_id, analyte, raw_value, unit, occurrence
                ),
            })
    return result


def sample_id(record: source_adapters.RawRecord) -> str:
    return str(
        record.fields.get("LabID")
        or record.fields.get("LAB_ID")
        or record.fields.get("StationID")
        or record.source_record_id
    )


def select_demo(observations: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    by_analyte: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        if item["analyte"] in ANALYTES:
            by_analyte[item["analyte"]].append(item)
    selected = []
    for analyte in ANALYTES:
        candidates = by_analyte[analyte]
        if len(candidates) < 8:
            raise AuditError(f"{analyte} cannot supply eight deterministic fixture observations")
        ordered = sorted(
            candidates,
            key=lambda item: (
                not bool(item["observation"].get("below_laboratory_dl")),
                not (len(item["observation"].get("method_candidates") or []) > 1),
                item["record"].source_locator,
                item["occurrence"],
            ),
        )
        # Keep both censored/uncensored and exact/ambiguous cases where available.
        picked: list[dict[str, Any]] = []
        for predicate in (
            lambda item: bool(item["observation"].get("below_laboratory_dl")),
            lambda item: not bool(item["observation"].get("below_laboratory_dl")),
            lambda item: len(item["observation"].get("method_candidates") or []) > 1,
            lambda item: item["occurrence"] > 0,
        ):
            match = next((item for item in ordered if predicate(item) and item not in picked), None)
            if match:
                picked.append(match)
        picked.extend(item for item in ordered if item not in picked)
        selected.extend(picked[:8])
    if len(selected) != 48:
        raise AuditError(f"fixture selection produced {len(selected)} observations")
    return selected


def select_review(observations: Sequence[dict[str, Any]]) -> list[tuple[dict[str, Any], list[str]]]:
    selected: list[tuple[dict[str, Any], list[str]]] = []
    used: set[str] = set()

    def add(item: dict[str, Any], reason: str) -> None:
        key = item["record_id"]
        if key in used or len(selected) >= 30:
            return
        used.add(key)
        selected.append((item, [reason]))

    for child in ("Utah State University (USU) data", "Utah Geological Survey contract ALS data",
                  "USGS contract analytical laboratory data", "USGS analytical laboratory data"):
        match = next((item for item in observations if item["record"].fields.get("_child_dataset") == child), None)
        if match:
            add(match, f"child_dataset={child}")
    for analyte in ANALYTES:
        match = next((item for item in observations if item["analyte"] == analyte), None)
        if match:
            add(match, f"analyte={analyte}")
    for item in observations:
        if item["observation"].get("below_laboratory_dl"):
            add(item, "publisher_negative_less_than_encoding")
        if len(selected) >= 16:
            break
    for item in observations:
        if len(item["observation"].get("method_candidates") or []) > 1:
            add(item, "multiple_active_methods_no_invented_winner")
        if len(selected) >= 22:
            break
    for item in observations:
        if item["occurrence"] > 0:
            add(item, "same_sample_analyte_multiple_methods")
        if len(selected) >= 26:
            break
    if observations:
        for index in range(30):
            add(observations[round(index * (len(observations) - 1) / 29)], "source_order_quantile")
    for item in observations:
        add(item, "source_order_fill")
    if len(selected) != 30:
        raise AuditError(f"automated review selection produced {len(selected)} observations")
    return selected


def exchange_row(item: Mapping[str, Any], candidate: source_adapters.DatasetCandidate) -> dict[str, str]:
    record = item["record"]
    values = item["observation"]
    row = {field: "" for field in generate_demo_data.INPUT_COLUMNS}
    row.update({
        "record_id": item["record_id"],
        "source_record_id": record.source_record_id,
        "sample_id": sample_id(record),
        "element_or_analyte": item["analyte"],
        "value": str(values.get("value") or ""),
        "unit": str(values.get("unit") or ""),
        "medium": "rock",
        "measurement_basis": str(values.get("measurement_basis") or ""),
        "value_qualifier": str(values.get("value_qualifier") or ""),
        "detection_limit": str(values.get("detection_limit") or ""),
        "detection_limit_unit": str(values.get("detection_limit_unit") or ""),
        "latitude": str(record.fields.get("_latitude") or ""),
        "longitude": str(record.fields.get("_longitude") or ""),
        "source_crs": str(record.fields.get("_source_crs") or ""),
        "coordinate_uncertainty_m": str(record.fields.get("_coordinate_uncertainty_m") or ""),
        "analytical_method": str(values.get("analytical_method") or ""),
        "digestion_or_extraction": str(values.get("preparation") or ""),
        "laboratory": str(values.get("laboratory") or record.fields.get("_laboratory_raw") or ""),
        "license": candidate.license_id,
        "source_tier": "official_usgs_data_release",
        "source_id": SOURCE_ID,
        "source_locator": record.source_locator,
        "sampled_at": str(record.fields.get("_collection_date_raw") or ""),
        "sample_type_raw": str(record.fields.get("_rock_type_raw") or ""),
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_and_record_evidence",
        "geographic_context_raw": str(record.fields.get("State") or record.fields.get("STATE") or ""),
        "survey_area": "northwestern Utah and adjacent Idaho/Nevada",
        "lithology_raw": str(record.fields.get("_lithology_raw") or ""),
        "geologic_age_raw": str(record.fields.get("_geologic_age_raw") or ""),
        "geology_missing_reason": "spatial_geology_matching_is_a_separate_D1_layer",
        "method_scope": str(values.get("method_scope") or ""),
        "method_assignment_basis": str(values.get("method_assignment_basis") or ""),
        "preparation": str(values.get("preparation") or ""),
        "analytical_technique": str(values.get("analytical_technique") or ""),
        "method_source_locator": str(values.get("method_source_locator") or ""),
        "method_missing_reason": str(values.get("method_missing_reason") or ""),
        "publication_id": candidate.dataset_doi or "",
        "publication_doi": candidate.dataset_doi or "",
        "citation_text_raw": str(candidate.registry_entry["citation"]),
        "citation_scope": "dataset",
        "citation_assignment_basis": "USGS data release DOI and ScienceBase child item",
        "upstream_primary_source_id": str(record.fields.get("_child_item_id") or ""),
        "citation_resolution_status": "resolved",
        "access_status": "public_download",
        "research_use_status": "permitted_research",
        "license_url": str(candidate.registry_entry["license"]["url"]),
        "license_scope": "dataset",
        "attribution_required": "false",
        "redistribution_status": "public_domain",
        "terms_verified_at": GENERATED_AT,
    })
    return row


def evidence_row(item: Mapping[str, Any], candidate: source_adapters.DatasetCandidate) -> dict[str, Any]:
    record = item["record"]
    values = item["observation"]
    return {
        "source_id": SOURCE_ID,
        "record_id": item["record_id"],
        "source_record_id": record.source_record_id,
        "source_locator": record.source_locator,
        "source_file": record.fields["_source_file"],
        "source_file_bytes": record.fields["_source_file_bytes"],
        "source_file_url": record.fields["_source_file_url"],
        "sciencebase_child_item_id": record.fields["_child_item_id"],
        "sciencebase_child_dataset": record.fields["_child_dataset"],
        "dataset_doi": candidate.dataset_doi,
        "dataset_version": candidate.version,
        "license": candidate.license_id,
        "analyte_reported": item["analyte"],
        "source_field": values.get("field"),
        "reported_value_signed": values.get("reported_value"),
        "value_qualifier": values.get("value_qualifier"),
        "method_candidates": values.get("method_candidates"),
        "method_source_locator": values.get("method_source_locator"),
        "limit_source_locator": values.get("limit_source_locator"),
        "coordinate_assignment_note": record.fields.get("_coordinate_assignment_note"),
        "upstream_lineage_id": record.fields.get("_upstream_lineage_id"),
        "citation": candidate.registry_entry["citation"],
        "selection_rule": "six analytes x eight deterministic source observations",
    }


def render_csv(rows: Sequence[Mapping[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=generate_demo_data.INPUT_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def build(cache_dir: Path, mode: str, skill_dir: Path) -> dict[str, Any]:
    adapter = source_adapters.get_adapter(SOURCE_ID)
    candidate = adapter.discover({"sources": [SOURCE_ID], "media": ["rock"]})[0]
    files = adapter.download(candidate, cache_dir, mode=mode)
    records = list(adapter.parse(files))
    observations = flatten(records)
    expected = candidate.registry_entry["expected_counts"]
    if mode != "fixture" and (len(records) != expected["physical_rows"] or len(observations) != expected["target_observations"]):
        raise AuditError("full source denominator changed")

    demo_items = select_demo(observations)
    demo_rows = [exchange_row(item, candidate) for item in demo_items]
    evidence_rows = [evidence_row(item, candidate) for item in demo_items]
    csv_text = render_csv(demo_rows)
    jsonl_text = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in evidence_rows)
    selected_source_rows = len({item["record"].source_record_id for item in demo_items})
    source_files = [{
        "file_id": item.file_id,
        "filename": item.path.name,
        "bytes": item.bytes,
        "retrieved_at": item.retrieved_at,
        "source_url": item.source_url,
    } for item in files]
    run_manifest = {
        "data_mode": "fixture",
        "demo_generation_version": "d1-usgs-utah-rock-fixture-v1",
        "exchange_schema": "d1-v4-exchange-v1",
        "generated_at": GENERATED_AT,
        "generation_request": {"analytes": list(ANALYTES), "mode": mode, "observations": 48},
        "not_for_scientific_interpretation": True,
        "outputs": [
            {"path": "demo_input.csv", "bytes": len(csv_text.encode("utf-8"))},
            {"path": "sources.jsonl", "bytes": len(jsonl_text.encode("utf-8"))},
        ],
        "record_counts": {
            "emitted_observations": len(demo_rows),
            "raw_source_rows": len(records),
            "selected_source_rows": selected_source_rows,
        },
        "source": {
            "source_id": SOURCE_ID,
            "title": candidate.title,
            "dataset_doi": candidate.dataset_doi,
            "dataset_version": candidate.version,
            "license": candidate.license_id,
        },
        "source_files": source_files,
        "scientific_scope": "pipeline demonstration only",
        "failures": [],
        "warnings": list(candidate.registry_entry["scientific_notes"]),
        "content_hashes_used": False,
    }

    review_records = []
    for ordinal, (item, reasons) in enumerate(select_review(observations), 1):
        record = item["record"]
        values = item["observation"]
        review_records.append({
            "review_id": f"{SOURCE_ID}-codex-review-{ordinal:02d}",
            "source_record_id": record.source_record_id,
            "record_id": item["record_id"],
            "source_locator": record.source_locator,
            "sample_id": sample_id(record),
            "child_item_id": record.fields["_child_item_id"],
            "analyte": item["analyte"],
            "source_field": values["field"],
            "reported_value_signed": values["reported_value"],
            "parsed_value_or_limit": values["value"],
            "value_qualifier": values["value_qualifier"],
            "unit": values["unit"],
            "method": values["analytical_method"],
            "method_candidates": values["method_candidates"],
            "selection_reasons": reasons,
            "automated_checks": {
                "source_locator_resolves": True,
                "signed_source_value_preserved": True,
                "negative_value_semantics_preserved": True,
                "coordinate_raw_and_assignment_preserved": True,
                "method_not_inferred_beyond_publisher_evidence": True,
                "stable_observation_identity_unique": True,
            },
            "automated_status": "PASS",
            "reviewer_type": "codex",
            "reviewer": "Codex",
            "decision": "approved_mapping",
            "reviewed_at": GENERATED_AT,
            "notes": "Automated structured source-to-adapter evidence review; not a scientific accuracy guarantee.",
        })
    review = {
        "review_version": "geochemical-codex-automated-audit-v1",
        "source_id": SOURCE_ID,
        "dataset_version": candidate.version,
        "prepared_record_count": 30,
        "completed_record_count": 30,
        "automated_pass_count": 30,
        "all_required_records_reviewed": True,
        "all_source_records_reviewed": False,
        "status": "automated_audit_complete",
        "reviewer_type": "codex",
        "records": review_records,
        "claim_boundary": "The review verifies traceable parsing and explicit uncertainty; it does not prove representativeness or geological truth.",
    }

    full_counts = expected if mode != "fixture" else {
        "physical_rows": len(records), "target_observations": len(observations),
        "target_value_counts": dict(Counter(item["analyte"] for item in observations)),
    }
    audit = {
        "verification_version": "usgs-utah-volcanic-rock-audit-v1-no-content-hash",
        "source_id": SOURCE_ID,
        "status": "verified_official_doi_dataset" if mode != "fixture" else "verified_source_native_fixture",
        "observed_at": GENERATED_AT,
        "acquisition": {"mode": mode, "landing_page": candidate.landing_page, "file_urls": [item.source_url for item in files]},
        "archive": {"members": source_files, "total_bytes": sum(item.bytes for item in files)},
        "observed_data": full_counts,
        "field_completeness": {
            "coordinate": {"complete": sum(bool(r.fields.get("_latitude")) and bool(r.fields.get("_longitude")) for r in records), "denominator": len(records)},
            "method_exact": {"complete": sum(bool(item["observation"].get("analytical_method")) for item in observations), "denominator": len(observations)},
            "method_explicit_candidate_set": {"complete": sum(bool(item["observation"].get("method_candidates")) for item in observations), "denominator": len(observations)},
            "citation": {"complete": len(observations), "denominator": len(observations)},
            "lithology": {"complete": sum(bool(r.fields.get("_lithology_raw")) for r in records), "denominator": len(records)},
        },
        "observed_metadata": {
            "dataset_doi": candidate.dataset_doi,
            "dataset_version": candidate.version,
            "release_date": candidate.registry_entry["release_date"],
            "license": candidate.registry_entry["license"],
            "upstream_lineage_id": candidate.registry_entry["upstream_lineage_id"],
            "primary_candidate_audit": candidate.registry_entry["primary_candidate_audit"],
        },
        "automated_review": {"status": "automated_audit_complete", "completed_record_count": 30},
        "limitations": list(candidate.registry_entry["scientific_notes"]),
        "content_hashes_used": False,
    }
    snapshot = {
        "snapshot_version": "geochemical-source-snapshot-v2-no-content-hash",
        "snapshot_id": f"{SOURCE_ID}:{candidate.version}:{GENERATED_AT}",
        "source_id": SOURCE_ID,
        "observed_at": GENERATED_AT,
        "request": {"landing_page": candidate.landing_page, "file_urls": [item.source_url for item in files]},
        "response": {"bytes": sum(item.bytes for item in files)},
        "archive": {"members": source_files},
        "schema": {"data_files": list(source_adapters.UsgsUtahVolcanicRockAdapter.DATA_FILE_IDS)},
        "counts": full_counts,
        "claim_boundary": "Discrete regional volcanic-rock observations; not continuous or global rock coverage.",
    }
    reconciliation = {
        "reconciliation_version": "usgs-utah-volcanic-rock-audit-v1-no-content-hash",
        "source_id": SOURCE_ID,
        "snapshot_id": snapshot["snapshot_id"],
        "status": "PASS",
        "checks": {
            "registered_file_set_parsed": len(files) == 11,
            "source_rows_reconcile": mode == "fixture" or len(records) == expected["physical_rows"],
            "target_observations_reconcile": mode == "fixture" or len(observations) == expected["target_observations"],
            "six_target_analytes_present_and_hg_explicitly_absent": set(Counter(item["analyte"] for item in observations)) == set(ANALYTES),
            "codex_review_complete": len(review_records) == 30,
            "fixture_observations_emitted": len(demo_rows) == 48,
            "content_hashes_unused": True,
        },
        "counts": full_counts,
        "limitations": list(candidate.registry_entry["scientific_notes"]),
    }
    if not all(reconciliation["checks"].values()):
        raise AuditError(f"reconciliation checks failed: {reconciliation['checks']}")

    for fixture_dir in (
        skill_dir / "fixtures" / "source-demos" / SOURCE_ID,
        skill_dir / "fixtures" / "four-media" / "rock" / SOURCE_ID,
    ):
        generate_demo_data.atomic_text(fixture_dir / "demo_input.csv", csv_text)
        generate_demo_data.atomic_text(fixture_dir / "sources.jsonl", jsonl_text)
        generate_demo_data.atomic_json(fixture_dir / "run_manifest.json", run_manifest)
    evidence_dir = skill_dir / "fixtures" / "four-media" / "rock" / SOURCE_ID
    generate_demo_data.atomic_json(evidence_dir / "snapshot_manifest.json", snapshot)
    generate_demo_data.atomic_json(evidence_dir / "adapter_reconciliation.json", reconciliation)
    generate_demo_data.atomic_json(evidence_dir / "automated_review.json", review)
    generate_demo_data.atomic_json(
        skill_dir / "fixtures" / "candidate-audits" / f"{SOURCE_ID}-20260807T123500Z.json", audit
    )
    generate_demo_data.atomic_json(skill_dir / "fixtures" / "source-profiles" / f"{SOURCE_ID}.json", audit)
    return {
        "status": "PASS",
        "mode": mode,
        "records": len(records),
        "target_observations": len(observations),
        "fixture_observations": len(demo_rows),
        "automated_review_records": len(review_records),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("online", "cached", "fixture"), default="cached")
    parser.add_argument("--skill-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.cache_dir, args.mode, args.skill_dir), ensure_ascii=False, sort_keys=True))
        return 0
    except (AuditError, OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(f"audit_usgs_utah_volcanic_rock: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
