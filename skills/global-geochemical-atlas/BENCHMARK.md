# Workflow Benchmark

## Claim

This benchmark measures the deterministic, offline production-demo workflow. It is
a local engineering baseline, not an official competition score, model-uplift
result, network-download benchmark, or claim of scientific representativeness.

## Frozen workload

- Executable revision: `150c02e841859c2c6042aba5088fae955504bcbd`.
- Request: `fixtures/production-usgs/request.json`.
- Demo and analysis profile: `production-usgs` and `production`.
- Protocol: 3 warm-up runs followed by 10 measured runs.
- Isolation: every run used a new temporary output directory.
- Validation: all 15 required artifacts were validated after every run.
- Consistency: the benchmark compared the canonical result signature across runs.

Run the same protocol from the Skill directory:

```bash
python scripts/benchmark_workflow.py \
  --warmups 3 \
  --runs 10 \
  --output /tmp/gga-workflow-benchmark.json
```

## Recorded result

| Metric | Result |
|---|---:|
| Successful measured runs | 10 / 10 |
| Median elapsed time | 0.504235 s |
| Mean elapsed time | 0.506052 s |
| Sample standard deviation | 0.005604 s |
| Minimum / maximum | 0.500016 s / 0.517357 s |
| Distinct result signatures | 1 |
| Validated records per run | 996 |
| Record-evidence entries per run | 996 |
| Map features per run | 996 |
| Anomaly candidates per run | 6 |

All measured workflow runs returned `partial_success`, while every output-validation
run returned `valid`. The partial status is intentional: the frozen source slice
proves the workflow but does not claim complete spatial coverage for the request.

## Environment

- Python 3.13.9.
- Linux 6.8 series, x86-64.
- 32 logical CPUs visible to the process.
- No network, GPU, model call, or non-standard Python runtime dependency.

This is not the official 2 CPU / 4 GB evaluation container. Use the recorded result
as a reproducible regression reference, not as a guaranteed runtime on another
machine.

## Interpretation limits

The timing includes request loading, normalization, QC, anomaly screening, artifact
generation, and output validation. It excludes public-source acquisition, OpenCode
startup, model inference, and browser rendering. It provides no before/after speedup
claim and no evidence about B0/S0 uplift. Official performance still requires the
frozen external campaign and its prescribed repeated model runs.
