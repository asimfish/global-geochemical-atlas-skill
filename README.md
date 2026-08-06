# Global Geochemical Atlas Skill

一个证据优先、覆盖度可解释、可离线降级的全球地球化学元素分布图谱 Agent Skill。它指导智能体从公开科学来源采集岩石、土壤、沉积物和水体元素测定，保守统一单位，执行坐标与方法质量控制，识别候选富集/亏损，并生成标准化数据库、来源与置信度报告、GeoJSON 和自包含交互地图。

本仓库只包含一个正式 Skill：`skills/global-geochemical-atlas/`。正文采用 Agent Skills、OpenCode 与 Codex 可共同读取的最小公共格式。

根目录的 `evaluation/` 是团队开发期科学 benchmark，不是主办方官方题库、不是 Skill 运行依赖，也不进入最终 Skill 提交包。Public Q01–Q08 只用于接口诊断；没有真实 B0/S0 三次运行和隔离隐藏集时，不得把 gold smoke 宣称为正式 uplift。

## 30 秒离线复现

要求：Python 3.11+；不需要第三方依赖、网络、密钥或 GPU。

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input skills/global-geochemical-atlas/fixtures/demo_input.csv \
  --output-dir demo_output
```

生成：

- `geochemistry.csv`：标准化地球化学数据库；
- `source_manifest.json`：记录级来源、许可、输入哈希及置信度报告哈希绑定；
- `record_evidence.jsonl`：与数据库记录一一对应的来源文件、源行、版本、哈希和引用；
- `qc_report.json` 与 `confidence_report.json`：QC 和运行级置信度；
- `anomalies.geojson` 与 `anomaly_report.json`：候选异常及背景组统计；
- `samples.geojson`：地图样点图层；
- `interactive_map.html`：无 CDN 的自包含交互图谱，含区域 bbox、分布图、样点密度热力图、介质/元素/可比浓度着色、元素组合与富集/亏损候选区域；
- `run_summary.json`：稳定输出清单、状态和限制。

地图首页默认展示全部可上图测定，并按 `source_id + sample_id + medium + coordinates`
折叠为样品级符号；没有 `sample_id` 的记录不做推测性去重。颜色默认表示介质，只有筛选结果
收敛到同一元素、介质、measurement basis、方法组和标准单位时才启用浓度对数色阶。
页面同时提供来源与置信度、候选异常、QC 与覆盖边界页签，全部直接消费 D1/D2 公共产物，
不在可视化层重算标准值、置信度或异常。

## D3 是可视化生成 Skill，不是一张固定网页

`interactive-atlas-v3.html` 是 Skill 内部模板。Agent 应从用户问题生成
`d3-visualization-profile-v1` 配置，再用一个目录级命令渲染，不能要求用户手改 HTML：

```bash
python skills/global-geochemical-atlas/scripts/render_visualization.py \
  --input-dir demo_output \
  --profile skills/global-geochemical-atlas/assets/visualization-profile.template.json \
  --output-dir visualization_output
python skills/global-geochemical-atlas/scripts/validate_visualization.py \
  --output-dir visualization_output
```

配置决定首屏任务、区域、元素、介质、地质单元、元素组合和图层；结果同时输出配置与
`visualization_report.json`，便于 Agent 和评测系统核验复现性及覆盖提示。

然后运行自检：

```bash
python skills/global-geochemical-atlas/scripts/self_test.py
```

## 真实来源四介质离线复现

仓库还提供五条已验证真实来源的最小切片：GEOROC 岩石、USGS 土壤、MarChem 沉积物、GEOTRACES 海水和 GEMStat 淡水。它们可合成一个 304 条观测的四介质输入，并生成统一地图包：

```bash
python skills/global-geochemical-atlas/scripts/build_four_media_demo.py \
  --output-dir /tmp/four-media-demo \
  --generated-at 2026-08-06T10:05:00Z

python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /tmp/four-media-demo/demo_input.csv \
  --output-dir /tmp/four-media-output
```

这套 fixture 用于证明真实数据的接口、证据链和比较隔离可以共同运行，不代表全球空间完整。海水/淡水、三种砷分相、部分消解沉积物、土层和岩石预编译值仍是不同背景组。

## 使用自己的 CSV

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /path/to/measurements.csv \
  --output-dir output \
  --region-bbox 73,18,135,54 \
  --max-records 50000
```

