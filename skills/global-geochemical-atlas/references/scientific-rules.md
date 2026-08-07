# 标准化、QC、置信度与异常规则

## 目录

1. 设计原则
2. 输入字段
3. 单位与删失值
4. QC flags
5. 运行级置信度
6. 候选异常
7. 输出文件
8. 科学依据与边界

## 1. 设计原则

- 保留原始表达，任何标准化都新增字段，不覆盖原值。
- 对语义不充分的换算失败关闭，不用默认密度或默认提取方法补齐。
- QC 用 flag 表达，不自动删除疑似错误或重复记录。
- 置信度表示记录对当前工作流的可用性，不是结论为真的概率。
- 异常表示相对于已声明背景组的候选高/低值，不表示污染、矿床或成因。

## 2. 输入字段

### 最低可运行列

| 字段 | 含义 |
|---|---|
| `element_or_analyte` | 元素符号、元素名或原始分析物名 |
| `value` | 原始数值或带 qualifier 的原始字符串，例如 `<0.1`、`BDL` |
| `unit` | 原始单位 |
| `medium` | `rock`、`soil`、`sediment`、`water` 等介质 |

### 推荐列

`record_id`、`source_record_id`、`sample_id`、`analysis_batch_id`、`igsn`、`analyte_reported`、`species_or_oxide`、
`measurement_basis`、`value_qualifier`、`source_qualifier_raw`、`missing_reason`、`detection_limit`、`detection_limit_unit`、
`original_latitude_raw`、`original_longitude_raw`、`latitude`、`longitude`、`source_crs`、
`coordinate_transform_method`、`coordinate_evidence_scope`、`coordinate_policy_id`、
`coordinate_latitude_field`、`coordinate_longitude_field`、`coordinate_uncertainty_m`、
`geologic_unit`、`lithology`、`analytical_method`、`method_family`、`digestion_or_extraction`、
`laboratory`、`reference_material`、`license`、`source_tier`、`sampled_at`、`sample_depth_min_m`、
`sample_depth_max_m`、`grain_fraction`、`dataset_title`、`dataset_doi`、`dataset_version`、
`source_file`、`source_row`、`source_locator`、`file_sha256`。

输出另保留 `original_latitude_raw` 与 `original_longitude_raw`。无效或疑似交换的坐标不会写入 canonical
`latitude`/`longitude`，但原始表达不会丢失。

来源列名不同时可向 D2 CLI 提供 `--schema-map` JSON 对象；脚本只输出 canonical 字段，D1 仍应在
source manifest 保存来源查询、许可、下载哈希和源列映射。

专业平台字段的语义参照、转换类型和信息损失见 `platform-field-crosswalk.md`；机器可读版本为
`platform-field-crosswalk.json`。Crosswalk 用于指导 D1 的显式 schema map 和未来 exporter 设计，
不表示当前 CSV 已通过 EarthChem、USGS、ODM2、IGSN 或 DataCite 的原生格式认证。来源数据字典优先于
通用列名相似度；`no_direct_equivalent` 字段不得由模型猜测补齐。

## 3. 单位与删失值

### 固体介质

目标单位为 `mg/kg`：

| 原单位 | 乘数 |
|---|---:|
| `mg/kg`、`ppm`、`µg/g`、`g/t` | 1 |
| `wt%`、`wt.%`、`wt. %` | 10,000 |
| `ppb`、`µg/kg`、`ng/g` | 0.001 |
| `g/kg`、`mg/g` | 1,000 |

适用介质：rock、soil、sediment、mineral、concentrate。`ppm`/`ppb` 只有在固体质量比上下文中才按上表处理。
裸 `%` 不等同于 `wt%`，因质量/体积语义不明而拒绝转换。

### 氧化物转元素

只有 `species_or_oxide` 或 `analyte_reported` 明确报告了化合物、目标元素一致且化学式位于审计白名单时才换算。v2 白名单包括常见
`SiO2`、`TiO2`、`Al2O3`、`FeO`、`Fe2O3`、`MnO`、`MgO`、`CaO`、`Na2O`、`K2O`、
`P2O5`、`Cr2O3`、`CoO`、`NiO`、`CuO` 和 `ZnO`。

