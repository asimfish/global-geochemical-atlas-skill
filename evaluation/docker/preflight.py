#!/usr/bin/env python3
"""Run deterministic L0 checks and prepare auditable L1 review evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from common import atomic_json, hash_records, sha256_file, utc_now


NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MARKDOWN_LINK = re.compile(r"\[[^]]*]\(([^)]+)\)")
INLINE_PATH = re.compile(r"`((?:references|scripts|assets)/[^`]+)`")
SECRET_PATTERNS = (
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9._-]{16,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
)
INJECTION_PATTERNS = (
    re.compile(r"给(?:本|这个|该)?\s*(?:skill|技能|作品).*高分", re.IGNORECASE),
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"(?:绕过|规避).{0,12}(?:评测|评分|检查)"),
)
SKIP_PARTS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "node_modules",
}
SKIP_SUFFIXES = {".pyc", ".pyo", ".log", ".tmp"}
TOTAL_LIMIT = 200 * 1024 * 1024
FILE_LIMIT = 100 * 1024 * 1024
ACTIVATION_RUBRICS = {
    "discoverability",
    "correctness",
    "security",
    "effectiveness",
    "efficiency",
}
SKILL_CARD_SECTIONS = (
    "## Purpose",
    "## Inputs and outputs",
    "## Effective capabilities",
    "## Trust boundaries and controls",
    "## Known limitations",
    "## Verification",
)
SKILL_CARD_CAPABILITIES = (
    "| Reads |",
    "| Writes |",
    "| Executes |",
    "| Network |",
    "| Credentials |",
    "| External effects |",
    "| Approval gates |",
)


class FrontmatterError(ValueError):
    pass


def parse_frontmatter(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("SKILL.md must start with YAML frontmatter")
    try:
        end = next(
            index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"
        )
    except StopIteration as exc:
        raise FrontmatterError("SKILL.md frontmatter is not closed") from exc
    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise FrontmatterError(f"unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key or not value or key in fields:
            raise FrontmatterError(f"invalid or duplicate frontmatter field: {key}")
        fields[key] = value
    return fields, "\n".join(lines[end + 1 :])


def package_files(repo: Path) -> list[Path]:
    roots = [repo / "skills"]
    for name in ("README.md", "LICENSE", "requirements.txt"):
        path = repo / name
        if path.is_file():
            roots.append(path)
    files: list[Path] = []
    for root in roots:
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            relative = path.relative_to(repo)
            if (
                path.is_file()
                and not path.is_symlink()
                and not any(part in SKIP_PARTS for part in relative.parts)
                and path.suffix.casefold() not in SKIP_SUFFIXES
            ):
                files.append(path)
    return sorted(set(files))


def repository_files(repo: Path) -> list[Path]:
    files: list[Path] = []
    for path in repo.rglob("*"):
        relative = path.relative_to(repo)
        if (
            path.is_file()
            and not path.is_symlink()
            and not any(part in SKIP_PARTS for part in relative.parts)
            and path.suffix.casefold() not in SKIP_SUFFIXES
        ):
            files.append(path)
    return sorted(files)


def direct_local_references(skill_dir: Path, body: str) -> tuple[set[str], list[str]]:
    raw = set(MARKDOWN_LINK.findall(body)) | set(INLINE_PATH.findall(body))
    paths: set[str] = set()
    errors: list[str] = []
    for target in sorted(raw):
        clean = target.split("#", 1)[0]
        if not clean or "://" in clean or clean.startswith("#"):
            continue
        candidate = (skill_dir / clean).resolve()
        try:
            relative = candidate.relative_to(skill_dir.resolve())
        except ValueError:
            errors.append(f"reference escapes the Skill directory: {target}")
            continue
        if not candidate.is_file():
            errors.append(f"referenced file does not exist: {target}")
        paths.add(relative.as_posix())
    return paths, errors


def validate_agent_metadata(skill_dir: Path, skill_name: str) -> list[str]:
    path = skill_dir / "agents" / "openai.yaml"
    if not path.is_file():
        return ["agents/openai.yaml is missing"]
    text = path.read_text(encoding="utf-8")
    fields = {
        key: value
        for key, value in re.findall(
            r'^  (display_name|short_description|default_prompt): "([^"]+)"\s*$',
            text,
            flags=re.MULTILINE,
        )
    }
    errors = [
        f"interface.{key} is missing or not a quoted string"
        for key in ("display_name", "short_description", "default_prompt")
        if key not in fields
    ]
    short_description = fields.get("short_description", "")
    if short_description and not 25 <= len(short_description) <= 64:
        errors.append("interface.short_description must contain 25..64 characters")
    default_prompt = fields.get("default_prompt", "")
    if default_prompt and f"${skill_name}" not in default_prompt:
        errors.append(f"interface.default_prompt must mention ${skill_name}")
    if not re.search(
        r"^  allow_implicit_invocation: (?:true|false)\s*$", text, re.MULTILINE
    ):
        errors.append("policy.allow_implicit_invocation must be an explicit boolean")
    return errors


def validate_skill_card(skill_dir: Path) -> list[str]:
    path = skill_dir / "skill-card.md"
    if not path.is_file():
        return ["skill-card.md is missing"]
    text = path.read_text(encoding="utf-8")
    errors = [
        f"missing section: {heading}"
        for heading in SKILL_CARD_SECTIONS
        if heading not in text
    ]
    errors.extend(
        f"missing capability declaration: {capability}"
        for capability in SKILL_CARD_CAPABILITIES
        if capability not in text
    )
    return errors


def validate_activation_eval(skill_dir: Path, skill_name: str) -> list[str]:
    path = skill_dir / "evals" / "activation.json"
    if not path.is_file():
        return ["evals/activation.json is missing"]
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"activation eval is not valid JSON: {exc}"]
    if not isinstance(document, dict):
        return ["activation eval root must be an object"]
    errors: list[str] = []
    if document.get("skill") != skill_name:
        errors.append("activation eval skill does not match the Skill directory")
    cases = document.get("cases")
    if not isinstance(cases, list):
        errors.append("activation eval cases must be an array")
        cases = []
    identifiers: set[str] = set()
    positive = 0
    negative = 0
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"activation case {index} must be an object")
            continue
        identifier = case.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"activation case {index} has no stable id")
        elif identifier in identifiers:
            errors.append(f"activation case id is duplicated: {identifier}")
        else:
            identifiers.add(identifier)
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            errors.append(f"activation case {index} has no prompt")
        should_activate = case.get("should_activate")
        if should_activate is True:
            positive += 1
        elif should_activate is False:
            negative += 1
        else:
            errors.append(f"activation case {index} should_activate must be boolean")
        behavior = case.get("expected_behavior")
        if (
            not isinstance(behavior, list)
            or not behavior
            or not all(isinstance(item, str) and item.strip() for item in behavior)
        ):
            errors.append(
                f"activation case {index} needs non-empty expected_behavior strings"
            )
    if positive < 2 or negative < 2:
        errors.append(
            "activation eval requires at least two positive and two adjacent negative cases"
        )
    rubrics = document.get("rubrics")
    if not isinstance(rubrics, dict):
        errors.append("activation eval rubrics must be an object")
    else:
        missing = sorted(ACTIVATION_RUBRICS - set(rubrics))
        if missing:
            errors.append(f"activation eval rubrics are missing: {', '.join(missing)}")
        for key in ACTIVATION_RUBRICS & set(rubrics):
            if not isinstance(rubrics[key], str) or not rubrics[key].strip():
                errors.append(f"activation rubric is empty: {key}")
    return errors


def check(
    checks: list[dict[str, Any]], check_id: str, status: str, evidence: str, detail: Any
) -> None:
    checks.append(
        {"id": check_id, "status": status, "evidence": evidence, "detail": detail}
    )


def evaluate(repo: Path, topic: str) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    skills_root = repo / "skills"
    skill_dirs = (
        sorted(path for path in skills_root.iterdir() if path.is_dir())
        if skills_root.is_dir()
        else []
    )
    check(
        checks,
        "l0.single_skill",
        "pass" if len(skill_dirs) == 1 else "fail",
        "skills/",
        len(skill_dirs),
    )
    if len(skill_dirs) != 1:
        return result(repo, topic, checks, [])
    skill_dir = skill_dirs[0]
    skill_file = skill_dir / "SKILL.md"
    check(
        checks,
        "l0.skill_file",
        "pass" if skill_file.is_file() else "fail",
        str(skill_file.relative_to(repo)),
        skill_file.is_file(),
    )
    if not skill_file.is_file():
        return result(repo, topic, checks, [])

    try:
        fields, body = parse_frontmatter(skill_file)
    except (OSError, UnicodeError, FrontmatterError) as exc:
        check(
            checks,
            "l0.frontmatter",
            "fail",
            str(skill_file.relative_to(repo)),
            str(exc),
        )
        return result(repo, topic, checks, [])
    allowed_fields = {"name", "description"}
    check(
        checks,
        "l0.frontmatter_fields",
        "pass" if set(fields) == allowed_fields else "fail",
        str(skill_file.relative_to(repo)),
        sorted(fields),
    )
    name = fields.get("name", "")
    description = fields.get("description", "")
    valid_name = (
        bool(NAME.fullmatch(name)) and len(name) <= 64 and name == skill_dir.name
    )
    check(
        checks,
        "l0.name",
        "pass" if valid_name else "fail",
        str(skill_file.relative_to(repo)),
        name,
    )
    valid_description = 1 <= len(description) <= 1024
    check(
        checks,
        "l0.description",
        "pass" if valid_description else "fail",
        str(skill_file.relative_to(repo)),
        len(description),
    )

    files = package_files(repo)
    total = sum(path.stat().st_size for path in files)
    largest = max((path.stat().st_size for path in files), default=0)
    check(
        checks,
        "l0.package_size",
        "pass" if total <= TOTAL_LIMIT else "fail",
        "submission package",
        {"bytes": total, "limit": TOTAL_LIMIT},
    )
    check(
        checks,
        "l0.single_file_size",
        "pass" if largest <= FILE_LIMIT else "fail",
        "submission package",
        {"largest_bytes": largest, "limit": FILE_LIMIT},
    )

    secret_hits = []
    injection_hits = []
    for path in repository_files(repo):
        if path.suffix.casefold() not in {
            ".md",
            ".py",
            ".json",
            ".jsonl",
            ".txt",
            ".yaml",
            ".yml",
            ".toml",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        for label, pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                secret_hits.append(
                    {
                        "file": path.relative_to(repo).as_posix(),
                        "kind": label,
                        "offset": match.start(),
                    }
                )
        if path in files:
            for pattern in INJECTION_PATTERNS:
                for match in pattern.finditer(text):
                    injection_hits.append(
                        {
                            "file": path.relative_to(repo).as_posix(),
                            "offset": match.start(),
                        }
                    )
    check(
        checks,
        "l0.secrets",
        "pass" if not secret_hits else "fail",
        "repository text files",
        secret_hits,
    )
    check(
        checks,
        "l0.scoring_injection",
        "pass" if not injection_hits else "review",
        "submission text files",
        injection_hits,
    )

    line_count = len(skill_file.read_text(encoding="utf-8").splitlines())
    check(
        checks,
        "l1.skill_length",
        "pass" if line_count < 500 else "review",
        str(skill_file.relative_to(repo)),
        line_count,
    )
    references, reference_errors = direct_local_references(skill_dir, body)
    check(
        checks,
        "l1.reference_targets",
        "pass" if not reference_errors else "fail",
        str(skill_file.relative_to(repo)),
        reference_errors,
    )
    unlinked = []
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        unlinked = [
            path.relative_to(skill_dir).as_posix()
            for path in references_dir.iterdir()
            if path.is_file()
            and path.relative_to(skill_dir).as_posix() not in references
        ]
    check(
        checks,
        "l1.direct_reachability",
        "pass" if not unlinked else "review",
        str(skill_file.relative_to(repo)),
        sorted(unlinked),
    )
    agent_errors = validate_agent_metadata(skill_dir, name)
    check(
        checks,
        "l1.agent_metadata",
        "pass" if not agent_errors else "fail",
        str((skill_dir / "agents" / "openai.yaml").relative_to(repo)),
        agent_errors,
    )
    card_errors = validate_skill_card(skill_dir)
    check(
        checks,
        "l1.skill_card",
        "pass" if not card_errors else "fail",
        str((skill_dir / "skill-card.md").relative_to(repo)),
        card_errors,
    )
    activation_errors = validate_activation_eval(skill_dir, name)
    check(
        checks,
        "l1.activation_eval",
        "pass" if not activation_errors else "fail",
        str((skill_dir / "evals" / "activation.json").relative_to(repo)),
        activation_errors,
    )
    lower = body.casefold()
    check(
        checks,
        "l1.structured_contract",
        "pass"
        if ("schema" in lower and ("json" in lower or "csv" in lower))
        else "review",
        str(skill_file.relative_to(repo)),
        "Schema plus JSON/CSV expected",
    )
    check(
        checks,
        "l1.examples",
        "pass" if "```" in body else "review",
        str(skill_file.relative_to(repo)),
        "at least one fenced example expected",
    )
    scientific_terms = ("不确定", "失败", "限制", "置信", "禁止", "边界")
    present = [term for term in scientific_terms if term in body]
    check(
        checks,
        "l1.scientific_boundaries",
        "pass" if len(present) >= 3 else "review",
        str(skill_file.relative_to(repo)),
        present,
    )
    topic_terms = {
        "global-geochemical-atlas": (
            "地球化学",
            "元素",
            "岩石",
            "土壤",
            "沉积物",
            "水体",
        ),
    }.get(topic, ())
    topic_hits = [term for term in topic_terms if term in f"{description}\n{body}"]
    check(
        checks,
        "l0.topic_relevance",
        "pass" if topic_terms and len(topic_hits) >= 3 else "review",
        str(skill_file.relative_to(repo)),
        topic_hits,
    )
    check(
        checks,
        "l0.originality",
        "manual",
        "external corpus required",
        "automatic similarity screening cannot establish originality",
    )
    check(
        checks,
        "l1.llm_static_review",
        "manual",
        "independent frozen reviewer required",
        "deterministic checks prepare evidence but do not replace the L1 reviewer",
    )
    return result(repo, topic, checks, files)


def result(
    repo: Path, topic: str, checks: list[dict[str, Any]], files: list[Path]
) -> dict[str, Any]:
    failures = [item["id"] for item in checks if item["status"] == "fail"]
    reviews = [item["id"] for item in checks if item["status"] in {"review", "manual"}]
    return {
        "schema_version": "ai4s-docker-preflight-v1",
        "generated_at": utc_now(),
        "repo": str(repo),
        "topic": topic,
        "status": "fail" if failures else ("review" if reviews else "pass"),
        "checks": checks,
        "failures": failures,
        "manual_review": reviews,
        "package": {
            "files": len(files),
            "bytes": sum(path.stat().st_size for path in files),
            "sha256": hash_records(
                (path.relative_to(repo).as_posix(), sha256_file(path)) for path in files
            )
            if files
            else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path, nargs="?", default=Path.cwd())
    parser.add_argument("--topic", default="global-geochemical-atlas")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(args.repo.resolve(), args.topic)
        if args.output:
            atomic_json(args.output, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return (
            74
            if report["status"] == "fail"
            else (2 if report["status"] == "review" else 0)
        )
    except (OSError, ValueError, StopIteration) as exc:
        print(
            json.dumps({"status": "environment_invalid", "error": str(exc)}),
            file=sys.stderr,
        )
        return 73


if __name__ == "__main__":
    raise SystemExit(main())
