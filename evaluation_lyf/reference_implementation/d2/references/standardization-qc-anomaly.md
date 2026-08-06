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

`record_id`、`source_record_id`、`sample_id`、`igsn`、`analyte_reported`、`species_or_oxide`、
`measurement_basis`、`value_qualifier`、`source_qualifier_raw`、`missing_reason`、`detection_limit`、`detection_limit_unit`、
`latitude`、`longitude`、`source_crs`、`coordinate_transform_method`、`coordinate_uncertainty_m`、
`geologic_unit`、`analytical_method`、`method_family`、`digestion_or_extraction`、`laboratory`、
`reference_material`、`license`、`source_tier`、`sampled_at`、`sample_depth_min_m`、
`sample_depth_max_m`、`grain_fraction`、`dataset_title`、`dataset_doi`、`dataset_version`、
`source_file`、`source_row`、`source_locator`、`file_sha256`。

输出另保留 `original_latitude_raw` 与 `original_longitude_raw`。无效或疑似交换的坐标不会写入 canonical
`latitude`/`longitude`，但原始表达不会丢失。

来源列名不同时使用 `--schema-map`，映射格式见 `contracts/schema-map.schema.json`。脚本只输出 canonical 字段，
D1 仍应在 source manifest 保存来源查询、许可和下载证据。

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

只有 `species_or_oxide` 明确、目标元素一致且化学式位于审计白名单时才换算。v2 白名单包括常见
`SiO2`、`TiO2`、`Al2O3`、`FeO`、`Fe2O3`、`MnO`、`MgO`、`CaO`、`Na2O`、`K2O`、
`P2O5`、`Cr2O3`、`CoO`、`NiO`、`CuO` 和 `ZnO`。

`element_value = compound_value × element_stoichiometric_mass / molecular_mass`。输出必须记录复合换算因子、
公式和 `d2-atomic-weights-v1`。`Fe2O3T`、总铁等含混表达失败关闭，不进行通用化学式猜测。

### 水体介质

目标单位为 `µg/L`：

| 原单位 | 乘数 |
|---|---:|
| `µg/L`、`mcg/L` | 1 |
| `mg/L` | 1,000 |
| `ng/L` | 0.001 |
| `g/L` | 1,000,000 |

水体中的 ppm、ppb、wt% 或质量比单位没有密度与 basis 时保持未转换，并加 `AMBIGUOUS_AQUEOUS_RATIO_UNIT`。

### 删失值

- `<x`、`<=x`、`BDL`、`ND`、`N`、`L` 作为左删失或未检出；`trace` 表示检出但不可定量。
- `>x`、`>=x` 作为右删失。
- 删失记录的 `normalized_value` 必须为空；若检出限可换算，写入 `normalized_censoring_limit`。
- 不默认使用 0、LOD/2、LOD/√2 或随机值替代。
- 下游异常分析默认排除删失记录，并报告排除数量。
- `not_reported`、`not_analyzed`、`insufficient_sample` 和 `invalid_value` 写入 `missing_reason`，不与零或 ND 混同。

## 4. QC flags

严重级别：`error`、`warning`、`info`。

关键 flags：

- 值与单位：`MISSING_VALUE`、`INVALID_NUMERIC_VALUE`、`INVALID_MISSING_REASON`、`INVALID_DETECTION_LIMIT`、`NEGATIVE_CONCENTRATION`、`UNSUPPORTED_UNIT`、`AMBIGUOUS_AQUEOUS_RATIO_UNIT`、`UNSUPPORTED_SPECIES_CONVERSION`、`OXIDE_ELEMENT_MISMATCH`、`CENSORED_VALUE`、`NONDETECT_WITHOUT_LIMIT`、`UNQUANTIFIED_TRACE`。
- 语义：`MISSING_MEASUREMENT_BASIS`、`MISSING_ANALYTICAL_METHOD`、`MISSING_DIGESTION_OR_EXTRACTION`、`UNRECOGNIZED_ANALYTE`。
- 坐标：`INVALID_COORDINATE`、`INCOMPLETE_COORDINATE`、`POSSIBLE_COORDINATE_SWAP`、`ZERO_ISLAND_COORDINATE`、`OUTSIDE_REQUEST_REGION`、`MISSING_SOURCE_CRS`、`UNSUPPORTED_SOURCE_CRS`、`MISSING_COORDINATE_UNCERTAINTY`、`INVALID_COORDINATE_UNCERTAINTY`。
- 来源：`MISSING_SOURCE_ID`、`MISSING_SOURCE_LOCATOR`、`MISSING_LICENSE`、`UNKNOWN_SOURCE_TIER`。
- 样品：`MISSING_SAMPLE_ID`、`DEPTH_RANGE_INVALID`、`DUPLICATE_CANDIDATE`。

