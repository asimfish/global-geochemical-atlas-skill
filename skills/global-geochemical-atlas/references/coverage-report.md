# D1 数据源覆盖报告

核对时间：`2026-08-05T14:41:20Z`

整体状态：`partial`

发现轮次：`3`，饱和状态：`false`

## 当前目标

- 地区：`"global"`
- 介质：`rock, soil, sediment, water`
- 分析物：`As, Cu, Ni, Zn`
- 科研使用策略：`permitted_research`
- 最低证据等级：`D`
- 最低使用级别：`normalized_analysis`

## 覆盖矩阵

| 介质 | 状态 | 当前分析来源 | 其他候选 | 来源独立性 | 分析物/方法/密度 |
|---|---|---|---|---|---|
| rock | `partial` | georoc-archaean | australia-ozchem, brazil-sgb-geochemistry, earthchem-library, earthchem-portal, finland-gtk-geochemistry, georoc-database, iodp-data-systems, jamstec-darwin, noaa-ncei-marine-geology, norway-ngu-lito, nz-petlab, pangaea-repository, petdb, usgs-ngdb | `single_source_dependency` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| soil | `partial` | usgs-conus-soil | bgs-gbase, brazil-sgb-geochemistry, earthchem-library, foregs-europe, gemas-europe, ireland-tellus, pangaea-repository, soils4africa, usgs-ngdb, wosis | `single_source_dependency` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| sediment | `partial` | norway-marchem | australia-ngsa, australia-ozchem, bgs-gbase, brazil-sgb-geochemistry, canada-cdogs, earthchem-library, earthchem-portal, eea-waterbase, emodnet-chemistry, finland-gtk-geochemistry, foregs-europe, iodp-data-systems, ireland-tellus, jamstec-darwin, noaa-ncei-marine-geology, nz-petlab, pangaea-repository, sweden-sgu-geochemical-atlas, us-water-quality-portal, usgs-ngdb | `single_source_dependency` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| water | `partial` | gemstat-open-archive, geotraces-idp2025 | bgs-gbase, brazil-sgb-geochemistry, canada-cdogs, earthchem-library, eea-waterbase, emodnet-chemistry, foregs-europe, glorich, iodp-data-systems, ireland-tellus, pangaea-repository, us-water-quality-portal | `multiple_sources_but_single_source_per_analyte` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |

## 当前判断

- 岩石与土壤各有一个满足当前 `normalized_analysis` 条件的局部来源，因此仍是 `partial`；
- 沉积物已有一个满足 `normalized_analysis` 的 MarChem 挪威海域样板，但仍是单一国家来源，因此为 `partial`；
- 水体已由 GEOTRACES IDP2025 补 Cu、Ni、Zn，GEMStat v3 补 As；目标分析物在登记范围内齐全，但每个分析物仍只有一个来源，且海水与淡水不可直接混为同一背景；
- 岩石、土壤和沉积物样板的 As、Cu、Ni、Zn 目标字段已登记；方法、时间和空间密度仍需逐源审计；
- 聚合平台不计作独立证据，必须追溯并去重其上游数据集。

## 限制

- Catalog routing identifies possible sources; evidence tier is not a truth probability, and analyte availability plus record-level comparability still require source queries and D2 review.
- A partial route must not be presented as complete global coverage.
- Source discovery is still in progress; absence from this route is not proof that no source exists.
- Analyte coverage is credited only for explicit target mappings in the production registry; method, time and spatial-density coverage still require separate audits.
- Record count alone is not evidence of representative global coverage.

## 结论边界

Coverage states describe sources that meet the requested evidence/use mode and documented lower-use candidates. They do not imply uniform sampling, method comparability, or absence of undiscovered sources.