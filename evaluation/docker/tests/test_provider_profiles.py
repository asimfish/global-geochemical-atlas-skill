from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


DOCKER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_ROOT))

from provider_profiles import (  # noqa: E402
    ProviderProfileError,
    canonical_sha256,
    file_sha256,
    load_provider_profile,
    validate_registry,
)


class ProviderProfileTests(unittest.TestCase):
    def test_registry_profiles_have_stable_audit_hashes(self) -> None:
        first = load_provider_profile("local-qwen38-openai-v1")
        second = load_provider_profile("local-qwen38-openai-v1")
        self.assertEqual(first.profile_sha256, second.profile_sha256)
        self.assertEqual(first.registry_sha256, second.registry_sha256)
        self.assertEqual(len(first.profile_sha256), 64)
        self.assertTrue(first.audit_record(thinking_mode="not_configured")["evidence"])

    def test_repository_evidence_hash_is_current(self) -> None:
        profile = load_provider_profile("local-qwen38-openai-v1")
        evidence = next(
            item
            for item in profile.entry["evidence"]
            if item["locator"].startswith("repo:")
        )
        repository_root = DOCKER_ROOT.parents[1]
        evidence_path = repository_root / evidence["locator"].removeprefix("repo:")
        self.assertTrue(evidence_path.is_file())
        self.assertEqual(file_sha256(evidence_path), evidence["sha256"])

    def test_local_profile_fails_closed_on_parameter_drift(self) -> None:
        profile = load_provider_profile("local-qwen38-openai-v1")
        valid = {
            "base_url": "https://gateway.example/v1",
            "model": "qwen3.8-max",
            "temperature": 0.0,
            "thinking_mode": "not_configured",
            "require_endpoint": True,
        }
        self.assertEqual(profile.validate_runtime(**valid), "not_configured")
        for changed in (
            {"model": "qwen3.8-max-preview"},
            {"temperature": 0.6},
            {"thinking_mode": "disabled"},
        ):
            request = {**valid, **changed}
            with self.subTest(changed=changed), self.assertRaises(ProviderProfileError):
                profile.validate_runtime(**request)

    def test_endpoint_credentials_query_and_insecure_scheme_are_rejected(self) -> None:
        profile = load_provider_profile("openai-compatible")
        for endpoint in (
            "http://gateway.example/v1",
            "https://user:pass@gateway.example/v1",
            "https://gateway.example/v1?token=secret",
        ):
            with (
                self.subTest(endpoint=endpoint),
                self.assertRaises(ProviderProfileError),
            ):
                profile.validate_runtime(
                    base_url=endpoint,
                    model="vendor/model",
                    temperature=0,
                    thinking_mode=None,
                    require_endpoint=True,
                )

    def test_unknown_and_unresolved_profiles_fail_closed(self) -> None:
        with self.assertRaises(ProviderProfileError):
            load_provider_profile("does-not-exist")
        unresolved = load_provider_profile("competition-qwen-primary-unresolved")
        with self.assertRaises(ProviderProfileError):
            unresolved.validate_runtime(
                base_url="https://gateway.example/v1",
                model="qwen3.8-max",
                temperature=0,
                thinking_mode=None,
                require_endpoint=True,
            )

    def test_container_detects_registry_or_entry_hash_drift(self) -> None:
        profile = load_provider_profile("local-qwen38-openai-v1")
        with self.assertRaises(ProviderProfileError):
            profile.verify_frozen_hashes(
                registry_sha256="0" * 64,
                profile_sha256=profile.profile_sha256,
            )
        with self.assertRaises(ProviderProfileError):
            profile.verify_frozen_hashes(
                registry_sha256=profile.registry_sha256,
                profile_sha256="0" * 64,
            )

    def test_runnable_profile_cannot_hide_unknown_parameters(self) -> None:
        registry_path = DOCKER_ROOT / "provider_profiles.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["profiles"]["broken"] = {
            **registry["profiles"]["competition-qwen-primary-unresolved"],
            "runnable": True,
        }
        with self.assertRaises(ProviderProfileError):
            validate_registry(registry)

    def test_canonical_entry_hash_changes_with_policy(self) -> None:
        entry = {"id": "profile", "temperature": 0.0}
        changed = {"id": "profile", "temperature": 0.6}
        self.assertNotEqual(canonical_sha256(entry), canonical_sha256(changed))


if __name__ == "__main__":
    unittest.main()
