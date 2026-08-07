# D1 候选来源逐源复核报告

> 历史审计快照：本文主体记录 2026-08-06 时的 14 来源阶段，不是当前覆盖总结。当前状态以 `v4-source-completeness.md`、`v4-full-population-profile.md` 和 V4 计划为准。文中的历史 MD5/SHA-256 值只为档案兼容保留；V4 不读取、比对、更新或使用它们准入、评分、缓存和验收。

复核标准：`geochemical-source-evidence-v3`

更新时间：2026-08-06 18:35（Asia/Shanghai）

## 当前结论

四个介质均已完成 canonical 适配、真实来源对账和端到端 fixture；在原七条路线和 FOREGS 六个介质来源基础上，AfSIS Phase I V2.0 非洲土壤已完成接入，因此共十四个可执行来源，当前都是 85 分、A 级、`normalized_analysis`。十四份 30 条人工复核单均已准备且机器比对通过，但尚未由具名人员逐条签署，因此不增加人工复核分，也不标记为 `benchmark_ready`。本轮另将 TPDC 中国山地土壤作为第 49 个目录来源完成官方 API、文件、hash 和字段审计，但按 V4 计划暂不接入旧 27 列交换格式。旧字段 `needs_human_review`、`production_eligible=false` 只为 V1 兼容保留，不再抹去已验证证据。

| 来源 | 已通过的关键项 | 尚未通过的关键项 | 当前决定 |
|---|---|---|---|
| `georoc-archaean` | DOI v12.0、28 个固定成员及校验、33,745 条源记录解析、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只覆盖太古宙克拉通专题 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `usgs-conus-soil` | USGS 固定发布、三层文件及 hash、14,571 条源记录解析、48 条 fixture 地图运行、跨三层 30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只覆盖美国本土 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `pangaea-north-africa-soil` | 具体 DOI、CC BY 4.0、固定 TSV/hash、43 行及六个目标元素各 43 条对账、48 条 fixture、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只有北非 43 个可风蚀细粒组分样点 | A 级 `normalized_analysis`，补充非洲土壤但尚未达到 `benchmark_ready` |
| `geotraces-idp2025` | 官方 DOI/IDP2025、CC BY 4.0/Fair Data Use、WebODV 冻结快照、242 个成员及 hash、69,704 行/39,327 条 Cu/Ni/Zn 观测对账、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；贡献者/方法完整率仍需审计；官方海水变量表没有 As | A 级 `normalized_analysis`，尚未达到 `benchmark_ready`；As 由 GEMStat 淡水路由补充且保持背景隔离 |
| `norway-marchem` | 官方公开 API、CC BY 4.0/NLOD、目标元素字段、单位、批次方法、观测 hash、完整成员清单、canonical 适配器、1,070 行对账和地图运行 | 30 条人工回看尚待完成 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `japan-gsj-geochemical-map` | 官方双 CSV、文件版本/hash、CP932 解码、JGD2000、3,024/3,024 序号连接、七元素/单位对账、48 条 fixture、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；源 CSV 缺逐行方法、检出限和 QC | A 级 `normalized_analysis`，补充独立河流沉积物区域但尚未达到 `benchmark_ready` |
| `gemstat-open-archive` | v3 版本 DOI、CC BY 4.0、五个精确 ZIP range、492,999 条 As 观测、站点/参数/方法连接、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；大量方法代码 0；33 国覆盖不均；重复、删失和 Pending review 值需分层使用 | A 级 `normalized_analysis`，补齐登记中的水体 As，但尚未达到 `benchmark_ready` |
| `foregs-topsoil` | 官方 ZIP/hash、5 个分析 CSV、4,195 行、10,908 条七目标元素映射、总量/王水量隔离、48 条 fixture、30 条复核准备 | 人工决定未签署；欧洲低密度调查；行级 `<DL` 限定符不可恢复 | A 级 `normalized_analysis`；不等于欧洲连续土壤覆盖 |
| `foregs-subsoil` | 官方 ZIP/hash、5 个分析 CSV、3,922 行、10,201 条七目标元素映射、深层土壤语义保留 | 同上；具体样点只说明 50–200 cm 范围内取 25 cm 层，不能伪造精确起止深度 | A 级 `normalized_analysis`；与 topsoil 分开 |
| `foregs-humus` | 官方 ZIP/hash、3 个分析 CSV、1,111 行、1,845 条目标映射、温和硝酸提取边界保留 | 人工决定未签署；没有 As/Cr；温和浸出不是总量 | A 级 `normalized_analysis`；仅补充腐殖质介质 |
| `foregs-stream-water` | 官方 ZIP/hash、808 行、As/Cr/Cu/Ni/Pb/Zn 各 808 条、<0.45 µm 与 ICP-QMS 方法保留 | 人工决定未签署；没有可接受 Hg；单次基线不是时间序列 | A 级 `normalized_analysis`；补充欧洲溪流水 |
| `foregs-stream-sediment` | 官方 ZIP/hash、4 个分析 CSV、3,393 行、11,030 条目标映射、总量/王水量和 <150 µm 粒级隔离 | 人工决定未签署；低密度溪流汇水区样点 | A 级 `normalized_analysis`；与 GSJ/MarChem 不静默合并 |
| `foregs-floodplain-sediment` | 官方 ZIP/hash、4 个分析 CSV、2,935 行、9,672 条目标映射、0–25 cm 与粒级保留 | 人工决定未签署；泛滥平原与溪流沉积物不是同一介质子型 | A 级 `normalized_analysis`；独立于 stream sediment |
| `afsis-phase-i-wet-chemistry` | 官方 Dataverse V2.0 三文件、2,002 个样品、12,012 条六元素数值、DL/QL 和方法映射、48 条 fixture、30 条复核准备 | 人工决定未签署；126 个缺坐标样品；负数和低于限值结果需分层解释 | A 级 `normalized_analysis`；补充非洲土壤但尚未达到 `benchmark_ready` |
| `tpdc-china-mountain-soil` | 官方 DOI/UUID、metadata/file API、1,828,683-byte ZIP 和三成员 hash、1,314 行与 6,570 条五元素观测对账 | V4 schema、canonical adapter 和 30 条复核未完成；As/Hg 缺失；CRS 未声明；bulk-density 补表存在冲突 | 文件契约已冻结的候选；当前不计入十四个可执行来源 |

