#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
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


class SourceTruthScoringTest(unittest.TestCase):
    def test_public_contract_is_pinned_by_scorer(self) -> None:
        contract = SCORER_PATH.with_name("sources.json")
        self.assertEqual(
            SCORER.PUBLIC_SOURCE_CONTRACT_SHA256,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
