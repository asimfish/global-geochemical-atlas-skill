#!/usr/bin/env python3
"""Content-addressed, role-isolated adversarial source audit protocol.

The module does not pretend that Python code is an independent language model.
It prepares two deliberately different, allowlisted workspaces for fresh scout
and challenger invocations, validates their result envelopes, and lets a
deterministic judge score only frozen source facts.  Previous-round memory may
choose which gap to audit, but is never serialized into either evaluator packet.

No agent result can admit a source.  A passing score creates an integration
draft that still requires normal D1 evidence gates and explicit human approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

PROTOCOL_VERSION = "gga-adversarial-source-audit-v1"
PACKET_VERSION = "gga-agent-role-packet-v1"
RESULT_VERSION = "gga-agent-role-result-v1"
JUDGE_VERSION = "gga-deterministic-source-judge-v1"
ROLES = ("scout", "challenger")
FACT_DIMENSIONS = (
    "official_identity",
    "machine_access",
    "research_use_license",
    "version_and_integrity",
    "region_relevance",
    "medium_relevance",
    "record_locator",
)
DIMENSION_WEIGHTS = {
    "official_identity": 2,
    "machine_access": 2,
    "research_use_license": 2,
    "version_and_integrity": 1,
    "region_relevance": 1,
    "medium_relevance": 1,
    "record_locator": 1,
}


class AgentAuditError(RuntimeError):
    """Raised when an audit bundle violates an isolation or integrity rule."""


class AgentRoleBackend(Protocol):
    """Model-neutral boundary implemented by a Codex/OpenCode/other host.

    The host MUST start a fresh session whose only readable task material is the
    supplied workspace and write a JSON payload.  The protocol deliberately has
    no provider credential or accumulated-conversation parameter.
    """

    def run(self, *, role: str, workspace: Path, result_path: Path) -> None: ...


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentAuditError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AgentAuditError(f"{path} must contain a JSON object")
    return value


def _clean_string(value: Any, field: str, maximum: int = 4000) -> str:
    text = str(value or "").strip()
    if not text or len(text) > maximum or "\x00" in text:
        raise AgentAuditError(f"{field} must be 1..{maximum} safe characters")
    return text


def _validate_source_facts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise AgentAuditError("source_facts must be a non-empty array")
    if len(value) > 200:
        raise AgentAuditError("source_facts exceeds the 200-candidate audit limit")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise AgentAuditError(f"source_facts[{index}] must be an object")
        source_id = _clean_string(
            raw.get("source_id"), f"source_facts[{index}].source_id", 160
        )
        if source_id in seen:
            raise AgentAuditError(f"duplicate source_id: {source_id}")
        seen.add(source_id)
        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, Mapping):
            raise AgentAuditError(f"{source_id}.dimensions must be an object")
        normalized_dimensions: dict[str, bool | None] = {}
        for dimension in FACT_DIMENSIONS:
            fact = dimensions.get(dimension)
            if fact is not None and not isinstance(fact, bool):
                raise AgentAuditError(
                    f"{source_id}.dimensions.{dimension} must be true, false or null"
                )
            normalized_dimensions[dimension] = fact
        locators = raw.get("evidence_locators")
        if not isinstance(locators, Mapping):
            raise AgentAuditError(f"{source_id}.evidence_locators must be an object")
        normalized_locators = {
            str(key): _clean_string(item, f"{source_id}.evidence_locators.{key}", 2000)
            for key, item in sorted(locators.items())
            if str(key) in FACT_DIMENSIONS
        }
        validated.append(
            {
                "source_id": source_id,
                "title": _clean_string(raw.get("title"), f"{source_id}.title", 500),
                "official_url": _clean_string(
                    raw.get("official_url"), f"{source_id}.official_url", 2000
                ),
                "dimensions": normalized_dimensions,
                "evidence_locators": normalized_locators,
            }
        )
    return sorted(validated, key=lambda item: item["source_id"])


def _packet(role: str, round_id: str, context: Mapping[str, Any]) -> dict[str, Any]:
    if role not in ROLES:
        raise AgentAuditError(f"unsupported role: {role}")
    context_hash = sha256_bytes(canonical_json_bytes(context))
    packet_without_hash = {
        "schema_version": PACKET_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "round_id": round_id,
        "role": role,
        "fresh_session_required": True,
        "previous_memory_allowed": False,
        "previous_review_allowed": False,
        "hidden_scratch_allowed": False,
        "allowed_inputs": {"context": context_hash},
        "context": context,
        "output_contract": {
            "scout": {
                "required": ["candidate_ids", "evidence_requests"],
                "forbidden": ["score", "admit", "final_verdict"],
            },
            "challenger": {
                "required": ["challenges", "unresolved_dimensions"],
                "forbidden": ["score", "admit", "final_verdict"],
            },
        }[role],
    }
    return {
        **packet_without_hash,
        "packet_sha256": sha256_bytes(canonical_json_bytes(packet_without_hash)),
    }


def prepare_audit_round(
    output_dir: Path,
    *,
    round_id: str,
    gap: Mapping[str, Any],
    source_facts: Sequence[Mapping[str, Any]],
    rubric: Mapping[str, Any] | None = None,
    prior_memory: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create two immutable role workspaces from current-round facts only.

    ``prior_memory`` is fingerprinted in the outer selection receipt so use of
    memory remains auditable.  Its content is intentionally excluded from both
    packets; this is the mechanically tested cross-round independence boundary.
    """

    if output_dir.exists():
        raise AgentAuditError(f"audit output already exists: {output_dir}")
    round_id = _clean_string(round_id, "round_id", 160)
    clean_gap = json.loads(canonical_json_bytes(dict(gap)))
    clean_facts = _validate_source_facts(list(source_facts))
    clean_rubric = {
        "dimensions": list(FACT_DIMENSIONS),
        "weights": dict(DIMENSION_WEIGHTS),
        "thresholds": {"integration_draft": 7, "supplement": 4, "reject": 0},
        "human_approval_required": True,
        **dict(rubric or {}),
    }
    frozen = {
        "schema_version": "gga-source-audit-frozen-facts-v1",
        "round_id": round_id,
        "gap": clean_gap,
        "source_facts": clean_facts,
        "rubric": clean_rubric,
    }
    frozen_sha256 = sha256_bytes(canonical_json_bytes(frozen))
    scout_context = {
        "task": "Nominate relevant source IDs and list missing evidence; do not score or admit.",
        "gap": clean_gap,
        "source_facts": clean_facts,
    }
    challenger_context = {
        "task": (
            "Challenge the frozen candidates on identity, access, license, version, "
            "region, medium and record locators; do not score or admit."
        ),
        "gap": clean_gap,
        "candidate_facts": clean_facts,
        "rubric_dimensions": list(FACT_DIMENSIONS),
    }
    packets = {
        "scout": _packet("scout", round_id, scout_context),
        "challenger": _packet("challenger", round_id, challenger_context),
    }
    output_dir.mkdir(parents=True)
    _write_json(output_dir / "frozen_facts.json", frozen)
    for role, packet in packets.items():
        workspace = output_dir / "roles" / role / "input"
        workspace.mkdir(parents=True)
        _write_json(workspace / "packet.json", packet)
    selection_receipt = {
        "schema_version": "gga-audit-selection-receipt-v1",
        "round_id": round_id,
        "frozen_facts_sha256": frozen_sha256,
        "prior_memory_sha256": (
            sha256_bytes(canonical_json_bytes(prior_memory))
            if prior_memory is not None
            else None
        ),
        "memory_effect": "gap_selection_only_not_serialized_into_role_packets",
        "role_packet_sha256": {
            role: packet["packet_sha256"] for role, packet in packets.items()
        },
    }
    _write_json(output_dir / "selection_receipt.json", selection_receipt)
    return selection_receipt


