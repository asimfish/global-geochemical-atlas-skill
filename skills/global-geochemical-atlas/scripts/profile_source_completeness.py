#!/usr/bin/env python3
"""Profile full-population evidence separately from deterministic demo slices.

The report is intentionally conservative: a registered expected count is not an
observed full-population count, and a demo fixture is never used as the
denominator for a full-source completeness claim.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_REGISTRY = SKILL_DIR / "assets" / "source_manifest.json"
DEFAULT_AUDITS = SKILL_DIR / "fixtures" / "candidate-audits"
DEFAULT_DEMOS = SKILL_DIR / "fixtures" / "source-demos"
DEFAULT_FULL_PROFILES = SKILL_DIR / "assets" / "v4-full-profiles"
DEFAULT_JSON = SKILL_DIR / "assets" / "v4-source-completeness.json"
DEFAULT_MARKDOWN = SKILL_DIR / "references" / "v4-source-completeness.md"

PROFILE_VERSION = "d1-v4-source-completeness-v1"
DEMO_FIELDS = (
    "element_or_analyte",
    "value",
    "unit",
    "medium",
    "sample_id",
    "coordinate_pair",
    "sample_type_raw",
    "sample_type",
    "sample_type_mapping_status",
    "soil_horizon_raw",
    "sediment_environment",
    "water_body_type",
    "water_fraction",
    "grain_fraction",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "analytical_method",
    "method_scope",
    "method_assignment_basis",
    "source_locator",
    "license",
    "citation_scope",
)


class ProfileError(RuntimeError):
    """Raised when a completeness profile cannot be built safely."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ProfileError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _latest_audits(audit_dir: Path) -> dict[str, tuple[Path, dict[str, Any]]]:
    audits: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path in sorted(audit_dir.glob("*.json")):
        value = _load_json(path)
        source_id = value.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            raise ProfileError(f"candidate audit has no source_id: {path}")
        audits[source_id] = (path, value)
    return audits


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def _first_int(mapping: Mapping[str, Any], paths: Sequence[Sequence[str]]) -> int | None:
    for path in paths:
        value = _nested(mapping, *path)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _target_observations(observed: Mapping[str, Any]) -> tuple[int | None, str | None]:
    direct = _first_int(observed, (("target_observations",), ("counts", "target_observations")))
    if direct is not None:
        return direct, "observed_data.target_observations"
    counts = observed.get("counts")
    if isinstance(counts, Mapping):
        arsenic = counts.get("arsenic_observations")
        if isinstance(arsenic, int) and not isinstance(arsenic, bool):
            return arsenic, "observed_data.counts.arsenic_observations"
    analytes = observed.get("target_analytes")
    if isinstance(analytes, Mapping) and analytes:
        counts: list[int] = []
        for value in analytes.values():
            if isinstance(value, int) and not isinstance(value, bool):
                counts.append(value)
            elif isinstance(value, Mapping):
                present = value.get("present_count")
                data_count = value.get("data_count")
                if isinstance(present, int) and not isinstance(present, bool):
                    counts.append(present)
                elif isinstance(data_count, int) and not isinstance(data_count, bool):
                    counts.append(data_count)
                else:
                    return None, None
            else:
                return None, None
        return sum(counts), "sum(observed_data.target_analytes explicit counts)"
    return None, None


def _full_population(audit_path: Path | None, audit: Mapping[str, Any] | None) -> dict[str, Any]:
    if audit_path is None or audit is None:
        return {
            "audit_status": "not_measured",
            "audit_path": None,
            "denominator_status": "not_available",
            "target_observation_count": None,
            "physical_row_count": None,
            "distinct_sample_count": None,
            "warning": "No checked-in full-population audit; demo counts must not be substituted.",
        }
    observed = audit.get("observed_data")
    if not isinstance(observed, Mapping):
        observed = {}
    target_count, target_basis = _target_observations(observed)
    physical_rows = _first_int(
        observed,
        (("physical_rows",), ("counts", "physical_rows"), ("data_record_count",), ("sample_rows",)),
    )
    distinct_samples = _first_int(
        observed,
        (
            ("distinct_samples",),
            ("distinct_res_id",),
            ("distinct_reported_sample_ids",),
            ("distinct_gtn_union",),
            ("target_bearing_row_count",),
            ("counts", "selected_cruise_station_pairs"),
            ("counts", "arsenic_station_count"),
        ),
    )
    return {
        "audit_status": "audited_snapshot",
        "audit_path": str(audit_path.relative_to(SKILL_DIR)),
        "audit_sha256": _sha256(audit_path),
        "snapshot_id": audit.get("snapshot_id"),
        "denominator_status": "available" if target_count is not None else "not_available",
        "target_observation_count": target_count,
        "target_observation_count_basis": target_basis,
        "physical_row_count": physical_rows,
        "distinct_sample_count": distinct_samples,
        "field_completeness_status": "not_measured_uniformly",
        "warning": (
            "The audit proves only its explicit counts and metadata. It does not imply row-level completeness "
            "for fields whose non-null numerator was not measured."
        ),
    }


