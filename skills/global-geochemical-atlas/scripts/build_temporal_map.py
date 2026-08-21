#!/usr/bin/env python3
"""Build the temporal-evolution interactive map as a single offline HTML file.

Reads the standardized D2 geochemistry.csv, extracts the records that carry a
publisher-reported sampling time, detects fixed-location stations with >= 3
sampling timepoints, and injects a deterministic JSON payload plus the offline
Natural Earth coastline into the temporal-atlas-v1.html template.

Honest degradation rules:
  * only sampling_time_status == "publisher_reported" rows join the replay;
  * rows without usable time are never faked -- they are counted and can only
    be shown as an explicitly labelled grey underlay;
  * "YYYY/YYYY" year ranges keep their interval and sort at the midpoint;
  * censored values are plotted hollow at the censoring limit and are
    excluded from trend slopes.

Determinism: same input bytes produce byte-identical HTML (sorted
serialization, no timestamps, no randomness).
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEFAULT_TEMPLATE = SKILL_DIR / "assets" / "temporal-atlas-v1.html"
DEFAULT_BASEMAP = SKILL_DIR / "assets" / "natural-earth-110m-land.json"

PAYLOAD_SCHEMA_VERSION = "temporal-atlas-payload-v1"
POINT_PRECISION_FORMATS = {
    "second": "%Y-%m-%dT%H:%M:%S",
    "minute": "%Y-%m-%dT%H:%M",
    "day": "%Y-%m-%d",
    "month": "%Y-%m",
    "year": "%Y",
}
TREND_RELATIVE_THRESHOLD = 0.15
STATION_MIN_TIMEPOINTS = 3
STATION_COORD_DECIMALS = 3


class TemporalMapBuildError(RuntimeError):
    """Raised when inputs or the bundled template/basemap are invalid."""


def parse_float(text: str) -> float | None:
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def decimal_year(moment: datetime) -> float:
    year_start = datetime(moment.year, 1, 1)
    year_end = datetime(moment.year + 1, 1, 1)
    fraction = (moment - year_start).total_seconds() / (
        year_end - year_start
    ).total_seconds()
    return round(moment.year + fraction, 5)


def parse_sampling_time(raw: str, precision: str) -> tuple[float, float, float] | None:
    """Return (t_mid, t_start, t_end) as decimal years, or None if unusable."""
    if not raw or not precision:
        return None
    if precision == "year_range":
        parts = raw.split("/")
        if len(parts) != 2:
            return None
        try:
            y0, y1 = int(parts[0]), int(parts[1])
        except ValueError:
            return None
        if y1 < y0:
            y0, y1 = y1, y0
        t_start, t_end = float(y0), float(y1 + 1)
        return (round((t_start + t_end) / 2, 5), t_start, t_end)
    fmt = POINT_PRECISION_FORMATS.get(precision)
    if fmt is None:
        return None
    try:
        moment = datetime.strptime(raw, fmt)
    except ValueError:
        return None
    t_start = decimal_year(moment)
    if precision in ("second", "minute"):
        return (t_start, t_start, t_start)
    if precision == "day":
        t_end = round(t_start + 1 / 365.25, 5)
    elif precision == "month":
        if moment.month == 12:
            t_end = decimal_year(datetime(moment.year + 1, 1, 1))
        else:
            t_end = decimal_year(datetime(moment.year, moment.month + 1, 1))
    else:  # year
        t_end = float(moment.year + 1)
    return (round((t_start + t_end) / 2, 5), t_start, t_end)


def resolve_coordinates(row: dict[str, str]) -> tuple[float, float, bool] | None:
    """Return (lon, lat, used_raw_fallback) or None when the record cannot map."""
    lat = parse_float(row.get("latitude", ""))
    lon = parse_float(row.get("longitude", ""))
    fallback = False
    if lat is None or lon is None:
        lat = parse_float(row.get("original_latitude_raw", ""))
        lon = parse_float(row.get("original_longitude_raw", ""))
        fallback = True
    if lat is None or lon is None:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return (round(lon, 4), round(lat, 4), fallback)


def resolve_value(
    row: dict[str, str],
) -> tuple[float | None, str | None, bool, float | None]:
    """Return (value, unit, censored, censoring_limit) for one measurement row."""
    censored = row.get("censored", "").strip().lower() == "true"
    normalized = parse_float(row.get("normalized_value", ""))
    if censored:
        limit = parse_float(row.get("normalized_censoring_limit", ""))
        unit = row.get("normalized_unit", "") or None
        if limit is None:
            limit = parse_float(row.get("detection_limit", ""))
            unit = row.get("detection_limit_unit", "") or unit
        if limit is None:
            limit = parse_float(row.get("original_value", ""))
            unit = row.get("original_unit", "") or unit
        return (None, unit, True, limit)
    if normalized is not None:
        return (normalized, row.get("normalized_unit", "") or None, False, None)
    original = parse_float(row.get("original_value", ""))
    if original is not None:
        return (original, row.get("original_unit", "") or None, False, None)
    return (None, None, False, None)


def station_key(row: dict[str, str], lon: float, lat: float) -> tuple[str, str]:
    sample_id = row.get("sample_id", "")
    source_id = row.get("source_id", "")
    if "|" in sample_id:
        return (source_id, sample_id.split("|", 1)[0])
    return (source_id, f"{lat:.4f},{lon:.4f}")


def station_label(key: tuple[str, str], sample_ids: list[str]) -> str:
    if not key[1].replace(".", "").replace(",", "").replace("-", "").isdigit():
        return key[1]
    # Coordinate-keyed station: prefer the common dotted prefix of sample ids.
    split_ids = [sid.split(".") for sid in sorted(set(sample_ids))]
    common: list[str] = []
    for segments in zip(*split_ids):
        if all(seg == segments[0] for seg in segments):
            common.append(segments[0])
        else:
            break
    if common:
        return ".".join(common)
    return key[1]


def linear_trend(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Least-squares slope and intercept for (t, value) pairs."""
    n = len(points)
    mean_t = sum(p[0] for p in points) / n
    mean_v = sum(p[1] for p in points) / n
    sxx = sum((p[0] - mean_t) ** 2 for p in points)
    if sxx == 0:
        return (0.0, mean_v)
    slope = sum((p[0] - mean_t) * (p[1] - mean_v) for p in points) / sxx
    return (slope, mean_v - slope * mean_t)


