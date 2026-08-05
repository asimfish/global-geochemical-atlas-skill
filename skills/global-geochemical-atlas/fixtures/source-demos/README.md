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

## MarChem demo

目录：`norway-marchem/`。

- 来源：MarChem 挪威海域沉积物动态 API 快照 `norway-marchem:2026-08-05T10:27:11Z:be888784ee2e`；
- 许可：CC BY 4.0，保留来源署名；
- 内容：从已经准备的 30 条分层复核记录中保留 28 条含目标元素的源行，生成 As、Cu、Ni、Zn 各 28 条，共 112 条观测；
- 方法边界：所有值均为干重 `mg/kg` 的部分硝酸消解结果，不代表总含量；批次认可状态和 LLQ 按观测保留；
- 关系边界：完整快照的 1,070 行对应 880 个样品，fixture 不把第二参数组产生的附加行误算成新样品。

## GEOTRACES demo

目录：`geotraces-idp2025/`。

- 来源：GEOTRACES IDP2025 官方 WebODV 离散海水快照 `geotraces-idp2025:IDP2025:a61f441e5ae2`；
- 许可：CC BY 4.0，并遵守 Fair Data Use 的数据集和原贡献者引用要求；
- 内容：从 QC 1/2、坐标和深度有效的 dissolved 观测中平衡选择 Cu、Ni、Zn 各 16 条，共 48 条；
- 单位边界：原始 `nmol/kg` 保持不变；没有明确元素原子量和海水密度时不换算为 `ug/L`；
- 覆盖边界：样点来自海洋航次，不是规则全球网格；官方离散海水变量表没有 As，必须用其他水体来源补齐。

## GEMStat demo

目录：`gemstat-open-archive/`。

- 来源：UNEP GEMS/Water Global Freshwater Quality Archive v3，版本 DOI `10.5281/zenodo.18459694`；
- 许可：CC BY 4.0，保留 archive 引用；
- 内容：只从 Good/Fair、方法代码明确、非负且非极端的记录中选择 dissolved、suspended、total As 各 16 条；在来源具备时平衡 `mg/l`/`µg/l`、湖泊/河流和 `<` 删失值；
- 质量边界：原始 492,999 条观测中的方法代码 0、Pending review、Suspect、重复和异常哨兵仍保留在全量适配器与审计报告中，但不进入演示；
- 覆盖边界：As 子集只涉及 33 个贡献国家，不是规则全球淡水网格，也不能与 GEOTRACES 海水背景直接混算。

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
  --source norway-marchem \
  --cache-dir .cache/data \
  --archive /path/to/marchem-inorganic-2003-2024.zip \
  --output-dir /tmp/marchem-demo \
  --mode cached \
  --observations 112 \
  --generated-at 2026-08-05T12:50:00Z

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
```

使用相同注册表版本、验证缓存/快照和 `--generated-at` 时，每个来源的三个输出文件均应字节级一致。不要把 `.cache/data` 或完整第三方数据提交到仓库。

## 四介质联合 fixture

`fixtures/four-media/combined-v3/` 将以上五个来源合并到同一个 `sources=auto` 请求：304 条观测包括 rock 48、soil 48、sediment 112、water 96。`run_manifest.json` 绑定五个输入 fixture 的 hash、来源证据等级、路由结果和 34 个 D2 比较分区；`expected-output/` 是可字节级重建的九文件工作流结果。

这只是接口联合测试。34 个背景组按元素、介质、measurement basis、地质单元、方法和消解/提取方法隔离；当前没有一个组跨越不兼容来源。输出中的 10 个候选异常只验证筛查流程，不构成区域异常、污染或矿化结论。
