#!/usr/bin/env python3
"""Run deterministic offline regression tests for the bundled Skill."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import standardize_geochemistry as standardizer
import evaluate_batch_qc as batch_qc
import build_iteration_backlog as backlog_builder

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
DEMO_INPUT = SKILL_DIR / "fixtures" / "demo_input.csv"
WORKFLOW = SCRIPT_DIR / "run_workflow.py"
VALIDATOR = SCRIPT_DIR / "validate_outputs.py"
DOWNLOADER = SCRIPT_DIR / "download_data.py"
STANDARDIZER = SCRIPT_DIR / "standardize_geochemistry.py"

EXPECTED_OUTPUTS = {
    "geochemistry.csv",
    "source_manifest.json",
    "record_evidence.jsonl",
    "qc_report.json",
    "confidence_report.json",
    "anomalies.geojson",
    "anomaly_report.json",
    "anomaly_regions.geojson",
    "spatial_anomaly_report.json",
    "batch_acceptance.csv",
    "batch_qc_report.json",
    "samples.geojson",
    "interactive_map.html",
    "iteration_backlog.csv",
    "run_summary.json",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_command(arguments: list[str], expected_code: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(arguments, capture_output=True, text=True, check=False, timeout=60)
    if result.returncode != expected_code:
        raise AssertionError(
            f"unexpected exit {result.returncode}, expected {expected_code}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    return result


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def by_id(rows: list[dict[str, str]], record_id: str) -> dict[str, str]:
    return next(row for row in rows if row["record_id"] == record_id)


def json_value(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def complete_d2_row(**overrides: str) -> dict[str, str]:
    row = {
        "record_id": "d2-test-1",
        "source_record_id": "source-row-1",
        "sample_id": "sample-1",
        "element_or_analyte": "As",
        "value": "10",
        "unit": "mg/kg",
        "medium": "soil",
        "measurement_basis": "dry_total",
        "latitude": "35",
        "longitude": "103",
        "source_crs": "EPSG:4326",
        "coordinate_uncertainty_m": "25",
        "geologic_unit": "granite",
        "analytical_method": "ICP-MS",
        "digestion_or_extraction": "four_acid",
        "license": "CC-BY-4.0",
        "source_tier": "government",
        "source_id": "dataset-1",
        "dataset_title": "Synthetic contract test",
        "dataset_version": "v1",
        "source_file": "synthetic.csv",
        "source_row": "2",
        "file_sha256": "0" * 64,
        "source_locator": "https://example.invalid/dataset#row=2",
    }
    row.update(overrides)
    return row


def write_test_glim_grid(path: Path) -> str:
    """Create a tiny-compressed, structurally complete GLiM-compatible test archive."""

    header = (
        "ncols 720\n"
        "nrows 360\n"
        "xllcorner -180\n"
        "yllcorner -90\n"
        "cellsize 0.5\n"
        "NODATA_value -9999\n"
    )
    raster = header + (("1 " * 719 + "1\n") * 360)
    classes = '"OBJECTID";"Value_";"Count_";"xx"\n1;1;259200;"su"\n'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Classnames.txt", classes)
        archive.writestr("glim_wgs84_0point5deg.txt.asc", raster)
    return standardizer.sha256_file(path)


def run_suite() -> dict[str, Any]:
    require(DEMO_INPUT.is_file(), "bundled demo_input.csv is missing")
    for schema_name in (
        "request.schema.json",
        "result.schema.json",
        "geochemistry-record.schema.json",
        "source-manifest.schema.json",
        "confidence-report.schema.json",
        "schema-map.schema.json",
        "platform-field-crosswalk.schema.json",
        "record-evidence.schema.json",
        "acquisition-run-manifest.schema.json",
        "source-registry.schema.json",
        "source-catalog.schema.json",
        "source-route-result.schema.json",
        "source-audit.schema.json",
        "source-evidence-report.schema.json",
        "snapshot-manifest.schema.json",
        "snapshot-diff.schema.json",
        "coverage-matrix.schema.json",
        "source-discovery-record.schema.json",
        "source-discovery-scope.schema.json",
        "marchem-candidate-verification.schema.json",
        "visualization-profile.schema.json",
        "visualization-report.schema.json",
        "iteration-backlog.schema.json",
        "dataset-source.schema.json",
        "publication.schema.json",
        "sampling-event.schema.json",
        "sample.schema.json",
        "analytical-method.schema.json",
        "provenance.schema.json",
        "observation.schema.json",
        "acquisition-run.schema.json",
        "batch-qc-policy.schema.json",
        "batch-qc-report.schema.json",
        "anomaly-regions.schema.json",
        "spatial-anomaly-report.schema.json",
        "request-execution.schema.json",
    ):
        schema = json_value(SKILL_DIR / "references" / schema_name)
        require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema", f"bad {schema_name}")

    record_schema = json_value(SKILL_DIR / "references" / "geochemistry-record.schema.json")
    coordinate_registry = json_value(
        SKILL_DIR / "references" / "coordinate-policy-registry.json"
    )
    require(
        coordinate_registry.get("schema_version")
        == "geochemical-coordinate-policy-registry-v1"
        and len(coordinate_registry.get("policies", [])) == 1,
        "coordinate policy registry is not frozen and auditable",
    )
    crosswalk = json_value(SKILL_DIR / "references" / "platform-field-crosswalk.json")
    mapped_fields = [item["canonical_field"] for item in crosswalk["field_mappings"]]
    non_core_fields = [field for group in crosswalk["non_core_fields"] for field in group["fields"]]
    require(crosswalk["crosswalk_version"] == "d2-platform-crosswalk-v1", "bad D2 crosswalk version")
    require(
        len(mapped_fields) == len(set(mapped_fields)) and len(non_core_fields) == len(set(non_core_fields)),
        "crosswalk contains duplicate canonical fields",
    )
    require(
        set(mapped_fields).isdisjoint(non_core_fields)
        and set(mapped_fields) | set(non_core_fields) == set(record_schema["properties"]),
        "crosswalk drifted from the D2 record schema",
    )
    require(
        all(source["url"].startswith("https://") for source in crosswalk["evidence_sources"]),
        "crosswalk evidence must use stable HTTPS locators",
    )
    batch_fixture = SKILL_DIR / "fixtures" / "batch-qc"
    batch_rows, batch_report = batch_qc.evaluate(
        batch_fixture / "batch_qc.csv", batch_fixture / "qc_policy.json"
    )
    require(
        batch_report["passed_batch_count"] == 1
        and batch_rows[0]["batch_id"] == "LAB-A"
        and batch_rows[0]["batch_pass"] is True
        and batch_rows[1]["batch_pass"] is False,
        "batch QC fixture did not preserve all-checks-must-pass semantics",
    )
    require(
        abs(batch_rows[0]["duplicate_rpd_percent"] - 9.523809523809524) < 1e-12
        and batch_rows[1]["crm_recovery_percent"] == 135.0
        and batch_rows[1]["blank_value"] == 8.0
        and batch_rows[1]["duplicate_rpd_percent"] == 40.0,
        "batch QC controls were not recomputed from observed values",
    )
    require(
        0 < standardizer.hypergeometric_survival(5, 40, 5, 20) < 0.05,
        "exact spatial-enrichment test mishandled a zero-candidate outside cell",
    )
    require(
        abs(standardizer.hypergeometric_survival(2, 10, 4, 3) - (1 / 3)) < 1e-12
        and abs(standardizer.hypergeometric_survival(1, 200_000, 100_000, 1) - 0.5)
        < 1e-9,
        "exact spatial-enrichment test lost short-tail accuracy or scalability",
    )
    _, fractional_grid_report = standardizer.detect_spatial_anomaly_regions(
        [],
        {"features": []},
        {"groups": []},
        standardizer.DEFAULT_GROUP_BY,
        grid_degrees=0.1,
    )
    require(
        fractional_grid_report["status"] == "insufficient_spatial_background",
        "spatial grid validation rejected a valid floating-point divisor",
    )

    with tempfile.TemporaryDirectory() as first_temp, tempfile.TemporaryDirectory() as second_temp:
        first = Path(first_temp)
        second = Path(second_temp)
        command = [sys.executable, str(WORKFLOW), "--input", str(DEMO_INPUT), "--output-dir"]
        run_command([*command, str(first)])
        run_command([*command, str(second)])
        require({path.name for path in first.iterdir()} == EXPECTED_OUTPUTS, "first run output set is unstable")
        require({path.name for path in second.iterdir()} == EXPECTED_OUTPUTS, "second run output set is unstable")
        for filename in EXPECTED_OUTPUTS:
            require((first / filename).read_bytes() == (second / filename).read_bytes(), f"{filename} is not deterministic")

        validation = run_command([sys.executable, str(VALIDATOR), "--output-dir", str(first)])
        validation_report = json.loads(validation.stdout)
        require(validation_report["status"] == "valid", "output validator did not return valid")
        tampered_transaction = first / "tampered-transaction"
        tampered_transaction.mkdir()
        for filename in EXPECTED_OUTPUTS:
            shutil.copy2(first / filename, tampered_transaction / filename)
        database_path = tampered_transaction / "geochemistry.csv"
        database_path.write_text(
            database_path.read_text(encoding="utf-8") + "\n", encoding="utf-8"
        )
        transaction_validation = run_command(
            [sys.executable, str(VALIDATOR), "--output-dir", str(tampered_transaction)],
            expected_code=1,
        )
        require(
            "artifact transaction mismatch for geochemistry.csv"
            in transaction_validation.stdout,
            "workflow validator accepted a post-commit D2 mutation",
        )
        tampered_interface = first / "tampered-interface"
        tampered_interface.mkdir()
        for filename in EXPECTED_OUTPUTS:
            shutil.copy2(first / filename, tampered_interface / filename)
        tampered_report_path = tampered_interface / "anomaly_report.json"
        tampered_report = json_value(tampered_report_path)
        tampered_report.pop("interface_version")
        tampered_report_path.write_text(
            json.dumps(tampered_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_validation = run_command(
            [sys.executable, str(VALIDATOR), "--output-dir", str(tampered_interface)],
            expected_code=1,
        )
        require(
            "unsupported interface_version" in tampered_validation.stdout,
            "output validator accepted a missing D2 interface version",
        )
        tampered_method = first / "tampered-method"
        tampered_method.mkdir()
        for filename in EXPECTED_OUTPUTS:
            shutil.copy2(first / filename, tampered_method / filename)
        tampered_method_report_path = tampered_method / "anomaly_report.json"
        tampered_method_report = json_value(tampered_method_report_path)
        tampered_method_report["method_version"] = "tampered-method-v999"
        tampered_method_report_path.write_text(
            json.dumps(tampered_method_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_anomalies_path = tampered_method / "anomalies.geojson"
        tampered_anomalies = json_value(tampered_anomalies_path)
        tampered_anomalies["method_version"] = "tampered-method-v999"
        for feature in tampered_anomalies["features"]:
            feature["properties"]["method_version"] = "tampered-method-v999"
        tampered_anomalies_path.write_text(
            json.dumps(tampered_anomalies, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_method_validation = run_command(
            [sys.executable, str(VALIDATOR), "--output-dir", str(tampered_method)],
            expected_code=1,
        )
        require(
            "unsupported method_version" in tampered_method_validation.stdout,
            "output validator accepted a tampered D2 anomaly method version",
        )
        tampered_spatial = first / "tampered-spatial-method"
        tampered_spatial.mkdir()
        for filename in EXPECTED_OUTPUTS:
            shutil.copy2(first / filename, tampered_spatial / filename)
        tampered_regions_path = tampered_spatial / "anomaly_regions.geojson"
        tampered_regions = json_value(tampered_regions_path)
        tampered_regions["method_version"] = "tampered-spatial-v999"
        tampered_regions_path.write_text(
            json.dumps(tampered_regions, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tampered_spatial_validation = run_command(
            [sys.executable, str(VALIDATOR), "--output-dir", str(tampered_spatial)],
            expected_code=1,
        )
        require(
            "unsupported interface or method version" in tampered_spatial_validation.stdout,
            "output validator accepted a tampered empty spatial-region collection",
        )

        rows = read_csv(first / "geochemistry.csv")
        require(len(rows) == 19, "demo should contain 19 canonical records")
        iteration_rows = read_csv(first / "iteration_backlog.csv")
        require(
            any(
                row["issue_code"] == "CENSORED_OBSERVATION"
                and row["status"] == "scientific_limit"
                and row["auto_recheck"] == "false"
                for row in iteration_rows
            ),
            "iteration backlog must preserve censored observations as non-imputed scientific limits",
        )
        require(float(by_id(rows, "rock-fe-001")["normalized_value"]) == 25_000, "wt% conversion failed")
        spaced_weight_percent = standardizer.normalize_row(
            complete_d2_row(value="1", unit="wt. %", medium="rock"),
            2,
        )
        require(
            spaced_weight_percent["normalized_value"] == 10_000,
            "wt. % alias conversion failed",
        )
        require(float(by_id(rows, "water-pb-001")["normalized_value"]) == 20, "water mg/L conversion failed")
        molar_ni = standardizer.normalize_row(
            complete_d2_row(
                element_or_analyte="Ni", value="20.814", unit="nmol/L",
                medium="water", measurement_basis="dissolved",
            ),
            2,
        )
        require(
            abs(molar_ni["normalized_value"] - 1.2216444276) < 1e-12
            and molar_ni["normalized_unit"] == "ug/L"
            and "d2-ciaaw-abridged-2024-v1" in molar_ni["conversion_formula"],
            "audited nmol/L elemental conversion failed",
        )
        molar_unknown = standardizer.normalize_row(
            complete_d2_row(
                element_or_analyte="U", value="2", unit="nmol/L",
                medium="water", measurement_basis="dissolved",
            ),
            2,
        )
        require(
            molar_unknown["normalized_value"] is None
            and "UNSUPPORTED_MOLAR_MASS" in molar_unknown["qc_flags"],
            "unknown nmol/L atomic mass did not fail closed",
        )
        molar_per_mass = standardizer.normalize_row(
            complete_d2_row(
                element_or_analyte="Ni", value="2", unit="nmol/kg",
                medium="water", measurement_basis="dissolved",
            ),
            2,
        )
        require(
            molar_per_mass["normalized_value"] == 2
            and molar_per_mass["normalized_unit"] == "nmol/kg",
            "nmol/kg must remain a same-unit canonical value without density inference",
        )
        ambiguous = by_id(rows, "water-as-ambiguous")
        require(ambiguous["normalized_value"] == "", "ambiguous water ppm must not be converted")
        require("AMBIGUOUS_AQUEOUS_RATIO_UNIT" in ambiguous["qc_flags"], "ambiguous water flag missing")
        censored = by_id(rows, "soil-as-013")
        require(censored["normalized_value"] == "", "censored value was imputed")
        require(float(censored["normalized_censoring_limit"]) == 0.1, "censoring limit was not preserved")
        swapped = by_id(rows, "swap-coord-001")
        require(swapped["latitude"] == "" and swapped["longitude"] == "", "coordinate swap was silently applied")
        require("POSSIBLE_COORDINATE_SWAP" in swapped["qc_flags"], "coordinate swap flag missing")
        duplicates = [row for row in rows if "DUPLICATE_CANDIDATE" in row["qc_flags"]]
        require(len(duplicates) == 2, "duplicate candidates should be retained and flagged")
        require(censored["censored"] == "true", "censored state was not serialized explicitly")
        require(by_id(rows, "soil-as-001")["method_family"] == "icp_ms", "method family normalization failed")
        source_qualified = standardizer.normalize_row(
            complete_d2_row(
                value="0.6", value_qualifier="", source_qualifier_raw="<",
                detection_limit="0.6", detection_limit_unit="mg/kg",
            ),
            2,
        )
        require(
            source_qualified["source_qualifier_raw"] == "<"
            and source_qualified["value_qualifier"] == "lt"
            and source_qualified["normalized_value"] is None
            and source_qualified["normalized_censoring_limit"] == 0.6,
            "source qualifier was not preserved and canonicalized conservatively",
        )
        embedded_lt = standardizer.normalize_row(
            complete_d2_row(value="<0.4", value_qualifier="", source_qualifier_raw=""),
            2,
        )
        embedded_nd = standardizer.normalize_row(
            complete_d2_row(
                value="N", value_qualifier="", source_qualifier_raw="",
                detection_limit="0.2", detection_limit_unit="mg/kg",
            ),
            2,
        )
        require(
            embedded_lt["source_qualifier_raw"] == "<"
            and embedded_lt["value_qualifier"] == "lt"
            and embedded_nd["source_qualifier_raw"] == "N"
            and embedded_nd["value_qualifier"] == "nd",
            "qualifiers embedded in value were not retained in the dedicated raw field",
        )

        record_schema = json_value(SKILL_DIR / "references" / "geochemistry-record.schema.json")
        normalized_record = standardizer.normalize_row(complete_d2_row(), 2)
        require(set(normalized_record) == set(record_schema["required"]), "D2 record keys drifted from required schema")
        require(set(normalized_record) == set(record_schema["properties"]), "D2 record keys drifted from schema properties")
        require(
            normalized_record["operational_confidence"]["version"] == "d2-confidence-v3",
            "D2 confidence version did not advance with the schema",
        )

        oxide = standardizer.normalize_row(
            complete_d2_row(
                element_or_analyte="Ni", analyte_reported="NiO", species_or_oxide="NiO",
                value="0.018", unit="wt%", medium="rock",
            ),
            3,
        )
        expected_ni = 0.018 * 10_000 * 58.6934 / (58.6934 + 15.999)
        require(abs(oxide["normalized_value"] - expected_ni) < 1e-9, "audited NiO-to-Ni conversion failed")
        require("d2-atomic-weights-v1" in oxide["conversion_formula"], "oxide conversion lacks version evidence")
        unsupported_species = standardizer.normalize_row(
            complete_d2_row(element_or_analyte="Fe2O3T", value="1", unit="wt%"),
            4,
        )
        require(unsupported_species["normalized_value"] is None, "ambiguous total-iron conversion did not fail closed")
        require(
            "UNSUPPORTED_SPECIES_CONVERSION" in unsupported_species["qc_flags"],
            "ambiguous species conversion flag is missing",
        )
        require(
            unsupported_species["operational_confidence"]["band"] == "low"
            and unsupported_species["operational_confidence"]["overall"] <= 0.59,
            "error-level species ambiguity escaped the confidence gate",
        )
        oxide_mismatch = standardizer.normalize_row(
            complete_d2_row(element_or_analyte="Fe", species_or_oxide="NiO", value="1", unit="wt%"),
            5,
        )
        require(oxide_mismatch["normalized_value"] is None, "oxide-element mismatch was converted")
        require("OXIDE_ELEMENT_MISMATCH" in oxide_mismatch["qc_flags"], "oxide-element mismatch flag is missing")

        trace = standardizer.normalize_row(complete_d2_row(value="trace"), 6)
        not_analyzed = standardizer.normalize_row(complete_d2_row(value="N/A"), 7)
        require(trace["censored"] is True and trace["value_qualifier"] == "trace", "trace semantics were lost")
        require("UNQUANTIFIED_TRACE" in trace["qc_flags"], "trace quality flag is missing")
        require(
            not_analyzed["censored"] is False and not_analyzed["missing_reason"] == "not_analyzed",
            "missing reason was conflated with censoring",
        )
        bad_limit = standardizer.normalize_row(
            complete_d2_row(value="ND", detection_limit="-0.1", detection_limit_unit="mg/kg"),
            8,
        )
        require(bad_limit["normalized_censoring_limit"] is None, "invalid detection limit was normalized")
        require("INVALID_DETECTION_LIMIT" in bad_limit["qc_flags"], "invalid detection-limit flag is missing")

        lod = standardizer.normalize_row(
            complete_d2_row(value="<LOD", detection_limit="0.2", detection_limit_unit="mg/kg"), 9
        )
        loq = standardizer.normalize_row(
            complete_d2_row(value="<LOQ", quantitation_limit="0.4", quantitation_limit_unit="mg/kg"), 10
        )
        require(
            lod["censored"] is True
            and lod["value_qualifier"] == "bdl"
            and lod["normalized_value"] is None
            and lod["normalized_censoring_limit"] == 0.2,
            "literal <LOD was not preserved as a non-imputed detection-limit censor",
        )
        require(
            loq["censored"] is True
            and loq["value_qualifier"] == "loq"
            and loq["normalized_value"] is None
            and loq["normalized_censoring_limit"] == 0.4,
            "literal <LOQ was not preserved with its quantitation limit",
        )

        projected = standardizer.normalize_row(complete_d2_row(source_crs="EPSG:3857"), 9)
        transformed = standardizer.normalize_row(
            complete_d2_row(
                original_latitude_raw="4163881.144",
                original_longitude_raw="11465907.552",
                source_crs="EPSG:3857",
                coordinate_transform_method="pyproj EPSG:3857 to EPSG:4326; always_xy=true",
            ),
            10,
        )
        require(projected["latitude"] is None and projected["longitude"] is None, "projected CRS was mislabeled WGS84")
        require("UNSUPPORTED_SOURCE_CRS" in projected["qc_flags"], "missing coordinate-transform evidence was not flagged")
        require(transformed["latitude"] == 35 and transformed["longitude"] == 103, "declared coordinate transform was rejected")
        require(
            transformed["original_latitude_raw"] == "4163881.144"
            and transformed["original_longitude_raw"] == "11465907.552",
            "source-coordinate evidence was not preserved after transformation",
        )
        reported_only = standardizer.normalize_row(
            complete_d2_row(
                latitude="", longitude="", source_crs="",
                original_latitude_raw="35", original_longitude_raw="103",
            ),
            11,
        )
        require(
            reported_only["latitude"] is None
            and reported_only["longitude"] is None
            and "COORDINATE_NOT_CANONICALIZED" in reported_only["qc_flags"]
            and "INVALID_COORDINATE" not in reported_only["qc_flags"],
            "valid reported coordinates without datum evidence are withheld rather than mislabeled invalid",
        )
        missing_crs = standardizer.normalize_row(complete_d2_row(source_crs=""), 12)
        require(
            missing_crs["latitude"] is None
            and missing_crs["longitude"] is None
            and "MISSING_SOURCE_CRS" in missing_crs["qc_flags"]
            and "COORDINATE_NOT_CANONICALIZED" in missing_crs["qc_flags"],
            "numeric coordinates without CRS evidence are withheld from canonical map fields",
        )
        pangaea_policy = standardizer.normalize_row(
            complete_d2_row(
                source_crs="", dataset_doi="10.1594/PANGAEA.947275",
                coordinate_evidence_scope="platform_policy_declared",
                coordinate_policy_id="pangaea-geocode-wgs84-v1",
                coordinate_latitude_field="LATITUDE",
                coordinate_longitude_field="LONGITUDE",
            ),
            13,
        )
        require(
            pangaea_policy["latitude"] == 35
            and pangaea_policy["longitude"] == 103
            and pangaea_policy["source_crs"] == "EPSG:4326"
            and pangaea_policy["coordinate_policy_sha256"]
            == "48a3e043e5a82a99e23dbde4fd9b97b012846a45ba47e46a5faf2f2ce0649a1b"
            and "PLATFORM_CRS_POLICY_APPLIED" in pangaea_policy["qc_flags"],
            "allowlisted PANGAEA platform CRS policy was not applied with evidence",
        )
        non_pangaea_policy = standardizer.normalize_row(
            complete_d2_row(
                source_crs="", dataset_doi="10.17632/example.1",
                coordinate_evidence_scope="platform_policy_declared",
                coordinate_policy_id="pangaea-geocode-wgs84-v1",
                coordinate_latitude_field="LATITUDE",
                coordinate_longitude_field="LONGITUDE",
            ),
            14,
        )
        require(
            non_pangaea_policy["latitude"] is None
            and "INVALID_COORDINATE_POLICY" in non_pangaea_policy["qc_flags"],
            "PANGAEA CRS policy leaked to a non-PANGAEA repository",
        )

        backlog_ids = {
            backlog_builder.item_id("record-1", "QC_ERROR_REVIEW", "qc_flags", observed)
            for observed in ("INVALID_COORDINATE", "UNSUPPORTED_UNIT")
        }
        require(
            len(backlog_ids) == 2
            and backlog_builder.item_id(
                "record-1", "QC_ERROR_REVIEW", "qc_flags", " INVALID_COORDINATE "
            )
            == backlog_builder.item_id(
                "record-1", "QC_ERROR_REVIEW", "qc_flags", "INVALID_COORDINATE"
            ),
            "iteration backlog IDs collide or are not deterministically normalized",
        )

        duplicate_records = standardizer.process_rows([
            complete_d2_row(record_id="duplicate-1", source_record_id="source-row-1"),
            complete_d2_row(record_id="duplicate-2", source_record_id="source-row-2"),
        ])
        require(
            all("DUPLICATE_CANDIDATE" in record["qc_flags"] for record in duplicate_records),
            "unique provenance row IDs masked duplicate measurement candidates",
        )
        duplicates_without_sample_ids = standardizer.process_rows([
            complete_d2_row(record_id="duplicate-3", source_record_id="source-row-3", sample_id=""),
            complete_d2_row(record_id="duplicate-4", source_record_id="source-row-4", sample_id=""),
        ])
        require(
            all("DUPLICATE_CANDIDATE" in record["qc_flags"] for record in duplicates_without_sample_ids),
            "distinct source row IDs masked duplicates when sample identifiers were absent",
        )
        distinct_sampling_times = standardizer.process_rows([
            complete_d2_row(record_id="time-1", source_record_id="time-row-1", sample_id="", sampled_at="2020-01-01"),
            complete_d2_row(record_id="time-2", source_record_id="time-row-2", sample_id="", sampled_at="2021-01-01"),
        ])
        require(
            all("DUPLICATE_CANDIDATE" not in record["qc_flags"] for record in distinct_sampling_times),
            "duplicate fallback collapsed measurements from distinct sampling times",
        )

        try:
            standardizer.run_pipeline(
                DEMO_INPUT,
                Path(first_temp) / "invalid-production",
                analysis_profile="production",
                min_group_size=8,
            )
        except standardizer.PipelineError as exc:
            require("at least 20" in str(exc), "production minimum-group failure is not actionable")
        else:
            raise AssertionError("production analysis accepted a background group threshold below 20")

        with tempfile.TemporaryDirectory(prefix="d2-geology-") as geology_temp:
            geology_root = Path(geology_temp)
            geology_grid = geology_root / "glim-test.zip"
            geology_hash = write_test_glim_grid(geology_grid)
            geology_input = geology_root / "input.csv"
            geology_rows = [
                complete_d2_row(
                    record_id="geo-soil", source_record_id="geo-source-soil",
                    sample_id="geo-sample-soil", latitude="35.25", longitude="103.25",
                ),
                complete_d2_row(
                    record_id="geo-water", source_record_id="geo-source-water",
                    sample_id="geo-sample-water", medium="water", unit="ug/L",
                    latitude="35.25", longitude="103.25",
                ),
            ]
            with geology_input.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(geology_rows[0]))
                writer.writeheader()
                writer.writerows(geology_rows)
            geology_outputs = standardizer.run_pipeline(
                geology_input,
                geology_root / "output",
                min_group_size=3,
                geology_grid_path=geology_grid,
                geology_grid_sha256=geology_hash,
            )
            geology_database = {row["record_id"]: row for row in read_csv(geology_outputs["database"])}
            geology_qc = json_value(geology_outputs["qc_report"])["geology_matching"]
            require(
                geology_database["geo-soil"]["matched_geologic_unit"] == "GLiM:1:su"
                and geology_database["geo-soil"]["geology_map_source"] == standardizer.GLIM_SOURCE
                and float(geology_database["geo-soil"]["boundary_distance_m"]) > 20_000,
                "D2 GLiM point-in-cell did not populate versioned spatial geology evidence",
            )
            require(
                geology_database["geo-water"]["matched_geologic_unit"] == ""
                and geology_database["geo-water"]["geology_missing_reason"] == "not_applicable_water"
                and geology_qc["water_records_with_assigned_land_unit"] == 0
                and geology_qc["grid"]["sha256"] == geology_hash,
                "D2 GLiM join assigned land geology to water or lost the grid hash",
            )
            try:
                standardizer.run_pipeline(
                    geology_input,
                    geology_root / "hash-mismatch",
                    min_group_size=3,
                    geology_grid_path=geology_grid,
                    geology_grid_sha256="0" * 64,
                )
            except standardizer.PipelineError as exc:
                require("SHA-256" in str(exc), "geology hash mismatch error is not actionable")
            else:
                raise AssertionError("D2 accepted a geology grid whose SHA-256 did not match")

        low_fraction_values = ["8", "9", "10", "11", "12", "13", "500", "<1", "<1", "ND", "trace"]
        low_fraction_records = [
            standardizer.normalize_row(
                complete_d2_row(
                    record_id=f"fraction-{index}", source_record_id=f"source-{index}",
                    sample_id=f"sample-{index}", value=value,
                ),
                index + 10,
            )
            for index, value in enumerate(low_fraction_values)
        ]
        low_geojson, low_report = standardizer.detect_anomalies(
            low_fraction_records, min_group_size=3, min_quantified_fraction=0.70
        )
        require(not low_geojson["features"], "low quantified fraction still produced an anomaly")
        require(
            low_report["groups"][0]["status"] == "insufficient_quantified_fraction",
            "low quantified fraction did not produce an explicit failure state",
        )

        small_records = [
            standardizer.normalize_row(
                complete_d2_row(
                    record_id=f"small-{index}", source_record_id=f"small-source-{index}",
                    sample_id=f"small-sample-{index}", value=str(10 + index),
                ),
                index + 30,
            )
            for index in range(4)
        ]
        _, small_report = standardizer.detect_anomalies(small_records)
        require(
            small_report["groups"][0]["status"] == "insufficient_group_size",
            "small background group did not fail closed",
        )
        priority_records = [
            standardizer.normalize_row(
                complete_d2_row(
                    record_id=f"priority-{index}",
                    source_record_id=f"priority-source-{index}",
                    sample_id=f"priority-sample-{index}",
                    value=value,
                ),
                index + 34,
            )
            for index, value in enumerate(("10", "<1", "ND", "trace"))
        ]
        _, priority_report = standardizer.detect_anomalies(
            priority_records, min_group_size=8, min_quantified_fraction=0.70
        )
        require(
            priority_report["groups"][0]["status"] == "insufficient_group_size"
            and priority_report["gate_evaluation_order"][:2]
            == ["independent_record_count", "quantified_fraction"],
            "anomaly gates did not evaluate total sample size before quantified fraction",
        )
        flat_records = [
            standardizer.normalize_row(
                complete_d2_row(
                    record_id=f"flat-{index}", source_record_id=f"flat-source-{index}",
                    sample_id=f"flat-sample-{index}", value="10",
                ),
                index + 40,
            )
            for index in range(8)
        ]
        _, flat_report = standardizer.detect_anomalies(flat_records)
        require(flat_report["groups"][0]["status"] == "zero_dispersion", "zero-MAD group was force-scored")

        with tempfile.TemporaryDirectory(prefix="d2-batch-gate-") as batch_temp:
            batch_root = Path(batch_temp)
            batch_input = batch_root / "measurements.csv"
            batch_measurements = [
                complete_d2_row(
                    record_id=f"batch-{index}",
                    source_record_id=f"batch-source-{index}",
                    sample_id=f"batch-sample-{index}",
                    analysis_batch_id=batch_id,
                    value=str(value),
                )
                for index, (batch_id, value) in enumerate(
                    (("LAB-A", 10), ("LAB-A", 11), ("LAB-A", 12),
                     ("LAB-B", 100), ("LAB-B", 110), ("LAB-B", 120))
                )
            ]
            with batch_input.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(batch_measurements[0]))
                writer.writeheader()
                writer.writerows(batch_measurements)
            batch_outputs = standardizer.run_pipeline(
                batch_input,
                batch_root / "output",
                min_group_size=3,
                batch_qc_input_path=batch_fixture / "batch_qc.csv",
                batch_qc_policy_path=batch_fixture / "qc_policy.json",
            )
            batch_database = read_csv(batch_outputs["database"])
            batch_anomaly = json_value(batch_outputs["anomaly_report"])
            batch_gate_report = json_value(batch_outputs["batch_qc_report"])
            require(
                batch_gate_report["passed_batch_count"] == 1
                and sum(row["batch_qc_status"] == "pass" for row in batch_database) == 3
                and sum(row["batch_qc_status"] == "fail" for row in batch_database) == 3
                and batch_anomaly["groups"][0]["records_used"] == 3
                and batch_anomaly["groups"][0]["exclusion_reasons"]["batch_qc_failed"] == 3,
                "end-to-end batch gate did not retain failed records while excluding their background values",
            )

        with tempfile.TemporaryDirectory() as mapped_temp:
            mapped_root = Path(mapped_temp)
            mapped_input = mapped_root / "mapped.csv"
            mapped_input.write_text("Analyte,Result,Units,Matrix\nAs,10,mg/kg,soil\n", encoding="utf-8")
            schema_map_path = mapped_root / "schema-map.json"
            schema_map_path.write_text(
                json.dumps({
                    "element_or_analyte": "Analyte", "value": "Result", "unit": "Units", "medium": "Matrix"
                }),
                encoding="utf-8",
            )
            mapped_outputs = standardizer.run_pipeline(
                mapped_input, mapped_root / "outputs", schema_map_path=schema_map_path, min_group_size=3
            )
            mapped_rows = read_csv(mapped_outputs["database"])
            require(mapped_rows[0]["element_or_analyte"] == "As", "D1-to-D2 schema map was not applied")
            mapped_confidence = json_value(mapped_outputs["confidence_report"])
            require(
                mapped_confidence["run_metadata"]["schema_map_sha256"] is not None,
                "schema-map evidence hash was not recorded",
            )
            bad_map = mapped_root / "bad-schema-map.json"
            bad_map.write_text('{"invented_field":"Analyte"}', encoding="utf-8")
            run_command(
                [
                    sys.executable, str(STANDARDIZER), "--input", str(mapped_input),
                    "--output-dir", str(mapped_root / "bad-outputs"), "--schema-map", str(bad_map),
                ],
                expected_code=2,
            )
            require(not (mapped_root / "bad-outputs").exists(), "invalid schema map produced partial outputs")

        anomaly_report = json_value(first / "anomaly_report.json")
        anomalies = json_value(first / "anomalies.geojson")
        require(
            anomaly_report["interface_version"] == "d2-interface-v2"
            and anomalies["interface_version"] == "d2-interface-v2",
            "D2 anomaly interface version is missing",
        )
        require(anomaly_report["candidate_count"] == 1, "demo should contain one anomaly candidate")
        require(anomalies["features"][0]["properties"]["record_id"] == "soil-as-012", "wrong anomaly")
        require(anomalies["features"][0]["properties"]["status"] == "candidate_anomaly", "causal overclaim")
        summary = json_value(first / "run_summary.json")
        result_schema = json_value(SKILL_DIR / "references" / "result.schema.json")
        require(
            set(summary["metrics"])
            == set(result_schema["properties"]["metrics"]["properties"])
            == set(result_schema["properties"]["metrics"]["required"]),
            "run summary metrics drifted from the public result Schema",
        )
        require(summary["input"]["synthetic_demo"] is True, "demo must be labeled synthetic")
        require(summary["coverage"]["interpolation"] is False, "demo must not interpolate blank areas")
        manifest = json_value(first / "source_manifest.json")
        confidence_hash = hashlib.sha256((first / "confidence_report.json").read_bytes()).hexdigest()
        require(manifest["confidence_report"]["sha256"] == confidence_hash, "confidence evidence hash mismatch")
        require(manifest["coverage"]["source_locator_rate"] == 1.0, "demo provenance coverage should be complete")
        require(manifest["manifest_version"] == "geochemical-source-manifest-v2", "source manifest version drifted")
        require(
            manifest["record_evidence"]["sha256"]
            == hashlib.sha256((first / "record_evidence.jsonl").read_bytes()).hexdigest(),
            "record evidence hash mismatch",
        )
        confidence = json_value(first / "confidence_report.json")
        require(
            set(confidence["component_definitions"])
            == {"source", "completeness", "method", "spatial", "qc", "overall"},
            "confidence component definitions are incomplete",
        )

        html = (first / "interactive_map.html").read_text(encoding="utf-8")
        require("<script src=" not in html.casefold(), "map has an external script dependency")
        require("候选异常不代表污染" in html, "map omits interpretation boundary")
        require("d3-interactive-atlas-v3" in html, "map version is missing")
        require("ALL DATA" in html, "map does not default to the complete overview")
        require("Natural Earth 1:110m" in html, "map omits the offline land basemap")
        require(
            "ai4s-natural-earth-admin0-v1" in html and "pointInCountry" in html,
            "map omits pinned country boundaries or strict country clipping",
        )
        require(
            "一行 = 一个样品的一项元素测定" in html,
            "map does not explain measurement-to-sample deduplication",
        )
        require(
            all(
                marker in html
                for marker in (
                    'id="region"',
                    'id="mapMode"',
                    'id="colorMode"',
                    'id="comboX"',
                    'id="comboY"',
                    'id="comboRegionSelect"',
                    'id="comboCustomBounds"',
                    'id="applyComboBounds"',
                    "applyCustomBounds",
                    'id="openAnomalyRegions"',
                    'id="statisticalRegionSummary"',
                    "d2-spatial-hypergeometric-fdr-v1",
                    "d3-dual-scope-atlas-v4",
                    'id="projectionMode"',
                    'id="globe"',
                    'id="anomalyDensityCanvas"',
                    "showAnomalyRegion",
                    "focusAnomalyRegion",
                    "D2 未提供分析方法",
                    "该结果比较同类样品的统计背景",
                    'id="deliverableCenter"',
                    'id="taskContext"',
                    "task-first-progressive-disclosure-v2",
                    "d3-visual-question-contract-v1",
                    "competition-geochemistry-v1",
                    "可交互元素分布地图",
                    "标准化地球化学数据库",
                    "元素组合对比",
                    "数据来源与置信度说明",
                    "异常区域识别结果",
                    "质量控制与数据复核",
                    'id="zoomIn"',
                    "comboQuadrants",
                    'id="databaseView"',
                    'id="databaseSearch"',
                    'id="databaseDistributionCanvas"',
                    'id="databaseCoverageMatrix"',
                    'id="databaseCompletenessChart"',
                    'id="confidenceSummary"',
                    'id="confidenceComponents"',
                    "renderDatabase",
                    "renderConfidence",
                    'href="geochemistry.csv"',
                    'href="confidence_report.json"',
                    "不是正确概率",
                )
            ),
            "map omits D3 v3 region, heatmap, combination or anomaly-region controls",
        )
        require(
            'id="storyPreset"' not in html and html.count('class="tabs"') == 1,
            "map duplicates its task navigation",
        )
        require(
            summary["map_report"]["display_sample_count"] == 17
            and summary["map_report"]["unmappable_record_count"] == 1,
            "map report does not reconcile sample-level display and coordinate failures",
        )
        samples_open = '<script id="samples-data" type="application/json">'
        packed = json.loads(html.split(samples_open, 1)[1].split("</script>", 1)[0])
        require(
            packed["schema_version"] == "d3-compact-payload-v1"
            and len(packed["rows"]) == 18
            and len(packed["fields"]) == len(packed["rows"][0])
            and isinstance(packed["strings"], list),
            "map compact payload does not round-trip the mapped demo records",
        )
        coverage = summary["map_report"]["region_coverage"]
        require(
            coverage["global"]["record_count"] == 18
            and coverage["global"]["sample_count"] == 17
            and coverage["shanghai"]["administrative_clip"] is False,
            "map region coverage does not reconcile records or bbox semantics",
        )
        require("\\u003c/script\\u003e" in __import__("build_interactive_map").safe_embedded_json("</script>"), "unsafe JSON embedding")

        limited = first / "limited"
        run_command(
            [sys.executable, str(WORKFLOW), "--input", str(DEMO_INPUT), "--output-dir", str(limited), "--max-records", "5"],
            expected_code=2,
        )
        limited_summary = json_value(limited / "run_summary.json")
        require(limited_summary["status"] == "unsupported_scope", "record limit must fail closed")

        no_provenance_input = first / "no-provenance.csv"
        no_provenance_input.write_text(
            "element_or_analyte,value,unit,medium\nAs,10,mg/kg,soil\n",
            encoding="utf-8",
        )
        no_provenance_output = first / "no-provenance-output"
        run_command(
            [
                sys.executable, str(WORKFLOW), "--input", str(no_provenance_input),
                "--output-dir", str(no_provenance_output),
            ],
            expected_code=2,
        )
        require(
            json_value(no_provenance_output / "run_summary.json")["status"] == "conflicting_evidence",
            "full workflow must fail closed when core provenance is absent",
        )

        bad_manifest = first / "bad-download.json"
        run_command(
            [
                sys.executable,
                str(DOWNLOADER),
                "--url",
                "http://127.0.0.1/private.csv",
                "--output",
                str(first / "should-not-exist.csv"),
                "--manifest",
                str(bad_manifest),
                "--license",
                "unresolved",
                "--retries",
                "0",
            ],
            expected_code=2,
        )
        require(not (first / "should-not-exist.csv").exists(), "unsafe downloader wrote an output")

        return {
            "status": "PASS",
            "tests": 75,
            "records": len(rows),
            "mapped_records": len(json_value(first / "samples.geojson")["features"]),
            "candidate_anomalies": anomaly_report["candidate_count"],
        }


def main() -> int:
    try:
        report = run_suite()
    except (AssertionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
