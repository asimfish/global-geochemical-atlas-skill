#!/usr/bin/env python3
"""Migrate checked-in source demos to the evidence-bound V4 exchange columns."""

from __future__ import annotations

import argparse
import csv
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


def expected_fixture(
    source_id: str,
    fixture_dir: Path,
    registry: Mapping[str, Any],
) -> tuple[bytes, bytes, dict[str, Any]]:
    input_path = fixture_dir / "demo_input.csv"
    evidence_path = fixture_dir / "sources.jsonl"
    manifest_path = fixture_dir / "run_manifest.json"
    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    evidence = [json.loads(line) for line in evidence_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise MigrationError(f"{source_id} has no demo observations")
    evidence_by_record = {str(item.get("record_id") or ""): item for item in evidence}
    if len(evidence_by_record) != len(evidence):
        raise MigrationError(f"{source_id} evidence contains duplicate record IDs")
    try:
        evidence = [evidence_by_record[str(row.get("record_id") or "")] for row in rows]
    except KeyError as exc:
        raise MigrationError(f"{source_id} lacks evidence for record {exc.args[0]}") from exc
    registry_sources = registry.get("sources")
    if not isinstance(registry_sources, Mapping) or source_id not in registry_sources:
        raise MigrationError(f"{source_id} is absent from source registry")
    enriched = []
    for row, item in zip(rows, evidence, strict=True):
        migrated = v4_semantics.enrich_row(
            row,
            item,
            registry_sources[source_id],
            str(registry.get("verified_at") or ""),
        )
        enriched.append(
            {field: migrated.get(field, "") for field in generate_demo_data.INPUT_COLUMNS}
        )
        item.setdefault("license", migrated.get("license") or "")
        item.setdefault(
            "analyte_reported",
            migrated.get("analyte_reported") or migrated.get("element_or_analyte") or "",
        )
        item.setdefault("dataset_title", migrated.get("dataset_title") or "")
        item.setdefault("dataset_doi", migrated.get("dataset_doi") or None)
        item.setdefault("dataset_version", migrated.get("dataset_version") or None)
    evidence_content = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for item in evidence
    ).encode("utf-8")
    content = _csv_bytes(enriched)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["exchange_schema"] = "d1-v4-exchange-v1"
    manifest["v4_semantics_version"] = v4_semantics.SEMANTICS_VERSION
    outputs = {str(item["path"]): item for item in manifest.get("outputs", [])}
    demo_output = outputs.get("demo_input.csv")
    if not isinstance(demo_output, dict):
        raise MigrationError(f"{source_id} manifest has no demo_input.csv output")
    demo_output["bytes"] = len(content)
    evidence_output = outputs.get("sources.jsonl")
    if not isinstance(evidence_output, dict):
        raise MigrationError(f"{source_id} manifest has no sources.jsonl output")
    evidence_output["bytes"] = len(evidence_content)
    # Once a fixture manifest is rewritten under V4, retain only the readable
    # artifact identity.  Historical digest fields are neither recomputed nor
    # carried forward with a now-changed byte count.
    for output in outputs.values():
        if isinstance(output, dict):
            output.pop("sha256", None)
            output.pop("md5", None)
            output.pop("checksum", None)
    manifest["content_hashing_used"] = False
    return content, evidence_content, manifest


def migrate(demo_root: Path, *, check: bool) -> dict[str, Any]:
    registry = source_adapters.load_source_registry()
    source_ids = sorted(v4_semantics.SOURCE_CONTRACTS)
    migrated: list[str] = []
    for source_id in source_ids:
        fixture_dir = demo_root / source_id
        content, evidence_content, manifest = expected_fixture(source_id, fixture_dir, registry)
        input_path = fixture_dir / "demo_input.csv"
        evidence_path = fixture_dir / "sources.jsonl"
        manifest_path = fixture_dir / "run_manifest.json"
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        if check:
            if input_path.read_bytes() != content:
                raise MigrationError(f"stale V4 demo CSV: {source_id}")
            if evidence_path.read_bytes() != evidence_content:
                raise MigrationError(f"stale V4 evidence JSONL: {source_id}")
            if manifest_path.read_bytes() != manifest_bytes:
                raise MigrationError(f"stale V4 demo manifest: {source_id}")
        else:
            _atomic_bytes(input_path, content)
            _atomic_bytes(evidence_path, evidence_content)
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
