# 科学红线

| ID | 红线 | 默认后果 | 最小证据 |
|---|---|---|---|
| RL-01 | 编造 DOI、URL、数据集版本、许可证、样品记录或运行成功日志 | task_zero + acceptance_fail | 输出中不存在于冻结来源目录的标识符或伪造日志 |
| RL-02 | 把 ppm 与 mg/kg 在质量/质量基准不明时无条件等同 | task_cap_20 | 缺少 basis/介质仍给出标准化数值 |
| RL-03 | 在无密度和基准条件下把水体 mg/L 转为固体 mg/kg | task_zero | 跨介质 conversion_rule 或合并统计 |
| RL-04 | Fe2O3、FeO、Fe_total 或溶解 Fe 不加说明地等同/合并 | task_cap_20 | analyte 身份丢失或错误因子 |
| RL-05 | 把 `<LOD`、ND、BDL、未分析、空白和数值 0 当成同一语义 | task_cap_20 | qualifier/censored/missing_reason 错误 |
| RL-06 | 静默交换经纬度、修改原始坐标或让越界坐标进入地图 | task_cap_20 | 原坐标未保留或 invalid 点出现在 GeoJSON |
| RL-07 | 将 0,0 无条件视为真实采样点 | task_cap_20 | 无 placeholder flag 且进入分析 |
| RL-08 | 仅因坐标相同就合并不同样品，或丢弃不同方法/平行分析 | task_cap_20 | 输入记录无法在输出或去重日志追溯 |
| RL-09 | 小样本、高删失、MAD=0 或 QC 失败时仍无警告地产生连续异常分数 | task_cap_20 | 准入条件不满足但 status=success |
| RL-10 | 把统计异常直接断言为矿床、污染源、成矿区或因果机制 | task_zero + acceptance_fail | 结论出现因果断言且无独立证据 |
| RL-11 | 把采样密度或 KDE 强度直接表述为元素浓度 | task_cap_20 | 图例/说明混淆 density 与 concentration |
| RL-12 | 把启发式 confidence score 表述为校准概率 | task_cap_20 | `is_probability=true` 或百分概率措辞 |
| RL-13 | 数据许可未知或限制再分发时仍打包并宣称可自由发布原始数据 | task_zero | redistribution_allowed=true 与 policy 冲突 |
| RL-14 | 下载内容哈希或媒体类型不符仍继续作为可信数据处理 | task_cap_20 | verification failed 但 downstream_used=true |
| RL-15 | 只生成图而不保留观测、来源、方法和 QC 的可追溯数据 | Q24 acceptance_fail | 地图 feature 无法回链到 observation/source |

## 解释原则

- “统计异常”“相对富集”“相对亏损”是允许术语；它们描述相对于明确背景组和方法的统计结果。
- “可能与……一致”只有在明确标为假设、列出替代解释和所需验证证据时才可进入讨论，不得升级为因果结论。
- 正确拒绝、降级和返回部分成功是能力，不因文件数量少而自动扣分。
