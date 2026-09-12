<div align="center">

# 🌍 Global Geochemical Atlas Skill

**全球地球化学元素分布图谱 —— 面向 AI Agent 的可复用科研 Skill**

*把零散的公开地球化学数据，变成可追溯的数据库、经筛查的异常候选与自包含的交互图谱。*

[English](README.md) | **简体中文**

[![CI](https://github.com/asimfish/global-geochemical-atlas-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/asimfish/global-geochemical-atlas-skill/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](#-90-秒快速开始)
[![Runtime Deps](https://img.shields.io/badge/%E8%BF%90%E8%A1%8C%E6%97%B6%E4%BE%9D%E8%B5%96-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9-brightgreen)](#-90-秒快速开始)
[![Tests](https://img.shields.io/badge/tests-677%20%2B%2060%20%2B%2076%20%2B%20117%20passing-brightgreen)](#-开发与验证)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-compatible-4B2E83)](#-在你的-ai-agent-中使用)
[![Works with](https://img.shields.io/badge/Works%20with-Claude%20Code%20%C2%B7%20Codex%20%C2%B7%20Cursor%20%C2%B7%20Copilot%20CLI-6E56CF)](#-在你的-ai-agent-中使用)
[![Champion](https://img.shields.io/badge/AI4S%20Hackathon-🏆%20Champion-f6c344)](#-荣誉与报道)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[🌐 项目主页](https://asimfish.github.io/global-geochemical-atlas-demo/) ·
[🗺️ 在线图谱](https://asimfish.github.io/global-geochemical-atlas-demo/live/world-atlas.html) ·
[🎬 演示视频](https://asimfish.github.io/global-geochemical-atlas-demo/finals/Global-Geochemical-Atlas-Final-Demo.mp4) ·
[🧪 团队官网](https://chembot.zgca.com/)

[🚀 快速开始](#-90-秒快速开始) ·
[🤖 在 Agent 中使用](#-在你的-ai-agent-中使用) ·
[🏗️ 工作原理](#️-工作原理) ·
[🧭 数据来源](#-数据来源37-个已冻结可执行来源--69-条审计目录记录) ·
[⏳ 时间维度](#-时间维度演变地图与成因归因) ·
[📦 输出产物](#-十八个输出产物) ·
[❓ FAQ](#-faq)

<a href="https://synmatai.cn/hackathon/"><img src="docs/readme/synmatai-champion.png" alt="新研智材 SynMatAI · AI4S Future ScienceSkills Hackathon 冠军 · 词元代理人队" width="640"></a>

<p><img src="docs/readme/orgs-banner.png" alt="上海交通大学 · 北京中关村学院 · 北京航空航天大学 · 浙江大学" width="720"></p>

<img src="docs/readme/atlas-world-map.png" alt="全球地球化学元素图谱交互界面实拍：198,445 条可显示测定的全球分布、异常候选环标与介质覆盖侧栏" width="100%">

<sub>2026-08-19 全球在线生产运行界面实拍：全库 <b>199,730</b> 条测定正式入库 · <b>45,753</b> 个独立物理样品 · <b>35</b> 个公开来源 · <b>3,721</b> 个异常筛查候选（robust-z 筛查候选，非成因结论）。空白区域如实显示数据缺口。<b><a href="https://asimfish.github.io/global-geochemical-atlas-demo/">在线演示 ↗</a></b></sub>

<br><br>

<img src="skills/global-geochemical-atlas/assets/readme-atlas-globe.png" alt="同一份自包含产物内置的可旋转三维地球仪视图，样点立柱颜色与二维地图一致" width="88%">

<sub>同一个自包含 HTML 内置二维世界地图与可拖动旋转的三维地球仪，一键切换；无 CDN、无服务器，断网照常交互。</sub>

</div>

---

## 📌 这是什么

这是一个面向 AI Agent 的**完整科研 Skill**，而不是一张预制地图。给它一个「元素 × 区域 × 介质」请求，Agent 会按 **D1 → D2 → D3** 工作流发现并冻结公开数据源、执行单位与坐标质量控制、在可比背景组内筛查富集/亏损候选，最终交付可审计的标准数据库、证据报告和交互图谱。

**能力一览**——基于公开文献与开源数据平台，自动采集岩石、土壤、沉积物、水体四介质中的元素含量、采样坐标、地质背景与分析方法信息；完成单位统一、空间匹配、质量控制与来源追溯；支持按元素、区域、地质单元和样品类型生成全球或区域分布图、热力图及元素组合对比；同时识别富集与亏损两类异常候选区域。

| 你关心的 | 它保证的 |
|---|---|
| 数据从哪来 | 69 条审计目录记录，其中 37 个已冻结、可执行公开来源、32 个 discovery-only 候选（岩石/土壤/沉积物/水体）；正式记录逐条绑定 DOI/URL、版本、许可、定位与文件 SHA-256 |
| 数值可不可信 | 原值永不覆盖、删失值不插补、批次 QC 逐条重算、五分量置信度并明确声明「不是正确概率」 |
| 结论敢不敢引 | 异常仅作筛查候选并列出竞争解释；跑不齐的范围如实报告缺口，绝不冒充全量覆盖 |
| 能不能复用 | 40+ JSON Schema、十八文件产物契约、自包含 HTML 地图、纯标准库脚本，可脱离本仓库对接；纯 Markdown + 标准库，Claude Code / Codex / Cursor 等运行时零改动挂载 |
| 时间维度呢 | 每条记录带采样时刻三列（`atlas-sampling-time-v1`，发表年不算数）；时间演变四模式是主 `interactive_map.html` 的一级选项；异常富集沿岩性/空间/伴生/时序四条证据线归因「母质高背景 / 疑似人为输入」，证据不足如实不判 |
| Loop 会互相带偏吗 | 当前轮侦察者与质疑者使用独立 fresh-session packet，上一轮记忆只参与选题并留下 hash；第三层由确定性 judge 计分，agent 无权自行准入来源 |
| 图谱后还能做什么 | 用户可在同一 HTML 选择 Auto-Research：冻结图谱后自动生成候选、试点、文献核验、论文骨架、制图契约与独立评审；失败进入不可覆盖的修订轮，通过后仍停在人工批准 |

最近一次全球在线生产运行（2026-08-19，全程自主）：**199,730** 条确定性入库记录 · **45,753** 个独立物理样品 · **35** 个已接入公开来源（另有 31 个候选经审计后拒绝）· **100%** 记录级来源定位链 · **3,721** 个异常筛查候选 · **393** 条未过标准化门禁的记录如实保留、不静默丢弃。结构化运行证据与逐项解读见[项目主页](https://asimfish.github.io/global-geochemical-atlas-demo/)。

## 🎯 设计承诺

六条承诺定义了这个 Skill。每一条都有实现、有回归测试、有文档——这张表就是索引：

| 承诺 | 保证什么 | 实现与文档 |
|---|---|---|
| **完整的 Loop 机制** | 九个研究步骤、三道门禁；验收不过进入五步修复循环；修不动的缺口标记 `needs_human_review`，绝不粉饰 | [Loop 状态机](#loop-状态机发现问题就回头修修不动就承认) · `run_self_correction_loop.py` |
| **三层 Agent 对抗机制** | 数据入口处侦察提名、质疑挑错、确定性裁判计分；出口处金丝雀校准的审计器把关 | [对抗机制](#对抗机制它可以驱动修复但永远不能自我豁免) · `discovery_duel.py` / `agent_audit.py` / `adversarial_audit.py` |
| **每轮评测相对独立** | 评审者在全新线程、跨模型家族运行；跨次记忆只影响第 1 轮调度，运行内证据永远压过记忆——任何一轮都不继承上一轮的结论 | [每一轮保持相对独立](#loop-状态机发现问题就回头修修不动就承认) · `acquisition_memory.py` |
| **SHA-256 数字指纹与结果一一对应** | 哈希锚定冻结请求、来源文件、摘要提交标记内其余 17 个产物、支持的规范断言（`文件 + JSON 指针 + SHA-256`） | [证据链](#证据链每个数字都带指纹) · `claim_ledger.py` |
| **时序演化是图谱内的视图选项** | 每条记录带采样时刻契约（`atlas-sampling-time-v1`）；时间演变四模式与异常成因视图都嵌在主 `interactive_map.html` 内，由同一份标准化数据库驱动——不是独立交付物 | [时间维度](#-时间维度演变地图与成因归因) · `build_temporal_map.py` / `classify_anomaly_provenance.py` · [时序视图在线演示](https://asimfish.github.io/global-geochemical-atlas-demo/live/world-temporal.html) |
| **Auto-research 真实接入** | 图谱运行通过校验后，用户可选择继续进入研究层——分析队列、环境背景、采样优先级，再到可恢复、声明绑定、独立评审且必以打包产物收尾的 Auto-Research | [图谱之后](#图谱之后可选择继续进入研究模式) · [Auto-Research](#从图谱继续-auto-research) · `build_research_products.py` / `auto_research.py` / `serve_atlas_research.py` |

## 🚀 90 秒快速开始

只需 Python 3.10+，**无需网络、密钥、GPU 或任何第三方包**。在仓库根目录运行：

```bash
# 1. 运行生产阈值真实数据演示（996 条 hash 固定的 USGS 土壤测定）
python skills/global-geochemical-atlas/scripts/run_atlas_request.py \
  --request skills/global-geochemical-atlas/fixtures/production-usgs/request.json \
  --demo production-usgs \
  --analysis-profile production \
  --generated-at 2026-08-07T00:00:00Z \
  --output-dir /tmp/geochemical-production-demo

# 2. 校验十八文件产物契约
python skills/global-geochemical-atlas/scripts/validate_outputs.py \
  --output-dir /tmp/geochemical-production-demo
```

两个命令应分别返回 `"status": "partial_success"` 与 `"status": "valid"`。前者是**刻意设计的科学状态**：hash 固定切片完整跑通，但不冒充冻结请求的全量空间覆盖；后者证明十八项产物契约全部有效。

### 或者交给指挥官：一条命令跑完全程

```bash
# 冻结请求 → 任务路由 → 修复循环 → 全部校验 → 对抗审计 → 合规报告
python skills/global-geochemical-atlas/scripts/autopilot.py \
  --prompt-file TASK_PROMPT.txt \
  --output-dir /tmp/atlas-run

# 若运行因修复队列停下，恢复也只需一条命令
python skills/global-geochemical-atlas/scripts/autopilot.py \
  --output-dir /tmp/atlas-run --continue
```

`autopilot.py` 把整份 SKILL 合同压成一条确定性命令：把自然语言诉求冻结为 schema 合法的请求（附可审计的 `freeze_report.json`）、完成任务路由、在授权小时级预算时自动调用自纠错循环（`--time-budget-seconds`）、执行全部校验器与对抗审计，最终产出 `executor_compliance_report.json`——其中的 `final_answer_facts` 是最终回复唯一允许引用的数字。终态机器可读：`DONE | CONTINUE_REQUIRED | NEEDS_HUMAN_REVIEW | FAILED`。

然后用浏览器打开 `/tmp/geochemical-production-demo/interactive_map.html`——一个完全自包含、零 CDN 依赖的交互图谱。

<details>
<summary><b>这条回归验证了什么？（点开看预期指标）</b></summary>

- 996/996 条记录完成 GLiM 岩性地质匹配；
- 72 个背景组中 **12 个达到生产阈值 `n≥20` 完成分析，60 个因样本不足被如实排除**（不降阈值、不硬凑）；
- 识别 6 个 high/low 候选异常；
- 输出校验 0 错误 / 0 警告。

它证明工程与科学规则可执行，不代表美国土壤的统计分布。完整证据见[生产演示说明](skills/global-geochemical-atlas/references/production-demo.md)。

</details>

本地重复基准采用 3 次预热与 10 次独立测量，每次都创建新输出目录并验证全部 18 项产物；结果与适用边界见[工作流性能基准](skills/global-geochemical-atlas/BENCHMARK.md)。它不是官方模型得分或 2 CPU 容器成绩。

## 🤖 在你的 AI Agent 中使用

本 Skill 按 [Agent Skills](https://agentskills.io) 公共子集编写（`SKILL.md` + `references/` + `scripts/` + `assets/`，一层引用、相对路径、纯标准库）。**整个 Skill 就是 Markdown + Python 标准库脚本——没有框架、没有守护进程、没有第三方依赖**，任何能读 `SKILL.md` 的 LLM Agent 都能直接用；换运行时不需要改一行代码：

```bash
# Claude Code（个人技能目录）
cp -r skills/global-geochemical-atlas ~/.claude/skills/

# Codex CLI
cp -r skills/global-geochemical-atlas ~/.codex/skills/

# Cursor（项目级技能目录）
cp -r skills/global-geochemical-atlas /path/to/your-project/.cursor/skills/

# GitHub Copilot CLI（原生 SKILL.md 支持）
cp -r skills/global-geochemical-atlas ~/.copilot/skills/

# OpenCode / Trae / OpenClaw 及其他兼容运行时：将 skill 目录复制/挂载到其技能目录即可
```

### 开箱即用的启动 Prompt

挂载后，一句自然语言即可触发。**下面是默认任务 Prompt**——它完整走一遍全流程，你只需替换三个加粗槽位（比如换个地区）就是自己的任务：

> 只基于公开文献与开源数据平台，为**西欧**构建**土壤**中**砷（As）**元素的分布图谱：自动采集元素含量、采样坐标、地质背景与分析方法信息；完成单位统一、空间匹配、质量控制与来源追溯；生成可按元素、区域、地质单元和样品类型筛选的分布图、热力图与元素组合对比；识别候选的异常富集与亏损区域；并交付可交互元素分布地图、标准化地球化学数据库、数据来源与置信度说明及异常区域识别结果。

| 槽位 | 填什么 | 示例 |
|---|---|---|
| **介质** | 支持四种介质中的一种或多种 | `土壤` · `沉积物` · `水体` · `岩石` |
| **元素** | 元素符号或分析物名称 | `砷（As）` · `Cu` · `Pb` · `Hg` |
| **区域** | `global`、命名区域或 WGS84 边界框 | `西欧` · `中国` · `纬度 30–45，经度 –10–30` |

更简短的说法同样能触发：

> 只用公开数据，为**西欧**做一张**土壤砷**分布图谱：统一单位，标出候选富集区域，并为每条记录附上来源、许可与置信度。

> 用公开来源构建**全球沉积物汞**图谱，用 FDR 控制筛查空间聚集异常，并如实报告所有数据缺口。

对接时的常用参考：

- 激活边界与样例：[`evals/activation.json`](skills/global-geochemical-atlas/evals/activation.json)（含 5 条应激活与 4 条相邻不应激活样例）
- 平台元数据：[`agents/openai.yaml`](skills/global-geochemical-atlas/agents/openai.yaml) · 能力卡片：[`skill-card.md`](skills/global-geochemical-atlas/skill-card.md)
- Agent 的完整执行合同（状态机、门禁、失败状态）：[`SKILL.md`](skills/global-geochemical-atlas/SKILL.md)

## 🧑‍🔬 三种运行方式

### 方式一：使用自己的数据

```bash
python skills/global-geochemical-atlas/scripts/run_atlas_request.py \
  --request /path/to/request.json \
  --input /path/to/measurements.csv \
  --evidence-jsonl /path/to/record_evidence.jsonl \
  --acquisition-manifest /path/to/run_manifest.json \
  --output-dir /tmp/geochemical-output
```

D2 最低分析字段是 `element_or_analyte,value,unit,medium`；完整证据工作流还要求 `source_id,source_locator,license`。非标准列名必须通过显式 schema map 映射，不能靠语义猜测。正式科学运行还应提供样品标识、measurement basis、WGS84/原 CRS、分析与消解方法、检出限、来源层级及文件 SHA-256。

### 方式二：在线采集公开来源

```bash
python skills/global-geochemical-atlas/scripts/run_atlas_request.py \
  --request /path/to/request.json \
  --online-source auto \
  --cache-dir .cache/data \
  --analysis-profile production \
  --output-dir /tmp/geochemical-online
```

`auto` 会对所有与请求兼容的已路由来源确定性分配记录配额，逐源验证 manifest 与 SHA-256 后合并；单源失败不阻塞整体，以已验证子集继续并返回 `partial_success`。下载均有超时、限量、有限重试与缓存，`--offline` 模式只接受已验证缓存。

#### 同一个控制器的三档预算

同一个控制器按预算分三档，档位只改时间与轮数，科学与证据门禁完全一致：

| 模式 | 预算 | 适用场景 | 交付语义 |
|---|---|---|---|
| ⚡ 快速 quick | ≤900 秒（约 15 分钟） | 想先看效果的轻量试跑、官方沙箱评审 | 真实在线采集，产出全部 18 文件；checkpoint 收据，如实标注非全量覆盖 |
| 🚶 标准 standard | ≤3,600 秒 | 单区域/少元素的日常研究 | 两个完整扩采轮次，未收敛时如实返回待继续状态 |
| 🔬 完整 full | ≤43,200 秒 | 显式授权的全球全介质研究（约 2–12 小时） | 唯一能通过 `validate_research_delivery.py` 的正式交付 |

**简单模式一条命令**（全球地图不用等 2–3 小时，先拿一版轻量真实结果）：

```bash
python skills/global-geochemical-atlas/scripts/run_self_correction_loop.py \
  --request /path/to/request.json \
  --online-source auto \
  --analysis-profile production \
  --time-budget-seconds 900 --max-rounds 1 --checkpoint-only \
  --output-dir /tmp/atlas-quick
```

官方自动评审未另给时限时，先生成任务合同并保留 `deadline_seconds=900`；`task_router.py` 会生成 720 秒内部在线检查点，给 Agent 启动、验证和回复预留 180 秒。检查点仍生成可评分的核心产物并如实报告缺口，但不能冒充完整全球研究。

### 方式三：复现四介质离线样例（21 来源 · 1,144 条观测）

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

### 写你自己的 `request.json`

每次运行都由一份冻结请求驱动。从生产 fixture 出发，改几个字段就是你的任务：

```json
{
  "elements": ["As", "Cu", "Ni", "Zn"],
  "region": "global",
  "media": ["soil"],
  "measurement_basis": null,
  "time_range": null,
  "sources": ["usgs-conus-soil"],
  "output_formats": ["csv", "json", "geojson", "html_map"],
  "target_crs": "EPSG:4326",
  "license_policy": "open_only",
  "research_use_policy": "permitted_research",
  "minimum_evidence_tier": "A",
  "minimum_use_mode": "normalized_analysis",
  "max_records": 1000,
  "offline": true
}
```

| 你最可能修改的字段 | 含义 |
|---|---|
| `elements` | 要分析的元素符号，如 `["As"]` 或 `["Cu", "Pb"]` |
| `region` | `"global"`、命名区域或 WGS84 边界框对象 |
| `media` | `soil` / `sediment` / `water` / `rock` 中的一种或多种 |
| `sources` | 固定指定来源 ID；或删除该字段并配合 `--online-source auto` 自动路由 |
| `max_records` | 本次运行的记录上限 |
| `offline` | `true` 只用已验证本地缓存；`false` 允许在线采集 |

逐字段 schema、默认值与状态语义见[请求与输出契约](skills/global-geochemical-atlas/references/request-output-contract.md)。

## 🏗️ 工作原理

「帮我画一张全球土壤砷的分布图谱，并告诉我哪里异常」听上去是个检索任务。放进真实研究团队，它立刻变成四个更难的问题：不同调查、单位与消解方法的数字能不能放进同一张图（**统一指标**）；高值是污染超标还是地质本底（**动态时序**）；几十年前老记录的检出限与坐标系还查得到吗（**质量控制**）；AI 给出的每个数字敢直接引用吗（**来源可回溯**）。这个 Skill 把四类需求统一成一条可信的 Agentic-Native 研究流程。

<img src="docs/readme/slide-03-question.png" alt="一句听起来很简单的提问：帮我画一张全球土壤砷元素的分布图谱" width="100%">

### 机制总图：模型提案，代码裁决

<img src="docs/readme/slide-10-mechanism.png" alt="Skill 机制总图：输入与准入、确定性处理与验证循环、出版审计与模块化交付" width="100%">

整条流水线分三段。**输入与准入**：请求以 SHA-256 冻结，来源经许可/版本/哈希审计，逐记录采集并附证据。**确定性处理与验证循环**：按介质和量纲标准化（固体 mg/kg、水体质量/体积 µg/L），有据转换坐标，再做 QC、GLiM 地质匹配、robust-z 筛查和产物验证；失败进入修复 Loop 重跑比对，`memory.json` 只影响后续调度，不改变本轮判定。**出版审计与模块化交付**：植入缺陷的「考试」校准审计器，规范断言逐条绑定支持的事实与证据。自由文本科学解释另行审查。**模型负责提案，确定性检查执行已声明的规则，不证明科学真实性。**

```mermaid
flowchart LR
    Q[研究问题<br/>元素·区域·介质] --> D1[D1 来源<br/>发现·准入·采集·证据]
    D1 --> D2[D2 数据<br/>标准化·QC·空间匹配·异常]
    D2 --> D3[D3 产品<br/>研究配置·地图·迭代]
    D3 --> O[数据库<br/>证据与置信度<br/>异常结果<br/>交互地图]
    O -. iteration_backlog 驱动的多轮闭环 .-> D1
    O -->|用户选择继续| AR[Auto-Research<br/>试点·文献·论文·图·独立评审]
    AR -->|评审失败·版本化反馈| AR
    AR -->|全门通过| H[人工批准<br/>不自动发表]
```

- **D1** 保存许可、版本、下载请求、文件哈希和记录级定位；来源目录中的候选不等于本次请求可用。
- **D2** 保守处理单位、删失值、坐标、方法、实验室批次与可选地质匹配；先用稳健 MAD z-score 筛记录级高/低值，再用精确超几何检验 + BH-FDR 筛空间聚集。
- **D3** 只消费公共产物，通过版本化 profile 生成全球、国家或 WGS84 bbox 研究视图；从不重算 D2 的科学结果。
- **循环内的三层来源对抗**：每个待修 action group 可生成互相隔离的侦察者与质疑者 packet；上一轮记忆不进入本轮 evaluator context。确定性 judge 只按冻结的七维来源事实计分，agent 结果不能直接准入，所有 packet、input、payload、result 与 judge receipt 均作 SHA-256 绑定。
- **逐声明对账**：正式 delivery receipt 内含 typed claim ledger。展示的记录数、覆盖元素/介质、来源数、删失数、坐标率、异常数和 FDR 区域数均指向精确文件、locator、重算方法与 SHA-256；改数字或改证据都会使 validator 失败。

### Loop 状态机：发现问题就回头修，修不动就承认

<img src="docs/readme/slide-11-loop.png" alt="Skill 的 Loop 状态机：九个步骤、三道门，验收不过走五步修复循环" width="100%">

主线是九个研究步骤、三道门（来源准入、单位坐标 QC、逐项验收），一步不跳。第 09 步验收不过时进入修复循环：**列清问题 → 逐条记入 `iteration_backlog` → 按登记的方法对症修 → 重跑再验收 → 沉淀进跨轮记忆库**。每次修复另开新运行、原始证据不可变；修不动的缺口标记 `needs_human_review` 交人处理，绝不硬凑。可直接用 [`run_self_correction_loop.py`](skills/global-geochemical-atlas/scripts/run_self_correction_loop.py) 启动（见 FAQ），或交给 `autopilot.py` 自动调用；完整协议见[迭代闭环参考](skills/global-geochemical-atlas/references/iteration-loop.md)。

**每一轮保持相对独立。**[跨次运行采集记忆](skills/global-geochemical-atlas/references/acquisition-memory.md)（`memory.json`）跨运行累积每个来源的成败账，但它被刻意设计得无力干预评测：记忆**只重排**技能已经路由的来源、永不新增；种子只影响第 1 轮调度，后续轮次的优先级全部由本次运行自己的修复动作推导；记忆文件是**运行输入**而非 Skill 代码——可审计、可删除、可重建。运行内的证据永远压过运行间的记忆，任何一轮都不会继承上一轮的结论。

### 对抗机制：它可以驱动修复，但永远不能自我豁免

两层对抗分别把守数据的入口与出口。

**入口——来源发现对决。**新数据源入库前要过三个角色（[对决协议](skills/global-geochemical-atlas/references/discovery-duel.md)）：

<img src="docs/readme/slide-13-adversarial.png" alt="对抗审计机制：侦察 Scout 提名候选来源，质疑 Skeptic 只挑问题，裁判 Referee 按明文计分" width="100%">

**侦察员**（模型）面向空白区域提名候选来源——只提名，不审批；**质疑员**（独立模型）逐条检查许可、介质、区域——只提问题，不打分、不决定；**裁判**是确定性代码（`discovery_duel.py`），不产生任何意见，只执行明文计分牌：**≥7 分**放行起草接入 spec，**4–6 分**打回重报，**<4 分**出局。评分通过也只取得起草资格，正式入库仍须具名负责人终审。

**出口——对抗性产物审计。**每次运行结束后，[`adversarial_audit.py`](skills/global-geochemical-atlas/scripts/adversarial_audit.py) 必须先证明自己称职才有资格裁决（[协议](skills/global-geochemical-atlas/references/adversarial-audit.md)）：它先把产物复制成影子副本，按种子确定性植入 **10 类已知缺陷**（数值篡改、单位翻转、删失填补、伪造来源、证据孤儿、哈希损坏、定位越界、URL 掉包、坐标交换、异常 z 值篡改），先审影子副本这场「考试」。只有**全部抓到（recall = 1.0）**，它对真实产物的裁决才可采信；有漏网则自动降级为 `inadmissible_calibration_failed`，不允许出具 PASS。裁决分三级——`pass` / `pass_scope_narrowed` / `fail`——warning 不杀稿，而是强制收窄引用口径：受影响数字只能连同范围句一起出现。

**审计独立性靠契约保证，不靠信任。**双 Agent 模式下，审计简报携带机读 `reviewer_contract`：质疑员必须来自与执行者**不同的模型家族**，必须在**全新线程**中工作（无共享记忆、不接收 Builder 的任何叙述）、只读产物字节、先通过同一场金丝雀考试，且当简报中任何路径或 SHA-256 校验不符时**必须拒审**。已确认的发现回流修复队列、驱动下一轮循环——对抗结果推动流水线前进，而不是停在报告里。

**循环内——隔离的来源审计。**在入口与出口之间，[`agent_audit.py`](skills/global-geochemical-atlas/scripts/agent_audit.py) 对每个待修 action group 施行同一套纪律（[合同](skills/global-geochemical-atlas/references/adversarial-agent-audit.md)）：控制器在 `agent_audits/round-…/` 下写出侦察者与质疑者两份 packet，宿主为每个角色分别启动全新会话且只读各自的 `packet.json`，二者都不能评分或准入。第三层 `agent_audit.py judge` 从冻结事实确定性计分，结果仍须通过 D1 门禁和具名人工批准。相同 `invocation_id`、角色/packet 替换、未知输入或任一 hash 变化均失败关闭。

### 证据链：每个数字都带指纹

信任在四个环节锚定 SHA-256，让结果与证据一一对应：

1. **请求冻结**——任务本身在执行前先被哈希，中途目标漂移可被发现；
2. **来源文件**——每个下载文件入库前都要通过记录在案的哈希校验；
3. **产物**——`run_summary.json` 是十八文件事务的提交标记，记录其余 17 个产物哈希，不包含自身；评审契约在哈希不符时拒审；
4. **断言**——[`claim_ledger.py`](skills/global-geochemical-atlas/scripts/claim_ledger.py) 从当前产物重建支持的断言。先用 `--run-dir OUT --render-answer NEW_ANSWER.md` 生成新证据附录，再用 `--run-dir OUT --check-answer NEW_ANSWER.md` 核验。`atlas-answer-binding-v2` 仅接受原样规范行：断言身份、语义、JSON 类型/值、完整范围句、证据定位/hash 与整条断言 digest。无效断言、改字段、重复、追加说明和空答复均失败关闭。这是对旧自由文本接口的有意收紧，不再用数字碰巧相同、计数容差、小整数或年份豁免来认证答复。补充说明单独审查，不能把附录通过宣称为全文或科学结论已认证。
5. **交付收据**——正式研究交付另带由 `report_claim_ledger.py` 生成的 typed claim ledger；`validate_research_delivery.py` 逐条从内容寻址产物重算，正式交付引用不了自己文件不支持的数字。

### 图谱之后：可选择继续进入研究模式

图谱是检查点，不是终点。在任何一次**已完成并通过校验**的运行之上，一条命令即可叠加可选的研究后处理层（[research mode 契约](skills/global-geochemical-atlas/references/research-mode.md)）：

```bash
python skills/global-geochemical-atlas/scripts/build_research_products.py \
  --output-dir /tmp/atlas-run \
  --research-dir /tmp/atlas-run/research \
  --minimum-confidence medium
```

它不采集新数据、不修改任何核心产物，只把已有证据确定性地重组为三类研究者产品——**分析队列**（`analysis_cohorts.csv`：哪些记录可以相互比较、哪些不能、为什么）、**环境背景**（`research_context.csv`：逐样品的岩性、地质单元、沉积环境、深度、粒级与采样时间）、**采样优先级**（`sampling_priority.geojson`：把数据缺口排序成下一批采集队列）——外加一份 model-card 式收据（`research_products_receipt.json`，含输入哈希、参数与不可宣称事项）。同样的续跑在冻结快照上走得更远，就是下文[五篇论文初稿](#-从图谱到论文科学发现层)的来源。

### 从图谱继续 Auto-Research

`interactive_map.html` 的 Auto-Research 选项会把当前十八文件冻结成内容寻址快照，然后生成可比研究队列、确定性选题、行级试点合同、原始文献核验队列、科学机会门、贡献优先论文骨架、数据主图契约和五篇候选研究计划。只有已执行的 effect/null 试点与经核验的前沿增量同时成立，才创建写作和绘图任务；缺数据、只需采集、分析无效或选题前沿性弱会停在 `needs_research_redirection`，不会拿修订轮润色成论文。静态页面只导出请求；要真实创建可恢复任务，运行：

```bash
python skills/global-geochemical-atlas/scripts/serve_atlas_research.py \
  --atlas-dir /tmp/geochemical-output \
  --research-root /tmp/geochemical-research
```

本地服务只绑定 `127.0.0.1`，使用 URL fragment token、单次 nonce、Host/Origin 校验和固定 JSON API。外部 agent 宿主按 `state.json.required_roles` 为试点、文献、写作、绘图和 reviewer 分别启动新会话，并通过 hash-bound payload 推进状态。写作必须提交 2–5 项 claim-bound 贡献；绘图必须提交 primary/spatial/robustness 三类数据主图，分别绑定真实 SVG/PDF/PNG 及检查修改记录。评审使用 controller 固定的科学有效性、新颖性、前沿适配、论文论证、视觉证据等七门 0–4 分量表；失败会自动开启新的 `revision-NN`，只把结构化反馈交给修订角色，下一轮 reviewer 不接收旧评语或 executor summary。选定研究方向是唯一人工输入：全部七门通过后控制器校验各产物哈希并自动打包 `publication/`（等级 `camera_ready`，终态 `completed_published`）；三轮修订或引用修复预算用尽则以 `draft_with_disclosed_findings` 等级打包，未解决反馈逐条写入 `publication_manifest.json`（终态 `completed_with_findings`）；科研机会门失败则把该尝试归档到 `attempts/` 并在同一 run 内改道回退队列中的下一个实证候选；候选耗尽也绝不空手——有已执行试点就还原最佳一次、披露前沿弱点写成草稿（等级上限 `draft_with_disclosed_findings`），完全无法执行则自动产出经评审的数据充分性与研究方向报告（等级 `evidence_report`，终态 `completed_evidence_report`）。详见 [Auto-Research 运行合同](skills/global-geochemical-atlas/references/auto-research.md)。

## ⏳ 时间维度：演变地图与成因归因

环境监测最大的争议是「超标还是高背景」——比如某地土壤砷本底天然就高，按通用阈值筛就是假异常。本 Skill 从三个层面回答这个问题：

<img src="skills/global-geochemical-atlas/assets/readme-temporal-map.jpg" alt="时间演变交互地图·区域对比模式：5° 网格早晚两期中位含量对比，红=上升、蓝=下降，可拖动分割年，虚线暗格如实标注仅单期观测" width="100%">

<sub>时间演变地图默认模式「区域对比」：同一个 5° 格子早晚两期实测中位含量直接对比（红升 / 蓝降 / 灰平），拖动分割年实时重算；点击格子看该区域的含量—时间散点。只有单期观测的格子如实画成虚线暗格。</sub>

<br><br>

<img src="skills/global-geochemical-atlas/assets/readme-anomaly-provenance.jpg" alt="异常成因模式弹窗：四条证据线（岩性/空间/伴生元素/时序）各给通俗解释，两条同向才下母质或人为结论，否则如实标注证据不足" width="88%">

<sub>「异常成因」模式：每个富集候选沿岩性 / 空间 / 伴生元素 / 时序四条证据线归因，每条给一句通俗解释；至少两条同向才判「母质高背景」或「疑似人为输入」，证据不够就明说不判——不会把高背景硬扣成污染。</sub>

- **采样时刻契约**（`atlas-sampling-time-v1`）：`sampling_time` 记录样品被采集那一刻，发表年一律不算；逐源声明取值字段与格式，发布方没报就如实标 `publisher_not_reported`。
- **时间演变选项**（`interactive_map.html#temporalView`）：区域对比 / 异常成因 / 含量着色采样史回放 / 站点演变四模式完整嵌在主图；`temporal_map.html` 仅保留为相同字节的兼容镜像。
- **成因归因**（`anomaly_provenance.json`）：时序证据线的规则很直白——同一点位含量随时间明显上升支持「人为输入」，长期平稳支持「母质决定」；与岩性、空间、伴生元素三条线合议。

## 📦 十八个输出产物

每次完整运行固定生成 18 个文件，逐文件 schema 与状态定义见[请求与输出契约](skills/global-geochemical-atlas/references/request-output-contract.md)：

| 交付类别 | 运行产物 | 核心保证 |
|---|---|---|
| **可交互元素分布地图** | `interactive_map.html` · `samples.geojson` | 唯一主产品体验，自包含零 CDN；按元素、介质、区域、地质单元、样品类型、方法与置信度筛选；样点、热力图、元素组合对比与异常候选视图，时序演化和 Auto-Research 均为同一主导航的一级选项 |
| **时序兼容镜像** | `temporal_map.html` | 完整四模式字节嵌入主图，只为旧链接/单页下载保留；主导航不跳转独立文件，无采样时刻的记录绝不假装有时间 |
| **标准化地球化学数据库** | `geochemistry.csv` · `batch_acceptance.csv` | 保留原值与换算轨迹；统一单位、basis、坐标、方法、分析批次与 QC 字段；含 `atlas-sampling-time-v1` 采样时刻三列（采样那一刻的含量，发表年不算），支持时序查询 |
| **数据来源与置信度说明** | `source_manifest.json` · `record_evidence.jsonl` · `confidence_report.json` · `sources_and_confidence.json` | URL/DOI、许可、版本、哈希、源记录定位与五分量置信度全程可追溯，另附面向读者的合并摘要 |
| **异常区域识别结果** | `anomalies.geojson` · `anomaly_report.json` · `anomaly_regions.geojson` · `spatial_anomaly_report.json` · `anomaly_provenance.json` | 记录级 robust-MAD 候选 + 精确超几何/BH-FDR 空间筛查，覆盖富集与亏损两向；每个富集候选沿岩性/空间/伴生/时序四条证据线归因「母质高背景 / 疑似人为输入 / 混合 / 证据不足」，每条证据线给通俗解释 |
| **质量与运行证据** | `qc_report.json` · `batch_qc_report.json` · `iteration_backlog.csv` · `run_summary.json` | 逐项 QC 留证、失败批次绝不静默删除、迭代待办与全运行摘要（含各产物哈希） |

第五类交付「可复用 Skill 文档」即 [`SKILL.md`](skills/global-geochemical-atlas/SKILL.md) 本体及其 schema、脚本与 fixture。选择[继续进入研究模式](#图谱之后可选择继续进入研究模式)时，会在独立的 `research/` 目录追加 `analysis_cohorts.csv`、`research_context.csv`、`sampling_priority.geojson` 与收据，不触碰核心契约。

## 🧭 数据来源（37 个已冻结可执行来源 · 69 条审计目录记录）

| 介质 | 已冻结可执行来源 |
|---|---|
| 🪨 岩石 | GEOROC（太古宙克拉通、汇聚边缘、南极板内火山岩）· EarthChem Library 3338（中国东昆仑德海龙岗岩石）· Gard 2019 全球全岩汇编 |
| 🌱 土壤 | USGS DS801（美国本土）· GEMAS（欧洲）· FOREGS 表土/底土/腐殖质 · AfSIS Phase I（撒哈拉以南非洲）· PANGAEA 北非/巴伦支海沿岸/Amazonas/Batagay/BraSol · TPDC 中国山地 · EIDC 宁波 · Figshare 长江流域 |
| 🏞️ 沉积物 | FOREGS 河流/洪泛平原沉积物 · GSJ 日本地球化学图/日本海洋沉积物 · 澳大利亚 NGSA（多元素与 Hg 产品）· 挪威 MarChem · PANGAEA 阿拉伯海/东海/南海 · Zenodo 长江/黄河沉积物 · 4TU 中国北方/西北沉积物（准噶尔、塔里木、柴达木、河套、阿拉善与青藏高原东部） |
| 💧 水体 | FOREGS 河水 · GEMStat 全球内陆水 · GEOTRACES IDP2025 海水 · 美国 WQP 萨克拉门托河（As）· 珠江 81 站丰/枯水期溶解金属 · 闽粤沿海 124 口井地下水 |

37 个 executable source 已完成版本冻结、下载/解析契约与证据评分；69 条 catalog 记录是总目录，其中另外 32 条仍为 discovery-only，不能与正式入库来源重复相加。每个来源的 DOI、版本、许可、科研使用条件、字段边界与八维证据评分记录在[来源目录](skills/global-geochemical-atlas/references/data-sources.md)、[来源准入标准](skills/global-geochemical-atlas/references/source-acceptance-standard.md)与[许可引用说明](skills/global-geochemical-atlas/references/licenses-and-citations.md)；中国区域双源 fixture（TPDC 全量 + Zenodo 7098563）的登记与重建见[中国区域 fixture](skills/global-geochemical-atlas/references/china-fixture.md)。EarthChem 等联邦检索站仅作**发现层**：只有追溯到原始记录后才能作为测量证据。

## 🛡️ 科学护栏

- 原值、原单位、qualifier、来源坐标表达与转换记录始终保留；不能证明的转换一律失败关闭。
- 固体质量比可统一为 `mg/kg`，水体质量/体积可统一为 `ug/L`；`nmol/L` 只对冻结原子量表中的明确元素换算，缺少摩尔质量或密度证据时失败关闭。
- `<LOD`、`<LOQ`、`BDL`、`ND` 不替换为 0 或 LOD/2。
- CRM、空白、重复样按显式 policy 重算；失败批次保留在数据库，但不进入异常背景。
- 不静默交换经纬度，不把未知 CRS 冒充 WGS84；版本化平台坐标政策要求 DOI、字段名、URL 与内容哈希同时匹配，空间匹配记录数据源、版本、方法与边界距离。
- 背景组样本不足时如实返回 `insufficient_background`，绝不降阈值硬算（上方 demo 中 72 组只分析达标的 12 组）。
- 异常点与 FDR 网格均只表示筛查候选；网格不是地质/行政/污染边界，不等于污染、矿床或成因结论。
- demo 与真实来源切片只用于工程复现，不支持全球或区域代表性的科学结论。

## 🧾 三重真实运行验证

除仓库内的离线回归外，本 Skill 经过三组相互独立的真实运行检验，覆盖不同风险面（证据文件均可在[项目主页](https://asimfish.github.io/global-geochemical-atlas-demo/)核查）：

| 运行 | 验证内容 | 关键结果 |
|---|---|---|
| 全球在线生产运行（2026-08-15） | 真实网络条件下的自主采集、失败处置与缺口报告 | 33 分钟全自主：63 个来源候选审计 → 31 正式接入 → 29 实际入库；两个 GEOROC 端点持续 HTTP 500，如实记录；238 项待修复项全部登记进修复队列 |
| 确定性回归（`main@ed8249e`） | 全新克隆环境中产物能否逐字节复现 | 0.714 秒完成回归：996/996 条地质匹配、6 个异常候选逐字节一致；hash-bound 快照防止跨环境漂移 |
| 对抗审计（2026-08-20） | 红队向产物影子副本植入 10 类缺陷（数值篡改、单位翻转、伪造声明等），校准审计层检出能力 | 10/10 全部捕获；幻觉数字「25000」被判 `answer_unbound`——没有证据绑定的数字不允许出场 |

三组结果各自独立口径，不作混合统计。证据入口：[`run_summary.json`](https://asimfish.github.io/global-geochemical-atlas-demo/finals/real-run/run_summary.json) · [`audit_receipt.json`](https://asimfish.github.io/global-geochemical-atlas-demo/finals/audit-run/audit_receipt.json) · [`claim_ledger.json`](https://asimfish.github.io/global-geochemical-atlas-demo/finals/audit-run/claim_ledger.json)。

## 🌏 实测效果：同一套 Skill，四个分析域

<img src="docs/readme/slide-15-four-regions.png" alt="世界、中国、欧洲、美国四个分析域的实际运行结果" width="100%">

同一套方法在四个地区真实运行，不改一行代码：**世界** 198,445 条可显示测定 / 3,446 条待复核异常；**中国** 24,536 条 / 740 条异常 / 78 个集中区域；**欧洲** 47,459 条 / 981 条；**美国** 91,458 条 / 1,398 条。各地区按各自范围统计，不能与全球总数直接相加或对比。每张图都是自包含 HTML，可在线打开逐项核查：

[世界图谱](https://asimfish.github.io/global-geochemical-atlas-demo/live/world-atlas.html) ·
[中国图谱](https://asimfish.github.io/global-geochemical-atlas-demo/live/china-atlas.html) ·
[欧洲图谱](https://asimfish.github.io/global-geochemical-atlas-demo/live/europe-atlas.html) ·
[美国图谱](https://asimfish.github.io/global-geochemical-atlas-demo/live/us-atlas.html) ·
[时序演化图谱（1986–2024）](https://asimfish.github.io/global-geochemical-atlas-demo/live/world-temporal.html)

其中**时序演化视图**是图谱可视化的选项之一，而非独立交付物：它由同一份标准化数据库驱动，当记录具备可靠采样时间时，联合方法分层、地质背景、剖面对照与多期观测，把「高值是地质富集，还是工业活动」变成可检验的问题——把稳定的地质高背景与随工业活动变化的人为富集信号分开检验。

## 🔭 从图谱到论文：科学发现层

<img src="docs/readme/slide-18-papers.png" alt="从图谱扫描、提出选题、试点验证、文献核对、多角色接力到独立审稿的完整科研流水线" width="100%">

图谱不是终点。discovery_mode 在同一份冻结快照（191,715 条 / 29 源）上走完整条流水线：**图谱扫描发现现象 → 31 个候选选题按证据挑选 → 小样本试点验证（站不住的题当场停掉）→ 复现闸门与文献核对 → 多角色接力成稿 → 独立审稿并把缺口回灌采集队列**。已完整跑通五次，成稿 5 篇论文初稿（46 页 · 24 图 · 9 表），每个数字均可由快照 + 固定种子脚本确定性重放：

1. [欧洲土壤剖面 Hg/Pb 遗留富集的方法分层筛查](https://asimfish.github.io/global-geochemical-atlas-demo/research/P1-comparability-aware-screening-europe.pdf)
2. [表层遗留富集并非全球常态：澳大利亚土壤的检验](https://asimfish.github.io/global-geochemical-atlas-demo/research/P2-hemispheric-contrast-australia.pdf)
3. [同一份土样、两种方法可差三倍：跨方法偏移的量化与换算](https://asimfish.github.io/global-geochemical-atlas-demo/research/P3-method-transfer-models.pdf)
4. [两个独立调查是否一致：全球砷图的地面验证](https://asimfish.github.io/global-geochemical-atlas-demo/research/P4-arsenic-validation.pdf)
5. [零调参能否恢复已知海洋学结构：GEOTRACES 剖面提取与方法审计](https://asimfish.github.io/global-geochemical-atlas-demo/research/P5-geotraces-audit.pdf)

五篇均为筛查级（screening-level）结论：富集 ≠ 污染定论，剖面形态 ≠ 机制证明，正式投稿前需领域专家复核。路线图见[五篇论文规划](https://asimfish.github.io/global-geochemical-atlas-demo/research/five-paper-roadmap.md)。

## 📊 与同类数据库的定位

<img src="docs/readme/slide-19-comparison.png" alt="GGA 与 GEOROC、EarthChem、USGS NGDB、GEOTRACES 等数据库的能力对比表" width="100%">

诚实前提：不与机构级规模竞争。GEOROC / EarthChem / NGDB 强在体量与存档，专题调查库强在库内一致性；GGA 补的是它们之间缺失的**统一数据层**——四介质一表、逐行 lineage 与 SHA-256、记录级许可与四维置信度、缺口以机器可读采集队列输出。本节引用的外部数字均已核对官方页面（查阅日期 2026-08-20），逐项出处见 [database-comparison.md](https://asimfish.github.io/global-geochemical-atlas-demo/research/database-comparison.md)。

## 📚 文档导航

| 如果你想…… | 从这里开始 |
|---|---|
| 在浏览器里体验完整交互图谱 | [项目主页](https://asimfish.github.io/global-geochemical-atlas-demo/) |
| 让 Agent 执行完整任务 | [Skill 入口](skills/global-geochemical-atlas/SKILL.md) |
| 为单阶段或完整任务生成最小命令计划 | [任务合同 schema](skills/global-geochemical-atlas/references/task-contract.schema.json) |
| 对接输入或消费 18 个输出 | [请求与输出契约](skills/global-geochemical-atlas/references/request-output-contract.md) |
| 从图谱启动可恢复研究流程 | [Auto-Research 运行合同](skills/global-geochemical-atlas/references/auto-research.md) |
| 审计三层 agent 独立性与准入边界 | [对抗式来源审计合同](skills/global-geochemical-atlas/references/adversarial-agent-audit.md) |
| 理解数据库字段与专业平台 crosswalk | [数据模型](skills/global-geochemical-atlas/references/data-model.md) |
| 审查单位、删失值、置信度和异常规则 | [科学规则](skills/global-geochemical-atlas/references/scientific-rules.md) |
| 复现真实数据生产阈值闭环 | [生产演示](skills/global-geochemical-atlas/references/production-demo.md) |
| 定制全球、区域或元素组合地图 | [D3 可视化契约](skills/global-geochemical-atlas/references/d3-visualization-contract.md) |
| 做多轮迭代修复 | [迭代闭环协议](skills/global-geochemical-atlas/references/iteration-loop.md) |
| 修改 D1/D2/D3 或提交 PR | [贡献指南](CONTRIBUTING.md) |
| 复现离线工作流性能基线 | [性能基准](skills/global-geochemical-atlas/BENCHMARK.md) |

## 🧪 开发与验证

| 入口 | 验证内容 |
|---|---|
| `component_test.py --component all` | D1/D2/D3 公共接口与契约边界（677 项检查：D1 447 · D2 63 · D3 167） |
| `component_test_more.py` | autopilot、对抗审计、断言台账、跨次记忆、来源对决与声明式适配器（60 项检查） |
| `self_test.py` | 科学边界、异常输入与两次运行字节级确定性（76 项检查） |
| `run_self_correction_loop.py --self-test` | 在线扩采、独立样品、尺度自适应及逐筛选视图空间充分性决策（117 项检查） |
| `benchmark_workflow.py` | 可重复的离线工作流性能基线 |

```bash
# 全仓格式、lint 与公共契约类型门
ruff check .
ruff format --check .
mypy --config-file mypy-critical.ini

# D1/D2/D3 公共接口与契约
python skills/global-geochemical-atlas/scripts/component_test.py --component all

# autopilot、对抗审计、断言台账、跨次记忆、来源对决与声明式适配器
python skills/global-geochemical-atlas/scripts/component_test_more.py

# 端到端离线回归
python skills/global-geochemical-atlas/scripts/self_test.py

# 在线研究循环策略
python skills/global-geochemical-atlas/scripts/run_self_correction_loop.py --self-test

# 重复执行并验证完整离线工作流性能
python skills/global-geochemical-atlas/scripts/benchmark_workflow.py \
  --warmups 3 --runs 10 \
  --output /tmp/gga-workflow-benchmark.json
```

可把 `all` 换成 `d1`、`d2` 或 `d3` 单独验证责任域。每个脚本都提供稳定的 `--help`；路径归属、接口变更规则与完成定义见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。以上门禁在每个 PR 和 `main` 推送上由 GitHub Actions 自动执行。

## ❓ FAQ

<details>
<summary><b>完全离线能用吗？</b></summary>

能。90 秒 demo、四介质样例与全部测试都基于 hash 固定的本地切片，零网络、零第三方包。在线采集只在显式传入 `--online-source` 时发生，且 `--offline` 模式只接受已验证缓存。

</details>

<details>
<summary><b>返回 <code>partial_success</code> 是失败吗？</b></summary>

不是。它是刻意设计的科学状态：已验证子集完整跑通并交付，但不冒充冻结请求的全量空间覆盖。缺口、排除原因与下一步建议都写在 `run_summary.json` 里。只有全部范围通过验证才返回 `success`。

</details>

<details>
<summary><b>异常候选可以直接当矿化/污染结论用吗？</b></summary>

不可以。所有异常均为 screening-only 候选：自然背景、采样偏差、空间自相关、方法差异与人为输入都是竞争解释。任何成因解释都需回看原记录与 QC、做尺度敏感性分析，并取得采样设计、分析质量与地质/矿物学的独立证据。

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

控制器先做早期门禁（路由可行性、最低输入列），每轮独立产出并校验十八文件契约，自动重试瞬态获取失败，把 schema/许可/坐标等需要证据的问题分组写入 `loop_report.json` 的修复计划；收敛、无进展或预算用尽时诚实停机。人工修复后在同一目录重新调用即可续跑。canonical 数据不可变，每轮生成新版本；删失值等 `scientific_limit` 不计入修复率——科学限制不能靠循环「修」掉。协议详见[迭代闭环](skills/global-geochemical-atlas/references/iteration-loop.md)。

</details>

<details>
<summary><b>如何新增一个数据源？</b></summary>

按 D1 准入流程：登记来源目录（DOI/版本/许可/科研使用条件）→ 编写来源适配器 → 通过八维证据评分与快照 hash 验证 → 30 条记录具名人工复核后方可进入 `benchmark_ready`。详见[来源准入标准](skills/global-geochemical-atlas/references/source-acceptance-standard.md)与[贡献指南](CONTRIBUTING.md)。

</details>

<details>
<summary><b>为什么坚持零第三方依赖？</b></summary>

评测与生产沙箱环境不可控。纯标准库意味着没有安装失败、没有版本冲突、没有供应链风险；交互地图同样自包含（无 CDN），断网可开。

</details>

## 🏆 荣誉与报道

- 🏆 **[新研智材 SynMatAI · AI4S Future ScienceSkills Hackathon](https://synmatai.cn/hackathon/) 冠军**（词元代理人队）
- 🎬 [主讲幻灯片](https://asimfish.github.io/global-geochemical-atlas-demo/slides.html)（22 页 HTML，含完整机制讲解与实测结果）· [海报 PDF](https://asimfish.github.io/global-geochemical-atlas-demo/finals/Global-Geochemical-Atlas-Poster.pdf)
- 📕 [小红书项目介绍](https://xhslink.cn/o/7EMuFyOOsO5) · 📘 [知乎专栏文章](https://zhuanlan.zhihu.com/p/2073539526404879853)

## 👥 团队

**词元代理人队** —— 五名博士生，覆盖机器学习、具身智能、三维重建与实验室自动化：

| 成员 | 单位 | 方向 |
|---|---|---|
| 李雨峰 | 上海交通大学 | 图机器学习、具身智能与最优传输理论（师从严骏驰教授） |
| 王培朔 | 上海交通大学 | 视觉-语言-动作（VLA）模型与化学实验室自动化（师从吴帆教授） |
| 郭欣睿 | 北京航空航天大学 | 人工智能；材料与 AI 交叉背景 |
| 白丰硕 | 上海交通大学 | PAIR-Lab；师从杨耀东、温颖两位教授 |
| 李明伟 | 浙江大学 | 三维（3D）与四维（4D）场景重建及生成式模型 |

团队主页：[chembot.zgca.com](https://chembot.zgca.com/)

## 🤝 贡献

欢迎 Issue 与 PR。修改 D1/D2/D3、新增数据源或调整契约前，请先阅读[贡献指南](CONTRIBUTING.md)（路径归属、接口变更规则、完成定义）与[架构文档](ARCHITECTURE.md)；所有 PR 须通过 CI 的 lint、类型与 930 项测试门禁。

## 📄 License 与引用

代码与原创文档采用 [MIT License](LICENSE)。外部数据仍遵守各自许可、署名与再分发条件；发布结果前请检查运行生成的 `source_manifest.json`。

如果本项目对你的研究或工程有帮助，欢迎引用：

```bibtex
@software{gga_skill_2026,
  author = {Li, Yufeng and Wang, Peishuo and Guo, Xinrui and Bai, Fengshuo and Li, Mingwei},
  title  = {Global Geochemical Atlas Skill: A Reusable Research Skill for AI Agents},
  year   = {2026},
  url    = {https://github.com/asimfish/global-geochemical-atlas-skill}
}
```

<div align="center">
<sub>用公开数据说话，让每个数字可追溯。</sub>
</div>
