# 公开地球化学数据源路由

核对日期：2026-08-16。端点和使用条件可能变化；每次运行重新记录访问日期和实际响应。

## 优先级

按“官方结构化数据库 → DOI 数据仓储 → 论文补充材料 → 正文表格”的顺序选择。搜索摘要只用于发现来源。

| 来源 | 适合介质 | 入口 | 使用条件与限制 |
|---|---|---|---|
| USGS National Geochemical Database | rock/soil/sediment/mineral/concentrate | `https://www.usgs.gov/centers/gggsc/science/national-geochemical-database` | 政府来源；具体数据发布可能用不同 legacy qualifier 编码，逐数据集读取元数据 |
| EarthChem Portal | rock 与文献汇编 | `https://earthchem.org/data-access/overview` | 联邦检索 PetDB、GEOROC 等；保留原数据库、样品和文献引用；不要把聚合站当唯一证据 |
| EarthChem developer resources | 结构化服务 | `https://earthchem.org/resources/developers` | 使用文档化 WFS/XML；验证 schema、计数和服务版本 |
| GEMStat open archive | water | `https://doi.org/10.5281/zenodo.18459694` | 已冻结 v3/CC BY 4.0；按 ZIP byte range 只取得 As 和必需元数据，保留贡献者、分相、方法、质量和删失语义 |
| GEMStat portal | water | `https://gemstat.org/data-gemstat/data-portal/` | 门户下载可能要求联系信息或限制站点数；不要自动绕过表单；受限批次不再分发 |
| Macrostrat | 地质背景 | `https://macrostrat.org/` | 数据通常 CC BY 4.0；同时引用 API 返回的原始地图来源和 source ID；记录比例尺与边界不确定性 |
| Macrostrat API docs | 点位地质匹配 | `https://dev.macrostrat.org/docs` | API 版本快速演进；固定实际路由和响应字段，不凭记忆构造端点 |
| GLiM 0.5° raster | 全球表层岩性筛查 | `https://doi.org/10.1594/PANGAEA.788537` | CC BY 3.0；D2 可执行 hash 固定的 point-in-cell，必须标注 0.5° 粗分辨率且不得冒充场地级地层 |

## MVP 冻结数据源

机器可读的版本、文件、校验和、许可和引用信息位于
`../assets/source_manifest.json`。这里的 `source_manifest.json` 是 D1 的**数据源注册表**；运行输出中的同名文件是记录级证据包，两者不得混用。

### `georoc-archaean`

- 数据集：GEOROC Compilation: Archaean Cratons；
- DOI：`10.25625/1KRR1P`；
- 当前冻结版本：12.0，发布时间 2026-06-11，数据生成日期 2026-06-01；
- 内容：按克拉通分组的 28 个 CSV，总展开体积 31,696,168 字节；
- 许可：CC BY-SA 4.0；
- 获取：优先使用 GRO.data Dataverse 的 versioned dataset API；若整包端点不可用，则自动退回同一版本、同一数据集下的 28 个 member persistent-ID 官方端点，不转用镜像；
- 校验：动态 ZIP 本身不固定哈希；无论走整包还是成员回退，都必须验证完全相同的 28 个成员集合、文件名、大小、发布方 MD5 和必需字段，并为本次取得的每个成员另算 SHA-256。成员回退先写私有暂存目录，全部通过后才原子发布；
- 抽样：研究模式按发布方克拉通成员轮转后再应用逐元素上限，避免把按文件排序的前缀误当全球岩石分布；这只改进有限预算下的来源内部广度，不把 reported 坐标升级为 canonical；
- 区域适用性：发布方固定成员名 `NORTH_CHINA_CRATON` 与 `YANGTZE_BLOCK` 构成中国相关性的正向证据，路由器据此允许中国任务在线取得并逐记录筛选；它不是完整国家目录，不能据“未列出”排除其他国家，也不能代替 CRS、国界或位置精度证据；
- 科学边界：这是 GEOROC 预编译选择值，不是全部原始重复分析的无筛选拼接；结果必须保留数据集 DOI、版本、成员文件和 CITATIONS 字段。

### `georoc-convergent-margins`

