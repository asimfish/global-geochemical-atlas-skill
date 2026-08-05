# Q23 背景条件化异常

使用每个地质单元的冻结 `center_log10` 和 `scale_log10` 计算候选记录的 robust z；`|z| >= 3.5` 才写入 `contextual_anomalies.csv`。异常方向为 `relative_enrichment` 或 `relative_depletion`。

另写 `interpretation.md`，说明结果是相对于地质单元背景的统计异常，不能单独建立矿床、污染源或因果机制。不得使用全局背景替代 unit_id 匹配。
