#!/usr/bin/env python3
"""Plan the minimum deterministic D1/D2/D3 command for a frozen task contract."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import execution_budget


SCRIPT_DIR = Path(__file__).resolve().parent
PYTHON_COMMAND = "python3"
CONTRACT_VERSION = "atlas-task-contract-v1"
PLAN_VERSION = "atlas-task-plan-v1"
TASK_TYPES = {
    "source_discovery",
    "normalize_qc",
    "spatial_geology",
    "anomaly_screening",
    "visualization",
    "element_comparison",
    "full_atlas",
}
ALLOWED_KEYS = {
    "contract_version",
    "task_type",
    "request",
    "input",
    "evidence_jsonl",
    "acquisition_manifest",
    "input_dir",
    "profile",
    "output_dir",
    "acquisition_mode",
    "required_outputs",
    "deadline_seconds",
}
FULL_OUTPUTS = [
    "geochemistry.csv",
    "source_manifest.json",
    "record_evidence.jsonl",
    "qc_report.json",
    "confidence_report.json",
    "sources_and_confidence.json",
    "anomalies.geojson",
    "anomaly_report.json",
    "batch_acceptance.csv",
    "batch_qc_report.json",
    "anomaly_regions.geojson",
    "spatial_anomaly_report.json",
    "samples.geojson",
    "interactive_map.html",
    "iteration_backlog.csv",
    "run_summary.json",
]
TASK_OUTPUTS = {
    "source_discovery": ["source_route.json", "coverage.json", "coverage.md"],
    "normalize_qc": ["geochemistry.csv", "qc_report.json", "confidence_report.json"],
    "spatial_geology": ["geochemistry.csv", "qc_report.json", "confidence_report.json"],
    "anomaly_screening": [
        "geochemistry.csv",
        "qc_report.json",
        "confidence_report.json",
        "anomalies.geojson",
        "anomaly_report.json",
        "anomaly_regions.geojson",
        "spatial_anomaly_report.json",
    ],
    "visualization": [
        "interactive_map.html",
        "samples.geojson",
        "visualization_report.json",
    ],
    "element_comparison": [
        "interactive_map.html",
        "samples.geojson",
        "element_comparison.json",
        "visualization_report.json",
    ],
    "full_atlas": FULL_OUTPUTS,
}


class TaskRoutingError(ValueError):
    """Raised when a task contract is ambiguous or cannot use a stable entry point."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise TaskRoutingError(f"task contract does not exist: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TaskRoutingError(
            f"task contract is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise TaskRoutingError("task contract must be a JSON object")
    return value


def _path_text(
    contract: Mapping[str, Any], key: str, required: bool = False
) -> str | None:
    value = contract.get(key)
    if value is None and not required:
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 4096
        or "\x00" in value
    ):
        qualifier = "required" if required else "invalid"
        raise TaskRoutingError(f"task contract {key} is {qualifier}")
    return value


