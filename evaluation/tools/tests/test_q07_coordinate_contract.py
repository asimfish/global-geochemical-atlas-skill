from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[2]
Q07 = EVALUATION_ROOT / "release" / "public" / "Q07"
EXPECTED = "latitude_out_of_range;possible_lat_lon_swap"


class Q07CoordinateContractTests(unittest.TestCase):
    def test_p02_swap_rule_is_consistent_across_task_checker_and_gold(self) -> None:
        task = (Q07 / "task.md").read_text(encoding="utf-8")
        checker = json.loads(
            (Q07 / "checker" / "grader_spec.json").read_text(encoding="utf-8")
        )
        with (Q07 / "gold" / "coordinate_qc.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = {row["record_id"]: row for row in csv.DictReader(handle)}

        p02_check = next(check for check in checker["checks"] if check["id"] == "p02_lat")
        self.assertIn(EXPECTED, task)
        self.assertEqual(p02_check["expected"], EXPECTED)
        self.assertEqual(rows["P02"]["qc_flags"], EXPECTED)
        self.assertEqual(rows["P02"]["suggested_latitude"], "10")
        self.assertEqual(rows["P02"]["suggested_longitude"], "95")


if __name__ == "__main__":
    unittest.main()
