# D1 候选来源接入顺序

核对日期：2026-08-06。排序只安排接入和复核先后，不删减全介质、全信源普查范围。

| 顺序 | 来源 | 主要覆盖收益 | 接入成本 | 当前主要风险 | 下一道动作 |
|---:|---|---|---|---|---|
| 已接入 | `geotraces-idp2025` | 已补全球海洋航次 Cu/Ni/Zn normalized-analysis 样板；固定版本、DOI、QC、动态快照和全量关系已核实 | 已完成工程接入 | 航次覆盖不连续；无 As；30 条人工复核和贡献者/方法完整率尚未签署 | 与 GEMStat 淡水 As 保持背景隔离；继续补独立海水来源和人工签署 |
| 已接入 | `gemstat-open-archive` | 已补淡水 As normalized-analysis 路由；v3 DOI、CC BY 4.0、五个精确 ZIP range、492,999 条观测和站点/方法连接已核实 | 已完成工程接入 | 33 国不均匀覆盖；大量方法代码 0；删失、重复和 Pending review 值需分层处理；人工复核未签署 | 扩大方法明确的可比子集，补独立淡水来源并完成具名复核 |
| 已接入 | `norway-marchem` | 已补海洋沉积物 normalized-analysis 样板；公开 API、许可、目标元素、方法、动态快照和全量关系均已核实 | 已完成工程接入 | 只覆盖挪威海域；30 条人工复核尚未签署 | 完成 30 条逐条复核后升为 `benchmark_ready`；另补独立沉积物来源 |
| 已接入 | `pangaea-north-africa-soil` | 具体 DOI 的北非可风蚀细粒土壤，补非洲区域和完整行级方法/引用血缘 | 已完成工程接入 | 只有 43 个离散样点；与 bulk-soil 调查不可直接混用；人工复核未签署 | 完成具名复核；继续用逐 DOI 方式补论文长尾而不把 PANGAEA 仓库当独立来源 |
| 已接入 | `japan-gsj-geochemical-map` | 3,024 行全国河流沉积物，补亚洲和独立沉积物区域 | 已完成工程接入 | CSV 缺逐行方法、检出限和 QC；海洋/土壤产品尚未接入；人工复核未签署 | 完成具名复核；固定详细方法资料，再把海洋沉积物和表层土壤作为独立产品接入 |
| 已接入 | FOREGS 六个介质来源 | 16,364 个 CSV 行、48,504 条七目标元素映射，补欧洲 topsoil/subsoil/humus/stream water/stream sediment/floodplain sediment | 已完成工程接入 | 低密度；父项目共享血缘；行级 `<DL` 限定符不可恢复；官方旧站为 hash 固定 HTTP | 完成六份具名复核；继续补与 FOREGS 独立的国家/区域来源 |
| 已接入 | `afsis-phase-i-wet-chemistry` | 2,002 个非洲多国 topsoil/subsoil 样品、18 个国家标签、51 个站点和六目标元素，补非洲土壤与方法/阈值证据 | 已完成工程接入 | 非均匀 LDSF 站点；126 个缺坐标样品；负数及大量低于 DL/QL 的发布数值；人工复核未签署 | 完成具名复核和 V4 全量 profile；继续补非洲水体、岩石及独立土壤来源 |
| 1 | `canada-bc-rgs` / `argentina-segemar-geochemistry` / `alaska-dggs-webgeochem` | 同时补北美省/州级与南美覆盖；均已有数值下载或公开目录，且保留方法/出版物线索 | 中高 | 多原始调查、历史方法、重复发布和逐文件许可 | BC 固定 2020 版文件；Argentina 选一个开放图幅；Alaska 选一个具 DOI 的 DGGS 数据包，各自做字段/方法/hash 对账 |
| 2 | `ireland-tellus` | 同时补土壤、沉积物和水，适合验证跨介质 schema | 中 | 官网临时下线、多个区域/国家 release、许可通知需重新固定 | 官网恢复后固定具体 ZIP、release note、方法表、许可和 checksum |
| 3 | `sweden-sgu-geochemical-atlas` / `finland-gtk-geochemistry` | 增加北欧沉积物和岩石的官方可查询数值 | 中 | 产品/图层许可和版本不同，介质及提取方法必须分开 | 瑞典先固定 till CSV 许可与 hash；芬兰先选一个岩石和一个沉积物产品复核 |
| 4 | `canada-cdogs` | 大量沉积物和水体调查，且有官方原始/标准化文件 | 中高 | 逐调查版本、联邦/省许可、复测与重发布关系 | 先选一个开放、字段完整的沉积物+水调查做端到端复核 |
| 5 | `emodnet-chemistry` | 扩展欧洲海洋水/沉积物候选，并为水体分析物提供独立交叉来源 | 中高 | 聚合、贡献者引用和上游重复 | 固定一个不受限协调产品，并先完成 record-level provider 血缘解析 |
| 6 | `usgs-ngdb` / `norway-ngu-lito` | 扩展岩石、沉积物和土壤的国家数据 | 高 | 历史异质；LITO 2026 版尚未完成最终 QC | USGS 先选不可变发布；LITO 等最终 QC 或明确保留 preliminary 标志后再适配 |
| 7 | `petdb` / `georoc-database` | 把岩石从太古宙专题扩展到更多全球构造环境 | 中 | 动态数据库、相互聚合、与原论文和预编译集重叠 | 固定查询快照，验证生产端点并建立原论文/样品去重键 |
| 8 | `soils4africa` / `brazil-sgb-geochemistry` | 增加非洲土壤与南美多介质官方入口 | 中高 | 隐私/聚合约束、许可未固定、项目和集成服务重叠 | 分别先审许可边界和导出小样，再决定适配器范围 |
| 9 | `pangaea-repository` / `earthchem-library` / `noaa-ncei-marine-geology` / `iodp-data-systems` | 扩大 DOI、海洋和论文数据发现范围 | 高 | 逐数据集 schema 与许可，样品目录和数值混杂，镜像重复 | 先实现发现与血缘解析，不把仓库、目录或分发系统当作独立生产来源 |

`glorich` 与 `bgs-gbase` 原始点数据当前分别受非商业条款和单独授权限制，不排除于目录，但不进入 open-only 适配器排期。`australia-ozchem` 在找到当前官方数值端点前保持元数据状态。`jamstec-darwin` 与 NOAA IMLGS 当前只按样品/数据发现入口处理。

第四轮新发现中，`chile-sernageomin-geochemistry` 与 `south-africa-cgs-geochemistry` 排在上述首批之后：二者均有数值图层潜力，但必须先固定产品许可、方法、单位和版本。`mexico-sgm-geochemical-cartography` 当前只证实派生图层且存在两套许可文字，`india-gsi-ngcm` 当前公开 Atlas 无记录，均保持 metadata/discovery，不进入近期适配器主线。

## 排序规则

1. 先补齐当前 `normalized_analysis` 来源缺失的区域、介质子类型和独立交叉来源；水体 As 已由 GEMStat 补入，但仍优先扩大淡水国家覆盖并补每个元素的第二来源；
2. 再扩大当前单一区域或单一来源覆盖；
3. 在覆盖收益相近时，优先不可变版本、开放许可、结构化接口和完整方法元数据；
4. 缺失证据按维度降分并限制 use mode，不因为排名靠前而隐藏限制；
5. 每完成一批来源后重算覆盖矩阵，排序可以变化但目录范围不能缩小。
