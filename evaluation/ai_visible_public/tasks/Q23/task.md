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

下文提到的 `contextual_anomalies.csv`、`interpretation.md` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q23 背景条件化异常

使用每个地质单元的冻结 `center_log10` 和 `scale_log10` 计算候选记录的 robust z；`|z| >= 3.5` 才写入 `contextual_anomalies.csv`。异常方向为 `relative_enrichment` 或 `relative_depletion`。

另写 `interpretation.md`，说明结果是相对于地质单元背景的统计异常，不能单独建立矿床、污染源或因果机制。不得使用全局背景替代 unit_id 匹配。

`anomaly_type` 使用 `relative_enrichment` 或 `relative_depletion`。为使确定性审计不依赖写作语言，`interpretation.md` 必须原样包含以下四个英文证据标记，并可在其前后补充中文解释：

```text
statistical anomalies
relative to each matched geologic unit
does not establish
independent
```