`standardize_geochemistry.py` 的最低分析列为 `element_or_analyte,value,unit,medium`；要运行并交付完整 `run_workflow.py`，还必须提供非空 `source_id,source_locator,license`，否则证据打包会失败关闭。正式科学运行还应提供 `source_tier`、样品 ID、measurement basis、经纬度、CRS、分析方法、消解/提取方法、检出限和文件哈希。完整契约见 `skills/global-geochemical-atlas/references/`；D3 消费层详见 [可视化契约](skills/global-geochemical-atlas/references/d3-visualization-contract.md)。

## 真实来源预检与 D1 原值索引

对真实请求先生成渐进式来源证据评分，再执行准入审计、保守路由和覆盖矩阵。以下固定 fixture 覆盖 rock、soil、sediment、water 与 As/Cu/Ni/Zn，可离线复现：

```bash
python skills/global-geochemical-atlas/scripts/score_source_evidence.py
python skills/global-geochemical-atlas/scripts/source_audit.py
python skills/global-geochemical-atlas/scripts/source_router.py \
  --request skills/global-geochemical-atlas/fixtures/source-routing/global-all-media-request.json
python skills/global-geochemical-atlas/scripts/coverage_report.py \
  --request skills/global-geochemical-atlas/fixtures/source-routing/global-all-media-request.json
```

`source_catalog.json` 中的候选不等于本次请求可执行的来源。证据分数衡量八类证据的完整度，不是真值概率；路由器再按访问状态、科研使用条件、最低证据等级和 use mode 选择来源。`offline=true` 时，在调用方另行验证版本化缓存及 SHA-256 前不会选中任何在线来源。动态 API 还需用 `snapshot_source.py` 固定请求、响应哈希和成员清单。需要保存 D1 分层原值归档并查询时，先运行 `validate_acquisition.py`，再用 `build_index.py` 构建可重建的 SQLite 索引。索引不执行 D2 的单位换算、QC、置信度或异常分析，最终标准化数据库仍是 `geochemistry.csv`。

## 科学边界

- 保留原值、原单位、qualifier 和原始坐标表达；无法证明的转换失败关闭。
- 固体质量比可统一为 `mg/kg`；水体质量/体积统一为 `ug/L`，但不把水体 `ppm` 猜成质量/体积。
- `<LOD`、`BDL`、`ND` 不替换为 0 或 LOD/2。
- 不静默交换经纬度，不把未知 CRS 冒充 WGS84。
- 异常是相对已声明背景组的筛查候选，不等于污染、矿床或成因结论。
- demo 是 CC0 合成验收数据；真实来源最小 fixture 保留各数据集许可、引用和运行清单。两者都只用于工程复现，不支持全球或区域代表性科学结论。

## 仓库结构

```text
skills/
└── global-geochemical-atlas/
    ├── SKILL.md
    ├── assets/natural-earth-110m-land.json
    ├── fixtures/demo_input.csv
    ├── references/
    └── scripts/
```

没有 `requirements.txt`：运行脚本只使用 Python 标准库。完整数据不进入仓库；可使用受控下载脚本获取公开文件，并保存 URL、时间、许可和 SHA-256。

## 三人协作

仓库仍然只有一个生产 Skill，但内部按稳定接口拆为三个责任域：

- D1 维护来源目录、准入审计、路由与覆盖、下载缓存、原值归档索引、demo 数据和证据打包，负责 **数据来源与置信度说明**；
- D2 维护标准化、QC、置信度算法和异常分析，负责 **标准化地球化学数据库** 与 **异常区域识别结果**；
- D3 维护唯一 `SKILL.md`、总工作流、地图和 demo，负责 **可交互元素分布地图** 与 **可复用 Skill 文档**。

各角色可独立运行最小契约测试：

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component d1
python skills/global-geochemical-atlas/scripts/component_test.py --component d2
python skills/global-geochemical-atlas/scripts/component_test.py --component d3
```

合并前运行 `--component all` 和 `self_test.py`。完整路径归属、接口冻结规则、分支约定和完成定义见仓库根目录 `CONTRIBUTING.md`；该文件服务开发协作，不属于运行时 Skill。

## Skill 加载

- OpenCode：把 `skills/global-geochemical-atlas/` 暴露到其 Skill 搜索路径。
- Codex：在临时验证工作区把同一目录映射到 `.agents/skills/global-geochemical-atlas/`。

不要在仓库中维护多个副本，也不要提交 provider 配置、API key、缓存、评测 gold 或演示视频。

## 许可与数据

代码和原创文档采用 MIT License。每个外部数据集仍服从其自身许可和署名要求；下载或再分发前检查 `source_manifest.json`。Macrostrat 和 GEMStat 等聚合平台还可能要求同时引用原始数据提供者。
