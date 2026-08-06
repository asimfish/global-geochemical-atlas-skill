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
| sediment | `partial` | foregs-floodplain-sediment, foregs-stream-sediment, japan-gsj-geochemical-map, norway-marchem | alaska-dggs-webgeochem, argentina-segemar-geochemistry, australia-ngsa, australia-ozchem, bgs-gbase, brazil-sgb-geochemistry, canada-bc-rgs, canada-cdogs, chile-sernageomin-geochemistry, earthchem-library, earthchem-portal, eea-waterbase, emodnet-chemistry, finland-gtk-geochemistry, foregs-europe, india-gsi-ngcm, iodp-data-systems, ireland-tellus, jamstec-darwin, mexico-sgm-geochemical-cartography, noaa-ncei-marine-geology, nz-petlab, pangaea-repository, south-africa-cgs-geochemistry, sweden-sgu-geochemical-atlas, us-water-quality-portal, usgs-ngdb | `multiple_sources_lineage_not_yet_deduplicated` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |
| water | `partial` | foregs-stream-water, gemstat-open-archive, geotraces-idp2025 | bgs-gbase, brazil-sgb-geochemistry, canada-bc-rgs, canada-cdogs, earthchem-library, eea-waterbase, emodnet-chemistry, foregs-europe, glorich, iodp-data-systems, ireland-tellus, pangaea-repository, us-water-quality-portal | `multiple_sources_lineage_not_yet_deduplicated` | `complete_for_registered_targets/not_yet_audited/not_yet_audited` |

## 当前判断

- `rock`：状态 `partial`；来源 georoc-archaean；注册目标覆盖本次元素；仍需记录级核验；来源独立性 `single_source_dependency`。
- `soil`：状态 `partial`；来源 afsis-phase-i-wet-chemistry、foregs-humus、foregs-subsoil、foregs-topsoil、pangaea-north-africa-soil、usgs-conus-soil；注册目标覆盖本次元素；仍需记录级核验；来源独立性 `multiple_sources_lineage_not_yet_deduplicated`。
- `sediment`：状态 `partial`；来源 foregs-floodplain-sediment、foregs-stream-sediment、japan-gsj-geochemical-map、norway-marchem；注册目标覆盖本次元素；仍需记录级核验；来源独立性 `multiple_sources_lineage_not_yet_deduplicated`。
- `water`：状态 `partial`；来源 foregs-stream-water、gemstat-open-archive、geotraces-idp2025；注册目标覆盖本次元素；仍需记录级核验；来源独立性 `multiple_sources_lineage_not_yet_deduplicated`。
- 方法、时间与空间密度没有完成记录级审计时保持 `not_yet_audited`；不得用来源数量替代覆盖结论。
- 聚合平台不计作独立证据，必须追溯并去重其上游数据集。

## 限制

- Catalog routing applies frozen analyte, region, measurement-basis and temporal evidence; record-level availability and comparability still require acquisition plus D2 review.
- A partial route must not be presented as complete global coverage.
- max_records is an acquisition/output ceiling enforced by the downstream runner, not evidence that the selected records are representative.
- Source discovery is still in progress; absence from this route is not proof that no source exists.
- Analyte coverage is credited only for explicit target mappings in the production registry; method, time and spatial-density coverage still require separate audits.
- Record count alone is not evidence of representative global coverage.

## 结论边界

Coverage states describe sources that meet the requested evidence/use mode and documented lower-use candidates. They do not imply uniform sampling, method comparability, or absence of undiscovered sources.