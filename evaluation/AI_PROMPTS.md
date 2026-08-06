# AI Prompt 导航

本目录有两类 AI，职责和可见材料必须严格分开。

## 让 AI 做题

Q01–Q24 的可直接使用版本全部位于：

- [`ai_visible_public/AGENT_PROMPT.md`](ai_visible_public/AGENT_PROMPT.md)

它的维护源文件位于：

- [`prompts/answering_agent_prompt.md`](prompts/answering_agent_prompt.md)

工作目录必须设为 `evaluation/ai_visible_public/`，然后把 `AGENT_PROMPT.md` 的全文交给答题 AI。答题 AI 能看到的全部 Benchmark 材料只能来自这个目录：公共接口、Q01–Q24 的 `task.md`、`task.json` 和 `inputs/`；它只能写 `submissions/Qxx/`，不得读取父目录、checker、rubric、gold、评分 prompt 或评分工具。

评分侧 Q01–Q08 的完整源位于 `release/public/`，Q09–Q24 的完整源位于 `evaluator_private/`；两者都包含答题 AI 不应看到的 gold、checker 或 rubric。运行器不得把这些目录直接交给答题 AI，只能使用 `ai_visible_public/` 的白名单投影。

如需单题运行，也必须从 `ai_visible_public/` 创建沙箱，并在答题 prompt 前提供本次沙箱内的路径：

```text
TASK_ROOT=<沙箱内只读题面目录>
SUBMISSION_ROOT=<沙箱内可写提交目录>
只处理 TASK_ROOT 中这一道题，并把 task.json.required_outputs 的相对路径写到 SUBMISSION_ROOT 下。
```

## 让另一个 AI 评分

完整的独立评分代理 prompt 位于：

- [`docs/independent_grading_agent_prompt.md`](docs/independent_grading_agent_prompt.md)

逐题冻结的 LLM grader system/user prompt 和输出 Schema 位于：

- [`docs/llm_grader_protocol.md`](docs/llm_grader_protocol.md)

把 `independent_grading_agent_prompt.md` 中“PROMPT 开始”到“PROMPT 结束”的全部内容交给评分 AI，并替换其中的评测根目录、提交根目录和全新评分输出目录。评分 AI 不得修改提交，也不得把 gold 用作候选答案证据。

## 不要混用

- `prompts/answering_agent_prompt.md`：给被测/答题 AI。
- `docs/independent_grading_agent_prompt.md`：给独立评分编排 AI。
- `docs/llm_grader_protocol.md`：评分编排中的逐题冻结裁判 prompt。

题面或候选可见契约发生变化时必须提升 Benchmark 版本并重新运行答题 AI；不得用新题面追溯性地重评旧提交。`shadow` 和 `final_holdout` 在本版本中只是保留的回归分组标签，不表示这些题仍然隐藏；Q17–Q24 已经历史暴露，不具备正式 holdout 资格。
