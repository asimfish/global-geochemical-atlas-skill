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

下文提到的 `group_statistics.csv`、`anomalies.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q14 稳健异常

严格按 `inputs/anomaly_policy.json` 处理 `inputs/values.csv`：正值取 `log10`，中心为 median，尺度为 `1.4826 × MAD`，`|robust_z| >= 3.5` 标异常。若 MAD=0，使用 policy 指定的严格经验分位数回退，不除零、不加任意 epsilon。

输出 `group_statistics.csv` 和 `anomalies.csv`。中心、尺度和 z 至少保留 8 位小数。

`group_statistics.csv.method` 的冻结值为：正常 MAD 路径使用 `robust_log10_mad`，MAD=0 回退使用 `empirical_quantile_fallback`。`anomalies.csv.anomaly_type` 使用 `relative_enrichment` 或 `relative_depletion`。
