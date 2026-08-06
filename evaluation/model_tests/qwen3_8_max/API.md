# Qwen3.8-Max 测试 API 接口

本文中的“Qwen3.8”按阿里云百炼当前正式模型 ID **`qwen3.8-max`** 处理。测试运行器只依赖 OpenAI 兼容的 Chat Completions 和原生 tool calls。

## 1. 接口地址

```http
POST {QWEN_BASE_URL}/chat/completions
Authorization: Bearer {QWEN_API_KEY}
Content-Type: application/json
```

`QWEN_BASE_URL` 应包含 `/v1`，不要再附加 `/chat/completions`；运行器也兼容直接传入完整接口地址。

| 地域 | `QWEN_BASE_URL` | `QWEN_MODEL` |
|---|---|---|
| 阿里云百炼北京 | `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` | `qwen3.8-max` |
| 阿里云百炼新加坡 | `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` | `qwen3.8-max`（以控制台实际可用性为准） |

密钥只从环境变量读取，不写入参数、报告或 Git。

## 2. 最小对话请求

```bash
curl "$QWEN_BASE_URL/chat/completions" \
  -H "Authorization: Bearer $QWEN_API_KEY" \
  -H 'Content-Type: application/json' \
  -d "$(python3 - <<'PY'
import json, os
print(json.dumps({
    'model': os.environ['QWEN_MODEL'],
    'messages': [{'role': 'user', 'content': '只回复 QWEN_API_OK'}],
    'temperature': 0.6,
    'max_completion_tokens': 512,
    'reasoning_effort': 'low',
    'preserve_thinking': True
}))
PY
)"
```

核心请求字段：

| 字段 | 类型 | 用途 |
|---|---|---|
| `model` | string | 本测试固定为 `qwen3.8-max` |
| `messages` | array | `system`、`user`、`assistant`、`tool` 多轮消息 |
| `tools` | array | OpenAI function tool 定义；正式文件评测必需 |
| `tool_choice` | string | 本运行器使用 `auto` |
| `temperature` / `top_p` | number | 必须在 B0/S0 之间固定；官方建议只调整其中一个 |
| `seed` | integer | 作为配对指纹的一部分；服务端不保证跨后端完全等价 |
| `max_completion_tokens` | integer | 单次完整输出上限，包含思维链和回答 |
| `reasoning_effort` | string | Qwen3.8-Max 可用 `low`、`medium`、`xhigh` |
| `preserve_thinking` | boolean | 本运行器固定为 `true`，保证多步工具调用连续性 |

Qwen3.8-Max 在 `preserve_thinking=true` 时要求历史 assistant 消息中的 `reasoning_content` 原样回传。运行器会保留它，但不会在普通终端输出中展示；它会计入后续输入 Token。

## 3. 工具调用约定

运行器向模型注册一个工具：

```json
{
  "type": "function",
  "function": {
    "name": "run_in_benchmark_sandbox",
    "parameters": {
      "type": "object",
      "properties": {
        "command": {"type": "string"}
      },
      "required": ["command"],
      "additionalProperties": false
    }
  }
}
```

服务端应返回原生 OpenAI 形状的 `tool_calls`：

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [{
        "id": "call_1",
        "type": "function",
        "function": {
          "name": "run_in_benchmark_sandbox",
          "arguments": "{\"command\":\"ls -R /model_input\"}"
        }
      }]
    }
  }]
}
```

运行器执行后把结果作为 `role=tool` 和相同 `tool_call_id` 回传，直到模型不再调用工具或达到 `--max-tool-calls`。

## 4. 运行器输出接口

一次运行在 `run_root` 下生成：

```text
model_input/                 仅当前题的安全输入
submission/artifacts/       候选模型的十个固定产物
agent_transcript.json       模型与工具事件，不含 API key
objective_report.json       确定性 checker 证据
score.json                  E1 六维分数；缺 LLM/静态证据时为 partial
run_record.json             可供 campaign 汇总的运行记录
*.log                       Agent、checker 和 scorer 日志
```

进程退出码遵循 E1：`0` 成功，`70` runner/API 错误，`73` 环境无效，`74` 产物缺失或格式无效，`75` scorer 错误。

## 5. 常见错误

- 只有普通文本、没有结构化 `message.tool_calls`：模型未按 Function Calling 返回，先运行 API probe 排查。
- HTTP 401/403：API key、WorkspaceId 或地域不匹配。
- HTTP 404：`QWEN_BASE_URL` 已错误包含了其他资源路径。
- Q01 能对话但运行器无产物：通过了 chat-only 检查，没有通过工具调用检查。
- `score_status=partial`：只生成了客观 checker 分；还未提供冻结的 LLM grader 与静态评审证据。

## 6. 官方接口依据

- [百炼 OpenAI 兼容 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [百炼文本生成模型列表](https://help.aliyun.com/zh/model-studio/text-generation-model)
