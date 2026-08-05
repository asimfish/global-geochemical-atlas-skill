# Q07 坐标 QC

检查 `inputs/coordinates.csv`，输出 `coordinate_qc.csv`：

```text
record_id,sample_id,original_latitude,original_longitude,qc_flags,suggested_latitude,suggested_longitude,eligible_map
```

规则：纬度范围 `[-90,90]`、经度范围 `[-180,180]`；`0,0` 标记为疑似占位；缺失值不可地图化；若交换后范围合法，只能标记 `possible_lat_lon_swap` 并给建议值，不得静默修改；同一 `sample_id` 出现相距明显的坐标时，两条都标记 `sample_coordinate_conflict` 并暂停入图。

多个 flag 使用分号连接并按字母排序；无 flag 留空。
