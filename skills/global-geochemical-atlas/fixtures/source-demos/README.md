# 真实来源的最小演示切片

这些文件用于验证 D1 → D2 → D3 流水线，不是统计代表性样本，不支持区域或全球科学解释。

每个目录包含：

- `demo_input.csv`：D1 交给 D2 的长表输入，保留原值、原单位、来源和许可；
- `sources.jsonl`：逐观测证据链，链接源文件、源行、文件 hash、数据集 DOI/版本和原始引用；
- `run_manifest.json`：固定生成参数、输入文件 hash、记录数、输出 hash 和科学限制。

## GEOROC demo

目录：`georoc-archaean/`。

- 来源：GEOROC Compilation: Archaean Cratons，DOI `10.25625/1KRR1P`，版本 12.0；
- 许可：CC BY-SA 4.0；
- 内容：按源文件顺序选择 whole-rock、精确点坐标记录，并平衡抽取 As、Cu、Ni、Zn 各 12 条；
- 边界：数值是 GEOROC 预编译选择值，不代表全部重复测量。

## USGS demo

目录：`usgs-conus-soil/`。

- 来源：USGS Data Series 801，DOI `10.3133/ds801`；
- 权利状态：USGS 制作的数据属于美国公有领域，仍保留建议引用；
- 内容：0–5 cm、A horizon、C horizon 各选择 4 个源样品，每个样品保留 As、Cu、Ni、Zn；
- 边界：三个土层保持可区分，legacy qualifier 和科学标准化由 D2 处理。

## PANGAEA 北非土壤 demo

目录：`pangaea-north-africa-soil/`。

- 来源：PANGAEA 具体子数据集 DOI `10.1594/PANGAEA.949903`，不是 PANGAEA 通用入口；
- 许可：CC BY 4.0；
- 内容：43 个离散样点中选择 12 个源行，平衡保留 As、Cu、Ni、Zn 各 12 条，共 48 条；完整适配器另对账六个登记目标元素各 43 条；
- 方法边界：样品是可风蚀细粒土壤组分，使用 HF-HNO3 消解和 ICP-MS；不能与不同粒级、不同消解的 bulk-soil 调查静默合并；
- 空间边界：保留发布方地点文字，边境样点不按坐标强制归属国家。

## MarChem demo

目录：`norway-marchem/`。

- 来源：MarChem 挪威海域沉积物动态 API 快照 `norway-marchem:2026-08-05T10:27:11Z:be888784ee2e`；
- 许可：CC BY 4.0，保留来源署名；
- 内容：从已经准备的 30 条分层复核记录中保留 28 条含目标元素的源行，生成 As、Cu、Ni、Zn 各 28 条，共 112 条观测；
- 方法边界：所有值均为干重 `mg/kg` 的部分硝酸消解结果，不代表总含量；批次认可状态和 LLQ 按观测保留；
- 关系边界：完整快照的 1,070 行对应 880 个样品，fixture 不把第二参数组产生的附加行误算成新样品。

## GSJ 日本河流沉积物 demo

目录：`japan-gsj-geochemical-map/`。

- 来源：GSJ 日本全国地球化学图的 `samplejoho.csv` 和 `noudo.csv` 固定文件对；
- 使用条件：GSJ 网站研究成果按日本政府标准利用规约 2.0 使用并署名，第三方内容仍需单独核对；
- 内容：3,024 个细粒河流沉积物源行中选择 12 个样品，平衡生成 As、Cu、Ni、Zn 各 12 条，共 48 条；
- 编码和坐标：两表按 CP932/Shift-JIS 解码，原始坐标系是 JGD2000；演示按 WGS84 展示并设置 20 m 不确定度下限；
- 关系边界：重复样品号 `78013` 按两表中的出现序号配对，绝不使用会覆盖重复键的普通字典连接；Hg 为 ppb，其他登记痕量元素为 ppm；源 CSV 没有逐行方法、检出限或 QC 字段，适配器不补猜。

