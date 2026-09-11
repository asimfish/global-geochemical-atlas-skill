#!/usr/bin/env python3
"""Export a figure SVG to a same-size vector PDF and a print-resolution PNG.

Contract ``gga-figure-kit-v1``.  The page box of the PDF and the pixel box of
the PNG are derived from the SVG's own width/height (mm) so nothing is clipped
or letter-boxed -- the publication lint later compares the PDF MediaBox and
PNG aspect ratios against the SVG viewBox and rejects mismatches.

Backends, in order: headless Chrome/Chromium (present on the reference
machine), rsvg-convert, inkscape, cairosvg.  When none is available the script
exits 3 with a clear message instead of producing a fake render.

Usage:
    python scripts/render_figure.py --svg fig1.svg [--pdf fig1.pdf] [--png fig1.png] [--scale 3]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

CONTRACT_ID = "gga-figure-kit-v1"
MM_PER_INCH = 25.4
CSS_PX_PER_INCH = 96.0
PT_PER_INCH = 72.0
ASPECT_TOLERANCE = 0.02


class RenderError(RuntimeError):
    pass


def svg_size_mm(svg_text: str) -> tuple[float, float]:
    """Physical size from width/height (mm/cm/in/pt/px) or from the viewBox in pt."""
    root = re.search(r"<svg\b[^>]*>", svg_text, re.S)
    if root is None:
        raise RenderError("not an SVG document")
    attrs = root.group(0)

    def dim(name: str) -> float | None:
        match = re.search(rf'\b{name}="([0-9.]+)\s*([a-z%]*)"', attrs)
        if match is None:
            return None
        value, unit = float(match.group(1)), match.group(2)
        factor = {
            "mm": 1.0,
            "cm": 10.0,
            "in": MM_PER_INCH,
            "pt": MM_PER_INCH / PT_PER_INCH,
            "px": MM_PER_INCH / CSS_PX_PER_INCH,
            "": MM_PER_INCH / CSS_PX_PER_INCH,
        }
        if unit not in factor:
            return None
        return value * factor[unit]

    width, height = dim("width"), dim("height")
    if width and height:
        return width, height
    view_box = re.search(r'viewBox="([^"]+)"', attrs)
    if view_box is None:
        raise RenderError("SVG declares neither physical size nor viewBox")
    parts = view_box.group(1).replace(",", " ").split()
    vb_w, vb_h = float(parts[2]), float(parts[3])
    return vb_w * MM_PER_INCH / PT_PER_INCH, vb_h * MM_PER_INCH / PT_PER_INCH


def wrapper_html(svg_text: str, width_mm: float, height_mm: float) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"@page{{size:{width_mm:.4f}mm {height_mm:.4f}mm;margin:0}}"
        f"html,body{{margin:0;padding:0;width:{width_mm:.4f}mm;height:{height_mm:.4f}mm;overflow:hidden;background:#fff}}"
        f"svg{{display:block;width:{width_mm:.4f}mm;height:{height_mm:.4f}mm}}"
        "</style></head><body>" + svg_text + "</body></html>"
    )


BROWSER_ENV = "GGA_HEADLESS_BROWSER"


def find_chrome() -> str | None:
    """Locate a Chromium-family browser; GGA_HEADLESS_BROWSER overrides discovery.

    An empty override disables the browser backend (used by tests to exercise
    the no-renderer exit path); a non-empty one names the binary to use.
    """
    override = os.environ.get(BROWSER_ENV)
    if override is not None:
        if override.strip() == "":
            return None
        return (
            override if (shutil.which(override) or os.path.exists(override)) else None
        )
    for name in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ):
        path = shutil.which(name)
        if path:
            return path
    mac = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac if os.path.exists(mac) else None


def run(command: list[str], timeout: int = 180) -> None:
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False
    )
    if completed.returncode != 0:
        raise RenderError(
            f"{command[0]} failed ({completed.returncode}): {completed.stderr[-400:]}"
        )


def run_until_output(command: list[str], output: Path, timeout: int = 120) -> None:
    """Run a browser export and stop as soon as the output file is complete.

    Headless Chrome sometimes keeps running after it has written the file, so
    waiting for process exit is not reliable; the file being present and
    byte-stable for a second is the completion signal.
    """
    import time

    if output.exists():
        output.unlink()
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    deadline = time.monotonic() + timeout
    last_size, stable_since = -1, None
    try:
        while time.monotonic() < deadline:
            if output.exists():
                size = output.stat().st_size
                if size > 0 and size == last_size:
                    if (
                        stable_since is not None
                        and time.monotonic() - stable_since >= 1.0
                    ):
                        return
                else:
                    last_size, stable_since = size, time.monotonic()
            if process.poll() is not None:
                if output.exists() and output.stat().st_size > 0:
                    return
                stderr = (
                    process.stderr.read().decode("utf-8", "replace")
                    if process.stderr
                    else ""
                )
                raise RenderError(
                    f"{command[0]} exited {process.returncode} without output: {stderr[-400:]}"
                )
            time.sleep(0.2)
        raise RenderError(f"{command[0]} produced no output within {timeout}s")
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, 9)
            except (ProcessLookupError, PermissionError):
                process.kill()
            process.wait(timeout=10)


# Headless Chrome (new mode) lays the page out in a viewport shorter than
# --window-size by its hidden UI strip (87 px in Chrome 142) but still emits a
# screenshot of the full window, so the bottom of a same-size screenshot is
# blank. Screenshots are therefore taken taller and cropped to the figure box.
HEADLESS_UI_ALLOWANCE_PX = 160


def export_with_chrome(
    chrome: str,
    svg_text: str,
    width_mm: float,
    height_mm: float,
    pdf: Path | None,
    png: Path | None,
    scale: int,
) -> str:
    """Export via Chrome; returns the PNG backend actually used ("" when no PNG)."""
    png_backend = ""
    with tempfile.TemporaryDirectory() as temp:
        html = Path(temp) / "figure.html"
        html.write_text(wrapper_html(svg_text, width_mm, height_mm), encoding="utf-8")
        common = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            f"--user-data-dir={Path(temp) / 'profile'}",
        ]
        # The PDF page box comes from @page, so it is exact; the PNG is best
        # rasterised from that page (poppler) rather than screenshotted.
        pdf_target = (
            pdf
            if pdf is not None
            else (
                Path(temp) / "figure.pdf"
                if png is not None and shutil.which("pdftoppm")
                else None
            )
        )
        if pdf_target is not None:
            run_until_output(
                common
                + [
                    "--no-pdf-header-footer",
                    "--print-to-pdf-no-header",
                    f"--print-to-pdf={pdf_target}",
                    html.as_uri(),
                ],
                pdf_target,
            )
        if png is not None:
            if pdf_target is not None and shutil.which("pdftoppm"):
                rasterize_pdf_with_poppler(
                    pdf_target, png, dpi=round(CSS_PX_PER_INCH * scale)
                )
                png_backend = "chrome-pdf+pdftoppm"
            else:
                css_w = round(width_mm / MM_PER_INCH * CSS_PX_PER_INCH)
                css_h = round(height_mm / MM_PER_INCH * CSS_PX_PER_INCH)
                shot = Path(temp) / "shot.png"
                run_until_output(
                    common
                    + [
                        f"--force-device-scale-factor={scale}",
                        f"--window-size={css_w},{css_h + HEADLESS_UI_ALLOWANCE_PX}",
                        f"--screenshot={shot}",
                        html.as_uri(),
                    ],
                    shot,
                )
                png.write_bytes(crop_png_rows(shot.read_bytes(), css_h * scale))
                png_backend = "chrome-screenshot-cropped"
    return png_backend


def rasterize_pdf_with_poppler(pdf: Path, png: Path, *, dpi: int) -> None:
    """pdftoppm renders exactly the page box, so the PNG aspect equals the PDF's."""
    stem = png.with_suffix("")
    run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", str(pdf), str(stem)])
    produced = stem.with_suffix(".png")
    if produced != png:
        produced.replace(png)
    if not png.is_file() or png.stat().st_size == 0:
        raise RenderError("pdftoppm produced no PNG")


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RenderError("screenshot is not a PNG")
    chunks: list[tuple[bytes, bytes]] = []
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        chunks.append((kind, data[offset + 8 : offset + 8 + length]))
        offset += 12 + length
        if kind == b"IEND":
            break
    return chunks


