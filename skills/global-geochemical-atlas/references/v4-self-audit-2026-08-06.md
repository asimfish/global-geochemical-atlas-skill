# V4 阶段自查（2026-08-06）

> 这是 2026-08-06 的历史快照，已被当前 26 来源、4,096,615 条观测的全量能力报告取代。当前默认按需获取、小 fixture 和增量缓存；全量构建仅用于显式发布/验收。V4 不计算、读取、比对或更新 MD5/SHA 内容哈希。

> 2026-08-07 D2 已支持对版本固定的 PANGAEA.788537 GLiM 0.5° 栅格执行可选 point-in-cell，并记录来源、版本、分辨率、边界距离和不确定性。下文“真正地质单元仍未匹配”仍适用于场地级地层/构造单元：GLiM 只补充主导表层岩性筛查上下文。

审计时间：2026-08-06 21:49（Asia/Shanghai）

审计口径：按预期粒度分别检查归档实体、交换记录、来源 demo、全量候选审计、标准输出和查询索引。演示样板不作为全量来源分母。

## 结论

V4-M0、M2 和 M3 已完成。十四来源不仅完成 736 条演示回填，也已从 verified full cache 逐条解析全部 742,060 条目标测定。每个来源均生成统一字段、方法、样品类型、空间、地质、引用、使用条件和自动化健康 profile；覆盖立方体包含 5,773 个明确比较单元。

全量结果表明，记录量与可比覆盖差异很大：554,429 个逐来源去重样品中 549,510 个有有效坐标，但只有 105,279 条测定同时具备数值、单位、样品类型、坐标、measurement basis、方法和 scope。真正的地质单元仍未采集或空间匹配；不过 GEOROC 已显式提供岩性、地质年龄和构造背景，现已与地质单元分开保留。

验证结果：

- `component_test.py`：185/185 PASS；
- `self_test.py`：22/22 PASS；
- v2 归档关系校验：PASS；
- v1/v2 SQLite 构建与查询：PASS；
- 十四来源 full profile 与覆盖立方体从当时缓存重建：PASS。

## 数据质量发现

| 严重度 | 发现 | 证据 | 下游风险 | 处理建议 |
|---|---|---|---|---|
| Resolved | 全量逐字段完整率此前不可统一比较 | 14/14 已在 verified full cache 上生成统一 numerator/denominator；候选审计仍单独保留为 12/14 | 当时可以一致回答全量字段完整率，同时不会把 demo 冒充全量 | 用 `build_v4_full_profiles.py --check` 保持版本、字节数、成员、schema、row-count 和关键统计漂移检测 |
| High | 当前没有可用的真正地质单元 | `geologic_unit_raw` 与 `matched_geologic_unit` 在 demo 和全量 profile 中仍为 0；GEOROC 的 65,988 条岩性、61,418 条年龄和 65,988 条构造背景已另列 | 能按岩性/年龄/构造背景筛选，但不能冒充按地质单元统计 | 引入带版本、比例尺与边界不确定度的地质图空间匹配，或补来源显式 unit 字段 |
| High | 四个来源仍缺方法 | GEOROC、GEOTRACES、GSJ、USGS 共 192 条没有 `analytical_method/method_scope`，但全部带 `method_missing_reason` | 这些记录只能在“方法未知”组使用，不能和已知方法数据直接比较 | 优先连接 GEOTRACES contributor metadata、USGS/GSJ 方法文档和 GEOROC 原始论文方法 |
| Medium | 引用尚未成为独立关系表 | GEOROC 的一对多 citation ID 和文本已作为 JSON 列表进入交换 CSV，evidence JSON 也完整保留；但 SQLite 仍主要依赖 method-publication 关系 | 按文献反查全部测定或区分 dataset/method/observation citation 的查询仍不够直接 | 在归档层增加 observation-citation 关系表，CSV 继续作为查询摘要而非唯一证据载体 |
| Medium | JSON Schema 文件没有被完整运行时执行 | 当前 validator 检查实体版本、关系、缺失原因和关键 v2 语义，但未执行 draft 2020-12 的所有关键字 | 将来新增字段时可能通过手写校验但违反 schema 的 enum/type/additionalProperties | 增加固定依赖或标准库兼容的 schema 校验步骤，并加入非法类型/多余字段测试 |
| Medium | 在线实时健康与可复现缓存审计仍需分开 | 14/14 已记录文件身份、字节数、schema fingerprint、row-count、最后成功 fetch/parse 与离线重放；在线状态大多为未主动探测。MarChem 已检测到外层 ZIP 漂移，但科学数据/方法成员的行数和关键统计未变 | 上游服务不可用可能无法在离线测试中即时发现 | 后续增加受控在线探针；失败时继续回放最后验证缓存并显示陈旧度 |
| Medium | v2 archive fixture 只证明一个土壤样板 | 当前只有 1 条合成 topsoil observation | 尚未证明水体分相、沉积环境、空间匹配地质和 dataset-scope 方法的全部分支 | 增加 rock/soil/sediment/water 四介质 v2 fixture，覆盖 null、unmapped 和边界情况 |