## `georoc-archaean` 与 `usgs-conus-soil` 复核准备

GEOROC 复核单从完整 33,745 条缓存源记录中选择 30 个源行，覆盖 27 个归档成员、目标元素缺失案例、多引用案例和空间边界，共对应 63 条非缺失 As/Cu/Ni/Zn 观测。每条机器检查均确认成员 hash、样品 ID、精确点坐标、whole-rock 介质、未插补目标值、引用解析和稳定观测 ID。

USGS 复核单从三个各 4,857 行的土层文件中分别选择 10 行，共 30 行、120 条 As/Cu/Ni/Zn 观测。每条机器检查均确认文件 hash、样品 ID、坐标、土层、四元素原值与单位、深度语义和稳定观测 ID。

两份复核单均为 `status=prepared`、`automated_pass_count=30`、`completed_record_count=0`。自动通过只证明待检查内容与 hash 固定的源文件和适配器一致；人工签署前，人工复核维度仍为 `missing`、0 分。相关文件位于 `fixtures/four-media/rock/georoc-archaean/human_review.json` 和 `fixtures/four-media/soil/usgs-conus-soil/human_review.json`。

## `pangaea-north-africa-soil` 复核

- 具体表 DOI `10.1594/PANGAEA.949903`；父包 DOI `10.1594/PANGAEA.949906` 用于补充粒级、方法、参考物质和论文关系；
- 官方 `Table_S5.tab` 为 30,336 bytes，SHA-256 `de402b7f469c2d7c182abb285e624f2a1e6b1d00ec66e3dc2fae7ec9c8e4a485`；
- 解析 43 个源行、48 个元素字段，共 2,061 个非空元素值；As/Cr/Cu/Ni/Pb/Zn 各有 43 条，六元素合计 258 条登记目标观测；
- 数据集说明使用 HF-HNO3 消解和 Agilent 7900 ICP-MS；父包说明样品是可风蚀细粒组分，并报告参考物质结果处于目标值 ±10% 范围；
- 30 条分层复核记录已准备且机器比对 30/30 通过，人工决定为空；48 条 demo 从 12 个源行生成 As/Cu/Ni/Zn 各 12 条；
- 适用范围仅是 43 个离散样点。边境样点保留发布方地点文字，不按坐标强制赋国家，也不能把外包矩形解释为连续覆盖。

