# D1 数据源接口卡片

> V4 当前使用 DOI/PID、版本、文件 ID/名称、发布/访问时间、字节数、schema、行数和关键统计追踪来源；历史完整性令牌不参与当前流程。

核对日期：2026-08-07。发现事实以 `../assets/source_catalog.json` 为准；V4 状态以 `../assets/source_evidence_scores.json` 为准。下方候选卡保留发现历史，不覆盖机器目录。

## 当前接口状态

核对日期：2026-08-07。当前可执行来源为 21 个，全部完成 30 条结构化 Codex 自动审计、候选来源审计和统一全量 profile。旧字段 `needs_human_review` 只用于兼容历史目录；新流程不要求具名人工签署。

所有可执行来源都通过 DOI/PID、版本、文件 ID/名称、发布日期、字节数、schema、行数和关键统计进行追踪。历史 checksum 字段不参与准入、缓存、评分或验收。

| 介质 | 当前可执行来源 | 主要证据缺口 |
|---|---|---|
| 岩石 | GEOROC Archaean、GEOROC Antarctica | 两者共享 GEOROC 上游血缘；逐记录方法缺失 |
| 土壤 | USGS CONUS、GEMAS、FOREGS 三类、AfSIS、TPDC、PANGAEA 北非 | AfSIS/TPDC 原始 CRS 未声明；USGS 缺逐记录方法 |
| 沉积物 | FOREGS 两类、GSJ 河流/海洋、NGSA、MarChem、PANGAEA Arabian Sea | GSJ 缺逐记录方法、DL 和 QC；区域覆盖不均 |
| 水体 | GEMStat、GEOTRACES、FOREGS、WQP Sacramento | 水体类型和地域不均；部分方法连接缺失 |

逐来源版本、字段和边界以 `assets/source_catalog.json`、`assets/source_manifest.json`、`assets/v4-full-profiles/` 和 `fixtures/four-media/**/automated_audit.json` 为准。

## 历史候选接口卡（状态以机器目录为准）

### `tpdc-china-mountain-soil`

- 介质与范围：中国 30 个山地生态系统、166 个站点、1,314 个 O/A/C 层样品，不是全国规则网格；
- 接口与版本：DOI `10.11888/Terre.tpdc.302620` 解析到固定 TPDC UUID；官方 metadata POST、file-inventory GET 和 file-ID POST 下载均已核实；
- 获取与校验：`Soil dataset.zip` 为 1,828,683 bytes，三个成员逐项固定文件身份、大小、schema、行数和关键统计；
- 对账：主表 1,314 行，Cr/Cu/Ni/Pb/Zn 各 1,314 条，共 6,570 条目标观测；As/Hg 不在源表；坐标、母岩类别、土纲和土类逐行完整；
- 方法：风干、<2 mm、HNO3-HF-HClO4 消解；Cr/Cu/Ni/Pb 为 ICP-MS，Zn 为 ICP-AES。方法和 QC 来自关联论文，只能标成 publication scope；
- 质量边界：来源未声明 CRS；SN5/SN6/SN7 各有多个坐标对；独立 bulk-density 表可补部分缺失，但存在六个非空值冲突和五个坐标冲突，不能静默覆盖主表；
- 当前：V4 schema、canonical adapter、30 条自动审计和完整率 profile 已完成；原始 CRS 仍保持 unknown。

### `georoc-database`

- 介质与范围：全球火成岩、变质岩、玻璃、矿物和包裹体文献汇编；
- 已发现接口：筛选下载、样品、地点、元素、引用和统计 API，以及 DOI 预编译数据集；
- 可用过滤：地点、材料、岩石类型、元素、样品 ID 等；
- 许可：数据库查询数据为 CC BY-SA 4.0；仓储数据集可能有独立条款；
- 待办：当前发现的是 test API 文档，必须核对生产端点、API 版本、分页和下载完整性；
- 上游要求：每条记录保留原始论文引用，不能把 GEOROC 当作独立的第二份证据。