def classify_trend(slope: float, span: float, values: list[float]) -> str:
    median = statistics.median(values)
    if median <= 0:
        return "stable"
    relative = slope * span / median
    if relative > TREND_RELATIVE_THRESHOLD:
        return "rising"
    if relative < -TREND_RELATIVE_THRESHOLD:
        return "falling"
    return "stable"


def build_series(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one station-element series: unit vote, sorted points, trend."""
    unit_votes: dict[str, int] = {}
    for point in points:
        if point["unit"] and (point["value"] is not None or point["limit"] is not None):
            unit_votes[point["unit"]] = unit_votes.get(point["unit"], 0) + 1
    unit = None
    if unit_votes:
        unit = sorted(unit_votes.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    kept, dropped = [], 0
    for point in points:
        has_data = point["value"] is not None or point["limit"] is not None
        if has_data and unit is not None and point["unit"] != unit:
            dropped += 1
            continue
        kept.append(point)
    kept.sort(key=lambda p: (p["t"], p["time_text"]))
    numeric = [(p["t"], p["value"]) for p in kept if p["value"] is not None]
    trend: dict[str, Any] = {
        "class": "insufficient",
        "slope": None,
        "intercept": None,
        "n_numeric": len(numeric),
    }
    distinct_numeric_times = sorted({t for t, _ in numeric})
    if len(distinct_numeric_times) >= STATION_MIN_TIMEPOINTS:
        slope, intercept = linear_trend(numeric)
        span = distinct_numeric_times[-1] - distinct_numeric_times[0]
        trend["class"] = classify_trend(slope, span, [v for _, v in numeric])
        trend["slope"] = float(f"{slope:.4g}")
        trend["intercept"] = round(intercept, 4)
    return {
        "unit": unit,
        "points": [
            [p["t"], p["time_text"], p["value"], 1 if p["censored"] else 0, p["limit"]]
            for p in kept
        ],
        "dropped_units": dropped,
        "trend": trend,
    }


def safe_embedded_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def load_basemap(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    rings = raw.get("rings")
    if not isinstance(rings, list) or not rings:
        raise TemporalMapBuildError("offline basemap has no coastline rings")
    # Keep only offline-safe fields: no URLs may leak into the output HTML.
    return {
        "asset_version": raw.get("asset_version", "unknown"),
        "title": raw.get("title", "Natural Earth land"),
        "scale": raw.get("scale", ""),
        "license": raw.get("license", ""),
        "rings": rings,
    }


def load_provenance(
    path: Path, coord_by_record: dict[str, tuple[float, float, bool] | None]
) -> dict[str, Any]:
    """Embed anomaly-provenance-v1 results so the map can show, per anomaly,
    whether enrichment looks geogenic (parent material) or anthropogenic."""
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("contract") != "anomaly-provenance-v1":
        raise TemporalMapBuildError("unsupported anomaly provenance contract")
    entries: list[dict[str, Any]] = []
    unmapped = 0
    class_counts: dict[str, int] = {}
    for item in sorted(raw["anomalies"], key=lambda a: str(a["record_id"])):
        cls = item["classification"]
        class_counts[cls] = class_counts.get(cls, 0) + 1
        coords = coord_by_record.get(item["record_id"])
        if coords is None:
            unmapped += 1
            continue
        lon, lat, fallback = coords
        lines = [
            [name, line["verdict"], line["plain_language"]]
            for name, line in sorted(item.get("evidence_lines", {}).items())
        ]
        entries.append(
            {
                "lon": lon,
                "lat": lat,
                "element": item["element"],
                "medium": item["medium"],
                "classification": cls,
                "label_zh": item["classification_label_zh"],
                "direction": item["direction"],
                "summary": item["plain_language"],
                "lines": lines,
                "coord_fallback": fallback,
            }
        )
    return {
        "contract": raw["contract"],
        "candidate_count": raw["candidate_count"],
        "mapped": len(entries),
        "unmapped": unmapped,
        "class_counts": class_counts,
        "labels_zh": raw["classification_labels_zh"],
        "entries": entries,
    }


def region_from_profile(profile_path: Path) -> dict[str, Any] | None:
    """Resolve the frozen request region from a d3 visualization profile.

    Returns the same label/bounds/clip_method structure the interactive map
    uses so both deliverables always frame the identical study region.
    """
    import build_interactive_map as map_builder

    try:
        with profile_path.open(encoding="utf-8") as handle:
            profile = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise TemporalMapBuildError(
            f"visualization profile is unreadable: {exc}"
        ) from exc
    try:
        return map_builder.selected_region(profile)
    except (KeyError, TypeError) as exc:
        raise TemporalMapBuildError(
            f"visualization profile has no resolvable region: {exc}"
        ) from exc


def build_payload(
    input_path: Path,
    provenance_path: Path | None = None,
    region: dict[str, Any] | None = None,
) -> dict[str, Any]:
    with input_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise TemporalMapBuildError("input CSV has no data rows")
    required = {
        "record_id",
        "sample_id",
        "source_id",
        "element_or_analyte",
        "medium",
        "latitude",
        "longitude",
        "sampling_time",
        "sampling_time_precision",
        "sampling_time_status",
    }
    missing = required - set(rows[0].keys())
    if missing:
        raise TemporalMapBuildError(f"input CSV lacks columns: {sorted(missing)}")

    elements = sorted(
        {row["element_or_analyte"] for row in rows if row["element_or_analyte"]}
    )
    media = sorted({row["medium"] for row in rows if row["medium"]})
    sources = sorted({row["source_id"] for row in rows if row["source_id"]})
    element_index = {name: i for i, name in enumerate(elements)}
    medium_index = {name: i for i, name in enumerate(media)}
    source_index = {name: i for i, name in enumerate(sources)}

    status_counts: dict[str, int] = {}
    precision_counts: dict[str, int] = {}
    dated: list[dict[str, Any]] = []
    undated: list[dict[str, Any]] = []
    coord_by_record: dict[str, tuple[float, float, bool] | None] = {}
    time_parse_failed = 0
    for row in rows:
        status = row["sampling_time_status"] or "missing_status"
        status_counts[status] = status_counts.get(status, 0) + 1
        parsed = None
        if status == "publisher_reported":
            parsed = parse_sampling_time(
                row["sampling_time"].strip(), row["sampling_time_precision"].strip()
            )
            if parsed is None:
                time_parse_failed += 1
        entry: dict[str, Any] = {"row": row, "coords": resolve_coordinates(row)}
        coord_by_record[row["record_id"]] = entry["coords"]
        if parsed is None:
            undated.append(entry)
            continue
        precision = row["sampling_time_precision"].strip()
        precision_counts[precision] = precision_counts.get(precision, 0) + 1
        entry["t_mid"], entry["t_start"], entry["t_end"] = parsed
        entry["precision"] = precision
        dated.append(entry)

    precisions = sorted(precision_counts)
    precision_index = {name: i for i, name in enumerate(precisions)}

    # --- station detection (mode B): fixed location, >= 3 distinct timepoints
    station_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in dated:
        if entry["coords"] is None:
            continue
        lon, lat, fallback = entry["coords"]
        key = station_key(entry["row"], lon, lat)
        group = station_groups.setdefault(
            key, {"coords": set(), "times": set(), "entries": [], "fallback": False}
        )
        group["coords"].add(
            (round(lat, STATION_COORD_DECIMALS), round(lon, STATION_COORD_DECIMALS))
        )
        group["times"].add(entry["row"]["sampling_time"])
        group["entries"].append(entry)
        group["fallback"] = group["fallback"] or fallback

    eligible_keys = sorted(
        key
        for key, group in station_groups.items()
        if len(group["coords"]) == 1 and len(group["times"]) >= STATION_MIN_TIMEPOINTS
    )
    stations: list[dict[str, Any]] = []
    station_index: dict[tuple[str, str], int] = {}
    for key in eligible_keys:
        group = station_groups[key]
        per_element: dict[str, list[dict[str, Any]]] = {}
        for entry in group["entries"]:
            row = entry["row"]
            value, unit, censored, limit = resolve_value(row)
            per_element.setdefault(row["element_or_analyte"], []).append(
                {
                    "t": entry["t_mid"],
                    "time_text": row["sampling_time"],
                    "value": value,
                    "unit": unit,
                    "censored": censored,
                    "limit": limit,
                }
            )
        series = {
            name: build_series(points) for name, points in sorted(per_element.items())
        }
        ranked = sorted(
            series.items(), key=lambda kv: (-kv[1]["trend"]["n_numeric"], kv[0])
        )
        best_element = ranked[0][0]
        trend_class = series[best_element]["trend"]["class"]
        lon, lat, _ = group["entries"][0]["coords"]
        station_index[key] = len(stations)
        stations.append(
            {
                "id": f"{key[0]}::{key[1]}",
                "label": station_label(
                    key, [e["row"]["sample_id"] for e in group["entries"]]
                ),
                "source": key[0],
                "lon": lon,
                "lat": lat,
                "coord_fallback": group["fallback"],
                "timepoints": len(group["times"]),
                "series": series,
                "best_element": best_element,
                "trend_class": trend_class,
            }
        )

    # --- compact record arrays, deterministically ordered by record_id
    records: list[list[Any]] = []
    dated_unmapped = 0
    coordinate_fallback_used = 0
    for entry in sorted(dated, key=lambda e: e["row"]["record_id"]):
        row = entry["row"]
        if entry["coords"] is None:
            dated_unmapped += 1
            continue
        lon, lat, fallback = entry["coords"]
        if fallback:
            coordinate_fallback_used += 1
        value, unit, censored, limit = resolve_value(row)
        key = station_key(row, lon, lat)
        records.append(
            [
                lon,
                lat,
                element_index[row["element_or_analyte"]],
                medium_index[row["medium"]],
                source_index[row["source_id"]],
                precision_index[entry["precision"]],
                entry["t_mid"],
                entry["t_start"],
                entry["t_end"],
                row["sampling_time"],
                row["sample_id"],
                value,
                unit,
                1 if censored else 0,
                limit,
                1 if fallback else 0,
                station_index.get(key, -1),
            ]
        )
    undated_points: list[list[Any]] = []
    undated_unmapped = 0
    for entry in sorted(undated, key=lambda e: e["row"]["record_id"]):
        if entry["coords"] is None:
            undated_unmapped += 1
            continue
        row = entry["row"]
        lon, lat, _ = entry["coords"]
        undated_points.append(
            [
                lon,
                lat,
                element_index[row["element_or_analyte"]],
                medium_index[row["medium"]],
            ]
        )

    # Zero dated records is an honest, valid state: the map must still be
    # produced and show the explicit time-metadata-gap guidance instead of
    # failing the whole workflow.
    year_min = min((int(rec[7]) for rec in records), default=None)
    year_max = max((int(rec[8] - 1e-9) for rec in records), default=None)

    stats = {
        "total_records": len(rows),
        "dated_records": len(dated),
        "undated_records": len(undated),
        "dated_share": round(len(dated) / len(rows), 4),
        "status_counts": status_counts,
        "precision_counts": precision_counts,
        "time_parse_failed": time_parse_failed,
        "dated_mapped": len(records),
        "dated_unmapped": dated_unmapped,
        "undated_mapped": len(undated_points),
        "undated_unmapped": undated_unmapped,
        "coordinate_fallback_used": coordinate_fallback_used,
        "year_min": year_min,
        "year_max": year_max,
        "station_total": len(station_groups),
        "stations_mode_b": len(stations),
    }
    provenance = (
        load_provenance(provenance_path, coord_by_record)
        if provenance_path is not None
        else None
    )
    region_payload: dict[str, Any] | None = None
    if region is not None:
        bounds = region["bounds"]
        region_payload = {
            "label": str(region["label"]),
            "bounds": {
                "w": float(bounds["w"]),
                "s": float(bounds["s"]),
                "e": float(bounds["e"]),
                "n": float(bounds["n"]),
            },
            "clip_method": str(region.get("clip_method", "bbox")),
        }
    return {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "source_dataset": input_path.name,
        "region": region_payload,
        "stats": stats,
        "elements": elements,
        "media": media,
        "sources": sources,
        "precisions": precisions,
        "records": records,
        "undated_points": undated_points,
        "stations": stations,
        "anomaly_provenance": provenance,
    }


def build_html(payload: dict[str, Any], template_path: Path, basemap_path: Path) -> str:
    template = template_path.read_text(encoding="utf-8")
    for placeholder in ("__TEMPORAL_PAYLOAD_JSON__", "__BASEMAP_JSON__"):
        if template.count(placeholder) != 1:
            raise TemporalMapBuildError(f"template placeholder missing: {placeholder}")
    basemap = load_basemap(basemap_path)
    html = template.replace(
        "__TEMPORAL_PAYLOAD_JSON__", safe_embedded_json(payload)
    ).replace("__BASEMAP_JSON__", safe_embedded_json(basemap))
    if "__TEMPORAL_PAYLOAD_JSON__" in html or "__BASEMAP_JSON__" in html:
        raise TemporalMapBuildError("placeholder replacement failed")
    return html


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the temporal-evolution map (single offline HTML)."
    )
    parser.add_argument("--input", required=True, type=Path, help="D2 geochemistry.csv")
    parser.add_argument("--output", required=True, type=Path, help="output HTML path")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--basemap", type=Path, default=DEFAULT_BASEMAP)
    parser.add_argument(
        "--provenance",
        type=Path,
        default=None,
        help="optional anomaly_provenance.json to show geogenic-vs-anthropogenic "
        "verdicts on the map",
    )
    parser.add_argument(
        "--visualization-profile",
        type=Path,
        default=None,
        help="optional d3 visualization profile; frames the initial view on "
        "the frozen request region instead of the whole world",
    )
    args = parser.parse_args()
    try:
        region = (
            region_from_profile(args.visualization_profile)
            if args.visualization_profile is not None
            else None
        )
        payload = build_payload(args.input, args.provenance, region=region)
        html = build_html(payload, args.template, args.basemap)
    except (TemporalMapBuildError, OSError) as error:
        print(f"build_temporal_map: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(html.encode("utf-8"))
    report = {
        "output": str(args.output),
        "output_bytes": len(html.encode("utf-8")),
        "stats": payload["stats"],
        "stations": [
            {
                "label": station["label"],
                "source": station["source"],
                "timepoints": station["timepoints"],
                "trend_class": station["trend_class"],
                "best_element": station["best_element"],
            }
            for station in payload["stations"]
        ],
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
