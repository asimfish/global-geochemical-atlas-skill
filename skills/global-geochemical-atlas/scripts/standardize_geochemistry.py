#!/usr/bin/env python3
"""Conservative geochemical standardization, QC, confidence and anomaly baseline.

The module intentionally uses only the Python standard library so it can run in
OpenCode/Codex-style evaluation sandboxes without a heavyweight geospatial stack.
It never imputes censored values or silently swaps coordinates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

PIPELINE_VERSION = "d2-pipeline-v1"
CONFIDENCE_VERSION = "d2-confidence-v1"
ANOMALY_VERSION = "d2-robust-mad-v1"

MINIMUM_INPUT_COLUMNS = {"element_or_analyte", "value", "unit", "medium"}
DEFAULT_GROUP_BY = (
    "element_or_analyte",
    "medium",
    "sample_type",
    "soil_horizon",
    "sediment_environment",
    "water_fraction",
    "grain_fraction",
    "measurement_basis",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "analytical_method",
    "method_scope",
    "digestion_or_extraction",
)
GROUPABLE_FIELDS = {
    "element_or_analyte",
    "medium",
    "sample_type",
    "soil_horizon",
    "sediment_environment",
    "water_body_type",
    "water_fraction",
    "grain_fraction",
    "measurement_basis",
    "geologic_unit",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "analytical_method",
    "method_scope",
    "digestion_or_extraction",
    "source_id",
    "source_tier",
    "normalized_unit",
}

SCHEMA_COLUMNS = (
    "record_id",
    "sample_id",
    "element_or_analyte",
    "medium",
    "measurement_basis",
    "original_value_raw",
    "original_value",
    "original_unit",
    "value_qualifier",
    "normalized_value",
    "normalized_unit",
    "normalized_censoring_limit",
    "conversion_factor",
    "conversion_formula",
    "original_latitude_raw",
    "original_longitude_raw",
    "latitude",
    "longitude",
    "source_crs",
    "coordinate_uncertainty_m",
    "sampled_at",
    "sample_depth_min_m",
    "sample_depth_max_m",
    "grain_fraction",
    "sample_type_raw",
    "sample_type",
    "sample_type_mapping_status",
    "sample_type_missing_reason",
    "geographic_context_raw",
    "survey_area",
    "map_sheet",
    "cruise_track",
    "lithology_raw",
    "lithology",
    "soil_horizon_raw",
    "soil_horizon",
    "sediment_environment",
    "water_body_type",
    "water_fraction",
    "filtered_state",
    "geologic_unit",
    "geologic_unit_raw",
    "geologic_age_raw",
    "tectonic_setting_raw",
    "matched_geologic_unit",
    "geology_map_source",
    "geology_map_version",
    "match_method",
    "match_scale",
    "boundary_distance_m",
    "match_uncertainty",
    "geology_missing_reason",
    "analytical_method",
    "method_scope",
    "method_assignment_basis",
    "preparation",
    "analytical_technique",
    "instrument",
    "digestion_or_extraction",
    "laboratory",
    "detection_limit",
    "detection_limit_unit",
    "quantitation_limit",
    "quantitation_limit_unit",
    "reference_materials",
    "method_source_locator",
    "method_publication_id",
    "method_missing_reason",
    "citation_id_raw",
    "publication_id",
    "publication_doi",
    "citation_text_raw",
    "citation_scope",
    "citation_assignment_basis",
    "upstream_primary_source_id",
    "citation_resolution_status",
    "citation_missing_reason",
    "source_id",
    "source_locator",
    "license",
    "access_status",
    "research_use_status",
    "license_url",
    "license_scope",
    "attribution_required",
    "redistribution_status",
    "terms_verified_at",
    "source_tier",
    "qc_flags",
    "operational_confidence",
)

FLAG_SEVERITY = {
    "MISSING_VALUE": "error",
    "INVALID_NUMERIC_VALUE": "error",
    "INVALID_DETECTION_LIMIT": "error",
    "NEGATIVE_CONCENTRATION": "error",
    "UNSUPPORTED_UNIT": "error",
    "AMBIGUOUS_AQUEOUS_RATIO_UNIT": "error",
    "INVALID_COORDINATE": "error",
    "UNSUPPORTED_SOURCE_CRS": "error",
    "DEPTH_RANGE_INVALID": "error",
    "CENSORED_VALUE": "info",
    "GENERATED_RECORD_ID": "info",
    "DUPLICATE_CANDIDATE": "warning",
    "NONDETECT_WITHOUT_LIMIT": "warning",
    "MISSING_MEASUREMENT_BASIS": "warning",
    "MISSING_ANALYTICAL_METHOD": "warning",
    "MISSING_DIGESTION_OR_EXTRACTION": "warning",
    "UNRECOGNIZED_ANALYTE": "warning",
    "UNRECOGNIZED_MEDIUM": "warning",
    "POSSIBLE_COORDINATE_SWAP": "warning",
    "INCOMPLETE_COORDINATE": "warning",
    "ZERO_ISLAND_COORDINATE": "warning",
    "OUTSIDE_REQUEST_REGION": "warning",
    "MISSING_SOURCE_CRS": "warning",
    "MISSING_COORDINATE_UNCERTAINTY": "warning",
    "INVALID_COORDINATE_UNCERTAINTY": "warning",
    "MISSING_SOURCE_ID": "warning",
    "MISSING_SOURCE_LOCATOR": "warning",
    "MISSING_LICENSE": "warning",
    "UNKNOWN_SOURCE_TIER": "warning",
    "MISSING_SAMPLE_ID": "warning",
}

ELEMENT_SYMBOLS = {
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne", "Na", "Mg", "Al", "Si", "P", "S",
    "Cl", "Ar", "K", "Ca", "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn", "Ga", "Ge",
    "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr", "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd",
    "In", "Sn", "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd",
    "Tb", "Dy", "Ho", "Er", "Tm", "Yb", "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm",
    "Bk", "Cf", "Es", "Fm", "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds", "Rg", "Cn",
    "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
}

ELEMENT_NAMES = {
    "aluminium": "Al", "aluminum": "Al", "antimony": "Sb", "arsenic": "As", "barium": "Ba",
    "beryllium": "Be", "bismuth": "Bi", "boron": "B", "cadmium": "Cd", "calcium": "Ca",
    "carbon": "C", "cerium": "Ce", "cesium": "Cs", "caesium": "Cs", "chromium": "Cr",
    "cobalt": "Co", "copper": "Cu", "dysprosium": "Dy", "erbium": "Er", "europium": "Eu",
    "fluorine": "F", "gadolinium": "Gd", "gallium": "Ga", "germanium": "Ge", "gold": "Au",
    "hafnium": "Hf", "holmium": "Ho", "indium": "In", "iodine": "I", "iron": "Fe",
    "lanthanum": "La", "lead": "Pb", "lithium": "Li", "lutetium": "Lu", "magnesium": "Mg",
    "manganese": "Mn", "mercury": "Hg", "molybdenum": "Mo", "neodymium": "Nd", "nickel": "Ni",
    "niobium": "Nb", "palladium": "Pd", "phosphorus": "P", "platinum": "Pt", "potassium": "K",
    "praseodymium": "Pr", "rhenium": "Re", "rubidium": "Rb", "samarium": "Sm", "scandium": "Sc",
    "selenium": "Se", "silicon": "Si", "silver": "Ag", "sodium": "Na", "strontium": "Sr",
    "sulfur": "S", "sulphur": "S", "tantalum": "Ta", "tellurium": "Te", "terbium": "Tb",
    "thallium": "Tl", "thorium": "Th", "thulium": "Tm", "tin": "Sn", "titanium": "Ti",
    "tungsten": "W", "uranium": "U", "vanadium": "V", "ytterbium": "Yb", "yttrium": "Y",
    "zinc": "Zn", "zirconium": "Zr",
    "砷": "As", "铅": "Pb", "镉": "Cd", "汞": "Hg", "铜": "Cu", "锌": "Zn", "铁": "Fe",
    "锰": "Mn", "铬": "Cr", "镍": "Ni", "钴": "Co", "金": "Au", "银": "Ag", "铀": "U",
}

MEDIUM_ALIASES = {
    "rock": "rock", "rocks": "rock", "bedrock": "rock", "岩石": "rock",
    "soil": "soil", "soils": "soil", "topsoil": "soil", "subsoil": "soil", "土壤": "soil",
    "sediment": "sediment", "sediments": "sediment", "stream sediment": "sediment",
    "stream_sediment": "sediment", "河流沉积物": "sediment", "沉积物": "sediment",
    "water": "water", "groundwater": "water", "surface water": "water", "surface_water": "water",
    "seawater": "water", "porewater": "water", "river water": "water", "水": "water", "水体": "water",
    "mineral": "mineral", "minerals": "mineral", "矿物": "mineral",
    "concentrate": "concentrate", "heavy mineral concentrate": "concentrate", "精矿": "concentrate",
}

SOLID_MEDIA = {"rock", "soil", "sediment", "mineral", "concentrate"}
SOLID_FACTORS = {
    "mg/kg": 1.0, "ppm": 1.0, "ug/g": 1.0, "g/t": 1.0,
    "wt%": 10_000.0,
    "ppb": 0.001, "ug/kg": 0.001, "ng/g": 0.001,
    "g/kg": 1_000.0, "mg/g": 1_000.0,
}
WATER_FACTORS = {"ug/l": 1.0, "mg/l": 1_000.0, "ng/l": 0.001, "g/l": 1_000_000.0}
AQUEOUS_AMBIGUOUS_UNITS = {
    "ppm", "ppb", "wt%", "%", "percent", "mg/kg", "ug/kg", "g/kg", "ug/g", "ng/g", "mg/g",
}

SOURCE_TIER_SCORES = {
    "official_curated": 1.0,
    "government": 0.95,
    "peer_reviewed": 0.90,
    "institutional_repository": 0.80,
    "author_supplement": 0.75,
    "aggregator": 0.55,
    "unknown": 0.30,
}
SOURCE_TIER_ALIASES = {
    "official": "official_curated", "official curated": "official_curated", "official_curated": "official_curated",
    "government": "government", "gov": "government", "government agency": "government",
    "peer reviewed": "peer_reviewed", "peer-reviewed": "peer_reviewed", "peer_reviewed": "peer_reviewed",
    "journal": "peer_reviewed", "institutional repository": "institutional_repository",
    "institutional_repository": "institutional_repository", "author supplement": "author_supplement",
    "author_supplement": "author_supplement", "supplement": "author_supplement",
    "aggregator": "aggregator", "unknown": "unknown", "": "unknown",
}

QUALIFIER_ALIASES = {
    "": "reported", "=": "reported", "reported": "reported", "exact": "reported",
    "~": "approximate", "approx": "approximate", "approximate": "approximate",
    "<": "lt", "lt": "lt", "<=": "le", "≤": "le", "le": "le",
    ">": "gt", "gt": "gt", ">=": "ge", "≥": "ge", "ge": "ge",
    "bdl": "bdl", "below detection limit": "bdl", "l": "bdl",
    "g": "gt",
    "nd": "nd", "n.d.": "nd", "not detected": "nd", "n": "nd",
}
CENSORED_QUALIFIERS = {"lt", "le", "gt", "ge", "bdl", "nd"}
# NAD83 geographic coordinates are map-ready at this workflow's declared 15 m
# uncertainty floor. The original datum is retained in source_crs; no claim of
# sub-metre WGS84 equivalence is made.
WGS84_CRS_ALIASES = {
    "epsg:4326", "4326", "wgs84", "wgs 84", "ogc:crs84", "crs84",
    "epsg:4269", "4269", "nad83", "nad 83",
}
NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
PREFIXED_NUMBER_RE = re.compile(r"^(<=|>=|<|>|≤|≥|~)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$")


class PipelineError(ValueError):
    """Raised for invalid pipeline input or configuration."""


def blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def parse_optional_float(value: Any) -> float | None:
    text = blank_to_none(value)
    if text is None:
        return None
    cleaned = text.replace(",", "")
    if not NUMBER_RE.fullmatch(cleaned):
        return None
    number = float(cleaned)
    return number if math.isfinite(number) else None


def normalize_analyte(value: Any) -> tuple[str, bool]:
    text = blank_to_none(value)
    if text is None:
        return "unknown", False
    by_name = ELEMENT_NAMES.get(text.casefold())
    if by_name:
        return by_name, True
    symbol = text[:1].upper() + text[1:].lower()
    if symbol in ELEMENT_SYMBOLS:
        return symbol, True
    return text, False


def normalize_medium(value: Any) -> tuple[str, bool]:
    text = blank_to_none(value)
    if text is None:
        return "unknown", False
    canonical = MEDIUM_ALIASES.get(text.casefold())
    return (canonical, True) if canonical else ("unknown", False)


def canonicalize_unit(value: Any) -> str | None:
    text = blank_to_none(value)
    if text is None:
        return None
    unit = text.casefold().replace("μ", "u").replace("µ", "u").replace("−", "-").replace("·", "")
    unit = unit.replace("micrograms", "ug").replace("microgram", "ug").replace("mcg", "ug")
    unit = unit.replace("milligrams", "mg").replace("milligram", "mg")
    unit = unit.replace("nanograms", "ng").replace("nanogram", "ng")
    unit = unit.replace("grams", "g").replace("gram", "g")
    unit = unit.replace("kilograms", "kg").replace("kilogram", "kg").replace("litres", "l").replace("liters", "l")
    unit = unit.replace("litre", "l").replace("liter", "l").replace("tonne", "t")
    unit = unit.replace("weightpercent", "wt%").replace("weight%", "wt%").replace("wt.%", "wt%")
    unit = re.sub(r"\s+", "", unit)
    unit = unit.replace("per", "/")
    unit = re.sub(r"kg\^?-?1$", "/kg", unit)
    unit = re.sub(r"g\^?-?1$", "/g", unit)
    unit = re.sub(r"l\^?-?1$", "/l", unit)
    unit = unit.replace("//", "/")
    aliases = {
        "wtpercent": "wt%",
        "mgkg": "mg/kg", "ugkg": "ug/kg", "gkg": "g/kg",
        "ugg": "ug/g", "ngg": "ng/g", "mgg": "mg/g", "gt": "g/t",
        "ugl": "ug/l", "mgl": "mg/l", "ngl": "ng/l", "gl": "g/l",
    }
    return aliases.get(unit, unit)


def parse_measurement(
    row: Mapping[str, Any], flags: list[str]
) -> tuple[float | None, str, float | None, float | None]:
    raw = blank_to_none(row.get("value"))
    explicit_qualifier = blank_to_none(row.get("value_qualifier"))
    qualifier: str | None = None
    number: float | None = None

    if raw is not None:
        compact = raw.strip().replace(",", "")
        match = PREFIXED_NUMBER_RE.fullmatch(compact)
        if match:
            qualifier = QUALIFIER_ALIASES.get((match.group(1) or "").casefold(), "reported")
            number = float(match.group(2))
        else:
            qualifier = QUALIFIER_ALIASES.get(compact.casefold())
            if qualifier is None:
                flags.append("INVALID_NUMERIC_VALUE")
                qualifier = "unknown"
    else:
        flags.append("MISSING_VALUE")

    if explicit_qualifier is not None:
        explicit = QUALIFIER_ALIASES.get(explicit_qualifier.casefold())
        if explicit is None:
            qualifier = "unknown"
        else:
            qualifier = explicit

    qualifier = qualifier or "unknown"
    detection_limit_raw = blank_to_none(row.get("detection_limit"))
    detection_limit = parse_optional_float(detection_limit_raw)
    if detection_limit_raw is not None and (detection_limit is None or detection_limit < 0):
        detection_limit = None
        flags.append("INVALID_DETECTION_LIMIT")
    censoring_limit = number if qualifier in {"lt", "le", "gt", "ge"} else detection_limit

    if qualifier in CENSORED_QUALIFIERS:
        flags.append("CENSORED_VALUE")
        if censoring_limit is None:
            flags.append("NONDETECT_WITHOUT_LIMIT")
    if number is not None and number < 0:
        flags.append("NEGATIVE_CONCENTRATION")
    return number, qualifier, censoring_limit, detection_limit


def conversion_for(medium: str, original_unit: Any, flags: list[str]) -> tuple[float | None, str | None]:
    unit = canonicalize_unit(original_unit)
    if medium in SOLID_MEDIA and unit in SOLID_FACTORS:
        return SOLID_FACTORS[unit], "mg/kg"
    if medium == "water" and unit == "nmol/kg":
        return 1.0, "nmol/kg"
    if medium == "water" and unit in WATER_FACTORS:
        return WATER_FACTORS[unit], "ug/L"
    if medium == "water" and unit in AQUEOUS_AMBIGUOUS_UNITS:
        flags.append("AMBIGUOUS_AQUEOUS_RATIO_UNIT")
        return None, None
    flags.append("UNSUPPORTED_UNIT")
    return None, None


def add_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def is_wgs84_crs(value: str) -> bool:
    return value.casefold().strip() in WGS84_CRS_ALIASES


def normalize_coordinates(
    row: Mapping[str, Any], flags: list[str], region_bbox: tuple[float, float, float, float] | None
) -> tuple[str | None, str | None, float | None, float | None]:
    lat_raw = blank_to_none(row.get("latitude"))
    lon_raw = blank_to_none(row.get("longitude"))
    lat = parse_optional_float(lat_raw)
    lon = parse_optional_float(lon_raw)

    if lat_raw is None and lon_raw is None:
        return None, None, None, None
    if lat_raw is None or lon_raw is None or lat is None or lon is None:
        add_flag(flags, "INCOMPLETE_COORDINATE")
        add_flag(flags, "INVALID_COORDINATE")
        return lat_raw, lon_raw, None, None

    valid = -90 <= lat <= 90 and -180 <= lon <= 180
    if not valid:
        add_flag(flags, "INVALID_COORDINATE")
        if -90 <= lon <= 90 and -180 <= lat <= 180:
            add_flag(flags, "POSSIBLE_COORDINATE_SWAP")
        return lat_raw, lon_raw, None, None

    if lat == 0 and lon == 0:
        add_flag(flags, "ZERO_ISLAND_COORDINATE")
    if region_bbox is not None:
        west, south, east, north = region_bbox
        longitude_inside = west <= lon <= east if west <= east else lon >= west or lon <= east
        if not (longitude_inside and south <= lat <= north):
            add_flag(flags, "OUTSIDE_REQUEST_REGION")
    return lat_raw, lon_raw, lat, lon


def normalize_source_tier(value: Any, flags: list[str]) -> str:
    text = (blank_to_none(value) or "").casefold()
    tier = SOURCE_TIER_ALIASES.get(text, "unknown")
    if tier == "unknown":
        add_flag(flags, "UNKNOWN_SOURCE_TIER")
    return tier


def normalize_depth(row: Mapping[str, Any], flags: list[str]) -> tuple[float | None, float | None]:
    depth_min = parse_optional_float(row.get("sample_depth_min_m"))
    depth_max = parse_optional_float(row.get("sample_depth_max_m"))
    invalid_raw = (
        (blank_to_none(row.get("sample_depth_min_m")) is not None and depth_min is None)
        or (blank_to_none(row.get("sample_depth_max_m")) is not None and depth_max is None)
    )
    if invalid_raw or (depth_min is not None and depth_min < 0) or (depth_max is not None and depth_max < 0):
        add_flag(flags, "DEPTH_RANGE_INVALID")
        return None, None
    if depth_min is not None and depth_max is not None and depth_min > depth_max:
        add_flag(flags, "DEPTH_RANGE_INVALID")
        return depth_min, depth_max
    return depth_min, depth_max


def stable_record_id(row: Mapping[str, Any], row_number: int) -> str:
    payload = {
        "source_id": blank_to_none(row.get("source_id")),
        "sample_id": blank_to_none(row.get("sample_id")),
        "analyte": blank_to_none(row.get("element_or_analyte")),
        "value": blank_to_none(row.get("value")),
        "unit": blank_to_none(row.get("unit")),
        "row_number": row_number,
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    return f"gen-{digest}"


def score_confidence(record: Mapping[str, Any]) -> dict[str, float | str]:
    flags = list(record["qc_flags"])
    tier = str(record["source_tier"])
    source = SOURCE_TIER_SCORES.get(tier, SOURCE_TIER_SCORES["unknown"])
    if record["source_id"] is None:
        source -= 0.15
    if record["source_locator"] is None:
        source -= 0.25
    if record["license"] is None:
        source -= 0.10
    source = max(0.0, min(1.0, source))

    completeness_fields = (
        "sample_id", "element_or_analyte", "medium", "measurement_basis", "original_unit",
        "source_id", "source_locator", "analytical_method", "digestion_or_extraction", "license",
    )
    present = sum(record[field] not in (None, "", "unknown") for field in completeness_fields)
    present += int(record["latitude"] is not None and record["longitude"] is not None)
    completeness = present / (len(completeness_fields) + 1)

    method = statistics.fmean(
        float(record[field] not in (None, ""))
        for field in ("measurement_basis", "analytical_method", "digestion_or_extraction")
    )

    if record["latitude"] is None or record["longitude"] is None:
        spatial = 0.0
    else:
        spatial = 0.60 + (0.20 if record["source_crs"] else 0.0)
        uncertainty = record["coordinate_uncertainty_m"]
        if uncertainty is not None:
            if uncertainty <= 100:
                spatial += 0.20
            elif uncertainty <= 1_000:
                spatial += 0.15
            elif uncertainty <= 10_000:
                spatial += 0.10
            else:
                spatial += 0.05
        if "ZERO_ISLAND_COORDINATE" in flags:
            spatial = min(spatial, 0.30)
        spatial = min(1.0, spatial)

    severity_counts = Counter(FLAG_SEVERITY.get(flag, "warning") for flag in flags)
    qc = max(
        0.0,
        1.0
        - 0.35 * severity_counts["error"]
        - 0.08 * severity_counts["warning"]
        - 0.02 * severity_counts["info"],
    )
    overall = 0.30 * source + 0.20 * completeness + 0.20 * method + 0.15 * spatial + 0.15 * qc
    if severity_counts["error"]:
        overall = min(overall, 0.59)
    band = "high" if overall >= 0.80 else "medium" if overall >= 0.60 else "low"
    return {
        "version": CONFIDENCE_VERSION,
        "source": round(source, 6),
        "completeness": round(completeness, 6),
        "method": round(method, 6),
        "spatial": round(spatial, 6),
        "qc": round(qc, 6),
        "overall": round(overall, 6),
        "band": band,
    }


def normalize_row(
    row: Mapping[str, Any], row_number: int, region_bbox: tuple[float, float, float, float] | None = None
) -> dict[str, Any]:
    flags: list[str] = []
    analyte, analyte_recognized = normalize_analyte(row.get("element_or_analyte"))
    if not analyte_recognized:
        add_flag(flags, "UNRECOGNIZED_ANALYTE")
    medium, medium_recognized = normalize_medium(row.get("medium"))
    if not medium_recognized:
        add_flag(flags, "UNRECOGNIZED_MEDIUM")

    record_id = blank_to_none(row.get("record_id"))
    if record_id is None:
        record_id = stable_record_id(row, row_number)
        add_flag(flags, "GENERATED_RECORD_ID")
    sample_id = blank_to_none(row.get("sample_id"))
    if sample_id is None:
        add_flag(flags, "MISSING_SAMPLE_ID")

    measurement_basis = blank_to_none(row.get("measurement_basis"))
    if measurement_basis is None:
        add_flag(flags, "MISSING_MEASUREMENT_BASIS")
    analytical_method = blank_to_none(row.get("analytical_method"))
    if analytical_method is None:
        add_flag(flags, "MISSING_ANALYTICAL_METHOD")
    digestion = blank_to_none(row.get("digestion_or_extraction"))
    if digestion is None:
        add_flag(flags, "MISSING_DIGESTION_OR_EXTRACTION")

    source_id = blank_to_none(row.get("source_id"))
    if source_id is None:
        add_flag(flags, "MISSING_SOURCE_ID")
    source_locator = blank_to_none(row.get("source_locator"))
    if source_locator is None:
        add_flag(flags, "MISSING_SOURCE_LOCATOR")
    license_value = blank_to_none(row.get("license"))
    if license_value is None:
        add_flag(flags, "MISSING_LICENSE")
    source_tier = normalize_source_tier(row.get("source_tier"), flags)

    original_value, qualifier, censoring_limit, detection_limit = parse_measurement(row, flags)
    factor, normalized_unit = conversion_for(medium, row.get("unit"), flags)
    normalized_value: float | None = None
    normalized_censoring_limit: float | None = None
    if factor is not None:
        if qualifier not in CENSORED_QUALIFIERS and original_value is not None and original_value >= 0:
            normalized_value = original_value * factor
        if qualifier in CENSORED_QUALIFIERS and censoring_limit is not None and censoring_limit >= 0:
            limit_unit = blank_to_none(row.get("detection_limit_unit"))
            if qualifier in {"bdl", "nd"} and limit_unit is not None:
                limit_flags: list[str] = []
                limit_factor, limit_target = conversion_for(medium, limit_unit, limit_flags)
                if limit_factor is not None and limit_target == normalized_unit:
                    normalized_censoring_limit = censoring_limit * limit_factor
                else:
                    for flag in limit_flags:
                        add_flag(flags, flag)
            else:
                normalized_censoring_limit = censoring_limit * factor

    lat_raw, lon_raw, latitude, longitude = normalize_coordinates(row, flags, region_bbox)
    source_crs = blank_to_none(row.get("source_crs"))
    if source_crs is None:
        add_flag(flags, "MISSING_SOURCE_CRS")
    elif (lat_raw is not None or lon_raw is not None) and not is_wgs84_crs(source_crs):
        add_flag(flags, "UNSUPPORTED_SOURCE_CRS")
        latitude = None
        longitude = None
    coordinate_uncertainty = parse_optional_float(row.get("coordinate_uncertainty_m"))
    uncertainty_raw = blank_to_none(row.get("coordinate_uncertainty_m"))
    if uncertainty_raw is None:
        add_flag(flags, "MISSING_COORDINATE_UNCERTAINTY")
    elif coordinate_uncertainty is None or coordinate_uncertainty < 0:
        coordinate_uncertainty = None
        add_flag(flags, "INVALID_COORDINATE_UNCERTAINTY")

    depth_min, depth_max = normalize_depth(row, flags)
    original_unit = blank_to_none(row.get("unit"))
    record: dict[str, Any] = {
        "record_id": record_id,
        "sample_id": sample_id,
        "element_or_analyte": analyte,
        "medium": medium,
        "measurement_basis": measurement_basis,
        "original_value_raw": blank_to_none(row.get("value")),
        "original_value": original_value,
        "original_unit": original_unit,
        "value_qualifier": qualifier,
        "normalized_value": round(normalized_value, 12) if normalized_value is not None else None,
        "normalized_unit": normalized_unit,
        "normalized_censoring_limit": (
            round(normalized_censoring_limit, 12) if normalized_censoring_limit is not None else None
        ),
        "conversion_factor": factor,
        "conversion_formula": f"normalized = original * {factor:g}" if factor is not None else None,
        "original_latitude_raw": lat_raw,
        "original_longitude_raw": lon_raw,
        "latitude": latitude,
        "longitude": longitude,
        "source_crs": source_crs,
        "coordinate_uncertainty_m": coordinate_uncertainty,
        "sampled_at": blank_to_none(row.get("sampled_at")),
        "sample_depth_min_m": depth_min,
        "sample_depth_max_m": depth_max,
        "grain_fraction": blank_to_none(row.get("grain_fraction")),
        "sample_type_raw": blank_to_none(row.get("sample_type_raw")),
        "sample_type": blank_to_none(row.get("sample_type")),
        "sample_type_mapping_status": blank_to_none(row.get("sample_type_mapping_status")),
        "sample_type_missing_reason": blank_to_none(row.get("sample_type_missing_reason")),
        "geographic_context_raw": blank_to_none(row.get("geographic_context_raw")),
        "survey_area": blank_to_none(row.get("survey_area")),
        "map_sheet": blank_to_none(row.get("map_sheet")),
        "cruise_track": blank_to_none(row.get("cruise_track")),
        "lithology_raw": blank_to_none(row.get("lithology_raw")),
        "lithology": blank_to_none(row.get("lithology")),
        "soil_horizon_raw": blank_to_none(row.get("soil_horizon_raw")),
        "soil_horizon": blank_to_none(row.get("soil_horizon")),
        "sediment_environment": blank_to_none(row.get("sediment_environment")),
        "water_body_type": blank_to_none(row.get("water_body_type")),
        "water_fraction": blank_to_none(row.get("water_fraction")),
        "filtered_state": blank_to_none(row.get("filtered_state")),
        "geologic_unit": blank_to_none(row.get("geologic_unit")),
        "geologic_unit_raw": blank_to_none(row.get("geologic_unit_raw")),
        "geologic_age_raw": blank_to_none(row.get("geologic_age_raw")),
        "tectonic_setting_raw": blank_to_none(row.get("tectonic_setting_raw")),
        "matched_geologic_unit": blank_to_none(row.get("matched_geologic_unit")),
        "geology_map_source": blank_to_none(row.get("geology_map_source")),
        "geology_map_version": blank_to_none(row.get("geology_map_version")),
        "match_method": blank_to_none(row.get("match_method")),
        "match_scale": blank_to_none(row.get("match_scale")),
        "boundary_distance_m": parse_optional_float(row.get("boundary_distance_m")),
        "match_uncertainty": blank_to_none(row.get("match_uncertainty")),
        "geology_missing_reason": blank_to_none(row.get("geology_missing_reason")),
        "analytical_method": analytical_method,
        "method_scope": blank_to_none(row.get("method_scope")),
        "method_assignment_basis": blank_to_none(row.get("method_assignment_basis")),
        "preparation": blank_to_none(row.get("preparation")),
        "analytical_technique": blank_to_none(row.get("analytical_technique")),
        "instrument": blank_to_none(row.get("instrument")),
        "digestion_or_extraction": digestion,
        "laboratory": blank_to_none(row.get("laboratory")),
        "detection_limit": detection_limit,
        "detection_limit_unit": blank_to_none(row.get("detection_limit_unit")),
        "quantitation_limit": parse_optional_float(row.get("quantitation_limit")),
        "quantitation_limit_unit": blank_to_none(row.get("quantitation_limit_unit")),
        "reference_materials": blank_to_none(row.get("reference_materials")),
        "method_source_locator": blank_to_none(row.get("method_source_locator")),
        "method_publication_id": blank_to_none(row.get("method_publication_id")),
        "method_missing_reason": blank_to_none(row.get("method_missing_reason")),
        "citation_id_raw": blank_to_none(row.get("citation_id_raw")),
        "publication_id": blank_to_none(row.get("publication_id")),
        "publication_doi": blank_to_none(row.get("publication_doi")),
        "citation_text_raw": blank_to_none(row.get("citation_text_raw")),
        "citation_scope": blank_to_none(row.get("citation_scope")),
        "citation_assignment_basis": blank_to_none(row.get("citation_assignment_basis")),
        "upstream_primary_source_id": blank_to_none(row.get("upstream_primary_source_id")),
        "citation_resolution_status": blank_to_none(row.get("citation_resolution_status")),
        "citation_missing_reason": blank_to_none(row.get("citation_missing_reason")),
        "source_id": source_id,
        "source_locator": source_locator,
        "license": license_value,
        "access_status": blank_to_none(row.get("access_status")),
        "research_use_status": blank_to_none(row.get("research_use_status")),
        "license_url": blank_to_none(row.get("license_url")),
        "license_scope": blank_to_none(row.get("license_scope")),
        "attribution_required": blank_to_none(row.get("attribution_required")),
        "redistribution_status": blank_to_none(row.get("redistribution_status")),
        "terms_verified_at": blank_to_none(row.get("terms_verified_at")),
        "source_tier": source_tier,
        "qc_flags": flags,
    }
    record["operational_confidence"] = score_confidence(record)
    return record


def duplicate_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        record["source_id"], record["sample_id"], record["element_or_analyte"], record["original_value_raw"],
        record["original_unit"], record["analytical_method"], record["measurement_basis"],
        record["original_latitude_raw"], record["original_longitude_raw"],
    )


def mark_duplicate_candidates(records: list[dict[str, Any]]) -> None:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[duplicate_key(record)].append(record)
    for candidates in groups.values():
        if len(candidates) < 2:
            continue
        for record in candidates:
            add_flag(record["qc_flags"], "DUPLICATE_CANDIDATE")
            record["operational_confidence"] = score_confidence(record)


def process_rows(
    rows: Iterable[Mapping[str, Any]], region_bbox: tuple[float, float, float, float] | None = None
) -> list[dict[str, Any]]:
    records = [normalize_row(row, index, region_bbox) for index, row in enumerate(rows, start=2)]
    mark_duplicate_candidates(records)
    return records


def group_identifier(group_by: Sequence[str], key: Sequence[Any]) -> str:
    payload = dict(zip(group_by, key, strict=True))
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    return f"grp-{digest}"


def detect_anomalies(
    records: Sequence[Mapping[str, Any]], group_by: Sequence[str] = DEFAULT_GROUP_BY,
    min_group_size: int = 8, robust_z_threshold: float = 3.5,
) -> tuple[dict[str, Any], dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[tuple(record.get(field) for field in group_by)].append(record)

    features: list[dict[str, Any]] = []
    group_reports: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: tuple("" if value is None else str(value) for value in item)):
        group_records = grouped[key]
        usable: list[Mapping[str, Any]] = []
        exclusions: Counter[str] = Counter()
        for record in group_records:
            value = record.get("normalized_value")
            if "DUPLICATE_CANDIDATE" in record.get("qc_flags", []):
                exclusions["duplicate_candidate"] += 1
            elif record.get("value_qualifier") in CENSORED_QUALIFIERS:
                exclusions["censored"] += 1
            elif value is None:
                exclusions["not_standardized"] += 1
            elif not isinstance(value, (int, float)) or value <= 0:
                exclusions["non_positive"] += 1
            else:
                usable.append(record)

        group_id = group_identifier(group_by, key)
        report: dict[str, Any] = {
            "group_id": group_id,
            "group": dict(zip(group_by, key, strict=True)),
            "records_total": len(group_records),
            "records_used": len(usable),
            "records_excluded": len(group_records) - len(usable),
            "exclusion_reasons": dict(sorted(exclusions.items())),
            "status": "insufficient_group_size",
            "log10_median": None,
            "log10_mad": None,
            "candidate_count": 0,
        }
        if len(usable) < min_group_size:
            group_reports.append(report)
            continue

        log_values = [math.log10(float(record["normalized_value"])) for record in usable]
        median = statistics.median(log_values)
        mad = statistics.median(abs(value - median) for value in log_values)
        report["log10_median"] = round(median, 12)
        report["log10_mad"] = round(mad, 12)
        if mad == 0:
            report["status"] = "zero_dispersion"
            group_reports.append(report)
            continue

        report["status"] = "analyzed"
        candidates: list[tuple[Mapping[str, Any], float]] = []
        for record, log_value in zip(usable, log_values, strict=True):
            robust_z = 0.67448975 * (log_value - median) / mad
            if abs(robust_z) >= robust_z_threshold:
                candidates.append((record, robust_z))
        report["candidate_count"] = len(candidates)
        for record, robust_z in sorted(candidates, key=lambda item: str(item[0]["record_id"])):
            longitude, latitude = record.get("longitude"), record.get("latitude")
            geometry = None
            if longitude is not None and latitude is not None:
                geometry = {"type": "Point", "coordinates": [longitude, latitude]}
            features.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": {
                        "record_id": record["record_id"],
                        "sample_id": record["sample_id"],
                        "element_or_analyte": record["element_or_analyte"],
                        "medium": record["medium"],
                        "sample_type": record["sample_type"],
                        "soil_horizon": record["soil_horizon"],
                        "sediment_environment": record["sediment_environment"],
                        "water_fraction": record["water_fraction"],
                        "grain_fraction": record["grain_fraction"],
                        "measurement_basis": record["measurement_basis"],
                        "geologic_unit": record["geologic_unit"],
                        "geologic_unit_raw": record["geologic_unit_raw"],
                        "matched_geologic_unit": record["matched_geologic_unit"],
                        "normalized_value": record["normalized_value"],
                        "normalized_unit": record["normalized_unit"],
                        "group_id": group_id,
                        "robust_z": round(robust_z, 6),
                        "direction": "high" if robust_z > 0 else "low",
                        "status": "candidate_anomaly",
                        "method_version": ANOMALY_VERSION,
                        "interpretation_limit": "Candidate relative to the declared background group; no causal claim.",
                    },
                }
            )
        group_reports.append(report)

    geojson = {
        "type": "FeatureCollection",
        "name": "geochemical_candidate_anomalies",
        "features": features,
    }
    anomaly_report = {
        "method_version": ANOMALY_VERSION,
        "method": "log10 median/MAD modified robust z-score",
        "group_by": list(group_by),
        "minimum_group_size": min_group_size,
        "robust_z_threshold": robust_z_threshold,
        "scientific_status": "screening_baseline_only",
        "caveat": (
            "Candidates are relative to the declared background group and do not establish pollution, mineralization, "
            "provenance, or cause."
        ),
        "candidate_count": len(features),
        "groups": group_reports,
    }
    return geojson, anomaly_report


def build_qc_report(records: Sequence[Mapping[str, Any]], run_metadata: Mapping[str, Any]) -> dict[str, Any]:
    flags = Counter(flag for record in records for flag in record["qc_flags"])
    severity = Counter(FLAG_SEVERITY.get(flag, "warning") for record in records for flag in record["qc_flags"])
    numeric_or_limit = sum(
        record["original_value"] is not None or record["detection_limit"] is not None for record in records
    )
    standardized = sum(
        record["normalized_value"] is not None or record["normalized_censoring_limit"] is not None
        for record in records
    )
    return {
        "pipeline_version": PIPELINE_VERSION,
        "run_metadata": dict(run_metadata),
        "definitions": {
            "standardized_record": "normalized_value or normalized_censoring_limit is available",
            "coordinate_valid": "both canonical latitude and longitude are present and range-valid",
            "records_are_not_dropped": True,
        },
        "record_count": len(records),
        "records_with_numeric_value_or_limit": numeric_or_limit,
        "standardized_record_count": standardized,
        "standardization_rate": round(standardized / len(records), 6) if records else 0.0,
        "censored_record_count": sum(record["value_qualifier"] in CENSORED_QUALIFIERS for record in records),
        "valid_coordinate_count": sum(
            record["latitude"] is not None and record["longitude"] is not None for record in records
        ),
        "flag_counts": dict(sorted(flags.items())),
        "severity_counts": dict(sorted(severity.items())),
    }


def build_confidence_report(
    records: Sequence[Mapping[str, Any]], run_metadata: Mapping[str, Any]
) -> dict[str, Any]:
    components = ("source", "completeness", "method", "spatial", "qc", "overall")
    means = {
        component: round(
            statistics.fmean(float(record["operational_confidence"][component]) for record in records), 6
        ) if records else 0.0
        for component in components
    }
    bands = Counter(str(record["operational_confidence"]["band"]) for record in records)
    return {
        "confidence_version": CONFIDENCE_VERSION,
        "name": "operational_confidence",
        "not_a_probability": True,
        "meaning": "Record usability for this workflow; not truth probability, statistical confidence, or accuracy.",
        "run_metadata": dict(run_metadata),
        "weights": {"source": 0.30, "completeness": 0.20, "method": 0.20, "spatial": 0.15, "qc": 0.15},
        "band_thresholds": {"high": ">=0.80", "medium": ">=0.60 and <0.80", "low": "<0.60"},
        "gates": {"any_error_flag": "overall capped at 0.59 (low)"},
        "component_means": means,
        "band_counts": {band: bands.get(band, 0) for band in ("high", "medium", "low")},
    }


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    try:
        parts = tuple(float(part.strip()) for part in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bbox values must be numeric") from exc
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north")
    west, south, east, north = parts
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox values are outside valid longitude/latitude ranges")
    return west, south, east, north


def load_csv(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise PipelineError(f"input CSV does not exist: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PipelineError("input CSV has no header")
        headers = [header.strip() for header in reader.fieldnames]
        missing = sorted(MINIMUM_INPUT_COLUMNS - set(headers))
        if missing:
            raise PipelineError(f"input CSV missing minimum columns: {', '.join(missing)}")
        rows = [dict(row) for row in reader]
    if not rows:
        raise PipelineError("input CSV has no data rows")
    recommended = {
        "record_id", "sample_id", "measurement_basis", "source_id", "source_locator", "latitude", "longitude",
        "source_crs", "coordinate_uncertainty_m", "sample_type", "sample_type_mapping_status",
        "analytical_method", "method_scope", "digestion_or_extraction", "license", "source_tier",
    }
    return rows, sorted(recommended - set(headers))


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=SCHEMA_COLUMNS, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["qc_flags"] = json.dumps(row["qc_flags"], ensure_ascii=False, separators=(",", ":"))
            row["operational_confidence"] = json.dumps(
                row["operational_confidence"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            writer.writerow(row)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run_pipeline(
    input_path: Path, output_dir: Path, group_by: Sequence[str] = DEFAULT_GROUP_BY, min_group_size: int = 8,
    robust_z_threshold: float = 3.5, region_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Path]:
    unknown_group_fields = sorted(set(group_by) - GROUPABLE_FIELDS)
    if unknown_group_fields:
        raise PipelineError(f"unknown --group-by fields: {', '.join(unknown_group_fields)}")
    if min_group_size < 3:
        raise PipelineError("--min-group-size must be at least 3")
    if not math.isfinite(robust_z_threshold) or robust_z_threshold <= 0:
        raise PipelineError("--robust-z-threshold must be positive")

    input_bytes = input_path.read_bytes() if input_path.is_file() else b""
    rows, missing_recommended_columns = load_csv(input_path)
    records = process_rows(rows, region_bbox)
    config = {
        "group_by": list(group_by),
        "minimum_group_size": min_group_size,
        "robust_z_threshold": robust_z_threshold,
        "region_bbox": list(region_bbox) if region_bbox else None,
    }
    input_hash = hashlib.sha256(input_bytes).hexdigest()
    run_id = hashlib.sha256(
        (input_hash + json.dumps(config, sort_keys=True, separators=(",", ":"))).encode()
    ).hexdigest()[:16]
    run_metadata = {
        "run_id": run_id,
        "input_sha256": input_hash,
        "input_row_count": len(rows),
        "missing_recommended_input_columns": missing_recommended_columns,
        "configuration": config,
    }
    geojson, anomaly_report = detect_anomalies(records, group_by, min_group_size, robust_z_threshold)
    anomaly_report["run_metadata"] = run_metadata
    qc_report = build_qc_report(records, run_metadata)
    confidence_report = build_confidence_report(records, run_metadata)

    outputs = {
        "database": output_dir / "geochemistry.csv",
        "qc_report": output_dir / "qc_report.json",
        "confidence_report": output_dir / "confidence_report.json",
        "anomalies": output_dir / "anomalies.geojson",
        "anomaly_report": output_dir / "anomaly_report.json",
    }
    write_csv(outputs["database"], records)
    atomic_write_text(outputs["qc_report"], json_text(qc_report))
    atomic_write_text(outputs["confidence_report"], json_text(confidence_report))
    atomic_write_text(outputs["anomalies"], json_text(geojson))
    atomic_write_text(outputs["anomaly_report"], json_text(anomaly_report))
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standardize geochemical CSV records, run QC, score operational confidence, and screen anomalies."
    )
    parser.add_argument("--input", required=True, type=Path, help="Input CSV from the D1 acquisition/provenance stage")
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory for five deterministic D2 outputs")
    parser.add_argument(
        "--group-by", default=",".join(DEFAULT_GROUP_BY),
        help="Comma-separated canonical background fields (default: analyte, medium, basis, geologic unit)",
    )
    parser.add_argument("--min-group-size", type=int, default=8, help="Minimum positive uncensored records per group")
    parser.add_argument("--robust-z-threshold", type=float, default=3.5, help="Absolute modified z threshold")
    parser.add_argument(
        "--region-bbox", type=parse_bbox, metavar="W,S,E,N",
        help="Optional requested region; dateline-crossing west > east is supported",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    group_by = tuple(field.strip() for field in args.group_by.split(",") if field.strip())
    if not group_by:
        parser.error("--group-by must contain at least one field")
    try:
        outputs = run_pipeline(
            args.input, args.output_dir, group_by, args.min_group_size, args.robust_z_threshold, args.region_bbox
        )
    except (PipelineError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({name: str(path) for name, path in outputs.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