def _uniform_full_profile(profile_dir: Path, source_id: str) -> dict[str, Any] | None:
    field_path = profile_dir / source_id / "field_completeness.json"
    if not field_path.is_file():
        return None
    field_profile = _load_json(field_path)
    automation_path = profile_dir / source_id / "automation_health.json"
    automation = _load_json(automation_path) if automation_path.is_file() else {}
    denominator = field_profile.get("observation_count")
    if not isinstance(denominator, int) or denominator <= 0:
        raise ProfileError(f"invalid full-population denominator: {field_path}")
    fields = field_profile.get("fields")
    if not isinstance(fields, Mapping) or not fields:
        raise ProfileError(f"full-population field counts are missing: {field_path}")
    return {
        "audit_status": "uniform_full_profile",
        "audit_path": str(field_path.relative_to(SKILL_DIR)),
        "audit_sha256": _sha256(field_path),
        "snapshot_id": field_profile.get("dataset_version"),
        "profile_scope": field_profile.get("profile_scope"),
        "denominator_status": "available",
        "target_observation_count": denominator,
        "target_observation_count_basis": field_profile.get("denominator_definition"),
        "physical_row_count": automation.get("parsed_source_record_count"),
        "distinct_sample_count": None,
        "field_completeness_status": "measured_uniformly",
        "field_completeness": fields,
        "warning": (
            "The full profile covers every target-bearing adapter observation in the verified cache. "
            "It does not imply spatial representativeness or that unreported source fields are complete."
        ),
    }


def _present(row: Mapping[str, str], field: str) -> bool:
    if field == "coordinate_pair":
        return bool((row.get("latitude") or "").strip() and (row.get("longitude") or "").strip())
    return bool((row.get(field) or "").strip())


def _demo_profile(path: Path, manifest_path: Path) -> dict[str, Any]:
    if not path.is_file() or not manifest_path.is_file():
        return {"status": "missing_fixture", "record_count": 0, "field_completeness": {}}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        rows = list(reader)
    denominator = len(rows)
    fields: dict[str, Any] = {}
    for field in DEMO_FIELDS:
        numerator = sum(_present(row, field) for row in rows)
        fields[field] = {
            "non_empty": numerator,
            "denominator": denominator,
            "rate": round(numerator / denominator, 6) if denominator else 0.0,
            "column_present": field == "coordinate_pair" or field in headers,
        }
    media = Counter((row.get("medium") or "missing").strip() or "missing" for row in rows)
    analytes = Counter((row.get("element_or_analyte") or "missing").strip() or "missing" for row in rows)
    return {
        "status": "deterministic_demo_only",
        "record_count": denominator,
        "header_sha256": hashlib.sha256("\n".join(headers).encode()).hexdigest(),
        "file_sha256": _sha256(path),
        "manifest_sha256": _sha256(manifest_path),
        "field_completeness": fields,
        "media": dict(sorted(media.items())),
        "analytes": dict(sorted(analytes.items())),
        "warning": "This profile describes a deliberately selected fixture, not the full source population.",
    }


def _rights(source: Mapping[str, Any]) -> dict[str, Any]:
    license_value = source.get("license")
    license_value = license_value if isinstance(license_value, Mapping) else {}
    return {
        "access_status": "registered_landing_and_download" if source.get("landing_page") and source.get("download") else "not_assessed",
        "research_use_status": source.get("research_use_status", "not_assessed_separately"),
        "license_id": license_value.get("spdx"),
        "license_url": license_value.get("url"),
        "attribution_evidence_present": bool(source.get("citation")),
        "redistribution_note_present": bool(source.get("redistribution")),
        "warning": "Access, research use and redistribution are separate facts; this report does not infer one from another.",
    }


