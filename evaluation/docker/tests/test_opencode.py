from __future__ import annotations

import sys
import unittest
from pathlib import Path


CONTAINER_ROOT = Path(__file__).resolve().parents[1] / "container"
sys.path.insert(0, str(CONTAINER_ROOT))

from run_opencode import build_config  # noqa: E402


class OpenCodeConfigTests(unittest.TestCase):
    def test_custom_provider_keeps_secret_as_environment_reference(self) -> None:
        config = build_config("https://gateway.example/v1", "vendor/model", 0.0)
        provider = config["provider"]["eval"]
        self.assertEqual(config["model"], "eval/vendor/model")
        self.assertEqual(provider["options"]["apiKey"], "{env:EVAL_API_KEY}")
        self.assertNotIn("secret", str(config).casefold())
        self.assertEqual(config["agent"]["build"]["temperature"], 0.0)
        self.assertIn("openai-compatible", provider["name"])

    def test_manual_compose_supplies_frozen_fields_and_isolated_b0_s0_mounts(
        self,
    ) -> None:
        compose = (CONTAINER_ROOT.parent / "compose.yaml").read_text(encoding="utf-8")
        for name in (
            "EVAL_PROVIDER_MODEL_ID",
            "EVAL_TEMPERATURE",
            "EVAL_THINKING_MODE",
            "EVAL_PROVIDER_PROFILE_ID",
            "EVAL_PROVIDER_PROFILE_SHA256",
            "EVAL_PROVIDER_REGISTRY_SHA256",
        ):
            self.assertGreaterEqual(compose.count(name), 1, name)
        self.assertIn("candidate-b0:", compose)
        self.assertIn("candidate-s0:", compose)
        self.assertGreaterEqual(compose.count(":/task:ro"), 2)
        self.assertGreaterEqual(compose.count(":/workspace:rw"), 2)
        self.assertGreaterEqual(compose.count(":/submission:rw"), 2)
        self.assertEqual(
            compose.count(":/workspace/.opencode/skills/global-geochemical-atlas:ro"), 1
        )


if __name__ == "__main__":
    unittest.main()
