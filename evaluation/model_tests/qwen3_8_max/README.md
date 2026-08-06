# Qwen3.8-Max Benchmark 测试准备

本目录把阿里云百炼 **Qwen3.8-Max**（模型 ID `qwen3.8-max`）接到 Global Geochemical Atlas Benchmark v6。它提供 API 连通性检查和真实文件产物运行器，不把普通聊天回复冒充 Benchmark 成绩。

## 能力与边界

- 支持阿里云百炼的 OpenAI 兼容 Chat Completions；
- 通过原生 tool calls 驱动一个无网络的 bubblewrap 沙箱；
- 模型只能读当前 `model_input/`，只能写 `submission/`；
- B0 不挂载 Skill，S0 只读挂载冻结 Skill；
- 每次运行后自动执行 `grade_task.py` 和 `finalize_score.py`；
- 未提供 LLM grader/static review 时，`score.json` 是可诊断的 `partial` 分数，不是完整赛事分数。

## 1. 配置百炼接口

```bash
export QWEN_BASE_URL=https://WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
export QWEN_API_KEY="$DASHSCOPE_API_KEY"
export QWEN_MODEL=qwen3.8-max
```

不要把真实密钥写入 `qwen_api_environment.example` 或提交到 Git。

## 2. 先做 API 检查

正式运行器依赖结构化 tool calls，因此默认同时检查对话和工具调用：

```bash
cd evaluation/model_tests/qwen3_8_max
python3 check_qwen_api.py
```

输出报告默认为 `/tmp/qwen3.8-max-api-smoke.json`。若只排查网络和鉴权，可临时运行 `python3 check_qwen_api.py --chat-only`；chat-only 通过不代表能执行 Benchmark。

## 3. 跑一题 B0 基线

从仓库根目录执行：

```bash
python3 evaluation/model_tests/qwen3_8_max/run_public_benchmark_task.py \
  --question Q01 \
  --variant B0 \
  --repeat 1 \
  --seed 4201 \
  --run-root /tmp/qwen3.8-max-q01-b0-r1
```

## 4. 跑同一题 S0 Skill 条件

S0 的模型、参数、输入、seed 和沙箱必须与对应 B0 相同；唯一差异是只读 Skill 挂载：

```bash
python3 evaluation/model_tests/qwen3_8_max/run_public_benchmark_task.py \
  --question Q01 \
  --variant S0 \
  --repeat 1 \
  --seed 4201 \
  --skill-dir skills/global-geochemical-atlas \
  --run-root /tmp/qwen3.8-max-q01-s0-r1
```

两个 `run_record.json` 的 `pair_fingerprint` 应完全相同。

## 5. 正式 Public 测试矩阵

先对 Q01 做一组 B0/S0 冒烟；确认产物、token 成本和工具稳定后，再执行 Q01–Q08。每题每个条件运行三次，共 `8 × 2 × 3 = 48` 次。配对运行可使用相同 repeat seed，例如：

```text
repeat 1 -> seed 4201
repeat 2 -> seed 4202
repeat 3 -> seed 4203
```

冻结并记录：模型 ID/服务版本、temperature、可选 top_p、max_completion_tokens、reasoning_effort、preserve_thinking、seed、system prompt、工具定义、Skill tree SHA-256、bubblewrap 与主机镜像。默认使用 `reasoning_effort=xhigh`；冒烟阶段可加 `--reasoning-effort low` 控制成本，但正式 B0/S0 必须保持完全一致。

## 6. 验收顺序

1. `check_qwen_api.py` 返回 0，报告包含 `benchmark_api_probe`；
2. `submission/artifacts/` 恰好有十个文件；
3. `run_record.json.exit_code=0`；
4. `objective_report.json` 无 scorer 异常，人工复核 redline；
5. 有冻结 LLM grader/static review 时，通过 `--llm-report` 和 `--static-review` 传入，获得完整六维分数；
6. B0/S0 各三次完成后，再用 `evaluation/tools/aggregate_runs.py` 聚合，不用单次结果宣称 uplift。

完整 HTTP 请求、响应和字段说明见 [API.md](API.md)。

官方依据：[百炼文本模型列表](https://help.aliyun.com/zh/model-studio/text-generation-model)将 `qwen3.8-max` 列为支持 1M 上下文和 Function Calling 的模型；[OpenAI 兼容 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)给出地域 endpoint、工具调用和 `reasoning_content` 回传要求。
