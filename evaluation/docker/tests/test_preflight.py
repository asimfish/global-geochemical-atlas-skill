from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


DOCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_ROOT))

from preflight import evaluate  # noqa: E402


SKILL = """---
name: global-geochemical-atlas
description: 处理岩石、土壤、沉积物和水体元素数据，生成可追溯地球化学图谱。
---

# Workflow

输入输出使用 JSON Schema 与 CSV。必须报告置信度、不确定性、失败模式和适用边界，禁止编造证据。

```json
{"element": "Cu"}
```
"""


class PreflightTests(unittest.TestCase):
    def make_repo(self) -> Path:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        skill = root / "skills" / "global-geochemical-atlas"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(SKILL, encoding="utf-8")
        (skill / "agents").mkdir()
        (skill / "agents" / "openai.yaml").write_text(
            "interface:\n"
            '  display_name: "Global Geochemical Atlas"\n'
            '  short_description: "Build traceable global geochemical atlases"\n'
            '  default_prompt: "Use $global-geochemical-atlas for this atlas request."\n'
            "policy:\n"
            "  allow_implicit_invocation: true\n",
            encoding="utf-8",
        )
        (skill / "skill-card.md").write_text(
            "# Card\n\n"
            "## Purpose\n## Inputs and outputs\n## Effective capabilities\n"
            "| Reads | x |\n| Writes | x |\n| Executes | x |\n| Network | x |\n"
            "| Credentials | x |\n| External effects | x |\n| Approval gates | x |\n"
            "## Trust boundaries and controls\n## Known limitations\n## Verification\n",
            encoding="utf-8",
        )
        (skill / "evals").mkdir()
        (skill / "evals" / "activation.json").write_text(
            json.dumps(
                {
                    "skill": "global-geochemical-atlas",
                    "cases": [
                        {"id": "p1", "prompt": "atlas one", "should_activate": True, "expected_behavior": ["route"]},
                        {"id": "p2", "prompt": "atlas two", "should_activate": True, "expected_behavior": ["route"]},
                        {"id": "n1", "prompt": "subway map", "should_activate": False, "expected_behavior": ["skip"]},
                        {"id": "n2", "prompt": "redox", "should_activate": False, "expected_behavior": ["skip"]},
                    ],
                    "rubrics": {key: "required" for key in (
                        "discoverability", "correctness", "security", "effectiveness", "efficiency"
                    )},
                }
            ),
            encoding="utf-8",
        )
        return root

    def tearDown(self) -> None:
        if hasattr(self, "temporary"):
            self.temporary.cleanup()

    def test_valid_package_has_no_deterministic_failures(self) -> None:
        report = evaluate(self.make_repo(), "global-geochemical-atlas")
        self.assertEqual(report["failures"], [])
        self.assertIn(report["status"], {"pass", "review"})

    def test_secret_is_blocking(self) -> None:
        root = self.make_repo()
        secret = "sk-" + "A" * 24
        path = root / "skills" / "global-geochemical-atlas" / "secret.txt"
        path.write_text(secret, encoding="utf-8")
        report = evaluate(root, "global-geochemical-atlas")
        self.assertIn("l0.secrets", report["failures"])

    def test_secret_outside_submission_package_is_blocking(self) -> None:
        root = self.make_repo()
        path = root / "evaluation" / "accidental-secret.md"
        path.parent.mkdir()
        path.write_text("sk-sp-" + "segment.with.dots-and-dashes" * 2, encoding="utf-8")
        report = evaluate(root, "global-geochemical-atlas")
        self.assertIn("l0.secrets", report["failures"])
        secret_check = next(item for item in report["checks"] if item["id"] == "l0.secrets")
        self.assertEqual(secret_check["detail"][0]["file"], "evaluation/accidental-secret.md")

    def test_malformed_governance_artifact_is_blocking(self) -> None:
        root = self.make_repo()
        skill = root / "skills" / "global-geochemical-atlas"
        (skill / "agents" / "openai.yaml").write_text(
            'interface:\n  display_name: "Atlas"\n', encoding="utf-8"
        )
        (skill / "skill-card.md").write_text("# incomplete\n", encoding="utf-8")
        (skill / "evals" / "activation.json").write_text(
            '{"skill":"wrong","cases":[],"rubrics":{}}\n', encoding="utf-8"
        )
        report = evaluate(root, "global-geochemical-atlas")
        self.assertIn("l1.agent_metadata", report["failures"])
        self.assertIn("l1.skill_card", report["failures"])
        self.assertIn("l1.activation_eval", report["failures"])


if __name__ == "__main__":
    unittest.main()
