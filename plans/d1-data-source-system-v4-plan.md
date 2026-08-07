# D1 数据语义、字段完整率与介质覆盖平衡 V4 计划（审阅稿）

更新时间：2026-08-06 23:46（Asia/Shanghai）

状态：执行中；V4-M0 至 M4 已完成，正在执行 M5 沉积物增强

承接版本：`plans/d1-data-source-system-v3-plan.md`

当前基线：分支 `d1/source-system-v2`，最后已推送提交 `5854861`，其后 M4 变更在工作区

## 一、结论先行

当前系统已经证明采集架构能够覆盖四种介质和主要处理步骤，但并不是每类信息都同样完整。“架构能力存在”和“字段已充分填充”必须分开验收。

1. **元素含量**：当前十五个可执行数据集都能输出元素、原始数值、单位和来源定位；联合演示 792/792 具备这些字段。但演示只抽取可用记录，不能代表全量数据的缺失率。
2. **采样坐标**：联合演示 792/792 有可用于地图的坐标，但这是经过筛选的演示切片。全量 profile 单列原始坐标、CRS 和缺失，例如 AfSIS 2,002 个样品中有 126 个缺少经纬度；WQP 的 NAD83 原值和 15 m 地图不确定度也单独保留。
3. **地质背景**：语义混用已经清理。旧 `geologic_unit` 现为 0/792，原来的 192 条地区、图幅、航次或项目范围已迁入 `geographic_context_raw`、`map_sheet`、`cruise_track` 和 `survey_area`。`geologic_unit_raw/matched_geologic_unit` 同样为 0/792，说明当前没有足够证据支持“已采集地质单元”，后续必须补来源地质字段或版本化空间匹配。
4. **分析方法**：联合演示中 648/792（81.8%）非空，其余 144 条有明确缺失原因。全量口径差异很大：GEMStat 只有 279,225/3,739,180（7.47%）方法明确；GEOTRACES 有 22,254/39,327（56.59%）能唯一关联到 BODC 方法记录，其余保留候选集而不猜测。
5. **样品类型**：十五来源均已贯通 V4 语义。联合演示 792/792 有 `sample_type_raw + sample_type + mapping_status`；288 条土壤有层位，256 条沉积物有环境类型，200 条水体有水体类型和分相。映射只来自来源 evidence 或注册常量，不从元素、单位或方法推断。
6. **公开文献**：已经具备 publication/citation 关系和 GEOROC 记录级 `citation_ids` 样板，但不是所有来源都完成记录级或方法级文献连接。数据集 DOI 不能自动等同于每条测定的原始分析文献。
7. **访问与使用条件**：当前来源均可公开访问或按声明条件用于本项目科研分析，但许可类型包括 CC、公共领域和自定义引用/版权条款，不宜统一写成“全部开源许可”。V4 分开记录访问状态、科研使用状态、许可标识和署名要求。
8. **自动采集**：下载、缓存、快照、hash、适配器和来源定位链路已经存在；十五来源现已发布最近成功获取/解析、文件 hash、schema fingerprint、row-count、缓存/离线重放和版本漂移状态。在线实时探测仍与可复现离线审计分开运行。

V4 的第一优先级不是继续增加来源名称，而是让“元素—坐标—地质背景—分析方法—样品类型”五类信息在归档、交换、查询、地图和置信度中使用同一套可追溯语义。第二优先级才是按可比较覆盖补齐水体和沉积物。

## 二、当前审计基线

### 2.1 十五个可执行数据集

| 介质 | 可执行数据集数 | 数据集 |
|---|---:|---|
| 岩石 | 1 | GEOROC Archaean Cratons |
| 土壤 | 6 | USGS CONUS、PANGAEA North Africa、FOREGS topsoil/subsoil/humus、AfSIS Phase I V2.0 |
| 沉积物 | 4 | MarChem、GSJ Japan、FOREGS stream/floodplain sediment |
| 水体 | 4 | GEOTRACES、GEMStat、FOREGS stream water、USGS/WQP Sacramento River dissolved As |

岩石的记录量较大，但只有一个可执行来源；土壤来源数量最多；水体和沉积物来源数量及地理类型仍较少。不能用单一“记录总数”判断哪种介质更全面。

### 2.2 304 条与 736 条历史基线的口径对齐

用户提供的 304 条检查对应 2026-08-05 的五来源联合 fixture；736 条对应 M2 完成时的十四来源版本。当前 M4 基线已经是十五来源、792 条 fixture。三个数字都是各自时点的真实快照，不能混成同一时点的完整率。

