#!/usr/bin/env python3
"""Build the optional research_mode post-processing products.

This layer consumes one completed, validated atlas run directory and reorganizes
existing evidence into three researcher-facing products plus a receipt:

1. analysis_cohorts.csv / analysis_cohort_exclusions.csv  (research cohorts)
2. research_context.csv                                   (per-sample context)
3. sampling_priority.geojson                              (gap-driven sampling)
4. research_products_receipt.json                         (model-card receipt)

It never acquires new data, never edits core deliverables, uses only the Python
standard library, performs a single streaming pass over geochemistry.csv and
emits deterministically sorted outputs. See references/research-mode.md.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TOOL_VERSION = "research-mode-v1"

BAND_ORDER = {"low": 0, "medium": 1, "high": 2}

COHORT_KEY_FIELDS = (
    "element_or_analyte",
    "medium",
    "sample_type",
    "grain_fraction",
    "measurement_basis",
    "method_family",
    "digestion_or_extraction",
    "unit_layer",
)

# Tier thresholds intentionally mirror the D2 production background gates.
TIER_MIN_QUANTIFIED_SAMPLES = 20
TIER_MIN_QUANTIFIED_FRACTION = 0.7
TIER_EXPLORATORY_MIN_SAMPLES = 8
TIER_MAX_SINGLE_SOURCE_SHARE = 0.9

EXTERNAL_COVARIATE_INTERFACE = [
    {
        "covariate_family": "climate_reanalysis",
        "candidate_source": "ERA5-Land (Copernicus Climate Data Store)",
        "official_url": "https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land",
        "status": "declared_interface_not_fetched",
    },
    {
        "covariate_family": "hydrological_basins",
        "candidate_source": "HydroBASINS (HydroSHEDS)",
        "official_url": "https://www.hydrosheds.org/products/hydrobasins",
        "status": "declared_interface_not_fetched",
    },
    {
        "covariate_family": "soil_properties",
        "candidate_source": "SoilGrids (ISRIC)",
        "official_url": "https://docs.isric.org/globaldata/soilgrids/index.html",
        "status": "declared_interface_not_fetched",
    },
]

NON_CLAIMS = [
    "cohorts, context rows and sampling priorities are screening/data-preparation "
    "products, not pollution, mineralization, weathering-rate or climate-mechanism conclusions",
    "latitude_band is a geometric latitude class, not a climate observation",
    "no interpolation surface is built and no observation is fabricated for empty areas",
    "spatial emptiness means missing evidence, not absence of natural signal",
    "tiers describe comparability under current evidence, not data quality or scientific truth",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latitude_band(lat: float) -> str:
    abs_lat = abs(lat)
    if abs_lat >= 66.5:
        return "polar"
    if abs_lat >= 55.0:
        return "subpolar"
    if abs_lat >= 35.0:
        return "temperate"
    if abs_lat >= 23.5:
        return "subtropical"
    return "tropical"


def parse_float(text: str) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


class CohortStats:
    __slots__ = (
        "quantified",
        "censored",
        "not_normalized",
        "quantified_samples",
        "source_counts",
        "bbox",
        "with_coordinates",
        "with_geology_match",
        "band_counts",
        "sampled_at_min",
        "sampled_at_max",
    )

    def __init__(self) -> None:
        self.quantified = 0
        self.censored = 0
        self.not_normalized = 0
        self.quantified_samples: set[str] = set()
        self.source_counts: Counter[str] = Counter()
        self.bbox: list[float] | None = None
        self.with_coordinates = 0
        self.with_geology_match = 0
        self.band_counts: Counter[str] = Counter()
        self.sampled_at_min = ""
        self.sampled_at_max = ""

    def add_bbox_point(self, lon: float, lat: float) -> None:
        if self.bbox is None:
            self.bbox = [lon, lat, lon, lat]
        else:
            self.bbox[0] = min(self.bbox[0], lon)
            self.bbox[1] = min(self.bbox[1], lat)
            self.bbox[2] = max(self.bbox[2], lon)
            self.bbox[3] = max(self.bbox[3], lat)

    def add_sampled_at(self, sampled_at: str) -> None:
        if not sampled_at:
            return
        if not self.sampled_at_min or sampled_at < self.sampled_at_min:
            self.sampled_at_min = sampled_at
        if not self.sampled_at_max or sampled_at > self.sampled_at_max:
            self.sampled_at_max = sampled_at


class SampleContext:
    __slots__ = (
        "sample_key",
        "sample_id",
        "source_ids",
        "medium",
        "sample_type",
        "latitude",
        "longitude",
        "coordinate_status",
        "lithology",
        "matched_geologic_unit",
        "geologic_unit_id",
        "sediment_environment",
        "water_body_type",
        "grain_fraction",
        "depth_min_m",
        "depth_max_m",
        "sampled_at_min",
        "sampled_at_max",
        "elements",
        "n_records",
    )

    def __init__(self, sample_key: str, sample_id: str) -> None:
        self.sample_key = sample_key
        self.sample_id = sample_id
        self.source_ids: set[str] = set()
        self.medium = ""
        self.sample_type = ""
        self.latitude: float | None = None
        self.longitude: float | None = None
        self.coordinate_status = ""
        self.lithology = ""
        self.matched_geologic_unit = ""
        self.geologic_unit_id = ""
        self.sediment_environment = ""
        self.water_body_type = ""
        self.grain_fraction = ""
        self.depth_min_m: float | None = None
        self.depth_max_m: float | None = None
        self.sampled_at_min = ""
        self.sampled_at_max = ""
        self.elements: set[str] = set()
        self.n_records = 0


def keep_first(current: str, candidate: str) -> str:
    return current if current else candidate


def cohort_tier(stats: CohortStats) -> str:
    total_candidates = stats.quantified + stats.censored + stats.not_normalized
    quantified_fraction = (
        stats.quantified / total_candidates if total_candidates else 0.0
    )
    n_samples = len(stats.quantified_samples)
    n_sources = len(stats.source_counts)
    max_share = (
        max(stats.source_counts.values()) / stats.quantified
        if stats.quantified
        else 0.0
    )
    if (
        n_samples >= TIER_MIN_QUANTIFIED_SAMPLES
        and quantified_fraction >= TIER_MIN_QUANTIFIED_FRACTION
    ):
        if n_sources >= 2 and max_share <= TIER_MAX_SINGLE_SOURCE_SHARE:
            return "analysis_ready"
        return "single_lineage_ready"
    if n_samples >= TIER_EXPLORATORY_MIN_SAMPLES:
        return "exploratory_only"
    return "insufficient_background"


def process_database(
    database_path: Path, minimum_band: int
) -> tuple[dict[tuple[str, ...], CohortStats], dict[str, SampleContext], Counter, int]:
    cohorts: dict[tuple[str, ...], CohortStats] = {}
    samples: dict[str, SampleContext] = {}
    exclusions: Counter[tuple[str, str, str]] = Counter()
    total_rows = 0

    with database_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            total_rows += 1
            element = row.get("element_or_analyte", "")
            medium = row.get("medium", "")
            if not element or not medium:
                exclusions[("missing_element_or_medium", element, medium)] += 1
                continue

            confidence_raw = row.get("operational_confidence", "")
            workflow_band = ""
            coordinate_status = ""
            try:
                confidence = json.loads(confidence_raw) if confidence_raw else {}
                dimensions = confidence.get("quality_dimensions", {})
                workflow_band = dimensions.get("workflow_usability", {}).get("band", "")
                coordinate_status = dimensions.get("spatial_usability", {}).get(
                    "coordinate_status", ""
                )
            except (json.JSONDecodeError, AttributeError):
                exclusions[("unparseable_confidence", element, medium)] += 1
                continue
            if workflow_band not in BAND_ORDER:
                exclusions[("missing_workflow_band", element, medium)] += 1
                continue
            if BAND_ORDER[workflow_band] < minimum_band:
                exclusions[("below_minimum_confidence", element, medium)] += 1
                continue

            unit_layer = row.get("normalized_unit", "") or row.get("original_unit", "")
            key = (
                element,
                medium,
                row.get("sample_type", ""),
                row.get("grain_fraction", ""),
                row.get("measurement_basis", ""),
                row.get("method_family", ""),
                row.get("digestion_or_extraction", ""),
                unit_layer,
            )
            stats = cohorts.get(key)
            if stats is None:
                stats = cohorts[key] = CohortStats()

            source_id = row.get("source_id", "")
            sample_id = row.get("sample_id", "")
            identity_group = row.get("sample_identity_group", "")
            sample_key = identity_group or f"{source_id}::{sample_id}"

            censored = row.get("censored", "") == "true"
            normalized_value = parse_float(row.get("normalized_value", ""))
            latitude = parse_float(row.get("latitude", ""))
            longitude = parse_float(row.get("longitude", ""))
            sampled_at = row.get("sampled_at", "")

            stats.band_counts[workflow_band] += 1
            if censored:
                stats.censored += 1
            elif normalized_value is None:
                stats.not_normalized += 1
            else:
                stats.quantified += 1
                stats.quantified_samples.add(sample_key)
                stats.source_counts[source_id] += 1
                stats.add_sampled_at(sampled_at)
                if latitude is not None and longitude is not None:
                    stats.with_coordinates += 1
                    stats.add_bbox_point(longitude, latitude)
                if row.get("matched_geologic_unit", "") or row.get(
                    "geologic_unit_id", ""
                ):
                    stats.with_geology_match += 1

            context = samples.get(sample_key)
            if context is None:
                context = samples[sample_key] = SampleContext(sample_key, sample_id)
            context.n_records += 1
            context.elements.add(element)
            if source_id:
                context.source_ids.add(source_id)
            context.medium = keep_first(context.medium, medium)
            context.sample_type = keep_first(
                context.sample_type, row.get("sample_type", "")
            )
            if (
                context.latitude is None
                and latitude is not None
                and longitude is not None
            ):
                context.latitude = latitude
                context.longitude = longitude
                context.coordinate_status = coordinate_status
            context.lithology = keep_first(context.lithology, row.get("lithology", ""))
            context.matched_geologic_unit = keep_first(
                context.matched_geologic_unit, row.get("matched_geologic_unit", "")
            )
            context.geologic_unit_id = keep_first(
                context.geologic_unit_id, row.get("geologic_unit_id", "")
            )
            context.sediment_environment = keep_first(
                context.sediment_environment, row.get("sediment_environment", "")
            )
            context.water_body_type = keep_first(
                context.water_body_type, row.get("water_body_type", "")
            )
            context.grain_fraction = keep_first(
                context.grain_fraction, row.get("grain_fraction", "")
            )
            depth_min = parse_float(row.get("sample_depth_min_m", ""))
            depth_max = parse_float(row.get("sample_depth_max_m", ""))
            if depth_min is not None and (
                context.depth_min_m is None or depth_min < context.depth_min_m
            ):
                context.depth_min_m = depth_min
            if depth_max is not None and (
                context.depth_max_m is None or depth_max > context.depth_max_m
            ):
                context.depth_max_m = depth_max
            if sampled_at:
                if not context.sampled_at_min or sampled_at < context.sampled_at_min:
                    context.sampled_at_min = sampled_at
                if not context.sampled_at_max or sampled_at > context.sampled_at_max:
                    context.sampled_at_max = sampled_at

    return cohorts, samples, exclusions, total_rows


def cohort_id_for(key: tuple[str, ...]) -> str:
    digest = hashlib.sha256("|".join(key).encode("utf-8")).hexdigest()
    return f"cohort-{digest[:12]}"


def write_cohorts_csv(
    path: Path, cohorts: dict[tuple[str, ...], CohortStats]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(cohorts):
        stats = cohorts[key]
        total_candidates = stats.quantified + stats.censored + stats.not_normalized
        quantified_fraction = (
            stats.quantified / total_candidates if total_candidates else 0.0
        )
        dominant_source = ""
        dominant_share = 0.0
        if stats.quantified and stats.source_counts:
            dominant_source, dominant_count = max(
                stats.source_counts.items(), key=lambda item: (item[1], item[0])
            )
            dominant_share = dominant_count / stats.quantified
        bbox = stats.bbox or ["", "", "", ""]
        rows.append(
            {
                "cohort_id": cohort_id_for(key),
                **dict(zip(COHORT_KEY_FIELDS, key)),
                "comparability_tier": cohort_tier(stats),
                "n_quantified_records": stats.quantified,
                "n_censored_records": stats.censored,
                "n_not_normalized_records": stats.not_normalized,
                "quantified_fraction": round(quantified_fraction, 4),
                "n_quantified_samples": len(stats.quantified_samples),
                "n_sources": len(stats.source_counts),
                "source_ids": ";".join(sorted(stats.source_counts)),
                "dominant_source_id": dominant_source,
                "dominant_source_share": round(dominant_share, 4),
                "n_with_coordinates": stats.with_coordinates,
                "n_with_geology_match": stats.with_geology_match,
                "workflow_band_high": stats.band_counts.get("high", 0),
                "workflow_band_medium": stats.band_counts.get("medium", 0),
                "workflow_band_low": stats.band_counts.get("low", 0),
                "bbox_west": bbox[0],
                "bbox_south": bbox[1],
                "bbox_east": bbox[2],
                "bbox_north": bbox[3],
                "sampled_at_min": stats.sampled_at_min,
                "sampled_at_max": stats.sampled_at_max,
            }
        )
    if rows:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("", encoding="utf-8")
    return rows


def write_exclusions_csv(path: Path, exclusions: Counter) -> int:
    header = ["exclusion_reason", "element_or_analyte", "medium", "n_records"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for (reason, element, medium), count in sorted(exclusions.items()):
            writer.writerow([reason, element, medium, count])
    return sum(exclusions.values())


def write_context_csv(path: Path, samples: dict[str, SampleContext]) -> int:
    header = [
        "sample_key",
        "sample_id",
        "source_ids",
        "medium",
        "sample_type",
        "latitude",
        "longitude",
        "coordinate_status",
        "latitude_band",
        "lithology",
        "matched_geologic_unit",
        "geologic_unit_id",
        "sediment_environment",
        "water_body_type",
        "grain_fraction",
        "sample_depth_min_m",
        "sample_depth_max_m",
        "sampled_at_min",
        "sampled_at_max",
        "n_elements",
        "elements",
        "n_records",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for sample_key in sorted(samples):
            context = samples[sample_key]
            band = (
                latitude_band(context.latitude) if context.latitude is not None else ""
            )
            writer.writerow(
                [
                    context.sample_key,
                    context.sample_id,
                    ";".join(sorted(context.source_ids)),
                    context.medium,
                    context.sample_type,
                    "" if context.latitude is None else context.latitude,
                    "" if context.longitude is None else context.longitude,
                    context.coordinate_status,
                    band,
                    context.lithology,
                    context.matched_geologic_unit,
                    context.geologic_unit_id,
                    context.sediment_environment,
                    context.water_body_type,
                    context.grain_fraction,
                    "" if context.depth_min_m is None else context.depth_min_m,
                    "" if context.depth_max_m is None else context.depth_max_m,
                    context.sampled_at_min,
                    context.sampled_at_max,
                    len(context.elements),
                    ";".join(sorted(context.elements)),
                    context.n_records,
                ]
            )
    return len(samples)


def bbox_polygon(bbox: list[float] | None) -> dict[str, Any] | None:
    if not bbox or len(bbox) != 4:
        return None
    west, south, east, north = bbox
    return {
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
    }


def build_sampling_priority(
    repair_queue: dict[str, Any], cohort_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []

    tasks = repair_queue.get("tasks", [])
    for task in sorted(
        tasks, key=lambda item: (item.get("priority", 10**9), item.get("task_id", ""))
    ):
        observed = task.get("observed", {})
        features.append(
            {
                "type": "Feature",
                "geometry": bbox_polygon(task.get("bbox")),
                "properties": {
                    "gap_kind": "coverage_repair_task",
                    "task_id": task.get("task_id", ""),
                    "task_kind": task.get("task_kind", ""),
                    "view_id": task.get("view_id", ""),
                    "scope_key": task.get("scope_key", ""),
                    "priority": task.get("priority"),
                    "status": task.get("status", ""),
                    "country_name": task.get("country_name", ""),
                    "country_iso_a3": task.get("country_iso_a3", ""),
                    "macroregion": task.get("macroregion", ""),
                    "reason_codes": task.get("reason_codes", []),
                    "required_elements": task.get("required_elements", []),
                    "required_media": task.get("required_media", []),
                    "preferred_repair_mode": task.get("preferred_repair_mode", ""),
                    "observed_canonical_grid_cells": observed.get(
                        "canonical_occupied_grid_cells"
                    ),
                    "observed_canonical_unique_samples": observed.get(
                        "canonical_unique_samples"
                    ),
                    "registered_source_candidates": task.get(
                        "registered_source_candidates", []
                    ),
                    "discovery_platform_sequence": task.get(
                        "discovery_platform_sequence", []
                    ),
                    "recommended_action": "targeted source discovery or new sampling "
                    "inside bbox; bbox is a search scope, not an administrative or "
                    "scientific boundary",
                },
            }
        )

    dominated = [
        row
        for row in cohort_rows
        if row["comparability_tier"] == "single_lineage_ready"
    ]
    for row in sorted(
        dominated, key=lambda item: (-item["dominant_source_share"], item["cohort_id"])
    ):
        bbox = (
            [
                row["bbox_west"],
                row["bbox_south"],
                row["bbox_east"],
                row["bbox_north"],
            ]
            if row["bbox_west"] != ""
            else None
        )
        features.append(
            {
                "type": "Feature",
                "geometry": bbox_polygon(bbox),
                "properties": {
                    "gap_kind": "single_source_dominated_cohort",
                    "cohort_id": row["cohort_id"],
                    "element_or_analyte": row["element_or_analyte"],
                    "medium": row["medium"],
                    "sample_type": row["sample_type"],
                    "method_family": row["method_family"],
                    "unit_layer": row["unit_layer"],
                    "n_quantified_samples": row["n_quantified_samples"],
                    "dominant_source_id": row["dominant_source_id"],
                    "dominant_source_share": row["dominant_source_share"],
                    "recommended_action": "acquire an independent source lineage for "
                    "this cohort instead of re-sampling the same footprint",
                },
            }
        )

    return {
        "type": "FeatureCollection",
        "name": "sampling_priority",
        "generated_by": TOOL_VERSION,
        "claim_boundary": "features are prioritized evidence-gap candidates for the "
        "next retrieval or sampling round; they are not statements about natural "
        "abundance, pollution or any administrative boundary",
        "features": features,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--research-dir", type=Path, default=None)
    parser.add_argument(
        "--minimum-confidence",
        choices=sorted(BAND_ORDER, key=BAND_ORDER.get),
        default="medium",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    research_dir: Path = args.research_dir or output_dir / "research"

    required_inputs = {
        "geochemistry.csv": output_dir / "geochemistry.csv",
        "d1_repair_queue.json": output_dir / "d1_repair_queue.json",
        "sources_and_confidence.json": output_dir / "sources_and_confidence.json",
        "run_summary.json": output_dir / "run_summary.json",
    }
    missing = [name for name, path in required_inputs.items() if not path.is_file()]
    if missing:
        print(f"missing required inputs: {', '.join(missing)}", file=sys.stderr)
        return 2

    research_dir.mkdir(parents=True, exist_ok=True)

    input_hashes = {
        name: sha256_file(path) for name, path in sorted(required_inputs.items())
    }
    repair_queue = json.loads(
        required_inputs["d1_repair_queue.json"].read_text(encoding="utf-8")
    )
    run_summary = json.loads(
        required_inputs["run_summary.json"].read_text(encoding="utf-8")
    )

    minimum_band = BAND_ORDER[args.minimum_confidence]
    cohorts, samples, exclusions, total_rows = process_database(
        required_inputs["geochemistry.csv"], minimum_band
    )

    cohort_rows = write_cohorts_csv(research_dir / "analysis_cohorts.csv", cohorts)
    excluded_rows = write_exclusions_csv(
        research_dir / "analysis_cohort_exclusions.csv", exclusions
    )
    n_samples = write_context_csv(research_dir / "research_context.csv", samples)

    sampling_priority = build_sampling_priority(repair_queue, cohort_rows)
    (research_dir / "sampling_priority.geojson").write_text(
        json.dumps(sampling_priority, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )

    tier_counts = Counter(row["comparability_tier"] for row in cohort_rows)
    receipt = {
        "tool_version": TOOL_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "parameters": {
            "minimum_confidence": args.minimum_confidence,
            "cohort_key_fields": list(COHORT_KEY_FIELDS),
            "tier_thresholds": {
                "min_quantified_samples": TIER_MIN_QUANTIFIED_SAMPLES,
                "min_quantified_fraction": TIER_MIN_QUANTIFIED_FRACTION,
                "exploratory_min_samples": TIER_EXPLORATORY_MIN_SAMPLES,
                "max_single_source_share": TIER_MAX_SINGLE_SOURCE_SHARE,
            },
        },
        "inputs": {
            "output_dir": str(output_dir),
            "sha256": input_hashes,
            "upstream_run_status": run_summary.get("status", ""),
        },
        "counts": {
            "database_rows_scanned": total_rows,
            "rows_excluded_before_cohorts": excluded_rows,
            "cohorts": len(cohort_rows),
            "cohort_tiers": dict(sorted(tier_counts.items())),
            "context_samples": n_samples,
            "sampling_priority_features": len(sampling_priority["features"]),
            "coverage_repair_tasks": len(repair_queue.get("tasks", [])),
        },
        "outputs": [
            "analysis_cohorts.csv",
            "analysis_cohort_exclusions.csv",
            "research_context.csv",
            "sampling_priority.geojson",
            "research_products_receipt.json",
        ],
        "external_covariate_interface": EXTERNAL_COVARIATE_INTERFACE,
        "non_claims": NON_CLAIMS,
    }
    (research_dir / "research_products_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "success",
                "research_dir": str(research_dir),
                "counts": receipt["counts"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
