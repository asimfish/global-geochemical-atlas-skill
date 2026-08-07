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

## 统一 Docker runner

`docker/campaign.py` 将当前 E2 题库接入比赛式执行环境：OpenCode 固定版本、2 CPU、4 GB、无 GPU、900 秒、受控网络、B0/S0 只差一个只读 Skill 挂载。主模型默认每题每条件三次，可选补充模型每题每条件一次；输出直接兼容现有 `grade_task.py`、`finalize_score.py` 和 `aggregate_runs.py`。

```bash
python3 evaluation/docker/campaign.py build-image \
  --image global-geochemical-eval:local
python3 evaluation/docker/campaign.py run \
  --image global-geochemical-eval:local \
  --agent mock --network offline \
  --tasks Q01 --conditions B0,S0 --repeats 3 \
  --output-dir /tmp/gga-docker-smoke
```

mock 只验证运行器，不是模型成绩。正式 OpenCode 命令、网关密钥规则和证据目录见 [`docs/docker_usage.md`](docs/docker_usage.md)。
赛事 Anthropic-compatible Qwen 地址使用 `--provider-profile qwen-anthropic`；
该 profile 固定 `temperature=0.6` 和 `thinking=disabled`，不会自动切换备用模型。
如果目标是让用户只开两个空目录并分别测试纯 Qwen 与 Qwen + Skill，请从 [`evaluation_lyf/agent_uplift/`](../evaluation_lyf/agent_uplift/DOCKER_UPLIFT.md) 选择主机版或 Docker 版的一对固定 Prompt；该公开 uplift case 与 Q01–Q24 的 campaign 分开计分，Docker profile 复用这里的执行环境。

Q01–Q24 也提供显式的[手工 B0 无 Skill Prompt](prompts/QWEN_B0_NO_SKILL_PROMPT.md)和[手工 S0 有 Skill Prompt](prompts/QWEN_S0_WITH_SKILL_PROMPT.md)。它们用于人工观察两个条件；正式可比较成绩仍以 Docker runner 的同题面、同资源、只改变 Skill 挂载为准。

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

## 保持待答题目录为空

从 `evaluation/` 目录先预览，再执行清理：

```bash
python3 tools/reset_ai_submissions.py --dry-run
python3 tools/reset_ai_submissions.py
```

仓库中的 `ai_visible_public/submissions/Q01` 至 `Q24` 默认只保留空的 `.gitkeep`。脚本用于清理本地上一次运行结果；题面、输入和评分材料不会被修改。历史运行必须归档到 `results/runs/`，不得留在候选可见目录。`export_ai_bundle.py --validate-only` 默认会拒绝历史答案；只有明确检查一次已经结束的运行时才传入 `--allow-submissions`。

## 被测 Codex 快速入口

Q01–Q24 的唯一答题工作目录和可直接复制的提示词见 [`ai_visible_public/README.md`](ai_visible_public/README.md)。不要把整个 `evaluation/` 作为答题 AI 工作目录。
