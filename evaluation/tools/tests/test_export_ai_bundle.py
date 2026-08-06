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

    def test_export_contains_only_allowlisted_public_materials(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "ai-visible"
            summary = MODULE.export_bundle(self.benchmark_root, bundle)

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["questions"], 8)
            self.assertTrue((bundle / "AGENT_PROMPT.md").is_file())
            self.assertTrue((bundle / "contracts" / "benchmark-execution-contract.json").is_file())
            self.assertTrue((bundle / "tasks" / "Q01" / "inputs" / "data_sources.json").is_file())
            self.assertTrue((bundle / "submissions" / "Q08").is_dir())
            self.assertTrue((bundle / "submissions" / "Q08" / ".gitkeep").is_file())

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

    def test_validator_rejects_a_tampered_content_manifest_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "ai-visible"
            MODULE.export_bundle(self.benchmark_root, bundle)
            manifest_path = bundle / "BUNDLE_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["content_manifest_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            with self.assertRaises(MODULE.BundleError):
                MODULE.validate_bundle(bundle)

    def test_task_metadata_must_match_the_e1_output_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            metadata_path = Path(temporary) / "task.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "question_id": "Q01",
                        "split": "public",
                        "input_assets": ["input.csv"],
                        "required_outputs": ["answer.json"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(MODULE.BundleError):
                MODULE._load_task_metadata(
                    metadata_path,
                    "Q01",
                    ("artifacts/run_manifest.json",),
                )

    def test_task_alignment_fields_must_match_the_e1_contract(self) -> None:
        contract_path = self.benchmark_root / "contracts" / "benchmark-execution-contract.json"
        contract, required_outputs = MODULE._load_execution_contract(contract_path)
        metadata = json.loads(
            (self.benchmark_root / "release" / "public" / "Q01" / "task.json").read_text(
                encoding="utf-8"
            )
        )
        metadata["e1_eval_version"] = "drifted-version"
        with tempfile.TemporaryDirectory() as temporary:
            metadata_path = Path(temporary) / "task.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaises(MODULE.BundleError):
                MODULE._load_task_metadata(
                    metadata_path,
                    "Q01",
                    required_outputs,
                    contract,
                )


if __name__ == "__main__":
    unittest.main()
