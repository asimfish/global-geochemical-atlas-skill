from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "grade_task", TOOLS_ROOT / "grade_task.py"
)
assert SPEC and SPEC.loader
GRADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GRADER)


class CheckerSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evaluation_root = Path(__file__).resolve().parents[2]

    def _copy_gold(
        self, task_dir: Path
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        holder = tempfile.TemporaryDirectory()
        submission = Path(holder.name) / "submission"
        shutil.copytree(task_dir / "gold", submission)
        return holder, submission

    def test_q03_original_numeric_lexemes_are_not_scored_as_raw_text(self) -> None:
        task_dir = self.evaluation_root / "release" / "public" / "Q03"
        holder, submission = self._copy_gold(task_dir)
        self.addCleanup(holder.cleanup)
        path = submission / "normalized_elements.csv"
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
            columns = list(rows[0])
        for row in rows:
            if row["sample_id"] == "S01":
                row["original_value"] = "42.0"
            if row["sample_id"] == "S03":
                row["original_value"] = "8000.0"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

        report = GRADER.grade(task_dir, submission)
        self.assertEqual(report["evidence_points_awarded"], 80)
        self.assertTrue(all(item["passed"] for item in report["checks"]))

    def test_q10_uses_declared_columns_instead_of_undeclared_row_snippets(self) -> None:
        task_dir = self.evaluation_root / "evaluator_private" / "shadow" / "Q10"
        spec = json.loads(
            (task_dir / "checker" / "grader_spec.json").read_text(encoding="utf-8")
        )
        self.assertFalse(
            any(item["type"] == "text_contains_all" for item in spec["checks"])
        )
        holder, submission = self._copy_gold(task_dir)
        self.addCleanup(holder.cleanup)
        report = GRADER.grade(task_dir, submission)
        self.assertEqual(report["evidence_points_awarded"], 80)

    def test_q13_group_order_does_not_change_score(self) -> None:
        task_dir = self.evaluation_root / "evaluator_private" / "shadow" / "Q13"
        holder, submission = self._copy_gold(task_dir)
        self.addCleanup(holder.cleanup)
        path = submission / "eligibility.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["groups"].reverse()
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        report = GRADER.grade(task_dir, submission)
        self.assertEqual(report["evidence_points_awarded"], 80)
        self.assertTrue(all(item["passed"] for item in report["checks"]))


if __name__ == "__main__":
    unittest.main()
