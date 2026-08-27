# Atlas-to-Auto-Research runtime contract

`Auto-Research` is an optional continuation inside the generated
`interactive_map.html`.  It consumes a validated, frozen atlas; it never edits
the eighteen core products and never publishes.

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
   The pilot packet includes hash-bound row-level geochemistry plus cohort,
   exclusion, context and source/QC files; it does not receive chat or mutable
   atlas paths. The literature result must document its search coverage
   (queries, sources searched, inclusion criteria and at least eight screened
   candidates, never fewer than the citations returned) and must bind every
   citation to a declared retrieval-evidence artifact with a retrieval
   timestamp. Memory-only citations are rejected before they can enter the
   verification queue.
5. Apply the outer scientific-opportunity gate. Only an executed
   `supported_effect` or `supported_null` plus a verified
   `supports_empirical_article` frontier assessment may start writing. An
   unsupported, acquisition-only, invalid or weak-frontier result stops at
   `needs_research_redirection`; no manuscript/figure packets are created.
6. Start `manuscript_writer` and `figure_designer` only after that gate. Every
   contribution and plotted result must cite an atlas or pilot claim ID. The
   manuscript delivers a typed reference list (unique reference IDs, titles,
   ordered authors, years, venues and one resolvable DOI/arXiv/official-URL
   identifier each) plus a typeset manifest binding a distinct manuscript
   source artifact and a rendered PDF whose section manifest covers every
   frozen paper-spine section. The empirical visual storyboard must contain
   primary-result, spatial-pattern, and robustness/external-validation roles;
   a methods diagram cannot replace them. Each figure binds distinct
   SVG/PDF/PNG artifacts by SHA-256, records non-empty inspection findings
   plus the revisions actually applied, documents at least two candidate
   designs with the rejected alternatives, states how the rendered figure
   stays faithful to its source data, and binds an editable source artifact
   that is neither the PDF nor the PNG render.
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
   excluding executor summaries and all previous review prose.
9. Failed gates create an immutable `revision-NN` cycle. Only the writer and
   figure roles see structured feedback plus the prior canonical artifacts.
   Every revision cycle repeats the fresh citation audit before independent
   review. The next reviewer sees only the revised artifacts and frozen claim
   contracts, never feedback or previous review prose. At most three revision
   cycles run; unresolved failures then stop at `needs_human_intervention`.
10. Passing gates stop at human approval; same-family review is provisional
    and `publication_allowed` stays false.

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
the scientific and human gates remain separate.

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
uniqueness across every cycle, typed claim/citation contracts and stage
dependencies before advancing. Accepted results are never overwritten. An agent
result is evidence to review, never authority to alter the atlas.