def _automation(source: Mapping[str, Any], demo: Mapping[str, Any]) -> dict[str, Any]:
    download = source.get("download")
    download = download if isinstance(download, Mapping) else {}
    version = source.get("dataset_version")
    expected_hash_text = json.dumps(download, sort_keys=True)
    return {
        "adapter_registered": bool(source.get("adapter")),
        "dataset_version_pinned": bool(version),
        "download_mode": download.get("mode"),
        "download_contract_has_hash": "sha256" in expected_hash_text or "checksum" in expected_hash_text,
        "offline_demo_replay_available": demo.get("status") == "deterministic_demo_only",
        "online_fetch_health": "not_checked_by_offline_profile",
        "schema_drift_status": "not_measured",
        "row_count_drift_status": "not_measured",
    }


def build_profile(
    registry_path: Path,
    audit_dir: Path,
    demo_dir: Path,
    full_profile_dir: Path = DEFAULT_FULL_PROFILES,
) -> dict[str, Any]:
    registry = _load_json(registry_path)
    sources = registry.get("sources")
    if not isinstance(sources, Mapping) or not sources:
        raise ProfileError("source registry has no sources object")
    audits = _latest_audits(audit_dir)
    profiles: dict[str, Any] = {}
    for source_id in sorted(sources):
        source = sources[source_id]
        if not isinstance(source, Mapping):
            raise ProfileError(f"invalid source registry entry: {source_id}")
        demo = _demo_profile(demo_dir / source_id / "demo_input.csv", demo_dir / source_id / "run_manifest.json")
        audit_item = audits.get(source_id)
        candidate_audit = _full_population(*(audit_item or (None, None)))
        full = _uniform_full_profile(full_profile_dir, source_id) or candidate_audit
        full_rights_path = full_profile_dir / source_id / "usage_rights_coverage.json"
        full_automation_path = full_profile_dir / source_id / "automation_health.json"
        profiles[source_id] = {
            "source_id": source_id,
            "dataset_version": source.get("dataset_version"),
            "media": source.get("media", []),
            "full_population": full,
            "candidate_audit": candidate_audit,
            "demo_fixture": demo,
            "usage_rights": _load_json(full_rights_path) if full_rights_path.is_file() else _rights(source),
            "automation_health": (
                _load_json(full_automation_path) if full_automation_path.is_file() else _automation(source, demo)
            ),
        }
    audited = sum(value["candidate_audit"]["audit_status"] == "audited_snapshot" for value in profiles.values())
    uniform = sum(
        value["full_population"]["field_completeness_status"] == "measured_uniformly"
        for value in profiles.values()
    )
    denominators = sum(value["full_population"]["denominator_status"] == "available" for value in profiles.values())
    demo_records = sum(value["demo_fixture"]["record_count"] for value in profiles.values())
    missing_audits = sorted(
        source_id for source_id, value in profiles.items()
        if value["candidate_audit"]["audit_status"] == "not_measured"
    )
    missing_uniform_profiles = sorted(
        source_id for source_id, value in profiles.items()
        if value["full_population"]["field_completeness_status"] != "measured_uniformly"
    )
    findings = [
        {
            "severity": "high" if missing_uniform_profiles else "info",
            "code": "FULL_FIELD_COMPLETENESS_NOT_UNIFORM",
            "affected_sources": len(missing_uniform_profiles),
            "source_ids": missing_uniform_profiles,
            "detail": (
                "Every executable source has a uniform full-population numerator/denominator."
                if not missing_uniform_profiles
                else "These sources do not yet have uniform V4 full-population field counts."
            ),
            "next_action": "Run adapters over verified full caches and emit per-field non-null, valid and missing-reason counts.",
        },
        {
            "severity": "high" if missing_audits else "info",
            "code": "FULL_AUDIT_MISSING",
            "affected_sources": len(missing_audits),
            "source_ids": missing_audits,
            "detail": "These executable sources have no checked-in candidate full-population audit.",
            "next_action": "Add immutable full-source audits without substituting demo rows.",
        },
    ]
    return {
        "profile_version": PROFILE_VERSION,
        "generated_from_registry_verified_at": registry.get("verified_at"),
        "population_definitions": {
            "full_population": (
                "Uniform field counts produced by parsing every target-bearing observation in a verified full cache; "
                "candidate audits remain separate supporting evidence."
            ),
            "registered_contract": "Expected counts in source_manifest.json; not treated as observations by this profile.",
            "demo_fixture": "Deterministic selected rows for engineering tests; never a full-population denominator.",
        },
        "summary": {
            "executable_source_count": len(profiles),
            "sources_with_full_audit": audited,
            "sources_with_target_observation_denominator": denominators,
            "sources_without_full_audit": len(missing_audits),
            "demo_record_count": demo_records,
            "uniform_full_field_profiles": uniform,
        },
        "sources": profiles,
        "findings": findings,
        "claim_boundary": (
            "This report measures full-cache and demo-field completeness. It does not validate scientific "
            "accuracy, spatial representativeness or comparability, and it never promotes demo metrics to full-source claims."
        ),
    }


