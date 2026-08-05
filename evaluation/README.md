# Global Geochemical Atlas Benchmark v5

这是从 `global_geochemical_atlas_benchmark_v4_2_executable.md` 独立派生的评测工作区。原始文件只读，本目录不回写任何既有文件。

## 目标

本评测包用于判断 Global Geochemical Atlas Skill 是否能够在真实沙箱约束下，生成科学可靠、可追溯、可复核的数据库、质量控制结果、置信度说明、地图与异常结论。

“可执行题”必须同时满足：

1. 题目引用的每个输入资产真实存在；
2. 输入资产有固定内容、来源类型和完整性信息；
3. 要求的输出路径和 schema 明确；
4. 客观部分可由代码评分；
5. 开放解释部分有锚定证据的 LLM rubric；
6. 金标准可从固定输入复算；
7. 科学红线能够触发任务封顶或验收失败；
8. 至少通过一次 package validation 和 checker smoke test 后，才可标记为 executable。

## 目录边界

```text
benchmark_rebuild_v5/
├── audit/                         # 对旧版本的只读审计
├── docs/                          # 矩阵、评分、红线、隔离和来源依据
├── release/public/                # 可交付给设计组的公开题 Q01-Q08
├── evaluator_private/shadow/      # 仅评测侧持有 Q09-Q16
├── evaluator_private/final_holdout/ # 功能冻结后才运行 Q17-Q24
├── tools/                         # 通用 checker 与包验证器
└── results/                       # 原始运行和报告模板；不伪造实测结果
```

公开发布时只能导出 `release/public/` 与不泄题的聚合规范。`evaluator_private/` 不得复制到被测 Skill 仓库，也不得在给 D1、D2、D3 的问题反馈中出现输入值、金标准、文件哈希或逐题判分细节。

## 状态标签

- `DESIGNED`：题意、输入和金标准已定义；
- `VALIDATED`：资产和 schema 通过静态检查；
- `SMOKE_PASSED`：金标准被通用 checker 实际评分并达到满分；
- `FROZEN`：题面、输入、金标准、checker 和 rubric 已生成冻结清单；
- `EXECUTED`：已按裸模型/挂载 Skill 协议完成真实运行。

在没有真实模型运行日志前，本包不会把模板或金标准自检写成“盲测原始结果”。

## 运行方式

待任务资产完成后：

```bash
python3 tools/validate_package.py .
python3 tools/grade_task.py <task_dir> <submission_dir> --output <report.json>
```

## 官方评审对齐

本包主要服务于官方 L2 沙箱实战，并提供科学验收证据。官方总评仍应按公开规则执行 L0 合规、L1 静态质量、L2 沙箱实战和 L3 六维加权。本包的领域任务分数不应冒充官方最终总分。
