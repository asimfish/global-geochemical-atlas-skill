---
title: "Global Geochemical Atlas Benchmark v5 测试执行指南"
audience: "首次运行评测的执行人员"
version: "5.0.0-draft.1"
exports: ["md"]
---

# Global Geochemical Atlas Benchmark v5 测试执行指南

## 先看这里：这个 benchmark 到底怎么用

这套 benchmark **不会自己调用模型**。它做两件事：

1. 给模型一份题目和固定输入，要求模型把结果写成指定文件；
2. 模型完成后，用本仓库的 checker 和 rubric 给这些文件判分。

因此，一次评测永远分成两个动作：

| 动作 | 谁执行 | 输入 | 输出 |
|---|---|---|---|
| 做题 | 被测模型或 Agent | `task.md`、安全的 `task.json`、`inputs/` | `submission/` 中的要求文件 |
| 判分 | 评测人员 | 题目目录和模型的 `submission/` | 客观分、LLM 分、红线和验收结论 |

最重要的一点是：**模型不是在聊天窗口里回答一道问答题，而是读取文件并把结果文件写入 `submission/`。** `task.json.required_outputs` 是必须生成的文件清单，评分只读取这些实际文件。

如果你第一次接触本项目，先按下面的 Public Q01 示例走一遍。Public 用来学习接口，不计入正式盲测。能完成这个示例以后，再阅读后面的 Shadow、Final、bare/skill 和科学验收规则。

### 五分钟跑通一题 Public

以下命令都从仓库根目录开始：

```bash
cd evaluation
python3 tools/validate_package.py . \
  --report results/validation/package_validation.json
```

看到 `status: PASS`，表示题库和 checker 自身完整；这还不是模型得分。

选择 Q01，并为这一次模型运行创建独立目录：

```bash
task_dir="release/public/Q01"
run_dir="$(mktemp -d -p /tmp gga-q01.XXXXXX)"

mkdir "$run_dir/model_input"
mkdir "$run_dir/submission"
cp "$task_dir/task.md" "$run_dir/model_input/"
cp "$task_dir/task.json" "$run_dir/model_input/"
cp -R "$task_dir/inputs" "$run_dir/model_input/inputs"
```

现在有两个目录：

```text
<run_dir>/
├── model_input/       # 只读地提供给模型
│   ├── task.md
│   ├── task.json
│   └── inputs/
└── submission/        # 初始为空，只允许模型向这里写结果
```

接下来，用你的模型平台、Agent CLI 或 API 启动一次**全新会话**。本仓库尚未绑定某个模型平台，所以这里没有通用的 `run_model.py` 命令。无论使用什么平台，都要做到：模型只能读取 `model_input/`，只能把结果写入 `submission/`，不能把整个 `evaluation/` 作为模型工作目录。

如果所用模型只能返回聊天文本、不能直接写文件，外部适配器必须把模型返回的每个要求产物保存到 `submission/`。不要把整段聊天记录直接当作 submission。

把下面这段任务说明交给模型，并将其中两个路径替换为刚创建的真实路径：

```text
你正在执行一个隔离的文件产物评测任务。

输入目录：<run_dir>/model_input
输出目录：<run_dir>/submission

请执行以下步骤：
1. 阅读输入目录中的 task.md 和 task.json。
2. 只使用输入目录中的 inputs/ 以及本次明确允许的工具或 Skill。
3. 查看 task.json.required_outputs，并把其中列出的每个文件直接写入输出目录。
4. 不要只在聊天中描述答案；最终评分只读取输出目录中的文件。
5. 不要修改输入，不要读取其他任务、gold、checker、rubric 或以前的运行结果。
6. 如果输入损坏、证据不足或科学条件不满足，按题面输出明确的拒绝或部分成功结果，不得编造数据。
7. 完成后列出已经生成的文件。
```

模型运行结束后，先检查它是否真的生成了文件：

```bash
find "$run_dir/submission" -maxdepth 1 -type f -print
python3 -m json.tool "$task_dir/task.json"
```

