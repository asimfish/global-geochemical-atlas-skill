#!/usr/bin/env python3
"""Deterministic print-readiness lint for publication artifacts.

The controller runs these checks when a manuscript or figure result is
submitted: an artifact that would be unreadable or structurally broken in the
typeset paper is rejected at the gate instead of surviving on an executor's
self-attested render inspection. Checks are stdlib-only and deterministic so
identical artifacts always lint identically.

Scope is deliberately a floor, not a style guide: well-formedness, a
print-equivalent font-size floor for vector text, a print-quality width floor
for raster renders, and page-bearing structure for PDFs. Aesthetic judgement
stays with the render-inspect-revise loop and the independent reviewer's a6
gate.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ElementTree
from pathlib import Path

# Print-equivalent scaling reference: a full-width figure in a US-letter
# single-column layout spans roughly 468 pt of text width, so effective
# print size = declared size x (468 / canvas width in user units).
PRINT_COLUMN_WIDTH_PT = 468.0
# Text below this print-equivalent size is unreadable on paper.
MIN_PRINT_FONT_PT = 4.5
# Raster renders narrower than this cannot reach print quality at column width.
MIN_RASTER_WIDTH_PX = 1000

_FONT_SIZE_STYLE = re.compile(r"font-size\s*:\s*([0-9.]+)")
_NUMBER = re.compile(r"[0-9.]+")
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _declared_font_size(element: ElementTree.Element) -> float | None:
    declared = element.get("font-size")
    if declared is None:
        style = element.get("style") or ""
        match = _FONT_SIZE_STYLE.search(style)
        declared = match.group(1) if match else None
    if declared is None:
        return None
    match = _NUMBER.search(declared)
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _svg_canvas_width(root: ElementTree.Element) -> float | None:
    view_box = root.get("viewBox")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            try:
                width = float(parts[2])
            except ValueError:
                width = 0.0
            if width > 0:
                return width
    declared = root.get("width")
    if declared:
        match = _NUMBER.search(declared)
        if match:
            try:
                width = float(match.group(0))
            except ValueError:
                width = 0.0
            if width > 0:
                return width
    return None


def lint_svg_bytes(data: bytes) -> list[str]:
    """Font-floor lint for vector figures.

    Walks the element tree with inherited font sizes; every element that
    carries visible text is checked against the print-equivalent floor. Text
    converted to paths carries no size declaration and is skipped, as are
    scale transforms: this is a floor for the common failure mode (tiny
    axis and annotation text), not a full layout engine.
    """
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as exc:
        return [f"SVG is not well-formed XML: {exc}"]
    if _local_name(root.tag) != "svg":
        return ["file does not contain a root <svg> element"]
    width = _svg_canvas_width(root)
    errors: list[str] = []
    if width is None:
        return errors
    scale = PRINT_COLUMN_WIDTH_PT / width

    def walk(element: ElementTree.Element, inherited: float | None) -> None:
        size = _declared_font_size(element)
        effective = size if size is not None else inherited
        has_text = bool((element.text or "").strip())
        if has_text and effective is not None:
            print_pt = effective * scale
            if print_pt < MIN_PRINT_FONT_PT:
                errors.append(
                    f"text {(element.text or '').strip()[:40]!r} renders at "
                    f"{print_pt:.2f} pt print-equivalent, below the "
                    f"{MIN_PRINT_FONT_PT} pt floor"
                )
        for child in element:
            walk(child, effective)

    walk(root, None)
    return errors


def lint_png_bytes(data: bytes) -> list[str]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return ["PNG signature is missing or the file is truncated"]
    if data[12:16] != b"IHDR":
        return ["PNG lacks a leading IHDR chunk"]
    width, height = struct.unpack(">II", data[16:24])
    errors: list[str] = []
    if width < MIN_RASTER_WIDTH_PX:
        errors.append(
            f"raster render is {width} px wide, below the "
            f"{MIN_RASTER_WIDTH_PX} px print-quality floor"
        )
    if height == 0:
        errors.append("raster render has zero height")
    return errors


def lint_pdf_bytes(data: bytes) -> list[str]:
    if not data.startswith(b"%PDF-"):
        return ["PDF header is missing"]
    errors: list[str] = []
    if _PDF_PAGE.search(data) is None:
        errors.append("PDF declares no page object")
    if b"%%EOF" not in data:
        errors.append("PDF end-of-file marker is missing")
    return errors


_LINTERS = {
    ".svg": lint_svg_bytes,
    ".png": lint_png_bytes,
    ".pdf": lint_pdf_bytes,
}


def lint_publication_artifact(path: Path) -> list[str]:
    """Lint one artifact by suffix; unknown suffixes carry no print checks."""
    linter = _LINTERS.get(path.suffix.lower())
    if linter is None:
        return []
    return [f"{path.name}: {message}" for message in linter(path.read_bytes())]
