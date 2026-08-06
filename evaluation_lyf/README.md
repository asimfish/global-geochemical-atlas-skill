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
