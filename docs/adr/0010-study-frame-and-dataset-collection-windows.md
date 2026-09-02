# ADR-0010: Study frame separate from clipping, and dataset collection windows

## Status

Accepted

## Context

A full China run exposed three product defects in the frozen atlas. The main
and temporal maps showed no emphasised national outline because the D3 profile
had `country_code = null`: a named-country request that admits adjacent-marine
rows must not clip on the Admin-0 polygon, and the profile conflated "clip on
this country" with "frame this country". Regional navigation allowed zooming
out to `max(70°, 1.35 x region width)` and panning the centre 30 % of the
region outside it, so the China atlas could be scrolled to Kazakhstan, India or
Japan. Finally the temporal view dated only 223 of 42,645 records (0.5 %),
which readers could not distinguish from a parsing bug: ten of the twelve China
sources carry no row-level dates, but two of them publish a dataset-level
collection period in their own metadata, and one of them publishes a window
that dates papers rather than samples.

## Decision drivers

- Never weaken the sampling-time doctrine: publication, release and
  compilation years are not collection times.
- A cartographic frame must not change which records are admitted.
- A regional atlas must stay inside its frozen study region at every zoom.
- A thin dated share must be explainable per source from the frozen contract.

## Decision

1. **`highlight_country_codes` is emphasis only.** The profile schema gains an
   optional `custom_region.highlight_country_codes` (1-6 ISO-3 codes that must
   exist in the offline Admin-0 asset, otherwise the build fails closed).
   `run_atlas_request` writes it for every named-country request from the
   analysis units (China: `["CHN","TWN"]`), presets derive it from their
   analysis or clip codes, and `selected_region` exposes it to both templates.
   `country_code` alone still governs polygon clipping. The main map tints and
   gold-outlines the frame countries and strengthens neighbouring borders and
   Chinese Admin-1 lines in regional scope; the temporal map embeds a `focus`
   boundary layer with the same semantics, labelled by ISO code only.
2. **Regional navigation is locked to the fitted frame.** In both templates the
   zoom-out limit equals the region's fitted view span and the viewport
   rectangle may not leave the frame (3-4 % slack per axis); deeper zoom inside
   the region remains free. The old 70° floor, 1.35x factor and 30 % centre
   drift are removed.
3. **Publisher-documented dataset collection windows are a first-class time
   tier.** `sampling_time.PUBLISHER_DOCUMENTED_SAMPLING_WINDOWS` lists whole-
   dataset collection periods with a cited publisher source; D1 attaches the
   window to every row of that dataset and D2 parses it at its honest coarser
   precision. The table gains EIDC Ningbo (`2016-03`, abstract: "collected in
   March 2016") and TPDC mountain soil (`2012/2013`, metadata temporal
   coverage), alongside the existing GEMAS campaign. The Figshare Yangtze
   compilation is re-classified `publication_year_not_sampling_time` because
   its "2000-2020" dates the searched literature.
4. **The temporal payload explains every undated record.**
   `temporal-atlas-payload-v2` adds `dated_tiers` (per-sample vs window),
   `undated_by_reason` and a per-source `source_time_semantics` table (records,
   dated, basis, publisher field or contract reason, evidence link); the KPI
   card and an expandable table surface it, and `validate_outputs.py` requires
   it.

## Consequences

- China's temporal view rises from 223 to roughly 7,200 dated records while
  every added record traces to a quoted publisher statement; the remaining
  undated records (rock compilations with geological ages, literature
  compilations with publication years, archives without dates) are now listed
  with their reason instead of hiding behind a percentage.
- Adjacent-marine rows survive unchanged; only the drawing changed.
- The combined-v3 expected outputs were regenerated for the template and
  payload contract changes; all data products are byte-identical to before.
- Downstream consumers of `spatial_scope` see a new `highlight_country_codes`
  list (empty for global runs).
