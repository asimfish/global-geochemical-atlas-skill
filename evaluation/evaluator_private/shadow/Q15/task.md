# Q15 点图 GeoJSON

从 `inputs/observations.csv` 生成 RFC 7946 GeoJSON `points.geojson` 和 `map_manifest.json`。

- 只纳入 `eligible_map=true`；
- Position 顺序必须为 `[longitude, latitude]`；
- features 按 record_id 排序；
- properties 保留 record_id、element、value、unit、medium、source_id、confidence_score、qc_flags；
- manifest 报告输入数、映射数、排除数、坐标顺序和 CRS84。

GeoJSON 本身不要添加旧式自定义 `crs` 成员。