### `usgs-ngdb`

- 介质与范围：美国及领地的岩石、土壤、沉积物、矿物和精矿；
- 已发现接口：USGS National Geochemical Database 页面与数据发布入口；
- 许可：USGS 来源通常为美国公有领域，但逐数据发布核对非 USGS 内容和引用；
- 待办：选择不可变的具体数据发布，核对下载文件、版本、字段字典、方法和 qualifier；
- 风险：历史系统合并导致方法、单位和编码高度异质。

### `wosis`

- 介质与范围：全球土壤剖面和属性，空间与属性覆盖不均；
- 已发现接口：动态 OGC WFS、GraphQL 说明、带 DOI 的 2023-12 TSV snapshot；
- 许可：公开记录仍可能分别为 CC BY 或 CC BY-NC，必须记录级过滤；
- 待办：确认哪些字段属于元素地球化学、固定 snapshot 校验和、建立记录级许可门；
- 边界：WoSIS 是标准化土壤属性系统，不等同于统一分析方法的全球元素调查。

## 发现与元数据候选

### `earthchem-portal`

- 用途：发现 PetDB、GEOROC、SedDB 等上游固体地球化学记录；
- 状态：`metadata_only`，当前不直接作为独立数值来源；
- 原因：聚合结果必须回到原数据库、数据集 DOI 和原始论文，避免重复计数与许可混淆。

### `gemas-europe`

- 介质与范围：欧洲农业与放牧地土壤；
- 已发现接口：GEMAS 项目页、BGR WMS 和产品链接；
- 状态：`metadata_only`；
- 待办：查明可下载数值版本、许可、引用、字段和批量访问方式后再决定准入。

## M6 第二轮新增候选

本轮当时新增 14 个入口，候选总数从 8 个增至 22 个；以下保留当轮发现记录。之后 MarChem 和 GEOTRACES 已完成工程接入，当前状态见本文开头和机器评分文件。

| 来源 | 介质 | 范围 | 当前可见接口 | 主要阻断项 |
|---|---|---|---|---|
| `petdb` | 岩石、矿物 | 全球海底及部分陆域 | EarthChem 查询与导出 | 动态版本、原论文去重、适配器 |
| `foregs-europe` | 土壤、沉积物、水 | 欧洲 | 项目总入口 | 仅作发现与父项目血缘；数值接入已拆成下列六项 |
| `foregs-topsoil` | 土壤 | 欧洲 | 固定 ZIP/CSV | 已实现；总量/王水、重复 GTN、表级 DL 分开保留 |
| `foregs-subsoil` | 土壤 | 欧洲 | 固定 ZIP/CSV | 已实现；25 cm 下层样品只保留发布方深度范围语义 |
| `foregs-humus` | 土壤 | 欧洲 | 固定 ZIP/CSV | 已实现；温和硝酸浸出，不含 As/Cr |
| `foregs-stream-water` | 水 | 欧洲 | 固定 ZIP/CSV | 已实现；<0.45 µm 溶解态，无可接受 Hg |
| `foregs-stream-sediment` | 沉积物 | 欧洲 | 固定 ZIP/CSV | 已实现；<150 µm，总量/王水分开 |
| `foregs-floodplain-sediment` | 沉积物 | 欧洲 | 固定 ZIP/CSV | 已实现；0–25 cm，与溪流沉积物分开 |
| `canada-cdogs` | 沉积物、水、精矿 | 加拿大 | 调查目录和部分标准化下载 | 逐调查版本/许可、复测关系 |
| `australia-ngsa` | 沉积物（运移表生覆盖物） | 澳大利亚 | 国家 Atlas 和产品下载 | 固定具体产品、文件身份、字节数、schema、行数和介质语义 |
| `australia-ozchem` | 岩石、沉积物 | 澳大利亚 | 仅核实到官方旧版产品说明 | 当前数值端点、版本、上游重叠 |
| `us-water-quality-portal` | 水、沉积物 | 美国 | WQP Web Services | 贡献者许可、介质/方法异质、上游去重 |
| `soils4africa` | 土壤 | 非洲农业用地 | CSV、GeoPackage | 隐私与聚合条款、分析物清单、适配器 |
| `bgs-gbase` | 土壤、沉积物、水、精矿 | 英国 | 开放派生栅格、授权点数据 | 原始点数据非 open-only |
| `brazil-sgb-geochemistry` | 岩石、土壤、沉积物、水、精矿 | 巴西 | ArcGIS FeatureServer、项目 ZIP | 许可、字段、方法、重复关系 |
| `nz-petlab` | 岩石、矿物、沉积物 | 新西兰及部分全球馆藏 | 开放查询、注册后导出 | 导出条款、动态版本、引用去重 |
| `earthchem-library` | 全介质发现 | 全球 DOI 仓库 | 检索和原始文件下载 | 逐数据集许可、版本、schema 和统计；仓库本身不是统一数据集 |
| `geotraces-idp2025` | 海水 | 全球海洋航次 | BODC PDL 元数据、WebODV 子集 | 当轮只核实 DOI、许可和产品元数据；后续已用 WebODV 完成快照、字段、QC、适配器和端到端验收 |
| `glorich` | 河水 | 全球河流 | PANGAEA DOI 批量包 | CC BY-NC-SA，不进入当前 open-only 生产 |
| `eea-waterbase` | 水、沉积物 | 欧洲 | CSV 下载与筛选 | 动态版本、国家方法差异、具体许可标识 |