`element_value = compound_value × element_stoichiometric_mass / molecular_mass`。输出记录复合换算因子、
公式和 `d2-atomic-weights-v1`。`Fe2O3T`、总铁等含混表达失败关闭，不进行通用化学式猜测。

### 水体介质

水体质量/体积浓度的目标单位为 `µg/L`：

| 原单位 | 乘数 |
|---|---:|
| `µg/L`、`mcg/L` | 1 |
| `mg/L` | 1,000 |
| `ng/L` | 0.001 |
| `g/L` | 1,000,000 |

水体中的 ppm、ppb、wt% 或质量比单位没有密度与 basis 时保持未转换，并加 `AMBIGUOUS_AQUEOUS_RATIO_UNIT`。

元素分析物的 `nmol/L` 仅在元素位于冻结原子量表时按
`µg/L = nmol/L × atomic_weight / 1000` 转换，并在 `conversion_formula` 记录元素、原子量和
`d2-ciaaw-abridged-2024-v1`。当前审计表覆盖 As、Cu、Fe、Ni、Pb、Zn；化合物、氧化物或未知元素
失败关闭，分别标记 `UNSUPPORTED_MOLAR_SPECIES` 或 `UNSUPPORTED_MOLAR_MASS`。

`nmol/kg` 是摩尔/质量浓度，不是 `µg/L` 的同义单位；即使元素原子量已知，缺少适用水体密度时也不
转换为质量/体积浓度。它原样作为 canonical same-unit 结果，并按单位与 measurement basis 隔离比较组。

### 坐标证据层级

`source_crs` 可来自文件、数据集元数据或版本化平台政策，输出分别标记
`file_declared`、`dataset_metadata_declared`、`platform_policy_declared`。平台政策不是按数值形态猜 CRS：
必须同时命中政策 ID、平台 DOI 规则和原始经纬度字段白名单，政策 URL、版本与页面 SHA-256 写入记录。

当前 `pangaea-geocode-wgs84-v1` 仅适用于带 `10.1594/PANGAEA.<id>` DOI 的 PANGAEA
`LATITUDE`/`LONGITUDE` geocode；依据固定版本的 PANGAEA Geocode 官方说明。字段被重命名、派生、投影，
或 DOI/字段证据不匹配时标记 `INVALID_COORDINATE_POLICY` 并停止 canonical 映射。该政策不扩展到
Mendeley 或普通用户 CSV。

### 删失值

- 将来源限定符原词写入 `source_qualifier_raw`；若旧输入只有 `value_qualifier` 或把限定符嵌在 `value`，从原表达无损提取限定符 token，再另行生成 canonical `value_qualifier`。
- `<x`、`<=x`、`<LOD`、`LOD`、`BDL`、`ND`、`N`、`L` 作为左删失或未检出；`<LOQ`、`LOQ`、`BQL` 使用显式 quantitation limit；`trace` 表示检出但不可定量。
- `>x`、`>=x` 作为右删失。
- 删失记录的 `normalized_value` 必须为空；若检出限可换算，写入 `normalized_censoring_limit`。
- 不默认使用 0、LOD/2、LOD/√2 或随机值替代。
- 下游异常分析默认排除删失记录，并报告排除数量。
- `not_reported`、`not_analyzed`、`insufficient_sample` 和 `invalid_value` 写入 `missing_reason`，不与零或 ND 混同。

## 4. QC flags

严重级别：`error`、`warning`、`info`。

关键 flags：

