#!/usr/bin/env python3
"""Find exact-upstream and possible cross-source duplicates without merging rows."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sqlite3
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class DuplicateAuditError(RuntimeError):
    """Raised when a duplicate audit input cannot be interpreted safely."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _coordinate(value: Any) -> str:
    try:
        number = float(_text(value))
    except ValueError:
        return ""
    return f"{number:.5f}" if math.isfinite(number) else ""


def exact_natural_key(row: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Return an upstream-backed natural key or None when evidence is too weak."""

    upstream = _text(row.get("upstream_primary_source_id"))
    publication = _text(row.get("publication_doi"))
    sample = _text(row.get("sample_id")) or _text(row.get("source_record_id"))
    analyte = _text(row.get("element_or_analyte"))
    if not sample or not analyte or not (upstream or publication):
        return None
    return (
        upstream or publication,
        sample,
        analyte,
        _text(row.get("analytical_method")) or _text(row.get("analytical_technique")),
        _text(row.get("measurement_basis")),
        _text(row.get("value")),
        _text(row.get("unit")),
        _text(row.get("value_qualifier")),
    )


def possible_natural_key(row: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Return a conservative near-duplicate key; matches remain review-only."""

    latitude = _coordinate(row.get("latitude"))
    longitude = _coordinate(row.get("longitude"))
    analyte = _text(row.get("element_or_analyte"))
    medium = _text(row.get("medium"))
    if not latitude or not longitude or not analyte or not medium:
        return None
    return (
        latitude,
        longitude,
        _text(row.get("sampled_at")),
        medium,
        _text(row.get("sample_type")),
        _text(row.get("lithology")) or _text(row.get("lithology_raw")),
        analyte,
        _text(row.get("value")),
        _text(row.get("unit")),
    )


def _key_text(key: tuple[str, ...] | None) -> str | None:
    return json.dumps(key, ensure_ascii=False, separators=(",", ":")) if key else None


def audit(input_csv: Path, output_jsonl: Path) -> dict[str, Any]:
    if not input_csv.is_file():
        raise DuplicateAuditError(f"input CSV does not exist: {input_csv}")
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect("")
    database.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE candidates(
          row_number INTEGER NOT NULL,
          record_id TEXT NOT NULL,
          source_id TEXT NOT NULL,
          source_locator TEXT NOT NULL,
          exact_key TEXT,
          possible_key TEXT
        );
        CREATE INDEX idx_candidates_exact ON candidates(exact_key, source_id);
        CREATE INDEX idx_candidates_possible ON candidates(possible_key, source_id);
        """
    )
    row_count = 0
    batch: list[tuple[Any, ...]] = []
    with input_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"record_id", "source_id", "source_locator", "element_or_analyte", "value", "unit"}
        missing = sorted(required - set(reader.fieldnames or []))
        if missing:
            raise DuplicateAuditError("input CSV lacks fields: " + ", ".join(missing))
        for row_number, row in enumerate(reader, start=2):
            row_count += 1
            batch.append(
                (
                    row_number,
                    _text(row.get("record_id")),
                    _text(row.get("source_id")),
                    _text(row.get("source_locator")),
                    _key_text(exact_natural_key(row)),
                    _key_text(possible_natural_key(row)),
                )
            )
            if len(batch) >= 20_000:
                database.executemany("INSERT INTO candidates VALUES (?,?,?,?,?,?)", batch)
                batch.clear()
        if batch:
            database.executemany("INSERT INTO candidates VALUES (?,?,?,?,?,?)", batch)
    exact_keys = [
        row[0]
        for row in database.execute(
            "SELECT exact_key FROM candidates WHERE exact_key IS NOT NULL "
            "GROUP BY exact_key HAVING COUNT(DISTINCT source_id) > 1 ORDER BY exact_key"
        )
    ]
    exact_key_set = set(exact_keys)
    possible_keys = [
        row[0]
        for row in database.execute(
            "SELECT possible_key FROM candidates WHERE possible_key IS NOT NULL "
            "GROUP BY possible_key HAVING COUNT(DISTINCT source_id) > 1 ORDER BY possible_key"
        )
    ]
    exact_records = 0
    possible_records = 0
    emitted_possible_groups = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=output_jsonl.parent, delete=False) as handle:
        temporary = Path(handle.name)
        for prefix, keys in (("exact", exact_keys), ("possible", possible_keys)):
            for ordinal, key in enumerate(keys, start=1):
                if prefix == "possible":
                    group_exact_keys = {
                        row[0]
                        for row in database.execute(
                            "SELECT DISTINCT exact_key FROM candidates WHERE possible_key=? AND exact_key IS NOT NULL",
                            (key,),
                        )
                    }
                    if group_exact_keys & exact_key_set:
                        continue
                rows = [
                    {"row_number": row[0], "record_id": row[1], "source_id": row[2], "source_locator": row[3]}
                    for row in database.execute(
                        f"SELECT row_number, record_id, source_id, source_locator FROM candidates "
                        f"WHERE {prefix}_key=? ORDER BY source_id, record_id",
                        (key,),
                    )
                ]
                if prefix == "exact":
                    exact_records += len(rows)
                else:
                    emitted_possible_groups += 1
                    possible_records += len(rows)
                handle.write(
                    json.dumps(
                        {
                            "duplicate_group_id": f"{prefix}-{ordinal:07d}",
                            "classification": "exact_upstream_duplicate" if prefix == "exact" else "possible_duplicate",
                            "natural_key": json.loads(key),
                            "records": rows,
                            "automatic_merge_allowed": False,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
    os.replace(temporary, output_jsonl)
    database.close()
    return {
        "audit_version": "d1-cross-source-duplicate-audit-v1",
        "status": "PASS",
        "input_record_count": row_count,
        "exact_group_count": len(exact_keys),
        "exact_record_count": exact_records,
        "possible_group_count": emitted_possible_groups,
        "possible_record_count": possible_records,
        "output": str(output_jsonl),
        "automatic_merge_performed": False,
        "claim_boundary": "Possible duplicates are candidates only; no source evidence or observation was removed.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = audit(args.input, args.output)
    except (OSError, sqlite3.Error, DuplicateAuditError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
