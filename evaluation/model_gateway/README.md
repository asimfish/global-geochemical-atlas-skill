# Docker 模型网关验证

本目录把赛事模型要求落实为一个独立的 Docker smoke。它不改变 Public Q01–Q08 的离线包校验；`run_docker_validation.sh` 仍使用 `--network none`。模型 smoke 使用一对容器：候选 worker 只连接内部 Docker 网络，唯一能访问公网的是只允许两个赛事域名的 Squid 代理。

## 冻结配置

| 项目 | 值 |
|---|---|
| 评测 Gateway | `https://ai.chipcloud.cc` |
| Anthropic Base URL | `https://token-plan.cn-beijing.maas.aliyuncs.com/apps/anthropic` |
| 首选模型 | `qwen3.8-max` |
| 多模态备用 | `qwen3-vl-plus` |
| 纯文本备用 | `glm-5.2` |
| 文生图备用 | `wan2.7-image-pro` |
| 被替换模型 | `K3`（禁用） |
| 备用启用条件 | 仅官方首选服务不可用，且必须由操作员显式确认 |
| OpenCode | 原生 `opencode-ai@1.18.14` |
| API 协议 | Anthropic-compatible Messages |
| Temperature | `0.6` |
| Thinking | `disabled` |
| 第一轮 | 先 2 次，再 16 次；每次全新会话 |

`opencode.json` 将 `qwen3.8-max` 固定为默认模型，没有自动降级逻辑。HTTP 400/401/403/404/429、TLS 验证失败、无效响应都不属于“官方服务不可用”，不能借此切换备用。仅 502/503/504 或重试后的连接超时可进入人工确认流程。

Anthropic 兼容端点只提供 Messages API，不提供 `/v1/models`；Base URL 末尾不要添加 `/v1`。`wan2.7-image-pro` 不是 Messages 模型，因此只登记在评审路由策略中，必须由赛事提供的图像生成路由调用，不能硬塞入 OpenCode 的 Anthropic provider。

## 无凭据验证（默认）

```bash
cd /home/ubuntu/global-geochemical-atlas-skill/evaluation
bash tools/run_model_gateway_validation.sh
```

该命令会构建固定 OpenCode 版本的 worker 和白名单代理，然后验证：

- Gateway 与 Qwen Base URL 的 DNS、TLS 和 HTTP 连通性；
- TLS 证书必须通过系统 CA 校验，禁止 `-k`；
- `example.com` 等非白名单域名被代理拒绝；
- worker 为 2 CPU、4 GiB、无额外 swap、256 PID、无 GPU、只读根文件系统；
- worker 只有内部网络，不能绕过代理直连公网；
- 主模型、备用模型、K3 替换规则和 12 小时上限未漂移；
- Docker inspect 中不存在 API Key。

成功标志为：

```text
PASS: Docker model gateway probe (qwen3.8-max)
```

## 使用 OpenCode 调用首选模型

Token Plan Key 不写入仓库、不放进命令行参数，也不作为 Docker 环境变量传入。先在宿主机准备权限为 `600` 的密钥文件，再执行：

```bash
cd /home/ubuntu/global-geochemical-atlas-skill/evaluation
bash tools/run_model_gateway_validation.sh \
  --invoke-primary \
  --api-key-file /home/ubuntu/.config/gga/qwen_api_key
```

脚本把文件只读挂载到 `/run/secrets/qwen_api_key`，容器入口只在 OpenCode 子进程启动前读取。证据和 `docker inspect` 不记录密钥内容。

阿里云 Token Plan 的官方使用范围要求通过 AI 编程工具或 OpenClaw 类 Agent 接入，禁止把套餐 Key 用于普通自写 API 测试程序。因此带凭据验证由 OpenCode CLI 发起；Python probe 永远不读取密钥。

OpenCode 配置同时在 `gateway-smoke` agent 和三个可对话模型上冻结参数。agent 提供 `temperature=0.6`；provider model options 提供 `thinking.type=disabled`。这样不会依赖 Qwen 的默认采样值或默认思考开关。

