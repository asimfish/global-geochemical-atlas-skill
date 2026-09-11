# ADR-0006: Citation audit stage and publication-evidence contracts

## Status

Accepted

## Context

ADR-0005 made the paper loop scientifically honest: an unsupported pilot can no
longer become a manuscript, and the seven review gates cannot drift.  The
remaining failure class is publication evidence.  A literature role could
return citations recalled from model memory with no proof that any search was
performed.  A manuscript could pass review while its bibliography contained a
wrong author order, a mislabelled venue, or an identifier that resolves to a
different paper, because no role re-derived the reference list against the
public registries.  A manuscript could also pass as loose prose: nothing bound
a typeset source document and a rendered PDF whose sections match the frozen
paper spine.  Figures were inspected but not designed: a single first-draft
chart with a self-review satisfied the storyboard, and nothing guaranteed an
editable source file for later human revision.

## Decision drivers

- Keep the deterministic controller, hash-bound packets, fresh sessions,
  immutable revisions, and human publication approval unchanged.
- Make literature results falsifiable: a citation must carry retrieval
  evidence, not only a claim of verification.
- Catch wrong titles, authors, author order, years, venues, and dead or
  misdirected identifiers before any reviewer reads the manuscript.
- Make the manuscript a deliverable document, not loose text: source plus
  rendered PDF plus a section manifest that covers the frozen spine.
- Make figures the product of a documented design choice with an editable
  source, without weakening the existing render-inspect-revise loop.
- Keep every new check controller-owned so agents cannot self-certify.

## Options

| Option | Publication integrity | Agent cost | Failure mode |
|---|---:|---:|---|
| A. Trust writer-reported reference checks | low | low | Fabricated or degraded citations reach review |
| B. Dedicated fresh citation-audit stage plus typed evidence contracts | high | medium | May add one revision round per repaired bibliography |
| C. Verify references only in optional human polish | medium | low | Automated runs archive drafts with unverified bibliographies |

Choose Option B.  A bibliography error found after review restarts the whole
review; a dedicated pre-review audit finds it while repair is cheap.

## Decision

### Literature retrieval evidence

A literature result is accepted only when every citation binds a declared
retrieval-evidence artifact plus a retrieval timestamp, and the payload
documents its search coverage: queries, sources searched, inclusion criteria,
and a screened-candidate count of at least eight and never fewer than the
citations returned.  Memory-only citations fail closed at submission.

### Manuscript delivery contract

Every manuscript payload must include a typed reference list (unique
reference IDs; title; ordered authors; year; venue; exactly one resolvable
DOI, arXiv, or official-URL identifier) and a typeset manifest binding two
distinct declared artifacts — the manuscript source document and the rendered
PDF — with a section manifest that covers every frozen paper-spine section.
The controller verifies the PDF signature and the spine coverage itself.

### Figure design contract

Each storyboard figure additionally records candidate generation (at least
two considered designs and the rejected alternatives), a source-fidelity
statement, and a declared editable source artifact that is neither the PDF
nor the PNG render.  The existing role coverage, distinct SVG/PDF/PNG
bindings, and non-empty inspection findings remain mandatory.

### Citation audit stage

Accepted manuscript and figure results no longer route directly to review.
The controller freezes the manuscript reference list into a cycle-level
`reference_manifest.json` and opens a fresh `citation_auditor` packet bound to
that manifest.  The auditor returns, per manifest entry, a verdict
(`verified`, `mismatch`, or `unverifiable`), six typed registry checks
(title, authors, author order, year, venue, identifier resolution), written
evidence, and a declared registry-evidence artifact.  The controller enforces
verdict-check consistency (`verified` requires all checks true; `mismatch`
requires a resolving identifier plus at least one failing check;
`unverifiable` requires a non-resolving identifier), exact manifest coverage,
and a summary that matches the per-entry verdicts.  Any non-verified entry
opens a citation-repair revision with enumerated feedback tasks; every
revision cycle repeats the fresh audit before a reviewer packet is built.
The reviewer packet carries the receipted audit and the reference manifest.

## Security and trust boundary

The citation auditor is an untrusted agent like every other role: fresh
session, no previous review prose, no executor summaries, artifacts only
inside its declared output directory, and payloads validated against the
packet-identity, path, symlink, hash, and invocation-reuse checks.  Registry
evidence artifacts prove that a lookup was recorded; they do not extend any
network or write authority of the controller, which still executes no agent
code.

## Consequences

- A run can now stop with a truthful `needs_human_intervention` because a
  bibliography could not be verified, which is preferable to archiving a
  draft with fabricated references.
- Each cycle costs one additional fresh agent invocation for the audit.
- Existing v1 literature, manuscript, and figure payloads without retrieval
  evidence, search coverage, reference lists, typeset manifests, or figure
  design records are rejected and must be regenerated from current packets.
- The state machine gains one stage (`citation_audit`) between
  `manuscript_and_figures` and `independent_review`; state, packet, result,
  and quality-contract schemas record it explicitly.

## Verification

Component tests must prove all of the following:

- citations without a bound retrieval-evidence artifact or timestamp are
  rejected, as are searches that screened fewer than the minimum candidates;
- manuscripts without a complete typeset section manifest or with untyped
  references are rejected;
- finished manuscript and figures open a citation-audit stage whose packet is
  bound to the manuscript reference manifest;
- audits with partial coverage, verdict-check contradictions, or summary
  drift are rejected;
- a mismatched reference blocks review and opens a citation-repair revision
  with enumerated tasks;
- every revision cycle repeats the fresh audit, and a fully verified audit is
  receipted into the reviewer packet;
- all prior path, symlink, invocation, claim, gate-drift, and same-family
  provisional checks continue to hold.