| 需求 | 304 条历史基线 | 736 条前一基线 | V4 采用的验收口径 |
|---|---|---|---|
| 岩石/土壤/沉积物/水体 | 四介质均有落地来源 | 四介质、十四个可执行数据集 | 同时报介质、样品类型、独立血缘和空间覆盖，不只判断“有/无” |
| 元素含量 | 304/304 有可处理元素记录；来源存在删失值时保留限定符和检出限 | 736/736 有元素、值/限定符、单位和来源定位 | 全量来源分别统计有效值、删失、缺失、单位可换算和来源定位比例 |
| 采样坐标 | 304/304 有 WGS84 查询坐标和不确定度字段 | 736/736 有查询坐标；AfSIS 全量仍明确记录 126 个缺坐标样品 | 同时验收原始坐标、原 CRS、转换记录、有效坐标和不确定度；演示不替代全量 |
| 地质背景 | 岩石 100%、水体 50%、土壤/沉积物 0% 非空 | 来源/匹配地质单元 0/736；原 192 条地区/图幅/航线已拆到地理上下文 | 地理上下文、来源地质字段和空间匹配地质字段分开统计，语义错误不得算完整 |
| 分析方法 | 沉积物 100%、水体 50%，岩石/土壤 0%；矩阵标记 `not_yet_audited` | 544/736 有方法且全部带 scope；其余 192/736 有明确缺失原因 | 按 observation/sample/batch/file/dataset/publication scope 统计；全量而非优选 demo 作分母 |
| 公开文献 | GEOROC 记录携带原始 `citation_ids` | 数据集级引用已扩大，但逐记录/逐方法引用仍不均匀 | 分别统计数据集、方法、样品和测定的文献连接率及可解析 DOI 率 |
| 开源数据平台 | 五个来源均公开获取并可按声明条件研究使用 | 十四来源均有明确访问/科研使用记录 | 使用 `access_status + research_use_status + license_id`，不把自定义条款误称标准开源许可 |
| 自动采集 | 脚本化流水线和 snapshot manifest | 十四个 adapter、离线 fixture、hash 与联合重建 | 增加最近成功获取、版本/字段漂移、缓存完整性和失败降级监控 |
| 覆盖结论 | `partial`；岩石、土壤、沉积物为单一来源，水体存在按元素的单一来源依赖 | 来源数增加，但所有介质仍为 `partial`；细分到元素×样品类型×地区后仍有单一血缘 | 以覆盖立方体显示依赖，不因来源数或记录数增长自动改成“全面” |

这里对“元素含量完整”的解释是：演示中的每条 observation 都有可处理的元素测定语义；不是说每条记录都有检出限，也不是说每个来源测了所有元素。检出限与删失限定符应在来源存在时保留，缺失时必须明确标为未报告。

### 2.3 当前联合演示字段完整率

下表统计的是当前 792 条 hash 固定联合演示，不是全量来源总体。

| 介质 | 演示记录 | 元素+值 | 坐标 | 来源/匹配地质单元 | 方法或缺失原因 | 样品类型 |
|---|---:|---:|---:|---:|---:|---:|
| 岩石 | 48 | 100% | 100% | 0% | 100% | 100% |
| 土壤 | 288 | 100% | 100% | 0% | 100% | 100% |
| 沉积物 | 256 | 100% | 100% | 0% | 100% | 100% |
| 水体 | 200 | 100% | 100% | 0% | 100% | 100% |
| 合计 | 792 | 100% | 100% | 0% | 100% | 100% |

这里的“方法或缺失原因”不等于方法完整率：544 条有方法和 scope，192 条只有明确缺失原因。真正地质单元 0% 是清理错误语义后的诚实结果，不是数据被误删；192 条原值仍保留在地理上下文字段。

### 2.4 为什么演示会高估完整率

- 每个来源只选 48 条左右适合回归的记录，联合演示是工程样板，不是随机样本。
- GEMStat 七元素全量 3,739,180 条观测中有 3,459,955 条没有定义方法代码，即只有 7.47% 方法明确；当前 56 条演示特意选择了方法明确且质量较好的记录。
- GEOROC、USGS、GSJ 和 GEOTRACES 的演示长表中分析方法为空，现已逐条标明缺失原因；相应报告或论文可能有数据集级方法，仍需建立带 scope 的文档连接，不能直接填成逐记录方法。
- 坐标完整的演示不能证明全量来源没有缺坐标、错误 CRS 或坐标精度问题。

