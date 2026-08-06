# V4 阶段自查（2026-08-06）

审计时间：2026-08-06 21:25（Asia/Shanghai）

审计口径：按预期粒度分别检查归档实体、交换记录、来源 demo、全量候选审计、标准输出和查询索引。演示样板不作为全量来源分母。

## 结论

V4-M2 的十四来源演示回填已经完成，并已接入正式生成器。736/736 条记录都有来源原始样品类型、规范类型和映射依据；水体、沉积物和土壤层位字段按介质填充；544 条已有方法记录全部带 scope，另外 192 条明确写出方法缺失原因；引用 scope、访问状态、科研使用状态和许可定位均已进入交换层。旧 `geologic_unit` 已清零，原来的地区、航线、图幅和项目范围改存地理上下文。

这证明当前十四来源的工程样板已具备 V4 语义，不代表十四个全量来源已经完成统一逐字段统计。M0 全量 profile 和真正的地质背景仍是主要缺口。

验证结果：

- `component_test.py`：184/184 PASS；
- `self_test.py`：22/22 PASS；
- v2 归档关系校验：PASS；
- v1/v2 SQLite 构建与查询：PASS；
- 完整率结果可重建：PASS。

## 数据质量发现

| 严重度 | 发现 | 证据 | 下游风险 | 处理建议 |
|---|---|---|---|---|
| High | 全量逐字段完整率尚不可统一比较 | 14 个来源中 12 个有候选全量审计，GEOROC/USGS 缺失；14/14 均未生成统一 V4 字段 numerator/denominator | 无法用一致口径回答全量坐标、方法、样品类型、地质和引用覆盖率 | 在 verified full cache 上运行 adapter profile，输出非空、有效、显式缺失原因三个计数 |
| High | 当前没有可用的真正地质单元 | `geologic_unit_raw` 与 `matched_geologic_unit` 都是 0/736；原 192 条混杂值已移入 `geographic_context_raw/map_sheet/cruise_track/survey_area` | 不能按地质单元生成可靠统计或地图 | 从来源显式岩性/构造字段回填，或引入带版本、比例尺与边界不确定度的地质图空间匹配 |
| High | 四个来源仍缺方法 | GEOROC、GEOTRACES、GSJ、USGS 共 192 条没有 `analytical_method/method_scope`，但全部带 `method_missing_reason` | 这些记录只能在“方法未知”组使用，不能和已知方法数据直接比较 | 优先连接 GEOTRACES contributor metadata、USGS/GSJ 方法文档和 GEOROC 原始论文方法 |
| Medium | 引用尚未成为独立关系表 | GEOROC 的一对多 citation ID 和文本已作为 JSON 列表进入交换 CSV，evidence JSON 也完整保留；但 SQLite 仍主要依赖 method-publication 关系 | 按文献反查全部测定或区分 dataset/method/observation citation 的查询仍不够直接 | 在归档层增加 observation-citation 关系表，CSV 继续作为查询摘要而非唯一证据载体 |
| Medium | JSON Schema 文件没有被完整运行时执行 | 当前 validator 检查实体版本、关系、缺失原因和关键 v2 语义，但未执行 draft 2020-12 的所有关键字 | 将来新增字段时可能通过手写校验但违反 schema 的 enum/type/additionalProperties | 增加固定依赖或标准库兼容的 schema 校验步骤，并加入非法类型/多余字段测试 |
| Medium | 自动采集健康仍是静态声明 | profile 中 online fetch、schema drift、row-count drift 均为 `not_measured` | 上游变更可能只在下一次人工运行时发现 | 保存最近成功 fetch/parse、header fingerprint、row count，并在缓存重放时比较漂移 |
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

## 下一步顺序

1. 完成 V4-M0 的全量层：补 GEOROC/USGS 全量审计，并让 14 个 adapter 对 verified cache 输出统一逐字段统计。
2. 进入 V4-M3：构建 observation/sample/lineage/coordinate/comparable/spatial-cell 覆盖立方体。
3. 补四个缺方法来源，优先 GEOTRACES contributor metadata。
4. 增加四介质 v2 fixture、真正的 JSON Schema 执行校验和 adapter 漂移健康记录。
5. 按 V4 水体与沉积物优先级继续接 GEMStat 多元素、NGSA 和 GSJ marine。
