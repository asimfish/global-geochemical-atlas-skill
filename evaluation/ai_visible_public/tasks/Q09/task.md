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

下文提到的 `normalized_observations.csv`、`group_summary.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q09 介质、相态和基准隔离

标准化 `inputs/mixed_media.csv`，但不得把不可比记录强行合并。

- 固体质量/质量统一到 `mg/kg`；
- 水体质量/体积统一到 `ug/L`；
- 不在没有含水率时把湿基换成干基；
- dissolved 与 total 不自动合并；题中 `filtered_dissolved` 映射到 dissolved family；
- `comparison_group` 为 `medium|basis|phase_family`。

输出 `normalized_observations.csv` 与按 comparison_group 汇总的 `group_summary.csv`。汇总使用非删失记录中位数，且必须保留组内单位。

`comparison_group` 必须按冻结的 `medium|basis|phase_family` 三段格式输出。例如湿基土壤 total 为 `soil|wet|total`，aqueous 水体的 dissolved family 为 `water|aqueous|dissolved`。不得使用自由文本同义标签。
