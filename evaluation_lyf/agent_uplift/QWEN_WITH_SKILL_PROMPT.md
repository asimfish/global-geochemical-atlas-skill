# 复制给空白 Qwen3.8-Max Agent：使用 Skill 组

你正在参加一次受控的 Agent Skill uplift 实验。请直接执行任务，不要只给方案，不要询问我确认。你的当前目录是空白目录，
唯一允许的 Skill 是指定仓库分支中的 `global-geochemical-atlas`。不得读取该仓库的参考实现、gold 或历史运行结果。

固定仓库与分支：

- repository: `https://github.com/asimfish/global-geochemical-atlas-skill.git`
- branch: `main`

先执行以下等价操作（目录名可不同，但必须记录最终 commit）：

```bash
git clone --filter=blob:none --no-checkout --branch main \
  https://github.com/asimfish/global-geochemical-atlas-skill.git repo
cd repo
git sparse-checkout init --no-cone
git sparse-checkout set '/skills/global-geochemical-atlas/**' '/evaluation_lyf/agent_uplift/**'
git checkout main
git rev-parse HEAD
```

完整读取 `skills/global-geochemical-atlas/SKILL.md`，并按其路由规则只读取任务所需 references/scripts/assets；明确把它作为本次
任务使用的 Skill。然后完整读取 `evaluation_lyf/agent_uplift/TASK.md`，在仓库外或 `evaluation_lyf/agent_uplift/experiment/with_skill/`
完成任务。

约束：

- 模型固定为 Qwen3.8-Max；不得调用其他模型代做科学判断或代码生成。
- 可以联网下载 `public_case/prepare_case.py` 声明的数据；下载时间不计时。
- 不得扩展 sparse checkout；不得读取或恢复 `evaluation_lyf/stage_benchmark`、`evaluation_lyf/reference_implementation`、gold 或 Git 历史中的参考实现。
- 可以运行和修改 Skill 自带脚本，也可以在实验目录新增代码；不得修改 scorer。
- 真实来源未报告的分析方法、地质背景、坐标不确定度必须显式 unknown，不能推断补齐。
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