然后对这次 submission 做 0–80 分客观判分：

```bash
python3 tools/grade_task.py \
  "$task_dir" \
  "$run_dir/submission" \
  --output "$run_dir/objective_report.json"
```

查看结果：

```bash
python3 -m json.tool "$run_dir/objective_report.json"
```

报告中最先看三个字段：

- `objective_score`：模型本题的客观得分，范围 0–80；
- `checks`：每个检查项是否通过，以及对应证据；
- `redline_events`：是否触发科学红线。

Public 调试时，可以对照该题的 `gold/` 和 `checker/` 找接口问题。正式 Shadow/Final 时，被测模型和设计组不能看到这些内容。

### 跑通 Public 后，正式评测还要做什么

正式结果不是只运行一次 Q01，而是完成下面这条链路：

```text
冻结 benchmark、模型、Skill 和沙箱
        ↓
对每道 Shadow/Final 分别运行 bare 和 skill
        ↓
每次运行保存独立 submission、stdout 和 stderr
        ↓
grade_task.py 给出 0–80 分客观结果
        ↓
独立 LLM grader 按 rubric 给出 0–20 分
        ↓
落实红线封顶或验收失败
        ↓
重复运行并汇总 bare、skill 和 uplift
        ↓
出具科学验收报告
```

第一次使用时可以按需求跳转：

- 只想跑一个 Public 示例：读到这里即可开始；
- 要接入自己的模型平台：继续读“第七步：执行 bare 与 skill 条件”；
- 已经有 submission，只想判分：直接读“第四步：客观判分”；
- 要做正式盲测：从“隔离规则”开始完整阅读后文；
- 要出最终报告：重点读“运行完整性检查”“汇总分数与 uplift”和“科学验收”。

### 当前缺少什么

本仓库已经提供题目、输入输出契约、客观 checker、LLM rubric、聚合脚本和报告模板，但还缺少绑定具体模型平台的通用 runner。因此：

- “如何把题交给模型”已经规定清楚；
- “调用哪个模型 API/CLI”需要赛事平台提供适配器；
- `grade_task.py` 只能给已经生成好的 submission 判分，不能代替模型运行；
- 在 runner、LLM grader 调用器和最终红线计分器补齐前，完整流程仍是半自动的。

下面是正式评测的详细操作规程。首次跑 Public 时不需要一次性读完。

## 详细规程

本文面向独立评测人员，说明如何用本评测包组织一次可复核的 Global Geochemical Atlas Skill 测试。它覆盖题库自检、单题执行、客观判分、LLM rubric、重复运行、结果汇总、科学红线和验收报告。

## 0. 先明确当前自动化边界

本仓库当前提供：

- 24 道带固定输入、required outputs、金标准、客观 checker 和 LLM rubric 的任务；
- `validate_package.py`：检查评测包结构，并用每题 gold 对 checker 做 smoke test；
- `grade_task.py`：对一个已经生成好的 submission 做 0–80 分客观判分并报告红线；
- `aggregate_runs.py`：对已经完成的 bare/skill 原始运行记录计算中位数、极差、MAD 和 uplift；
- 冻结清单、原始结果、汇总和科学验收报告模板。

本仓库当前不提供：

- 调用具体模型或 Agent 的通用 runner；
- 自动切换裸模型与挂载 Skill 的执行器；
- 自动调用 LLM grader、校验其 JSON 或处理双评争议的程序；
- 对运行次数、模型参数、沙箱、产物和日志进行完整性验收的结果验证器；
- 自动落实所有红线后果并生成最终 PASS/FAIL 的总控程序。

因此，当前流程是“外部 runner 执行 + 本包客观阅卷 + 受控 LLM/人工复核 + 本包聚合”。不要把 gold smoke test 称为真实模型成绩，也不要把 `aggregate_runs.py` 的输出未经复核直接称为正式验收结论。

## 1. 角色、对象和术语

