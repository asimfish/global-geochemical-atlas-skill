# 请求与输出契约

## 输入

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|---|---|---:|---|---|
| `elements` | string[] | 是 | 无 | 使用元素符号或可无歧义规范化的名称 |
| `region` | object/string | 是 | 无 | `global`、命名区域或 WGS84 bbox |
| `media` | string[] | 是 | 无 | rock/soil/sediment/water/mineral/concentrate |
| `measurement_basis` | string[]/null | 否 | null | 非空数组；total/dissolved/extractable 等 |
| `geology_units` | string[]/null | 否 | null | 只保留 exact normalized 地质单元标签 |
| `geology_match` | string | 否 | reported_or_matched | reported_or_matched/reported/matched；matched 缺地质匹配数据时失败关闭 |
| `time_range` | [string,string]/null | 否 | null | 采样时间而非发布日期；两项以四位年份开头且 start ≤ end |
| `sources` | `auto`/string[] | 否 | auto | 只选择公开科学来源 |
| `output_formats` | string[] | 否 | csv,json,geojson,html_map | 结构化产物 |
| `target_crs` | string | 否 | EPSG:4326 | v1 只输出 WGS84 canonical 坐标 |
| `license_policy` | string | 否 | open_only | V1 兼容字段；V3 使用 `research_use_policy` |
| `research_use_policy` | string | 否 | permitted_research | 按本次科研使用条件筛选，不把科研使用与再分发混为一谈 |
| `minimum_evidence_tier` | string | 否 | D | A/B/C/D/U，控制最低来源证据完整度 |
| `minimum_use_mode` | string | 否 | normalized_analysis | discovery/raw_observation/normalized_analysis/benchmark_ready |
| `max_records` | integer | 否 | 50000 | 1–200000；超出需分批 |
| `offline` | boolean | 否 | false | 只使用哈希验证缓存或 demo |

## bbox 约定

顺序固定为 `[west, south, east, north]`。经度为 -180–180，纬度为 -90–90；`west > east` 表示跨越日期变更线。不要猜测经纬顺序。

## 可选实验室批次门禁

若输入记录带 `analysis_batch_id`，可同时向执行器提供 `--batch-qc-input` 和 `--batch-qc-policy`。前者是一行一个 CRM、空白或重复样测定的 UTF-8 CSV；后者必须符合
[batch-qc-policy.schema.json](batch-qc-policy.schema.json)，显式冻结 CRM 回收率、空白上限、重复样 RPD 与单位。两者必须成对出现。D2 重新计算而不信任来源给出的 pass/fail；任一必需控制缺失或失败，整个批次保留在数据库但从异常背景排除。

## 稳定产物

| 文件 | 核心用途 |
|---|---|
| `geochemistry.csv` | 一行一个样品 × 分析物测定，保留原值与 canonical 值 |
| `source_manifest.json` | 输入哈希、来源、定位、许可、记录数、覆盖率及置信度报告哈希绑定 |
| `record_evidence.jsonl` | 与 canonical `record_id` 一一对应的来源文件、源行、版本、哈希、引用及来源特有证据 |
| `qc_report.json` | 标准化率、删失、坐标和 flags 汇总 |
| `confidence_report.json` | 运行级置信度公式、分量和 band 分布 |
| `batch_acceptance.csv` | 逐分析批次的 CRM 回收率、空白、重复样 RPD、通过状态与处置 |
| `batch_qc_report.json` | 批次规则、输入/policy hash、失败或不完整批次数及科学边界 |
| `anomalies.geojson` | 候选异常点；允许 null geometry |
| `anomaly_report.json` | 背景组、阈值、排除和失败状态 |
| `anomaly_regions.geojson` | 通过精确超几何富集与 BH-FDR 门禁的固定网格候选区域 |
| `spatial_anomaly_report.json` | 空间零假设、样本门槛、全部检验数、FDR 与未通过原因 |
| `samples.geojson` | 可地图化的标准样点，不含无效坐标 |
| `interactive_map.html` | 自包含交互地图；内嵌固定底图与 D1/D2 报告，不依赖 CDN，不在 D3 重算科学结果 |
| `iteration_backlog.csv` | D1/D2 证据缺口、处理失败、复核项与删失科学限制的机器可读迭代清单 |
| `run_summary.json` | 整体状态、请求摘要、产物、coverage 与限制 |

