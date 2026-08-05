# Q13 异常分析准入

按 `inputs/eligibility_policy.json` 检查 `inputs/anomaly_input.csv` 中每个 group 是否允许连续异常评分。输出 `eligibility.json`。

优先级：先检查总样本数，再检查 quantified fraction。条件不满足时必须返回拒绝状态，`anomaly_scores_written=0`；不得为了生成完整产物而替代删失值。
