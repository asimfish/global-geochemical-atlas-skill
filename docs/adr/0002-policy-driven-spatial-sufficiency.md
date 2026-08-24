# ADR-0002: Policy-driven, request-derived spatial sufficiency

## Status

Accepted

## Context

An atlas can contain many records while still showing only one dense region. A
single aggregate geography check also lets one element or medium hide an empty
filter view for another. Fixing those failures with named-country conditions
does not generalize to hidden requests, arbitrary WGS84 bounding boxes, or new
element and medium combinations.

The loop needs to turn the frozen request and the observations from the latest
round into a deterministic research queue. Country names such as China or
Russia may appear in regression tests, but they must not be control-flow inputs
or hard-coded coverage requirements.

## Driving factors

- Derive checks from `region`, requested elements, requested media, and actual
  canonical sample locations.
- Detect empty or geographically narrow element, medium, and element × medium
  map views instead of checking their union only.
- Apply a useful grid to global, country, and arbitrary bbox scopes without
  treating the grid as interpolation or statistical representativeness.
- Keep thresholds versioned, reviewable, and fail closed when policy drifts.
- Produce machine-readable D1 targets that identify both *where* and *which
  dimensions* need evidence.
- Remain dependency-free and compatible with the frozen Natural Earth asset.

## Candidate A: keep the current code and add more named checks

- Pros: smallest change and easy to tune for one observed failure.
- Cons: every new country, bbox, element, or medium can require another patch;
  aggregate coverage continues to hide empty filter views.

Rejected because it does not address the class of failure.

## Candidate B: externalize only the current numeric constants

- Pros: thresholds become auditable and can change without editing Python.
- Cons: the model is still aggregate and fixed at 5°; it cannot explain that a
  particular element or medium is spatially narrow and still skips small but
  meaningful regional scopes.

Rejected as an incomplete architectural fix.

## Candidate C: policy-driven coverage views over request-derived scopes

- Pros: one engine handles global, named-country, and bbox requests; an
  adaptive regional grid avoids both a global-resolution blind spot and an
  unbounded fine global grid; every requested filter view is audited; repair
  targets are generated from observed gaps rather than place-name branches.
- Cons: adds a versioned policy/schema and a richer report contract; thresholds
  require scientific review and regression evidence.

Accepted.

## Decision

Introduce one validated `spatial-sufficiency-policy.json` and one deterministic
spatial-policy module. The engine will:

1. resolve the frozen request with the shared spatial registry;
2. use the policy's 5° global grid or select the nearest multiplicative
   regional resolution from a bounded list according to scope extent, avoiding
   cutoff-driven over-refinement;
3. derive target coverage cells from the country polygon or bbox, retaining
   Natural Earth land ownership and deterministic open-ocean longitude zones;
4. audit canonical independent samples for `overall`, every requested
   `element`, every requested `medium`, and every requested
   `element_medium` view;
5. require global views to span multiple coverage zones (land macroregions or
   open-ocean sectors) as well as cells;
6. emit structured gaps with exact observed/target facts, required elements
   and media, and dynamically selected country backfill targets;
7. keep reported-only coordinates visible but outside the canonical pass.

The existing large-country and macroregion sentinels remain as an independent
global *overall* guard. Their country order continues to be derived from the
frozen land grid. They do not replace the per-view audit.

Unknown policy keys, unsupported versions, invalid fractions, non-dividing
grid sizes, or inconsistent thresholds fail closed before a research result is
declared sufficient.

## Stable interfaces

- Policy: `skills/global-geochemical-atlas/assets/spatial-sufficiency-policy.json`
  validated against
  `skills/global-geochemical-atlas/references/spatial-sufficiency-policy.schema.json`.
- Internal evidence: `read_database_coverage()` returns one de-duplicated
  spatial sample summary per `source_id + sample_identity_group` for the policy
  engine. This internal field is not a public atlas artifact.
- Loop report: `sufficiency.criteria.spatial_dimension_coverage` contains the
  complete audit; `sufficiency.discovery_gaps.spatial_dimension_gaps` is the
  machine-readable agent/D1 research queue.
- Backward compatibility: the existing overall global country targets and
  regional gap remain present while consumers migrate to the generic queue.

## Consequences

- A large European archive cannot make a global Cu view pass if Cu remains
  geographically confined, even when As or total row counts are broad.
- Marine water and sediment points count in auditable ocean zones instead of
  being forced into a land country; the separate overall land sentinel still
  prevents an ocean-only bundle from claiming a complete global atlas.
- An arbitrary regional bbox is evaluated with the same policy as a named
  country; place names do not select algorithms.
- Truly tiny scopes for which the coarsest permitted audit has fewer than two
  land-centre cells remain explicitly unassessable and use exact point/bbox
  validation. The report distinguishes that state from a pass.
- Passing remains a minimum evidence-bearing coverage statement, never a claim
  of uniform or representative sampling.