以上是固定十五项核心产物；未提供批次 QC 时仍生成带 `not_supplied` 状态的空批次契约。`anomaly_regions.geojson` 是统计筛查产物；D3 的缩放圆环仍是 `visual_aggregation_only`，二者不得混称。

使用 `run_atlas_request.py` 时还生成 `request_evidence/`，保存冻结的 `request.json`、请求特定 `source_route.json`、`coverage.json/.md` 和符合 [request-execution.schema.json](request-execution.schema.json) 的 `execution.json`。实际用于验证的请求过滤 manifest、父 manifest 与在线逐源 manifest 原字节保存在 `request_evidence/acquisition/`，并由 `execution.json.acquisition_manifests` 的相对路径和 SHA-256 绑定，避免临时目录退出后只剩不可复核的孤立哈希。这些是十五项核心产物之外的请求执行证据；其中实时路由状态与本地 fixture/hash 解析状态分开记录，不能互相覆盖。`--online-source auto` 会按确定性预算逐个获取全部兼容来源、验证各自 manifest，再合并长表和逐记录证据；`execution.json.source_outcomes` 保留每源记录数、manifest hash 与失败。默认允许已验证子集以 `partial_success` 继续；`--require-all-sources` 改为任一来源失败即关闭。

## 证据链

`standardize_geochemistry.py` 可在四个最低分析字段上输出 QC；完整 `run_workflow.py` 为保证任务要求的来源追溯，额外要求非空 `source_id`、`source_locator` 和 `license`。缺失时不得用 `unknown` 冒充已验证来源，应返回 `conflicting_evidence` 并提示补充 sidecar 或来源字段；`source_tier` 缺失可以保留为 `unknown`，但必须降低来源分量。

完整请求执行共享单一 monotonic deadline：官方上限 900 秒，默认内部预算 840 秒。`request_evidence/execution.json.timing` 记录官方上限、内部预算、工作流预留、实际耗时与 deadline 策略；逐源 timeout 和工作流 timeout 都只能缩短剩余预算，不能叠加突破总时限。

独立 D3 产物在核心十五文件之外按 profile 条件生成：元素组合任务生成 `element_comparison.json`，单元素任务生成 `concentration_grid.geojson`。二者均由 `visualization_report.json` 路径和 SHA-256 绑定，分别遵循 [element-comparison.schema.json](element-comparison.schema.json) 与 [concentration-grid.schema.json](concentration-grid.schema.json)。

每条关键记录至少保留：

```json
{
  "source_id": "dataset-or-publication-id",
  "source_locator": "stable URL/DOI plus table, page, or record locator",
  "license": "source license or unresolved",
  "source_tier": "official_curated|government|peer_reviewed|institutional_repository|author_supplement|aggregator|unknown",
  "original_value_raw": "<0.1",
  "source_qualifier_raw": "<",
  "original_unit": "mg/kg",
  "analytical_method": "ICP-MS",
  "qc_flags": ["CENSORED_VALUE"]
}
```

`operational_confidence` 只表示记录对当前流程的可用性，不是测量准确度、统计置信水平或事实为真的概率。

地图的默认全元素视图按有证据的样品标识折叠符号，KPI 仍统计测定记录；这只是显示层去叠加，
不删除或合并 `geochemistry.csv`/`samples.geojson` 记录。浓度色阶的启用条件固定为单一元素、
介质、measurement basis、已知方法组和标准单位，否则使用介质分类色。

证据等级分三层：只有 CSV 声明时为 `source_declared_in_input`；sidecar 通过字段与 record ID 校验时为 `validated_record_evidence`；`run_manifest.json` 同时绑定 CSV 与 sidecar SHA-256 时才是 `verified_record_evidence`。哈希和定位证明可追溯性，不证明测量真实、方法可比或异常成因。

## 失败状态

失败时仍输出 `run_summary.json`，`status` 使用：`success`、`partial_success`、`invalid_input`、`unsupported_scope`、`network_unavailable`、`source_not_accessible`、`incomplete_retrieval`、`conflicting_evidence`、`insufficient_background` 或 `needs_human_review`。
