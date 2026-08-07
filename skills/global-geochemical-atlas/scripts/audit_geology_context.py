#!/usr/bin/env python3
"""Compare Macrostrat point candidates with local carto-tile matching."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VALID_STATUSES = {
    "matched",
    "ambiguous",
    "unmatched",
    "failed",
    "not_attempted_missing_coordinate",
}


class AuditError(ValueError):
    """Raised when paired audit results are incomplete or inconsistent."""


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict) or not value.get("sample_id"):
            raise AuditError(f"{path}:{line_number} lacks sample_id")
        sample_id = str(value["sample_id"])
        if sample_id in rows:
            raise AuditError(f"duplicate sample_id in {path}: {sample_id}")
        rows[sample_id] = value
    return rows


def _read_samples(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def build_audit(samples_path: Path, point_path: Path, tile_path: Path) -> dict[str, Any]:
    samples = _read_samples(samples_path)
    points = _read_jsonl(point_path)
    tiles = _read_jsonl(tile_path)
    sample_ids = [row["sample_id"] for row in samples]
    if len(sample_ids) != len(set(sample_ids)):
        raise AuditError("audit samples contain duplicate sample_id values")
    expected = set(sample_ids)
    if set(points) != expected or set(tiles) != expected:
        raise AuditError("point and tile results must cover every audit sample exactly once")

    checks: list[dict[str, Any]] = []
    point_counts: dict[str, int] = {}
    tile_counts: dict[str, int] = {}
    consistent_tile_matches = 0
    for sample in samples:
        sample_id = sample["sample_id"]
        point = points[sample_id]
        tile = tiles[sample_id]
        for result in (point, tile):
            if result.get("match_status") not in VALID_STATUSES:
                raise AuditError(f"invalid match status for {sample_id}: {result.get('match_status')}")
            if (result.get("geologic_unit_raw") or "") != sample.get("geologic_unit_raw", ""):
                raise AuditError(f"geologic_unit_raw was not preserved for {sample_id}")
        point_status = str(point["match_status"])
        tile_status = str(tile["match_status"])
        point_counts[point_status] = point_counts.get(point_status, 0) + 1
        tile_counts[tile_status] = tile_counts.get(tile_status, 0) + 1
        candidate_source_ids = {
            str(candidate["source_id"])
            for candidate in point.get("match_candidates", [])
            if candidate.get("source_id") is not None
        }
        tile_source_id = tile.get("geology_map_source_id")
        source_consistent: bool | None = None
        if tile_status == "matched":
            source_consistent = str(tile_source_id) in candidate_source_ids
            if source_consistent:
                consistent_tile_matches += 1
        checks.append(
            {
                "sample_id": sample_id,
                "audit_type": sample.get("audit_type"),
                "region": sample.get("region"),
                "point_status": point_status,
                "point_candidate_count": len(point.get("match_candidates", [])),
                "tile_status": tile_status,
                "tile_source_id": tile_source_id,
                "tile_source_present_in_point_candidates": source_consistent,
                "source_geology_preserved": True,
            }
        )

    failed = point_counts.get("failed", 0) + tile_counts.get("failed", 0)
    matched_tiles = tile_counts.get("matched", 0)
    return {
        "audit_version": "d1-geology-context-audit-v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "sample_count": len(samples),
        "point_status_counts": point_counts,
        "tile_status_counts": tile_counts,
        "tile_matches_consistent_with_point_candidates": consistent_tile_matches,
        "tile_match_count": matched_tiles,
        "failed_lookup_count": failed,
        "status": "PASS" if failed == 0 and consistent_tile_matches == matched_tiles else "FAIL",
        "interpretation": (
            "Point mode preserves overlapping source-scale candidates. Tile mode reproduces Macrostrat's carto "
            "visualization priority locally and must retain the carto_blended uncertainty label."
        ),
        "checks": checks,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--point-results", type=Path, required=True)
    parser.add_argument("--tile-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_audit(args.samples, args.point_results, args.tile_results)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except (AuditError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({key: report[key] for key in ("status", "sample_count", "failed_lookup_count")}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
