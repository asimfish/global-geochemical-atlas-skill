# 在线研究与 D1/D2 自我修正循环

## 目标

`run_self_correction_loop.py` 是完整图谱任务的默认入口。它不只在命令失败时重试，还在每个 30 分钟轮次后审计数据是否足以支撑请求。默认共享 43,200 秒总上限；首轮未达到门禁时按精确缺口继续下一轮，最多 24 轮。若门禁提前通过可提前交付；到时仍不足则诚实输出检查点。统计通过不表示全球/全国代表性，只表示达到一个显式、可审计的最小证据包。

hash 固定 fixture 只用于显式 demo、离线回归或在线失败后已声明的最小降级。研究请求必须尝试网络可访问、请求兼容的来源。

## 每轮状态机

1. 冻结请求，检查 request hash 未变。用户未明确指定来源白名单时必须保留 `sources: auto`；实际选源属于 `source_route.json` 证据，不能反写成固定清单，否则后续发现的区域来源无法在同一请求中加入。
2. 在版本化 `source_catalog` 和完整来源 profile 中按元素、介质、空间域、区域、measurement basis、许可、evidence tier、已知数据内容与可执行接口路由。空间域按介质确定性派生为 `land`、`inland_water`、`marine`；命名国家的陆地/内陆水体使用冻结 Admin-0，多边形外仅来源明确标注的 marine 记录可进入默认 600 km 邻近海洋分析域，该缓冲区不是领海、EEZ 或主权边界。题面点名的平台必须逐个进入适用性审计；不含请求维度的来源记录排除理由，不盲目下载。
3. 尝试全部已选且可执行的在线来源，保留逐源 `source_outcomes`、manifest、hash、获取时间与失败。有限轮次内的顺序按完整 profile 的空间区 × 介质边际增益与独立血缘确定，避免同一区域的兄弟表先耗尽时限；reported 覆盖只用于公平调度，仍不计入 canonical 空间通过。研究路径优先真实在线/已验证缓存的完整可扩切片，不以 hash fixture 替代在线采集。
4. 运行 D2/D3，验证固定十六文件契约和渲染门禁。即使 D2/D3 失败，已完成的来源尝试、过滤数量和 manifest 也先写入 `request_evidence/execution_failure.json`，不得随临时目录丢失。
5. 计算 `atlas-data-sufficiency-v6`：
   - 每个显式请求元素、介质、空间域以及每个元素 × 介质组合单元均须有观测；75% 覆盖率或集合并集不得通过；
   - 自适应记录下限 `max(5000, 500 × 元素数 × 介质数)`，不超过 `max_records`；
   - 自适应独立物理样品下限 `max(2000, 250 × 元素数 × 介质数)`，不超过 `max_records`；同一样品的多元素测定行不重复计数；
   - 全球至少 6 条、区域至少 3 条独立来源血缘，每介质至少 2 条；
   - 按独立样品计算的单一来源占比全球不超过 50%、区域不超过 80%；
   - 已选择在线来源的成功率至少 75%；
   - 100% 记录含 `source_id + source_locator`；在线研究中，每条记录还必须保留由 sidecar/manifest 绑定的官方数据页、下载 URL 或 DOI，来源汇总不得用一个首页掩盖同源其他记录的链接缺失；精确记录定位与官方链接是两条独立路径；
   - 来源证据非 low 至少 95%，分析就绪度非 low 至少 60%；
   - 100% 记录明确记账方法证据、坐标精度证据和精确记录定位；每种请求介质的非空分析方法率至少 80%，不能用方法完整的介质替另一个介质通过；
   - 至少一个 production 背景组达到异常分析门槛；
   - 全球最多要求 500 个、区域最多要求 250 个可映射独立样品，而不是测定行；
   - 全球 canonical 陆地样品至少覆盖 4 个 Natural Earth 大区、每个至少 100 个独立样品，最大大区占比不超过 60%；这是总体分布门禁，不替代下方逐视图六大区与三十个优先国家全覆盖门禁。
   - 运行[策略驱动空间覆盖门禁](global-spatial-coverage.md)：整体全球视图检查六个核心大国、由固定陆地格面积自动导出的三十个优先国家、每个非南极大区及非极地陆地格；这组哨兵覆盖中东、俄罗斯各经度带、美国、非洲、澳大利亚、中国和南美等大块陆地，而非按用户点名增补。请求还自动枚举 overall、逐元素、逐介质和逐元素 × 介质视图，逐一检查 canonical 独立样品、覆盖格及全球 coverage-zone 广度。`maximize_evidence_breadth` 要求每个视图触达六个陆地大区，缺失大区优先各派生一个国家补采目标。陆地点按大区、海洋点按固定经度扇区审计；reported-only 坐标可以带警示展示，但不计入 canonical 通过。
   - `maximize_evidence_breadth` 另有采集容量门禁：最低记录量、最少三种元素或两个介质只是可用性底线；只要任一成功来源仍填满本轮分配，就继续下一轮。仅在达到 `max_records`、达到每元素扩展上限，或所有可执行来源均返回低于分配量的容量信号时才认为已尽量扩展；固定容量恰等于分配量的适配器由外层无进展保护终止，不能制造无限循环。
   - 非全球命名国家或 bbox 依范围尺度从策略允许的 5° 至 0.25°选择网格；整体至少 20 个 canonical 独立样品并覆盖目标陆地、内陆水体或邻近海洋审计格的至少 15%，每个筛选视图再按策略比例检查。marine 点必须有明确来源语义并通过逐记录边界距离门禁；最细网格仍不足两个目标格时明确标记不可评估并继续使用精确点/边界 validator，不能把不可评估写成通过。