def crop_png_rows(data: bytes, keep_rows: int) -> bytes:
    """Keep the top ``keep_rows`` scanlines of an 8-bit non-interlaced PNG.

    Pure Python: inflate, unfilter only the rows that are kept (each row
    depends on the one above), re-emit them with filter 0.
    """
    chunks = _png_chunks(data)
    header = dict(chunks)[b"IHDR"]
    width, height, bit_depth, colour_type, _, _, interlace = struct.unpack(
        ">IIBBBBB", header
    )
    channels = {0: 1, 2: 3, 4: 2, 6: 4}.get(colour_type)
    if bit_depth != 8 or channels is None or interlace != 0:
        raise RenderError("screenshot PNG layout is not supported for cropping")
    keep_rows = min(keep_rows, height)
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    bpp = channels
    stride = width * bpp + 1
    previous = bytearray(width * bpp)
    out_rows: list[bytes] = []
    for row in range(keep_rows):
        filter_type = raw[row * stride]
        line = bytearray(raw[row * stride + 1 : (row + 1) * stride])
        if filter_type == 1:
            for x in range(bpp, len(line)):
                line[x] = (line[x] + line[x - bpp]) & 255
        elif filter_type == 2:
            for x in range(len(line)):
                line[x] = (line[x] + previous[x]) & 255
        elif filter_type == 3:
            for x in range(len(line)):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + previous[x]) >> 1)) & 255
        elif filter_type == 4:
            for x in range(len(line)):
                a = line[x - bpp] if x >= bpp else 0
                b = previous[x]
                c = previous[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else b if pb <= pc else c
                line[x] = (line[x] + predictor) & 255
        elif filter_type != 0:
            raise RenderError(f"unknown PNG filter type {filter_type}")
        out_rows.append(b"\x00" + bytes(line))
        previous = line

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    new_header = struct.pack(">IIBBBBB", width, keep_rows, 8, colour_type, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", new_header)
        + chunk(b"IDAT", zlib.compress(b"".join(out_rows), 6))
        + chunk(b"IEND", b"")
    )


def export_with_rsvg(
    svg_path: Path, width_mm: float, pdf: Path | None, png: Path | None, scale: int
) -> None:
    if pdf is not None:
        run(["rsvg-convert", "-f", "pdf", "-o", str(pdf), str(svg_path)])
    if png is not None:
        px = round(width_mm / MM_PER_INCH * CSS_PX_PER_INCH * scale)
        run(["rsvg-convert", "-f", "png", "-w", str(px), "-o", str(png), str(svg_path)])


def export_with_inkscape(
    svg_path: Path, width_mm: float, pdf: Path | None, png: Path | None, scale: int
) -> None:
    if pdf is not None:
        run(
            ["inkscape", str(svg_path), "--export-type=pdf", f"--export-filename={pdf}"]
        )
    if png is not None:
        px = round(width_mm / MM_PER_INCH * CSS_PX_PER_INCH * scale)
        run(
            [
                "inkscape",
                str(svg_path),
                "--export-type=png",
                f"--export-width={px}",
                f"--export-filename={png}",
            ]
        )


def export_with_cairosvg(
    svg_text: str, width_mm: float, pdf: Path | None, png: Path | None, scale: int
) -> None:
    import cairosvg  # type: ignore

    if pdf is not None:
        cairosvg.svg2pdf(bytestring=svg_text.encode("utf-8"), write_to=str(pdf))
    if png is not None:
        px = round(width_mm / MM_PER_INCH * CSS_PX_PER_INCH * scale)
        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"), write_to=str(png), output_width=px
        )


