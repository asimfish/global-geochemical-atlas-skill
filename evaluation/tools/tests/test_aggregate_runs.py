from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


TOOLS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_ROOT))

from aggregate_runs import AggregateError, ALIGNMENT_PATH, aggregate  # noqa: E402


def records_for_one_task() -> list[dict[str, object]]:
    alignment = json.loads(ALIGNMENT_PATH.read_text(encoding="utf-8"))
    dimensions = [
        {
            "dimension_id": item["dimension_id"],
            "weight": item["weight"],
            "score": 80.0,
            "metrics": [{"metric_id": "test", "status": "scored"}],
        }
        for item in alignment["dimensions"]
    ]
    records: list[dict[str, object]] = []
    skill_sha256 = "a" * 64
    for repeat in (1, 2, 3):
        fingerprint = f"{repeat}" * 64
        for variant in ("B0", "S0"):
            run_id = f"q01-{variant.casefold()}-r{repeat}"
            records.append(
                {
                    "run_id": run_id,
                    "task_id": "Q01",
                    "split": "public",
                    "variant": variant,
                    "repeat": repeat,
                    "pair_fingerprint": fingerprint,
                    "status": "success",
                    "exit_code": 0,
                    "provider": {
                        "official_claim": False,
                        "verification_status": "local_frozen_policy",
                    },
                    "model": "qwen3.8-max",
                    "sandbox_image": "sha256:image",
                    "skill_version": skill_sha256 if variant == "S0" else None,
                    "frozen_skill_sha256": skill_sha256,
                    "benchmark_version": alignment["benchmark_version"],
                    "protocol_mode": "formal",
                    "benchmark_scope": "repo_local_regression",
                    "formal_result_eligible": False,
                    "redline_events": [],
                    "score": {
                        "contract_sha256": alignment["e1_contract_sha256"],
                        "run_id": run_id,
                        "candidate_status": "success",
                        "score_status": "complete",
                        "hard_gate_passed": True,
                        "dimensions": copy.deepcopy(dimensions),
                        "total_score": 80.0,
                    },
                }
            )
    return records


class AggregateRunsTests(unittest.TestCase):
    def test_complete_local_campaign_is_not_mislabeled_official_ready(self) -> None:
        _, summary = aggregate(records_for_one_task())
        self.assertTrue(summary["all_scores_complete"])
        self.assertFalse(summary["official_ready"])
        self.assertIn("full_24_task_campaign", summary["official_ready_reasons"])
        self.assertIn("official_frozen_benchmark", summary["official_ready_reasons"])

    def test_campaign_rejects_skill_identity_drift(self) -> None:
        records = records_for_one_task()
        for record in records:
            if record["repeat"] == 2:
                record["frozen_skill_sha256"] = "b" * 64
                if record["variant"] == "S0":
                    record["skill_version"] = "b" * 64
        with self.assertRaisesRegex(
            AggregateError, "more than one frozen Skill identity"
        ):
            aggregate(records)

    def test_s0_must_bind_the_frozen_skill(self) -> None:
        records = records_for_one_task()
        next(record for record in records if record["variant"] == "S0")[
            "skill_version"
        ] = "b" * 64
        with self.assertRaisesRegex(AggregateError, "does not match the frozen Skill"):
            aggregate(records)


if __name__ == "__main__":
    unittest.main()
