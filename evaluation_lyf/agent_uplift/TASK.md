# Qwen3.8-Max Skill uplift blind-browser public case v4

本任务评估 `global-geochemical-atlas` Skill 是否能让 Agent 更完整、可信地完成全球地球化学图谱工作流。
不得读取仓库中的 `evaluation_lyf/stage_benchmark/scripts`、`evaluation_lyf/reference_implementation`、
任何 `gold`、历史运行或另一实验臂产物。

## 1. 冻结请求

必须按以下请求执行，不得把固定输入所在区域误写成任务范围：

```yaml
region: global
elements: [As, Cu, Fe, Ni, Pb, Zn]
media: [rock, soil, sediment, water]
sources: auto
scope: bounded_best_effort
license_policy: open_or_research_reusable
target_crs: EPSG:4326
max_records: 50000
```

“全球”表示执行全球来源发现并如实报告观测覆盖，不表示一次运行可以收齐全球数据。不得把记录数、全球底图或
数据源自称的全球范围写成完整全球覆盖。未检索到不等于不存在。

## 2. 固定真值锚点不是数据全集

先运行：

开发 bundle 中可用以下命令作冒烟反馈；formal bundle 从启动前就不包含 scorer，候选不得寻找、还原或代写评分器：

```bash
python public_case/prepare_case.py --output-dir case_data
```

脚本下载五个 hash 固定的真实开放资源：四个地球化学数据锚点和一个 GLiM 地质背景锚点。它们用于：

- 逐记录来源真实性、单位、坐标、删失、地质匹配和可复现性抽检；
- 保证 B0/S0 至少共享一组完全相同的输入；
- 在外部来源临时不可用时保留可评分的最低真实数据子集。

它们**只是最低真值锚点，不是允许使用的全部来源，也不是全球覆盖分母**。四个地球化学锚点没有岩石介质，
仅处理这四个文件不能完成本任务的 D1。

## 3. D1 有界多平台发现与采集

在允许访问公开科学数据源的采集阶段，按 `public_case/discovery_contract.json` 执行可复现的多平台发现。
至少检索 EarthChem/PetDB/GEOROC、USGS、PANGAEA、GEMStat、国家或区域地球化学调查等适用候选；候选不可访问、
许可不清、字段不兼容或区域/介质不匹配时保留拒绝或失败记录，不得为了数量伪造来源。

公开开发门槛是最低合约，不是“达到即完整”：

- 记录至少 8 个候选来源、5 个平台的实际检索或审计结果；
- 最终使用至少 6 个经文件 hash 验证的地球化学数据集，其中至少 2 个在固定锚点之外；
- 最终来源至少覆盖 3 个独立平台，并新增至少 1 个可验证岩石来源；
- 四种介质 `rock/soil/sediment/water` 和六个目标元素均有实际观测；
- 新增来源合计至少 200 条测定、30 个可区分样品；
- 对每个候选记录 `selected/rejected/failed`、查询、版本、许可、访问时间、原因与覆盖贡献；
- 采集文件放入 `case_data/discovered/`，并生成 `case_data/discovered_manifest.json`，逐文件记录 bytes 和 SHA-256。

达到上述数量门槛后**不能自动停止**。在 240 秒来源发现/元数据审计预算、150 MB 新增下载上限和 50,000 条
最终测定上限内，只要仍有可验证候选能新增“介质 × 元素 × 区域 × 平台”覆盖、改善坐标/方法/地质字段完整率，
或提供独立交叉来源，就继续采集。优先补齐缺失介质、元素和大区，再提高已有单元密度；不得按最易下载的数据堆积
记录数。`discovery_report.json` 必须记录开始/截止时间、实际主动发现秒数、停止原因、剩余候选和每个入选来源的
边际覆盖贡献。若原始合格记录超过 50,000，使用预先声明、固定随机种子或稳定排序的分层抽样，保留来源/平台/
介质/元素/区域的稀有单元，并报告入选和排除数；不得只保留最密集区域。

下载传输时间单列且不计入 900 秒处理时间；来源规划、解析、标准化、空间匹配、统计与制图仍计入执行时间。
完成采集后冻结 `case_data/`，D2、D3、公开 scorer 和 clean rebuild 均在无网络条件下运行。若某来源失败，使用已验证
子集继续并报告 `partial_success`；不得用合成点填补介质或区域空白。

## 4. 必需输出

