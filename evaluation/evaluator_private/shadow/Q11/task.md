# Q11 地质单元匹配

对 `inputs/points.csv` 与 `inputs/units.geojson` 做点在多边形匹配，并按 `match_policy.json` 输出 `geologic_matches.csv`：

```text
point_id,unit_id,match_status,distance_to_boundary_deg,coordinate_precision_m,match_confidence,qc_flags
```

共享边界上的点记为 `ambiguous_boundary`，不得任意选一侧；无覆盖点记为 `no_match`。距离边界过近或坐标精度过粗都必须降低置信度。