- **task directory**：一道题的目录，例如 `release/public/Q01`。
- **submission directory**：一次模型运行生成的独立输出目录，只放该次运行的要求产物。
- **bare**：不挂载、不引用、也不能读取被测 Skill 的对照条件。
- **skill**：使用完全相同模型、参数、题面、输入和沙箱，但挂载冻结后的被测 Skill。
- **objective report**：`grade_task.py` 生成的 0–80 分机器判分报告。
- **LLM grader report**：独立 grader 按 `rubric.json` 生成的 0–20 分报告。
- **raw run record**：一次运行的模型、参数、时间、日志、产物、分数和红线索引。
- **campaign**：同一冻结 benchmark、Skill、模型和沙箱下的一组可比较运行。

一个可计入正式统计的 run 必须能够从 `run_id` 回链到题面版本、输入、模型参数、Skill 版本、沙箱、stdout/stderr、submission、两个 grader 原始结果和红线证据。

## 2. 隔离规则

### 2.1 给被测模型的内容

每道隐藏题只向被测模型提供：

- `task.md`；
- `task.json` 中不泄露答案的任务元数据；
- 该题 `inputs/`；
- 一个空的、独立的 submission directory。

不得向被测模型提供：

- `gold/`；
- `checker/`；
- 隐藏题的 `rubric.json`；
- 其他题目的输入或运行产物；
- 上一次运行的对话、缓存、工作目录或日志；
- 任何能从文件名、路径、环境变量或 Git 历史中读取的隐藏答案。

Public Q01–Q08 可把 gold 和 checker 提供给开发者作接口自测，但 Public 分数不计入正式盲测主分。

### 2.2 Shadow 与 Final

- Shadow Q09–Q16 可在功能冻结前运行，用于发现聚合失败模式。
- Final Q17–Q24 只能在 Skill、模型参数、默认配置和沙箱冻结后运行。
- 如果 D1、D2、D3 或被测 Agent 已能读取当前 Final 的题面、输入、gold 或 checker，这组 Final 不再是严格 holdout；正式比赛应轮换为一组新的、存放在评测负责人独占位置的 Final。
- 向设计组只反馈 capability、failure tag、频次、严重度和聚合分，不反馈隐藏输入值、样品 ID、答案、阈值组合或逐题 checker 日志。

## 3. 运行前冻结信息

正式 campaign 开始前记录：

1. benchmark 版本和冻结清单 SHA-256；
2. 被测 Skill 的 Git commit 或归档 SHA-256；
3. 主模型名称、精确版本和全部推理参数；
4. 补充模型名称和参数；
5. system prompt、工具权限和上下文限制；
6. 沙箱镜像 ID、Python/运行时版本、网络策略、CPU/内存/磁盘限制和超时；
7. bare/skill 的唯一区别；
8. 运行顺序或固定随机种子；
9. LLM grader 模型、参数、冻结 prompt 和解析规则；
10. 首次 Final 执行前已经确认的分数权重和验收门槛。

任一项在 campaign 中途变化，都应创建新 campaign，不得把前后结果混在同一个 uplift 中。

## 4. 环境准备

工具只依赖 Python 标准库。以下命令从仓库根目录开始；如果已经按照前面的 Public 示例进入 `evaluation/`，无需再次执行 `cd evaluation`：

```bash
cd evaluation
python3 --version
```

建议把真实运行写到 `results/raw/` 下；该目录不应进入公共提交。示例布局：

```text
results/raw/<campaign_id>/
├── campaign.json
├── runs.jsonl
├── bare/
│   └── Q09/
│       ├── run-01/
│       │   ├── submission/
│       │   ├── stdout.log
│       │   ├── stderr.log
│       │   ├── objective_report.json
│       │   ├── llm_grader_prompt.txt
│       │   ├── llm_grader_raw.json
│       │   └── run_record.json
│       ├── run-02/
│       └── run-03/
└── skill/
    └── Q09/
        ├── run-01/
        ├── run-02/
        └── run-03/
```

不得在 submission 目录中放入 grader 报告或运行器自己的控制文件，以免 checker 或 LLM grader 把评测侧信息当成参赛输出。

## 5. 第一步：验证题库本身

