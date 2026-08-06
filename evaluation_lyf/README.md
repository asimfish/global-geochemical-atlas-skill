# D1 / D2 / D3 独立评测工作区

`evaluation_lyf/` 是独立的模块评测与 Skill uplift 工作区。它不修改、覆盖或依赖团队其他同学维护的
`evaluation/`。

## 目录边界

```text
evaluation_lyf/
├── README.md
├── stage_benchmark/          # D1、D2、D3 独立单元测试和简化端到端测试
├── reference_implementation/
│   └── d2/                 # 只供基准自校验的 D2 参考实现
└── agent_uplift/            # Qwen3.8-Max 有 Skill / 无 Skill 对照实验
```

`reference_implementation/` 不是参赛正式代码，也不应替代 D1、D2 或 D3 同学的候选实现。它只用于证明基准的
输入、输出和评分器能完整跑通。

## 分阶段测试

从仓库根目录执行：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage d1 \
  --d1-script /absolute/path/to/candidate_d1.py \
  --output-dir /tmp/geochem-d1-candidate
```

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage d2 \
  --d2-script /absolute/path/to/candidate_d2.py \
  --output-dir /tmp/geochem-d2-candidate
```

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage d3 \
  --d3-script /absolute/path/to/candidate_d3.py \
  --output-dir /tmp/geochem-d3-candidate
```

运行 93,369 条冻结真实测定的 D1→D2→D3 参考链路：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_completion_reference.py \
  --output-dir /tmp/geochem-stage-v2-reference
```

评分输出中必须区分候选实现缺陷、真实来源缺失与不适用情况；不得通过填造分析方法、坐标精度、地质背景或因果结论使检查通过。

## Agent uplift 隔离

`agent_uplift/` 只向被测 Agent 暴露公开任务、数据下载器和不变的 scorer。候选 Agent 不得读取
`stage_benchmark/`、`reference_implementation/`、gold 或历史运行结果。这保证有 Skill 与无 Skill 两组的唯一自变量是 Skill 是否可见。

## Qwen3.8-Max 测试 Prompt

准备两个空白且相互隔离的 Qwen3.8-Max Agent 会话和目录，分别原样发送下面两段 Prompt。两组必须使用同一
commit、机器资源、网络策略、公开任务和 scorer；不得把一组的产物、错误或解决方法告诉另一组。每组独立运行三次，以最终
`score.json.score` 的中位数计算 `uplift = with_skill - no_skill`。数据下载时间单独记录，不算入任务执行时间。

两段 Prompt 也单独保存在
[`QWEN_WITH_SKILL_PROMPT.md`](agent_uplift/QWEN_WITH_SKILL_PROMPT.md) 和
[`QWEN_NO_SKILL_PROMPT.md`](agent_uplift/QWEN_NO_SKILL_PROMPT.md)，便于直接复制。

### Prompt A：使用 Skill

````text
你正在参加一次受控的 Agent Skill uplift 实验。请直接执行任务，不要只给方案，不要询问我确认。你的当前目录是空白目录，
唯一允许的 Skill 是指定仓库分支中的 `global-geochemical-atlas`。不得读取该仓库的参考实现、gold 或历史运行结果。

固定仓库与分支：

- repository: `https://github.com/asimfish/global-geochemical-atlas-skill.git`
- branch: `evaluation-stage-benchmark-v2`

先执行以下等价操作（目录名可不同，但必须记录最终 commit）：

```bash
git clone --filter=blob:none --no-checkout --branch evaluation-stage-benchmark-v2 \
  https://github.com/asimfish/global-geochemical-atlas-skill.git repo
cd repo
git sparse-checkout init --no-cone
git sparse-checkout set '/skills/global-geochemical-atlas/**' '/evaluation_lyf/agent_uplift/**'
git checkout evaluation-stage-benchmark-v2
git rev-parse HEAD
```

完整读取 `skills/global-geochemical-atlas/SKILL.md`，并按其路由规则只读取任务所需 references/scripts/assets；明确把它作为本次任务使用的 Skill。
然后完整读取 `evaluation_lyf/agent_uplift/TASK.md`，在 `evaluation_lyf/agent_uplift/experiment/with_skill/` 完成任务。

约束：

- 模型固定为 Qwen3.8-Max；不得调用其他模型代做科学判断或代码生成。
- 可以联网下载 `public_case/prepare_case.py` 声明的数据；下载时间不计时。
- 不得扩展 sparse checkout；不得读取或恢复 `evaluation_lyf/stage_benchmark`、`evaluation_lyf/reference_implementation`、gold 或 Git 历史中的参考实现。
- 可以运行和修改 Skill 自带脚本，也可以在实验目录新增代码；不得修改 scorer。
- 真实来源未报告的分析方法、地质背景、坐标不确定度必须显式写 unknown，不能推断补齐。
- 最多进行三轮“实现→公开 scorer→修正”。无论最终通过与否都必须保存真实结果。