6. 若未通过，分别判断每个缺口。记录量、独立样品量或背景组等通用数量缺口可将 `per_analyte_observations` 扩大 2 倍；空间空洞不属于通用扩量修复，必须从 `spatial_dimension_gaps` 与 `geographic_search_targets` 生成符合 [D1 修复队列 schema](d1-repair-queue.schema.json) 的 `d1_repair_queue.json`。逐介质方法短缺与逐来源官方链接短缺分别生成 `metadata_evidence_gap`，精确保留介质/来源、observed、target 与不可推断边界。队列由请求和观测自动派生，不按示例国家/元素写规则。每次检索或 adapter 修复只要产生经过验证的正记录/样品/canonical 格/方法/链接增量，就先纳入新轮次并重算，即使尚未一次关闭整项缺口；无增量才沿 fallback chain 前进。当前 v5 报告缺少或未完成充分性评估时，队列先生成单步 `rerun_current_controller` 任务；旧版 `loop_report` 不能原地续跑，必须以相同冻结请求换新输出目录，让当前控制器重新评估。旧字段不能被解释为“无缺口”，也不能在重新评估前驱动当前修复策略。结构性缺口不能阻断其他已覆盖维度的真实改进，但也不能被更多无关区域或其他视图记录掩盖。只有来源证据/溯源损坏时才禁止所有扩量。
7. 通过、不再有自主修复、扩大目标后记录数与独立样品数仍无变化（来源容量）、达到 24 轮或声明的总预算时诚实停机。没有通过充分性门禁的终态是 `needs_human_review` 检查点，不是成功或正式研究交付。`sufficiency.reporting_facts` 固定记录 observed、target、短缺倍数与四维 band，供最终报告原样引用。

## 扩采与人工路由边界

可自主扩采的典型缺口是记录数、独立样品数或异常背景样本量不足。已路由来源明确包含未观测元素/介质时，也可扩采以实现覆盖。某个介质无来源时，它继续进入 `SOURCE_COVERAGE_GAP`，但不会阻止其他介质的独立扩采目标。

以下问题不能靠增加同源记录解决：

- 现有可执行来源不包含缺失元素/介质；
- 已尝试全部选定来源后仍不足所需独立血缘；
- 记录级溯源缺失、许可不明、schema 漂移、CRS 或方法语义不明；
- 核心/优先国家、大区或某一元素/介质筛选视图的网格空洞；其他区域或视图增加不能修复；
- 删失值、样本代表性或其他 `scientific_limit`。

这些问题按 `stage_owner + issue_code` 分组写入 `repair_plan.manual`。D1 必须补充候选来源/适配器或原始证据；D2 必须保留原值并只使用确定性转换/匹配规则。无法证明的值继续为空。