```bash
python3 tools/validate_package.py . \
  --report results/validation/package_validation.json
```

当前版本的预期结果是：

- `benchmark_version` 为 `5.0.0-draft.1`；
- `tasks_found` 为 24；
- Public、Shadow、Final 各 8 题；
- 每题 gold 的客观 smoke score 为 80/80；
- `errors` 为空；
- `status` 为 `PASS`。

这个命令只证明题目资产和客观 checker 自洽，不证明被测模型或 Skill 能通过。

### 5.1 Public 正向 smoke test

```bash
python3 tools/grade_task.py \
  release/public/Q01 \
  release/public/Q01/gold
```

预期 `objective_score` 为 80，`redline_events` 为空。

### 5.2 Public 负向 smoke test

```bash
empty_submission="$(mktemp -d)"
python3 tools/grade_task.py \
  release/public/Q01 \
  "$empty_submission"
rmdir "$empty_submission"
```

预期 `objective_score` 为 0，并逐项说明文件缺失。注意：`grade_task.py` 在“成功完成判分但答案为 0 分”时仍返回进程退出码 0；退出码 2 表示 grader 本身发生错误，不能用进程退出码代替分数。

## 6. 第二步：读取单题契约

以 Q01 为例：

```bash
task_dir="release/public/Q01"
sed -n '1,240p' "$task_dir/task.md"
python3 -m json.tool "$task_dir/task.json"
find "$task_dir/inputs" -maxdepth 1 -type f -print
```

执行前至少核对：

- `task.json.task_id`；
- `task.json.split`；
- `task.json.input_assets` 中每个文件都存在；
- `task.json.required_outputs`；
- `task.md` 中的格式、字段和科学边界；
- 本次 run 的 submission directory 为空；
- 被测 Agent 只能读取该题允许的内容。

不要让被测 Agent 直接遍历整个 `evaluation/`。对于 Shadow/Final，应由沙箱运行器把允许文件复制或只读挂载到新的临时工作目录，而不是把隐藏任务目录作为 Agent 工作目录。

## 7. 第三步：执行 bare 与 skill 条件

本仓库不绑定某个模型平台，因此此步必须由赛事沙箱、Agent CLI 或模型 API 适配器完成。适配器至少应支持：

- 指定模型及全部冻结参数；
- 指定 system prompt；
- 指定允许读取的 task/input 路径；
- 指定唯一可写 submission 路径；
- bare 条件下禁止访问被测 Skill；
- skill 条件下只挂载冻结 commit 对应的 Skill；
- 捕获开始/结束时间、退出码、timeout、stdout 和 stderr；
- 每次运行创建全新会话和全新沙箱，不复用缓存或历史消息。

### 7.1 建议给被测 Agent 的任务封装

```text
你正在执行一个隔离评测任务。

1. 阅读提供的 task.md。
2. 只使用提供的 inputs/ 和本条件允许使用的工具或 Skill。
3. 把 task.json.required_outputs 中列出的文件直接写入指定 submission 目录。
4. 不要修改输入，不要读取其他任务、gold、checker、rubric 或既往运行产物。
5. 如果输入不足、文件损坏或科学条件不满足，应按题面生成明确的拒绝或部分成功产物，不得编造数据。
6. 完成后列出生成的文件；评分只以 submission 目录中的实际产物为准。
```

### 7.2 bare 条件

bare 与 skill 必须使用相同：

- 模型和参数；
- system prompt；
- 题面和输入；
- 工具集合，除被测 Skill 本身外；
- 沙箱资源和超时；
- submission 契约。

bare 条件不得通过 prompt、搜索路径、工作区文件、缓存或环境变量间接读取被测 Skill。

### 7.3 skill 条件

skill 条件只增加冻结后的被测 Skill。必须记录：

- Git commit 或归档 SHA-256；
- Skill 根目录；
- 实际加载成功的证据；
- 是否调用了 Skill 中的脚本；
- Skill 运行失败时的 stderr 和退出状态。