在 `submission/` 生成以下产物。

### D1：来源、覆盖和记录证据

- `d1_raw.csv`：一行一个样品 × 元素测定，保留原值、原单位、限定符、reported/canonical 坐标、介质、
  样品类型、地质背景、分析方法、来源定位、版本、许可和文件哈希；
- `discovery_report.json`：冻结请求、候选来源、检索平台、查询、选择/拒绝/失败原因和 claim boundary；
- `coverage_report.json`：按来源、平台、元素、介质、洲/区域统计测定数、唯一样品数、reported/canonical
  坐标数、方法/地质完整率和覆盖空洞；
- `source_manifest.json`、`record_evidence.jsonl`：数据集级和记录级证据链。

固定锚点字段必须与 `public_case/sources.json` 和 `case_manifest.json` 精确一致。新增来源必须与
`case_data/discovered_manifest.json` 的本地文件、bytes、SHA-256 和权威元数据一致。`source_locator` 必须定位到
行、事件、字段、元素、页码或表号，不能只指向首页。未报告的方法、地质、单位、CRS 或精度使用显式状态，
不得编造。

### D2：标准化、空间匹配、QC 和异常

- `geochemistry.csv`、`qc_report.json`、`confidence_report.json`、`geology_report.json`；
- `anomalies.geojson`、`anomaly_report.json`。

固体质量比统一为 `mg/kg`，水体质量/体积统一为 `µg/L`；只有元素身份和量纲证据充分时才做摩尔质量换算。
未知或不兼容单位必须显式失败关闭，不能为追求 `UNSUPPORTED_UNIT=0` 猜测单位。保留删失语义；未经证明的 CRS
不得写入 canonical WGS84；可使用版本化、URL/hash 可追溯且精确限定 DOI/字段范围的平台坐标政策，不得仅凭
经纬度数值形态推断。对适用陆地固体执行版本化地质匹配；水体和明确海洋沉积物不得赋陆地岩性。
异常只能称相对已声明可比背景的候选 high/low，不得声明污染、矿化或成因。

canonical 地质字段以 `public_case/benchmark_export_crosswalk.json` 为准。旧版 `spatial_geology_*` 只作只读兼容，
不得为了 scorer 把 benchmark alias 写回或污染标准化数据库。

### D3：研究型交互产品

- `interactive_map.html`、`samples.geojson`、`source_confidence.json`。

地图必须离线自包含并由真实输出驱动，支持按元素、区域、地质单元、介质、样品类型、来源和置信度筛选，包含
全球/区域分布、样点密度热力图、元素组合对比、high/low 异常和记录级来源下钻。必须分别显示测定记录数、
唯一样品数和唯一坐标数；空白区域表示未覆盖，不表示元素不存在。

### 复现与报告

- `run.sh`：在无网络条件下，从冻结的 `case_data/` 一次重建全部输出；
- `agent_report.md`、`agent_report.json`：记录命令、模型、Skill 使用状态、下载/执行耗时、失败案例、局限与
  `success/partial_success`；
- clean rebuild 不得复制已有结果冒充重建。

## 5. 禁止行为

- 不得复制参考实现、gold、历史答案或另一实验臂产物；
- 不得硬编码 scorer 期望值；
- 不得把合成点、区域质心或推断单位伪装成真实测定；
- 不得为了扩大地图覆盖而放宽来源、CRS、许可或 QC 证据；
- 不得把“满足公开最低门槛”写成“已全面采集全球数据”。

## 6. 评分与解释

```bash
python public_case/score_submission.py \
  --case-dir case_data \
  --submission-dir submission \
  --output score.json
```

总分 100：D1 来源/覆盖/证据链 30、D2 科学处理 35、D3 产品交付 20、可复现性 15。公开 scorer 检查最低
锚点和不变量；上面不带 `--browser-audit` 的调用只用于候选开发反馈，因此不能取得完整 D3 证据或正式满分。
候选退出后，外部控制器必须运行 `evaluation/reporting/browser_audit.py`，再把控制器目录中的审计文件通过
`--browser-audit` 传给 scorer，并用 `evaluation/reporting/generate_report.py` 生成统一 JSON/Markdown 报告。
正式结论还必须结合不可见来源目录、浏览器交互测试和三次独立 B0/S0 运行。两组必须使用相同
commit、冻结请求、资源、网络策略、时限和 scorer，唯一自变量是 Skill 可见性。
