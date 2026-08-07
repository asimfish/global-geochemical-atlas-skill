# Architecture

The production submission is the single Skill under
`skills/global-geochemical-atlas/`. Its runtime is dependency-free Python and
uses four explicit boundaries:

1. request planning resolves a typed task and frozen spatial scope;
2. D1 routes and acquires only evidence-qualified sources within one deadline;
3. D2 preserves raw observations, standardizes, quality-controls, and screens
   anomalies within declared comparable groups;
4. D3 renders only D1/D2 outputs and never invents scientific evidence.

The public orchestration entry point is `scripts/run_atlas_request.py`.
Stage scripts remain independently reusable, but they do not own cross-stage
policy. Canonical interchange remains UTF-8 CSV plus versioned JSON/GeoJSON
sidecars so the complete runtime works without installing third-party packages.

Major structural decisions are recorded in [ADR-0001](docs/adr/0001-evaluation-critical-runtime-and-request-boundaries.md).
