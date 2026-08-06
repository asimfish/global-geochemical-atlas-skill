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
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

INTERFACE_VERSION = "d2-interface-v2"
PIPELINE_VERSION = "d2-pipeline-v2"
CONFIDENCE_VERSION = "d2-confidence-v2"
ANOMALY_VERSION = "d2-robust-mad-v2"
ATOMIC_WEIGHT_VERSION = "d2-atomic-weights-v1"
GEOLOGY_JOIN_VERSION = "d2-glim-05deg-cell-join-v1"

MINIMUM_INPUT_COLUMNS = {"element_or_analyte", "value", "unit", "medium"}
DEFAULT_GROUP_BY = (
    "element_or_analyte",
    "medium",
    "material",
    "measurement_basis",
    "geologic_unit",
    "method_family",
    "digestion_or_extraction",
)
GROUPABLE_FIELDS = {
    "element_or_analyte",
    "medium",
    "material",
    "measurement_basis",
    "geologic_unit",
    "analytical_method",
    "method_family",
    "digestion_or_extraction",
    "source_id",
    "source_tier",
    "normalized_unit",
    "spatial_geologic_unit",
}

SCHEMA_COLUMNS = (
    "record_id",
    "source_record_id",
    "sample_id",
    "sample_identity_group",
    "replicate_group_id",
    "igsn",
    "element_or_analyte",
    "analyte_reported",
    "species_or_oxide",
    "medium",
    "material",
    "measurement_basis",
    "original_value_raw",
    "source_qualifier_raw",
    "original_value",
    "original_unit",
    "value_qualifier",
    "censored",
    "missing_reason",
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
    "coordinate_transform_method",
    "coordinate_uncertainty_m",
    "coordinate_uncertainty_status",
    "coordinate_uncertainty_basis",
    "coordinate_resolution_m",
    "coordinate_resolution_basis",
    "measurement_uncertainty",
    "measurement_uncertainty_unit",
    "measurement_uncertainty_basis",
    "sampled_at",
    "sample_depth_min_m",
    "sample_depth_max_m",
    "grain_fraction",
    "lithology",
    "geologic_unit",
    "geologic_unit_id",
    "geologic_context_source",
    "geologic_context_version",
    "geologic_match_method",
    "distance_to_geologic_boundary_m",
    "geologic_match_confidence",
    "geologic_context_status",
    "spatial_geology_status",
    "spatial_geologic_unit",
    "spatial_geologic_unit_id",
    "spatial_geology_source",
    "spatial_geology_version",
    "spatial_geology_match_method",
    "spatial_geology_resolution_deg",
    "spatial_geology_applicability",
    "spatial_geology_reason",
    "analytical_method",
    "analytical_method_status",
    "method_family",
    "digestion_or_extraction",
    "laboratory",
    "reference_material",
    "detection_limit",
    "detection_limit_unit",
    "source_id",
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_file",
    "source_row",
    "source_locator",
    "file_sha256",
    "license",
    "source_tier",
    "qc_flags",
    "operational_confidence",
)

INPUT_FIELDS = {
    "record_id", "source_record_id", "sample_id", "sample_identity_group", "replicate_group_id", "igsn",
    "element_or_analyte", "analyte_reported", "species_or_oxide", "value", "unit", "value_qualifier",
    "source_qualifier_raw",
    "missing_reason", "medium", "material", "measurement_basis", "original_latitude_raw",
    "original_longitude_raw", "latitude", "longitude", "source_crs",
    "coordinate_transform_method", "coordinate_uncertainty_m", "coordinate_uncertainty_status",
    "coordinate_uncertainty_basis", "coordinate_resolution_m", "coordinate_resolution_basis",
    "measurement_uncertainty", "measurement_uncertainty_unit", "measurement_uncertainty_basis",
    "sampled_at", "sample_depth_min_m",
    "sample_depth_max_m", "grain_fraction", "lithology", "geologic_unit", "geologic_unit_id",
    "geologic_context_source", "geologic_context_version", "geologic_match_method",
    "distance_to_geologic_boundary_m", "geologic_match_confidence", "geologic_context_status",
    "analytical_method", "analytical_method_status", "method_family",
    "digestion_or_extraction", "laboratory", "reference_material", "detection_limit", "detection_limit_unit",
    "source_id", "dataset_title", "dataset_doi", "dataset_version", "source_file", "source_row",
    "source_locator", "file_sha256", "license", "source_tier",
}
RECOMMENDED_INPUT_COLUMNS = {
    "record_id", "source_record_id", "sample_id", "measurement_basis", "source_id", "source_locator",
    "dataset_title", "dataset_version", "source_file", "source_row", "latitude", "longitude", "source_crs",
    "coordinate_uncertainty_m", "coordinate_uncertainty_status", "analytical_method",
    "analytical_method_status", "method_family", "digestion_or_extraction", "license",
    "source_tier",
}

