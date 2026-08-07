from __future__ import annotations

import sys
import unittest
from pathlib import Path


CONTAINER_ROOT = Path(__file__).resolve().parents[1] / "container"
sys.path.insert(0, str(CONTAINER_ROOT))

from provider_relay import parse_upstream, upstream_target  # noqa: E402


class ProviderRelayTests(unittest.TestCase):
    def test_target_is_confined_to_frozen_https_origin_and_base_path(self) -> None:
        base = parse_upstream("https://gateway.example/api/v1")
        self.assertEqual(
            upstream_target(base, "/chat/completions?trace=0"),
            "https://gateway.example/api/v1/chat/completions?trace=0",
        )

    def test_credentials_and_non_https_upstreams_are_rejected(self) -> None:
        for value in (
            "http://gateway.example/v1",
            "https://user:secret@gateway.example/v1",
            "https://gateway.example/v1?redirect=https://evil.example",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_upstream(value)

    def test_absolute_request_targets_cannot_escape_the_frozen_origin(self) -> None:
        base = parse_upstream("https://gateway.example/v1")
        for value in ("https://evil.example/steal", "//evil.example/steal", "relative"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                upstream_target(base, value)

    def test_arbitrary_provider_paths_are_rejected(self) -> None:
        base = parse_upstream("https://gateway.example/v1")
        for value in ("/models", "/echo", "/files"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                upstream_target(base, value)


if __name__ == "__main__":
    unittest.main()
