# D1 候选来源逐源复核报告

复核标准：`geochemical-source-evidence-v3`

更新时间：2026-08-05 21:13（Asia/Shanghai）

## 当前结论

首批复核已进入 V3 渐进评分：`georoc-archaean`、`usgs-conus-soil` 和 `norway-marchem` 均已完成 canonical 适配、真实来源对账和端到端 fixture，当前均为 85 分、A 级、`normalized_analysis`；三者的 30 条人工复核单已准备但尚未签署，因此不增加人工复核分，也不标记为 `benchmark_ready`。`geotraces-idp2025` 当前为 32.5 分、D 级、`discovery`。旧字段 `needs_human_review`、`production_eligible=false` 只为 V1 兼容保留，不再抹去已验证证据。

| 来源 | 已通过的关键项 | 尚未通过的关键项 | 当前决定 |
|---|---|---|---|
| `georoc-archaean` | DOI v12.0、28 个固定成员及校验、33,745 条源记录解析、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只覆盖太古宙克拉通专题 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `usgs-conus-soil` | USGS 固定发布、三层文件及 hash、14,571 条源记录解析、48 条 fixture 地图运行、跨三层 30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只覆盖美国本土 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `geotraces-idp2025` | 官方身份、不可变 DOI/IDP2025、CC BY 4.0、产品级 QC 描述 | BODC 归档仍在异步准备，未取得实际文件清单、成员 hash、变量表；未做适配器和人工抽查 | D 级 `discovery`，保留全部发现证据 |
| `norway-marchem` | 官方公开 API、CC BY 4.0/NLOD、目标元素字段、单位、批次方法、观测 hash、完整成员清单、canonical 适配器、1,070 行对账和地图运行 | 30 条人工回看尚待完成 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |

## `georoc-archaean` 与 `usgs-conus-soil` 复核准备

GEOROC 复核单从完整 33,745 条缓存源记录中选择 30 个源行，覆盖 27 个归档成员、目标元素缺失案例、多引用案例和空间边界，共对应 63 条非缺失 As/Cu/Ni/Zn 观测。每条机器检查均确认成员 hash、样品 ID、精确点坐标、whole-rock 介质、未插补目标值、引用解析和稳定观测 ID。

USGS 复核单从三个各 4,857 行的土层文件中分别选择 10 行，共 30 行、120 条 As/Cu/Ni/Zn 观测。每条机器检查均确认文件 hash、样品 ID、坐标、土层、四元素原值与单位、深度语义和稳定观测 ID。

两份复核单均为 `status=prepared`、`automated_pass_count=30`、`completed_record_count=0`。自动通过只证明待检查内容与 hash 固定的源文件和适配器一致；人工签署前，人工复核维度仍为 `missing`、0 分。相关文件位于 `fixtures/four-media/rock/georoc-archaean/human_review.json` 和 `fixtures/four-media/soil/usgs-conus-soil/human_review.json`。

## `norway-marchem` 复核

### 1. 获取契约

官方前端使用 `https://marchem-api.hi.no`。本轮先调用公开列表端点确认参数 ID，再请求无机元素组：

```text
GET https://marchem-api.hi.no/labParameterGroup/list
GET https://marchem-api.hi.no/mission/list
GET https://marchem-api.hi.no/project/list
GET https://marchem-api.hi.no/area/list
GET https://marchem-api.hi.no/owner/list

GET https://marchem-api.hi.no/export/published/dataByCriteria?fromYear=2003&toYear=2024&labParameterGroupIds=3,4&latitudeFrom=57&latitudeTo=85&longitudeFrom=-5&longitudeTo=38&asExcel=false
```

组 `3` 为重无机元素，组 `4` 为其他无机元素。服务返回 `application/zip`，导出说明文件记录生成时间为 `2026-08-05T10:27:11Z`。请求年份是 2003–2024，实际返回样品年份是 2015–2024，其中没有 2018 年样品；因此请求范围不能直接写成实际时间覆盖。

