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

下文提到的 `element_database.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q04 Fe2O3 转 Fe

处理 `inputs/rock_oxide.csv`，按 `inputs/conversion_constants.json` 的冻结原子量把 **Fe2O3** 换算为元素 Fe，并统一元素结果到 `mg/kg`。

```text
Fe fraction in Fe2O3 = (2 × M(Fe)) / (2 × M(Fe) + 3 × M(O))
```

要求：

- 原始 analyte、值和单位必须保留；
- 原本已是 Fe 的记录只做单位换算；
- FeO 记录保留，但本题不得套用 Fe2O3 因子；将其 `status` 记为 `not_requested`，标准化值留空；
- 输出 `element_database.csv`，列为：

```text
sample_id,analyte_reported,reported_value,reported_unit,element,normalized_value,normalized_unit,conversion_factor,conversion_rule,status
```

数值 checker 的绝对容差为 `0.02 mg/kg`。
