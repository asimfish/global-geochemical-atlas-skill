# Global Geochemical Atlas Benchmark v6（E1 对齐版）

给答题 AI 和评分 AI 的 Prompt 入口统一见 [`AI_PROMPTS.md`](AI_PROMPTS.md)。

本目录是 E2 领域 Benchmark。E2 负责提供地球化学任务、确定性检查和评审证据；交卷格式、最终六维评分和退出码全部以 E1 为准，不再另建一套规则。

## 一句话理解

- 参赛程序只交 E1 规定的 `artifacts/` 下十个文件；
- Q01–Q24 原有的题目专用结果写入 `artifacts/run_manifest.json.benchmark_evidence`，不再新增交卷文件；
- checker 和 LLM 只产出归属于 E1 六维的证据，最终由 `finalize_score.py` 生成 E1 `score.json`；
- 裸模型和挂载 Skill 分别记作 `B0`、`S0`，每题各跑三次；
- Q01–Q24 的评分源全部随本仓库维护；答题 AI 只能看到 `ai_visible_public/` 中的白名单投影。

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
├── AI_PROMPTS.md                 # 做题 AI 与评分 AI 的统一入口
├── ai_visible_public/            # 被测 AI 唯一可见的 Q01-Q24 题面、输入和 submissions
├── contracts/                    # E1 对齐契约、E1 score schema、gold 模板
├── docs/                         # 评分、接口和隔离规则
├── evaluator_private/            # Q09-Q24 完整评分源；严禁挂载给答题 AI
├── prompts/                      # 做题 AI prompt 的维护源
├── release/public/Q01-Q08/       # 可公开开发题
├── tools/                        # 校验、证据判分、最终计分、汇总和导出工具
└── results/                      # 运行记录与报告模板，不包含伪造实测结果
```

`evaluator_private/` 中的 `shadow` 和 `final_holdout` 是历史分组标签。Q09–Q24 的候选可见题面已经有意导出到 `ai_visible_public/`，因此不属于隐藏题；其中旧 Final Q17–Q24 只能用于回归，不能恢复成严格 holdout。正式盲测题必须另行生成并私下冻结，不能放入本 repo 或当前答题 bundle。

## 最小验证流程

从 `evaluation/` 目录执行：

```bash
# 推荐：按公开评审资源规格在 Docker 中运行 Public Q01-Q08
bash tools/run_docker_validation.sh

# 宿主机验证完整版本化评测包和 AI 可见投影
python3 tools/validate_package.py . \
  --report results/validation/package_validation.json
python3 tools/export_ai_bundle.py --validate-only ai_visible_public
python3 tools/verify_isolation.py --evaluation-root .
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

Docker runner 固定使用 2 CPU、4 GiB、无 GPU、最长 12 小时（43200 秒）、无网络和只读根文件系统，并生成容器 inspect、运行日志、验证报告和 `SHA256SUMS`。详细说明见 [`docs/docker_usage.md`](docs/docker_usage.md)。

赛事 Gateway、Qwen Anthropic Base URL、OpenCode 首选/备用模型和白名单代理的独立 Docker smoke 见 [`model_gateway/README.md`](model_gateway/README.md)。它不会放宽上述 Public 校验的 `--network none` 合同。

## 重新答题前清空结果

从 `evaluation/` 目录先预览，再执行清理：

```bash
python3 tools/reset_ai_submissions.py --dry-run
python3 tools/reset_ai_submissions.py
```

脚本只清理 `ai_visible_public/submissions/Q01` 至 `Q24` 中的答题结果，并确保每题最终只保留空的 `.gitkeep`；题面、输入和评分材料不会被修改。

## 被测 Codex 快速入口

Q01–Q24 的唯一答题工作目录和可直接复制的提示词见 [`ai_visible_public/README.md`](ai_visible_public/README.md)。不要把整个 `evaluation/` 作为答题 AI 工作目录。
