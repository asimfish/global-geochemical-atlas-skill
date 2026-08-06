#!/usr/bin/env python3
"""Fail-closed policy tests for private benchmark package validation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from validate_package import assess_private_eligibility  # noqa: E402


class PrivateEligibilityTest(unittest.TestCase):
    def waiting_alignment(self) -> dict[str, object]:
        return {
            "final_rotation": {
                "status": "WAITING_EXTERNAL_NEW_FINAL",
                "formal_final_eligible": False,
            }
        }

    def frozen_alignment(self) -> dict[str, object]:
        return {
            "final_rotation": {
                "status": "FROZEN_FOR_OFFICIAL",
                "formal_final_eligible": True,
            }
        }

    def test_missing_private_status_fails_formal_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            eligible, errors, limitations = assess_private_eligibility(
                self.waiting_alignment(), Path(temporary), False
            )
        self.assertFalse(eligible)
        self.assertTrue(any("status is missing or invalid" in item for item in errors))
        self.assertTrue(any("not FROZEN_FOR_OFFICIAL" in item for item in errors))
        self.assertEqual(limitations, [])

    def test_missing_private_status_is_only_legacy_regression_with_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            eligible, errors, limitations = assess_private_eligibility(
                self.waiting_alignment(), Path(temporary), True
            )
        self.assertFalse(eligible)
        self.assertEqual(errors, [])
        self.assertTrue(all("structural regression only" in item for item in limitations))

    def test_private_status_cannot_override_waiting_e2_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "PRIVATE_STATUS.json").write_text(
                json.dumps({"status": "FROZEN_PRIVATE_FINAL", "formal_final_eligible": True}),
                encoding="utf-8",
            )
            eligible, errors, _ = assess_private_eligibility(self.waiting_alignment(), root, False)
        self.assertFalse(eligible)
        self.assertTrue(any("not FROZEN_FOR_OFFICIAL" in item for item in errors))

    def test_both_sides_must_be_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "PRIVATE_STATUS.json").write_text(
                json.dumps({"status": "FROZEN_PRIVATE_FINAL", "formal_final_eligible": True}),
                encoding="utf-8",
            )
            eligible, errors, limitations = assess_private_eligibility(
                self.frozen_alignment(), root, False
            )
        self.assertTrue(eligible)
        self.assertEqual(errors, [])
        self.assertEqual(limitations, [])


if __name__ == "__main__":
    unittest.main()