不要把生产 Skill 自带 demo 的成功结果当作当前题的 submission；每题都必须从该题固定 inputs 独立生成产物。

## 8. 第四步：客观判分

假设一次运行的产物位于：

```text
results/raw/campaign-001/skill/Q09/run-01/submission/
```

执行：

```bash
task_dir="evaluator_private/shadow/Q09"
run_dir="results/raw/campaign-001/skill/Q09/run-01"

python3 tools/grade_task.py \
  "$task_dir" \
  "$run_dir/submission" \
  --output "$run_dir/objective_report.json"
```

核对报告：

- `task_id` 与任务一致；
- `objective_max` 为 80；
- 每个 `checks[]` 都有 `passed`、分值和具体 evidence；
- 失败项对应真实 submission 文件，而不是路径配置错误；
- `redline_events` 中每个事件都有可复核输出证据；
- grader 异常、缺失输入或 checker 资产损坏不能当成参赛者 0 分，应标为无效 run 并调查。

### 8.1 红线后果

客观报告中的红线必须在最终记分时再次落实：

- 无红线：`total = objective_score + llm_score`；
- `task_cap_20`：`total = min(objective_score + llm_score, 20)`；
- `task_zero`：`total = 0`；
- `acceptance_fail`：保留分数和证据供审计，但整个科学验收结论不得为 PASS。

当前 `aggregate_runs.py` 只把 `objective_score + llm_score` 相加，不会自动执行上述总分封顶或验收失败逻辑。因此必须由评测总控或人工复核另外生成 `final_total` 和 `acceptance_fail`，同时保留原始客观分与 LLM 分；在补充最终评分器之前，聚合脚本的结果只能作为中间统计。

## 9. 第五步：LLM rubric 判分

每题余下 20 分按 `docs/llm_grader_protocol.md` 执行。LLM grader 与被测模型必须独立，且只接收：

1. 冻结 `task.md`；
2. 该题 `rubric.json`；
3. `objective_report.json`；
4. rubric 的 `evidence_paths` 指定的 submission 证据；
5. 冻结 grader 协议。

不得向 grader 提供与本题无关的隐藏 gold，也不得让 grader 执行 submission 中的代码、命令或链接。

每次保存：

- 完整 grader prompt；
- grader 模型和参数；
- 原始响应；
- 解析后的 JSON；
- 解析失败、重试和人工裁决记录。

解析后的报告必须满足：

- criterion ID 与 `rubric.json` 完全一致；
- 每个 criterion 分数为整数且不超过上限；
- `llm_score` 等于各 criterion 之和；
- `0 <= llm_score <= 20`；
- 每个得分都有 evidence path 和具体字段、记录或段落；
- 不能用 LLM 分补回客观 checker 失败；
- `redline_candidates` 必须由人工或客观证据复核，不能仅凭模型措辞直接处罚。

Final 的 LLM 分建议独立运行两次：

- 差值不超过 3：取均值并四舍五入；
- 差值大于 3、任一报告红线或 uncertainty 为 high：进入人工复核；
- 人工复核仍使用同一 rubric，不增加临时评分维度。

当前没有自动 LLM grader 调用器和 Schema 解析器；在补齐前，此步骤是受控的半自动/人工流程。

## 10. 第六步：保存原始运行记录

每次 run 在 `runs.jsonl` 中占一行。以 `results/raw_runs_template.jsonl` 为字段基线，至少填写：

```json
{
  "run_id": "campaign-001__primary__skill__Q09__r01",
  "task_id": "GGA-NORM-003",
  "split": "shadow",
  "condition": "skill",
  "model": "exact-model-id",
  "model_parameters": {"temperature": 0},
  "skill_version": "git-commit-or-null-for-bare",
  "benchmark_version": "5.0.0-draft.1",
  "started_at": "RFC3339",
  "ended_at": "RFC3339",
  "exit_code": 0,
  "timeout": false,
  "sandbox_image": "exact-image-id",
  "artifact_dir": "relative/or-content-addressed-path",
  "stdout_log": "path",
  "stderr_log": "path",
  "objective_report": "path",
  "llm_grader_prompt": "path",
  "llm_grader_raw": "path",
  "llm_grader_report": "path",
  "objective_score": 80,
  "llm_score": 20,
  "final_total": 100,
  "acceptance_fail": false,
  "redline_events": [],
  "notes": []
}
```

