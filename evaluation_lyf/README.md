# D1 / D2 / D3 独立评测与 Skill uplift

`evaluation_lyf/` 负责模块级科学门禁和公开数据上的 Skill uplift；`evaluation/` 负责 Q01–Q24、B0/S0 和 E1 对齐评分。它们是两类评测内容，统一复用 `evaluation/docker/` 执行底座，互不冒充分数。

## 目录边界

```text
evaluation_lyf/
├── suite_adapter.py           # 统一 JSON/日志/超时/退出码入口
├── stage_benchmark/           # D1、D2、D3 独立门禁与简化端到端测试
├── reference_implementation/  # 仅供基准自校验，不是参赛实现
└── agent_uplift/              # Qwen3.8-Max 有/无 Skill 公开对照实验
```

`reference_implementation/` 不应替代 D1、D2 或 D3 的候选实现，也绝不能挂载给被测 Agent。评分必须区分候选实现缺陷、真实来源缺失与不适用情况；不得通过填造分析方法、坐标精度、地质背景或因果结论使检查通过。

## 来源真实性门禁

以下入口复用 `evaluation` 中独立维护的 8 来源、4 介质冻结契约，检查 DOI/标题/版本/许可证、文件哈希及代表性原始行：

```bash
python3 evaluation_lyf/suite_adapter.py \
  --suite source-truth \
  --timeout-seconds 120 \
  --output-dir /tmp/gga-lyf-source-truth
```

它与 `real`/`completion` 的大规模处理测试互补：前者检查来源声明是否准确，后者检查真实数据处理是否完整。通过门禁不等于证明出版方无误或样品具有全球代表性。

## 统一入口

主机诊断：

```bash
python3 evaluation_lyf/suite_adapter.py \
  --suite isolated \
  --stress-records 10000 \
  --timeout-seconds 900 \
  --output-dir /tmp/gga-isolated-gate
```

统一 Docker 执行：

```bash
python3 evaluation/docker/campaign.py stage \
  --image global-geochemical-eval:local \
  --suite all \
  --output-dir /tmp/gga-stage-all
```

Docker 镜像、隔离、mock smoke 和 OpenCode campaign 的完整命令见 [`../evaluation/docs/docker_usage.md`](../evaluation/docs/docker_usage.md)。

## 分阶段候选测试

从仓库根目录执行；把脚本路径替换为候选 D1、D2 或 D3 实现：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage d1 --d1-script /absolute/path/to/candidate_d1.py \
  --output-dir /tmp/geochem-d1-candidate

python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage d2 --d2-script /absolute/path/to/candidate_d2.py \
  --output-dir /tmp/geochem-d2-candidate

python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage d3 --d3-script /absolute/path/to/candidate_d3.py \
  --output-dir /tmp/geochem-d3-candidate
```

冻结真实测定的参考链路只用于确认基准本身可运行：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_completion_reference.py \
  --output-dir /tmp/geochem-stage-v2-reference
```

## Qwen 有/无 Skill 测试

主机直跑和 Docker 隔离两种方式都保留；每种方式各有纯 Qwen 与 Qwen + Skill 两个实验臂：

- [主机版：无 Skill](agent_uplift/QWEN_NO_SKILL_PROMPT.md)
- [主机版：有 Skill](agent_uplift/QWEN_WITH_SKILL_PROMPT.md)
- [Docker 版：无 Skill](agent_uplift/QWEN_NO_SKILL_DOCKER_PROMPT.md)
- [Docker 版：有 Skill](agent_uplift/QWEN_WITH_SKILL_DOCKER_PROMPT.md)

Prompt 会自行下载仓库和数据、运行公开 scorer 并生成可回收 manifest；Docker 版还会准备镜像。不要从 README 复制过期副本；完整协议、正式三次重复要求和 Docker 文件位置见 [`agent_uplift/DOCKER_UPLIFT.md`](agent_uplift/DOCKER_UPLIFT.md)。主机版与 Docker 版必须分别统计，不能混合计算中位数。

Agent 只能看到 `agent_uplift/` 的公开任务；有 Skill 组额外看到一个 Skill。`stage_benchmark/`、`reference_implementation/`、gold 和历史结果必须隔离。单次联调不能宣称正式 uplift。
