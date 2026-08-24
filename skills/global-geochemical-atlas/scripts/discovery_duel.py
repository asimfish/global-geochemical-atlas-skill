"""Adversarial source-discovery duel: fan out for breadth, adjudicate for trust.

The gap-to-data chain (repair queue -> propose_adapter_spec -> human approval
-> declarative_adapter) admits sources one at a time, and only when somebody
happens to think of them. This module puts a scored duel in front of the
drafting step, adapted from cross-model research pipelines:

- a *scout* is explicitly encouraged to over-generate candidate sources per
  uncovered gap -- at this stage hallucination is cheap, because nothing is
  admitted on the scout's word;
- a cross-family *skeptic* attaches objections from a fixed taxonomy;
- a deterministic *referee* (this script) scores every candidate against the
  same admission axes the adapter gates will later enforce, and returns
  per-candidate verdicts with actionable revision items.

Modes:

``--mode brief``          write ``scout_brief.json`` + ``skeptic_brief.json``
                          from the repair queue's open gaps (or ``--gap``
                          overrides);
``--adjudicate C.json``   score candidates (with optional ``--objections``),
                          verdicts: ``admit_to_spec_draft`` | ``revise`` |
                          ``reject``; the duel stops when every targeted gap
                          has an admission or ``--max-rounds`` is reached.

A duel verdict can draft a spec; it can never approve one. License evidence,
hash pinning, spec-* namespacing and human approval stay exactly where they
were: the duel widens the candidate funnel, not the trust boundary.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

DUEL_VERSION = "atlas-discovery-duel-v1"
ADMIT_THRESHOLD = 7
REVISE_THRESHOLD = 4
DEFAULT_MAX_ROUNDS = 3
MAX_CANDIDATES_PER_GAP = 6

OPEN_LICENSE_HINTS = (
    "cc0",
    "cc-by",
    "cc by",
    "public domain",
    "pddl",
    "odc-by",
    "odbl",
    "government open",
    "open government",
)
TABULAR_HINTS = (
    ".csv",
    ".tsv",
    ".xlsx",
    ".parquet",
    "format=csv",
    "/api/",
    "wfs",
    "wcs",
)
OBJECTION_CLASSES = (
    "license_unclear",
    "domain_untrusted",
    "medium_mismatch",
    "region_mismatch",
    "duplicate_of_registered",
    "paywalled",
    "no_dataset_identifier",
    "method_incomparable",
)


def load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Gap extraction
# ---------------------------------------------------------------------------


def gaps_from_queue(queue: dict[str, Any]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for task in queue.get("tasks") or []:
        if task.get("status") not in (None, "pending"):
            continue
        gaps.append(
            {
                "gap_id": str(task.get("task_id") or f"gap-{len(gaps)}")[:16],
                "task_id": task.get("task_id"),
                "elements": list(task.get("required_elements") or []),
                "media": list(task.get("required_media") or []),
                "bbox": task.get("bbox"),
                "country": task.get("country_name"),
                "macroregion": task.get("macroregion"),
                "target_label": task.get("target_label"),
                "search_aliases": list(task.get("search_aliases") or [])[:6],
            }
        )
    return gaps


def gaps_from_args(specs: list[str]) -> list[dict[str, Any]]:
    gaps = []
    for index, spec in enumerate(specs):
        fields = dict(part.split("=", 1) for part in spec.split(";") if "=" in part)
        gaps.append(
            {
                "gap_id": f"manual-{index}",
                "task_id": None,
                "elements": [
                    e.strip()
                    for e in (fields.get("elements") or "").split(",")
                    if e.strip()
                ],
                "media": [
                    m.strip()
                    for m in (fields.get("medium") or "").split(",")
                    if m.strip()
                ],
                "bbox": None,
                "country": fields.get("country"),
                "macroregion": fields.get("macroregion"),
                "target_label": fields.get("label") or spec,
                "search_aliases": [],
            }
        )
    return gaps


# ---------------------------------------------------------------------------
# Briefs
# ---------------------------------------------------------------------------


def write_briefs(duel_dir: Path, gaps: list[dict[str, Any]]) -> dict[str, Any]:
    scout = {
        "brief_version": DUEL_VERSION,
        "role": "scout",
        "stance": (
            "over-generate: propose up to "
            f"{MAX_CANDIDATES_PER_GAP} candidate sources per gap; a wrong "
            "candidate costs one referee round, a missed candidate costs a "
            "blank map region"
        ),
        "gaps": gaps,
        "candidate_schema": {
            "gap_id": "gap this candidate targets (required)",
            "title": "dataset title (required)",
            "source_url": "direct https data URL (required)",
            "official_url": "landing page (recommended)",
            "license_hint": "license name as published (strongly recommended)",
            "dataset_doi": "DOI or versioned identifier if any",
            "medium": "rock|soil|sediment|water (required)",
            "region_hint": "country/region the data covers",
            "resolved_objections": "list of objection ids answered in revision rounds",
        },
        "output_file": str(duel_dir / "candidates.json"),
    }
    skeptic = {
        "brief_version": DUEL_VERSION,
        "role": "skeptic",
        "contract": {
            "model_family": "must differ from the scout's model family",
            "context": "fresh thread; sees candidates.json only",
            "stance": "attach every defensible objection; unresolved objections cost -3 each",
        },
        "objection_classes": list(OBJECTION_CLASSES),
        "objection_schema": {
            "candidate_index": "index into candidates.json (required)",
            "class": "one of objection_classes (required)",
            "detail": "one-sentence evidence-backed reason (required)",
        },
        "output_file": str(duel_dir / "objections.json"),
    }
    write_json(duel_dir / "scout_brief.json", scout)
    write_json(duel_dir / "skeptic_brief.json", skeptic)
    return {
        "scout_brief": str(duel_dir / "scout_brief.json"),
        "skeptic_brief": str(duel_dir / "skeptic_brief.json"),
        "gap_count": len(gaps),
    }


# ---------------------------------------------------------------------------
# Referee
# ---------------------------------------------------------------------------


def _gap_for(
    candidate: dict[str, Any], gaps: list[dict[str, Any]]
) -> dict[str, Any] | None:
    for gap in gaps:
        if gap["gap_id"] == candidate.get("gap_id"):
            return gap
    return None


def score_candidate(
    candidate: dict[str, Any],
    gap: dict[str, Any] | None,
    objections: list[dict[str, Any]],
) -> dict[str, Any]:
    action_items: list[str] = []
    url = str(candidate.get("source_url") or "")
    if not url.startswith("https://"):
        return {
            "verdict": "reject",
            "score": 0,
            "action_items": ["provide a direct https data URL"],
        }
    score = 0
    license_hint = str(candidate.get("license_hint") or "").lower()
    if any(hint in license_hint for hint in OPEN_LICENSE_HINTS):
        score += 3
    else:
        action_items.append(
            "confirm an open license (CC0/CC-BY family) with a quotable evidence URL"
        )
    if candidate.get("dataset_doi"):
        score += 2
    else:
        action_items.append("locate the dataset DOI or a versioned identifier")
    if gap and candidate.get("medium") in (gap.get("media") or []):
        score += 2
    elif gap:
        action_items.append(
            f"gap requires media {gap.get('media')}; candidate offers {candidate.get('medium')}"
        )
    region_hint = str(candidate.get("region_hint") or "").lower()
    region_targets = (
        [
            str(gap.get("country") or ""),
            str(gap.get("macroregion") or ""),
            *(gap.get("search_aliases") or []),
        ]
        if gap
        else []
    )
    if region_hint and any(
        target and target.lower() in region_hint for target in region_targets
    ):
        score += 2
    elif gap:
        action_items.append("state which part of the gap region the data covers")
    if any(hint in url.lower() for hint in TABULAR_HINTS):
        score += 1
    unresolved = [
        o
        for o in objections
        if not any(
            str(o.get("class")) == str(r)
            for r in candidate.get("resolved_objections") or []
        )
    ]
    score -= 3 * len(unresolved)
    if unresolved:
        action_items.extend(
            f"resolve objection [{o.get('class')}]: {o.get('detail')}"
            for o in unresolved
        )
    if score >= ADMIT_THRESHOLD:
        verdict = "admit_to_spec_draft"
    elif score >= REVISE_THRESHOLD:
        verdict = "revise"
    else:
        verdict = "reject"
    return {"verdict": verdict, "score": score, "action_items": action_items}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "candidate"


def adjudicate(
    duel_dir: Path,
    gaps: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    objections: list[dict[str, Any]],
    round_index: int,
    max_rounds: int,
    queue_path: Path | None,
) -> dict[str, Any]:
    results = []
    for index, candidate in enumerate(candidates):
        gap = _gap_for(candidate, gaps)
        mine = [o for o in objections if o.get("candidate_index") == index]
        scored = score_candidate(candidate, gap, mine)
        entry = {
            "candidate_index": index,
            "gap_id": candidate.get("gap_id"),
            "title": candidate.get("title"),
            "source_url": candidate.get("source_url"),
            **scored,
        }
        if scored["verdict"] == "admit_to_spec_draft":
            argv = [
                "python scripts/propose_adapter_spec.py",
                f"--candidate-url {candidate.get('source_url')}",
                f'--title "{candidate.get("title")}"',
                f"--medium {candidate.get('medium')}",
                "--sniff",
                f"--output adapter_proposals/spec-{_slug(str(candidate.get('title')))}.json",
            ]
            if queue_path is not None and gap and gap.get("task_id"):
                argv.insert(1, f"--from-repair-queue {queue_path}")
                argv.insert(2, f"--task-id {gap['task_id']}")
            entry["next_command"] = " ".join(argv)
        results.append(entry)

    admitted_gaps = {
        r["gap_id"] for r in results if r["verdict"] == "admit_to_spec_draft"
    }
    targeted_gaps = {c.get("gap_id") for c in candidates}
    if targeted_gaps and targeted_gaps <= admitted_gaps:
        stop_reason = "threshold_met"
    elif round_index >= max_rounds:
        stop_reason = "max_rounds_reached"
    else:
        stop_reason = None
    verdict = {
        "duel_version": DUEL_VERSION,
        "round": round_index,
        "max_rounds": max_rounds,
        "candidate_count": len(candidates),
        "admitted": sum(1 for r in results if r["verdict"] == "admit_to_spec_draft"),
        "revise": sum(1 for r in results if r["verdict"] == "revise"),
        "rejected": sum(1 for r in results if r["verdict"] == "reject"),
        "stop_reason": stop_reason,
        "results": results,
        "boundary": (
            "a duel verdict can draft a spec, it can never approve one: "
            "license evidence, hash pinning and human approval are unchanged"
        ),
    }
    write_json(duel_dir / f"duel_verdict_round{round_index}.json", verdict)
    state = load_json(duel_dir / "duel_state.json") or {
        "duel_version": DUEL_VERSION,
        "rounds": [],
    }
    state["rounds"] = [r for r in state["rounds"] if r.get("round") != round_index]
    state["rounds"].append(
        {
            "round": round_index,
            "admitted": verdict["admitted"],
            "revise": verdict["revise"],
            "rejected": verdict["rejected"],
        }
    )
    state["stop_reason"] = stop_reason
    write_json(duel_dir / "duel_state.json", state)
    return verdict


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duel-dir", type=Path, default=None)
    parser.add_argument("--mode", choices=("brief", "adjudicate"), default="brief")
    parser.add_argument("--candidates", type=Path, default=None)
    parser.add_argument("--objections", type=Path, default=None)
    parser.add_argument("--round", type=int, default=None)
    parser.add_argument("--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    parser.add_argument(
        "--gap",
        action="append",
        default=[],
        help='manual gap, e.g. "medium=soil;country=Mongolia;elements=As,Cd"',
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir.resolve()
    duel_dir: Path = (
        args.duel_dir.resolve()
        if args.duel_dir
        else output_dir.parent / (output_dir.name + "_duel")
    )
    queue_path = output_dir / "d1_repair_queue.json"
    queue = load_json(queue_path)
    gaps = gaps_from_queue(queue) if isinstance(queue, dict) else []
    gaps.extend(gaps_from_args(args.gap))
    if not gaps:
        print(json.dumps({"error": "no open gaps in repair queue and no --gap given"}))
        return 2

    if args.mode == "brief":
        summary = write_briefs(duel_dir, gaps)
        print(json.dumps({"status": "briefs_written", **summary}, ensure_ascii=False))
        return 0

    if args.candidates is None:
        parser.error("--mode adjudicate requires --candidates")
    candidates = load_json(args.candidates) or []
    if isinstance(candidates, dict):
        candidates = candidates.get("candidates", [])
    objections = load_json(args.objections) if args.objections else []
    if isinstance(objections, dict):
        objections = objections.get("objections", [])
    state = load_json(duel_dir / "duel_state.json") or {"rounds": []}
    round_index = args.round or (len(state["rounds"]) + 1)
    verdict = adjudicate(
        duel_dir,
        gaps,
        candidates,
        objections or [],
        round_index,
        args.max_rounds,
        queue_path if queue_path.is_file() else None,
    )
    print(
        json.dumps(
            {
                "round": verdict["round"],
                "admitted": verdict["admitted"],
                "revise": verdict["revise"],
                "rejected": verdict["rejected"],
                "stop_reason": verdict["stop_reason"],
                "verdict_file": str(duel_dir / f"duel_verdict_round{round_index}.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0 if verdict["admitted"] else 1


if __name__ == "__main__":
    sys.exit(main())
