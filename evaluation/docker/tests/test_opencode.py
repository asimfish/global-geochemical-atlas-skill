from __future__ import annotations

import sys
import unittest
from pathlib import Path


CONTAINER_ROOT = Path(__file__).resolve().parents[1] / "container"
sys.path.insert(0, str(CONTAINER_ROOT))

from run_opencode import build_config, provider_sdk_base_url  # noqa: E402


class OpenCodeConfigTests(unittest.TestCase):
    def test_custom_provider_keeps_secret_as_environment_reference(self) -> None:
        config = build_config("https://gateway.example/v1", "vendor/model", 0.0)
        provider = config["provider"]["eval"]
        self.assertEqual(config["model"], "eval/vendor/model")
        self.assertEqual(provider["options"]["apiKey"], "{env:EVAL_API_KEY}")
        self.assertNotIn("secret", str(config).casefold())
        self.assertEqual(config["agent"]["build"]["temperature"], 0.0)

    def test_qwen_anthropic_profile_freezes_messages_path_and_thinking(self) -> None:
        config = build_config(
            "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic",
            "qwen3.8-max",
            0.6,
            "qwen-anthropic",
        )
        provider = config["provider"]["eval-anthropic"]
        self.assertEqual(config["model"], "eval-anthropic/qwen3.8-max")
        self.assertEqual(provider["npm"], "@ai-sdk/anthropic")
        self.assertEqual(
            provider["options"]["baseURL"],
            "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic/v1",
        )
        self.assertEqual(provider["options"]["apiKey"], "{env:EVAL_API_KEY}")
        self.assertEqual(config["agent"]["build"]["temperature"], 0.6)
        self.assertEqual(
            config["agent"]["build"]["thinking"], {"type": "disabled"}
        )
        self.assertNotIn("secret", str(config).casefold())

    def test_unknown_provider_profile_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            build_config("https://gateway.example", "model", 0.0, "unknown")

    def test_qwen_anthropic_profile_rejects_unapproved_base_url(self) -> None:
        with self.assertRaises(ValueError):
            provider_sdk_base_url(
                "https://example.com/apps/anthropic", "qwen-anthropic"
            )
        with self.assertRaises(ValueError):
            provider_sdk_base_url(
                "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic?x=1",
                "qwen-anthropic",
            )


if __name__ == "__main__":
    unittest.main()
