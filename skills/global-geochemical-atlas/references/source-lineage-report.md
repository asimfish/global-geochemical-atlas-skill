# D1 来源血缘与独立性报告

核对日期：2026-08-05。此报告用于避免把聚合站转载、同一上游数据的多个镜像或预编译子集误算成多份独立证据。

## 当前关系

| 来源 | 角色 | 已知上游或下游关系 | 独立性处理 |
|---|---|---|---|
| `georoc-archaean` | DOI 预编译数据集 | 数据来自 GEOROC 收录的原始论文；是 `georoc-database` 的专题预编译集合 | 与 GEOROC 在线库重叠时按原始样品、论文和来源记录去重，不算独立证据 |
| `georoc-database` | 文献汇编数据库 | 汇编大量原始论文测定；可生成预编译数据集 | 必须保留原始论文引用；同一论文/样品在不同下载中出现只算一个上游来源 |
| `earthchem-portal` | 联邦聚合与发现入口 | 可发现 GEOROC、PetDB、SedDB 等上游数据库 | 不作为独立数值证据；记录必须解析到上游数据库和数据集/论文 |
| `usgs-conus-soil` | 原始国家调查数据发布 | 独立的 USGS Data Series 801 | 当前土壤生产体系唯一来源，标记 `single_source_dependency` |
| `usgs-ngdb` | 国家历史数据汇编 | 汇合 RASS、PLUTO、ATHENA、NURE 等项目数据 | 每条记录保留项目和实验室来源；与单独 USGS 发布重叠时按样品和分析记录去重 |
| `gemstat-open-archive` | 国际水质聚合数据库 | 数据由各国和各机构监测网络提供 | GEMStat 是分发层；独立性按原始 data provider 和监测计划计算，不按下载批次计算 |
| `wosis` | 国际土壤数据标准化与分发系统 | 汇集多个数据提供者的土壤剖面 | 独立性按原始数据集/提供者计算，动态 WFS 与 DOI snapshot 不能算两份来源 |
| `gemas-europe` | 协调采样的区域调查项目 | 欧洲各参与地调机构按统一项目设计采样 | 作为一个协调项目处理；参与机构数量不自动等于独立采样体系数量 |
| `petdb` | 文献汇编数据库 | EarthChem Portal 上游之一，包含原始论文数据 | 与 Portal 导出及论文补充数据按样品、分析和引用去重 |
| `foregs-europe` | 协调采样的区域调查项目 | 多个欧洲地调参与，但使用共同项目设计 | 整个 FOREGS 视为一个调查体系；国家参与者不自动算独立来源 |
| `canada-cdogs` | 国家调查目录与部分标准化分发 | 汇集联邦、省级、历史调查和复测发布 | 独立性按原采样调查计算；复测或重新发布不增加采样来源数 |
| `australia-ngsa` | 协调国家调查 | Geoscience Australia 与各州/领地共同采样 | 作为一个国家项目；不能把每个合作机构重复计数 |
| `australia-ozchem` | 国家汇编数据库 | 含 Geoscience Australia 和州级开放文件数据 | 必须回到贡献调查；与州级单独发布按样品/分析去重 |
| `us-water-quality-portal` | 联邦聚合入口 | 分发 NWIS 与 WQX 多组织记录 | Portal 本身不算独立来源；按原组织、监测计划和活动 ID 计算 |
| `soils4africa` | 协调洲际调查 | 多国采样但使用统一项目设计 | 作为一个协调项目；按站点/样品 ID 去重，不按国家数扩张独立性 |
| `bgs-gbase` | 国家调查项目 | 英国各区域批次与 TellusNI 等关联产品 | 按原调查和样品编号计算；开放栅格是点数据派生物，不是第二来源 |
| `brazil-sgb-geochemistry` | 国家集成服务 | 集成 FeatureServer 与多个项目 ZIP/仓库发布 | 项目 ZIP 和集成点必须按项目、样品、分析方法去重 |
| `nz-petlab` | 国家馆藏和文献汇编 | 汇集 GNS、大学、论文、报告和多个馆藏 | 按原馆藏/论文与样品记录计算，Petlab 导出不自动成为独立证据 |
| `earthchem-library` | DOI 文件仓库 | 保存作者提交的论文关联数据和专题汇编 | 仓库不是统一来源；独立性按每个 DOI 的原项目和样品判定 |
| `geotraces-idp2025` | 协调国际数据产品 | 汇合各航次和实验室，经项目内校准/QC | 项目级产品可作为一套协调数据；仍保留航次、实验室和原贡献者 |
| `glorich` | 全球河流数据汇编 | 汇集多个国家/研究数据集 | 与 GEMStat、WQP、Waterbase 等可能重叠；按原提供者/站点/日期去重 |
| `eea-waterbase` | 区域报告聚合库 | 各欧洲国家向 EEA 报送 | EEA 分发不增加独立性；按国家提供者、监测站和计划计算 |
| `noaa-ncei-marine-geology` | 海洋/湖泊长期档案与样品目录 | 汇集多机构、航次、IODP legacy 数据及实物样品库元数据 | IMLGS 只作发现；数值必须回到具体档案文件、项目和原始引用，与 IODP/PANGAEA 镜像去重 |
| `pangaea-repository` | DOI 数据仓库 | 保存作者、项目和数据中心提交的数据；包含 `glorich` 及部分 IODP 数据 | 仓库不算独立来源；按 DOI 背后的原项目、样品和论文判定，并与 EarthChem Library 等仓库镜像去重 |
| `iodp-data-systems` | 国际协调钻探计划的多系统档案 | 同一航次数据可同时出现在运营方 LIMS、SEDIS、PANGAEA 和 NCEI | 按航次/站位/孔/样品/分析记录合并血缘，不按分发系统数量增加独立性 |
| `emodnet-chemistry` | 欧洲海洋化学聚合与协调产品 | CDI 来自国家数据中心，ERDDAP/webODV 是其中不受限记录的标准化汇编 | 与 EEA、SeaDataNet 和国家发布按提供者、站位、样品与时间去重；派生产品不是第二来源 |
| `jamstec-darwin` | 航次、潜次与样品发现系统 | JAMSTEC 航次数据及岩石/沉积物样品目录；可能关联 legacy GANSEKI | 当前不把样品目录当数值证据；GANSEKI 未解析到当前端点前不另计来源 |
| `ireland-tellus` | 国家协调地球化学调查 | 多批 Tellus 地区调查和可能的后续国家发布 | 独立性按原采样批次和样品计算；区域重发、地图产品及向其他门户供数不重复计数 |
| `sweden-sgu-geochemical-atlas` | 国家地球化学图集数据 | 原始 till 下载及相关方法/统计表 | 原始观测只计一次；统计表、地图和 CSV/API 表达不构成额外证据 |
| `finland-gtk-geochemistry` | 国家数据产品和多套调查服务 | Hakku 岩石产品、区域/详细 till 与河流沉积物 ArcGIS 图层 | 每套原调查分别建血缘；同一记录在 Hakku、地图服务和下载文件之间去重 |
| `norway-ngu-lito` | 国家协调岩石调查 | NGU LITO 采样、实验室分析及版本化 XLSX | 作为一个调查体系；旧静态页面与 2026 新发布不算两套独立数据 |
| `norway-marchem` | 国家海洋沉积物数据库 | MAREANO 及 NGU/IMR 其他监测项目，另在 NMDC 发布 DOI | 按原监测项目、站位、样品和 DOI 版本去重；MarChem、NMDC 与 EMODnet 镜像只算一次 |
| `mexico-sgm-geochemical-cartography` | 国家派生地球化学图层 | 由 SGM 活性河流沉积物分析生成的 1:250,000 SHP/KML 图层 | 派生地图不能作为第二份观测证据；必须找到样点表并按原样品/图幅与后续 1:50,000 异常层去重 |
| `canada-bc-rgs` | 省级多调查汇编 | 汇入 BCGS、GSC、Geoscience BC 的 116 个原始来源 | 独立性按原调查、样品和分析批次计算；RGS 2020 汇编、CDoGS 和原报告重叠时只算一次 |
| `alaska-dggs-webgeochem` | 州级多机构汇编与发布系统 | 汇入 DGGS、USGS、BLM、BOM 及扫描历史报告；DGGS 新数据另有 DOI publication package | WebGeochem 导出与单独 DGGS/USGS 发布按 publication/sample/analysis 去重；门户本身不增加独立性 |
| `chile-sernageomin-geochemistry` | 国家协调计划和逐图幅发布 | 同一样品可出现在官方 viewer、ArcGIS 服务、Excel 产品和图幅报告 | 按图幅/项目、采样点、样品和分析记录合并；全国计划统计不能按产品数扩张证据数 |
| `argentina-segemar-geochemistry` | 国家历史与现代调查发布系统 | SIGAM 汇合 1960–1980 年代档案样品、1990 年代以后 SEGEMAR 采样和逐图幅报告 | 按原项目、图幅、样品和分析批次去重；GeoNetwork、viewer、repository PDF 和产品表不是独立来源 |
| `india-gsi-ngcm` | 国家协调地球化学计划 | NGCM 按统一 2×2 km 单元设计；数据可在 Atlas、专题报告或活动分发中出现 | 整个计划按调查体系处理；同一 toposheet 的 Atlas、Excel 和报告不重复计数，未公开单元不推断为已覆盖 |
| `japan-gsj-geochemical-map` | 国家陆海地球化学调查与派生地图服务 | 河流沉积物、海洋沉积物、精密区域和后续表层土壤由样点数据库派生 WMS/WMTS/3D 地图 | 按调查代际、介质和样品去重；点表是观测，Shapefile/WMS/WMTS/3D 地图不各算一份来源 |
| `south-africa-cgs-geochemistry` | 国家门户中的逐图幅产品集合 | 多个 geochemistry FeatureServer/MapServer 图层对应不同地图幅和出版物 | 按地图幅、原调查和样品计算；同一图层的 Feature/Map service 表达只算一次，门户不代表连续全国覆盖 |

## 当前单一来源依赖

- 岩石生产路由只有 `georoc-archaean`，且仅覆盖太古宙克拉通；
- 土壤生产路由只有 `usgs-conus-soil`，且仅覆盖美国本土；
- 沉积物当前只有 `norway-marchem`，且仅覆盖挪威海域；
- 水体虽有 `gemstat-open-archive` 与 `geotraces-idp2025` 两个分析来源，但 As 只来自前者，Cu/Ni/Zn 只来自后者；介质子类型也分别是淡水与海水，因此每个目标元素仍是单一来源依赖；
- 当前没有任何介质可以声明全球、方法一致且多来源独立覆盖。

## 去重键原则

优先使用永久样品标识和原始记录标识；缺失时组合使用：

```text
原始提供者 + 原始项目/数据集 + 样品 ID/IGSN + 采样位置与时间
+ 分析物原名 + 方法 + 原始值 + 原始单位
```

坐标接近或数值相同只能生成重复候选，不能自动删除。最终去重和方法可比性由 D2 决定，D1 只提供血缘和候选关系。
