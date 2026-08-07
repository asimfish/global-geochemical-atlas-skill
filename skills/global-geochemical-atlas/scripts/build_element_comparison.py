#!/usr/bin/env python3
"""Build a structured same-sample, comparable-layer element-pair report."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import build_interactive_map as map_builder


COMPARISON_VERSION = "d3-element-comparison-v1"
COMPARABILITY_FIELDS = (
    "medium",
    "material",
    "sample_type",
    "soil_horizon",
    "sediment_environment",
    "water_fraction",
    "grain_fraction",
    "measurement_basis",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "analytical_method",
    "method_family",
    "method_scope",
    "digestion_or_extraction",
    "normalized_unit",
)


class ComparisonError(ValueError):
    """Raised when a comparison profile or canonical database is invalid."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _rank(values: Sequence[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: (values[index], index))
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        average = (cursor + 1 + end) / 2.0
        for position in range(cursor, end):
            ranks[ordered[position]] = average
        cursor = end
    return ranks


def _spearman(first: Sequence[float], second: Sequence[float]) -> float | None:
    if len(first) < 8 or len(first) != len(second):
        return None
    rank_first = _rank(first)
    rank_second = _rank(second)
    mean_first = statistics.fmean(rank_first)
    mean_second = statistics.fmean(rank_second)
    numerator = sum(
        (left - mean_first) * (right - mean_second)
        for left, right in zip(rank_first, rank_second, strict=True)
    )
    denominator = math.sqrt(
        sum((value - mean_first) ** 2 for value in rank_first)
        * sum((value - mean_second) ** 2 for value in rank_second)
    )
    return round(numerator / denominator, 6) if denominator else None


def _profile_record_matches(row: Mapping[str, str], profile: Mapping[str, Any]) -> bool:
    filters = profile["filters"]
    field_map = {
        "medium": "medium",
        "sample_type": "sample_type",
        "basis": "measurement_basis",
        "method_scope": "method_scope",
        "source": "source_id",
    }
    for profile_key, field in field_map.items():
        requested = filters.get(profile_key)
        if requested and row.get(field) != requested:
            return False
    requested_method = filters.get("method")
    actual_method = row.get("method_family") or row.get("analytical_method")
    if requested_method and actual_method != requested_method:
        return False
    requested_geology = filters.get("geology")
    actual_geology = row.get("matched_geologic_unit") or row.get("geologic_unit")
    if requested_geology and actual_geology != requested_geology:
        return False
    requested_confidence = filters.get("confidence")
    if requested_confidence:
        try:
            confidence = json.loads(row.get("operational_confidence") or "{}")
        except json.JSONDecodeError:
            return False
        if not isinstance(confidence, dict) or confidence.get("band") != requested_confidence:
            return False
    comparison_medium = profile["comparison"].get("medium")
    return not comparison_medium or row.get("medium") == comparison_medium


def _in_profile_region(
    row: Mapping[str, str],
    region: Mapping[str, Any],
    countries_by_code: Mapping[str, Mapping[str, Any]],
) -> bool:
    try:
        longitude = float(row.get("longitude") or "")
        latitude = float(row.get("latitude") or "")
    except ValueError:
        return False
    return map_builder.coordinate_in_region(longitude, latitude, region, countries_by_code)


