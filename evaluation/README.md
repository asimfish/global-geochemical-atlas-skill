# Global Geochemical Atlas Benchmark v6（E1 对齐版）

本目录是 E2 领域 Benchmark。E2 负责提供地球化学任务、确定性检查和评审证据；交卷格式、最终六维评分和退出码全部以 E1 为准，不再另建一套规则。

这是团队开发期评测资产，不是主办方官方题库或官方 gold，也不是参赛 Skill 的运行依赖。最终 Skill 提交包只包含 `skills/global-geochemical-atlas/` 及必要仓库文件；本目录需单独管理和运行。

## 一句话理解

- 参赛程序只交 E1 规定的 `artifacts/` 下十个文件；
- Q01–Q24 原有的题目专用结果写入 `artifacts/run_manifest.json.benchmark_evidence`，不再新增交卷文件；
- checker 和 LLM 只产出归属于 E1 六维的证据，最终由 `finalize_score.py` 生成 E1 `score.json`；
- 裸模型和挂载 Skill 分别记作 `B0`、`S0`，每题各跑三次；
- Public 留在本仓库；Shadow/Final 位于工作区外的受控私有根目录。

冻结接口见 [`contracts/benchmark-execution-contract.json`](contracts/benchmark-execution-contract.json)，人类可读说明见 [`docs/execution-contract-guide.md`](docs/execution-contract-guide.md)。Docker 环境的连接、构建、测试和当前验收边界见 [`docs/docker_usage.md`](docs/docker_usage.md)。

## E1 交卷文件

每次运行的 submission 根目录必须且只能声明以下物理产物：

```text
artifacts/observations.csv
artifacts/geochemical.sqlite
artifacts/sources.jsonl
artifacts/qc_report.json
artifacts/anomaly_results.csv
artifacts/anomalies.geojson
artifacts/h3_cells.csv
artifacts/map.png
artifacts/map.html
artifacts/run_manifest.json
```

题目专用逻辑证据放在最后一个文件的 `benchmark_evidence` 字段中。

## 目录边界

```text
evaluation/
├── ai_visible_public/            # 被测 AI 的 Public 题面、输入和 submissions
├── contracts/                    # E1 对齐契约、E1 score schema、gold 模板
├── docs/                         # 评分、接口和隔离规则
├── model_tests/qwen3_8_max/      # Qwen3.8-Max API 检查与隔离运行器
├── release/public/Q01-Q08/       # 可公开开发题
├── tools/                        # 校验、证据判分、最终计分、汇总和导出工具
└── results/                      # 运行记录与报告模板，不包含伪造实测结果
```

Shadow/Final 不在本目录。正式执行时通过 `--private-root` 指向工作区外的私有根目录；当前从公开 Git 历史迁出的旧 Final 只能用于回归，不能恢复成严格 holdout。

## 最小验证流程

从 `evaluation/` 目录执行：

```bash
python3 tools/validate_package.py . --public-only
python3 tools/validate_package.py . --private-root /secure/e2-private-root
# 旧 Final 只允许显式做结构回归，且报告 formal_private_eligible=false：
python3 tools/validate_package.py . \
  --private-root /secure/e2-legacy-private-root \
  --allow-legacy-regression
python3 tools/verify_isolation.py \
  --evaluation-root . \
  --private-root /secure/e2-private-root \
  --e1-workspace ..
python3 tools/grade_task.py release/public/Q01 release/public/Q01/gold \
  --output /tmp/q01-objective.json
python3 tools/finalize_score.py \
  --objective-report /tmp/q01-objective.json \
  --rubric release/public/Q01/rubric.json \
  --run-id demo-q01-s0-r1 \
  --candidate-status success \
  --output /tmp/q01-score.json
```

`grade_task.py` 的点数只是证据覆盖量，不是独立总分。只有符合 E1 schema 的六维 `score.json` 才是单次运行分数。完整执行步骤见 [`RUNBOOK.md`](RUNBOOK.md)。

使用 Qwen3.8-Max 执行 Public B0/S0 的准备、API 和命令示例见 [`model_tests/qwen3_8_max/README.md`](model_tests/qwen3_8_max/README.md)。

## 被测 Codex 快速入口

工作目录和可直接复制的提示词见 [`ai_visible_public/README.md`](ai_visible_public/README.md)。
