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
