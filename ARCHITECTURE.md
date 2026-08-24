# Architecture

The production submission is the single Skill under
`skills/global-geochemical-atlas/`. Its runtime is dependency-free Python and
uses four explicit boundaries:

1. request planning resolves a typed task and frozen spatial scope;
2. D1 routes and acquires only evidence-qualified sources within one deadline;
3. D2 preserves raw observations, standardizes, quality-controls, and screens
   anomalies within declared comparable groups;
4. D3 renders only D1/D2 outputs and never invents scientific evidence.

The public planning entry point is `scripts/task_router.py`; it freezes the task
contract, applies the official deadline, and selects the minimum stable executor.
`scripts/run_atlas_request.py` is the single-round D1–D3 executor, while
`scripts/run_self_correction_loop.py` owns explicitly authorized multi-round
research. Stage scripts remain independently reusable, but they do not own
cross-stage policy. Canonical interchange remains UTF-8 CSV plus versioned
JSON/GeoJSON sidecars so the complete runtime works without installing
third-party packages.

Research completion is governed by a separate, versioned sufficiency boundary:
`run_self_correction_loop.py` de-duplicates physical samples and delegates
request-derived spatial checks to `spatial_sufficiency.py`. Numeric thresholds
live in the schema-bound `assets/spatial-sufficiency-policy.json`; neither the
source router nor the visualization layer may silently weaken them. The engine
audits the overall map and every requested element, medium, and element × medium
view, then emits machine-readable where-plus-dimension D1 research targets.

Major structural decisions are recorded in
[ADR-0001](docs/adr/0001-evaluation-critical-runtime-and-request-boundaries.md)
[ADR-0002](docs/adr/0002-policy-driven-spatial-sufficiency.md), and
[ADR-0003](docs/adr/0003-domain-aware-country-scope-and-confidence-views.md).
