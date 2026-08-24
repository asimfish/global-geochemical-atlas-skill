# 分层全球空间覆盖门禁

## 为什么需要这一门禁

大洲样品数会掩盖国家级空洞，总体样品数还会掩盖筛选图层空洞：某一元素在欧洲的高密度数据不能证明另一个元素在全球有覆盖。`atlas-data-sufficiency-v9` 因此同时执行整体层级审计、宽核心国家经度带审计、请求维度审计、逐介质严格科学子集审计与实质来源方法证据审计，并把 `maximize_evidence_breadth` 的来源容量扩展与最低可用门禁分开。该门禁回答“现有可追溯观测是否达到显式的最低图谱证据包”，不回答“抽样是否均匀或具有统计代表性”。阈值统一来自 `assets/spatial-sufficiency-policy.json`，其结构由 `spatial-sufficiency-policy.schema.json` 固定；代码不按国家名称选择规则。

## 固定空间证据与阈值

门禁使用仓库内固定的 Natural Earth 110m Admin-0 边界和国家—大区 crosswalk。全球层级以 5°经纬网单元中心做国界点内判定；网格只是轻量、可复现的观察空洞索引，不是等面积科学格网、浓度插值面或元素不存在的证据。

全球 production 请求必须同时满足：

1. 按非极地陆地网格单元数确定的六个核心国家全部通过；当前固定资产导出的顺序为 `RUS, CAN, USA, CHN, AUS, BRA`。
2. 三十个优先国家全部通过，或对每个未通过国家留下经过实际检索/适配后的不可获得证据并以 `needs_human_review` 停止；不能把 2/3 通过当成其余大片空白可忽略。优先列表按固定边界中的非极地陆地 5°格数量自动导出，不手写政治名单；当前范围会自然包含中东、俄罗斯、美国、非洲、澳大利亚、中国和南美等主要陆地区块，并随固定边界资产/策略版本一起审计。
3. 每个优先国家至少有 20 个 canonical 独立样品，并占用 `max(2, ceil(该国陆地单元数 × 10%))` 个 canonical 单元，上限 6 个；只有一个网格单元的国家要求 1 个。
4. 对经固定国界推导的经度跨度不少于 30° 的核心大国，把其陆地格按最小圆周经度顺序等分为三个带。overall 视图必须覆盖 3/3；逐元素和逐介质视图至少覆盖 2/3；元素×介质视图至少覆盖 1/3，每个命中带至少有一个 canonical 格。该规则由国界几何与策略阈值触发，不按俄罗斯、中国等名称写分支，专门阻止“国家总量够但只集中在一端”。
5. Africa、Asia、Europe、North America、Oceania、South America 各自至少占用其陆地单元数的 10%，且不少于 2 个 canonical 单元。
6. 全部非极地陆地至少占用 15% 的 canonical 单元。

南极洲和格陵兰仍在空间事实中可见，但不是一般全球元素图谱的默认阻断项。reported-only 坐标单独计数并可带警示展示，绝不计入上述 canonical 通过条件。通过也只代表显式最低证据包，不得写成全球均匀覆盖。

## 请求维度覆盖

整体门禁之外，策略引擎从冻结请求自动枚举以下视图，不依赖题面举过哪些国家或元素：

1. `overall`；
2. 每一个请求元素；
3. 每一种请求介质；
4. 每一个请求元素 × 介质组合。

每个视图独立计算 canonical 独立样品数和占用 coverage 格数。全球元素/介质视图至少达到整体陆地参考格门槛的 50%，组合视图至少达到 25%，并分别跨越策略声明的 coverage zone 数；当请求使用 `coverage_mode=maximize_evidence_breadth` 时，overall、每个元素、每种介质和每个组合视图还必须分别触达 Africa、Asia、Europe、North America、Oceania、South America 六个陆地大区。缺一个就写 `land_macroregion_coverage_debt`，不能让欧洲密集数据或其他图层替代。陆地点按 Natural Earth 大区分区，海洋点按固定 60°经度扇区分区，避免把海洋水体/沉积物错误排除，同时保留独立的整体陆地国家门禁。准确数值以版本化策略文件为准。一个视图的样点不得替另一个视图计数。失败项写入 `sufficiency.discovery_gaps.spatial_dimension_gaps`，每项包含 `required_elements`、`required_media`、范围、精确 observed/target、缺口原因、动态国家目标、来源候选及首选 `repair_mode`。

国家目标按固定陆地格规模、视图实际占用格和缺失大区动态排序；先为每个 `missing_land_macroregions` 选择一个仍有观察空洞的国家，再按核心/优先国家与未占用陆地格补齐剩余名额。中国、俄罗斯、欧洲等名称可以出现在数据驱动结果或测试中，但不进入算法分支。这样新元素、新介质、任意国家和任意 bbox 都走同一机制。

## 逐区域修复队列

失败时，控制器把最后一轮 `sufficiency.discovery_gaps.spatial_dimension_gaps` 与 `geographic_search_targets` 扁平化为符合 [schema](d1-repair-queue.schema.json) 的 `d1_repair_queue.json`。筛选视图目标优先于整体目标；整体目标再按 `core → extended → macroregion_backfill → global_backfill` 排序。宽核心国家的未命中经度带还会给出精确 `target_bboxes`，而不是只写国家名。每项都给出 canonical/reported 事实、阈值、缺口原因、候选来源、首选修复模式、fallback chain、完成证据要求和机器可判定的 `execution_class`。`data_action_current_skill` 可立即定向重查/路由，`evidence_audit_current_skill` 先只读核验证据，`skill_maintenance_new_run` 只有在原用户授权维护 Skill 时才修改代码并以同请求开新目录；队列本身不扩大写权限。

