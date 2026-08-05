# 公开地球化学数据源路由

核对日期：2026-08-05。端点和许可可能变化；每次运行重新记录访问日期和实际响应。

## 优先级

按“官方结构化数据库 → DOI 数据仓储 → 论文补充材料 → 正文表格”的顺序选择。搜索摘要只用于发现来源。

| 来源 | 适合介质 | 入口 | 使用条件与限制 |
|---|---|---|---|
| USGS National Geochemical Database | rock/soil/sediment/mineral/concentrate | `https://www.usgs.gov/centers/gggsc/science/national-geochemical-database` | 政府来源；具体数据发布可能用不同 legacy qualifier 编码，逐数据集读取元数据 |
| EarthChem Portal | rock 与文献汇编 | `https://earthchem.org/portal` | 联邦检索 PetDB、GEOROC 等；保留原数据库、样品和文献引用；不要把聚合站当唯一证据 |
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

### `usgs-conus-soil`

- 数据集：Geochemical and mineralogical data for soils of the conterminous United States；
- DOI：`10.3133/ds801`；
- 当前冻结版本：Data Series 801，2013 release；
- 内容：4,857 个站点，分别提供 0–5 cm、A horizon、C horizon/deep 三个制表符文本文件；
- 许可：USGS 制作的数据属于美国公有领域，但仍保留建议引用；
- 获取：USGS Publications Warehouse 的三个直接 HTTPS 文件；
- 校验：注册表中的 SHA-256 是 2026-08-05 从官方 URL 观测所得，不冒充发布方 checksum；每次下载仍记录响应元数据和实际 SHA-256；
- 科学边界：三种土层不得静默合并；legacy qualifier 和单位必须按该数据集自己的元数据解码。

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
- 要求 HTTPS、超时、有限重试、最大字节、内容类型和响应形状检查。
- 优先使用发布方给出的 SHA-256；否则首次下载计算哈希并在 manifest 标为 `observed`，不能冒充发布方校验和。
- 压缩包先检查成员路径、总展开大小和成员数，避免路径穿越和压缩炸弹。
- 下载后记录服务端过滤、本地过滤、预期记录数、实际记录数和任何截断。

完成 D2 标准化后，用证据打包器生成来源清单并绑定置信度报告：

```bash
python scripts/build_evidence_bundle.py \
  --input INPUT.csv \
  --database OUTPUT/geochemistry.csv \
  --confidence-report OUTPUT/confidence_report.json \
  --output OUTPUT/source_manifest.json
```

该步骤只验证并打包置信度版本、输入哈希和报告哈希，不改变 D2 的置信度算法或数值。

## 科研使用与仓库存储边界

MIT 只覆盖本仓库原创代码和文档，不覆盖外部数据。本项目使用第三方数据开展科研查询和分析，不制作原数据库镜像。科研使用条件不明时先保存公开元数据和检索说明；允许科研使用的完整原始文件进入本地只读缓存，不提交 Git，比赛交付保存标准化科研结果、地图、引用和证据说明。
