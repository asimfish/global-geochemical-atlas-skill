# ADR-0005: Scientific opportunity gate and evidence-first paper loop

## Status

Accepted

## Context

The first end-to-end Auto-Research runs proved the packet, hash, revision, and
review-isolation mechanisms, but they also exposed a different failure class.
The controller copied row-level atlas data into the frozen run and then omitted
those files from the pilot packet.  Both pilots therefore returned an
input-sufficiency or acquisition-plan status.  The controller nevertheless
advanced to manuscript and figure generation, so repeated review improved the
presentation of a weak research premise instead of finding a stronger supported
question.

The public worked example is materially different: it contains executed paired
analyses, effect sizes, uncertainty, spatial results, sensitivity checks, and
independent comparisons.  Byte identity, compliant prose, and legible figures
are necessary but cannot substitute for those scientific ingredients.

## Decision drivers

- Preserve frozen inputs, role isolation, claim hashes, and human publication
  approval.
- Let a pilot use the exact frozen row-level files needed for analysis without
  exposing unrelated chat, review prose, credentials, or mutable atlas paths.
- Prevent an unsupported or acquisition-only pilot from becoming a paper by
  default.
- Make reviewer gates stable across revisions; an agent may not redefine what
  `a1` through `a7` mean.
- Evaluate scientific opportunity and visual evidence, not only correctness and
  formatting.
- Keep new data acquisition in D1 and keep the atlas immutable.

## Options

| Option | Scientific yield | Integrity | Cost | Failure mode |
|---|---:|---:|---:|---|
| A. Add more writer/reviewer revisions | low | high | low | Polishes the same weak premise |
| B. Add a pre-paper opportunity gate, bind row data, and fail closed | high | high | medium | May stop without a paper when evidence is insufficient |
| C. Let agents browse, acquire, analyze, and publish in one unconstrained loop | variable | low | high | Unbounded provenance and authority |

Choose Option B.  A truthful no-paper outcome is preferable to a polished paper
without a scientific result.

## Decision

Auto-Research uses two nested loops.

### Outer scientific opportunity loop

1. Build deterministic candidates and label their paper readiness.
2. Freeze one selected hypothesis and an explicit quality contract.
3. Give the pilot a content-addressed projection containing the row-level
   geochemistry, cohort definitions, exclusions, context, and source/QC summary.
4. Run pilot and primary-literature roles in fresh, separate sessions.
5. Admit the inner paper loop only when the pilot reports an executed supported
   effect or an executed scientifically interpretable null result and the
   literature assessment supports a real frontier contribution.
6. Route missing inputs, acquisition-only topics, invalid analyses, and weak
   frontier positions to `needs_research_redirection`.  Do not create writer or
   figure packets.  A new candidate uses a new content-addressed run; a data gap
   returns to D1.

### Inner evidence-to-paper loop

1. Require a contribution map from every manuscript and an evidence storyboard
   from every figure package.
2. Require data-bearing primary, spatial, and robustness figures for an empirical
   article. A generic methods diagram cannot satisfy those roles. Each figure
   binds distinct SVG/PDF/PNG artifacts and records inspection findings and
   applied revisions; the controller verifies paths, hashes, and file signatures.
3. Review against one controller-owned seven-gate contract:
   evidence integrity, scientific validity, novelty/significance, frontier/venue
   fit, manuscript argument, figure evidence/visual quality, and reproducible
   release integration.
4. Require named gates, evidence, and thresholded scores.  A revision reviewer
   receives the same quality contract and cannot redefine a gate.
5. Keep revisions immutable and reviewers fresh.  Same-model-family review
   remains provisional; human approval remains mandatory and publication remains
   disabled.

## Security and trust boundary

The pilot projection is read-only by contract, lives inside the run directory,
and is bound into the packet by path, size, and SHA-256.  Existing traversal,
symlink, packet-identity, invocation-reuse, payload, and artifact checks remain
unchanged.  Row-level data are an allowed input, not executable instructions;
the controller does not execute code from the data or model output.  Agents may
write only inside their declared artifact directory.

## Consequences

- Empirical candidates can now execute against frozen rows instead of failing
  because only a manifest was visible.
- Coverage-repair and other acquisition-only candidates may produce a plan, but
  the default article workflow stops until D1 admits new evidence.
- A successful seven-gate receipt now means the stable scientific-quality rubric
  passed; it still does not prove measurement truth or guarantee journal
  acceptance.
- Existing v1 agent payloads without a typed analysis outcome, frontier
  assessment, contribution map, figure storyboard, or named scored review gates
  are rejected and must be regenerated from the current packet.

## Verification

Component tests must prove all of the following:

- the pilot packet exposes frozen row and cohort files with correct hashes;
- unsupported and acquisition-required outcomes stop before writing;
- supported empirical outcomes advance only with a verified frontier assessment;
- reviewer gate names cannot drift across revisions;
- a one-diagram figure payload cannot satisfy the empirical storyboard;
- all prior path, symlink, invocation, claim, and same-family provisional checks
  continue to hold.