### 本轮最重要的判断

- 沉积物候选从少数发现线索扩展到欧洲、加拿大、澳大利亚、英国、巴西、美国和 DOI 仓库入口；该结论记录的是当轮发现状态，后续 MarChem 已接入；
- 水体已区分河流、一般水质、欧洲报告水体和全球海洋航次，不能把它们混成一种介质；
- `geotraces-idp2025` 当轮已具备固定版本、DOI、CC BY 4.0 和质量控制说明；当时 BODC 异步归档为 `notready`，后续改用官方 WebODV 冻结子集并完成文件与变量验收；
- `glorich` 很大但带 NC 限制，`bgs-gbase` 原始点数据需单独授权；两者保留用于覆盖判断，不参与 open-only 自动路由；
- `earthchem-library` 和 Water Quality Portal 是发现/聚合入口，生产数据必须保留并去重上游数据集与提供者。

## M6 第三轮新增候选

本轮新增 10 个入口，候选目录由 22 个增至 32 个，重点补海洋/湖泊档案和欧洲、亚洲国家机构。当轮二元批准来源仍只有两个；当时 V3 已有四个 A 级 `normalized_analysis` 样板。

| 来源 | 介质 | 范围 | 当前可见接口 | 当前判断与主要阻断项 |
|---|---|---|---|---|
| `noaa-ncei-marine-geology` | 岩石、沉积物 | 全球海洋与湖床馆藏 | NCEI 检索/地图/服务、IMLGS ERDDAP | 档案含数值文件，但 IMLGS 本身主要是样品目录；必须逐原始数据集接入 |
| `pangaea-repository` | 四类介质发现 | 全球 DOI 仓库 | 高级检索、DOI 元数据和逐数据集文件 | 逐 DOI 核对许可、版本、schema、方法和上游项目，仓库不算独立证据 |
| `iodp-data-systems` | 岩石、沉积物、孔隙水 | 全球大洋钻探站点 | SEDIS、各科学运营方系统、LIMS 报表 | 系统和 schema 分散；需按航次、站位、孔、深度及解禁状态固定版本 |
| `emodnet-chemistry` | 海水、海洋沉积物 | 欧洲海域 | ERDDAP、CDI、webODV | ERDDAP 是不受限记录的协调产品，CDI 含受限记录；均需保留数据提供者血缘 |
| `jamstec-darwin` | 岩石、沉积物 | JAMSTEC 航次区域 | 航次、潜次和样品搜索 | 当前只确认到样品与观测发现；未把 legacy GANSEKI 或样品目录误写为统一数值库 |
| `ireland-tellus` | 土壤、沉积物、水 | 爱尔兰 | 官方地理数据下载 | 多介质、方法文档较完整；本轮官网临时下线，需重新固定具体文件和许可通知 |
| `sweden-sgu-geochemical-atlas` | 冰碛物 | 瑞典 | 官方 CSV/API、方法与检出限表 | 已核实原始下载是 till；土壤比较表不是原始土壤观测；许可仍需固定 |
| `finland-gtk-geochemistry` | 岩石、冰碛物、河流沉积物 | 芬兰 | Hakku、ArcGIS REST | 国家岩石产品与多套沉积物调查不能共用方法假设；逐产品核对许可和版本 |
| `norway-ngu-lito` | 岩石 | 挪威 | 2026-06 初步 XLSX | NGU 明示最终岩性命名与批次校正尚未完成，暂不能批准 |
| `norway-marchem` | 海洋沉积物 | 挪威海域 | 公开 JSON 列表 API、按条件导出 ZIP | 已验证 As/Cu/Ni/Zn、干重单位、批次方法和许可；动态导出无对应不可变 DOI，部分消解、认可状态和重复样品行需保留 |

