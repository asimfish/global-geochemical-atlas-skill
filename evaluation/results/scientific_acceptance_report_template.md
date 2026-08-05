# 科学验收报告

## 冻结信息

- Benchmark version:
- Benchmark private manifest SHA-256:
- Skill commit/archive SHA-256:
- Sandbox image:
- Primary model and frozen parameters:
- Supplementary model and frozen parameters:
- Execution window:

## 完整性

- Expected runs:
- Completed runs:
- Timeouts:
- Missing/corrupt artifacts:
- Invalidated task events:

## 聚合结果

| 指标 | 裸模型 | 挂载 Skill | Uplift |
|---|---:|---:|---:|
| Shadow mean | | | |
| Final mean | | | |
| Blind weighted | | | |

## 科学维度

| 维度 | 分数/证据 | 主要失败标签 |
|---|---|---|
| 来源与 provenance | | |
| 单位、元素形态和基准 | | |
| LOD/LOQ 与 QC | | |
| 坐标、空间与地图 | | |
| 置信度 | | |
| 异常与解释边界 | | |

## 红线事件

逐项给出 run_id、task_id、输出路径、触发规则、复核结论和对分数/验收的影响。

## 低置信度与争议项

记录跨运行方差、LLM grader 分歧、资产异常、人工复核证据和最终处置。不得只写“人工判断通过”。

## 验收结论

- [ ] PASS
- [ ] CONDITIONAL PASS
- [ ] FAIL

结论依据：

## 可向设计组反馈的聚合问题

只列 capability、failure tag、频次和严重度；不得泄露 Shadow/Final 的具体样例、输入、gold 或 checker 条件。
