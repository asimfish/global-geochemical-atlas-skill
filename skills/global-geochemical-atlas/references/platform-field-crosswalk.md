# 专业平台字段 Crosswalk

## 1. 结论与使用边界

本 crosswalk 将 D2 的 `geochemistry-record.schema.json` 与四类专业数据表述对齐：EarthChem
Library（ECL）、USGS Alaska Geochemical Database 2.0（AGDB2）、ODM2，以及采用 DataCite
元数据的 IGSN。它有三项直接用途：

1. D1 接入新数据源时能说明“源字段为什么映射到这个 canonical 字段”；
2. D2 能区分直接复制、词表归一、单位转换、关系表拼接与本地扩展；
3. 后续导出 EarthChem/ODM2/IGSN 兼容数据时能识别缺失信息和不可逆损失。

**它不是 EarthChem、USGS、ODM2、IGSN 或 DataCite 的符合性认证。** 当前成果是语义对齐和差距清单，
没有声称生成任一平台的原生提交包。USGS AGDB2 是一个具体专业数据集的字段实践，也不是通用 USGS
交换标准。IGSN/DataCite 主要描述实体样品和持久标识符，不负责承载逐项分析结果。

机器可读版本见 `platform-field-crosswalk.json`；其结构由
`platform-field-crosswalk.schema.json` 约束。自动测试还会验证 crosswalk 与当前 118 个 canonical 字段
完全分区，防止 Schema 改动后文档悄悄过期。

## 2. 映射类型

| 类型 | 含义 | D1/D2 行为 |
|---|---|---|
| `exact` | 外部字段与 canonical 字段在已审查范围内语义相同 | 可复制，但仍保留来源定位 |
| `renamed` | 语义一致，只需改名或无损标识符规范化 | 显式列名映射，不猜测 |
| `transformed` | 需要单位、词表、日期、qualifier 或标识符转换 | 记录规则；失败时保留原值并置空 canonical 值 |
| `composite` | 需要多个字段、关系表或来源元数据共同构造 | 所有依赖字段齐全才生成 |
| `local_extension` | D2 为审计、QC 或分析主动增加的字段 | 不冒充专业平台原生字段 |
| `no_direct_equivalent` | 在引用的已审查表面中没有找到直接字段 | 不代表平台扩展机制无法表达；默认不推断 |

信息损失必须与映射同时记录。例如 `USGS Geol2.FIELD_ID + LAB_ID → sample_id` 不是简单改名：
前者偏向野外样品标识，后者是实验室接样标识，只保留其中一个会丢失身份层次。

## 3. 平台层次不能混为一谈

| 平台 | 本 crosswalk 使用的层次 | 适合对齐的内容 | 不应据此声称 |
|---|---|---|---|
| EarthChem ECL | 地球化学仓储模板与数据模型 | 样品、坐标、岩性、参数、方法、实验室、数据源 | 已生成可直接提交 ECL 的工作簿 |
| USGS AGDB2 | 政府地球化学数据集 | 实际历史字段、qualifier、单位、方法、坐标 datum、介质分类 | 所有 USGS 数据都使用同一 Schema |
| ODM2 | 观测关系模型 | SamplingFeature、Action、Method、Variable、Result、Unit、DataQuality、Provenance | 一个扁平 CSV 等价于完整 ODM2 关系库 |
| IGSN/DataCite | 实体样品 PID 与发现元数据 | IGSN、样品本地 ID、材料、采样日期、地理位置、关联数据集、权利 | IGSN 记录本身包含元素分析结果 |

OneGeochemistry 被作为全球地球化学标准化工作的背景方向引用，但当前 crosswalk 不把它当作已经冻结的、
可逐字段认证的统一 Schema。

## 4. 优先互操作字段矩阵

下表是快速索引。完整的转换规则、词表、信息损失和逐条证据 ID 位于机器可读 JSON。
“—”表示在本次引用的已审查表面中没有建立直接映射，而不是断言平台永远无法扩展表达。

### 4.1 样品、空间与地质描述