V4 必须同时发布 `full_population_profile` 和 `demo_profile`，禁止用演示完整率替代全量完整率。每份覆盖或完整率报告必须携带 `as_of`、`fixture_or_snapshot_id`、`source_count`、`profile_scope=historical_fixture|current_demo|full_population`、`denominator_definition` 和生成代码提交号；缺少这些元数据的百分比不能进入正式进展结论。

### 2.5 数据质量风险分级

| 风险 | 证据 | 影响 | 严重度 | V4 处理 |
|---|---|---|---|---|
| 样品类型在交换层丢失 | 历史 27 列长表没有 `sample_type` 等字段 | 无法可靠按样品类型查询、制图和分组 | Resolved in M2 | 736/736 已回填并纳入生成器和回归测试 |
| 地理上下文冒充地质单元 | 历史 `LOCATION`、图幅、航线写入 `geologic_unit` | 按地质单元统计可能产生错误结论 | Resolved in M2 | 旧字段清零，192 条迁入四类地理上下文字段；真正地质单元仍为空 |
| 方法完整率被 demo 高估 | GEMStat demo 选方法明确记录，全量方法完整率实测 7.47% | 置信度和可比较记录数量被高估 | Resolved in M4 | 已发布 full/demo 两套 profile；覆盖立方体只把 279,225/3,739,180 条 GEMStat 测定计为最低可比 |
| 文献覆盖口径混合 | 数据集 DOI、原始论文、方法文献未分 scope | 来源追溯看似完整但不能回到测定依据 | Medium | 增加 citation scope 和逐层覆盖率 |
| “开源许可”术语过宽 | CC、公共领域、自定义引用条款被合并描述 | 科研使用说明和署名要求可能失真 | Medium | 分开访问、研究使用和许可字段 |
| 历史/当前 fixture 数字混用 | 304 与 736 属于不同版本 | 进展报告和覆盖率不可比较 | Medium | 所有报告携带 fixture/version/as_of 和分母 |

## 三、数据量差异应该怎样衡量

### 3.1 不再只报原始行数

每种介质同时报告以下六个指标：

1. `observation_count`：元素测定数；
2. `distinct_sample_count`：不同物理样品数；
3. `independent_lineage_count`：独立上游项目/调查数；
4. `valid_coordinate_sample_count`：有可用坐标的不同样品数；
5. `comparable_observation_count`：元素、单位、样品类型、measurement basis 和方法范围足以进入明确比较组的测定数；
6. `covered_spatial_cells`：在声明分辨率下有实测点的空间格网数，不插值冒充观测。

“数据多”至少要说明是测定多、样品多、独立来源多、地区多，还是可比较记录多。

### 3.2 当前水体并非简单的“原始记录少”

当前已登记水体目标观测包括：

- GEMStat As/Cr/Cu/Hg/Ni/Pb/Zn：3,739,180 条；
- GEOTRACES Cu/Ni/Zn：39,327 条；
- FOREGS stream water：4,848 条。
- USGS/WQP Sacramento River dissolved As：189 条。

数量合计很大，但高度集中在 GEMStat 的单一 As 路线，且大量记录缺少明确方法。GEOTRACES 是航线覆盖，FOREGS 是低密度欧洲溪流水。严格按元素、分相、方法、空间背景和质量筛选后，可比较记录会明显减少。

因此用户看到的“水体数据少”，更准确地说是：

- 独立来源少；
- 元素—水体类型—分相组合不均衡；
- 方法完整的记录少；
- 海水、河水、湖水、地下水不能直接合并；
- 空间上不是规则全球覆盖。

沉积物也类似：当前有四个可执行数据集，但主要集中在挪威海域、日本河流和欧洲低密度基线，南美、非洲、北美地方调查、湖泊和更多海洋沉积物仍不足。

## 四、V4 数据模型修正

### 4.1 样品类型与分析方法彻底分离

样品类型回答“采了什么”；分析方法回答“怎样测的”。分析方法不能决定样品类型。

样品类型的解析优先级：

1. 来源记录逐样品显式字段；
2. 来源文件或产品显式层位/介质常量；
3. 数据集方法文档明确适用于全部记录的常量；
4. 有版本的受控词汇映射；
5. 无法确定时为 `unknown`，并记录缺失原因。

禁止规则：

