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

import evaluate_batch_qc as batch_qc

INTERFACE_VERSION = "d2-interface-v2"
PIPELINE_VERSION = "d2-pipeline-v2"
CONFIDENCE_VERSION = "d2-confidence-v3"
ANOMALY_VERSION = "d2-robust-mad-v2"
SPATIAL_ANOMALY_VERSION = "d2-spatial-hypergeometric-fdr-v1"
ATOMIC_WEIGHT_VERSION = "d2-atomic-weights-v1"
MOLAR_MASS_VERSION = "d2-ciaaw-abridged-2024-v1"
COORDINATE_POLICY_REGISTRY = (
    Path(__file__).resolve().parent.parent
    / "references"
    / "coordinate-policy-registry.json"
)
GEOLOGY_JOIN_VERSION = "d2-glim-05deg-cell-join-v1"
GLIM_SOURCE = "https://doi.org/10.1594/PANGAEA.788537"
GLIM_VERSION = (
    "PANGAEA.788537; 2012 publication; 0.5 degree dominant surface lithology raster"
)
GLIM_LICENSE = "CC-BY-3.0"
GLIM_RESOLUTION_DEG = 0.5
MAX_GEOLOGY_ARCHIVE_BYTES = 10_000_000
MAX_GEOLOGY_MEMBER_BYTES = 10_000_000

MINIMUM_INPUT_COLUMNS = {"element_or_analyte", "value", "unit", "medium"}
DEFAULT_GROUP_BY = (
    "element_or_analyte",
    "medium",
    "material",
    "sample_type",
    "soil_horizon",
    "sediment_environment",
    "water_fraction",
    "grain_fraction",
    "measurement_basis",
    "geologic_unit_raw",
    "matched_geologic_unit",
    "analytical_method",
    "method_family",
    "method_scope",
    "digestion_or_extraction",
)
GROUPABLE_FIELDS = {
    "element_or_analyte",
    "medium",
    "material",
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
    "method_family",
    "method_scope",
    "digestion_or_extraction",
    "source_id",
    "source_tier",
    "normalized_unit",
}

