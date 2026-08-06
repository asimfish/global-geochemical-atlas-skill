#!/usr/bin/env python3
"""Build and validate the submission contract visible to a tested AI.

The visible contract exposes output shape, never gold values or checker points.
It is embedded in each task.json so an isolated candidate can construct the
legacy logical evidence inside the E1 run manifest without reading evaluator
files.
"""

from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "e2.candidate-visible.v1"
MARKER_START = "<!-- candidate-visible-contract-v1:start -->"
MARKER_END = "<!-- candidate-visible-contract-v1:end -->"
CSV_ROW_ENCODING = "array_of_objects_keyed_by_column_name"


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"unsupported JSON value type: {type(value).__name__}")


def _merge_schema(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    if left == right:
        return deepcopy(left)
    left_type = left.get("type")
    right_type = right.get("type")
    if {left_type, right_type} <= {"integer", "number"}:
        return {"type": "number"}
    if left_type != right_type:
        variants: list[dict[str, Any]] = []
        for schema in (left, right):
            for candidate in schema.get("anyOf", [schema]):
                if candidate not in variants:
                    variants.append(deepcopy(candidate))
        return {"anyOf": variants}
    if left_type == "object":
        left_properties = left.get("properties", {})
        right_properties = right.get("properties", {})
        properties: dict[str, Any] = {}
        for key in sorted(set(left_properties) | set(right_properties)):
            if key in left_properties and key in right_properties:
                properties[key] = _merge_schema(left_properties[key], right_properties[key])
            elif key in left_properties:
                properties[key] = deepcopy(left_properties[key])
            else:
                properties[key] = deepcopy(right_properties[key])
        required = sorted(set(left.get("required", [])) & set(right.get("required", [])))
        return {"type": "object", "required": required, "properties": properties}
    if left_type == "array":
        return {
            "type": "array",
            "items": _merge_schema(left.get("items", {}), right.get("items", {})),
        }
    return {"type": left_type}


def json_shape(value: Any) -> dict[str, Any]:
    """Return a value-free JSON shape suitable for candidate-visible metadata."""

    value_type = _json_type(value)
    if value_type == "object":
        properties = {key: json_shape(item) for key, item in sorted(value.items())}
        return {"type": "object", "required": sorted(value), "properties": properties}
    if value_type == "array":
        if not value:
            return {"type": "array", "items": {}}
        item_schema = json_shape(value[0])
        for item in value[1:]:
            item_schema = _merge_schema(item_schema, json_shape(item))
        return {"type": "array", "items": item_schema}
    return {"type": value_type}


def _output_contract(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            columns = next(csv.reader(handle), [])
        return {
            "format": "csv",
            "columns": columns,
            "row_encoding": CSV_ROW_ENCODING,
            "null_encoding": "empty_string_or_null",
        }
    if suffix in {".json", ".geojson"}:
        value = json.loads(path.read_text(encoding="utf-8"))
        return {"format": "json", "json_shape": json_shape(value)}
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        shape = json_shape(rows[0]) if rows else {}
        for row in rows[1:]:
            shape = _merge_schema(shape, json_shape(row))
        return {"format": "jsonl", "row_shape": shape}
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {"format": "base64", "encoding": "RFC4648 base64 string"}
    return {"format": "text", "encoding": "UTF-8"}


def build_candidate_visible_contract(
    task_dir: Path, legacy_outputs: list[str], container: str
) -> dict[str, Any]:
    logical_outputs: dict[str, Any] = {}
    for relative in legacy_outputs:
        source = task_dir / "gold" / relative
        if not source.is_file():
            raise FileNotFoundError(f"{task_dir.name}: missing legacy gold evidence {relative}")
        logical_outputs[relative] = _output_contract(source)
    return {
        "schema_version": SCHEMA_VERSION,
        "container": container,
        "field": "benchmark_evidence",
        "logical_outputs": logical_outputs,
    }


def _schema_at_path(schema: dict[str, Any], path: str) -> dict[str, Any] | None:
    current = schema
    for token in path.removeprefix("$.").split(".") if path not in {"", "$"} else []:
        if "anyOf" in current:
            options = [_schema_at_path(option, ".".join([token])) for option in current["anyOf"]]
            current = next((option for option in options if option is not None), {})
            continue
        if current.get("type") == "array":
            if not token.isdigit():
                return None
            current = current.get("items", {})
        elif current.get("type") == "object":
            current = current.get("properties", {}).get(token)
            if current is None:
                return None
        else:
            return None
    return current


def validate_candidate_visible_contract(
    task_dir: Path, metadata: dict[str, Any], grader_spec: dict[str, Any]
) -> list[str]:
    """Return candidate-contract errors for one task without exposing values."""

    errors: list[str] = []
    question = task_dir.name
    contract = metadata.get("candidate_visible_contract")
    if not isinstance(contract, dict):
        return [f"{question}: missing task.json candidate_visible_contract"]
    if contract.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{question}: candidate_visible_contract schema_version mismatch")
    if contract.get("container") != metadata.get("benchmark_evidence_container"):
        errors.append(f"{question}: candidate contract container mismatch")
    if contract.get("field") != "benchmark_evidence":
        errors.append(f"{question}: candidate contract field must be benchmark_evidence")
    outputs = contract.get("logical_outputs")
    if not isinstance(outputs, dict):
        return [*errors, f"{question}: candidate contract logical_outputs must be an object"]
    expected_outputs = set(metadata.get("legacy_logical_outputs", []))
    if set(outputs) != expected_outputs:
        errors.append(
            f"{question}: candidate contract logical output set mismatch; "
            f"expected={sorted(expected_outputs)}, actual={sorted(outputs)}"
        )

    task_text = (task_dir / "task.md").read_text(encoding="utf-8")
    if MARKER_START not in task_text or MARKER_END not in task_text:
        errors.append(f"{question}: task.md missing candidate-visible contract marker block")

    for check in [*grader_spec.get("checks", []), *grader_spec.get("redlines", [])]:
        relative = check.get("path")
        if relative not in outputs:
            errors.append(f"{question}: checker {check.get('id')} path {relative!r} is not candidate-visible")
            continue
        output = outputs[relative]
        check_type = str(check.get("type", ""))
        fmt = output.get("format")
        if check_type.startswith("csv_"):
            if fmt != "csv":
                errors.append(f"{question}: checker {check.get('id')} requires CSV but contract says {fmt}")
                continue
            if output.get("row_encoding") != CSV_ROW_ENCODING:
                errors.append(f"{question}: {relative} does not require object-encoded CSV rows")
            declared = set(output.get("columns", []))
            referenced: set[str] = set()
            referenced.update(str(item) for item in check.get("required", []))
            referenced.update(str(item) for item in check.get("columns", []))
            referenced.update(str(item) for item in check.get("key", {}))
            if check.get("column"):
                referenced.add(str(check["column"]))
            missing = sorted(referenced - declared)
            if missing:
                errors.append(
                    f"{question}: checker {check.get('id')} references undeclared CSV columns {missing} in {relative}"
                )
        elif check_type.startswith("jsonl_"):
            if fmt != "jsonl":
                errors.append(f"{question}: checker {check.get('id')} requires JSONL but contract says {fmt}")
        elif check_type.startswith("json_"):
            if fmt != "json":
                errors.append(f"{question}: checker {check.get('id')} requires JSON but contract says {fmt}")
                continue
            json_path = str(check.get("json_path", ""))
            target = _schema_at_path(output.get("json_shape", {}), json_path)
            if target is None:
                errors.append(
                    f"{question}: checker {check.get('id')} JSON path {json_path!r} is absent from candidate schema"
                )
                continue
            required_keys = set(str(item) for item in check.get("required", []))
            properties = set(target.get("properties", {})) if isinstance(target, dict) else set()
            missing = sorted(required_keys - properties)
            if missing:
                errors.append(
                    f"{question}: checker {check.get('id')} requires undeclared JSON keys {missing} at {json_path}"
                )
    return errors
