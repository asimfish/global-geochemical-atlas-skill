#!/usr/bin/env python3

from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "audit_source_truth.py"
SPEC = importlib.util.spec_from_file_location("audit_source_truth", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class SourceTruthAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.demos = self.root / "demos"
        source = {
            "source_id": "test-source",
            "dataset_title": "Test authority dataset",
            "dataset_doi": "10.9999/test",
            "dataset_version": "1",
            "license": "CC-BY-4.0",
            "authority_url": "https://doi.org/10.9999/test",
            "allowed_resolution_hosts": ["doi.org"],
            "medium": "soil",
            "source_file": "raw.csv",
            "source_file_sha256": "a" * 64,
            "spot_record": {
                "source_record_id": "src-1",
                "element_or_analyte": "As",
                "value": "2.1",
                "unit": "mg/kg",
                "latitude": "1.0",
                "longitude": "2.0",
                "source_locator": "raw.csv#row=2",
            },
        }
        self.contract = {
            "schema_version": "source-truth-contract-v1",
            "verified_at": "2026-08-07",
            "claim_boundary": "test only",
            "required_media": ["soil"],
            "sources": [source],
        }
        self.contract_path = self.root / "contract.json"
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
        demo = self.demos / "test-source"
        demo.mkdir(parents=True)
        source_row = {
            key: "" if value is None else str(value)
            for key, value in {**source, **source["spot_record"]}.items()
            if key not in {"spot_record", "authority_url", "allowed_resolution_hosts"}
        }
        (demo / "sources.jsonl").write_text(
            json.dumps(source_row) + "\n", encoding="utf-8"
        )
        demo_row = dict(source_row)
        demo_row["file_sha256"] = demo_row.pop("source_file_sha256")
        with (demo / "demo_input.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(demo_row))
            writer.writeheader()
            writer.writerow(demo_row)
        (demo / "run_manifest.json").write_text(
            json.dumps({"source_id": "test-source", "source_file_sha256": "a" * 64}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_fixture_passes(self) -> None:
        report = AUDIT.run_audit(self.contract_path, self.demos, False, 0.1)
        self.assertEqual("verified", report["status"])
        self.assertTrue(report["blocking_gate_passed"])

    def test_metadata_tampering_fails_closed(self) -> None:
        path = self.demos / "test-source" / "demo_input.csv"
        text = path.read_text(encoding="utf-8").replace("CC-BY-4.0", "CC0-1.0")
        path.write_text(text, encoding="utf-8")
        report = AUDIT.run_audit(self.contract_path, self.demos, False, 0.1)
        self.assertEqual("conflict", report["status"])
        self.assertFalse(report["blocking_gate_passed"])

    def test_spot_value_tampering_fails_closed(self) -> None:
        path = self.demos / "test-source" / "demo_input.csv"
        text = path.read_text(encoding="utf-8").replace(",2.1,", ",2100,")
        path.write_text(text, encoding="utf-8")
        report = AUDIT.run_audit(self.contract_path, self.demos, False, 0.1)
        self.assertEqual("conflict", report["status"])

    def test_missing_medium_coverage_invalidates_contract(self) -> None:
        self.contract["required_media"] = ["soil", "water"]
        self.contract_path.write_text(json.dumps(self.contract), encoding="utf-8")
        report = AUDIT.run_audit(self.contract_path, self.demos, False, 0.1)
        self.assertEqual("conflict", report["status"])
        self.assertTrue(report["contract_errors"])


if __name__ == "__main__":
    unittest.main()
