# ADR-0003: Evidence debt and dual provenance

## Status

Accepted

## Context

A large atlas can pass aggregate checks while one requested medium has no
documented analytical method, most coordinates have no accuracy evidence, or
clickable source links disappear between D1, D2, and D3. A source-level home
page is also not a substitute for locating the exact record in the acquired
file. Filling missing metadata by inference would make the product look better
while weakening its scientific evidence chain.

## Driving factors

- Preserve unknown method and coordinate accuracy as explicit source facts.
- Prevent a method-rich medium from hiding another requested medium's debt.
- Keep exact record location and an official human-verification link as two
  independently auditable paths.
- Distinguish numeric coordinate representation from positional accuracy.
- Turn every repairable deficit into a deterministic D1 task instead of a
  vague low-quality label.

## Decision

1. Canonical rows retain `source_locator` for file/table/row location and
   `official_source_url` for the official data file, landing page, or DOI.
   Online research requires both on every row.
2. The record sidecar binds `official_source_url`; the source manifest derives
   its official URL and DOI allowlist from those hash-bound records. The output
   validator rejects summary links outside that allowlist.
3. Every requested medium requires at least 80% of its records to carry an
   explicit analytical method. Missing methods remain null with a reason and
   create a medium-specific D1 evidence-repair task.
4. Every row records whether coordinate uncertainty was source-reported. The
   decimal-place-derived metre value is named representation resolution and
   never increases positional confidence.
5. `sources_and_confidence.json` reports completeness counts per source and for
   the complete database. D3 embeds those exact facts and labels workflow low
   as high review priority, not low source quality.

## Consequences

- A partial but honest dataset can remain a checkpoint, but it cannot be a
  delivery-ready online result until its provenance and metadata debts close.
- Some authoritative historical datasets will stay method- or accuracy-limited;
  the system must find better-documented complementary evidence rather than
  invent metadata.
- A valid URL alone no longer proves provenance. It must survive the canonical
  row, record sidecar, source manifest, summary, and D3 display chain.
- Completeness is evidence presence, not measurement correctness or
  representativeness.
