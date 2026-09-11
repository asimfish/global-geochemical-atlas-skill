# ADR-0012: Every run ends with a graded deliverable

## Status

Accepted (extends ADR-0009 and ADR-0011)

## Context

Three complete real runs (one world run through three review rounds, then a
world and a China run that stopped at the scientific gate) never produced a
final product. ADR-0009 removed the human approval terminal and ADR-0011 made
the run chain through candidates inside one run, but the design still allowed
an honest dead end: when every empirical candidate was exhausted the run
ended at `needs_research_redirection` with archives and receipts but no paper.
The operating requirement is explicit — after the single direction selection
the pipeline must run to a paper-like deliverable — while the scientific
doctrine is equally explicit that no empirical effect may be claimed without an
executed pilot and that a weak frontier position may not be dressed up as
novelty.

## Decision drivers

- Always deliver: a typeset, cited, independently reviewed product at the end
  of every run, with a grade that states its basis.
- Never overstate: the grade is capped by the writing basis, not by how the
  reviewer happened to score.
- Prefer the strongest direction first: fallbacks apply only after every
  untried candidate has been tried.

## Decision

1. **Writeable attempts.** An executed pilot (`supported_effect` or
   `supported_null`) whose literature frontier is `weak_frontier_position` or
   `needs_verification` is not written immediately; it is archived as a
   *writeable* attempt while untried candidates are pursued. Gate receipt v2
   records `executed_pilot` and `writing_basis`.
2. **Best available executed pilot.** When the queue is exhausted and at least
   one attempt is writeable, the best one (`supported_effect` before
   `supported_null`, then the earliest) is restored from its archive to the run
   root (`restored.json` marks the archive) and the manuscript and figure wave
   starts with `writing_basis = best_available_executed_pilot`. A `frontier`
   disclosure (status, closest prior work, novelty delta, framing instruction)
   is written into the re-issued gate receipt and both packets, and the final
   grade is capped at `draft_with_disclosed_findings` even when all seven
   review gates pass.
3. **Evidence report.** When no attempt is writeable, the run switches
   `deliverable_mode` to `evidence_report`: the archived attempts' diagnostic
   claims (re-registered with an attempt prefix), literature verdicts and gate
   receipts plus the acquisition/audit candidates become the inputs of the same
   writer, figure, citation-audit and review roles under a report spine and the
   report figure roles `coverage_and_gaps`, `pilot_diagnostics` and
   `acquisition_priority`. The package is graded `evidence_report` and ends at
   `completed_evidence_report`; its manifest discloses that no empirical effect
   is claimed.
4. **Contracts.** Quality contract v2 states the weak-frontier and
   no-executed-pilot policies; state schema v5 adds `deliverable_mode`,
   `attempt_history[].writeable/restored_as_attempt`,
   `research_gate.writing_basis` and the new status; publication manifest v2
   records `deliverable_mode`, `writing_basis` and `attempted_directions`.
   `needs_research_redirection` remains only as a defensive terminal for a run
   with no archived attempt at all.

## Consequences

- The last world run (`supported_null` + weak frontier on dc-001) would now
  chain through the method-artifact and cross-media candidates and, failing
  those, still deliver a disclosed-findings null-result manuscript on dc-001.
- The last China run (`unsupported_inputs` on every T6 sibling) would now end
  with a reviewed data-adequacy report recommending the acquisition plan,
  instead of a state file.
- Reviewers judge report-mode a3/a4 as the value and honesty of the adequacy
  finding and its fit for a data or methods venue; the contract says so.
- Hosts can no longer treat `needs_research_redirection` as the expected end
  of a difficult run; the expected ends are the three publication statuses.
