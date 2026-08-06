# 测试 Prompt 总入口

本仓库有两类评测内容和一套 Docker 执行底座。不要把 Docker 当成第三套题库，也不要把评分 Prompt 发给答题 Agent。

| 场景 | 被测内容 | 需要人工粘贴什么 | Canonical 来源 |
|---|---|---|---|
| `evaluation/` 手工答 Q01–Q24 | E1 十产物、题目契约与科学证据 | B0 无 Skill / S0 有 Skill 两个启动 Prompt，共用同一核心题面 | `evaluation/prompts/QWEN_*_PROMPT.md` |
| `evaluation/` 独立评分 | checker、LLM rubric、E1 finalizer | 完整评分编排 Prompt | `evaluation/docs/independent_grading_agent_prompt.md` |
| `evaluation_lyf/stage_benchmark/` | D1/D2/D3 独立科学门禁 | 不使用模型 Prompt，运行确定性命令 | `evaluation_lyf/README.md` |
| `evaluation_lyf/agent_uplift/` | 公开真实数据的纯 Qwen / Qwen + Skill uplift | 主机版两份 + Docker 版两份 | `evaluation_lyf/agent_uplift/QWEN_*_PROMPT.md` |
| `evaluation/docker/` | 隔离、资源限制、OpenCode、B0/S0 campaign | 不另写候选 Prompt；runner 自动按题注入 | `evaluation/docker/campaign.py` |

## 1. `evaluation/`：Q01–Q24 答题 Prompt

工作目录必须只包含候选可见材料，不能把整个仓库作为答题 Agent 工作目录。需要从空目录手工启动两个实验臂时，分别使用：

- [Qwen B0 无 Skill Prompt](evaluation/prompts/QWEN_B0_NO_SKILL_PROMPT.md)
- [Qwen S0 有 Skill Prompt](evaluation/prompts/QWEN_S0_WITH_SKILL_PROMPT.md)

两者负责不同的环境准备，但最终都执行下面同一份核心题面。正式 Docker B0/S0 也始终使用同一核心题面，仅由 runner 改变 Skill 挂载。

### Prompt E-A：答题 Agent

```text
请完整阅读当前工作目录中的 AGENT_PROMPT.md，并严格执行其中的全部要求。自主完成 Q01–Q24，把每道题要求的输出写入 submissions/Qxx/。不要访问父目录，不要寻找 gold、checker、rubric 或其他评测材料，也不要自行评分。除非遇到真正无法解决的环境错误，否则持续执行到二十四道题全部完成。
```

真正约束答题行为的维护源是 [`evaluation/prompts/answering_agent_prompt.md`](evaluation/prompts/answering_agent_prompt.md)，候选可见副本是 [`evaluation/ai_visible_public/AGENT_PROMPT.md`](evaluation/ai_visible_public/AGENT_PROMPT.md)。拆分的 B0/S0 文件是“启动与隔离 Prompt”，不是两套不同的科学题面；这样既能让手工测试明确条件，又不让题面措辞成为混杂变量。

### Prompt E-G：独立评分 Agent

答题结束后，另开一个无法修改 submission 的评分会话。把 [`evaluation/docs/independent_grading_agent_prompt.md`](evaluation/docs/independent_grading_agent_prompt.md) 中“PROMPT 开始”到“PROMPT 结束”的全文发给评分 Agent，只替换以下三个路径：

```text
EVALUATION_ROOT=<仓库中的 evaluation 绝对路径>
SUBMISSIONS_ROOT=<evaluation/ai_visible_public/submissions 绝对路径>
OUTPUT_ROOT=<一个全新且不存在的评分输出目录>
```

评分 Prompt、gold、checker、rubric 和私有题源绝不能暴露给答题 Agent。

## 2. `evaluation_lyf/`：阶段门禁与公开 uplift

### D1/D2/D3 阶段门禁

这部分是确定性测试，不需要模型 Prompt：

```bash
python3 evaluation_lyf/suite_adapter.py \
  --suite isolated \
  --stress-records 10000 \
  --timeout-seconds 900 \
  --output-dir /tmp/gga-isolated-gate
```

候选 D1、D2、D3 的逐阶段入口见 [`evaluation_lyf/README.md`](evaluation_lyf/README.md)。

### Qwen Skill uplift

`evaluation_lyf` 同时保留原主机直跑和 Docker 隔离两种 runtime profile。每种方式都分别创建两个空目录和两个互不通信的 Qwen3.8-Max 会话。

主机直跑（明确禁止 Docker）：