- 值与单位：`MISSING_VALUE`、`INVALID_NUMERIC_VALUE`、`INVALID_MISSING_REASON`、`INVALID_DETECTION_LIMIT`、`INVALID_QUANTITATION_LIMIT`、`NEGATIVE_CONCENTRATION`、`UNSUPPORTED_UNIT`、`UNSUPPORTED_MOLAR_MASS`、`UNSUPPORTED_MOLAR_SPECIES`、`AMBIGUOUS_AQUEOUS_RATIO_UNIT`、`UNSUPPORTED_SPECIES_CONVERSION`、`OXIDE_ELEMENT_MISMATCH`、`CENSORED_VALUE`、`NONDETECT_WITHOUT_LIMIT`、`UNQUANTIFIED_TRACE`。
- 语义：`MISSING_MEASUREMENT_BASIS`、`MISSING_ANALYTICAL_METHOD`、`MISSING_DIGESTION_OR_EXTRACTION`、`UNRECOGNIZED_ANALYTE`。
- 坐标：`INVALID_COORDINATE`、`INCOMPLETE_COORDINATE`、`COORDINATE_NOT_CANONICALIZED`、`POSSIBLE_COORDINATE_SWAP`、`ZERO_ISLAND_COORDINATE`、`OUTSIDE_REQUEST_REGION`、`MISSING_SOURCE_CRS`、`UNSUPPORTED_SOURCE_CRS`、`INVALID_COORDINATE_POLICY`、`PLATFORM_CRS_POLICY_APPLIED`、`MISSING_COORDINATE_UNCERTAINTY`、`INVALID_COORDINATE_UNCERTAINTY`。
- 地质匹配：`GEOLOGY_MATCH_NO_COVERAGE`、`GEOLOGY_BOUNDARY_UNCERTAIN`、`INVALID_GEOLOGIC_DISTANCE`、`INVALID_GEOLOGIC_MATCH_CONFIDENCE`。
- 来源：`MISSING_SOURCE_ID`、`MISSING_SOURCE_LOCATOR`、`MISSING_LICENSE`、`UNKNOWN_SOURCE_TIER`。
- 样品与批次：`MISSING_SAMPLE_ID`、`DEPTH_RANGE_INVALID`、`DUPLICATE_CANDIDATE`、`MISSING_ANALYSIS_BATCH_ID`、`BATCH_QC_NOT_EVALUATED`、`BATCH_QC_FAILED`。

脚本不得静默修正可能交换的坐标；只有 D1 提供区域范围并能无歧义证明交换后落入范围时，后续版本才允许显式更正并保留变更记录。

### 实验室分析批次门禁

批次 QC 是记录级 QC 之外的独立门禁。输入和 policy 分别由
[batch-qc-policy.schema.json](batch-qc-policy.schema.json) 与 CLI 契约冻结：

- CRM：对每条 `CRM` 重新计算 `recovery = observed / certified × 100%`，所有 CRM 均须落在显式闭区间；
- 空白：所有 `BLANK` 均须不超过 policy 上限；
- 重复样：每个 `pair_id` 必须恰好两条，以 `RPD = |x1-x2| / ((x1+x2)/2) × 100%` 重算并满足上限；
- 不接受输入自带的通过标签；缺 CRM、空白、完整重复对、批次 ID 或单位不一致均失败关闭；
- 只有全部必需检查通过才写 `batch_qc_status=pass`。失败/不完整批次写明处置并保留记录，但不能进入记录级或空间异常背景。

未提供批次 policy 不表示批次通过：产物状态固定为 `not_supplied`，运行摘要说明这项证据未评估。

## 5. 运行级置信度

五个分量均为 0–1：

| 分量 | 权重 | 依据 |
|---|---:|---|
| `source` | 0.30 | 来源等级、定位和许可 |
| `completeness` | 0.20 | 样品、分析物、介质、basis、方法、坐标、来源等字段 |
| `method` | 0.20 | measurement basis、分析方法、消解/提取完整性 |
| `spatial` | 0.15 | 坐标有效性、CRS 和坐标不确定性 |
| `qc` | 0.15 | error/warning/info flags 的惩罚 |

`overall = 0.30*source + 0.20*completeness + 0.20*method + 0.15*spatial + 0.15*qc`。

来源分量的 v3 起始值为：官方策展 1.00、政府机构 0.95、同行评审 0.90、机构仓储 0.80、作者补充材料 0.75、聚合站 0.55、未知 0.30；缺少 source ID、精确定位、许可，或有源文件却无 SHA-256 会继续扣分。来源 tier 必须由 D1 根据来源与版本信息显式填写，不按域名自动猜测。

