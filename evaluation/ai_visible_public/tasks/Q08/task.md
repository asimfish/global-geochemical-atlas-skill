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

下文提到的 `observations.csv`、`dedup_log.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q08 重复与多方法记录

处理 `inputs/duplicate_records.csv`：

- 仅去除科学字段和 `source_record_id` 完全相同的重复导入行；
- 实验室平行记录必须保留；
- 同一样品不同方法必须保留；
- 坐标相同但 sample_id 不同，不得自动合并。

输出：

- `observations.csv`：保留的记录，至少包含 `raw_row_id,source_record_id,sample_id,method,replicate_group_id,disposition`；
- `dedup_log.csv`：被移除的 raw row，列为 `removed_raw_row_id,duplicate_of_raw_row_id,reason`。

不需要从多方法记录中选“最佳值”。

`observations.csv.disposition` 使用以下冻结值：

```text
kept_original
kept_replicate
kept_method_difference
kept_distinct_sample
```

`dedup_log.csv.reason` 对完全重复导入固定写
`exact_duplicate_import`，不能使用自由文本同义说明。
