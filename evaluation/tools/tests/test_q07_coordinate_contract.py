from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[2]
RELEASE_Q07 = EVALUATION_ROOT / "release" / "public" / "Q07"
VISIBLE_Q07 = EVALUATION_ROOT / "ai_visible_public" / "tasks" / "Q07"
EXPECTED_FLAGS = "latitude_out_of_range;possible_lat_lon_swap"


class Q07CoordinateContractTests(unittest.TestCase):
    def test_p02_swap_rule_is_consistent_across_visible_task_checker_and_gold(self) -> None:
        release_task = (RELEASE_Q07 / "task.md").read_text(encoding="utf-8")
        visible_task = (VISIBLE_Q07 / "task.md").read_text(encoding="utf-8")
        checker = json.loads(
            (RELEASE_Q07 / "checker" / "grader_spec.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (RELEASE_Q07 / "gold" / "artifacts" / "run_manifest.json").read_text(encoding="utf-8")
        )
        with (RELEASE_Q07 / "gold" / "coordinate_qc.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = {row["record_id"]: row for row in csv.DictReader(handle)}

        p02_check = next(check for check in checker["checks"] if check["id"] == "p02_lat")
        evidence_rows = {
            row["record_id"]: row
            for row in manifest["benchmark_evidence"]["coordinate_qc.csv"]["rows"]
        }
        self.assertEqual(release_task, visible_task)
        self.assertIn(EXPECTED_FLAGS, visible_task)
        self.assertEqual(p02_check["expected"], EXPECTED_FLAGS)
        self.assertEqual(rows["P02"]["qc_flags"], EXPECTED_FLAGS)
        self.assertEqual(rows["P02"]["suggested_latitude"], "10")
        self.assertEqual(rows["P02"]["suggested_longitude"], "95")
        self.assertEqual(evidence_rows["P02"]["qc_flags"], EXPECTED_FLAGS)
        self.assertEqual(evidence_rows["P02"]["suggested_latitude"], "10")
        self.assertEqual(evidence_rows["P02"]["suggested_longitude"], "95")


if __name__ == "__main__":
    unittest.main()
