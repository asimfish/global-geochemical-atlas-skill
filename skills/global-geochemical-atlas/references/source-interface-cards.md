# D1 数据源接口卡片

核对日期：2026-08-05。机器可读事实以 `../assets/source_catalog.json` 为准。本文件只作人工审阅入口；候选目录中的来源不等于已经批准用于生产。

## 状态说明

| 状态 | 含义 |
|---|---|
| `approved` | 版本、许可、来源链、字段、校验和适配器已经通过生产门 |
| `conditional` | 只有满足记录级许可、地区、介质或字段条件时才能使用 |
| `metadata_only` | 用于发现上游数据或说明覆盖，当前不提供生产数值 |
| `needs_human_review` | 已发现相关数据，但版本、许可、接口、字段或适配器仍需复核 |
| `rejected` | 已有证据表明不适合当前用途；仍保留排除理由 |

## 已批准来源

### `georoc-archaean`

- 介质与范围：全球太古宙克拉通岩石，属于全球岩石覆盖的局部集合；
- 接口：GRO.data Dataverse 版本化元数据 API 和完整 ZIP 下载；
- 版本：12.0，数据集 DOI `10.25625/1KRR1P`；
- 许可：CC BY-SA 4.0，必须保留 GEOROC 与原始论文引用；
- 校验：28 个成员文件名、大小、发布方 MD5 和本地 SHA-256；
- 适配器：`georoc_dataverse`，已实现；
- 边界：预编译选择值不是所有重复测定的无筛选全集。

### `usgs-conus-soil`

- 介质与范围：美国本土土壤，包含 0–5 cm、A horizon 和 C/deep 三层；
- 接口：USGS Data Series 801 静态制表符文件；
- 版本：Data Series 801，2013 release，DOI `10.3133/ds801`；
- 许可：USGS 公有领域，保留建议引用；
- 校验：三个文件固定 URL、观测 SHA-256、必需字段和土层区分；
- 适配器：`usgs_static_txt`，已实现；
- 边界：只代表 CONUS，legacy qualifier 和方法必须按数据集元数据解释。

## 待复核生产候选

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

### `gemstat-open-archive`

- 介质与范围：全球河流、湖泊、水库、湿地和地下水，覆盖不均；
- 已发现接口：Data Portal、年度 Zenodo 开放批次 `10.5281/zenodo.13881899`；
- 可用过滤：站点、国家、流域、参数和日期；门户下载有站点数与表单限制；
- 许可：逐提交批次可以是 Open、Limited 或 Restricted；生产只允许明确开放批次；
- 待办：固定具体 Zenodo 版本、文件清单、checksum、字段和数据提供者署名；
- 红线：不绕过联系表单、站点上限或 Restricted 数据策略。

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

本轮新增 14 个入口，候选总数从 8 个增至 22 个。新增不等于批准；默认路由仍只有 `georoc-archaean` 和 `usgs-conus-soil` 两个生产来源。

| 来源 | 介质 | 范围 | 当前可见接口 | 主要阻断项 |
|---|---|---|---|---|
| `petdb` | 岩石、矿物 | 全球海底及部分陆域 | EarthChem 查询与导出 | 动态版本、原论文去重、适配器 |
| `foregs-europe` | 土壤、沉积物、水 | 欧洲 | 压缩 Excel/Atlas | 再分发条款、文件清单、方法映射 |
| `canada-cdogs` | 沉积物、水、精矿 | 加拿大 | 调查目录和部分标准化下载 | 逐调查版本/许可、复测关系 |
| `australia-ngsa` | 沉积物（运移表生覆盖物） | 澳大利亚 | 国家 Atlas 和产品下载 | 固定具体产品、文件 hash、介质语义 |
| `australia-ozchem` | 岩石、沉积物 | 澳大利亚 | 仅核实到官方旧版产品说明 | 当前数值端点、版本、上游重叠 |
| `us-water-quality-portal` | 水、沉积物 | 美国 | WQP Web Services | 贡献者许可、介质/方法异质、上游去重 |
| `soils4africa` | 土壤 | 非洲农业用地 | CSV、GeoPackage | 隐私与聚合条款、分析物清单、适配器 |
| `bgs-gbase` | 土壤、沉积物、水、精矿 | 英国 | 开放派生栅格、授权点数据 | 原始点数据非 open-only |
| `brazil-sgb-geochemistry` | 岩石、土壤、沉积物、水、精矿 | 巴西 | ArcGIS FeatureServer、项目 ZIP | 许可、字段、方法、重复关系 |
| `nz-petlab` | 岩石、矿物、沉积物 | 新西兰及部分全球馆藏 | 开放查询、注册后导出 | 导出条款、动态版本、引用去重 |
| `earthchem-library` | 全介质发现 | 全球 DOI 仓库 | 检索和原始文件下载 | 逐数据集许可/schema/hash，不是统一数据集 |
| `geotraces-idp2025` | 海水 | 全球海洋航次 | BODC PDL 元数据/异步归档、WebODV 子集 | DOI、许可和产品元数据已核实；归档仍未准备完成，文件清单、字段映射、贡献者引用待验收 |
| `glorich` | 河水 | 全球河流 | PANGAEA DOI 批量包 | CC BY-NC-SA，不进入当前 open-only 生产 |
| `eea-waterbase` | 水、沉积物 | 欧洲 | CSV 下载与筛选 | 动态版本、国家方法差异、具体许可标识 |

