# Pitch claims acceptance matrix

This document converts the public pitch at
`https://asimfish.github.io/global-geochemical-atlas-demo/slides.html` into
release-blocking, observable requirements.  A slide or prose statement is not
evidence of implementation.  Each row closes only when the named artifact and
test both exist.

## Scope and source snapshot

- Audited public deck: 22 slides, fetched 2026-08-24, SHA-256
  `2573baf166cf2c38c9c47d867dbd6f5be9f8eff652fe932a0c7d68709f2a6e2c`.
- Relevant slides by displayed order: 10 mechanism overview, 11 loop state
  machine, 12 iteration ledger, 13 adversarial source audit, 14 claim ledger,
  17 temporal atlas, and 18 atlas-to-paper research workflow.
- The four supplied screenshots are presentation evidence only.  Runtime
  artifacts and tests below are the acceptance evidence.

## Release-blocking acceptance criteria

| ID | Public promise | Observable acceptance | Evidence location |
|---|---|---|---|
| LOOP-01 | Failed validation is registered, routed, rerun, and compared without rewriting history. | Every repair has a stable item ID, action class, previous/current hashes, and terminal disposition; immutable round directories remain byte-addressable. | `iteration_backlog.csv`, `loop_report.json`, `rounds/`, component loop tests |
| LOOP-02 | Cross-round memory improves routing without biasing the current evaluation. | Memory may rank next acquisition targets, but no prior verdict, review prose, or prior agent output appears in a current evaluator context manifest.  Changing only prior memory leaves current evaluator packet hashes unchanged. | `agent_audit.py`, context manifests, independence regression |
| AGENT-01 | Scout, challenger, and judge are independent layers. | Scout and challenger run from separate allowlisted workspaces and invocation IDs.  Challenger receives the submitted candidate facts, never scout scratch/reasoning.  The judge is deterministic code and accepts no model-authored score. | adversarial audit bundle and schema; adversarial component tests |
| AGENT-02 | No role can approve its own work. | Role identity, model family, invocation ID, packet hash, result hash, and allowed-input hashes are recorded.  Reused invocation IDs, role substitution, unknown inputs, or a result from the wrong packet fail closed. | agent result envelopes and negative tests |
| HASH-01 | Every reported result is one-to-one with its evidence. | Every reportable claim records its typed value, unit, semantic boundary, exact artifact and locator/recompute method, artifact SHA-256, canonical claim SHA-256, and verification status. | `research_delivery_receipt.json.claim_ledger` and validator |
| HASH-02 | Tampered numbers or evidence are blocked. | Changing a value, locator, artifact, or result envelope makes validation fail.  The validator independently recomputes fixed facts instead of trusting report prose. | claim-ledger tamper tests |
| VIS-01 | Temporal evolution is an option inside the atlas, not a separate product experience. | `interactive_map.html` contains a top-level temporal view with the complete offline temporal app embedded in the same file; it has no `src`/network dependency on `temporal_map.html`. | D3 template markers, HTML validator, browser smoke |
| VIS-02 | Existing links remain usable. | `temporal_map.html` remains a byte-generated compatibility artifact, but primary navigation opens the embedded view. | output validator and compatibility test |
| AUTO-01 | Users can continue research after atlas generation. | The atlas contains an Auto-Research view that creates a typed request against the served atlas snapshot and starts a local research run; static-file use can export the identical request without pretending a job started. | `serve_atlas_research.py`, `auto_research.py`, UI integration test |
| AUTO-02 | Auto-Research is a real resumable workflow. | The state machine materializes a frozen snapshot, research cohorts, deterministic topic candidates, selected hypothesis, pilot contract, evidence-backed literature/citation queue, paper spine, typeset manifest, figure contract, claim audit, a fresh registry-backed citation audit whenever the manuscript changes, deterministic publication lint on every submitted render, independent review, and immutable revision rounds routed to the roles that own the failing gates while untouched work carries forward by hash. It resumes from the first incomplete gate, serializes parallel role submissions through a state lock, caps automatic revision at three rounds, never overwrites an accepted result, and rejects paper-eligible pilot outcomes at the entry gate unless they carry typed scientific-rigor evidence (site identity, spatial-dependence-aware inference, hold-out replication, deterministic regeneration). After the one-time direction selection the run terminates autonomously: passing review auto-publishes a hash-bound `camera_ready` package, exhausted budgets auto-publish `draft_with_disclosed_findings` with every open finding listed, and a failed opportunity gate archives the attempt and continues the same run on the next untried empirical candidate (type-diverse order, dead-end siblings exhausted together); when none remains the run still ends with a graded deliverable — the best executed pilot written up with its frontier weakness disclosed, or a reviewed evidence report when no direction could execute a pilot. | research state/receipt schemas and end-to-end fixture run |
| AUTO-03 | Paper and figure agents cannot invent results. | All numerical manuscript claims must resolve through the atlas claim ledger or a hash-bound pilot result; unsupported claims block drafting/review.  Figure specs cite the same claim IDs and data hashes. | claim/citation/figure manifests and negative tests |
| AUTO-04 | Review does not inherit previous-round framing. | Each review receives only the current cycle's canonical artifacts and venue/rubric metadata through a fresh packet. Previous review prose, structured feedback, prior artifacts and executor summaries are excluded from the reviewer packet (revision executors may receive the structured feedback). Same-family review is labelled provisional inside the receipt, and the publication manifest grade records honestly which gates the package cleared. | review context manifests and receipt status |
| OSS-01 | The published method is safe to publish. | The skill's schemas, state machine, contracts, prompts and tests are original to this repository and governed by the root MIT license; dataset and basemap licenses remain source-specific and are tracked per source. | root `LICENSE`, per-source license evidence in the source manifest, security/provenance review |

## Completion rule

The project may call these pitch promises implemented only when every row above
has current passing evidence.  Unit tests, schema validation, and hashes prove
specified mechanics and byte identity; they do not prove scientific truth,
causality, publication merit, or external model independence.  Those remaining
boundaries must stay visible in the generated receipts and UI.

## Current verification record

Verified on 2026-08-24 against the working release tree:

- `component_test.py --component all`: PASS, 604/604 checks
  (D1 447, D2 62, D3 95).
- `self_test.py`: PASS, 76/76 checks.
- `run_self_correction_loop.py --self-test`: PASS, 117/117 checks.
- `mypy --config-file mypy-critical.ini`: PASS, 0 issues in 9 critical source
  files.
- Ruff lint and format checks: PASS for the release tree.
- AI4S competition structure/static validator: PASS.

This record closes every row in the matrix at the implementation and
regression-test level.  It does not change the scientific and human-review
boundaries in the completion rule.
