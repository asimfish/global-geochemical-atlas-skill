#!/usr/bin/env python3
"""Load, audit, and fail closed on evaluation provider profiles."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


REGISTRY_PATH = Path(__file__).resolve().with_name("provider_profiles.json")
SCHEMA_VERSION = "ai4s-provider-profile-registry-v1"
SAFE_PROFILE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAFE_MODEL_ID = re.compile(r"^[A-Za-z0-9._:/-]+$")
THINKING_MODES = {"not_configured", "provider_default", "enabled", "disabled", "unknown"}
VERIFICATION_STATUSES = {"generic_transport", "local_frozen_policy", "official_partial_unresolved"}
REGISTRY_FIELDS = {"schema_version", "updated_at", "claim_boundary", "profiles"}
PROFILE_FIELDS = {
    "description",
    "runnable",
    "verification_status",
    "official_claim",
    "transport",
    "endpoint_policy",
    "model_policy",
    "temperature_policy",
    "thinking_policy",
    "evidence",
}
EVIDENCE_FIELDS = {"id", "kind", "title", "locator", "accessed_at", "supports", "sha256"}


class ProviderProfileError(ValueError):
    """Raised when a profile or requested runtime is not auditable."""


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderProfileError(f"{field} must be a non-empty string")
    return value.strip()


def _policy(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderProfileError(f"{field} must be an object")
    _nonempty_string(value.get("kind"), f"{field}.kind")
    return value


def _reject_unknown_fields(value: dict[str, Any], allowed: set[str], field: str) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise ProviderProfileError(f"{field} has unknown fields: {', '.join(unexpected)}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_evidence(items: Any, profile_id: str) -> None:
    if not isinstance(items, list) or not items:
        raise ProviderProfileError(f"profile {profile_id!r} must contain evidence")
    seen: set[str] = set()
    for index, item in enumerate(items):
        field = f"profiles.{profile_id}.evidence[{index}]"
        if not isinstance(item, dict):
            raise ProviderProfileError(f"{field} must be an object")
        _reject_unknown_fields(item, EVIDENCE_FIELDS, field)
        evidence_id = _nonempty_string(item.get("id"), f"{field}.id")
        if evidence_id in seen:
            raise ProviderProfileError(f"profile {profile_id!r} has duplicate evidence id {evidence_id!r}")
        seen.add(evidence_id)
        for name in ("kind", "title", "locator", "accessed_at"):
            _nonempty_string(item.get(name), f"{field}.{name}")
        try:
            date.fromisoformat(item["accessed_at"])
        except ValueError as exc:
            raise ProviderProfileError(f"{field}.accessed_at must be YYYY-MM-DD") from exc
        supports = item.get("supports")
        if not isinstance(supports, list) or not supports:
            raise ProviderProfileError(f"{field}.supports must be a non-empty list")
        for support_index, support in enumerate(supports):
            _nonempty_string(support, f"{field}.supports[{support_index}]")
        if len(supports) != len(set(supports)):
            raise ProviderProfileError(f"{field}.supports must not contain duplicates")
        if "sha256" in item and not re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])):
            raise ProviderProfileError(f"{field}.sha256 must be 64 lowercase hexadecimal characters")


def validate_registry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderProfileError("provider profile registry must be an object")
    _reject_unknown_fields(value, REGISTRY_FIELDS, "registry")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ProviderProfileError(f"unsupported provider profile schema: {value.get('schema_version')!r}")
    _nonempty_string(value.get("claim_boundary"), "claim_boundary")
    updated_at = _nonempty_string(value.get("updated_at"), "updated_at")
    try:
        date.fromisoformat(updated_at)
    except ValueError as exc:
        raise ProviderProfileError("updated_at must be YYYY-MM-DD") from exc
    profiles = value.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ProviderProfileError("profiles must be a non-empty object")
    for profile_id, entry in profiles.items():
        if not isinstance(profile_id, str) or not SAFE_PROFILE_ID.fullmatch(profile_id):
            raise ProviderProfileError(f"unsafe provider profile id: {profile_id!r}")
        if not isinstance(entry, dict):
            raise ProviderProfileError(f"profile {profile_id!r} must be an object")
        _reject_unknown_fields(entry, PROFILE_FIELDS, f"profiles.{profile_id}")
        _nonempty_string(entry.get("description"), f"profiles.{profile_id}.description")
        if not isinstance(entry.get("runnable"), bool):
            raise ProviderProfileError(f"profiles.{profile_id}.runnable must be boolean")
        verification_status = _nonempty_string(
            entry.get("verification_status"), f"profiles.{profile_id}.verification_status"
        )
        if verification_status not in VERIFICATION_STATUSES:
            raise ProviderProfileError(f"profile {profile_id!r} has invalid verification status")
        if not isinstance(entry.get("official_claim"), bool):
            raise ProviderProfileError(f"profiles.{profile_id}.official_claim must be boolean")
        transport = _nonempty_string(entry.get("transport"), f"profiles.{profile_id}.transport")
        if transport not in {"openai-compatible", "unknown"}:
            raise ProviderProfileError(f"profile {profile_id!r} has unsupported transport {transport!r}")
        endpoint = _policy(entry.get("endpoint_policy"), f"profiles.{profile_id}.endpoint_policy")
        model = _policy(entry.get("model_policy"), f"profiles.{profile_id}.model_policy")
        temperature = _policy(entry.get("temperature_policy"), f"profiles.{profile_id}.temperature_policy")
        thinking = _policy(entry.get("thinking_policy"), f"profiles.{profile_id}.thinking_policy")
        if endpoint["kind"] not in {"absolute_https", "unknown"}:
            raise ProviderProfileError(f"profile {profile_id!r} has invalid endpoint policy")
        _reject_unknown_fields(endpoint, {"kind"}, f"profiles.{profile_id}.endpoint_policy")
        if model["kind"] not in {"exact", "safe_id", "unknown"}:
            raise ProviderProfileError(f"profile {profile_id!r} has invalid model policy")
        model_fields = {"kind", "value"} if model["kind"] == "exact" else {"kind", "display_name"}
        _reject_unknown_fields(model, model_fields, f"profiles.{profile_id}.model_policy")
        if model["kind"] == "exact":
            exact_model = _nonempty_string(model.get("value"), f"profiles.{profile_id}.model_policy.value")
            if not SAFE_MODEL_ID.fullmatch(exact_model):
                raise ProviderProfileError(f"profile {profile_id!r} has unsafe exact model id")
        if temperature["kind"] not in {"exact", "range", "unknown"}:
            raise ProviderProfileError(f"profile {profile_id!r} has invalid temperature policy")
        temperature_fields = {
            "exact": {"kind", "value"},
            "range": {"kind", "minimum", "maximum"},
            "unknown": {"kind"},
        }[temperature["kind"]]
        _reject_unknown_fields(temperature, temperature_fields, f"profiles.{profile_id}.temperature_policy")
        if temperature["kind"] == "exact" and not _is_number(temperature.get("value")):
            raise ProviderProfileError(f"profile {profile_id!r} exact temperature must be finite and numeric")
        if temperature["kind"] == "range":
            if not all(_is_number(temperature.get(key)) for key in ("minimum", "maximum")):
                raise ProviderProfileError(f"profile {profile_id!r} temperature range must be finite and numeric")
            if temperature["minimum"] > temperature["maximum"]:
                raise ProviderProfileError(f"profile {profile_id!r} temperature range is reversed")
        if thinking["kind"] not in {"exact", "unknown"}:
            raise ProviderProfileError(f"profile {profile_id!r} has invalid thinking policy")
        _reject_unknown_fields(thinking, {"kind", "value", "semantics"}, f"profiles.{profile_id}.thinking_policy")
        expected_thinking = "unknown" if thinking["kind"] == "unknown" else thinking.get("value")
        if thinking.get("value") != expected_thinking or thinking.get("value") not in THINKING_MODES:
            raise ProviderProfileError(f"profile {profile_id!r} has invalid thinking value")
        _nonempty_string(thinking.get("semantics"), f"profiles.{profile_id}.thinking_policy.semantics")
        if entry["runnable"]:
            if transport != "openai-compatible":
                raise ProviderProfileError(f"runnable profile {profile_id!r} has unsupported transport")
            if endpoint["kind"] != "absolute_https":
                raise ProviderProfileError(f"runnable profile {profile_id!r} must require absolute HTTPS")
            if model["kind"] not in {"exact", "safe_id"}:
                raise ProviderProfileError(f"runnable profile {profile_id!r} has unresolved model policy")
            if temperature["kind"] not in {"exact", "range"}:
                raise ProviderProfileError(f"runnable profile {profile_id!r} has unresolved temperature policy")
            if thinking["kind"] != "exact" or thinking.get("value") not in THINKING_MODES - {"unknown"}:
                raise ProviderProfileError(f"runnable profile {profile_id!r} has unresolved thinking policy")
        _validate_evidence(entry.get("evidence"), profile_id)
    return value


@dataclass(frozen=True)
class ProviderProfile:
    profile_id: str
    entry: dict[str, Any]
    registry_sha256: str
    profile_sha256: str
    registry_claim_boundary: str

    @property
    def transport(self) -> str:
        return str(self.entry["transport"])

    def validate_runtime(
        self,
        *,
        base_url: str,
        model: str,
        temperature: float,
        thinking_mode: str | None,
        require_endpoint: bool,
    ) -> str:
        if not self.entry["runnable"]:
            raise ProviderProfileError(
                f"provider profile {self.profile_id!r} is audit-only and not runnable; "
                "freeze the missing official parameters in a new profile first"
            )
        if not isinstance(temperature, (int, float)) or not math.isfinite(float(temperature)):
            raise ProviderProfileError("temperature must be a finite number")
        endpoint = base_url.strip()
        if require_endpoint and not endpoint:
            raise ProviderProfileError("provider endpoint is required for this agent")
        if endpoint:
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ProviderProfileError(
                    "provider endpoint must be an absolute HTTPS URL without credentials, query, or fragment"
                )
        model_id = model.strip()
        if not model_id or not SAFE_MODEL_ID.fullmatch(model_id):
            raise ProviderProfileError("model id is empty or contains unsafe characters")
        model_policy = self.entry["model_policy"]
        if model_policy["kind"] == "exact" and model_id != model_policy["value"]:
            raise ProviderProfileError(
                f"model drift for profile {self.profile_id!r}: expected {model_policy['value']!r}, got {model_id!r}"
            )
        temperature_policy = self.entry["temperature_policy"]
        value = float(temperature)
        if temperature_policy["kind"] == "exact" and value != float(temperature_policy["value"]):
            raise ProviderProfileError(
                f"temperature drift for profile {self.profile_id!r}: "
                f"expected {temperature_policy['value']!r}, got {temperature!r}"
            )
        if temperature_policy["kind"] == "range" and not (
            float(temperature_policy["minimum"]) <= value <= float(temperature_policy["maximum"])
        ):
            raise ProviderProfileError(
                f"temperature {temperature!r} is outside profile {self.profile_id!r} range"
            )
        expected_thinking = str(self.entry["thinking_policy"]["value"])
        effective_thinking = thinking_mode or expected_thinking
        if effective_thinking != expected_thinking:
            raise ProviderProfileError(
                f"thinking drift for profile {self.profile_id!r}: "
                f"expected {expected_thinking!r}, got {effective_thinking!r}"
            )
        return effective_thinking

    def verify_frozen_hashes(self, *, registry_sha256: str, profile_sha256: str) -> None:
        if registry_sha256 != self.registry_sha256:
            raise ProviderProfileError("provider profile registry hash drift detected inside the container")
        if profile_sha256 != self.profile_sha256:
            raise ProviderProfileError(f"provider profile {self.profile_id!r} hash drift detected inside the container")

    def audit_record(self, *, thinking_mode: str) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "profile_sha256": self.profile_sha256,
            "registry_sha256": self.registry_sha256,
            "transport": self.transport,
            "runtime_policy": {
                "endpoint": self.entry["endpoint_policy"],
                "model": self.entry["model_policy"],
                "temperature": self.entry["temperature_policy"],
                "thinking": self.entry["thinking_policy"],
            },
            "thinking": {
                "mode": thinking_mode,
                "semantics": self.entry["thinking_policy"]["semantics"],
            },
            "verification_status": self.entry["verification_status"],
            "official_claim": self.entry["official_claim"],
            "claim_boundary": self.registry_claim_boundary,
            "evidence": self.entry["evidence"],
        }


def load_provider_profile(profile_id: str, registry_path: Path = REGISTRY_PATH) -> ProviderProfile:
    if not SAFE_PROFILE_ID.fullmatch(profile_id):
        raise ProviderProfileError(f"unsafe provider profile id: {profile_id!r}")
    try:
        raw = registry_path.read_text(encoding="utf-8")
        registry = validate_registry(json.loads(raw))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProviderProfileError(f"cannot load provider profile registry: {registry_path}") from exc
    entry = registry["profiles"].get(profile_id)
    if entry is None:
        available = ", ".join(sorted(registry["profiles"]))
        raise ProviderProfileError(f"unknown provider profile {profile_id!r}; available: {available}")
    return ProviderProfile(
        profile_id=profile_id,
        entry=entry,
        registry_sha256=file_sha256(registry_path),
        profile_sha256=canonical_sha256({"id": profile_id, **entry}),
        registry_claim_boundary=registry["claim_boundary"],
    )