## `japan-gsj-geochemical-map` 复核

- 官方文件对为 `samplejoho.csv`（334,302 bytes，SHA-256 `9fdb58d86ad48eae564291421a0dad2b6f8a4f243d3e89d90016f3c61b0b521c`）和 `noudo.csv`（1,198,951 bytes，SHA-256 `0dbd2beae356adc45b762d50a9aa06ad556fd3ea004d427e369837bedda05671`）；
- 两表均按 CP932/Shift-JIS 解码。样点表 3,024 行，浓度表 3,024 个有效行；按“规范化样品号 + 出现序号”连接后 3,024/3,024，零漏连；
- 唯一重复样品号 `78013` 在两表中都出现两次，两次记录均保留，未被普通字典覆盖；
- As/Cr/Cu/Hg/Ni/Pb/Zn 各有 3,024 条。Hg 是 ppb，其他登记痕量元素是 ppm；原始坐标系是 JGD2000；
- 30 条复核记录覆盖重复键和单位边界，机器比对 30/30 通过，人工决定为空；48 条 demo 从 12 个样点生成 As/Cu/Ni/Zn 各 12 条；
- 本适配器只接河流沉积物。源 CSV 对没有逐行方法、检出限和 QC，适配器保持缺失，不把 GSJ 的海洋沉积物、表层土壤或 WMS 图层混入。

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

### 1. 产品与集合边界

- 产品：GEOTRACES Intermediate Data Product 2025，DOI `10.5285/42c92148-8d03-8be6-e063-7086abc09f0c`；
- 许可：CC BY 4.0，并适用 Fair Data Use Agreement；
- 完整产品元数据报告 123 个航次、4,097 个站位，包含离散海水、气溶胶、降水、冰冻圈和海水传感器五个包；
- 本轮只接入官方 WebODV 的 `GEOTRACES_IDP2025_Seawater` 离散海水集合。该集合元数据列出 4,094 个站位、82 个航次标签、28 个元数据变量和 418 个数据变量；
- 本轮进一步以“Cu、Ni、Zn 任一有值”为条件选择站位，因此快照内含目标观测的范围是 46 个航次和 1,550 个航次—站位组合，不能把产品、集合和本次快照三个层级的数量混写。

产品 DOI 不能替代记录级贡献者引用。Fair Data Use Agreement 要求引用相关原始出版物；适配器已经保留航次信息链接和随导出提供的引用字段，后续还要量化贡献者、方法和原始文献的完整率。

### 2. 冻结请求、文件与完整性

官方提取端点：

```text
POST https://geotraces.webodv.awi.de/IDP2025%3Eseawater%3EGEOTRACES_IDP2025_Seawater/service/DataExtraction/wsODV
```

本轮冻结深度以及 `Cu_D_CONC`、`Ni_D_CONC`、`Zn_D_CONC`，并用三个目标变量的 OR 条件选择站位。生成时间为 `2026-08-05T13:41:55Z`。完整第三方文件只进入本地缓存，Git 保存成员 manifest、对账和最小 fixture。

- 快照 ID：`geotraces-idp2025:IDP2025:a61f441e5ae2`；
- 归档：903,710 bytes，SHA-256 `a61f441e5ae269f6c5514a9279393728f464859d970ca6be19207f7e601e5677`；
- 归档成员：242 个，总展开大小 29,049,057 bytes；
- 主 ODV 文件：28,760,915 bytes，SHA-256 `c8b36f03b5950d751a497c91898cd2988ac07e1e4e9c4cebcb37ee1801106c44`；
- snapshot manifest 固定每个成员的路径、大小和 SHA-256；适配器在解析前验证归档、主文件、成员路径和预期物理行数。

可用 `scripts/acquire_geotraces_idp2025.py --accept-fair-use` 重新执行官方提取，也可用 `scripts/audit_geotraces_snapshot.py` 对缓存快照重算全部证据。重新下载会产生新快照，不覆盖本轮 hash。

