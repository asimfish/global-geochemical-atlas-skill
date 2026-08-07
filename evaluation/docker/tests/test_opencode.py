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


if __name__ == "__main__":
    unittest.main()
