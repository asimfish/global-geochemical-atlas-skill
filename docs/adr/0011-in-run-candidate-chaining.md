# ADR-0011: In-run candidate chaining and self-checkable role payloads

## Status

Accepted (supersedes the redirect terminal of ADR-0009)

## Context

Two complete runs (world and China) executed the pilot and literature roles
correctly and then stopped at the scientific opportunity gate: the world pilot
returned `supported_null` against a `weak_frontier_position` literature
verdict, the China pilot returned `unsupported_inputs`. Both were honest
verdicts, but neither run went anywhere afterwards. Three defects combined:

1. The fallback queue was always empty. `_build_research_contracts` filtered
   candidates on a top-level `paper_track` key, while the discovery document
   stores it under `research_readiness.paper_track`. The world atlas had 27
   untried empirical candidates and China had three; the redirect designed in
   ADR-0009 never fired once.
2. Even when it fires, the ADR-0009 redirect ended the run at
   `redirected_next_candidate` with a `next_request.json`, so the agent host
   had to notice the terminal and start a new run by hand. That is a human
   step in disguise.
3. The China T6 template asked for a physical "leachable share", which no
   archive can identify without leachate or residue mass recovery, so every
   T6 pilot must fail closed regardless of element. Separately, both runs
   burned several agent round trips on payload details the packets stated
   only in prose (artifact paths relative to the run root, the exact
   `retrieved_at` field, the `search_coverage` shape, the frontier enum, the
   per-claim `artifact_sha256`).

## Decision drivers

- After the single direction selection the run must reach a packaged
  deliverable or an honest `needs_research_redirection` without a human step.
- A failed direction is evidence, not garbage: archive it hash-bound.
- Do not spend two fresh agent sessions per element on a data limitation that
  is already known to apply to every sibling of a failed template.
- Roles should be able to check a payload against the controller's exact
  contract before they submit.

## Decision

1. **Queue built from `research_readiness.paper_track`, ordered for
   diversity.** `rank_fallback_candidates` lists every untried empirical
   candidate round-robin across template types (types ordered by their best
   discovery rank, the selected candidate's own type rotating last; frozen
   rank inside a type). Exhausted candidates never re-enter. The queue
   document is `gga-candidate-fallback-queue-v2` and carries each
   candidate's `data_signature`.
2. **Gate failures continue inside the same run.** `_prepare_candidate_fallback`
   archives every attempt-scoped entry (contracts, packets, agent outputs,
   revisions, receipts) under `attempts/attempt-NN-<candidate>/` with a
   hash-bound `attempt_manifest.json`, rebuilds the contracts and first-wave
   packets for the next candidate at the run root and sets the run back to
   `awaiting_agents`. State schema v4 adds `attempt`, `attempt_history` and
   `exhausted_candidate_ids`; the `redirected_next_candidate` terminal and
   `next_request.json` are removed. Invocation IDs consumed by archived
   attempts stay reserved.
3. **Dead-end siblings are exhausted together.** When the failed pilot outcome
   is `unsupported_inputs`, every queued candidate with the same data
   signature (template type, medium and sample-type pairing) is exhausted as
   well; `supported_null` and weak-frontier failures keep siblings, because a
   different element can still carry an effect or a stronger frontier.
4. **T6 asks the identifiable question.** The paired-fraction template now
   frames the operational paired concentration contrast (partial / bulk
   log-ratio per physical sample) and states explicitly that no leachable
   mass share is claimed.
5. **Self-checkable payloads.** First-wave packets embed
   `required_output.payload_contract` (exact keys, enum values, retrieval
   field name, search-coverage shape, artifact path rule), and
   `auto_research.py submit --validate-only` runs the identical acceptance
   checks without recording a result or advancing the run.

## Consequences

- A China run that fails T6 for Cr no longer wastes Cu, Pb and Zn pilots on
  the same unidentifiable estimand; with the reframed template the Cr pilot
  itself can now return `supported_effect` or `supported_null` on the 22
  exact-identifier pairs it already analysed.
- A world run whose paired-layer Cu question has close prior art moves to a
  method-artifact or cross-media candidate next instead of re-running the
  same template for Ni, Zn and As first.
- Attempt archives make the audit trail longer but complete: every rejected
  direction keeps its pilot statistics, literature verdict and gate receipt.
- Hosts and audits that polled for `redirected_next_candidate` must read
  `attempt_history` instead; the state schema bump makes stale readers fail
  loudly.
