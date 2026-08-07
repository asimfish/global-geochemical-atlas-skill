#!/usr/bin/env python3
"""Validate the frozen model policy and probe the two allowed HTTPS origins."""

from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


EXPECTED_PRIMARY = "qwen3.8-max"
EXPECTED_FALLBACKS = {"qwen3-vl-plus", "glm-5.2", "wan2.7-image-pro"}
EXPECTED_DOMAINS = {
    "ai.chipcloud.cc",
    "token-plan.cn-beijing.maas.aliyuncs.com",
}


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_json(path: str) -> dict[str, object]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        fail(f"JSON root must be an object: {path}")
    return value


def validate(policy: dict[str, object], config: dict[str, object]) -> None:
    if policy.get("schema_version") != "gga-model-gateway-policy-v1":
        fail("model policy schema mismatch")
    network = policy.get("network")
    routing = policy.get("routing")
    runtime = policy.get("runtime")
    generation = policy.get("generation")
    campaign = policy.get("campaign")
    if not isinstance(network, dict) or set(network.get("allowed_domains", [])) != EXPECTED_DOMAINS:
        fail("network allowlist differs from the two frozen domains")
    if network.get("tls_verification_required") is not True:
        fail("TLS verification must remain enabled")
    if network.get("direct_candidate_egress") is not False:
        fail("candidate direct egress must remain disabled")
    if not isinstance(routing, dict):
        fail("routing policy is missing")
    primary = routing.get("primary")
    fallbacks = routing.get("fallbacks")
    if not isinstance(primary, dict) or primary.get("model_id") != EXPECTED_PRIMARY:
        fail("primary model must be qwen3.8-max")
    if not isinstance(fallbacks, list):
        fail("fallback list is missing")
    fallback_ids = {item.get("model_id") for item in fallbacks if isinstance(item, dict)}
    if fallback_ids != EXPECTED_FALLBACKS:
        fail("fallback model set mismatch")
    if routing.get("fallback_activation") != "official_primary_service_unavailable_only":
        fail("fallback activation rule is too broad")
    if routing.get("automatic_fallback") is not False:
        fail("automatic fallback must remain disabled")
    if "K3" not in routing.get("legacy_models_disabled", []):
        fail("K3 must be explicitly disabled")
    if not isinstance(runtime, dict) or runtime.get("max_runtime_seconds") != 43200:
        fail("maximum runtime must be 43200 seconds")
    if not isinstance(generation, dict):
        fail("generation settings are missing")
    if generation.get("opencode_version") != "1.18.14":
        fail("OpenCode version must be 1.18.14")
    if generation.get("protocol") != "anthropic_compatible_messages":
        fail("provider protocol mismatch")
    if generation.get("temperature") != 0.6:
        fail("temperature must be 0.6")
    if generation.get("thinking") != {"type": "disabled"}:
        fail("thinking must be disabled")
    if not isinstance(campaign, dict) or campaign.get("first_round_stage_repeats") != [2, 16]:
        fail("first-round repeat stages must be [2, 16]")
    if campaign.get("fresh_opencode_session_per_repeat") is not True:
        fail("each repeat must use a fresh OpenCode session")
    if campaign.get("whole_batch_max_runtime_seconds") != 43200:
        fail("whole batch maximum runtime must be 43200 seconds")

    provider = config.get("provider")
    if config.get("model") != "alibaba-token-plan-cn/qwen3.8-max":
        fail("OpenCode default model is not the primary model")
    if config.get("default_agent") != "gateway-smoke":
        fail("OpenCode default agent mismatch")
    if config.get("enabled_providers") != ["alibaba-token-plan-cn"]:
        fail("OpenCode provider allowlist mismatch")
    if not isinstance(provider, dict) or not isinstance(provider.get("alibaba-token-plan-cn"), dict):
        fail("OpenCode Alibaba Token Plan provider is missing")
    anthropic = provider["alibaba-token-plan-cn"]
    if anthropic.get("npm") != "@ai-sdk/anthropic":
        fail("OpenCode provider must use the Anthropic protocol package")
    options = anthropic.get("options")
    models = anthropic.get("models")
    if not isinstance(options, dict) or options.get("baseURL") != policy.get("anthropic_base_url"):
        fail("OpenCode Anthropic base URL mismatch")
    if options.get("apiKey") != "{env:ALIBABA_TOKEN_PLAN_API_KEY}":
        fail("OpenCode API key must come from the runtime environment")
    if not isinstance(models, dict) or set(models) != {EXPECTED_PRIMARY, "qwen3-vl-plus", "glm-5.2"}:
        fail("OpenCode chat model set mismatch")
    agent = config.get("agent")
    if not isinstance(agent, dict) or not isinstance(agent.get("gateway-smoke"), dict):
        fail("OpenCode gateway-smoke agent is missing")
    smoke_agent = agent["gateway-smoke"]
    if smoke_agent.get("temperature") != 0.6:
        fail("OpenCode agent temperature must be 0.6")
    if smoke_agent.get("thinking") != {"type": "disabled"}:
        fail("OpenCode agent thinking must be disabled")
    for model in models.values():
        if not isinstance(model, dict) or model.get("options", {}).get("thinking") != {"type": "disabled"}:
            fail("every OpenCode chat model must disable thinking")
    serialized = json.dumps(config, sort_keys=True)
    if "K3" in serialized or "wan2.7-image-pro" in serialized:
        fail("unsupported or replaced models leaked into the Anthropic Messages config")


