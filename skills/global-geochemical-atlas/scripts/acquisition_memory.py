"""Cross-run acquisition memory: spiral learning instead of starting blind.

The self-correction loop already reprioritises sources between rounds inside
one run (``next_round_priority_source_ids``). What it forgets is everything
between runs: a source that delivered ten thousand records yesterday and a
source that returned HTTP 403 three times both start from the same neutral
position today.

This module keeps a small, auditable memory file across runs:

``update``  harvest one finished run directory into the memory file --
            adopted sources from ``source_manifest.json`` count as
            successes, entries in the acquisition manifest ``failures``
            array count as failures;
``advise``  given a frozen request, emit first-round scheduling advice:
            proven sources matching the requested media become
            ``priority_source_ids`` and repeat offenders (two or more
            consecutive failures, never adopted) become a ``banlist`` with
            explicit reasons.

Advice never widens the acquisition surface: it only reorders the sources
the skill already routes, so the immutable-skill boundary of the loop is
preserved. Failed attempts are the most valuable memory; validated sources
are the foundations of the next run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

MEMORY_VERSION = "atlas-acquisition-memory-v1"
BAN_FAIL_STREAK = 2
DEFAULT_MAX_PRIORITIES = 4


def load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _empty_memory() -> dict[str, Any]:
    return {
        "memory_version": MEMORY_VERSION,
        "runs_recorded": 0,
        "updated_at": None,
        "sources": {},
    }


def _entry(sources: dict[str, Any], source_id: str) -> dict[str, Any]:
    return sources.setdefault(
        source_id,
        {
            "ok_runs": 0,
            "fail_runs": 0,
            "fail_streak": 0,
            "total_records": 0,
            "media": [],
            "last_outcome": None,
            "last_seen": None,
        },
    )


def _harvest_successes(run_dir: Path, sources: dict[str, Any], now: str) -> int:
    manifest = load_json(run_dir / "source_manifest.json")
    sc = load_json(run_dir / "sources_and_confidence.json")
    media_by_source: dict[str, list[str]] = {}
    if isinstance(sc, dict):
        for source in sc.get("sources") or []:
            counts = source.get("medium_record_counts") or {}
            media_by_source[str(source.get("source_id"))] = sorted(counts)
    harvested = 0
    if isinstance(manifest, dict):
        for source in manifest.get("sources") or []:
            source_id = str(source.get("source_id") or "")
            if not source_id:
                continue
            entry = _entry(sources, source_id)
            entry["ok_runs"] += 1
            entry["fail_streak"] = 0
            entry["total_records"] += int(source.get("record_count") or 0)
            entry["media"] = sorted(
                set(entry["media"]) | set(media_by_source.get(source_id, []))
            )
            entry["last_outcome"] = "adopted"
            entry["last_seen"] = now
            harvested += 1
    return harvested


def _harvest_failures(run_dir: Path, sources: dict[str, Any], now: str) -> int:
    harvested = 0
    for manifest_path in (
        run_dir / "request_evidence" / "acquisition" / "request_manifest.json",
        run_dir / "request_evidence" / "acquisition" / "parent_manifest.json",
    ):
        manifest = load_json(manifest_path)
        if not isinstance(manifest, dict):
            continue
        for failure in manifest.get("failures") or []:
            source_id = str(failure.get("source_id") or "")
            if not source_id:
                continue
            entry = _entry(sources, source_id)
            entry["fail_runs"] += 1
            entry["fail_streak"] += 1
            entry["last_outcome"] = "error:" + str(
                failure.get("status") or failure.get("error") or "unknown"
            )
            entry["last_seen"] = now
            harvested += 1
    return harvested


def update_memory(memory_path: Path, run_dir: Path) -> dict[str, Any]:
    memory = load_json(memory_path) or _empty_memory()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sources = memory["sources"]
    ok = _harvest_successes(run_dir, sources, now)
    failed = _harvest_failures(run_dir, sources, now)
    memory["runs_recorded"] += 1
    memory["updated_at"] = now
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {
        "memory_file": str(memory_path),
        "sources_harvested_ok": ok,
        "failures_harvested": failed,
        "known_sources": len(sources),
        "runs_recorded": memory["runs_recorded"],
    }


def advise(
    memory_path: Path, request_path: Path, max_priorities: int
) -> dict[str, Any]:
    memory = load_json(memory_path) or _empty_memory()
    request = load_json(request_path) or {}
    requested_media = set(request.get("media") or [])

    proven: list[tuple[int, int, str]] = []
    banlist: list[dict[str, str]] = []
    for source_id, entry in memory["sources"].items():
        if entry["ok_runs"] > 0:
            media = set(entry.get("media") or [])
            if requested_media and media and not (requested_media & media):
                continue
            proven.append((entry["ok_runs"], entry["total_records"], source_id))
        elif entry["fail_streak"] >= BAN_FAIL_STREAK:
            banlist.append(
                {
                    "source_id": source_id,
                    "reason": (
                        f"{entry['fail_streak']} consecutive failures, never "
                        f"adopted; last outcome {entry['last_outcome']}"
                    ),
                }
            )
    proven.sort(reverse=True)
    return {
        "advice_version": MEMORY_VERSION,
        "memory_file": str(memory_path),
        "runs_recorded": memory["runs_recorded"],
        "priority_source_ids": [sid for _, _, sid in proven[:max_priorities]],
        "banlist": banlist,
        "boundary": (
            "advice only reorders sources the skill already routes; it never "
            "adds an unrouted source and the banlist is advisory, not a gate"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("update", "advise"))
    parser.add_argument("--memory-file", required=True, type=Path)
    parser.add_argument("--run-dir", type=Path, help="finished run directory (update)")
    parser.add_argument("--request", type=Path, help="frozen request JSON (advise)")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-priorities", type=int, default=DEFAULT_MAX_PRIORITIES)
    args = parser.parse_args()

    if args.mode == "update":
        if args.run_dir is None:
            parser.error("update requires --run-dir")
        result = update_memory(args.memory_file.resolve(), args.run_dir.resolve())
    else:
        if args.request is None:
            parser.error("advise requires --request")
        result = advise(
            args.memory_file.resolve(), args.request.resolve(), args.max_priorities
        )

    payload = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