## GEOTRACES demo

目录：`geotraces-idp2025/`。

- 来源：GEOTRACES IDP2025 官方 WebODV 离散海水快照 `geotraces-idp2025:IDP2025:a61f441e5ae2`；
- 许可：CC BY 4.0，并遵守 Fair Data Use 的数据集和原贡献者引用要求；
- 内容：从 QC 1/2、坐标和深度有效的 dissolved 观测中平衡选择 Cu、Ni、Zn 各 16 条，共 48 条；
- 单位边界：原始 `nmol/kg` 保持不变；没有明确元素原子量和海水密度时不换算为 `ug/L`；
- 方法边界：39,327 条目标观测均连接到航次×元素 contributor metadata；只有唯一 BODC 方法记录时才赋值，多候选记录只保留候选集，不猜成行级方法；
- 覆盖边界：样点来自海洋航次，不是规则全球网格；官方离散海水变量表没有 As，必须用其他水体来源补齐。

## GEMStat demo

目录：`gemstat-open-archive/`。

- 来源：UNEP GEMS/Water Global Freshwater Quality Archive v3，版本 DOI `10.5281/zenodo.18459694`；
- 许可：CC BY 4.0，保留 archive 引用；
- 内容：只从 Good/Fair、方法代码明确、非负且非极端的记录中为 As、Cr、Cu、Hg、Ni、Pb、Zn 各选择 8 条，共 56 条；dissolved、extractable、suspended、total 分相和 `<` 删失值保持独立；
- 质量边界：全量 3,739,180 条七元素观测中只有 279,225 条方法代码明确；Pending review、Suspect、重复、异常哨兵和 1,836,306 条删失观测仍保留在全量适配器与审计报告中；
- 覆盖边界：七元素子集涉及 35 个贡献国家、17,248 个站点和 689,291 个物理采样事件，不是规则全球淡水网格，也不能与 GEOTRACES 海水背景直接混算。Cr-VI 不计作元素 Cr。

## USGS/WQP Sacramento River dissolved As demo

目录：`us-wqp-sacramento-river-arsenic/`。

- 来源：Water Quality Portal 固定的 USGS/NWIS 结果与站点查询响应，站点 `USGS-11447650`；
- 内容：189 条 2010–2023 dissolved As 记录中确定性选择 48 条，覆盖 Not Detected、field replicate、Preliminary 和 Accepted routine 状态；
- 方法与 QC：逐行保留 `USGS:PLM10`、实验室、检出限类型和值、结果状态与活动类型；Not Detected 以 `<0.10 ug/l` 保留，不填零；
- 覆盖边界：这是一个方法丰富的独立淡水时间序列，不是美国或全球河流水质覆盖。WQP 是交付入口，USGS/NWIS 是上游证据，不重复计作两条血缘。

## FOREGS 六介质 demo

目录分别为 `foregs-topsoil/`、`foregs-subsoil/`、`foregs-humus/`、`foregs-stream-water/`、`foregs-stream-sediment/` 和 `foregs-floodplain-sediment/`。

- 来源：EuroGeoSurveys/GTK《Geochemical Atlas of Europe》2005 科学发布，固定 2026-03-03 发布方文件快照；
- 使用条件：科研分析保留 Salminen et al. (2005) 引用和发布页要求的 EuroGeoSurveys/GTK copyright notice；
- 内容：每个来源 48 条。topsoil、subsoil、stream sediment、floodplain sediment 按 As/Cu/Ni/Zn × 总量/王水量平衡；stream water 按四元素平衡；humus 按实际存在的 Cu/Ni/Zn 平衡；
- 方法边界：总量、王水可浸出量、腐殖质温和硝酸可浸出量和 `<0.45 µm` 溶解态保持为不同 `measurement_basis`；
- 检出限边界：CSV 有表级 DL，但没有逐行 `<` 限定符；恰好等于 `DL/2` 的值只在证据中标为可能的上游替代，不自动改写为删失值；
- 覆盖边界：约 1 个站点/4,700 km²，是低密度欧洲大陆基线，不是欧洲连续覆盖，也不是本地调查精度。

