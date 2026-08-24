# ADR-0001: Evaluation-critical runtime and request boundaries

## Status

Accepted. The 900-second evaluator is the default contract. An explicit
extended-research mode may run longer, but it does not change evaluation
defaults or prevent an evidence-sufficient 840-second run from becoming
delivery-ready.

## Context

The official evaluator gives one task 900 seconds in a 2 CPU, 4 GB, no-GPU
container. Hidden requests may be narrow or full-workflow tasks and may name a
country, a WGS84 bounding box (including one that crosses the antimeridian), or
a geological unit. The current implementation has strong D1/D2/D3 stages, but
per-source timeouts, hand-written region presets, and an always-full workflow
make those stages unreliable at the public request boundary.

## Driving factors

- Never exceed the official task deadline; retain time for validation and the
  calling agent.
- Produce scientifically consistent outputs rather than partially rewritten
  artifacts.
- Work offline and without new Python dependencies.
- Keep one canonical request interpretation across D1, D2, and D3.
- Minimize model decisions on fragile execution paths while preserving reusable
  stage-level tools for narrow tasks.

## Decision 1: orchestration

### Option A: always generate the complete atlas bundle

- Pros: one output contract and simple documentation.
- Cons: wastes deadline on narrow tasks and increases failure surface.

### Option B: let the model freely compose stage scripts

- Pros: flexible and requires little orchestration code.
- Cons: nondeterministic tool selection, inconsistent outputs, and high hidden-task variance.

### Option C: deterministic task contract over reusable stages

- Pros: exact required outputs, stable failure semantics, and minimal work per task.
- Cons: adds one small routing contract that must remain synchronized with the Skill.

### Decision

Choose Option C. The public runner owns task classification, required outputs,
deadline, and spatial scope. Stage scripts continue to own domain algorithms.

## Decision 2: deadline

### Option A: independent per-stage timeouts

- Pros: locally simple.
- Cons: cumulative runtime can exceed 900 seconds.

### Option B: acquire all sources concurrently

- Pros: lower best-case latency.
- Cons: poor fit for 2 CPU/4 GB, harder rate limiting, and less deterministic failure evidence.

### Option C: one monotonic deadline with reserved downstream capacity

- Pros: proves a global upper bound and gives each child only its remaining allocation.
- Cons: some sources may be skipped or time out and must be reported as partial coverage.

### Decision

Choose Option C. Default the production command to an 840-second internal
budget, leaving 60 seconds for agent overhead. Acquisition receives only the
budget remaining before a workflow reserve; validation shares the same global
deadline. Never extend the deadline after a partial failure. A caller may
explicitly request up to 43,200 seconds for non-evaluation research; execution
evidence keeps that choice distinguishable from the official profile.

## Decision 3: spatial scope

### Option A: maintain a short list of named presets

- Pros: trivial implementation.
- Cons: rejects most valid country requests and duplicates semantics across stages.

### Option B: call an online geocoder

- Pros: broad names and administrative levels.
- Cons: violates offline determinism and adds network/version ambiguity.

### Option C: frozen Natural Earth country registry plus explicit bbox

- Pros: 177 versioned country polygons, English/Chinese/ISO-3 aliases, offline
  reproducibility, and strict point-in-polygon filtering.
- Cons: intentionally does not resolve arbitrary subnational place names.

### Decision

Choose Option C. A shared registry resolves countries and the small set of
documented non-country scopes. Unknown names fail closed. Longitude containment
uses wrapped intervals, so `west > east` means antimeridian crossing everywhere.

## Decision 4: data availability

### Option A: online-only acquisition

- Pros: potentially broader and fresher coverage.
- Cons: high variance and deadline/network failure risk.

### Option B: fixture-only execution

- Pros: fast and deterministic.
- Cons: insufficient scientific and geographic coverage.

### Option C: verified offline core with budget-aware online extension

- Pros: deterministic minimum capability plus evidence-qualified expansion.
- Cons: offline slices must be described as bounded and non-representative.

### Decision

Choose Option C. Preserve hash-bound fixtures as the reliable core, rank online
extensions deterministically, and report every omitted or failed source. Never
convert engineering fixture coverage into a global completeness claim.

## Impact

- Request schema, source routing, acquisition, D2 filtering, D3 profiles, and
  tests share one versioned spatial/task interpretation.
- Full bundles remain available; narrow tasks run only the stages and validators
  required by their contract.
- Execution evidence records deadline-induced partial coverage explicitly.
- No external geocoder, projection package, task framework, or async runtime is introduced.
