#!/usr/bin/env python3
"""Validate a standalone D3 visualization bundle, including a real render smoke test."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import zlib
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import build_interactive_map as map_builder
import render_visualization as renderer
import validate_outputs as workflow_validator


MAX_OUTPUT_BYTES = 100_000_000

# --- headless render smoke -------------------------------------------------
BROWSER_ENV = "GGA_HEADLESS_BROWSER"
BROWSER_CANDIDATES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "headless_shell",
    "msedge",
)
RENDER_ATTEST_MARKER = "data-gca-render-attest"
BANNER_MARKER = f'id="{map_builder.REPORTED_BANNER_ID}"'
REPORTED_MODE_MARKER = '"coordinate_mode":"reported"'
SVG_GRAPHIC_PATTERN = re.compile(
    r"<(?:circle|path|polygon|polyline|rect|ellipse|line)\b", re.IGNORECASE
)
CANVAS_PATTERN = re.compile(r"<canvas\b", re.IGNORECASE)
ATTEST_PATTERN = re.compile(r'data-gca-render-attest="([^"]*)"')
RENDER_TIMEOUT_SECONDS = 60.0
VIRTUAL_TIME_BUDGET_MS = 10_000
MIN_PAINTED_FRACTION = 0.02
MIN_DISTINCT_COLORS = 16


def find_headless_browser() -> str | None:
    """Locate a Chromium-family browser; GGA_HEADLESS_BROWSER overrides discovery."""
    override = os.environ.get(BROWSER_ENV)
    if override is not None:
        if override.strip() == "":
            return None
        return override if shutil.which(override) else None
    for candidate in BROWSER_CANDIDATES:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _browser_run(
    browser: str, extra_args: Sequence[str], target: str
) -> tuple[int, str, str]:
    command = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--window-size=1280,860",
        f"--virtual-time-budget={VIRTUAL_TIME_BUDGET_MS}",
        "--enable-logging=stderr",
        *extra_args,
        target,
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=RENDER_TIMEOUT_SECONDS,
    )
    return result.returncode, result.stdout, result.stderr


def _console_uncaught_lines(stderr: str) -> list[str]:
    """Keep page console lines reporting uncaught errors; drop network/OS noise."""
    lines = []
    for line in stderr.splitlines():
        if "CONSOLE" in line and "uncaught" in line.casefold():
            lines.append(line.strip())
    return lines


def _png_unfilter(width: int, height: int, bpp: int, raw: bytes) -> bytes:
    stride = width * bpp
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        if pos >= len(raw):
            raise ValueError("PNG scanline data is truncated")
        filter_type = raw[pos]
        pos += 1
        line = bytearray(raw[pos : pos + stride])
        if len(line) < stride:
            raise ValueError("PNG scanline data is truncated")
        pos += stride
        if filter_type == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"unsupported PNG filter type {filter_type}")
        out += line
        prev = line
    return bytes(out)


def png_paint_statistics(data: bytes) -> dict[str, Any]:
    """Decode a non-interlaced 8-bit RGB/RGBA PNG and measure painted coverage."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    pos = 8
    width = height = 0
    bpp = 0
    idat = bytearray()
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        chunk_type = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
            if bit_depth != 8 or color_type not in (2, 6) or interlace != 0:
                raise ValueError(
                    "render smoke expects an 8-bit non-interlaced RGB/RGBA screenshot"
                )
            bpp = 3 if color_type == 2 else 4
        elif chunk_type == b"IDAT":
            idat += chunk
        elif chunk_type == b"IEND":
            break
    if not width or not height or not idat:
        raise ValueError("PNG lacks IHDR/IDAT data")
    pixels = _png_unfilter(width, height, bpp, zlib.decompress(bytes(idat)))
    counts: Counter[tuple[int, int, int]] = Counter()
    stride = width * bpp
    step = 2
    for y in range(0, height, step):
        row = y * stride
        for x in range(0, width, step):
            offset = row + x * bpp
            counts[
                (
                    pixels[offset] >> 4,
                    pixels[offset + 1] >> 4,
                    pixels[offset + 2] >> 4,
                )
            ] += 1
    sampled = sum(counts.values())
    top_share = counts.most_common(1)[0][1] / sampled if sampled else 1.0
    return {
        "width": width,
        "height": height,
        "sampled_pixels": sampled,
        "non_background_fraction": round(1.0 - top_share, 6),
        "distinct_quantized_colors": len(counts),
    }