### 3. 行、观测与覆盖对账

| 项目 | 结果 |
|---|---:|
| 物理样品深度行 | 69,704 |
| 至少含一个目标值的行 | 19,186 |
| 目标观测总数 | 39,327 |
| Cu / Ni / Zn 非空观测 | 6,275 / 17,035 / 16,017 |
| 含目标值的航次 | 46 |
| 航次—站位组合 | 1,550 |
| 深度范围 | 0–7,167 m |
| 采样日期范围 | 2005-01-10 至 2021-01-07 |

经纬度包围盒为 `[-179.990997, -77.7015, 180.0, 89.990501]`。它只表示航次采样点的外包范围，不代表包围盒内部或全球海洋连续覆盖。

### 4. 参数、单位和 QC

| 元素 | WebODV 变量 | 单位 | 非空观测 |
|---|---|---|---:|
| Cu | `Cu_D_CONC` | `nmol/kg` | 6,275 |
| Ni | `Ni_D_CONC` | `nmol/kg` | 17,035 |
| Zn | `Zn_D_CONC` | `nmol/kg` | 16,017 |

`nmol/kg` 是溶解态海水摩尔质量比。适配器原样保存；没有显式的元素原子量和海水密度转换时，不与 `ug/L` 静默混合。官方离散海水变量表没有 As 命中，因此本来源不能满足水体 As，请求 As 时必须转向另一个水体来源。

SeaDataNet QC 码按原值保留：1=good、2=probably good、3=probably bad、4=bad、5=changed、6=below detection。全量对账包含 3/4/5/6，不删除有问题的原始事实；最小 demo 只选择 QC 1/2。30 条复核样本特意覆盖 QC 1–6、地理和深度边界、多元素行及源文件顺序。

### 5. 端到端结果与剩余工作

- 适配器输出保留航次、站位、时间、经纬度、深度、dissolved 分相、标准差、QC、采样装置、航次链接、数据集 DOI 和源行定位；
- 30 条复核单机器检查 30/30 通过，共比较 65 个目标观测，覆盖 17 个航次；具名人工决定仍为空；
- fixture 平衡选择 Cu/Ni/Zn 各 16 条，共 48 条 QC 1/2 观测；标准化流程保留 `nmol/kg`，48/48 坐标有效并成功生成交互地图；
- 证据评分为 85/A/`normalized_analysis`，人工复核维度为 0 分，未虚增为 `benchmark_ready`。

剩余工作是完成 30 条具名人工签署、审计贡献者/方法/原始文献字段完整率，并继续增加独立海水来源。水体 As 已由 GEMStat 淡水路由补入，但不能与海水背景混算。

## `gemstat-open-archive` 复核

### 1. 版本、许可与选择性获取

- 产品：UNEP GEMS/Water Global Freshwater Quality Archive v3；
- 版本 DOI：`10.5281/zenodo.18459694`；概念 DOI：`10.5281/zenodo.13881899`；
- 发布日期：2026-02-02；许可：CC BY 4.0；
- 官方文件：`GFQA_v3.zip`，201,278,791 bytes，发布方 MD5 `00f3ea19ce529753977eb3aeb08fbc47`，84 个 ZIP 成员。

本轮没有把完整第三方归档提交到仓库，也没有把发布方 MD5 写成本机重算结果。`scripts/acquire_gemstat_arsenic.py` 用五段精确 HTTP Range 取得 `Arsenic.csv`、方法、参数、站点和 README；对每段分别验证压缩字节 SHA-256、本地 ZIP header、raw-deflate 解压、CRC、展开大小和展开 SHA-256。完整 ZIP 的大小和 MD5 只保留为发布方声明，`locally_full_archive_verified=false`。

### 2. 观测、分相与覆盖对账

