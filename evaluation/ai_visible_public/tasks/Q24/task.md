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

下文提到的 `observations.csv`、`qc_report.json`、`sources.jsonl`、`confidence_report.json`、`map.geojson`、`anomalies.geojson`、`run_manifest.json`、`summary.md` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

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
confidence_report.json
map.geojson
anomalies.geojson
run_manifest.json
summary.md
```

`sources.jsonl` 必须按输入来源文件逐文件记录来源完整性证据；本题有且仅有
`source_a.csv` 和 `source_b.csv` 两个来源文件，因此必须恰好输出 2 行，不得把每条测定重复写成来源行。

`confidence_report.json` 必须报告来源完整性、单位标准化、空间证据、质量控制和来源追溯五个证据分量、聚合方法及适用边界；该分数是可审计的工作流证据完整度，不得解释为测定值或异常成因“正确”的概率。

E1 物理产物 `artifacts/map.html` 必须离线打开后真实渲染上述 `map.geojson` 的点，并至少支持缩放或平移、异常图层开关、点击样点查看 `record_id` 与 `source_id`。仅生成静态 SVG、表格或包含关键词但不工作的控件不算可交互地图；候选退出后由控制器使用 Chromium 和截图验收。

由于至少一个来源完整性失败且一个分析组不满足异常条件，成功生成其余产物时也应报告 `partial_success` 和退出码 `2`，不能隐藏降级。

异常 GeoJSON 的 `properties.anomaly_type` 固定写
`statistical_relative_enrichment` 或 `statistical_relative_depletion`。
`summary.md` 必须原样包含以下确定性审计标记，并可在其前后补充中文解释：

```text
partial success
Source integrity
censored
invalid coordinate
statistical relative enrichment
does not establish
```
