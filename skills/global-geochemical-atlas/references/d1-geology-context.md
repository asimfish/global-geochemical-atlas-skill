# D1 independent geology context matching

## Boundary

This layer attaches map context to sample coordinates. It does not reinterpret
the source dataset's geology and never uses a source-reported unit to select a
map polygon. `geologic_unit_raw` remains the upstream statement;
`matched_geologic_unit` is a separate spatial result.

The result contract is `geology-context-result.schema.json`. Existing
`sample-v2` archives can receive the compatible fields through `sample_patch`;
the complete result, including `geology_map_source_id`, `match_status`, and all
candidates, remains in a companion JSONL until the shared archive schema is
extended by the integration branch.

## Macrostrat endpoints verified on 2026-08-07

- Point candidates: `https://macrostrat.org/api/v2/geologic_units/map?lat=...&lng=...`
- API metadata: `https://macrostrat.org/api/v2/meta`
- Carto vector tiles: `https://tiles.macrostrat.org/carto/{z}/{x}/{y}.mvt`
- Observed API version: `2.3.8`
- License: CC BY 4.0. Attribute Macrostrat and the original map provider exposed
  by each `source_id`.

Point mode is the evidence-preserving mode. A single candidate becomes
`matched`; multiple overlapping maps become `ambiguous`, with
`matched_geologic_unit=null`; no candidate becomes `unmatched`. The API's
`refs` object is retained for each source candidate.

Tile mode is the scalable mode. It downloads each occupied MVT tile once,
decodes the `units` layer locally, and performs point-in-polygon without an
external GIS dependency. Macrostrat documents `carto` as a visualization layer
that blends map priority and source scales. Therefore every tile result uses a
`carto_blended_zN` scale label and an explicit uncertainty. It is suitable for
coarse D1 context and candidate discovery, not for claiming a definitive local
geologic unit or map scale.

The default z5 level favors global coarse coverage. Higher zoom levels can
legitimately return empty tiles where Macrostrat has no local map at that
display scale. Carto tiles use Web Mercator; coordinates poleward of
±85.05112878° automatically fall back to point-candidate mode.

## Running the adapter

Online point audit:

```bash
python3 scripts/geology_context.py \
  --input samples.csv \
  --output geology-context.jsonl \
  --cache-dir /path/to/readable-cache \
  --mode point \
  --run-manifest geology-context-run.json
```

Scalable z5 matching:

```bash
python3 scripts/geology_context.py \
  --input unique-sample-locations.csv \
  --output geology-context.jsonl \
  --cache-dir /path/to/readable-cache \
  --mode tile \
  --zoom 5 \
  --run-manifest geology-context-run.json
```

Offline fixture replay:

```bash
python3 scripts/geology_context.py \
  --input fixtures/geology-context/audit-samples.csv \
  --output /tmp/geology-context.jsonl \
  --fixture-dir fixtures/geology-context/cache \
  --mode tile --zoom 5
```

Inputs may be CSV or JSONL and must contain `sample_id`, `latitude`, and
`longitude`; `geologic_unit_raw` is optional. The CLI streams input and output,
uses an atomic final rename, keeps only 128 decoded tiles in memory, and caches
raw responses by readable coordinates or z/x/y. It does not calculate or read
content digests.

Run the dedicated offline checks with:

```bash
python3 scripts/test_geology_context.py -v
```

## Audit result and full-run feasibility

The tracked fixture contains 30 cross-continent, mountain, coast, ocean,
boundary-pair, island, and polar samples. On 2026-08-07:

- point mode: 16 ambiguous, 10 matched, 4 unmatched, 0 failed;
- local z5 tile mode: 22 matched, 8 unmatched, 0 failed;
- all 22 tile selections had the same original `source_id` among the point API
  candidates;
- both source-reported geology strings remained unchanged.

At z5 the world contains at most 1,024 tiles, so 766,402 valid sample locations
can be processed with bounded network requests and streaming memory. Runtime is
then dominated by local point-in-polygon work and output size, not one HTTP call
per sample. Re-running reuses named tile files; an interrupted run leaves those
completed tiles reusable even though the final JSONL is atomically replaced.

Before running the complete D1 population, integration must provide a unique
sample-location export rather than the observation long table, otherwise the
same sample will be matched once per analyte. The integration branch must also
decide how the three new companion fields (`geology_map_source_id`,
`match_status`, `match_candidates`) enter the shared archive and SQLite schema.

Known upstream limitations:

- Macrostrat's `/defs/sources` route returned an empty data array during this
  verification; point-response `refs` and `source_id` remain usable, but full
  provider metadata enrichment needs a later live recheck.
- Carto provides no stable source scale and is explicitly unsuitable for
  scale-dependent decisions.
- Boundary distance is estimated from clipped MVT geometry and may be a lower
  bound near tile edges.
- Ocean or map-gap coordinates are valid `unmatched` results, not errors.
- A service, decode, or corrupt-cache failure is retained as `failed`; the
  adapter never fills a unit from place name, survey name, or source prose.
