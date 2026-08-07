#!/usr/bin/env python3
"""Deterministic contract checks for host, Docker, B0 and S0 prompts."""

from __future__ import annotations

import json
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
        cls.candidate_prompts = {
            "host_no_skill": (UPLIFT / "candidate_prompts/HOST_B0.md").read_text(encoding="utf-8"),
            "host_with_skill": (UPLIFT / "candidate_prompts/HOST_S0.md").read_text(encoding="utf-8"),
            "docker_no_skill": (UPLIFT / "candidate_prompts/DOCKER_B0.md").read_text(encoding="utf-8"),
            "docker_with_skill": (UPLIFT / "candidate_prompts/DOCKER_S0.md").read_text(encoding="utf-8"),
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
                self.assertIn("export_candidate_bundle.py", prompt)
                self.assertIn("--mode formal", prompt)
                self.assertIn("browser", prompt.casefold())
                self.assertIn("aggregate_uplift.py", prompt)
                self.assertIn("build_experiment_manifest.py", prompt)
                self.assertIn("只处理四个固定地球化学锚点属于未完成 D1", prompt)
        for name, prompt in self.candidate_prompts.items():
            with self.subTest(candidate_prompt=name):
                self.assertIn(commit, prompt)
                self.assertIn(self.config["model"], prompt)
                self.assertIn("temperature=0", prompt)
                self.assertIn("TASK.md", prompt)
                self.assertIn("discovery_contract.json", prompt)
                self.assertIn("benchmark_export_crosswalk.json", prompt)
                self.assertIn("run.sh", prompt)
                self.assertNotIn("git clone", prompt)
                self.assertNotIn("score_submission.py", prompt)
                self.assertIn("不要写", prompt)
                self.assertIn("experiment_manifest.json", prompt)

    def test_host_and_docker_profiles_are_both_explicit(self) -> None:
        for name in ("host_no_skill", "host_with_skill"):
            prompt = self.prompts[name]
            with self.subTest(prompt=name):
                self.assertIn("不使用 Docker", prompt)
                self.assertIn("禁止候选调用 Docker", prompt)
                self.assertIn("runtime_mode=host", prompt)
        for name in ("docker_no_skill", "docker_with_skill"):
            prompt = self.prompts[name]
            with self.subTest(prompt=name):
                self.assertIn("evaluation/docker/Dockerfile", prompt)
                self.assertIn("CPU 2", prompt)
                self.assertIn("memory 4g", prompt)
                self.assertIn("runtime_mode=docker", prompt)

    def test_only_with_skill_arm_archives_the_skill_in_each_profile(self) -> None:
        for profile in ("host", "docker"):
            with_prompt = self.prompts[f"{profile}_with_skill"]
            no_prompt = self.prompts[f"{profile}_no_skill"]
            self.assertIn("--condition S0", with_prompt)
            self.assertIn("--condition B0", no_prompt)
            self.assertIn("skill_used=true", with_prompt)
            self.assertIn("skill_used=false", no_prompt)
            self.assertIn("只额外", with_prompt)
            self.assertNotIn("git -C bootstrap_repo archive", with_prompt + no_prompt)
            self.assertIn("skill_used=true", self.candidate_prompts[f"{profile}_with_skill"])
            self.assertIn("skill_used=false", self.candidate_prompts[f"{profile}_no_skill"])

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