| Canonical 字段 | EarthChem ECL | USGS AGDB2 | ODM2 | IGSN/DataCite |
|---|---|---|---|---|
| `sample_id` | Sample Metadata.Sample name | `FIELD_ID`，辅以 `LAB_ID` | `SamplingFeatures.SamplingFeatureCode` | `alternateIdentifiers[]` |
| `igsn` | Sample Metadata.IGSN | — | `SamplingFeatureExternalIdentifiers` + identifier system | IGSN 记录的 DOI identifier |
| `medium` | sample type/material + Analyzed Material | `PRIMARY_CLASS` | `Specimens.SpecimenMediumCV` | `subjects`/title/resourceType 的显式材料词 |
| `material` | Data.Analyzed Material | `SECONDARY_CLASS` + `SPECIFIC_NAME` | `SpecimenTypeCV` + `SpecimenMediumCV` | `subjects[].subject` 或 title 中的显式材料 |
| `sampled_at` | 显式扩展采样日期 | `DATE_COLLECT` | collection `Actions.BeginDateTime` | `dates[]` 且 `dateType=Collected` |
| `latitude` | Sample Metadata.Latitude | `LATITUDE` + datum | `Sites.Latitude` + SpatialReference | `geoLocationPoint.pointLatitude` |
| `longitude` | Sample Metadata.Longitude | `LONGITUDE` + datum | `Sites.Longitude` + SpatialReference | `geoLocationPoint.pointLongitude` |
| `source_crs` | 仅接受显式声明 | `DATUM` + `SPHEROID` | `SpatialReferences.SRSCode/SRSName` | — |
| `sample_depth_min_m` | 显式扩展深度 | `DEPTH` 在值、单位和基准明确时解析 | 有定义的 extension/property | — |
| `sample_depth_max_m` | 显式扩展区间深度 | 只有显式区间才提取上界 | 有定义的 interval-depth extension | — |
| `lithology` | Sample Metadata.Lithology | 明确的样品描述字段，不能只用 `PRIMARY_CLASS` | SamplingFeature extension property | `subject`/title 中的显式岩性词 |

坐标转换必须特别保守。AGDB2 明确记录了历史坐标常见 NAD27/Clarke 1866 且精度不一，因此不能把其
经纬度直接改标签为 WGS84。只有 source datum 可解析、转换方法可记录时才写 canonical
`latitude`/`longitude`；否则保留原始坐标并输出 QC flag。

### 4.2 分析结果与方法

| Canonical 字段 | EarthChem ECL | USGS AGDB2 | ODM2 | IGSN/DataCite |
|---|---|---|---|---|
| `element_or_analyte` | Data.Parameter(s) 经词表归一 | `SPECIES` 经 Chem2 定义归一 | `Variables.VariableNameCV` + `VariableCode` | — |
| `analyte_reported` | Data.Parameter(s) 原标签 | `SPECIES` 源代码/标签 | `Variables.VariableCode` | — |
| `species_or_oxide` | 明确的 parameter species/oxide | `Chem2.SPECIES` | `Variables.SpeciationCV` | — |
| `measurement_basis` | Analyzed Material + Parameter + Method | method definition + species | Specimen + Action/Method + ProcessingLevel | — |
| `original_value` | Data 参数值列 | `DATA_VALUE` | `MeasurementResultValues.DataValue` | — |
| `original_unit` | 参数单位元数据 | `UNITS` | `Results.UnitsID → Units.UnitsAbbreviation` | — |
| `value_qualifier` | 只解析显式值语法 | `QUALIFIER` + 数据集编码规则 | `MeasurementResults.CensorCodeCV` | — |
| `censored` | 由显式 qualifier 派生 | `QUALIFIER` + `DATA_VALUE` | `CensorCodeCV` | — |
| `missing_reason` | 只有来源明确说明时填写 | qualifier/value + 数据集元数据 | `NoDataValue` + presence + annotation | — |
| `normalized_value` | 由 source value/unit 派生 | `DATA_VALUE` + `UNITS` + `SPECIES` 派生 | 建议表示为与源 Result 关联的 derived Result | — |
| `normalized_unit` | source unit 经介质/basis 规则转换 | `UNITS` 经规则转换 | derived Result 关联 canonical Unit | — |
| `normalized_censoring_limit` | Detection Limit + unit | `DATA_VALUE` + `QUALIFIER` + `UNITS` | `DataQuality` limit + `CensorCodeCV` | — |
| `analytical_method` | Method Code → Technique/Instrument | `ANALYTIC_METHOD` → AnalyticMethod lookup | Result → FeatureAction → Action → Method | — |
| `method_family` | Technique + Instrument 归一 | 从 method definition 分类 | `MethodTypeCV` + MethodName 归一 | — |
| `digestion_or_extraction` | 显式 method description/comment | 从方法定义和引用来源分类 | preparation Actions/Methods 关系链 | — |
| `laboratory` | Primary Analytical Metadata.Laboratory | 不把 `LAB_ID` 误当实验室名称 | `Methods.OrganizationID → OrganizationName` | — |
| `reference_material` | Primary Analytical Metadata.Reference Sample | 仅在方法资料明确给出时 | `ReferenceMaterials` + applicable action | — |
| `detection_limit` | Primary Analytical Metadata.Detection Limit | 只有 qualifier/编码规则证明时使用 `DATA_VALUE` | `DataQualityTypeCV` + `DataQualityValue` | — |
| `detection_limit_unit` | Detection Limit unit | 与已证明 limit 同一语义下的 `UNITS` | `DataQualityValueUnitsID → Units` | — |

