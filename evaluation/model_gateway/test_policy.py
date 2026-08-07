#!/usr/bin/env python3
"""Offline unit checks for the frozen model gateway configuration."""

from __future__ import annotations

import importlib.util
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("gateway_probe", ROOT / "probe.py")
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class ModelGatewayPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = json.loads((ROOT / "model-policy.json").read_text(encoding="utf-8"))
        self.config = json.loads((ROOT / "opencode.json").read_text(encoding="utf-8"))

    def test_frozen_policy_and_opencode_config_match(self) -> None:
        PROBE.validate(self.policy, self.config)

    def test_primary_is_not_a_fallback(self) -> None:
        primary = self.policy["routing"]["primary"]["model_id"]
        fallbacks = {item["model_id"] for item in self.policy["routing"]["fallbacks"]}
        self.assertNotIn(primary, fallbacks)

    def test_auth_and_quota_errors_do_not_activate_fallback(self) -> None:
        blocked = set(self.policy["routing"]["not_service_unavailable_signals"])
        self.assertTrue({"http_401", "http_403", "http_429"} <= blocked)

    def test_proxy_connect_denial_counts_as_blocked(self) -> None:
        denied = urllib.error.URLError(OSError("Tunnel connection failed: 403 Forbidden"))
        with mock.patch.object(PROBE.urllib.request, "urlopen", side_effect=denied):
            status, url = PROBE.request("https://example.com", expect_blocked=True)
        self.assertEqual(status, 403)
        self.assertEqual(url, "https://example.com")


if __name__ == "__main__":
    unittest.main()
