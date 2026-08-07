#!/usr/bin/env python3
"""Query a derived D1 SQLite index using bounded, parameterized filters."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class QueryError(ValueError):
    """Raised when an index or query cannot be used safely."""


def _append_in_filter(
    clauses: list[str], parameters: list[Any], column: str, values: Sequence[str] | None
) -> None:
    if not values:
        return
    normalized = [value.strip() for value in values]
    if any(not value for value in normalized):
        raise QueryError(f"{column} filters must not be empty")
    clauses.append(f"os.{column} IN ({','.join('?' for _ in normalized)})")
    parameters.extend(normalized)


def _text_entity_filters(
    connection: sqlite3.Connection, text: str
) -> dict[str, list[str]]:
    try:
        rows = connection.execute(
            "SELECT entity_type, entity_id FROM archive_fts WHERE archive_fts MATCH ? LIMIT 10000",
            (text,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        raise QueryError(f"invalid full-text expression: {exc}") from exc
    grouped: dict[str, list[str]] = {}
    for entity_type, entity_id in rows:
        grouped.setdefault(str(entity_type), []).append(str(entity_id))
    return grouped


def query_index(
    index_path: Path,
    *,
    analytes: Sequence[str] | None = None,
    media: Sequence[str] | None = None,
    sample_types: Sequence[str] | None = None,
    soil_horizons: Sequence[str] | None = None,
    sediment_environments: Sequence[str] | None = None,
    water_body_types: Sequence[str] | None = None,
    water_fractions: Sequence[str] | None = None,
    geologic_units: Sequence[str] | None = None,
    source_ids: Sequence[str] | None = None,
    methods: Sequence[str] | None = None,
    method_scopes: Sequence[str] | None = None,
    license_ids: Sequence[str] | None = None,
    bbox: Sequence[float] | None = None,
    sampled_after: str | None = None,
    sampled_before: str | None = None,
    text: str | None = None,
    limit: int = 1000,
) -> dict[str, Any]:
    """Return matching observations without modifying the SQLite index."""

    if not index_path.is_file():
        raise QueryError(f"SQLite index does not exist: {index_path}")
    if limit < 1 or limit > 10000:
        raise QueryError("limit must be between 1 and 10000")
    if bbox is not None:
        if len(bbox) != 4:
            raise QueryError("bbox must contain west south east north")
        west, south, east, north = (float(value) for value in bbox)
        if not (
            -180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90
        ):
            raise QueryError(
                "bbox is outside WGS84 bounds or has invalid latitude order"
            )

    uri = f"file:{index_path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        required = {
            "observation_search",
            "provenance_trace",
            "sampling_event_rtree",
            "archive_fts",
        }
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE name IN (?,?,?,?)",
                tuple(sorted(required)),
            )
        }
        missing = sorted(required - existing)
        if missing:
            raise QueryError(f"index lacks required objects: {', '.join(missing)}")

        clauses: list[str] = []
        parameters: list[Any] = []
        _append_in_filter(clauses, parameters, "analyte_reported", analytes)
        _append_in_filter(clauses, parameters, "medium_raw", media)
        _append_in_filter(clauses, parameters, "sample_type", sample_types)
        _append_in_filter(clauses, parameters, "soil_horizon", soil_horizons)
        _append_in_filter(
            clauses, parameters, "sediment_environment", sediment_environments
        )
        _append_in_filter(clauses, parameters, "water_body_type", water_body_types)
        _append_in_filter(clauses, parameters, "water_fraction", water_fractions)
        if geologic_units:
            normalized_geology = [value.strip() for value in geologic_units]
            if any(not value for value in normalized_geology):
                raise QueryError("geologic unit filters must not be empty")
            placeholders = ",".join("?" for _ in normalized_geology)
            clauses.append(
                f"(os.geologic_unit_raw IN ({placeholders}) OR os.matched_geologic_unit IN ({placeholders}))"
            )
            parameters.extend(normalized_geology)
            parameters.extend(normalized_geology)
        _append_in_filter(clauses, parameters, "source_id", source_ids)
        _append_in_filter(clauses, parameters, "technique_raw", methods)
        _append_in_filter(clauses, parameters, "method_scope", method_scopes)
        _append_in_filter(clauses, parameters, "license_id", license_ids)

        warnings: list[str] = []
        if sampled_after:
            clauses.append("os.sampled_at_raw >= ?")
            parameters.append(sampled_after)
            warnings.append(
                "Time filtering compares source-native sampled_at_raw strings; use ISO dates only."
            )
        if sampled_before:
            clauses.append("os.sampled_at_raw <= ?")
            parameters.append(sampled_before)
            if not warnings:
                warnings.append(
                    "Time filtering compares source-native sampled_at_raw strings; use ISO dates only."
                )

        if bbox is not None:
            west, south, east, north = (float(value) for value in bbox)
            longitude_clause = (
                "rt.max_longitude >= ? AND rt.min_longitude <= ?"
                if west <= east
                else "(rt.max_longitude >= ? OR rt.min_longitude <= ?)"
            )
            clauses.append(
                "EXISTS (SELECT 1 FROM sampling_events se "
                "JOIN sampling_event_rtree rt ON rt.event_rowid = se.rowid "
                "WHERE se.sampling_event_id = os.sampling_event_id "
                f"AND {longitude_clause} AND rt.max_latitude >= ? AND rt.min_latitude <= ?)"
            )
            parameters.extend((west, east, south, north))

        if text:
            grouped = _text_entity_filters(connection, text.strip())
            entity_columns = {
                "dataset": "dataset_id",
                "sampling_event": "sampling_event_id",
                "sample": "sample_id",
                "method": "method_id",
            }
            text_clauses: list[str] = []
            text_parameters: list[str] = []
            for entity_type, column in entity_columns.items():
                identifiers = sorted(set(grouped.get(entity_type, [])))
                if identifiers:
                    text_clauses.append(
                        f"os.{column} IN ({','.join('?' for _ in identifiers)})"
                    )
                    text_parameters.extend(identifiers)
            publication_ids = sorted(set(grouped.get("publication", [])))
            if publication_ids:
                text_clauses.append(
                    "EXISTS (SELECT 1 FROM method_publications mp "
                    "WHERE mp.method_id = os.method_id "
                    f"AND mp.publication_id IN ({','.join('?' for _ in publication_ids)}))"
                )
                text_parameters.extend(publication_ids)
            clauses.append(f"({' OR '.join(text_clauses)})" if text_clauses else "0")
            parameters.extend(text_parameters)

        sql = "SELECT DISTINCT os.* FROM observation_search os"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY os.observation_id LIMIT ?"
        parameters.append(limit)
        records = [dict(row) for row in connection.execute(sql, parameters)]
    finally:
        connection.close()

    filters = {
        "analytes": list(analytes or []),
        "media": list(media or []),
        "sample_types": list(sample_types or []),
        "soil_horizons": list(soil_horizons or []),
        "sediment_environments": list(sediment_environments or []),
        "water_body_types": list(water_body_types or []),
        "water_fractions": list(water_fractions or []),
        "geologic_units": list(geologic_units or []),
        "source_ids": list(source_ids or []),
        "methods": list(methods or []),
        "method_scopes": list(method_scopes or []),
        "license_ids": list(license_ids or []),
        "bbox": list(bbox) if bbox is not None else None,
        "sampled_after": sampled_after,
        "sampled_before": sampled_before,
        "text": text,
        "limit": limit,
    }
    return {
        "query_version": "d1-sqlite-query-v1",
        "status": "success",
        "index": str(index_path),
        "filters": filters,
        "record_count": len(records),
        "records": records,
        "warnings": warnings,
        "claim_boundary": "Results preserve source-native values and provenance; no D2 normalization, QC or geological inference was applied.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--analyte", action="append", dest="analytes")
    parser.add_argument("--medium", action="append", dest="media")
    parser.add_argument("--sample-type", action="append", dest="sample_types")
    parser.add_argument("--soil-horizon", action="append", dest="soil_horizons")
    parser.add_argument(
        "--sediment-environment", action="append", dest="sediment_environments"
    )
    parser.add_argument("--water-body-type", action="append", dest="water_body_types")
    parser.add_argument("--water-fraction", action="append", dest="water_fractions")
    parser.add_argument("--geologic-unit", action="append", dest="geologic_units")
    parser.add_argument("--source-id", action="append", dest="source_ids")
    parser.add_argument(
        "--method",
        action="append",
        dest="methods",
        help="Exact source-native technique",
    )
    parser.add_argument("--method-scope", action="append", dest="method_scopes")
    parser.add_argument("--license-id", action="append", dest="license_ids")
    parser.add_argument(
        "--bbox", nargs=4, type=float, metavar=("WEST", "SOUTH", "EAST", "NORTH")
    )
    parser.add_argument(
        "--sampled-after", help="Inclusive source-native ISO date lower bound"
    )
    parser.add_argument(
        "--sampled-before", help="Inclusive source-native ISO date upper bound"
    )
    parser.add_argument(
        "--text",
        help="FTS5 expression over dataset, publication, event, sample and method text",
    )
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = query_index(
            args.index,
            analytes=args.analytes,
            media=args.media,
            sample_types=args.sample_types,
            soil_horizons=args.soil_horizons,
            sediment_environments=args.sediment_environments,
            water_body_types=args.water_body_types,
            water_fractions=args.water_fractions,
            geologic_units=args.geologic_units,
            source_ids=args.source_ids,
            methods=args.methods,
            method_scopes=args.method_scopes,
            license_ids=args.license_ids,
            bbox=args.bbox,
            sampled_after=args.sampled_after,
            sampled_before=args.sampled_before,
            text=args.text,
            limit=args.limit,
        )
    except (OSError, sqlite3.Error, QueryError) as exc:
        print(
            json.dumps(
                {"status": "invalid_query", "error": str(exc)}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
