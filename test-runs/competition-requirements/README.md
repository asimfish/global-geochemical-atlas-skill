# Official competition-requirements acceptance

This directory tests the official task independently of the pitch-only
extensions. It uses the frozen world fixture because it covers rock, soil,
sediment, and water in one reproducible, offline request.

Run from the repository root:

```bash
python test-runs/competition-requirements/run.py \
  --output-root test-runs/competition-requirements/results/run-YYYYMMDD-HHMMSS
```

The result contains:

- `atlas/interactive_map.html`: open this to inspect the atlas.
- `screenshots/atlas-overview.png`: real browser rendering evidence.
- `atlas/geochemistry.csv`: standardized database.
- `atlas/sources_and_confidence.json`: source and confidence explanation.
- `atlas/anomaly_regions.geojson` plus anomaly reports: anomaly screening.
- `submission.zip`: package created by the AI4S packaging tool; it contains
  exactly one production Skill.
- `COMPETITION-ACCEPTANCE.json`: field-by-field mapping from the task statement
  to observed files and values.

The atlas run may be `partial_success`: the frozen fixture is deliberately a
small engineering slice and must not claim complete global representativeness.
That boundary is a required scientific behavior, not a failed test.
