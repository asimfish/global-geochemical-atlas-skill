#!/usr/bin/env python3
"""Evidence-bound V4 semantic mappings for the twenty-one executable sources."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any


SEMANTICS_VERSION = "d1-v4-source-semantics-v1"

SOURCE_CONTRACTS: dict[str, dict[str, Any]] = {
    "zenodo-gard-whole-rock": {
        "sample_type_raw": "whole rock",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_constant",
        "method_scope": "observation",
        "method_assignment_basis": "publisher_method_table_join_where_reported",
        "method_missing_reason": "not_reported",
        "citation_scope": "observation",
    },
    "georoc-archaean": {
        "sample_type_raw": "WR",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_constant",
        "method_missing_reason": "not_reported",
        "citation_scope": "observation",
    },
    "georoc-convergent-margins": {
        "sample_type_raw": "WR",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "dataset_constant",
        "method_missing_reason": "winning_method_not_encoded_in_precompiled_member",
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
        "method_scope": "dataset",
        "method_assignment_basis": "registered_dataset_method_by_analyte",
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
    "australia-ngsa": {
        "sediment_environment": "outlet_catchment",
        "method_scope": "dataset_parameter",
        "method_assignment_basis": "official_file_header_and_method_key",
        "citation_scope": "dataset",
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
    "earthchem-dehailonggang-rock": {
        "sample_type_raw": "whole rock",
        "sample_type": "rock_whole_rock",
        "sample_type_mapping_status": "exact",
        "method_scope": "dataset_parameter",
        "method_assignment_basis": "workbook_method_code_to_parameter_join",
        "citation_scope": "dataset",
    },
    "4tu-northern-china-sediment": {
        "method_scope": "dataset_parameter",
        "method_assignment_basis": "publisher_readme_element_method_mapping",
        "citation_scope": "dataset",
    },
    "pangaea-brasol-ne-brazil-soil": {
        "method_scope": "dataset_parameter",
        "method_assignment_basis": "publisher_metadata_and_selected_method_column",
        "citation_scope": "dataset",
    },
    "figshare-yangtze-basin-soil-heavy-metals": {
        "sample_type_raw": "literature-compiled soil occurrence",
        "sample_type": "soil_literature_occurrence",
        "sample_type_mapping_status": "dataset_constant",
        "method_missing_reason": "publisher_compilation_omits_row_method",
        "citation_scope": "dataset",
    },
    "eidc-ningbo-soil": {
        "sample_type_raw": "composite topsoil 0-20 cm",
        "sample_type": "soil_topsoil",
        "sample_type_mapping_status": "dataset_constant",
        "soil_horizon": "topsoil_0_20cm",
        "method_scope": "dataset_analyte",
        "method_assignment_basis": "publisher_supporting_document_and_csv_method_suffix",
        "citation_scope": "dataset",
    },
    "gemas-europe": {
        "method_scope": "dataset_analysis_group",
        "method_assignment_basis": "registered_AR_or_XRF_method_contract",
        "citation_scope": "dataset",
    },
    "zenodo-yangtze-yellow-river-sediment": {
        "sample_type_raw": "river sediment size-fraction separate",
        "sample_type": "sediment_river_fraction",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "river",
        "method_missing_reason": "workbook_reports_no_analytical_method",
        "citation_scope": "dataset",
    },
    "pangaea-east-china-sea-clay": {
        "method_scope": "parameter",
        "method_assignment_basis": "pangaea_parameter_method_metadata",
        "citation_scope": "dataset",
    },
    "pangaea-south-china-sea-sediment": {
        "sample_type_raw": "marine surface sediment",
        "sample_type": "sediment_marine_surface",
        "sample_type_mapping_status": "dataset_constant",
        "sediment_environment": "marine",
        "method_scope": "parameter",
        "method_assignment_basis": "pangaea_parameter_method_metadata",
        "citation_scope": "dataset",
    },
    "pangaea-barents-c-horizon-soil": {
        "sample_type_raw": "C-horizon soil",
        "sample_type": "soil_c_horizon",
        "sample_type_mapping_status": "dataset_constant",
        "soil_horizon": "C",
        "method_scope": "parameter",
        "method_assignment_basis": "pangaea_parameter_method_metadata",
        "citation_scope": "dataset",
    },
    "pangaea-amazonas-soil": {
        "method_scope": "parameter",
        "method_assignment_basis": "pangaea_parameter_method_metadata",
        "citation_scope": "dataset",
    },
    "pangaea-batagay-soil": {
        "method_scope": "parameter",
        "method_assignment_basis": "pangaea_parameter_method_metadata",
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


def _official_source_url(
    row: Mapping[str, Any],
    evidence: Mapping[str, Any],
    registry_entry: Mapping[str, Any],
) -> str:
    """Choose an evidence-backed official URL without corrupting DOI URLs."""

    for value in (row.get("official_source_url"), evidence.get("source_file_url")):
        text = _text(value)
        if text.startswith(("https://", "http://")):
            return text
    doi = _text(evidence.get("dataset_doi") or registry_entry.get("dataset_doi"))
    if doi.casefold().startswith("https://doi.org/"):
        return doi
    if doi.casefold().startswith("doi:"):
        doi = doi[4:].strip()
    if re.fullmatch(r"10\.\d{4,9}/\S+", doi, flags=re.IGNORECASE):
        return f"https://doi.org/{doi}"
    landing_page = _text(registry_entry.get("landing_page"))
    return landing_page if landing_page.startswith(("https://", "http://")) else ""


def _first(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return _text(values[0]) if values else ""


def _json_list(values: Any) -> str:
    if not isinstance(values, list) or not values:
        return ""
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _sample_semantics(
    source_id: str, evidence: Mapping[str, Any], contract: Mapping[str, Any]
) -> dict[str, str]:
    result = {
        key: _text(contract.get(key))
        for key in (
            "sample_type_raw",
            "sample_type",
            "sample_type_mapping_status",
            "soil_horizon",
            "sediment_environment",
            "water_body_type",
            "water_fraction",
            "filtered_state",
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
    elif source_id in {"australia-ngsa", "australia-ngsa-mercury"}:
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
    elif source_id == "4tu-northern-china-sediment":
        raw = _text(evidence.get("sample_type"))
        mapped = {
            "surface catchment, fluvial and/or alluvial sediment at approximately 25 cm depth": "sediment_surface_catchment_fluvial_alluvial",
            "last glacial loess, upper L1 Quaternary loess layer": "sediment_last_glacial_loess",
            "present interglacial sediment, S0 Quaternary paleosol layer": "sediment_present_interglacial_paleosol",
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped 4TU sediment type: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped,
            sample_type_mapping_status="exact",
            sediment_environment=_text(evidence.get("sediment_environment")),
        )
    elif source_id == "tpdc-china-mountain-soil":
        raw = _text(evidence.get("reported_horizon"))
        mapped = {
            "O": "soil_organic_horizon",
            "A": "soil_a_horizon",
            "C": "soil_c_horizon",
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped TPDC soil horizon: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped,
            sample_type_mapping_status="exact",
            soil_horizon_raw=raw,
            soil_horizon=raw,
        )
    elif source_id == "gemas-europe":
        raw = _text(evidence.get("sample_type"))
        mapped = {
            "Ap": ("soil_agricultural_ploughed", "Ap"),
            "Gr": ("soil_grazing_land", "Gr"),
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped GEMAS soil type: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped[0],
            sample_type_mapping_status="exact",
            soil_horizon_raw=raw,
            soil_horizon=mapped[1],
        )
    elif source_id == "pangaea-east-china-sea-clay":
        raw = _text(evidence.get("sample_fraction"))
        mapped = {
            "Bulk": "sediment_clay_fraction_bulk",
            "Residue": "sediment_clay_fraction_leach_residue",
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped East China Sea clay fraction: {raw}")
        event = _text(evidence.get("event"))
        if event.startswith(("331-", "ECS-")):
            sediment_environment = "marine"
        elif event.startswith(("CJ-", "TWR-")):
            sediment_environment = "river"
        else:
            raise SemanticError(
                f"unmapped East China Sea clay event environment: {event}"
            )
        result.update(
            sample_type_raw=raw,
            sample_type=mapped,
            sample_type_mapping_status="exact",
            sediment_environment=sediment_environment,
        )
    elif source_id == "pangaea-amazonas-soil":
        raw = _text(evidence.get("depth_class"))
        mapped = {
            "TOP": ("soil_topsoil", "topsoil_0_20cm"),
            "BOT": ("soil_subsoil", "subsoil_30_50cm"),
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped Amazonas depth class: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped[0],
            sample_type_mapping_status="exact",
            soil_horizon_raw=raw,
            soil_horizon=mapped[1],
        )
    elif source_id == "pangaea-brasol-ne-brazil-soil":
        raw = _text(evidence.get("layer"))
        mapped = {
            "ORG": ("soil_organic_litter", "organic_litter"),
            "TOP": ("soil_topsoil", "topsoil_0_20cm"),
            "BOT": ("soil_subsoil", "subsoil_30_50cm"),
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped BraSol layer: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped[0],
            sample_type_mapping_status="exact",
            soil_horizon_raw=raw,
            soil_horizon=mapped[1],
        )
    elif source_id == "pangaea-batagay-soil":
        raw = _text(evidence.get("sample_type")) or "not reported"
        mapped = {
            "Soil": "soil_profile",
            "Inclusions in Ice Wedge": "soil_inclusion_in_ice_wedge",
            "Ground particles included in ice, left after thawed ice water remove": "soil_ground_particles_from_thawed_ice",
            "not reported": "soil_material_unspecified",
        }.get(raw)
        if mapped is None:
            raise SemanticError(f"unmapped Batagay sample type: {raw}")
        result.update(
            sample_type_raw=raw,
            sample_type=mapped,
            sample_type_mapping_status="exact"
            if raw != "not reported"
            else "source_missing_mapped_to_unspecified",
            soil_horizon_raw=_text(evidence.get("soil_horizon")),
            soil_horizon=_text(evidence.get("soil_horizon")),
        )
    return result


def _geographic_semantics(
    source_id: str, row: Mapping[str, Any], evidence: Mapping[str, Any]
) -> dict[str, str]:
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
    if source_id in {
        "georoc-archaean",
        "georoc-convergent-margins",
        "georoc-antarctica-intraplate",
    }:
        result["geographic_context_raw"] = result["geographic_context_raw"] or legacy
    elif source_id == "geotraces-idp2025":
        result["cruise_track"] = _text(evidence.get("cruise")) or result["cruise_track"]
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (_text(evidence.get("cruise")), _text(evidence.get("station")))
            if part
        )
    elif source_id == "earthchem-dehailonggang-rock":
        result["survey_area"] = "Dehailonggang complex, East Kunlun Orogen"
        result["geographic_context_raw"] = legacy or result["survey_area"]
    elif source_id == "4tu-northern-china-sediment":
        result["survey_area"] = _text(evidence.get("survey_area"))
        result["geographic_context_raw"] = result["survey_area"]
    elif source_id == "japan-gsj-geochemical-map":
        result["map_sheet"] = (
            _text(evidence.get("map_sheet")) or result["map_sheet"] or legacy
        )
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                _text(evidence.get("reported_place")),
                _text(evidence.get("reported_river")),
                result["map_sheet"],
            )
            if part
        )
    elif source_id == "eidc-ningbo-soil":
        result["survey_area"] = "Ningbo Zhangxi catchment"
        result["geographic_context_raw"] = result["survey_area"]
    elif source_id == "pangaea-north-africa-soil":
        result["survey_area"] = (
            _text(evidence.get("potential_source_area"))
            or result["survey_area"]
            or legacy
        )
        result["geographic_context_raw"] = (
            _text(evidence.get("reported_location")) or result["geographic_context_raw"]
        )
    elif source_id in {"australia-ngsa", "australia-ngsa-mercury"}:
        result["survey_area"] = _text(evidence.get("state")) or result["survey_area"]
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (_text(evidence.get("state")), _text(evidence.get("site_id")))
            if part
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
            part
            for part in (result["survey_area"], _text(evidence.get("site")))
            if part
        )
    elif source_id == "zenodo-yangtze-yellow-river-sediment":
        result["survey_area"] = _text(evidence.get("river_system"))
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                result["survey_area"],
                _text(evidence.get("sample_label")),
            )
            if part
        )
    elif source_id == "pangaea-east-china-sea-clay":
        result["cruise_track"] = _text(evidence.get("event")) or result["cruise_track"]
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                _text(evidence.get("event")),
                _text(evidence.get("sample_description")),
            )
            if part
        )
    elif source_id == "pangaea-south-china-sea-sediment":
        result["cruise_track"] = _text(evidence.get("event")) or result["cruise_track"]
        result["geographic_context_raw"] = _text(evidence.get("event"))
    elif source_id == "pangaea-barents-c-horizon-soil":
        result["survey_area"] = "central Barents region"
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                "central Barents region",
                _text(evidence.get("sample_label")),
            )
            if part
        )
    elif source_id == "pangaea-amazonas-soil":
        result["survey_area"] = "Amazonas, Brazil"
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                _text(evidence.get("event")),
                _text(evidence.get("region")),
                _text(evidence.get("land_use")),
            )
            if part
        )
    elif source_id == "pangaea-brasol-ne-brazil-soil":
        result["survey_area"] = "northeastern Brazil transects"
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                result["survey_area"],
                _text(evidence.get("site_id")),
                _text(evidence.get("biome")),
                _text(evidence.get("land_use")),
            )
            if part
        )
    elif source_id == "figshare-yangtze-basin-soil-heavy-metals":
        result["survey_area"] = "Yangtze River Basin, China"
        hierarchy = evidence.get("location_hierarchy")
        result["geographic_context_raw"] = " / ".join(
            [result["survey_area"]]
            + [
                _text(item)
                for item in (hierarchy if isinstance(hierarchy, list) else [])
                if _text(item)
            ]
        )
    elif source_id == "pangaea-batagay-soil":
        result["survey_area"] = "Batagay megaslump, North Yakutia, Russia"
        result["geographic_context_raw"] = " / ".join(
            part
            for part in (
                result["survey_area"],
                _text(evidence.get("sampling_site")),
            )
            if part
        )
    elif source_id == "gemas-europe":
        result["survey_area"] = _text(evidence.get("country_raw"))
        result["geographic_context_raw"] = result["survey_area"]
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
    result.update(
        analyte_reported=_text(row.get("analyte_reported"))
        or _text(evidence.get("analyte_reported")),
        dataset_title=_text(row.get("dataset_title"))
        or _text(evidence.get("dataset_title")),
        dataset_doi=(
            _text(row.get("dataset_doi"))
            or _text(evidence.get("dataset_doi"))
            or _text(registry_entry.get("dataset_doi"))
        ),
        dataset_version=_text(row.get("dataset_version"))
        or _text(evidence.get("dataset_version")),
        source_file=_text(row.get("source_file")) or _text(evidence.get("source_file")),
        source_row=_text(row.get("source_row")) or _text(evidence.get("source_row")),
        official_source_url=_official_source_url(row, evidence, registry_entry),
        file_sha256=_text(row.get("file_sha256"))
        or _text(evidence.get("source_file_sha256")),
    )
    if source_id in {"georoc-archaean", "georoc-convergent-margins"}:
        coordinate_evidence = evidence.get("coordinate_evidence")
        coordinate_evidence = (
            coordinate_evidence if isinstance(coordinate_evidence, Mapping) else {}
        )
        result.update(
            original_latitude_raw=(
                _text(row.get("original_latitude_raw"))
                or _text(coordinate_evidence.get("reported_latitude"))
                or _text(row.get("latitude"))
            ),
            original_longitude_raw=(
                _text(row.get("original_longitude_raw"))
                or _text(coordinate_evidence.get("reported_longitude"))
                or _text(row.get("longitude"))
            ),
            latitude="",
            longitude="",
            source_crs="",
            coordinate_transform_method="",
            coordinate_uncertainty_m="",
        )
    result.update(_sample_semantics(source_id, evidence, contract))
    result.update(_geographic_semantics(source_id, row, evidence))

    analytical_method = _text(row.get("analytical_method"))
    if analytical_method:
        result.update(
            method_scope=_text(contract.get("method_scope")),
            method_assignment_basis=_text(contract.get("method_assignment_basis")),
            analytical_technique=analytical_method,
            method_source_locator=(
                _text(evidence.get("method_source_locator"))
                or _text(evidence.get("metadata_source_locator"))
                or _text(row.get("source_locator"))
            ),
            method_missing_reason="",
        )
        if not result["method_scope"] or not result["method_assignment_basis"]:
            raise SemanticError(
                f"method contract is incomplete for source: {source_id}"
            )
    else:
        result.update(
            method_scope="",
            method_assignment_basis="",
            analytical_technique="",
            method_source_locator="",
            method_missing_reason=_text(contract.get("method_missing_reason"))
            or "not_reported",
        )

    article_dois = evidence.get("article_dois")
    dataset_doi = _text(evidence.get("dataset_doi")) or _text(
        registry_entry.get("dataset_doi")
    )
    first_doi = _first(article_dois)
    publication_doi = (
        first_doi
        if first_doi and first_doi.casefold() != dataset_doi.casefold()
        else ""
    )
    citation_scope = _text(contract.get("citation_scope"))
    citation_ids = evidence.get("citation_ids")
    result.update(
        citation_id_raw=_json_list(citation_ids),
        publication_id=f"doi:{publication_doi}" if publication_doi else "",
        publication_doi=publication_doi,
        citation_text_raw=(
            _json_list(evidence.get("article_citations"))
            or _text(registry_entry.get("citation"))
        ),
        citation_scope=citation_scope,
        citation_assignment_basis=(
            "record_citation_ids"
            if citation_scope == "observation"
            else "dataset_metadata"
        ),
        citation_resolution_status=(
            "resolved"
            if _first(evidence.get("article_citations"))
            or registry_entry.get("citation")
            else "not_reported"
        ),
        citation_missing_reason="",
        method_publication_id=f"doi:{publication_doi}"
        if publication_doi and analytical_method
        else "",
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
            "false"
            if _text(license_value.get("spdx")) == "LicenseRef-USGS-Public-Domain"
            else "true"
        ),
        redistribution_status="not_evaluated_for_project_output",
        # The registry-wide timestamp advances whenever any source is
        # reverified.  Preserve an already-bound row timestamp so adding an
        # unrelated source does not rewrite every checked-in fixture and its
        # record IDs; new rows receive the current registry timestamp.
        terms_verified_at=_text(row.get("terms_verified_at")) or registry_verified_at,
    )
    result["upstream_primary_source_id"] = ""
    return result