- 数据集：GEOROC Compilation: Convergent Margins；
- DOI：`10.25625/PVFZCE`；
- 当前冻结版本：12.0，发布时间 2026-06-11，数据生成日期 2026-06-01；
- 内容：按汇聚边缘弧/带分组的 46 个 CSV，总展开体积 134,730,702 字节；155,811 条物理行、177,217 条 As/Cu/Ni/Zn 目标观测（As 5,681、Cu 44,592、Ni 75,685、Zn 51,259），125,035 行为精确点坐标；
- 许可：CC BY-SA 4.0；
- 获取：与 `georoc-archaean` 相同的 versioned dataset API 整包下载加 46 个 member persistent-ID 官方端点回退，适配器复用同一实现（`GeorocConvergentMarginsAdapter`）；
- 校验：动态 ZIP 不固定哈希；验证完全相同的 46 个成员集合、文件名、大小、发布方 MD5 和必需字段，并为每个成员另算 SHA-256（见 `fixtures/candidate-audits/georoc-convergent-margins-20260819T093000Z.json`，2026-08-19 实测在线取得并全部通过）；
- 区域适用性：发布方固定成员名 `KOHISTAN-LADAKH_TERRANE_OR_GANGDISE_BELT`（冈底斯带，藏南，1,306 行）构成中国相关性正向证据；`KAMCHATKA_ARC`、`KURILE_ARC`、`OKHOTSK-CHUKOTKA_ARC`、`SIKHOTE-ALIN-SAKHALIN_ARC`、`UDA-MURGAL_ARC`（合计 11,701 行）构成俄罗斯相关性正向证据；安第斯弧三个分卷 25,760 行补南美；成员名跨政治边界（Kohistan-Ladakh 同时覆盖巴基斯坦与印度），国家归属必须由记录坐标与下游审查决定，不得凭成员文件名推断；
- 科学边界：GEOROC 预编译选择值，与 `georoc-archaean`、`georoc-antarctica-intraplate` 同谱系（`georoc-compilation`），不构成独立岩石来源家族；结果必须保留数据集 DOI、版本、成员文件和 CITATIONS 字段；坐标保留 reported-only，不凭数值格式升级 EPSG:4326。

### `earthchem-dehailonggang-rock`

- 数据集：The bulk-rock composition of the Dehailonggang volcanic-plutonic complex of the East Kunlun Orogen, northern Tibet Plateau；
- DOI/版本：`10.60520/IEDA/113338`，EarthChem Library dataset 3338 version 1.0 (2024)；
- 内容：15 个 whole-rock 样品，Cr/Cu/Ni/Pb/Zn 共 75 条目标观测；ICP-MS、Agilent 7700e 和实验室信息来自同一 workbook 的方法表；
- 许可：CC BY-SA 4.0；
- 获取与校验：固定官方 POST 下载参数；ZIP、四个成员、主 workbook 行数与逐成员 SHA-256 全部固定，主 workbook SHA-256 为 `ccdc26ee169919144f7d1c8726eb8075c99b4d9cba30d249906f79c045a12ca7`；
- 科学边界：两个坐标对未声明 CRS 或位置精度，故保留 reported-only，绝不冒充 WGS84；这是局地杂岩体，不代表中国西部或全国岩石覆盖。
- 坐标边界：经审查的公开页面/元数据说明坐标采用十进制度，但未充分声明所有历史记录的统一 datum；D1 保留 reported coordinate，不能仅凭数值范围标记 EPSG:4326。缺 datum 时 canonical 坐标留空并等待人工核验，也不得对其执行 WGS84 bbox 筛选。

### `4tu-northern-china-sediment`

- 数据集：北方中国河流/冲积沉积物以及黄土—古土壤多元素数据；DOI `10.4121/uuid:6cb0bf79-7467-4e78-a531-cc91655d9fd0`；CC0；
- 内容：867 个物理样品、799 个发布坐标对，As/Cr/Cu/Hg/Ni/Pb/Zn 各 867 条，共 6,069 条观测；表层样点明确分到准噶尔、塔里木、柴达木、河套、阿拉善、青藏高原东部和东北沙地，另含黄土高原黄土/古土壤；
- 获取：Figshare 官方 metadata API 与三个固定文件 ID；workbook、README、KML 的字节数、发布方 MD5 和本地 SHA-256 全部登记，三者必须同时通过才原子发布；
- 方法与 QC：README 证据把 As 绑定到王水 + HG-AFS、Cr 绑定到熔片 XRF、Cu/Ni/Pb/Zn 绑定到四酸 + ICP-MS，并报告 3% 野外重复、盲重复和标准物质；Hg 方法没有充分证据，保持缺失；
- 空间与地质边界：发布方分区是采样区域/沉积环境背景，不冒充点位地质单元。来源未声明 CRS/datum 和位置精度，因此只保留 reported 坐标；可用于可追溯浏览和非空间标准库，但不得计入 canonical WGS84 空间充分性或空间异常统计；
- 校验入口：`../fixtures/candidate-audits/4tu-northern-china-sediment-20260816T000000Z.json`、`../assets/source_manifest.json` 与逐源 demo 的三文件 hash 链。