FLAG_SEVERITY = {
    "MISSING_VALUE": "error",
    "INVALID_NUMERIC_VALUE": "error",
    "INVALID_MISSING_REASON": "error",
    "INVALID_DETECTION_LIMIT": "error",
    "NEGATIVE_CONCENTRATION": "error",
    "UNSUPPORTED_UNIT": "error",
    "UNSUPPORTED_SPECIES_CONVERSION": "error",
    "OXIDE_ELEMENT_MISMATCH": "error",
    "AMBIGUOUS_AQUEOUS_RATIO_UNIT": "error",
    "INVALID_COORDINATE": "error",
    "UNSUPPORTED_SOURCE_CRS": "error",
    "DEPTH_RANGE_INVALID": "error",
    "INVALID_GEOLOGIC_DISTANCE": "error",
    "CENSORED_VALUE": "info",
    "INFERRED_ELEMENT_FROM_OXIDE": "info",
    "GENERATED_RECORD_ID": "info",
    "DUPLICATE_CANDIDATE": "warning",
    "NONDETECT_WITHOUT_LIMIT": "warning",
    "UNQUANTIFIED_TRACE": "warning",
    "MISSING_MEASUREMENT_BASIS": "warning",
    "MISSING_ANALYTICAL_METHOD": "warning",
    "MISSING_DIGESTION_OR_EXTRACTION": "warning",
    "UNRECOGNIZED_ANALYTE": "warning",
    "UNRECOGNIZED_MEDIUM": "warning",
    "POSSIBLE_COORDINATE_SWAP": "warning",
    "INCOMPLETE_COORDINATE": "warning",
    "COORDINATE_NOT_CANONICALIZED": "warning",
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
    "INVALID_FILE_SHA256": "warning",
    "INVALID_GEOLOGIC_MATCH_CONFIDENCE": "warning",
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

# Fixed conventional atomic weights for a deliberately small, auditable oxide whitelist.
ATOMIC_WEIGHTS = {
    "O": 15.999,
    "Na": 22.98976928,
    "Mg": 24.305,
    "Al": 26.9815385,
    "Si": 28.085,
    "P": 30.973761998,
    "K": 39.0983,
    "Ca": 40.078,
    "Ti": 47.867,
    "Cr": 51.9961,
    "Mn": 54.938044,
    "Fe": 55.845,
    "Co": 58.933194,
    "Ni": 58.6934,
    "Cu": 63.546,
    "Zn": 65.38,
    "As": 74.921595,
    "Cd": 112.414,
    "Hg": 200.592,
    "Pb": 207.2,
}
OXIDE_RULES: dict[str, tuple[str, str, dict[str, int]]] = {
    "SIO2": ("SiO2", "Si", {"Si": 1, "O": 2}),
    "TIO2": ("TiO2", "Ti", {"Ti": 1, "O": 2}),
    "AL2O3": ("Al2O3", "Al", {"Al": 2, "O": 3}),
    "FEO": ("FeO", "Fe", {"Fe": 1, "O": 1}),
    "FE2O3": ("Fe2O3", "Fe", {"Fe": 2, "O": 3}),
    "MNO": ("MnO", "Mn", {"Mn": 1, "O": 1}),
    "MGO": ("MgO", "Mg", {"Mg": 1, "O": 1}),
    "CAO": ("CaO", "Ca", {"Ca": 1, "O": 1}),
    "NA2O": ("Na2O", "Na", {"Na": 2, "O": 1}),
    "K2O": ("K2O", "K", {"K": 2, "O": 1}),
    "P2O5": ("P2O5", "P", {"P": 2, "O": 5}),
    "CR2O3": ("Cr2O3", "Cr", {"Cr": 2, "O": 3}),
    "COO": ("CoO", "Co", {"Co": 1, "O": 1}),
    "NIO": ("NiO", "Ni", {"Ni": 1, "O": 1}),
    "CUO": ("CuO", "Cu", {"Cu": 1, "O": 1}),
    "ZNO": ("ZnO", "Zn", {"Zn": 1, "O": 1}),
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
WATER_MOLAR_MULTIPLIERS = {
    "nmol/l": 0.001,
    "umol/l": 1.0,
    "mmol/l": 1_000.0,
    "mol/l": 1_000_000.0,
}
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
    "trace": "trace", "tr": "trace",
}
CENSORED_QUALIFIERS = {"lt", "le", "gt", "ge", "bdl", "nd", "trace"}
MISSING_REASON_ALIASES = {
    "not_reported": "not_reported", "not reported": "not_reported", "nr": "not_reported",
    "not_analyzed": "not_analyzed", "not analysed": "not_analyzed", "not analyzed": "not_analyzed",
    "na": "not_analyzed", "n/a": "not_analyzed",
    "insufficient_sample": "insufficient_sample", "insufficient sample": "insufficient_sample", "ins": "insufficient_sample",
    "invalid_value": "invalid_value", "invalid value": "invalid_value",
    "unknown": "unknown",
}
METHOD_FAMILY_PATTERNS = (
    ("icp_ms", ("icp-ms", "icp ms", "icpms")),
    ("icp_oes", ("icp-oes", "icp oes", "icp-aes", "icp aes")),
    ("xrf", ("xrf", "x-ray fluorescence", "x ray fluorescence")),
    ("aas", ("aas", "atomic absorption")),
    ("inaa", ("inaa", "neutron activation")),
    ("idms", ("idms", "isotope dilution")),
    ("ion_chromatography", ("ion chromatography",)),
)
WGS84_CRS_ALIASES = {"epsg:4326", "4326", "wgs84", "wgs 84", "ogc:crs84", "crs84"}
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
PREFIXED_NUMBER_RE = re.compile(r"^(<=|>=|<|>|≤|≥|~)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$")


class PipelineError(ValueError):
    """Raised for invalid pipeline input or configuration."""


def blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def extract_source_qualifier_raw(row: Mapping[str, Any]) -> str | None:
    explicit = blank_to_none(row.get("source_qualifier_raw")) or blank_to_none(row.get("value_qualifier"))
    if explicit is not None:
        return explicit
    raw = blank_to_none(row.get("value"))
    if raw is None:
        return None
    compact = raw.replace(",", "")
    prefixed = PREFIXED_NUMBER_RE.fullmatch(compact)
    if prefixed is not None and prefixed.group(1):
        return prefixed.group(1)
    if compact.casefold() in QUALIFIER_ALIASES:
        return raw
    return None


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


def canonical_species_key(value: Any) -> str | None:
    text = blank_to_none(value)
    if text is None:
        return None
    translated = text.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789"))
    return re.sub(r"[^A-Za-z0-9]", "", translated).upper() or None


def resolve_analyte(row: Mapping[str, Any], flags: list[str]) -> tuple[str, bool, str | None, str | None]:
    reported = blank_to_none(row.get("analyte_reported")) or blank_to_none(row.get("element_or_analyte"))
    explicit_species = blank_to_none(row.get("species_or_oxide"))
    species_key = canonical_species_key(explicit_species)
    reported_key = canonical_species_key(reported)

    if explicit_species is None and reported_key in OXIDE_RULES:
        formula, element, _ = OXIDE_RULES[reported_key]
        add_flag(flags, "INFERRED_ELEMENT_FROM_OXIDE")
        return element, True, reported, formula

    # Preserve compound-like reported analytes as species evidence so unsupported
    # forms such as total-iron encodings fail closed instead of looking elemental.
    if (
        explicit_species is None
        and reported_key is not None
        and "O" in reported_key
        and any(character.isdigit() for character in reported_key)
    ):
        analyte, recognized = normalize_analyte(row.get("element_or_analyte"))
        return analyte, recognized, reported, reported

    analyte, recognized = normalize_analyte(row.get("element_or_analyte"))
    if species_key in OXIDE_RULES:
        formula, oxide_element, _ = OXIDE_RULES[species_key]
        if not recognized and reported_key == species_key:
            analyte, recognized = oxide_element, True
            add_flag(flags, "INFERRED_ELEMENT_FROM_OXIDE")
        return analyte, recognized, reported, formula
    return analyte, recognized, reported, explicit_species


def species_conversion_factor(
    species_or_oxide: str | None, analyte: str, flags: list[str]
) -> tuple[float | None, str | None]:
    species_key = canonical_species_key(species_or_oxide)
    if species_key is None or (species_key == analyte.upper() and analyte in ELEMENT_SYMBOLS):
        return 1.0, None
    rule = OXIDE_RULES.get(species_key)
    if rule is None:
        add_flag(flags, "UNSUPPORTED_SPECIES_CONVERSION")
        return None, None
    formula, expected_element, composition = rule
    if analyte != expected_element:
        add_flag(flags, "OXIDE_ELEMENT_MISMATCH")
        return None, None
    molecular_mass = sum(ATOMIC_WEIGHTS[element] * count for element, count in composition.items())
    element_mass = ATOMIC_WEIGHTS[expected_element] * composition[expected_element]
    fraction = element_mass / molecular_mass
    formula_text = (
        f"{formula}_to_{expected_element}; fraction={fraction:.12g}; atomic_weights={ATOMIC_WEIGHT_VERSION}"
    )
    return fraction, formula_text


def normalize_medium(value: Any) -> tuple[str, bool]:
    text = blank_to_none(value)
    if text is None:
        return "unknown", False
    canonical = MEDIUM_ALIASES.get(text.casefold())
    return (canonical, True) if canonical else ("unknown", False)


def normalize_method_family(value: Any, analytical_method: str | None) -> str | None:
    explicit = blank_to_none(value)
    if explicit is not None:
        return re.sub(r"[^a-z0-9]+", "_", explicit.casefold()).strip("_") or None
    if analytical_method is None:
        return None
    method_text = analytical_method.casefold()
    for family, patterns in METHOD_FAMILY_PATTERNS:
        if any(pattern in method_text for pattern in patterns):
            return family
    slug = re.sub(r"[^a-z0-9]+", "_", method_text).strip("_")
    return f"other_{slug}" if slug else None


def normalize_missing_reason(value: Any, flags: list[str]) -> str | None:
    text = blank_to_none(value)
    if text is None:
        return None
    reason = MISSING_REASON_ALIASES.get(text.casefold())
    if reason is None:
        add_flag(flags, "INVALID_MISSING_REASON")
        return "unknown"
    return reason


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
        "wtpercent": "wt%", "wt.%": "wt%",
        "mgkg": "mg/kg", "ugkg": "ug/kg", "gkg": "g/kg",
        "ugg": "ug/g", "ngg": "ng/g", "mgg": "mg/g", "gt": "g/t",
        "ugl": "ug/l", "mgl": "mg/l", "ngl": "ng/l", "gl": "g/l",
    }
    return aliases.get(unit, unit)


