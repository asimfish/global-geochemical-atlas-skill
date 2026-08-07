#!/usr/bin/env python3
"""Aggregate one element into non-interpolated observed WGS84 concentration cells."""

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
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import build_interactive_map as map_builder


GRID_VERSION = "d3-observed-concentration-grid-v1"
LAYER_FIELDS = (
    "medium",
    "material",
    "sample_type",
    "measurement_basis",
    "normalized_unit",
    "matched_geologic_unit",
    "geologic_unit_raw",
    "analytical_method",
    "method_family",
    "method_scope",
    "digestion_or_extraction",
)


class ConcentrationGridError(ValueError):
    """Raised when the requested concentration aggregation is not comparable."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _profile_matches(row: Mapping[str, str], profile: Mapping[str, Any]) -> bool:
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
    method = row.get("method_family") or row.get("analytical_method")
    if filters.get("method") and filters["method"] != method:
        return False
    geology = row.get("matched_geologic_unit") or row.get("geologic_unit")
    if filters.get("geology") and filters["geology"] != geology:
        return False
    if filters.get("confidence"):
        try:
            confidence = json.loads(row.get("operational_confidence") or "{}")
        except json.JSONDecodeError:
            return False
        if (
            not isinstance(confidence, dict)
            or confidence.get("band") != filters["confidence"]
        ):
            return False
    return True


def _cell(
    value: float, size: int, minimum: float, maximum: float
) -> tuple[float, float]:
    lower = minimum + math.floor((value - minimum) / size) * size
    if math.isclose(value, maximum):
        lower = maximum - size
    return lower, min(maximum, lower + size)


def build_grid(
    database: Path, profile: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    element = profile["filters"].get("element")
    if not element:
        raise ConcentrationGridError(
            "a concentration grid requires filters.element; multi-element concentration scales are not comparable"
        )
    grid_degrees = int(profile["display"]["anomaly_grid_degrees"])
    boundaries = map_builder.load_country_boundaries(map_builder.DEFAULT_BOUNDARIES)
    countries_by_code = {
        str(country["iso_a3"]): country for country in boundaries["countries"]
    }
    region = map_builder.selected_region(profile)
    required = {
        "record_id",
        "sample_id",
        "source_id",
        "element_or_analyte",
        "latitude",
        "longitude",
        "normalized_value",
        "normalized_unit",
        "censored",
        *LAYER_FIELDS,
    }
    try:
        with database.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                missing = sorted(required - set(reader.fieldnames or []))
                raise ConcentrationGridError(
                    "canonical database lacks grid fields: " + ", ".join(missing)
                )
            rows = [dict(row) for row in reader]
    except (OSError, UnicodeError) as exc:
        raise ConcentrationGridError(
            f"canonical database is unreadable: {database}"
        ) from exc

    groups: dict[tuple[Any, ...], list[dict[str, str]]] = defaultdict(list)
    excluded = defaultdict(int)
    for row in rows:
        if row.get("element_or_analyte") != element or not _profile_matches(
            row, profile
        ):
            continue
        try:
            longitude = float(row.get("longitude") or "")
            latitude = float(row.get("latitude") or "")
        except ValueError:
            excluded["unmappable"] += 1
            continue
        if not map_builder.coordinate_in_region(
            longitude, latitude, region, countries_by_code
        ):
            excluded["outside_scope"] += 1
            continue
        west, east = _cell(longitude, grid_degrees, -180.0, 180.0)
        south, north = _cell(latitude, grid_degrees, -90.0, 90.0)
        layer = tuple(str(row.get(field) or "") for field in LAYER_FIELDS)
        groups[(west, south, east, north, *layer)].append(row)

    features: list[dict[str, Any]] = []
    for key in sorted(groups):
        west, south, east, north = (float(item) for item in key[:4])
        layer = {
            field: key[index + 4] or None for index, field in enumerate(LAYER_FIELDS)
        }
        group_rows = groups[key]
        values: list[float] = []
        censored_count = 0
        unquantified_count = 0
        for row in group_rows:
            if str(row.get("censored") or "").casefold() == "true":
                censored_count += 1
                continue
            try:
                value = float(row.get("normalized_value") or "")
            except ValueError:
                unquantified_count += 1
                continue
            if math.isfinite(value) and value >= 0:
                values.append(value)
            else:
                unquantified_count += 1
        sample_keys = {
            (row.get("source_id"), row.get("sample_id") or row.get("record_id"))
            for row in group_rows
        }
        feature_id = hashlib.sha256(
            json.dumps(key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:20]
        features.append(
            {
                "type": "Feature",
                "id": f"cell-{feature_id}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [west, south],
                            [east, south],
                            [east, north],
                            [west, north],
                            [west, south],
                        ]
                    ],
                },
                "properties": {
                    "element": element,
                    "grid_degrees": grid_degrees,
                    "record_count": len(group_rows),
                    "physical_sample_count": len(sample_keys),
                    "quantified_count": len(values),
                    "censored_count": censored_count,
                    "unquantified_count": unquantified_count,
                    "censored_fraction": round(censored_count / len(group_rows), 6),
                    "median": round(statistics.median(values), 9) if values else None,
                    "q25": round(_percentile(values, 0.25), 9) if values else None,
                    "q75": round(_percentile(values, 0.75), 9) if values else None,
                    "layer": layer,
                    "aggregation": "observed_records_only_no_interpolation",
                },
            }
        )
    scientific_boundary = (
        "Each polygon is a fixed WGS84 cell containing observations from one explicit comparable "
        "medium/basis/geology/method/unit layer. Median and quartiles use quantified values only; "
        "censored observations remain in density and censoring counts, while missing, non-finite or "
        "negative canonical values remain unquantified. Empty cells are omitted and "
        "no concentration is interpolated into unsampled space."
    )
    collection = {
        "type": "FeatureCollection",
        "grid_version": GRID_VERSION,
        "element": element,
        "input_sha256": sha256_file(database),
        "grid_degrees": grid_degrees,
        "feature_count": len(features),
        "interpolation": False,
        "scientific_boundary": scientific_boundary,
        "features": features,
    }
    summary = {
        "grid_version": GRID_VERSION,
        "element": element,
        "grid_degrees": grid_degrees,
        "feature_count": len(features),
        "included_record_count": sum(len(rows) for rows in groups.values()),
        "excluded_record_counts": dict(sorted(excluded.items())),
        "interpolation": False,
        "scientific_boundary": scientific_boundary,
    }
    return collection, summary


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
        collection, summary = build_grid(args.database, profile)
        atomic_json(args.output, collection)
    except (ConcentrationGridError, map_builder.MapBuildError, OSError) as exc:
        print(
            json.dumps(
                {"status": "invalid_input", "error": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {"status": "success", "output": str(args.output), **summary},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
