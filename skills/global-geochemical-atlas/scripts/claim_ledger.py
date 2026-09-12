"""Result-to-claim ledger with draft-answer cross-checking.

Two failure modes survive every deterministic pipeline check:

- a number in the final chat answer that no artifact supports (a phantom
  result), and
- a true number reported without the scope sentence that licenses it (an
  overstated claim).

This module closes both gaps with a two-stage discipline:

``build``         derive every reportable claim from the run artifacts,
                  re-verify each against its evidence file (recomputing the
                  value where possible) and grade it:

                  - ``pass``             evidence re-verified,
                  - ``warn_scope``       true only together with an explicit
                                         scope sentence,
                  - ``fail_unsupported`` evidence missing or recompute
                                         mismatch.

``render-answer`` generate canonical, evidence-bound claim lines.
``check-answer``  accept only those exact lines, including statement, typed
                  value, full scope and evidence identity. Free prose cannot
                  be certified through numeric coincidence.

The executor can build the ledger but can never edit a verdict: integrity
grades are recomputed from evidence on every invocation. A scoped claim
narrows; it must not silently widen.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

LEDGER_VERSION = "atlas-claim-ledger-v1"
LEDGER_SCHEMA = "claim-ledger.schema.json"
ANSWER_CHECK_VERSION = "atlas-answer-binding-v2"

# Scope keywords accept English or Chinese drafts (CJK spelled as escapes to
# keep this file ASCII-safe).
SCOPE_KEYWORDS = {
    "confidence": (
        "not a probability",
        "usability",
        "\u975e\u6982\u7387",  # fei gailv
        "\u4e0d\u662f\u6982\u7387",  # bushi gailv
        "\u53ef\u7528\u6027",  # keyongxing
    ),
    "anomaly_candidates": (
        "candidate",
        "\u5019\u9009",  # houxuan
    ),
    "censored_records": (
        "detection limit",
        "censored",
        "\u68c0\u51fa\u9650",  # jianchuxian
    ),
}


class LedgerError(RuntimeError):
    """Raised when the run directory cannot support a ledger at all."""


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _evidence(run_dir: Path, filename: str, pointer: str) -> dict[str, Any]:
    path = run_dir / filename
    return {
        "file": filename,
        "pointer": pointer,
        "sha256": sha256_of(path) if path.is_file() else None,
    }


def _claim(
    claim_id: str,
    statement: str,
    value: Any,
    evidence: dict[str, Any],
    *,
    recompute: dict[str, Any] | None = None,
    integrity: str = "pass",
    scope: str | None = None,
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "statement": statement,
        "value": value,
        "evidence": evidence,
        "recompute": recompute,
        "integrity": integrity,
        "scope": scope,
        "scope_keywords": list(SCOPE_KEYWORDS.get(claim_id, ())),
    }


def build_claims(run_dir: Path) -> list[dict[str, Any]]:
    run_summary = load_json(run_dir / "run_summary.json")
    if not isinstance(run_summary, dict):
        raise LedgerError("run_summary.json missing; cannot derive claims")
    metrics = run_summary.get("metrics") or {}
    coverage = run_summary.get("coverage") or {}
    rows: list[dict[str, str]] | None = None
    geochem = run_dir / "geochemistry.csv"
    if geochem.is_file():
        rows = _read_rows(geochem)

    claims: list[dict[str, Any]] = []

    # -- record count: recomputed from the shipped CSV, exact match required.
    claimed_records = metrics.get("standardized_record_count")
    recomputed_records = len(rows) if rows is not None else None
    match = recomputed_records is not None and recomputed_records == claimed_records
    claims.append(
        _claim(
            "records",
            "standardized measurement records shipped in geochemistry.csv",
            claimed_records,
            _evidence(
                run_dir, "run_summary.json", "/metrics/standardized_record_count"
            ),
            recompute={
                "method": "row count of geochemistry.csv",
                "value": recomputed_records,
                "match": match,
            },
            integrity="pass" if match else "fail_unsupported",
        )
    )

    # -- covered elements and media: claimed lists must exist in the data.
    for claim_id, column, claimed in (
        ("elements", "element_or_analyte", coverage.get("elements")),
        ("media", "medium", coverage.get("media")),
    ):
        observed = (
            sorted({row.get(column, "") for row in rows} - {""})
            if rows is not None
            else None
        )
        subset = (
            observed is not None
            and isinstance(claimed, list)
            and set(claimed) <= set(observed)
        )
        claims.append(
            _claim(
                claim_id,
                f"covered {claim_id} listed in run_summary coverage",
                claimed,
                _evidence(run_dir, "run_summary.json", f"/coverage/{claim_id}"),
                recompute={
                    "method": f"distinct {column} values in geochemistry.csv",
                    "value": observed,
                    "match": subset,
                },
                integrity="pass" if subset else "fail_unsupported",
            )
        )

    # -- coordinate rate: recomputed from latitude/longitude columns.
    claimed_rate = coverage.get("coordinate_rate")
    recomputed_rate = None
    if rows:
        located = sum(
            1
            for row in rows
            if (row.get("latitude") or "").strip()
            and (row.get("longitude") or "").strip()
        )
        recomputed_rate = round(located / len(rows), 4)
    rate_match = (
        recomputed_rate is not None
        and claimed_rate is not None
        and abs(float(claimed_rate) - recomputed_rate) <= 0.005
    )
    claims.append(
        _claim(
            "coordinate_rate",
            "fraction of records with usable coordinates",
            claimed_rate,
            _evidence(run_dir, "run_summary.json", "/coverage/coordinate_rate"),
            recompute={
                "method": "non-empty latitude and longitude fraction in geochemistry.csv",
                "value": recomputed_rate,
                "match": rate_match,
            },
            integrity="pass" if rate_match else "fail_unsupported",
        )
    )

    # -- workflow confidence: verified by quotation, licensed only with scope.
    sc = load_json(run_dir / "sources_and_confidence.json")
    if isinstance(sc, dict):
        claims.append(
            _claim(
                "confidence",
                "overall workflow confidence from sources_and_confidence.json",
                sc.get("overall_workflow_confidence"),
                _evidence(
                    run_dir,
                    "sources_and_confidence.json",
                    "/overall_workflow_confidence",
                ),
                integrity="warn_scope",
                scope=(
                    "workflow-usability signal, not a probability and not a "
                    "single quality label for the dataset"
                ),
            )
        )

    # -- anomaly candidates: cross-checked against the anomaly report,
    #    licensed only as statistical candidates.
    anomaly_report = load_json(run_dir / "anomaly_report.json")
    claimed_anomalies = metrics.get("candidate_anomaly_count")
    reported = (
        anomaly_report.get("candidate_count")
        if isinstance(anomaly_report, dict)
        else None
    )
    anomaly_match = reported is not None and reported == claimed_anomalies
    claims.append(
        _claim(
            "anomaly_candidates",
            "candidate anomalies flagged by the robust-z screen",
            claimed_anomalies,
            _evidence(run_dir, "anomaly_report.json", "/candidate_count"),
            recompute={
                "method": "candidate_count in anomaly_report.json",
                "value": reported,
                "match": anomaly_match,
            },
            integrity="warn_scope" if anomaly_match else "fail_unsupported",
            scope=(
                "statistical candidates under the documented robust-z screen, "
                "not confirmed geochemical anomalies"
            ),
        )
    )

    # -- censored records: recomputed; a nonzero count narrows the claim.
    claimed_censored = metrics.get("censored_record_count")
    recomputed_censored = (
        sum(1 for row in rows if (row.get("censored") or "").strip().lower() == "true")
        if rows is not None
        else None
    )
    censored_match = (
        recomputed_censored is not None and recomputed_censored == claimed_censored
    )
    claims.append(
        _claim(
            "censored_records",
            "records carrying a detection-limit censoring flag",
            claimed_censored,
            _evidence(run_dir, "run_summary.json", "/metrics/censored_record_count"),
            recompute={
                "method": "censored == true rows in geochemistry.csv",
                "value": recomputed_censored,
                "match": censored_match,
            },
            integrity=(
                "fail_unsupported"
                if not censored_match
                else ("warn_scope" if (claimed_censored or 0) > 0 else "pass")
            ),
            scope=(
                "summary statistics include detection-limit-censored values; "
                "report them as censored, not as measured concentrations"
            )
            if (claimed_censored or 0) > 0
            else None,
        )
    )

    # -- source count: manifest self-consistency.
    manifest = load_json(run_dir / "source_manifest.json")
    if isinstance(manifest, dict):
        declared = manifest.get("source_count")
        listed = len(manifest.get("sources") or [])
        source_match = declared == listed
        claims.append(
            _claim(
                "sources",
                "adopted sources listed in source_manifest.json",
                declared,
                _evidence(run_dir, "source_manifest.json", "/source_count"),
                recompute={
                    "method": "length of sources array",
                    "value": listed,
                    "match": source_match,
                },
                integrity="pass" if source_match else "fail_unsupported",
            )
        )

    # -- loop facts, when the run went through the self-correction loop.
    loop_report = load_json(run_dir / "loop_report.json")
    if isinstance(loop_report, dict):
        claims.append(
            _claim(
                "loop",
                "self-correction loop rounds and stop reason",
                {
                    "rounds": loop_report.get("round_count")
                    or loop_report.get("rounds_completed"),
                    "stop_reason": loop_report.get("stop_reason"),
                },
                _evidence(run_dir, "loop_report.json", "/stop_reason"),
            )
        )

    return claims


def build_ledger(run_dir: Path) -> dict[str, Any]:
    claims = build_claims(run_dir)
    summary = {
        "pass": sum(1 for c in claims if c["integrity"] == "pass"),
        "warn_scope": sum(1 for c in claims if c["integrity"] == "warn_scope"),
        "fail_unsupported": sum(
            1 for c in claims if c["integrity"] == "fail_unsupported"
        ),
    }
    return {
        "ledger_schema": LEDGER_SCHEMA,
        "ledger_version": LEDGER_VERSION,
        "run_dir": str(run_dir),
        "claims": claims,
        "summary": summary,
        "principle": (
            "every reportable number must trace to evidence; a scoped claim "
            "narrows, it must not silently widen"
        ),
    }


# ---------------------------------------------------------------------------
# Draft-answer cross-check
# ---------------------------------------------------------------------------

NUMBER_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?%?")


def canonical_claim_line(claim: dict[str, Any]) -> str:
    """Render a trusted, freshly recomputed claim, never caller-authored prose.

    JSON escaping prevents a value or source locator from introducing another
    line. The digest binds the complete typed claim, including recomputation.
    It is a content identity, not a signature or proof of scientific truth.
    """
    evidence = claim.get("evidence") or {}
    recompute = claim.get("recompute")
    if (
        claim.get("integrity") not in {"pass", "warn_scope"}
        or not isinstance(claim.get("claim_id"), str)
        or not re.fullmatch(r"[a-z_]+", claim["claim_id"])
        or not claim.get("statement")
        or claim.get("value") is None
        or not evidence.get("file")
        or not evidence.get("pointer")
        or not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("sha256", "")))
        or (recompute is not None and recompute.get("match") is not True)
        or (claim.get("integrity") == "warn_scope" and not claim.get("scope"))
    ):
        raise LedgerError("claim is unsupported or lacks binding evidence")
    canonical = json.dumps(claim, sort_keys=True, ensure_ascii=True, allow_nan=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    payload = {
        key: claim.get(key) for key in ("statement", "value", "scope", "evidence")
    }
    rendered = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False)
    return f"- [{claim['claim_id']}] {rendered} | claim_sha256={digest}"


def _answer_lines(ledger: dict[str, Any]) -> dict[str, str]:
    lines: dict[str, str] = {}
    seen: set[str] = set()
    for claim in ledger.get("claims", []):
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str):
            continue
        if claim_id in seen:
            raise LedgerError("duplicate claim identity")
        seen.add(claim_id)
        try:
            lines[canonical_claim_line(claim)] = claim_id
        except (LedgerError, ValueError):
            continue
    return lines


def render_answer(ledger: dict[str, Any]) -> str:
    lines = _answer_lines(ledger)
    if not lines:
        raise LedgerError("no supported claims to render")
    return "\n".join(lines) + "\n"


def check_answer(ledger: dict[str, Any], answer_text: str) -> dict[str, Any]:
    allowed = _answer_lines(ledger)
    phantom: list[dict[str, str]] = []
    unbound: list[dict[str, Any]] = []
    matched: list[str] = []
    scope_violations: list[dict[str, str]] = []
    for line_number, line in enumerate(answer_text.splitlines(), 1):
        if not line.strip():
            continue
        claim_id = allowed.get(line)
        if claim_id is not None and claim_id not in matched:
            matched.append(claim_id)
            continue
        unbound.append(
            {"line": line_number, "reason": "noncanonical_or_duplicate_claim"}
        )
        phantom.extend(
            {"token": m.group(), "context": line[:160]}
            for m in NUMBER_TOKEN.finditer(line)
        )
        for claim in ledger.get("claims", []):
            if (
                line.startswith(f"- [{claim.get('claim_id')}]")
                and claim.get("integrity") == "warn_scope"
            ):
                scope_violations.append(
                    {
                        "claim_id": claim["claim_id"],
                        "required_scope": claim.get("scope") or "",
                    }
                )
    if not matched and not unbound:
        unbound.append({"line": 0, "reason": "empty_answer"})
    return {
        "check_version": ANSWER_CHECK_VERSION,
        "answer_sha256": hashlib.sha256(answer_text.encode("utf-8")).hexdigest(),
        "ledger_sha256": hashlib.sha256(
            json.dumps(ledger, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest(),
        "licensed_value_count": len(allowed),
        "matched_token_count": sum(
            len(NUMBER_TOKEN.findall(line))
            for line in answer_text.splitlines()
            if line in allowed
        ),
        "matched_claim_count": len(matched),
        "matched_claim_ids": matched,
        "unbound_lines": unbound,
        "phantom_numbers": phantom,
        "scope_violations": scope_violations,
        "verdict": "answer_bound" if matched and not unbound else "answer_unbound",
        "boundary": "Only canonical claim lines are certified; no free-text semantic or scientific-truth certification.",
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=None,
        help="ledger path; defaults to <run>_audit/claim_ledger.json",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--render-answer",
        type=Path,
        help="write canonical evidence-bound answer lines to a new file",
    )
    action.add_argument(
        "--check-answer",
        type=Path,
        default=None,
        help="check exact canonical lines generated by --render-answer; free prose fails closed",
    )
    args = parser.parse_args()

    run_dir: Path = args.run_dir.resolve()
    ledger_path: Path = (
        args.ledger.resolve()
        if args.ledger
        else run_dir.parent / (run_dir.name + "_audit") / "claim_ledger.json"
    )
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        ledger = build_ledger(run_dir)
    except LedgerError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 3
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if args.render_answer is not None:
        try:
            answer = render_answer(ledger)
            with args.render_answer.open("x", encoding="utf-8") as handle:
                handle.write(answer)
        except (LedgerError, OSError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}), file=sys.stderr)
            return 3
        print(
            json.dumps({"answer": str(args.render_answer), "ledger": str(ledger_path)})
        )
        return 0

    if args.check_answer is not None:
        answer_text = args.check_answer.read_text(encoding="utf-8")
        result = check_answer(ledger, answer_text)
        result_path = ledger_path.parent / "answer_check.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "verdict": result["verdict"],
                    "phantom_count": len(result["phantom_numbers"]),
                    "scope_violation_count": len(result["scope_violations"]),
                    "ledger": str(ledger_path),
                    "answer_check": str(result_path),
                },
                ensure_ascii=False,
            )
        )
        return 0 if result["verdict"] == "answer_bound" else 1

    print(
        json.dumps(
            {
                "ledger": str(ledger_path),
                "summary": ledger["summary"],
                "claim_count": len(ledger["claims"]),
            },
            ensure_ascii=False,
        )
    )
    return 0 if ledger["summary"]["fail_unsupported"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