def render_smoke(html_path: Path) -> dict[str, Any]:
    """Load the map in a headless browser and verify it actually draws.

    Returns status "pass", "fail", or "skipped_no_browser". A skipped result
    means no Chromium-family browser was found; the map then REQUIRES manual
    visual confirmation before delivery and must not be treated as validated.
    """
    html_source = html_path.read_text(encoding="utf-8", errors="replace")
    banner_required = REPORTED_MODE_MARKER in html_source
    report: dict[str, Any] = {
        "html": str(html_path),
        "banner_required": banner_required,
        "banner_in_source": BANNER_MARKER in html_source,
    }
    browser = find_headless_browser()
    if browser is None:
        report.update(
            {
                "status": "skipped_no_browser",
                "browser": None,
                "action_required": (
                    "no headless Chromium-family browser was found; open the map "
                    "manually, confirm visible sample graphics and the absence of "
                    "console errors, and record that confirmation - do not deliver "
                    "an unreviewed map"
                ),
            }
        )
        return report
    report["browser"] = browser
    target = html_path.resolve().as_uri()
    reasons: list[str] = []
    try:
        dom_rc, dom, dom_stderr = _browser_run(browser, ["--dump-dom"], target)
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "render.png"
            shot_rc, _, shot_stderr = _browser_run(
                browser, [f"--screenshot={shot}"], target
            )
            screenshot: dict[str, Any]
            if shot_rc == 0 and shot.is_file():
                try:
                    screenshot = png_paint_statistics(shot.read_bytes())
                except (ValueError, zlib.error) as exc:
                    screenshot = {"error": f"screenshot decode failed: {exc}"}
            else:
                screenshot = {"error": f"screenshot capture failed (rc={shot_rc})"}
    except (OSError, subprocess.TimeoutExpired) as exc:
        report.update(
            {"status": "fail", "reasons": [f"headless browser did not complete: {exc}"]}
        )
        return report
    uncaught = _console_uncaught_lines(dom_stderr) + _console_uncaught_lines(
        shot_stderr
    )
    svg_graphics = len(SVG_GRAPHIC_PATTERN.findall(dom))
    canvas_elements = len(CANVAS_PATTERN.findall(dom))
    attest_match = ATTEST_PATTERN.search(dom)
    attest: dict[str, Any] | None = None
    if attest_match:
        try:
            attest = json.loads(
                attest_match.group(1).replace("&quot;", '"').replace("&amp;", "&")
            )
        except json.JSONDecodeError:
            attest = None
    painted = bool(
        not screenshot.get("error")
        and screenshot.get("non_background_fraction", 0.0) >= MIN_PAINTED_FRACTION
        and screenshot.get("distinct_quantized_colors", 0) >= MIN_DISTINCT_COLORS
    )
    attest_symbols = int(attest.get("symbols", 0)) if isinstance(attest, dict) else 0
    banner_present = BANNER_MARKER in dom
    if dom_rc != 0:
        reasons.append(f"headless DOM dump failed (rc={dom_rc})")
    if uncaught:
        reasons.append("console reported uncaught errors")
    visible_graphics = (
        svg_graphics > 0 or attest_symbols > 0 or (canvas_elements > 0 and painted)
    )
    if not visible_graphics:
        reasons.append(
            "no visible graphic elements: 0 SVG shapes, no render attestation, "
            "and the canvas screenshot shows no painted content"
        )
    if banner_required and not banner_present:
        reasons.append(
            "reported-coordinate map is missing its unverified-datum warning banner"
        )
    report.update(
        {
            "status": "pass" if not reasons else "fail",
            "dom": {
                "svg_graphic_elements": svg_graphics,
                "canvas_elements": canvas_elements,
                "render_attest": attest,
                "banner_present": banner_present,
            },
            "screenshot": screenshot,
            "console_uncaught_errors": uncaught[:5],
            "reasons": reasons,
        }
    )
    return report