def _markdown(profile: Mapping[str, Any]) -> str:
    summary = profile["summary"]
    lines = [
        "# V4 来源完整率审计",
        "",
        "> 本报告强制区分全量来源、登记契约和工程演示样板。没有全量分母时写 `not_measured`，不使用 demo 行数替代。",
        "",
        "## 摘要",
        "",
        f"- 可执行来源：{summary['executable_source_count']}",
        f"- 有全量候选审计：{summary['sources_with_full_audit']}",
        f"- 有明确目标测定分母：{summary['sources_with_target_observation_denominator']}",
        f"- 缺少全量候选审计：{summary['sources_without_full_audit']}",
        f"- 演示样板记录：{summary['demo_record_count']}（仅工程测试）",
        f"- 已完成统一全量逐字段 profile：{summary['uniform_full_field_profiles']}",
        "",
        "## 来源口径",
        "",
        "| 来源 | 全量审计 | 全量目标测定 | demo 行 | 样品类型 demo 完整率 | 方法 scope demo 完整率 |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for source_id, value in profile["sources"].items():
        full = value["full_population"]
        demo = value["demo_fixture"]
        fields = demo["field_completeness"]
        target = full["target_observation_count"]
        target_text = str(target) if target is not None else "not_measured"
        sample_rate = fields.get("sample_type", {}).get("rate", 0.0)
        method_rate = fields.get("method_scope", {}).get("rate", 0.0)
        lines.append(
            f"| `{source_id}` | {full['audit_status']} | {target_text} | {demo['record_count']} | "
            f"{sample_rate:.1%} | {method_rate:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 当前阻塞",
            "",
            f"1. 统一全量逐字段 profile 已完成 {summary['uniform_full_field_profiles']}/{summary['executable_source_count']}；任何缺口仍显示 `not_measured`。",
            "2. 候选来源审计与全量 adapter profile 分开保留，缺候选审计不再用 demo 补位。",
            "3. 在线实时可用性仍需独立探测；固定缓存的 hash、schema、row-count 与离线重放已纳入 profile。",
            "",
            "机器可读结果见 `assets/v4-source-completeness.json`。",
        ]
    )
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--audit-dir", type=Path, default=DEFAULT_AUDITS)
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMOS)
    parser.add_argument("--full-profile-dir", type=Path, default=DEFAULT_FULL_PROFILES)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--check", action="store_true", help="Fail if checked-in outputs differ from a fresh profile")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = build_profile(args.registry, args.audit_dir, args.demo_dir, args.full_profile_dir)
        json_text = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        markdown_text = _markdown(profile)
        if args.check:
            if args.output_json.read_text(encoding="utf-8") != json_text:
                raise ProfileError(f"checked-in JSON profile is stale: {args.output_json}")
            if args.output_markdown.read_text(encoding="utf-8") != markdown_text:
                raise ProfileError(f"checked-in Markdown profile is stale: {args.output_markdown}")
        else:
            _atomic_json(args.output_json, profile)
            _atomic_text(args.output_markdown, markdown_text)
    except (OSError, ProfileError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "PASS", "summary": profile["summary"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