### 第三轮的边界判断

- 样品目录和数值测定已经拆开：IMLGS、DARWIN 只承担发现，不能直接满足分析请求；
- PANGAEA、NOAA、IODP、EMODnet 与国家数据库可能发布同一航次或项目，来源独立性按原项目和原样品计算；
- 新增候选提升的是“去哪里找”的全面性；当轮沉积物、水体尚无 V1 `approved`，后续已分别完成 MarChem 和 GEOTRACES V3 工程样板；
- `source_discovery_scope.json` 按区域记录尚未完成的检索，亚洲、非洲、南美及州/省级调查仍是明显缺口；发现状态继续为 `in_progress`、`saturated=false`。

## M7 第四轮新增候选

本轮新增 8 个官方入口，目录由 32 个增至 40 个，补到墨西哥、加拿大省级、美国州级、智利、阿根廷、印度、日本和南非。新增的是“已找到并有官方证据的入口”，不是已经完成适配或达到生产置信度的来源。

| 来源 | 介质 | 范围与可见规模 | 已验证接口 | 当前判断与下一步 |
|---|---|---|---|---|
| `mexico-sgm-geochemical-cartography` | 河流沉积物派生图层 | 墨西哥全国 1:250,000，源于 1995–2005 活性河流沉积物分析 | GeoInfoMex SHP/KML、联邦开放数据页 | 先确认下载文件是否包含样点原始数值；联邦 CC BY 4.0 与 GeoInfoMex 限制性告示需按文件核对 |
| `canada-bc-rgs` | 沉积物、水、重矿物精矿 | BC 省；2020 版称 65,000 样品、约 500 万测定、116 个原始来源、18 种方法/实验室 | XLS/PDF 版本下载、样点 ArcGIS | 高价值多介质候选；先固定 2020 文件身份、字节数、字段表、许可和原调查血缘 |
| `alaska-dggs-webgeochem` | 岩石、土壤、沉积物、精矿 | 阿拉斯加；持续汇入 DGGS、USGS、BLM 和历史来源 | WebGeochem 查询/全量导出、具 DOI 的 DGGS 数据包 | 首个适配器优先选不可变 DGGS publication package，不直接冻结无版本全库 |
| `chile-sernageomin-geochemistry` | 河流沉积物 | 智利区域图幅；官方称超过 10,000 样品、23 万平方公里、每样最多 66 元素 | 官方 viewer、ArcGIS、逐图幅 Excel 产品 | 产品和许可逐图幅核对；全国规模描述不能替代文件级验收 |
| `argentina-segemar-geochemistry` | 河流沉积物、土壤 | 阿根廷；SIGAM 年报称超过 40,000 条沉积物记录 | GeoNetwork 开放目录、SIGAM viewer、逐图幅产品 | 先挑一个可下载图幅核对 54 元素字段、方法、坐标误差和许可 |
| `india-gsi-ngcm` | 河流沉积物 | 印度 NGCM；2×2 km 单元、计划 66 元素、1:50,000 | 官方 Atlas、曾用于黑客松的 Excel/PDF 分发 | 当前 Atlas 返回 0 条，数值入口带登录/活动属性，暂只作发现 |
| `japan-gsj-geochemical-map` | 河流/海洋沉积物、后续表层土壤 | 日本陆海；约 3,000 河流沉积物和 5,000 海洋沉积物 | 样点/浓度数据库、Shapefile、As/Cu/Ni/Zn WMS/WMTS | 后续已将 3,024 行河流沉积物文件对固定并实现适配器；海洋沉积物和表层土壤仍是独立待接入产品 |
| `south-africa-cgs-geochemistry` | 河流沉积物、替代土壤 | 南非多个图幅；已验证 Alexander Bay 点层含 As/Cu/Ni/Zn 和坐标字段 | ArcGIS Feature/MapServer | 先完整读取产品许可、方法、单位和检出限；图幅集合不冒充连续全国库 |

