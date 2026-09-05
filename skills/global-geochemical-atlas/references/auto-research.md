# Atlas-to-Auto-Research runtime contract

`Auto-Research` is an optional continuation inside the generated
`interactive_map.html`.  It consumes a validated, frozen atlas and never edits
the eighteen core products.  Selecting a research direction is the only human
decision: from there the controller advances autonomously and **every run ends
with a packaged, reviewed deliverable** whose grade states its basis:
`camera_ready` (strong frontier, every review gate passed),
`draft_with_disclosed_findings` (revision budget exhausted, or the manuscript
rests on the best executed pilot whose frontier the literature judged weak), or
`evidence_report` (no attempted direction could execute a pilot, so the run
writes a data-adequacy and research-direction report).  Failed directions are
archived and the same run redirects itself to the next untried empirical
candidate before any of these fallbacks apply.

## Start locally

```bash
python scripts/serve_atlas_research.py \
  --atlas-dir OUTPUT_DIR \
  --research-root RESEARCH_ROOT \
  --port 8765
```

Open the exact URL printed by the command.  Its random token is in the URL
fragment, so it is not sent in the initial HTTP request.  The browser sends it
only in `X-GGA-Research-Token` together with a one-use nonce.  GitHub Pages and
plain `file://` mode cannot execute local research: the UI exports the identical
typed request and explicitly says no run was created.

The CLI equivalent is:

```bash
python scripts/auto_research.py start \
  --atlas-dir OUTPUT_DIR \
  --research-root RESEARCH_ROOT \
  --request gga-auto-research-request.json
```

If the request intentionally omits both a question and candidate, the run stops
at `awaiting_selection`. Resume it without rebuilding the atlas snapshot:

```bash
python scripts/auto_research.py select \
  --run-dir RESEARCH_ROOT/run-... \
  --candidate-id dc-001
```

`--question` is the mutually exclusive alternative. The local API exposes the
same transition at `POST /api/v1/research-runs/<run-id>/selection`.

## State and gates

One request and atlas snapshot deterministically map to one `run-<hash>`
directory. Re-running `start` resumes that directory. Append-only `events.jsonl`
and `state.json` expose the next incomplete gate.

1. Validate all eighteen atlas files, copy a research-only snapshot projection,
   and recompute the nine-claim SHA-256 ledger.
2. Build cohorts, exclusions, context, sampling priorities and deterministic
   discovery candidates.
3. Freeze the selected/user hypothesis, pilot contract, primary-literature
   verification queue, scientific-quality contract, contribution-first paper
   spine, figure storyboard contract and a type-diverse five-paper candidate
   program. The program is labelled proposals, not papers.
4. Start `pilot_analyst` and `literature_researcher` in separate fresh sessions.
   Roles inside one wave may run concurrently: each role writes only inside its
   own `artifact_output_dir`, and the controller serializes every state
   transition through an exclusive `state.lock`, so parallel submissions cannot
   interleave ledger writes.    The pilot packet includes hash-bound row-level geochemistry plus cohort,
   exclusion, context and source/QC files; it does not receive chat or mutable
   atlas paths. The frozen pilot contract (`gga-pilot-contract-v2`) carries four
   inference requirements, and every paper-eligible outcome must return a typed
   `scientific_rigor` object covering site identity (basis plus residual risk of
   coordinate-key pairing), spatial dependence (diagnostic, finding and a
   dependence-aware uncertainty method), hold-out replication (scheme, result
   and a `consistent` boolean) and deterministic regeneration (pinned-seed
   command). The controller rejects paper-eligible submissions that omit any of
   these fields, so statistical-design gaps surface at the pilot gate instead of
   burning review revision rounds. The literature result must document its search coverage
   (queries, sources searched, inclusion criteria and at least eight screened
   candidates, never fewer than the citations returned) and must bind every
   citation to a declared retrieval-evidence artifact with a retrieval
   timestamp. Memory-only citations are rejected before they can enter the
   verification queue.