SCHEMA_COLUMNS = (
    "record_id",
    "source_record_id",
    "sample_id",
    "sample_identity_group",
    "replicate_group_id",
    "analysis_batch_id",
    "batch_qc_status",
    "batch_qc_disposition",
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
    "coordinate_evidence_scope",
    "coordinate_policy_id",
    "coordinate_policy_version",
    "coordinate_policy_url",
    "coordinate_policy_sha256",
    "coordinate_latitude_field",
    "coordinate_longitude_field",
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
    "geologic_unit_id",
    "geologic_context_source",
    "geologic_context_version",
    "geologic_match_method",
    "distance_to_geologic_boundary_m",
    "geologic_match_confidence",
    "method_family",
    "digestion_or_extraction",
    "laboratory",
    "reference_material",
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
    "dataset_title",
    "dataset_doi",
    "dataset_version",
    "source_file",
    "source_row",
    "source_locator",
    "file_sha256",
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

INPUT_FIELDS = {
    "record_id",
    "source_record_id",
    "sample_id",
    "sample_identity_group",
    "replicate_group_id",
    "analysis_batch_id",
    "igsn",
    "element_or_analyte",
    "analyte_reported",
    "species_or_oxide",
    "value",
    "unit",
    "value_qualifier",
    "source_qualifier_raw",
    "missing_reason",
    "medium",
    "material",
    "measurement_basis",
    "original_latitude_raw",
    "original_longitude_raw",
    "latitude",
    "longitude",
    "source_crs",
    "coordinate_transform_method",
    "coordinate_evidence_scope",
    "coordinate_policy_id",
    "coordinate_latitude_field",
    "coordinate_longitude_field",
    "coordinate_uncertainty_m",
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
    "analytical_method",
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
}
RECOMMENDED_INPUT_COLUMNS = {
    "record_id",
    "source_record_id",
    "sample_id",
    "measurement_basis",
    "source_id",
    "source_locator",
    "dataset_title",
    "dataset_version",
    "source_file",
    "source_row",
    "latitude",
    "longitude",
    "source_crs",
    "coordinate_uncertainty_m",
    "analytical_method",
    "method_family",
    "digestion_or_extraction",
    "license",
    "source_tier",
}

FLAG_SEVERITY = {
    "MISSING_VALUE": "error",
    "INVALID_NUMERIC_VALUE": "error",
    "INVALID_MISSING_REASON": "error",
    "INVALID_DETECTION_LIMIT": "error",
    "NEGATIVE_CONCENTRATION": "error",
    "UNSUPPORTED_UNIT": "error",
    "UNSUPPORTED_MOLAR_MASS": "error",
    "UNSUPPORTED_MOLAR_SPECIES": "error",
    "UNSUPPORTED_SPECIES_CONVERSION": "error",
    "OXIDE_ELEMENT_MISMATCH": "error",
    "AMBIGUOUS_AQUEOUS_RATIO_UNIT": "error",
    "INVALID_COORDINATE": "error",
    "UNSUPPORTED_SOURCE_CRS": "error",
    "INVALID_COORDINATE_POLICY": "error",
    "DEPTH_RANGE_INVALID": "error",
    "INVALID_GEOLOGIC_DISTANCE": "error",
    "INVALID_QUANTITATION_LIMIT": "error",
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
    "PLATFORM_CRS_POLICY_APPLIED": "info",
    "MISSING_COORDINATE_UNCERTAINTY": "warning",
    "INVALID_COORDINATE_UNCERTAINTY": "warning",
    "MISSING_SOURCE_ID": "warning",
    "MISSING_SOURCE_LOCATOR": "warning",
    "MISSING_LICENSE": "warning",
    "UNKNOWN_SOURCE_TIER": "warning",
    "MISSING_SAMPLE_ID": "warning",
    "MISSING_ANALYSIS_BATCH_ID": "warning",
    "BATCH_QC_NOT_EVALUATED": "warning",
    "BATCH_QC_FAILED": "error",
    "INVALID_FILE_SHA256": "warning",
    "INVALID_GEOLOGIC_MATCH_CONFIDENCE": "warning",
    "GEOLOGY_MATCH_NO_COVERAGE": "warning",
    "GEOLOGY_BOUNDARY_UNCERTAIN": "warning",
}

ELEMENT_SYMBOLS = {
    "H",
    "He",
    "Li",
    "Be",
    "B",
    "C",
    "N",
    "O",
    "F",
    "Ne",
    "Na",
    "Mg",
    "Al",
    "Si",
    "P",
    "S",
    "Cl",
    "Ar",
    "K",
    "Ca",
    "Sc",
    "Ti",
    "V",
    "Cr",
    "Mn",
    "Fe",
    "Co",
    "Ni",
    "Cu",
    "Zn",
    "Ga",
    "Ge",
    "As",
    "Se",
    "Br",
    "Kr",
    "Rb",
    "Sr",
    "Y",
    "Zr",
    "Nb",
    "Mo",
    "Tc",
    "Ru",
    "Rh",
    "Pd",
    "Ag",
    "Cd",
    "In",
    "Sn",
    "Sb",
    "Te",
    "I",
    "Xe",
    "Cs",
    "Ba",
    "La",
    "Ce",
    "Pr",
    "Nd",
    "Pm",
    "Sm",
    "Eu",
    "Gd",
    "Tb",
    "Dy",
    "Ho",
    "Er",
    "Tm",
    "Yb",
    "Lu",
    "Hf",
    "Ta",
    "W",
    "Re",
    "Os",
    "Ir",
    "Pt",
    "Au",
    "Hg",
    "Tl",
    "Pb",
    "Bi",
    "Po",
    "At",
    "Rn",
    "Fr",
    "Ra",
    "Ac",
    "Th",
    "Pa",
    "U",
    "Np",
    "Pu",
    "Am",
    "Cm",
    "Bk",
    "Cf",
    "Es",
    "Fm",
    "Md",
    "No",
    "Lr",
    "Rf",
    "Db",
    "Sg",
    "Bh",
    "Hs",
    "Mt",
    "Ds",
    "Rg",
    "Cn",
    "Nh",
    "Fl",
    "Mc",
    "Lv",
    "Ts",
    "Og",
}

ELEMENT_NAMES = {
    "aluminium": "Al",
    "aluminum": "Al",
    "antimony": "Sb",
    "arsenic": "As",
    "barium": "Ba",
    "beryllium": "Be",
    "bismuth": "Bi",
    "boron": "B",
    "cadmium": "Cd",
    "calcium": "Ca",
    "carbon": "C",
    "cerium": "Ce",
    "cesium": "Cs",
    "caesium": "Cs",
    "chromium": "Cr",
    "cobalt": "Co",
    "copper": "Cu",
    "dysprosium": "Dy",
    "erbium": "Er",
    "europium": "Eu",
    "fluorine": "F",
    "gadolinium": "Gd",
    "gallium": "Ga",
    "germanium": "Ge",
    "gold": "Au",
    "hafnium": "Hf",
    "holmium": "Ho",
    "indium": "In",
    "iodine": "I",
    "iron": "Fe",
    "lanthanum": "La",
    "lead": "Pb",
    "lithium": "Li",
    "lutetium": "Lu",
    "magnesium": "Mg",
    "manganese": "Mn",
    "mercury": "Hg",
    "molybdenum": "Mo",
    "neodymium": "Nd",
    "nickel": "Ni",
    "niobium": "Nb",
    "palladium": "Pd",
    "phosphorus": "P",
    "platinum": "Pt",
    "potassium": "K",
    "praseodymium": "Pr",
    "rhenium": "Re",
    "rubidium": "Rb",
    "samarium": "Sm",
    "scandium": "Sc",
    "selenium": "Se",
    "silicon": "Si",
    "silver": "Ag",
    "sodium": "Na",
    "strontium": "Sr",
    "sulfur": "S",
    "sulphur": "S",
    "tantalum": "Ta",
    "tellurium": "Te",
    "terbium": "Tb",
    "thallium": "Tl",
    "thorium": "Th",
    "thulium": "Tm",
    "tin": "Sn",
    "titanium": "Ti",
    "tungsten": "W",
    "uranium": "U",
    "vanadium": "V",
    "ytterbium": "Yb",
    "yttrium": "Y",
    "zinc": "Zn",
    "zirconium": "Zr",
    "砷": "As",
    "铅": "Pb",
    "镉": "Cd",
    "汞": "Hg",
    "铜": "Cu",
    "锌": "Zn",
    "铁": "Fe",
    "锰": "Mn",
    "铬": "Cr",
    "镍": "Ni",
    "钴": "Co",
    "金": "Au",
    "银": "Ag",
    "铀": "U",
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
    "rock": "rock",
    "rocks": "rock",
    "bedrock": "rock",
    "岩石": "rock",
    "soil": "soil",
    "soils": "soil",
    "topsoil": "soil",
    "subsoil": "soil",
    "土壤": "soil",
    "sediment": "sediment",
    "sediments": "sediment",
    "stream sediment": "sediment",
    "stream_sediment": "sediment",
    "河流沉积物": "sediment",
    "沉积物": "sediment",
    "water": "water",
    "groundwater": "water",
    "surface water": "water",
    "surface_water": "water",
    "seawater": "water",
    "porewater": "water",
    "river water": "water",
    "水": "water",
    "水体": "water",
    "mineral": "mineral",
    "minerals": "mineral",
    "矿物": "mineral",
    "concentrate": "concentrate",
    "heavy mineral concentrate": "concentrate",
    "精矿": "concentrate",
}

SOLID_MEDIA = {"rock", "soil", "sediment", "mineral", "concentrate"}
SOLID_FACTORS = {
    "mg/kg": 1.0,
    "ppm": 1.0,
    "ug/g": 1.0,
    "g/t": 1.0,
    "wt%": 10_000.0,
    "ppb": 0.001,
    "ug/kg": 0.001,
    "ng/g": 0.001,
    "g/kg": 1_000.0,
    "mg/g": 1_000.0,
}
WATER_FACTORS = {"ug/l": 1.0, "mg/l": 1_000.0, "ng/l": 0.001, "g/l": 1_000_000.0}
# Frozen conventional/abridged atomic weights used only for explicit elemental
# nmol/L -> ug/L conversion.  Do not use this table for compounds or nmol/kg.
AQUEOUS_MOLAR_MASSES = {
    "As": 74.921595,
    "Cu": 63.546,
    "Fe": 55.845,
    "Ni": 58.6934,
    "Pb": 207.2,
    "Zn": 65.38,
}
AQUEOUS_AMBIGUOUS_UNITS = {
    "ppm",
    "ppb",
    "wt%",
    "%",
    "percent",
    "mg/kg",
    "ug/kg",
    "g/kg",
    "ug/g",
    "ng/g",
    "mg/g",
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
    "official": "official_curated",
    "official curated": "official_curated",
    "official_curated": "official_curated",
    "government": "government",
    "gov": "government",
    "government agency": "government",
    "peer reviewed": "peer_reviewed",
    "peer-reviewed": "peer_reviewed",
    "peer_reviewed": "peer_reviewed",
    "journal": "peer_reviewed",
    "institutional repository": "institutional_repository",
    "institutional_repository": "institutional_repository",
    "author supplement": "author_supplement",
    "author_supplement": "author_supplement",
    "supplement": "author_supplement",
    "aggregator": "aggregator",
    "unknown": "unknown",
    "": "unknown",
}

QUALIFIER_ALIASES = {
    "": "reported",
    "=": "reported",
    "reported": "reported",
    "exact": "reported",
    "~": "approximate",
    "approx": "approximate",
    "approximate": "approximate",
    "<": "lt",
    "lt": "lt",
    "<=": "le",
    "≤": "le",
    "le": "le",
    ">": "gt",
    "gt": "gt",
    ">=": "ge",
    "≥": "ge",
    "ge": "ge",
    "bdl": "bdl",
    "below detection limit": "bdl",
    "l": "bdl",
    "lod": "bdl",
    "<lod": "bdl",
    "loq": "loq",
    "<loq": "loq",
    "bql": "loq",
    "below quantitation limit": "loq",
    "below quantification limit": "loq",
    "g": "gt",
    "nd": "nd",
    "n.d.": "nd",
    "not detected": "nd",
    "n": "nd",
    "trace": "trace",
    "tr": "trace",
}
CENSORED_QUALIFIERS = {"lt", "le", "gt", "ge", "bdl", "loq", "nd", "trace"}
MISSING_REASON_ALIASES = {
    "not_reported": "not_reported",
    "not reported": "not_reported",
    "nr": "not_reported",
    "not_analyzed": "not_analyzed",
    "not analysed": "not_analyzed",
    "not analyzed": "not_analyzed",
    "na": "not_analyzed",
    "n/a": "not_analyzed",
    "insufficient_sample": "insufficient_sample",
    "insufficient sample": "insufficient_sample",
    "ins": "insufficient_sample",
    "invalid_value": "invalid_value",
    "invalid value": "invalid_value",
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
PREFIXED_NUMBER_RE = re.compile(
    r"^(<=|>=|<|>|≤|≥|~)?\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$"
)


class PipelineError(ValueError):
    """Raised for invalid pipeline input or configuration."""


def blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def extract_source_qualifier_raw(row: Mapping[str, Any]) -> str | None:
    explicit = blank_to_none(row.get("source_qualifier_raw")) or blank_to_none(
        row.get("value_qualifier")
    )
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


def resolve_analyte(
    row: Mapping[str, Any], flags: list[str]
) -> tuple[str, bool, str | None, str | None]:
    reported = blank_to_none(row.get("analyte_reported")) or blank_to_none(
        row.get("element_or_analyte")
    )
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
    if species_key is None or (
        species_key == analyte.upper() and analyte in ELEMENT_SYMBOLS
    ):
        return 1.0, None
    rule = OXIDE_RULES.get(species_key)
    if rule is None:
        add_flag(flags, "UNSUPPORTED_SPECIES_CONVERSION")
        return None, None
    formula, expected_element, composition = rule
    if analyte != expected_element:
        add_flag(flags, "OXIDE_ELEMENT_MISMATCH")
        return None, None
    molecular_mass = sum(
        ATOMIC_WEIGHTS[element] * count for element, count in composition.items()
    )
    element_mass = ATOMIC_WEIGHTS[expected_element] * composition[expected_element]
    fraction = element_mass / molecular_mass
    formula_text = f"{formula}_to_{expected_element}; fraction={fraction:.12g}; atomic_weights={ATOMIC_WEIGHT_VERSION}"
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
    unit = (
        text.casefold()
        .replace("μ", "u")
        .replace("µ", "u")
        .replace("−", "-")
        .replace("·", "")
    )
    unit = (
        unit.replace("micrograms", "ug").replace("microgram", "ug").replace("mcg", "ug")
    )
    unit = unit.replace("milligrams", "mg").replace("milligram", "mg")
    unit = unit.replace("nanograms", "ng").replace("nanogram", "ng")
    unit = unit.replace("grams", "g").replace("gram", "g")
    unit = (
        unit.replace("kilograms", "kg")
        .replace("kilogram", "kg")
        .replace("litres", "l")
        .replace("liters", "l")
    )
    unit = unit.replace("litre", "l").replace("liter", "l").replace("tonne", "t")
    unit = (
        unit.replace("weightpercent", "wt%")
        .replace("weight%", "wt%")
        .replace("wt.%", "wt%")
    )
    unit = re.sub(r"\s+", "", unit)
    unit = unit.replace("per", "/")
    unit = re.sub(r"kg\^?-?1$", "/kg", unit)
    unit = re.sub(r"g\^?-?1$", "/g", unit)
    unit = re.sub(r"l\^?-?1$", "/l", unit)
    unit = unit.replace("//", "/")
    aliases = {
        "wtpercent": "wt%",
        "wt.%": "wt%",
        "mgkg": "mg/kg",
        "ugkg": "ug/kg",
        "gkg": "g/kg",
        "ugg": "ug/g",
        "ngg": "ng/g",
        "mgg": "mg/g",
        "gt": "g/t",
        "ugl": "ug/l",
        "mgl": "mg/l",
        "ngl": "ng/l",
        "gl": "g/l",
    }
    return aliases.get(unit, unit)


def parse_measurement(
    row: Mapping[str, Any], flags: list[str]
) -> tuple[float | None, str, float | None, float | None, float | None, str | None]:
    raw = blank_to_none(row.get("value"))
    source_qualifier_raw = extract_source_qualifier_raw(row)
    explicit_qualifier = (
        blank_to_none(row.get("value_qualifier")) or source_qualifier_raw
    )
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
            qualifier = QUALIFIER_ALIASES.get(
                (match.group(1) or "").casefold(), "reported"
            )
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
    if detection_limit_raw is not None and (
        detection_limit is None or detection_limit < 0
    ):
        detection_limit = None
        flags.append("INVALID_DETECTION_LIMIT")
    quantitation_limit_raw = blank_to_none(row.get("quantitation_limit"))
    quantitation_limit = parse_optional_float(quantitation_limit_raw)
    if quantitation_limit_raw is not None and (
        quantitation_limit is None or quantitation_limit < 0
    ):
        quantitation_limit = None
        flags.append("INVALID_QUANTITATION_LIMIT")
    if qualifier in {"lt", "le", "gt", "ge"} and number is not None:
        censoring_limit = number
    elif qualifier == "loq":
        censoring_limit = quantitation_limit
    else:
        censoring_limit = detection_limit

    if qualifier in CENSORED_QUALIFIERS:
        flags.append("CENSORED_VALUE")
        if qualifier == "trace":
            flags.append("UNQUANTIFIED_TRACE")
        elif censoring_limit is None:
            flags.append("NONDETECT_WITHOUT_LIMIT")
    if number is not None and number < 0:
        flags.append("NEGATIVE_CONCENTRATION")
    return (
        number,
        qualifier,
        censoring_limit,
        detection_limit,
        quantitation_limit,
        missing_reason,
    )


def conversion_for(
    medium: str,
    original_unit: Any,
    flags: list[str],
    analyte: str | None = None,
    species_or_oxide: str | None = None,
) -> tuple[float | None, str | None]:
    unit = canonicalize_unit(original_unit)
    if medium in SOLID_MEDIA and unit in SOLID_FACTORS:
        return SOLID_FACTORS[unit], "mg/kg"
    if medium == "water" and unit == "nmol/kg":
        return 1.0, "nmol/kg"
    if medium == "water" and unit == "nmol/l":
        if species_or_oxide not in (None, "", analyte):
            add_flag(flags, "UNSUPPORTED_MOLAR_SPECIES")
            return None, None
        molar_mass = AQUEOUS_MOLAR_MASSES.get(analyte or "")
        if molar_mass is None:
            add_flag(flags, "UNSUPPORTED_MOLAR_MASS")
            return None, None
        # nmol/L * g/mol * 1e-3 = ug/L.
        return molar_mass / 1_000.0, "ug/L"
    if medium == "water" and unit in WATER_FACTORS:
        return WATER_FACTORS[unit], "ug/L"
    if medium == "water" and unit in AQUEOUS_AMBIGUOUS_UNITS:
        flags.append("AMBIGUOUS_AQUEOUS_RATIO_UNIT")
        return None, None
    flags.append("UNSUPPORTED_UNIT")
    return None, None


def load_coordinate_policies() -> dict[str, dict[str, Any]]:
    try:
        registry = json.loads(COORDINATE_POLICY_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PipelineError(
            "coordinate policy registry is unavailable or invalid"
        ) from exc
    if registry.get("schema_version") != "geochemical-coordinate-policy-registry-v1":
        raise PipelineError(
            "coordinate policy registry has an unsupported schema version"
        )
    policies = registry.get("policies")
    if not isinstance(policies, list):
        raise PipelineError("coordinate policy registry policies must be an array")
    indexed: dict[str, dict[str, Any]] = {}
    for policy in policies:
        if not isinstance(policy, dict) or not isinstance(policy.get("policy_id"), str):
            raise PipelineError("coordinate policy registry contains an invalid policy")
        if policy["policy_id"] in indexed:
            raise PipelineError(
                "coordinate policy registry contains duplicate policy IDs"
            )
        indexed[policy["policy_id"]] = policy
    return indexed


def coordinate_evidence(
    row: Mapping[str, Any], flags: list[str]
) -> tuple[str | None, str | None, dict[str, str | None]]:
    """Resolve coordinate CRS from explicit row evidence or an allowlisted platform policy."""

    source_crs = blank_to_none(row.get("source_crs"))
    method = blank_to_none(row.get("coordinate_transform_method"))
    requested_scope = blank_to_none(row.get("coordinate_evidence_scope"))
    metadata: dict[str, str | None] = {
        "coordinate_evidence_scope": requested_scope
        or ("file_declared" if source_crs else None),
        "coordinate_policy_id": None,
        "coordinate_policy_version": None,
        "coordinate_policy_url": None,
        "coordinate_policy_sha256": None,
        "coordinate_latitude_field": blank_to_none(
            row.get("coordinate_latitude_field")
        ),
        "coordinate_longitude_field": blank_to_none(
            row.get("coordinate_longitude_field")
        ),
    }
    if source_crs is not None:
        if requested_scope == "platform_policy_declared":
            add_flag(flags, "INVALID_COORDINATE_POLICY")
        return source_crs, method, metadata
    if requested_scope != "platform_policy_declared":
        return None, method, metadata

    policy_id = blank_to_none(row.get("coordinate_policy_id"))
    policy = load_coordinate_policies().get(policy_id or "")
    doi = blank_to_none(row.get("dataset_doi")) or ""
    latitude_field = metadata["coordinate_latitude_field"] or ""
    longitude_field = metadata["coordinate_longitude_field"] or ""
    valid = bool(
        policy
        and re.fullmatch(
            str(policy.get("dataset_doi_pattern") or "(?!)"), doi, re.IGNORECASE
        )
        and latitude_field.casefold()
        in {str(value).casefold() for value in policy.get("latitude_fields", [])}
        and longitude_field.casefold()
        in {str(value).casefold() for value in policy.get("longitude_fields", [])}
        and policy.get("target_crs") == "EPSG:4326"
        and re.fullmatch(
            r"[0-9a-f]{64}", str(policy.get("authority_page_sha256") or "")
        )
    )
    if not valid:
        add_flag(flags, "INVALID_COORDINATE_POLICY")
        return None, method, metadata
    metadata.update(
        {
            "coordinate_policy_id": str(policy["policy_id"]),
            "coordinate_policy_version": str(policy["version"]),
            "coordinate_policy_url": str(policy["authority_url"]),
            "coordinate_policy_sha256": str(policy["authority_page_sha256"]),
        }
    )
    add_flag(flags, "PLATFORM_CRS_POLICY_APPLIED")
    return "EPSG:4326", f"identity:{policy['policy_id']}", metadata


def add_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def is_wgs84_crs(value: str) -> bool:
    return value.casefold().strip() in WGS84_CRS_ALIASES


def normalize_coordinates(
    row: Mapping[str, Any],
    flags: list[str],
    region_bbox: tuple[float, float, float, float] | None,
) -> tuple[str | None, str | None, float | None, float | None]:
    canonical_lat_raw = blank_to_none(row.get("latitude"))
    canonical_lon_raw = blank_to_none(row.get("longitude"))
    original_lat_raw = (
        blank_to_none(row.get("original_latitude_raw")) or canonical_lat_raw
    )
    original_lon_raw = (
        blank_to_none(row.get("original_longitude_raw")) or canonical_lon_raw
    )
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
    if (
        canonical_lat_raw is None
        or canonical_lon_raw is None
        or lat is None
        or lon is None
    ):
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
        longitude_inside = (
            west <= lon <= east if west <= east else lon >= west or lon <= east
        )
        if not (longitude_inside and south <= lat <= north):
            add_flag(flags, "OUTSIDE_REQUEST_REGION")
    return original_lat_raw, original_lon_raw, lat, lon


def normalize_source_tier(value: Any, flags: list[str]) -> str:
    text = (blank_to_none(value) or "").casefold()
    tier = SOURCE_TIER_ALIASES.get(text, "unknown")
    if tier == "unknown":
        add_flag(flags, "UNKNOWN_SOURCE_TIER")
    return tier


def normalize_depth(
    row: Mapping[str, Any], flags: list[str]
) -> tuple[float | None, float | None]:
    depth_min = parse_optional_float(row.get("sample_depth_min_m"))
    depth_max = parse_optional_float(row.get("sample_depth_max_m"))
    invalid_raw = (
        blank_to_none(row.get("sample_depth_min_m")) is not None and depth_min is None
    ) or (
        blank_to_none(row.get("sample_depth_max_m")) is not None and depth_max is None
    )
    if (
        invalid_raw
        or (depth_min is not None and depth_min < 0)
        or (depth_max is not None and depth_max < 0)
    ):
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
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]
    return f"gen-{digest}"


def score_confidence(record: Mapping[str, Any]) -> dict[str, Any]:
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
        "sample_id",
        "element_or_analyte",
        "analyte_reported",
        "medium",
        "measurement_basis",
        "original_unit",
        "source_id",
        "source_locator",
        "dataset_title",
        "dataset_version",
        "source_file",
        "source_row",
        "analytical_method",
        "method_family",
        "digestion_or_extraction",
        "license",
    )
    present = sum(
        record[field] not in (None, "", "unknown") for field in completeness_fields
    )
    present += int(record["latitude"] is not None and record["longitude"] is not None)
    completeness = present / (len(completeness_fields) + 1)

    method = statistics.fmean(
        float(record[field] not in (None, ""))
        for field in (
            "measurement_basis",
            "analytical_method",
            "method_family",
            "digestion_or_extraction",
        )
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
    overall = (
        0.30 * source + 0.20 * completeness + 0.20 * method + 0.15 * spatial + 0.15 * qc
    )
    gates_applied: list[str] = []
    if severity_counts["error"]:
        overall = min(overall, 0.59)
        gates_applied.append("error_qc_low_cap")
    if record["latitude"] is None or record["longitude"] is None:
        overall = min(overall, 0.59)
        gates_applied.append("missing_canonical_coordinate_low_cap")
    elif record["coordinate_uncertainty_m"] is None:
        overall = min(overall, 0.79)
        gates_applied.append("missing_coordinate_uncertainty_medium_cap")
    if any(
        record[field] in (None, "")
        for field in (
            "measurement_basis",
            "analytical_method",
            "method_family",
            "digestion_or_extraction",
        )
    ):
        overall = min(overall, 0.79)
        gates_applied.append("incomplete_method_context_medium_cap")
    geologic_context_present = any(
        record.get(field) not in (None, "")
        for field in (
            "matched_geologic_unit",
            "geologic_unit_raw",
            "geologic_unit",
            "lithology_raw",
            "lithology",
        )
    )
    geology_required = record.get("medium") in {"rock", "soil"} or (
        record.get("medium") == "sediment"
        and record.get("sediment_environment") != "marine"
    )
    if geology_required and not geologic_context_present:
        overall = min(overall, 0.79)
        gates_applied.append("missing_geologic_context_medium_cap")
    if str(record.get("source_id") or "").casefold().startswith("synthetic"):
        overall = min(overall, 0.59)
        gates_applied.append("synthetic_fixture_low_cap")
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
        "gates_applied": sorted(gates_applied),
    }


def normalize_row(
    row: Mapping[str, Any],
    row_number: int,
    region_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    flags: list[str] = []
    analyte, analyte_recognized, analyte_reported, species_or_oxide = resolve_analyte(
        row, flags
    )
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

    (
        original_value,
        qualifier,
        censoring_limit,
        detection_limit,
        quantitation_limit,
        missing_reason,
    ) = parse_measurement(row, flags)
    unit_factor, normalized_unit = conversion_for(
        medium, row.get("unit"), flags, analyte, species_or_oxide
    )
    species_factor, species_formula = species_conversion_factor(
        species_or_oxide, analyte, flags
    )
    factor = (
        unit_factor * species_factor
        if unit_factor is not None and species_factor is not None
        else None
    )
    conversion_formula = None
    if factor is not None:
        conversion_formula = f"normalized = original * {unit_factor:g}"
        if canonicalize_unit(row.get("unit")) == "nmol/l":
            conversion_formula += (
                f"; nmol/L * atomic_weight({analyte})/1000; "
                f"atomic_weight={AQUEOUS_MOLAR_MASSES[analyte]:.12g}; {MOLAR_MASS_VERSION}"
            )
        if species_formula is not None:
            conversion_formula += f" * {species_factor:.12g}; {species_formula}"
    normalized_value: float | None = None
    normalized_censoring_limit: float | None = None
    if factor is not None:
        if (
            qualifier not in CENSORED_QUALIFIERS
            and original_value is not None
            and original_value >= 0
        ):
            normalized_value = original_value * factor
        if (
            qualifier in CENSORED_QUALIFIERS
            and censoring_limit is not None
            and censoring_limit >= 0
        ):
            limit_unit = blank_to_none(row.get("detection_limit_unit"))
            if qualifier == "loq":
                limit_unit = blank_to_none(row.get("quantitation_limit_unit"))
            if qualifier in {"bdl", "loq", "nd"} and limit_unit is not None:
                limit_flags: list[str] = []
                limit_factor, limit_target = conversion_for(
                    medium, limit_unit, limit_flags, analyte, species_or_oxide
                )
                if (
                    limit_factor is not None
                    and limit_target == normalized_unit
                    and species_factor is not None
                ):
                    normalized_censoring_limit = (
                        censoring_limit * limit_factor * species_factor
                    )
                else:
                    for flag in limit_flags:
                        add_flag(flags, flag)
            else:
                normalized_censoring_limit = censoring_limit * factor

    lat_raw, lon_raw, latitude, longitude = normalize_coordinates(
        row, flags, region_bbox
    )
    source_crs, coordinate_transform_method, coordinate_metadata = coordinate_evidence(
        row, flags
    )
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
    if boundary_distance_raw is not None and (
        boundary_distance is None or boundary_distance < 0
    ):
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
        "analysis_batch_id": blank_to_none(row.get("analysis_batch_id")),
        "batch_qc_status": "not_supplied",
        "batch_qc_disposition": None,
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
        "normalized_value": round(normalized_value, 12)
        if normalized_value is not None
        else None,
        "normalized_unit": normalized_unit,
        "normalized_censoring_limit": (
            round(normalized_censoring_limit, 12)
            if normalized_censoring_limit is not None
            else None
        ),
        "conversion_factor": factor,
        "conversion_formula": conversion_formula,
        "original_latitude_raw": lat_raw,
        "original_longitude_raw": lon_raw,
        "latitude": latitude,
        "longitude": longitude,
        "source_crs": source_crs,
        "coordinate_transform_method": coordinate_transform_method,
        **coordinate_metadata,
        "coordinate_uncertainty_m": coordinate_uncertainty,
        "sampled_at": blank_to_none(row.get("sampled_at")),
        "sample_depth_min_m": depth_min,
        "sample_depth_max_m": depth_max,
        "grain_fraction": blank_to_none(row.get("grain_fraction")),
        "sample_type_raw": blank_to_none(row.get("sample_type_raw")),
        "sample_type": blank_to_none(row.get("sample_type")),
        "sample_type_mapping_status": blank_to_none(
            row.get("sample_type_mapping_status")
        ),
        "sample_type_missing_reason": blank_to_none(
            row.get("sample_type_missing_reason")
        ),
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
        "geologic_unit_id": blank_to_none(row.get("geologic_unit_id")),
        "geologic_context_source": blank_to_none(row.get("geologic_context_source")),
        "geologic_context_version": blank_to_none(row.get("geologic_context_version")),
        "geologic_match_method": blank_to_none(row.get("geologic_match_method")),
        "distance_to_geologic_boundary_m": boundary_distance,
        "geologic_match_confidence": geologic_match_confidence,
        "method_family": method_family,
        "digestion_or_extraction": digestion,
        "laboratory": blank_to_none(row.get("laboratory")),
        "reference_material": blank_to_none(row.get("reference_material")),
        "detection_limit": detection_limit,
        "detection_limit_unit": blank_to_none(row.get("detection_limit_unit")),
        "quantitation_limit": quantitation_limit,
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
        "citation_assignment_basis": blank_to_none(
            row.get("citation_assignment_basis")
        ),
        "upstream_primary_source_id": blank_to_none(
            row.get("upstream_primary_source_id")
        ),
        "citation_resolution_status": blank_to_none(
            row.get("citation_resolution_status")
        ),
        "citation_missing_reason": blank_to_none(row.get("citation_missing_reason")),
        "source_id": source_id,
        "dataset_title": blank_to_none(row.get("dataset_title")),
        "dataset_doi": blank_to_none(row.get("dataset_doi")),
        "dataset_version": blank_to_none(row.get("dataset_version")),
        "source_file": blank_to_none(row.get("source_file")),
        "source_row": blank_to_none(row.get("source_row")),
        "source_locator": source_locator,
        "file_sha256": file_sha256,
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
    sample_identity = record["sample_identity_group"] or record["sample_id"]
    if sample_identity is None:
        # A source row identifier identifies provenance, not necessarily a distinct
        # physical sample. Fall back to conservative sample context so separate
        # source rows cannot mask otherwise identical measurement candidates.
        sample_identity = (
            record["original_latitude_raw"],
            record["original_longitude_raw"],
            record["sampled_at"],
            record["sample_depth_min_m"],
            record["sample_depth_max_m"],
            record["material"],
            record["sample_type"],
            record["soil_horizon"],
            record["sediment_environment"],
            record["water_fraction"],
            record["grain_fraction"],
        )
    return (
        record["source_id"],
        sample_identity,
        record["replicate_group_id"],
        record["element_or_analyte"],
        record["species_or_oxide"],
        record["original_value_raw"],
        record["original_unit"],
        record["method_family"],
        record["analytical_method"],
        record["measurement_basis"],
        record["original_latitude_raw"],
        record["original_longitude_raw"],
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
    rows: Iterable[Mapping[str, Any]],
    region_bbox: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    records = [
        normalize_row(row, index, region_bbox)
        for index, row in enumerate(rows, start=2)
    ]
    mark_duplicate_candidates(records)
    return records


def apply_batch_acceptance(
    records: Sequence[dict[str, Any]], acceptance_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Attach a fail-closed batch decision to every analytical record.

    The laboratory controls are evaluated separately by ``evaluate_batch_qc``.
    Records from failed, incomplete, unknown, or undeclared batches are retained
    in the canonical database but cannot enter anomaly background groups.
    """

    decisions: dict[str, Mapping[str, Any]] = {}
    for item in acceptance_rows:
        batch_id = str(item.get("batch_id") or "").strip()
        if not batch_id or batch_id in decisions:
            raise PipelineError(
                "batch acceptance contains a missing or duplicate batch_id"
            )
        decisions[batch_id] = item
    status_counts: Counter[str] = Counter()
    for record in records:
        batch_id = record.get("analysis_batch_id")
        if batch_id in (None, ""):
            record["batch_qc_status"] = "incomplete"
            record["batch_qc_disposition"] = "exclude_batch_and_investigate"
            add_flag(record["qc_flags"], "MISSING_ANALYSIS_BATCH_ID")
            add_flag(record["qc_flags"], "BATCH_QC_NOT_EVALUATED")
        else:
            decision = decisions.get(str(batch_id))
            if decision is None:
                record["batch_qc_status"] = "incomplete"
                record["batch_qc_disposition"] = "exclude_batch_and_investigate"
                add_flag(record["qc_flags"], "BATCH_QC_NOT_EVALUATED")
            elif bool(decision.get("batch_pass")):
                record["batch_qc_status"] = "pass"
                record["batch_qc_disposition"] = "accept_for_scientific_analysis"
            else:
                record["batch_qc_status"] = "fail"
                record["batch_qc_disposition"] = "exclude_batch_and_investigate"
                add_flag(record["qc_flags"], "BATCH_QC_FAILED")
        status_counts[str(record["batch_qc_status"])] += 1
        record["operational_confidence"] = score_confidence(record)
    return {
        "gate_applied": True,
        "decision_count": len(decisions),
        "record_status_counts": dict(sorted(status_counts.items())),
        "accepted_batch_ids": sorted(
            batch_id
            for batch_id, item in decisions.items()
            if bool(item.get("batch_pass"))
        ),
        "excluded_batch_ids": sorted(
            batch_id
            for batch_id, item in decisions.items()
            if not bool(item.get("batch_pass"))
        ),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class GlimGrid:
    """Read the official GLiM 0.5 degree Arc/ASCII screening grid."""

    def __init__(self, archive_path: Path) -> None:
        if not archive_path.is_file():
            raise PipelineError(f"geology grid does not exist: {archive_path}")
        if archive_path.stat().st_size > MAX_GEOLOGY_ARCHIVE_BYTES:
            raise PipelineError(
                f"geology grid exceeds the {MAX_GEOLOGY_ARCHIVE_BYTES}-byte archive safety limit"
            )
        try:
            with zipfile.ZipFile(archive_path) as archive:
                required = {"Classnames.txt", "glim_wgs84_0point5deg.txt.asc"}
                names = [item.filename for item in archive.infolist()]
                if any(names.count(name) != 1 for name in required):
                    raise PipelineError(
                        "GLiM archive must contain each required member exactly once"
                    )
                for name in required:
                    info = archive.getinfo(name)
                    if info.file_size > MAX_GEOLOGY_MEMBER_BYTES:
                        raise PipelineError(
                            f"GLiM member exceeds the extraction safety limit: {name}"
                        )
                class_lines = (
                    archive.read("Classnames.txt").decode("utf-8").splitlines()[1:]
                )
                grid_lines = (
                    archive.read("glim_wgs84_0point5deg.txt.asc")
                    .decode("ascii")
                    .splitlines()
                )
        except PipelineError:
            raise
        except (OSError, zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
            raise PipelineError(
                f"invalid GLiM 0.5 degree archive: {archive_path}"
            ) from exc

        try:
            self.class_codes: dict[int, str] = {}
            for line in class_lines:
                if not line.strip():
                    continue
                parts = next(csv.reader([line], delimiter=";"))
                class_id = int(parts[1])
                class_code = parts[3].strip().strip('"')
                if class_id in self.class_codes or not class_code:
                    raise ValueError("duplicate or empty class")
                self.class_codes[class_id] = class_code
            header = {
                line.split()[0].casefold(): float(line.split()[1])
                for line in grid_lines[:6]
            }
            self.ncols = int(header["ncols"])
            self.nrows = int(header["nrows"])
            self.xllcorner = header["xllcorner"]
            self.yllcorner = header["yllcorner"]
            self.cellsize = header["cellsize"]
            self.nodata = int(header["nodata_value"])
            self.values = [
                tuple(int(value) for value in line.split()) for line in grid_lines[6:]
            ]
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise PipelineError("invalid GLiM class table or raster values") from exc

        if (self.ncols, self.nrows, self.xllcorner, self.yllcorner, self.cellsize) != (
            720,
            360,
            -180.0,
            -90.0,
            GLIM_RESOLUTION_DEG,
        ):
            raise PipelineError("unexpected GLiM grid geometry")
        if len(self.values) != self.nrows or any(
            len(row) != self.ncols for row in self.values
        ):
            raise PipelineError("GLiM grid dimensions do not match its header")
        allowed_values = set(self.class_codes) | {self.nodata}
        if any(value not in allowed_values for row in self.values for value in row):
            raise PipelineError("GLiM grid contains a class absent from Classnames.txt")

    def lookup(
        self, latitude: float, longitude: float
    ) -> tuple[int, str, float] | None:
        row = min(self.nrows - 1, max(0, math.floor((90.0 - latitude) / self.cellsize)))
        column = min(
            self.ncols - 1, max(0, math.floor((longitude + 180.0) / self.cellsize))
        )
        value = self.values[row][column]
        code = self.class_codes.get(value)
        if value == self.nodata or code is None or code == "nd":
            return None
        west = self.xllcorner + column * self.cellsize
        east = west + self.cellsize
        north = self.yllcorner + self.nrows * self.cellsize - row * self.cellsize
        south = north - self.cellsize
        metres_per_degree_latitude = 111_320.0
        metres_per_degree_longitude = metres_per_degree_latitude * max(
            0.0, math.cos(math.radians(latitude))
        )
        boundary_distance = min(
            abs(longitude - west) * metres_per_degree_longitude,
            abs(east - longitude) * metres_per_degree_longitude,
            abs(latitude - south) * metres_per_degree_latitude,
            abs(north - latitude) * metres_per_degree_latitude,
        )
        return value, code, max(0.0, boundary_distance)


def apply_spatial_geology(
    records: Sequence[dict[str, Any]],
    grid: GlimGrid,
    grid_path: Path,
    expected_sha256: str,
) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    for record in records:
        record.update(
            {
                "matched_geologic_unit": None,
                "geology_map_source": GLIM_SOURCE,
                "geology_map_version": GLIM_VERSION,
                "match_method": GEOLOGY_JOIN_VERSION,
                "match_scale": "0.5 degree dominant surface lithology raster",
                "boundary_distance_m": None,
                "match_uncertainty": None,
                "geology_missing_reason": None,
            }
        )
        medium = str(record.get("medium") or "")
        sediment_context = " ".join(
            str(record.get(field) or "")
            for field in ("material", "sediment_environment")
        ).casefold()
        if medium == "water":
            statuses["not_applicable_water"] += 1
            record["geology_missing_reason"] = "not_applicable_water"
        elif medium == "sediment" and "marine" in sediment_context:
            statuses["not_applicable_marine_sediment"] += 1
            record["geology_missing_reason"] = "not_applicable_marine_sediment"
        elif record.get("latitude") is None or record.get("longitude") is None:
            statuses["invalid_or_missing_coordinate"] += 1
            record["geology_missing_reason"] = "invalid_or_missing_canonical_coordinate"
        else:
            match = grid.lookup(float(record["latitude"]), float(record["longitude"]))
            if match is None:
                statuses["no_coverage"] += 1
                record["geology_missing_reason"] = "glim_nodata_or_unclassified"
                add_flag(record["qc_flags"], "GEOLOGY_MATCH_NO_COVERAGE")
            else:
                class_id, class_code, boundary_distance = match
                record["boundary_distance_m"] = round(boundary_distance, 3)
                coordinate_uncertainty = record.get("coordinate_uncertainty_m")
                if coordinate_uncertainty is None:
                    record["match_uncertainty"] = (
                        "coordinate_uncertainty_unknown; coarse_screening_grid"
                    )
                    statuses["matched_coordinate_uncertainty_unknown"] += 1
                elif boundary_distance <= float(coordinate_uncertainty):
                    record["match_uncertainty"] = (
                        "coordinate_uncertainty_crosses_cell_boundary"
                    )
                    statuses["matched_boundary_uncertain"] += 1
                    add_flag(record["qc_flags"], "GEOLOGY_BOUNDARY_UNCERTAIN")
                else:
                    record["match_uncertainty"] = (
                        "stable_within_coordinate_uncertainty; coarse_screening_grid"
                    )
                    statuses["matched"] += 1
                # Retain the official class integer in the provenance-bearing value without
                # overwriting source-reported geologic_unit or geologic_unit_raw.
                record["matched_geologic_unit"] = f"GLiM:{class_id}:{class_code}"
        record["operational_confidence"] = score_confidence(record)

    eligible = sum(
        count
        for status, count in statuses.items()
        if status not in {"not_applicable_water", "not_applicable_marine_sediment"}
    )
    matched = sum(
        count for status, count in statuses.items() if status.startswith("matched")
    )
    return {
        "join_version": GEOLOGY_JOIN_VERSION,
        "grid_supplied": True,
        "grid": {
            "filename": grid_path.name,
            "sha256": expected_sha256,
            "source": GLIM_SOURCE,
            "version": GLIM_VERSION,
            "license": GLIM_LICENSE,
            "resolution_degrees": GLIM_RESOLUTION_DEG,
        },
        "status_counts": dict(sorted(statuses.items())),
        "disposition_coverage": round(sum(statuses.values()) / len(records), 6)
        if records
        else 1.0,
        "eligible_record_count": eligible,
        "matched_record_count": matched,
        "eligible_match_rate": round(matched / eligible, 6) if eligible else 0.0,
        "water_records_with_assigned_land_unit": sum(
            record["medium"] == "water"
            and record.get("matched_geologic_unit") is not None
            for record in records
        ),
        "scientific_limit": (
            "GLiM dominant 0.5 degree surface lithology is screening context, not a site-scale "
            "formation, stratigraphic assignment, or causal interpretation."
        ),
    }


def group_identifier(group_by: Sequence[str], key: Sequence[Any]) -> str:
    payload = dict(zip(group_by, key, strict=True))
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:12]
    return f"grp-{digest}"


def detect_anomalies(
    records: Sequence[Mapping[str, Any]],
    group_by: Sequence[str] = DEFAULT_GROUP_BY,
    min_group_size: int = 8,
    robust_z_threshold: float = 3.5,
    min_quantified_fraction: float = 0.70,
    batch_qc_gate_applied: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[tuple(record.get(field) for field in group_by)].append(record)

    features: list[dict[str, Any]] = []
    group_reports: list[dict[str, Any]] = []
    for key in sorted(
        grouped,
        key=lambda item: tuple("" if value is None else str(value) for value in item),
    ):
        group_records = grouped[key]
        usable: list[Mapping[str, Any]] = []
        exclusions: Counter[str] = Counter()
        for record in group_records:
            value = record.get("normalized_value")
            batch_status = record.get("batch_qc_status")
            if batch_qc_gate_applied and batch_status == "fail":
                exclusions["batch_qc_failed"] += 1
            elif batch_qc_gate_applied and batch_status != "pass":
                exclusions["batch_qc_incomplete"] += 1
            elif "DUPLICATE_CANDIDATE" in record.get("qc_flags", []):
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
        independent_total = len(group_records) - sum(
            exclusions[reason]
            for reason in (
                "duplicate_candidate",
                "batch_qc_failed",
                "batch_qc_incomplete",
            )
        )
        quantified_fraction = (
            len(usable) / independent_total if independent_total else 0.0
        )
        censored_fraction = (
            exclusions["censored"] / independent_total if independent_total else 0.0
        )
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
        if independent_total < min_group_size:
            group_reports.append(report)
            continue
        if quantified_fraction < min_quantified_fraction:
            report["status"] = "insufficient_quantified_fraction"
            group_reports.append(report)
            continue
        if len(usable) < min_group_size:
            report["status"] = "insufficient_usable_group_size"
            group_reports.append(report)
            continue

        log_values = [
            math.log10(float(record["normalized_value"])) for record in usable
        ]
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
        for record, robust_z in sorted(
            candidates, key=lambda item: str(item[0]["record_id"])
        ):
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
                        "method_family": record["method_family"],
                        "geologic_unit_raw": record["geologic_unit_raw"],
                        "matched_geologic_unit": record["matched_geologic_unit"],
                        "normalized_value": record["normalized_value"],
                        "normalized_unit": record["normalized_unit"],
                        "operational_confidence_band": record["operational_confidence"][
                            "band"
                        ],
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
        "gate_evaluation_order": [
            "independent_record_count",
            "quantified_fraction",
            "usable_record_count",
            "nonzero_dispersion",
        ],
        "batch_qc_gate_applied": batch_qc_gate_applied,
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


def log_combination(total: int, selected: int) -> float:
    if selected < 0 or selected > total:
        return float("-inf")
    return (
        math.lgamma(total + 1)
        - math.lgamma(selected + 1)
        - math.lgamma(total - selected + 1)
    )


def hypergeometric_survival(
    successes: int, population: int, population_successes: int, draws: int
) -> float:
    """Return the one-sided exact P[X >= successes] without SciPy.

    Conditioning on the observed group-wide candidate count avoids estimating a
    zero null probability when every candidate happens to fall in one cell.
    """

    if not 0 <= population_successes <= population or not 0 <= draws <= population:
        raise PipelineError("invalid hypergeometric test counts")
    minimum = max(0, draws - (population - population_successes))
    maximum = min(draws, population_successes)
    if successes <= minimum:
        return 1.0
    if successes > maximum:
        return 0.0
    denominator = log_combination(population, draws)

    def log_probability(value: int) -> float:
        return (
            log_combination(population_successes, value)
            + log_combination(population - population_successes, draws - value)
            - denominator
        )

    def log_sum(start: int, stop: int) -> float:
        value_range = range(start, stop)
        anchor = max(log_probability(value) for value in value_range)
        return anchor + math.log(
            math.fsum(
                math.exp(log_probability(value) - anchor) for value in value_range
            )
        )

    lower_term_count = successes - minimum
    upper_term_count = maximum - successes + 1
    if lower_term_count < upper_term_count:
        # P[X >= x] = 1 - P[X < x].  ``-expm1`` retains precision when
        # the shorter lower-tail sum is close to one.
        log_lower_probability = min(0.0, log_sum(minimum, successes))
        probability = -math.expm1(log_lower_probability)
    else:
        probability = math.exp(log_sum(successes, maximum + 1))
    return min(1.0, max(0.0, probability))


def benjamini_hochberg(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    order = sorted(range(len(values)), key=lambda index: (values[index], index))
    adjusted = [1.0] * len(values)
    running = 1.0
    count = len(values)
    for rank_index in range(count - 1, -1, -1):
        original_index = order[rank_index]
        rank = rank_index + 1
        running = min(running, values[original_index] * count / rank)
        adjusted[original_index] = min(1.0, running)
    return adjusted


def spatial_cell(
    longitude: float, latitude: float, grid_degrees: float
) -> tuple[int, int, float, float, float, float]:
    longitude_cells = int(round(360.0 / grid_degrees))
    latitude_cells = int(round(180.0 / grid_degrees))
    longitude_index = min(
        longitude_cells - 1, max(0, int(math.floor((longitude + 180) / grid_degrees)))
    )
    latitude_index = min(
        latitude_cells - 1, max(0, int(math.floor((latitude + 90) / grid_degrees)))
    )
    west = -180.0 + longitude_index * grid_degrees
    south = -90.0 + latitude_index * grid_degrees
    return (
        longitude_index,
        latitude_index,
        west,
        south,
        west + grid_degrees,
        south + grid_degrees,
    )


def detect_spatial_anomaly_regions(
    records: Sequence[Mapping[str, Any]],
    point_anomalies: Mapping[str, Any],
    anomaly_report: Mapping[str, Any],
    group_by: Sequence[str],
    *,
    grid_degrees: float = 2.0,
    minimum_spatial_samples: int = 5,
    minimum_spatial_candidates: int = 2,
    fdr_alpha: float = 0.10,
    batch_qc_gate_applied: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Screen fixed cells for over-represented high/low record-level candidates.

    The one-sided exact hypergeometric test conditions on the group-wide
    candidate count, then applies Benjamini-Hochberg correction over every
    eligible cell/direction hypothesis. The resulting polygons are screening
    cells, never inferred geologic, pollution, or mineralization boundaries.
    """

    longitude_cells = 360.0 / grid_degrees if grid_degrees > 0 else math.inf
    latitude_cells = 180.0 / grid_degrees if grid_degrees > 0 else math.inf
    if (
        not math.isfinite(grid_degrees)
        or not 0 < grid_degrees <= 30
        or not math.isclose(longitude_cells, round(longitude_cells), abs_tol=1e-9)
        or not math.isclose(latitude_cells, round(latitude_cells), abs_tol=1e-9)
    ):
        raise PipelineError(
            "--spatial-grid-degrees must divide both 180 and 360 and be in (0, 30]"
        )
    if minimum_spatial_samples < 3:
        raise PipelineError("--min-spatial-samples must be at least 3")
    if minimum_spatial_candidates < 1:
        raise PipelineError("--min-spatial-candidates must be at least 1")
    if not 0 < fdr_alpha <= 0.25:
        raise PipelineError("--spatial-fdr-alpha must be in (0, 0.25]")

    analyzed_groups = {
        str(item.get("group_id"))
        for item in anomaly_report.get("groups", [])
        if isinstance(item, Mapping) and item.get("status") == "analyzed"
    }
    candidate_direction = {
        str(feature.get("properties", {}).get("record_id")): str(
            feature.get("properties", {}).get("direction")
        )
        for feature in point_anomalies.get("features", [])
        if isinstance(feature, Mapping)
        and isinstance(feature.get("properties"), Mapping)
        and feature.get("properties", {}).get("direction") in {"high", "low"}
    }
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    group_payloads: dict[str, dict[str, Any]] = {}
    for record in records:
        key = tuple(record.get(field) for field in group_by)
        group_id = group_identifier(group_by, key)
        if group_id not in analyzed_groups:
            continue
        if batch_qc_gate_applied and record.get("batch_qc_status") != "pass":
            continue
        if "DUPLICATE_CANDIDATE" in record.get("qc_flags", []):
            continue
        value = record.get("normalized_value")
        if (
            record.get("value_qualifier") in CENSORED_QUALIFIERS
            or not isinstance(value, (int, float))
            or value <= 0
            or not isinstance(record.get("longitude"), (int, float))
            or not isinstance(record.get("latitude"), (int, float))
        ):
            continue
        grouped[group_id].append(record)
        group_payloads[group_id] = dict(zip(group_by, key, strict=True))

    hypotheses: list[dict[str, Any]] = []
    group_summaries: list[dict[str, Any]] = []
    for group_id in sorted(grouped):
        group_records = grouped[group_id]
        cells: dict[tuple[int, int], dict[str, Any]] = {}
        for record in group_records:
            cell = spatial_cell(
                float(record["longitude"]), float(record["latitude"]), grid_degrees
            )
            key = (cell[0], cell[1])
            bucket = cells.setdefault(
                key,
                {
                    "bounds": cell[2:],
                    "records": [],
                    "candidate_ids": {"high": [], "low": []},
                },
            )
            bucket["records"].append(record)
            direction = candidate_direction.get(str(record.get("record_id")))
            if direction in {"high", "low"}:
                bucket["candidate_ids"][direction].append(str(record["record_id"]))
        direction_counts = Counter(
            candidate_direction.get(str(item.get("record_id")))
            for item in group_records
        )
        eligible_cell_count = 0
        for direction in ("high", "low"):
            total_candidates = int(direction_counts.get(direction, 0))
            if total_candidates == 0:
                continue
            for cell_key in sorted(cells):
                cell = cells[cell_key]
                cell_total = len(cell["records"])
                outside_total = len(group_records) - cell_total
                if (
                    cell_total < minimum_spatial_samples
                    or outside_total < minimum_spatial_samples
                ):
                    continue
                eligible_cell_count += 1
                cell_candidates = len(cell["candidate_ids"][direction])
                outside_candidates = total_candidates - cell_candidates
                outside_rate = outside_candidates / outside_total
                p_value = hypergeometric_survival(
                    cell_candidates,
                    len(group_records),
                    total_candidates,
                    cell_total,
                )
                hypotheses.append(
                    {
                        "group_id": group_id,
                        "group": group_payloads[group_id],
                        "direction": direction,
                        "cell_key": cell_key,
                        "bounds": cell["bounds"],
                        "sample_count": cell_total,
                        "candidate_count": cell_candidates,
                        "candidate_record_ids": sorted(
                            cell["candidate_ids"][direction]
                        ),
                        "outside_sample_count": outside_total,
                        "outside_candidate_count": outside_candidates,
                        "outside_candidate_rate": outside_rate,
                        "p_value": p_value,
                    }
                )
        group_summaries.append(
            {
                "group_id": group_id,
                "mapped_usable_record_count": len(group_records),
                "mapped_cell_count": len(cells),
                "high_candidate_count": int(direction_counts.get("high", 0)),
                "low_candidate_count": int(direction_counts.get("low", 0)),
                "eligible_hypothesis_count": eligible_cell_count,
            }
        )

    adjusted = benjamini_hochberg([float(item["p_value"]) for item in hypotheses])
    features: list[dict[str, Any]] = []
    reported_tests: list[dict[str, Any]] = []
    for item, q_value in zip(hypotheses, adjusted, strict=True):
        item["fdr_q_value"] = q_value
        if item["candidate_count"]:
            reported_tests.append(
                {
                    key: item[key]
                    for key in (
                        "group_id",
                        "direction",
                        "cell_key",
                        "sample_count",
                        "candidate_count",
                        "outside_sample_count",
                        "outside_candidate_count",
                        "outside_candidate_rate",
                        "p_value",
                        "fdr_q_value",
                    )
                }
            )
        observed_rate = item["candidate_count"] / item["sample_count"]
        if (
            item["candidate_count"] < minimum_spatial_candidates
            or q_value > fdr_alpha
            or observed_rate <= item["outside_candidate_rate"]
        ):
            continue
        west, south, east, north = item["bounds"]
        region_payload = {
            "group_id": item["group_id"],
            "direction": item["direction"],
            "cell": [west, south, east, north],
        }
        region_id = (
            "region-"
            + hashlib.sha256(
                json.dumps(
                    region_payload, sort_keys=True, separators=(",", ":")
                ).encode()
            ).hexdigest()[:16]
        )
        outside_rate = item["outside_candidate_rate"]
        features.append(
            {
                "type": "Feature",
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
                    "region_id": region_id,
                    "status": "candidate_anomaly_region",
                    "scientific_status": "screening_candidate_only",
                    "direction": item["direction"],
                    "group_id": item["group_id"],
                    "group": item["group"],
                    "grid_degrees": grid_degrees,
                    "sample_count": item["sample_count"],
                    "candidate_count": item["candidate_count"],
                    "candidate_record_ids": item["candidate_record_ids"],
                    "observed_candidate_rate": round(observed_rate, 12),
                    "outside_candidate_rate": round(outside_rate, 12),
                    "enrichment_ratio": (
                        round(observed_rate / outside_rate, 12)
                        if outside_rate > 0
                        else None
                    ),
                    "p_value": round(float(item["p_value"]), 12),
                    "fdr_q_value": round(float(q_value), 12),
                    "method_version": SPATIAL_ANOMALY_VERSION,
                    "boundary_model": "fixed_wgs84_grid_cell_not_geologic_boundary",
                    "interpretation_limit": (
                        "Candidate co-location cell after FDR control; not an interpolated concentration surface, "
                        "site boundary, pollution claim, mineralization claim, or causal attribution."
                    ),
                },
            }
        )

    geojson = {
        "type": "FeatureCollection",
        "name": "geochemical_candidate_anomaly_regions",
        "interface_version": INTERFACE_VERSION,
        "method_version": SPATIAL_ANOMALY_VERSION,
        "features": features,
    }
    report = {
        "interface_version": INTERFACE_VERSION,
        "method_version": SPATIAL_ANOMALY_VERSION,
        "status": "screened" if hypotheses else "insufficient_spatial_background",
        "scientific_status": "screening_candidate_regions_only",
        "point_candidate_method_version": ANOMALY_VERSION,
        "grid_degrees": grid_degrees,
        "minimum_spatial_samples": minimum_spatial_samples,
        "minimum_spatial_candidates": minimum_spatial_candidates,
        "multiple_testing_method": "Benjamini-Hochberg FDR",
        "fdr_alpha": fdr_alpha,
        "null_model": (
            "one-sided exact hypergeometric enrichment conditional on the candidate count "
            "within the same D2 comparable background group"
        ),
        "hypothesis_count": len(hypotheses),
        "candidate_region_count": len(features),
        "groups": group_summaries,
        "nonzero_candidate_cell_tests": reported_tests,
        "caveat": (
            "Fixed cells with over-represented record-level candidates are screening regions only. "
            "Grid edges are not geological or administrative boundaries and blank areas are not absence."
        ),
    }
    return geojson, report


def build_qc_report(
    records: Sequence[Mapping[str, Any]], run_metadata: Mapping[str, Any]
) -> dict[str, Any]:
    flags = Counter(flag for record in records for flag in record["qc_flags"])
    severity = Counter(
        FLAG_SEVERITY.get(flag, "warning")
        for record in records
        for flag in record["qc_flags"]
    )
    numeric_or_limit = sum(
        record["original_value"] is not None
        or record["detection_limit"] is not None
        or record["quantitation_limit"] is not None
        for record in records
    )
    standardized = sum(
        record["normalized_value"] is not None
        or record["normalized_censoring_limit"] is not None
        for record in records
    )
    flagged = sum(bool(record["qc_flags"]) for record in records)
    error_flagged = sum(
        any(
            FLAG_SEVERITY.get(flag, "warning") == "error" for flag in record["qc_flags"]
        )
        for record in records
    )
    missing_reasons = Counter(
        record["missing_reason"]
        for record in records
        if record["missing_reason"] is not None
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
        "standardization_rate": round(standardized / len(records), 6)
        if records
        else 0.0,
        "censored_record_count": sum(bool(record["censored"]) for record in records),
        "missing_reason_counts": dict(sorted(missing_reasons.items())),
        "valid_coordinate_count": sum(
            record["latitude"] is not None and record["longitude"] is not None
            for record in records
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
            statistics.fmean(
                float(record["operational_confidence"][component]) for record in records
            ),
            6,
        )
        if records
        else 0.0
        for component in components
    }
    bands = Counter(str(record["operational_confidence"]["band"]) for record in records)
    gates = Counter(
        str(gate)
        for record in records
        for gate in record["operational_confidence"].get("gates_applied", [])
    )
    return {
        "confidence_version": CONFIDENCE_VERSION,
        "name": "operational_confidence",
        "not_a_probability": True,
        "meaning": "Record usability for this workflow; not truth probability, statistical confidence, or accuracy.",
        "run_metadata": dict(run_metadata),
        "weights": {
            "source": 0.30,
            "completeness": 0.20,
            "method": 0.20,
            "spatial": 0.15,
            "qc": 0.15,
        },
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
        "band_thresholds": {
            "high": ">=0.80",
            "medium": ">=0.60 and <0.80",
            "low": "<0.60",
        },
        "gates": {
            "error_qc_low_cap": "Any error-level QC flag caps overall at 0.59 (low).",
            "missing_canonical_coordinate_low_cap": "Missing canonical WGS84 coordinates cap overall at 0.59 (low).",
            "missing_coordinate_uncertainty_medium_cap": "Canonical coordinates without declared uncertainty cap overall at 0.79 (medium).",
            "incomplete_method_context_medium_cap": "Missing basis, method family, analytical method or digestion/extraction caps overall at 0.79 (medium).",
            "missing_geologic_context_medium_cap": "Rock, soil and non-marine sediment without source or matched geology cap overall at 0.79 (medium).",
            "synthetic_fixture_low_cap": "Synthetic validation records are capped at 0.59 (low) and cannot imply real-world scientific confidence.",
        },
        "gate_counts": dict(sorted(gates.items())),
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
        raise argparse.ArgumentTypeError(
            "bbox values are outside valid longitude/latitude ranges"
        )
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
        raise PipelineError(
            "schema map must be a JSON object of canonical_field -> source_column"
        )
    mapping: dict[str, str] = {}
    for canonical, source_column in value.items():
        if canonical not in INPUT_FIELDS:
            raise PipelineError(
                f"schema map contains unknown canonical field: {canonical}"
            )
        if not isinstance(source_column, str) or not source_column.strip():
            raise PipelineError(
                f"schema map source column for {canonical} must be a non-empty string"
            )
        mapping[canonical] = source_column.strip()
    return mapping, hashlib.sha256(raw).hexdigest()


def load_csv(
    path: Path, schema_map: Mapping[str, str] | None = None
) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise PipelineError(f"input CSV does not exist: {path}")
    mapping = dict(schema_map or {})
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise PipelineError("input CSV has no header")
        headers = [header.strip() for header in reader.fieldnames]
        if len(headers) != len(set(headers)):
            raise PipelineError(
                "input CSV contains duplicate column names after trimming whitespace"
            )
        missing_source_columns = sorted(set(mapping.values()) - set(headers))
        if missing_source_columns:
            raise PipelineError(
                f"schema map references missing source columns: {', '.join(missing_source_columns)}"
            )
        available_canonical = set(headers) | set(mapping)
        missing = sorted(MINIMUM_INPUT_COLUMNS - available_canonical)
        if missing:
            raise PipelineError(
                f"input CSV missing minimum columns: {', '.join(missing)}"
            )
        rows: list[dict[str, str]] = []
        for raw_row in reader:
            trimmed_row = {
                header.strip(): value
                for header, value in raw_row.items()
                if header is not None
            }
            canonical_row = dict(trimmed_row)
            for canonical, source_column in mapping.items():
                canonical_row[canonical] = trimmed_row.get(source_column, "")
            rows.append(canonical_row)
    if not rows:
        raise PipelineError("input CSV has no data rows")
    return rows, sorted(RECOMMENDED_INPUT_COLUMNS - available_canonical)


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def write_csv(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=SCHEMA_COLUMNS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["censored"] = "true" if row["censored"] else "false"
            row["qc_flags"] = json.dumps(
                row["qc_flags"], ensure_ascii=False, separators=(",", ":")
            )
            row["operational_confidence"] = json.dumps(
                row["operational_confidence"],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            writer.writerow(row)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def run_pipeline(
    input_path: Path,
    output_dir: Path,
    group_by: Sequence[str] = DEFAULT_GROUP_BY,
    min_group_size: int | None = None,
    robust_z_threshold: float = 3.5,
    region_bbox: tuple[float, float, float, float] | None = None,
    schema_map_path: Path | None = None,
    min_quantified_fraction: float = 0.70,
    analysis_profile: str = "demo",
    geology_grid_path: Path | None = None,
    geology_grid_sha256: str | None = None,
    batch_qc_input_path: Path | None = None,
    batch_qc_policy_path: Path | None = None,
    spatial_grid_degrees: float = 2.0,
    min_spatial_samples: int | None = None,
    min_spatial_candidates: int = 2,
    spatial_fdr_alpha: float = 0.10,
) -> dict[str, Path]:
    if analysis_profile not in {"demo", "production"}:
        raise PipelineError("--analysis-profile must be demo or production")
    if min_group_size is None:
        min_group_size = 20 if analysis_profile == "production" else 8
    if min_spatial_samples is None:
        min_spatial_samples = 20 if analysis_profile == "production" else 5
    unknown_group_fields = sorted(set(group_by) - GROUPABLE_FIELDS)
    if unknown_group_fields:
        raise PipelineError(
            f"unknown --group-by fields: {', '.join(unknown_group_fields)}"
        )
    if min_group_size < 3:
        raise PipelineError("--min-group-size must be at least 3")
    if analysis_profile == "production" and min_group_size < 20:
        raise PipelineError(
            "production analysis requires --min-group-size of at least 20"
        )
    if not math.isfinite(robust_z_threshold) or robust_z_threshold <= 0:
        raise PipelineError("--robust-z-threshold must be positive")
    if (
        not math.isfinite(min_quantified_fraction)
        or not 0 <= min_quantified_fraction <= 1
    ):
        raise PipelineError("--min-quantified-fraction must be between 0 and 1")
    if (batch_qc_input_path is None) != (batch_qc_policy_path is None):
        raise PipelineError(
            "--batch-qc-input and --batch-qc-policy must be supplied together"
        )

    if (geology_grid_path is None) != (geology_grid_sha256 is None):
        raise PipelineError(
            "--geology-grid and --geology-grid-sha256 must be supplied together"
        )
    normalized_grid_sha256 = (
        geology_grid_sha256.casefold() if geology_grid_sha256 is not None else None
    )
    if normalized_grid_sha256 is not None and not SHA256_RE.fullmatch(
        normalized_grid_sha256
    ):
        raise PipelineError(
            "--geology-grid-sha256 must contain exactly 64 hexadecimal characters"
        )

    input_bytes = input_path.read_bytes() if input_path.is_file() else b""
    schema_map, schema_map_hash = load_schema_map(schema_map_path)
    rows, missing_recommended_columns = load_csv(input_path, schema_map)
    records = process_rows(rows, region_bbox)
    batch_acceptance_rows: list[dict[str, Any]] = []
    batch_report: dict[str, Any] = {
        "schema_version": batch_qc.REPORT_VERSION,
        "status": "not_supplied",
        "batch_count": 0,
        "passed_batch_count": 0,
        "failed_or_incomplete_batch_count": 0,
        "scientific_boundary": (
            "No batch policy was supplied; batch acceptance was not used as an anomaly-background gate."
        ),
    }
    batch_gate_summary: dict[str, Any] = {
        "gate_applied": False,
        "decision_count": 0,
        "record_status_counts": {"not_supplied": len(records)},
        "accepted_batch_ids": [],
        "excluded_batch_ids": [],
    }
    if batch_qc_input_path is not None and batch_qc_policy_path is not None:
        try:
            batch_acceptance_rows, batch_report = batch_qc.evaluate(
                batch_qc_input_path, batch_qc_policy_path
            )
        except batch_qc.BatchQCError as exc:
            raise PipelineError(f"batch QC evaluation failed: {exc}") from exc
        batch_gate_summary = apply_batch_acceptance(records, batch_acceptance_rows)
    geology_summary = None
    if geology_grid_path is not None and normalized_grid_sha256 is not None:
        if not geology_grid_path.is_file():
            raise PipelineError(f"geology grid does not exist: {geology_grid_path}")
        observed_grid_sha256 = sha256_file(geology_grid_path)
        if observed_grid_sha256 != normalized_grid_sha256:
            raise PipelineError(
                "geology grid SHA-256 does not match --geology-grid-sha256"
            )
        geology_grid = GlimGrid(geology_grid_path)
        geology_summary = apply_spatial_geology(
            records, geology_grid, geology_grid_path, normalized_grid_sha256
        )
    config = {
        "group_by": list(group_by),
        "minimum_group_size": min_group_size,
        "robust_z_threshold": robust_z_threshold,
        "minimum_quantified_fraction": min_quantified_fraction,
        "region_bbox": list(region_bbox) if region_bbox else None,
        "schema_map": dict(sorted(schema_map.items())),
        "batch_qc_gate_applied": batch_gate_summary["gate_applied"],
        "spatial_grid_degrees": spatial_grid_degrees,
        "minimum_spatial_samples": min_spatial_samples,
        "minimum_spatial_candidates": min_spatial_candidates,
        "spatial_fdr_alpha": spatial_fdr_alpha,
    }
    if analysis_profile == "production":
        config["analysis_profile"] = analysis_profile
    if normalized_grid_sha256 is not None:
        config["geology_grid_sha256"] = normalized_grid_sha256
        config["geology_join_version"] = GEOLOGY_JOIN_VERSION
    if batch_qc_input_path is not None and batch_qc_policy_path is not None:
        config["batch_qc_input_sha256"] = sha256_file(batch_qc_input_path)
        config["batch_qc_policy_sha256"] = sha256_file(batch_qc_policy_path)
    input_hash = hashlib.sha256(input_bytes).hexdigest()
    run_id = hashlib.sha256(
        (
            input_hash + json.dumps(config, sort_keys=True, separators=(",", ":"))
        ).encode()
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
        records,
        group_by,
        min_group_size,
        robust_z_threshold,
        min_quantified_fraction,
        batch_qc_gate_applied=batch_gate_summary["gate_applied"],
    )
    anomaly_report["run_metadata"] = run_metadata
    anomaly_regions, spatial_anomaly_report = detect_spatial_anomaly_regions(
        records,
        geojson,
        anomaly_report,
        group_by,
        grid_degrees=spatial_grid_degrees,
        minimum_spatial_samples=min_spatial_samples,
        minimum_spatial_candidates=min_spatial_candidates,
        fdr_alpha=spatial_fdr_alpha,
        batch_qc_gate_applied=batch_gate_summary["gate_applied"],
    )
    spatial_anomaly_report["run_metadata"] = run_metadata
    qc_report = build_qc_report(records, run_metadata)
    qc_report["batch_qc"] = {
        **batch_gate_summary,
        "report_status": batch_report["status"],
        "passed_batch_count": int(batch_report.get("passed_batch_count", 0)),
        "failed_or_incomplete_batch_count": int(
            batch_report.get("failed_or_incomplete_batch_count", 0)
        ),
    }
    if geology_summary is not None:
        qc_report["geology_matching"] = geology_summary
    confidence_report = build_confidence_report(records, run_metadata)

    outputs = {
        "database": output_dir / "geochemistry.csv",
        "qc_report": output_dir / "qc_report.json",
        "confidence_report": output_dir / "confidence_report.json",
        "anomalies": output_dir / "anomalies.geojson",
        "anomaly_report": output_dir / "anomaly_report.json",
        "batch_acceptance": output_dir / "batch_acceptance.csv",
        "batch_qc_report": output_dir / "batch_qc_report.json",
        "anomaly_regions": output_dir / "anomaly_regions.geojson",
        "spatial_anomaly_report": output_dir / "spatial_anomaly_report.json",
    }
    write_csv(outputs["database"], records)
    atomic_write_text(outputs["qc_report"], json_text(qc_report))
    atomic_write_text(outputs["confidence_report"], json_text(confidence_report))
    atomic_write_text(outputs["anomalies"], json_text(geojson))
    atomic_write_text(outputs["anomaly_report"], json_text(anomaly_report))
    batch_qc.write_csv(outputs["batch_acceptance"], batch_acceptance_rows)
    batch_qc.write_report(outputs["batch_qc_report"], batch_report)
    atomic_write_text(outputs["anomaly_regions"], json_text(anomaly_regions))
    atomic_write_text(
        outputs["spatial_anomaly_report"], json_text(spatial_anomaly_report)
    )
    return outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Standardize geochemical CSV records, run QC, score operational confidence, and screen anomalies."
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Input CSV from the D1 acquisition/provenance stage",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory for nine deterministic D2 outputs",
    )
    parser.add_argument(
        "--schema-map",
        type=Path,
        help="Optional JSON object mapping canonical D2 input fields to source CSV column names",
    )
    parser.add_argument(
        "--batch-qc-input",
        type=Path,
        help="Optional normalized CRM/blank/duplicate CSV; requires --batch-qc-policy",
    )
    parser.add_argument(
        "--batch-qc-policy",
        type=Path,
        help="Explicit laboratory acceptance policy; requires --batch-qc-input",
    )
    parser.add_argument(
        "--geology-grid",
        type=Path,
        help="Optional official PANGAEA.788537 GLiM 0.5 degree ZIP for screening point-in-cell matching",
    )
    parser.add_argument(
        "--geology-grid-sha256",
        help="Required SHA-256 pin when --geology-grid is supplied",
    )
    parser.add_argument(
        "--analysis-profile",
        choices=("demo", "production"),
        default="demo",
        help="Production enforces at least 20 usable records per anomaly background group",
    )
    parser.add_argument(
        "--group-by",
        default=",".join(DEFAULT_GROUP_BY),
        help="Comma-separated canonical background fields (default also separates method family and extraction)",
    )
    parser.add_argument(
        "--min-group-size",
        type=int,
        help="Minimum usable records per group (default: demo=8, production=20)",
    )
    parser.add_argument(
        "--min-quantified-fraction",
        type=float,
        default=0.70,
        help="Minimum usable noncensored fraction per independent background group (default: 0.70)",
    )
    parser.add_argument(
        "--robust-z-threshold",
        type=float,
        default=3.5,
        help="Absolute modified z threshold",
    )
    parser.add_argument(
        "--spatial-grid-degrees",
        type=float,
        default=2.0,
        help="Fixed WGS84 screening-cell size; must divide 180 and 360 (default: 2)",
    )
    parser.add_argument(
        "--min-spatial-samples",
        type=int,
        help="Minimum mapped usable records inside and outside a tested cell (demo=5, production=20)",
    )
    parser.add_argument(
        "--min-spatial-candidates",
        type=int,
        default=2,
        help="Minimum record-level candidates before a significant cell is reported (default: 2)",
    )
    parser.add_argument(
        "--spatial-fdr-alpha",
        type=float,
        default=0.10,
        help="Benjamini-Hochberg FDR threshold for candidate regions (default: 0.10)",
    )
    parser.add_argument(
        "--region-bbox",
        type=parse_bbox,
        metavar="W,S,E,N",
        help="Optional requested region; dateline-crossing west > east is supported",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    group_by = tuple(
        field.strip() for field in args.group_by.split(",") if field.strip()
    )
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
            analysis_profile=args.analysis_profile,
            geology_grid_path=args.geology_grid,
            geology_grid_sha256=args.geology_grid_sha256,
            batch_qc_input_path=args.batch_qc_input,
            batch_qc_policy_path=args.batch_qc_policy,
            spatial_grid_degrees=args.spatial_grid_degrees,
            min_spatial_samples=args.min_spatial_samples,
            min_spatial_candidates=args.min_spatial_candidates,
            spatial_fdr_alpha=args.spatial_fdr_alpha,
        )
    except (PipelineError, OSError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {name: str(path) for name, path in outputs.items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
