#!/usr/bin/env python3
"""Benchmark the public atlas workflow with repeated, validated fresh runs."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import validate_outputs


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
RUNNER = SCRIPT_DIR / "run_atlas_request.py"
DEFAULT_REQUEST = SKILL_DIR / "fixtures" / "production-usgs" / "request.json"
SCHEMA_VERSION = "geochemical-workflow-benchmark-v1"


class BenchmarkError(RuntimeError):
    """Raised when a benchmark run cannot produce validated comparable evidence."""


def _last_json_object(stdout: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise BenchmarkError("runner stdout did not contain a JSON object")


def _revision() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    revision = result.stdout.strip()
    return revision if result.returncode == 0 and len(revision) == 40 else None


def _portable_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _run_once(
    *,
    request: Path,
    demo: str,
    analysis_profile: str,
    generated_at: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="gga-workflow-benchmark-") as temporary:
        output_dir = Path(temporary) / "output"
        command = [
            sys.executable,
            str(RUNNER),
            "--request",
            str(request),
            "--demo",
            demo,
            "--analysis-profile",
            analysis_profile,
            "--generated-at",
            generated_at,
            "--output-dir",
            str(output_dir),
        ]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=SKILL_DIR,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BenchmarkError(
                f"workflow exceeded the {timeout_seconds:g}-second benchmark timeout"
            ) from exc
        elapsed = time.perf_counter() - started
        payload = _last_json_object(completed.stdout)
        if completed.returncode != 0:
            raise BenchmarkError(
                f"workflow exited {completed.returncode}: {payload.get('status', 'unknown')}"
            )
        validation = validate_outputs.validate_dir(output_dir)
        if validation.get("status") != "valid":
            raise BenchmarkError(
                "workflow output validation failed: "
                + "; ".join(str(item) for item in validation.get("errors", []))
            )
        return {
            "duration_seconds": round(elapsed, 6),
            "runner_status": payload.get("status"),
            "record_counts": payload.get("record_counts"),
            "request_coverage": payload.get("request_coverage"),
            "validation_metrics": validation.get("metrics"),
        }


def run_benchmark(
    *,
    request: Path = DEFAULT_REQUEST,
    demo: str = "production-usgs",
    analysis_profile: str = "production",
    generated_at: str = "2026-08-07T00:00:00Z",
    warmups: int = 3,
    runs: int = 10,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Run a frozen workflow repeatedly and return validated timing statistics."""

    if not request.is_file():
        raise BenchmarkError(f"request does not exist: {request}")
    if warmups < 0 or runs < 1:
        raise BenchmarkError("warmups must be non-negative and runs must be positive")
    if timeout_seconds <= 0:
        raise BenchmarkError("timeout_seconds must be positive")

    for _ in range(warmups):
        _run_once(
            request=request,
            demo=demo,
            analysis_profile=analysis_profile,
            generated_at=generated_at,
            timeout_seconds=timeout_seconds,
        )

    measurements = [
        _run_once(
            request=request,
            demo=demo,
            analysis_profile=analysis_profile,
            generated_at=generated_at,
            timeout_seconds=timeout_seconds,
        )
        for _ in range(runs)
    ]
    signatures = {
        json.dumps(
            {
                "runner_status": item["runner_status"],
                "record_counts": item["record_counts"],
                "request_coverage": item["request_coverage"],
                "validation_metrics": item["validation_metrics"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for item in measurements
    }
    if len(signatures) != 1:
        raise BenchmarkError("validated workflow results changed between measured runs")

    durations = [float(item["duration_seconds"]) for item in measurements]
    first = measurements[0]
    return {
        "schema_version": SCHEMA_VERSION,
        "revision": _revision(),
        "workload": {
            "request": _portable_path(request),
            "demo": demo,
            "analysis_profile": analysis_profile,
            "generated_at": generated_at,
            "fresh_output_directory_per_run": True,
            "network": "disabled by frozen demo",
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
        },
        "protocol": {
            "warmups": warmups,
            "measured_runs": runs,
            "timeout_seconds_per_run": timeout_seconds,
            "clock": "time.perf_counter",
            "validation": "fifteen-file validate_outputs contract after every run",
        },
        "timing_seconds": {
            "median": round(statistics.median(durations), 6),
            "mean": round(statistics.mean(durations), 6),
            "sample_stdev": round(statistics.stdev(durations), 6)
            if len(durations) > 1
            else 0.0,
            "minimum": round(min(durations), 6),
            "maximum": round(max(durations), 6),
            "samples": durations,
        },
        "result_consistency": {
            "distinct_result_signatures": len(signatures),
            "runner_status_counts": dict(
                sorted(Counter(item["runner_status"] for item in measurements).items())
            ),
            "record_counts": first["record_counts"],
            "request_coverage": first["request_coverage"],
            "validation_metrics": first["validation_metrics"],
        },
        "claim_boundary": (
            "This measures the frozen local workflow and output validation only. It excludes "
            "network acquisition, OpenCode/model latency, scientific representativeness, and official uplift."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, default=DEFAULT_REQUEST)
    parser.add_argument("--demo", default="production-usgs")
    parser.add_argument("--analysis-profile", default="production")
    parser.add_argument("--generated-at", default="2026-08-07T00:00:00Z")
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_benchmark(
            request=args.request,
            demo=args.demo,
            analysis_profile=args.analysis_profile,
            generated_at=args.generated_at,
            warmups=args.warmups,
            runs=args.runs,
            timeout_seconds=args.timeout_seconds,
        )
    except (BenchmarkError, OSError, ValueError) as exc:
        print(
            json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    if args.output:
        _atomic_json(args.output, report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