| 项目 | 结果 |
|---|---:|
| As 观测总数 | 492,999 |
| As-Dis / As-Sus / As-Tot | 188,961 / 5,439 / 298,599 |
| As 站点 / 国家 | 15,621 / 33 |
| mg/l / µg/l | 453,413 / 39,586 |
| reported / `<` / `>` | 289,636 / 203,344 / 19 |
| 河流 / 湖泊 / 地下水 / 水库 / 湿地 | 402,080 / 43,253 / 30,671 / 13,886 / 3,109 |
| 采样日期 | 1975-04-28 至 2023-12-29 |
| 深度 | 0–500 m |
| 包围盒 | `[-139.78, -34.252553, 92.60805556, 81.9356]` |

包围盒和国家数只描述已提交站点，不能外推为包围盒内连续覆盖。`As-Dis`、`As-Sus`、`As-Tot` 分别表示溶解、悬浮和总量操作性分相，不能静默合并。

### 3. 方法、质量与源数据缺陷

- 24 个实际使用的参数—方法—单位组合全部能连接到方法元数据，但 449,714 条观测使用未定义方法代码 `0`；
- Data Quality 为 Fair 466,710、Unknown 19,789、Good 4,557、Pending review 1,649、Suspect 294；
- 发现 5,655 条额外精确重复观测，分布在 5,513 个重复组，最大重复倍数为 6；适配器不静默删除；
- 三条 `-999.999 µg/l` 负哨兵和 78 条 `>=1000 mg/l` 极端值均为 Pending review；保留用于审计，但不进入演示或异常结论；
- 站点元数据有 22,981 行、22,946 个唯一 ID 和 35 条内容完全相同的重复行；发布页称 22,982 个站点。参数元数据有 621 行，发布页称 622 个参数。这两个差 1 的矛盾保持显式。

### 4. 复核样本与端到端结果

30 条复核单覆盖三种分相、两种单位、五类水体、所有质量标签、定义/未定义方法、删失符号、空间/深度边界、精确重复和 Pending review 异常；机器检查 30/30 通过，人工字段为空。48 条 demo 则只选择 Good/Fair、方法明确、非负且非极端的观测，三种分相各 16 条，保留 12 条 `<` 删失值；48/48 完成 `ug/L` 标准化或同类质量/体积换算、坐标 QC、候选异常筛查和交互地图生成。

证据评分为 85/A/`normalized_analysis`。人工复核未签署只损失对应证据分，不阻断科研路由；它不能升级为 `benchmark_ready`。

## FOREGS 六介质复核

FOREGS 不是一个模糊的“欧洲来源”适配器，而是六个独立 `source_id`。官方数据包的科学发布为 2005 年；本轮固定 2026-03-03 发布方文件快照，每个 ZIP 和纳入解析的 CSV 都有 SHA-256、字节数、物理行数和源行定位。

| 来源 | CSV 行 | 不同 GTN 并集 | 七目标元素映射 |
|---|---:|---:|---:|
| topsoil | 4,195 | 862 | 10,908 |
| subsoil | 3,922 | 794 | 10,201 |
| humus | 1,111 | 388 | 1,845 |
| stream water | 808 | 808 | 4,848 |
| stream sediment | 3,393 | 855 | 11,030 |
| floodplain sediment | 2,935 | 750 | 9,672 |
| 合计 | 16,364 | 不跨介质相加 | 48,504 |

适配器保留三类不能越过的边界：

- 土壤和沉积物的 `total_selected` 与 `aqua_regia_leachable` 同时保留为不同测量基础；腐殖质的 4.5% HNO3 超声提取单独标为温和酸可浸出量；水体为 `<0.45 µm` 过滤溶解态；
- 表格第二、三行的原单位和检出限进入逐观测证据；发布 CSV 没有逐行 `<` 限定符，因此恰好等于 `DL/2` 的数值只标记为“可能的上游替代”，不伪装成已确认检出或可恢复删失值；
- GTN、国家字段、坐标、样品深度/粒级和具体分析成员保持原样。topsoil 中重复 GTN 通过文件名和行号保持为独立源记录，不用字典覆盖。

GTK 旧站当前的 HTTPS 证书链不能通过标准 TLS 校验，而官方文件端点仍可通过 HTTP 取得。适配器将其作为明确的来源级例外：只允许固定主机和固定 URL、拒绝重定向、下载前必须登记 64 位 SHA-256，只有内容完全匹配才发布到缓存。这个限制降低传输可用性，不改变文件内容完整性检查，也不能推广成通用 HTTP 下载策略。