### 第四至第六轮的边界判断

- 第四轮结束时目录有 40 个来源和 5 个 A 级 `normalized_analysis` 样板；此后 GSJ 河流沉积物、PANGAEA 北非土壤、FOREGS 六个介质数据集和 AfSIS Phase I V2.0 完成接入，TPDC 中国山地土壤完成文件契约冻结；当前目录为 49 项、A 级可执行样板仍为 14 项；
- GSJ 已完成首个河流沉积物适配器；BC RGS、阿拉斯加 WebGeochem 和阿根廷 SIGAM 仍是下一批高价值数值接入候选；
- 墨西哥目前证明的是派生图层，印度目前证明的是项目和有限分发路线，不能写成已获得原始全量数据；
- 南非、BC 和阿拉斯加均含多来源或多图幅内容，独立来源数必须回到原调查、出版物和样品，而不是按门户计数；
- 第四轮仍未解决非洲水体、亚洲更多国家、太平洋岛国和论文 DOI 长尾，发现状态保持 `in_progress`、`saturated=false`。

## M7 首批逐源复核

详细历史证据、记录对账和阻断项见 `source-verification-report.md`；当前状态以机器目录和完整率报告为准。

- `norway-marchem` 的公开 API 已能稳定返回目标元素，但当前响应是带生成时间的动态 ZIP，不是已固定 DOI 的不可变发布；
- MarChem 本次导出有 1,070 个物理数据行、880 个不同样品。190 个样品因两个参数组而重复出现，但每个样品只有一行含目标元素；适配器必须按参数和批次展开，不能按行计样品；
- 四个目标元素均为干重 `mg/kg`，保留 `<` 删失值；方法是部分硝酸消解，不代表总量；目标方法元数据中同时存在 accredited 和 not-accredited 批次；
- MarChem 已完成 30 条结构化自动审计、canonical 适配和全量对账；
- `geotraces-idp2025` 已完成 30 条结构化自动审计，并用官方 WebODV 完成 69,704 行和 39,327 条 Cu/Ni/Zn 观测验收；无 As，贡献者/方法完整率仍需深化。

## 路由示例

```bash
python scripts/source_router.py \
  --request request.json \
  --output route_result.json
```

V4 路由器按 `research_use_policy`、`minimum_evidence_tier` 和 `minimum_use_mode` 选择来源，不再只检查 `production_eligible=true`。其余匹配来源进入 `review_sources` 并显示当前较低的证据或使用级别。只要目录发现尚未饱和，缺少来源就保持 `unknown`，不会提前写成 `uncovered`。
