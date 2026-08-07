# Workflow Benchmark

## Claim

This benchmark measures the deterministic, offline production-demo workflow. It is
a local engineering baseline, not an official competition score, model-uplift
result, network-download benchmark, or claim of scientific representativeness.

## Frozen workload

- Measured repository revision: `dca2ce59f88da85e745ae346fab9cf5addc8342b`.
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

For the recorded Linux compatibility run, set `CPU_PAIR` to two CPUs allowed by the
host, then apply the official resource ceiling:

```bash
CPU_PAIR=0,1
(
  ulimit -v 4194304
  /usr/bin/time -v taskset -c "$CPU_PAIR" python3.11 \
    scripts/benchmark_workflow.py \
    --warmups 3 --runs 10 \
    --output /tmp/gga-workflow-benchmark.json
)
```

## Recorded result

| Metric | Result |
|---|---:|
| Successful measured runs | 10 / 10 |
| Median elapsed time | 0.504323 s |
| Mean elapsed time | 0.504491 s |
| Sample standard deviation | 0.009565 s |
| Minimum / maximum | 0.486645 s / 0.518466 s |
| Peak benchmark-process RSS | 54,784 KiB |
| Distinct result signatures | 1 |
| Validated records per run | 996 |
| Record-evidence entries per run | 996 |
| Map features per run | 996 |
| Anomaly candidates per run | 6 |

All measured workflow runs returned `partial_success`, while every output-validation
run returned `valid`. The partial status is intentional: the frozen source slice
proves the workflow but does not claim complete spatial coverage for the request.

## Environment

- Python 3.11.15.
- Linux 6.8 series, x86-64.
- CPU affinity restricted to 2 logical CPUs; 32 logical CPUs were present on the host.
- Virtual-memory limit set to 4 GiB for the benchmark process and its children.
- No network, GPU, model call, or non-standard Python runtime dependency.

This reproduces the official CPU count, memory ceiling, and Python compatibility on
the local host, but it is not the official Docker image. Use the result as a
regression reference, not as a guaranteed runtime on another machine.

## Interpretation limits

The timing includes request loading, normalization, QC, anomaly screening, artifact
generation, and output validation. It excludes public-source acquisition, OpenCode
startup, model inference, and browser rendering. It provides no before/after speedup
claim and no evidence about official no-skill vs with-skill uplift. Official performance still requires the
frozen external campaign and its prescribed repeated model runs.
