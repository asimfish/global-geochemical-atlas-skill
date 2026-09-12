# Answer binding v2 — correction and verification

Review date: 2026-09-12. Base: `cf6d9ee1e8a56cd3481a8f4110c080b1f905652f`.
Scope: the existing CLI answer-check boundary, its callers and documentation.
Implementation is original project code under the root MIT license. No external
code, dependency, credential, model, or data source was imported.

## Failure and cause

The old checker pooled all numeric values without their subjects, used a 0.5%
tolerance even for integer counts, and skipped small integers and year-like
numbers. With only 10,000 standardized records licensed, it accepted 10,001
records, 10,000 confirmed pollution regions, 8 unsupported regions and 2026
records. A same-input comparison against the base implementation reproduced all
four false positives; the corrected checker rejects all four.

## Contract and compatibility

`atlas-answer-binding-v2` certifies canonical evidence-appendix lines, not arbitrary
prose. `--render-answer NEW_ANSWER.md` generates them from the freshly rebuilt
ledger and refuses to overwrite a file. `--check-answer NEW_ANSWER.md` rebuilds
the ledger again, matches complete lines and records answer and ledger SHA-256.
Each line binds the claim identity, statement, JSON value/type, full scope,
evidence path/pointer/hash and a digest of the full claim including recomputation.

Unsupported claims do not license values. Modified claims, duplicates, appended
prose and empty answers fail closed. Exact supported small and year-like counts
still pass. Free-text drafts that used to pass now return exit 1; use a generated
appendix and independently review explanatory prose. This is an intentional
compatibility tightening, not a semantic-language understanding claim.

The CLI trusts local pipeline artifacts as its input boundary and rebuilds rather
than trusting an edited ledger. Hashes are not signatures, publisher identity,
measurement correctness or scientific-truth proofs. Rewriting evidence and
rehashing it does not exempt the upstream validation/adversarial gates.

## Verification evidence

- Focused regressions: 25/25 PASS (`component_test_more.py --binding-only`).
- Full component suite: 677 PASS (D1 447, D2 63, D3 167), including actual
  headless-browser China fixture rendering.
- Supplemental suite: 89/89 PASS, including CLI render/check, preserved existing
  answer files, stale source-byte rejection and answer digest verification.
- Deterministic self-test: 76 PASS; loop self-test: 117 PASS; spatial policy v6 PASS.
- Ruff lint/format PASS; critical mypy 9 files PASS; separate claim-ledger mypy PASS.
- All 76 script `--help` interfaces PASS. `component_test_more.py --help` now exits
  through argparse instead of executing its suite. CI explicitly runs that suite
  so fixing help cannot silently remove its regression coverage.
- Competition structure/static validator and Skill frontmatter validator PASS.
- Changed-line credential-pattern check: no matches; no new network or execution
  capability. This bounded check is not a claim of a full-repository security audit.

One earlier run overlapped Skill edits and failed the fixture/autopilot path; it
is not acceptance evidence. After freezing the code, the full ordered gate above
passed. A format-only gate failure was corrected before that successful run.

Reproduce from the repository root with Python 3.10+:

```bash
ruff check .
ruff format --check .
mypy --config-file mypy-critical.ini
python3 skills/global-geochemical-atlas/scripts/component_test.py --component all
python3 skills/global-geochemical-atlas/scripts/component_test_more.py
python3 skills/global-geochemical-atlas/scripts/self_test.py
python3 skills/global-geochemical-atlas/scripts/run_self_correction_loop.py --self-test
python3 skills/global-geochemical-atlas/scripts/spatial_sufficiency.py
```

## Release limits

Website corrections are a separate change in `global-geochemical-atlas-demo`:
units by medium, 17 non-summary artifact hashes, explicit canonical-only answer
certification and exploratory temporal interpretation. Historical data counts
remain labelled snapshots, not new runs. Homepage and temporal-slide browser
renders plus inline JavaScript syntax checks passed.

No new online global/China collection, external-model paper-quality run, OpenCode
uplift measurement or resource-limited Docker run is claimed. Full publication
still requires PR/CI evidence for these new commits; the old main CI is not such
evidence. The general directory packager captured a transient `.pyc` during tests;
use an archive of the reviewed commit's tracked Skill files for distribution,
not that rejected working-directory package.
