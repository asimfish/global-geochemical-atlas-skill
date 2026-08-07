#!/usr/bin/env python3
"""Evidence-bound V4 semantic mappings for the fourteen executable sources."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


SEMANTICS_VERSION = "d1-v4-source-semantics-v1"

SOURCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "georoc-archaean": {
        "sample_type_raw": "WR",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_constant",
        "method_missing_reason": "not_reported",
        "citation_scope": "observation",
    },
    "georoc-antarctica-intraplate": {
        "sample_type_raw": "WR",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_constant",
        "method_missing_reason": "winning_method_not_encoded_in_precompiled_member",
        "citation_scope": "observation",
    },
    "usgs-conus-soil": {
        "method_missing_reason": "not_available",
        "citation_scope": "dataset",
    },
    "norway-marchem": {
        "sample_type_raw": "marine sediment",
        "sample_type": "sediment_marine",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "marine",
        "method_scope": "batch",
        "method_assignment_basis": "batch_code_to_method_metadata_join",
        "citation_scope": "dataset",
    },
    "geotraces-idp2025": {
        "sample_type_raw": "dissolved seawater",
        "sample_type": "water_seawater",
        "sample_type_mapping_status": "dataset_constant",
        "water_body_type": "seawater",
        "water_fraction": "dissolved",
        "method_scope": "cruise_analyte",
        "method_assignment_basis": "cruise_and_analyte_to_exported_originator_method_record",
        "method_missing_reason": "multiple_linked_method_records_unresolved_to_observation",
        "citation_scope": "dataset",
    },
    "gemstat-open-archive": {
        "method_scope": "observation",
        "method_assignment_basis": "observation_method_code_join",
        "citation_scope": "dataset",
    },
    "japan-gsj-geochemical-map": {
        "sample_type_raw": "river sediment",
        "sample_type": "sediment_stream",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "stream",
        "method_missing_reason": "not_reported",
        "citation_scope": "dataset",
    },
    "pangaea-north-africa-soil": {
        "sample_type_raw": "deflatable surface soil fraction",
        "sample_type": "soil_surface",
        "sample_type_mapping_status": "dataset_constant",
        "soil_horizon": "surface",
        "method_scope": "dataset",
        "method_assignment_basis": "dataset_documented_constant",
        "citation_scope": "dataset",
    },
    "foregs-topsoil": {
        "sample_type": "soil_topsoil",
        "sample_type_mapping_status": "dataset_constant",
        "soil_horizon": "topsoil",
        "method_scope": "file",
        "method_assignment_basis": "source_file_method_constant",
        "citation_scope": "dataset",
    },
    "foregs-subsoil": {
        "sample_type": "soil_subsoil",
        "sample_type_mapping_status": "dataset_constant",
        "soil_horizon": "subsoil",
        "method_scope": "file",
        "method_assignment_basis": "source_file_method_constant",
        "citation_scope": "dataset",
    },
    "foregs-humus": {
        "sample_type": "soil_humus",
        "sample_type_mapping_status": "dataset_constant",
        "soil_horizon": "organic_horizon",
        "method_scope": "file",
        "method_assignment_basis": "source_file_method_constant",
        "citation_scope": "dataset",
    },
    "foregs-stream-water": {
        "sample_type": "water_stream",
        "sample_type_mapping_status": "dataset_constant",
        "water_body_type": "stream",
        "water_fraction": "dissolved",
        "filtered_state": "filtered_<0.45um",
        "method_scope": "file",
        "method_assignment_basis": "source_file_method_constant",
        "citation_scope": "dataset",
    },
    "foregs-stream-sediment": {
        "sample_type": "sediment_stream",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "stream",
        "method_scope": "file",
        "method_assignment_basis": "source_file_method_constant",
        "citation_scope": "dataset",
    },
    "foregs-floodplain-sediment": {
        "sample_type": "sediment_floodplain",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "floodplain",
        "method_scope": "file",
        "method_assignment_basis": "source_file_method_constant",
        "citation_scope": "dataset",
    },
    "afsis-phase-i-wet-chemistry": {
        "method_scope": "dataset",
        "method_assignment_basis": "dataset_variable_and_threshold_metadata",
        "citation_scope": "dataset",
    },
    "us-wqp-sacramento-river-arsenic": {
        "sample_type_raw": "Water / Surface Water / Stream",
        "sample_type": "water_stream",
        "sample_type_mapping_status": "exact",
        "water_body_type": "stream",
        "water_fraction": "dissolved",
        "filtered_state": "filtered_water_method",
        "method_scope": "observation",
        "method_assignment_basis": "result_row_analytical_method_fields",
        "citation_scope": "observation",
    },
    "australia-ngsa-mercury": {
        "sediment_environment": "outlet_catchment",
        "method_scope": "dataset",
        "method_assignment_basis": "official_file_metadata_preamble",
        "citation_scope": "dataset",
    },
    "japan-gsj-marine-sediment": {
        "sample_type_raw": "marine sediment",
        "sample_type": "sediment_marine",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "marine",
        "method_missing_reason": "not_reported_in_concentration_csv",
        "citation_scope": "dataset",
    },
    "pangaea-arabian-sea-sediment": {
        "sample_type_raw": "marine core sediment",
        "sample_type": "sediment_marine_core",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "marine",
        "method_scope": "parameter",
        "method_assignment_basis": "pangaea_parameter_method_metadata",
        "citation_scope": "dataset",
    },
    "tpdc-china-mountain-soil": {
        "method_scope": "publication",
        "method_assignment_basis": "article_element_method_mapping",
        "citation_scope": "dataset",
    },
    "gemas-europe": {
        "method_scope": "dataset_analysis_group",
        "method_assignment_basis": "registered_AR_or_XRF_method_contract",
        "citation_scope": "dataset",
    },
    "usgs-utah-volcanic-whole-rock": {
        "sample_type_raw": "whole rock",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_constant",
        "method_scope": "observation",
        "method_assignment_basis": "source_method_table_and_row_method_codes",
        "citation_scope": "dataset",
    },
    "cdogs-210102-lake-sediment": {
        "sample_type_raw": "NGR lake sediment grab sample",
        "sample_type": "sediment_lake",
        "sample_type_mapping_status": "exact",
        "sediment_environment": "lake",
        "method_scope": "package_column",
        "method_assignment_basis": "official_cdogs_package_column_method_table",
        "citation_scope": "dataset",
    },
    "cdogs-210102-lake-water": {
        "sample_type_raw": "Fluid (lake)",
        "sample_type": "water_lake",
        "sample_type_mapping_status": "exact",
        "water_body_type": "lake",
        "water_fraction": "untreated",
        "method_scope": "package_column",
        "method_assignment_basis": "official_cdogs_package_column_method_table",
        "citation_scope": "dataset",
    },
    "brazil-sgb-florianopolis-stream-sediment": {
        "sample_type_raw": "sedimento de corrente",
        "sample_type": "sediment_stream",
        "sample_type_mapping_status": "mapped",
        "sediment_environment": "stream",
        "method_scope": "record",
        "method_assignment_basis": "source_workbook_leitura_field",
        "citation_scope": "dataset",
    },
}

SOIL_TYPE_MAP = {
    "top-0-5cm": ("soil_topsoil", "top_0_5cm"),
    "a-horizon": ("soil_a_horizon", "A"),
    "c-horizon": ("soil_c_horizon", "C"),
    "Topsoil": ("soil_topsoil", "topsoil"),
    "Subsoil": ("soil_subsoil", "subsoil"),
}

WATER_TYPE_MAP = {
    "Groundwater station": "water_groundwater",
    "Lake station": "water_lake",
    "Reservoir station": "water_reservoir",
    "River station": "water_river",
    "Wetland station": "water_wetland",
}


class SemanticError(ValueError):
    """Raised when a registered source cannot be mapped without inference."""


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return _text(values[0]) if values else ""


def _json_list(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return ""
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _sample_semantics(source_id: str, evidence: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, str]:
    result = {
        key: _text(contract.get(key))
        for key in (
            "sample_type_raw", "sample_type", "sample_type_mapping_status", "soil_horizon",
            "sediment_environment", "water_body_type", "water_fraction", "filtered_state",
        )
    }
    if source_id.startswith("foregs-"):
        result["sample_type_raw"] = _text(evidence.get("sample_type"))
    elif source_id == "usgs-conus-soil":
        raw = _text(evidence.get("soil_layer"))
        mapped = SOIL_TYPE_MAP.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped USGS soil layer: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped[0],
            sample_type_mapping_status="exact",
            soil_horizon_raw=raw,
            soil_horizon=mapped[1],
        )
    elif source_id == "afsis-phase-i-wet-chemistry":
        raw = _text(evidence.get("reported_depth"))
        mapped = SOIL_TYPE_MAP.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped AfSIS depth: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped[0],
            sample_type_mapping_status="exact",
            soil_horizon_raw=raw,
            soil_horizon=mapped[1],
        )
    elif source_id == "gemstat-open-archive":
        raw = _text(evidence.get("water_type"))
        canonical = WATER_TYPE_MAP.get(raw)
        if canonical is None:
            raise SemanticError(f"unmapped GEMStat water type: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=canonical,
            sample_type_mapping_status="exact",
            water_body_type=canonical.removeprefix("water_"),
            water_fraction=_text(evidence.get("water_fraction")),
        )
    elif source_id == "australia-ngsa-mercury":
        raw = _text(evidence.get("reported_depth"))
        mapped = {
            "TOS": "sediment_outlet_top",
            "BOS": "sediment_outlet_bottom",
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped NGSA outlet-sediment depth: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped,
            sample_type_mapping_status="exact",
        )
    elif source_id == "tpdc-china-mountain-soil":
        raw = _text(evidence.get("reported_horizon"))
        mapped = {"O": "soil_organic_horizon", "A": "soil_a_horizon", "C": "soil_c_horizon"}.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped TPDC soil horizon: {raw}")
        result.update(sample_type_raw=raw, sample_type=mapped, sample_type_mapping_status="exact",
                      soil_horizon_raw=raw, soil_horizon=raw)
    elif source_id == "gemas-europe":
        raw = _text(evidence.get("sample_type"))
        mapped = {"Ap": ("soil_agricultural_ploughed", "Ap"), "Gr": ("soil_grazing_land", "Gr")}.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped GEMAS soil type: {raw}")
        result.update(sample_type_raw=raw, sample_type=mapped[0], sample_type_mapping_status="exact",
                      soil_horizon_raw=raw, soil_horizon=mapped[1])
    elif source_id == "usgs-utah-volcanic-whole-rock":
        raw = _text(evidence.get("sample_type")) or "whole rock"
        result.update(sample_type_raw=raw, sample_type="rock_whole_rock", sample_type_mapping_status="dataset_constant")
    elif source_id.startswith("cdogs-210102-"):
        raw = _text(evidence.get("sample_type_raw"))
        if raw != _text(contract.get("sample_type_raw")):
            raise SemanticError(f"unexpected CDoGS sample type: {raw}")
    elif source_id == "brazil-sgb-florianopolis-stream-sediment":
        raw = _text(evidence.get("sample_type_raw"))
        result["sample_type_raw"] = raw
    return result


def _geographic_semantics(source_id: str, row: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, str]:
    legacy = _text(row.get("geologic_unit"))
    result = {
        "geologic_unit": "",
        "geologic_unit_raw": "",
        "matched_geologic_unit": "",
        "geology_missing_reason": "not_reported",
        "geographic_context_raw": _text(row.get("geographic_context_raw")),
        "survey_area": _text(row.get("survey_area")),
        "map_sheet": _text(row.get("map_sheet")),
        "cruise_track": _text(row.get("cruise_track")),
    }
    if source_id in {"georoc-archaean", "georoc-antarctica-intraplate"}:
        result["geographic_context_raw"] = result["geographic_context_raw"] or legacy
    elif source_id == "geotraces-idp2025":
        result["cruise_track"] = _text(evidence.get("cruise")) or result["cruise_track"]
        result["geographic_context_raw"] = " / ".join(
            part for part in (_text(evidence.get("cruise")), _text(evidence.get("station"))) if part
        )
    elif source_id == "japan-gsj-geochemical-map":
        result["map_sheet"] = _text(evidence.get("map_sheet")) or result["map_sheet"] or legacy
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                _text(evidence.get("reported_place")),
                _text(evidence.get("reported_river")),
                result["map_sheet"],
            )
            if part
        )
    elif source_id == "pangaea-north-africa-soil":
        result["survey_area"] = _text(evidence.get("potential_source_area")) or result["survey_area"] or legacy
        result["geographic_context_raw"] = (
            _text(evidence.get("reported_location")) or result["geographic_context_raw"]
        )
    elif source_id == "australia-ngsa-mercury":
        result["survey_area"] = _text(evidence.get("state")) or result["survey_area"]
        result["geographic_context_raw"] = " / ".join(
            part for part in (_text(evidence.get("state")), _text(evidence.get("site_id"))) if part
        )
    elif source_id == "japan-gsj-marine-sediment":
        result["cruise_track"] = _text(evidence.get("cruise")) or result["cruise_track"]
        result["survey_area"] = _text(evidence.get("region")) or result["survey_area"]
        result["geographic_context_raw"] = " / ".join(
            part for part in (result["survey_area"], result["cruise_track"]) if part
        )
    elif source_id == "pangaea-arabian-sea-sediment":
        result["cruise_track"] = _text(evidence.get("event")) or result["cruise_track"]
        result["survey_area"] = _text(evidence.get("location")) or result["survey_area"]
        result["geographic_context_raw"] = " / ".join(
            part for part in (result["survey_area"], result["cruise_track"]) if part
        )
    elif source_id == "tpdc-china-mountain-soil":
        result["survey_area"] = _text(evidence.get("mountain"))
        result["geographic_context_raw"] = " / ".join(
            part for part in (result["survey_area"], _text(evidence.get("site"))) if part
        )
    elif source_id == "gemas-europe":
        result["survey_area"] = _text(evidence.get("country_raw"))
        result["geographic_context_raw"] = result["survey_area"]
    elif source_id == "usgs-utah-volcanic-whole-rock":
        result["survey_area"] = _text(evidence.get("state"))
        result["geographic_context_raw"] = " / ".join(
            part for part in (result["survey_area"], _text(evidence.get("location"))) if part
        )
    elif source_id.startswith("cdogs-210102-"):
        result["survey_area"] = "CDoGS survey 21:0102"
        result["geographic_context_raw"] = " / ".join(
            part for part in (result["survey_area"], _text(evidence.get("site_id"))) if part
        )
    elif source_id == "brazil-sgb-florianopolis-stream-sediment":
        result["survey_area"] = "Florianopolis, Brazil"
        result["geographic_context_raw"] = " / ".join(
            part for part in (result["survey_area"], _text(evidence.get("project")), _text(evidence.get("sample_id"))) if part
        )
    return result


def enrich_row(
    row: Mapping[str, Any],
    evidence: Mapping[str, Any],
    registry_entry: Mapping[str, Any],
    registry_verified_at: str,
) -> dict[str, str]:
    """Return a V4 row using only explicit evidence and registered constants."""

    source_id = _text(row.get("source_id"))
    if source_id != _text(evidence.get("source_id")):
        raise SemanticError(f"row/evidence source mismatch: {source_id}")
    if _text(row.get("record_id")) != _text(evidence.get("record_id")):
        raise SemanticError(f"row/evidence record mismatch: {row.get('record_id')}")
    contract = SOURCE_CONTRACTS.get(source_id)
    if contract is None:
        raise SemanticError(f"no V4 semantic contract for source: {source_id}")
    result = {key: _text(value) for key, value in row.items()}
    result.update(_sample_semantics(source_id, evidence, contract))
    result.update(_geographic_semantics(source_id, row, evidence))

    analytical_method = _text(row.get("analytical_method"))
    if analytical_method:
        result.update(
            method_scope=_text(result.get("method_scope")) or _text(contract.get("method_scope")),
            method_assignment_basis=(
                _text(result.get("method_assignment_basis")) or _text(contract.get("method_assignment_basis"))
            ),
            analytical_technique=_text(result.get("analytical_technique")) or analytical_method,
            method_source_locator=(
                _text(evidence.get("method_source_locator"))
                or _text(evidence.get("metadata_source_locator"))
                or _text(row.get("source_locator"))
            ),
            method_missing_reason="",
        )
        if not result["method_scope"] or not result["method_assignment_basis"]:
            raise SemanticError(f"method contract is incomplete for source: {source_id}")
    else:
        result.update(
            method_scope="",
            method_assignment_basis="",
            analytical_technique="",
            method_source_locator="",
            method_missing_reason=_text(contract.get("method_missing_reason")) or "not_reported",
        )

    article_dois = evidence.get("article_dois")
    dataset_doi = _text(evidence.get("dataset_doi")) or _text(registry_entry.get("dataset_doi"))
    first_doi = _first(article_dois)
    publication_doi = first_doi if first_doi and first_doi.casefold() != dataset_doi.casefold() else ""
    citation_scope = _text(contract.get("citation_scope"))
    citation_ids = evidence.get("citation_ids")
    result.update(
        citation_id_raw=_json_list(citation_ids),
        publication_id=f"doi:{publication_doi}" if publication_doi else "",
        publication_doi=publication_doi,
        citation_text_raw=(
            _json_list(evidence.get("article_citations")) or _text(registry_entry.get("citation"))
        ),
        citation_scope=citation_scope,
        citation_assignment_basis=(
            "record_citation_ids" if citation_scope == "observation" else "dataset_metadata"
        ),
        citation_resolution_status=(
            "resolved" if _first(evidence.get("article_citations")) or registry_entry.get("citation") else "not_reported"
        ),
        citation_missing_reason="",
        method_publication_id=f"doi:{publication_doi}" if publication_doi and analytical_method else "",
    )
    if not result["citation_text_raw"]:
        result["citation_missing_reason"] = "not_reported"

    license_value = registry_entry.get("license")
    license_value = license_value if isinstance(license_value, Mapping) else {}
    result.update(
        access_status="public_download",
        research_use_status="permitted_research",
        license_url=_text(license_value.get("url")),
        license_scope="dataset",
        attribution_required=(
            "false" if _text(license_value.get("spdx")) == "LicenseRef-USGS-Public-Domain" else "true"
        ),
        redistribution_status="not_evaluated_for_project_output",
        terms_verified_at=registry_verified_at,
    )
    result["upstream_primary_source_id"] = ""
    return result
