#!/usr/bin/env python3
"""Render a task-configured D3 atlas from a standard D1/D2 output directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import build_interactive_map as map_builder


INTERFACE_VERSION = "d3-visualization-interface-v1"
REQUIRED_INPUTS = (
    "geochemistry.csv",
    "anomalies.geojson",
    "qc_report.json",
    "confidence_report.json",
    "source_manifest.json",
    "anomaly_report.json",
)
OPTIONAL_INPUTS = ("record_evidence.jsonl",)
GENERATED_OUTPUTS = (
    "interactive_map.html",
    "samples.geojson",
    "visualization_profile.json",
    "visualization_report.json",
)


class VisualizationError(RuntimeError):
    """Raised with a stable public failure status."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def copy_if_needed(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def failure_report(status: str, message: str) -> dict[str, Any]:
    return {
        "interface_version": INTERFACE_VERSION,
        "status": status,
        "outputs": {},
        "limitations": [message],
        "next_actions": [
            "Correct the reported input or profile error and rerun without inventing missing evidence."
        ],
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.input_dir.is_dir():
        raise VisualizationError("invalid_input", f"input directory does not exist: {args.input_dir}")
    if args.max_points < 1 or args.max_points > 200_000:
        raise VisualizationError("unsupported_scope", "--max-points must be between 1 and 200000")
    inputs = {name: args.input_dir / name for name in REQUIRED_INPUTS}
    missing = [name for name, path in inputs.items() if not path.is_file()]
    if missing:
        raise VisualizationError(
            "invalid_input", "D3 input directory is missing: " + ", ".join(missing)
        )
    if not args.profile.is_file():
        raise VisualizationError("invalid_input", f"visualization profile does not exist: {args.profile}")
    existing = [name for name in GENERATED_OUTPUTS if (args.output_dir / name).exists()]
    for name in (*REQUIRED_INPUTS, *OPTIONAL_INPUTS):
        source = args.input_dir / name
        destination = args.output_dir / name
        if (
            source.is_file()
            and destination.exists()
            and source.resolve() != destination.resolve()
        ):
            existing.append(name)
    if existing and not args.force:
        raise VisualizationError(
            "invalid_input",
            "output files already exist; choose a new directory or pass --force: "
            + ", ".join(existing),
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    try:
        profile = map_builder.load_visualization_profile(args.profile)
        map_report = map_builder.build_map(
            database=inputs["geochemistry.csv"],
            anomalies_path=inputs["anomalies.geojson"],
            output_html=args.output_dir / "interactive_map.html",
            output_geojson=args.output_dir / "samples.geojson",
            max_points=args.max_points,
            qc_report_path=inputs["qc_report.json"],
            confidence_report_path=inputs["confidence_report.json"],
            source_manifest_path=inputs["source_manifest.json"],
            anomaly_report_path=inputs["anomaly_report.json"],
            visualization_profile_path=args.profile,
        )
    except map_builder.MapBuildError as exc:
        message = str(exc)
        status = "unsupported_scope" if "exceed" in message or "--max-points" in message else "invalid_input"
        raise VisualizationError(status, message) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise VisualizationError("incomplete_retrieval", str(exc)) from exc

    for name, source in inputs.items():
        copy_if_needed(source, args.output_dir / name)
    for name in OPTIONAL_INPUTS:
        source = args.input_dir / name
        if source.is_file():
            copy_if_needed(source, args.output_dir / name)
    atomic_json(args.output_dir / "visualization_profile.json", profile)

    input_hashes = {name: sha256_file(path) for name, path in inputs.items()}
    output_hashes = {
        name: sha256_file(args.output_dir / name)
        for name in ("interactive_map.html", "samples.geojson", "visualization_profile.json")
    }
    report = {
        "interface_version": INTERFACE_VERSION,
        "status": "success",
        "input_contract": "D1/D2 standard output directory",
        "inputs": input_hashes,
        "profile_input": {
            "filename": args.profile.name,
            "sha256": sha256_file(args.profile),
        },
        "profile": profile,
        "profile_warnings": map_report.get("visualization_profile_warnings", []),
        "outputs": {
            "interactive_map": "interactive_map.html",
            "samples": "samples.geojson",
            "profile": "visualization_profile.json",
        },
        "output_sha256": output_hashes,
        "map_report": map_report,
        "limitations": [
            "D3 renders existing D1/D2 evidence and candidate anomalies; it does not recompute them.",
            "Blank areas indicate no included observations, not element absence or zero concentration.",
        ],
        "next_actions": [
            "Open interactive_map.html at the configured task view.",
            "Inspect profile_warnings and record-level source links before interpretation.",
        ],
    }
    atomic_json(args.output_dir / "visualization_report.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render a profile-driven interactive atlas from standard D1/D2 artifacts; "
            "the bundled HTML is an internal template and does not need manual editing."
        )
    )
    parser.add_argument(
        "--input-dir",
        required=True,
        type=Path,
        help="Directory containing the six required standard D1/D2 artifacts",
    )
    parser.add_argument("--output-dir", required=True, type=Path, help="New visualization bundle")
    parser.add_argument(
        "--profile",
        type=Path,
        default=map_builder.DEFAULT_PROFILE,
        help="d3-visualization-profile-v1 JSON; defaults to the bundled template",
    )
    parser.add_argument(
        "--max-points", type=int, default=50_000, help="Fail closed above this mappable record count"
    )
    parser.add_argument("--force", action="store_true", help="Replace generated D3 files")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except VisualizationError as exc:
        failure = exc
    except (OSError, json.JSONDecodeError) as exc:
        failure = VisualizationError("incomplete_retrieval", str(exc))
    else:
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "output_dir": str(args.output_dir),
                    "profile_warnings": report["profile_warnings"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(
            args.output_dir / "visualization_report.json",
            failure_report(failure.status, str(failure)),
        )
    except OSError as report_error:
        print(
            f"render_visualization: {failure}; could not write failure report: {report_error}",
            file=sys.stderr,
        )
        return 2
    print(f"render_visualization: {failure}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