执行：

```bash
python evaluation_lyf/agent_uplift/public_case/prepare_case.py \
  --output-dir evaluation_lyf/agent_uplift/experiment/with_skill/case_data
# 按 TASK.md 生成 experiment/with_skill/submission
python evaluation_lyf/agent_uplift/public_case/score_submission.py \
  --submission-dir evaluation_lyf/agent_uplift/experiment/with_skill/submission \
  --output evaluation_lyf/agent_uplift/experiment/with_skill/score.json
```

最终回复必须给出：commit SHA、`skill_used=true`、总耗时（另列下载耗时）、每轮 scorer 分数、最终 100 分明细、失败检查、
实际生成文件及字节数、关键科学边界，以及以下三个绝对路径：`score.json`、`agent_report.md`、`interactive_map.html`。
不要只说“已完成”；若失败，保留失败产物并解释根因。
````

### Prompt B：不使用 Skill

````text
你正在参加一次受控的 Agent Skill uplift 实验。请直接执行任务，不要只给方案，不要询问我确认。你的当前目录是空白目录。
本组禁止读取、安装、搜索或使用任何 Skill；只能依赖 Qwen3.8-Max 自身知识、公开任务说明、固定数据和你现场编写的代码。
不得读取指定仓库的参考实现、gold、历史运行结果或 `skills/` 目录。

固定仓库与分支：

- repository: `https://github.com/asimfish/global-geochemical-atlas-skill.git`
- branch: `evaluation-stage-benchmark-v2`

先只稀疏检出公开任务与 scorer（不得检出 `skills`）：

```bash
git clone --filter=blob:none --no-checkout --branch evaluation-stage-benchmark-v2 \
  https://github.com/asimfish/global-geochemical-atlas-skill.git repo
cd repo
git sparse-checkout init --no-cone
git sparse-checkout set '/evaluation_lyf/agent_uplift/**'
git checkout evaluation-stage-benchmark-v2
git rev-parse HEAD
```

完整读取 `evaluation_lyf/agent_uplift/TASK.md`，在 `evaluation_lyf/agent_uplift/experiment/no_skill/` 完成同一任务。

约束：

- 模型固定为 Qwen3.8-Max；不得调用其他模型代做科学判断或代码生成。
- 禁止使用任何 Skill、插件生成器或来自其他会话的实现；`agent_report.json` 必须写 `skill_used=false`。
- 可以联网下载 `public_case/prepare_case.py` 声明的数据；下载时间不计时。
- 不得扩展 sparse checkout；不得读取或恢复 `skills`、`evaluation_lyf/stage_benchmark`、`evaluation_lyf/reference_implementation`、gold 或 Git 历史参考实现。
- 可以安装已声明依赖并现场新增代码；不得修改 scorer。
- 真实来源未报告的分析方法、地质背景、坐标不确定度必须显式写 unknown，不能推断补齐。
- 最多进行三轮“实现→公开 scorer→修正”。无论最终通过与否都必须保存真实结果。

执行：

```bash
python evaluation_lyf/agent_uplift/public_case/prepare_case.py \
  --output-dir evaluation_lyf/agent_uplift/experiment/no_skill/case_data
# 按 TASK.md 生成 experiment/no_skill/submission
python evaluation_lyf/agent_uplift/public_case/score_submission.py \
  --submission-dir evaluation_lyf/agent_uplift/experiment/no_skill/submission \
  --output evaluation_lyf/agent_uplift/experiment/no_skill/score.json
```

最终回复必须给出：commit SHA、`skill_used=false`、总耗时（另列下载耗时）、每轮 scorer 分数、最终 100 分明细、失败检查、
实际生成文件及字节数、关键科学边界，以及以下三个绝对路径：`score.json`、`agent_report.md`、`interactive_map.html`。
不要只说“已完成”；若失败，保留失败产物并解释根因。
````

### 结果回收

对每一组的三次运行收集：

- commit SHA 和 `skill_used`；
- 首轮、最终轮及中位数分数；
- D1、D2、D3 和可复现性分项分；
- 失败检查、科学红线和人工复核项；
- 扣除下载后的执行时间与运行成功率；
- `score.json`、`agent_report.md`、`agent_report.json` 和 `interactive_map.html` 的绝对路径。

只有有 Skill 组的中位数更高、科学红线没有恶化且两组条件一致，才可宣称存在正 uplift。
