#!/usr/bin/env python3
"""Standalone D1 adapter for SGB Florianopolis soil geochemistry.

The adapter pins the soil child workbook inside RIGeo item ``doc/23413`` and
joins records to the official SGB soil feature layer with the composite field
sample/laboratory key. It intentionally remains outside the shared adapter
registry until the integration branch registers it.
"""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
import urllib.parse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import zipfile

from brazil_sgb_florianopolis import (
    ARCHIVE_MEMBERS,
    BITSTREAM_BYTES,
    BITSTREAM_ID,
    BITSTREAM_NAME,
    BITSTREAM_URL,
    ITEM_API,
    ITEM_HANDLE,
    ITEM_ID,
    _atomic_write,
    _download_bytes,
    _excel_date,
    _sample_lab_key,
    _xlsx_rows,
)
from source_adapters import (
    DataSourceAdapter,
    DatasetCandidate,
    DownloadedFile,
    DownloadMode,
    RawRecord,
    SourceAdapterError,
    stable_source_record_id,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
SOURCE_ID = "brazil-sgb-florianopolis-soil"
DATASET_VERSION = "SGB-RIGEO-doc-23413-2022-bitstream-4ac11c55-soil"
WORKBOOK_MEMBER = "Florianopolis_Geoquimica_Solo.xlsx"
WORKBOOK_BYTES = 15_455
ARCGIS_LAYER = (
    "https://geoportal.sgb.gov.br/server/rest/services/geoquimica/"
    "geoquimica_integrada/FeatureServer/5"
)
ARCGIS_QUERY = f"{ARCGIS_LAYER}/query"
FIXTURE_DIR = SKILL_DIR / "fixtures" / "south-america" / SOURCE_ID
FIXTURE_PATH = FIXTURE_DIR / "source_native_fixture.csv"
AUDIT_PATH = FIXTURE_DIR / "automated_audit.json"

TARGET_FIELDS = {
    "As": "As_ppm",
    "Cr": "Cr_ppm",
    "Cu": "Cu_ppm",
    "Ni": "Ni_ppm",
    "Pb": "Pb_ppm",
    "Zn": "Zn_ppm",
}
REQUIRED_FIELDS = {
    "projeto_amostragem", "projeto_publicacao", "centro_custo", "classe",
    "num_campo", "num_lab", "data_visita", "abertura", "leitura", "job",
    *TARGET_FIELDS.values(), "observacao",
}
EXPECTED = {
    "workbook_rows": 32,
    "target_rows": 32,
    "unique_target_samples": 32,
    "unique_target_sample_lab_pairs": 32,
    "target_observations": 192,
    "target_observations_by_analyte": {
        "As": 32, "Cr": 32, "Cu": 32, "Ni": 32, "Pb": 32, "Zn": 32,
    },
    "qualifiers": {"below_detection_limit": 3, "not_detected": 64, "reported": 125},
    "methods": {"Espectrografia Ótica de Emissão": 32},
}


def _workbook_rows(archive_path: Path) -> list[tuple[int, dict[str, str]]]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            inventory = {item.filename: item.file_size for item in archive.infolist()}
            if inventory != ARCHIVE_MEMBERS:
                missing = sorted(set(ARCHIVE_MEMBERS) - set(inventory))
                added = sorted(set(inventory) - set(ARCHIVE_MEMBERS))
                changed = sorted(
                    name for name in set(inventory) & set(ARCHIVE_MEMBERS)
                    if inventory[name] != ARCHIVE_MEMBERS[name]
                )
                raise SourceAdapterError(
                    f"SGB ZIP member inventory changed: missing={missing}, added={added}, bytes_changed={changed}"
                )
            if inventory.get(WORKBOOK_MEMBER) != WORKBOOK_BYTES:
                raise SourceAdapterError("SGB soil workbook identity changed")
            payload = archive.read(WORKBOOK_MEMBER)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise SourceAdapterError(f"SGB soil archive is unreadable: {archive_path.name}") from exc
    rows = _xlsx_rows(payload)
    if not rows:
        raise SourceAdapterError("SGB soil workbook is empty")
    headers = [header.strip() for header in rows[0][1]]
    missing = REQUIRED_FIELDS - set(headers)
    if missing:
        raise SourceAdapterError(f"SGB soil schema changed; missing={sorted(missing)}")
    result: list[tuple[int, dict[str, str]]] = []
    for row_number, row in rows[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        result.append((row_number, dict(zip(headers, padded, strict=False))))
    if len(result) != EXPECTED["workbook_rows"]:
        raise SourceAdapterError(f"SGB soil workbook row count changed: {len(result)}")
    return result


def _fixture_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [(int(row.pop("source_row")), dict(row)) for row in reader]
    if not rows:
        raise SourceAdapterError("SGB soil fixture is empty")
    missing = REQUIRED_FIELDS - set(rows[0][1])
    if missing:
        raise SourceAdapterError(f"SGB soil fixture schema changed; missing={sorted(missing)}")
    return rows


def _observation(raw_value: str, field: str) -> dict[str, Any]:
    raw = raw_value.strip()
    result: dict[str, Any] = {
        "field": field,
        "raw_value": raw,
        "unit": "ppm",
        "measurement_basis": "source_reported_soil_unspecified_horizon",
    }
    if raw.upper() == "ND":
        result.update(value=None, value_qualifier="not_detected", detection_limit=None)
    elif raw.startswith("<"):
        threshold = raw[1:].strip().replace(",", ".")
        try:
            detection_limit: float | None = float(threshold)
        except ValueError:
            detection_limit = None
        result.update(value=None, value_qualifier="below_detection_limit", detection_limit=detection_limit)
    else:
        try:
            value: float | None = float(raw.replace(",", "."))
        except ValueError:
            value = None
        result.update(value=value, value_qualifier="reported" if value is not None else "unparsed")
    return result


def _source_ids(rows: Sequence[tuple[int, Mapping[str, str]]]) -> list[str]:
    return sorted({str(values.get("num_campo") or "").strip() for _, values in rows})


def _query_coordinates(sample_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    escaped = [sample_id.replace("'", "''") for sample_id in sample_ids]
    where = "NUM_CAMPO IN (" + ",".join(f"'{sample_id}'" for sample_id in escaped) + ")"
    query = urllib.parse.urlencode({
        "where": where,
        "outFields": (
            "OBJECTID,PROJETO,CLASSE,NUM_CAMPO,NUM_LAB,DTVISITA,DESCAMOSTR,"
            "MATCOLETAD,HORIZ_SOLO,TIPO_SOLO,OBSERVACAO,URL"
        ),
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    })
    payload = json.loads(_download_bytes(f"{ARCGIS_QUERY}?{query}", 2_000_000))
    if "error" in payload:
        raise SourceAdapterError(f"SGB soil coordinate query failed: {payload['error']}")
    features: dict[str, dict[str, Any]] = {}
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        key = _sample_lab_key(properties.get("NUM_CAMPO"), properties.get("NUM_LAB"))
        if key in features:
            raise SourceAdapterError(f"SGB soil layer duplicated sample+lab metadata: {key}")
        features[key] = feature
    return features


def _coordinate_payload(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features: dict[str, dict[str, Any]] = {}
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        key = _sample_lab_key(properties.get("NUM_CAMPO"), properties.get("NUM_LAB"))
        if key in features:
            raise SourceAdapterError(f"SGB cached soil coordinates duplicated sample+lab metadata: {key}")
        features[key] = feature
    return features


class BrazilSgbFlorianopolisSoilAdapter(DataSourceAdapter):
    """SGB regional soil workbook with record methods and exact sample coordinates."""

    source_id = SOURCE_ID

    @property
    def candidate(self) -> DatasetCandidate:
        return DatasetCandidate(
            source_id=SOURCE_ID,
            title="SGB Florianopolis soil geochemistry",
            adapter=self.__class__.__name__,
            version=DATASET_VERSION,
            dataset_doi=None,
            license_id="LicenseRef-SGB-RIGEO-open-item-metadata",
            landing_page=ITEM_HANDLE,
            registry_entry={
                "repository_item_id": ITEM_ID,
                "bitstream_id": BITSTREAM_ID,
                "bitstream_name": BITSTREAM_NAME,
                "bitstream_bytes": BITSTREAM_BYTES,
                "workbook_member": WORKBOOK_MEMBER,
                "workbook_bytes": WORKBOOK_BYTES,
                "expected_counts": EXPECTED,
            },
        )

    def discover(self, request: Mapping[str, Any] | None = None) -> list[DatasetCandidate]:
        request = request or {}
        media = {str(item).lower() for item in request.get("media", [])}
        regions = {str(item).lower() for item in request.get("regions", [])}
        if media and "soil" not in media:
            return []
        if regions and not ({"south america", "brazil", "brasil"} & regions):
            return []
        return [self.candidate]

    def download(
        self,
        candidate: DatasetCandidate,
        cache_dir: Path,
        mode: DownloadMode = "online",
    ) -> list[DownloadedFile]:
        if candidate.source_id != SOURCE_ID:
            raise SourceAdapterError("SGB soil adapter received another source")
        if mode == "fixture":
            if not FIXTURE_PATH.exists():
                raise SourceAdapterError(f"SGB soil fixture is missing: {FIXTURE_PATH}")
            return [DownloadedFile(
                source_id=SOURCE_ID,
                file_id="fixture-joined-records",
                path=FIXTURE_PATH,
                source_url=f"{ITEM_HANDLE}#soil-fixture",
                bytes=FIXTURE_PATH.stat().st_size,
                cache_status="offline_fixture",
                retrieved_at=None,
            )]

        root = cache_dir / SOURCE_ID / DATASET_VERSION
        archive_path = root / BITSTREAM_NAME
        coordinate_path = root / "arcgis-soil-sample-coordinates.geojson"
        if mode == "online":
            payload = _download_bytes(BITSTREAM_URL, 2_000_000)
            if len(payload) != BITSTREAM_BYTES:
                raise SourceAdapterError(f"SGB soil bitstream byte count changed: {len(payload)}")
            _atomic_write(archive_path, payload)
            rows = _workbook_rows(archive_path)
            features = _query_coordinates(_source_ids(rows))
            if len(features) != EXPECTED["unique_target_sample_lab_pairs"]:
                raise SourceAdapterError(
                    f"SGB soil ArcGIS coverage changed: {len(features)}/{EXPECTED['unique_target_sample_lab_pairs']}"
                )
            collection = {"type": "FeatureCollection", "features": list(features.values())}
            _atomic_write(
                coordinate_path,
                (json.dumps(collection, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
            )
            status = "downloaded"
            retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        else:
            if not archive_path.exists() or not coordinate_path.exists():
                raise SourceAdapterError("SGB cached soil mode requires the ZIP and coordinate response")
            if archive_path.stat().st_size != BITSTREAM_BYTES:
                raise SourceAdapterError("SGB cached soil bitstream byte count changed")
            status = "verified_readable_identity_cache"
            retrieved_at = None
        return [
            DownloadedFile(
                source_id=SOURCE_ID, file_id=BITSTREAM_ID, path=archive_path,
                source_url=BITSTREAM_URL, bytes=archive_path.stat().st_size,
                cache_status=status, retrieved_at=retrieved_at,
            ),
            DownloadedFile(
                source_id=SOURCE_ID, file_id="sgb-arcgis-layer-5-soil-coordinates", path=coordinate_path,
                source_url=ARCGIS_QUERY, bytes=coordinate_path.stat().st_size,
                cache_status=status, retrieved_at=retrieved_at,
            ),
        ]

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        fixture_mode = "fixture-joined-records" in by_id
        if fixture_mode:
            rows = _fixture_rows(by_id["fixture-joined-records"].path)
            coordinates: dict[str, dict[str, Any]] = {}
        else:
            try:
                rows = _workbook_rows(by_id[BITSTREAM_ID].path)
                coordinates = _coordinate_payload(by_id["sgb-arcgis-layer-5-soil-coordinates"].path)
            except KeyError as exc:
                raise SourceAdapterError("SGB soil parse requires archive and coordinate response") from exc

        counts = Counter()
        qualifiers = Counter()
        methods = Counter()
        samples: set[str] = set()
        pairs: set[str] = set()
        target_rows = 0
        coordinate_failures = 0
        for row_number, values in rows:
            observations = {
                analyte: _observation(str(values.get(field) or ""), field)
                for analyte, field in TARGET_FIELDS.items()
                if str(values.get(field) or "").strip()
            }
            if not observations:
                continue
            target_rows += 1
            counts.update(observations.keys())
            qualifiers.update(item["value_qualifier"] for item in observations.values())
            method = str(values.get("leitura") or "").strip()
            methods[method or "missing"] += 1
            sample_id = str(values.get("num_campo") or "").strip()
            lab_id = str(values.get("num_lab") or "").strip()
            if not sample_id or not lab_id:
                raise SourceAdapterError(f"SGB soil row lacks sample/lab identity: row {row_number}")
            pair = _sample_lab_key(sample_id, lab_id)
            samples.add(sample_id)
            pairs.add(pair)

            if fixture_mode:
                object_id = str(values.get("arcgis_objectid") or "").strip()
                longitude = str(values.get("longitude") or "").strip()
                latitude = str(values.get("latitude") or "").strip()
                properties = {
                    "OBJECTID": int(object_id) if object_id else None,
                    "NUM_CAMPO": sample_id,
                    "NUM_LAB": lab_id,
                    "DESCAMOSTR": values.get("sample_description"),
                    "MATCOLETAD": values.get("material_collected"),
                    "HORIZ_SOLO": values.get("soil_horizon_raw"),
                    "TIPO_SOLO": values.get("soil_type_raw"),
                    "URL": values.get("project_report_url"),
                }
                geometry = {"type": "Point", "coordinates": [float(longitude), float(latitude)]}
                feature = {"properties": properties, "geometry": geometry}
            else:
                feature = coordinates.get(pair, {})
                properties = feature.get("properties") or {}
                geometry = feature.get("geometry")
                object_id = str(properties.get("OBJECTID") or "")
            if not feature:
                coordinate_status = "unmatched_sample_metadata"
                longitude = latitude = None
                coordinate_failures += 1
            elif not geometry or len(geometry.get("coordinates") or []) < 2:
                coordinate_status = "missing_coordinate"
                longitude = latitude = None
                coordinate_failures += 1
            else:
                coordinate_status = "matched_arcgis_sample_lab"
                longitude, latitude = geometry["coordinates"][:2]
            horizon_raw = str(properties.get("HORIZ_SOLO") or "").strip()
            soil_type_raw = str(properties.get("TIPO_SOLO") or "").strip()
            source_locator = (
                f"{BITSTREAM_NAME}/{WORKBOOK_MEMBER}#row={row_number};"
                f"{ARCGIS_LAYER}#OBJECTID={object_id or 'unmatched'}"
            )
            native_id = f"{sample_id}|{lab_id}|{row_number}"
            yield RawRecord(
                source_id=SOURCE_ID,
                source_record_id=stable_source_record_id(SOURCE_ID, native_id, source_locator),
                source_locator=source_locator,
                fields={
                    **values,
                    "_source_file": BITSTREAM_NAME,
                    "_source_member": WORKBOOK_MEMBER,
                    "_source_row": row_number,
                    "_dataset_version": DATASET_VERSION,
                    "_repository_item_id": ITEM_ID,
                    "_bitstream_id": BITSTREAM_ID,
                    "_target_observations": observations,
                    "sample_id": sample_id,
                    "medium": "soil",
                    "sample_type_raw": values.get("classe"),
                    "sample_type": "soil_unspecified_horizon",
                    "soil_horizon_raw": horizon_raw or None,
                    "soil_horizon": None,
                    "soil_horizon_missing_reason": (
                        "source reports Nao Identificado" if horizon_raw.casefold() == "nao identificado"
                        else "source does not provide a canonical horizon"
                    ),
                    "soil_type_raw": soil_type_raw or None,
                    "sampled_at": _excel_date(str(values.get("data_visita") or "")),
                    "analytical_method_raw": method or None,
                    "method_scope": "record",
                    "method_assignment_basis": "source_workbook_leitura_field",
                    "digestion_or_extraction_raw": values.get("abertura") or None,
                    "digestion_missing_reason": (
                        None if values.get("abertura") else "source row does not report abertura"
                    ),
                    "laboratory_id_raw": lab_id,
                    "longitude": longitude,
                    "latitude": latitude,
                    "coordinate_status": coordinate_status,
                    "source_crs": "EPSG:4326" if latitude is not None else None,
                    "original_coordinate_crs": "EPSG:4674 (SIRGAS 2000)",
                    "coordinate_assignment_basis": "exact NUM_CAMPO + NUM_LAB join to SGB ArcGIS layer 5",
                    "arcgis_objectid": properties.get("OBJECTID"),
                    "sample_description_raw": properties.get("DESCAMOSTR"),
                    "material_collected_raw": properties.get("MATCOLETAD"),
                    "project_report_url": properties.get("URL"),
                    "publication_id": ITEM_HANDLE,
                    "citation_text_raw": (
                        "SERVICO GEOLOGICO DO BRASIL - CPRM (2022), Resultados Analiticos de "
                        "Amostras Geoquimicas e Produtos Associados, RIGeo doc/23413."
                    ),
                    "citation_scope": "dataset",
                    "access_status": "public_download",
                    "research_use_status": "permitted_research",
                    "license": "LicenseRef-SGB-RIGEO-open-item-metadata",
                    "license_scope": "repository item metadata says open; no explicit reuse license located",
                    "redistribution_status": "not_evaluated_for_project_output",
                },
            )

        if not fixture_mode:
            observed = {
                "target_rows": target_rows,
                "unique_target_samples": len(samples),
                "unique_target_sample_lab_pairs": len(pairs),
                "target_observations": sum(counts.values()),
                "target_observations_by_analyte": dict(counts),
                "qualifiers": dict(qualifiers),
                "methods": dict(methods),
            }
            for key in (
                "target_rows", "unique_target_samples", "unique_target_sample_lab_pairs",
                "target_observations", "target_observations_by_analyte", "qualifiers", "methods",
            ):
                if observed[key] != EXPECTED[key]:
                    raise SourceAdapterError(f"SGB soil reconciliation changed for {key}: {observed[key]!r}")
            if coordinate_failures:
                raise SourceAdapterError(f"SGB soil coordinate joins failed: {coordinate_failures}")

    def provenance(self) -> Mapping[str, Any]:
        return {
            "source_id": SOURCE_ID,
            "title": self.candidate.title,
            "dataset_version": DATASET_VERSION,
            "repository_item_id": ITEM_ID,
            "repository_item": ITEM_HANDLE,
            "repository_api": ITEM_API,
            "bitstream_id": BITSTREAM_ID,
            "bitstream_name": BITSTREAM_NAME,
            "bitstream_bytes": BITSTREAM_BYTES,
            "workbook_member": WORKBOOK_MEMBER,
            "workbook_bytes": WORKBOOK_BYTES,
            "release_year": 2022,
            "citation": (
                "SERVICO GEOLOGICO DO BRASIL - CPRM. Resultados Analiticos de Amostras "
                "Geoquimicas e Produtos Associados. Brasil: SGB-CPRM, 2022."
            ),
            "rights": {
                "repository_metadata": "open",
                "research_use_status": "permitted_research",
                "license_scope": "item metadata only; no explicit dataset reuse license located",
                "redistribution_status": "not_evaluated_for_project_output",
            },
            "limitations": [
                "This is a 32-sample regional soil product, not national Brazil or continuous South America coverage.",
                "The official layer reports soil horizon as Nao Identificado and soil type as Nao Especificado.",
                "The workbook has no Hg column and reports As and Zn as ND for all 32 samples.",
                "The source does not report digestion/preparation for these optical-emission rows.",
            ],
        }


def profile(adapter: BrazilSgbFlorianopolisSoilAdapter, files: Sequence[DownloadedFile]) -> dict[str, Any]:
    rows = list(adapter.parse(files))
    analytes = Counter()
    qualifiers = Counter()
    methods = Counter()
    coordinates = Counter()
    horizons = Counter()
    for row in rows:
        observations = row.fields["_target_observations"]
        analytes.update(observations.keys())
        qualifiers.update(item["value_qualifier"] for item in observations.values())
        methods[str(row.fields.get("analytical_method_raw") or "missing")] += 1
        coordinates[str(row.fields.get("coordinate_status"))] += 1
        horizons[str(row.fields.get("soil_horizon_raw") or "missing")] += 1
    return {
        "source_id": SOURCE_ID,
        "dataset_version": DATASET_VERSION,
        "raw_analysis_rows": len(rows),
        "unique_samples": len({row.fields["sample_id"] for row in rows}),
        "target_observations": sum(analytes.values()),
        "target_observations_by_analyte": dict(sorted(analytes.items())),
        "qualifiers": dict(sorted(qualifiers.items())),
        "methods": dict(sorted(methods.items())),
        "coordinate_status": dict(sorted(coordinates.items())),
        "soil_horizon_raw": dict(sorted(horizons.items())),
        "files": [
            {"file_id": item.file_id, "name": item.path.name, "bytes": item.bytes, "status": item.cache_status}
            for item in files
        ],
    }


def check_audit(path: Path = AUDIT_PATH) -> None:
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("source_id") != SOURCE_ID or audit.get("status") != "automated_audit_complete":
        raise SourceAdapterError("SGB soil audit identity/status changed")
    if audit.get("audited_record_count") != 30 or len(audit.get("records") or []) != 30:
        raise SourceAdapterError("SGB soil audit requires exactly 30 reviewed observations")
    fixture = {
        (row_number, analyte): {
            "observation": _observation(str(values.get(field) or ""), field),
            "sample_id": values.get("num_campo"),
            "method": values.get("leitura"),
            "object_id": values.get("arcgis_objectid"),
        }
        for row_number, values in _fixture_rows(FIXTURE_PATH)
        for analyte, field in TARGET_FIELDS.items()
        if str(values.get(field) or "").strip()
    }
    reviewed: set[tuple[int, str]] = set()
    for record in audit["records"]:
        key = (record.get("source_row"), record.get("analyte"))
        if key in reviewed or key not in fixture:
            raise SourceAdapterError(f"SGB soil audit duplicate or unmapped observation: {key}")
        reviewed.add(key)
        expected = fixture[key]
        if str(record.get("raw_value")) != expected["observation"]["raw_value"]:
            raise SourceAdapterError(f"SGB soil audit raw value changed: {key}")
        if record.get("qualifier") != expected["observation"]["value_qualifier"]:
            raise SourceAdapterError(f"SGB soil audit qualifier changed: {key}")
        if record.get("sample_id") != expected["sample_id"] or record.get("method_raw") != expected["method"]:
            raise SourceAdapterError(f"SGB soil audit sample/method changed: {key}")
        locator = str(record.get("source_locator") or "")
        if f"row={key[0]}" not in locator or f"OBJECTID={expected['object_id']}" not in locator:
            raise SourceAdapterError(f"SGB soil audit locator changed: {key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("online", "cached", "fixture"), default="fixture")
    parser.add_argument("--cache-dir", type=Path, default=SKILL_DIR / ".cache")
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()
    adapter = BrazilSgbFlorianopolisSoilAdapter()
    files = adapter.download(adapter.candidate, args.cache_dir, args.mode)
    check_audit(args.audit)
    print(json.dumps(profile(adapter, files), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
