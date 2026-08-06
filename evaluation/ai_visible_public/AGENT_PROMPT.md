# Instructions for the tested AI agent

You are the tested agent, not the evaluator. Complete Public tasks Q01-Q08.

## Visibility boundary

Treat this directory as your entire benchmark filesystem. Do not traverse to a
parent directory or search elsewhere for benchmark materials. This bundle does
not contain gold answers, checkers, rubrics, or private tasks.

For each task, read only:

- `tasks/Qxx/task.md`
- `tasks/Qxx/task.json`
- `tasks/Qxx/inputs/**`

Write every file listed in `task.json.required_outputs` to
`submissions/Qxx/`. Do not modify anything under `tasks/`.

You may use local code to process the supplied inputs. Do not invent sources,
identifiers, downloads, measurements, geological interpretations, or causal
claims. When evidence is insufficient, state the limitation or reject the
unsupported operation as required by the task.

Complete Q01 through Q08 independently. At the end, verify that all required
outputs exist and that structured files parse successfully. Report generated
paths and any genuine environment failures. Do not attempt to grade or repair
the submission against hidden expectations.
