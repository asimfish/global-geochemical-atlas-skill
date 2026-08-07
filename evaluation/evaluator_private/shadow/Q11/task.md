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

下文提到的 `geologic_matches.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q11 地质单元匹配

对 `inputs/points.csv` 与 `inputs/units.geojson` 做点在多边形匹配，并按 `match_policy.json` 输出 `geologic_matches.csv`：

```text
point_id,unit_id,match_status,distance_to_boundary_deg,coordinate_precision_m,match_confidence,qc_flags
```

共享边界上的点记为 `ambiguous_boundary`，不得任意选一侧；无覆盖点记为 `no_match`。距离边界过近或坐标精度过粗都必须降低置信度。

冻结枚举为：

- `match_status`：`matched`、`no_match`、`ambiguous_boundary`；
- `match_confidence`：`high`、`medium`、`low`；
- `qc_flags`：`near_unit_boundary`、`coordinate_precision_coarse`；多个 flag 使用分号连接并按字母排序，无 flag 留空。