控制器因 `SOURCE_COVERAGE_GAP`、`GLOBAL_SPATIAL_COVERAGE_GAP` 或 `SPATIAL_DIMENSION_COVERAGE_GAP` 停机时，只说明当前可执行路径不能继续修复。剩余预算允许时，Agent MUST 读取 `d1_repair_queue.json`，按 `priority` 尝试已注册候选与只读定向发现，并为每项留下来源定位、许可、版本决策及新增记录/样品/canonical 格或无命中证据。运行时不得修改当前 Skill、实现新 adapter 或自行扩大权限；未注册来源、未知条款和需要代码变更的候选转 `needs_human_review`，供维护者在获得用户授权后于独立开发运行中准入、测试并重新发布 Skill。统一扩大所有来源、删除密集来源、让其他元素/介质代替当前视图或用同洲其他国家代替目标均不算修复。不得绕过许可、CRS、方法或原始记录定位门禁来伪造“充分”。

## 运行与产物

```bash
python scripts/run_self_correction_loop.py \
  --request REQUEST.json \
  --online-source auto \
  --cache-dir .cache/data \
  --analysis-profile production \
  --output-dir OUTPUT_DIR
```

默认单轮上限 1,800 秒、内部工作流 1,740 秒、单来源 600 秒、总预算上限 43,200 秒。短于一个完整 1,800 秒轮次必须显式声明 `--checkpoint-only`，其结果永远不能成为正式交付。续跑累计既有轮次耗时，不重新获得预算；`fixed` 请求在门禁通过时可提前结束，`maximize_evidence_breadth` 还必须满足采集容量门禁。fixture 更快不是跳过在线尝试的理由。

每轮产物保存在 `OUTPUT_DIR/rounds/round-NN/`。最新通过十六文件验证的完整包可作为检查点发布到 `OUTPUT_DIR/`；`loop_report.json` 记录路由、轮次、充分性标准、扩采目标、修复计划、停机理由和已发布轮次，`d1_repair_queue.json` 是 Agent 必须消费的结构化 D1 控制面，`research_delivery_receipt.json` 将根目录十六文件逐字节绑定到该不可变轮次、清空的修复队列与未变的完整 Skill 树。在同一输出目录续跑时，请求 hash 必须不变且既有充分性评估必须是当前 `atlas-data-sufficiency-v6`；旧版本报告应保留作历史证据，并在新输出目录用相同请求重新开始。执行证据使用 `geochemical-request-execution-v5`；若另一个进程在一轮中修改 Skill，当前轮以 `conflicting_evidence` 失败关闭，避免混合版本产物。

正式交付必须再运行：

```bash
python scripts/validate_research_delivery.py --output-dir OUTPUT_DIR
```

不得手工运行一次 staging 后把其文件复制、移动或覆盖到 loop 根目录；不得把 `validate_outputs.py` 或评测 checker 的全绿等同于数据充分。若需要检查不充分轮次，只能显式加 `--allow-insufficient-checkpoint`，并保持其非交付语义。

`iteration_backlog.csv` 仍是记录级修复控制面，不是自动插补列表。canonical 数据库与原始证据不在原地修改；每轮都生成新版本。

## 四维质量语义

循环的“数据充分性”与 D2 的“工作流可用性”是两个不同门禁。产物不得用一个模糊的“低质量”标签代替以下四个维度：

| 维度 | 回答的问题 |
|---|---|
| `source_evidence` | 来源、许可、版本、定位与 hash 证据是否可追溯？ |
| `analytical_readiness` | 方法和 QC 是否支持当前定量比较？ |
| `spatial_usability` | 坐标证据是否支持 canonical 空间分析，还是只能 reported 示意？ |
| `workflow_usability` | 综合门控后，记录对当前工作流的可用性如何？ |

例如，一个政府数据集可以有 high `source_evidence`，但因 datum 未声明而只有 low `spatial_usability`；这不等于来源本身“低质量”。

固定生成的 `sources_and_confidence.json` 按来源报告 URL/DOI、许可、文件 hash、获取时间、测定行数、独立样品数、方法/坐标/定位完整率和四维 band 计数。`coordinate_representation_resolution` 只由坐标文本小数位推得，不是位置准确度；只有来源报告/政策绑定的不确定度才进入 `source_reported_coordinate_uncertainty`。展示或总结时必须写出维度全名；禁止只输出一个“数据质量：低”。