- 不因 `ICP-MS` 推断为水样或土壤；
- 不因 `aqua regia` 推断为某种沉积物；
- 不因单位 `mg/kg` 推断为岩石、土壤或沉积物；
- 不把数据集标题中的宽泛介质覆盖到与其矛盾的逐行字段。

### 4.2 新的样品分类字段

保留现有 `medium` 作为一级大类，并增加：

| 字段 | 含义 | 示例 |
|---|---|---|
| `sample_type_raw` | 来源原始样品类型 | `Topsoil`, `stream sediment composite` |
| `sample_type` | 规范化二级类型 | `soil_topsoil`, `sediment_stream` |
| `sample_type_mapping_status` | 映射状态 | `exact`, `dataset_constant`, `unmapped` |
| `material_raw` | 原始材料或岩性描述 | `whole rock`, `humus` |
| `lithology_raw` / `lithology` | 岩石类型 | `basalt`, `granite` |
| `soil_horizon_raw` / `soil_horizon` | 土层或深度类型 | `A horizon`, `0-20 cm` |
| `sediment_environment` | 沉积环境 | `stream`, `floodplain`, `marine`, `lake` |
| `grain_fraction` | 筛分/粒级 | `<150 µm` |
| `water_body_type` | 水体类型 | `river`, `lake`, `groundwater`, `seawater` |
| `water_fraction` | 操作性分相 | `dissolved`, `suspended`, `total` |
| `filtered_state` | 过滤状态和孔径 | `filtered_<0.45um` |
| `sample_depth_min_m/max_m` | 采样深度 | `0`, `0.2` |

这些字段进入归档实体、D1→D2 长表、`geochemistry.csv`、SQLite 查询视图、GeoJSON、地图提示和筛选器。

### 4.3 地质背景拆分

新增三个互不替代的概念：

| 概念 | 字段 | 规则 |
|---|---|---|
| 地理上下文 | `geographic_context_raw`, `survey_area`, `map_sheet` | 保存地区、航次、图幅和项目范围，不称为地质单元 |
| 来源报告的地质背景 | `geologic_unit_raw`, `lithology_raw`, `geologic_age_raw`, `tectonic_setting_raw` | 来源明确提供时原样保存 |
| 空间匹配的地质背景 | `matched_geologic_unit`, `geology_map_source`, `geology_map_version`, `match_method`, `match_scale`, `boundary_distance_m`, `match_uncertainty` | 必须绑定地质图版本、比例尺和匹配证据 |

空间匹配结果不能覆盖来源原始地质字段。位于边界、离岸或地图空白处时保留多个候选或 `unmatched`，不强制指派。

### 4.4 分析方法增加适用范围

现有 analytical method 实体继续保留，并新增：

- `method_scope`：`observation | sample | batch | file | dataset | publication`；
- `method_assignment_basis`：来源字段、批次连接、文件常量、数据集文档或论文；
- `preparation`、`digestion_or_extraction`、`technique`、`instrument`、`laboratory`；
- `detection_limit`、`quantitation_limit`、`reference_materials`、`blank_qc`、`replicate_qc`；
- `method_source_locator` 和 `method_publication_id`；
- `method_missing_reason`。

如果只知道数据集级方法，允许使用，但必须显示 `method_scope=dataset`，其置信度低于逐记录或批次连接，不冒充行级事实。

### 4.5 公开文献关联增加适用范围

文献关系与方法关系一样需要 scope：

- `citation_id_raw`：来源原始引用代码；
- `publication_id`、`publication_doi`、`citation_text_raw`；
- `citation_scope`：`dataset | file | sampling_event | sample | observation | method`；
- `citation_assignment_basis`：逐行字段、文件常量、数据集元数据或人工核对；
- `upstream_primary_source_id`：聚合来源指向的原论文或原调查；
- `citation_resolution_status`：`resolved | partial | unresolved | not_reported`。

GEOROC 的 `citation_ids` 继续作为记录级样板；其他来源只有数据集 DOI 时，明确标记 `citation_scope=dataset`。引用覆盖率不能仅以“有 DOI”判断。

### 4.6 访问、科研使用与许可分层

不再使用一个 `open=true/false` 字段概括所有条件，改为：

- `access_status`：是否公开可访问、是否需登录或申请；
- `research_use_status`：当前科研分析是否允许；
- `license_id`、`license_url`、`license_scope`；
- `attribution_required` 和 `citation_text`；
- `redistribution_status`：仅作事实记录，不作为本项目科研分析的默认硬门禁；
- `terms_verified_at` 和条款证据定位。

