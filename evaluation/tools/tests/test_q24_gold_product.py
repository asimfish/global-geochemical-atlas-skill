from __future__ import annotations

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_q24_gold_artifacts", TOOLS_ROOT / "build_q24_gold_artifacts.py"
)
assert SPEC and SPEC.loader
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


class Q24PhysicalGoldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gold = (
            Path(__file__).resolve().parents[2]
            / "evaluator_private/final_holdout/Q24/gold/artifacts"
        )

    def test_physical_product_rebuild_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "artifacts"
            BUILDER.build(self.gold / "run_manifest.json", output)
            for name in [*BUILDER.ARTIFACT_IDS, "run_manifest.json"]:
                self.assertEqual(
                    BUILDER.sha256_file(output / name),
                    BUILDER.sha256_file(self.gold / name),
                    name,
                )

    def test_database_map_and_manifest_form_one_q24_evidence_chain(self) -> None:
        manifest = json.loads((self.gold / "run_manifest.json").read_text(encoding="utf-8"))
        logical_rows = manifest["benchmark_evidence"]["observations.csv"]["rows"]
        logical_sources = manifest["benchmark_evidence"]["sources.jsonl"]["rows"]
        connection = sqlite3.connect(self.gold / "geochemical.sqlite")
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM observations").fetchone()[0], len(logical_rows))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0], len(logical_sources))
            self.assertEqual(connection.execute("PRAGMA quick_check").fetchone()[0], "ok")
        finally:
            connection.close()
        html = (self.gold / "map.html").read_text(encoding="utf-8")
        for token in ("zoomBy", "showAnom", "record_id", "source_id", "POINTS", "ANOMALIES"):
            self.assertIn(token, html)
        hashes = {item["artifact_id"]: item["sha256"] for item in manifest["artifacts"]}
        for name, artifact_id in BUILDER.ARTIFACT_IDS.items():
            self.assertEqual(hashes[artifact_id], BUILDER.sha256_file(self.gold / name))


if __name__ == "__main__":
    unittest.main()