### `usgs-conus-soil`

- 数据集：Geochemical and mineralogical data for soils of the conterminous United States；
- DOI：`10.3133/ds801`；
- 当前冻结版本：Data Series 801，2013 release；
- 内容：4,857 个站点，分别提供 0–5 cm、A horizon、C horizon/deep 三个制表符文本文件；
- 许可：USGS 制作的数据属于美国公有领域，但仍保留建议引用；
- 获取：USGS Publications Warehouse 的三个直接 HTTPS 文件；
- 校验：注册表中的 SHA-256 是 2026-08-05 从官方 URL 观测所得，不冒充发布方 checksum；每次下载仍记录响应元数据和实际 SHA-256；
- 科学边界：三种土层不得静默合并；legacy qualifier 和单位必须按该数据集自己的元数据解码。
- 元数据解码：Appendix 5 声明坐标为 WGS 84；As 使用 HG-AAS（sodium peroxide + sodium hydroxide fusion），Cu/Ni/Zn 使用 ICP-AES（near-total HCl-HNO3-HClO4-HF digestion）。`<`/`<=` 必须同时保留原值、qualifier 和 detection limit，不能插补。

### `pangaea-north-africa-soil`

- 数据集：Chemical compositions of deflatable soil fractions from North Africa；
- DOI：具体表 DOI `10.1594/PANGAEA.949903`，父数据包 DOI `10.1594/PANGAEA.949906`；
- 当前冻结版本：2022-10-25，直接数据成员 `Table_S5.tab`；
- 许可：CC BY 4.0；
- 获取：PANGAEA DOI 的 `?format=textfile` 官方 TSV 响应；
- 校验：30,336 bytes，SHA-256 `de402b7f469c2d7c182abb285e624f2a1e6b1d00ec66e3dc2fae7ec9c8e4a485`；43 个源行、48 个元素字段、As/Cr/Cu/Ni/Pb/Zn 各 43 条；
- 科学边界：可风蚀细粒组分经 HF-HNO3 消解和 ICP-MS 分析，不代表北非连续覆盖或通用 bulk-soil 总量；保留发布方地点文字，边境样点不按坐标猜国家。

### `japan-gsj-geochemical-map`

- 数据集：GSJ Geochemical Map of Japan 全国河流沉积物样点与浓度表；
- 当前冻结版本：`samplejoho.csv` 更新 2024-02-20，`noudo.csv` 更新 2007-01-10；
- 使用条件：GSJ 说明其网站研究成果依日本政府标准利用规约 2.0 使用并要求署名；第三方内容排除在外；
- 获取：GSJ 官方下载页的两个 CSV，使用 CP932/Shift-JIS 解码；
- 校验：样点表 334,302 bytes / SHA-256 `9fdb58d86ad48eae564291421a0dad2b6f8a4f243d3e89d90016f3c61b0b521c`；浓度表 1,198,951 bytes / SHA-256 `0dbd2beae356adc45b762d50a9aa06ad556fd3ea004d427e369837bedda05671`；按出现序号连接得到 3,024/3,024 行，零漏连；
- 坐标与单位：原始坐标系 JGD2000（EPSG:4612）；Hg 为 ppb，其他登记痕量元素为 ppm；
- 科学边界：本适配器只覆盖细粒河流沉积物，不把海洋沉积物、表层土壤或 WMS 派生图层混入；源 CSV 没有逐行分析方法、检出限和 QC，必须显式保留缺失。

### `geotraces-idp2025`

