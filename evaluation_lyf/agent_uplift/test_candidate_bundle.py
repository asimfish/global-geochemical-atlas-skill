from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("export_candidate_bundle.py")
SPEC = importlib.util.spec_from_file_location("uplift_bundle", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CandidateBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[2]
        cls.prompt = Path(__file__).with_name("QWEN_NO_SKILL_PROMPT.md")

    def test_formal_b0_never_contains_skill_scorer_or_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            result = MODULE.export(self.repo, bundle, "B0", "formal", self.prompt)
            self.assertEqual(result["status"], "PASS")
            self.assertFalse((bundle / ".git").exists())
            self.assertFalse((bundle / ".agents").exists())
            self.assertFalse((bundle / "public_case/score_submission.py").exists())

    def test_formal_s0_diff_is_only_skill_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            b0, s0 = root / "b0", root / "s0"
            MODULE.export(self.repo, b0, "B0", "formal", self.prompt)
            MODULE.export(self.repo, s0, "S0", "formal", self.prompt)
            self.assertTrue(
                (s0 / ".agents/skills/global-geochemical-atlas/SKILL.md").is_file()
            )
            self.assertFalse(any("__pycache__" in path.parts for path in s0.rglob("*")))
            tracked = subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={self.repo}",
                    "ls-tree",
                    "-r",
                    "--name-only",
                    "HEAD",
                    "--",
                    "skills/global-geochemical-atlas",
                ],
                cwd=self.repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            exported_skill = [
                path
                for path in (s0 / ".agents/skills/global-geochemical-atlas").rglob("*")
                if path.is_file()
            ]
            self.assertEqual(len(tracked), len(exported_skill))
            common_b0 = {
                path.relative_to(b0).as_posix()
                for path in b0.rglob("*")
                if path.is_file() and path.name != "BUNDLE_MANIFEST.json"
            }
            common_s0 = {
                path.relative_to(s0).as_posix()
                for path in s0.rglob("*")
                if path.is_file()
                and path.name != "BUNDLE_MANIFEST.json"
                and ".agents" not in path.parts
            }
            self.assertEqual(common_b0, common_s0)


if __name__ == "__main__":
    unittest.main()
