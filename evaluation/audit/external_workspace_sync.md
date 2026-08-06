# External workspace synchronization record

The repo-local `evaluation/` tree is the authoritative maintenance location after this synchronization.

- Repaired Q09–Q24 source: copied from `e2-private-root-v6.0.0-draft.2` into `evaluation/evaluator_private/` before the external source was deleted.
- Source tree SHA-256: `326d20116863b6c17afbcbfe53aebdcf517f895421e1b0ea18c51cea919bfb94` over sorted relative file paths and file SHA-256 values.
- Files copied and checksum-verified before documentation normalization: 291.
- Q09–Q24 task-tree SHA-256 after repo synchronization: `4dbdcbafc8d67a82251b71bc9301a8a8cc670224b25f3bbbd5d242e75810c25c`; the external and repo-local task trees matched exactly before deletion.
- Legacy `benchmark_rebuild_v5` tree SHA-256: `0082fd2c9a4e074cb78c21a33b7e1df35f06611856ad14b5048727f2b0b56787`.
- The legacy rebuild contained no non-private file path absent from the current `evaluation/` tree. Its Q09–Q24 sources were superseded by the repaired draft.2 copies above.
- Candidate submissions were not sourced from either external directory and were preserved in place.

Q01–Q24 candidate-visible materials are generated only into `evaluation/ai_visible_public/`. Evaluator-only gold, checker and rubric files remain under `evaluation/release/public/` or `evaluation/evaluator_private/` and are forbidden from that bundle.
