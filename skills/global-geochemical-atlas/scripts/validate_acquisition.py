#!/usr/bin/env python3
"""Validate D1 archive bundle IDs, relations and raw-value preservation offline."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_BUNDLE = SKILL_DIR / "fixtures" / "schema-v1" / "archive-bundle.json"

ENTITY_CONTRACTS = {
    "datasets": ("dataset_id", "d1-dataset-source-v1", "dataset-source.schema.json"),
    "publications": ("publication_id", "d1-publication-v1", "publication.schema.json"),
    "sampling_events": ("sampling_event_id", "d1-sampling-event-v1", "sampling-event.schema.json"),
    "samples": ("sample_id", "d1-sample-v1", "sample.schema.json"),
    "methods": ("method_id", "d1-analytical-method-v1", "analytical-method.schema.json"),
    "provenance": ("provenance_id", "d1-provenance-v1", "provenance.schema.json"),
    "observations": ("observation_id", "d1-observation-v1", "observation.schema.json"),
    "acquisition_runs": ("acquisition_run_id", "d1-acquisition-run-v1", "acquisition-run.schema.json"),
}
MISSING_REASONS = {"not_reported", "not_applicable", "not_available", "redacted", "parse_failed"}


def _matches_json_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return False


def _validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    root_schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    """Validate the deterministic JSON Schema subset used by D1 entity contracts."""

    reference = schema.get("$ref")
    if reference is not None:
        prefix = "#/$defs/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            errors.append(f"{path} uses unsupported schema reference: {reference}")
            return
        definition = root_schema.get("$defs", {}).get(reference[len(prefix) :])
        if not isinstance(definition, dict):
            errors.append(f"{path} references missing schema definition: {reference}")
            return
        _validate_schema_value(value, definition, root_schema, path, errors)
        return

    expected = schema.get("type")
    if expected is not None:
        expected_types = [expected] if isinstance(expected, str) else expected
        if not isinstance(expected_types, list) or not all(isinstance(item, str) for item in expected_types):
            errors.append(f"{path} has an invalid schema type declaration")
            return
        if not any(_matches_json_type(value, item) for item in expected_types):
            errors.append(f"{path} must have JSON type {' or '.join(expected_types)}")
            return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} is outside the allowed enum")

    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            errors.append(f"{path} is shorter than minLength={minimum_length}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            errors.append(f"{path} does not match pattern {pattern}")
        if schema.get("format") == "date-time":
            try:
                parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{path} is not an ISO 8601 date-time")
            else:
                if parsed.tzinfo is None:
                    errors.append(f"{path} date-time must include a timezone")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} is below minimum={schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} is above maximum={schema['maximum']}")

    if isinstance(value, list):
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            errors.append(f"{path} has fewer than minItems={minimum_items} entries")
        if schema.get("uniqueItems") is True:
            encoded = [json.dumps(item, ensure_ascii=False, separators=(",", ":"), sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{path} contains duplicate entries")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for position, item in enumerate(value):
                _validate_schema_value(item, item_schema, root_schema, f"{path}[{position}]", errors)

    if isinstance(value, dict):
        minimum_properties = schema.get("minProperties")
        if isinstance(minimum_properties, int) and len(value) < minimum_properties:
            errors.append(f"{path} has fewer than minProperties={minimum_properties} fields")
        required = schema.get("required", [])
        if isinstance(required, list):
            for field in required:
                if field not in value:
                    errors.append(f"{path} is missing required field: {field}")
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        for field, field_schema in properties.items():
            if field in value and isinstance(field_schema, dict):
                _validate_schema_value(value[field], field_schema, root_schema, f"{path}.{field}", errors)
        extras = sorted(set(value) - set(properties))
        additional = schema.get("additionalProperties", True)
        if additional is False and extras:
            errors.append(f"{path} contains unsupported fields: {', '.join(extras)}")
        elif isinstance(additional, dict):
            for field in extras:
                _validate_schema_value(value[field], additional, root_schema, f"{path}.{field}", errors)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"archive bundle does not exist: {path}") from exc
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"archive bundle is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError("archive bundle must be a JSON object")
    return value


def _index_entities(bundle: Mapping[str, Any], errors: list[str]) -> dict[str, dict[str, Mapping[str, Any]]]:
    indexes: dict[str, dict[str, Mapping[str, Any]]] = {}
    for collection, (id_field, expected_version, schema_name) in ENTITY_CONTRACTS.items():
        schema_path = SKILL_DIR / "references" / schema_name
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            errors.append(f"missing schema file: {schema_name}")
            schema = None
        except (UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid schema file {schema_name}: {exc}")
            schema = None
        values = bundle.get(collection)
        if not isinstance(values, list) or not values:
            errors.append(f"{collection} must be a non-empty array")
            indexes[collection] = {}
            continue
        indexed: dict[str, Mapping[str, Any]] = {}
        for position, entity in enumerate(values):
            if not isinstance(entity, dict):
                errors.append(f"{collection}[{position}] is not an object")
                continue
            if isinstance(schema, dict):
                _validate_schema_value(entity, schema, schema, f"{collection}[{position}]", errors)
            entity_id = entity.get(id_field)
            if not isinstance(entity_id, str) or not entity_id:
                errors.append(f"{collection}[{position}] has no {id_field}")
                continue
            if entity_id in indexed:
                errors.append(f"duplicate {id_field}: {entity_id}")
            indexed[entity_id] = entity
            if entity.get("schema_version") != expected_version:
                errors.append(f"{entity_id} has schema_version={entity.get('schema_version')}, expected {expected_version}")
            missing = entity.get("missing_reasons", {})
            if not isinstance(missing, dict):
                errors.append(f"{entity_id} missing_reasons must be an object")
            else:
                for field, reason in missing.items():
                    if reason not in MISSING_REASONS:
                        errors.append(f"{entity_id} has invalid missing reason for {field}: {reason}")
                    if field not in entity:
                        errors.append(f"{entity_id} missing reason names an unknown field: {field}")
                    elif entity[field] is not None:
                        errors.append(f"{entity_id} marks non-null field {field} as missing")
        indexes[collection] = indexed
    return indexes


def _require_reference(
    owner: str,
    field: str,
    value: Any,
    target: Mapping[str, Any],
    errors: list[str],
    *,
    nullable: bool = False,
) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str) or value not in target:
        errors.append(f"{owner}.{field} references missing ID: {value}")


def validate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if bundle.get("bundle_version") != "d1-archive-fixture-v1":
        errors.append("unsupported or missing bundle_version")
    indexes = _index_entities(bundle, errors)
    datasets = indexes["datasets"]
    publications = indexes["publications"]
    events = indexes["sampling_events"]
    samples = indexes["samples"]
    methods = indexes["methods"]
    provenance = indexes["provenance"]
    observations = indexes["observations"]
    runs = indexes["acquisition_runs"]

    for event_id, event in events.items():
        _require_reference(event_id, "dataset_id", event.get("dataset_id"), datasets, errors)
    for sample_id, sample in samples.items():
        _require_reference(sample_id, "sampling_event_id", sample.get("sampling_event_id"), events, errors)
        _require_reference(sample_id, "parent_sample_id", sample.get("parent_sample_id"), samples, errors, nullable=True)
        if sample.get("parent_sample_id") == sample_id:
            errors.append(f"{sample_id} cannot be its own parent")
        seen = {sample_id}
        parent_id = sample.get("parent_sample_id")
        while isinstance(parent_id, str) and parent_id in samples:
            if parent_id in seen:
                errors.append(f"sample parent cycle includes {sample_id}")
                break
            seen.add(parent_id)
            parent_id = samples[parent_id].get("parent_sample_id")
    for publication_id, publication in publications.items():
        for dataset_id in publication.get("dataset_ids", []):
            _require_reference(publication_id, "dataset_ids", dataset_id, datasets, errors)
    for method_id, method in methods.items():
        for publication_id in method.get("publication_ids", []):
            _require_reference(method_id, "publication_ids", publication_id, publications, errors)
    for provenance_id, item in provenance.items():
        _require_reference(provenance_id, "dataset_id", item.get("dataset_id"), datasets, errors)
        _require_reference(provenance_id, "acquisition_run_id", item.get("acquisition_run_id"), runs, errors)
        if not item.get("source_locator") or not item.get("input_sha256"):
            errors.append(f"{provenance_id} lacks a record locator or input hash")
    for observation_id, observation in observations.items():
        _require_reference(observation_id, "sample_id", observation.get("sample_id"), samples, errors)
        _require_reference(observation_id, "method_id", observation.get("method_id"), methods, errors)
        _require_reference(observation_id, "provenance_id", observation.get("provenance_id"), provenance, errors)
        if not observation.get("analyte_reported") or not observation.get("value_raw"):
            errors.append(f"{observation_id} lacks raw analyte or value")
        raw = str(observation.get("value_raw", "")).strip()
        qualifier = observation.get("value_qualifier")
        if raw.startswith("<") and qualifier not in {"lt", "le"}:
            errors.append(f"{observation_id} loses less-than qualifier semantics")
        if raw.startswith(">") and qualifier not in {"gt", "ge"}:
            errors.append(f"{observation_id} loses greater-than qualifier semantics")
    for run_id, run in runs.items():
        for dataset_id in run.get("dataset_ids", []):
            _require_reference(run_id, "dataset_ids", dataset_id, datasets, errors)
        counts = run.get("counts", {})
        if counts.get("observations") != len(observations):
            errors.append(f"{run_id} observation count does not reconcile")
        if not run.get("schema_versions") or not run.get("vocabulary_versions"):
            errors.append(f"{run_id} lacks schema or vocabulary versions")

    return {
        "validation_version": "d1-archive-validation-v1",
        "status": "PASS" if not errors else "FAIL",
        "entity_counts": {name: len(values) for name, values in indexes.items()},
        "errors": errors,
        "claim_boundary": "This validates archive contracts and relations, not scientific correctness of measurements.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = validate_bundle(_load(args.bundle))
    except (OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