`normalized_value` 是本工作流的派生结果，导出到 ODM2 时应当建成与源 Result 有关系的 derived Result，
并保留 derivation equation；不能只覆盖源结果。导出到扁平平台时也必须同时提供 original value、unit、
qualifier 与 conversion evidence，避免不可逆的数据“清洗”。

### 4.3 数据来源与权利

| Canonical 字段 | EarthChem ECL | USGS AGDB2 | ODM2 | IGSN/DataCite |
|---|---|---|---|---|
| `source_id` | 数据集 PID 或 namespaced accession | USGS publication/catalog ID | `Datasets.DatasetUUID` 或 namespaced `DatasetCode` | 明确关系的 related dataset identifier |
| `dataset_title` | Data Source.Title | 权威 USGS 数据集标题 | `Datasets.DatasetTitle` | 解引用 related dataset 后取其 title |
| `dataset_doi` | Data Source.DOI | 只有数据集/出版物明确分配 DOI 时 | DatasetCitation → CitationExternalIdentifier DOI | DOI 类型的 relatedIdentifier，不能默认复制样品 IGSN |
| `dataset_version` | 显式 repository release/version | 数据集 edition/version | `RelatedDatasets.VersionCode` | related dataset 的 DataCite version |
| `source_locator` | landing page/DOI + 合法 record fragment | publication URL + table/key | `CitationLink` + namespaced DatasetID/ResultID | 注册 DOI URL 或有关系类型的 relatedIdentifier |
| `license` | 数据集声明 license，不从“可下载”推断 | `Use_Constraints` + `Access_Constraints` | core reviewed surface 无直接字段 | `rightsList` 的 identifier/URI/text |

## 5. 82 个非核心映射字段为什么仍然保留

Crosswalk 不会为了看起来“全覆盖”而制造虚假对应。当前 118 个 canonical 字段中，36 个进入优先互操作
矩阵，另外 82 个被明确分成两类；机器文件中的字段数组是唯一完整清单：

- `local_extension`（34 个）：稳定记录 ID、raw value/qualifier/coordinate、转换因子与公式、源文件/源行/hash、来源层级、QC、置信度，以及 V4 引入的样品类型映射、引用和权利审计字段。这些是证据链与运行安全设计，不冒充平台原生字段。
- `deferred_crosswalk`（48 个）：样品身份/重复/分析批次、`batch_qc_status` 与处置、坐标不确定性、粒级、样品细类、水体/沉积环境、方法 scope、引用关系，以及地质单元匹配与边界距离字段。它们有专业意义，但已审查表面不足以做可靠的一对一映射。后续应引入 GeoSciML/CGI、实验室 QA/QC 与平台 extension 规范后再升级。

