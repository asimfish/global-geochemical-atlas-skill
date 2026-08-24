# 请求与输出契约

## 输入

| 字段 | 类型 | 必需 | 默认值 | 说明 |
|---|---|---:|---|---|
| `elements` | string[] | 是 | 无 | 使用元素符号或可无歧义规范化的名称 |
| `region` | object/string | 是 | 无 | `global`、命名区域或 WGS84 bbox |
| `media` | string[] | 是 | 无 | rock/soil/sediment/water/mineral/concentrate |
| `coverage_mode` | string | 否 | fixed | 明确闭集用 fixed；“至少 N/尽量全面/图谱”用 maximize_evidence_breadth |
| `minimum_elements` | integer/null | 否 | null | 用户给出的元素验收下限；候选数组仍保留题面全部元素，不按此数截断采集 |
| `minimum_media` | integer/null | 否 | null | 用户给出的介质验收下限；候选数组仍保留题面全部介质，不按此数截断采集 |
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
| `max_records` | integer | 否 | fixed=50000；maximize=200000 | 1–200000；开放式广度任务默认使用较高上限，防止来源增多后被固定任务配额静默截断；超出需分批 |
| `offline` | boolean | 否 | false | 只使用哈希验证缓存或 demo |

`minimum_elements` 与 `minimum_media` 只记录题面最低验收线，不是停止条件。若题面写“至少覆盖
As、Cu、Pb、Zn 中 3 个”和“岩石、土壤、沉积物、水体中的 2 类”，应冻结全部四个元素、全部四类
介质并设置 `coverage_mode=maximize_evidence_breadth`、`minimum_elements=3`、`minimum_media=2`。
在线路由和充分性循环逐项审计完整候选矩阵；缺失候选必须留下来源发现/排除证据，不能悄悄从请求中删除。

## bbox 约定

顺序固定为 `[west, south, east, north]`。经度为 -180–180，纬度为 -90–90；`west > east` 表示跨越日期变更线。不要猜测经纬顺序。

## 可选实验室批次门禁

若输入记录带 `analysis_batch_id`，可同时向执行器提供 `--batch-qc-input` 和 `--batch-qc-policy`。前者是一行一个 CRM、空白或重复样测定的 UTF-8 CSV；后者必须符合
[batch-qc-policy.schema.json](batch-qc-policy.schema.json)，显式冻结 CRM 回收率、空白上限、重复样 RPD 与单位。两者必须成对出现。D2 重新计算而不信任来源给出的 pass/fail；任一必需控制缺失或失败，整个批次保留在数据库但从异常背景排除。

## 稳定产物

| 文件 | 核心用途 |
|---|---|
| `geochemistry.csv` | 一行一个样品 × 分析物测定，保留原值、canonical 值、精确记录定位和官方来源 URL |
| `source_manifest.json` | 输入哈希、来源、定位、许可、记录数、覆盖率及置信度报告哈希绑定 |
| `record_evidence.jsonl` | 与 canonical `record_id` 一一对应的来源文件、源行、版本、哈希、引用及来源特有证据 |
| `qc_report.json` | 标准化率、删失、坐标和 flags 汇总 |
| `confidence_report.json` | 来源证据、分析就绪度、空间可用性、工作流可用性的公式与 band 分布 |
| `sources_and_confidence.json` | 按来源汇总 URL/DOI、许可、获取时间、文件 hash、测定行/独立样品数、方法/坐标/定位完整率、缺失责任原因及四维 band；发布方未报告、关联未解析与管线未记账必须分开，禁止单一“低质量”标签 |
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

以上是固定十六项核心产物；未提供批次 QC 时仍生成带 `not_supplied` 状态的空批次契约。`anomaly_regions.geojson` 是统计筛查产物；D3 的缩放圆环仍是 `visual_aggregation_only`，二者不得混称。

使用 `run_atlas_request.py` 时还生成 `request_evidence/`，保存冻结的 `request.json`、请求特定 `source_route.json`、`coverage.json/.md` 和符合 `request-execution.schema.json` 的 `execution.json`；该 schema 由 Skill 直接路由。`geochemical-request-execution-v6.skill_snapshot` 绑定整棵 Skill 树的开始/结束 SHA-256，运行中修改会失败关闭。实际用于验证的请求过滤 manifest、父 manifest 与在线逐源 manifest 原字节保存在 `request_evidence/acquisition/`，并由 `execution.json.acquisition_manifests` 的相对路径和 SHA-256 绑定，避免临时目录退出后只剩不可复核的孤立哈希。这些是十六项核心产物之外的请求执行证据；其中实时路由状态与本地 fixture/hash 解析状态分开记录，不能互相覆盖。若下游 D2/D3 失败，控制器仍先写 `execution_progress.json` 和 `execution_failure.json`，保留逐源结果、过滤记录数与 manifest。`--online-source auto` 先根据版本化来源库和完整来源 profile 审计元素、介质、区域、measurement basis、许可、已知数据内容与可执行接口，再按空间区 × 介质边际增益和独立血缘确定首轮尝试顺序，验证各自 manifest，然后合并长表和逐记录证据。后续控制器轮次先把上一轮自主修复计划中的失败/空间重查来源置于队首，再轮换其余完整队列；`execution_progress.json` 与 `execution.json.acquisition_scheduler` 保存 gap-priority、实际顺序、offset 和 `gap-priority-then-coverage-balanced-round-robin-v2` 策略。题面中点名的平台必须进入适用性审计；不包含请求维度、不可访问或不允许当前用途时记录排除理由，不盲目下载。`execution.json.source_outcomes` 保留每源记录数、manifest hash 与失败。默认允许已验证子集以 `partial_success` 继续；`--require-all-sources` 改为任一来源失败即关闭。