- 数据集：GEOTRACES Intermediate Data Product 2025，离散海水集合；
- DOI：`10.5285/42c92148-8d03-8be6-e063-7086abc09f0c`；
- 许可：CC BY 4.0，并遵守 Fair Data Use 的数据集、贡献者和原始文献引用要求；
- 获取：官方 WebODV 提取服务；运行 `scripts/acquire_geotraces_idp2025.py --accept-fair-use`，冻结选择参数、cookies/CSRF 会话内的响应、归档 hash 和全部成员；
- 当前快照：只选择深度和 dissolved Cu/Ni/Zn；69,704 个样品深度行、39,327 条非空目标观测；
- 校验：验证 903,710-byte ZIP 的 SHA-256、242 个成员和主 ODV 文件 hash；`scripts/audit_geotraces_snapshot.py` 重算行数、变量、QC 和空间/深度覆盖；
- 2026-08-19 重观测：WebODV 导出器的 `Creator`/`Software` 头字段随服务部署漂移（worker 容器主机名与构建号），导致 2026-08-05 注册快照的逐字节校验失败；适配器规范化已扩展到 `CreateTime`/`View`/`Creator`/`Software` 四个易变字段，扩展规范化后 2026-08-05 归档与 2026-08-19 在线导出产生相同 canonical payload hash `96663b85…07f5eb`，科学负载证实未变；manifest 已按最新观测重钉；
- 科学边界：`nmol/kg` 原样保留，不与 `ug/L` 静默换算；航次点不是规则全球覆盖；变量表没有 As，水体 As 请求必须路由到其他来源。

### `gemstat-open-archive`

- 数据集：UNEP GEMS/Water Global Freshwater Quality Archive v3；
- DOI：版本 DOI `10.5281/zenodo.18459694`，概念 DOI `10.5281/zenodo.13881899`；
- 许可：CC BY 4.0，保留 archive 引用和版本 DOI；
- 获取：`scripts/acquire_gemstat_arsenic.py --accept-cc-by` 使用官方 ZIP 的精确 HTTP byte range，只物化 `Arsenic.csv`、站点、参数、方法和 README 五个成员；
- 校验：每个 range 校验压缩字节 SHA-256、本地 ZIP header、解压 CRC、展开大小和展开内容 SHA-256；完整 201,278,791-byte ZIP 的发布方 MD5 只记录为发布方声明，不冒充本机完整校验；
- 对账：492,999 条 As 观测、15,621 个站点、33 个国家，覆盖 dissolved/suspended/total 三种分相和河流、湖泊、地下水、水库、湿地五类站点；
- 质量边界：保留 `<`/`>`、Good/Fair/Unknown/Pending review/Suspect、5,655 条额外精确重复观测和所有源行定位；演示排除方法代码 0、Pending review、Suspect、负哨兵和极端值；
- 覆盖边界：它是各国自愿提交的不均匀淡水汇编，不是规则全球网格。As 与 GEOTRACES 的海水 Cu/Ni/Zn 共同补齐登记目标，但不能把淡水和海水静默合并为同一背景。

### FOREGS 六个独立来源

- `foregs-topsoil`、`foregs-subsoil`、`foregs-humus`、`foregs-stream-water`、`foregs-stream-sediment`、`foregs-floodplain-sediment` 分别注册，不能退化成一个无法说明介质和方法的 `foregs-europe` 适配器；
- 科学发布：Salminen et al. (2005)《Geochemical Atlas of Europe, Part 1》；固定发布方文件快照：2026-03-03；
- 文件：六个官方 ZIP 均固定字节数和 SHA-256，解析 22 个元素分析 CSV、16,364 个物理行和 48,504 条 As/Cr/Cu/Hg/Ni/Pb/Zn 测定映射；
- 方法：土壤和沉积物同时保留 `total_selected` 与 `aqua_regia_leachable`；腐殖质为 4.5% HNO3 超声温和浸出；溪流水为 `<0.45 µm` 过滤溶解态；
- 使用条件：按发布方说明保留 Salminen et al. (2005) 引用和 EuroGeoSurveys/GTK copyright notice。本项目只作科研分析，不把完整归档提交 Git，也不推断宽泛的再分发许可；
- 检出限：CSV 第三行保存表级 DL，但没有逐行 `<` 限定符。适配器对恰好 `DL/2` 的数值只增加 `possible_upstream_dl_over_2_substitution` 证据警告，不自动标成删失或检出；
- 覆盖：平均约一个样点/4,700 km²，属于欧洲低密度大陆基线；坐标由各国坐标系转换用于大陆尺度展示，不能解释成欧洲每处有数据或本地调查精度；
- 传输：GTK 旧站的标准 HTTPS 证书验证当前失败，实际归档端点为官方 HTTP。该适配器仅对固定 `weppi.gtk.fi` URL 启用来源级例外，拒绝重定向，并在发布缓存前强制匹配登记 SHA-256；通用下载器仍保持 HTTPS-only。