`analysis_batch_id`、`batch_qc_status`、`batch_qc_disposition` 因而提升的是**本项目 canonical 数据库内部的批次可审计性和失败关闭能力**，不是对 ODM2/EarthChem 批次模型的认证。未来 exporter 必须把批次、Action/Method、DataQuality 和观测关系显式建模，不能只改列名。

这种显式缺口比强行把 `geologic_unit` 映射成任意 lithology 字符串更规范：前者能触发补充元数据，后者会制造
不可见的语义错误。

## 6. D1、D2、D3 的落地方式

### D1 接入

1. 先阅读数据集自身 metadata/data dictionary，不能只按相似列名匹配。
2. 在 `schema-map` 中写“实际源列 → canonical 字段”；crosswalk 中的 external path 是专业语义参照，
   不保证每个版本的下载文件都使用同名列。
3. 对 `transformed` 和 `composite` 映射，保留参与转换的全部源列、数据字典 URL、版本、许可与文件 SHA-256。
4. `no_direct_equivalent` 字段保持 null，不用语言模型根据上下文补造。

### D2 标准化

1. 原始值、单位、qualifier、坐标和来源定位必须保留；canonical 转换只新增字段。
2. 映射提供的是语义依据，实际单位、删失值、坐标与异常行为仍以 `scientific-rules.md` 为准。
3. Crosswalk 不直接改变置信度。置信度来自来源等级、完整度、方法、空间信息与 QC；专业字段对齐只能通过
   提高这些证据的完整性间接提高可用性评分。
4. 任何新平台映射都要写 conversion rule、controlled vocabulary、information loss 和 evidence ID。

### D3 展示/导出

1. 展示层可以说明“字段参考 EarthChem/AGDB2/ODM2/IGSN 语义”，不能写“已通过平台认证”。
2. 要导出某一平台的原生格式，必须另写该平台 exporter 和 conformance test；本 crosswalk 只是 exporter 的设计输入。
3. 地图与报告继续使用本仓库 canonical Schema，避免平台特有字段泄漏成不稳定公共接口。

## 7. 审查和升级规则

- Canonical Schema 新增、删除或改名字段时，crosswalk 的完整字段分区测试必须同步更新。
- 专业平台版本变化时新增 evidence source，不覆盖旧版本含义；破坏性语义变化升级
  `crosswalk_version`。
- `exact` 需要最强证据；只要存在单位、词表、层级或关系损失，就降为 `renamed`、`transformed` 或
  `composite`。
- 外部平台未在已审查资料中给出字段时使用 `no_direct_equivalent`，不要把“没找到”写成“平台绝对不支持”。
- OneGeochemistry 只有在发布可版本化、可引用的字段/词表规范后，才加入逐字段 platform mapping。

## 8. 官方资料

- [EarthChem Library Templates](https://earthchem.org/ecl/templates)
- [EarthChem Resources for Developers](https://earthchem.org/resources/developers)
- [EarthChem Library Submission Guidelines](https://earthchem.org/ecl/submission-guidelines)
- [USGS AGDB2 metadata](https://pubs.usgs.gov/ds/759/contents/AGDB2_DS759_metadata/AGDB2_MD.faq.html)
- [ODM2 overview](https://www.odm2.org/)
- [ODM2 relational schema source](https://github.com/ODM2/ODM2/blob/master/schemas/ODM2_DBWrench_Schema.xml)
- [IGSN metadata guidance](https://igsn.github.io/metadata/)
- [DataCite IGSN metadata recommendations](https://support.datacite.org/docs/igsn-id-metadata-recommendations)
- [DataCite Metadata Schema 4.6](https://schema.datacite.org/meta/kernel-4.6/)
- [OneGeochemistry initiative](https://onegeochemistry.github.io/)

资料访问日期：2026-08-05。
