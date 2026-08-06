from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
