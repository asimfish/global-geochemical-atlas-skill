from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


DOCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_ROOT))

from campaign import (  # noqa: E402
    RuntimeProfile,
    candidate_status,
    locate_llm_report,
    pair_fingerprint,
    parser,
    parse_conditions,
    parse_tasks,
    prepare_task_bundle,
    redact_file,
    redact_tree,
)


class CampaignTests(unittest.TestCase):
    def test_source_truth_stage_is_a_supported_offline_suite(self) -> None:
        args = parser().parse_args(
            ["stage", "--suite", "source-truth", "--output-dir", "/tmp/source-truth"]
        )
        self.assertEqual(args.suite, "source-truth")
        self.assertEqual(args.network, "offline")

    def test_selection_and_candidate_status(self) -> None:
        self.assertEqual(parse_tasks("q01,Q01,q24"), ["Q01", "Q24"])
        self.assertEqual(parse_conditions("s0,b0,s0"), ["S0", "B0"])
        self.assertEqual(candidate_status(0, False, ["artifacts/map.png"]), (74, "failed"))
        self.assertEqual(candidate_status(137, False, []), (72, "resource_exceeded"))
        self.assertEqual(candidate_status(0, True, []), (71, "timed_out"))

    def test_pair_fingerprint_is_shared_by_b0_and_s0_inputs(self) -> None:
        profile = RuntimeProfile()
        first = pair_fingerprint(
            task_hash="a" * 64,
            image_id="sha256:image",
            model="model",
            model_variant="",
            temperature=0.0,
            provider_profile="openai-compatible",
            repeat=1,
            profile=profile,
            network="offline",
        )
        second = pair_fingerprint(
            task_hash="a" * 64,
            image_id="sha256:image",
            model="model",
            model_variant="",
            temperature=0.0,
            provider_profile="openai-compatible",
            repeat=1,
            profile=profile,
            network="offline",
        )
        self.assertEqual(first, second)

    def test_qwen_anthropic_profile_is_explicit(self) -> None:
        args = parser().parse_args(
            [
                "run",
                "--provider-profile",
                "qwen-anthropic",
                "--provider-base-url",
                "https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic",
                "--temperature",
                "0.6",
                "--output-dir",
                "/tmp/qwen-campaign",
            ]
        )
        self.assertEqual(args.provider_profile, "qwen-anthropic")
        self.assertEqual(args.model, "qwen3.8-max")
        self.assertEqual(args.temperature, 0.6)

    def test_task_bundle_contains_only_public_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "task"
            _, split, digest = prepare_task_bundle("Q09", destination)
            self.assertEqual(split, "shadow")
            self.assertEqual(len(digest), 64)
            self.assertTrue((destination / "task.md").is_file())
            self.assertFalse((destination / "rubric.json").exists())
            self.assertFalse(any(path.name in {"gold", "checker.py"} for path in destination.rglob("*")))

    def test_llm_report_resolution_is_per_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "main" / "Q01" / "S0" / "repeat-2.json"
            report.parent.mkdir(parents=True)
            report.write_text(json.dumps({"criteria": []}), encoding="utf-8")
            self.assertEqual(locate_llm_report(root, "run", "main", "Q01", "S0", 2), report)

    def test_log_secret_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.log"
            path.write_text("before secret-value after\n", encoding="utf-8")
            redact_file(path, ["secret-value"])
            self.assertEqual(path.read_text(encoding="utf-8"), "before [REDACTED_EVAL_SECRET] after\n")

    def test_submission_secret_is_removed_and_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "artifact.bin"
            path.write_bytes(b"prefix-secret-value-suffix")
            self.assertEqual(redact_tree(root, ["secret-value"]), ["artifact.bin"])
            self.assertNotIn(b"secret-value", path.read_bytes())


if __name__ == "__main__":
    unittest.main()
