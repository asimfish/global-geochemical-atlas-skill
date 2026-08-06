# D1 数据语义、字段完整率与介质覆盖平衡 V4 计划（审阅稿）

更新时间：2026-08-06 17:30（Asia/Shanghai）

状态：待审阅，尚未开始 V4 代码迁移

承接版本：`plans/d1-data-source-system-v3-plan.md`

当前基线：分支 `d1/source-system-v2`，提交 `22ea938`

## 一、结论先行

当前系统并不是四类信息都同样完整。

1. **元素含量**：当前十三个可执行数据集都能输出元素、原始数值、单位和来源定位；联合演示中的完整率为 100%。但演示只抽取可用记录，不能代表全量数据的缺失率。
2. **采样坐标**：联合演示 688/688 有坐标，但这是经过筛选的演示切片。正式报告还没有按全量来源统计“原始坐标、CRS、转换方式和坐标不确定度”的完整率。
3. **地质背景**：当前明显不足。联合演示中只有 192/688（27.9%）的 `geologic_unit` 非空，而且其中一部分其实是地区名、图幅名或航次范围，并不是真正的地质单元。现状不能表述为“已经完整采集地质背景”。
4. **分析方法**：联合演示中 496/688（72.1%）非空，但不同来源的粒度不一致，有的是逐记录方法，有的是批次或数据集说明，有的完全缺失。演示还主动选择了方法明确的 GEMStat 记录，因此会高估全量完整率。
5. **样品类型**：这是当前最直接的结构缺口。归档层虽有 `medium_raw`、`material_raw`、`soil_horizon_raw`、`grain_fraction_raw` 和 `filtered_state_raw`，但 D1→D2 的 27 列交换长表没有 `sample_type`、`water_fraction`、`sediment_environment` 等字段。适配器已经提取的一部分信息在扁平输出时被丢弃，最终不能真正支持“按样品类型”查询和制图。

V4 的第一优先级不是继续增加来源名称，而是让“元素—坐标—地质背景—分析方法—样品类型”五类信息在归档、交换、查询、地图和置信度中使用同一套可追溯语义。第二优先级才是按可比较覆盖补齐水体和沉积物。

## 二、当前审计基线

### 2.1 十三个可执行数据集

| 介质 | 可执行数据集数 | 数据集 |
|---|---:|---|
| 岩石 | 1 | GEOROC Archaean Cratons |
| 土壤 | 5 | USGS CONUS、PANGAEA North Africa、FOREGS topsoil/subsoil/humus |
| 沉积物 | 4 | MarChem、GSJ Japan、FOREGS stream/floodplain sediment |
| 水体 | 3 | GEOTRACES、GEMStat、FOREGS stream water |

岩石的记录量较大，但只有一个可执行来源；土壤来源数量最多；水体和沉积物来源数量及地理类型仍较少。不能用单一“记录总数”判断哪种介质更全面。

### 2.2 联合演示字段完整率

下表统计的是当前 688 条 hash 固定联合演示，不是全量来源总体。

| 介质 | 演示记录 | 元素+值 | 坐标 | `geologic_unit` 非空 | 分析方法非空 | 标准输出中的样品类型 |
|---|---:|---:|---:|---:|---:|---:|
| 岩石 | 48 | 100% | 100% | 100%* | 0% | 0% |
| 土壤 | 240 | 100% | 100% | 20.0%* | 80.0% | 0% |
| 沉积物 | 256 | 100% | 100% | 18.8%* | 81.3% | 0% |
| 水体 | 144 | 100% | 100% | 33.3%* | 66.7% | 0% |
| 合计 | 688 | 100% | 100% | 27.9%* | 72.1% | 0% |

`*`：非空不等于语义正确。当前字段中包含 `LOCATION`、`Area`、日本图幅名和 `global_ocean_cruise_track` 等地理上下文，这些值必须从真正的地质单元中拆出。

### 2.3 为什么演示会高估完整率

- 每个来源只选 48 条左右适合回归的记录，联合演示是工程样板，不是随机样本。
- GEMStat 全量 492,999 条 As 观测中有 449,714 条没有定义方法代码，即只有约 8.8% 方法明确；当前演示特意选择了方法明确且质量较好的记录。
- GEOROC、USGS、GSJ 和 GEOTRACES 的演示长表中分析方法为空，但相应报告或论文可能有数据集级方法。当前系统没有表达“方法适用于逐记录、批次、文件、数据集还是论文”的范围。
- 坐标完整的演示不能证明全量来源没有缺坐标、错误 CRS 或坐标精度问题。

V4 必须同时发布 `full_population_profile` 和 `demo_profile`，禁止用演示完整率替代全量完整率。

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

当前已登记水体目标观测至少包括：

