#!/usr/bin/env python3
"""Shared, standard-library-only helpers for the D2 validation lab."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
D2_SCRIPT = REPO_ROOT / "workstreams" / "d2" / "scripts" / "geochem_d2_pipeline.py"
D2_FIXTURE = REPO_ROOT / "workstreams" / "d2" / "fixtures" / "demo_input.csv"
D2_SCHEMA = REPO_ROOT / "workstreams" / "d2" / "schema.json"
D2_MANIFEST_SCHEMA = REPO_ROOT / "workstreams" / "d2" / "contracts" / "run-manifest.schema.json"
LAB_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = LAB_ROOT / "contracts"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json_text(value))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_empty_output_dir(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"output directory must not exist or must be empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def repository_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


def load_d2_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("d2_validation_target", D2_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import D2 module: {D2_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class CheckResult:
    name: str
    category: str
    severity: str
    passed: bool
    expected: Any = None
    actual: Any = None
    note: str | None = None


class CheckBook:
    """Collect machine-readable blocking and review checks without hiding failures."""

    def __init__(self) -> None:
        self._checks: list[CheckResult] = []

    def add(
        self,
        name: str,
        passed: bool,
        *,
        category: str,
        severity: str = "blocking",
        expected: Any = None,
        actual: Any = None,
        note: str | None = None,
    ) -> None:
        if severity not in {"blocking", "review"}:
            raise ValueError(f"unsupported severity: {severity}")
        self._checks.append(
            CheckResult(
                name=name,
                category=category,
                severity=severity,
                passed=bool(passed),
                expected=expected,
                actual=actual,
                note=note,
            )
        )

    @property
    def checks(self) -> list[CheckResult]:
        return list(self._checks)

    def summary(self) -> dict[str, Any]:
        counts: dict[str, dict[str, int]] = {}
        for severity in ("blocking", "review"):
            selected = [check for check in self._checks if check.severity == severity]
            counts[severity] = {
                "total": len(selected),
                "passed": sum(check.passed for check in selected),
                "failed": sum(not check.passed for check in selected),
            }
        if counts["blocking"]["failed"]:
            status = "fail"
        elif counts["review"]["failed"]:
            status = "pass_with_findings"
        else:
            status = "pass"
        findings = [asdict(check) for check in self._checks if not check.passed]
        return {
            "status": status,
            "counts": counts,
            "review_required": bool(counts["review"]["failed"]),
            "findings": findings,
            "checks": [asdict(check) for check in self._checks],
        }
