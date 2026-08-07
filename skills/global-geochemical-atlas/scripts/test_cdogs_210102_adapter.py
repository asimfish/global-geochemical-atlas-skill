#!/usr/bin/env python3
"""Offline tests for the CDoGS survey 210102 D1 adapter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cdogs_210102_adapter as adapter


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SCHEMA_PATH = SKILL_DIR / "references" / "cdogs-210102-observation.schema.json"
FIXTURE_ROOT = SKILL_DIR / "fixtures" / "four-media"
SOURCE_DIRS = {
    "cdogs-210102-lake-sediment": FIXTURE_ROOT / "sediment" / "cdogs-210102-lake-sediment",
    "cdogs-210102-lake-water": FIXTURE_ROOT / "water" / "cdogs-210102-lake-water",
}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class CDoGS210102AdapterTests(unittest.TestCase):
    def test_fixture_replays_exactly(self) -> None:
        for source_id, directory in SOURCE_DIRS.items():
            expected = read_jsonl(directory / "fixture-observations.jsonl")
            actual = adapter.extract_fixture_source(source_id, directory / "raw-fixture.jsonl")
            self.assertEqual(actual, expected)

    def test_observations_follow_companion_schema_shape(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        required = set(schema["required"])
        qualifier_enum = set(schema["properties"]["value_qualifier"]["enum"])
        for directory in SOURCE_DIRS.values():
            for row in read_jsonl(directory / "fixture-observations.jsonl"):
                self.assertEqual(set(row), required)
                self.assertIn(row["value_qualifier"], qualifier_enum)
                self.assertEqual(row["survey_key"], "21:0102")
                self.assertEqual(row["source_crs"], "EPSG:4269")

    def test_each_source_has_thirty_codex_audits(self) -> None:
        for source_id, directory in SOURCE_DIRS.items():
            audit = json.loads((directory / "automated_audit.json").read_text(encoding="utf-8"))
            self.assertEqual(audit["source_id"], source_id)
            self.assertEqual(audit["reviewer_type"], "codex")
            self.assertEqual(audit["status"], "automated_audit_complete")
            self.assertEqual(audit["record_count"], 30)
            self.assertEqual(len(audit["records"]), 30)
            self.assertEqual({row["status"] for row in audit["records"]}, {"PASS"})

    def test_full_profiles_reconcile_methods_and_detection_limits(self) -> None:
        expected = {
            "cdogs-210102-lake-sediment": (4411, 684, 580),
            "cdogs-210102-lake-water": (655, 655, 580),
        }
        for source_id, directory in SOURCE_DIRS.items():
            profile = json.loads((directory / "full-profile.json").read_text(encoding="utf-8"))
            observations, samples, sites = expected[source_id]
            self.assertEqual(profile["observation_count"], observations)
            self.assertEqual(profile["sample_count"], samples)
            self.assertEqual(profile["site_count"], sites)
            self.assertEqual(profile["method_assignment_count"], observations)
            self.assertEqual(profile["detection_limit_assignment_count"], observations)
            for file_record in profile["files"].values():
                self.assertGreater(file_record["survey_rows"], 0)
                self.assertTrue(all(file_record["method_observation_counts"].values()))

    def test_source_native_qualifiers_are_not_converted(self) -> None:
        sediment_profile = json.loads(
            (SOURCE_DIRS["cdogs-210102-lake-sediment"] / "full-profile.json").read_text()
        )
        water_profile = json.loads(
            (SOURCE_DIRS["cdogs-210102-lake-water"] / "full-profile.json").read_text()
        )
        self.assertEqual(sediment_profile["qualifier_counts"]["lt"], 485)
        self.assertEqual(sediment_profile["qualifier_counts"]["missing"], 221)
        self.assertEqual(water_profile["qualifier_counts"]["rejected"], 38)
        self.assertEqual(water_profile["qualifier_counts"]["missing"], 70)
        for directory in SOURCE_DIRS.values():
            for row in read_jsonl(directory / "fixture-observations.jsonl"):
                if row["value_qualifier"] != "reported":
                    self.assertIsNone(row["parsed_value"])

    def test_method_publication_and_source_locators_are_explicit(self) -> None:
        allowed_methods = {"2091", "2092", "2093", "2094", "2118", "2117", "1088", "1999"}
        for directory in SOURCE_DIRS.values():
            for row in read_jsonl(directory / "fixture-observations.jsonl"):
                self.assertIn(row["method_id"], allowed_methods)
                self.assertIn(row["publication_id"], {"GSC-OF-405", "GSC-OF-899"})
                self.assertIn("#sheet=1&row=", row["source_locator"])
                self.assertIn("&column=", row["source_locator"])
                self.assertTrue(row["method_source_locator"].startswith("https://geochem.nrcan.gc.ca/"))

    def test_water_sampling_year_conflict_is_not_resolved_by_guess(self) -> None:
        rows = read_jsonl(SOURCE_DIRS["cdogs-210102-lake-water"] / "fixture-observations.jsonl")
        self.assertTrue(rows)
        self.assertEqual({row["sampled_year_raw"] for row in rows}, {None})
        self.assertTrue(all("unresolved" in row["sampling_time_note"] for row in rows))

    def test_wrong_survey_key_fixture_fails(self) -> None:
        source_id = "cdogs-210102-lake-water"
        raw = read_jsonl(SOURCE_DIRS[source_id] / "raw-fixture.jsonl")
        raw[0]["row"]["Survey_Key"] = "99:9999"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-survey.jsonl"
            path.write_text(json.dumps(raw[0]) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(adapter.CDoGSError, "does not belong"):
                adapter.extract_fixture_source(source_id, path)

    def test_no_content_digest_contract(self) -> None:
        forbidden = ("md5", "sha1", "sha256", "sha-1", "sha-256", "checksum")
        code = (SCRIPT_DIR / "cdogs_210102_adapter.py").read_text(encoding="utf-8").lower()
        self.assertFalse(any(token in code for token in forbidden))
        for directory in SOURCE_DIRS.values():
            manifest = (directory / "run-manifest.json").read_text(encoding="utf-8").lower()
            self.assertFalse(any(token in manifest for token in forbidden))


if __name__ == "__main__":
    unittest.main()
