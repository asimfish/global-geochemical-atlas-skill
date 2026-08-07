<div align="center">

# 🌍 Global Geochemical Atlas Skill

**全球地球化学元素分布图谱 —— 面向 AI Agent 的可复用科研 Skill**

*Turn scattered public geochemistry into a traceable database, screened anomaly candidates, and self-contained interactive atlases.*

[![CI](https://github.com/asimfish/global-geochemical-atlas-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/asimfish/global-geochemical-atlas-skill/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](#-90-秒快速开始)
[![Runtime Deps](https://img.shields.io/badge/%E8%BF%90%E8%A1%8C%E6%97%B6%E4%BE%9D%E8%B5%96-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9-brightgreen)](#-90-秒快速开始)
[![Tests](https://img.shields.io/badge/tests-383%20%2B%2075%20passing-brightgreen)](#-开发与验证)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-4B2E83)](#-在你的-ai-agent-中使用)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[🚀 快速开始](#-90-秒快速开始) ·
[🤖 在 Agent 中使用](#-在你的-ai-agent-中使用) ·
[🧭 数据来源](#-数据来源21-个已冻结来源) ·
[📦 输出产物](#-十五个输出产物) ·
[❓ FAQ](#-faq)

<img src="skills/global-geochemical-atlas/assets/readme-atlas-overview.png" alt="全球地球化学元素图谱交互界面，展示四介质样点、候选异常与覆盖情况" width="100%">

<sub>真实工作流截图：21 个公开来源的最小复现切片，1,144 条观测。它验证工程链路，不代表全球空间覆盖。</sub>

</div>

---

## 📌 这是什么

这是一个面向 AI Agent 的**完整科研 Skill**，而不是一张预制地图。给它一个「元素 × 区域 × 介质」请求，Agent 会按 **D1 → D2 → D3** 工作流发现和冻结公开数据源、执行单位与坐标质量控制、在可比背景组内筛查富集/亏损候选，最终产出可审计的标准数据库、证据报告和交互地图。

| 你关心的 | 它给你的 |
|---|---|
| 数据从哪来 | 21 个已冻结公开来源（岩石/土壤/沉积物/水体），逐记录绑定 DOI、版本、许可与文件 SHA-256 |
| 数值可不可信 | 原值永不覆盖、删失值不插补、批次 QC 逐条重算、五分量置信度 + 明确的「不是正确概率」声明 |
| 结论敢不敢用 | 异常只作筛查候选并列出竞争解释；跑不齐的范围诚实报告缺口，绝不冒充全量覆盖 |
| 能不能复用 | 40+ JSON Schema、十五文件产物契约、自包含 HTML 地图、纯标准库脚本，可脱离本仓库对接 |

## 🚀 90 秒快速开始

只需要 Python 3.11+，**无需网络、密钥、GPU 或任何第三方包**。在仓库根目录运行：

```bash
# 1. 运行生产阈值真实数据演示（996 条 hash 固定的 USGS 土壤测定）
python skills/global-geochemical-atlas/scripts/run_atlas_request.py \
  --request skills/global-geochemical-atlas/fixtures/production-usgs/request.json \
  --demo production-usgs \
  --analysis-profile production \
  --generated-at 2026-08-07T00:00:00Z \
  --output-dir /tmp/geochemical-production-demo

# 2. 校验十五文件产物契约
python skills/global-geochemical-atlas/scripts/validate_outputs.py \
  --output-dir /tmp/geochemical-production-demo
```

两个命令应分别返回 `"status": "partial_success"` 和 `"status": "valid"`。前者是**刻意的科学状态**：hash 固定切片完整跑通，但不冒充冻结请求的全量空间覆盖；后者证明十五项产物契约全部有效。

然后用浏览器打开 `/tmp/geochemical-production-demo/interactive_map.html` —— 一个完全自包含、无 CDN 依赖的交互图谱。

<details>
<summary><b>这条回归验证了什么？（点开看预期指标）</b></summary>

- 996/996 条记录完成 GLiM 岩性地质匹配；
- 72 个背景组中 **12 个达到生产阈值 `n≥20` 完成分析，60 个样本不足被诚实排除**（不降阈值、不硬凑）；
- 识别 6 个 high/low 候选异常；
- 输出校验 0 错误 / 0 警告。

它证明工程和科学规则可执行，不代表美国土壤的统计分布。完整证据见[生产演示说明](skills/global-geochemical-atlas/references/production-demo.md)。

</details>

本地重复基准采用 3 次预热和 10 次独立测量，每次都创建新输出目录并验证全部 15 项产物；记录结果与适用边界见[工作流性能基准](skills/global-geochemical-atlas/BENCHMARK.md)。它不是官方模型得分或 2 CPU 容器成绩。

## 🤖 在你的 AI Agent 中使用

本 Skill 按 [Agent Skills](https://agentskills.io) 公共子集编写（`SKILL.md` + `references/` + `scripts/` + `assets/`，一层引用、相对路径、纯标准库），可直接挂载到任何兼容运行时：

```bash
# Claude Code（个人技能目录）
cp -r skills/global-geochemical-atlas ~/.claude/skills/

# Codex CLI
cp -r skills/global-geochemical-atlas ~/.codex/skills/

# OpenCode 及其他兼容运行时：将 skill 目录复制/挂载到其技能目录即可
```

挂载后直接向 Agent 提出诉求即可触发，例如：*「用公开数据做一张西欧土壤砷分布图，标出候选富集区并给出来源和置信度」*。

- 激活边界与示例：[`evals/activation.json`](skills/global-geochemical-atlas/evals/activation.json)（含 4 条应激活/不应激活样例）
- 平台元数据：[`agents/openai.yaml`](skills/global-geochemical-atlas/agents/openai.yaml) · 能力卡片：[`skill-card.md`](skills/global-geochemical-atlas/skill-card.md)
- Agent 的完整执行合同（状态机、门禁、失败状态）：[`SKILL.md`](skills/global-geochemical-atlas/SKILL.md)

## 🧑‍🔬 三种运行方式

### ① 使用自己的数据

```bash
python skills/global-geochemical-atlas/scripts/run_atlas_request.py \
  --request /path/to/request.json \
  --input /path/to/measurements.csv \
  --evidence-jsonl /path/to/record_evidence.jsonl \
  --acquisition-manifest /path/to/run_manifest.json \
  --output-dir /tmp/geochemical-output
```

D2 最低分析字段是 `element_or_analyte,value,unit,medium`；完整证据工作流还要求 `source_id,source_locator,license`。非标准列名必须通过显式 schema map 映射，不能靠语义猜测。正式科学运行还应提供样品标识、measurement basis、WGS84/原 CRS、分析与消解方法、检出限、来源层级及文件 SHA-256。

### ② 在线采集公开来源

```bash
python skills/global-geochemical-atlas/scripts/run_atlas_request.py \
  --request /path/to/request.json \
  --online-source auto \
  --cache-dir .cache/data \
  --analysis-profile production \
  --output-dir /tmp/geochemical-online
```

`auto` 会对所有与请求兼容的已路由来源确定性分配记录配额，逐源验证 manifest 与 SHA-256 后合并；单源失败不阻塞整体，以已验证子集继续并返回 `partial_success`。下载均有超时、限量、有限重试与缓存，`--offline` 模式只接受已验证缓存。

### ③ 复现四介质离线样例（首页截图）

<details>
<summary>运行 21 来源、四介质、1,144 条观测的离线样例</summary>

```bash
python skills/global-geochemical-atlas/scripts/build_four_media_demo.py \
  --output-dir /tmp/four-media-demo \
  --generated-at 2026-08-06T10:05:00Z

python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /tmp/four-media-demo/demo_input.csv \
  --output-dir /tmp/four-media-output

python skills/global-geochemical-atlas/scripts/validate_outputs.py \
  --output-dir /tmp/four-media-output
```

这些版本化切片来自 GEOROC、USGS、PANGAEA、AfSIS、FOREGS、MarChem、GSJ、GEOTRACES 与 GEMStat 等公开平台。来源适用条件与复现说明见[来源 demo 文档](skills/global-geochemical-atlas/fixtures/source-demos/README.md)。

</details>

## 🔬 工作流与科学设计

```mermaid
flowchart LR
    Q[研究问题<br/>元素·区域·介质] --> D1[D1 来源<br/>发现·准入·采集·证据]
    D1 --> D2[D2 数据<br/>标准化·QC·空间匹配·异常]
    D2 --> D3[D3 产品<br/>研究配置·地图·迭代]
    D3 --> O[数据库<br/>证据与置信度<br/>异常结果<br/>交互地图]
    O -. iteration_backlog 驱动的多轮闭环 .-> D1
```

- **D1** 保存许可、版本、下载请求、文件哈希和记录级定位；来源目录中的候选不等于本次请求可用。
- **D2** 保守处理单位、删失值、坐标、方法、实验室批次和可选地质匹配；先用稳健 MAD z-score 筛记录级高/低值，再用精确超几何检验 + BH-FDR 筛空间聚集。
- **D3** 只消费公共产物，通过版本化 profile 生成全球、国家或 WGS84 bbox 研究视图；不重算 D2 科学结果。
- **多轮迭代**：每次运行产出 `iteration_backlog.csv`（可审计的回路控制面）。长时限沙箱下可按[迭代闭环协议](skills/global-geochemical-atlas/references/iteration-loop.md)多轮运行：只修复 `action_required` 项、每轮重新采集/映射/重跑生成新版本、canonical 数据与原始证据不可变、收敛条件显式（问题数不下降或需要猜测时停机并交人工复核）。

## 📦 十五个输出产物

每次完整运行固定生成 15 个文件，逐文件 schema 与状态定义见[输入输出契约](skills/global-geochemical-atlas/references/request-output-contract.md)：

| 赛题交付物 | 运行产物 | 核心保证 |
|---|---|---|
| **可交互元素分布地图** | `interactive_map.html` · `samples.geojson` | 自包含无 CDN；按元素、介质、区域、方法与置信度筛选；样点、热力与异常候选视图 |
| **标准化地球化学数据库** | `geochemistry.csv` · `batch_acceptance.csv` | 保留原值与换算轨迹；统一单位、basis、坐标、方法、分析批次与 QC 字段 |
| **数据来源与置信度说明** | `source_manifest.json` · `record_evidence.jsonl` · `confidence_report.json` | URL/DOI、许可、版本、哈希、源记录定位和五分量置信度可追溯 |
| **异常区域识别结果** | `anomalies.geojson` · `anomaly_report.json` · `anomaly_regions.geojson` · `spatial_anomaly_report.json` | 记录级 robust-MAD 候选 + 精确超几何富集/BH-FDR 空间筛查；完整报告失败边界 |
| **质量与运行证据** | `qc_report.json` · `batch_qc_report.json` · `iteration_backlog.csv` · `run_summary.json` | 逐项 QC 留证、失败批次不静默删除、迭代待办与全运行摘要（含各产物 hash） |

第五项赛题交付「可复用 Skill 文档」即 [`SKILL.md`](skills/global-geochemical-atlas/SKILL.md) 本体与其 schema、脚本和 fixture。

## 🧭 数据来源（21 个已冻结来源）

| 介质 | 已冻结来源 |
|---|---|
| 🪨 岩石 | GEOROC（太古宙克拉通汇编 · 南极板内火山岩） |
| 🌱 土壤 | USGS DS801（美国本土）· GEMAS（欧洲）· FOREGS 表土/底土/腐殖质 · AfSIS Phase I（撒哈拉以南非洲）· PANGAEA 北非 · TPDC 中国山地 |
| 🏞️ 沉积物 | FOREGS 河流/洪泛平原沉积物 · GSJ 日本地球化学图 · GSJ 日本海洋沉积物 · 澳大利亚 NGSA（Hg）· 挪威 MarChem · PANGAEA 阿拉伯海 |
| 💧 水体 | FOREGS 河水 · GEMStat 全球内陆水 · GEOTRACES IDP2025 海水 · 美国 WQP 萨克拉门托河（As） |

每个来源的 DOI、版本、许可、科研使用条件、字段边界与八维证据评分记录在[来源目录](skills/global-geochemical-atlas/references/data-sources.md)、[来源准入标准](skills/global-geochemical-atlas/references/source-acceptance-standard.md)与[许可引用说明](skills/global-geochemical-atlas/references/licenses-and-citations.md)。EarthChem 等联邦检索站作为**发现层**使用：只有追溯到原始记录后才能作测量证据。

## 🛡️ 科学护栏

- 原值、原单位、qualifier、来源坐标表达和转换记录始终保留；不能证明的转换会失败关闭。
- 固体质量比可统一为 `mg/kg`，水体质量/体积可统一为 `ug/L`；`nmol/L` 只对冻结原子量表中的明确元素换算，没有摩尔质量或密度证据时失败关闭。
- `<LOD`、`<LOQ`、`BDL`、`ND` 不替换为 0 或 LOD/2。
- CRM、空白、重复样按显式 policy 重新计算；失败批次保留在数据库，但不进入异常背景。
- 不静默交换经纬度，不把未知 CRS 冒充 WGS84；允许 DOI、字段名、URL 与内容哈希同时匹配的版本化平台坐标政策，空间匹配记录数据源、版本、方法和边界距离。
- 背景组样本不足时诚实返回 `insufficient_background`，绝不降低阈值硬算（上方 demo 中 72 组只分析达标的 12 组）。
- 异常点和 FDR 网格都只表示筛查候选；网格不是地质/行政/污染边界，不等于污染、矿床或成因结论。
- demo 与真实来源切片只用于工程复现，不支持全球或区域代表性科学结论。

## 📚 文档导航

| 如果你想…… | 从这里开始 |
|---|---|
| 让 Agent 执行完整任务 | [Skill 入口](skills/global-geochemical-atlas/SKILL.md) |
| 为单阶段或完整任务生成最小命令计划 | [任务合同 schema](skills/global-geochemical-atlas/references/task-contract.schema.json) |
| 对接输入或消费 15 个输出 | [请求与输出契约](skills/global-geochemical-atlas/references/request-output-contract.md) |
| 理解数据库字段与专业平台 crosswalk | [数据模型](skills/global-geochemical-atlas/references/data-model.md) |
| 审查单位、删失值、置信度和异常规则 | [科学规则](skills/global-geochemical-atlas/references/scientific-rules.md) |
| 复现真实数据生产阈值闭环 | [生产演示](skills/global-geochemical-atlas/references/production-demo.md) |
| 定制全球、区域或元素组合地图 | [D3 可视化契约](skills/global-geochemical-atlas/references/d3-visualization-contract.md) |
| 做多轮迭代修复 | [迭代闭环协议](skills/global-geochemical-atlas/references/iteration-loop.md) |
| 修改 D1/D2/D3 或提交 PR | [贡献指南](CONTRIBUTING.md) |
| 查看开发期 Q01–Q24 benchmark | [评测说明](evaluation/README.md) |
| 复现离线工作流性能基线 | [性能基准](skills/global-geochemical-atlas/BENCHMARK.md) |
| 选择正确的测试 Prompt | [测试 Prompt 总入口](TESTING_PROMPTS.md) |

## 🧪 开发与验证

仓库的测试分层如下。Docker 是统一执行环境，不是第三套 benchmark：

| 入口 | 验证内容 |
|---|---|
| Skill `component_test.py` / `self_test.py` | D1/D2/D3 契约与最小端到端回归（383 + 75 项检查） |
| [`evaluation/`](evaluation/) | Q01–Q24、B0/S0、E1 十产物和评分证据 |
| [`evaluation_lyf/`](evaluation_lyf/) | D1/D2/D3 独立科学门禁与 Qwen Skill uplift |
| [`evaluation/docker/`](evaluation/docker/) | 上述评测共用的镜像、隔离、OpenCode 与 campaign runner |

```bash
# 全仓格式、lint 与评测关键/公共契约类型门
ruff check .
ruff format --check .
mypy --config-file mypy-critical.ini

# D1/D2/D3 公共接口与契约
python skills/global-geochemical-atlas/scripts/component_test.py --component all

# 端到端离线回归
python skills/global-geochemical-atlas/scripts/self_test.py

# 重复执行并验证完整离线工作流性能
python skills/global-geochemical-atlas/scripts/benchmark_workflow.py \
  --warmups 3 --runs 10 \
  --output /tmp/gga-workflow-benchmark.json

# L0/L1 确定性合规预检（结构、大小、frontmatter、引用可达性、红线扫描）
python evaluation/docker/preflight.py . --output /tmp/preflight.json

# evaluation 工具单元测试
python -m unittest discover -s evaluation/tools/tests -v

# Docker 控制器与两份 Qwen Prompt 契约
python -m unittest discover -s evaluation/docker/tests -v
python evaluation_lyf/agent_uplift/test_prompt_contract.py

# 统一报告、三次独立运行聚合和浏览器证据契约
python -m unittest discover -s evaluation/reporting -p 'test_*.py' -v
```

也可以把 `all` 换成 `d1`、`d2` 或 `d3`，单独验证责任域。Docker 的标准构建和 smoke 命令见 [`evaluation/docs/docker_usage.md`](evaluation/docs/docker_usage.md)；主机版与 Docker 版的有/无 Skill Prompt 见 [`evaluation_lyf/agent_uplift/DOCKER_UPLIFT.md`](evaluation_lyf/agent_uplift/DOCKER_UPLIFT.md)；路径归属、接口变更规则和完成定义见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

> `evaluation/` 和 `evaluation_lyf/` 是开发基准，不是主办方官方题库，也不会进入最终提交包。比赛提交主体只有 `skills/global-geochemical-atlas/` 中这一份 Skill。

## ❓ FAQ

<details>
<summary><b>完全离线能用吗？</b></summary>

能。90 秒 demo、四介质样例和全部测试都基于 hash 固定的本地切片，零网络、零第三方包。在线采集只在你显式传入 `--online-source` 时发生，且 `--offline` 模式只接受已验证缓存。

</details>

<details>
<summary><b>返回 <code>partial_success</code> 是失败吗？</b></summary>

不是。它是刻意设计的科学状态：已验证子集完整跑通并交付，但不冒充冻结请求的全量空间覆盖。缺口、排除原因和下一步建议都写在 `run_summary.json` 里。全部范围与验证通过才会返回 `success`。

</details>

<details>
<summary><b>异常候选可以直接当矿化/污染结论用吗？</b></summary>

不可以。所有异常均为 screening-only 候选：自然背景、采样偏差、空间自相关、方法差异和人为输入都是竞争解释。任何成因解释都需回看原记录与 QC、做尺度敏感性，并取得独立的采样设计、分析质量与地质/矿物学证据。

</details>

<details>
<summary><b>任务时限很长（小时级）时，能自动多轮迭代吗？</b></summary>

能，一条命令启动自我修正循环：

```bash
python skills/global-geochemical-atlas/scripts/run_self_correction_loop.py \
  --request /path/to/request.json \
  --online-source auto \
  --max-rounds 5 \
  --output-dir /tmp/atlas-loop
```

控制器先做早期门禁（路由可行性、最低输入列），每轮独立产出并校验十五文件契约，自动重试瞬态获取失败，把 schema/许可/坐标等需要证据的问题分组写入 `loop_report.json` 的修复计划；收敛、无进展或预算用尽时诚实停机。人工修复后在同一目录重新调用即可续跑。canonical 数据不可变，每轮生成新版本；删失值等 `scientific_limit` 不计入修复率——科学限制不能靠循环"修"掉。协议详见[迭代闭环](skills/global-geochemical-atlas/references/iteration-loop.md)。

</details>

<details>
<summary><b>如何新增一个数据源？</b></summary>

按 D1 准入流程：登记来源目录（DOI/版本/许可/科研使用条件）→ 编写来源适配器 → 通过八维证据评分与快照 hash 验证 → 30 条记录具名人工复核后方可进入 `benchmark_ready`。详见[来源准入标准](skills/global-geochemical-atlas/references/source-acceptance-standard.md)与[贡献指南](CONTRIBUTING.md)。

</details>

<details>
<summary><b>为什么坚持零第三方依赖？</b></summary>

评测与生产沙箱环境不可控。纯标准库意味着没有安装失败、没有版本冲突、没有供应链风险；交互地图同样自包含（无 CDN），断网可开。

</details>

## 📄 License

代码和原创文档采用 [MIT License](LICENSE)。外部数据仍遵守各自许可、署名和再分发条件；发布结果前请检查运行生成的 `source_manifest.json`。

<div align="center">
<sub>用公开数据说话，让每个数字可追溯。</sub>
</div>
