#!/usr/bin/env python3
"""Migrate checked-in source demos to the evidence-bound V4 exchange columns."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import generate_demo_data
import source_adapters
import v4_semantics


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_DEMOS = SKILL_DIR / "fixtures" / "source-demos"


class MigrationError(RuntimeError):
    """Raised when fixture migration cannot preserve one-to-one evidence."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _csv_bytes(rows: Sequence[Mapping[str, str]]) -> bytes:
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=generate_demo_data.INPUT_COLUMNS,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
        handle.seek(0)
        return handle.read().encode("utf-8")


def _atomic_bytes(path: Path, value: bytes) -> None:
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())


def expected_fixture(source_id: str, fixture_dir: Path, registry: Mapping[str, Any]) -> tuple[bytes, dict[str, Any]]:
    input_path = fixture_dir / "demo_input.csv"
    evidence_path = fixture_dir / "sources.jsonl"
    manifest_path = fixture_dir / "run_manifest.json"
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    evidence = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(evidence) or not rows:
        raise MigrationError(f"{source_id} does not have one evidence row per observation")
    registry_sources = registry.get("sources")
    if not isinstance(registry_sources, Mapping) or source_id not in registry_sources:
        raise MigrationError(f"{source_id} is absent from source registry")
    enriched = [
        v4_semantics.enrich_row(row, item, registry_sources[source_id], str(registry.get("verified_at") or ""))
        for row, item in zip(rows, evidence, strict=True)
    ]
    content = _csv_bytes(enriched)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["exchange_schema"] = "d1-v4-exchange-v1"
    manifest["v4_semantics_version"] = v4_semantics.SEMANTICS_VERSION
    outputs = {str(item["path"]): item for item in manifest.get("outputs", [])}
    demo_output = outputs.get("demo_input.csv")
    if not isinstance(demo_output, dict):
        raise MigrationError(f"{source_id} manifest has no demo_input.csv output")
    demo_output["bytes"] = len(content)
    demo_output["sha256"] = _sha256_bytes(content)
    return content, manifest


def migrate(demo_root: Path, *, check: bool) -> dict[str, Any]:
    registry = source_adapters.load_source_registry()
    source_ids = sorted(v4_semantics.SOURCE_CONTRACTS)
    migrated: list[str] = []
    for source_id in source_ids:
        fixture_dir = demo_root / source_id
        content, manifest = expected_fixture(source_id, fixture_dir, registry)
        input_path = fixture_dir / "demo_input.csv"
        manifest_path = fixture_dir / "run_manifest.json"
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        if check:
            if input_path.read_bytes() != content:
                raise MigrationError(f"stale V4 demo CSV: {source_id}")
            if manifest_path.read_bytes() != manifest_bytes:
                raise MigrationError(f"stale V4 demo manifest: {source_id}")
        else:
            _atomic_bytes(input_path, content)
            _atomic_json(manifest_path, manifest)
        migrated.append(source_id)
    return {"status": "PASS", "source_count": len(migrated), "sources": migrated, "mode": "check" if check else "write"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-root", type=Path, default=DEFAULT_DEMOS)
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = migrate(args.demo_root, check=args.check)
    except (OSError, ValueError, MigrationError, v4_semantics.SemanticError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
