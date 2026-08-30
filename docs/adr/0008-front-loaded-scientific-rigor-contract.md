# ADR-0008: Front-loaded scientific rigor in the pilot and figure contracts

## Status

Accepted

## Context

A full world-scenario run exercised the complete loop — pilot, literature,
opportunity gate, manuscript plus figures, a verified nine-for-nine citation
audit, and three immutable revision rounds — and still ended fail-closed at
`needs_human_intervention`. The final independent reviewer passed only a1 and
failed a2 through a7. Its findings were rooted in the frozen upstream design,
not in the prose or panels the revision loop can reopen: coordinate-rounding
pairing could not prove same-site identity, inference assumed iid errors over
spatially dependent sites, no hold-out or split replication existed, the
spatial figure showed data availability rather than the claimed effect, and no
single command regenerated the reported numbers. Revision cycles only reopen
the manuscript and figure roles, so all three rounds were spent on work that
could never repair the root cause. The loop behaved correctly by refusing the
paper, but the contract system let a statistically under-designed pilot walk
deep into the pipeline before an adversarial reviewer said what the contract
should have demanded on day one.

## Decision drivers

- Keep the deterministic controller, frozen hypothesis, fail-closed routing,
  bounded revision budget, and human publication approval unchanged.
- Move requirements that reviewers predictably enforce from the review stage
  into the frozen entry contracts, so failures surface where the owning role
  can still act.
- Demand typed, machine-checkable evidence of rigor rather than prose
  promises, while leaving the scientific judgment of adequacy to the reviewer.

## Decision

1. **Pilot contract v2 freezes four inference requirements.**
   `gga-pilot-contract-v2` adds an `inference_requirements` block covering
   site identity, spatial dependence, hold-out replication, and deterministic
   regeneration. The pilot packet's required output restates them.
2. **Paper-eligible outcomes must carry typed `scientific_rigor` evidence.**
   For `supported_effect` and `supported_null`, the controller validates a
   `scientific_rigor` object: `site_identity` (basis, residual_risk),
   `spatial_dependence` (diagnostic, finding, uncertainty_method),
   `holdout_replication` (scheme, result, boolean `consistent`), and
   `regeneration` (command, `deterministic` strictly true). Any missing field
   rejects the submission at the pilot gate. Non-eligible outcomes are exempt
   because they already route away from paper production.
3. **The figure contract pins spatial-pattern semantics.**
   `gga-figure-contract-v2` states that the spatial-pattern role must encode
   the claimed effect or measured values in space; an availability or
   coverage map does not satisfy the role and fails gate a6.

## Consequences

- Statistical-design gaps become first-wave rejections with named fields
  instead of terminal review findings after the revision budget is spent.
- The controller checks presence and typing, not scientific truth: a pilot can
  still report an inconsistent hold-out honestly, and the reviewer still owns
  the adequacy judgment on a2 and a7.
- Pilot agents must actually run dependence diagnostics and a split
  replication, which raises the cost of the pilot stage; that cost was
  previously paid threefold in futile revision rounds.
- Data that cannot support any disjoint split will fail to produce a
  compliant rigor block and will stop at the pilot gate — the honest outcome
  for evidence that thin.
