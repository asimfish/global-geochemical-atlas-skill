---
title: "Global Geochemical Atlas Benchmark v6 执行指南"
audience: "首次运行评测的执行人员与独立复核人员"
version: "6.0.0-draft.1"
exports: ["md"]
---

# Global Geochemical Atlas Benchmark v6 执行指南

本指南执行一个原则：E2 出题并收集领域证据，E1 规定怎么交卷、怎么算最终分、怎么返回退出码。

## 0. 五分钟跑通一题 Public

这套 Benchmark 不直接调用模型。执行人员把当前题的题面和输入交给模型或 Agent，模型在独立 submission 根目录的 `artifacts/` 下生成十个固定产物；随后 checker 生成六维评审证据，`finalize_score.py` 才生成 E1 `score.json`。

从仓库根目录开始：

```bash
cd evaluation
python3 tools/validate_package.py . --public-only \
  --report results/validation/package_validation.json

task_dir="release/public/Q01"
run_dir="$(mktemp -d -p /tmp gga-q01.XXXXXX)"
mkdir -p "$run_dir/model_input" "$run_dir/submission/artifacts"
cp "$task_dir/task.md" "$run_dir/model_input/"
cp "$task_dir/task.json" "$run_dir/model_input/"
cp -R "$task_dir/inputs" "$run_dir/model_input/inputs"
```

启动一次全新模型会话，只允许它读取 `model_input/`，只允许写入 `submission/`。不要把整个 `evaluation/` 作为模型工作目录，也不要向模型提供 gold、checker 或 rubric。可使用以下任务说明：

```text
你正在执行一个隔离的文件产物评测任务。

输入目录：<run_dir>/model_input
Submission 根目录：<run_dir>/submission

请阅读 task.md、task.json 和 inputs/，将 task.json.required_outputs
列出的十个 artifacts/ 文件写入 Submission 根目录对应相对路径。
题目专用逻辑证据写入 artifacts/run_manifest.json 的
benchmark_evidence 对象，不要创建额外题目专用物理文件。
不得修改输入、读取其他任务或编造缺失科学证据。
```

模型结束后检查并生成确定性证据报告：

```bash
find "$run_dir/submission/artifacts" -maxdepth 1 -type f -print | sort

python3 tools/grade_task.py \
  "$task_dir" \
  "$run_dir/submission" \
  --output "$run_dir/objective_report.json"

python3 tools/finalize_score.py \
  --objective-report "$run_dir/objective_report.json" \
  --rubric "$task_dir/rubric.json" \
  --run-id demo-q01-s0-r1 \
  --candidate-status success \
  --output "$run_dir/score.json"
```

`objective_report.json` 的点数只是 checker 证据覆盖量，不是独立总分。最终只认符合 `contracts/benchmark-score.schema.json` 的六维 `score.json`；没有 LLM 或静态证据的维度保持 `not_scored`，整体为 `partial`。Public 用于接口开发诊断，不能证明隐藏题泛化或正式 uplift。

## 1. 当前能力边界

本包提供：

- Public Q01–Q08，以及对外部 Shadow/Final 根目录的校验；
- E1 十产物交卷模板和题目逻辑证据容器；
- 确定性 evidence checker；
- 把 checker、LLM 和静态评审证据合成为 E1 `score.json` 的工具；
- B0/S0 三次配对运行的完整性检查与描述性汇总；
- Public 白名单导出和隐藏集隔离检查。

本包不绑定具体模型平台。模型调用、容器调度和 LLM grader 调用仍由赛事 runner 完成；gold smoke test 不能冒充真实模型成绩。

## 2. 冻结契约

正式 campaign 开始前固定：

1. `VERSION` 与 `contracts/benchmark-execution-contract.json`；
2. E1 contract SHA-256；
3. Benchmark public/private manifest；
4. Skill commit 或归档 SHA-256；
5. 模型、全部参数、system prompt、工具权限和 seed；
6. 沙箱镜像、网络策略、CPU/内存/磁盘和超时；
7. LLM grader 模型、prompt、rubric 和解析规则；
8. B0/S0 的唯一区别只能是是否只读挂载冻结 Skill。

任一项变化都创建新 campaign，不能混入原 uplift。

## 3. 验证题库和隔离

从 `evaluation/` 执行：

```bash
python3 tools/validate_package.py . --public-only \
  --report results/validation/package_validation.json

python3 tools/validate_package.py . \
  --private-root /secure/e2-private-root

# 仅对已泄漏旧 Final 做结构回归；此命令永远不形成正式证据：
python3 tools/validate_package.py . \
  --private-root /secure/e2-legacy-private-root \
  --allow-legacy-regression

python3 tools/verify_isolation.py \
  --evaluation-root . \
  --private-root /secure/e2-private-root \
  --e1-workspace ..
```

预期版本为 `6.0.0-draft.1`，Public 8 题。正式 private root 必须是新 Final、通过 E2 签名冻结且 `formal_private_eligible=true`；旧 24 题包即使 gold smoke 全过，也只能作为 regression，不能进入正式 cohort。

Public 包只能白名单导出：

