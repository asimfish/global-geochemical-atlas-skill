#!/usr/bin/env python3
"""Offline checks for the USGS Utah volcanic whole-rock adapter."""

from __future__ import annotations

import unittest
from pathlib import Path

import source_adapters


class UsgsUtahVolcanicRockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapter = source_adapters.get_adapter("usgs-utah-volcanic-whole-rock")
        cls.candidate = cls.adapter.discover({"media": ["rock"]})[0]
        cls.files = cls.adapter.download(cls.candidate, Path("unused"), mode="fixture")
        cls.records = list(cls.adapter.parse(cls.files))
        cls.observations = [
            observation
            for record in cls.records
            for observation in record.fields["_target_observations"].values()
        ]

    def test_fixture_contract(self) -> None:
        self.assertEqual(len(self.files), 11)
        self.assertEqual(len(self.records), 31)
        self.assertEqual(len(self.observations), 171)
        self.assertEqual({item["analyte"] for item in self.observations}, {"As", "Cr", "Cu", "Ni", "Pb", "Zn"})

    def test_censor_and_method_uncertainty_are_explicit(self) -> None:
        censored = [item for item in self.observations if item["below_laboratory_dl"]]
        self.assertTrue(censored)
        self.assertTrue(all(item["value_qualifier"] == "<" for item in censored))
        self.assertTrue(all(float(item["reported_value"]) < 0 for item in censored))
        ambiguous = [item for item in self.observations if len(item["method_candidates"]) > 1]
        self.assertTrue(ambiguous)
        self.assertTrue(all(not item["analytical_method"] for item in ambiguous))
        self.assertTrue(all(item["method_missing_reason"] == "multiple_active_methods_cover_analyte" for item in ambiguous))

    def test_usgs_alabs_coordinate_swap_is_traceable(self) -> None:
        record = next(item for item in self.records if item.fields["_child_item_id"] == "67f95691d4be022c3e84f3af")
        self.assertEqual(record.fields["_latitude"], record.fields["LONGITUDE"])
        self.assertEqual(record.fields["_longitude"], record.fields["LATITUDE"])
        self.assertEqual(record.fields["_source_crs"], "EPSG:4269")
        self.assertIn("raw columns are retained", record.fields["_coordinate_assignment_note"])

    def test_independent_lineage_and_lab_evidence(self) -> None:
        self.assertEqual(self.candidate.dataset_doi, "10.5066/P1NZXUZF")
        self.assertEqual(source_adapters.source_lineage_id(self.candidate.source_id), self.candidate.source_id)
        record = next(item for item in self.records if item.fields["_child_item_id"] == "67f954e4d4be022c3e84f384")
        self.assertIn("ALS", record.fields["_laboratory_raw"])


if __name__ == "__main__":
    unittest.main()