def build_comparison(database: Path, profile: Mapping[str, Any]) -> dict[str, Any]:
    x_element = profile["comparison"].get("x")
    y_element = profile["comparison"].get("y")
    if not x_element or not y_element or x_element == y_element:
        raise ComparisonError("comparison profile requires two different elements")
    boundaries = map_builder.load_country_boundaries(map_builder.DEFAULT_BOUNDARIES)
    countries_by_code = {
        str(country["iso_a3"]): country for country in boundaries["countries"]
    }
    region = map_builder.selected_region(profile)
    required = {
        "record_id", "sample_id", "source_id", "element_or_analyte", "normalized_value",
        "normalized_unit", "censored", "latitude", "longitude", *COMPARABILITY_FIELDS,
    }
    try:
        with database.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                missing = sorted(required - set(reader.fieldnames or []))
                raise ComparisonError("canonical database lacks comparison fields: " + ", ".join(missing))
            raw_rows = [dict(row) for row in reader]
    except (OSError, UnicodeError) as exc:
        raise ComparisonError(f"canonical database is unreadable: {database}") from exc

    exclusions: Counter[str] = Counter()
    grouped: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    observed_by_element: Counter[str] = Counter()
    for row in raw_rows:
        element = str(row.get("element_or_analyte") or "")
        if element not in {x_element, y_element}:
            continue
        if not _profile_record_matches(row, profile):
            exclusions["profile_filter"] += 1
            continue
        if not _in_profile_region(row, region, countries_by_code):
            exclusions["outside_region_or_unmappable"] += 1
            continue
        sample_id = str(row.get("sample_id") or "").strip()
        source_id = str(row.get("source_id") or "").strip()
        if not sample_id or not source_id:
            exclusions["missing_stable_physical_sample_identity"] += 1
            continue
        if str(row.get("censored") or "").casefold() == "true":
            exclusions["censored"] += 1
            continue
        value = _finite_positive(row.get("normalized_value"))
        if value is None:
            exclusions["nonpositive_or_unstandardized"] += 1
            continue
        comparison_key = tuple(str(row.get(field) or "") for field in COMPARABILITY_FIELDS)
        key = (source_id, sample_id, *comparison_key)
        grouped[key][element].append({"row": row, "value": value})
        observed_by_element[element] += 1

    paired_records: list[dict[str, Any]] = []
    ambiguous_groups = 0
    x_only = 0
    y_only = 0
    for key in sorted(grouped):
        observations = grouped[key]
        x_values = observations.get(str(x_element), [])
        y_values = observations.get(str(y_element), [])
        if len(x_values) > 1 or len(y_values) > 1:
            ambiguous_groups += 1
            continue
        if not x_values:
            y_only += 1
            continue
        if not y_values:
            x_only += 1
            continue
        x_item = x_values[0]
        y_item = y_values[0]
        comparison = {
            field: key[index + 2] for index, field in enumerate(COMPARABILITY_FIELDS)
        }
        paired_records.append(
            {
                "source_id": key[0],
                "sample_id": key[1],
                "x_record_id": x_item["row"]["record_id"],
                "y_record_id": y_item["row"]["record_id"],
                "x_value": x_item["value"],
                "y_value": y_item["value"],
                "x_log10": round(math.log10(x_item["value"]), 9),
                "y_log10": round(math.log10(y_item["value"]), 9),
                "comparability": comparison,
            }
        )
    x_logs = [item["x_log10"] for item in paired_records]
    y_logs = [item["y_log10"] for item in paired_records]
    x_median = statistics.median(x_logs) if x_logs else None
    y_median = statistics.median(y_logs) if y_logs else None
    quadrants: Counter[str] = Counter()
    if x_median is not None and y_median is not None:
        for item in paired_records:
            x_side = "high" if item["x_log10"] >= x_median else "low"
            y_side = "high" if item["y_log10"] >= y_median else "low"
            quadrants[f"{x_side}_{y_side}"] += 1
    return {
        "comparison_version": COMPARISON_VERSION,
        "status": "success" if len(paired_records) >= 8 else "insufficient_pairs",
        "elements": {"x": x_element, "y": y_element},
        "input_sha256": sha256_file(database),
        "filters": {
            "profile": profile["filters"],
            "comparison_medium": profile["comparison"].get("medium"),
            "spatial_scope": {
                "region_key": profile["default_region"],
                "label": region["label"],
                "bounds": region["bounds"],
                "country_code": region.get("country_code"),
                "clip_method": region["clip_method"],
            },
            "comparability_fields": list(COMPARABILITY_FIELDS),
        },
        "coverage": {
            "eligible_x_observation_count": observed_by_element[str(x_element)],
            "eligible_y_observation_count": observed_by_element[str(y_element)],
            "paired_sample_layer_count": len(paired_records),
            "x_only_sample_layer_count": x_only,
            "y_only_sample_layer_count": y_only,
            "ambiguous_replicate_group_count": ambiguous_groups,
        },
        "statistics": {
            "spearman_rho": _spearman(x_logs, y_logs),
            "x_log10_median": round(x_median, 9) if x_median is not None else None,
            "y_log10_median": round(y_median, 9) if y_median is not None else None,
            "quadrant_counts": dict(sorted(quadrants.items())),
        },
        "paired_records": paired_records,
        "exclusions": dict(sorted(exclusions.items())),
        "scientific_boundary": (
            "Pairs share source, physical sample identity, medium/material/sample context, basis, "
            "geology, method, extraction and canonical unit. Censored, nonpositive and ambiguous "
            "replicate groups are excluded. Spearman association is descriptive and does not prove causality."
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        profile = map_builder.load_visualization_profile(args.profile)
        report = build_comparison(args.database, profile)
        atomic_json(args.output, report)
    except (ComparisonError, map_builder.MapBuildError, OSError) as exc:
        print(json.dumps({"status": "invalid_input", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": report["status"],
                "paired_sample_layer_count": report["coverage"]["paired_sample_layer_count"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