5. Apply the outer scientific-opportunity gate. Only an executed
   `supported_effect` or `supported_null` plus a verified
   `supports_empirical_article` frontier assessment may start writing. An
   unsupported, acquisition-only, invalid or weak-frontier result never
   fabricates a paper and never stops the run for a human: the controller
   archives the whole attempt (contracts, packets, results, gate receipt)
   under `attempts/attempt-NN-<candidate>/` with a hash-bound
   `attempt_manifest.json`, pops the next candidate from
   `candidate_fallback_queue.json`, rebuilds the contracts and first-wave
   packets for it at the run root and returns to `awaiting_agents` in the
   **same run** (`state.attempt` increments, `attempt_history` and
   `exhausted_candidate_ids` grow). The agent host simply keeps serving
   `required_roles`. The queue holds every untried empirical candidate
   ordered round-robin across template types (the failed type rotates last,
   discovery rank inside a type); an `unsupported_inputs` pilot also exhausts
   the siblings that share the failed candidate's data signature (same type,
   medium and sample-type pairing), because the archive cannot identify that
   estimand for any element. An executed pilot whose frontier is weak or
   unverified is a *writeable* attempt: it is archived and kept while other
   directions are tried. When the queue is exhausted the run never stops
   empty-handed: if any attempt is writeable, the best one (`supported_effect`
   before `supported_null`, then the earliest) is restored to the run root and
   written up with a `frontier` disclosure in the gate receipt, the writer and
   figure packets and the final manifest (`writing_basis =
   best_available_executed_pilot`, grade capped at
   `draft_with_disclosed_findings`); otherwise the controller opens an
   **evidence report** (`writing_basis = evidence_report`): the archived pilots'
   diagnostic claims (attempt-prefixed), literature verdicts, gate receipts and
   the acquisition/audit candidates become the inputs of the same writer,
   figure, citation-audit and review roles under a report spine and report
   figure roles (`coverage_and_gaps`, `pilot_diagnostics`,
   `acquisition_priority`). No manuscript/figure packets are created for a
   direction while a stronger one may still be found.
6. Start `manuscript_writer` and `figure_designer` only after that gate. When
   the wave opens, the controller installs two kits into the run and binds them
   into the packets by hash:
   - **Paper kit** (`paper_kit/`, contract `gga-paper-v1`): the fixed LaTeX
     style `gga-paper.sty` (Times stack with fallbacks, compact journal
     headings, running head, caption and float rules), the manuscript skeleton
     `manuscript-template.tex`, a controller-generated `claims.tex` that
     registers every atlas and pilot claim of the frozen registry as a
     `\registerclaim` line, a `references.bib` seeded from the verified
     literature (keys `lit01`, `lit02`, ...) and `seeded_reference_list.json`
     with the matching reference records.
   - **Figure kit** (`figure_kit/`, contract `gga-figure-kit-v1`): the
     dependency-free SVG toolkit `paper_figures.py` (`Figure`, `Axes`,
     `MapPanel`; Okabe-Ito palette; point-based typography above the print
     floor), the renderer `render_figure.py` (same-size vector PDF and
     288 dpi PNG through headless Chrome or rsvg/inkscape/cairosvg, aspect
     verified; exits 3 rather than faking a render), `publication_lint.py`
     for self-checks, and the offline Natural Earth land / Admin-0 / China
     Admin-1 basemaps that `MapPanel` draws inside a group tagged
     `data-gga-layer="basemap"`.

   Every contribution and plotted result must cite an atlas or pilot claim ID.
   The manuscript delivers a typed reference list (unique reference IDs,
   titles, ordered authors, years, venues and one resolvable
   DOI/arXiv/official-URL identifier each) plus a typeset manifest binding the
   LaTeX source, the `.bib` it loads and the rendered PDF, whose section
   manifest covers every frozen paper-spine section. The **typesetting gate**
   then lints the source and the PDF deterministically: the source must load
   `gga-paper`, `\input{claims}`, cite every number only through
   `\claimref{claim_id}` marks that resolve to registered ids (legacy inline
   `\claim{...}` tags and typewriter identifiers in prose are rejected), keep
   every figure full-width (`width=\linewidth`, never a fixed height) with
   caption and label, referenced in the text and placed before the
   bibliography, cite only keys that exist in the submitted `.bib`, and end
   with `\printclaimledger`; the `reference_list` must list exactly the bib
   keys the source cites. The PDF must be a TeX-engine product (pdfTeX, XeTeX
   or LuaTeX; browser or office exports fail), at least four pages, with an
   Abstract on page one and the template font families embedded. The lint
   reads page objects and MediaBoxes inside PDF 1.5 object streams, so
   compressed pdfTeX output is judged correctly.

   The empirical visual storyboard must contain primary-result,
   spatial-pattern, and robustness/external-validation roles; a methods
   diagram cannot replace them. The spatial-pattern figure must encode the
   claimed effect or measured values in space; per the frozen figure contract
   a data-availability or cohort-coverage map does not satisfy the role and
   fails review gate a6. Each figure binds distinct SVG/PDF/PNG artifacts by
   SHA-256, records non-empty inspection findings plus the revisions actually
   applied, documents at least two candidate designs with the rejected
   alternatives, states how the rendered figure stays faithful to its source
   data, and binds an editable source artifact that is neither the PDF nor the
   PNG render. On submission the controller runs a deterministic publication
   lint over every declared SVG/PNG/PDF artifact of both roles: vector text
   below the 4.5 pt print-equivalent floor (undeclared SVG text counts as
   16 px), text runs longer than 120 characters (captions and disclaimers
   belong in the manuscript caption), rasters narrower than 1000 px, page-less
   or malformed PDFs and non-well-formed SVGs are rejected. The **render
   fidelity** check compares each figure's PDF page box and PNG pixel box with
   the SVG aspect (2 % tolerance, so clipped or letter-boxed exports fail) and
   requires the basemap layer in the spatial roles (`spatial_pattern`,
   `coverage_and_gaps`). The quality contract also fixes manuscript layout
   rules (noun-phrase headings, structured inline lists, figure typography
   hierarchy) that the a5/a6 reviewer gates enforce.
