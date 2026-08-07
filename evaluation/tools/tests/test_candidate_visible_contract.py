from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "candidate_visible_contract", TOOLS_ROOT / "candidate_visible_contract.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CandidateVisibleContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evaluation_root = Path(__file__).resolve().parents[2]

    def test_all_contracts_cover_checker_structure(self) -> None:
        task_dirs = sorted((self.evaluation_root / "release" / "public").glob("Q??"))
        task_dirs.extend(sorted((self.evaluation_root / "evaluator_private" / "shadow").glob("Q??")))
        task_dirs.extend(sorted((self.evaluation_root / "evaluator_private" / "final_holdout").glob("Q??")))
        self.assertEqual(len(task_dirs), 24)
        for task_dir in task_dirs:
            metadata = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
            grader = json.loads((task_dir / "checker" / "grader_spec.json").read_text(encoding="utf-8"))
            self.assertEqual(MODULE.validate_candidate_visible_contract(task_dir, metadata, grader), [])

    def test_csv_positional_rows_contract_is_rejected(self) -> None:
        task_dir = self.evaluation_root / "release" / "public" / "Q03"
        metadata = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        grader = json.loads((task_dir / "checker" / "grader_spec.json").read_text(encoding="utf-8"))
        metadata["candidate_visible_contract"]["logical_outputs"]["normalized_elements.csv"][
            "row_encoding"
        ] = "positional_arrays"
        errors = MODULE.validate_candidate_visible_contract(task_dir, metadata, grader)
        self.assertTrue(any("object-encoded CSV rows" in error for error in errors))

    def test_json_checker_path_must_be_candidate_visible(self) -> None:
        task_dir = self.evaluation_root / "release" / "public" / "Q01"
        metadata = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
        grader = json.loads((task_dir / "checker" / "grader_spec.json").read_text(encoding="utf-8"))
        properties = metadata["candidate_visible_contract"]["logical_outputs"]["provenance_plan.json"][
            "json_shape"
        ]["properties"]
        properties.pop("record_fields")
        errors = MODULE.validate_candidate_visible_contract(task_dir, metadata, grader)
        self.assertTrue(any("record_fields" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
