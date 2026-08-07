#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCORER_PATH = Path(__file__).with_name("public_case") / "score_submission.py"
SPEC = importlib.util.spec_from_file_location("score_submission", SCORER_PATH)
assert SPEC and SPEC.loader
SCORER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCORER)


RESOURCE = {
    "id": "example",
    "source_id": "authority_1",
    "dataset_title": "Authority dataset",
    "doi": "10.9999/example",
    "dataset_version": "v1",
    "license": "CC-BY-4.0",
    "medium": "soil",
    "locator_prefix": "https://doi.org/10.9999/example#",
    "sha256": "a" * 64,
}

DISCOVERED_RESOURCE = {
    "source_id": "earthchem_example",
    "platform": "EarthChem",
    "dataset_title": "Verified rock dataset",
    "dataset_doi": "10.9999/rock",
    "dataset_version": "2026-08",
    "license": "CC-BY-4.0",
    "media": ["rock"],
    "authority_url": "https://example.org/dataset",
    "download_url": "https://example.org/data.csv",
    "locator_prefix": "https://example.org/dataset#",
    "file": "discovered/earthchem-example.csv",
    "accessed_at": "2026-08-07T00:00:00Z",
    "query": "As Cu Fe Ni Pb Zn rock",
}


def valid_row() -> dict[str, str]:
    return {
        "source_id": "authority_1",
        "dataset_title": "Authority dataset",
        "dataset_doi": "10.9999/example",
        "dataset_version": "v1",
        "license": "CC-BY-4.0",
        "medium": "soil",
        "source_locator": "https://doi.org/10.9999/example#row=2&field=As",
        "file_sha256": "a" * 64,
    }


def valid_discovered_row(digest: str) -> dict[str, str]:
    return {
        "source_id": DISCOVERED_RESOURCE["source_id"],
        "dataset_title": DISCOVERED_RESOURCE["dataset_title"],
        "dataset_doi": DISCOVERED_RESOURCE["dataset_doi"],
        "dataset_version": DISCOVERED_RESOURCE["dataset_version"],
        "license": DISCOVERED_RESOURCE["license"],
        "medium": "rock",
        "source_locator": DISCOVERED_RESOURCE["locator_prefix"] + "row=2&field=As",
        "file_sha256": digest,
    }