## 确定性再生成

先按 `references/data-sources.md` 下载并验证来源。完整第三方文件留在仓库外缓存，然后在仓库根目录运行：

```bash
python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source georoc-archaean \
  --cache-dir .cache/data \
  --output-dir /tmp/georoc-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-05T06:25:00Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source usgs-conus-soil \
  --cache-dir .cache/data \
  --output-dir /tmp/usgs-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-05T06:25:00Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source pangaea-north-africa-soil \
  --cache-dir .cache/data \
  --output-dir /tmp/pangaea-north-africa-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-06T03:13:54Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source norway-marchem \
  --cache-dir .cache/data \
  --archive /path/to/marchem-inorganic-2003-2024.zip \
  --output-dir /tmp/marchem-demo \
  --mode cached \
  --observations 112 \
  --generated-at 2026-08-05T12:50:00Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source japan-gsj-geochemical-map \
  --cache-dir .cache/data \
  --output-dir /tmp/gsj-japan-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-06T03:48:23Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source geotraces-idp2025 \
  --cache-dir .cache/data \
  --output-dir /tmp/geotraces-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-05T13:41:55Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source gemstat-open-archive \
  --cache-dir .cache/data \
  --output-dir /tmp/gemstat-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-05T14:41:20Z

# FOREGS 的六个 source_id 分别运行；以下以 topsoil 为例
python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source foregs-topsoil \
  --cache-dir .cache/data/foregs-adapters \
  --output-dir /tmp/foregs-topsoil-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-06T08:00:00Z
```

使用相同注册表版本、验证缓存/快照和 `--generated-at` 时，每个来源的三个输出文件均应字节级一致。不要把 `.cache/data` 或完整第三方数据提交到仓库。

## AfSIS Phase I V2.0 土壤 demo

`afsis-phase-i-wet-chemistry/` 从官方 Dataverse 的三个 original 文件生成 48 条正值观测：12 个国家标签各选一个有完整坐标的样品，并为 As/Cu/Ni/Zn 各保留一条测定。原始国家标签 `SAfrica`、`Zimbambwe` 不被覆盖，规范名只写入独立证据字段；上下层、王水准全量基础、ICP-MS/ICP-OES、实验室、DL 和 QL 均逐观测绑定。

全量来源有 2,002 个样品，其中 126 个缺少经纬度；As/Cu/Pb 有负数仪器结果，Pb 有 1,969 条正值低于来源 DL。注册文件和相关论文没有声明坐标 CRS，因此 demo 保留经纬度但 `source_crs` 为空；变量表的 `As.75`/“Arsenic-78”以及采样年份也有文字冲突并保留在 evidence。demo 为了通过地图流水线只选正值与完整坐标，不得据此宣称全量无缺失或所有数值均为可靠检出。完整边界见 candidate audit 和 30 条待签署复核单。

## 四介质联合 fixture

`fixtures/four-media/combined-v3/` 将以上十五个来源合并到同一个 `sources=auto` 请求：792 条观测包括 rock 48、soil 288、sediment 256、water 200。`run_manifest.json` 绑定十五个输入 fixture 的 hash、来源证据等级、路由结果和 111 个 D2 比较分区；`expected-output/` 是可字节级重建的九文件工作流结果。

这只是接口联合测试。111 个背景组按元素、介质、样品类型、分相、measurement basis、地质单元、方法和消解/提取方法隔离；当前没有一个组跨越不兼容来源。输出中的 12 个候选异常只验证筛查流程，不构成区域异常、污染或矿化结论。8 条 suspended `µg/g` 记录因不是水体质量/体积单位而明确不作 `µg/L` 标准化。
