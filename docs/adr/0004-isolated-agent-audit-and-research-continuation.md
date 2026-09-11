# ADR-0004: Isolated agent audit, claim binding, and research continuation

## Status

Accepted

## Context

The public pitch promises a validation/repair loop, a three-layer adversarial
source audit, result-level SHA-256 traceability, a temporal view inside the
atlas, and a user-selectable atlas-to-paper workflow.  At the time of this
decision, the repository already had immutable loop rounds, deterministic
D1-D3 processing, a standalone temporal artifact, research cohort/candidate
builders, and a delivery receipt, but lacked enforceable role isolation,
one-to-one report-claim bindings, an in-atlas temporal view, and a resumable
research controller.  The decisions below are now implemented by the stable
interfaces and release gates in this ADR.

## Driving factors

- Preserve the single production Skill and the D1 -> D2 -> D3 ownership model.
- Run in Python 3.10+ with no third-party runtime dependency or embedded model
  credential.
- Keep scientific computation deterministic and make model output untrusted.
- Prevent previous reviews, hidden scratch, and cross-round memory from coaching
  a current evaluator.
- Keep the main atlas self-contained and usable offline.
- Make browser-triggered research safe from path traversal, shell injection,
  cross-origin requests, replay, and arbitrary publication.
- Preserve backward compatibility for existing temporal links and atlas output
  consumers.

## Decision 1: three-layer adversarial source audit

### Option A: three personas in one accumulated agent conversation

- Pros: smallest implementation and low orchestration overhead.
- Cons: all roles inherit the same narrative, previous verdicts, and hidden
  framing; independence cannot be audited.

### Option B: content-addressed role packets, separate workspaces, deterministic judge

- Pros: exact context is inspectable; prior memory can be excluded; outputs are
  bound to roles and packets; the final score is reproducible code rather than
  a model grading itself.
- Cons: the host must actually launch a fresh agent/session for scout and
  challenger; filesystem isolation is evidence isolation, not an operating-
  system sandbox.

### Option C: replace all roles with one deterministic source scorer

- Pros: completely reproducible and simple.
- Cons: loses adversarial discovery and does not implement the promised agent
  mechanism.

### Decision

Choose Option B.  The scout receives the frozen current gap and source facts.
The challenger receives the submitted candidate facts and rubric, but never
the scout's scratch/reasoning.  The deterministic judge receives only the two
validated result envelopes plus the frozen scoreboard.  Cross-round memory may
prioritize which gap is audited next; it is not an evaluator input.  Every role
packet and result is canonical JSON with an SHA-256 envelope and a unique
invocation ID.  A different model family is recommended for challenger review;
same-family output remains explicitly provisional rather than being presented
as independent ground truth.

## Decision 2: result trust binding

### Option A: one hash manifest for complete files

- Pros: already close to the current delivery receipt.
- Cons: cannot answer which byte range or recomputation supports a reported
  number, and a correct file hash can coexist with unsupported prose.

### Option B: typed claim ledger over content-addressed artifacts

- Pros: each number/statement has an exact value, semantic boundary, locator or
  recompute method, artifact hash, and canonical claim hash; tampering is
  independently detectable.
- Cons: supported claim types need deterministic extractors.

### Decision

Choose Option B.  Embed the ledger in the existing
`research_delivery_receipt.json` so it is covered by the delivery protocol
without adding another production deliverable name.  The validator recomputes
the fixed claim set from CSV/JSON and verifies every binding.  Hashes prove byte
identity and association only; the receipt states that they do not prove
measurement correctness or causal interpretation.

## Decision 3: temporal view composition

### Option A: keep a navigation link to `temporal_map.html`

- Pros: no larger main file and no UI change.
- Cons: contradicts the product requirement that temporal evolution is a view
  of the atlas itself.

### Option B: duplicate the temporal renderer into the main atlas DOM

- Pros: one DOM and potentially shared controls.
- Cons: creates two implementations of a large renderer and high regression
  risk.

### Option C: embed the generated temporal app as an in-file `srcdoc` view

- Pros: one downloadable `interactive_map.html`, no external dependency, one
  temporal implementation, and backward compatibility through the existing
  standalone artifact.
- Cons: increases the main HTML size and uses an iframe boundary for the view.

### Decision

Choose Option C.  `build_interactive_map.py` accepts the already generated
temporal document, base64-embeds it, and exposes a top-level `temporalView`.
The iframe has `srcdoc`, a restrictive sandbox, and no `src`.  The compatibility
`temporal_map.html` remains generated but is no longer primary navigation.
The combined file remains under the existing 100 MB limit or fails closed.

## Decision 4: Auto-Research execution boundary

### Option A: a static UI that only downloads a prompt/request

- Pros: works on GitHub Pages and has no local service risk.
- Cons: it cannot truthfully report that a research run started.

### Option B: call an LLM provider directly from browser JavaScript

- Pros: immediate experience.
- Cons: exposes credentials, couples the Skill to one provider, weakens
  provenance, and creates an uncontrolled network/execution boundary.

### Option C: localhost controller plus model-neutral, hash-bound agent packets

- Pros: the button starts a real local run; the server owns the fixed atlas
  root; no model credential enters the page; Codex/OpenCode/other hosts can
  execute the same typed packets; deterministic stages remain testable offline.
- Cons: GitHub Pages can only export the identical request until the user starts
  the local controller; model-authored stages still require a compatible agent
  host.

### Decision

Choose Option C.  `auto_research.py` owns a resumable state machine and only
accepts an atlas directory that passes the existing output/delivery gates.
`serve_atlas_research.py` binds loopback, fixes the atlas and research roots at
startup, validates Origin/Host/content type/body size/nonces, and invokes Python
APIs without a shell.  The browser submits a typed question and candidate
choice only.  Agent stages use file-exchange packets whose allowlisted inputs
and outputs are hashed.  Missing external agents produce `awaiting_agent`, not
a fabricated paper.  Static-file mode exports the same request and clearly says
that no job was started.

## Stable interfaces

- Agent audit: versioned context manifest, role-result envelope, deterministic
  judge receipt, and `AgentRoleBackend` protocol.
- Claim ledger: `atlas-report-claim-ledger-v1`, embedded in the research
  delivery receipt and validated by recomputation.
- Main visualization: one `interactive_map.html` with `temporalView` and
  `autoResearchView`; `temporal_map.html` remains a compatibility artifact.
- Auto-Research: typed request, append-only events, resumable state, role
  packets, paper spine, figure contract, review receipt, and feedback tasks.
- Canonical formats remain UTF-8 CSV and canonical JSON/GeoJSON.

## Impact

- D1 owns candidate source facts and admission; the adversarial packet layer
  cannot admit a source by itself.
- D2 continues to own all scientific numbers; agent roles may propose questions
  and prose but never calculate or overwrite canonical results.
- D3 embeds the temporal app and research launcher without acquiring evidence.
- Auto-Research consumes immutable D1-D3 outputs and routes new acquisition
  gaps back to D1 rather than editing the frozen atlas.
- Existing output filenames remain stable.  Generated main HTML files grow, so
  the combined-size gate and browser regression are release blockers.