### `afsis-phase-i-wet-chemistry`

- 数据集：AfSIS Phase I archived soil samples wet chemistry，官方 World Agroforestry Dataverse V2.0；
- DOI：`10.34725/DVN/66BFOB`；许可：CC BY 4.0；
- 获取：三个 `format=original` datafile 端点，分别为 847,634-byte CSV、21,024-byte variables XLSX 和 10,445-byte DL/QL XLSX；每个文件同时校验发布方 MD5、登记 SHA-256 和字节数；
- 对账：2,002 个唯一 SSN/RES.ID、18 个原国家标签、51 个 LDSF 站点、992 个 topsoil、1,010 个 subsoil、1,876 个完整坐标对和六元素共 12,012 条数值；
- 方法：风干土王水消解准全量；As 为 ICP-MS，Cr/Cu/Ni/Pb/Zn 为 ICP-OES；方法、单位、实验室、DL 和 QL 都从固定工作簿绑定到逐观测证据；
- 质量边界：126 个样品没有坐标；As/Cu/Pb 存在负数仪器结果；Pb 的大多数发布数值低于全局 DL。原数值保留并分级标记，不静默删除、不当作普通检出；
- 元数据边界：注册文件和相关论文没有明确 CRS；变量表把 `As.75` 描述成“Arsenic-78”，且变量表与相关论文的采样年份分别为 2009–2013 和 2009–2012。适配器保留冲突，不猜测修复；
- 命名边界：`SAfrica` 和 `Zimbambwe` 等发布方标签原样保留，规范名只写独立字段；18 个国家标签不代表均匀非洲覆盖。

### `tpdc-china-mountain-soil`

- 数据集：中国山地不同气候区土壤剖面多元素综合数据集；DOI `10.11888/Terre.tpdc.302620`；TPDC metadata UUID `2f4c2f30-166c-4a76-9b4a-74c98b4ca3b1`；
- 使用条件：TPDC 元数据返回 licence code `1`、`sharePolicy=A`、`shareType=online`；前端许可表把 code `1` 映射为 CC BY 4.0，使用时保留数据作者、数据 DOI 和 TPDC 署名；
- 获取：官方 metadata POST、文件清单 GET 和 file-ID POST 下载已验证；`Soil dataset.zip` 为 1,828,683 bytes，SHA-256 `8cf3189b44aad64b65cd213c0fd015d30df5f1c59676823846292f83baa1a84a`；
- 成员：`Soil dataset.xlsx`、`Soil bulk density.xlsx`、`Description of the dataset.docx` 三项均登记字节数和 SHA-256；完整第三方文件只进入本地缓存，不提交 Git；
- 对账：主表 1,314 条唯一“样品号 × 土层”记录，覆盖 30 座山地、166 个站点、O/A/C 三层；Cr/Cu/Ni/Pb/Zn 各 1,314 条，共 6,570 条目标测定，As/Hg 缺失；
- 背景字段：逐行有母岩类别、母岩组、土纲、土类、海拔、经纬度、气候和植被信息，适合验证 V4 样品类型、地质背景与环境上下文 schema；
- 方法：风干并过 2 mm 筛，HNO3-HF-HClO4 消解；Zn 用 ICP-AES，Cr/Cu/Ni/Pb 用 ICP-MS；论文报告空白、重复、GBW-07405、95%–105% 回收率和相应 RSD。工作簿没有逐行方法或检出限，因此这些事实只能以 publication scope 连接；
- 质量边界：元数据和文件未声明坐标 CRS；SN5、SN6、SN7 各有多个发布坐标对；单独 bulk-density 表能补 58 个主表缺失行，但同时有六个非空 BD 冲突和五个坐标冲突，必须保留双来源值和冲突标记，不能覆盖主表；
- 当前状态：canonical adapter 已注册并通过组件测试；40 条 per-source demo 与全量 6,570 条中国区域 fixture 切片（`fixtures/china/combined-v1`）均由该适配器生成。datum 未声明的 GPS 坐标保持 reported-only（canonical 留空，失败关闭），上图需 `--coordinate-mode reported` 并自动注入警示条；datum 证据审查记录在 `coordinate-policy-registry.json`。

