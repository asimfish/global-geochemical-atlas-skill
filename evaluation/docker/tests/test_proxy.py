from __future__ import annotations

import sys
import unittest
from pathlib import Path


CONTAINER_ROOT = Path(__file__).resolve().parents[1] / "container"
sys.path.insert(0, str(CONTAINER_ROOT))

from allowlist_proxy import host_allowed, normalized_rules  # noqa: E402


class AllowlistTests(unittest.TestCase):
    def test_exact_and_suffix_rules(self) -> None:
        rules = normalized_rules("gateway.example,.usgs.gov,GATEWAY.EXAMPLE.")
        self.assertEqual(rules, ("gateway.example", ".usgs.gov"))
        self.assertTrue(host_allowed("gateway.example", rules))
        self.assertFalse(host_allowed("sub.gateway.example", rules))
        self.assertTrue(host_allowed("usgs.gov", rules))
        self.assertTrue(host_allowed("data.usgs.gov", rules))
        self.assertFalse(host_allowed("usgs.gov.evil.example", rules))

    def test_ip_literals_are_never_allowed(self) -> None:
        self.assertFalse(host_allowed("8.8.8.8", ("8.8.8.8",)))
        self.assertFalse(host_allowed("::1", ("::1",)))


if __name__ == "__main__":
    unittest.main()
