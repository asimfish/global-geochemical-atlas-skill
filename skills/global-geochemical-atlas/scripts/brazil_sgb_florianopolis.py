#!/usr/bin/env python3
"""Standalone D1 adapter for SGB Florianopolis stream-sediment analyses.

This module is deliberately not registered in ``source_adapters.py``.  It pins
one numeric child product from the SGB RIGeo repository item and joins its
analysis rows to the SGB ArcGIS sample layer by the original field sample ID.
The integration branch can register the adapter after reviewing this commit.

No content hash is calculated, read, updated, or used.  Drift checks use the
repository item/bitstream identifiers, byte counts, ZIP member inventory,
worksheet schema, row counts, and key category counts.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import tempfile
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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

SOURCE_ID = "brazil-sgb-florianopolis-stream-sediment"
ITEM_ID = "5adc5a2e-78ca-4da4-990c-c932658481a7"
ITEM_HANDLE = "https://rigeo.sgb.gov.br/handle/doc/23413"
ITEM_API = f"https://rigeo.sgb.gov.br/server/api/core/items/{ITEM_ID}"
BITSTREAM_ID = "4ac11c55-2d10-4aac-9dce-5266b442c500"
BITSTREAM_NAME = "geoquimica_florianopolis_1985.zip"
BITSTREAM_BYTES = 841_480
BITSTREAM_URL = f"https://rigeo.sgb.gov.br/server/api/core/bitstreams/{BITSTREAM_ID}/content"
WORKBOOK_MEMBER = "Florianopolis_Geoquimica_Sedimento_de_Corrente.xlsx"
WORKBOOK_BYTES = 193_591
ARCHIVE_MEMBERS = {
    "Florianopolis.cpg": 5,
    "Florianopolis.dbf": 15_051_674,
    "Florianopolis.prj": 151,
    "Florianopolis.sbn": 13_916,
    "Florianopolis.sbx": 1_188,
    "Florianopolis.shp": 37_508,
    "Florianopolis.shx": 10_788,
    "Florianopolis_Geoquimica_Agua.xlsx": 29_218,
    "Florianopolis_Geoquimica_Concentrado_de_Bateia.xlsx": 9_446,
    "Florianopolis_Geoquimica_Rocha.xlsx": 438_881,
    "Florianopolis_Geoquimica_Sedimento_de_Corrente.xlsx": 193_591,
    "Florianopolis_Geoquimica_Solo.xlsx": 15_455,
    "Florianopolis_Mineralometria.xlsx": 29_342,
    "LEIA_ME_Florianópolis.pdf": 107_256,
}
ARCGIS_LAYER = (
    "https://geoportal.sgb.gov.br/server/rest/services/geoquimica/"
    "geoquimica_integrada/FeatureServer/2"
)
ARCGIS_QUERY = f"{ARCGIS_LAYER}/query"
DATASET_VERSION = "SGB-RIGEO-doc-23413-2022-bitstream-4ac11c55"
FIXTURE_PATH = (
    SKILL_DIR
    / "fixtures"
    / "south-america"
    / SOURCE_ID
    / "source_native_fixture.csv"
)
AUDIT_PATH = (
    SKILL_DIR
    / "fixtures"
    / "south-america"
    / SOURCE_ID
    / "automated_audit.json"
)

TARGET_FIELDS = {
    "As": "As_ppm",
    "Cr": "Cr_ppm",
    "Cu": "Cu_ppm",
    "Ni": "Ni_ppm",
    "Pb": "Pb_ppm",
    "Zn": "Zn_ppm",
}
REQUIRED_FIELDS = {
    "projeto_amostragem",
    "projeto_publicacao",
    "centro_custo",
    "classe",
    "num_campo",
    "num_lab",
    "data_visita",
    "abertura",
    "leitura",
    "job",
    *TARGET_FIELDS.values(),
    "observacao",
}
EXPECTED = {
    "workbook_rows": 1054,
    "target_rows": 527,
    "unique_target_samples": 520,
    "unique_target_sample_lab_pairs": 521,
    "target_observations": 3132,
    "target_observations_by_analyte": {
        "As": 521,
        "Cr": 521,
        "Cu": 527,
        "Ni": 521,
        "Pb": 521,
        "Zn": 521,
    },
}


def _download_bytes(url: str, max_bytes: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "global-geochemical-atlas-d1/4"})
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = response.read(max_bytes + 1)
    except OSError as exc:
        raise SourceAdapterError(f"SGB request failed: {url}: {exc}") from exc
    if len(payload) > max_bytes:
        raise SourceAdapterError(f"SGB response exceeded {max_bytes} bytes: {url}")
    return payload


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
    temporary.replace(path)


def _column_index(reference: str) -> int:
    match = re.match(r"^([A-Z]+)", reference)
    if not match:
        raise SourceAdapterError(f"invalid XLSX cell reference: {reference!r}")
    value = 0
    for character in match.group(1):
        value = value * 26 + ord(character) - ord("A") + 1
    return value - 1


def _xlsx_rows(payload: bytes) -> list[tuple[int, list[str]]]:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as workbook:
            members = workbook.infolist()
            if len(members) > 100 or sum(member.file_size for member in members) > 10_000_000:
                raise SourceAdapterError("SGB workbook exceeds safe structural limits")
            if "xl/worksheets/sheet1.xml" not in workbook.namelist():
                raise SourceAdapterError("SGB workbook lacks sheet1.xml")
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in workbook.namelist():
                root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared_strings = [
                    "".join(node.text or "" for node in item.iter(f"{namespace}t"))
                    for item in root.findall(f"{namespace}si")
                ]
            sheet = ET.fromstring(workbook.read("xl/worksheets/sheet1.xml"))
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError) as exc:
        raise SourceAdapterError("SGB workbook is unreadable") from exc

    rows: list[tuple[int, list[str]]] = []
    for row in sheet.findall(f".//{namespace}sheetData/{namespace}row"):
        indexed: dict[int, str] = {}
        for cell in row.findall(f"{namespace}c"):
            index = _column_index(str(cell.get("r") or ""))
            value_node = cell.find(f"{namespace}v")
            value = "" if value_node is None else str(value_node.text or "")
            if cell.get("t") == "s" and value:
                try:
                    value = shared_strings[int(value)]
                except (ValueError, IndexError) as exc:
                    raise SourceAdapterError("SGB workbook shared-string index changed") from exc
            elif cell.get("t") == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{namespace}t"))
            indexed[index] = value.strip()
        width = max(indexed, default=-1) + 1
        rows.append((int(row.get("r") or len(rows) + 1), [indexed.get(i, "") for i in range(width)]))
    return rows


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
            payload = archive.read(WORKBOOK_MEMBER)
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise SourceAdapterError(f"SGB archive is unreadable: {archive_path.name}") from exc
    rows = _xlsx_rows(payload)
    if not rows:
        raise SourceAdapterError("SGB workbook is empty")
    headers = [header.strip() for header in rows[0][1]]
    missing = REQUIRED_FIELDS - set(headers)
    if missing:
        raise SourceAdapterError(f"SGB workbook schema changed; missing={sorted(missing)}")
    result: list[tuple[int, dict[str, str]]] = []
    for row_number, row in rows[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        result.append((row_number, dict(zip(headers, padded, strict=False))))
    if len(result) != EXPECTED["workbook_rows"]:
        raise SourceAdapterError(f"SGB workbook row count changed: {len(result)}")
    return result


def _fixture_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [(int(row.pop("source_row")), dict(row)) for row in reader]
    if not rows:
        raise SourceAdapterError("SGB fixture is empty")
    missing = REQUIRED_FIELDS - set(rows[0][1])
    if missing:
        raise SourceAdapterError(f"SGB fixture schema changed; missing={sorted(missing)}")
    return rows


def _excel_date(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    try:
        serial = float(value)
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace(" 00:00:00", "")).date().isoformat()
        except ValueError:
            return value
    return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()


def _observation(raw_value: str, field: str) -> dict[str, Any]:
    raw = raw_value.strip()
    observation: dict[str, Any] = {
        "field": field,
        "raw_value": raw,
        "unit": "ppm",
        "measurement_basis": "source_reported_stream_sediment",
    }
    if raw.upper() == "ND":
        observation.update(value=None, value_qualifier="not_detected", detection_limit=None)
    elif raw.startswith("<"):
        limit = raw[1:].strip().replace(",", ".")
        try:
            parsed_limit: float | None = float(limit)
        except ValueError:
            parsed_limit = None
        observation.update(value=None, value_qualifier="below_detection_limit", detection_limit=parsed_limit)
    else:
        try:
            value: float | None = float(raw.replace(",", "."))
        except ValueError:
            value = None
        observation.update(value=value, value_qualifier="reported" if value is not None else "unparsed")
    return observation


def _source_ids(rows: Sequence[tuple[int, Mapping[str, str]]]) -> list[str]:
    return sorted({values["num_campo"].strip() for _, values in rows if values["num_campo"].strip()})


def _sample_lab_key(sample_id: Any, lab_id: Any) -> str:
    return f"{str(sample_id or '').strip()}|{str(lab_id or '').strip()}"


def _query_coordinates(sample_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    features: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(sample_ids), 60):
        batch = sample_ids[offset : offset + 60]
        escaped = [sample_id.replace("'", "''") for sample_id in batch]
        where = "NUM_CAMPO IN (" + ",".join(f"'{sample_id}'" for sample_id in escaped) + ")"
        query = urllib.parse.urlencode(
            {
                "where": where,
                "outFields": (
                    "OBJECTID,PROJETO,CLASSE,NUM_CAMPO,NUM_LAB,DTVISITA,DESCAMOSTR,"
                    "MATCOLETAD,FONTEAMOST,SITUACAO,AREADRENAG,URL"
                ),
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            }
        )
        payload = json.loads(_download_bytes(f"{ARCGIS_QUERY}?{query}", 5_000_000))
        if "error" in payload:
            raise SourceAdapterError(f"SGB ArcGIS coordinate query failed: {payload['error']}")
        for feature in payload.get("features", []):
            properties = feature.get("properties") or {}
            sample_id = str(properties.get("NUM_CAMPO") or "").strip()
            if not sample_id:
                continue
            key = _sample_lab_key(sample_id, properties.get("NUM_LAB"))
            if key in features:
                raise SourceAdapterError(f"SGB ArcGIS returned duplicate sample+lab metadata: {key}")
            features[key] = feature
    return features


def _coordinate_payload(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features: dict[str, dict[str, Any]] = {}
    for feature in payload.get("features", []):
        properties = feature.get("properties") or {}
        sample_id = str(properties.get("NUM_CAMPO") or "").strip()
        if sample_id:
            key = _sample_lab_key(sample_id, properties.get("NUM_LAB"))
            if key in features:
                raise SourceAdapterError(f"SGB cached coordinates duplicate sample+lab metadata: {key}")
            features[key] = feature
    return features


class BrazilSgbFlorianopolisStreamSedimentAdapter(DataSourceAdapter):
    """Pinned SGB stream-sediment workbook plus record-level sample coordinates."""

    source_id = SOURCE_ID

    @property
    def candidate(self) -> DatasetCandidate:
        return DatasetCandidate(
            source_id=SOURCE_ID,
            title="SGB Florianopolis stream-sediment geochemistry",
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
                "member_inventory": ARCHIVE_MEMBERS,
                "release_year": 2022,
                "expected_counts": EXPECTED,
            },
        )

    def discover(self, request: Mapping[str, Any] | None = None) -> list[DatasetCandidate]:
        request = request or {}
        media = {str(item).lower() for item in request.get("media", [])}
        regions = {str(item).lower() for item in request.get("regions", [])}
        if media and not ({"sediment", "stream sediment", "river sediment"} & media):
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
            raise SourceAdapterError("SGB adapter received another source")
        if mode == "fixture":
            if not FIXTURE_PATH.exists():
                raise SourceAdapterError(f"SGB fixture is missing: {FIXTURE_PATH}")
            return [
                DownloadedFile(
                    source_id=SOURCE_ID,
                    file_id="fixture-joined-records",
                    path=FIXTURE_PATH,
                    source_url=f"{ITEM_HANDLE}#fixture",
                    bytes=FIXTURE_PATH.stat().st_size,
                    cache_status="offline_fixture",
                    retrieved_at=None,
                )
            ]

        root = cache_dir / SOURCE_ID / DATASET_VERSION
        archive_path = root / BITSTREAM_NAME
        coordinate_path = root / "arcgis-sample-coordinates.geojson"
        if mode == "online":
            payload = _download_bytes(BITSTREAM_URL, 2_000_000)
            if len(payload) != BITSTREAM_BYTES:
                raise SourceAdapterError(f"SGB bitstream byte count changed: {len(payload)}")
            _atomic_write(archive_path, payload)
            rows = _workbook_rows(archive_path)
            features = _query_coordinates(_source_ids(rows))
            if len(features) != EXPECTED["unique_target_sample_lab_pairs"]:
                raise SourceAdapterError(
                    "SGB ArcGIS sample+lab coverage changed: "
                    f"{len(features)}/{EXPECTED['unique_target_sample_lab_pairs']}"
                )
            feature_collection = {"type": "FeatureCollection", "features": list(features.values())}
            _atomic_write(
                coordinate_path,
                (json.dumps(feature_collection, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
            )
            cache_status = "downloaded"
            retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        else:
            if not archive_path.exists() or not coordinate_path.exists():
                raise SourceAdapterError("SGB cached mode requires both the pinned ZIP and coordinate response")
            if archive_path.stat().st_size != BITSTREAM_BYTES:
                raise SourceAdapterError("SGB cached bitstream byte count changed")
            cache_status = "verified_readable_identity_cache"
            retrieved_at = None
        return [
            DownloadedFile(
                source_id=SOURCE_ID,
                file_id=BITSTREAM_ID,
                path=archive_path,
                source_url=BITSTREAM_URL,
                bytes=archive_path.stat().st_size,
                cache_status=cache_status,
                retrieved_at=retrieved_at,
            ),
            DownloadedFile(
                source_id=SOURCE_ID,
                file_id="sgb-arcgis-layer-2-sample-coordinates",
                path=coordinate_path,
                source_url=ARCGIS_QUERY,
                bytes=coordinate_path.stat().st_size,
                cache_status=cache_status,
                retrieved_at=retrieved_at,
            ),
        ]

    def parse(self, files: Sequence[DownloadedFile]) -> Iterable[RawRecord]:
        by_id = {item.file_id: item for item in files}
        if "fixture-joined-records" in by_id:
            rows = _fixture_rows(by_id["fixture-joined-records"].path)
            fixture_mode = True
            coordinates: dict[str, dict[str, Any]] = {}
        else:
            try:
                archive = by_id[BITSTREAM_ID]
                coordinate_file = by_id["sgb-arcgis-layer-2-sample-coordinates"]
            except KeyError as exc:
                raise SourceAdapterError("SGB parse requires the archive and coordinate response") from exc
            rows = _workbook_rows(archive.path)
            coordinates = _coordinate_payload(coordinate_file.path)
            fixture_mode = False

        counts = Counter()
        target_rows = 0
        samples: set[str] = set()
        sample_lab_pairs: set[str] = set()
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
            sample_id = str(values.get("num_campo") or "").strip()
            if not sample_id:
                raise SourceAdapterError(f"SGB target row lacks num_campo: row {row_number}")
            samples.add(sample_id)
            sample_lab_key = _sample_lab_key(sample_id, values.get("num_lab"))
            sample_lab_pairs.add(sample_lab_key)
            if fixture_mode:
                longitude = str(values.get("longitude") or "").strip()
                latitude = str(values.get("latitude") or "").strip()
                object_id = str(values.get("arcgis_objectid") or "").strip()
                properties = {
                    "OBJECTID": int(object_id) if object_id else None,
                    "NUM_CAMPO": sample_id,
                    "NUM_LAB": values.get("num_lab"),
                    "DESCAMOSTR": values.get("sample_description"),
                    "MATCOLETAD": values.get("material_collected"),
                    "FONTEAMOST": values.get("sample_source"),
                    "SITUACAO": values.get("sample_situation"),
                    "AREADRENAG": values.get("drainage_area"),
                    "URL": values.get("project_report_url"),
                }
                geometry = {
                    "type": "Point",
                    "coordinates": [float(longitude), float(latitude)],
                } if longitude and latitude else None
                feature = {"properties": properties, "geometry": geometry}
            else:
                feature = coordinates.get(sample_lab_key, {})
                properties = feature.get("properties") or {}
                geometry = feature.get("geometry")
                object_id = str(properties.get("OBJECTID") or "")
            if not feature:
                coordinate_status = "unmatched_sample_metadata"
                latitude = longitude = None
                coordinate_failures += 1
            elif not geometry or len(geometry.get("coordinates") or []) < 2:
                coordinate_status = "missing_coordinate"
                latitude = longitude = None
                coordinate_failures += 1
            else:
                coordinate_status = "matched_arcgis_sample_id"
                longitude, latitude = geometry["coordinates"][:2]
            source_locator = (
                f"{BITSTREAM_NAME}/{WORKBOOK_MEMBER}#row={row_number};"
                f"{ARCGIS_LAYER}#OBJECTID={object_id or 'unmatched'}"
            )
            native_id = f"{sample_id}|{values.get('num_lab','')}|{row_number}"
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
                    "medium": "sediment",
                    "sample_type_raw": values.get("classe"),
                    "sample_type": "sediment_stream",
                    "sediment_environment": "stream",
                    "sampled_at": _excel_date(str(values.get("data_visita") or "")),
                    "analytical_method_raw": values.get("leitura") or None,
                    "method_scope": "record",
                    "method_assignment_basis": "source_workbook_leitura_field",
                    "digestion_or_extraction_raw": values.get("abertura") or None,
                    "method_missing_reason": None if values.get("leitura") else "source row has no leitura value",
                    "laboratory_id_raw": values.get("num_lab") or None,
                    "longitude": longitude,
                    "latitude": latitude,
                    "coordinate_status": coordinate_status,
                    "source_crs": "EPSG:4326" if latitude is not None else None,
                    "original_coordinate_crs": "EPSG:4674 (SIRGAS 2000)",
                    "coordinate_assignment_basis": "exact NUM_CAMPO + NUM_LAB join to SGB ArcGIS layer 2",
                    "arcgis_objectid": properties.get("OBJECTID"),
                    "sample_description_raw": properties.get("DESCAMOSTR"),
                    "material_collected_raw": properties.get("MATCOLETAD"),
                    "sample_source_raw": properties.get("FONTEAMOST"),
                    "sample_situation_raw": properties.get("SITUACAO"),
                    "drainage_area_raw": properties.get("AREADRENAG"),
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
                "unique_target_sample_lab_pairs": len(sample_lab_pairs),
                "target_observations": sum(counts.values()),
                "target_observations_by_analyte": dict(counts),
            }
            for key in (
                "target_rows",
                "unique_target_samples",
                "unique_target_sample_lab_pairs",
                "target_observations",
            ):
                if observed[key] != EXPECTED[key]:
                    raise SourceAdapterError(f"SGB reconciliation changed for {key}: {observed[key]!r}")
            if observed["target_observations_by_analyte"] != EXPECTED["target_observations_by_analyte"]:
                raise SourceAdapterError("SGB target-analyte counts changed")
            if coordinate_failures:
                raise SourceAdapterError(f"SGB exact sample+lab coordinate joins failed: {coordinate_failures}")

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
            "citation": self.parse_citation(),
            "rights": {
                "repository_metadata": "open",
                "research_use_status": "permitted_research",
                "license_scope": "item metadata only; no explicit dataset reuse license located",
                "redistribution_status": "not_evaluated_for_project_output",
            },
            "coordinate_join": {
                "layer": ARCGIS_LAYER,
                "key": "NUM_CAMPO + NUM_LAB (NUM_CAMPO alone is not unique)",
                "requested_output_crs": "EPSG:4326",
                "original_layer_crs": "SIRGAS 2000",
            },
            "method_semantics": {
                "method_field": "leitura",
                "preparation_or_extraction_field": "abertura",
                "scope": "record",
                "no_inference": True,
            },
            "limitations": [
                "The product is a regional Florianopolis survey, not national or continuous South American coverage.",
                "ND has no recoverable numeric detection limit unless a separate source record states one.",
                "The source reports semiquantitative optical-emission results and a small atomic-absorption subset; methods are not merged.",
                "The RIGeo item says open, but no explicit dataset reuse license was located; fixture use is limited to evidence testing.",
            ],
        }

    @staticmethod
    def parse_citation() -> str:
        return (
            "SERVICO GEOLOGICO DO BRASIL - CPRM. Resultados Analiticos de Amostras "
            "Geoquimicas e Produtos Associados (planilhas de analises geoquimicas). "
            "Brasil: SGB-CPRM, 2022."
        )


def _profile(adapter: BrazilSgbFlorianopolisStreamSedimentAdapter, files: Sequence[DownloadedFile]) -> dict[str, Any]:
    rows = list(adapter.parse(files))
    counts = Counter()
    qualifiers = Counter()
    methods = Counter()
    coordinates = Counter()
    for row in rows:
        counts.update(row.fields["_target_observations"].keys())
        methods[str(row.fields.get("analytical_method_raw") or "missing")] += 1
        coordinates[str(row.fields.get("coordinate_status"))] += 1
        for observation in row.fields["_target_observations"].values():
            qualifiers[str(observation["value_qualifier"])] += 1
    return {
        "source_id": SOURCE_ID,
        "dataset_version": DATASET_VERSION,
        "raw_analysis_rows": len(rows),
        "unique_samples": len({row.fields["sample_id"] for row in rows}),
        "target_observations": sum(counts.values()),
        "target_observations_by_analyte": dict(sorted(counts.items())),
        "qualifiers": dict(sorted(qualifiers.items())),
        "methods": dict(sorted(methods.items())),
        "coordinate_status": dict(sorted(coordinates.items())),
        "files": [
            {"file_id": item.file_id, "name": item.path.name, "bytes": item.bytes, "status": item.cache_status}
            for item in files
        ],
    }


def _check_audit(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("source_id") != SOURCE_ID:
        raise SourceAdapterError("SGB audit source_id changed")
    records = payload.get("records") or []
    if len(records) != 30:
        raise SourceAdapterError(f"SGB automated audit requires 30 observations, got {len(records)}")
    if payload.get("reviewer_type") != "codex" or payload.get("status") != "automated_audit_complete":
        raise SourceAdapterError("SGB automated audit status/reviewer changed")
    fixture = {
        (row_number, analyte): {
            "observation": _observation(str(values.get(field) or ""), field),
            "sample_id": values.get("num_campo"),
            "method_raw": values.get("leitura"),
            "object_id": values.get("arcgis_objectid"),
        }
        for row_number, values in _fixture_rows(FIXTURE_PATH)
        for analyte, field in TARGET_FIELDS.items()
        if str(values.get(field) or "").strip()
    }
    reviewed: set[tuple[int, str]] = set()
    for record in records:
        if not record.get("source_locator") or not record.get("sample_id") or not record.get("analyte"):
            raise SourceAdapterError("SGB audit record lost record-level traceability")
        key = (record.get("source_row"), record.get("analyte"))
        if key in reviewed:
            raise SourceAdapterError(f"SGB audit duplicated one source observation: {key}")
        reviewed.add(key)
        expected = fixture.get(key)
        if not expected:
            raise SourceAdapterError(f"SGB audit no longer maps to the fixture: {key}")
        observation = expected["observation"]
        if str(record.get("raw_value")) != observation["raw_value"]:
            raise SourceAdapterError(f"SGB audit raw value changed: {key}")
        if record.get("qualifier") != observation["value_qualifier"]:
            raise SourceAdapterError(f"SGB audit qualifier changed: {key}")
        if record.get("sample_id") != expected["sample_id"] or record.get("method_raw") != expected["method_raw"]:
            raise SourceAdapterError(f"SGB audit sample/method mapping changed: {key}")
        locator = str(record["source_locator"])
        if f"row={key[0]}" not in locator or f"OBJECTID={expected['object_id']}" not in locator:
            raise SourceAdapterError(f"SGB audit locator changed: {key}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("online", "cached", "fixture"), default="fixture")
    parser.add_argument("--cache-dir", type=Path, default=SKILL_DIR / ".cache")
    parser.add_argument("--audit", type=Path, default=AUDIT_PATH)
    args = parser.parse_args()
    adapter = BrazilSgbFlorianopolisStreamSedimentAdapter()
    files = adapter.download(adapter.candidate, args.cache_dir, args.mode)
    _check_audit(args.audit)
    print(json.dumps(_profile(adapter, files), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
