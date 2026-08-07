#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import aggregate_uplift
import build_experiment_manifest
import generate_report


class ReportingTests(unittest.TestCase):
    def test_controller_manifest_binds_pair_and_only_allows_skill_visibility_difference(self) -> None:
        config = json.loads(
            (Path(__file__).resolve().parents[2]
             / "evaluation_lyf/agent_uplift/experiment_config.json").read_text(encoding="utf-8")
        )
        common = [{"path": "TASK.md", "bytes": 10, "sha256": "a" * 64}]
        b0 = {
            "schema_version": "qwen-uplift-candidate-bundle-v1", "mode": "formal",
            "condition": "B0", "source_commit": config["commit"],
            "content_manifest_sha256": "b" * 64,
            "files": common + [{"path": "AGENT_PROMPT.md", "bytes": 1, "sha256": "c" * 64}],
        }
        s0 = {
            **b0, "condition": "S0", "content_manifest_sha256": "d" * 64,
            "files": common + [
                {"path": "AGENT_PROMPT.md", "bytes": 1, "sha256": "e" * 64},
                {"path": ".agents/skills/global-geochemical-atlas/SKILL.md", "bytes": 2, "sha256": "f" * 64},
            ],
        }
        b0_manifest = build_experiment_manifest.build(
            config, b0, s0, condition="B0", runtime="host-uplift", run_id="b0-1",
            provider_base_url="https://gateway.example.test/v1",
        )
        s0_manifest = build_experiment_manifest.build(
            config, b0, s0, condition="S0", runtime="host-uplift", run_id="s0-1",
            provider_base_url="https://gateway.example.test/v1",
        )
        self.assertEqual(b0_manifest["pair_fingerprint"], s0_manifest["pair_fingerprint"])
        self.assertNotEqual(b0_manifest["run_fingerprint"], s0_manifest["run_fingerprint"])
        s0["files"][0] = {"path": "TASK.md", "bytes": 11, "sha256": "0" * 64}
        with self.assertRaisesRegex(build_experiment_manifest.ManifestError, "public task bytes differ"):
            build_experiment_manifest.build(
                config, b0, s0, condition="S0", runtime="host-uplift", run_id="s0-2",
                provider_base_url="https://gateway.example.test/v1",
            )

    def test_report_distinguishes_measurements_samples_and_locations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = [
                {
                    "record_id": f"r{i}", "sample_id": "sample-1", "element_or_analyte": element,
                    "value": "1", "unit": "mg/kg", "medium": "soil", "latitude": "-31.93",
                    "longitude": "115.85", "original_latitude_raw": "-31.93",
                    "original_longitude_raw": "115.85", "normalized_value": "1",
                    "normalized_unit": "mg/kg", "source_id": "source-1",
                    "source_locator": f"https://example.test#row={i}", "file_sha256": "0" * 64,
                    "license": "CC0", "qc_flags": "[]",
                    "operational_confidence": '{"band":"high"}',
                    "analytical_method": "ICP-MS", "geologic_context_status": "reported",
                    "coordinate_uncertainty_status": "reported",
                }
                for i, element in enumerate(("As", "Ni"), 1)
            ]
            for name in ("d1_raw.csv", "geochemistry.csv"):
                with (root / name).open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader(); writer.writerows(rows)
            samples = {
                "type": "FeatureCollection", "features": [
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [115.85, -31.93]}, "properties": {"record_id": row["record_id"]}}
                    for row in rows
                ],
            }
            for name, value in (
                ("samples.geojson", samples),
                ("anomalies.geojson", {"type": "FeatureCollection", "features": []}),
                ("anomaly_report.json", {"scientific_status": "screening_only"}),
                ("source_manifest.json", {"sources": []}),
                ("confidence_report.json", {"not_a_probability": True}),
                ("qc_report.json", {}),
            ):
                (root / name).write_text(json.dumps(value), encoding="utf-8")
            html = root / "interactive_map.html"
            html.write_text("<html>map</html>", encoding="utf-8")
            digest = hashlib.sha256(html.read_bytes()).hexdigest()
            browser = root / "browser.json"
            screenshot_root = root / "screenshots"
            screenshot_root.mkdir()
            screenshots = []
            for index in range(5):
                screenshot = screenshot_root / f"shot-{index}.png"
                screenshot.write_bytes(f"shot-{index}".encode())
                screenshots.append({
                    "file": screenshot.name, "bytes": screenshot.stat().st_size,
                    "sha256": hashlib.sha256(screenshot.read_bytes()).hexdigest(),
                })
            browser.write_text(json.dumps({
                "schema_version": "geochemical-browser-audit-v1", "status": "pass",
                "generated_by": "external_evaluation_controller", "loaded": True,
                "rendered_product": True, "javascript_errors": [],
                "html": {"sha256": digest, "bytes": html.stat().st_size},
                "screenshot_directory": "screenshots", "screenshots": screenshots,
            }), encoding="utf-8")
            args = argparse.Namespace(
                submission_dir=root, runtime="docker-uplift", condition="S0", run_id="s0-1",
                independent_session=True, blind_bundle=True, score=None,
                browser_audit=browser, experiment_manifest=None, skill_document=None,
            )
            report = generate_report.build(args)
            self.assertEqual(report["d1"]["measurement_records"], 2)
            self.assertEqual(report["d1"]["unique_samples"], 1)
            self.assertEqual(report["d3"]["map_measurement_features"], 2)
            self.assertEqual(report["d3"]["map_unique_locations"], 1)
            self.assertTrue(report["d3"]["browser_audit_bound"])

    def test_aggregate_requires_three_independent_runs_and_flags_ceiling(self) -> None:
        reports = []
        for condition, scores in (("B0", (100, 100, 100)), ("S0", (97, 98, 97))):
            for index, score in enumerate(scores, 1):
                reports.append({
                    "schema_version": "global-geochemical-evaluation-report-v1",
                    "experiment": {"condition": condition, "run_id": f"{condition}-{index}", "manifest": {"pair_fingerprint": "pair-1"}},
                    "fairness": {"eligible_run_component": True},
                    "score": {"observed": score},
                })
        result = aggregate_uplift.aggregate(reports)
        self.assertEqual(result["status"], "eligible")
        self.assertEqual(result["median_uplift_s0_minus_b0"], -3)
        self.assertTrue(result["ceiling_saturated"])
        self.assertFalse(result["valid_uplift_evidence"])
        result = aggregate_uplift.aggregate(reports[:-1])
        self.assertEqual(result["status"], "not_eligible")


if __name__ == "__main__":
    unittest.main()
