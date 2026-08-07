# Instructions for the tested AI agent

You are the tested agent, not the evaluator. Complete only the tasks supplied in your isolated working directory.

## Visibility boundary

Treat the supplied working directory as your entire benchmark filesystem. Do not traverse to a parent directory or search elsewhere for benchmark materials. The candidate-visible bundle must not contain gold answers, checkers, rubrics, scoring prompts, evaluator-only assets, or historical submissions.

Use the task and submission roots explicitly supplied by the runner. Two layouts are supported:

- Q01-Q24 multi-task bundle: task roots are `tasks/Qxx/`, and submission roots are `submissions/Qxx/`.
- Isolated single-task run: the runner declares `TASK_ROOT` and `SUBMISSION_ROOT`; read only `TASK_ROOT/task.md`, `TASK_ROOT/task.json`, and `TASK_ROOT/inputs/**`, and write required relative paths under `SUBMISSION_ROOT`.

If the runner does not declare roots, use the Q01-Q24 multi-task layout. Never guess a parent path or search for another task.

Before starting, read the supplied `public_interface.md`. For each selected task, read only its `task.md`, `task.json`, and `inputs/**` under the applicable task root.

The `task.json.candidate_visible_contract` object is part of the question. It defines every task-local logical output's exact format, CSV columns and JSON structure. Follow it exactly. In particular, logical CSV evidence uses `columns` plus `rows` as an array of objects keyed by column name; do not use positional row arrays.

Write every relative file listed in `task.json.required_outputs` under the applicable submission root. Do not modify the public interface or anything under a task root.

You may use local code to process the supplied inputs. Do not invent sources, identifiers, downloads, measurements, geological interpretations, or causal claims. When evidence is insufficient, state the limitation or reject the unsupported operation as required by the task.

Complete the supplied tasks independently. Before handoff, run the public, value-free contract validator supplied in the bundle:

```bash
python3 validate_submission_contract.py --bundle-root .
```

For an isolated task, run:

```bash
python3 /task/validate_submission_contract.py \
  --task-root /task --submission-root /submission
```

If it reports `FAIL`, repair only the declared structure and rerun it. The tool checks required files, parseability and `candidate_visible_contract`; it contains no gold answers, scores, rubrics or hidden checker logic. Report generated paths and genuine environment failures. Do not attempt to grade or repair the submission against hidden expectations.
