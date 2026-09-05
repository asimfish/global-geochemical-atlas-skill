"""Dependency-free publication figure toolkit (contract ``gga-figure-kit-v1``).

Figure agents run in sandboxes that have Python but neither matplotlib nor a
raster library, so this module draws SVG directly and lets ``render_figure.py``
export PDF/PNG through a headless browser.  It encodes the house rules the
review gate a6 and the publication lint check:

* one sans-serif family; sizes fixed in points at a 180 mm two-column width
  (panel label 10 pt, panel title 9 pt, axis label 8 pt, tick 7 pt), all above
  the print floor at column width;
* Okabe-Ito colour-blind-safe palette, no gradients, no glow, no shadows;
* caveats belong in the caption, never in boxes drawn inside the figure;
* spatial panels draw the offline Natural Earth land, Admin-0 and (for China)
  Admin-1 layers, tagged ``data-gga-layer="basemap"`` so the lint can prove a
  spatial figure has a geographic frame;
* every drawn quantity should come from a registry claim or a hash-bound pilot
  artifact -- the toolkit records ``data-gga-claims`` on the root element from
  the ids you pass to :meth:`Figure.bind_claims`.

Typical use::

    fig = Figure(width_mm=180, height_mm=70)
    ax = fig.add_axes(x=14, y=12, w=70, h=48, xlabel="Bulk Cr (mg/kg)",
                      ylabel="Residue Cr (mg/kg)", xlog=True, ylog=True, label="A")
    ax.scatter(xs, ys, color=PALETTE["blue"])
    ax.diagonal(dash=True)
    m = fig.add_map(x=100, y=12, w=70, h=48, bounds=(73.7, 18.2, 135.0, 53.5),
                    label="B", assets_dir=ASSETS)
    m.points(lons, lats, values, cmap="viridis_lite")
    fig.bind_claims(["pilot.dc003.paired_n"])
    fig.save("fig1.svg")
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

CONTRACT_ID = "gga-figure-kit-v1"
FONT_FAMILY = "Helvetica, Arial, 'Liberation Sans', sans-serif"
# Point sizes at the reference width; the SVG user unit is 1 pt (viewBox in pt).
FONT_PT = {"panel_label": 10.0, "title": 9.0, "axis": 8.0, "tick": 7.0, "annotation": 7.5, "legend": 7.5}
MM_TO_PT = 72.0 / 25.4
PALETTE = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermilion": "#D55E00",
    "purple": "#CC79A7",
    "grey": "#7F7F7F",
}
SEQUENCE = [PALETTE[name] for name in ("blue", "orange", "green", "vermilion", "purple", "sky", "yellow", "grey")]
INK = "#1F2933"
MUTED = "#52616B"
RULE = "#B8C2C8"
LAND = "#EDF1F4"
WATER = "#FFFFFF"
COAST = "#7C8C96"
ADMIN0 = "#9AA8B0"
ADMIN1 = "#C4CDD3"
FOCUS = "#B7791F"

_HERE = Path(__file__).resolve().parent
# Inside the skill the basemaps live in ../assets; inside a run's figure_kit/
# the controller copies them next to this file.
DEFAULT_ASSETS = (
    _HERE.parent / "assets"
    if (_HERE.parent / "assets" / "natural-earth-110m-land.json").is_file()
    else _HERE
)


def _fmt(value: float) -> str:
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def _esc(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Linear tick positions at 1/2/5 steps covering [lo, hi]."""
    if hi <= lo:
        return [lo]
    raw = (hi - lo) / max(n, 1)
    magnitude = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if (hi - lo) / step <= n + 1:
            break
    start = math.floor(lo / step) * step
    ticks = []
    value = start
    while value <= hi + step * 1e-9:
        if value >= lo - step * 1e-9:
            ticks.append(round(value, 10))
        value += step
    return ticks


