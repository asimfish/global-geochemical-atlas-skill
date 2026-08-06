# D1 候选来源逐源复核报告

复核标准：`geochemical-source-evidence-v3`

更新时间：2026-08-06 12:00（Asia/Shanghai）

## 当前结论

四个介质均已完成 canonical 适配、真实来源对账和端到端 fixture；土壤、沉积物和水体各有两条互补路由，因此共七个来源，当前都是 85 分、A 级、`normalized_analysis`。七份 30 条人工复核单均已准备且机器比对通过，但尚未由具名人员逐条签署，因此不增加人工复核分，也不标记为 `benchmark_ready`。旧字段 `needs_human_review`、`production_eligible=false` 只为 V1 兼容保留，不再抹去已验证证据。

| 来源 | 已通过的关键项 | 尚未通过的关键项 | 当前决定 |
|---|---|---|---|
| `georoc-archaean` | DOI v12.0、28 个固定成员及校验、33,745 条源记录解析、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只覆盖太古宙克拉通专题 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `usgs-conus-soil` | USGS 固定发布、三层文件及 hash、14,571 条源记录解析、48 条 fixture 地图运行、跨三层 30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只覆盖美国本土 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `pangaea-north-africa-soil` | 具体 DOI、CC BY 4.0、固定 TSV/hash、43 行及六个目标元素各 43 条对账、48 条 fixture、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；只有北非 43 个可风蚀细粒组分样点 | A 级 `normalized_analysis`，补充非洲土壤但尚未达到 `benchmark_ready` |
| `geotraces-idp2025` | 官方 DOI/IDP2025、CC BY 4.0/Fair Data Use、WebODV 冻结快照、242 个成员及 hash、69,704 行/39,327 条 Cu/Ni/Zn 观测对账、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；贡献者/方法完整率仍需审计；官方海水变量表没有 As | A 级 `normalized_analysis`，尚未达到 `benchmark_ready`；As 由 GEMStat 淡水路由补充且保持背景隔离 |
| `norway-marchem` | 官方公开 API、CC BY 4.0/NLOD、目标元素字段、单位、批次方法、观测 hash、完整成员清单、canonical 适配器、1,070 行对账和地图运行 | 30 条人工回看尚待完成 | A 级 `normalized_analysis`，尚未达到 `benchmark_ready` |
| `japan-gsj-geochemical-map` | 官方双 CSV、文件版本/hash、CP932 解码、JGD2000、3,024/3,024 序号连接、七元素/单位对账、48 条 fixture、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；源 CSV 缺逐行方法、检出限和 QC | A 级 `normalized_analysis`，补充独立河流沉积物区域但尚未达到 `benchmark_ready` |
| `gemstat-open-archive` | v3 版本 DOI、CC BY 4.0、五个精确 ZIP range、492,999 条 As 观测、站点/参数/方法连接、48 条 fixture 地图运行、30 条复核单机器比对 30/30 通过 | 人工决定尚未签署；大量方法代码 0；33 国覆盖不均；重复、删失和 Pending review 值需分层使用 | A 级 `normalized_analysis`，补齐登记中的水体 As，但尚未达到 `benchmark_ready` |

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

## 四介质联合运行

`fixtures/four-media/combined-v3/request.json` 以 `sources=auto` 请求 As/Cu/Ni/Zn 和 rock/soil/sediment/water。路由选择七个 A 级 `normalized_analysis` 来源，`scripts/build_four_media_demo.py` 验证每个来源 fixture 的 manifest hash 和逐观测证据后再合并：

| 介质/来源 | 观测数 |
|---|---:|
| rock / GEOROC | 48 |
| soil / USGS | 48 |
| soil / PANGAEA North Africa | 48 |
| sediment / MarChem | 112 |
| sediment / GSJ Japan | 48 |
| water / GEOTRACES | 48 |
| water / GEMStat | 48 |
| 合计 | 400 |

联合流程得到 400/400 标准化、400/400 有效坐标、20 条删失记录和完整九文件输出。D2 的默认背景键形成 46 个组：`element + medium + measurement_basis + geologic_unit + analytical_method + digestion_or_extraction`。测试确认当前每组只来自一个兼容来源；除既有海水/淡水、分相、部分消解、土层和岩石选择值边界外，PANGAEA 细粒 HF-HNO3 土壤与 USGS 土层、GSJ 来源特定单位和方法缺失边界也未被混合。

筛查产生 11 个 fixture 候选异常，仅证明算法和地图可运行；联合 manifest 和结果都声明它们不支持污染、富集或亏损的科学结论。联合输入、证据、manifest 和九文件输出均可从七个来源 fixture 字节级重建。

## 复核边界

本报告证明的是官方接口、下载响应、文件结构、适配器和元数据之间的可追溯关系，不证明每个历史测量值等于真实环境状态。覆盖矩阵按请求的最低 evidence tier 和 use mode 计算；四种介质都有 `normalized_analysis` 路由，但仍是专题、国家、区域、航次或自愿提交覆盖，全部保持 `partial`。土壤和沉积物虽各有两个来源，但粒级、消解、海洋/河流与方法边界使它们不能自动构成同背景复测；水体 As、Cu、Ni、Zn 各自仍只有一个来源，海水与淡水也必须隔离比较。