### 本轮最重要的判断

- 沉积物候选从少数发现线索扩展到欧洲、加拿大、澳大利亚、英国、巴西、美国和 DOI 仓库入口，但仍无批准来源；
- 水体已区分河流、一般水质、欧洲报告水体和全球海洋航次，不能把它们混成一种介质；
- `geotraces-idp2025` 同时具备固定版本、DOI、CC BY 4.0 和质量控制说明；BODC 异步归档在本轮仍为 `notready`，不能提前声称文件与变量已经验收；
- `glorich` 很大但带 NC 限制，`bgs-gbase` 原始点数据需单独授权；两者保留用于覆盖判断，不参与 open-only 自动路由；
- `earthchem-library` 和 Water Quality Portal 是发现/聚合入口，生产数据必须保留并去重上游数据集与提供者。

## M6 第三轮新增候选

本轮新增 10 个入口，候选目录由 22 个增至 32 个，重点补海洋/湖泊档案和欧洲、亚洲国家机构。生产批准来源仍只有两个。

| 来源 | 介质 | 范围 | 当前可见接口 | 当前判断与主要阻断项 |
|---|---|---|---|---|
| `noaa-ncei-marine-geology` | 岩石、沉积物 | 全球海洋与湖床馆藏 | NCEI 检索/地图/服务、IMLGS ERDDAP | 档案含数值文件，但 IMLGS 本身主要是样品目录；必须逐原始数据集接入 |
| `pangaea-repository` | 四类介质发现 | 全球 DOI 仓库 | 高级检索、DOI 元数据和逐数据集文件 | 逐 DOI 核对许可、schema、hash、方法和上游项目，仓库不算独立证据 |
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
- 新增候选提升的是“去哪里找”的全面性，不改变沉积物、水体仍无 approved 来源的事实；
- `source_discovery_scope.json` 按区域记录尚未完成的检索，亚洲、非洲、南美及州/省级调查仍是明显缺口；发现状态继续为 `in_progress`、`saturated=false`。

## M7 首批逐源复核

详细证据、hash、记录对账和阻断项见 `source-verification-report.md`。

- `norway-marchem` 的公开 API 已能稳定返回目标元素，但当前响应是带生成时间的动态 ZIP，不是已固定 DOI 的不可变发布；
- MarChem 本次导出有 1,070 个物理数据行、880 个不同样品。190 个样品因两个参数组而重复出现，但每个样品只有一行含目标元素；适配器必须按参数和批次展开，不能按行计样品；
- 四个目标元素均为干重 `mg/kg`，保留 `<` 删失值；方法是部分硝酸消解，不代表总量；目标方法元数据中同时存在 accredited 和 not-accredited 批次；
- 已准备 30 条分层机器抽样，人工回看仍为 pending，因此没有把来源改为 approved；
- `geotraces-idp2025` 的 DOI、CC BY 4.0、产品范围、五个数据包和 QC 描述已核实；BODC 归档仍在准备，实际文件和变量级验收继续等待。

## 路由示例

```bash
python scripts/source_router.py \
  --request request.json \
  --output route_result.json
```

路由器只会自动选择 `production_eligible=true` 的来源。其余匹配来源进入 `review_sources`，并显示阻断原因。只要目录发现尚未饱和，缺少来源就保持 `unknown`，不会提前写成 `uncovered`。