## 已确认没有发生的问题

- 没有用 736 条 demo 替代全量来源分母；
- 没有从元素、单位、介质或分析方法推断 `sample_type`；
- 没有把 geographic context 自动复制为 `geologic_unit_raw`；
- 没有因新增可选列破坏 V3 输入兼容；
- 不同水体分相、土壤层位和沉积环境已进入默认比较组；比较组从 80 个增至 93 个，工程异常候选从 16 个变为 11 个，这是背景组语义改变后的预期重算，不能解释为自然异常减少；
- 没有降低缓存、来源定位和实体关系的既有校验。

## M2 已完成指标

- 样品类型：736/736；原始类型与映射状态同为 736/736；
- 土壤层位：288/288 土壤记录；
- 沉积环境：256/256 沉积物记录；
- 水体类型和分相：144/144 水体记录；
- 方法 scope：544/544 有方法记录；方法缺失原因：192/192 无方法记录；
- 引用 scope、解析状态、访问状态、科研使用状态和许可 URL：736/736；
- 旧 `geologic_unit`：0/736；地理上下文迁移：192/192；
- 十四个 source demo 可由 `migrate_v4_source_demos.py --check` 逐字节复核。

## M0/M3 已完成指标

- 全量来源：14/14；目标测定 742,060 条；逐来源去重样品 554,429 个；
- 有效坐标样品：549,510；最低可比较测定：105,279；
- 覆盖立方体：5,773 行，每行同时包含 observation、sample、lineage、coordinate、comparable 和 spatial-cell 六类指标；
- 介质测定/独立血缘：rock 65,988/1，soil 93,508/6，sediment 45,390/4，water 537,174/3；
- GEMStat 全量方法完整率：43,285/492,999，即 8.78%，不再用方法完整的 48 条 demo 代表全量；
- GEOROC 全量地质背景：岩性 65,988、年龄 61,418、构造背景 65,988；真正地质单元仍为 0；
- MarChem 外层动态 ZIP 漂移已显式报告；数据表与方法表的版本、字节数、行数和关键统计一致，因此仅标记非科学成员漂移，不静默升级版本。

## 下一步顺序

1. 执行 V4-M4：把 GEMStat 从 As 扩展到 As/Cr/Cu/Hg/Ni/Pb/Zn，并按水体类型、分相和方法重新量化覆盖。
2. 连接 GEOTRACES contributor/method metadata，避免 39,327 条测定全部落入方法未知组。
3. 审计并接入一个独立淡水或海水来源，再进入 M5 的 NGSA、GSJ marine 和独立沉积物来源。
4. 增加四介质 v2 archive fixture、observation-citation 独立关系和完整 draft 2020-12 runtime 校验。
5. 为真正地质单元设计有版本、比例尺、边界距离和不确定度的空间匹配流程。