```bash
python3 tools/export_public_package.py . /tmp/gga-public
```

## 4. 给候选程序的文件

每次运行创建全新沙箱，只提供当前题的题面、安全任务元数据和 `inputs/`。隐藏题的 gold、checker、rubric、其他题目、历史会话和运行缓存均不可见。

每次运行也创建全新的 submission 根目录。候选程序只向其中的 `artifacts/` 写 E1 十个固定文件：

```text
observations.csv
geochemical.sqlite
sources.jsonl
qc_report.json
anomaly_results.csv
anomalies.geojson
h3_cells.csv
map.png
map.html
run_manifest.json
```

旧版题目专用输出必须写入 `run_manifest.json.benchmark_evidence`。不允许用额外物理文件恢复旧接口。

## 5. 执行 B0/S0

每题运行六次：`B0` 三次、`S0` 三次。同一 repeat 的模型、参数、输入、seed、沙箱和资源限制完全一致，并记录相同的 `pair_fingerprint`。

- B0：候选不能通过 prompt、搜索路径、缓存、环境变量或工作区文件读取 Skill；
- S0：只增加冻结 Skill 的只读挂载，并记录实际加载证据；
- 每次捕获开始/结束时间、E1 状态和退出码、stdout/stderr、产物哈希及 runner 元数据；
- 不把 grader 报告写进 submission，以免混入候选产物。

候选退出码必须使用 E1：`0` 成功，`2` 部分成功，`10–30` 为输入/科学/写出失败，`70–76` 为 runner、资源、环境、产物、scorer 和取消类错误。原始子进程码写入 `cause_exit_code`，不能覆盖 E1 码。特别注意：grader 自身异常是 `75`，不是 `2`。

## 6. 确定性证据判分

Public 正向 smoke：

```bash
python3 tools/grade_task.py \
  release/public/Q01 \
  release/public/Q01/gold \
  --output /tmp/q01-objective.json
```

隐藏题示例：

```bash
python3 tools/grade_task.py \
  /secure/e2-private-root/shadow/Q09 \
  /runs/campaign-001/S0/Q09/repeat-1/submission \
  --output /runs/campaign-001/S0/Q09/repeat-1/objective_report.json
```

报告中的 `evidence_points_awarded` 只表示冻结 checker 的证据覆盖量。它不在 0–100 总分中单独占一块，也不能与 LLM 点数直接相加。

## 7. LLM 与静态评审证据

LLM grader 按 `docs/llm_grader_protocol.md` 输出 `criteria[]`。每项必须包含冻结的 `id`、`dimension_id`、`score`、`max`、具体证据位置和理由。

静态评审使用同样的 `criteria[]` 形状，主要补充平台复用、创新生态和开源潜力等仓库级证据。每条证据都必须能回链到冻结文件；无证据的维度保留 `not_scored`。

## 8. 生成 E1 score.json

```bash
python3 tools/finalize_score.py \
  --objective-report /runs/.../objective_report.json \
  --rubric /secure/e2-private-root/shadow/Q09/rubric.json \
  --run-id campaign-001-q09-s0-r1 \
  --candidate-status success \
  --llm-report /runs/.../llm_grader_report.json \
  --static-review /runs/.../static_review.json \
  --output /runs/.../score.json
```

输出必须符合 `contracts/benchmark-score.schema.json`，包含 E1 固定 contract hash、六个 dimension、固定权重和加权 `total_score`。

- 六维证据齐全：`score_status=complete`；
- 有维度缺证据：`score_status=partial`，不凭空补分；
- 候选失败或硬门禁失败：`score_status=ineligible`、`total_score=null`；
- `task_cap_20` 只封顶科学可信性维度；`task_zero` 和 `acceptance_fail` 触发硬门禁。

## 9. 记录与汇总

每行原始记录使用 `results/raw_runs_template.jsonl` 的结构，内嵌完整 E1 `score`。完成一组 campaign 后：

```bash
python3 tools/aggregate_runs.py results/raw/campaign-001/runs.jsonl \
  --csv-output results/raw/campaign-001/summary.csv \
  --json-output results/raw/campaign-001/summary.json
```

聚合器拒绝缺少 B0/S0 × 三次、配对指纹不一致、退出码/状态冲突、E1 contract hash 漂移或六维权重漂移的数据。它按题报告两侧 E1 总分中位数、极差、MAD 与 uplift，并按 split 给描述性汇总；不能代替人工红线复核和赛事最终决策。

## 10. 交付前检查

- submission 只有 E1 十个物理产物；
- 题目逻辑结果位于 `run_manifest.json.benchmark_evidence`；
- 每个 `score.json` 通过 E1 schema；
- 每题恰有 B0/S0 各三次，同 repeat 的 `pair_fingerprint` 相同；
- 退出码和状态符合 E1，`2` 没被当成 grader 错误；
- Public 导出由白名单生成；
- Shadow/Final 位于工作区外，私有目录权限合格；
- 当前历史已暴露的旧 Final 只标记为回归，不宣称严格盲测；
- 报告同时保留绝对分、uplift、不确定性、红线和原始证据。
