# Local acceptance runs

This directory is for local, reproducible acceptance evidence. It is not part
of the single-Skill competition submission and generated `results/` directories
must not be committed.

- `pitch-full-flow/` runs the world and China atlas journeys plus the pitch
  promises: immutable Loop rounds, role-isolated adversarial packets,
  claim-to-artifact SHA-256 bindings, the in-atlas temporal view, and a real
  Auto-Research continuation that stops at external-agent/human gates.
- `competition-requirements/` independently tests the official geochemical
  task and packages exactly one reusable Skill.

Both runners refuse to overwrite an existing output directory. Choose a new
path for every run so earlier evidence remains recoverable.