- GEMStat As：492,999 条；
- GEOTRACES Cu/Ni/Zn：39,327 条；
- FOREGS stream water：4,848 条。

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

## 五、全量字段完整率报告

新增 `scripts/profile_source_completeness.py`，对每个可执行来源的全量缓存生成：

- `field_completeness.json`：逐字段非空、有效、显式缺失原因的数量和比例；
- `method_completeness.json`：按方法适用范围统计；
- `sample_type_coverage.json`：介质、样品类型、层位、分相和粒级组合；
- `spatial_coverage.json`：点数、国家/区域、bbox、空间格网和 CRS/不确定度；
- `geology_coverage.json`：来源地质字段与空间匹配字段分开统计；
- `coverage-cube.parquet` 或 CSV：按来源、介质、元素、样品类型、方法和地区查询。

每个比例必须携带分母，不允许只写“覆盖率高”。演示报告和全量报告分别命名。

## 六、V4 补源策略

V4 采用两条并行线：语义修正不等待补源，补源也不绕过新 schema。

### 6.1 水体优先线

1. 将 GEMStat 从仅 As 扩展为 As/Cr/Cu/Hg/Ni/Pb/Zn，按水体类型、分相、方法代码和质量分层，不把同站重复上报当独立证据；
2. 补一个方法和 QC 较完整的独立淡水来源，优先审计 US Water Quality Portal 或 EEA/国家水质发布；
3. 完成 GEOTRACES contributor/method metadata 连接，不能只写 `contributor-specific protocol`；
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

- TPDC 中国山地土壤：补中国、土层、母岩和环境背景；
- AfSIS Phase I：补非洲十八国标签、topsoil/subsoil、坐标和方法；正式接入必须使用当前官方 Dataverse V2.0（2025-10-13 发布），而不是沿用旧的 V1 描述；
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
| V4-M0：全量审计 | 1 天 | 十三来源 full/demo completeness 报告 | 能回答每个来源五类核心字段的真实完整率，演示与全量分开 |
| V4-M1：Schema v2 | 1–2 天 | sample/method/geology schema、交换长表和迁移说明 | `sample_type` 等字段从归档贯通到输出；旧字段可兼容读取 |
| V4-M2：十三来源回填 | 2–3 天 | 当前适配器字段回填、方法 scope、地理/地质拆分 | 不再把地区/图幅/航线冒充地质单元；所有缺失有原因 |
| V4-M3：覆盖立方体 | 1 天 | 六类数量指标、空间格网、介质平衡报告 | 不再只用 observation count 宣称全面 |
| V4-M4：水体增强 | 2–4 天 | GEMStat 多元素、GEOTRACES 方法、独立淡水或海水来源 | 水体按类型/分相/方法可查询，覆盖收益可量化 |
| V4-M5：沉积物增强 | 2–4 天 | NGSA、GSJ marine、一个独立具体数据集 | stream/floodplain/lake/marine 至少显式分型，不混合 |
| V4-M6：土壤/岩石扩展 | 2–4 天 | TPDC、AfSIS、GEMAS、GEOROC Antarctica 中已完成文件契约的来源 | 新数据遵守 V4 schema，不产生新的字段债务 |
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
10. 旧 V3 请求在兼容模式下仍能运行，但输出明确标出缺失的新字段。

## 十一、V4 完成定义

V4 完成不等于“所有字段都不为空”，而是：

- 能明确区分来源没有报告、暂未解析、不适用和解析失败；
- 样品类型不再在交换层丢失，也不再由分析方法错误推断；
- 地理上下文和真正地质背景不再混用；
- 方法信息带适用范围和证据定位；
- 水体和沉积物的不足通过独立来源数、样品数、可比较记录和空间覆盖共同度量；
- 新增来源不会因记录多就被宣称更全面；
- 最终确实支持按元素、区域、地质单元和样品类型查询、归档、检索与制图；
- 所有不足都会降低对应置信度或限制使用模式，但不会因为没有满足全部目标而被一刀切删除。

## 十二、建议的执行顺序

审阅通过后按以下顺序开始：

1. 先实现 V4-M0 全量字段审计；
2. 紧接着修复交换长表缺失 `sample_type`、`water_fraction` 等字段；
3. 清理当前 `geologic_unit` 中的地区/图幅/航线值；
4. 为当前十三来源补 method scope 和缺失原因；
5. 再并行推进水体/沉积物补源与 TPDC/AfSIS 等地区补源；
6. 最后重建联合 fixture、覆盖矩阵、地图和置信度报告。

在 M0–M2 完成之前可以继续发现和冻结新来源，但不应再把新来源接入旧的 27 列交换契约，以免扩大样品类型和地质背景的字段债务。
