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

The post-atlas trust and research boundary has three additional rules.  Agent
source discovery uses content-addressed, role-specific context packets: scout
and challenger workspaces are separate, and a deterministic judge alone applies
the source-admission scoreboard.  Prior-run memory can schedule the next target
but is excluded from the current evaluator context.  The formal delivery
receipt contains a claim ledger that independently recomputes every supported
reporting fact and binds it to its artifact hash and locator.

D3 owns one primary product surface: `interactive_map.html`.  The complete
temporal application is embedded as an offline top-level view; the standalone
`temporal_map.html` is a generated compatibility copy, not a second product.
The optional Auto-Research controller is downstream-only: it validates and
freezes D1-D3 outputs, materializes model-neutral agent packets and resumable
paper/figure/review state, and routes any new data need back to D1.  It never
mutates the atlas snapshot or performs D2 calculations.  The structural choice,
alternatives, security boundary, and interfaces are recorded in
[ADR-0004](docs/adr/0004-isolated-agent-audit-and-research-continuation.md).
The downstream research controller additionally separates a scientific
opportunity loop from the paper-production loop: only an executed, frontier-
supported result may enter writing and figure generation.  This fail-closed
quality boundary and its stable reviewer rubric are recorded in
[ADR-0005](docs/adr/0005-auto-research-scientific-quality-loop.md).
Publication evidence is controller-enforced as well: literature results carry
retrieval evidence and search coverage, manuscripts deliver a typed reference
list plus a spine-complete typeset manifest, figures record design candidates
and an editable source, and a dedicated fresh citation-audit stage verifies
the full bibliography against public registries before every review.  These
contracts are recorded in
[ADR-0006](docs/adr/0006-citation-audit-and-publication-evidence-loop.md).
The revision loop itself is targeted and parallel-safe: failed gates reopen
only their owner roles while untouched work carries forward by content hash, a
deterministic publication lint rejects print-unreadable SVG/PNG/PDF artifacts
at submission, and all state transitions serialize through a file lock so wave
roles can run concurrently. This loop mechanics layer is recorded in
[ADR-0007](docs/adr/0007-targeted-revision-routing-and-publication-lint.md).
Scientific rigor is front-loaded into the entry contracts rather than left to
review: the frozen pilot contract demands typed evidence of site identity,
spatial-dependence-aware inference, hold-out replication and deterministic
regeneration before any paper-eligible outcome is accepted, and the figure
contract pins the spatial-pattern role to empirical values rather than data
availability. This is recorded in
[ADR-0008](docs/adr/0008-front-loaded-scientific-rigor-contract.md).
Selecting a direction is the only human decision: passing runs auto-publish a
hash-bound `camera_ready` package, exhausted revision or citation budgets
auto-publish a `draft_with_disclosed_findings` package that lists every open
finding, and a failed opportunity gate descends a frozen empirical-candidate
fallback queue with a ready-to-run next request instead of waiting for a new
instruction. This autonomy layer is recorded in
[ADR-0009](docs/adr/0009-autonomous-publication-and-candidate-fallback.md).
On the atlas side, a named-country study frame (`highlight_country_codes`) is
drawn independently of record clipping, regional navigation is locked to the
fitted frame in both map templates, and publisher-documented dataset collection
windows form an explicit second dated tier whose per-source reasons ship inside
the temporal payload. This is recorded in
[ADR-0010](docs/adr/0010-study-frame-and-dataset-collection-windows.md).
When a direction fails the scientific opportunity gate, the run does not stop:
the attempt is archived hash-bound under `attempts/`, the next untried
empirical candidate (round-robin across template types, dead-end siblings
exhausted together) gets fresh contracts and first-wave packets, and the same
run returns to `awaiting_agents`; first-wave packets carry a machine-precise
payload contract and roles can dry-run submissions with `--validate-only`. This
is recorded in [ADR-0011](docs/adr/0011-in-run-candidate-chaining.md).
Every run ends with a graded deliverable: once no untried candidate remains,
the best executed pilot is restored and written up with its frontier weakness
disclosed (grade capped at `draft_with_disclosed_findings`), or — when no
direction could execute a pilot — the run writes a reviewed evidence report
(`evidence_report`). This is recorded in
[ADR-0012](docs/adr/0012-every-run-ends-with-a-graded-deliverable.md).
The deliverable itself is held to a typesetting contract: the controller installs a
paper kit (fixed LaTeX style, skeleton, controller-generated claim ledger, seeded
bibliography) and a figure kit (dependency-free SVG toolkit with offline basemaps,
same-size PDF/PNG renderer) into every manuscript wave, and the gate rejects
manuscripts that leave the kit (inline claim tags, fixed figure heights, figures
behind the bibliography, non-TeX PDFs) and figures whose renders are clipped or
whose spatial panels lack a geographic frame. This is recorded in
[ADR-0013](docs/adr/0013-typesetting-and-figure-quality-contract.md).
