from __future__ import annotations

import copy
import hashlib
import json
import subprocess
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
    NetworkHandle,
    ProviderRelayHandle,
    RuntimeProfile,
    apply_q24_browser_gate,
    candidate_status,
    cleanup_provider_relay,
    docker_build_proxy_options,
    freeze_skill_snapshot,
    finalize_campaign_reviews,
    locate_llm_report,
    pair_fingerprint,
    parser,
    parse_conditions,
    parse_tasks,
    prepare_task_bundle,
    redact_file,
    redact_tree,
    run_campaign,
    run_one,
    start_provider_relay,
    validate_review,
    _campaign_path,
)
from common import hash_records, hash_tree  # noqa: E402
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
            self.assertFalse(plan["skill_snapshot"]["created"])
            self.assertEqual(len(plan["skill_snapshot"]["sha256"]), 64)
            self.assertFalse((output / "controller" / "frozen-skill").exists())

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

    def test_inline_reviews_fail_before_docker_because_bindings_do_not_exist_yet(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reviews = root / "reviews"
            reviews.mkdir()
            args = parser().parse_args(
                [
                    "run", "--agent", "mock", "--network", "offline",
                    "--llm-report-dir", str(reviews),
                    "--output-dir", str(root / "campaign"),
                ]
            )
            with patch("campaign.docker_available") as docker:
                with self.assertRaisesRegex(Exception, "finalize-reviews"):
                    run_campaign(args)
                docker.assert_not_called()

    def test_campaign_paths_reject_traversal_and_escaping_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaign"
            root.mkdir()
            inside = root / "score.json"
            inside.write_text("{}", encoding="utf-8")
            self.assertEqual(_campaign_path(root, "score.json", "score"), inside)
            with self.assertRaisesRegex(Exception, "escapes"):
                _campaign_path(root, "../score.json", "score")
            outside = Path(temporary) / "outside.json"
            outside.write_text("{}", encoding="utf-8")
            (root / "linked.json").symlink_to(outside)
            with self.assertRaisesRegex(Exception, "escapes"):
                _campaign_path(root, "linked.json", "score")

    def test_selection_and_candidate_status(self) -> None:
        self.assertEqual(parse_tasks("q01,Q01,q24"), ["Q01", "Q24"])
        self.assertEqual(parse_conditions("s0,b0,s0"), ["S0", "B0"])
        self.assertEqual(candidate_status(0, False, ["artifacts/map.png"]), (74, "failed"))
        self.assertEqual(candidate_status(137, False, []), (72, "resource_exceeded"))
        self.assertEqual(candidate_status(0, True, []), (71, "timed_out"))

    def test_q24_browser_audit_is_an_acceptance_gate(self) -> None:
        self.assertEqual(
            apply_q24_browser_gate("Q24", {"status": "pass"}, 0, "success"),
            (0, "success"),
        )
        self.assertEqual(
            apply_q24_browser_gate("Q24", {"status": "fail"}, 0, "success"),
            (70, "failed"),
        )
        self.assertEqual(
            apply_q24_browser_gate("Q24", None, 0, "success"),
            (70, "failed"),
        )
        self.assertEqual(
            apply_q24_browser_gate("Q23", None, 0, "success"),
            (0, "success"),
        )
        self.assertEqual(
            apply_q24_browser_gate("Q24", {"status": "fail"}, 71, "timed_out"),
            (71, "timed_out"),
        )

    def test_loopback_proxy_uses_host_build_network_without_serializing_secrets(self) -> None:
        options, network, forwarded = docker_build_proxy_options({
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "HTTPS_PROXY": "http://127.0.0.1:7897",
            "NO_PROXY": "localhost,127.0.0.1",
        })
        self.assertEqual(network, "host")
        self.assertEqual(forwarded, ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"])
        self.assertEqual(options[:2], ["--network", "host"])
        self.assertNotIn("password", " ".join(options))

    def test_credentialed_build_proxy_fails_closed(self) -> None:
        with self.assertRaisesRegex(Exception, "contains credentials"):
            docker_build_proxy_options({"HTTPS_PROXY": "http://user:password@proxy.example:8080"})

    def test_provider_key_is_not_serialized_in_the_relay_docker_command(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="true\n", stderr="")
        with (
            patch("campaign.run_checked", return_value=completed) as run_checked,
            patch("campaign.time.sleep"),
        ):
            relay = start_provider_relay(
                image="evaluation:test",
                network=NetworkHandle(
                    mode="whitelist", internal="internal", egress="egress", proxy="proxy"
                ),
                run_id="test-run",
                upstream_base_url="https://gateway.example/v1",
                upstream_api_key="provider-secret-value",
                model="qwen3.8-max",
                temperature=0.0,
                thinking_mode="not_configured",
                timeout_seconds=900,
            )
        first_call = run_checked.call_args_list[0]
        docker_command = first_call.args[0]
        self.assertNotIn("provider-secret-value", " ".join(docker_command))
        relay_token = first_call.kwargs["environment"]["EVAL_RELAY_TOKEN"]
        self.assertNotIn(relay_token, " ".join(docker_command))
        self.assertIn("EVAL_RELAY_TOKEN", docker_command)
        self.assertIn("EVAL_UPSTREAM_API_KEY", docker_command)
        self.assertEqual(
            first_call.kwargs["environment"]["EVAL_UPSTREAM_API_KEY"],
            "provider-secret-value",
        )
        self.assertEqual(len(relay.token), 64)

    def test_candidate_relay_token_is_not_serialized_in_docker_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign_root = Path(temporary) / "campaign"
            campaign_root.mkdir()
            relay = ProviderRelayHandle(container="relay", token="relay-capability-token")
            score = {
                "score_status": "partial",
                "hard_gate_passed": True,
                "total_score": None,
            }
            with (
                patch.dict("os.environ", {"EVAL_API_KEY": "provider-secret-value"}),
                patch("campaign.start_provider_relay", return_value=relay),
                patch("campaign.cleanup_provider_relay", return_value=True),
                patch("campaign.execute_container", return_value=(0, False, 0.1)) as execute,
                patch("campaign.grade_run", return_value=(score, None, None, False)),
            ):
                run_one(
                    campaign_root=campaign_root,
                    group="main",
                    campaign_id="token-test",
                    question="Q01",
                    condition="B0",
                    repeat=1,
                    image="evaluation:test",
                    image_id="sha256:image",
                    model="qwen3.8-max",
                    model_variant="",
                    temperature=0.0,
                    thinking_mode="not_configured",
                    api_key_env="EVAL_API_KEY",
                    provider_base_url="https://gateway.example/v1",
                    provider_profile=load_provider_profile("local-qwen38-openai-v1"),
                    agent_command=["python", "/opt/evaluation/container/run_opencode.py"],
                    network=NetworkHandle(
                        mode="whitelist", internal="internal", egress="egress", proxy="proxy"
                    ),
                    profile=RuntimeProfile(),
                    required_paths=[],
                    llm_report_dir=None,
                    static_review=None,
                    skill_dir=Path(temporary),
                    skill_sha256="f" * 64,
                    protocol_mode="formal",
                )
            arguments = execute.call_args.kwargs
            self.assertEqual(arguments["environment_names"], ["EVAL_API_KEY"])
            self.assertNotIn("EVAL_API_KEY", arguments["environment_values"])
            self.assertEqual(
                arguments["host_environment"]["EVAL_API_KEY"], "relay-capability-token"
            )

    def test_provider_relay_cleanup_requires_verified_container_removal(self) -> None:
        handle = ProviderRelayHandle(container="relay", token="token")
        removed = subprocess.CompletedProcess([], 0, stdout="relay\n", stderr="")
        gone = subprocess.CompletedProcess([], 1, stdout="", stderr="No such container")
        with patch("campaign.subprocess.run", side_effect=[removed, gone]):
            self.assertTrue(cleanup_provider_relay(handle))
        still_present = subprocess.CompletedProcess([], 0, stdout="{}", stderr="")
        with patch("campaign.subprocess.run", side_effect=[removed, still_present]):
            self.assertFalse(cleanup_provider_relay(handle))

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
            skill_sha256="f" * 64,
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
            skill_sha256="f" * 64,
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
            "skill_sha256": "f" * 64,
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

    def test_skill_snapshot_is_hash_identical_and_refuses_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("skill\n", encoding="utf-8")
            (source / "__pycache__").mkdir()
            (source / "__pycache__" / "ignored.pyc").write_bytes(b"ignored")
            destination = root / "snapshot"
            digest = freeze_skill_snapshot(source, destination)
            self.assertEqual(len(digest), 64)
            self.assertEqual((destination / "SKILL.md").read_text(), "skill\n")
            self.assertFalse((destination / "__pycache__").exists())

            linked_source = root / "linked-source"
            linked_source.mkdir()
            (linked_source / "SKILL.md").symlink_to(source / "SKILL.md")
            with self.assertRaisesRegex(Exception, "refuses symlinks"):
                freeze_skill_snapshot(linked_source, root / "linked-snapshot")

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

    def test_llm_review_must_bind_to_the_exact_run(self) -> None:
        binding = {
            "schema_version": "ai4s-evaluation-review-binding-v1",
            "run_id": "campaign-q01-s0-r2",
            "question_id": "Q01",
            "rubric_task_id": "GGA-SOURCE-001",
            "condition": "S0",
            "repeat": 2,
            "pair_fingerprint": "1" * 64,
            "task_bundle_sha256": "2" * 64,
            "submission_artifacts_sha256": "3" * 64,
            "objective_report_sha256": "4" * 64,
            "rubric_sha256": "5" * 64,
            "frozen_skill_sha256": "6" * 64,
            "grader_protocol_sha256": "7" * 64,
        }
        report = {
            "schema_version": "ai4s-bound-llm-review-v1",
            "review_type": "llm",
            "run_binding": binding,
            "reviewer": {"id": "independent-1", "model": "grader", "prompt_sha256": "7" * 64},
            "task_id": "GGA-SOURCE-001",
            "criteria": [],
            "redline_candidates": [],
            "grader_uncertainty": "low",
            "human_review_required": False,
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "review.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            validate_review(path, "LLM grader report", binding)
            stale = copy.deepcopy(report)
            stale["run_binding"]["repeat"] = 1
            path.write_text(json.dumps(stale), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "does not match the current run"):
                validate_review(path, "LLM grader report", binding)

            path.write_text(json.dumps({"task_id": "GGA-SOURCE-001", "criteria": []}), encoding="utf-8")
            with self.assertRaisesRegex(Exception, "frozen envelope"):
                validate_review(path, "LLM grader report", binding)

    def test_finalize_reviews_updates_an_existing_bound_run(self) -> None:
        repository = DOCKER_ROOT.parents[1]
        archived = (
            repository
            / "evaluation"
            / "results"
            / "runs"
            / "2026-08-06-q01-q24-independent-grade"
        )
        rubric = repository / "evaluation" / "release" / "public" / "Q01" / "rubric.json"
        protocol = repository / "evaluation" / "docs" / "llm_grader_protocol.md"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            campaign = root / "campaign"
            run_dir = campaign / "main" / "Q01" / "S0" / "repeat-1"
            reports = root / "reports"
            run_dir.mkdir(parents=True)
            reports.mkdir()
            task_dir = run_dir / "task"
            task_dir.mkdir()
            (task_dir / "task.md").write_text("frozen task\n", encoding="utf-8")
            frozen_skill = campaign / "controller" / "frozen-skill"
            frozen_skill.mkdir(parents=True)
            (frozen_skill / "SKILL.md").write_text("frozen skill\n", encoding="utf-8")
            alignment = json.loads(
                (repository / "evaluation" / "contracts" / "benchmark-execution-contract.json")
                .read_text(encoding="utf-8")
            )
            artifact_records = []
            for item in alignment["submission"]["required_artifacts"]:
                path = run_dir / "submission" / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"fixture for {item['path']}\n", encoding="utf-8")
                artifact_records.append(
                    (item["path"], hashlib.sha256(path.read_bytes()).hexdigest())
                )
            objective = run_dir / "objective_report.json"
            objective.write_bytes((archived / "Q01-objective_report.json").read_bytes())
            pair_inputs = {
                "image_id": "sha256:image",
                "model": "qwen3.8-max",
                "repeat": 1,
                "task_hash": hash_tree(task_dir),
                "skill_sha256": hash_tree(frozen_skill),
            }
            fingerprint = hashlib.sha256(
                json.dumps(pair_inputs, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            binding = {
                "schema_version": "ai4s-evaluation-review-binding-v1",
                "run_id": "campaign-q01-s0-r1",
                "question_id": "Q01",
                "rubric_task_id": "GGA-DATA-001",
                "condition": "S0",
                "repeat": 1,
                "pair_fingerprint": fingerprint,
                "task_bundle_sha256": hash_tree(task_dir),
                "submission_artifacts_sha256": hash_records(artifact_records),
                "objective_report_sha256": hashlib.sha256(objective.read_bytes()).hexdigest(),
                "rubric_sha256": hashlib.sha256(rubric.read_bytes()).hexdigest(),
                "frozen_skill_sha256": hash_tree(frozen_skill),
                "grader_protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
            }
            (run_dir / "review_binding.json").write_text(
                json.dumps(binding), encoding="utf-8"
            )
            (run_dir / "runner_metadata.json").write_text(
                json.dumps(
                    {
                        "candidate_status": "success",
                        "candidate_exit_code": 0,
                        "status": "success",
                        "exit_code": 0,
                        "scorer_failed": False,
                        "run_id": binding["run_id"],
                        "task": binding["question_id"],
                        "condition": binding["condition"],
                        "repeat": binding["repeat"],
                        "pair_fingerprint": binding["pair_fingerprint"],
                        "pair_fingerprint_inputs": pair_inputs,
                        "task_bundle_sha256": binding["task_bundle_sha256"],
                        "frozen_skill_sha256": binding["frozen_skill_sha256"],
                    }
                ),
                encoding="utf-8",
            )
            report = json.loads((archived / "Q01-llm_grader_report.json").read_text())
            report.update(
                {
                    "schema_version": "ai4s-bound-llm-review-v1",
                    "review_type": "llm",
                    "run_binding": binding,
                    "reviewer": {
                        "id": "independent-regression-reviewer",
                        "model": "archived-review-fixture",
                        "prompt_sha256": binding["grader_protocol_sha256"],
                    },
                }
            )
            allowed_evidence = json.loads(rubric.read_text())["evidence_paths"][0]
            for criterion in report["criteria"]:
                criterion["evidence"] = [allowed_evidence]
            (reports / "campaign-q01-s0-r1.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
            record = {
                "run_id": "campaign-q01-s0-r1",
                "task_id": "Q01",
                "variant": "S0",
                "repeat": 1,
                "pair_fingerprint": binding["pair_fingerprint"],
                "frozen_skill_sha256": binding["frozen_skill_sha256"],
                "score_path": "main/Q01/S0/repeat-1/score.json",
                "score": {"score_status": "partial", "total_score": None},
                "status": "success",
                "exit_code": 0,
            }
            (campaign / "runs.jsonl").write_text(
                json.dumps(record) + "\n", encoding="utf-8"
            )
            args = parser().parse_args(
                [
                    "finalize-reviews",
                    "--campaign-dir", str(campaign),
                    "--llm-report-dir", str(reports),
                ]
            )
            with redirect_stdout(StringIO()):
                self.assertEqual(finalize_campaign_reviews(args), 0)
            updated = json.loads((campaign / "runs.jsonl").read_text())
            self.assertEqual(updated["score"]["score_status"], "partial")
            self.assertGreater(updated["score"]["total_score"], 0)
            self.assertTrue((run_dir / "llm_grader_report.json").is_file())

            first_artifact = run_dir / "submission" / alignment["submission"]["required_artifacts"][0]["path"]
            first_artifact.write_text("tampered after binding\n", encoding="utf-8")
            with self.assertRaisesRegex(Exception, "bound run evidence drift"):
                finalize_campaign_reviews(args)

    def test_finalize_reviews_preserves_ineligible_runs_without_requesting_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            campaign = Path(temporary) / "campaign"
            run_dir = campaign / "main" / "Q01" / "B0" / "repeat-1"
            reports = Path(temporary) / "reports"
            run_dir.mkdir(parents=True)
            reports.mkdir()
            score = {
                "score_status": "ineligible",
                "total_score": None,
                "candidate_status": "failed",
            }
            (run_dir / "score.json").write_text(json.dumps(score), encoding="utf-8")
            (run_dir / "runner_metadata.json").write_text(
                json.dumps(
                    {
                        "candidate_status": "failed",
                        "candidate_exit_code": 74,
                        "status": "failed",
                        "exit_code": 74,
                    }
                ),
                encoding="utf-8",
            )
            record = {
                "run_id": "campaign-q01-b0-r1",
                "task_id": "Q01",
                "variant": "B0",
                "repeat": 1,
                "score_path": "main/Q01/B0/repeat-1/score.json",
                "score": score,
                "status": "failed",
                "exit_code": 74,
            }
            (campaign / "runs.jsonl").write_text(
                json.dumps(record) + "\n", encoding="utf-8"
            )
            args = parser().parse_args(
                [
                    "finalize-reviews",
                    "--campaign-dir", str(campaign),
                    "--llm-report-dir", str(reports),
                ]
            )
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(finalize_campaign_reviews(args), 0)
            self.assertIn('"reviewed_runs": 0', output.getvalue())
            self.assertEqual(json.loads((campaign / "runs.jsonl").read_text())["score"], score)

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
