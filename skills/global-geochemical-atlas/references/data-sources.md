# 公开地球化学数据源路由

核对日期：2026-08-06。端点和使用条件可能变化；每次运行重新记录访问日期和实际响应。

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

## MVP 冻结数据源

机器可读的版本、文件、校验和、许可和引用信息位于
`../assets/source_manifest.json`。这里的 `source_manifest.json` 是 D1 的**数据源注册表**；运行输出中的同名文件是记录级证据包，两者不得混用。

### `georoc-archaean`

- 数据集：GEOROC Compilation: Archaean Cratons；
- DOI：`10.25625/1KRR1P`；
- 当前冻结版本：12.0，发布时间 2026-06-11，数据生成日期 2026-06-01；
- 内容：按克拉通分组的 28 个 CSV，总展开体积 31,696,168 字节；
- 许可：CC BY-SA 4.0；
- 获取：GRO.data Dataverse 的 versioned dataset API；
- 校验：动态 ZIP 本身不固定哈希，必须验证 28 个成员的文件名、大小和发布方 MD5，并为本次取得的 ZIP 和成员另算 SHA-256；
- 科学边界：这是 GEOROC 预编译选择值，不是全部原始重复分析的无筛选拼接；结果必须保留数据集 DOI、版本、成员文件和 CITATIONS 字段。
- 坐标边界：经审查的公开页面/元数据说明坐标采用十进制度，但未充分声明所有历史记录的统一 datum；D1 保留 reported coordinate，不能仅凭数值范围标记 EPSG:4326。缺 datum 时 canonical 坐标留空并等待人工核验，也不得对其执行 WGS84 bbox 筛选。

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