def _inflated_object_streams(pdf_bytes: bytes) -> bytes:
    """PDF 1.5 writers pack page dictionaries into Flate object streams."""
    chunks = [pdf_bytes]
    for match in re.finditer(rb"stream\r?\n", pdf_bytes):
        header = pdf_bytes[max(0, match.start() - 300) : match.start()]
        header = header[header.rfind(b"<<") :] if b"<<" in header else b""
        if b"/ObjStm" not in header or b"/FlateDecode" not in header:
            continue
        end = pdf_bytes.find(b"endstream", match.end())
        if end < 0:
            continue
        try:
            chunks.append(zlib.decompress(pdf_bytes[match.end() : end]))
        except zlib.error:
            continue
    return b"\n".join(chunks)


def pdf_media_box(pdf_bytes: bytes) -> tuple[float, float] | None:
    match = re.search(
        rb"/MediaBox\s*\[\s*([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s+([0-9.\-]+)\s*\]",
        _inflated_object_streams(pdf_bytes),
    )
    if match is None:
        return None
    x0, y0, x1, y1 = (float(v) for v in match.groups())
    return abs(x1 - x0), abs(y1 - y0)


def png_size(png_bytes: bytes) -> tuple[int, int] | None:
    if not png_bytes.startswith(b"\x89PNG\r\n\x1a\n") or len(png_bytes) < 24:
        return None
    width, height = struct.unpack(">II", png_bytes[16:24])
    return width, height


