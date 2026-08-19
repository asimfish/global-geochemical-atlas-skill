# 在线研究与 D1/D2 自我修正循环

## 目标

`task_router.py` 是公开任务与官方评审的默认入口：任务合同未声明 deadline 时按官方 900 秒外部上限规划，预留 180 秒给 Agent 启动、验证和回复，并把 720 秒在线运行明确标记为检查点。`run_self_correction_loop.py` 是操作者明确授权小时级研究后的扩展入口；它不只在命令失败时重试，还在每个 30 分钟轮次后审计数据是否足以支撑请求，显式总上限可达 43,200 秒、最多 24 轮。若门禁提前通过可提前交付；到时仍不足则诚实输出检查点。统计通过不表示全球/全国代表性，只表示达到一个显式、可审计的最小证据包。

hash 固定 fixture 只用于显式 demo、离线回归或在线失败后已声明的最小降级。研究请求必须尝试网络可访问、请求兼容的来源。

## 每轮状态机

1. 冻结请求，检查 request hash 未变。用户未明确指定来源白名单时必须保留 `sources: auto`；实际选源属于 `source_route.json` 证据，不能反写成固定清单，否则后续发现的区域来源无法在同一请求中加入。
2. 在版本化 `source_catalog` 和完整来源 profile 中按元素、介质、空间域、区域、measurement basis、许可、evidence tier、已知数据内容与可执行接口路由。空间域按介质确定性派生为 `land`、`inland_water`、`marine`；命名国家的陆地/内陆水体使用冻结 Admin-0 科学分析几何。`China`/`中国`/`CHN` 的分析集合为 `CHN + TWN`，避免台湾记录被静默裁掉；`中国大陆` 才是 `CHN` 单体。该集合不是法定国界或主权表达，中国可视化另须链接自然资源部标准地图服务及审图号。多边形外仅来源明确标注的 marine 记录可进入默认 600 km 邻近海洋分析域，该缓冲区不是领海、EEZ 或主权边界。题面点名的平台必须逐个进入适用性审计；不含请求维度的来源记录排除理由，不盲目下载。
3. 尝试全部已选且可执行的在线来源，保留逐源 `source_outcomes`、manifest、hash、获取时间与失败。首轮顺序按完整 profile 的空间区 × 介质边际增益与独立血缘确定；后续轮次先消费上一轮自主修复计划中的瞬态失败来源和 `spatial_requery_source_ids`，再执行覆盖均衡与轮转顺序，避免已识别的俄罗斯/中国西部等缺口只写报告却没有真实补采机会。优先级只调整已路由来源的时间顺序，不能绕过兼容性、许可、记录上限或实现新 adapter。reported 覆盖只用于公平调度，仍不计入 canonical 空间通过。研究路径优先真实在线/已验证缓存的完整可扩切片，不以 hash fixture 替代在线采集。
4. 运行 D2/D3，验证固定十六文件契约和渲染门禁。即使 D2/D3 失败，已完成的来源尝试、过滤数量和 manifest 也先写入 `request_evidence/execution_failure.json`，不得随临时目录丢失。
5. 计算 `atlas-data-sufficiency-v9`：
   - 每个显式请求元素、介质、空间域以及每个元素 × 介质组合单元均须有观测；75% 覆盖率或集合并集不得通过；
   - 自适应记录下限 `max(5000, 500 × 元素数 × 介质数)`，不超过 `max_records`；
   - 自适应独立物理样品下限 `max(2000, 250 × 元素数 × 介质数)`，不超过 `max_records`；同一样品的多元素测定行不重复计数；
   - 全球至少 6 条、区域至少 3 条独立来源血缘，每介质至少 2 条；此外按独立物理样点对介质、元素和元素×介质三层检查容量平衡。非 demo 任务中，介质和元素的动态目标为同层最大样点数的 20%，下限 100、上限 2,000，并受请求容量约束；元素×介质单元为同层最大值的 10%，下限 20、上限 500。它只识别明显结构性短缺，不要求天然介质等量，也不声称代表性；少量岩石、水体或元素不能再被优势土壤/沉积物/元素掩盖；
   - 按独立样品计算的单一来源占比全球不超过 50%、区域不超过 80%；
   - 已选择在线来源的成功率至少 75%；
   - 100% 记录含 `source_id + source_locator`；在线研究中，每条记录还必须保留由 sidecar/manifest 绑定的官方数据页、下载 URL 或 DOI，来源汇总不得用一个首页掩盖同源其他记录的链接缺失；精确记录定位与官方链接是两条独立路径；
   - 100% 记录还须具备 `source_record_id`、源文件名、64 位 SHA-256、数据集标题、版本和明确许可；逐记录字段必须与 source manifest/sidecar 一致。任何错配都属于证据完整性阻断项，不得用更多记录抵消；
   - 来源证据非 low 至少 95%，分析就绪度非 low 至少 60%；
   - 100% 记录明确记账方法证据、坐标精度证据、地质背景证据和精确记录定位；发布方未报告时写责任原因，不得推断填充。每一种请求介质必须同时满足：非空分析方法率至少 20%、至少 `min(20, 该介质独立样品数)` 个方法就绪独立样品、至少 1 条方法就绪来源血缘；并至少有 20 个独立样品同时具备定量标准值、canonical 坐标、方法、地质/沉积背景、严格来源链和 QC，来自至少一条血缘。再按 `source × medium` 检查实质来源：当一个来源不少于 50 条且占该介质至少 10%，其方法非空率也须达到 20%，否则生成精确到来源和介质的补证/替换采集任务。海洋水体没有适用的陆地岩性时，可用明确的 `not_applicable_marine_water` 处置，不得伪造地质单元。其余可追溯但不完整的归档行保留为筛查证据，不能进入严格比较子集；也不能用方法完整的来源或介质替另一个来源或介质通过；
   - 至少一个 production 背景组达到异常分析门槛；
   - 全球最多要求 500 个、区域最多要求 250 个可映射独立样品，而不是测定行；
   - 全球 canonical 陆地样品至少覆盖 4 个 Natural Earth 大区、每个至少 100 个独立样品，最大大区占比不超过 60%；这是总体分布门禁，不替代下方逐视图六大区与三十个优先国家全覆盖门禁。
   - 运行[策略驱动空间覆盖门禁](global-spatial-coverage.md)：整体全球视图检查六个核心大国、由固定陆地格面积自动导出的三十个优先国家、每个非南极大区及非极地陆地格；经度跨度不少于 30° 的核心大国还拆成三个数据驱动经度带，防止俄罗斯或中国总量达标但只集中在一端。这组哨兵覆盖中东、美国、非洲、澳大利亚、中国和南美等大块陆地，而非按用户点名增补。请求还自动枚举 overall、逐元素、逐介质和逐元素 × 介质视图，逐一检查 canonical 独立样品、覆盖格及全球 coverage-zone 广度。`maximize_evidence_breadth` 要求每个视图触达六个陆地大区，缺失大区优先各派生一个国家补采目标。陆地点按大区、海洋点按固定经度扇区审计；reported-only 坐标可以带警示展示，但不计入 canonical 通过。
   - `maximize_evidence_breadth` 另有采集容量门禁：最低记录量、最少三种元素或两个介质只是可用性底线；只要任一成功来源仍填满本轮分配，就继续下一轮。仅在达到 `max_records`、达到每元素扩展上限，或所有可执行来源均返回低于分配量的容量信号时才认为已尽量扩展；固定容量恰等于分配量的适配器由外层无进展保护终止，不能制造无限循环。
   - 非全球命名国家或 bbox 依范围尺度从策略允许的 5° 至 0.25°选择网格，目标在长轴约 20 格；整体至少 20 个 canonical 独立样品、覆盖目标审计格的至少 50%，并触达 5×3 的全部方位分区。元素/介质视图至少触达 75% 分区，元素×介质视图至少触达 50%；因此东部或南部高密度不能掩盖新疆、西藏、台湾、华北等空洞。marine 点必须有明确来源语义并通过逐记录边界距离门禁；最细网格仍不足两个目标格时明确标记不可评估并继续使用精确点/边界 validator，不能把不可评估写成通过。
