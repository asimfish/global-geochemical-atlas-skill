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

下文提到的 `coordinate_qc.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q07 坐标 QC

检查 `inputs/coordinates.csv`，输出 `coordinate_qc.csv`：

```text
record_id,sample_id,original_latitude,original_longitude,qc_flags,suggested_latitude,suggested_longitude,eligible_map
```

规则：纬度范围 `[-90,90]`、经度范围 `[-180,180]`；`0,0` 标记为疑似占位；缺失值不可地图化；若交换后范围合法，只能标记 `possible_lat_lon_swap` 并给建议值，不得静默修改；同一 `sample_id` 出现相距明显的坐标时，两条都标记 `sample_coordinate_conflict` 并暂停入图。

多个 flag 使用分号连接并按字母排序；无 flag 留空。

`qc_flags` 只使用以下冻结字符串：

```text
latitude_out_of_range
longitude_out_of_range
possible_lat_lon_swap
possible_zero_zero_placeholder
missing_latitude
missing_longitude
sample_coordinate_conflict
```

例如纬度越界且交换后合法时使用
`latitude_out_of_range;possible_lat_lon_swap`。疑似 `0,0` 占位必须写
`possible_zero_zero_placeholder`，不能缩写为 `possible_placeholder`；缺少纬度或经度分别写 `missing_latitude`、`missing_longitude`。
