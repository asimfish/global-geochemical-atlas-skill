# 请求与输出契约

## 输入

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|---|---|---:|---|---|
| `elements` | string[] | 是 | 无 | 使用元素符号或可无歧义规范化的名称 |
| `region` | object/string | 是 | 无 | `global`、命名区域或 WGS84 bbox |
| `media` | string[] | 是 | 无 | rock/soil/sediment/water/mineral/concentrate |
| `measurement_basis` | string[]/null | 否 | null | total/dissolved/extractable 等 |
| `time_range` | [string,string]/null | 否 | null | 采样时间而非发布日期 |
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

## 稳定产物

| 文件 | 核心用途 |
|---|---|
| `geochemistry.csv` | 一行一个样品 × 分析物测定，保留原值与 canonical 值 |
| `source_manifest.json` | 输入哈希、来源、定位、许可、记录数、覆盖率及置信度报告哈希绑定 |
| `record_evidence.jsonl` | 与 canonical `record_id` 一一对应的来源文件、源行、版本、哈希、引用及来源特有证据 |
| `qc_report.json` | 标准化率、删失、坐标和 flags 汇总 |
| `confidence_report.json` | 运行级置信度公式、分量和 band 分布 |
| `anomalies.geojson` | 候选异常点；允许 null geometry |
| `anomaly_report.json` | 背景组、阈值、排除和失败状态 |
| `samples.geojson` | 可地图化的标准样点，不含无效坐标 |
| `interactive_map.html` | 自包含交互地图，不依赖 CDN |
| `run_summary.json` | 整体状态、请求摘要、产物、coverage 与限制 |

## 证据链

`standardize_geochemistry.py` 可在四个最低分析字段上输出 QC；完整 `run_workflow.py` 为保证任务要求的来源追溯，额外要求非空 `source_id`、`source_locator` 和 `license`。缺失时不得用 `unknown` 冒充已验证来源，应返回 `conflicting_evidence` 并提示补充 sidecar 或来源字段；`source_tier` 缺失可以保留为 `unknown`，但必须降低来源分量。

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

证据等级分三层：只有 CSV 声明时为 `source_declared_in_input`；sidecar 通过字段与 record ID 校验时为 `validated_record_evidence`；`run_manifest.json` 同时绑定 CSV 与 sidecar SHA-256 时才是 `verified_record_evidence`。哈希和定位证明可追溯性，不证明测量真实、方法可比或异常成因。

## 失败状态

失败时仍输出 `run_summary.json`，`status` 使用：`success`、`partial_success`、`invalid_input`、`unsupported_scope`、`network_unavailable`、`source_not_accessible`、`incomplete_retrieval`、`conflicting_evidence`、`insufficient_background` 或 `needs_human_review`。
