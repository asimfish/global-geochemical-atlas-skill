#!/usr/bin/env python3
"""Build a controller-owned, paired B0/S0 experiment manifest.

The candidate never writes this file.  It binds the common public task bytes,
the only allowed B0/S0 visibility difference, and the frozen provider policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
DOCKER = ROOT / "evaluation" / "docker"
sys.path.insert(0, str(DOCKER))
from provider_profiles import ProviderProfileError, load_provider_profile  # noqa: E402


class ManifestError(RuntimeError):
    pass


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ManifestError(f"JSON root must be an object: {path}")
    return value


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def public_projection(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    files = bundle.get("files")
    if not isinstance(files, list):
        raise ManifestError("candidate bundle has no file manifest")
    return [
        item
        for item in files
        if isinstance(item, dict)
        and item.get("path") != "AGENT_PROMPT.md"
        and not str(item.get("path") or "").startswith(".agents/skills/")
    ]


def build(
    config: dict[str, Any],
    b0: dict[str, Any],
    s0: dict[str, Any],
    *,
    condition: str,
    runtime: str,
    run_id: str,
    provider_base_url: str,
    expected_commit: str | None = None,
) -> dict[str, Any]:
    if condition not in {"B0", "S0"} or runtime not in {"host-uplift", "docker-uplift"}:
        raise ManifestError("unsupported condition or runtime")
    frozen_commit = expected_commit or config.get("commit")
    if not isinstance(frozen_commit, str) or len(frozen_commit) != 40:
        raise ManifestError("expected commit must be a full 40-character Git object ID")
    for expected, bundle in (("B0", b0), ("S0", s0)):
        if (
            bundle.get("schema_version") != "qwen-uplift-candidate-bundle-v1"
            or bundle.get("mode") != "formal"
            or bundle.get("condition") != expected
            or bundle.get("source_commit") != frozen_commit
        ):
            raise ManifestError(f"{expected} bundle is not the frozen formal bundle")
    b0_public, s0_public = public_projection(b0), public_projection(s0)
    if b0_public != s0_public:
        raise ManifestError(
            "B0/S0 public task bytes differ outside prompt and Skill visibility"
        )
    endpoint = urlsplit(provider_base_url)
    if (
        endpoint.scheme != "https"
        or not endpoint.hostname
        or endpoint.username
        or endpoint.password
    ):
        raise ManifestError("provider endpoint must be credential-free HTTPS")
    profile_id = str(config.get("provider_profile") or "")
    profile = load_provider_profile(profile_id)
    api_model = str(config.get("api_model") or "")
    temperature = config.get("temperature")
    thinking = profile.validate_runtime(
        base_url=provider_base_url,
        model=api_model,
        temperature=temperature,
        thinking_mode=config.get("thinking"),
        require_endpoint=True,
    )
    provider = profile.audit_record(thinking_mode=thinking)
    provider["endpoint_origin"] = f"{endpoint.scheme}://{endpoint.netloc}"
    common = {
        "protocol_version": config.get("protocol_version"),
        "repository": config.get("repository"),
        "commit": frozen_commit,
        "display_model": config.get("model"),
        "api_model": api_model,
        "temperature": temperature,
        "thinking": thinking,
        "runtime": runtime,
        "task_request": config.get("task_request"),
        "public_case": config.get("public_case"),
        "runtime_resources": config.get("docker")
        if runtime == "docker-uplift"
        else {"mode": "host"},
        "public_bundle_projection_sha256": canonical_sha256(b0_public),
        "provider": provider,
    }
    pair_fingerprint = canonical_sha256(common)
    selected = b0 if condition == "B0" else s0
    return {
        "schema_version": "qwen-uplift-controller-experiment-v1",
        "generated_by": "external_evaluation_controller",
        "condition": condition,
        "run_id": run_id,
        "pair_fingerprint": pair_fingerprint,
        "run_fingerprint": canonical_sha256(
            {
                "pair_fingerprint": pair_fingerprint,
                "condition": condition,
                "run_id": run_id,
                "candidate_bundle_content_sha256": selected.get(
                    "content_manifest_sha256"
                ),
            }
        ),
        "common_experiment": common,
        "candidate_bundle": {
            "condition": condition,
            "content_manifest_sha256": selected.get("content_manifest_sha256"),
            "source_commit": selected.get("source_commit"),
            "skill_visible": condition == "S0",
        },
        "claim_boundary": (
            "This controller-owned manifest proves the frozen local pair inputs. It does not prove "
            "the upstream provider served the advertised model without independent provider attestation."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--b0-bundle-manifest", type=Path, required=True)
    parser.add_argument("--s0-bundle-manifest", type=Path, required=True)
    parser.add_argument("--condition", choices=("B0", "S0"), required=True)
    parser.add_argument(
        "--runtime", choices=("host-uplift", "docker-uplift"), required=True
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--provider-base-url", required=True)
    parser.add_argument(
        "--expected-commit",
        help="Controller-frozen release commit; required when the checked-out config necessarily predates its own release pin.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(
            load(args.config),
            load(args.b0_bundle_manifest),
            load(args.s0_bundle_manifest),
            condition=args.condition,
            runtime=args.runtime,
            run_id=args.run_id,
            provider_base_url=args.provider_base_url,
            expected_commit=args.expected_commit,
        )
    except (ManifestError, ProviderProfileError) as exc:
        parser.exit(1, f"experiment manifest error: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {"status": "PASS", "pair_fingerprint": result["pair_fingerprint"]},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