“公开平台”只说明访问方式，不自动证明标准开放许可；“科研可用”也不自动意味着可以把原始文件重新发布。

### 4.7 自动采集健康状态

每个 adapter 增加可机器检查的运行状态：

- `last_successful_fetch_at`、`last_successful_parse_at`；
- `online/cached/offline_fixture` 支持情况；
- 固定版本、响应 hash、成员 hash 和 schema fingerprint；
- `version_drift`、`schema_drift`、`row_count_drift`；
- 超时、重试、缓存命中和降级路径；
- 最近失败原因以及是否影响旧快照复现。

自动采集验收不是“脚本存在”，而是能够发现上游变化、失败关闭并从已验证快照重放。

## 五、全量字段完整率报告

新增 `scripts/profile_source_completeness.py`，对每个可执行来源的全量缓存生成：

- `field_completeness.json`：逐字段非空、有效、显式缺失原因的数量和比例；
- `method_completeness.json`：按方法适用范围统计；
- `sample_type_coverage.json`：介质、样品类型、层位、分相和粒级组合；
- `spatial_coverage.json`：点数、国家/区域、bbox、空间格网和 CRS/不确定度；
- `geology_coverage.json`：来源地质字段与空间匹配字段分开统计；
- `citation_coverage.json`：按 citation scope 统计文献连接、DOI 解析和上游原始来源覆盖；
- `usage_rights_coverage.json`：访问、科研使用、许可和署名字段完整率；
- `automation_health.json`：在线获取、缓存、快照、漂移和失败降级状态；
- `coverage-cube.parquet` 或 CSV：按来源、介质、元素、样品类型、方法和地区查询。

每个比例必须携带分母，不允许只写“覆盖率高”。演示报告和全量报告分别命名。

## 六、V4 补源策略

V4 采用两条并行线：语义修正不等待补源，补源也不绕过新 schema。

### 6.1 水体优先线

1. **已完成**：将 GEMStat 从仅 As 扩展为 As/Cr/Cu/Hg/Ni/Pb/Zn，按水体类型、分相、方法代码和质量分层，同站同时间同深度按物理采样事件去重；
2. **已完成首个样板**：接入 USGS/WQP Sacramento River 单站 dissolved As，逐记录保留方法、检出限、Accepted/Preliminary 和 routine/field-replicate 状态；
3. **已完成**：连接 GEOTRACES contributor/method metadata；唯一方法记录可赋值，多候选只保留候选集；
4. 审计 EMODnet 一个明确版本的海水数据产品，回溯到记录级提供者，避免与 GEOTRACES/PANGAEA 重复计数；
5. 对 river/lake/groundwater/seawater、dissolved/suspended/total 分别报告覆盖。

### 6.2 沉积物优先线

1. 接入 NGSA Australia Hg，固定产品 DOI、粒级、单位、方法、检出限和坐标；
2. 将 GSJ marine sediment 作为独立产品接入，不与现有 river sediment 混为一个样品类型；
3. 从 BC RGS、PANGAEA、NOAA NCEI 或 IODP 中选择至少一个具体、不可变、含数值和方法的沉积物数据集；
4. 优先补南美、非洲、北美地方调查和湖泊/海洋空白；
5. stream/floodplain/lake/marine 与不同粒级、总量/浸出量始终隔离。

### 6.3 土壤和岩石持续线

土壤和岩石不停止补源，但不再占用全部适配器产能：

- TPDC 中国山地土壤：**已完成官方文件契约和全量字段审计，暂不接旧 schema**。DOI 解析到固定 TPDC UUID，metadata/file API 与 1,828,683-byte ZIP 已验证；主表 1,314 行、O/A/C 三层、五目标元素 6,570 条，母岩/土类/坐标齐全。As/Hg 缺失、CRS 未声明，独立 BD 表与主表存在六个非空值和五个坐标冲突；下一步在 V4 schema 中显式保留冲突后再实现 adapter；
- AfSIS Phase I：**已完成首轮工程闭环**。使用官方 Dataverse V2.0（2025-10-13 发布），固定三份 original 文件、publisher MD5、SHA-256 和 DOI；对账 2,002 个唯一样品、18 个国家标签、51 个站点、上下层、六个目标元素、方法与全局 DL/QL。下一步是具名签署 30 条复核和将全量质量统计接入 V4 profile；
- GEMAS：作为欧洲农业/放牧土壤独立来源，和 FOREGS 父项目血缘去重；
- GEOROC Antarctica Intraplate Volcanics：补具体岩石专题和构造背景；
- 岩石再增加至少一个与 GEOROC 预编译集不同血缘的可执行来源。

