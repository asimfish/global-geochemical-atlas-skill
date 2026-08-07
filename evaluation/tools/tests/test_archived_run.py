from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


QUESTIONS = tuple(f"Q{number:02d}" for number in range(1, 25))
RUN_NAME = "2026-08-06-q01-q24-independent-grade"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


class ArchivedRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evaluation_root = Path(__file__).resolve().parents[2]
        cls.archive = cls.evaluation_root / "results" / "runs" / RUN_NAME
        cls.identity = json.loads(
            (cls.archive / "frozen_identity.json").read_text(encoding="utf-8")
        )
        cls.summary = json.loads(
            (cls.archive / "independent_grading_summary.json").read_text(
                encoding="utf-8"
            )
        )

    def test_archive_contains_every_hash_pinned_submission(self) -> None:
        self.assertEqual(set(self.identity["tasks"]), set(QUESTIONS))
        self.assertEqual(self.identity["archived_submissions_root"], "submissions")
        for question in QUESTIONS:
            expected = self.identity["tasks"][question]["submission_sha256"]
            self.assertEqual(len(expected), 10, question)
            for relative, expected_sha256 in expected.items():
                path = self.archive / "submissions" / question / relative
                self.assertTrue(path.is_file(), f"missing archived file: {path}")
                self.assertEqual(sha256(path), expected_sha256, str(path))

    def test_archive_has_one_e1_score_and_summary_row_per_question(self) -> None:
        summary_rows = {row["question"]: row for row in self.summary["tasks"]}
        self.assertEqual(set(summary_rows), set(QUESTIONS))
        self.assertEqual(self.summary["archived_submissions_root"], "submissions")
        for question in QUESTIONS:
            score = json.loads(
                (self.archive / f"{question}-score.json").read_text(encoding="utf-8")
            )
            self.assertEqual(score["score_status"], "partial", question)
            self.assertIn(question.casefold(), score["run_id"].casefold())

    def test_candidate_visible_bundle_contains_no_archived_answers(self) -> None:
        submissions = self.evaluation_root / "ai_visible_public" / "submissions"
        for question in QUESTIONS:
            files = {
                path.relative_to(submissions / question).as_posix()
                for path in (submissions / question).rglob("*")
                if path.is_file()
            }
            self.assertEqual(files, {".gitkeep"}, question)


if __name__ == "__main__":
    unittest.main()