6. 若未通过，分别判断每个缺口。记录量、独立样品量或背景组等通用数量缺口可将 `per_analyte_observations` 扩大 2 倍；介质、元素和元素×介质容量失衡必须分别生成 `medium_sample_balance_gap`、`element_sample_balance_gap`、`element_medium_sample_balance_gap`，明确维度、observed、target、deficit、候选来源和完成证据，并优先补短缺单元，不能继续给已经占优的维度扩量。空间空洞不属于通用扩量修复，必须从 `spatial_dimension_gaps` 与 `geographic_search_targets` 生成符合 [D1 修复队列 schema](d1-repair-queue.schema.json) 的 `d1_repair_queue.json`。逐介质方法、实质来源方法、严格科学子集、地质证据记账和逐来源官方链接短缺分别生成机器可判定缺口，精确保留介质/来源、observed、target 与不可推断边界。发布方明确不提供逐行方法时，不得反复查询同一来源或推断补值，必须排除该血缘并寻找方法证据完整的替代来源；只有证据关联未解析或管线丢字段时才审计/修复同一来源。某国没有更细目标框时使用冻结国界 bbox，绝不继承全球 bbox；跨日期变更线国家的 bbox 重叠、东西方向和 Admin-1 检索提示按环形经度计算。请求明确四种介质时，岩石、土壤、沉积物、水体是四个独立硬门禁；只有三种不得以“至少两类”的最低线宣称完成。队列由请求和观测自动派生，不按示例国家/元素写规则。队列 v3 保留逐视图 `tasks`，同时把相同区域、候选层和执行方式合并为少量 `action_groups`；组内汇总元素/介质/视图，并用冻结的 Natural Earth Admin-1 gazetteer 生成仅供检索的地名提示（不是边界或覆盖证据），避免把新疆、西藏等缺口降格成不可检索的 bbox 数字。每组必须留下查询平台、URL/DOI、许可/版本结论及新增记录/样品/canonical 格或 no-hit 的尝试回执，随后重算全部成员视图；未尝试组存在时 `operator_continuation_required=true`、`control_state=continue_research` 且 `final_response_permitted=false`，控制器以 `repair_queue_pending` 移交下一动作而不是完成。每项仍写入 `execution_class`：当前 Skill 可直接重跑、当前 Skill 可执行数据动作、先做只读证据审计、或必须完成 Skill 维护后开新输出目录；顶层 `execution_class_counts` 让 Agent 不再把可执行补采误判成人工阻断。控制器会把当前 Skill 可重查来源带入下一轮的 gap-priority 调度，实际执行后再重算；每次检索或 adapter 修复只要产生经过验证的正记录/样品/canonical 格/方法/链接增量，就先纳入新轮次并重算，即使尚未一次关闭整项缺口；无增量才沿 fallback chain 前进。当前 v9 充分性评估缺少或未完成时，队列先生成单步 `rerun_current_controller` 任务；v8 及更旧的 `loop_report` 不能原地续跑，必须以相同冻结请求换新输出目录，让当前控制器重新评估。旧字段不能被解释为“无缺口”，也不能在重新评估前驱动当前修复策略。结构性缺口不能阻断其他已覆盖维度的真实改进，但也不能被更多无关区域或其他视图记录掩盖。只有来源证据/溯源损坏时才禁止所有扩量。
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

