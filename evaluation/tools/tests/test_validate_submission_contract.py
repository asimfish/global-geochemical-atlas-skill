from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_submission_contract", TOOLS_ROOT / "validate_submission_contract.py"
)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class PublicSubmissionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evaluation_root = Path(__file__).resolve().parents[2]

    def _task(self, question: str) -> Path:
        number = int(question[1:])
        if number <= 8:
            return self.evaluation_root / "release" / "public" / question
        split = "shadow" if number <= 16 else "final_holdout"
        return self.evaluation_root / "evaluator_private" / split / question

    def _copy_gold(
        self, question: str
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        task = self._task(question)
        holder = tempfile.TemporaryDirectory()
        submission = Path(holder.name) / "submission"
        shutil.copytree(task / "gold", submission)
        return holder, submission

    def test_all_gold_submissions_satisfy_public_contract(self) -> None:
        for number in range(1, 25):
            question = f"Q{number:02d}"
            task = self._task(question)
            report = VALIDATOR.validate_task(task, task / "gold")
            self.assertEqual(report["status"], "PASS", (question, report["errors"]))

    def test_q24_rejects_measurement_rows_masquerading_as_sources(self) -> None:
        task = self._task("Q24")
        holder, submission = self._copy_gold("Q24")
        self.addCleanup(holder.cleanup)
        manifest_path = submission / "artifacts" / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rows = manifest["benchmark_evidence"]["sources.jsonl"]["rows"]
        manifest["benchmark_evidence"]["sources.jsonl"]["rows"] = rows * 12
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        report = VALIDATOR.validate_task(task, submission)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(
            any("expected 2 rows, got 24" in error for error in report["errors"])
        )

    def test_json_shape_type_errors_are_reported_without_gold_values(self) -> None:
        task = self._task("Q13")
        holder, submission = self._copy_gold("Q13")
        self.addCleanup(holder.cleanup)
        manifest_path = submission / "artifacts" / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["benchmark_evidence"]["eligibility.json"]["value"]["groups"][0][
            "n_total"
        ] = "19"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        report = VALIDATOR.validate_task(task, submission)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("expected integer" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
