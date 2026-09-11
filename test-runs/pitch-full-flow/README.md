# Pitch full-flow acceptance: world + China

This test intentionally separates **mechanism correctness** from **scientific
sufficiency**. A frozen demo can pass all file, hash, isolation, rendering, and
state-machine checks while the Loop honestly remains `needs_human_review`
because global or regional evidence is incomplete.

Run from the repository root:

```bash
python test-runs/pitch-full-flow/run.py \
  --output-root test-runs/pitch-full-flow/results/run-YYYYMMDD-HHMMSS
```

Each case produces:

- `atlas/interactive_map.html`: the primary atlas; open this first.
- `screenshots/atlas-overview.png`: a real headless-browser render.
- `atlas/rounds/round-01` and `round-02`: immutable Loop attempts.
- `atlas/loop_report.json`, `d1_repair_queue.json`, and
  `research_delivery_receipt.json`: stop reason, repair control plane, 18-file
  hashes, and the nine-claim ledger.
- `evidence/adversarial-audit/`: two memory variants with identical evaluator
  packet hashes, separate scout/challenger results, deterministic judge receipt,
  and negative substitution/tamper/reuse checks.
- `auto-research-runs/run-*/`: a real atlas-grounded research run containing
  cohorts, candidates, pilot/literature contracts, paper spine, figure contract,
  and fresh agent packets. It correctly stops at `awaiting_agents`; the test
  never fabricates an external model or a paper.
- `evidence/localhost-api.json`: proof that the same request crossed the real
  loopback API used by the atlas Auto-Research form.
- `acceptance.json`: the machine-readable verdict and exact boundaries.

To continue Auto-Research interactively after the run:

```bash
python skills/global-geochemical-atlas/scripts/serve_atlas_research.py \
  --atlas-dir OUTPUT_ROOT/world/atlas \
  --research-root OUTPUT_ROOT/world/auto-research-runs \
  --port 8765
```

Open the exact tokenized URL printed by the server. The generated static atlas
exports the identical request when no local controller is running and never
claims that a job started.

The adversarial result payloads in this test are explicitly labelled protocol
harness data. They prove role, packet, invocation, and hash enforcement; they
are not presented as independent LLM opinions. A production host must honor
`fresh_session_required=true` and start each role in a new session.