7. Finished manuscript and figures route into a fresh `citation_auditor`
   session before any review. The controller freezes the manuscript reference
   list into a cycle-level reference manifest; the auditor must return one
   verdict (`verified`, `mismatch` or `unverifiable`) per manifest entry,
   backed by typed registry checks (title, authors, author order, year, venue,
   identifier resolution), written evidence and a declared registry-evidence
   artifact. A verdict of `verified` requires every check to pass; the audit
   must cover exactly the manifest and its summary must match the per-entry
   verdicts. Any non-verified reference blocks review and opens a
   citation-repair revision cycle with enumerated feedback tasks.
8. Start `independent_reviewer` with canonical artifacts, the receipted
   citation audit, the reference manifest and the fixed a1-a7 rubric,
   excluding executor summaries and all previous review prose. Isolation is
   enforced on both sides: a writer, designer or auditor cannot declare as an
   artifact any byte-identical copy of feedback tasks, review receipts or
   reviewer output (hash-matched wherever the copy is placed), any file named
   `feedback_tasks.json`/`review_receipt.json`, any JSON carrying the
   feedback-task schema, or a stale copy of the previous cycle's file declared
   next to its revised namesake; and the reviewer packet itself fails closed if
   any allowed input hashes to review provenance. Unchanged files (an
   untouched `references.bib`, an unrevised figure) may be re-submitted.
9. Failed gates create an immutable `revision-NN` cycle routed to the roles
   that own the failing gates: citation-audit and manuscript-argument failures
   reopen only `manuscript_writer`, figure-evidence failures reopen only
   `figure_designer`, and shared-evidence gates (a1, a2, a7) reopen both. Each
   feedback task records its `owner_roles`; a role outside the targeted set
   cannot submit into the cycle, and its newest accepted artifacts carry
   forward by hash into the next audit and review packets. Revision packets
   re-bind the installed paper kit or figure kit and carry the same
   `payload_contract` (including the deliverable rule) as the initial wave, so
   a revising role works on the same style, ledger and toolkit. A revision that
   touches the manuscript repeats the fresh citation audit; a figure-only
   revision carries the already-verified audit receipt forward instead of
   re-auditing an unchanged reference list. The next reviewer sees only the
   canonical artifacts and frozen claim contracts, never feedback or previous
   review prose. At most three revision cycles run; unresolved failures then
   auto-publish at grade `draft_with_disclosed_findings`, with every open
   feedback item disclosed verbatim in the publication manifest.