建议资源分配：水体与沉积物 60%，土壤与岩石 40%。这只是排期权重，不是拒绝其他高价值来源的硬门禁。

## 七、质量评分改造

所有目标均作为置信度维度，不作为必须全部满足的二元硬门禁；缺失越多，允许的使用层级和置信度越低。

建议新增记录级维度：

| 维度 | 目标 | 缺失时处理 |
|---|---|---|
| 元素、值、单位、来源定位 | 接近 100% | 无法解释的记录不得进入数值分析，但可保留证据 |
| 坐标语义 | 原值、CRS、转换和不确定度齐全 | 降低空间置信度，不能做精确空间匹配 |
| 样品类型 | 明确 raw 值或有证据的数据集常量 | 进入 `unknown` 类型，不能和已知类型合并 |
| 方法 | 至少有 technique + preparation/digestion，并标明 scope | 进入方法未知组，降低可比性和置信度 |
| 地质背景 | 来源显式或有版本的空间匹配 | 允许地质背景为空，不伪造；不能按地质单元输出结论 |
| QC | 检出限、限定符、重复、空白/标准物质尽可能完整 | 缺失进入置信度扣分和限制说明 |
| 文献关联 | DOI/引用文本有明确 scope 和来源定位 | 数据集级引用不能替代测定或方法文献，降低追溯粒度评分 |
| 使用条件 | 访问、科研使用、许可、署名分别有证据 | 条款未知时限制自动路由并提示人工核对，不影响已保存的科学事实 |
| 自动化健康 | 获取、解析、hash、schema 与离线重放可验证 | 漂移或下载失败时降级到最后验证快照并报告陈旧度 |

来源级分数与记录级完整率分开：官方来源也可能有低完整率记录；低完整率记录不会因为来源权威而自动变成高置信度。

## 八、查询、地图与最终输出

V4 请求正式支持：

- `sample_types`；
- `water_body_types`、`water_fractions`；
- `sediment_environments`；
- `soil_horizons`；
- `lithologies`；
- `geologic_units`；
- `method_scopes`、`analytical_techniques`。

地图筛选器从当前“元素、介质、置信度、异常”扩展为：

1. 元素；
2. 区域；
3. 一级介质；
4. 样品类型；
5. 地质单元或“未匹配”；
6. 分析方法/方法适用范围；
7. measurement basis；
8. 置信度和 QC；
9. 来源。

任何“按地质单元”的统计都必须显示地质单元来源、地图版本、匹配方式和未匹配比例。

## 九、实施里程碑

| 里程碑 | 预计 | 主要交付 | 完成标准 |
|---|---:|---|---|
| V4-M0：全量审计（完成） | 1 天 | 十五来源 full/demo completeness、文献、使用条件和自动化健康报告 | 15/15 verified cache 已统一逐字段解析；3,988,430 条全量目标测定与 792 条 demo 分开报告 |
| V4-M1：Schema v2 | 1–2 天 | sample/method/geology schema、交换长表和迁移说明 | `sample_type` 等字段从归档贯通到输出；旧字段可兼容读取 |
| V4-M2：现有来源回填（完成） | 2–3 天 | 当前适配器字段回填、方法 scope、地理/地质拆分 | 不再把地区/图幅/航线冒充地质单元；所有缺失有原因 |
| V4-M3：覆盖立方体（完成） | 1 天 | 六类数量指标、空间格网、介质平衡报告 | 6,651 个 source×medium×element×sample type×method×region×basis 单元，四介质均同时报告六类指标 |
| V4-M4：水体增强（完成） | 2–4 天 | GEMStat 多元素、GEOTRACES 方法、独立淡水来源 | 七元素、多水体类型/分相/方法已可查询；新增 WQP 独立淡水血缘并量化覆盖收益 |
| V4-M5：沉积物增强 | 2–4 天 | NGSA、GSJ marine、一个独立具体数据集 | stream/floodplain/lake/marine 至少显式分型，不混合 |
| V4-M6：土壤/岩石扩展 | 进行中 | AfSIS 已完成；TPDC 文件契约已冻结；继续 GEMAS、GEOROC Antarctica 和 TPDC V4 adapter | 新数据遵守 V4 schema，不产生新的字段债务 |
| V4-M7：联合验收 | 1–2 天 | 新联合 fixture、查询索引、地图和测试 | 按元素、区域、地质单元、样品类型和方法均能运行并解释缺口 |

