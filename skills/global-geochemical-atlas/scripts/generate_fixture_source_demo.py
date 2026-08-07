#!/usr/bin/env python3
"""Generate a small canonical V4 source demo through a registered fixture adapter."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import build_v4_full_profiles as full_profiles
import generate_demo_data
import source_adapters


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent


def _atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _csv_payload(rows: Sequence[dict[str, str]]) -> bytes:
    with tempfile.TemporaryFile("w+", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=generate_demo_data.INPUT_COLUMNS, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.seek(0)
        return handle.read().encode("utf-8")


def generate(source_id: str, output_root: Path, limit: int) -> dict[str, Any]:
    registry = source_adapters.load_source_registry()
    entry = registry["sources"].get(source_id)
    if not isinstance(entry, dict):
        raise ValueError(f"unknown source: {source_id}")
    adapter = source_adapters.get_adapter(source_id)
    files = adapter.download(adapter.candidate, Path("/unused"), mode="fixture")
    rows: list[dict[str, str]] = []
    evidence_rows: list[dict[str, Any]] = []
    raw_count = 0
    for raw in adapter.parse(files):
        raw_count += 1
        for ordinal, (analyte, field_name, value, values) in enumerate(
            full_profiles._target_values(source_id, raw.fields, entry)  # noqa: SLF001
        ):
            observation = full_profiles._observation(  # noqa: SLF001
                source_id, raw, entry, str(registry.get("verified_at") or ""),
                analyte, field_name, value, values, ordinal,
            )
            row = {field: str(observation.row.get(field) or "") for field in generate_demo_data.INPUT_COLUMNS}
            evidence = full_profiles._semantic_evidence(  # noqa: SLF001
                source_id, raw.fields, str(observation.row["record_id"])
            )
            evidence.update(
                source_id=source_id,
                source_record_id=raw.source_record_id,
                source_locator=raw.source_locator,
                record_id=observation.row["record_id"],
                dataset_doi=entry.get("dataset_doi"),
                dataset_pid=entry.get("dataset_pid"),
                dataset_version=entry.get("dataset_version"),
                article_citations=[entry.get("citation")] if entry.get("citation") else [],
                article_dois=[entry.get("dataset_doi")] if entry.get("dataset_doi") else [],
            )
            rows.append(row)
            evidence_rows.append(evidence)
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break
    if not rows:
        raise ValueError(f"fixture adapter emitted no observations: {source_id}")
    csv_payload = _csv_payload(rows)
    evidence_payload = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in evidence_rows
    ).encode("utf-8")
    output_dir = output_root / source_id
    _atomic(output_dir / "demo_input.csv", csv_payload)
    _atomic(output_dir / "sources.jsonl", evidence_payload)
    manifest = {
        "demo_generation_version": "d1-generic-fixture-demo-v1",
        "exchange_schema": "d1-v4-exchange-v1",
        "v4_semantics_version": "d1-v4-source-semantics-v1",
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "data_mode": "fixture",
        "not_for_scientific_interpretation": True,
        "source": {"source_id": source_id, "dataset_version": entry.get("dataset_version")},
        "record_counts": {"raw_source_rows_read": raw_count, "emitted_observations": len(rows)},
        "outputs": [
            {"path": "demo_input.csv", "bytes": len(csv_payload)},
            {"path": "sources.jsonl", "bytes": len(evidence_payload)},
        ],
        "content_hashing_used": False,
    }
    _atomic(
        output_dir / "run_manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {"source_id": source_id, "observation_count": len(rows), "output": str(output_dir)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", action="append", required=True, dest="source_ids")
    parser.add_argument("--output-root", type=Path, default=SKILL_DIR / "fixtures" / "source-demos")
    parser.add_argument("--limit", type=int, default=48)
    args = parser.parse_args(argv)
    try:
        reports = [generate(source_id, args.output_root, args.limit) for source_id in args.source_ids]
    except (OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "PASS", "sources": reports}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