def create_result_envelope(
    audit_dir: Path,
    *,
    role: str,
    invocation_id: str,
    model_family: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and bind one fresh role result to exactly one input packet."""

    if role not in ROLES:
        raise AgentAuditError(f"unsupported role: {role}")
    invocation_id = _clean_string(invocation_id, "invocation_id", 200)
    model_family = _clean_string(model_family, "model_family", 200)
    result_dir = audit_dir / "roles" / role / "result"
    if result_dir.exists():
        raise AgentAuditError(f"{role} already submitted a result")
    other_role = next(item for item in ROLES if item != role)
    other_path = audit_dir / "roles" / other_role / "result" / "envelope.json"
    if other_path.is_file():
        other = _read_object(other_path)
        if other.get("invocation_id") == invocation_id:
            raise AgentAuditError("invocation_id reuse across roles is forbidden")
    packet_path = audit_dir / "roles" / role / "input" / "packet.json"
    packet = _read_object(packet_path)
    validate_packet(packet, expected_role=role)
    clean_payload = json.loads(canonical_json_bytes(dict(payload)))
    payload_sha256 = sha256_bytes(canonical_json_bytes(clean_payload))
    envelope_without_hash = {
        "schema_version": RESULT_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "round_id": packet["round_id"],
        "role": role,
        "invocation_id": invocation_id,
        "model_family": model_family,
        "packet_sha256": packet["packet_sha256"],
        "input_hashes": packet["allowed_inputs"],
        "payload_sha256": payload_sha256,
        "payload": clean_payload,
    }
    envelope = {
        **envelope_without_hash,
        "result_sha256": sha256_bytes(canonical_json_bytes(envelope_without_hash)),
    }
    _write_json(result_dir / "envelope.json", envelope)
    return envelope


def validate_packet(packet: Mapping[str, Any], *, expected_role: str) -> None:
    if packet.get("schema_version") != PACKET_VERSION:
        raise AgentAuditError("unsupported role packet version")
    if packet.get("role") != expected_role:
        raise AgentAuditError("role packet substitution detected")
    if packet.get("previous_memory_allowed") is not False:
        raise AgentAuditError("role packet permits previous memory")
    if packet.get("previous_review_allowed") is not False:
        raise AgentAuditError("role packet permits previous review")
    context = packet.get("context")
    allowed = packet.get("allowed_inputs")
    if not isinstance(context, Mapping) or not isinstance(allowed, Mapping):
        raise AgentAuditError("role packet lacks context bindings")
    if set(allowed) != {"context"}:
        raise AgentAuditError("role packet contains an unknown input binding")
    if allowed.get("context") != sha256_bytes(canonical_json_bytes(context)):
        raise AgentAuditError("role context hash mismatch")
    unsigned = dict(packet)
    expected = unsigned.pop("packet_sha256", None)
    if expected != sha256_bytes(canonical_json_bytes(unsigned)):
        raise AgentAuditError("role packet hash mismatch")


def validate_result_envelope(
    envelope: Mapping[str, Any], packet: Mapping[str, Any], *, expected_role: str
) -> None:
    validate_packet(packet, expected_role=expected_role)
    if envelope.get("schema_version") != RESULT_VERSION:
        raise AgentAuditError("unsupported result envelope version")
    if envelope.get("role") != expected_role or envelope.get("round_id") != packet.get(
        "round_id"
    ):
        raise AgentAuditError("result role or round substitution detected")
    if envelope.get("packet_sha256") != packet.get("packet_sha256"):
        raise AgentAuditError("result came from the wrong role packet")
    if envelope.get("input_hashes") != packet.get("allowed_inputs"):
        raise AgentAuditError("result declared unknown or changed inputs")
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise AgentAuditError("result payload must be an object")
    if envelope.get("payload_sha256") != sha256_bytes(canonical_json_bytes(payload)):
        raise AgentAuditError("result payload hash mismatch")
    unsigned = dict(envelope)
    expected = unsigned.pop("result_sha256", None)
    if expected != sha256_bytes(canonical_json_bytes(unsigned)):
        raise AgentAuditError("result envelope hash mismatch")


def deterministic_judge(audit_dir: Path) -> dict[str, Any]:
    """Score frozen facts after validating independently bound role outputs."""

    frozen = _read_object(audit_dir / "frozen_facts.json")
    selection = _read_object(audit_dir / "selection_receipt.json")
    if selection.get("frozen_facts_sha256") != sha256_bytes(
        canonical_json_bytes(frozen)
    ):
        raise AgentAuditError("frozen source facts hash mismatch")
    envelopes: dict[str, dict[str, Any]] = {}
    for role in ROLES:
        packet = _read_object(audit_dir / "roles" / role / "input" / "packet.json")
        envelope = _read_object(audit_dir / "roles" / role / "result" / "envelope.json")
        validate_result_envelope(envelope, packet, expected_role=role)
        if selection.get("role_packet_sha256", {}).get(role) != packet.get(
            "packet_sha256"
        ):
            raise AgentAuditError("selection receipt packet hash mismatch")
        envelopes[role] = envelope
    if envelopes["scout"]["invocation_id"] == envelopes["challenger"]["invocation_id"]:
        raise AgentAuditError("invocation_id reuse across roles is forbidden")

    scout_payload = envelopes["scout"]["payload"]
    candidate_ids = scout_payload.get("candidate_ids")
    if not isinstance(candidate_ids, list) or any(
        not isinstance(item, str) for item in candidate_ids
    ):
        raise AgentAuditError("scout result must contain candidate_ids strings")
    frozen_by_id = {item["source_id"]: item for item in frozen.get("source_facts", [])}
    if not set(candidate_ids).issubset(frozen_by_id):
        raise AgentAuditError("scout nominated a source absent from frozen facts")

    challenge_payload = envelopes["challenger"]["payload"]
    challenges = challenge_payload.get("challenges")
    if not isinstance(challenges, list):
        raise AgentAuditError("challenger result must contain challenges array")
    unresolved_by_source: dict[str, set[str]] = {}
    for index, raw in enumerate(challenges):
        if not isinstance(raw, Mapping):
            raise AgentAuditError(f"challenge {index} must be an object")
        source_id = str(raw.get("source_id") or "")
        dimension = str(raw.get("dimension") or "")
        if source_id not in frozen_by_id or dimension not in FACT_DIMENSIONS:
            raise AgentAuditError("challenge references an unknown source or dimension")
        unresolved_by_source.setdefault(source_id, set()).add(dimension)

    decisions: list[dict[str, Any]] = []
    for source_id in sorted(set(candidate_ids)):
        facts = frozen_by_id[source_id]
        dimensions = facts["dimensions"]
        score = sum(
            DIMENSION_WEIGHTS[name]
            for name in FACT_DIMENSIONS
            if dimensions.get(name) is True
        )
        deterministic_gaps = [
            name for name in FACT_DIMENSIONS if dimensions.get(name) is not True
        ]
        unresolved = sorted(unresolved_by_source.get(source_id, set()))
        if score >= 7:
            route = "integration_draft"
        elif score >= 4:
            route = "supplement_evidence"
        else:
            route = "reject_candidate"
        decisions.append(
            {
                "source_id": source_id,
                "score": score,
                "maximum_score": sum(DIMENSION_WEIGHTS.values()),
                "route": route,
                "deterministic_gaps": deterministic_gaps,
                "challenger_unresolved_dimensions": unresolved,
                "human_review_required": True,
                "admitted": False,
            }
        )

    same_family = (
        envelopes["scout"]["model_family"] == envelopes["challenger"]["model_family"]
    )
    receipt_without_hash = {
        "schema_version": JUDGE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "round_id": frozen.get("round_id"),
        "frozen_facts_sha256": selection["frozen_facts_sha256"],
        "role_results": {
            role: {
                "invocation_id": envelopes[role]["invocation_id"],
                "model_family": envelopes[role]["model_family"],
                "packet_sha256": envelopes[role]["packet_sha256"],
                "result_sha256": envelopes[role]["result_sha256"],
            }
            for role in ROLES
        },
        "cross_model_status": "provisional_same_family"
        if same_family
        else "cross_family",
        "decisions": decisions,
        "final_admission_authority": "D1 deterministic gates plus human approval",
        "claim_boundary": (
            "Scores are recomputed from frozen boolean evidence facts. Agent prose and "
            "agent-authored scores cannot admit a source or establish scientific truth."
        ),
    }
    receipt = {
        **receipt_without_hash,
        "judge_receipt_sha256": sha256_bytes(
            canonical_json_bytes(receipt_without_hash)
        ),
    }
    _write_json(audit_dir / "judge_receipt.json", receipt)
    return receipt


def _load_list(path: Path, key: str) -> list[dict[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(value, Mapping):
        value = value.get(key)
    if not isinstance(value, list):
        raise AgentAuditError(f"{path} must contain an array or {key} array")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument("--round-id", required=True)
    prepare.add_argument("--gap", type=Path, required=True)
    prepare.add_argument("--source-facts", type=Path, required=True)
    prepare.add_argument("--prior-memory", type=Path)
    submit = sub.add_parser("submit")
    submit.add_argument("--audit-dir", type=Path, required=True)
    submit.add_argument("--role", choices=ROLES, required=True)
    submit.add_argument("--invocation-id", required=True)
    submit.add_argument("--model-family", required=True)
    submit.add_argument("--payload", type=Path, required=True)
    judge = sub.add_parser("judge")
    judge.add_argument("--audit-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            gap = _read_object(args.gap)
            memory = _read_object(args.prior_memory) if args.prior_memory else None
            result = prepare_audit_round(
                args.output_dir,
                round_id=args.round_id,
                gap=gap,
                source_facts=_load_list(args.source_facts, "source_facts"),
                prior_memory=memory,
            )
        elif args.command == "submit":
            result = create_result_envelope(
                args.audit_dir,
                role=args.role,
                invocation_id=args.invocation_id,
                model_family=args.model_family,
                payload=_read_object(args.payload),
            )
        else:
            result = deterministic_judge(args.audit_dir)
    except (AgentAuditError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