### 2. 文件与完整性

观测归档：`marchem-inorganic-2003-2024.zip`

- 归档大小：81,598 bytes；
- 本项目观测 SHA-256：`be888784ee2eafd45ab43c036eefbae9e760057d25f64fbc323993e8809ca6c6`；
- 数据 CSV：295,287 bytes，SHA-256 `0fdf99c5bfa3147c689d923acb9b56bea4ac9dac0455b58239eb2073858d2d10`；
- 方法元数据 CSV：320,402 bytes，SHA-256 `b6bcba10eab4bb8f2109cb7ac793c778dfe6e199b31214fdd2ab6d5a34056d2d`；
- 导出说明：3,383 bytes，SHA-256 `93e4db2dd0c726751f21557caa28a8da4275da87745369d0a506e8fbd84e584f`。

这些是本项目对一次响应的观测 hash，不是发布方 checksum。文件名包含生成时间，再次调用会产生新的归档和文件名。没有找到与本次含 As/Cu/Ni/Zn 的无机导出完全对应的不可变 DOI；搜索到的 NMDC DOI 是有机污染物发布，不能拿来给这批无机数据冒充版本标识。

完整机器复核结果和待人工检查的 30 条分层样本见 `fixtures/candidate-audits/marchem-inorganic-20260805T102709Z.json`。可用以下命令对相同下载包重算：

```bash
python scripts/verify_marchem_candidate.py \
  marchem-inorganic-2003-2024.zip \
  --request-url "EXACT_EXPORT_URL" \
  --observed-at 2026-08-05T10:27:11Z \
  --pretty
```

### 3. 记录、样品与目标元素对账

| 项目 | 结果 |
|---|---:|
| 数据 CSV 物理行 | 1,070 |
| 不同 `Sample_code` | 880 |
| 出现多行的 `Sample_code` | 190 |
| 至少含一个目标元素的物理行 | 880 |
| 至少含一个目标元素的样品 | 880 |
| 无目标元素的样品 | 0 |
| 同一样品含多条目标元素行 | 0 |

`1,070` 不能当作样品数。查询同时选择两个参数组后，190 个样品各出现了第二条不含 As/Cu/Ni/Zn 的行；每个样品只有一条目标元素行。适配器必须按“样品 × 参数 × 批次”展开，不能把物理行直接当样品，也不能在合并重复 `Sample_code` 时丢掉 `Batch_code`。

| 元素 | 原字段 | 非空 | 数值 | `<检出限` | 缺失 | 原始报告范围 |
|---|---|---:|---:|---:|---:|---:|
| As | `As_ICPOES_mg/kg` | 880 | 860 | 20 | 190 | 2–147 mg/kg |
| Cu | `Cu_ICPOES_mg/kg` | 880 | 862 | 18 | 190 | 1–47.9 mg/kg |
| Ni | `Ni_ICPOES_mg/kg` | 880 | 878 | 2 | 190 | 1–55.4 mg/kg |
| Zn | `Zn_ICPOES_mg/kg` | 880 | 875 | 5 | 190 | 4–154 mg/kg |

表里的下限和上限包含删失记录所报告的阈值，仅用于文件内容对账，不代表真实浓度最小值或最大值。`<2.0` 等原值必须保留为删失测定，不能用 0、阈值或阈值一半替代。

### 4. 方法与质量限制

方法元数据共有 338 行，其中目标元素对应 41 条“批次 × 参数”记录：28 条写明 `Accredited`，13 条写明 `Not accredited`。四个目标元素均为干重 `mg/kg`；LLQ 为 As 2、Cu 1、Ni 1、Zn 2 或 4 mg/kg，Zn 的限值随批次变化。

目标元素主要采用 ICP-OES/ICP-AES，并按 NS 4770 用 7 M HNO3 高压釜部分消解。发布方明确说明结果不代表样品总含量。因此后续适配器至少要保留：