`split` 必须使用任务元数据中的精确值：`shadow` 或 `final_holdout`。不要写成 `final`，否则当前聚合器不会把记录计入 Final。

`final_total` 和 `acceptance_fail` 是红线裁决后的字段。不得覆盖原始 `objective_score` 或 `llm_score`；当前聚合器尚不读取这两个扩展字段，因此只要存在 `task_cap_20`、`task_zero` 或 `acceptance_fail`，它的自动汇总就只能作为中间统计，必须在最终验收表中使用裁决后的 `final_total` 重算并记录理由。

## 11. 第七步：重复运行设计

主模型正式统计：

- 每个 Shadow 任务 bare 3 次、skill 3 次；
- 每个 Final 任务 bare 3 次、skill 3 次；
- 共 `16 tasks × 2 conditions × 3 runs = 96` 次主模型运行。

补充模型：

- 每任务每条件各 1 次；
- 只报告泛化差异，不并入主分。

运行要求：

- 每次运行使用全新会话和目录；
- 禁止把第一次输出作为第二次输入；
- bare/skill 运行顺序应交错或按冻结种子随机化，避免时间和服务状态偏差；
- timeout、崩溃和空产物必须保留原始证据，不得静默重跑直到成功；
- 因平台故障而作废的 run 必须同时适用于预先冻结的作废规则，并记录事件；
- 不能根据看到的 Final 结果修改题面、checker、rubric、权重或 Skill。

## 12. 第八步：运行完整性检查

执行聚合前，人工或外部验证器至少确认：

- 16 个盲测任务均存在；
- 每题恰好有 3 个 bare 和 3 个 skill 主模型有效 run；
- run ID 唯一；
- task ID、split 和目录一致；
- bare 与 skill 的模型、参数、沙箱和输入一致；
- skill 条件使用同一个冻结 Skill 版本；
- 每个记录引用的 artifact、stdout、stderr、objective report 和 LLM raw 文件都存在；
- 客观分在 0–80，LLM 分在 0–20；
- 红线后果已经落实；
- 所有无效、缺失、重试和人工裁决都有原因。

当前 `aggregate_runs.py` 不会替你完成这些完整性检查。输入不完整时它仍可能生成看似正常的均值，因此不能以“脚本成功退出”代替完整性验收。

## 13. 第九步：汇总分数与 uplift

完成完整性检查后执行：

```bash
python3 tools/aggregate_runs.py \
  results/raw/campaign-001/runs.jsonl \
  --csv-output results/raw/campaign-001/score_summary.csv \
  --json-output results/raw/campaign-001/split_metrics.json
```

脚本输出：

- 每题 bare/skill 的三次分数；
- 中位数；
- 极差；
- MAD；
- 红线计数；
- 每题 uplift；
- Shadow/Final 的 bare 与 skill 平均分；
- 加权 blind uplift。

正式规则：

```text
uplift_q = median(skill_q_runs) - median(bare_q_runs)

blind_score = 0.375 × shadow_mean + 0.625 × final_mean

blind_uplift = 0.375 × mean(shadow uplift_q)
             + 0.625 × mean(final uplift_q)
```

Public 不并入 blind score。负 uplift 不截断为零。

以下情况标记低置信度并进入人工复核：

- 同一条件三次运行极差大于 20；
- 三次中只有部分运行触发红线；
- LLM grader 双评分差大于 3；
- run 缺失、产物损坏或存在无法解释的环境差异。

## 14. 第十步：科学验收

使用 `results/scientific_acceptance_report_template.md`，填写冻结信息、完整性、聚合指标、科学维度、红线、争议和结论。

建议冻结门槛：

