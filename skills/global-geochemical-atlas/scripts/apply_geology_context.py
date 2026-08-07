#!/usr/bin/env python3
"""Join independent geology-context results onto a D1 raw-observation CSV."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any


VALID_STATUSES = {
    "matched", "ambiguous", "unmatched", "failed", "not_attempted_missing_coordinate"
}
OUTPUT_FIELDS = (
    "matched_geologic_unit", "geology_map_source", "geology_map_source_id", "geology_map_version",
    "match_method", "match_scale", "boundary_distance_m", "match_uncertainty", "match_status",
    "match_candidates",
)


class GeologyJoinError(RuntimeError):
    pass


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def join(input_csv: Path, results_jsonl: Path, output_csv: Path) -> dict[str, Any]:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output_csv.parent, prefix=".geology-join-", delete=False) as handle:
        database_path = Path(handle.name)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=output_csv.parent, prefix=f".{output_csv.name}.", delete=False
    ) as handle:
        temporary_output = Path(handle.name)
    connection = sqlite3.connect(database_path)
    counts: Counter[str] = Counter()
    try:
        connection.execute(
            "CREATE TABLE results (sample_id TEXT PRIMARY KEY, payload TEXT NOT NULL, match_status TEXT NOT NULL)"
        )
        with results_jsonl.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                sample_id = _text(row.get("sample_id"))
                status = _text(row.get("match_status"))
                if not sample_id or status not in VALID_STATUSES:
                    raise GeologyJoinError(f"invalid geology result at line {line_number}")
                try:
                    connection.execute(
                        "INSERT INTO results VALUES (?, ?, ?)",
                        (sample_id, json.dumps(row, ensure_ascii=False, separators=(",", ":")), status),
                    )
                except sqlite3.IntegrityError as exc:
                    raise GeologyJoinError(f"duplicate geology result for {sample_id}") from exc
                counts[status] += 1
        connection.commit()
        missing_samples: set[str] = set()
        observation_count = 0
        with input_csv.open("r", encoding="utf-8", newline="") as source, temporary_output.open(
            "w", encoding="utf-8", newline=""
        ) as target:
            reader = csv.DictReader(source)
            if reader.fieldnames is None:
                raise GeologyJoinError("input CSV lacks a header")
            fieldnames = list(reader.fieldnames)
            for field in OUTPUT_FIELDS:
                if field not in fieldnames:
                    fieldnames.append(field)
            writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in reader:
                native_sample_id = row.get("sample_id") or row.get("source_record_id") or ""
                qualified = f"{row.get('source_id', '')}|{native_sample_id}"
                result = connection.execute("SELECT payload FROM results WHERE sample_id = ?", (qualified,)).fetchone()
                if result is None:
                    missing_samples.add(qualified)
                    continue
                context = json.loads(result[0])
                for field in OUTPUT_FIELDS:
                    value = context.get(field)
                    row[field] = (
                        json.dumps(value or [], ensure_ascii=False, separators=(",", ":"))
                        if field == "match_candidates" else _text(value)
                    )
                writer.writerow(row)
                observation_count += 1
            target.flush()
            os.fsync(target.fileno())
        if missing_samples:
            preview = ", ".join(sorted(missing_samples)[:5])
            raise GeologyJoinError(
                f"geology results are incomplete for {len(missing_samples)} samples; examples: {preview}"
            )
        os.replace(temporary_output, output_csv)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
    finally:
        connection.close()
        database_path.unlink(missing_ok=True)
    return {
        "status": "PASS",
        "observation_count": observation_count,
        "sample_status_counts": dict(sorted(counts.items())),
        "output": str(output_csv),
        "output_bytes": output_csv.stat().st_size,
        "claim_boundary": "Spatial matches are separate evidence and never overwrite source-reported geologic context.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--geology-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = join(args.input, args.geology_results, args.output)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.report:
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, sqlite3.Error, GeologyJoinError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
