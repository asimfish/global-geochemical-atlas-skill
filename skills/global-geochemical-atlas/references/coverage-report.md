# D1 数据源覆盖报告

核对时间：`2026-08-05T00:00:00Z`

整体状态：`partial`

发现轮次：`1`，饱和状态：`false`

## 当前目标

- 地区：`"global"`
- 介质：`rock, soil, sediment, water`
- 分析物：`As, Cu, Ni, Zn`
- 许可策略：`open_only`

## 覆盖矩阵

| 介质 | 状态 | 已批准来源 | 待复核候选 | 来源独立性 | 分析物/方法/密度 |
|---|---|---|---|---|---|
| rock | `partial` | georoc-archaean | earthchem-portal, georoc-database, usgs-ngdb | `single_source_dependency` | `unknown/not_yet_audited/not_yet_audited` |
| soil | `partial` | usgs-conus-soil | gemas-europe, usgs-ngdb, wosis | `single_source_dependency` | `unknown/not_yet_audited/not_yet_audited` |
| sediment | `unknown` | 无 | earthchem-portal, usgs-ngdb | `no_approved_source` | `unknown/not_yet_audited/not_yet_audited` |
| water | `unknown` | 无 | gemstat-open-archive | `no_approved_source` | `unknown/not_yet_audited/not_yet_audited` |

## 当前判断

- 岩石与土壤只有局部批准来源，因此仍是 `partial`，不能写成全球完整覆盖；
- 沉积物与水体虽有候选来源，但尚未通过生产质量门，因此保持 `unknown`；
- 每个介质的分析物、方法、时间和空间密度仍需在 M6–M8 的逐源审计中补齐；
- 聚合平台不计作独立证据，必须追溯并去重其上游数据集。

## 限制

- Catalog routing identifies possible sources; analyte availability and record-level comparability still require source queries and D2 review.
- A partial route must not be presented as complete global coverage.
- Source discovery is still in progress; absence from this route is not proof that no source exists.
- Analyte, method, time and spatial-density coverage remain unknown until source-level inventories are audited.
- Record count alone is not evidence of representative global coverage.

## 结论边界

Coverage states describe the current approved source system and its documented candidates. They do not imply uniform sampling, method comparability, or absence of undiscovered sources.