10. Passing gates auto-publish: the controller verifies every deliverable
    hash, packages the manuscript, figures, review and audit receipts under
    `publication/`, and writes a hash-bound `publication_manifest.json` that
    records `grade`, `deliverable_mode`, `writing_basis` and the number of
    attempted directions. A strong-frontier manuscript that passes every gate
    is `camera_ready` (`completed_published`); a manuscript written on the
    best available weak-frontier pilot is capped at
    `draft_with_disclosed_findings` (`completed_with_findings`) even when every
    gate passes, with the frontier verdict listed in `disclosed_findings`; an
    evidence report is always graded `evidence_report`
    (`completed_evidence_report`) and discloses that it claims no empirical
    effect. Same-family review remains labeled provisional inside the receipt,
    and the manifest grade is the honest publication record; no human approval
    gate exists.

The controller owns the meaning of every review gate; the reviewer cannot rename
or substitute them between cycles. Each gate returns a score from 0 to 4,
non-empty evidence, and `pass=true` only for scores of at least 3:

| ID | Fixed meaning |
|---|---|
| a1 | evidence integrity |
| a2 | scientific validity |
| a3 | novelty and significance |
| a4 | frontier and venue fit |
| a5 | manuscript argument and contribution |
| a6 | figure evidence and visual quality |
| a7 | reproducibility and release integration |

`SHA-256` proves exact byte identity and declared association. It does not prove
measurement correctness, scientific importance, truth, or journal acceptance;
the publication grade in `publication_manifest.json` is the honest record of
which scientific gates the package cleared and which findings remain open.

An agent host reads only the active `agents/<role>/packet.json` or
`revisions/revision-NN/agents/<role>/packet.json`, creates files under the exact
`artifact_output_dir` declared by that packet, and submits a JSON payload using:

```bash
python scripts/auto_research.py submit \
  --run-dir RESEARCH_ROOT/run-... \
  --role pilot_analyst \
  --invocation-id UNIQUE_FRESH_INVOCATION \
  --model-family MODEL_FAMILY \
  --payload payload.json
```

The controller validates cycle, paths, hashes, role identity, invocation
uniqueness across every cycle and every archived attempt, typed claim/citation
contracts and stage dependencies before advancing. Accepted results are never
overwritten. An agent result is evidence to review, never authority to alter
the atlas.

Every first-wave packet carries `required_output.payload_contract`: the exact
field names, enum values (`analysis_outcome.status`,
`frontier_assessment.status`), the retrieval field name `retrieved_at`, the
`search_coverage` shape and the artifact path rule (paths are relative to the
run root and start with `artifact_output_dir`). Second-wave packets carry the
same block with the typesetting contract (`payload_contract.typesetting`:
start from `paper_kit/manuscript-template.tex`, claim marks, bibliography,
figure placement and PDF rules; `typeset_manifest_keys` includes
`bib_artifact`) or the figure-kit contract (`payload_contract.figure_kit` and
`rules`). Roles should dry-run their payload with `submit ... --validate-only`,
which executes the identical acceptance checks without recording a result or
advancing the run, and only then submit.

A writer's shortest compliant path is: copy `paper_kit/gga-paper.sty`,
`claims.tex` and `references.bib` next to `manuscript.tex`, start from the
template, cite numbers with `\claimref{...}` and literature with `\cite{lit01}`
(extend the bib and the `reference_list` together for new verified
references), embed the figure kit PDFs with
`\includegraphics[width=\linewidth]`, and compile with
`latexmk -pdf -interaction=nonstopmode manuscript.tex`. A figure designer's
shortest compliant path is: build each figure with `figure_kit/paper_figures.py`
(`MapPanel` for spatial roles), save the SVG as the editable source, and export
with `python figure_kit/render_figure.py --svg fig.svg --pdf fig.pdf --png
fig.png`, which verifies the aspect the gate later checks.
