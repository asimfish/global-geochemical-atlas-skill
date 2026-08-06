#!/usr/bin/env python3
"""Offline integration tests for the Qwen API probe and benchmark runner."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_public_benchmark_task import RunnerFailure, sha256_tree  # noqa: E402


def artifact_builder_command() -> str:
    source = r'''
import base64
import csv
import json
import sqlite3
from pathlib import Path

root = Path("/submission/artifacts")
root.mkdir(parents=True, exist_ok=True)
(root / "observations.csv").write_text(
    "observation_id,source_id,source_row,sample_id,element,raw_value,raw_unit,normalized_value_ppm,medium,qualifier,censored,detection_limit,latitude,longitude,method,qc_status\n"
    "obs-001,src-001,1,sample-001,Ni,10,ppm,10,rock,=,false,,0,0,XRF,accepted\n",
    encoding="utf-8",
)
connection = sqlite3.connect(root / "geochemical.sqlite")
connection.execute("create table observations(observation_id text primary key, element text, value real)")
connection.execute("insert into observations values ('obs-001', 'Ni', 10)")
connection.commit()
connection.close()
(root / "sources.jsonl").write_text(json.dumps({"source_id": "src-001", "license": "test"}) + "\n", encoding="utf-8")
(root / "qc_report.json").write_text(json.dumps({"checks": [], "warnings": [], "limitations": ["offline test"]}), encoding="utf-8")
(root / "anomaly_results.csv").write_text("observation_id,element,score,status\nobs-001,Ni,0,normal\n", encoding="utf-8")
(root / "anomalies.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
(root / "h3_cells.csv").write_text("cell,resolution,medium,status\n8a2a10728907fff,10,rock,mapped\n", encoding="utf-8")
(root / "map.png").write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z3xkAAAAASUVORK5CYII="))
(root / "map.html").write_text("<!doctype html><html><body>offline test map</body></html>", encoding="utf-8")
selection = {
    "task_id": "GGA-DATA-001",
    "target": {"medium": "rock", "lithology": "basalt", "element": "Ni", "coverage": "global"},
    "primary_source_id": "georoc_precompiled",
    "discovery_source_id": "earthchem_portal",
    "decisions": [
        {"source_id": "georoc_precompiled", "status": "primary", "reason": "versioned primary data"},
        {"source_id": "earthchem_portal", "status": "discovery", "reason": "federated discovery"},
        {"source_id": "random_web_table", "status": "reject", "reason": "no provenance or license"},
    ],
}
provenance = {
    "task_id": "GGA-DATA-001",
    "record_fields": ["source_id", "source_record_id", "dataset_title", "dataset_version", "dataset_doi", "source_url", "accessed_at", "license", "sha256", "citation"],
    "download_sha256_required": True,
    "allowed_example_doi": "10.25625/2JETOA",
    "on_missing_provenance": "exclude_from_scientific_primary_dataset",
}
manifest = {
    "schema_version": "offline-runner-test.v1",
    "benchmark_evidence": {
        "source_selection.json": {"format": "json", "value": selection},
        "provenance_plan.json": {"format": "json", "value": provenance},
    },
}
(root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
'''
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return f"python3 -c \"import base64;exec(base64.b64decode('{encoded}'))\""


class FakeQwenHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    saw_reasoning_history = False

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        tools = payload.get("tools", [])
        tool_names = {
            item.get("function", {}).get("name")
            for item in tools
            if isinstance(item, dict)
        }
        last_role = payload.get("messages", [{}])[-1].get("role")
        if last_role == "tool" and any(
            item.get("role") == "assistant" and item.get("reasoning_content") == "offline private reasoning"
            for item in payload.get("messages", [])
            if isinstance(item, dict)
        ):
            type(self).saw_reasoning_history = True
        if "benchmark_api_probe" in tool_names:
            message: dict[str, Any] = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "probe-call-1",
                        "type": "function",
                        "function": {"name": "benchmark_api_probe", "arguments": json.dumps({"value": "QWEN_TOOL_OK"})},
                    }
                ],
            }
            finish_reason = "tool_calls"
        elif "run_in_benchmark_sandbox" in tool_names and last_role != "tool":
            message = {
                "role": "assistant",
                "content": None,
                "reasoning_content": "offline private reasoning",
                "tool_calls": [
                    {
                        "id": "sandbox-call-1",
                        "type": "function",
                        "function": {"name": "run_in_benchmark_sandbox", "arguments": json.dumps({"command": artifact_builder_command()})},
                    }
                ],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "All required artifacts were created and checked."}
            finish_reason = "stop"
        response = json.dumps(
            {
                "id": "offline-fake-qwen",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


class RunnerIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeQwenHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def environment(self) -> dict[str, str]:
        return {
            **os.environ,
            "QWEN_BASE_URL": self.base_url,
            "QWEN_API_KEY": "offline-test-key",
            "QWEN_MODEL": "offline-fake-qwen",
        }

    def test_api_probe_requires_native_tool_call(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qwen-api-test-") as temporary:
            report = Path(temporary) / "report.json"
            completed = subprocess.run(
                [sys.executable, str(HERE / "check_qwen_api.py"), "--output", str(report)],
                env=self.environment(),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "pass")

    def test_skill_hash_matches_e1_path_size_content_contract(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qwen-skill-hash-") as temporary:
            root = Path(temporary)
            first = root / "SKILL.md"
            nested = root / "references" / "rule.md"
            nested.parent.mkdir()
            first.write_text("skill\n", encoding="utf-8")
            nested.write_text("rule\n", encoding="utf-8")
            import hashlib

            expected = hashlib.sha256()
            for path in (first, nested):
                relative = path.relative_to(root).as_posix()
                expected.update(relative.encode("utf-8"))
                expected.update(b"\0")
                expected.update(str(path.stat().st_size).encode("ascii"))
                expected.update(b"\0")
                expected.update(path.read_bytes())
                expected.update(b"\0")
            self.assertEqual(sha256_tree(root), expected.hexdigest())

    def test_skill_hash_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="qwen-skill-symlink-") as temporary:
            root = Path(temporary)
            target = root / "target"
            target.write_text("x", encoding="utf-8")
            (root / "link").symlink_to(target)
            with self.assertRaises(RunnerFailure):
                sha256_tree(root)

    @unittest.skipUnless(shutil.which("bwrap"), "bubblewrap is not installed")
    def test_q01_runner_produces_score_and_record(self) -> None:
        FakeQwenHandler.saw_reasoning_history = False
        with tempfile.TemporaryDirectory(prefix="qwen-runner-test-") as temporary:
            run_root = Path(temporary) / "run"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(HERE / "run_public_benchmark_task.py"),
                    "--question", "Q01",
                    "--variant", "B0",
                    "--repeat", "1",
                    "--seed", "4201",
                    "--run-id", "offline-q01-b0-r1",
                    "--run-root", str(run_root),
                ],
                env=self.environment(),
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            self.assertEqual(completed.returncode, 0, f"stdout={completed.stdout}\nstderr={completed.stderr}")
            record = json.loads((run_root / "run_record.json").read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "success")
            self.assertEqual(record["exit_code"], 0)
            self.assertEqual(len(record["actual_submission_files"]), 10)
            self.assertEqual(record["score"]["score_status"], "partial")
            objective = json.loads((run_root / "objective_report.json").read_text(encoding="utf-8"))
            self.assertTrue(objective["hard_gate_passed"])
            self.assertTrue(FakeQwenHandler.saw_reasoning_history)


if __name__ == "__main__":
    unittest.main()
