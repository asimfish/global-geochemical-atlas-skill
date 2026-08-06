# Q09–Q24 repo-local evaluator source

本目录保存 Benchmark `6.0.0-draft.2` 的 Q09–Q24 完整评分源，并随 repo 一起维护。

- `shadow/Q09`–`Q16`：八道历史 Shadow 回归题；
- `final_holdout/Q17`–`Q24`：八道历史已暴露的旧 Final 回归题，不是严格 holdout；
- 每个 `task.json` 都包含 `e2.candidate-visible.v1` 契约；
- 每个 `task.md` 都包含对应的候选可见契约与题目专用受控值；
- 答题 AI 不得读取本目录，只能读取 `../ai_visible_public/` 中生成的白名单投影；
- gold、checker 和 rubric 始终只用于评分与 smoke test。

从 `evaluation/` 验证：

```bash
python3 tools/validate_package.py .
python3 tools/verify_isolation.py --evaluation-root .
python3 tools/export_ai_bundle.py --validate-only ai_visible_public
```

这些任务最初从 Git commit `e2f91e6bf77f85bbf3d77b5b7959d23961fc7306` 恢复，并在 draft.2 中修复候选可见契约。正式 Final 必须重新生成、私下冻结和签名。
