from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "export_ai_bundle.py"
SPEC = importlib.util.spec_from_file_location("export_ai_bundle", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ExportAiBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.benchmark_root = Path(__file__).resolve().parents[2]

    def test_export_contains_only_allowlisted_candidate_materials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "ai-visible"
            summary = MODULE.export_bundle(self.benchmark_root, bundle)

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["questions"], 24)
            self.assertTrue((bundle / "AGENT_PROMPT.md").is_file())
            self.assertEqual(
                (bundle / "AGENT_PROMPT.md").read_bytes(),
                (self.benchmark_root / "prompts" / "answering_agent_prompt.md").read_bytes(),
            )
            q01_metadata = json.loads(
                (bundle / "tasks" / "Q01" / "task.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                q01_metadata["candidate_visible_contract"]["schema_version"],
                "e2.candidate-visible.v1",
            )
            self.assertIn(
                "array_of_objects_keyed_by_column_name",
                (bundle / "tasks" / "Q03" / "task.json").read_text(encoding="utf-8"),
            )
            self.assertTrue((bundle / "tasks" / "Q01" / "inputs" / "data_sources.json").is_file())
            q24_metadata = json.loads(
                (bundle / "tasks" / "Q24" / "task.json").read_text(encoding="utf-8")
            )
            self.assertEqual(q24_metadata["split"], "final_holdout")
            self.assertTrue((bundle / "submissions" / "Q24").is_dir())
            self.assertTrue((bundle / "submissions" / "Q24" / ".gitkeep").is_file())

            relative_paths = {path.relative_to(bundle).as_posix() for path in bundle.rglob("*")}
            for forbidden in ("gold", "checker", "rubric.json", "evaluator_private", "results"):
                self.assertFalse(any(forbidden in path.split("/") for path in relative_paths))

    def test_export_refuses_to_overwrite_existing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "ai-visible"
            bundle.mkdir()
            with self.assertRaises(MODULE.BundleError):
                MODULE.export_bundle(self.benchmark_root, bundle)

    def test_validator_rejects_a_leaked_gold_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "ai-visible"
            MODULE.export_bundle(self.benchmark_root, bundle)
            leaked = bundle / "tasks" / "Q01" / "gold" / "answer.json"
            leaked.parent.mkdir()
            leaked.write_text("{}\n", encoding="utf-8")
            with self.assertRaises(MODULE.BundleError):
                MODULE.validate_bundle(bundle)

    def test_validator_rejects_historical_submissions_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "ai-visible"
            MODULE.export_bundle(self.benchmark_root, bundle)
            answer = bundle / "submissions" / "Q01" / "artifacts" / "run_manifest.json"
            answer.parent.mkdir()
            answer.write_text("{}\n", encoding="utf-8")

            with self.assertRaises(MODULE.BundleError):
                MODULE.validate_bundle(bundle)

            summary = MODULE.validate_bundle(bundle, allow_submissions=True)
            self.assertEqual(summary["submission_files"], 1)


if __name__ == "__main__":
    unittest.main()
