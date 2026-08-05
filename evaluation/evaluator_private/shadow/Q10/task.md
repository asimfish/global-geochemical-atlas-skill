# Q10 Schema 漂移适配

使用 `inputs/field_mapping.json` 读取两个列名不同的来源文件，生成同一个长表 `observations.csv`：

```text
record_id,source_id,source_record_id,sample_id,latitude,longitude,medium,element,reported_value,reported_unit,normalized_value,normalized_unit
```

两来源中的 Cu 都是固体质量/质量数据；ppm 与 mg/kg 可按题设等价。不得用行号替代 source_record_id，也不得丢失 source_id。