六个来源各有 30 行待签署复核单，分层覆盖不同 CSV 成员、普通数值和可能的 `DL/2` 边界；机器比对均为 30/30 PASS，人工字段仍为空。每个来源另有 48 条 fixture；具备总量和王水量的来源按“元素 × 测量基础”平衡，水体和腐殖质按其实际可用目标元素平衡。

## AfSIS Phase I V2.0 复核

官方 World Agroforestry Dataverse 数据集 DOI 为 `10.34725/DVN/66BFOB`，固定版本 2.0（2025-10-13）。适配器只使用三个 `format=original` 文件，不使用 Dataverse 动态转换的 tabular 响应：

| 文件 | 字节 | SHA-256 | 发布方 MD5 |
|---|---:|---|---|
| wet chemistry CSV | 847,634 | `32a84536964d239969ecf3b7d805ceac0d14847b660ed99e209d70443d934605` | `2fa987e2c558e3b6c82eb6de3a772d26` |
| variables XLSX | 21,024 | `f2d5ee0b86af7b7d2066d610862e9bf8c97b7544803b201fb492bae61817ad3c` | `f5eadce8f97c265047a636b3cc9fc82e` |
| detection limits XLSX | 10,445 | `0b373fe17172d32861ebd829083a8f01c1bca7cbbc09e700c95dfb4f043011f1` | `df7a01bf4200a408c03280800f7d40bb` |

全量对账得到 2,002 个唯一 `SSN`、2,002 个唯一 `RES.ID`、18 个原国家标签、51 个国家-站点对、992 个 topsoil、1,010 个 subsoil 和 1,876 个完整坐标对；126 条记录同时缺少经纬度，不作坐标推断。注册文件和相关论文没有明确 CRS，因此不把经纬度无证据标成 EPSG:4326。As/Cr/Cu/Ni/Pb/Zn 各有 2,002 个发布数值，共 12,012 条目标测定。

所有元素均为风干土 `mg kg^-1` 王水消解准全量结果。As 使用 ICP-MS，其余五元素使用 ICP-OES；变量工作簿和 DL/QL 工作簿的单元格定位逐观测进入证据。变量表把字段 `As.75` 描述成“Arsenic-78”，并报告 2009–2013 采样，而相关 SOIL 论文报告 2009–2012；这两处冲突原样保留。发布数值不带逐行删失限定符，因此适配器保留原数值并另加阈值类别：As/Cu/Pb 分别有 48/6/7 个负数仪器结果；Pb 有 1,969 个正值低于 DL。它们不会被静默删除，也不会被冒充普通检出。30 条待签署复核单覆盖全部国家标签、上下层、缺坐标、三种负数元素和所有实际存在的阈值类别；机器 30/30 PASS，人工字段为空。

## TPDC 中国山地土壤文件契约复核

数据集 DOI `10.11888/Terre.tpdc.302620` 解析到 TPDC metadata UUID `2f4c2f30-166c-4a76-9b4a-74c98b4ca3b1`。本轮按照官方网页自身调用方式核实 metadata POST、根文件清单 GET 和 file-ID POST 下载；元数据返回 `sharePolicy=A`、`shareType=online` 和 licence code `1`，TPDC 前端许可表将 `1` 映射为 CC BY 4.0。

官方 `Soil dataset.zip` 为 1,828,683 bytes，SHA-256 `8cf3189b44aad64b65cd213c0fd015d30df5f1c59676823846292f83baa1a84a`，成员如下：

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `Description of the dataset.docx` | 1,246,886 | `e923ea91a29793cb224c29c1ff0693e92783c96889fbedb0100c10d48784999b` |
| `Soil bulk density.xlsx` | 33,386 | `bb03ed1ac9f2db514ca740c8a9c8eabe5965da871e9b77ca510942ba5159b682` |
| `Soil dataset.xlsx` | 577,715 | `923da5a896c0f403d227799cb04d565f75d641d5c81290889fcaddaa42ff593d` |

