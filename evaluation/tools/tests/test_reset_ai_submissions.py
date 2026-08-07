from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "reset_ai_submissions.py"
QUESTIONS = tuple(f"Q{number:02d}" for number in range(1, 25))


def load_module():
    spec = importlib.util.spec_from_file_location("reset_ai_submissions", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResetAiSubmissionsTests(unittest.TestCase):
    def make_bundle(self, root: Path) -> Path:
        bundle = root / "ai-visible"
        bundle.mkdir()
        (bundle / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(
                {
                    "bundle_type": "ai-visible-q01-q24",
                    "questions": list(QUESTIONS),
                }
            ),
            encoding="utf-8",
        )
        submissions = bundle / "submissions"
        for question in QUESTIONS:
            question_root = submissions / question
            question_root.mkdir(parents=True)
            (question_root / ".gitkeep").write_bytes(b"")
        return bundle

    def test_reset_removes_answers_and_preserves_only_gitkeep(self) -> None:
        if not SCRIPT_PATH.is_file():
            self.fail("reset_ai_submissions.py has not been implemented")
        module = load_module()

        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            artifacts = bundle / "submissions" / "Q01" / "artifacts"
            artifacts.mkdir()
            (artifacts / "run_manifest.json").write_text("{}\n", encoding="utf-8")
            (bundle / "submissions" / "Q02" / "answer.md").write_text(
                "old answer\n", encoding="utf-8"
            )

            summary = module.reset_submissions(bundle)

            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["removed_entries"], 2)
            for question in QUESTIONS:
                remaining = {
                    path.name for path in (bundle / "submissions" / question).iterdir()
                }
                self.assertEqual(remaining, {".gitkeep"})
                self.assertEqual(
                    (bundle / "submissions" / question / ".gitkeep").read_bytes(), b""
                )

    def test_reset_rejects_symlinked_question_before_deleting_answers(self) -> None:
        module = load_module()

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = self.make_bundle(root)
            first_answer = bundle / "submissions" / "Q01" / "answer.md"
            first_answer.write_text("keep on failed preflight\n", encoding="utf-8")
            outside = root / "outside"
            outside.mkdir()
            outside_answer = outside / "must-not-delete.md"
            outside_answer.write_text("outside\n", encoding="utf-8")
            question_24 = bundle / "submissions" / "Q24"
            (question_24 / ".gitkeep").unlink()
            question_24.rmdir()
            question_24.symlink_to(outside, target_is_directory=True)

            error_type = getattr(module, "ResetError", RuntimeError)
            with self.assertRaises(error_type):
                module.reset_submissions(bundle)

            self.assertTrue(first_answer.is_file())
            self.assertTrue(outside_answer.is_file())

    def test_reset_rejects_wrong_bundle_before_deleting_answers(self) -> None:
        module = load_module()

        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            answer = bundle / "submissions" / "Q01" / "answer.md"
            answer.write_text("must survive\n", encoding="utf-8")
            (bundle / "BUNDLE_MANIFEST.json").write_text(
                json.dumps(
                    {"bundle_type": "some-other-bundle", "questions": list(QUESTIONS)}
                ),
                encoding="utf-8",
            )

            with self.assertRaises(module.ResetError):
                module.reset_submissions(bundle)

            self.assertTrue(answer.is_file())

    def test_cli_dry_run_reports_answers_without_deleting_them(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = self.make_bundle(Path(temporary))
            answer = bundle / "submissions" / "Q01" / "answer.md"
            answer.write_text("preview me\n", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--bundle-root",
                    str(bundle),
                    "--dry-run",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(completed.stdout.strip(), "CLI must print a JSON summary")
            summary = json.loads(completed.stdout)
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["removed_entries"], 1)
            self.assertEqual(summary["removed_paths"], ["submissions/Q01/answer.md"])
            self.assertTrue(answer.is_file())


if __name__ == "__main__":
    unittest.main()