控制器因 `SOURCE_COVERAGE_GAP`、`GLOBAL_SPATIAL_COVERAGE_GAP`、`SPATIAL_DIMENSION_COVERAGE_GAP`、任一容量平衡缺口或 `repair_queue_pending` 停机时，只说明脚本把控制权交给修复动作，不是 Agent 任务已结束。剩余预算允许时，Agent MUST 读取 `d1_repair_queue.json`，执行 `required_next_action`，并按 v3 `action_groups[].priority` 尝试已注册候选与只读定向发现；一个组使用其地名别名、Admin-1 搜索提示、bbox、全部元素/介质/空间域一次处理，然后重算全部 `member_task_ids`。每组必须留下查询、平台、来源定位、许可、版本决策及新增记录/样品/canonical 格或无命中/blocked 证据。`final_response_permitted=false` 时不得写终稿或把“待修复”当成已修复；只有所有动作组有实际回执、新数据已验证重算或权限/条款边界已明确时才能停机。

活动控制器不得修改当前 Skill、实现新 adapter 或自行扩大权限。未注册来源、未知条款和需要代码变更的候选先转结构化 `skill_maintenance_new_run`。原任务未授权维护时停在 `needs_human_review`；原任务已明确授权隔离维护时，Agent 必须停止活动控制器，保存当前不可变轮次，在独立 Skill 副本中完成官方证据、许可、版本、hash、crosswalk、最小真实 fixture 与组件测试，冻结新 Skill hash 后，以相同 request hash、新输出目录重启，并保存 continuation receipt。禁止在活动快照或活动输出目录热改；相同无增量轮次不能代替可执行的 adapter 维护。统一扩大所有来源、删除密集来源、让其他元素/介质代替当前视图或用同洲其他国家代替目标均不算修复。不得绕过许可、CRS、方法或原始记录定位门禁来伪造“充分”。

## 运行与产物

```bash
python scripts/run_self_correction_loop.py \
  --request REQUEST.json \
  --online-source auto \
  --cache-dir .cache/data \
  --analysis-profile production \
  --output-dir OUTPUT_DIR
```

官方自动评审的任务合同默认 900 秒，规划器从中预留 180 秒给 Agent 启动、验证和回复，生成 720 秒内部在线检查点；短于一个完整 1,800 秒轮次必须显式声明 `--checkpoint-only`，其结果永远不能成为正式交付。只有操作者明确授权扩展研究时，才使用单轮 1,800 秒、内部工作流 1,740 秒、单来源 600 秒、总预算最多 43,200 秒。续跑累计既有轮次耗时，不重新获得预算；`fixed` 请求在门禁通过时可提前结束，`maximize_evidence_breadth` 还必须满足采集容量门禁。fixture 更快不是跳过在线尝试的理由。

每轮产物保存在 `OUTPUT_DIR/rounds/round-NN/`。最新通过十六文件验证的完整包可作为检查点发布到 `OUTPUT_DIR/`；`loop_report.json` 记录路由、轮次、充分性标准、扩采目标、修复计划、停机理由和已发布轮次，`d1_repair_queue.json` 是 Agent 必须消费的结构化 D1 控制面，`research_delivery_receipt.json` 将根目录十六文件逐字节绑定到该不可变轮次、清空的修复队列与未变的完整 Skill 树。在同一输出目录续跑时，请求 hash 必须不变且既有充分性评估必须是当前 `atlas-data-sufficiency-v9`；v8 及更旧报告应保留作历史证据，并在新输出目录用相同请求重新开始。执行证据使用 `geochemical-request-execution-v6` 并记录 gap-priority 调度输入与实际来源顺序；若另一个进程在一轮中修改 Skill，当前轮以 `conflicting_evidence` 失败关闭，避免混合版本产物。

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
