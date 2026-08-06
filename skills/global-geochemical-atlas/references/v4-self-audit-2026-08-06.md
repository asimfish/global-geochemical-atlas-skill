# V4 阶段自查（2026-08-06）

审计时间：2026-08-06 18:55（Asia/Shanghai）

审计口径：按预期粒度分别检查归档实体、交换记录、来源 demo、全量候选审计、标准输出和查询索引。演示样板不作为全量来源分母。

## 结论

V4-M1 的基础链路已经可用：sample/method/geology/citation scope 能从 v2 归档进入交换 CSV、标准化数据库、SQLite 查询、GeoJSON 和地图；旧 V3 输入仍可读取。M0 只完成了“全量证据与 demo 强制分口径”的审计框架，尚未完成十四来源统一逐字段全量统计。M2 的十四来源回填尚未开始，因此不能宣称生产数据已经具备 V4 字段完整性。

验证结果：

- `component_test.py`：178/178 PASS；
- `self_test.py`：22/22 PASS；
- v2 归档关系校验：PASS；
- v1/v2 SQLite 构建与查询：PASS；
- 完整率结果可重建：PASS。

## 数据质量发现

| 严重度 | 发现 | 证据 | 下游风险 | 处理建议 |
|---|---|---|---|---|
| High | 十四来源尚未回填 V4 样品语义 | 联合输出 `sample_type_raw/sample_type/sample_type_mapping_status` 均为 0/736；层位、沉积环境、水体类型和分相也均为 0/736 | 地图虽然已有筛选器，但生产样板无法按样品类型筛选；不同样品类型仍可能被错误解释为同类 | 按来源证据回填 M2，先 FOREGS、GEMStat、GEOTRACES、USGS、AfSIS，再处理其余来源 |
| High | 全量逐字段完整率尚不可统一比较 | 14 个来源中 12 个有候选全量审计，GEOROC/USGS 缺失；14/14 均未生成统一 V4 字段 numerator/denominator | 无法用一致口径回答全量坐标、方法、样品类型、地质和引用覆盖率 | 在 verified full cache 上运行 adapter profile，输出非空、有效、显式缺失原因三个计数 |
| High | 旧地质字段仍存在语义混用 | 旧 `geologic_unit` 非空 192/736，分别来自 GEOROC location、GEOTRACES cruise track、GSJ map sheet、PANGAEA area；新 `geologic_unit_raw/matched_geologic_unit` 均为 0/736。V4 默认异常分组已不再使用旧字段 | 兼容输出中的旧字段仍可能被外部使用者误读；当前也无法按真正地质单元分析 | M2 将地区、航线、图幅移入 geographic context；只把来源明确地质值写入 `geologic_unit_raw` |
| High | 生产方法没有 scope | `analytical_method` 非空 544/736，但 `method_scope` 为 0/736 | 数据集级或批次级方法可能被误当成逐记录方法，错误判断可比性 | 为每个 adapter 指定 observation/sample/batch/file/dataset/publication，并保留 assignment basis |
| Medium | 引用和使用条件 scope 尚未进入生产记录 | `citation_scope` 与 `research_use_status` 均为 0/736 | 有 DOI/许可不等于测定级引用或单独核实的科研使用条件 | 从现有 evidence JSON 和 registry 回填；数据集 DOI、方法论文、逐记录引用分开 |
| Medium | JSON Schema 文件没有被完整运行时执行 | 当前 validator 检查实体版本、关系、缺失原因和关键 v2 语义，但未执行 draft 2020-12 的所有关键字 | 将来新增字段时可能通过手写校验但违反 schema 的 enum/type/additionalProperties | 增加固定依赖或标准库兼容的 schema 校验步骤，并加入非法类型/多余字段测试 |
| Medium | 自动采集健康仍是静态声明 | profile 中 online fetch、schema drift、row-count drift 均为 `not_measured` | 上游变更可能只在下一次人工运行时发现 | 保存最近成功 fetch/parse、header fingerprint、row count，并在缓存重放时比较漂移 |
| Medium | v2 archive fixture 只证明一个土壤样板 | 当前只有 1 条合成 topsoil observation | 尚未证明水体分相、沉积环境、空间匹配地质和 dataset-scope 方法的全部分支 | 增加 rock/soil/sediment/water 四介质 v2 fixture，覆盖 null、unmapped 和边界情况 |

## 已确认没有发生的问题

- 没有用 736 条 demo 替代全量来源分母；
- 没有从元素、单位、介质或分析方法推断 `sample_type`；
- 没有把 geographic context 自动复制为 `geologic_unit_raw`；
- 没有因新增可选列破坏 V3 输入兼容；
- 736 条观测和 16 个工程异常候选未变；默认比较组从 89 个降为 80 个，这是停止使用混杂旧 `geologic_unit` 后的预期语义修正；
- 没有降低缓存、来源定位和实体关系的既有校验。

## 下一步顺序

1. 执行 V4-M2：给十四来源回填样品类型、方法 scope、引用 scope 和显式缺失原因，同时清理 192 条旧地质语义。
2. 完成 V4-M0 的全量层：补 GEOROC/USGS 全量审计，并让 14 个 adapter 对 verified cache 输出统一逐字段统计。
3. 增加四介质 v2 fixture 与真正的 JSON Schema 执行校验。
4. 增加 adapter fetch/parse/schema/row-count 漂移健康记录。
5. 在字段债务开始收敛后，按 V4 水体与沉积物优先级继续接 GEMStat 多元素、GEOTRACES 方法、NGSA 和 GSJ marine。