主表含 1,314 条唯一“`Sam.No` × `Horizons`”记录，没有精确重复，覆盖 30 座山地、166 个站点、485 个剖面样号；O/A/C 分别 381/481/452 条。Cr/Cu/Ni/Pb/Zn 均为 1,314 个数值且无负数或零，共 6,570 条目标观测；As 与 Hg 不在发布表。1,314 行都有数值有效经纬度、母岩类别、母岩组、土纲和土类，但来源没有声明 CRS。SN5、SN6、SN7 各出现多个坐标对，因此后续必须保留样品级坐标，不可强制聚合成站点中心。

关联论文说明样品风干并过 2 mm 筛，使用 HNO3-HF-HClO4 消解；Zn 属 ICP-AES 测定，Cr/Cu/Ni/Pb 属 ICP-MS。论文还报告空白、重复、GBW-07405、95%–105% 回收率以及 ICP-AES/ICP-MS 的 RSD 范围。工作簿本身没有逐行方法、检出限或限定符，所以这些事实只能作为 `method_scope=publication`，不能冒充行级字段。

主表有 67 个 BD 和 134 个 Thickness 缺失。单独 bulk-density 表提供 449 个“山地 × 站点 × 土层”键，可为 58 个主表缺失行提供候选值，但仍有 10 个主表行没有对应键；两表另有六个非空 BD 冲突和五个坐标冲突。适配器必须保留主表值、补表值、连接键和冲突标志，不得用补表静默覆盖主表。

这批证据已写入候选审计和目录，但没有提前计作第十五个可执行来源。下一步先落地 V4 `sample_type`、方法 scope 与地理/地质拆分，再实现适配器和 30 条分层复核。

## 四介质联合运行

`fixtures/four-media/combined-v3/request.json` 以 `sources=auto` 请求 As/Cu/Ni/Zn 和 rock/soil/sediment/water。路由选择十四个 A 级 `normalized_analysis` 来源，`scripts/build_four_media_demo.py` 验证每个来源 fixture 的 manifest hash 和逐观测证据后再合并：

| 介质/来源 | 观测数 |
|---|---:|
| rock / GEOROC | 48 |
| soil / USGS | 48 |
| soil / PANGAEA North Africa | 48 |
| sediment / MarChem | 112 |
| sediment / GSJ Japan | 48 |
| water / GEOTRACES | 48 |
| water / GEMStat | 48 |
| soil / FOREGS topsoil | 48 |
| soil / FOREGS subsoil | 48 |
| soil / FOREGS humus | 48 |
| soil / AfSIS Phase I | 48 |
| sediment / FOREGS stream sediment | 48 |
| sediment / FOREGS floodplain sediment | 48 |
| water / FOREGS stream water | 48 |
| 合计 | 736 |

联合流程得到 736/736 标准化、736/736 有效坐标、20 条已确认删失记录和完整九文件输出。D2 的默认背景键形成 89 个组，其中水体 17 个：`element + medium + measurement_basis + geologic_unit + analytical_method + digestion_or_extraction`。测试确认当前每组只来自一个兼容来源；FOREGS 的总量、王水、温和硝酸和溶解态边界以及 AfSIS 的王水准全量与 ICP-MS/ICP-OES 方法也没有与既有来源静默混合。FOREGS 中可能的 `DL/2` 数值和 AfSIS 的低于 DL/QL 数值只保留证据边界，不计入 20 条“已确认删失”。

筛查产生 16 个 fixture 候选异常，仅证明算法和地图可运行；联合 manifest 和结果都声明它们不支持污染、富集或亏损的科学结论。联合输入、证据、manifest 和九文件输出均可从十四个来源 fixture 字节级重建。

## 复核边界

本报告证明的是官方接口、下载响应、文件结构、适配器和元数据之间的可追溯关系，不证明每个历史测量值等于真实环境状态。覆盖矩阵按请求的最低 evidence tier 和 use mode 计算；四种介质都有 `normalized_analysis` 路由，但仍是专题、国家、区域、航次或自愿提交覆盖，全部保持 `partial`。土壤现有六个、沉积物四个、水体三个可执行数据集，但粒级、消解、海洋/河流/洪泛平原、分相与方法边界使它们不能自动构成同背景复测；水体 As、Cu、Ni、Zn 虽均已至少有两个来源，海水与淡水或不同方法仍必须隔离比较。
