# Global Geochemical Atlas Skill

从公开地球化学数据到可追溯标准库、候选异常和交互地图的一体化 Agent Skill。

本项目面向 AI4S Future ScienceSkills Hackathon「全球地球化学元素分布图谱」课题。它指导 Agent 采集岩石、土壤、沉积物和水体测定，保守处理单位、坐标、分析方法与删失值，并生成可复现、可审计的科学产物。

> 比赛提交主体是 [`skills/global-geochemical-atlas/`](skills/global-geochemical-atlas/) 中唯一的完整 Skill。数据库、报告和地图是每次任务运行生成的产物，不是第二个固定作品。

**当前可复现工程基线：** 4 类介质 · 14 个真实来源切片 · 796 条联合 demo 观测 · 11 个稳定运行产物 · Python 标准库离线可运行。

**快速入口：** [立即体验](#60-秒离线体验) · [接入自有数据](#使用自己的数据) · [运行真实来源 demo](#真实来源四介质-demo) · [查看架构](#工作流架构) · [了解科学边界](#科学边界) · [参与开发](#开发与验证)

## 核心交付物

| 赛题交付物 | 主要文件 | 能核验什么 |
|---|---|---|
| **可交互元素分布地图** | `interactive_map.html`、`samples.geojson` | 区域、元素、介质、样品类型、方法、置信度、热力与异常候选 |
| **标准化地球化学数据库** | `geochemistry.csv` | 原值与标准值、单位换算、删失状态、坐标、方法、QC 和记录级来源键 |
| **数据来源与置信度说明** | `source_manifest.json`、`record_evidence.jsonl`、`confidence_report.json` | URL/DOI、许可、版本、文件哈希、源记录定位和五分量置信度 |
| **异常区域识别结果** | `anomalies.geojson`、`anomaly_report.json` | 富集/亏损方向、背景组、样本量、median/MAD、稳健 z 分数和失败边界 |
| **可复用 Skill 文档** | [`SKILL.md`](skills/global-geochemical-atlas/SKILL.md) | 请求契约、工具路由、科学规则、失败状态和 D1/D2/D3 工作流 |

运行还会生成 `iteration_backlog.csv`，将来源、坐标、方法、地质背景、标准化与 QC 缺口路由到下一轮。删失观测会单独标记为科学限制，不会被当成可自动修复的错误。

## 60 秒离线体验

只需要 Python 3.11+；内置 demo 不需要网络、第三方依赖、密钥或 GPU。

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input skills/global-geochemical-atlas/fixtures/demo_input.csv \
  --output-dir demo_output

python skills/global-geochemical-atlas/scripts/validate_outputs.py \
  --output-dir demo_output
```

然后用浏览器打开 `demo_output/interactive_map.html`。

一次完整运行固定生成 11 个文件：

| 文件 | 用途 |
|---|---|
| `geochemistry.csv` | 标准化数据库；一行一个测定记录 |
| `qc_report.json` | 坐标、单位、删失值、重复候选和方法 QC 汇总 |
| `confidence_report.json` | 来源、完整性、方法、空间和 QC 五分量置信度 |
| `anomalies.geojson` | 可制图的候选异常点 |
| `anomaly_report.json` | 背景分组、阈值、排除原因和异常方法版本 |
| `source_manifest.json` | 来源、许可、输入与产物哈希绑定 |
| `record_evidence.jsonl` | 与数据库记录一一对应的来源证据 |
| `samples.geojson` | 有效 WGS84 地图点；无效坐标不会放到 `(0,0)` |
| `interactive_map.html` | 无 CDN、自包含的交互研究界面 |
| `iteration_backlog.csv` | D1/D2 缺口、复核项和科学限制 |
| `run_summary.json` | 运行状态、稳定输出清单、计数和限制 |

## 按研究问题生成地图

D3 使用 `d3-visualization-profile-v2` 将用户问题固定成可复现配置，不要求用户修改 HTML。下面的例子生成“中国土壤 As 候选异常”区域产品：

```bash
python skills/global-geochemical-atlas/scripts/create_visualization_profile.py \
  --story anomaly \
  --spatial-scope regional \
  --region china \
  --element As \
  --medium soil \
  --output /tmp/china-as-soil-profile.json

python skills/global-geochemical-atlas/scripts/render_visualization.py \
  --input-dir demo_output \
  --profile /tmp/china-as-soil-profile.json \
  --output-dir visualization_output

python skills/global-geochemical-atlas/scripts/validate_visualization.py \
  --output-dir visualization_output
```

全球任务、命名国家和自定义 WGS84 bbox 都使用同一接口。区域产品会裁剪 HTML 内嵌记录、异常显示和 `samples.geojson`，但不会改写完整的 `geochemistry.csv` 或上游证据。详细约束见 [D3 可视化契约](skills/global-geochemical-atlas/references/d3-visualization-contract.md)。

## 使用自己的数据

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /path/to/measurements.csv \
  --output-dir output \
  --region-bbox 73,18,135,54 \
  --max-records 50000
```

输入要求按用途分层：

| 层级 | 字段 |
|---|---|
| D2 最低分析输入 | `element_or_analyte,value,unit,medium` |
| 完整工作流必需来源字段 | `source_id,source_locator,license` |
| 正式科学运行建议字段 | `sample_id`、`measurement_basis`、`latitude`、`longitude`、`source_crs`、分析/消解方法、检出限、`source_tier` 和文件 SHA-256 |

缺少完整工作流必需来源字段时，证据打包会失败关闭。非 canonical 列名必须通过显式 schema map 映射，不能靠字段含义猜测。完整定义见 [输入输出契约](skills/global-geochemical-atlas/references/request-output-contract.md)、[数据模型](skills/global-geochemical-atlas/references/data-model.md)和[科学规则](skills/global-geochemical-atlas/references/scientific-rules.md)。

## 真实来源四介质 demo

仓库提供 14 个已验证来源的最小切片，共 796 条观测，覆盖：

- GEOROC 岩石；
- USGS、PANGAEA、AfSIS 与 FOREGS 土壤；
- MarChem、GSJ 与 FOREGS 沉积物；
- GEOTRACES、GEMStat 与 FOREGS 水体。

```bash
python skills/global-geochemical-atlas/scripts/build_four_media_demo.py \
  --output-dir /tmp/four-media-demo \
  --generated-at 2026-08-06T10:05:00Z

python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /tmp/four-media-demo/demo_input.csv \
  --output-dir /tmp/four-media-output
```

这些切片用于证明接口、证据链、比较隔离和地图工作流可以共同运行，不代表全球空间完整。海水与淡水、不同砷分相、土层、粒级、消解方法和岩石预编译值仍属于不同可比背景。

<details>
<summary><strong>真实来源预检、路由和 D1 原值索引</strong></summary>

先生成来源证据评分，再执行准入审计、保守路由和覆盖报告：

```bash
python skills/global-geochemical-atlas/scripts/score_source_evidence.py
python skills/global-geochemical-atlas/scripts/source_audit.py
python skills/global-geochemical-atlas/scripts/source_router.py \
  --request skills/global-geochemical-atlas/fixtures/source-routing/global-all-media-request.json
python skills/global-geochemical-atlas/scripts/coverage_report.py \
  --request skills/global-geochemical-atlas/fixtures/source-routing/global-all-media-request.json
```

`source_catalog.json` 中的候选不等于本次请求可执行的来源。证据分数表示证据完整度，不是数值为真的概率。离线模式只有在版本化缓存与 SHA-256 均被验证后才允许复用；动态 API 需用 `snapshot_source.py` 固定请求、响应哈希和成员清单。

需要查询 D1 分层原值归档时，先运行 `validate_acquisition.py`，再用 `build_index.py` 构建可重建 SQLite 索引。该索引不执行 D2 标准化、QC、置信度或异常分析。

</details>

## 工作流架构

```mermaid
flowchart LR
    Q[用户问题与范围] --> D1[D1 来源发现、准入、采集与证据链]
    D1 -->|原值、坐标、方法、许可、记录证据| D2[D2 单位标准化、QC、空间匹配、置信度与异常]
    D2 -->|标准库、报告、候选异常| D3[D3 任务配置、交互地图与迭代清单]
    D3 --> O[11 个可复现运行产物]
```

| 组件 | 责任边界 | 主要交付 |
|---|---|---|
| D1 | 来源目录、许可与引用、下载缓存、准入、覆盖、原值索引和证据打包 | 来源与记录级证据 |
| D2 | 单位与 basis、删失值、坐标/方法 QC、可选地质空间匹配、置信度和异常筛查 | 标准库、QC、置信度和异常结果 |
| D3 | 唯一 `SKILL.md`、工作流编排、研究配置、地图、数据库工作台和迭代反馈 | 交互地图、可视化报告和待办闭环 |

D3 只消费 D1/D2 公共产物，不重新计算标准值、置信度或异常。

## 科学边界

- 始终保留原值、原单位、qualifier、来源坐标表达和转换记录；不能证明的转换失败关闭。
- 固体质量比可统一为 `mg/kg`；水体质量/体积可统一为 `ug/L`，但没有密度时不把质量比与质量/体积互换。
- `<LOD`、`<LOQ`、`BDL`、`ND` 不替换为 0 或 LOD/2。
- 不静默交换经纬度，不把未知 CRS 冒充 WGS84；地质空间匹配必须记录数据源、版本、分辨率、方法和边界不确定性。
- 先按介质、样品类型、measurement basis、方法和地质背景建立可比组，再做元素组合或异常筛查。
- 富集/亏损只表示相对已声明背景组的候选异常，不等于污染、矿床或成因结论。
- demo 与真实来源切片只用于工程复现，不支持全球或区域代表性科学结论。

## 仓库结构

```text
.
├── skills/global-geochemical-atlas/   # 唯一正式 Skill；最终提交主体
│   ├── SKILL.md                       # Agent 入口与工作流
│   ├── assets/                        # 固定模板、词表、来源目录与离线底图
│   ├── fixtures/                      # 小型合成/真实来源复现切片
│   ├── references/                    # Schema、科学规则和接口契约
│   └── scripts/                       # 确定性采集、处理、制图与校验工具
├── evaluation/                        # E1 对齐 Q01–Q24 开发 benchmark
├── evaluation_lyf/                    # 隔离的 D1/D2/D3 阶段与 uplift 实验
├── plans/                             # 当前开发计划
└── CONTRIBUTING.md                    # 组件归属、接口冻结与 PR 规范
```

两个 `evaluation` 目录都不是主办方官方题库，不是 Skill 运行依赖，也不进入最终提交包。没有真实 B0/S0 三次运行和隔离隐藏集时，不得把 gold smoke 或回归结果宣称为正式 uplift。

## 开发与验证

```bash
# 全组件契约
python skills/global-geochemical-atlas/scripts/component_test.py --component all

# 端到端回归
python skills/global-geochemical-atlas/scripts/self_test.py

# evaluation 工具测试
python -m unittest discover -s evaluation/tools/tests -v
```

也可以把 `all` 换成 `d1`、`d2` 或 `d3`，单独验证责任域。路径归属、接口变更规则和完成定义见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

## 运行与加载

- 运行时仅依赖 Python 标准库，因此没有 `requirements.txt`。
- OpenCode：把 `skills/global-geochemical-atlas/` 暴露到 Skill 搜索路径。
- Codex：在临时验证工作区把同一目录映射到 `.agents/skills/global-geochemical-atlas/`。
- 不要维护第二份 Skill，也不要把 provider 配置、API key、缓存、模型权重、开发期评测 gold 或演示视频放入正式 Skill/提交包。

## 许可与第三方数据

代码和原创文档采用 [MIT License](LICENSE)。外部数据仍遵守各自许可、署名和再分发条件；使用或发布结果前检查 `source_manifest.json`。Macrostrat、GEMStat 等聚合平台还可能要求同时引用原始数据提供者。