class SourceTruthScoringTest(unittest.TestCase):
    def test_public_contract_is_pinned_by_scorer(self) -> None:
        contract = SCORER_PATH.with_name("sources.json")
        self.assertEqual(
            SCORER.PUBLIC_SOURCE_CONTRACT_SHA256,
            hashlib.sha256(contract.read_bytes()).hexdigest(),
        )

    def test_discovery_contract_is_pinned_by_scorer(self) -> None:
        contract = SCORER_PATH.with_name("discovery_contract.json")
        self.assertEqual(
            SCORER.DISCOVERY_CONTRACT_SHA256,
            hashlib.sha256(contract.read_bytes()).hexdigest(),
        )

    def test_exact_record_scores_one_hundred(self) -> None:
        metrics = SCORER.source_truth_metrics([valid_row()], {"a" * 64: RESOURCE})
        self.assertEqual(100.0, metrics["source_truth_score"])
        self.assertEqual(["example"], metrics["covered_resource_ids"])

    def test_hash_substitution_invalidates_all_linked_claims(self) -> None:
        row = valid_row()
        row["file_sha256"] = "b" * 64
        metrics = SCORER.source_truth_metrics([row], {"a" * 64: RESOURCE})
        self.assertEqual(0.0, metrics["source_truth_score"])

    def test_doi_or_license_tampering_fails_metadata(self) -> None:
        row = valid_row()
        row["dataset_doi"] = "10.9999/fabricated"
        row["license"] = "CC0-1.0"
        metrics = SCORER.source_truth_metrics([row], {"a" * 64: RESOURCE})
        self.assertEqual(1.0, metrics["hash_rate"])
        self.assertEqual(0.0, metrics["metadata_rate"])
        self.assertEqual(1.0, metrics["locator_rate"])

    def test_untraceable_locator_fails_even_with_valid_hash(self) -> None:
        row = valid_row()
        row["source_locator"] = "raw.csv"
        metrics = SCORER.source_truth_metrics([row], {"a" * 64: RESOURCE})
        self.assertEqual(0.0, metrics["locator_rate"])

    def test_verified_additional_source_is_not_penalized_as_unknown(self) -> None:
        payload = b"sample_id,As\nrock-1,12\n"
        digest = hashlib.sha256(payload).hexdigest()
        discovered = {**DISCOVERED_RESOURCE, "bytes": len(payload), "sha256": digest}
        resources = {"a" * 64: RESOURCE, digest: discovered}
        metrics = SCORER.source_truth_metrics([valid_row(), valid_discovered_row(digest)], resources)
        self.assertEqual(100.0, metrics["source_truth_score"])
        self.assertEqual(["earthchem_example", "example"], metrics["covered_resource_ids"])

    def test_discovered_manifest_is_bound_to_local_bytes(self) -> None:
        payload = b"sample_id,As\nrock-1,12\n"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            case_dir = Path(temporary)
            data_path = case_dir / DISCOVERED_RESOURCE["file"]
            data_path.parent.mkdir(parents=True)
            data_path.write_bytes(payload)
            manifest = {
                "schema_version": "qwen-uplift-discovered-manifest-v1",
                "resources": [{**DISCOVERED_RESOURCE, "bytes": len(payload), "sha256": digest}],
            }
            (case_dir / "discovered_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            resources, errors = SCORER.discovered_source_contract(
                case_dir, SCORER_PATH.with_name("discovery_contract.json")
            )
            self.assertEqual([], errors)
            self.assertEqual(DISCOVERED_RESOURCE["source_id"], resources[digest]["source_id"])

            data_path.write_bytes(payload + b"tampered")
            resources, errors = SCORER.discovered_source_contract(
                case_dir, SCORER_PATH.with_name("discovery_contract.json")
            )
            self.assertEqual({}, resources)
            self.assertTrue(any("byte identity mismatch" in error for error in errors))

    def test_unknown_units_need_explicit_failure_disposition(self) -> None:
        guessed = {"normalized_value": "1", "normalized_unit": "mg/kg", "qc_flags": "[\"UNIT_INFERRED\"]"}
        rejected = {"normalized_value": "", "normalized_unit": "", "qc_flags": "[\"UNSUPPORTED_UNIT\"]"}
        censored = {"normalized_value": "", "normalized_unit": "", "value_qualifier": "<", "censored": "true"}
        self.assertFalse(SCORER.explicit_unit_disposition(guessed))
        self.assertTrue(SCORER.explicit_unit_disposition(rejected))
        self.assertTrue(SCORER.explicit_unit_disposition(censored))

    def test_discovery_report_proves_bounded_continuation_not_five_file_stop(self) -> None:
        contract = json.loads(SCORER_PATH.with_name("discovery_contract.json").read_text(encoding="utf-8"))
        candidates = []
        for index in range(8):
            selected = index == 0
            candidates.append({
                "source_id": "earthchem_example" if selected else f"candidate_{index}",
                "platform": f"platform_{index % 5}",
                "status": "selected" if selected else "rejected",
                "authority_url": f"https://example.org/dataset/{index}",
                "query": f"query {index}",
                "reason": "adds verified rock coverage" if selected else "not selected after evidence audit",
                **({"marginal_contribution": ["rock", "new_platform"]} if selected else {}),
            })
        report = {
            "schema_version": "qwen-uplift-discovery-report-v1",
            "request": contract["request"],
            "started_at": "2026-08-07T00:00:00Z",
            "cutoff_at": "2026-08-07T00:04:00Z",
            "active_discovery_seconds": 240,
            "stop_reason": "discovery_budget_exhausted",
            "remaining_candidates": ["candidate_8"],
            "selection_policy": contract["continuation_policy"]["maximum_records_selection"],
            "candidates": candidates,
            "claim_boundary": "Not exhaustive; coverage gaps remain.",
        }
        metrics = SCORER.discovery_report_metrics(report, contract, {"earthchem_example"})
        self.assertTrue(metrics["valid"])
        self.assertEqual(8, metrics["candidate_source_count"])
        self.assertEqual(5, metrics["searched_platform_count"])

        report["candidates"][0].pop("marginal_contribution")
        self.assertFalse(SCORER.discovery_report_metrics(report, contract, {"earthchem_example"})["valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
