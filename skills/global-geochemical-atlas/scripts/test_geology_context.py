#!/usr/bin/env python3
"""Offline tests for the independent D1 geology context adapter."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import audit_geology_context
import geology_context


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
FIXTURE_DIR = SKILL_DIR / "fixtures" / "geology-context"


class GeologyContextTests(unittest.TestCase):
    def test_results_follow_the_companion_schema_shape(self) -> None:
        schema = json.loads(
            (SKILL_DIR / "references" / "geology-context-result.schema.json").read_text(encoding="utf-8")
        )
        required = set(schema["required"])
        candidate_required = set(schema["$defs"]["candidate"]["required"])
        for filename in ("point-audit-results.jsonl", "tile-audit-results.jsonl"):
            for line in (FIXTURE_DIR / filename).read_text(encoding="utf-8").splitlines():
                result = json.loads(line)
                self.assertEqual(set(result), required)
                self.assertIn(result["match_status"], schema["properties"]["match_status"]["enum"])
                for candidate in result["match_candidates"]:
                    self.assertEqual(set(candidate), candidate_required)

    def test_thirty_sample_audit_passes(self) -> None:
        report = audit_geology_context.build_audit(
            FIXTURE_DIR / "audit-samples.csv",
            FIXTURE_DIR / "point-audit-results.jsonl",
            FIXTURE_DIR / "tile-audit-results.jsonl",
        )
        self.assertEqual(report["sample_count"], 30)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["failed_lookup_count"], 0)
        self.assertEqual(
            report["tile_matches_consistent_with_point_candidates"],
            report["tile_match_count"],
        )

    def test_offline_point_and_tile_replay(self) -> None:
        locations = geology_context.load_locations(FIXTURE_DIR / "audit-samples.csv")
        client = geology_context.MacrostratClient(FIXTURE_DIR / "cache", offline=True)
        points = [geology_context.match_point(location, client) for location in locations]
        tiles = [geology_context.match_tile(location, client, zoom=5) for location in locations]
        self.assertEqual(len(points), 30)
        self.assertEqual(len(tiles), 30)
        self.assertNotIn("failed", {row["match_status"] for row in points + tiles})

    def test_point_overlap_is_not_forced(self) -> None:
        rows = [
            json.loads(line)
            for line in (FIXTURE_DIR / "point-audit-results.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        overlap = next(row for row in rows if row["sample_id"] == "geo-audit-01")
        self.assertEqual(overlap["match_status"], "ambiguous")
        self.assertIsNone(overlap["matched_geologic_unit"])
        self.assertGreater(len(overlap["match_candidates"]), 1)

    def test_source_geology_is_preserved_when_sample_is_patched(self) -> None:
        sample = {
            "sample_id": "sample-1",
            "geologic_unit_raw": "Field notebook unit",
            "matched_geologic_unit": None,
        }
        result = geology_context._base_result(
            geology_context.SampleLocation("sample-1", 10.0, 20.0, "Field notebook unit")
        )
        result.update(match_status="matched", matched_geologic_unit="Map unit")
        patched = geology_context.sample_patch(sample, result)
        self.assertEqual(patched["geologic_unit_raw"], "Field notebook unit")
        self.assertEqual(patched["matched_geologic_unit"], "Map unit")

    def test_missing_coordinate_has_explicit_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = geology_context.MacrostratClient(Path(directory), offline=True)
            result = geology_context.match_point(
                geology_context.SampleLocation("missing", None, None), client
            )
        self.assertEqual(result["match_status"], "not_attempted_missing_coordinate")
        self.assertEqual(result["cache_status"], "not_applicable")

    def test_polar_tile_request_falls_back_to_point_candidates(self) -> None:
        class PointOnlyClient:
            def point(self, latitude: float, longitude: float):
                return (
                    {
                        "success": {
                            "license": "CC-BY 4.0",
                            "data": [{"map_id": 1, "source_id": 2, "name": "Polar unit"}],
                            "refs": {"2": "Fixture map"},
                        }
                    },
                    "fixture",
                    "https://example.invalid/point",
                )

            def api_version(self):
                return "fixture", "fixture"

        result = geology_context.match_tile(
            geology_context.SampleLocation("polar", 89.0, 10.0), PointOnlyClient()
        )
        self.assertEqual(result["match_status"], "matched")
        self.assertEqual(result["matched_geologic_unit"], "Polar unit")
        self.assertEqual(result["match_method"], "macrostrat_v2_point_candidates_polar_fallback")

    def test_corrupt_offline_tile_is_failed_not_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            x, y, _, _ = geology_context._tile_position(43.0748, -89.3848, 9)
            tile = cache / "tiles" / "carto" / "9" / str(x) / f"{y}.mvt"
            tile.parent.mkdir(parents=True)
            tile.write_bytes(b"\x1a\xff")
            (cache / "macrostrat-api-meta-v2.json").write_text(
                '{"success":{"data":{"version":"fixture"}}}', encoding="utf-8"
            )
            client = geology_context.MacrostratClient(cache, offline=True)
            result = geology_context.match_tile(
                geology_context.SampleLocation("bad", 43.0748, -89.3848), client, zoom=9
            )
        self.assertEqual(result["match_status"], "failed")
        self.assertIsNone(result["matched_geologic_unit"])


if __name__ == "__main__":
    unittest.main()
