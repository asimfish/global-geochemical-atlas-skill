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

下文提到的 `parsed_values.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q06 LOD 与限定符解析

解析 `inputs/censored_values.csv`，输出 `parsed_values.csv`：

```text
record_id,reported_value_text,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_log_analysis
```

规则：

- `<x`：左删失，`bound_value=x`、`detection_limit=x`，不能把 x 当精确浓度；
- `ND`/`BDL`：未检出；有独立 DL 时保留，无 DL 时不得猜测；
- 数值 `0` 是报告值，不等同 ND，但不能直接进入对数分析；
- `>x`：右删失/超过上限，不能把 x 当精确浓度；
- 空字符串：未报告，不等同未检出或 0。

本题不要求对删失值进行替代估计。

使用以下冻结语义值；不使用同义改写：

```text
<x       qualifier=<,  missing_reason 留空
ND       qualifier=ND
BDL      qualifier=BDL
>x       qualifier=>,  missing_reason=above_upper_limit
空字符串 missing_reason=not_reported
BDL/ND 且无可用 DL  missing_reason=below_detection_limit_unknown_limit
```

`censored` 和 `eligible_log_analysis` 必须是布尔值。未知、删失和未报告记录的 `numeric_value` 留空；数值 0 的 `numeric_value=0`、`censored=false`、`eligible_log_analysis=false`。
