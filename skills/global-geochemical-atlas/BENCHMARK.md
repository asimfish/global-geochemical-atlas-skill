# Workflow Benchmark

## Claim

This benchmark measures the deterministic, offline production-demo workflow. It is
a local engineering baseline, not an official competition score, model-uplift
result, network-download benchmark, or claim of scientific representativeness.

## Frozen workload

- Revision binding: every newly generated JSON report records the exact executable
  Skill-tree fingerprint; the historical numbers below are not a current-revision
  attestation.
- Request: `fixtures/production-usgs/request.json`.
- Demo and analysis profile: `production-usgs` and `production`.
- Protocol: 3 warm-up runs followed by 10 measured runs.
- Isolation: every run used a new temporary output directory.
- Validation: all 16 required artifacts were validated after every run.
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

## Large-atlas browser benchmark (2026-08-15)

This second benchmark isolates the D3 performance change requested after the
world_822 run. It does not measure D1 downloads or D2 analysis and makes no
scientific-coverage claim.

- Canonical input: 191,715 measurements; `geochemistry.csv` SHA-256
  `e3616e88b6f5c716f5f69a0c786897f3878838281b7aec4bc280f2f6a653828d`.
- Scope/mode: global, reported-coordinate display; 190,437 plottable rows.
- Before: world_822 HTML SHA-256
  `2202ebaeae0b1011a6e7aa90358c62d0679044974dd50c343241c852b202adcc`;
  all 190,437 rows embedded.
- After: the same immutable inputs rendered with
  historical `d3-coverage-preserving-preview-v1` benchmark used a 50,000-row ceiling; current research defaults embed up to 200,000 rows and use zoom-aware rendering LOD. The historical run retained complete physical
  sample groups, all 3,351 candidate-anomaly records, and one representative
  per source × medium × element × 5° cell before deterministic fill.
- Browser: `/usr/bin/google-chrome`, headless, no GPU, no sandbox, 10-second
  virtual-time budget, three fresh processes per variant.

Rebuild the candidate map (choose a new output directory):

```bash
python3 scripts/render_visualization.py \
  --input-dir /path/to/world_822/output \
  --output-dir /tmp/gga-map-preview \
  --coordinate-mode reported \
  --max-points 200000 \
  --max-embedded-records 50000
```

Measure one fresh browser process; repeat three times:

```bash
/usr/bin/time -f 'elapsed=%e rss_kb=%M exit=%x' \
  google-chrome --headless --no-sandbox --disable-gpu \
  --disable-dev-shm-usage --virtual-time-budget=10000 --dump-dom \
  file:///tmp/gga-map-preview/interactive_map.html >/dev/null
```

| Variant | HTML | Embedded rows | Browser elapsed, three runs | Median | Peak RSS, three runs | Median |
|---|---:|---:|---|---:|---|---:|
| world_822 before | 74 MiB | 190,437 | 19.38 / 19.34 / 19.18 s | 19.34 s | 894,264 / 897,004 / 897,264 KiB | 897,004 KiB |
| coverage-preserving preview | 24 MiB | 50,000 | 5.66 / 5.59 / 5.75 s | 5.66 s | 433,680 / 433,660 / 435,452 KiB | 433,680 KiB |

The measured median startup fell by about 70.7%, median peak browser RSS by
about 51.7%, and HTML size by about 67.6%. The complete canonical CSV and its
aggregate database summaries are unchanged. Map-level searches and visual
pair exploration operate on the explicitly labelled preview; formal complete-
population work must use `geochemistry.csv` or a rerender with a higher preview
ceiling. Results are host- and browser-specific and are regression evidence,
not a guaranteed competition-runtime result.
