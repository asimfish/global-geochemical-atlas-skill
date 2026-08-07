#!/usr/bin/env python3
"""Dedicated offline tests for the standalone SGB Florianopolis soil adapter."""

from __future__ import annotations

import unittest

from brazil_sgb_florianopolis_soil import (
    BrazilSgbFlorianopolisSoilAdapter,
    EXPECTED,
    SKILL_DIR,
    check_audit,
    profile,
)


class BrazilSgbFlorianopolisSoilTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = BrazilSgbFlorianopolisSoilAdapter()
        self.files = self.adapter.download(self.adapter.candidate, SKILL_DIR / ".cache", "fixture")
        self.rows = list(self.adapter.parse(self.files))

    def test_fixture_profile(self) -> None:
        result = profile(self.adapter, self.files)
        self.assertEqual(result["raw_analysis_rows"], 5)
        self.assertEqual(result["unique_samples"], 5)
        self.assertEqual(result["target_observations"], 30)
        self.assertEqual(result["coordinate_status"], {"matched_arcgis_sample_lab": 5})

    def test_fixture_keeps_censoring(self) -> None:
        qualifiers = [
            observation["value_qualifier"]
            for row in self.rows
            for observation in row.fields["_target_observations"].values()
        ]
        self.assertEqual(qualifiers.count("below_detection_limit"), 3)
        self.assertEqual(qualifiers.count("not_detected"), 10)
        self.assertEqual(qualifiers.count("reported"), 17)

    def test_unknown_horizon_is_not_canonicalized(self) -> None:
        for row in self.rows:
            self.assertEqual(row.fields["soil_horizon_raw"], "Nao Identificado")
            self.assertIsNone(row.fields["soil_horizon"])
            self.assertIn("Nao Identificado", row.fields["soil_horizon_missing_reason"])
            self.assertIsNone(row.fields["digestion_or_extraction_raw"])

    def test_audit_maps_thirty_source_observations(self) -> None:
        check_audit()

    def test_discovery_scope_and_full_contract(self) -> None:
        self.assertEqual(self.adapter.discover({"media": ["sediment"]}), [])
        self.assertEqual(len(self.adapter.discover({"media": ["soil"], "regions": ["Brazil"]})), 1)
        self.assertEqual(EXPECTED["target_observations"], 192)
        self.assertEqual(EXPECTED["unique_target_samples"], 32)


if __name__ == "__main__":
    unittest.main()