v3 使用可审计门控：任一 `error` 级 flag 或缺少 canonical WGS84 坐标时，`overall` 上限为 0.59；坐标存在但缺少不确定性、方法上下文不完整，或岩石/土壤/非海洋沉积物缺少来源直报或空间匹配地质背景时，上限为 0.79。每条记录写入 `gates_applied`，报告汇总 `gate_counts`。这些 gate 防止字段看似完整但科学使用条件不足的记录得到 high。上述参数是版本化的工作流启发式，应通过 E2 的 holdout/失败案例校准，不能解释为统计概率。

- high：`overall >= 0.80`
- medium：`0.60 <= overall < 0.80`
- low：`overall < 0.60`

该分数名称必须写作 `operational_confidence`。不得称为概率、统计置信水平或测量准确度。

## 6. 候选异常

默认分组字段：`element_or_analyte`、`medium`、`material`、`sample_type`、`soil_horizon`、`sediment_environment`、`water_fraction`、`grain_fraction`、`measurement_basis`、`geologic_unit_raw`、`matched_geologic_unit`、`analytical_method`、`method_family`、`method_scope`、`digestion_or_extraction`。该组合防止土层、水体分相、沉积环境、方法 scope 和空间地质背景被静默合并；缺少字段的记录进入显式 `null` 组并降低置信度。

处理步骤：

1. 先排除批次失败/不完整与疑似重复，得到 `independent_record_count`；先检查总独立记录数，避免“小样本 + 高删失”被误报成删失率问题。
2. 再以独立记录为分母计算可量化有效比例，默认至少 70%；不足输出 `insufficient_quantified_fraction`。
3. 再检查成功标准化、非删失、正值的 `usable_record_count`。`demo` 默认至少 8，`production` 默认且强制至少 20；不足输出 `insufficient_usable_group_size`，不降低阈值。
4. 对可用浓度取 `log10`，计算中位数和原始 MAD。
5. 计算 modified robust z-score：`0.67448975 * (x - median) / MAD`。
6. 默认 `|z| >= 3.5` 标记为 `candidate_anomaly`，方向为 high 或 low。
7. MAD 为零时不强行给异常；输出 `zero_dispersion`，等待更合适的背景模型。
8. 输出背景组字段、独立记录数、有效比例、删失比例、排除数、median、MAD、阈值、门禁顺序和方法版本。

阈值可配置，但任何阈值变化必须写入报告。不同分析方法或消解/提取造成明显不可比时，调用方应把这些字段加入 `--group-by`。

### 空间候选区域

记录级 high/low 候选通过后，D2 可在固定 WGS84 网格中做第二道筛查：每个可比背景组和方向分别检验。在网格内、网格外均达到空间样本门槛时，使用一侧精确超几何检验判断候选是否过度集中；它以组内候选总数为条件，避免“网格外零候选”产生不现实的零 p 值。所有可检验的网格/方向假设一起执行 Benjamini–Hochberg FDR，默认 `q≤0.10`，且区域至少含 2 个记录级候选。生产空间门槛默认网格内外各 `n≥20`，demo 为各 `n≥5`。

结果方法版本为 `d2-spatial-hypergeometric-fdr-v1`。Polygon 只是固定筛查单元，不是插值面、地质/行政/污染边界；多尺度敏感性、空间自相关与独立验证仍是后续研究要求。没有通过门禁的区域表示证据不足，不表示不存在异常。

## 7. 输出文件

- `geochemistry.csv`：canonical 标准记录；`qc_flags` 为 JSON 数组字符串。
- `qc_report.json`：记录数、标准化率、删失数、坐标有效数和 flags 统计。
- `confidence_report.json`：公式版本、权重、分量均值和 band 分布。
- `batch_acceptance.csv`、`batch_qc_report.json`：批次重算结果、policy/hash 和排除处置。
- `anomalies.geojson`：候选异常点；无有效坐标时 geometry 为 null。
- `anomaly_report.json`：所有背景组的统计与无法计算原因。
- `anomaly_regions.geojson`、`spatial_anomaly_report.json`：FDR 筛查区域、精确检验、门槛和失败边界。

### D1、D3、E1、E2 协作接口

- D1 → D2：UTF-8 CSV，一行一个样品 × 分析物测定；非 canonical 列名必须用符合
  `schema-map.schema.json` 的显式映射，来源 qualifier、检出限、CRS、源行定位和文件 SHA-256 不得猜测。
