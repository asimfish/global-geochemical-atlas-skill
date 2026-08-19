#!/usr/bin/env python3
"""Validate that a formal atlas delivery came from a sufficient online loop.

``validate_outputs.py`` proves the scientific file contracts.  This validator
adds the orchestration claim that a root-level package is the byte-identical
publication of one immutable, validated self-correction-loop round and that the
round passed the explicit data-sufficiency gate.  A direct staging run or an
honest thin checkpoint therefore cannot be mislabeled as completed research.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import validate_outputs as output_validator
import skill_snapshot

RECEIPT_FILENAME = "research_delivery_receipt.json"
LOOP_REPORT_FILENAME = "loop_report.json"
D1_REPAIR_QUEUE_FILENAME = "d1_repair_queue.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_object(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"missing {path.name}")
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"unreadable {path.name}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} must be a JSON object")
        return {}
    return value


def validate_delivery(
    output_dir: Path, *, allow_insufficient_checkpoint: bool = False
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    base_validation = output_validator.validate_dir(output_dir)
    if base_validation.get("status") != "valid":
        errors.append("stable output contract is invalid")

    loop = read_object(output_dir / LOOP_REPORT_FILENAME, errors)
    receipt = read_object(output_dir / RECEIPT_FILENAME, errors)
    repair_queue = read_object(output_dir / D1_REPAIR_QUEUE_FILENAME, errors)
    execution_path = output_dir / "request_evidence" / "execution.json"
    execution = read_object(execution_path, errors) if receipt else {}

    def checkpoint_requirement(message: str) -> None:
        target = warnings if allow_insufficient_checkpoint else errors
        if message not in target:
            target.append(message)

    if loop and loop.get("schema_version") != "self-correction-loop-report-v7":
        errors.append("formal research delivery requires loop report v7")
    if (
        receipt
        and receipt.get("schema_version") != "atlas-research-delivery-receipt-v3"
    ):
        errors.append("unsupported research delivery receipt version")

    if loop:
        if loop.get("stop_reason") != "converged":
            checkpoint_requirement("formal research delivery requires a converged loop")
        if loop.get("status") not in ("success", "partial_success"):
            message = "formal research delivery requires a successful loop status"
            if loop.get("status") == "needs_human_review":
                checkpoint_requirement(message)
            else:
                errors.append(message)
    if receipt:
        if receipt.get("loop_stop_reason") != loop.get("stop_reason"):
            errors.append("receipt loop_stop_reason does not match loop report")
        if receipt.get("loop_status") != loop.get("status"):
            errors.append("receipt loop_status does not match loop report")

    checkpoint_only = bool(
        loop.get("checkpoint_only") is True or receipt.get("checkpoint_only") is True
    )
    if checkpoint_only:
        message = "shortened checkpoint-only run cannot be a formal research delivery"
        checkpoint_requirement(message)

    published_round = loop.get("published_round")
    if receipt and receipt.get("published_round") != published_round:
        errors.append("receipt published_round does not match loop report")
    immutable_round_dir: Path | None = None
    if isinstance(published_round, int) and not isinstance(published_round, bool):
        expected_round_dir = f"rounds/round-{published_round:02d}"
        if receipt and receipt.get("published_round_dir") != expected_round_dir:
            errors.append("receipt published_round_dir is not the canonical round path")
        candidate_round_dir = output_dir / expected_round_dir
        try:
            output_root = output_dir.resolve(strict=True)
            resolved_round_dir = candidate_round_dir.resolve(strict=True)
        except OSError as exc:
            errors.append(f"immutable published round is unavailable: {exc}")
        else:
            if (
                (output_dir / "rounds").is_symlink()
                or candidate_round_dir.is_symlink()
                or not resolved_round_dir.is_relative_to(output_root)
            ):
                errors.append("immutable published round escapes the output directory")
            elif not resolved_round_dir.is_dir():
                errors.append("immutable published round is not a directory")
            else:
                immutable_round_dir = resolved_round_dir
    elif loop:
        errors.append("published round must be a positive integer")
    rounds = loop.get("rounds") if isinstance(loop.get("rounds"), list) else []
    selected = next(
        (
            item
            for item in rounds
            if isinstance(item, Mapping) and item.get("round") == published_round
        ),
        None,
    )
    if selected is None and loop:
        errors.append("published round is absent from loop history")
    elif selected is not None:
        if selected.get("validation_status") != "valid":
            errors.append("published round did not pass validate_outputs")
        sufficiency = selected.get("sufficiency")
        if not isinstance(sufficiency, Mapping):
            errors.append("published round lacks a data-sufficiency assessment")
        elif sufficiency.get("status") != "sufficient":
            message = "published round is an insufficient research checkpoint"
            checkpoint_requirement(message)

    receipt_execution_mode = str(receipt.get("execution_mode") or "")
    execution_mode = str(execution.get("mode") or "")
    if receipt and receipt_execution_mode != execution_mode:
        errors.append("receipt execution_mode does not match execution evidence")
    if (
        execution
        and execution.get("execution_version") != "geochemical-request-execution-v6"
    ):
        errors.append("formal research delivery requires request execution evidence v6")
    if receipt and not execution_mode.startswith("online_"):
        errors.append(
            "formal research delivery must use online acquisition, not fixture/input mode"
        )

    if repair_queue:
        queue_tasks = repair_queue.get("tasks")
        if repair_queue.get("queue_version") != "d1-repair-queue-v3":
            errors.append("unsupported D1 repair queue version")
        if repair_queue.get("request_sha256") != loop.get("request_sha256"):
            errors.append("D1 repair queue request hash does not match loop report")
        if not isinstance(queue_tasks, list):
            errors.append("D1 repair queue tasks must be an array")
            queue_tasks = []
        if repair_queue.get("task_count") != len(queue_tasks):
            errors.append("D1 repair queue task_count does not match tasks")
        queue_action_groups = repair_queue.get("action_groups")
        if not isinstance(queue_action_groups, list):
            errors.append("D1 repair queue action_groups must be an array")
            queue_action_groups = []
        if repair_queue.get("action_group_count") != len(queue_action_groups):
            errors.append(
                "D1 repair queue action_group_count does not match action_groups"
            )
        if repair_queue.get("unattempted_action_group_count") != len(
            queue_action_groups
        ):
            errors.append("D1 repair queue has unaccounted action-group receipts")
        if repair_queue.get("operator_continuation_required") != bool(
            queue_action_groups
        ):
            errors.append("D1 repair queue continuation flag is inconsistent")
        queue_status = repair_queue.get("status")
        if queue_status not in ("clear", "pending"):
            errors.append("D1 repair queue status is invalid")
        elif queue_status == "clear" and queue_tasks:
            errors.append("clear D1 repair queue still contains tasks")
        elif queue_status == "pending":
            checkpoint_requirement(
                "formal research delivery has pending D1 repair tasks"
            )
        if receipt and receipt.get("d1_repair_queue_status") != repair_queue.get(
            "status"
        ):
            errors.append("receipt D1 repair queue status does not match queue file")

    control_files = receipt.get("control_files")
    if receipt:
        if not isinstance(control_files, Mapping):
            errors.append("receipt lacks control-file hash bindings")
        else:
            control_paths = {
                "loop_report_sha256": output_dir / LOOP_REPORT_FILENAME,
                "d1_repair_queue_sha256": output_dir / D1_REPAIR_QUEUE_FILENAME,
                "execution_sha256": execution_path,
            }
            for key, path in control_paths.items():
                expected = control_files.get(key)
                if not path.is_file():
                    errors.append(f"missing control file for {key}")
                elif expected != sha256_file(path):
                    errors.append(f"control-file hash mismatch for {key}")

    receipt_snapshot = receipt.get("skill_snapshot")
    execution_snapshot = execution.get("skill_snapshot")
    if receipt:
        if not isinstance(receipt_snapshot, Mapping):
            errors.append("receipt lacks the executable Skill snapshot")
        elif not isinstance(execution_snapshot, Mapping):
            errors.append("execution evidence lacks the executable Skill snapshot")
        else:
            try:
                current_snapshot = skill_snapshot.fingerprint_skill_tree(
                    Path(__file__).resolve().parent.parent
                )
            except (OSError, skill_snapshot.SkillSnapshotError) as exc:
                errors.append(f"cannot fingerprint current Skill: {exc}")
                current_snapshot = {}
            if receipt_snapshot.get("matches_execution") is not True:
                errors.append("receipt says the Skill snapshot did not match execution")
            if execution_snapshot.get("stable_during_execution") is not True:
                errors.append(
                    "execution evidence says the Skill changed during execution"
                )
            if execution_snapshot.get("start_sha256") != execution_snapshot.get(
                "end_sha256"
            ):
                errors.append("execution start/end Skill hashes differ")
            if receipt_snapshot.get("execution_sha256") != execution_snapshot.get(
                "end_sha256"
            ):
                errors.append("receipt Skill hash does not match execution evidence")
            if receipt_snapshot.get("algorithm") != execution_snapshot.get("algorithm"):
                errors.append(
                    "receipt Skill algorithm does not match execution evidence"
                )
            for field in ("file_count", "total_bytes"):
                if receipt_snapshot.get(field) != execution_snapshot.get(field):
                    errors.append(
                        f"receipt Skill {field} does not match execution evidence"
                    )
            if receipt_snapshot.get("execution_sha256") != receipt_snapshot.get(
                "current_sha256"
            ):
                errors.append("receipt execution/current Skill hashes differ")
            if receipt_snapshot.get("current_sha256") != current_snapshot.get("sha256"):
                errors.append(
                    "current Skill tree differs from the published execution snapshot"
                )

    artifacts = receipt.get("artifacts")
    if receipt:
        if not isinstance(artifacts, Mapping):
            errors.append("receipt artifacts must be an object")
            artifacts = {}
        for filename in output_validator.REQUIRED_FILES.values():
            path = output_dir / filename
            round_path = (
                immutable_round_dir / filename
                if immutable_round_dir is not None
                else None
            )
            binding = (
                artifacts.get(filename) if isinstance(artifacts, Mapping) else None
            )
            if not isinstance(binding, Mapping):
                errors.append(f"receipt does not bind {filename}")
                continue
            if path.is_symlink():
                errors.append(f"root artifact must not be a symbolic link: {filename}")
            elif path.is_file() and binding.get("root_sha256") != sha256_file(path):
                errors.append(f"root hash mismatch for {filename}")
            if round_path is None:
                continue
            if round_path.is_symlink():
                errors.append(
                    f"immutable round artifact must not be a symbolic link: {filename}"
                )
                continue
            if not round_path.is_file():
                errors.append(f"immutable round artifact is missing: {filename}")
                continue
            actual_round_sha256 = sha256_file(round_path)
            if binding.get("round_sha256") != actual_round_sha256:
                errors.append(f"immutable round hash mismatch for {filename}")
            if path.is_file() and sha256_file(path) != actual_round_sha256:
                errors.append(
                    f"published bytes differ from immutable round for {filename}"
                )

        if receipt.get("request_sha256") != loop.get("request_sha256"):
            errors.append("receipt request hash does not match loop report")
        if receipt.get("delivery_ready") is not True:
            message = "receipt marks delivery_ready=false"
            if allow_insufficient_checkpoint and not errors:
                if message not in warnings:
                    warnings.append(message)
            elif not allow_insufficient_checkpoint:
                errors.append(message)

    return {
        "status": "valid" if not errors else "invalid",
        "delivery_ready": not errors and receipt.get("delivery_ready") is True,
        "errors": errors,
        "warnings": warnings,
        "published_round": published_round,
        "sufficiency_status": receipt.get("sufficiency_status"),
        "execution_mode": execution_mode or None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--allow-insufficient-checkpoint",
        action="store_true",
        help="Validate binding evidence while retaining an insufficient checkpoint warning",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = validate_delivery(
        args.output_dir,
        allow_insufficient_checkpoint=args.allow_insufficient_checkpoint,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "valid" else 1


if __name__ == "__main__":
    raise SystemExit(main())