完整在线研究由 loop 额外生成 `loop_report.json`、`d1_repair_queue.json` 与 `research_delivery_receipt.json`。后者逐文件绑定根目录十六项核心产物与一个不可变轮次的 SHA-256，并且只有在线 loop 收敛、核心 validator、`atlas-data-sufficiency-v9`、清空的 D1 队列和当前 Skill 快照与执行快照一致时才写 `delivery_ready=true`。正式交付 MUST 通过 `python scripts/validate_research_delivery.py --output-dir OUTPUT_DIR`；直接单轮、fixture、数据不足检查点、待修队列、执行后改过的 Skill、显式 `--checkpoint-only` 或手工覆盖 staging 都不能通过。

## 证据链

`standardize_geochemistry.py` 可在四个最低分析字段上输出 QC；完整 `run_workflow.py` 为保证任务要求的来源追溯，额外要求非空 `source_id`、`source_locator` 和 `license`。缺失时不得用 `unknown` 冒充已验证来源，应返回 `conflicting_evidence` 并提示补充 sidecar 或来源字段；`source_tier` 缺失可以保留为 `unknown`，但必须降低来源分量。`source_locator` 保存本地文件/表/行等精确定位；`official_source_url` 保存由 acquisition manifest、官方数据页或 DOI 绑定的可点击入口。除明确 synthetic fixture 外，每条记录必须同时有两者，D3 分栏显示，禁止互相冒充。

完整请求共享一个只减不增的 monotonic 总 deadline。任务合同未声明时限时按官方 900 秒外部上限规划，并预留 180 秒给 Agent 启动、验证与结果交接，因此内部在线预算为 720 秒且自动标记 `--checkpoint-only`。只有操作者明确授权扩展研究时，才能把合同显式设为最多 43,200 秒；控制器再按 1,800 秒轮次运行，每轮给内部工作流 1,740 秒，并在轮末根据充分性门禁决定是否继续。短于一个完整轮次必须加 `--checkpoint-only` 且不能正式交付。`request_evidence/execution.json.timing` 记录外部任务上限、内部预算、当前轮预算、工作流预留、耗时与 deadline 策略；逐源和工作流 timeout 只能缩短剩余预算，不能叠加突破所声明总预算。

独立 D3 产物在核心十六文件之外按 profile 条件生成：元素组合任务生成 `element_comparison.json`，单元素任务生成 `concentration_grid.geojson`。二者均由 `visualization_report.json` 路径和 SHA-256 绑定，分别遵循 [element-comparison.schema.json](element-comparison.schema.json) 与 [concentration-grid.schema.json](concentration-grid.schema.json)。

每条关键记录至少保留：

```json
{
  "source_id": "dataset-or-publication-id",
  "source_locator": "stable URL/DOI plus table, page, or record locator",
  "official_source_url": "https://official.example/data-or-doi",
  "license": "source license or unresolved",
  "source_tier": "official_curated|government|peer_reviewed|institutional_repository|author_supplement|aggregator|unknown",
  "original_value_raw": "<0.1",
  "source_qualifier_raw": "<",
  "original_unit": "mg/kg",
  "analytical_method": "ICP-MS",
  "method_missing_reason": null,
  "coordinate_accuracy_evidence_status": "source_reported_uncertainty|not_reported|not_applicable_no_canonical_coordinate",
  "coordinate_representation_resolution_m": "numeric text resolution; not positional accuracy",
  "qc_flags": ["CENSORED_VALUE"]
}
```

`operational_confidence` 是兼容字段，只表示 `workflow_usability`，不是测量准确度、统计置信水平或事实为真的概率。必须同时报告 `source_evidence`、`analytical_readiness`、`spatial_usability` 和 `workflow_usability`；不得把因坐标缺失造成的 low workflow band 简化为“来源低质量”。

地图的默认全元素视图按有证据的样品标识折叠符号，KPI 仍统计测定记录；这只是显示层去叠加，
不删除或合并 `geochemistry.csv`/`samples.geojson` 记录。`samples.geojson` 使用 `d3-map-sample-properties-v3` 最小 GIS 字段保留每条可绘测定，并以 `record_id` 连接完整标准库，防止来源定位、完整置信度和方法长文本令十万级空间交换文件越过 100 MB。浓度色阶的启用条件固定为单一元素、
介质、measurement basis、已知方法组和标准单位，否则使用介质分类色。

证据等级分三层：只有 CSV 声明时为 `source_declared_in_input`；sidecar 通过字段与 record ID 校验时为 `validated_record_evidence`；`run_manifest.json` 同时绑定 CSV 与 sidecar SHA-256 时才是 `verified_record_evidence`。哈希和定位证明可追溯性，不证明测量真实、方法可比或异常成因。

## 失败状态

失败时仍输出 `run_summary.json`，`status` 使用：`success`、`partial_success`、`invalid_input`、`unsupported_scope`、`network_unavailable`、`source_not_accessible`、`incomplete_retrieval`、`conflicting_evidence`、`insufficient_background` 或 `needs_human_review`。
