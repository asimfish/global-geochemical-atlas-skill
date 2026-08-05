# Q24 端到端小型图谱

使用五个输入资产生成可追溯的小型图谱。必须先做文件完整性和批次准入，再做单位、限定符、坐标、地图和异常。

固定规则：

- SHA-256 与 manifest 不一致的整个来源不得进入 observations；
- 只有 `batch_pass=true` 可进入；
- 固体 mass/mass 的 ppm → mg/kg；水体 mg/L → ug/L，组间不合并；
- `<x` 为左删失，保留 bound/qualifier，不作为精确值；
- 越界坐标进入数据库但不进入地图；
- 异常组按 `medium|basis|phase|element|method`，并要求坐标合法、非删失正值、`n>=20`；
- 合格组使用 log10 median 与 `1.4826*MAD`，`|z|>=3.5`；
- GeoJSON 坐标顺序为 longitude、latitude；每个 feature 必须回链 record_id 和 source_id。

输出：

```text
observations.csv
qc_report.json
sources.jsonl
map.geojson
anomalies.geojson
run_manifest.json
summary.md
```

由于至少一个来源完整性失败且一个分析组不满足异常条件，成功生成其余产物时也应报告 `partial_success` 和退出码 `2`，不能隐藏降级。