### `zenodo-yangtze-yellow-river-sediment`（中国区域 fixture 来源）

- 数据集：Evaluation of Grain size, Amorphous Fe-Mn Oxides, and Chemical Weathering Effects on Geochemical Identification of the Yangtze River and Yellow River Sediments（Data Set S2）；DOI `10.5281/zenodo.7098563`；CC BY 4.0；
- 内容：93 个 HCl-/AC-残余粒级分离河流沉积物样品 × As/Cr/Cu/Ni/Pb/Zn = 558 条观测；`Data Set S2.xlsx` 76,596 bytes，SHA-256 `413f54f6…`（Zenodo 官方 `md5:f71702e1…`）；
- 单位证据：工作簿无单位行，构建器强制比对内嵌 BHVO-2/AGV-2/W-2/GSP-2 QC 块与认证 µg/g 值（容差 20%）后才接受 `ug/g`；
- 质量边界：不发布采样坐标，记录只入标准化数据库、不进任何地图层；HCl/AC 残余与粒级保持独立比较组；
- 登记范围：本来源只注册在中国区域 fixture（构建器 `scripts/build_china_demo.py`），不进入通用 source catalog 路由；完整登记、哈希与重建命令见 `references/china-fixture.md`。

### `pangaea-east-china-sea-clay`

- 数据集：Shao et al. (2016) 东海陆架、冲绳海槽 IODP 钻孔、长江与台湾河流黏土组分主微量元素表（Appendix A）；DOI `10.1594/PANGAEA.856762`（父数据集 `10.1594/PANGAEA.856763`）；CC BY 3.0；
- 内容：98 行 × 28 个带坐标事件，逐行 WGS84 经纬度；其中 8 个长江干流站位（CJ-01–08）与 3 个台湾河流站位为陆地河流沉积物，其余为东海陆架与 IODP 海洋钻孔；Cr/Cu/Pb/Zn 各 98 条、共 392 条目标测定（mg/kg，发布方注明原单位为 ppm）；不含 As；
- 获取：官方 `?format=textfile` 直链已验证；36,898 bytes，SHA-256 `b70b0d566d17d76c16e2bcad1f0ec176cca7c0efccf68243fb9ea28aac55d5e2`；完整发布表只进本地缓存，不提交 Git；
- 质量边界：每个物理样品有 Bulk 与酸浸 Residue 两行，测量基准分开登记、禁止平均合并；发布方把全部浓度参数方法标注为 X-ray diffraction (XRD)，按原样保留、不推断仪器或消解；
- 当前状态：canonical adapter 已注册并通过组件测试；32 条 per-source demo 由适配器生成；这是中国区域首个逐行 canonical 坐标的沉积物在线来源，与 TPDC、Zenodo 组成三条独立血缘。

### `pangaea-south-china-sea-sediment`

- 数据集：Wei et al. (2015) 南海不同沉积物岩芯微量元素表（Table 2）；DOI `10.1594/PANGAEA.855177`（父数据集 `10.1594/PANGAEA.855179`）；CC BY 3.0；
- 内容：44 个表层沉积物岩芯事件（4.07–20.60°N、105.28–120.16°E），逐行 WGS84 坐标；Cr/Cu/Ni/Pb/Zn 各 44 条、共 220 条 ICP-MS（Perkin-Elmer Elan 6000）测定；发布方已将原 ppm 单位归一为 mg/kg 并在字段名中注明；
- 获取：官方 `?format=textfile` 直链已验证；25,021 bytes，SHA-256 `703995078eaa849014e5075d357adaba5f33c76f95e349dc2329e8656047ea5d`；
- 质量边界：全部为海洋点位，陆地国家审计不得计入；消解细节表内未报告、不推断；
- 当前状态：canonical adapter 已注册并通过组件测试；40 条 per-source demo 由适配器生成；补强南海海域沉积物扇区覆盖。

### `pangaea-barents-c-horizon-soil`