- D2 → D3：固定生成上述九个分析产物；D3 可忽略可选内容，但不得把 null 浓度绘制为零、把统计区域与显示聚合混为一谈、把候选异常写成因果结论，或重新计算 `operational_confidence`。
- D2 → E1：`standardize_geochemistry.py` 成功时退出码为 0，并在 stdout 输出产物角色到路径的 JSON；无效输入或配置通过 argparse 以退出码 2 失败，写产物时采用原子替换。
- D2 → E2：`anomaly_report.json` 必须记录分组、最小样本量、最小可量化比例、modified z 阈值与
  `analyzed`、`insufficient_group_size`、`insufficient_quantified_fraction`、`insufficient_usable_group_size`、`zero_dispersion` 失败状态；空间报告另记录精确检验、假设总数和 BH-FDR。
- 相同输入字节、schema map、批次文件、policy 和参数应产生字节一致的九个 D2 产物；运行元数据记录输入与映射 SHA-256。

### 可选 GLiM 空间匹配

提供 `--geology-grid` 与对应 `--geology-grid-sha256` 时，D2 读取 PANGAEA.788537 的官方 GLiM 0.5° Arc/ASCII ZIP，按 WGS84 点位执行确定性 cell join。结果写入 `matched_geologic_unit`、`geology_map_source/version`、`match_method/scale`、`boundary_distance_m`、`match_uncertainty` 和 `geology_missing_reason`；输入的 `geologic_unit` 与 `geologic_unit_raw` 不被覆盖。网格 hash 和 join 版本进入所有运行元数据，汇总进入 `qc_report.json.geology_matching`。

GLiM 只表示 0.5° 主导表层岩性筛查背景，不是场地级地层或构造单元。水体和明确的海洋沉积物不赋陆地岩性；无 canonical WGS84 坐标、NODATA 和靠近 cell 边界的记录保留显式处置状态。没有同时提供网格与 SHA-256 时失败关闭，不从模型常识补地质单元。

## 8. 科学依据与边界

- [PANGAEA Geocode 官方说明](https://wiki.pangaea.de/w/handler?title=Geocode&oldid=17007) 声明平台
  `LATITUDE`/`LONGITUDE` geocode 为 WGS84 十进制度；`pangaea-geocode-wgs84-v1` 固定该页面版本、访问日和
  SHA-256，并只对 PANGAEA DOI 与精确字段白名单生效。
- [CIAAW 标准/简表原子量](https://www.ciaaw.org/abridged-atomic-weights.htm) 是
  `d2-ciaaw-abridged-2024-v1` 的权威依据；实现冻结常规元素值，在线页面更新不会静默改变已发布结果。
- [USGS QA/QC primer](https://pubs.usgs.gov/publication/ofr20111187) 强调从采样设计、实验分析到最终解释均需 QA/QC：DOI `10.3133/ofr20111187`。
- [USGS Alaska Geochemical Database 元数据](https://pubs.usgs.gov/ds/759/contents/AGDB2_DS759_metadata/AGDB2_MD.faq.html) 显示历史地球化学数据会用 qualifier、负数或尾数编码检测限。编码因数据集而异，因此 D1 必须保留并按来源元数据解码；D2 不从负数擅自推断 qualifier。
- [NIST Atomic Weights and Isotopic Compositions](https://www.nist.gov/pml/atomic-weights-and-isotopic-compositions-relative-atomic-masses) 说明其标准原子量数据来自 *Atomic Weights of the Elements 2013*；`d2-atomic-weights-v1` 固定使用该表中的代表值，避免在线表更新造成结果漂移。天然材料的同位素组成可能变化，因此这些换算是常规化学计量换算，不是样品特异的同位素质量模型。
- [NIST 异常检测手册](https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm) 给出 modified z-score 的 median/MAD 公式，并把绝对值 3.5 作为潜在 outlier 的常用阈值；本实现使用更精确常数 `0.67448975`。
- 稳健 median/MAD 可降低极值对背景估计的影响，但结果依赖分组和空间尺度；它只是可复现 baseline，不替代局部地质模型、空间自相关或多变量分析。
- 任何异常的自然背景、矿化、人为输入和方法差异均需作为竞争解释；本工作包不输出成因结论。
