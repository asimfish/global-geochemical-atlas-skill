# D2 真实数据验证集

这里保存的是可离线复跑的真实公开数据，不是人为编造的“像真实数据”的 CSV。冻结文件共
2,713,710 bytes，来源、查询、许可、版本、访问日期和 SHA-256 由
[`real-sources.json`](../contracts/real-sources.json) 固定；逐条人工金标准由
[`real-gold.json`](../contracts/real-gold.json) 固定。

## 数据源

| 数据产品 | 实际冻结内容 | 本测试使用范围 | 真实脏数据特征 |
|---|---:|---|---|
| [USGS Data Series 801](https://pubs.usgs.gov/ds/801/) | 4,857 个美国本土 0–5 cm 表层土壤样点及官方元数据 | As、Cd、Cu、Fe、Hg、Pb、Zn；共 33,999 条测定 | `<` 删失值、`mg/kg` 与 `wt. %`、不同分析/消解方法、WGS84 |
| [USGS RASS OFR 99-433](https://pubs.usgs.gov/of/1999/of99-433/) | Circle 图幅 1,662 条沉积物 CSV 及 FGDC 元数据 | 排除 OA 浸提与附加亚型后保留 1,422 个 stream-sediment 样品；As、Cu、Pb、Zn；共 5,688 条测定 | N/L/G/H/B 独立限定符、方法年代差异、粒级差异、NAD27 |
| [USGS Taylor Mountains OFR 2007-1196 v1.1](https://pubs.usgs.gov/of/2007/1196/) | 59 个岩石样品的 Table 3 CSV 及 FGDC 元数据 | Fe、Cr、Cu、Ni、Pb、Zn；共 354 条测定 | 裸 `%`、ppm、`<`、岩性与带问号地层、NAD27、约 20 ft 定位精度 |
| [Water Quality Portal](https://water.usgs.gov/catalog/datasets/b971c11a-0d87-496b-bb11-d78a950fcc9e/) | `USGS-01594440` 的 90 条砷结果和 1 条站点元数据 | Dissolved、Suspended、Total 三种 fraction；共 90 条测定 | 未检出与检出限分列、历史方法缺失、动态查询、NAD83 |

这些来源只用于检验 D2 对不同介质、格式、限定符、单位和 CRS 的处理。它们不构成全球代表性
样本，也不能据此得出污染、矿化或成因结论。

## 为什么把原始文件放进仓库

- 大赛不提供数据集，离线冻结切片能保证 OpenCode/Codex 自动评审可复现。
- WQP 是动态数据源；准确查询仍写入清单，但科学金标准绑定 2026-08-05 的字节哈希。
- 8 个冻结文件总大小约 2.71 MB，远低于 250 MB 仓库限制，也落在小型真实 holdout 的合理范围内。
- 数据文件和元数据一起冻结，避免只留下数字却失去限定符、CRS、方法和许可解释。

USGS DS801、RASS 和 Taylor 元数据均声明无访问限制；RASS 与 Taylor 同时声明无使用限制。WQP 冻结查询仅选择
USGS/NWIS 观测，并要求保留准确查询与 DOI `10.5066/P9QRKUVJ`。使用者仍需阅读各产品的
fitness-for-use 免责声明。

## 复现

只校验仓库内文件，不联网：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/fetch_real_fixtures.py --offline
```

显式重新下载并核对固定哈希；若上游有任何字节漂移，命令失败且不覆盖原文件：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/fetch_real_fixtures.py --refresh
```

跑完整 40,131 条 D1→D2→D3 真实数据基线：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_real_data_suite.py \
  --output-dir /tmp/d2-real-full
```

快速 CI 冒烟仍使用这些真实原始文件，将 DS801、RASS 与 Taylor 三张样品表各取前 20 个样品；WQP 90 条始终完整：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_real_data_suite.py \
  --output-dir /tmp/d2-real-smoke \
  --max-source-samples 20
```

## 解释原则

- `N` 映射为 nondetect，并把伴随值作为检出限；不把检出限当测得值。
- `L` 映射为 trace（已检出但低于可报告下限），不能错误映射为 nondetect。
- Taylor 岩石表的裸 `%` 在没有显式质量基准时不能自动当成 `wt.%`；当前以 `UNSUPPORTED_UNIT` 失败关闭。
- 非 WGS84 坐标没有真实重投影时必须停止进入地图；只保留原坐标、CRS 和 QC flag。
- 分析方法缺失时保持缺失并降低工作流置信度，不根据年代或元素猜测。
- 候选异常只相对于声明的介质、basis、方法和消解背景组，是筛查结果而非科学结论。

当前完整运行结果见 [`real_data_report.json`](../runs/real-latest/real_data_report.json)，离线地图见
[`atlas.html`](../runs/real-latest/d3/atlas.html)。同一次运行还会生成
[`source_confidence.json`](../runs/real-latest/d3/source_confidence.json)、
[`anomaly_regions.geojson`](../runs/real-latest/d3/anomaly_regions.geojson)、
[`anomaly_region_report.json`](../runs/real-latest/d3/anomaly_region_report.json) 和
[`showcase_manifest.json`](../runs/real-latest/d3/showcase_manifest.json)，并以阻断检查验证四项比赛
交付物的路径与 SHA-256。`runs/` 为本地验证证据并被 `.gitignore` 排除，
最终参赛 Skill 只需保留小型 fixture、下载器、契约和可复现实验说明。
