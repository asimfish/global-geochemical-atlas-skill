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

下文提到的 `decoded_values.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q18 来源编码解析

严格按 `inputs/encoding_rules.json` 解析 `inputs/encoded_values.csv`，输出：

```text
record_id,reported_value,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_quantitative
```

来源特定负数和哨兵值不得进入真实浓度统计；`G` 表示超过上限。保留 reported_value，不进行删失值替代。

输出中的标准化 `qualifier` 使用 `<` 或 `>`，因此来源代码 `G` 必须转换为 `>`。冻结 `missing_reason` 包括 `not_analyzed` 和 `not_reported`；缺失数值字段留空，不使用字符串 `null`。