## 十、必须新增的测试

1. `sample_type` 不能从 analytical method、单位或元素名称推断；
2. `sample_type_raw`、规范值和映射证据必须同时保留；
3. `survey_area`、`map_sheet` 和 `cruise_track` 不能写入规范 `geologic_unit`；
4. 数据集级方法必须带 `method_scope=dataset`，不能冒充逐记录方法；
5. 水体分相和过滤状态必须进入标准输出，不能只留在 evidence JSON；
6. 不同样品类型、分相、粒级和方法默认不能进入同一异常背景组；
7. 完整率报告必须基于全量缓存，并能证明与演示报告的分母不同；
8. 覆盖报告必须同时给出 observation、sample、lineage、coordinate、comparable 和 spatial-cell 数量；
9. 地质空间匹配必须携带地图版本、比例尺、匹配方式和不确定度；
10. 数据集 DOI、方法论文和逐记录原始文献不能被错误合并为同一 citation scope；
11. 公开访问、自定义科研条款和标准开放许可必须可区分；
12. adapter 必须检测 hash/schema 漂移，并能从最后验证快照离线重放；
13. 旧 V3 请求在兼容模式下仍能运行，但输出明确标出缺失的新字段。

## 十一、V4 完成定义

V4 完成不等于“所有字段都不为空”，而是：

- 能明确区分来源没有报告、暂未解析、不适用和解析失败；
- 样品类型不再在交换层丢失，也不再由分析方法错误推断；
- 地理上下文和真正地质背景不再混用；
- 方法信息带适用范围和证据定位；
- 公开文献按数据集、方法、样品和测定层级分别追溯；
- 访问状态、科研使用条件和许可类型不再混为“开源”；
- 自动采集不仅能运行，还能报告版本/字段漂移和降级状态；
- 水体和沉积物的不足通过独立来源数、样品数、可比较记录和空间覆盖共同度量；
- 新增来源不会因记录多就被宣称更全面；
- 最终确实支持按元素、区域、地质单元和样品类型查询、归档、检索与制图；
- 所有不足都会降低对应置信度或限制使用模式，但不会因为没有满足全部目标而被一刀切删除。

## 十二、建议的执行顺序

审阅通过后按以下顺序开始：

1. 先实现 V4-M0 全量字段、文献、使用条件和自动化健康审计；
2. 紧接着修复交换长表缺失 `sample_type`、`water_fraction` 等字段；
3. 清理当前 `geologic_unit` 中的地区/图幅/航线值；
4. 为当前十四来源补 method scope 和缺失原因；
5. 再并行推进水体/沉积物补源与 TPDC、GEMAS、GEOROC Antarctica 等地区补源；
6. 最后重建联合 fixture、覆盖矩阵、地图和置信度报告。

在 M0–M2 完成之前可以继续发现和冻结新来源，但不应再把新来源接入旧的 27 列交换契约，以免扩大样品类型和地质背景的字段债务。

## 十三、当前执行记录

