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

下文提到的 `cells.csv`、`heatmap_config.json`、`heatmap.html` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q16 热力图与网格聚合

按 `inputs/visualization_policy.json` 对 `inputs/cell_observations.csv` 预聚合，输出：

- `cells.csv`：cell_id、sample_count、quantified_count、median_value、censored_fraction；
- `heatmap_config.json`：冻结 aggregation、radius、color domain，并声明 sample-count 与 censored-fraction 图层；
- `heatmap.html`：包含标识 `GGA-HEATMAP-Q16`，以及 `sample_count`、`median_value` 字段说明。

删失值计入 sample_count 和 censored_fraction，但不进入 median。热力图只能称为探索性聚合视图，不得把样本密度表述为浓度。
