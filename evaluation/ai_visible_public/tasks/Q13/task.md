<!-- candidate-visible-contract-v1:start -->
## 答题 AI 可见的机器提交契约

本题逻辑输出的精确容器、格式、CSV 列和 JSON 结构位于
`task.json.candidate_visible_contract`。该字段是题面的一部分，答题 AI 必须读取并遵守。

特别是，`format="csv"` 的逻辑证据必须使用 `columns` 加对象数组 `rows`；
每个 row 以列名为键，不得使用依赖位置的数组行。JSON 逻辑证据必须使用
`{"format": "json", "value": ...}`。未声明的题目专用物理文件不得创建。
<!-- candidate-visible-contract-v1:end -->

<!-- e1-alignment-v1 -->
## E1 统一交卷要求

只生成 `task.json.required_outputs` 列出的十个 E1 物理产物，并保持 `artifacts/` 固定路径。不得另外创建题目专用文件。

下文提到的 `eligibility.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q13 异常分析准入

按 `inputs/eligibility_policy.json` 检查 `inputs/anomaly_input.csv` 中每个 group 是否允许连续异常评分。输出 `eligibility.json`。

优先级：先检查总样本数，再检查 quantified fraction。条件不满足时必须返回拒绝状态，`anomaly_scores_written=0`；不得为了生成完整产物而替代删失值。

`status` 使用冻结值：样本数不足写 `insufficient_sample_size`，quantified fraction 不足写 `excessive_censoring`，满足条件写 `eligible`。`eligible` 必须是 JSON 布尔值。
