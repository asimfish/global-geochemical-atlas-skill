#!/usr/bin/env python3
"""Audit source catalog entries against the D1 production acceptance gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import source_adapters
import source_router

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_CATALOG = SKILL_DIR / "assets" / "source_catalog.json"
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"

AUDIT_VERSION = "geochemical-source-audit-v1"
GateStatus = Literal["pass", "review", "fail"]


def _gate(status: GateStatus, note: str, evidence: Sequence[str] = ()) -> dict[str, Any]:
    return {"status": status, "note": note, "evidence": list(dict.fromkeys(evidence))}


def _https_urls(values: Sequence[Any]) -> bool:
    return bool(values) and all(isinstance(value, str) and value.startswith("https://") for value in values)


def _registry_integrity_gate(source_id: str, registry_entry: Mapping[str, Any] | None) -> dict[str, Any]:
    if registry_entry is None:
        return _gate("review", "No immutable production registry entry has been approved.")
    download = registry_entry.get("download")
    if not isinstance(download, dict):
        return _gate("fail", "Production registry has no download contract.")
    files = download.get("files")
    if isinstance(files, list) and files:
        hashes = [item.get("expected_sha256") for item in files if isinstance(item, dict)]
        if len(hashes) == len(files) and all(isinstance(value, str) and len(value) == 64 for value in hashes):
            return _gate("pass", "Every registered file has a pinned SHA-256.")
        return _gate("fail", "One or more registered files lack a pinned SHA-256.")
    members = download.get("members")
    if isinstance(members, list) and members:
        valid = all(
            isinstance(item, dict)
            and isinstance(item.get("bytes"), int)
            and isinstance(item.get("publisher_checksum"), dict)
            and item["publisher_checksum"].get("algorithm") in {"md5", "sha256"}
            and isinstance(item["publisher_checksum"].get("value"), str)
            for item in members
        )
        if valid:
            return _gate("pass", "Archive members are pinned by name, size and publisher checksum.")
        return _gate("fail", "Archive member inventory or publisher checksums are incomplete.")
    return _gate("fail", "Production download contract has no verifiable file or member inventory.")


def _audit_source(
    source_id: str,
    entry: Mapping[str, Any],
    registry_entry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    evidence_urls = entry.get("evidence_urls", [])
    identity = _gate(
        "pass" if entry.get("title") and entry.get("publisher") and _https_urls(evidence_urls) else "fail",
        "Publisher, title and official HTTPS evidence are present."
        if entry.get("title") and entry.get("publisher") and _https_urls(evidence_urls)
        else "Publisher, title or official HTTPS evidence is incomplete.",
        evidence_urls,
    )
    version = entry.get("version", {})
    if version.get("status") == "pinned" and version.get("value"):
        version_gate = _gate("pass", f"Immutable production version is pinned: {version['value']}")
    elif version.get("status") in {"snapshot_available", "annual_repository_versions", "dataset_specific", "dynamic"}:
        version_gate = _gate("review", "A concrete immutable version still needs to be selected and verified.")
    else:
        version_gate = _gate("review", "Version is unresolved.")

    license_entry = entry.get("license", {})
    if license_entry.get("status") == "open" and license_entry.get("id") and license_entry.get("url"):
        license_gate = _gate("pass", f"Open license is explicit: {license_entry['id']}", [license_entry["url"]])
    elif license_entry.get("status") == "restricted":
        license_gate = _gate("fail", "Raw data are restricted for the current production policy.")
    else:
        license_gate = _gate(
            "review",
            f"License is not uniformly open: {license_entry.get('status', 'missing')}",
            [license_entry["url"]] if license_entry.get("url") else [],
        )

    interfaces = entry.get("interfaces", [])
    interface_urls = [item.get("url") for item in interfaces if isinstance(item, dict)]
    if not interfaces or not all(isinstance(value, str) and value for value in interface_urls):
        interface_gate = _gate("fail", "No usable interface or download endpoint is recorded.")
    elif all(value.startswith("https://") for value in interface_urls):
        interface_gate = _gate("pass", "Recorded interfaces use explicit HTTPS endpoints.", interface_urls)
    else:
        interface_gate = _gate("review", "At least one interface is not HTTPS and needs transport review.", interface_urls)

    identifiers = entry.get("identifiers", {})
    provenance_gate = _gate(
        "pass",
        "Official landing page and evidence chain are recorded"
        + (f" with DOI {identifiers['dataset_doi']}." if identifiers.get("dataset_doi") else "."),
        [entry["landing_page"], *evidence_urls],
    )

    if registry_entry is None:
        schema_gate = _gate("review", "No production field contract has been frozen.")
        adapter_gate = _gate("review", "No production adapter has been approved.")
    else:
        required_fields = registry_entry.get("required_fields")
        schema_gate = _gate(
            "pass" if isinstance(required_fields, list) and required_fields else "fail",
            "Production registry declares required source fields."
            if isinstance(required_fields, list) and required_fields
            else "Production registry lacks required source fields.",
        )
        try:
            adapter = source_adapters.get_adapter(source_id)
        except source_adapters.SourceAdapterError:
            adapter_gate = _gate("fail", "Production registry has no callable adapter.")
        else:
            adapter_gate = _gate(
                "pass" if adapter.candidate.version == str(registry_entry.get("dataset_version")) else "fail",
                "Adapter resolves the same immutable registry version."
                if adapter.candidate.version == str(registry_entry.get("dataset_version"))
                else "Adapter and production registry versions differ.",
            )

    alignment_evidence: list[str] = []
    if registry_entry is None:
        alignment_gate = _gate("review", "Source is not present in the production registry.")
    else:
        catalog_version = version.get("value")
        registry_version = str(registry_entry.get("dataset_version"))
        catalog_license = license_entry.get("id")
        registry_license = registry_entry.get("license", {}).get("spdx")
        aligned = catalog_version == registry_version and catalog_license == registry_license
        if registry_entry.get("dataset_doi"):
            alignment_evidence.append(f"doi:{registry_entry['dataset_doi']}")
        alignment_gate = _gate(
            "pass" if aligned else "fail",
            "Catalog version and license match the immutable production registry."
            if aligned
            else "Catalog and production registry version or license differ.",
            alignment_evidence,
        )

    limitations = entry.get("limitations")
    limitations_gate = _gate(
        "pass" if isinstance(limitations, list) and limitations else "fail",
        "Scientific and operational limitations are explicit."
        if isinstance(limitations, list) and limitations
        else "Source limitations are missing.",
    )
    gates = {
        "identity": identity,
        "version": version_gate,
        "license": license_gate,
        "interface": interface_gate,
        "provenance": provenance_gate,
        "schema": schema_gate,
        "integrity": _registry_integrity_gate(source_id, registry_entry),
        "adapter": adapter_gate,
        "registry_alignment": alignment_gate,
        "limitations": limitations_gate,
    }
    blockers = [name for name, gate in gates.items() if gate["status"] != "pass"]
    if any(gate["status"] == "fail" for gate in gates.values()):
        audit_status: GateStatus = "fail" if entry.get("production_eligible") else "review"
    elif blockers:
        audit_status = "review"
    else:
        audit_status = "pass"
    return {
        "declared_status": entry["status"],
        "production_eligible": entry["production_eligible"],
        "audit_status": audit_status,
        "blockers": blockers,
        "gates": gates,
    }


def audit_catalog(
    catalog: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    """Audit every catalog source and fail if a production entry misses a hard gate."""

    results = {
        source_id: _audit_source(source_id, entry, registry.get("sources", {}).get(source_id))
        for source_id, entry in sorted(catalog["sources"].items())
    }
    invalid_production = [
        source_id
        for source_id, result in results.items()
        if result["production_eligible"] and result["audit_status"] != "pass"
    ]
    counts = Counter(result["audit_status"] for result in results.values())
    return {
        "audit_version": AUDIT_VERSION,
        "status": "FAIL" if invalid_production else "PASS",
        "catalog_version": catalog["catalog_version"],
        "registry_version": registry["registry_version"],
        "audited_at": catalog["reviewed_at"],
        "source_count": len(results),
        "summary": {status: counts.get(status, 0) for status in ("pass", "review", "fail")},
        "invalid_production_sources": invalid_production,
        "sources": results,
        "claim_boundary": (
            "A passing audit proves that acquisition metadata and production gates are internally consistent. "
            "It does not prove that every historical measurement equals the true geochemical state."
        ),
    }


def run(catalog_path: Path = DEFAULT_CATALOG, registry_path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    catalog = source_router.load_catalog(catalog_path)
    registry = source_adapters.load_source_registry(registry_path)
    return audit_catalog(catalog, registry)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run(args.catalog, args.registry)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError, source_adapters.SourceAdapterError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