def validate_contract(raw: Mapping[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - ALLOWED_KEYS)
    if unknown:
        raise TaskRoutingError(
            f"task contract has unsupported keys: {', '.join(unknown)}"
        )
    if raw.get("contract_version") != CONTRACT_VERSION:
        raise TaskRoutingError(f"task contract must use {CONTRACT_VERSION}")
    task_type = raw.get("task_type")
    if task_type not in TASK_TYPES:
        raise TaskRoutingError("task_type is unsupported")
    output_dir = _path_text(raw, "output_dir", required=True)
    request = _path_text(raw, "request")
    input_path = _path_text(raw, "input")
    input_dir = _path_text(raw, "input_dir")
    profile = _path_text(raw, "profile")
    evidence = _path_text(raw, "evidence_jsonl")
    manifest = _path_text(raw, "acquisition_manifest")
    acquisition_mode = raw.get(
        "acquisition_mode",
        "provided_input" if input_path is not None else "online_auto",
    )
    if acquisition_mode not in {
        "provided_input",
        "online_auto",
        "production_demo",
        "four_media_demo",
    }:
        raise TaskRoutingError("acquisition_mode is unsupported")
    # Online full-atlas work gets the 12-hour controller ceiling; each child
    # round is still capped at 30 minutes.  Provided-input and narrow tasks need
    # only the single-round default unless the caller declares another limit.
    default_deadline = (
        execution_budget.MAX_INTERNAL_BUDGET_SECONDS
        if acquisition_mode == "online_auto" and task_type == "full_atlas"
        else execution_budget.DEFAULT_INTERNAL_BUDGET_SECONDS
    )
    deadline = raw.get("deadline_seconds", default_deadline)
    if (
        isinstance(deadline, bool)
        or not isinstance(deadline, (int, float))
        or not math.isfinite(float(deadline))
        or not 1 <= float(deadline) <= execution_budget.MAX_INTERNAL_BUDGET_SECONDS
    ):
        raise TaskRoutingError("deadline_seconds must be between 1 and 43200")
    required_outputs = raw.get("required_outputs")
    defaults = TASK_OUTPUTS[str(task_type)]
    if required_outputs is None:
        required_outputs = list(defaults)
    if (
        not isinstance(required_outputs, list)
        or not required_outputs
        or len(required_outputs) != len(set(required_outputs))
        or not all(
            isinstance(item, str) and 0 < len(item) <= 120 for item in required_outputs
        )
    ):
        raise TaskRoutingError(
            "required_outputs must be a non-empty unique filename array"
        )
    unsupported_outputs = sorted(set(required_outputs) - set(defaults))
    if unsupported_outputs:
        raise TaskRoutingError(
            f"task_type={task_type} cannot guarantee outputs: {', '.join(unsupported_outputs)}"
        )
    if task_type in {"source_discovery", "full_atlas"} and request is None:
        raise TaskRoutingError(f"task_type={task_type} requires request")
    if (
        task_type in {"normalize_qc", "spatial_geology", "anomaly_screening"}
        and input_path is None
    ):
        raise TaskRoutingError(f"task_type={task_type} requires input")
    if task_type in {"visualization", "element_comparison"} and (
        input_dir is None or profile is None
    ):
        raise TaskRoutingError(f"task_type={task_type} requires input_dir and profile")
    if (
        task_type == "full_atlas"
        and acquisition_mode == "provided_input"
        and input_path is None
    ):
        raise TaskRoutingError("full_atlas provided_input mode requires input")
    return {
        "contract_version": CONTRACT_VERSION,
        "task_type": task_type,
        "request": request,
        "input": input_path,
        "evidence_jsonl": evidence,
        "acquisition_manifest": manifest,
        "input_dir": input_dir,
        "profile": profile,
        "output_dir": output_dir,
        "acquisition_mode": acquisition_mode,
        "required_outputs": required_outputs,
        "deadline_seconds": float(deadline),
    }


def _append_optional(command: list[str], flag: str, value: str | None) -> None:
    if value is not None:
        command.extend([flag, value])


def plan_task(raw: Mapping[str, Any]) -> dict[str, Any]:
    contract = validate_contract(raw)
    task_type = str(contract["task_type"])
    output_dir = str(contract["output_dir"])
    commands: list[list[str]] = []
    validators: list[list[str]] = []
    if task_type == "source_discovery":
        commands = [
            [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "source_router.py"),
                "--request",
                str(contract["request"]),
                "--output",
                str(Path(output_dir) / "source_route.json"),
            ],
            [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "coverage_report.py"),
                "--request",
                str(contract["request"]),
                "--json-output",
                str(Path(output_dir) / "coverage.json"),
                "--markdown-output",
                str(Path(output_dir) / "coverage.md"),
            ],
        ]
    elif task_type in {"normalize_qc", "spatial_geology", "anomaly_screening"}:
        command = [
            PYTHON_COMMAND,
            str(SCRIPT_DIR / "standardize_geochemistry.py"),
            "--input",
            str(contract["input"]),
            "--output-dir",
            output_dir,
        ]
        if task_type == "spatial_geology":
            command.extend(
                [
                    "--geology-grid",
                    str(
                        SCRIPT_DIR.parent / "assets" / "geology" / "pangaea-788537.zip"
                    ),
                    "--geology-grid-sha256",
                    "43b4ce3276b155d804db8ff9fb227d620b4c35015a4cf564eac4d06d2b69d88e",
                ]
            )
        commands = [command]
    elif task_type in {"visualization", "element_comparison"}:
        commands = [
            [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "render_visualization.py"),
                "--input-dir",
                str(contract["input_dir"]),
                "--profile",
                str(contract["profile"]),
                "--output-dir",
                output_dir,
            ]
        ]
        validators = [
            [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "validate_visualization.py"),
                "--output-dir",
                output_dir,
            ]
        ]
    else:
        mode = contract["acquisition_mode"]
        deadline = float(contract["deadline_seconds"])
        if mode == "online_auto" and deadline >= 120:
            round_timeout = min(
                execution_budget.DEFAULT_INTERNAL_BUDGET_SECONDS, deadline
            )
            run_timeout = max(60.0, round_timeout - min(60.0, round_timeout / 4))
            command = [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "run_self_correction_loop.py"),
                "--request",
                str(contract["request"]),
                "--output-dir",
                output_dir,
                "--online-source",
                "auto",
                "--time-budget-seconds",
                str(deadline),
                "--round-timeout-seconds",
                str(round_timeout),
                "--run-timeout-seconds",
                str(run_timeout),
                "--source-timeout-seconds",
                str(min(600.0, run_timeout)),
            ]
            if deadline < execution_budget.DEFAULT_INTERNAL_BUDGET_SECONDS:
                command.append("--checkpoint-only")
        else:
            command = [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "run_atlas_request.py"),
                "--request",
                str(contract["request"]),
                "--output-dir",
                output_dir,
                "--total-timeout-seconds",
                str(deadline),
            ]
        if mode == "provided_input":
            command.extend(["--input", str(contract["input"])])
            _append_optional(command, "--evidence-jsonl", contract["evidence_jsonl"])
            _append_optional(
                command, "--acquisition-manifest", contract["acquisition_manifest"]
            )
        elif mode == "online_auto" and deadline < 120:
            # Very short, explicitly frozen tasks cannot host a safe research
            # round; they still attempt online acquisition once and report the
            # partial boundary rather than substituting a fixture.
            command.extend(["--online-source", "auto", "--allow-single-round-partial"])
        elif mode == "production_demo":
            command.extend(["--demo", "production-usgs"])
        elif mode == "four_media_demo":
            command.extend(["--demo", "four-media"])
        commands = [command]
        validators = [
            [
                PYTHON_COMMAND,
                str(SCRIPT_DIR / "validate_outputs.py"),
                "--output-dir",
                output_dir,
            ]
        ]
    return {
        "plan_version": PLAN_VERSION,
        "task_type": task_type,
        "deadline_seconds": contract["deadline_seconds"],
        "required_outputs": contract["required_outputs"],
        "commands": commands,
        "validators": validators,
        "completion_rule": "only the frozen required_outputs and validators define completion",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = plan_task(_read_json(args.contract))
        rendered = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (OSError, TaskRoutingError) as exc:
        print(
            json.dumps(
                {"status": "invalid_input", "error": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