def verify(svg_aspect: float, pdf: Path | None, png: Path | None) -> list[str]:
    problems: list[str] = []
    if pdf is not None:
        box = pdf_media_box(pdf.read_bytes())
        if box is None or box[1] == 0:
            problems.append("PDF has no readable MediaBox")
        elif abs(box[0] / box[1] - svg_aspect) / svg_aspect > ASPECT_TOLERANCE:
            problems.append(
                f"PDF page aspect {box[0] / box[1]:.3f} differs from SVG aspect {svg_aspect:.3f}: the render is clipped or letter-boxed"
            )
    if png is not None:
        size = png_size(png.read_bytes())
        if size is None or size[1] == 0:
            problems.append("PNG header unreadable")
        elif abs(size[0] / size[1] - svg_aspect) / svg_aspect > ASPECT_TOLERANCE:
            problems.append(
                f"PNG aspect {size[0] / size[1]:.3f} differs from SVG aspect {svg_aspect:.3f}"
            )
    return problems


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(svg_path: Path, pdf: Path | None, png: Path | None, scale: int = 3) -> dict:
    svg_text = svg_path.read_text(encoding="utf-8")
    width_mm, height_mm = svg_size_mm(svg_text)
    aspect = width_mm / height_mm
    backend = None
    png_backend = ""
    chrome = find_chrome()
    if chrome:
        png_backend = export_with_chrome(
            chrome, svg_text, width_mm, height_mm, pdf, png, scale
        )
        backend = "chrome"
    elif shutil.which("rsvg-convert"):
        export_with_rsvg(svg_path, width_mm, pdf, png, scale)
        backend = "rsvg-convert"
    elif shutil.which("inkscape"):
        export_with_inkscape(svg_path, width_mm, pdf, png, scale)
        backend = "inkscape"
    else:
        try:
            export_with_cairosvg(svg_text, width_mm, pdf, png, scale)
            backend = "cairosvg"
        except ImportError as exc:
            raise RenderError(
                "no SVG renderer available (Chrome/Chromium, rsvg-convert, inkscape or cairosvg)"
            ) from exc
    problems = verify(aspect, pdf, png)
    if problems:
        raise RenderError("; ".join(problems))
    report = {
        "contract": CONTRACT_ID,
        "backend": backend,
        "svg": {
            "path": str(svg_path),
            "sha256": sha256(svg_path),
            "width_mm": round(width_mm, 3),
            "height_mm": round(height_mm, 3),
        },
    }
    if pdf is not None:
        report["pdf"] = {
            "path": str(pdf),
            "sha256": sha256(pdf),
            "media_box_pt": pdf_media_box(pdf.read_bytes()),
        }
    if png is not None:
        size = png_size(png.read_bytes())
        report["png"] = {
            "path": str(png),
            "sha256": sha256(png),
            "pixels": size,
            "dpi": round(size[0] / (width_mm / MM_PER_INCH)) if size else None,
            "backend": png_backend or backend,
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--png", type=Path)
    parser.add_argument(
        "--scale",
        type=int,
        default=3,
        help="PNG device scale factor over 96 dpi (3 = 288 dpi)",
    )
    args = parser.parse_args(argv)
    if args.pdf is None and args.png is None:
        args.pdf = args.svg.with_suffix(".pdf")
        args.png = args.svg.with_suffix(".png")
    try:
        report = render(args.svg, args.pdf, args.png, args.scale)
    except RenderError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