## 第一轮 2 + 16 次

服务器准备好 Key 文件后，运行完整第一轮：

```bash
cd /home/ubuntu/global-geochemical-atlas-skill/evaluation
bash tools/run_model_gateway_batch.sh \
  --api-key-file /home/ubuntu/.config/gga/qwen_api_key
```

执行顺序固定为：

1. stage-2：2 次独立 `opencode run`；
2. stage-16：16 次独立 `opencode run`。

总计 18 个全新 OpenCode 会话，不复用历史上下文。首个 repeat 构建镜像，后续 repeat 复用相同镜像。整个批次共享一个 43200 秒硬截止时间；失败立即停止，不会自动改用备用模型。证据默认写入：

```text
/home/ubuntu/evaluation-test-evidence/model-batch-<UTC时间>/
```

## 启用备用模型

只有已经确认首选模型的官方服务不可用时，才允许显式运行备用：

```bash
# 纯文本备用
bash tools/run_model_gateway_validation.sh \
  --invoke-fallback glm-5.2 \
  --confirm-primary-unavailable \
  --api-key-file /home/ubuntu/.config/gga/qwen_api_key

# 多模态理解备用（这里只做文本级最小连通 smoke）
bash tools/run_model_gateway_validation.sh \
  --invoke-fallback qwen3-vl-plus \
  --confirm-primary-unavailable \
  --api-key-file /home/ubuntu/.config/gga/qwen_api_key
```

不带 `--confirm-primary-unavailable` 时脚本 fail closed。该开关是人工确认，不会把认证失败、额度限制或配置错误错误地解释为服务不可用。

## 证据

默认证据目录为：

```text
/home/ubuntu/evaluation-test-evidence/model-gateway-<UTC时间>/
```

其中包含 worker/proxy 镜像 inspect、容器 inspect、两个网络 inspect、构建日志、运行日志、资源合同、运行摘要和 `SHA256SUMS`。验证完整性：

```bash
cd /home/ubuntu/evaluation-test-evidence/model-gateway-<UTC时间>
sha256sum -c SHA256SUMS
```

### bjzgcUbuntu 已验证结果

2026-08-07（HKT）已完成无凭据双容器 probe：

```text
policy_validation=PASS
opencode_version=1.18.14
opencode_config=PASS
opencode_models=qwen3.8-max,qwen3-vl-plus,glm-5.2
gateway_http_status=200
qwen_base_http_status=404
tls_verification=PASS
non_allowlisted_egress=BLOCKED
primary_model=qwen3.8-max
temperature=0.6
thinking=disabled
first_round_stage_repeats=2,16
resource_contract=PASS
status=PASS
```

Qwen Base URL 的 404 是预期结果：Anthropic 兼容端点只提供 `/v1/messages`，不提供根资源或 `/v1/models`。该结果与 TLS/网络失败不同。证据目录为：

```text
/home/ubuntu/evaluation-test-evidence/model-gateway-opencode-1.18.14-r3
```

目录内 `SHA256SUMS` 已再次执行 `sha256sum -c` 并全部通过。当前服务器尚无 `/home/ubuntu/.config/gga/qwen_api_key`，因此 2+16 次真实模型调用未启动，不能把无凭据 probe 表述为模型输出验证。

## 官方依据

- [阿里云：接入更多编程工具](https://help.aliyun.com/zh/model-studio/more-tools)
- [阿里云：Anthropic-compatible Messages API](https://help.aliyun.com/en/model-studio/anthropic-api-messages)
- [阿里云：Token Plan 个人版支持模型](https://help.aliyun.com/zh/model-studio/token-plan-personal-overview)
- [OpenCode：Provider 与自定义 Base URL](https://opencode.ai/docs/providers)
- [OpenCode：配置文件与密钥替换](https://opencode.ai/docs/config)