- 数据集：Reimann (1998) Kola 生态地球化学 C 层土壤表；DOI `10.1594/PANGAEA.56227`（父数据集 `10.1594/PANGAEA.686641`）；CC BY 3.0；
- 内容：中央巴伦支地区（科拉半岛俄罗斯段、芬兰北部、挪威北部，约 66–71°N、22–34°E）606 个站位，逐行 WGS84 坐标；注册目标为王水提取套件：As（AAS-GF，检出限 0.1 mg/kg）、Cu/Zn（ICP-AES，0.5）、Pb（AAS-GF，0.2），共 2,419 条测定，其中 As 有 10 条低于检出限、保留 `<` 限定符；
- 获取：官方 `?format=textfile` 直链已验证；407,662 bytes，SHA-256 `e22093a40b9c68d25398f2322b68ae7af9b00e331483ae8a3927fc2c13be3d30`；
- 结构边界：发布表头存在同名重复列（不同分析方法），适配器按注册列索引解析并逐次核验列名前缀，任何列序变化都会失败关闭；平行的全量/NAA 列暂未注册；
- 科学边界：王水可提取浓度不是全量含量，比较时必须保留提取基准；覆盖范围仅为中央巴伦支地区，不得声明为全俄覆盖；
- 当前状态：canonical adapter 已注册并通过组件测试；32 条 per-source demo 由适配器生成；**这是注册表首条俄罗斯陆地血缘**，Loop 的 RUS 目标现在会路由本来源而不再要求从零发现；同族的腐殖质层与 B 层数据集仍在候选目录中待实现。

## D1 适配器和稳定 ID

`scripts/source_adapters.py` 冻结以下接口：

```text
discover(request) -> list[DatasetCandidate]
download(candidate, cache_dir, mode) -> list[DownloadedFile]
parse(files) -> Iterable[RawRecord]
provenance() -> SourceManifest entry
```

- `source_id` 使用注册表中的稳定短名，例如 `georoc-archaean`；
- `source_record_id` 对 `source_id + native_id + source_locator` 做 canonical SHA-256；
- `record_id` 对来源记录、原始分析物、原始值、原始单位和重复序号做 canonical SHA-256；
- ID 不包含缓存路径、输出路径、下载时间或当前机器信息，因此重复运行保持稳定；
- D1 只生成原始记录和来源定位，不在适配器里进行 D2 的单位标准化、异常判断或置信度计算。

## 来源选择门

1. 先判断介质、区域、元素、时间和 measurement basis。
2. 优先能服务端按区域/元素过滤、提供方法和来源定位的结构化发布。
3. 单独检查是否允许本次科研分析、是否要求署名、限定非商业科研或需要申请；不把科研使用条件并入科学证据分。
4. 同一记录经聚合平台转载时，保留聚合来源和原始提供者两层定位。
5. 数据版本或字段字典缺失时标记 `needs_human_review`，不要猜 qualifier。

## 下载验证

- 只下载明确的数据文件 URL，不把 HTML 搜索结果保存成 CSV。
- 通用下载要求 HTTPS、超时、有限重试、最大字节、内容类型和响应形状检查。若发布方历史端点只有 HTTP，必须在单个适配器中限定固定主机/URL、拒绝重定向并强制预登记 SHA-256，不得放宽通用下载器。
- 优先使用发布方给出的 SHA-256；否则首次下载计算哈希并在 manifest 标为 `observed`，不能冒充发布方校验和。
- 压缩包先检查成员路径、总展开大小和成员数，避免路径穿越和压缩炸弹。
- 下载后记录服务端过滤、本地过滤、预期记录数、实际记录数和任何截断。

完成 D2 标准化后，用证据打包器生成来源清单并绑定置信度报告：

```bash
python scripts/build_evidence_bundle.py \
  --input INPUT.csv \
  --database OUTPUT/geochemistry.csv \
  --confidence-report OUTPUT/confidence_report.json \
  --evidence-jsonl sources.jsonl \
  --acquisition-manifest run_manifest.json \
  --output OUTPUT/source_manifest.json
```

该步骤要求 sidecar 与 canonical `record_id` 集合完全一致，校验对应来源字段，并绑定 CSV、sidecar、acquisition manifest 与置信度报告哈希。该步骤不改变 D2 的置信度算法或数值。

## 科研使用与仓库存储边界

MIT 只覆盖本仓库原创代码和文档，不覆盖外部数据。本项目使用第三方数据开展科研查询和分析，不制作原数据库镜像。科研使用条件不明时先保存公开元数据和检索说明；允许科研使用的完整原始文件进入本地只读缓存，不提交 Git，比赛交付保存标准化科研结果、地图、引用和证据说明。
