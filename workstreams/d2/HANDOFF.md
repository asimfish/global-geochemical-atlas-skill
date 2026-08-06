# D2 → D1 / D3 / E1 / E2 交接单

版本：`d2-interface-v2`
机器契约：[`contracts/interface-contract.json`](contracts/interface-contract.json)

## 最终交付映射

- **标准化地球化学数据库**：`geochemistry.csv` + `schema.json`。
- **数据来源与置信度说明**：记录级 provenance 字段 + `confidence_report.json` + `run_manifest.json`。
- **异常区域识别结果**：`anomalies.geojson` + `anomaly_report.json`。
- **可交互元素分布地图**：D2 提供 `samples.geojson`、`anomalies.geojson` 和 `map_spec.json`；D3 负责 UI。
- **可复用 Skill 文档**：D3 将 D2 契约、规则和脚本合入唯一正式 Skill；D2 不创建第二个参赛 Skill。

## 给 D1：输入与来源追溯

一行表示一次样品—分析物测定。最低 canonical 列为：

```text
element_or_analyte,value,unit,medium
```

正式来源优先补齐：

```text
record_id,source_record_id,sample_id,igsn,analyte_reported,species_or_oxide,
measurement_basis,latitude,longitude,source_crs,coordinate_transform_method,
coordinate_uncertainty_m,geologic_unit,analytical_method,method_family,
digestion_or_extraction,detection_limit,detection_limit_unit,
source_id,dataset_title,dataset_doi,dataset_version,source_file,source_row,
source_locator,file_sha256,license,source_tier
```

来源列名不匹配时只维护一个映射 JSON，并通过 `--schema-map` 传给 D2；格式见
[`contracts/schema-map.schema.json`](contracts/schema-map.schema.json)。

D1 必须：

1. 保留 `<0.1`、`ND`、`BDL`、`trace`、未分析和原始 legacy qualifier；后者写入 `source_qualifier_raw`，不先替换为数值。
2. `species_or_oxide` 只在来源明确报告化学种/氧化物时填写；不要把推测值写成事实。
3. 保留源文件、源行、版本、SHA-256、许可和可复查定位。
4. 不删除完全重复、平行样或同一样品不同方法记录；可填写 `replicate_group_id` 或 `sample_identity_group`。
5. 坐标若已重投影为 WGS84，填写 `coordinate_transform_method` 并保留原 CRS 证据。

## 给 D3：地图消费

优先直接加载：

```text
samples.geojson
anomalies.geojson
map_spec.json
```

`map_spec.json` 已定义筛选器、图层、空值规则和必须展示的免责声明。D3 必须：

1. `normalized_value=null` 不画成零，不进入连续色标。
2. `censored=true` 使用不同符号并显示 qualifier/limit。
3. 无坐标记录保留在表格和 QC 面板，不落到 `(0, 0)`。
4. 异常图层显示 `candidate_anomaly` 和无因果解释边界。
5. 地图点能回溯 `source_locator`、原值、方法和置信度。

D3 不应重算单位、置信度或异常阈值，也不应维护第二份字段定义。

## 给 E1：工程验收

脚本只依赖 Python 标准库，所有路径和参数显式传入；成功退出码为 0，输入/映射错误退出码为 2；stdout 成功时
只输出一个 `role -> path` JSON。

```bash
python3 workstreams/d2/scripts/geochem_d2_pipeline.py \
  --input workstreams/d2/fixtures/demo_input.csv \
  --output-dir /tmp/geochem-d2-eval \
  --min-group-size 8
```

E1 验收：

- 8 个接口文件存在且 JSON/GeoJSON 可解析；
- canonical 记录符合 `schema.json`；
- `run_manifest.json` 符合 `contracts/run-manifest.schema.json`；
- manifest 中 7 个业务输出的大小和 SHA-256 与文件一致；
- 相同输入、映射和参数的全部 8 个文件逐字节一致；
- 任意列名 CSV 经 schema-map 后与 canonical 输入语义一致；
- 不存在密钥、绝对开发路径或网络依赖。

## 给 E2：科学验收

| 场景 | 预期行为 |
|---|---|
| 固体 `2.5 wt%` | `25000 mg/kg`，保留原值、因子和公式 |
| 显式 `0.018 wt% NiO` | 按固定原子量白名单换算 Ni，并记录规则版本 |
| `Fe2O3T` 等非白名单表达 | 拒绝换算，报 `UNSUPPORTED_SPECIES_CONVERSION` |
| 水体 `0.02 mg/L` | `20 ug/L` |
| 水体 `1 ppm` | 无密度/basis 时拒绝换算 |
| `<0.1` / `ND` / `trace` | 不插补；分别保留 qualifier、limit 和 missing/censoring 语义 |
| 非删失可量化比例低于 70% | `insufficient_quantified_fraction`，不评分 |
| 有效独立记录少于 20 | 生产默认 `insufficient_group_size` |
| MAD 为 0 | `zero_dispersion`，不添加任意 epsilon |
| robust z 超阈值 | 只输出 `candidate_anomaly` |
| error 级 QC | `operational_confidence.overall <= 0.59` |

20、70% 和 3.5 是版本化 baseline 参数，不是自然常数。E2 如要修改，必须提供测试证据并同步接口版本、报告和 demo 参数。

## 已知边界

- v2 不做下载、CRS 重投影、地质多边形匹配、空间自相关、插值或多元素组成分析。
- 氧化物仅支持明确白名单；总铁等含混表达失败关闭。
- 重复记录保留在 canonical DB，候选重复默认不进入异常背景。
- 当前公开飞书链接仍要求登录；团队若有既有字段，使用一次 schema-map 对齐，不再复制第二套 Schema。
