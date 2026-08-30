# ADR-0009: Autonomous publication and candidate fallback

## Status

Accepted

## Context

Before this change every successful run stopped at `awaiting_human_approval`
and every exhausted revision or citation-repair budget stopped at
`needs_human_intervention`. A gate failure on the selected direction stopped
at `needs_research_redirection` and waited for a new human request. All three
terminals required the user to return and act. The operating model asked for
the opposite: the user picks a research direction once, and the run must end
with a packaged deliverable — a full paper when the gates pass, an honestly
labeled draft when the budget runs out, or an automatic retarget to the next
viable candidate when the chosen direction cannot support a paper. The
scientific gates themselves (a1–a7, citation audit, publication lint,
front-loaded pilot rigor) were already deterministic and adversarial; only the
final decision to package, disclose, or retarget still depended on a human.

## Decision drivers

- One human decision per run: selecting the direction. Everything after is
  controller-owned.
- Autonomy must not weaken any evidence gate. Removing the approval stop may
  not remove or relax a single scientific check.
- Failure honesty: a package produced from an exhausted budget must disclose
  every open finding rather than pretend to be camera-ready.
- Fallback must be finite and forward-moving: retargeting may only descend
  the frozen candidate ranking, never loop back or invent directions.

## Decision

1. **Two publication grades replace human approval.** When the independent
   review passes every gate, the controller packages the deliverables at grade
   `camera_ready` and ends at `completed_published`. When the three-round
   revision budget or the citation-repair budget is exhausted, it packages at
   grade `draft_with_disclosed_findings` and ends at `completed_with_findings`,
   copying every unresolved feedback item verbatim into the manifest.
2. **The publication package is hash-bound.** `_finalize_publication` verifies
   the recorded SHA-256 of every packaged artifact against the bytes on disk
   before copying it under `publication/`, then writes
   `publication_manifest.json` whose own `manifest_sha256` covers the manifest
   body. The state's `publication` block repeats the grade, package directory,
   manifest hash, packaged cycle and disclosed-finding count.
3. **Gate failures descend a frozen fallback queue.** At contract-build time
   the controller freezes `candidate_fallback_queue.json`: the empirical
   candidates ranked after the user's selection (all of them for a
   user-defined question). When the scientific-opportunity gate fails, the
   controller pops the next entry, records it in the state `fallback` block,
   writes a ready-to-run `next_request.json` preserving the original language
   and venue, and ends at `redirected_next_candidate`. An empty queue ends at
   `needs_research_redirection` — the controller never fabricates a direction.
4. **State schema v3 encodes the new terminals.**
   `gga-auto-research-state-v3` removes `awaiting_human_approval` and
   `needs_human_intervention`, adds `completed_published`,
   `completed_with_findings` and `redirected_next_candidate`, fixes
   `human_approval_required` to `false`, and types the `publication` and
   `fallback` blocks. The independent review receipt v2 carries an explicit
   `publication_decision` instead of a human-approval flag.

## Consequences

- A run started from one selection now always terminates in a packaged
  deliverable or a machine-readable retarget; no terminal state waits for a
  human decision.
- Same-family review remains labeled `provisional_same_family` inside the
  receipt; autonomy changes who presses publish, not what the receipt claims.
- A `draft_with_disclosed_findings` package can be shipped, criticized, or
  discarded — the disclosure list makes its weaknesses explicit instead of
  hiding them behind a stalled state.
- Downstream tooling that polled for `awaiting_human_approval` must migrate
  to the v3 terminals; the schema bump makes stale integrations fail loudly
  instead of silently misreading the state.