def parse_measurement(
    row: Mapping[str, Any], flags: list[str]
) -> tuple[float | None, str, float | None, float | None, str | None]:
    raw = blank_to_none(row.get("value"))
    source_qualifier_raw = extract_source_qualifier_raw(row)
    explicit_qualifier = blank_to_none(row.get("value_qualifier")) or source_qualifier_raw
    missing_reason = normalize_missing_reason(row.get("missing_reason"), flags)
    qualifier: str | None = None
    number: float | None = None

    if raw is not None:
        compact = raw.strip().replace(",", "")
        raw_missing_reason = MISSING_REASON_ALIASES.get(compact.casefold())
        match = PREFIXED_NUMBER_RE.fullmatch(compact)
        if raw_missing_reason is not None:
            missing_reason = missing_reason or raw_missing_reason
            qualifier = "unknown"
            flags.append("MISSING_VALUE")
        elif match:
            qualifier = QUALIFIER_ALIASES.get((match.group(1) or "").casefold(), "reported")
            number = float(match.group(2))
        else:
            qualifier = QUALIFIER_ALIASES.get(compact.casefold())
            if qualifier is None:
                flags.append("INVALID_NUMERIC_VALUE")
                qualifier = "unknown"
                missing_reason = missing_reason or "invalid_value"
    else:
        flags.append("MISSING_VALUE")
        missing_reason = missing_reason or "not_reported"

    if explicit_qualifier is not None:
        explicit = QUALIFIER_ALIASES.get(explicit_qualifier.casefold())
        if explicit is None:
            qualifier = "unknown"
        else:
            qualifier = explicit

    qualifier = qualifier or "unknown"
    if number is not None and missing_reason is not None:
        add_flag(flags, "INVALID_MISSING_REASON")
        missing_reason = None
    detection_limit_raw = blank_to_none(row.get("detection_limit"))
    detection_limit = parse_optional_float(detection_limit_raw)
    if detection_limit_raw is not None and (detection_limit is None or detection_limit < 0):
        detection_limit = None
        flags.append("INVALID_DETECTION_LIMIT")
    censoring_limit = number if qualifier in {"lt", "le", "gt", "ge"} else detection_limit

    if qualifier in CENSORED_QUALIFIERS:
        flags.append("CENSORED_VALUE")
        if qualifier == "trace":
            flags.append("UNQUANTIFIED_TRACE")
        elif censoring_limit is None:
            flags.append("NONDETECT_WITHOUT_LIMIT")
    if number is not None and number < 0:
        flags.append("NEGATIVE_CONCENTRATION")
    return number, qualifier, censoring_limit, detection_limit, missing_reason