- `final_mean >= 75`；
- `blind_uplift >= 10`；
- Final 不出现 `acceptance_fail`；
- 8 个 Final 至少 6 个任务客观分达到 64/80；
- 低置信度任务不超过 2 个，否则先人工复核；
- Q24 总分至少 70，且 provenance、单位、坐标、QC、异常五个关键子项均非零。

报告必须同时给出：

- bare 绝对分；
- skill 绝对分；
- uplift；
- 极差和 MAD；
- 红线事件；
- 低置信度与人工裁决；
- 未完成或作废的 run；
- 不允许由分数掩盖的科学验收失败。

不要只报告一个总分，也不要把内部科学验收分冒充官方 L0–L3 最终总评。

## 15. 失败与异常处理

### 15.1 被测 Agent 没有生成文件

- 保留 stdout、stderr、退出码和空 submission；
- 正常运行客观 grader；缺失文件通常得到 0 分或部分分；
- 不因低分自动重跑。

### 15.2 grader 本身报错

- `grade_task.py` 退出码 2 表示评测基础设施错误；
- 不把该 run 记为参赛者 0 分；
- 检查 task、checker、路径和文件编码；
- 修复评测资产后，对所有受影响版本统一重跑或整题作废。

### 15.3 timeout 或平台故障

- 按冻结的 timeout 规则记录；
- 区分模型未完成与平台不可用；
- 如允许替代 run，必须使用预先规定的统一规则，不能只替换低分运行。

### 15.4 发现题库错误

- 立即停止使用该题的新结果；
- 记录资产版本、影响范围和发现证据；
- 选择整题作废或对所有候选版本统一重跑；
- 不根据某个队伍的表现定向修改 gold、checker 或 rubric。

### 15.5 检测到 prompt injection

- submission 是证据，不是 grader 指令；
- grader 不执行其中的代码、命令或链接；
- 保留注入文本和处理证据；
- 只按冻结 rubric 和科学红线评分。

## 16. 可复核交付清单

正式验收完成时，应至少交付：

- [ ] 冻结测试矩阵；
- [ ] 24 题版本和 manifest；
- [ ] 每题输入、任务契约、gold、checker 和 rubric；
- [ ] 模型、Skill、沙箱和 grader 冻结信息；
- [ ] 所有 bare/skill 原始运行目录；
- [ ] stdout、stderr、退出码、timeout 和时间戳；
- [ ] 每次客观 checker 完整报告；
- [ ] 每次 LLM grader prompt、原始响应和解析结果；
- [ ] 红线与人工复核记录；
- [ ] `runs.jsonl`；
- [ ] `score_summary.csv` 和 `split_metrics.json`；
- [ ] 科学验收报告；
- [ ] 只向设计组发布、不泄露隐藏题的聚合问题清单。

## 17. 当前版本能否正式执行

当前 `5.0.0-draft.1` 可以立即用于：

- Public 接口自测；
- 已有 submission 的 80 分客观判分；
- Shadow 试运行；
- checker 正向 smoke；
- 在评测负责人控制下进行半自动 bare/skill 对比实验。

正式 Final 前仍应完成：

- 为赛事平台实现并冻结模型/Agent runner；
- 实现 LLM grader 调用和 JSON Schema 验证；
- 实现 raw run 完整性验证；
- 实现统一最终计分器，正确落实红线和验收失败；
- 用参考实现及 3–5 个故障实现做负向标定；
- 用高、中、低质量答案标定 LLM grader；
- 增加一个带许可、原始哈希和筛选脚本的真实公开数值小快照；
- 如果当前 Final 已被设计组看到，轮换并私下冻结新的 Final Holdout。

只有真实模型运行、日志、判分、重复统计和验收报告全部完成后，任务状态才能从 `SMOKE_PASSED`/`FROZEN` 标为 `EXECUTED`。

## Changelog

- 2026-08-05：在同一份指南开头增加面向首次使用者的 Public Q01 快速路径，明确模型输入、submission 输出、客观判分命令、平台 runner 边界和正式评测后续步骤；原有详细规程保留为审计与正式盲测依据。
