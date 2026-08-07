# D1 数据源覆盖报告

核对时间：`2026-08-06T10:35:00Z`

整体状态：`partial`

发现轮次：`6`，饱和状态：`false`

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
| rock | `partial` | georoc-archaean | alaska-dggs-webgeochem, australia-ozchem, brazil-sgb-geochemistry, earthchem-library, earthchem-portal, finland-gtk-geochemistry, georoc-database, iodp-data-systems, jamstec-darwin, noaa-ncei-marine-geology, norway-ngu-lito, nz-petlab, pangaea-repository, petdb, usgs-ngdb | `single_source_dependency` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| soil | `partial` | afsis-phase-i-wet-chemistry, foregs-humus, foregs-subsoil, foregs-topsoil, pangaea-north-africa-soil, usgs-conus-soil | alaska-dggs-webgeochem, bgs-gbase, brazil-sgb-geochemistry, earthchem-library, foregs-europe, gemas-europe, ireland-tellus, pangaea-repository, soils4africa, south-africa-cgs-geochemistry, tpdc-china-mountain-soil, usgs-ngdb, wosis | `multiple_sources_lineage_not_yet_deduplicated` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| sediment | `partial` | australia-ngsa-mercury, foregs-floodplain-sediment, foregs-stream-sediment, japan-gsj-geochemical-map, japan-gsj-marine-sediment, norway-marchem, pangaea-arabian-sea-sediment | alaska-dggs-webgeochem, argentina-segemar-geochemistry, australia-ngsa, australia-ozchem, bgs-gbase, brazil-sgb-geochemistry, canada-bc-rgs, canada-cdogs, chile-sernageomin-geochemistry, earthchem-library, earthchem-portal, eea-waterbase, emodnet-chemistry, finland-gtk-geochemistry, foregs-europe, india-gsi-ngcm, iodp-data-systems, ireland-tellus, jamstec-darwin, mexico-sgm-geochemical-cartography, noaa-ncei-marine-geology, nz-petlab, pangaea-repository, south-africa-cgs-geochemistry, sweden-sgu-geochemical-atlas, us-water-quality-portal, usgs-ngdb | `multiple_sources_lineage_not_yet_deduplicated` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| water | `partial` | foregs-stream-water, gemstat-open-archive, geotraces-idp2025, us-wqp-sacramento-river-arsenic | bgs-gbase, brazil-sgb-geochemistry, canada-bc-rgs, canada-cdogs, earthchem-library, eea-waterbase, emodnet-chemistry, foregs-europe, glorich, iodp-data-systems, ireland-tellus, pangaea-repository, us-water-quality-portal | `multiple_sources_lineage_not_yet_deduplicated` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |

## 当前判断

- 岩石只有 GEOROC 太古宙专题来源，因此仍是 `partial`；
- 土壤已有 USGS、PANGAEA、AfSIS 与 FOREGS topsoil/subsoil/humus；AfSIS 补充非洲 18 个国家标签和 51 个 LDSF 站点，但不是均匀大陆网格；温和硝酸浸出、王水准全量和总量不可混用，整体仍为 `partial`；
- 沉积物已有 MarChem、GSJ 与 FOREGS stream/floodplain sediment；海洋/河流/泛滥平原、粒级和消解基础不同，仍为 `partial`；
- 水体已有 GEOTRACES 海水、GEMStat 淡水和 FOREGS 欧洲溪流水；目标分析物有多个来源，但海水/淡水、单位和时间尺度不可直接混为同一背景；
- FOREGS 六类来源已经分别实现适配器并固定文件 hash；这增加了欧洲低密度基线覆盖，不代表欧洲每个位置有实测值；
- AfSIS V2.0 已固定三个 original 文件并全量对账 2,002 个样品；126 个缺坐标样品和逐元素低于 DL/QL 的数值保持显式，不能用 48 条完整坐标 demo 代替全量质量结论；
- 岩石、土壤和沉积物样板的 As、Cu、Ni、Zn 目标字段已登记；来源数增加不代表方法一致或空间充分，方法、时间和密度仍需逐源审计；
- 聚合平台不计作独立证据，必须追溯并去重其上游数据集。

## 限制

- Catalog routing identifies possible sources; evidence tier is not a truth probability, and analyte availability plus record-level comparability still require source queries and D2 review.
- A partial route must not be presented as complete global coverage.
- Source discovery is still in progress; absence from this route is not proof that no source exists.
- Analyte coverage is credited only for explicit target mappings in the production registry; method, time and spatial-density coverage still require separate audits.
- Record count alone is not evidence of representative global coverage.

## 结论边界

Coverage states describe sources that meet the requested evidence/use mode and documented lower-use candidates. They do not imply uniform sampling, method comparability, or absence of undiscovered sources.