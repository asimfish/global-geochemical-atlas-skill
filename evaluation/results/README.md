# Results

此处只保存真实运行产生的原始记录和由 E1 `score.json` 聚合出的报告。

除下方明确归档的真实运行外，本目录其余内容仅为模板或金标准自检；缺少被测 Skill、官方模型标识、冻结运行参数或沙箱日志的记录不得填写成“盲测结果”。金标准自检应写入 `validation/`，不能冒充 B0 或 S0 运行。原始记录必须使用 E1 状态、退出码和六维分数，旧版 `objective_score + llm_score` 字段不得作为正式总分。

## 已归档运行

- [`runs/2026-08-06-q01-q24-independent-grade/`](runs/2026-08-06-q01-q24-independent-grade/)：Q01–Q24 候选可见回归题的一次真实答题与独立评分记录，包含 `submissions/Qxx/artifacts/` 只读提交副本及其冻结 SHA-256。24 题的 `score.json` 均通过 E1 Schema，但由于缺少部分冻结维度证据，`score_status` 全部为 `partial`；Q17 标记为需要人工复核。该记录不是正式隐藏集成绩或完整官方总分，详细限制见 [`independent_grading_report.md`](runs/2026-08-06-q01-q24-independent-grade/independent_grading_report.md)。
