# ADR-0007: Targeted revision routing, publication lint, and parallel-safe submission

## Status

Accepted

## Context

ADR-0006 made publication evidence falsifiable: retrieval-backed literature, a
registry-audited reference list, a typeset manifest, and design-audited
figures. Three loop-mechanics weaknesses remained. First, every failed gate
reopened both the manuscript and figure roles wholesale, so a single
figure-quality finding forced a full manuscript rewrite and a redundant
citation re-audit of an unchanged reference list, spending revision rounds on
roles that had nothing to fix. Second, print readiness was self-attested: the
figure role reported its own render inspection, and nothing machine-checked
that a submitted SVG kept text above a readable size, that a PNG carried print
resolution, or that a typeset PDF actually contained a page. Third, roles in
one wave are designed to run as independent parallel sessions, but state
transitions were not serialized, so concurrent submissions could interleave
ledger writes.

## Decision drivers

- Keep the deterministic controller, hash-bound packets, fresh sessions,
  immutable revisions, and human publication approval unchanged.
- Route rework to the role that owns the failing gate, and never let an
  untouched role inject new artifacts into a cycle it was not asked to join.
- Preserve full provenance when work carries forward: an untouched role's
  newest accepted result stays bound by its original hashes.
- Reject print-unreadable artifacts deterministically at submission instead of
  trusting executor self-review, while leaving aesthetic judgement to the
  render-inspect-revise loop and the a6 review gate.
- Make the documented parallelism of wave roles actually safe on disk.

## Decision

1. **Gate ownership routing.** Each quality gate maps to owner roles:
   citation-audit and a3/a4/a5 failures reopen only `manuscript_writer`, a6
   reopens only `figure_designer`, and shared-evidence gates a1/a2/a7 reopen
   both. Every feedback task records `owner_roles`; the revision cycle writes
   packets and accepts submissions only for the reopened set. Unknown gates
   fail safe by reopening both roles.
2. **Hash-bound carry-forward.** For a role outside the reopened set, the
   controller resolves the newest accepted result across cycles and binds its
   artifacts into the citation-audit and reviewer packets unchanged. A
   revision that touches the manuscript repeats the fresh citation audit; a
   figure-only revision carries the verified audit receipt forward instead of
   re-auditing an identical reference list, and fails closed if that receipt
   is not fully verified.
3. **Publication lint.** A deterministic, stdlib-only linter runs at
   submission over every declared SVG/PNG/PDF of the manuscript and figure
   roles: vector text below a 4.5 pt print-equivalent floor (scaled by canvas
   width against a 468 pt column), rasters narrower than 1000 px, PDFs without
   a page object or end-of-file marker, and non-well-formed SVGs reject the
   submission. The floors are disclosed in the quality contract
   (`figure_storyboard_gate.typography_floor`), alongside manuscript layout
   rules (`typesetting_gate.layout_rules`) that the a5/a6 reviewer gates
   enforce lexically.
4. **Serialized state transitions.** All submissions acquire an exclusive
   `state.lock` file lock around the read-validate-write-advance sequence, so
   wave roles can run genuinely in parallel while ledger writes stay
   serialized.

## Consequences

- A figure-evidence finding now costs one figure revision, not a manuscript
  rewrite plus a redundant citation audit, so the three-round budget goes to
  real rework.
- Unreadable or structurally broken deliverables never reach the reviewer;
  what the a6 gate scores is already print-viable.
- Reviewer packets may reference artifacts from earlier cycles; provenance
  stays intact because every binding is by content hash.
- The lint is a floor, not a style engine: text converted to paths and scale
  transforms are not measured, and layout aesthetics remain a review concern.
