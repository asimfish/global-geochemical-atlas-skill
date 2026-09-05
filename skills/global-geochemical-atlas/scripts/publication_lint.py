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
import zlib
from pathlib import Path

# Print-equivalent scaling reference: a full-width figure in a US-letter
# single-column layout spans roughly 468 pt of text width, so effective
# print size = declared size x (468 / canvas width in user units).
PRINT_COLUMN_WIDTH_PT = 468.0
# Text below this print-equivalent size is unreadable on paper.
MIN_PRINT_FONT_PT = 4.5
# Raster renders narrower than this cannot reach print quality at column width.
MIN_RASTER_WIDTH_PX = 1000
# SVG initial font-size ("medium") in user units when no size is declared.
SVG_DEFAULT_FONT_SIZE = 16.0
# Text runs longer than this inside a figure are captions or disclaimers in
# disguise; they belong in the manuscript.
MAX_TEXT_RUN_CHARS = 120
# Renders must share the SVG's aspect ratio; larger deviations mean clipping.
ASPECT_TOLERANCE = 0.02

_FONT_SIZE_STYLE = re.compile(r"font-size\s*:\s*([0-9.]+)")
_NUMBER = re.compile(r"[0-9.]+")
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")
_PDF_MEDIABOX = re.compile(rb"/MediaBox\s*\[\s*([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s*\]")
_PDF_STREAM = re.compile(rb"stream\r?\n")
# Object-stream dictionaries are short; the header scan stays local to avoid
# mistaking a preceding object's dictionary for the stream's own.
_PDF_STREAM_HEADER_WINDOW = 300


def pdf_searchable_bytes(data: bytes) -> bytes:
    """The PDF bytes plus the inflated content of every object stream.

    pdfTeX, dvipdfmx and other PDF 1.5 writers pack page and other object
    dictionaries into Flate-compressed ``/ObjStm`` streams, so ``/Type /Page``
    and ``/MediaBox`` never appear in the raw file. Searching the inflated
    object streams as well keeps the byte-level checks valid for TeX output
    without needing poppler.
    """
    chunks = [data]
    for match in _PDF_STREAM.finditer(data):
        header = data[max(0, match.start() - _PDF_STREAM_HEADER_WINDOW) : match.start()]
        dictionary_start = header.rfind(b"<<")
        if dictionary_start < 0:
            continue
        header = header[dictionary_start:]
        if b"/ObjStm" not in header or b"/FlateDecode" not in header:
            continue
        end = data.find(b"endstream", match.end())
        if end < 0:
            continue
        payload = data[match.end() : end]
        try:
            chunks.append(zlib.decompress(payload))
        except zlib.error:
            try:
                chunks.append(zlib.decompressobj().decompress(payload))
            except zlib.error:
                continue
    return b"\n".join(chunks)


def pdf_page_count(data: bytes) -> int:
    """Number of page objects, including those packed into object streams."""
    return len(_PDF_PAGE.findall(pdf_searchable_bytes(data)))


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
    class_sizes = _stylesheet_font_sizes(root)

    def walk(element: ElementTree.Element, inherited: float | None) -> None:
        size = _declared_font_size(element)
        if size is None:
            for class_name in (element.get("class") or "").split():
                if class_name in class_sizes:
                    size = class_sizes[class_name]
                    break
        effective = size if size is not None else inherited
        text = (element.text or "").strip()
        has_text = bool(text) and _local_name(element.tag) in {"text", "tspan"}
        if has_text:
            # SVG's initial font-size is "medium" = 16 user units when nothing
            # declares one; treat it as such instead of skipping the check.
            print_pt = (effective if effective is not None else SVG_DEFAULT_FONT_SIZE) * scale
            if print_pt < MIN_PRINT_FONT_PT:
                errors.append(
                    f"text {text[:40]!r} renders at "
                    f"{print_pt:.2f} pt print-equivalent, below the "
                    f"{MIN_PRINT_FONT_PT} pt floor"
                )
            if len(text) > MAX_TEXT_RUN_CHARS:
                errors.append(
                    f"text run of {len(text)} characters ({text[:40]!r}...) reads like a "
                    "caption or disclaimer; such prose belongs in the manuscript caption, "
                    "not inside the figure"
                )
        for child in element:
            walk(child, effective)

    walk(root, None)
    return errors


def _stylesheet_font_sizes(root: ElementTree.Element) -> dict[str, float]:
    """font-size declared per CSS class inside <style> blocks (px/pt/unitless)."""
    sizes: dict[str, float] = {}
    for element in root.iter():
        if _local_name(element.tag) != "style":
            continue
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", element.text or ""):
            match = _FONT_SIZE_STYLE.search(body)
            if match is None:
                continue
            try:
                size = float(match.group(1))
            except ValueError:
                continue
            for part in selector.split(","):
                part = part.strip()
                if part.startswith("."):
                    sizes[part[1:].split(":")[0]] = size
    return sizes


def svg_aspect(data: bytes) -> float | None:
    """viewBox (or width/height) aspect ratio of an SVG document."""
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return None
    view_box = root.get("viewBox")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            try:
                width, height = float(parts[2]), float(parts[3])
            except ValueError:
                return None
            return width / height if height > 0 else None
    try:
        width = float(_NUMBER.search(root.get("width") or "").group(0))
        height = float(_NUMBER.search(root.get("height") or "").group(0))
    except (AttributeError, ValueError):
        return None
    return width / height if height > 0 else None


def pdf_aspect(data: bytes) -> float | None:
    match = _PDF_MEDIABOX.search(pdf_searchable_bytes(data))
    if match is None:
        return None
    x0, y0, x1, y1 = (float(value) for value in match.groups())
    width, height = abs(x1 - x0), abs(y1 - y0)
    return width / height if height > 0 else None


def png_aspect(data: bytes) -> float | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width / height if height > 0 else None


def svg_has_basemap(data: bytes) -> bool:
    return b'data-gga-layer="basemap"' in data or b"data-gga-layer='basemap'" in data


def lint_figure_renders(
    svg_path: Path, pdf_path: Path, png_path: Path, *, requires_basemap: bool = False
) -> list[str]:
    """Cross-format checks for one figure: identical aspect, geographic frame."""
    errors: list[str] = []
    svg_data = svg_path.read_bytes()
    reference = svg_aspect(svg_data)
    if reference is None:
        return [f"{svg_path.name}: SVG declares no usable viewBox or size"]
    for label, aspect in (("PDF", pdf_aspect(pdf_path.read_bytes())), ("PNG", png_aspect(png_path.read_bytes()))):
        if aspect is None:
            errors.append(f"{svg_path.name}: {label} render has no readable page or pixel box")
        elif abs(aspect - reference) / reference > ASPECT_TOLERANCE:
            errors.append(
                f"{svg_path.name}: {label} render aspect {aspect:.3f} differs from the SVG "
                f"aspect {reference:.3f}; the export is clipped or letter-boxed"
            )
    if requires_basemap and not svg_has_basemap(svg_data):
        errors.append(
            f"{svg_path.name}: a spatial figure must draw the offline coastline/boundary "
            'basemap (group tagged data-gga-layer="basemap")'
        )
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
    if pdf_page_count(data) == 0:
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
