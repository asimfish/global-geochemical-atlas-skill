# D1 规范化归档数据模型

版本：`d1-archive-model-v1`

## 核心结构

```text
dataset_source ── publication
      │
      └── sampling_event ── sample ── parent/child sample
                                  │
                                  └── observation ── analytical_method
                                            │
                                            └── provenance ── acquisition_run
```

归档层按实体拆分，避免在每个元素测定行重复并冲突地保存样品、地点、方法和来源信息。D1 交给 D2 时生成一行一个 `observation` 的长表；SQLite 查询索引从归档层派生，可以重建，不是唯一事实来源。

## 实体与稳定 ID

| 实体 | 主键 | 主要外键 | 含义 |
|---|---|---|---|
| `dataset_source` | `dataset_id` | 无 | 数据集版本、发布者、许可、文件和获取入口 |
| `publication` | `publication_id` | `dataset_ids` | 与数据集、样品或方法相关的论文/报告 |
| `sampling_event` | `sampling_event_id` | `dataset_id` | 采样地点、时间、深度和采集方法 |
| `sample` | `sample_id` | `sampling_event_id`, `parent_sample_id` | 物理样品、介质、材料和父子样关系 |
| `analytical_method` | `method_id` | `publication_ids` | 前处理、消解、技术、仪器、实验室和校准 |
| `provenance` | `provenance_id` | `dataset_id`, `acquisition_run_id` | 原文件/API、行列、hash、适配器和处理步骤 |
| `observation` | `observation_id` | `sample_id`, `method_id`, `provenance_id` | 一个样品的一个分析物测定 |
| `acquisition_run` | `acquisition_run_id` | `dataset_ids` | 一次 D1 请求、版本、数量、缓存和输出 hash |

来源提供永久标识时优先使用；样品支持 IGSN。缺少永久标识时，使用已文档化的 canonical 字段生成稳定 SHA-256 ID。ID 不能包含本地路径、机器名或本次下载时间。

## 字段优先级

### P0：必须有，或必须阻止生产

- 数据集：`source_id`、`dataset_id`、版本、发布者、许可、落地页、文件/响应 hash；
- 样品与采样：稳定样品 ID、介质原词、位置原值与 CRS；实验样品位置可不适用但必须说明；
- 测定：分析物原词、原始值、原始单位、限定符、样品外键；
- 证据：来源记录 ID、原文件/API 定位、适配器版本和输入 hash。

### P1：强烈建议并进入完整性统计

- 采样时间、深度、坐标不确定度、IGSN；
- 测量基准、检出限、方法、消解/提取、仪器和实验室；
- 原始论文 DOI/引用和数据提供者。

### P2：按介质和专业场景扩展

- 岩性、地质单元和地质年代；
- 土层、粒级、筛分尺寸；
- 水样过滤状态、现场/实验室测定条件；
- 分析批次 ID、标准物质、空白、校准、精密度、准确度和重复测定关系。

## 原始值与可逆解析

任何解析或标准化字段都不能覆盖 `*_raw`：

```text
value_raw="<5" → parsed_value=5, value_qualifier="lt"
unit_raw="ppm" → D1 保留原词；D2 决定是否以及如何换算
latitude_raw="39 30 N" → D1 可产生 WGS84 查询坐标，但保留原值、CRS 和转换记录
```

无法确定时使用 `null`，并在 `missing_reasons` 中记录：

```text
not_reported | not_applicable | not_available | redacted | parse_failed
```

空字符串不表示一个确定的缺失原因。

## D1 与 D2 边界

| 内容 | D1 | D2 |
|---|---|---|
| 分析物 | 保存 `analyte_reported` 和来源代码 | 统一元素、氧化物、同位素及语义 |
| 数值 | 保留 `value_raw`，做可逆数值/限定符解析 | 删失策略、单位换算、可比性和 QC |
| 介质/岩性 | 保存来源原词和词汇映射候选 | 决定最终科学分类和合并规则 |
| 坐标 | 原值、CRS、可复现转换和不确定度 | 空间 QC、异常和适用性判断 |
| 方法 | 原文、代码、方法引用和实验室 | 方法可比性、质量门和置信度分量 |
| 分析批次 | 保留来源批次 ID、CRM/空白/重复样原始测定与 policy 证据 | 重算批次通过状态；失败记录保留但排除出异常背景 |
| 来源质量 | 发布者、版本、许可、完整性和证据链 | 记录级 QC 与 operational confidence |

现有 `geochemistry-record.schema.json` 继续作为 D2 标准化测定结果。D1 的 `observation_id` 在交换长表中映射到 D2 `record_id`，不另造一个含义不同的随机 ID。

## 时间、空间和词汇规则

- 系统运行时间使用 ISO 8601 UTC；采样时间保留来源时区和原文；
- WGS84 查询坐标与来源坐标、来源 CRS、坐标不确定度同时保存；
- 经纬度小数位数不能自动解释为真实位置精度；
- DOI、IGSN、URL 和本地 ID 分字段保存；
- 受控术语保存 `code + label + vocabulary_uri + vocabulary_version`；
- 未映射术语保留原文和 `unmapped` 状态，不压成通用 `other`。

## 关系完整性

正式归档必须满足：

1. 每个 observation 引用存在的 sample、method 和 provenance；
2. 每个 sample 引用存在的 sampling event；父样引用不能形成循环；
3. 每个 provenance 引用存在的数据集和 acquisition run；
4. 同一实体类型的主键唯一；
5. observation 的 `value_raw`、`unit_raw`、`analyte_reported` 和限定符不在映射中丢失；
6. 所有 schema 和词汇版本进入 acquisition run。

本模型借鉴 EarthChem 的样品/数据/方法拆分、DataCite IGSN 的样品关系和 OGC OMS 的样品—观测概念边界，但只实现本项目需要的可审计子集。