def conversion_for(
    medium: str, original_unit: Any, analyte: str, flags: list[str]
) -> tuple[float | None, str | None]:
    unit = canonicalize_unit(original_unit)
    if medium in SOLID_MEDIA and unit in SOLID_FACTORS:
        return SOLID_FACTORS[unit], "mg/kg"
    if medium == "water" and unit in WATER_FACTORS:
        return WATER_FACTORS[unit], "ug/L"
    if medium == "water" and unit in WATER_MOLAR_MULTIPLIERS:
        atomic_weight = ATOMIC_WEIGHTS.get(analyte)
        if atomic_weight is None:
            flags.append("UNSUPPORTED_UNIT")
            return None, None
        return WATER_MOLAR_MULTIPLIERS[unit] * atomic_weight, "ug/L"
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
    canonical_lat_raw = blank_to_none(row.get("latitude"))
    canonical_lon_raw = blank_to_none(row.get("longitude"))
    original_lat_raw = blank_to_none(row.get("original_latitude_raw")) or canonical_lat_raw
    original_lon_raw = blank_to_none(row.get("original_longitude_raw")) or canonical_lon_raw
    lat = parse_optional_float(canonical_lat_raw)
    lon = parse_optional_float(canonical_lon_raw)

    if canonical_lat_raw is None and canonical_lon_raw is None:
        original_lat = parse_optional_float(original_lat_raw)
        original_lon = parse_optional_float(original_lon_raw)
        if (
            original_lat is not None
            and original_lon is not None
            and -90 <= original_lat <= 90
            and -180 <= original_lon <= 180
        ):
            add_flag(flags, "COORDINATE_NOT_CANONICALIZED")
        elif original_lat_raw is not None or original_lon_raw is not None:
            add_flag(flags, "INCOMPLETE_COORDINATE")
            add_flag(flags, "INVALID_COORDINATE")
        return original_lat_raw, original_lon_raw, None, None
    if canonical_lat_raw is None or canonical_lon_raw is None or lat is None or lon is None:
        add_flag(flags, "INCOMPLETE_COORDINATE")
        add_flag(flags, "INVALID_COORDINATE")
        return original_lat_raw, original_lon_raw, None, None

    valid = -90 <= lat <= 90 and -180 <= lon <= 180
    if not valid:
        add_flag(flags, "INVALID_COORDINATE")
        if -90 <= lon <= 90 and -180 <= lat <= 180:
            add_flag(flags, "POSSIBLE_COORDINATE_SWAP")
        return original_lat_raw, original_lon_raw, None, None

    if lat == 0 and lon == 0:
        add_flag(flags, "ZERO_ISLAND_COORDINATE")
    if region_bbox is not None:
        west, south, east, north = region_bbox
        longitude_inside = west <= lon <= east if west <= east else lon >= west or lon <= east
        if not (longitude_inside and south <= lat <= north):
            add_flag(flags, "OUTSIDE_REQUEST_REGION")
    return original_lat_raw, original_lon_raw, lat, lon


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
        "source_record_id": blank_to_none(row.get("source_record_id")),
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
    if record["source_file"] is not None and (
        record["file_sha256"] is None or "INVALID_FILE_SHA256" in flags
    ):
        source -= 0.05
    source = max(0.0, min(1.0, source))

    completeness_fields = (
        "sample_id", "element_or_analyte", "analyte_reported", "medium", "measurement_basis", "original_unit",
        "source_id", "source_locator", "dataset_title", "dataset_version", "source_file", "source_row",
        "analytical_method", "method_family", "digestion_or_extraction", "license",
    )
    present = sum(record[field] not in (None, "", "unknown") for field in completeness_fields)
    present += int(record["latitude"] is not None and record["longitude"] is not None)
    completeness = present / (len(completeness_fields) + 1)

    method = statistics.fmean(
        float(record[field] not in (None, ""))
        for field in ("measurement_basis", "analytical_method", "method_family", "digestion_or_extraction")
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
    analyte, analyte_recognized, analyte_reported, species_or_oxide = resolve_analyte(row, flags)
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
    method_family = normalize_method_family(row.get("method_family"), analytical_method)

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

    original_value, qualifier, censoring_limit, detection_limit, missing_reason = parse_measurement(row, flags)
    unit_factor, normalized_unit = conversion_for(medium, row.get("unit"), analyte, flags)
    species_factor, species_formula = species_conversion_factor(species_or_oxide, analyte, flags)
    factor = unit_factor * species_factor if unit_factor is not None and species_factor is not None else None
    conversion_formula = None
    if factor is not None:
        conversion_formula = f"normalized = original * {unit_factor:g}"
        if canonicalize_unit(row.get("unit")) in WATER_MOLAR_MULTIPLIERS:
            conversion_formula += f"; molar-to-mass using {analyte} atomic weight ({ATOMIC_WEIGHT_VERSION})"
        if species_formula is not None:
            conversion_formula += f" * {species_factor:.12g}; {species_formula}"
    normalized_value: float | None = None
    normalized_censoring_limit: float | None = None
    if factor is not None:
        if qualifier not in CENSORED_QUALIFIERS and original_value is not None and original_value >= 0:
            normalized_value = original_value * factor
        if qualifier in CENSORED_QUALIFIERS and censoring_limit is not None and censoring_limit >= 0:
            limit_unit = blank_to_none(row.get("detection_limit_unit"))
            if qualifier in {"bdl", "nd"} and limit_unit is not None:
                limit_flags: list[str] = []
                limit_factor, limit_target = conversion_for(medium, limit_unit, analyte, limit_flags)
                if limit_factor is not None and limit_target == normalized_unit and species_factor is not None:
                    normalized_censoring_limit = censoring_limit * limit_factor * species_factor
                else:
                    for flag in limit_flags:
                        add_flag(flags, flag)
            else:
                normalized_censoring_limit = censoring_limit * factor

    lat_raw, lon_raw, latitude, longitude = normalize_coordinates(row, flags, region_bbox)
    source_crs = blank_to_none(row.get("source_crs"))
    coordinate_transform_method = blank_to_none(row.get("coordinate_transform_method"))
    if source_crs is None:
        add_flag(flags, "MISSING_SOURCE_CRS")
        if latitude is not None or longitude is not None:
            add_flag(flags, "COORDINATE_NOT_CANONICALIZED")
            latitude = None
            longitude = None
    elif (
        (lat_raw is not None or lon_raw is not None)
        and not is_wgs84_crs(source_crs)
        and coordinate_transform_method is None
    ):
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
    boundary_distance = parse_optional_float(row.get("distance_to_geologic_boundary_m"))
    boundary_distance_raw = blank_to_none(row.get("distance_to_geologic_boundary_m"))
    if boundary_distance_raw is not None and (boundary_distance is None or boundary_distance < 0):
        boundary_distance = None
        add_flag(flags, "INVALID_GEOLOGIC_DISTANCE")
    geologic_match_confidence = blank_to_none(row.get("geologic_match_confidence"))
    if geologic_match_confidence is not None:
        geologic_match_confidence = geologic_match_confidence.casefold()
        if geologic_match_confidence not in {"high", "medium", "low", "unknown"}:
            geologic_match_confidence = "unknown"
            add_flag(flags, "INVALID_GEOLOGIC_MATCH_CONFIDENCE")
    file_sha256 = blank_to_none(row.get("file_sha256"))
    if file_sha256 is not None and not SHA256_RE.fullmatch(file_sha256):
        add_flag(flags, "INVALID_FILE_SHA256")
    elif file_sha256 is not None:
        file_sha256 = file_sha256.lower()
    original_unit = blank_to_none(row.get("unit"))
    source_qualifier_raw = extract_source_qualifier_raw(row)
    record: dict[str, Any] = {
        "record_id": record_id,
        "source_record_id": blank_to_none(row.get("source_record_id")),
        "sample_id": sample_id,
        "sample_identity_group": blank_to_none(row.get("sample_identity_group")),
        "replicate_group_id": blank_to_none(row.get("replicate_group_id")),
        "igsn": blank_to_none(row.get("igsn")),
        "element_or_analyte": analyte,
        "analyte_reported": analyte_reported,
        "species_or_oxide": species_or_oxide,
        "medium": medium,
        "material": blank_to_none(row.get("material")),
        "measurement_basis": measurement_basis,
        "original_value_raw": blank_to_none(row.get("value")),
        "source_qualifier_raw": source_qualifier_raw,
        "original_value": original_value,
        "original_unit": original_unit,
        "value_qualifier": qualifier,
        "censored": qualifier in CENSORED_QUALIFIERS,
        "missing_reason": missing_reason,
        "normalized_value": round(normalized_value, 12) if normalized_value is not None else None,
        "normalized_unit": normalized_unit,
        "normalized_censoring_limit": (
            round(normalized_censoring_limit, 12) if normalized_censoring_limit is not None else None
        ),
        "conversion_factor": factor,
        "conversion_formula": conversion_formula,
        "original_latitude_raw": lat_raw,
        "original_longitude_raw": lon_raw,
        "latitude": latitude,
        "longitude": longitude,
        "source_crs": source_crs,
        "coordinate_transform_method": coordinate_transform_method,
        "coordinate_uncertainty_m": coordinate_uncertainty,
        "coordinate_uncertainty_status": blank_to_none(row.get("coordinate_uncertainty_status")),
        "coordinate_uncertainty_basis": blank_to_none(row.get("coordinate_uncertainty_basis")),
        "coordinate_resolution_m": parse_optional_float(row.get("coordinate_resolution_m")),
        "coordinate_resolution_basis": blank_to_none(row.get("coordinate_resolution_basis")),
        "measurement_uncertainty": parse_optional_float(row.get("measurement_uncertainty")),
        "measurement_uncertainty_unit": blank_to_none(row.get("measurement_uncertainty_unit")),
        "measurement_uncertainty_basis": blank_to_none(row.get("measurement_uncertainty_basis")),
        "sampled_at": blank_to_none(row.get("sampled_at")),
        "sample_depth_min_m": depth_min,
        "sample_depth_max_m": depth_max,
        "grain_fraction": blank_to_none(row.get("grain_fraction")),
        "lithology": blank_to_none(row.get("lithology")),
        "geologic_unit": blank_to_none(row.get("geologic_unit")),
        "geologic_unit_id": blank_to_none(row.get("geologic_unit_id")),
        "geologic_context_source": blank_to_none(row.get("geologic_context_source")),
        "geologic_context_version": blank_to_none(row.get("geologic_context_version")),
        "geologic_match_method": blank_to_none(row.get("geologic_match_method")),
        "distance_to_geologic_boundary_m": boundary_distance,
        "geologic_match_confidence": geologic_match_confidence,
        "geologic_context_status": blank_to_none(row.get("geologic_context_status")),
        "spatial_geology_status": "not_run_no_grid",
        "spatial_geologic_unit": None,
        "spatial_geologic_unit_id": None,
        "spatial_geology_source": None,
        "spatial_geology_version": None,
        "spatial_geology_match_method": None,
        "spatial_geology_resolution_deg": None,
        "spatial_geology_applicability": None,
        "spatial_geology_reason": "No --geology-grid was supplied.",
        "analytical_method": analytical_method,
        "analytical_method_status": blank_to_none(row.get("analytical_method_status")),
        "method_family": method_family,
        "digestion_or_extraction": digestion,
        "laboratory": blank_to_none(row.get("laboratory")),
        "reference_material": blank_to_none(row.get("reference_material")),
        "detection_limit": detection_limit,
        "detection_limit_unit": blank_to_none(row.get("detection_limit_unit")),
        "source_id": source_id,
        "dataset_title": blank_to_none(row.get("dataset_title")),
        "dataset_doi": blank_to_none(row.get("dataset_doi")),
        "dataset_version": blank_to_none(row.get("dataset_version")),
        "source_file": blank_to_none(row.get("source_file")),
        "source_row": blank_to_none(row.get("source_row")),
        "source_locator": source_locator,
        "file_sha256": file_sha256,
        "license": license_value,
        "source_tier": source_tier,
        "qc_flags": flags,
    }
    record["operational_confidence"] = score_confidence(record)
    return record


def duplicate_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    sample_identity = record["sample_identity_group"] or record["sample_id"] or record["source_record_id"]
    return (
        record["source_id"], sample_identity, record["element_or_analyte"],
        record["species_or_oxide"], record["original_value_raw"], record["original_unit"],
        record["method_family"], record["analytical_method"], record["measurement_basis"],
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


class GlimGrid:
    """Reader for the official GLiM 0.5 degree Arc/ASCII distribution."""

    source = "https://doi.org/10.1594/PANGAEA.788537"
    version = "PANGAEA.788537; 0.5 degree dominant surface lithology raster"
    resolution = 0.5

    def __init__(self, archive_path: Path) -> None:
        if not archive_path.is_file():
            raise PipelineError(f"geology grid does not exist: {archive_path}")
        try:
            with zipfile.ZipFile(archive_path) as archive:
                class_lines = archive.read("Classnames.txt").decode("utf-8").splitlines()[1:]
                grid_lines = archive.read("glim_wgs84_0point5deg.txt.asc").decode("ascii").splitlines()
        except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
            raise PipelineError(f"invalid GLiM 0.5 degree archive: {archive_path}") from exc
        self.class_codes: dict[int, str] = {}
        for line in class_lines:
            parts = next(csv.reader([line], delimiter=";"))
            self.class_codes[int(parts[1])] = parts[3].strip('"')
        header = {line.split()[0].casefold(): float(line.split()[1]) for line in grid_lines[:6]}
        self.ncols = int(header["ncols"])
        self.nrows = int(header["nrows"])
        self.xllcorner = header["xllcorner"]
        self.yllcorner = header["yllcorner"]
        self.cellsize = header["cellsize"]
        self.nodata = int(header["nodata_value"])
        if (self.ncols, self.nrows, self.xllcorner, self.yllcorner, self.cellsize) != (
            720,
            360,
            -180.0,
            -90.0,
            0.5,
        ):
            raise PipelineError("unexpected GLiM grid geometry")
        self.values = [tuple(int(value) for value in line.split()) for line in grid_lines[6:]]
        if len(self.values) != self.nrows or any(len(row) != self.ncols for row in self.values):
            raise PipelineError("GLiM grid dimensions do not match its header")

    def lookup(self, latitude: float, longitude: float) -> tuple[int, str] | None:
        row = min(self.nrows - 1, max(0, math.floor((90.0 - latitude) / self.cellsize)))
        column = min(self.ncols - 1, max(0, math.floor((longitude + 180.0) / self.cellsize)))
        value = self.values[row][column]
        if value == self.nodata:
            return None
        code = self.class_codes.get(value)
        if code is None or code == "nd":
            return None
        return value, code


def apply_spatial_geology(records: Sequence[dict[str, Any]], grid: GlimGrid | None) -> None:
    for record in records:
        if grid is None:
            continue
        record.update(
            {
                "spatial_geology_source": grid.source,
                "spatial_geology_version": grid.version,
                "spatial_geology_match_method": GEOLOGY_JOIN_VERSION,
                "spatial_geology_resolution_deg": grid.resolution,
                "spatial_geology_applicability": "screening_dominant_surface_lithology_only",
            }
        )
        medium = str(record.get("medium") or "")
        material = str(record.get("material") or "").casefold()
        if medium == "water":
            record["spatial_geology_status"] = "not_applicable_water"
            record["spatial_geology_reason"] = "Land surface lithology is not assigned to water observations."
            continue
        if medium == "sediment" and "marine" in material:
            record["spatial_geology_status"] = "not_applicable_marine_sediment"
            record["spatial_geology_reason"] = "Land surface lithology is not assigned to marine sediment."
            continue
        latitude, longitude = record.get("latitude"), record.get("longitude")
        if latitude is None or longitude is None:
            record["spatial_geology_status"] = "invalid_or_missing_coordinate"
            record["spatial_geology_reason"] = "No valid canonical point was available for the spatial join."
            continue
        match = grid.lookup(float(latitude), float(longitude))
        if match is None:
            record["spatial_geology_status"] = "no_coverage"
            record["spatial_geology_reason"] = "The GLiM cell is NODATA or class nd."
            continue
        class_id, class_code = match
        record["spatial_geology_status"] = "matched"
        record["spatial_geologic_unit"] = class_code
        record["spatial_geologic_unit_id"] = f"GLiM:{class_id}"
        record["spatial_geology_reason"] = "Point contained by the deterministic 0.5 degree GLiM raster cell."


def build_geology_report(
    records: Sequence[Mapping[str, Any]], grid_path: Path | None, run_metadata: Mapping[str, Any]
) -> dict[str, Any]:
    statuses = Counter(str(record["spatial_geology_status"]) for record in records)
    excluded = {"not_applicable_water", "not_applicable_marine_sediment"}
    eligible = sum(str(record["spatial_geology_status"]) not in excluded for record in records)
    matched = statuses["matched"]
    water_with_unit = sum(
        record["medium"] == "water" and record.get("spatial_geologic_unit") is not None for record in records
    )
    return {
        "report_version": "d2-spatial-geology-report-v1",
        "join_version": GEOLOGY_JOIN_VERSION,
        "run_metadata": dict(run_metadata),
        "grid_supplied": grid_path is not None,
        "grid": None
        if grid_path is None
        else {
            "source": GlimGrid.source,
            "version": GlimGrid.version,
            "path": grid_path.name,
            "sha256": sha256_file(grid_path),
            "resolution_degrees": GlimGrid.resolution,
        },
        "status_counts": dict(sorted(statuses.items())),
        "disposition_coverage": round(sum(statuses.values()) / len(records), 6) if records else 1.0,
        "eligible_record_count": eligible,
        "matched_record_count": matched,
        "eligible_match_rate": round(matched / eligible, 6) if eligible else 0.0,
        "water_records_with_assigned_land_unit": water_with_unit,
        "scientific_limit": "GLiM dominant 0.5 degree surface lithology is screening context, not a site-scale formation or causal interpretation.",
    }


def group_identifier(group_by: Sequence[str], key: Sequence[Any]) -> str:
    payload = dict(zip(group_by, key, strict=True))
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:12]
    return f"grp-{digest}"


def detect_anomalies(
    records: Sequence[Mapping[str, Any]], group_by: Sequence[str] = DEFAULT_GROUP_BY,
    min_group_size: int = 8, robust_z_threshold: float = 3.5, min_quantified_fraction: float = 0.70,
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
        independent_total = len(group_records) - exclusions["duplicate_candidate"]
        quantified_fraction = len(usable) / independent_total if independent_total else 0.0
        censored_fraction = exclusions["censored"] / independent_total if independent_total else 0.0
        report: dict[str, Any] = {
            "group_id": group_id,
            "group": dict(zip(group_by, key, strict=True)),
            "records_total": len(group_records),
            "records_used": len(usable),
            "records_excluded": len(group_records) - len(usable),
            "exclusion_reasons": dict(sorted(exclusions.items())),
            "independent_record_count": independent_total,
            "quantified_fraction": round(quantified_fraction, 6),
            "censored_fraction": round(censored_fraction, 6),
            "status": "insufficient_group_size",
            "log10_median": None,
            "log10_mad": None,
            "candidate_count": 0,
        }
        if quantified_fraction < min_quantified_fraction:
            report["status"] = "insufficient_quantified_fraction"
            group_reports.append(report)
            continue
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
                        "measurement_basis": record["measurement_basis"],
                        "geologic_unit": record["geologic_unit"],
                        "spatial_geologic_unit": record["spatial_geologic_unit"],
                        "spatial_geology_status": record["spatial_geology_status"],
                        "method_family": record["method_family"],
                        "normalized_value": record["normalized_value"],
                        "normalized_unit": record["normalized_unit"],
                        "operational_confidence_band": record["operational_confidence"]["band"],
                        "source_id": record["source_id"],
                        "source_locator": record["source_locator"],
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
        "interface_version": INTERFACE_VERSION,
        "method_version": ANOMALY_VERSION,
        "features": features,
    }
    anomaly_report = {
        "interface_version": INTERFACE_VERSION,
        "method_version": ANOMALY_VERSION,
        "method": "log10 median/MAD modified robust z-score",
        "group_by": list(group_by),
        "minimum_group_size": min_group_size,
        "minimum_quantified_fraction": min_quantified_fraction,
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
    flagged = sum(bool(record["qc_flags"]) for record in records)
    error_flagged = sum(
        any(FLAG_SEVERITY.get(flag, "warning") == "error" for flag in record["qc_flags"])
        for record in records
    )
    missing_reasons = Counter(record["missing_reason"] for record in records if record["missing_reason"] is not None)
    return {
        "pipeline_version": PIPELINE_VERSION,
        "run_metadata": dict(run_metadata),
        "definitions": {
            "standardized_record": "normalized_value or normalized_censoring_limit is available",
            "coordinate_valid": "both canonical latitude and longitude are present and range-valid",
            "records_are_not_dropped": True,
        },
        "record_count": len(records),
        "record_counts": {
            "raw": len(records),
            "parsed": len(records),
            "standardized_or_censoring_limit": standardized,
            "flagged": flagged,
            "error_flagged": error_flagged,
            "rejected": 0,
        },
        "records_with_numeric_value_or_limit": numeric_or_limit,
        "standardized_record_count": standardized,
        "standardization_rate": round(standardized / len(records), 6) if records else 0.0,
        "censored_record_count": sum(bool(record["censored"]) for record in records),
        "missing_reason_counts": dict(sorted(missing_reasons.items())),
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
        "component_definitions": {
            "source": "Registry tier score minus explicit penalties for missing source ID, locator, license, or invalid file hash.",
            "completeness": "Fraction of required scientific, method, spatial, dataset, file and license fields present.",
            "method": "Fraction present among measurement basis, analytical method, method family and digestion/extraction.",
            "spatial": "Canonical coordinate availability plus declared CRS and coordinate uncertainty; original-only coordinates score zero.",
            "qc": "Deterministic deduction from error, warning and information QC flags.",
            "overall": "Weighted sum of source, completeness, method, spatial and QC, subject to declared gates.",
        },
        "source_scoring": {
            "tier_scores": dict(SOURCE_TIER_SCORES),
            "penalties": {
                "missing_source_id": 0.15,
                "missing_source_locator": 0.25,
                "missing_license": 0.10,
                "source_file_without_valid_sha256": 0.05,
            },
            "evidence_boundary": (
                "D2 scores declared fields and hash syntax. D1 separately validates record-ID equality and, when an "
                "acquisition manifest is supplied, binds the input and record-evidence hashes."
            ),
        },
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


def load_schema_map(path: Path | None) -> tuple[dict[str, str], str | None]:
    if path is None:
        return {}, None
    if not path.is_file():
        raise PipelineError(f"schema map does not exist: {path}")
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"schema map is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PipelineError("schema map must be a JSON object of canonical_field -> source_column")
    mapping: dict[str, str] = {}
    for canonical, source_column in value.items():
        if canonical not in INPUT_FIELDS:
            raise PipelineError(f"schema map contains unknown canonical field: {canonical}")
        if not isinstance(source_column, str) or not source_column.strip():
            raise PipelineError(f"schema map source column for {canonical} must be a non-empty string")
        mapping[canonical] = source_column.strip()
    return mapping, hashlib.sha256(raw).hexdigest()


def load_csv(path: Path, schema_map: Mapping[str, str] | None = None) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise PipelineError(f"input CSV does not exist: {path}")
    mapping = dict(schema_map or {})
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PipelineError("input CSV has no header")
        headers = [header.strip() for header in reader.fieldnames]
        if len(headers) != len(set(headers)):
            raise PipelineError("input CSV contains duplicate column names after trimming whitespace")
        missing_source_columns = sorted(set(mapping.values()) - set(headers))
        if missing_source_columns:
            raise PipelineError(f"schema map references missing source columns: {', '.join(missing_source_columns)}")
        available_canonical = set(headers) | set(mapping)
        missing = sorted(MINIMUM_INPUT_COLUMNS - available_canonical)
        if missing:
            raise PipelineError(f"input CSV missing minimum columns: {', '.join(missing)}")
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            trimmed_row = {header.strip(): value for header, value in raw_row.items() if header is not None}
            canonical_row = dict(trimmed_row)
            for canonical, source_column in mapping.items():
                canonical_row[canonical] = trimmed_row.get(source_column, "")
            rows.append(canonical_row)
    if not rows:
        raise PipelineError("input CSV has no data rows")
    return rows, sorted(RECOMMENDED_INPUT_COLUMNS - available_canonical)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEMA_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["censored"] = "true" if row["censored"] else "false"
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
    schema_map_path: Path | None = None, min_quantified_fraction: float = 0.70,
    geology_grid_path: Path | None = None,
) -> dict[str, Path]:
    unknown_group_fields = sorted(set(group_by) - GROUPABLE_FIELDS)
    if unknown_group_fields:
        raise PipelineError(f"unknown --group-by fields: {', '.join(unknown_group_fields)}")
    if min_group_size < 3:
        raise PipelineError("--min-group-size must be at least 3")
    if not math.isfinite(robust_z_threshold) or robust_z_threshold <= 0:
        raise PipelineError("--robust-z-threshold must be positive")
    if not math.isfinite(min_quantified_fraction) or not 0 <= min_quantified_fraction <= 1:
        raise PipelineError("--min-quantified-fraction must be between 0 and 1")

    input_bytes = input_path.read_bytes() if input_path.is_file() else b""
    schema_map, schema_map_hash = load_schema_map(schema_map_path)
    rows, missing_recommended_columns = load_csv(input_path, schema_map)
    records = process_rows(rows, region_bbox)
    geology_grid = GlimGrid(geology_grid_path) if geology_grid_path is not None else None
    apply_spatial_geology(records, geology_grid)
    config = {
        "group_by": list(group_by),
        "minimum_group_size": min_group_size,
        "robust_z_threshold": robust_z_threshold,
        "minimum_quantified_fraction": min_quantified_fraction,
        "region_bbox": list(region_bbox) if region_bbox else None,
        "schema_map": dict(sorted(schema_map.items())),
        "geology_grid_sha256": sha256_file(geology_grid_path) if geology_grid_path is not None else None,
        "geology_join_version": GEOLOGY_JOIN_VERSION if geology_grid_path is not None else None,
    }
    input_hash = hashlib.sha256(input_bytes).hexdigest()
    run_id = hashlib.sha256(
        (input_hash + json.dumps(config, sort_keys=True, separators=(",", ":"))).encode()
    ).hexdigest()[:16]
    run_metadata = {
        "run_id": run_id,
        "input_sha256": input_hash,
        "input_row_count": len(rows),
        "schema_map_sha256": schema_map_hash,
        "missing_recommended_input_columns": missing_recommended_columns,
        "configuration": config,
    }
    geojson, anomaly_report = detect_anomalies(
        records, group_by, min_group_size, robust_z_threshold, min_quantified_fraction
    )
    anomaly_report["run_metadata"] = run_metadata
    qc_report = build_qc_report(records, run_metadata)
    confidence_report = build_confidence_report(records, run_metadata)
    geology_report = build_geology_report(records, geology_grid_path, run_metadata)

    outputs = {
        "database": output_dir / "geochemistry.csv",
        "qc_report": output_dir / "qc_report.json",
        "confidence_report": output_dir / "confidence_report.json",
        "geology_report": output_dir / "geology_report.json",
        "anomalies": output_dir / "anomalies.geojson",
        "anomaly_report": output_dir / "anomaly_report.json",
    }
    write_csv(outputs["database"], records)
    atomic_write_text(outputs["qc_report"], json_text(qc_report))
    atomic_write_text(outputs["confidence_report"], json_text(confidence_report))
    atomic_write_text(outputs["geology_report"], json_text(geology_report))
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
        "--schema-map", type=Path,
        help="Optional JSON object mapping canonical D2 input fields to source CSV column names",
    )
    parser.add_argument(
        "--geology-grid",
        type=Path,
        help="Optional PANGAEA.788537 ZIP for versioned GLiM 0.5 degree point-in-cell matching",
    )
    parser.add_argument(
        "--group-by", default=",".join(DEFAULT_GROUP_BY),
        help="Comma-separated canonical background fields (default also separates method family and extraction)",
    )
    parser.add_argument("--min-group-size", type=int, default=8, help="Minimum positive uncensored records per group")
    parser.add_argument(
        "--min-quantified-fraction", type=float, default=0.70,
        help="Minimum usable noncensored fraction per independent background group (default: 0.70)",
    )
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
            input_path=args.input,
            output_dir=args.output_dir,
            group_by=group_by,
            min_group_size=args.min_group_size,
            robust_z_threshold=args.robust_z_threshold,
            region_bbox=args.region_bbox,
            schema_map_path=args.schema_map,
            min_quantified_fraction=args.min_quantified_fraction,
            geology_grid_path=args.geology_grid,
        )
    except (PipelineError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({name: str(path) for name, path in outputs.items()}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
