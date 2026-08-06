#!/usr/bin/env python3
"""Deterministic contract checks for the two copy-paste uplift prompts."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPLIFT = ROOT / "evaluation_lyf" / "agent_uplift"


class PromptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads((UPLIFT / "experiment_config.json").read_text(encoding="utf-8"))
        cls.with_skill = (UPLIFT / "QWEN_WITH_SKILL_PROMPT.md").read_text(encoding="utf-8")
        cls.no_skill = (UPLIFT / "QWEN_NO_SKILL_PROMPT.md").read_text(encoding="utf-8")

    def test_fixed_parameters_match_both_prompts(self) -> None:
        commit = self.config["commit"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        for prompt in (self.with_skill, self.no_skill):
            with self.subTest(prompt=prompt[:40]):
                self.assertIn(self.config["repository"], prompt)
                self.assertIn(commit, prompt)
                self.assertIn(self.config["model"], prompt)
                self.assertIn("temperature=0", prompt)
                self.assertIn("最多三轮", prompt)
                self.assertIn("experiment_manifest.json", prompt)
                self.assertIn("public_case/prepare_case.py", prompt)
                self.assertIn("public_case/score_submission.py", prompt)
                self.assertIn("evaluation/docker/Dockerfile", prompt)

    def test_only_intended_arm_can_receive_skill(self) -> None:
        archive_with_skill = re.search(r"git -C bootstrap_repo archive[\s\S]+?\| tar", self.with_skill)
        archive_no_skill = re.search(r"git -C bootstrap_repo archive[\s\S]+?\| tar", self.no_skill)
        self.assertIsNotNone(archive_with_skill)
        self.assertIsNotNone(archive_no_skill)
        self.assertIn("skills/global-geochemical-atlas", archive_with_skill.group(0))
        self.assertNotIn("skills/global-geochemical-atlas", archive_no_skill.group(0))
        self.assertIn(".agents/skills/global-geochemical-atlas/SKILL.md", self.with_skill)
        self.assertIn('"skill_used": true', self.with_skill)
        self.assertIn('"skill_used": false', self.no_skill)

    def test_isolation_and_clean_rebuild_are_explicit(self) -> None:
        for prompt in (self.with_skill, self.no_skill):
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("git -C bootstrap_repo archive", prompt)
                self.assertIn("rm -rf bootstrap_repo", prompt)
                self.assertIn("不得读取", prompt)
                self.assertIn("clean_rebuild", prompt)
                self.assertIn("run.sh", prompt)

    def test_docker_runtime_assets_exist(self) -> None:
        for relative in (
            "evaluation/docker/Dockerfile",
            "evaluation/docker/campaign.py",
            "evaluation/docker/compose.yaml",
            "evaluation/docker/container/run_opencode.py",
            "evaluation/docker/container/allowlist_proxy.py",
            "evaluation/docs/docker_usage.md",
        ):
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main(verbosity=2)