| `repair_mode` | 必须执行的动作 |
|---|---|
| `rerun_current_controller` | 当前 v6 报告的充分性评估缺失或失败；用相同冻结请求在当前 Skill 下重跑评估并重建队列。v5 及更旧的 `loop_report` 不得原地恢复，须换新输出目录重算。 |
| `repair_coordinate_evidence` | 原记录已能展示但 datum/CRS 不足；查找并绑定可验证坐标证据，不能把 reported 直接改名为 WGS84。 |
| `requery_selected_source` | 已选来源的完整 profile 证明含该国；执行国家定向查询、分页或抽取，并核验实际命中。统一提高所有来源记录上限不算完成。 |
| `route_registered_source` | 已有可执行注册来源覆盖该国；把它纳入冻结请求兼容路由并保留逐源结果。 |
| `implement_catalog_candidate` | catalog 有候选但尚不可执行；核验内容、许可、稳定定位与真实记录后实现适配器。 |
| `targeted_source_discovery` | 当前库没有候选；在线检索国家地调/环境机构、PANGAEA、EarthChem、公开论文补充数据等，并完成 D1 准入与逐记录溯源。 |

`repair_mode` 是当前证据下的第一步，不是失败后停机的理由。每项的 `discovery_queries` 和 `discovery_platform_sequence` 均从请求范围、元素与介质生成，用来指导真实在线发现；它们不是来源已适用的声明，仍须逐项核验数据内容、许可、版本、坐标与记录定位。坐标证据确实不存在、已选来源国家定向查询无命中、注册来源不兼容或 catalog 候选无法通过许可/内容门禁时，必须保留尝试证据并依次转向下一候选，最终进入 `targeted_source_discovery`。例如 TPDC datum 不能被证实时保留 reported-only，不得硬改 WGS84；同时应寻找另一条带 canonical 坐标的中国来源。

每次完成一组目标后，以相同请求 hash 恢复 `run_self_correction_loop.py`。仅缓存数据或坐标证据变化时使用同一 `OUTPUT_DIR`；若新增/修改来源 adapter、catalog、registry 或 profile，先结束旧运行并验证新 Skill，再在新 `OUTPUT_DIR` 重启同一请求，并保存前后目录与 Skill hash 的 continuation 证据。用户未指定来源白名单时，冻结请求保持 `sources: auto`；选中的来源只属于路由证据，不能改写成固定列表。控制器把上一轮自主修复项中的 `spatial_requery_source_ids` 与瞬态失败来源写入下一轮调度优先级，使有望修复俄罗斯/新疆等具体空洞的已注册来源先得到时间窗口；调度优先级不改变路由成员、许可结论、记录上限，也不能让未实现候选变成可执行来源。控制器以真实探测验证修复；每个来源产生的已验证正边际增量先进入新数据版本并重算全部视图，即使该增量不足以一次关闭整个大区债务。若仍不足，重写队列并继续下一个候选。`d1_repair_queue.json.status=pending` 时，正式收据必须保持 `delivery_ready=false`。不得通过删除高密度来源、复制记录、伪造坐标、降低阈值、让其他元素/介质代替当前视图或插值填空让门禁变绿。

## 停机与陈述边界

只有以下任一条件成立时，未通过队列才能以 `needs_human_review` 检查点停机：当前声明预算耗尽；所有合理候选因许可/访问/网络不可用；来源不发布请求元素、介质或坐标；或者继续需要无法验证的 CRS、方法或记录定位。必须逐项目标保留检索、排除和失败证据。

地图空白必须解释为“当前可追溯观测不足”，不得解释为该地区元素缺失、背景低值、无污染或无矿化。异常筛查仍只在可比背景组内进行，空间覆盖门禁不改变异常成因边界。

## 命名国家与范围框

非全球 production 请求也不能只靠一个局部高密度簇过关。引擎只看解析后的 polygon/bbox 尺度，从策略允许的 5°、2°、1°、0.5°、0.25°中选择分辨率，目标是在长轴形成约二十格；命名国家与同范围 bbox 使用同一策略引擎，前者额外做精确国界点内判定。整体视图必须有至少 20 个 canonical 独立样品，占用 `max(2, ceil(目标 coverage cells × 50%))` 个单元，并触达按范围等分的 5×3 十五个 coverage zone；元素与介质视图各须触达至少 75% 分区，元素×介质视图至少 50%。国家范围的目标格落在科学分析几何内，任意 bbox 则保留范围内陆地与水域，因此海域研究不会被误判为空。`China`/`中国`/`CHN` 使用 `CHN + TWN` 科学分析集合，`中国大陆` 使用 `CHN`；该集合不是法定国界，中国地图同时链接自然资源部标准地图和审图号。失败分区连同精确 bbox 写入兼容的 `regional_spatial_gap` 和通用 `spatial_dimension_gaps`，直接驱动西部、北部、岛屿或其他空洞的定向补采。若 reported-only 已达到门槛，先核验 CRS/datum，不能证明时转向带 canonical 坐标的新来源。只有在最细允许网格下仍不足两个目标格的微小范围才标记 `unassessable`，继续由精确点内判定、bbox 裁剪和地图渲染门禁负责，绝不把“无法粗粒度评估”写成通过。