def request(url: str, *, expect_blocked: bool = False) -> tuple[int, str]:
    context = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "gga-model-gateway-probe/1"})
    try:
        with urllib.request.urlopen(req, timeout=15, context=context) as response:
            return response.status, response.geturl()
    except urllib.error.HTTPError as exc:
        if expect_blocked and exc.code == 403:
            return exc.code, exc.geturl()
        if 400 <= exc.code < 500:
            return exc.code, exc.geturl()
        raise
    except urllib.error.URLError as exc:
        # A denied HTTPS CONNECT is rejected by Squid before TLS is created, so
        # urllib reports it as a tunnel URLError instead of an HTTPError.
        if expect_blocked and "Tunnel connection failed: 403" in str(exc.reason):
            return 403, url
        raise


def main() -> None:
    if len(sys.argv) != 3:
        fail("usage: probe.py POLICY CONFIG")
    policy = load_json(sys.argv[1])
    config = load_json(sys.argv[2])
    validate(policy, config)

    version = subprocess.run(
        ["opencode", "--version"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    if version != "1.18.14":
        fail(f"unexpected OpenCode version: {version!r}")
    listed = subprocess.run(
        ["opencode", "models", "alibaba-token-plan-cn"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()
    expected_models = {
        "alibaba-token-plan-cn/qwen3.8-max",
        "alibaba-token-plan-cn/qwen3-vl-plus",
        "alibaba-token-plan-cn/glm-5.2",
    }
    if not expected_models <= set(listed):
        fail(f"OpenCode model registration is incomplete: {sorted(set(listed))}")

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        fail("HTTPS proxy is not configured")

    gateway_status, gateway_final = request(str(policy["evaluation_gateway_url"]))
    qwen_status, qwen_final = request(str(policy["anthropic_base_url"]))
    blocked_status, _ = request("https://example.com", expect_blocked=True)
    if blocked_status != 403:
        fail(f"non-allowlisted egress was not blocked: HTTP {blocked_status}")

    print("policy_validation=PASS")
    print(f"opencode_version={version}")
    print("opencode_config=PASS")
    print("opencode_models=qwen3.8-max,qwen3-vl-plus,glm-5.2")
    print(f"gateway_http_status={gateway_status}")
    print(f"gateway_final_url={gateway_final}")
    print(f"qwen_base_http_status={qwen_status}")
    print(f"qwen_base_final_url={qwen_final}")
    print("tls_verification=PASS")
    print("non_allowlisted_egress=BLOCKED")
    print("primary_model=qwen3.8-max")
    print("temperature=0.6")
    print("thinking=disabled")
    print("first_round_stage_repeats=2,16")
    print("fallback_activation=official_primary_service_unavailable_only")
    print("credential_used=no")
    print("status=PASS")


if __name__ == "__main__":
    main()
