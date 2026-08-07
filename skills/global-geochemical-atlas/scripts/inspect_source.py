#!/usr/bin/env python3
"""Inspect one registered source without performing D2 scientific normalization."""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from source_adapters import ADAPTERS, SourceAdapterError, get_adapter


def inspect_source(source_id: str, cache_dir: Path, mode: str, sample_records: int) -> dict[str, Any]:
    adapter = get_adapter(source_id)
    candidates = adapter.discover({"sources": [source_id]})
    if len(candidates) != 1:
        raise SourceAdapterError(f"expected exactly one registered candidate for {source_id}")
    candidate = candidates[0]
    downloaded = adapter.download(candidate, cache_dir, mode=mode)  # type: ignore[arg-type]
    records = list(itertools.islice(adapter.parse(downloaded), sample_records))
    field_presence: Counter[str] = Counter()
    for record in records:
        field_presence.update(key for key, value in record.fields.items() if value not in (None, "", [], {}))
    return {
        "status": "success",
        "source_id": source_id,
        "title": candidate.title,
        "dataset_doi": candidate.dataset_doi,
        "dataset_version": candidate.version,
        "license": candidate.license_id,
        "mode": mode,
        "downloaded_files": [
            {
                "file_id": item.file_id,
                "filename": item.path.name,
                "bytes": item.bytes,
                "cache_status": item.cache_status,
            }
            for item in downloaded
        ],
        "sampled_record_count": len(records),
        "sample_limit": sample_records,
        "sample_source_locators": [item.source_locator for item in records[:5]],
        "sample_field_presence": dict(sorted(field_presence.items())),
        "scientific_boundary": "Source-native inspection only; no unit normalization, QC or anomaly decision was applied.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, choices=sorted(ADAPTERS))
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("online", "cached"), default="cached")
    parser.add_argument("--sample-records", type=int, default=20)
    parser.add_argument("--output", type=Path, help="Optional JSON report; stdout is always printed")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.sample_records < 1 or args.sample_records > 1000:
        print("inspect_source: --sample-records must be between 1 and 1000", file=sys.stderr)
        return 2
    try:
        report = inspect_source(args.source, args.cache_dir, args.mode, args.sample_records)
    except (SourceAdapterError, OSError, ValueError) as exc:
        print(f"inspect_source: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
