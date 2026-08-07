from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


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
    run_campaign,
)
from provider_profiles import ProviderProfileError, load_provider_profile  # noqa: E402


class CampaignTests(unittest.TestCase):
    def test_source_truth_stage_is_a_supported_offline_suite(self) -> None:
        args = parser().parse_args(
            ["stage", "--suite", "source-truth", "--output-dir", "/tmp/source-truth"]
        )
        self.assertEqual(args.suite, "source-truth")
        self.assertEqual(args.network, "offline")

    def test_campaign_plan_records_audited_provider_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            args = parser().parse_args(
                [
                    "run",
                    "--agent",
                    "mock",
                    "--network",
                    "offline",
                    "--tasks",
                    "Q01",
                    "--conditions",
                    "B0,S0",
                    "--repeats",
                    "3",
                    "--output-dir",
                    str(output),
                    "--dry-run",
                ]
            )
            with (
                patch("campaign.docker_available", return_value={}),
                patch("campaign.image_identity", return_value="sha256:image"),
                redirect_stdout(StringIO()),
            ):
                self.assertEqual(run_campaign(args), 0)
            plan = json.loads((output / "campaign_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["provider_profile"]["id"], "local-qwen38-openai-v1")
            self.assertEqual(plan["provider_profile"]["thinking"]["mode"], "not_configured")
            self.assertEqual(plan["provider_profile"]["runtime_policy"]["model"]["value"], "qwen3.8-max")
            self.assertEqual(len(plan["provider_profile"]["profile_sha256"]), 64)
            self.assertEqual(plan["temperature"], 0.0)

    def test_unknown_profile_fails_before_docker_or_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "campaign"
            args = parser().parse_args(
                [
                    "run",
                    "--agent",
                    "mock",
                    "--network",
                    "offline",
                    "--provider-profile",
                    "does-not-exist",
                    "--output-dir",
                    str(output),
                ]
            )
            with patch("campaign.docker_available") as docker:
                with self.assertRaises(ProviderProfileError):
                    run_campaign(args)
                docker.assert_not_called()
            self.assertFalse(output.exists())

    def test_formal_pair_fails_closed_when_repeats_are_not_three(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            args = parser().parse_args([
                "run", "--agent", "mock", "--network", "offline",
                "--conditions", "B0,S0", "--repeats", "1",
                "--output-dir", str(Path(temporary) / "campaign"),
            ])
            with patch("campaign.docker_available") as docker:
                with self.assertRaisesRegex(Exception, "exactly --repeats 3"):
                    run_campaign(args)
                docker.assert_not_called()

    def test_selection_and_candidate_status(self) -> None:
        self.assertEqual(parse_tasks("q01,Q01,q24"), ["Q01", "Q24"])
        self.assertEqual(parse_conditions("s0,b0,s0"), ["S0", "B0"])
        self.assertEqual(candidate_status(0, False, ["artifacts/map.png"]), (74, "failed"))
        self.assertEqual(candidate_status(137, False, []), (72, "resource_exceeded"))
        self.assertEqual(candidate_status(0, True, []), (71, "timed_out"))

    def test_pair_fingerprint_is_shared_by_b0_and_s0_inputs(self) -> None:
        profile = RuntimeProfile()
        provider_profile = load_provider_profile("local-qwen38-openai-v1")
        first = pair_fingerprint(
            task_hash="a" * 64,
            image_id="sha256:image",
            model="model",
            model_variant="",
            temperature=0.0,
            repeat=1,
            profile=profile,
            network="offline",
            provider_profile=provider_profile,
            provider_base_url="https://gateway.example/v1",
            thinking_mode="not_configured",
        )
        second = pair_fingerprint(
            task_hash="a" * 64,
            image_id="sha256:image",
            model="model",
            model_variant="",
            temperature=0.0,
            repeat=1,
            profile=profile,
            network="offline",
            provider_profile=provider_profile,
            provider_base_url="https://gateway.example/v1",
            thinking_mode="not_configured",
        )
        self.assertEqual(first, second)

    def test_pair_fingerprint_detects_provider_endpoint_or_profile_drift(self) -> None:
        common = {
            "task_hash": "a" * 64,
            "image_id": "sha256:image",
            "model": "qwen3.8-max",
            "model_variant": "",
            "temperature": 0.0,
            "repeat": 1,
            "profile": RuntimeProfile(),
            "network": "whitelist",
            "thinking_mode": "not_configured",
        }
        frozen = pair_fingerprint(
            **common,
            provider_profile=load_provider_profile("local-qwen38-openai-v1"),
            provider_base_url="https://gateway.example/v1",
        )
        changed_endpoint = pair_fingerprint(
            **common,
            provider_profile=load_provider_profile("local-qwen38-openai-v1"),
            provider_base_url="https://other.example/v1",
        )
        changed_profile = pair_fingerprint(
            **common,
            provider_profile=load_provider_profile("openai-compatible"),
            provider_base_url="https://gateway.example/v1",
        )
        self.assertNotEqual(frozen, changed_endpoint)
        self.assertNotEqual(frozen, changed_profile)

    def test_task_bundle_contains_only_public_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "task"
            _, split, digest = prepare_task_bundle("Q09", destination)
            self.assertEqual(split, "shadow")
            self.assertEqual(len(digest), 64)
            self.assertTrue((destination / "task.md").is_file())
            self.assertTrue((destination / "validate_submission_contract.py").is_file())
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
