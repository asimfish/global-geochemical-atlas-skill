# ADR-0013: Typesetting and figure quality contract

## Status

Accepted (extends ADR-0007 and ADR-0012)

## Context

The first China run that reached a graded deliverable (dc-003,
`best_available_executed_pilot`, three revision rounds) produced a manuscript
the owner judged unpublishable: a plain `article` with default fonts, numbers
tagged by blue monospace `\claim{...}` markers inside the prose, figures floated
behind the bibliography with a fixed `height=0.68\textheight`, a first figure
whose browser PDF export was clipped, disclaimer boxes and sub-floor text drawn
inside the figures, and a spatial figure without any coastline or boundary.
Every one of these passed the gates of ADR-0007: the publication lint only
checked well-formedness, a font floor and page-bearing PDFs, and the reviewer
gates a5/a6 rely on judgement that a same-family reviewer did not exercise.

Two controller defects surfaced in the same run: the publication manifest
listed four SVG paths twice with conflicting hashes (artifacts from different
cycles with the same basename collapsed onto one packaged file), and restoring
an archived attempt moved its files, leaving the archive manifest pointing at
nothing.

## Decision drivers

- The manuscript must look like a journal manuscript without the writer
  inventing a layout: give it a fixed style and skeleton, and reject anything
  else.
- Numbers must remain traceable to the frozen registry, but through
  typography that a reader accepts (superscript marks resolving to a ledger
  appendix), not inline identifiers.
- Figures must be complete, geographic when spatial, readable in print, and
  identical across SVG/PDF/PNG; the gate must prove that instead of trusting a
  self-attested render inspection.
- Everything must run in the executor sandbox: Python only, no matplotlib, no
  network; TeX and a headless browser are available on the reference machine.

## Decision

1. **Paper kit (`gga-paper-v1`).** The controller installs `paper_kit/` when
   the manuscript wave opens: `gga-paper.sty` (Times stack
   newtx -> mathptmx -> Latin Modern fallback, compact `\@startsection`
   headings, `fancyhdr` running head, caption/float rules, `natbib`), a
   manuscript skeleton, a controller-generated `claims.tex` that registers
   every registry claim, and `references.bib` seeded from the verified
   literature with the matching `seeded_reference_list.json`. The style defines
   `\registerclaim`, `\claimref` (hyperlinked superscript mark; compile error
   on an unregistered id), `\printclaimledger` (appendix table), a quiet
   `boundary` environment and `\ggafigure`.
2. **Typesetting gate.** `_validate_typeset_manifest` lints the LaTeX source
   deterministically (loads `gga-paper`, `\input{claims}`, `\claimref` only
   with registered ids, no `\claim{...}`, typewriter density, full-width
   figures without fixed height, caption + label + in-text reference, figures
   before the bibliography, `\cite` keys present in the submitted
   `bib_artifact`, `\printclaimledger`) and the PDF (TeX-engine producer,
   at least four pages, Abstract on page one, template fonts, using poppler
   when present and byte checks otherwise). The manuscript `reference_list`
   must equal the set of cited bib keys. The quality contract exposes the same
   rules as `typesetting_gate.typesetting_contract`.
3. **Figure kit (`gga-figure-kit-v1`).** `figure_kit/` ships
   `paper_figures.py` (pure-Python SVG `Figure`/`Axes`/`MapPanel`, Okabe-Ito
   palette, point-sized typography above the print floor, offline Natural
   Earth basemap tagged `data-gga-layer="basemap"`, deterministic ids),
   `render_figure.py` (same-size vector PDF via headless Chrome
   print-to-PDF with an `@page` box; PNG rasterised from that page by
   `pdftoppm`, or a cropped screenshot when poppler is absent because the new
   headless viewport is shorter than the requested window; rsvg/inkscape/
   cairosvg fallbacks; exit 3 instead of a fake render), the lint, and the
   basemap assets.
4. **Render fidelity gate.** For every figure the controller compares the PDF
   MediaBox and the PNG pixel box with the SVG aspect (2 % tolerance) and
   requires the basemap layer for `spatial_pattern` and `coverage_and_gaps`.
   The publication lint additionally treats undeclared SVG text as 16 px,
   honours stylesheet class sizes, rejects text runs longer than 120
   characters inside a figure, and reads page objects and MediaBoxes inside
   PDF 1.5 object streams so compressed pdfTeX output is judged correctly.
5. **Packaging and archives.** Packaged deliverables keep their sub-path below
   `agent_outputs/<role>/`, and a collision raises instead of overwriting.
   Restoring an archived attempt copies it; the archive stays byte-complete
   and `restored.json` (v2) records the copied entries.

## Consequences

- The real-data chains (world redirect, China publish, China evidence report,
  China best-available) now end with a pdfTeX-compiled four-page manuscript
  on the kit and Chrome-rendered kit figures that pass every gate; the
  earlier fixtures (Markdown source, one-page hand-written PDF, basemap-less
  spatial SVG) are rejected by design.
- A writer that ignores the kit fails at submission with an itemised message
  and can self-check with `submit --validate-only`; the shortest compliant path
  is documented in `references/auto-research.md`.
- The gates still do not judge prose quality or scientific reasoning; a5/a6
  remain reviewer judgement, now over a manuscript whose layout cannot fall
  below the contract.
- Executors need a TeX engine (`latexmk`/`pdflatex` with the packages listed in
  `gga-paper.sty`) and a headless browser; without them the run waits at the
  writer/figure packets rather than accepting a lesser deliverable.
