# P01–P08 Review Documents — 2026-08-05

This directory is a documentation-only snapshot of the latest evaluation review.
It was prepared for the `evaluation` branch and does not replace the production
Skill or the executable evaluator sources.

## Status

- Overall readiness: `NOT_READY`
- Evaluation contract: `1.0.0`
- Contract SHA-256: `b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee`
- Canonical defect register: `handoff/P04/P01-08缺陷台账.md`

The canonical register contains the P05 and P06 findings, including closed
history and open/external gates. The former component-local P05/P06 defect
registers were retired to avoid duplicated or drifting defect records.

## Contents

- `handoff/P04/`: canonical P01–P08 defect register and P04 review state.
- `handoff/P05/`: current scorer/validator checks, summary, and integrity list.
- `handoff/P06/`: current integration checks, summary, candidate bundle, and
  integrity list.
- `handoff/P08/`: current acceptance observation and audit state.
- `reports/`: human- and machine-readable evidence indexes plus schema.
- `SHA256SUMS`: snapshot-local hashes for every document in this directory.

## Integrity check

From this directory, run:

```bash
sha256sum -c SHA256SUMS
```

The component `SHA256SUMS` files retain their original project-relative paths;
the top-level `SHA256SUMS` is the portable integrity manifest for this snapshot.