脚本不得静默修正可能交换的坐标；只有 D1 提供区域范围并能无歧义证明交换后落入范围时，后续版本才允许显式更正并保留变更记录。

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

来源分量的 v2 起始值为：官方策展 1.00、政府机构 0.95、同行评审 0.90、机构仓储 0.80、作者补充材料 0.75、聚合站 0.55、未知 0.30；缺少 source ID、精确定位、许可，或有源文件却无 SHA-256 会继续扣分。来源 tier 必须由 D1 根据来源与版本信息显式填写，不按域名自动猜测。

若记录存在任一 `error` 级 flag，`overall` 上限为 0.59，即强制进入 low。这个 gate 防止字段看似完整、但单位或坐标不可用的记录得到 high。上述参数是版本化的工作流启发式，应通过 E2 的 holdout/失败案例校准，不能解释为统计概率。

- high：`overall >= 0.80`
- medium：`0.60 <= overall < 0.80`
- low：`overall < 0.60`

该分数名称必须写作 `operational_confidence`。不得称为概率、统计置信水平或测量准确度。

## 6. 候选异常

默认分组字段：`element_or_analyte`、`medium`、`measurement_basis`、`geologic_unit`、`method_family`、`digestion_or_extraction`。缺少方法字段的记录会落入显式 `null` 组并降低置信度；不同已知方法族默认不混合。

处理步骤：

1. 只使用成功标准化、非删失、非重复候选、正的 `normalized_value`。
2. 以去除重复候选后的独立记录为分母，可量化有效比例默认至少 70%；不足输出 `insufficient_quantified_fraction`。
3. 每个背景组默认至少 20 条有效记录；不足输出 `insufficient_group_size`。合成 demo 可显式传 `--min-group-size 8`，不得冒充生产默认。
4. 对浓度取 `log10`。
5. 计算中位数和原始 MAD。
6. 计算 modified robust z-score：`0.67448975 * (x - median) / MAD`。
7. 默认 `|z| >= 3.5` 标记为 `candidate_anomaly`，方向为 high 或 low。
8. MAD 为零时不强行给异常；输出 `zero_dispersion`，等待 E2 验证其他背景模型。
9. 输出背景组字段、独立记录数、有效比例、删失比例、排除数、median、MAD、阈值和方法版本。

阈值可配置，但任何阈值变化必须写入报告。不同分析方法或消解/提取造成明显不可比时，调用方应把这些字段加入 `--group-by`。

## 7. 输出文件

- `geochemistry.csv`：canonical 标准记录；`qc_flags` 为 JSON 数组字符串。
- `samples.geojson`：具有有效 WGS84 坐标的标准样点。
- `qc_report.json`：记录数、标准化率、删失数、坐标有效数和 flags 统计。
- `confidence_report.json`：公式版本、权重、分量均值和 band 分布。
- `anomalies.geojson`：候选异常点；无有效坐标时 geometry 为 null。
- `anomaly_report.json`：所有背景组的统计与无法计算原因。
- `map_spec.json`：D3 的图层、筛选、空值和免责声明契约。
- `run_manifest.json`：E1 的输入/输出 SHA-256、版本、参数和计数契约。

## 8. 科学依据与边界

- [USGS QA/QC primer](https://pubs.usgs.gov/publication/ofr20111187) 强调从采样设计、实验分析到最终解释均需 QA/QC：DOI `10.3133/ofr20111187`。
- [USGS Alaska Geochemical Database 元数据](https://pubs.usgs.gov/ds/759/contents/AGDB2_DS759_metadata/AGDB2_MD.faq.html) 显示历史地球化学数据会用 qualifier、负数或尾数编码检测限。编码因数据集而异，因此 D1 必须保留并按来源元数据解码；D2 不从负数擅自推断 qualifier。
- [NIST 异常检测手册](https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm) 给出 modified z-score 的 median/MAD 公式，并把绝对值 3.5 作为潜在 outlier 的常用阈值；本实现使用更精确常数 `0.67448975`。
- 稳健 median/MAD 可降低极值对背景估计的影响，但结果依赖分组和空间尺度；它只是可复现 baseline，不替代局部地质模型、空间自相关或多变量分析。
- 任何异常的自然背景、矿化、人为输入和方法差异均需作为竞争解释；本工作包不输出成因结论。
