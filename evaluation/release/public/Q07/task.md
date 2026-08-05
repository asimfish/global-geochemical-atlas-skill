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