- [主机 B0：无 Skill](evaluation_lyf/agent_uplift/QWEN_NO_SKILL_PROMPT.md)
- [主机 S0：有 Skill](evaluation_lyf/agent_uplift/QWEN_WITH_SKILL_PROMPT.md)

Docker 隔离：

- [Docker B0：无 Skill](evaluation_lyf/agent_uplift/QWEN_NO_SKILL_DOCKER_PROMPT.md)
- [Docker S0：有 Skill](evaluation_lyf/agent_uplift/QWEN_WITH_SKILL_DOCKER_PROMPT.md)

四份 Prompt 都包含仓库克隆、固定 commit、Skill 隔离、公开数据下载、最多三轮 scorer、`run.sh` 干净重建和结果回收；Docker 版额外准备镜像与资源隔离。不要再追加实现建议。正式实验每个 runtime profile 内每组独立运行三次并比较中位数；主机结果和 Docker 结果不得混算。

## 3. `evaluation/docker/`：Docker 自动注入 Prompt

Docker 是 `evaluation` 和 `evaluation_lyf` 共用的运行层。`campaign.py` 会为每个 Q01–Q24 单题容器自动生成以下候选 Prompt；B0/S0 的文字完全相同：

```text
你正在执行一个隔离的文件产物评测任务。请直接完成任务，不要只给方案，也不要询问确认。

只允许读取：/task
只允许将最终交卷写入：/submission
工作目录：/workspace

先读取 /task/public_interface.md、/task/task.md、/task/task.json 和 /task/inputs/。
如环境中发现与任务相关的 Agent Skill，应按其 description 判断并按需加载；若没有可用 Skill，则依靠当前模型完成同一任务。
严格生成 task.json.required_outputs 声明的十个 artifacts/ 文件。题目专用逻辑证据写入 /submission/artifacts/run_manifest.json 的 benchmark_evidence，不创建额外交卷文件。
不得读取其他任务、评分器、gold、rubric、历史结果或 /task 之外的外部目录；不得编造来源未报告的科学事实。
```

不要手工改写这段 Prompt。B0 不挂载 Skill，S0 只读挂载同一 Skill；镜像、模型、temperature、资源、网络、题面和运行次数保持一致。

### Docker runner smoke

mock 只验证 Docker 管线，不代表模型分数：

```bash
python3 evaluation/docker/campaign.py build-image \
  --image global-geochemical-eval:local

python3 evaluation/docker/campaign.py run \
  --image global-geochemical-eval:local \
  --agent mock \
  --network offline \
  --tasks Q01 \
  --conditions B0,S0 \
  --repeats 3 \
  --output-dir /tmp/gga-docker-smoke
```

### Docker + OpenCode 正式本地 campaign

```bash
export EVAL_API_KEY='<通过环境变量注入，不写入仓库或命令记录>'

python3 evaluation/docker/campaign.py run \
  --image global-geochemical-eval:local \
  --campaign-id qwen-main-v1 \
  --agent opencode \
  --network whitelist \
  --provider-base-url https://<兼容 OpenAI API 的网关>/v1 \
  --api-key-env EVAL_API_KEY \
  --model qwen3.8-max \
  --temperature 0 \
  --tasks all \
  --conditions B0,S0 \
  --repeats 3 \
  --timeout-seconds 900 \
  --output-dir /runs/qwen-main-v1
```

完整镜像构建、网络白名单、补充模型、证据目录和失败码见 [`evaluation/docs/docker_usage.md`](evaluation/docs/docker_usage.md)。

## 4. 应该选哪一个

- 想快速检查代码有没有破坏 D1/D2/D3：运行 `component_test.py`、`self_test.py` 或 `evaluation_lyf` stage，不需要 Prompt；
- 想人工比较 Q01–Q24 的纯 Qwen 与 Qwen + Skill：分别使用 `evaluation/prompts/` 中的 B0/S0 启动 Prompt；
- 想得到 Q01–Q24 的规范 B0/S0 运行记录：用 Docker OpenCode campaign，runner 自动注入 Prompt；
- 想测“这个 Skill 对公开真实数据全流程到底有没有帮助”：从 `evaluation_lyf` 选择主机或 Docker profile，再使用对应的一对 Prompt；
- 想评分已经生成的 Q01–Q24 submission：另开评分 Agent，使用 Prompt E-G。

这些本地题和公开 case 都不是主办方隐藏题。没有隔离运行、同条件三次重复和新的私有题集时，不得把结果称为官方最终 uplift。
