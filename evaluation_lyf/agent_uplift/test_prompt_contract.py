#!/usr/bin/env python3
"""Deterministic contract checks for host, Docker, B0 and S0 prompts."""

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
        cls.prompts = {
            key: (UPLIFT / filename).read_text(encoding="utf-8")
            for key, filename in cls.config["prompt_files"].items()
        }
        cls.evaluation_prompts = {
            "b0": (ROOT / "evaluation/prompts/QWEN_B0_NO_SKILL_PROMPT.md").read_text(encoding="utf-8"),
            "s0": (ROOT / "evaluation/prompts/QWEN_S0_WITH_SKILL_PROMPT.md").read_text(encoding="utf-8"),
        }

    def test_all_four_uplift_prompts_share_fixed_experiment(self) -> None:
        commit = self.config["commit"]
        self.assertRegex(commit, r"^[0-9a-f]{40}$")
        self.assertEqual(set(self.prompts), {"host_no_skill", "host_with_skill", "docker_no_skill", "docker_with_skill"})
        for name, prompt in self.prompts.items():
            with self.subTest(prompt=name):
                self.assertIn(self.config["repository"], prompt)
                self.assertIn(commit, prompt)
                self.assertIn(self.config["model"], prompt)
                self.assertIn("temperature=0", prompt)
                self.assertIn("最多三轮", prompt)
                self.assertIn("experiment_manifest.json", prompt)
                self.assertIn("public_case", prompt)
                self.assertIn("score_submission.py", prompt)
                self.assertIn("--case-dir", prompt)
                self.assertIn("source_truth.source_truth_score", prompt)
                self.assertIn("四个文件的 SHA-256", prompt)
                self.assertIn("clean_rebuild", prompt)
                self.assertIn("run.sh", prompt)

    def test_host_and_docker_profiles_are_both_explicit(self) -> None:
        for name in ("host_no_skill", "host_with_skill"):
            prompt = self.prompts[name]
            with self.subTest(prompt=name):
                self.assertIn("不使用 Docker", prompt)
                self.assertIn("禁止调用 Docker", prompt)
                self.assertIn("runtime_mode=host", prompt)
                self.assertNotIn("evaluation/docker/Dockerfile", prompt)
        for name in ("docker_no_skill", "docker_with_skill"):
            prompt = self.prompts[name]
            with self.subTest(prompt=name):
                self.assertIn("evaluation/docker/Dockerfile", prompt)
                self.assertIn("--cpus 2", prompt)
                self.assertIn("--memory 4g", prompt)
                self.assertIn("runtime_mode=docker", prompt)

    def test_only_with_skill_arm_archives_the_skill_in_each_profile(self) -> None:
        for profile in ("host", "docker"):
            with_prompt = self.prompts[f"{profile}_with_skill"]
            no_prompt = self.prompts[f"{profile}_no_skill"]
            archive_with = re.search(r"git -C bootstrap_repo archive[\s\S]+?\| tar", with_prompt)
            archive_no = re.search(r"git -C bootstrap_repo archive[\s\S]+?\| tar", no_prompt)
            self.assertIsNotNone(archive_with)
            self.assertIsNotNone(archive_no)
            self.assertIn("skills/global-geochemical-atlas", archive_with.group(0))
            self.assertNotIn("skills/global-geochemical-atlas", archive_no.group(0))
            self.assertIn(".agents/skills/global-geochemical-atlas/SKILL.md", with_prompt)
            self.assertIn('"skill_used": true', with_prompt)
            self.assertIn('"skill_used": false', no_prompt)

    def test_evaluation_has_explicit_b0_and_s0_launch_prompts(self) -> None:
        common = (
            self.config["repository"],
            self.config["commit"],
            self.config["model"],
            "temperature=0",
            "evaluation/ai_visible_public",
            "AGENT_PROMPT.md",
            "Q01–Q24",
        )
        for name, prompt in self.evaluation_prompts.items():
            with self.subTest(prompt=name):
                for value in common:
                    self.assertIn(value, prompt)
                self.assertIn("checker", prompt)
                self.assertIn("rubric", prompt)
                self.assertIn("gold", prompt)
        self.assertNotIn("skills/global-geochemical-atlas", self.evaluation_prompts["b0"])
        self.assertIn("skills/global-geochemical-atlas", self.evaluation_prompts["s0"])
        self.assertIn("skill_used=false", self.evaluation_prompts["b0"])
        self.assertIn("skill_used=true", self.evaluation_prompts["s0"])

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

    def test_central_prompt_index_routes_every_entry(self) -> None:
        index = (ROOT / "TESTING_PROMPTS.md").read_text(encoding="utf-8")
        relatives = (
            "evaluation/prompts/QWEN_B0_NO_SKILL_PROMPT.md",
            "evaluation/prompts/QWEN_S0_WITH_SKILL_PROMPT.md",
            "evaluation/ai_visible_public/AGENT_PROMPT.md",
            "evaluation/docs/independent_grading_agent_prompt.md",
            "evaluation_lyf/agent_uplift/QWEN_NO_SKILL_PROMPT.md",
            "evaluation_lyf/agent_uplift/QWEN_WITH_SKILL_PROMPT.md",
            "evaluation_lyf/agent_uplift/QWEN_NO_SKILL_DOCKER_PROMPT.md",
            "evaluation_lyf/agent_uplift/QWEN_WITH_SKILL_DOCKER_PROMPT.md",
            "evaluation/docker/campaign.py",
            "evaluation/docs/docker_usage.md",
        )
        for relative in relatives:
            with self.subTest(path=relative):
                self.assertIn(relative, index)
        self.assertIn("Docker 是", index)
        self.assertIn("runner 自动", index)


if __name__ == "__main__":
    unittest.main(verbosity=2)