- `Batch_code` 和分析物级方法记录；
- 原始方法名、仪器、消解/制样说明；
- `measurement_basis=dry_weight`；
- `digestion_scope=partial`，不能映射为 total；
- 批次级 LLQ、ULQ、测量不确定度和认可状态；
- 原始删失符号和值；
- 超出测量范围或不在认可范围内的批次备注。

### 5. 适配结果与剩余工作

canonical 适配器已处理合并批次表达式 `2021-0031 2023-0120`，并完成以下对账：

- 1,070 个物理行、880 个不同样品、190 个重复样品附加行；
- As/Cu/Ni/Zn 各 880 条，共 3,520 条目标观测；
- 3,520 条观测全部连接到批次级方法元数据，零漏连；
- `<` 删失值共 45 条，保持原始符号和阈值；
- 1,808 条目标观测连接到认可批次，1,712 条连接到未认可批次；
- 干重 `mg/kg`、部分硝酸消解和“非总含量”边界全部保留。

机器对账见 `fixtures/four-media/sediment/norway-marchem/adapter_reconciliation.json`。剩余工作是完成已经准备好的 30 条人工回看；在此之前保持 `normalized_analysis`，不标记为 `benchmark_ready`。

## `geotraces-idp2025` 复核

### 1. 已固定的产品事实

- 产品：GEOTRACES Intermediate Data Product 2025，第四次中间数据产品发布；
- DOI：`10.5285/42c92148-8d03-8be6-e063-7086abc09f0c`；
- BODC 元数据发布日期：2025-11-17，更新日期：2026-01-19；GEOTRACES 发布页标示 2025-11-20 发布；
- 许可：CC BY 4.0，并适用 Fair Data Use Agreement；
- 覆盖：2005-01-10 至 2023-01-24，所有主要海盆；
- 规模：123 个航次、4,097 个站位；
- 五个数据包：离散海水、气溶胶、降水、冰冻圈、海水传感器；
- 格式：ASCII、netCDF、ODV，带 QC flags 和可用时的 1-sigma 误差；
- 元数据声称可关联贡献者、分析方法和原始出版物。

产品级引用不能替代记录级贡献者引用。Fair Data Use Agreement 要求使用相关原始出版物；后续证据链必须保留航次、参数、数据贡献者和原始文献，不能只写 GEOTRACES DOI。

### 2. 下载状态与阻断项

BODC Published Data Library 提供官方元数据 API：

```text
GET  https://www.bodc.ac.uk/data/published_data_library/api/doi/42c92148-8d03-8be6-e063-7086abc09f0c
POST https://www.bodc.ac.uk/data/published_data_library/api/download/prepare/42c92148-8d03-8be6-e063-7086abc09f0c
POST https://www.bodc.ac.uk/data/published_data_library/api/download/check/42c92148-8d03-8be6-e063-7086abc09f0c
```

截至 2026-08-05 18:34（Asia/Shanghai），下载检查仍返回 `{"status":"notready","filename":null}`。因此本轮没有猜测下载文件名，也没有把网页摘要当作变量表或文件证据。

剩余工作：

1. 取得准备完成的官方归档，记录归档及全部成员文件名、大小、发布方 checksum 或本项目观测 hash；
2. 只选择与本任务介质一致的离散海水包，气溶胶、降水、冰冻圈和传感器包不能默认混入；
3. 核对 As/Cu/Ni/Zn 的具体参数、溶解/颗粒分相、采样系统、单位、QC flags、误差和检出限；
4. 冻结航次—站位—采样深度—样品—参数—贡献者—文献的映射；
5. 实现最小适配器并完成全量对账和 30 条分层人工回看。

## 复核边界

本报告证明的是官方接口、下载响应、文件结构和元数据之间的可追溯关系，不证明每个历史测量值等于真实环境状态。覆盖矩阵按请求的最低 evidence tier 和 use mode 计算；MarChem 现在可以参与 `normalized_analysis`，但只覆盖挪威海域，沉积物仍是 `partial` 而不是全球完整覆盖。