def log_ticks(lo: float, hi: float) -> list[float]:
    """Decade ticks (with 2 and 5 when the span is narrow) for log axes."""
    if lo <= 0 or hi <= lo:
        raise ValueError("log axis needs positive increasing limits")
    decades = math.log10(hi) - math.log10(lo)
    exponents = range(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1)
    mantissas = (1, 2, 5) if decades <= 3 else (1,)
    ticks = [m * 10**e for e in exponents for m in mantissas]
    return [t for t in ticks if lo * (1 - 1e-9) <= t <= hi * (1 + 1e-9)]


def tick_label(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1e5 or magnitude < 1e-3:
        exponent = math.floor(math.log10(magnitude))
        mantissa = value / 10**exponent
        return f"{_fmt(mantissa)}\u00d710^{exponent}" if abs(mantissa - 1) > 1e-9 else f"10^{exponent}"
    return _fmt(value)


def color_ramp(t: float, name: str = "viridis_lite") -> str:
    """Small perceptual ramps (t in [0,1]) that survive greyscale printing."""
    t = min(1.0, max(0.0, t))
    ramps = {
        "viridis_lite": [(68, 1, 84), (59, 82, 139), (33, 145, 140), (94, 201, 98), (253, 231, 37)],
        "teal_ochre": [(42, 127, 142), (140, 170, 150), (183, 121, 31)],
        "blue_red": [(0, 114, 178), (200, 200, 200), (213, 94, 0)],
    }
    stops = ramps[name]
    position = t * (len(stops) - 1)
    index = min(int(position), len(stops) - 2)
    frac = position - index
    rgb = [round(stops[index][k] + (stops[index + 1][k] - stops[index][k]) * frac) for k in range(3)]
    return "#%02x%02x%02x" % tuple(rgb)


class Axes:
    """A Cartesian panel with optional log scales; coordinates in pt."""

    def __init__(self, fig: "Figure", x: float, y: float, w: float, h: float, *, xlabel: str = "", ylabel: str = "",
                 xlog: bool = False, ylog: bool = False, label: str = "", title: str = "",
                 legend_loc: str = "lower right") -> None:
        self.fig, self.x, self.y, self.w, self.h = fig, x, y, w, h
        self.xlabel, self.ylabel, self.xlog, self.ylog = xlabel, ylabel, xlog, ylog
        self.label, self.title = label, title
        self.legend_loc = legend_loc
        self.xlim: tuple[float, float] | None = None
        self.ylim: tuple[float, float] | None = None
        self.body: list[str] = []
        self.legend_items: list[tuple[str, str, str]] = []

    def set_xlim(self, lo: float, hi: float) -> "Axes":
        self.xlim = (lo, hi)
        return self

    def set_ylim(self, lo: float, hi: float) -> "Axes":
        self.ylim = (lo, hi)
        return self

    def _auto_limits(self, values: Sequence[float], log: bool) -> tuple[float, float]:
        finite = [v for v in values if v is not None and math.isfinite(v) and (not log or v > 0)]
        if not finite:
            return (0.1, 10.0) if log else (0.0, 1.0)
        lo, hi = min(finite), max(finite)
        if log:
            return (10 ** math.floor(math.log10(lo)), 10 ** math.ceil(math.log10(hi) + 1e-9))
        span = hi - lo or abs(hi) or 1.0
        return (lo - 0.06 * span, hi + 0.06 * span)

    def _ensure_limits(self, xs: Sequence[float] = (), ys: Sequence[float] = ()) -> None:
        if self.xlim is None:
            self.xlim = self._auto_limits(xs, self.xlog)
        if self.ylim is None:
            self.ylim = self._auto_limits(ys, self.ylog)

    def px(self, value: float) -> float:
        assert self.xlim is not None
        lo, hi = self.xlim
        if self.xlog:
            frac = (math.log10(value) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        else:
            frac = (value - lo) / (hi - lo)
        return self.x + frac * self.w

    def py(self, value: float) -> float:
        assert self.ylim is not None
        lo, hi = self.ylim
        if self.ylog:
            frac = (math.log10(value) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
        else:
            frac = (value - lo) / (hi - lo)
        return self.y + self.h - frac * self.h

    # --- marks -----------------------------------------------------------
    def scatter(self, xs: Sequence[float], ys: Sequence[float], *, color: str = PALETTE["blue"], size: float = 2.2,
                alpha: float = 0.85, colors: Sequence[str] | None = None, legend: str = "") -> "Axes":
        self._ensure_limits(xs, ys)
        for index, (xv, yv) in enumerate(zip(xs, ys)):
            if not (math.isfinite(xv) and math.isfinite(yv)):
                continue
            fill = colors[index] if colors is not None else color
            self.body.append(
                f'<circle cx="{_fmt(self.px(xv))}" cy="{_fmt(self.py(yv))}" r="{_fmt(size)}" fill="{fill}" '
                f'fill-opacity="{alpha}" stroke="{INK}" stroke-opacity="0.35" stroke-width="0.3"/>'
            )
        if legend:
            self.legend_items.append(("circle", color, legend))
        return self

    def line(self, xs: Sequence[float], ys: Sequence[float], *, color: str = INK, width: float = 1.0,
             dash: bool = False, legend: str = "") -> "Axes":
        self._ensure_limits(xs, ys)
        points = " ".join(f"{_fmt(self.px(xv))},{_fmt(self.py(yv))}" for xv, yv in zip(xs, ys))
        dash_attr = ' stroke-dasharray="3 2"' if dash else ""
        self.body.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="{width}"{dash_attr}/>')
        if legend:
            self.legend_items.append(("line", color, legend))
        return self

    def hline(self, yv: float, *, color: str = MUTED, dash: bool = True, width: float = 0.8, text: str = "") -> "Axes":
        self._ensure_limits((), (yv,))
        yp = self.py(yv)
        dash_attr = ' stroke-dasharray="3 2"' if dash else ""
        self.body.append(f'<line x1="{_fmt(self.x)}" x2="{_fmt(self.x + self.w)}" y1="{_fmt(yp)}" y2="{_fmt(yp)}" stroke="{color}" stroke-width="{width}"{dash_attr}/>')
        if text:
            offset = 8 if yp - self.y < 10 else -2.5
            self.body.append(self.fig._text(self.x + self.w - 2, yp + offset, text, FONT_PT["annotation"], anchor="end", color=MUTED))
        return self

    def vline(self, xv: float, *, color: str = MUTED, dash: bool = True, width: float = 0.8) -> "Axes":
        self._ensure_limits((xv,), ())
        xp = self.px(xv)
        dash_attr = ' stroke-dasharray="3 2"' if dash else ""
        self.body.append(f'<line x1="{_fmt(xp)}" x2="{_fmt(xp)}" y1="{_fmt(self.y)}" y2="{_fmt(self.y + self.h)}" stroke="{color}" stroke-width="{width}"{dash_attr}/>')
        return self

    def diagonal(self, *, dash: bool = True, color: str = MUTED, text: str = "") -> "Axes":
        """The y = x reference line across the common range of both axes."""
        self._ensure_limits()
        assert self.xlim and self.ylim
        lo = max(self.xlim[0], self.ylim[0])
        hi = min(self.xlim[1], self.ylim[1])
        if hi > lo:
            self.line([lo, hi], [lo, hi], color=color, width=0.8, dash=dash)
            if text:
                # label sits inside the panel, just under the top edge, left of the line end
                self.body.append(self.fig._text(self.px(hi) - 4, self.py(hi) + 9, text, FONT_PT["annotation"], anchor="end", color=MUTED))
        return self

    def errorbar(self, xv: float, yv: float, lo: float, hi: float, *, color: str = PALETTE["vermilion"],
                 cap: float = 2.5, marker: float = 2.6, legend: str = "") -> "Axes":
        self._ensure_limits((xv,), (lo, hi, yv))
        xp, yp, ylo, yhi = self.px(xv), self.py(yv), self.py(lo), self.py(hi)
        self.body.append(f'<line x1="{_fmt(xp)}" x2="{_fmt(xp)}" y1="{_fmt(ylo)}" y2="{_fmt(yhi)}" stroke="{color}" stroke-width="1"/>')
        for yy in (ylo, yhi):
            self.body.append(f'<line x1="{_fmt(xp - cap)}" x2="{_fmt(xp + cap)}" y1="{_fmt(yy)}" y2="{_fmt(yy)}" stroke="{color}" stroke-width="1"/>')
        self.body.append(f'<circle cx="{_fmt(xp)}" cy="{_fmt(yp)}" r="{marker}" fill="{color}"/>')
        if legend:
            self.legend_items.append(("circle", color, legend))
        return self

    def bars(self, labels: Sequence[str], values: Sequence[float], *, color: str = PALETTE["blue"],
             errors: Sequence[tuple[float, float]] | None = None, baseline: float = 0.0) -> "Axes":
        n = len(values)
        self.xlim = (0.0, float(n))
        ys = list(values) + [baseline]
        if errors:
            ys += [e for pair in errors for e in pair]
        if self.ylim is None:
            self.ylim = self._auto_limits(ys, self.ylog)
        slot = self.w / max(n, 1)
        for index, (label, value) in enumerate(zip(labels, values)):
            x0 = self.x + index * slot + slot * 0.18
            width = slot * 0.64
            y_top, y_base = self.py(value), self.py(baseline)
            self.body.append(f'<rect x="{_fmt(x0)}" y="{_fmt(min(y_top, y_base))}" width="{_fmt(width)}" height="{_fmt(abs(y_base - y_top))}" fill="{color}" fill-opacity="0.9"/>')
            if errors:
                lo, hi = errors[index]
                xc = x0 + width / 2
                self.body.append(f'<line x1="{_fmt(xc)}" x2="{_fmt(xc)}" y1="{_fmt(self.py(lo))}" y2="{_fmt(self.py(hi))}" stroke="{INK}" stroke-width="0.9"/>')
            self.body.append(self.fig._text(x0 + width / 2, self.y + self.h + 9, label, FONT_PT["tick"], anchor="middle"))
        self._category_axis = True
        return self

    def annotate(self, xv: float, yv: float, text: str, *, dx: float = 3, dy: float = -3, color: str = INK, anchor: str = "start") -> "Axes":
        self._ensure_limits((xv,), (yv,))
        self.body.append(self.fig._text(self.px(xv) + dx, self.py(yv) + dy, text, FONT_PT["annotation"], anchor=anchor, color=color))
        return self

    # --- rendering -------------------------------------------------------
    def _axis_ticks(self, lim: tuple[float, float], log: bool) -> list[float]:
        return log_ticks(*lim) if log else nice_ticks(*lim)

    def render(self) -> str:
        self._ensure_limits()
        assert self.xlim and self.ylim
        out = [f'<g data-gga-panel="{_esc(self.label or self.title or "axes")}">']
        out.append(f'<rect x="{_fmt(self.x)}" y="{_fmt(self.y)}" width="{_fmt(self.w)}" height="{_fmt(self.h)}" fill="{WATER}" stroke="none"/>')
        # grid + ticks
        if not getattr(self, "_category_axis", False):
            for tick in self._axis_ticks(self.xlim, self.xlog):
                xp = self.px(tick)
                out.append(f'<line x1="{_fmt(xp)}" x2="{_fmt(xp)}" y1="{_fmt(self.y + self.h)}" y2="{_fmt(self.y + self.h + 2.5)}" stroke="{INK}" stroke-width="0.6"/>')
                out.append(self.fig._text(xp, self.y + self.h + 9.5, tick_label(tick), FONT_PT["tick"], anchor="middle"))
        for tick in self._axis_ticks(self.ylim, self.ylog):
            yp = self.py(tick)
            out.append(f'<line x1="{_fmt(self.x)}" x2="{_fmt(self.x + self.w)}" y1="{_fmt(yp)}" y2="{_fmt(yp)}" stroke="{RULE}" stroke-width="0.35"/>')
            out.append(f'<line x1="{_fmt(self.x - 2.5)}" x2="{_fmt(self.x)}" y1="{_fmt(yp)}" y2="{_fmt(yp)}" stroke="{INK}" stroke-width="0.6"/>')
            out.append(self.fig._text(self.x - 4, yp + 2.4, tick_label(tick), FONT_PT["tick"], anchor="end"))
        out.extend(self.body)
        # frame (left + bottom spines)
        out.append(f'<path d="M{_fmt(self.x)},{_fmt(self.y)} V{_fmt(self.y + self.h)} H{_fmt(self.x + self.w)}" fill="none" stroke="{INK}" stroke-width="0.8"/>')
        if self.xlabel:
            out.append(self.fig._text(self.x + self.w / 2, self.y + self.h + 19, self.xlabel, FONT_PT["axis"], anchor="middle"))
        if self.ylabel:
            cx, cy = self.x - 20, self.y + self.h / 2
            out.append(self.fig._text(cx, cy, self.ylabel, FONT_PT["axis"], anchor="middle", rotate=-90))
        if self.title:
            out.append(self.fig._text(self.x + self.w / 2, self.y - 4, self.title, FONT_PT["title"], anchor="middle", weight="600"))
        if self.label:
            out.append(self.fig._text(self.x - 24, self.y - 4, self.label, FONT_PT["panel_label"], anchor="start", weight="700"))
        if self.legend_items:
            rows = len(self.legend_items)
            step = FONT_PT["legend"] + 3
            right = "right" in self.legend_loc
            lower = "lower" in self.legend_loc
            lx = self.x + self.w - 4 if right else self.x + 14
            ly = (self.y + self.h - 4 - (rows - 1) * step) if lower else (self.y + 9)
            for kind, color, text in self.legend_items:
                marker_x = lx - 3 if right else lx - 10
                if kind == "circle":
                    out.append(f'<circle cx="{_fmt(marker_x)}" cy="{_fmt(ly - 2.4)}" r="2.2" fill="{color}"/>')
                else:
                    out.append(f'<line x1="{_fmt(marker_x - 4)}" x2="{_fmt(marker_x + 4)}" y1="{_fmt(ly - 2.4)}" y2="{_fmt(ly - 2.4)}" stroke="{color}" stroke-width="1.2"/>')
                if right:
                    out.append(self.fig._text(lx - 9, ly, text, FONT_PT["legend"], anchor="end"))
                else:
                    out.append(self.fig._text(lx - 4, ly, text, FONT_PT["legend"], anchor="start"))
                ly += step
        out.append("</g>")
        return "\n".join(out)


class MapPanel:
    """Equirectangular regional map with offline Natural Earth reference layers."""

    def __init__(self, fig: "Figure", x: float, y: float, w: float, h: float, bounds: tuple[float, float, float, float], *,
                 label: str = "", title: str = "", assets_dir: Path = DEFAULT_ASSETS, admin1: bool | None = None,
                 focus_codes: Sequence[str] = ()) -> None:
        self.fig, self.x, self.y, self.w, self.h = fig, x, y, w, h
        self.west, self.south, self.east, self.north = bounds
        self.label, self.title = label, title
        self.assets_dir = Path(assets_dir)
        self.focus_codes = list(focus_codes)
        mid_lat = math.radians((self.south + self.north) / 2)
        # keep degrees square-ish at the mid latitude
        span_lon = (self.east - self.west) * math.cos(mid_lat)
        span_lat = self.north - self.south
        scale = min(self.w / span_lon, self.h / span_lat)
        self.sx = scale * math.cos(mid_lat)
        self.sy = scale
        self.draw_w, self.draw_h = span_lon * scale, span_lat * scale
        self.ox = self.x + (self.w - self.draw_w) / 2
        self.oy = self.y + (self.h - self.draw_h) / 2
        china_overlap = not (self.east < 73 or self.west > 135 or self.north < 18 or self.south > 54)
        self.admin1 = china_overlap if admin1 is None else admin1
        self.body: list[str] = []
        # Deterministic id (panel ordinal), so identical inputs give identical SVG bytes.
        self.clip_id = f"clip-map-{len(fig.panels) + 1}"

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        return (self.ox + (lon - self.west) * self.sx, self.oy + (self.north - lat) * self.sy)

    def _visible(self, ring: Sequence[Sequence[float]]) -> bool:
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        return not (max(lons) < self.west - 5 or min(lons) > self.east + 5 or max(lats) < self.south - 5 or min(lats) > self.north + 5)

    def _path(self, ring: Sequence[Sequence[float]]) -> str:
        return "M" + " L".join(f"{_fmt(px)},{_fmt(py)}" for px, py in (self.project(p[0], p[1]) for p in ring)) + " Z"

    def _rings(self, geometry: dict[str, Any]) -> list[list[list[float]]]:
        if geometry.get("type") == "Polygon":
            return [ring for ring in geometry.get("coordinates", [])]
        if geometry.get("type") == "MultiPolygon":
            return [ring for polygon in geometry.get("coordinates", []) for ring in polygon]
        return []

    def basemap(self) -> str:
        land = json.loads((self.assets_dir / "natural-earth-110m-land.json").read_text(encoding="utf-8"))
        admin0 = json.loads((self.assets_dir / "natural-earth-110m-admin0.json").read_text(encoding="utf-8"))
        parts = [f'<g data-gga-layer="basemap" clip-path="url(#{self.clip_id})">']
        for ring in land["rings"]:
            if self._visible(ring):
                parts.append(f'<path d="{self._path(ring)}" fill="{LAND}" stroke="{COAST}" stroke-width="0.45" stroke-linejoin="round"/>')
        focus_paths = []
        for country in admin0["countries"]:
            rings = self._rings(country["geometry"])
            for ring in rings:
                if not self._visible(ring):
                    continue
                d = self._path(ring)
                parts.append(f'<path d="{d}" fill="none" stroke="{ADMIN0}" stroke-width="0.4"/>')
                if country.get("iso_a3") in self.focus_codes:
                    focus_paths.append(d)
        if self.admin1:
            admin1_path = self.assets_dir / "natural-earth-50m-admin1-china-visual.json"
            if admin1_path.is_file():
                admin1 = json.loads(admin1_path.read_text(encoding="utf-8"))
                for boundary in admin1["boundaries"]:
                    for ring in self._rings(boundary["geometry"]):
                        if self._visible(ring):
                            parts.append(f'<path d="{self._path(ring)}" fill="none" stroke="{ADMIN1}" stroke-width="0.3" stroke-dasharray="1.5 1"/>')
        for d in focus_paths:
            parts.append(f'<path d="{d}" fill="none" stroke="{FOCUS}" stroke-width="0.9"/>')
        parts.append("</g>")
        return "\n".join(parts)

    def graticule(self, step: float | None = None) -> str:
        span = max(self.east - self.west, self.north - self.south)
        step = step or (30 if span > 120 else 10 if span > 40 else 5 if span > 15 else 2)
        parts = ['<g data-gga-layer="graticule">']
        lon = math.ceil(self.west / step) * step
        while lon <= self.east:
            x0, _ = self.project(lon, self.north)
            parts.append(f'<line x1="{_fmt(x0)}" x2="{_fmt(x0)}" y1="{_fmt(self.oy)}" y2="{_fmt(self.oy + self.draw_h)}" stroke="{RULE}" stroke-width="0.3"/>')
            parts.append(self.fig._text(x0, self.oy + self.draw_h + 9, f"{abs(lon):g}\u00b0{'E' if lon >= 0 else 'W'}", FONT_PT["tick"], anchor="middle"))
            lon += step
        lat = math.ceil(self.south / step) * step
        while lat <= self.north:
            _, y0 = self.project(self.west, lat)
            parts.append(f'<line x1="{_fmt(self.ox)}" x2="{_fmt(self.ox + self.draw_w)}" y1="{_fmt(y0)}" y2="{_fmt(y0)}" stroke="{RULE}" stroke-width="0.3"/>')
            parts.append(self.fig._text(self.ox - 3, y0 + 2.4, f"{abs(lat):g}\u00b0{'N' if lat >= 0 else 'S'}", FONT_PT["tick"], anchor="end"))
            lat += step
        parts.append("</g>")
        return "\n".join(parts)

    def points(self, lons: Sequence[float], lats: Sequence[float], values: Sequence[float] | None = None, *,
               cmap: str = "viridis_lite", size: float = 2.6, color: str = PALETTE["vermilion"],
               vmin: float | None = None, vmax: float | None = None, legend_title: str = "") -> "MapPanel":
        if values is not None:
            finite = [v for v in values if v is not None and math.isfinite(v)]
            lo = vmin if vmin is not None else (min(finite) if finite else 0.0)
            hi = vmax if vmax is not None else (max(finite) if finite else 1.0)
            span = (hi - lo) or 1.0
            self._colorbar = (lo, hi, cmap, legend_title)
        for index, (lon, lat) in enumerate(zip(lons, lats)):
            if not (self.west <= lon <= self.east and self.south <= lat <= self.north):
                continue
            px, py = self.project(lon, lat)
            fill = color_ramp((values[index] - lo) / span, cmap) if values is not None else color
            self.body.append(f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="{_fmt(size)}" fill="{fill}" stroke="{INK}" stroke-width="0.35" fill-opacity="0.92"/>')
        return self

    def render(self) -> str:
        out = [f'<g data-gga-panel="{_esc(self.label or self.title or "map")}">']
        out.append(f'<defs><clipPath id="{self.clip_id}"><rect x="{_fmt(self.ox)}" y="{_fmt(self.oy)}" width="{_fmt(self.draw_w)}" height="{_fmt(self.draw_h)}"/></clipPath></defs>')
        out.append(f'<rect x="{_fmt(self.ox)}" y="{_fmt(self.oy)}" width="{_fmt(self.draw_w)}" height="{_fmt(self.draw_h)}" fill="{WATER}"/>')
        out.append(self.basemap())
        out.append(self.graticule())
        out.append(f'<g data-gga-layer="data" clip-path="url(#{self.clip_id})">' + "\n".join(self.body) + "</g>")
        out.append(f'<rect x="{_fmt(self.ox)}" y="{_fmt(self.oy)}" width="{_fmt(self.draw_w)}" height="{_fmt(self.draw_h)}" fill="none" stroke="{INK}" stroke-width="0.8"/>')
        if getattr(self, "_colorbar", None):
            lo, hi, cmap, title = self._colorbar
            bx, by, bw, bh = self.ox + self.draw_w - 48, self.oy + self.draw_h - 14, 40, 4
            out.append(f'<rect x="{_fmt(bx - 4)}" y="{_fmt(by - 11)}" width="{bw + 8}" height="{bh + 20}" fill="#FFFFFF" fill-opacity="0.85" stroke="none"/>')
            steps = 24
            for k in range(steps):
                out.append(f'<rect x="{_fmt(bx + k * bw / steps)}" y="{_fmt(by)}" width="{_fmt(bw / steps + 0.2)}" height="{bh}" fill="{color_ramp(k / (steps - 1), cmap)}"/>')
            out.append(f'<rect x="{_fmt(bx)}" y="{_fmt(by)}" width="{bw}" height="{bh}" fill="none" stroke="{INK}" stroke-width="0.4"/>')
            out.append(self.fig._text(bx, by + bh + 7, tick_label(lo), FONT_PT["tick"], anchor="start"))
            out.append(self.fig._text(bx + bw, by + bh + 7, tick_label(hi), FONT_PT["tick"], anchor="end"))
            if title:
                out.append(self.fig._text(bx + bw / 2, by - 2, title, FONT_PT["annotation"], anchor="middle"))
        # Title and panel label anchor to the drawn map, which is letter-boxed
        # inside the allotted slot when the region's aspect differs from it.
        if self.title:
            out.append(self.fig._text(self.ox + self.draw_w / 2, self.oy - 4, self.title, FONT_PT["title"], anchor="middle", weight="600"))
        if self.label:
            out.append(self.fig._text(self.ox - 24, self.oy - 4, self.label, FONT_PT["panel_label"], anchor="start", weight="700"))
        out.append("</g>")
        return "\n".join(out)


class Figure:
    """A figure canvas measured in pt (1 pt = 1 SVG user unit)."""

    def __init__(self, width_mm: float = 180.0, height_mm: float = 70.0) -> None:
        self.width_pt = width_mm * MM_TO_PT
        self.height_pt = height_mm * MM_TO_PT
        self.width_mm, self.height_mm = width_mm, height_mm
        self.panels: list[Any] = []
        self.extra: list[str] = []
        self.claims: list[str] = []
        self.footnote = ""

    def _text(self, x: float, y: float, text: Any, size: float, *, anchor: str = "start", color: str = INK,
              weight: str = "400", rotate: float | None = None) -> str:
        transform = f' transform="rotate({rotate} {_fmt(x)} {_fmt(y)})"' if rotate else ""
        return (
            f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-size="{size}" font-family="{FONT_FAMILY}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}"{transform}>{_esc(text)}</text>'
        )

    def add_axes(self, x: float, y: float, w: float, h: float, **kwargs: Any) -> Axes:
        panel = Axes(self, x * MM_TO_PT, y * MM_TO_PT, w * MM_TO_PT, h * MM_TO_PT, **kwargs)
        self.panels.append(panel)
        return panel

    def add_map(self, x: float, y: float, w: float, h: float, bounds: tuple[float, float, float, float], **kwargs: Any) -> MapPanel:
        panel = MapPanel(self, x * MM_TO_PT, y * MM_TO_PT, w * MM_TO_PT, h * MM_TO_PT, bounds, **kwargs)
        self.panels.append(panel)
        return panel

    def text(self, x_mm: float, y_mm: float, text: str, *, size: float = FONT_PT["annotation"], anchor: str = "start",
             color: str = INK, weight: str = "400") -> "Figure":
        self.extra.append(self._text(x_mm * MM_TO_PT, y_mm * MM_TO_PT, text, size, anchor=anchor, color=color, weight=weight))
        return self

    def bind_claims(self, claim_ids: Iterable[str]) -> "Figure":
        self.claims = sorted({str(c) for c in claim_ids})
        return self

    def render(self) -> str:
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(self.width_mm)}mm" height="{_fmt(self.height_mm)}mm" '
            f'viewBox="0 0 {_fmt(self.width_pt)} {_fmt(self.height_pt)}" data-gga-figure-kit="{CONTRACT_ID}" '
            f'data-gga-claims="{_esc(";".join(self.claims))}">'
        )
        parts = [head, f'<rect width="{_fmt(self.width_pt)}" height="{_fmt(self.height_pt)}" fill="#FFFFFF"/>']
        parts.extend(panel.render() for panel in self.panels)
        parts.extend(self.extra)
        parts.append("</svg>")
        return "\n".join(parts) + "\n"

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(self.render(), encoding="utf-8")
        return target