| 时间（Asia/Shanghai） | 事项 | 结果 | 下一步 |
|---|---|---|---|
| 2026-08-06 18:35 | TPDC 中国山地土壤官方文件契约与全量字段审计 | DOI `10.11888/Terre.tpdc.302620` 解析到固定 UUID，核实 metadata POST、文件清单 GET、file-ID POST 下载与 CC BY 4.0 code；固定 1,828,683-byte ZIP 及三成员 SHA-256。主表对账 1,314 条唯一 O/A/C 层记录、30 座山地、166 站点和 6,570 条 Cr/Cu/Ni/Pb/Zn 测定；As/Hg 缺失。坐标、母岩和土类逐行完整但 CRS 未声明；BD 补表能补 58 个缺失行，同时有六个非空 BD 冲突、五个坐标冲突和十个无匹配行。已写候选审计、目录和使用边界，没有提前计入十四个可执行来源 | 实现 V4-M0 profile 输出契约与 M1 sample/method/geology schema；随后用双值/冲突字段接入 TPDC adapter 和 30 条复核 |
| 2026-08-06 18:05 | AfSIS Phase I V2.0 非洲土壤工程闭环 | 从 World Agroforestry 官方 Dataverse 固定 3 份 original CSV/XLSX，publisher MD5 与 SHA-256 双重对账；解析 2,002 个唯一 SSN/RES.ID、18 个国家标签、51 个国家-站点对、1,876 个完整坐标对和 12,012 条六元素数值。逐元素附加 ICP-MS/ICP-OES、王水准全量基础、DL/QL、负数及低于限值标记；Pb 的 1,969 条正值低于 DL 被保留并降级解释。30 条复核样本覆盖全部国家标签、上下层、缺坐标、负数与阈值类别，机器 30/30 通过、人工未签署；48 条正值样板并入联合包，当前为 14 个 A/`normalized_analysis` 来源、736 条观测、89 个比较组、16 个工程异常候选 | 优先解析 TPDC 官方文件下载链路；并推进 GEMAS/NGSA 与 GEOROC Antarctica，人工签署独立跟进 |
| 2026-08-06 18:55 | V4-M0/M1 首批实现与独立自查 | 新增十四来源 full/demo 分口径 profile，确认 12/14 有候选全量审计、12/14 有明确目标测定分母、0/14 完成统一全量逐字段统计；新增 sample/method v2 归档 schema、archive→exchange exporter、扩展标准输出、SQLite 查询与地图筛选，V3 输入继续兼容。默认异常分组停止使用混杂旧 `geologic_unit`，比较组由 89 个语义修正为 80 个，16 个工程异常候选不变。组件 178/178、端到端 22/22 通过。自查确认生产联合样板的新样品类型、方法 scope 和引用 scope 仍为 0/736，旧 `geologic_unit` 192 条兼容值尚未清理 | 执行 M2 十四来源回填和地质语义清理；同时补 GEOROC/USGS 全量审计与统一 adapter profile |
| 2026-08-06 21:25 | V4-M2 十四来源语义回填 | 新增集中式 evidence-bound 映射并接入正式 demo 生成器；十四个 source demo 全部迁移且可逐字节复核。736/736 有 raw/canonical 样品类型与映射依据，288/288 土壤有层位，256/256 沉积物有环境，144/144 水体有类型与分相；544/544 已知方法带 scope，192/192 未知方法带原因；引用、访问、科研使用和许可定位 736/736。旧 `geologic_unit` 清零，192 条迁到地理上下文。比较组由 80 个增至 93 个，异常候选由 16 个重算为 11 个，不解释为自然异常减少。组件 184/184、端到端 22/22 通过 | 完成 M0 全量统一 profile 与 M3 覆盖立方体；补四个方法缺口和真正地质背景 |
| 2026-08-06 21:49 | V4-M0 全量审计与 M3 覆盖立方体 | 从 14 个 verified full cache 全量解析 742,060 条目标测定和 554,429 个逐来源去重样品；549,510 个样品有有效坐标，只有 105,279 条达到最低可比条件。生成 112 份分来源字段/方法/样品/空间/地质/引用/使用条件/自动化健康文件、5,773 行覆盖立方体和四介质平衡报告。水体虽有 537,174 条测定但仅 3 条独立血缘，GEMStat 方法完整率为 8.78%；MarChem 当前外层 ZIP 漂移，但数据与方法成员 hash 与冻结快照逐字节一致。GEOROC 全量显式岩性 65,988/65,988、年龄 61,418/65,988、构造背景 65,988/65,988，未伪造成地质单元；相应 48 条 demo 已回填 | 执行 M4：GEMStat 七元素扩展、GEOTRACES contributor/method 连接，并审计一个独立淡水或海水来源 |
| 2026-08-06 23:46 | V4-M4 水体增强完成 | GEMStat v3 从 As 扩为 As/Cr/Cu/Hg/Ni/Pb/Zn，精确解析 3,739,180 条测定、689,291 个物理采样事件、17,248 个站点和 35 国；Cr-VI 不计作元素 Cr，四种操作分相、删失和质量标签全部保留。GEOTRACES 39,327 条目标观测全部连接到 96 个航次×元素元数据组，其中 22,254 条只有一个 BODC 方法记录并可赋值，17,073 条为多候选并明确不猜。新增 USGS/WQP Sacramento River 单站 189 条 dissolved As，方法、实验室、检出限、Accepted/Preliminary 和 field replicate 均逐行保留。15 来源全量重算为 3,988,430 条测定、758,237 个样品、363,662 条最低可比测定和 6,651 行覆盖立方体；792 条联合 fixture、111 个比较组、190 项组件检查和 22 项端到端检查通过 | 执行 M5：NGSA、GSJ marine 与一个具体独立沉积物来源；所有新增来源继续使用 V4 schema 和全量 profile |
