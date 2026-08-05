# D1 候选来源接入顺序

核对日期：2026-08-05。排序只安排接入和复核先后，不删减全介质、全信源普查范围。

| 顺序 | 来源 | 主要覆盖收益 | 接入成本 | 当前主要风险 | 下一道动作 |
|---:|---|---|---|---|---|
| 已接入 | `geotraces-idp2025` | 已补全球海洋航次 Cu/Ni/Zn normalized-analysis 样板；固定版本、DOI、QC、动态快照和全量关系已核实 | 已完成工程接入 | 航次覆盖不连续；无 As；30 条人工复核和贡献者/方法完整率尚未签署 | 接入含 As 的水体来源；完成人工签署后升为 `benchmark_ready` |
| 已接入 | `norway-marchem` | 已补海洋沉积物 normalized-analysis 样板；公开 API、许可、目标元素、方法、动态快照和全量关系均已核实 | 已完成工程接入 | 只覆盖挪威海域；30 条人工复核尚未签署 | 完成 30 条逐条复核后升为 `benchmark_ready`；另补独立沉积物来源 |
| 3 | `ireland-tellus` | 同时补土壤、沉积物和水，适合验证跨介质 schema | 中 | 官网临时下线、多个区域/国家 release、许可通知需重新固定 | 官网恢复后固定具体 ZIP、release note、方法表、许可和 checksum |
| 4 | `foregs-europe` | 一个协调调查同时补土壤、沉积物和水体，可与 Tellus 做血缘/方法对照 | 中 | 再分发条款、旧 Excel 结构、多方法/实验室 | 固定下载文件清单，确认许可并盘点 As/Cu/Ni/Zn 字段与方法 |
| 5 | `sweden-sgu-geochemical-atlas` / `finland-gtk-geochemistry` | 增加北欧沉积物和岩石的官方可查询数值 | 中 | 产品/图层许可和版本不同，介质及提取方法必须分开 | 瑞典先固定 till CSV 许可与 hash；芬兰先选一个岩石和一个沉积物产品复核 |
| 6 | `canada-cdogs` | 大量沉积物和水体调查，且有官方原始/标准化文件 | 中高 | 逐调查版本、联邦/省许可、复测与重发布关系 | 先选一个开放、字段完整的沉积物+水调查做端到端复核 |
| 7 | `gemstat-open-archive` / `emodnet-chemistry` | 扩展淡水和欧洲海洋水/沉积物候选 | 中高 | 聚合、混合许可、数据提供者引用和上游重复 | 固定一个开放批次/协调产品，并先完成 record-level provider 血缘解析 |
| 8 | `usgs-ngdb` / `norway-ngu-lito` | 扩展岩石、沉积物和土壤的国家数据 | 高 | 历史异质；LITO 2026 版尚未完成最终 QC | USGS 先选不可变发布；LITO 等最终 QC 或明确保留 preliminary 标志后再适配 |
| 9 | `petdb` / `georoc-database` | 把岩石从太古宙专题扩展到更多全球构造环境 | 中 | 动态数据库、相互聚合、与原论文和预编译集重叠 | 固定查询快照，验证生产端点并建立原论文/样品去重键 |
| 10 | `soils4africa` / `brazil-sgb-geochemistry` | 增加非洲土壤与南美多介质官方入口 | 中高 | 隐私/聚合约束、许可未固定、项目和集成服务重叠 | 分别先审许可边界和导出小样，再决定适配器范围 |
| 11 | `pangaea-repository` / `earthchem-library` / `noaa-ncei-marine-geology` / `iodp-data-systems` | 扩大 DOI、海洋和论文数据发现范围 | 高 | 逐数据集 schema 与许可，样品目录和数值混杂，镜像重复 | 先实现发现与血缘解析，不把仓库、目录或分发系统当作独立生产来源 |

`glorich` 与 `bgs-gbase` 原始点数据当前分别受非商业条款和单独授权限制，不排除于目录，但不进入 open-only 适配器排期。`australia-ozchem` 在找到当前官方数值端点前保持元数据状态。`jamstec-darwin` 与 NOAA IMLGS 当前只按样品/数据发现入口处理。

## 排序规则

1. 先补齐当前 `normalized_analysis` 来源缺失的目标元素、区域和介质子类型；水体当前优先 As 与淡水；
2. 再扩大当前单一区域或单一来源覆盖；
3. 在覆盖收益相近时，优先不可变版本、开放许可、结构化接口和完整方法元数据；
4. 缺失证据按维度降分并限制 use mode，不因为排名靠前而隐藏限制；
5. 每完成一批来源后重算覆盖矩阵，排序可以变化但目录范围不能缩小。