def validate_dir(output_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    required_names = (*renderer.REQUIRED_INPUTS, *renderer.GENERATED_OUTPUTS)
    paths = {name: output_dir / name for name in required_names}
    for name, path in paths.items():
        if not path.is_file():
            errors.append(f"missing required D3 output: {name}")
        elif path.stat().st_size == 0:
            errors.append(f"required D3 output is empty: {name}")
        elif path.stat().st_size > MAX_OUTPUT_BYTES:
            errors.append(f"D3 output exceeds the 100 MB runtime safety limit: {name}")
    if errors:
        return {
            "status": "invalid",
            "errors": errors,
            "warnings": warnings,
            "metrics": {},
        }

    database_metrics = workflow_validator.validate_database(
        paths["geochemistry.csv"], errors, warnings
    )
    canonical_ids = set(
        workflow_validator.database_evidence_index(paths["geochemistry.csv"])
    )
    iteration_count = workflow_validator.validate_iteration_backlog(
        paths["iteration_backlog.csv"], canonical_ids, errors
    )
    parsed: dict[str, Any] = {}
    for name in (
        "anomalies.geojson",
        "samples.geojson",
        "confidence_report.json",
        "source_manifest.json",
        "anomaly_report.json",
        "visualization_profile.json",
        "visualization_report.json",
    ):
        try:
            parsed[name] = workflow_validator.strict_json(paths[name])
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{name} is invalid JSON: {exc}")

    anomaly_count = 0
    sample_count = 0
    sample_record_ids: set[str] = set()
    if "anomalies.geojson" in parsed:
        anomaly_count = workflow_validator.validate_feature_collection(
            parsed["anomalies.geojson"],
            "anomalies.geojson",
            errors,
            allow_null_geometry=True,
            require_candidate_status=True,
        )
    if "samples.geojson" in parsed:
        sample_count = workflow_validator.validate_feature_collection(
            parsed["samples.geojson"],
            "samples.geojson",
            errors,
            allow_null_geometry=False,
        )
        sample_record_ids = {
            str(feature.get("properties", {}).get("record_id"))
            for feature in parsed["samples.geojson"].get("features", [])
            if feature.get("properties", {}).get("record_id") is not None
        }
    scoped_anomaly_count = 0
    if "anomalies.geojson" in parsed:
        scoped_anomaly_count = sum(
            str(feature.get("properties", {}).get("record_id")) in sample_record_ids
            for feature in parsed["anomalies.geojson"].get("features", [])
            if feature.get("properties", {}).get("record_id") is not None
        )
    if sample_count > database_metrics["record_count"]:
        errors.append(
            "samples.geojson contains more features than geochemistry.csv records"
        )
    workflow_validator.validate_html(paths["interactive_map.html"], errors)

    profile = parsed.get("visualization_profile.json")
    if isinstance(profile, dict):
        try:
            validated_profile = map_builder.load_visualization_profile(
                paths["visualization_profile.json"]
            )
        except map_builder.MapBuildError as exc:
            errors.append(
                f"visualization_profile.json violates the D3 profile contract: {exc}"
            )
        else:
            if validated_profile != profile:
                errors.append("visualization_profile.json is not in canonical D3 form")
    else:
        errors.append("visualization_profile.json must contain an object")

    report = parsed.get("visualization_report.json")
    if not isinstance(report, dict):
        errors.append("visualization_report.json must contain an object")
    else:
        if report.get("interface_version") != renderer.INTERFACE_VERSION:
            errors.append(
                "visualization_report.json has an unsupported interface_version"
            )
        if report.get("status") != "success":
            errors.append("visualization_report.json does not report success")
        if report.get("profile") != profile:
            errors.append(
                "visualization_report.json profile differs from visualization_profile.json"
            )
        if not isinstance(report.get("profile_warnings"), list):
            errors.append("visualization_report.json profile_warnings must be an array")
        expected_outputs = {
            "interactive_map": "interactive_map.html",
            "samples": "samples.geojson",
            "profile": "visualization_profile.json",
            "iteration_backlog": "iteration_backlog.csv",
        }
        if isinstance(profile, dict) and profile.get("story") == "comparison":
            expected_outputs["element_comparison"] = "element_comparison.json"
            comparison_path = output_dir / "element_comparison.json"
            if not comparison_path.is_file() or comparison_path.stat().st_size == 0:
                errors.append(
                    "comparison visualization is missing element_comparison.json"
                )
            else:
                try:
                    comparison = workflow_validator.strict_json(comparison_path)
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    errors.append(f"element_comparison.json is invalid JSON: {exc}")
                else:
                    if (
                        comparison.get("comparison_version")
                        != "d3-element-comparison-v1"
                    ):
                        errors.append(
                            "element_comparison.json has an unsupported version"
                        )
                    expected_elements = {
                        "x": profile.get("comparison", {}).get("x"),
                        "y": profile.get("comparison", {}).get("y"),
                    }
                    if comparison.get("elements") != expected_elements:
                        errors.append(
                            "element_comparison.json elements differ from the profile"
                        )
                    pairs = comparison.get("paired_records")
                    coverage = comparison.get("coverage")
                    statistics = comparison.get("statistics")
                    if not isinstance(pairs, list) or not isinstance(coverage, dict):
                        errors.append(
                            "element_comparison.json lacks pair and coverage arrays"
                        )
                    elif coverage.get("paired_sample_layer_count") != len(pairs):
                        errors.append(
                            "element_comparison.json pair count is inconsistent"
                        )
                    elif comparison.get("status") != (
                        "success" if len(pairs) >= 8 else "insufficient_pairs"
                    ):
                        errors.append(
                            "element_comparison.json status violates the eight-pair gate"
                        )
                    if (
                        isinstance(pairs, list)
                        and len(pairs) < 8
                        and isinstance(statistics, dict)
                        and statistics.get("spearman_rho") is not None
                    ):
                        errors.append(
                            "element_comparison.json reports Spearman below eight pairs"
                        )
                    if comparison.get("input_sha256") != workflow_validator.sha256_file(
                        paths["geochemistry.csv"]
                    ):
                        errors.append(
                            "element_comparison.json input hash differs from geochemistry.csv"
                        )
                    if report.get("element_comparison") != comparison:
                        errors.append(
                            "visualization_report.json comparison differs from its artifact"
                        )
        if isinstance(profile, dict) and profile.get("filters", {}).get("element"):
            expected_outputs["concentration_grid"] = "concentration_grid.geojson"
            grid_path = output_dir / "concentration_grid.geojson"
            if not grid_path.is_file() or grid_path.stat().st_size == 0:
                errors.append(
                    "element-filtered visualization is missing concentration_grid.geojson"
                )
            else:
                try:
                    grid = workflow_validator.strict_json(grid_path)
                except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                    errors.append(f"concentration_grid.geojson is invalid JSON: {exc}")
                else:
                    if (
                        grid.get("type") != "FeatureCollection"
                        or grid.get("grid_version")
                        != "d3-observed-concentration-grid-v1"
                        or grid.get("element")
                        != profile.get("filters", {}).get("element")
                        or grid.get("interpolation") is not False
                        or grid.get("feature_count") != len(grid.get("features", []))
                    ):
                        errors.append(
                            "concentration_grid.geojson violates its observed-cell contract"
                        )
                    if grid.get("input_sha256") != workflow_validator.sha256_file(
                        paths["geochemistry.csv"]
                    ):
                        errors.append(
                            "concentration_grid.geojson input hash differs from geochemistry.csv"
                        )
                    for feature in grid.get("features", []):
                        properties = (
                            feature.get("properties", {})
                            if isinstance(feature, dict)
                            else {}
                        )
                        count_fields = (
                            properties.get("quantified_count"),
                            properties.get("censored_count"),
                            properties.get("unquantified_count"),
                        )
                        valid_counts = all(
                            isinstance(value, int)
                            and not isinstance(value, bool)
                            and value >= 0
                            for value in count_fields
                        )
                        if not valid_counts or sum(
                            cast(int, value) for value in count_fields
                        ) != properties.get("record_count"):
                            errors.append(
                                "concentration grid feature counts do not reconcile"
                            )
                    summary = report.get("concentration_grid_summary", {})
                    if (
                        summary.get("grid_version") != grid.get("grid_version")
                        or summary.get("element") != grid.get("element")
                        or summary.get("feature_count") != grid.get("feature_count")
                        or summary.get("interpolation") is not False
                    ):
                        errors.append(
                            "visualization_report.json concentration summary differs from its artifact"
                        )
        if report.get("outputs") != expected_outputs:
            errors.append(
                "visualization_report.json outputs do not match the D3 contract"
            )
        for name, expected_hash in report.get("inputs", {}).items():
            if name not in renderer.REQUIRED_INPUTS:
                errors.append(
                    f"visualization_report.json contains an unknown input hash: {name}"
                )
            elif expected_hash != workflow_validator.sha256_file(paths[name]):
                errors.append(
                    f"visualization_report.json input hash differs for {name}"
                )
        if set(report.get("inputs", {})) != set(renderer.REQUIRED_INPUTS):
            errors.append(
                "visualization_report.json does not hash every required D1/D2 input"
            )
        output_hashes = report.get("output_sha256")
        if not isinstance(output_hashes, dict):
            errors.append("visualization_report.json output_sha256 must be an object")
        else:
            for name in expected_outputs.values():
                if output_hashes.get(name) != workflow_validator.sha256_file(
                    output_dir / name
                ):
                    errors.append(
                        f"visualization_report.json output hash differs for {name}"
                    )
        map_report = report.get("map_report")
        if not isinstance(map_report, dict):
            errors.append("visualization_report.json map_report must be an object")
        else:
            if map_report.get("map_version") != "d3-interactive-atlas-v3":
                errors.append("visualization map_version is unsupported")
            if (
                map_report.get("ui_hierarchy_version")
                != "atlas-progressive-disclosure-v2"
            ):
                errors.append("visualization UI hierarchy contract is unsupported")
            if (
                map_report.get("template_contract_version")
                != map_builder.TEMPLATE_CONTRACT_VERSION
            ):
                errors.append("visualization template contract is unsupported")
            expected_template_hash = workflow_validator.sha256_file(
                map_builder.DEFAULT_TEMPLATE
            )
            if map_report.get("template_sha256") != expected_template_hash:
                errors.append(
                    "visualization template hash differs from the canonical Skill asset"
                )
            expected_variant = (
                "regional_focus"
                if isinstance(profile, dict)
                and profile.get("spatial_scope") == "regional"
                else "global_globe"
            )
            if map_report.get("template_variant") != expected_variant:
                errors.append(
                    "visualization template variant does not match the spatial scope"
                )
            if (
                map_report.get("database_visual_summary_schema")
                != "d3-database-visual-summary-v1"
            ):
                errors.append("visualization database summary contract is unsupported")
            if map_report.get("terminology_contract") != "competition-geochemistry-v1":
                errors.append(
                    "visualization professional terminology contract is unsupported"
                )
            interaction_design = map_report.get("capability_matrix", {}).get(
                "interaction_design", {}
            )
            required_interactions = (
                "professional_navigation_labels",
                "combination_region_selector",
                "combination_custom_bbox",
                "regional_combination_scope_lock_supported",
                "comparison_profile_export",
                "formal_comparison_requires_profile_rerender",
            )
            for capability in required_interactions:
                if interaction_design.get(capability) is not True:
                    errors.append(
                        "visualization interaction contract is missing required capability: "
                        + capability
                    )
            if (
                interaction_design.get("template_contract_version")
                != map_builder.TEMPLATE_CONTRACT_VERSION
            ):
                errors.append(
                    "visualization interaction template contract is unsupported"
                )
            output_capabilities = map_report.get("capability_matrix", {}).get(
                "outputs", {}
            )
            for capability in (
                "concentration_classified_points",
                "database_distribution_charts",
                "anomaly_candidate_density_surface",
            ):
                if output_capabilities.get(capability) is not True:
                    errors.append(
                        "visualization output contract is missing required capability: "
                        + capability
                    )
            if (
                expected_variant == "global_globe"
                and output_capabilities.get("global_interactive_globe") is not True
            ):
                errors.append(
                    "global visualization does not declare the interactive globe"
                )
            question_contract = map_report.get("visual_question_contract")
            expected_views = {
                "map",
                "database",
                "combination",
                "sources",
                "anomalies",
                "quality",
            }
            if (
                not isinstance(question_contract, dict)
                or question_contract.get("schema_version")
                != "d3-visual-question-contract-v1"
            ):
                errors.append(
                    "visualization visual-question contract is missing or unsupported"
                )
            elif set(question_contract.get("views", {})) != expected_views:
                errors.append(
                    "visualization visual-question contract does not cover every primary view"
                )
            else:
                for view_name, view_contract in question_contract["views"].items():
                    if not isinstance(view_contract, dict) or set(view_contract) != {
                        "question",
                        "comparison_baseline",
                        "encoding",
                        "boundary",
                    }:
                        errors.append(
                            f"visualization question contract is malformed for {view_name}"
                        )
                    elif (
                        not view_contract["question"]
                        or not view_contract["comparison_baseline"]
                        or not view_contract["encoding"]
                        or not view_contract["boundary"]
                    ):
                        errors.append(
                            f"visualization question contract is incomplete for {view_name}"
                        )
            if (
                map_report.get("external_assets") != 0
                or map_report.get("interpolation") is not False
            ):
                errors.append(
                    "visualization report violates the offline/no-interpolation boundary"
                )
            if map_report.get("mapped_record_count") != sample_count:
                errors.append(
                    "visualization mapped_record_count differs from samples.geojson"
                )
            if map_report.get("candidate_record_count") != scoped_anomaly_count:
                errors.append(
                    "visualization candidate_record_count differs from the anomalies linked "
                    "to scoped samples.geojson records"
                )
            if map_report.get("visualization_profile") != profile:
                errors.append(
                    "map_report profile differs from visualization_profile.json"
                )
            if map_report.get("visualization_profile_warnings") != report.get(
                "profile_warnings"
            ):
                errors.append(
                    "map_report warnings differ from visualization_report.json"
                )

    evidence_path = output_dir / "record_evidence.jsonl"
    evidence_count = 0
    if evidence_path.is_file():
        evidence_count = workflow_validator.validate_record_evidence(
            evidence_path,
            workflow_validator.database_evidence_index(paths["geochemistry.csv"]),
            errors,
        )
    else:
        warnings.append(
            "record_evidence.jsonl was not present in the D1/D2 input and was not carried into D3"
        )

    if isinstance(report, dict):
        map_report = report.get("map_report")
        if (
            isinstance(map_report, dict)
            and map_report.get("coordinate_mode") == "reported"
            and map_report.get("reported_coordinate_banner")
        ):
            html_source = paths["interactive_map.html"].read_text(
                encoding="utf-8", errors="replace"
            )
            if BANNER_MARKER not in html_source:
                errors.append(
                    "reported-coordinate map lost its unverified-datum warning banner"
                )

    smoke = render_smoke(paths["interactive_map.html"])
    if smoke["status"] == "fail":
        errors.append(
            "interactive_map.html failed the headless render smoke test: "
            + "; ".join(smoke.get("reasons", []))
        )
    elif smoke["status"] == "skipped_no_browser":
        warnings.append(
            "render smoke test skipped: no headless browser found; the map "
            "REQUIRES manual visual confirmation before delivery"
        )

    if errors:
        status = "invalid"
    elif smoke["status"] == "skipped_no_browser":
        status = "needs_render_confirmation"
    else:
        status = "valid"
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "render_smoke": smoke,
        "metrics": {
            **database_metrics,
            "record_evidence_count": evidence_count,
            "sample_feature_count": sample_count,
            "source_candidate_feature_count": anomaly_count,
            "scoped_candidate_feature_count": scoped_anomaly_count,
            "iteration_backlog_count": iteration_count,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--output-dir", type=Path, help="Standalone D3 bundle to validate in full"
    )
    target.add_argument(
        "--html",
        type=Path,
        help="Single interactive_map.html to render-smoke-test in isolation",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.html is not None:
            smoke = render_smoke(args.html)
            status = {
                "pass": "valid",
                "fail": "invalid",
                "skipped_no_browser": "needs_render_confirmation",
            }[smoke["status"]]
            report: dict[str, Any] = {
                "status": status,
                "errors": smoke.get("reasons", []) if status == "invalid" else [],
                "warnings": (
                    [smoke["action_required"]]
                    if status == "needs_render_confirmation"
                    else []
                ),
                "render_smoke": smoke,
                "metrics": {},
            }
        else:
            report = validate_dir(args.output_dir)
    except OSError as exc:
        report = {
            "status": "invalid",
            "errors": [str(exc)],
            "warnings": [],
            "metrics": {},
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if report["status"] == "valid":
        return 0
    if report["status"] == "needs_render_confirmation":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
