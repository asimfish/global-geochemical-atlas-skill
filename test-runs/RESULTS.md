# Current acceptance evidence

Branch: `fix/acquisition-coverage-v12`

## Pitch promises: world + China

Current immutable run: `pitch-full-flow/results/20260824-world-china-v3/`

- Overall verdict: `PASS`
- World atlas: `world/atlas/interactive_map.html`
- China atlas: `china/atlas/interactive_map.html`
- Machine verdict: `ACCEPTANCE.json`
- Both cases contain two immutable Loop rounds, adversarial-isolation evidence,
  claim-to-artifact SHA-256 bindings, an in-atlas temporal view, and a real
  resumable Auto-Research run.
- Both fixture runs correctly remain `needs_human_review`; passing the
  engineering acceptance does not turn a bounded fixture into a scientifically
  sufficient global or regional census.

## Official competition requirements

Current immutable run: `competition-requirements/results/20260824-official-v2/`

- Overall verdict: `PASS`
- Atlas: `atlas/interactive_map.html`
- Machine verdict: `COMPETITION-ACCEPTANCE.json`
- Submission package: `submission.zip`
- The package contains exactly one production Skill document.

Generated result directories are local evidence and are excluded from the
competition package. The runners refuse to overwrite them.
