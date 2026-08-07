from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "finalize_score.py"
SPEC = importlib.util.spec_from_file_location("finalize_score", SCRIPT)
assert SPEC and SPEC.loader
finalize_score = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(finalize_score)


class ReviewEvidenceScopeTests(unittest.TestCase):
    def metric(self, evidence: str) -> dict[str, object]:
        return {
            "id": "scope",
            "dimension_id": "scientific_credibility",
            "max": 5,
            "score": 5,
            "evidence": [evidence],
            "reason": "Bound evidence supports the criterion.",
        }

    def score(self, evidence: str) -> list[dict[str, object]]:
        frozen = {
            "scope": {
                "id": "scope",
                "dimension_id": "scientific_credibility",
                "points": 5,
            }
        }
        return finalize_score._review_metrics(
            {"task_id": "GGA-TEST-001", "criteria": [self.metric(evidence)]},
            "llm_grader_report.json",
            "llm",
            {"scientific_credibility"},
            expected_task_id="GGA-TEST-001",
            frozen_criteria=frozen,
            allowed_evidence_paths=[
                "artifacts/run_manifest.json#/benchmark_evidence/source"
            ],
            objective_reference="objective_report.json",
        )

    def test_accepts_a_refinement_of_frozen_submission_evidence(self) -> None:
        metrics = self.score(
            "artifacts/run_manifest.json#/benchmark_evidence/source/decisions/0"
        )
        self.assertEqual(metrics[0]["value"], 5.0)

    def test_accepts_a_current_objective_report_pointer(self) -> None:
        metrics = self.score("objective_report.json#/checks/0")
        self.assertEqual(metrics[0]["value"], 5.0)

    def test_rejects_unscoped_or_prose_suffixed_evidence(self) -> None:
        with self.assertRaisesRegex(Exception, "outside the frozen scope"):
            self.score("artifacts/unrelated.json#/claim")
        with self.assertRaisesRegex(Exception, "outside the frozen scope"):
            self.score(
                "artifacts/run_manifest.json: benchmark_evidence source looked correct"
            )


if __name__ == "__main__":
    unittest.main()
