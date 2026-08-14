# ADR-0003: Domain-aware country scope and separated confidence views

- Status: accepted
- Date: 2026-08-14

## Context

A named-country atlas previously treated its Natural Earth Admin-0 polygon as
the complete spatial scope. That was correct for land records, but it removed
publisher-labelled marine sediment and seawater observations before D2/D3 and
made a China atlas appear to have no sea evidence. Separately, the map exposed
the combined workflow-usability band as the prominent confidence label. A
traceable source with undeclared coordinate reference metadata could therefore
be presented as generically “low quality”.

## Decision

Requests carry first-class `land`, `inland_water`, and `marine` domains. Missing
domains are derived deterministically from requested media. Land and inland
water records remain subject to the frozen Admin-0 polygon. For a named-country
request that explicitly includes `marine`, only publisher-labelled marine
records within a bounded 600 km analysis buffer of the frozen boundary are
admitted. The buffer is a retrieval and analysis scope, not a territorial-sea,
EEZ, or sovereignty claim. Source routing, record filtering, spatial
sufficiency, D1 repair tasks, and D3 filtering use the same domain semantics.

D3 exposes four distinct dimensions: source evidence, analytical readiness,
spatial usability, and combined workflow usability. Source evidence is the
default confidence summary; spatial or workflow limitations remain visible as
separate review signals and are never relabelled as generic data quality.

## Consequences

- China and other coastal-country requests can include auditable sea evidence
  without admitting unrelated neighbouring-country land records.
- A missing marine domain is a machine-readable sufficiency gap and can drive a
  targeted source-discovery or adapter-repair task.
- Records with publisher-unreported CRS or positional uncertainty remain
  fail-closed for canonical spatial claims, while their source evidence can
  still be high.
- Existing request/execution reports remain schema-compatible; the new fields
  are additive, and newly generated reports always include them.
