# 公开地球化学数据源路由

核对日期：2026-08-06。端点和许可可能变化；每次运行重新记录访问日期和实际响应。

## 优先级

按“官方结构化数据库 → DOI 数据仓储 → 论文补充材料 → 正文表格”的顺序选择。搜索摘要只用于发现来源。

| 来源 | 适合介质 | 入口 | 使用条件与限制 |
|---|---|---|---|
| USGS National Geochemical Database | rock/soil/sediment/mineral/concentrate | `https://www.usgs.gov/centers/gggsc/science/national-geochemical-database` | 政府来源；具体数据发布可能用不同 legacy qualifier 编码，逐数据集读取元数据 |
| EarthChem Portal | rock 与文献汇编 | `https://earthchem.org/data-access/overview` | 联邦检索 PetDB、GEOROC 等；保留原数据库、样品和文献引用；不要把聚合站当唯一证据 |
| EarthChem developer resources | 结构化服务 | `https://earthchem.org/resources/developers` | 使用文档化 WFS/XML；验证 schema、计数和服务版本 |
| GEMStat open archive | water | `https://doi.org/10.5281/zenodo.13881899` | 只使用明确开放批次；通常 CC BY 4.0，并按数据提供者要求署名；大文件先按范围设计本地过滤 |
| GEMStat portal | water | `https://gemstat.org/data-gemstat/data-portal/` | 门户下载可能要求联系信息或限制站点数；不要自动绕过表单；受限批次不再分发 |
| Macrostrat | 地质背景 | `https://macrostrat.org/` | 数据通常 CC BY 4.0；同时引用 API 返回的原始地图来源和 source ID；记录比例尺与边界不确定性 |
| Macrostrat API docs | 点位地质匹配 | `https://dev.macrostrat.org/docs` | API 版本快速演进；固定实际路由和响应字段，不凭记忆构造端点 |
| GLiM | 全球主导表层岩性筛查 | `https://doi.org/10.1594/PANGAEA.788537` | CC BY 3.0；0.5° 栅格只作区域筛查背景，不冒充场地级地层或成因证据 |

## 七洲四介质补充路由

以下来源用于填补结构性覆盖空洞。它们证明工作流能处理对应洲—介质的真实数据，不证明国家级或全球代表性；
每次运行仍按请求区域、元素、许可和方法可比性筛选。

| 区域/介质 | 官方或 DOI 来源 | 方法与接口要点 |
|---|---|---|
| 非洲 sediment | PANGAEA `10.1594/PANGAEA.880617` | 坐标在 Event 元数据；关联论文 `10.1029/2017GC007228` 记录 bulk XRF 方法 |
| 非洲 water | PANGAEA `10.1594/PANGAEA.947275` | 溶解态 Ni/Cu/Zn/Pb 为 `nmol/L`，保留标准差和 GEOTRACES QF |
| 南美 soil | SGB/CPRM `https://rigeo.sgb.gov.br/handle/doc/11157` 与官方 FeatureServer layer 5 | 化学表按 `NUM_CAMPO` 连接官方点；保留 ND、`<`、`>` 与光学发射方法 |
| 南美 sediment | SGB/CPRM `https://rigeo.sgb.gov.br/handle/doc/11268` | 水系沉积物，aqua regia + ICP-MS，原始逗号小数和限定符不得丢失 |
| 大洋洲 soil | PANGAEA `10.1594/PANGAEA.935591` | 只把 `Samp type=Soil` 进入 soil；街尘和沉积物不改名混入 |
| 大洋洲 water | Geoscience Australia `10.11636/Record.2020.015` | 多 sheet 地下水；逐分析物读取单位、实验室、方法、过滤尺度和 LOD |
| 南极洲 soil | PANGAEA `10.1594/PANGAEA.816759` | 1:5 soil-water extract；不能与 total/near-total 固体浓度混成同一 background |
| 南极洲 sediment | Mendeley Data `10.17632/cfnhps54h7.1` | `<63 µm`、预浸取/消解、ICP-QQQ；关联论文 `10.1016/j.chemgeo.2020.119649` |
| 南极洲 water | BCO-DMO `10.26008/1912/bco-dmo.877466.1` | 总溶解 Ni/Cu/Zn，`nmol/L` 与 GEOTRACES flags；水样不连接陆地岩性 |

下载器必须固定直接数据 URL、文件字节数和 SHA-256；动态 ArcGIS 查询还要冻结完整参数、返回空间参考、
记录数与取得日期。仓库 `evaluation/stage_benchmark/contracts/completion-sources.json` 给出一套经过验证的测试快照，
它是评测契约，不是完整全球数据库镜像。

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
  --evidence-jsonl sources.jsonl \
  --acquisition-manifest run_manifest.json \
  --output OUTPUT/source_manifest.json
```

该步骤要求 sidecar 与 canonical `record_id` 集合完全一致，校验对应来源字段，并绑定 CSV、sidecar、acquisition manifest 与置信度报告哈希。该步骤不改变 D2 的置信度算法或数值。

## 科研使用与仓库存储边界

MIT 只覆盖本仓库原创代码和文档，不覆盖外部数据。本项目使用第三方数据开展科研查询和分析，不制作原数据库镜像。科研使用条件不明时先保存公开元数据和检索说明；允许科研使用的完整原始文件进入本地只读缓存，不提交 Git，比赛交付保存标准化科研结果、地图、引用和证据说明。
