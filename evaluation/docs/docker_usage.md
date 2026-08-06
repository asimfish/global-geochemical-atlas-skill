# Docker 统一评测指南

本仓库采用“一套 Docker 执行底座、两类评测入口”的结构：

- `evaluation_lyf/` 负责 D1/D2/D3 科学与工程门禁；
- `evaluation/` 负责比赛代理评测，即同题 B0（无 Skill）/S0（有 Skill）隔离执行、E1 十产物检查、六维证据计分和 uplift 汇总；
- `evaluation/docker/` 统一提供镜像、OpenCode 入口、网络白名单代理、L0/L1 预检和 campaign runner。

两套评测不会各自维护镜像，因此不会产生 OpenCode 版本、依赖或资源策略漂移。

Docker 实现集中在 [`evaluation/docker/`](../docker/)：`Dockerfile` 冻结环境，`campaign.py` 提供 build/run/stage，`container/` 提供 OpenCode、mock agent 与白名单代理，`tests/` 覆盖控制器契约。它是统一运行层，不是与 `evaluation`、`evaluation_lyf` 并列的第三套评分。只想在两个空目录里做 Qwen 有/无 Skill 对照时，直接使用 [`evaluation_lyf/agent_uplift/DOCKER_UPLIFT.md`](../../evaluation_lyf/agent_uplift/DOCKER_UPLIFT.md) 中的零准备流程。

## 1. 与比赛规则的对应关系

| 规则 | 本仓库实现 |
|---|---|
| L0 结构/安全初筛 | `preflight.py`：单 Skill、frontmatter、体积、密钥、引用与主题检查 |
| L1 静态审查 | preflight 生成冻结证据；原创性和独立模型审查明确保留为人工/外部 reviewer 项 |
| L2 运行与产物 | Docker 2 CPU、4 GB、无 GPU、900 秒、只读根文件系统、PID 限制、E1 十产物清单 |
| L3 质量评分 | 复用 Q01–Q24 checker、`finalize_score.py`、独立 LLM/static-review 报告接口 |
| B0/S0 uplift | 相同题面、镜像、模型、repeat、网络和资源；唯一差异是 S0 的只读 Skill 挂载 |
| 重复策略 | 主模型 B0/S0 各三次并取中位数；可选补充模型各一次，单独归档、不混入主聚合 |
| 数据下载不计时 | campaign 输入在运行前已打包；容器计时只覆盖 Agent 执行，元数据单列 `download_seconds` |
| 网络白名单 | candidate 仅接入 internal network；唯一出口是校验域名与公网解析地址的 CONNECT proxy |

当前 repo 内 Q01–Q24 是比赛契约的本地代理题，并非主办方隐藏题。runner 会把这一边界写进计划和记录，不把本地结果宣传为官方最终分。

## 2. 预检

从仓库根目录运行：

```bash
python3 evaluation/docker/preflight.py . \
  --output /tmp/gga-preflight.json
```

退出码：`0` 全自动检查通过；`2` 自动检查通过但仍有 L1/原创性人工复核；`74` 阻断失败；`73` 环境无效。`2` 不能改写成“全部通过”，但可以进入独立审查。

## 3. 构建冻结镜像

```bash
python3 evaluation/docker/campaign.py build-image \
  --image global-geochemical-eval:local
```

默认固定 Python `3.11.9-slim-bookworm`、OpenCode `1.18.14` 和科学 Python 依赖。构建结果输出 image ID，campaign 再次记录该 ID。受控离线主机可显式使用已有基础镜像：

```bash
python3 evaluation/docker/campaign.py build-image \
  --image global-geochemical-eval:local \
  --python-image python:3.12-slim \
  --no-pull
```

这只用于环境诊断；正式 campaign 应重新冻结并记录统一镜像。

## 4. Docker 冒烟测试

mock agent 仅验证隔离、资源参数和十产物管线，不代表模型能力成绩：

```bash
run_dir="$(mktemp -d -p /tmp gga-docker-smoke.XXXXXX)"
python3 evaluation/docker/campaign.py run \
  --image global-geochemical-eval:local \
  --agent mock \
  --network offline \
  --tasks Q01 \
  --conditions B0,S0 \
  --repeats 3 \
  --supplemental-model qwen3-vl-plus \
  --output-dir "$run_dir/campaign"
```

B0 的 `run_manifest.json.benchmark_evidence.skill_visible` 必须为 `false`，S0 必须为 `true`。完整三次运行还必须生成 `summary.json`。

## 5. D1/D2/D3 科学门禁

统一适配器保留 `evaluation_lyf` 的独立报告和失败边界：

```bash
python3 evaluation/docker/campaign.py stage \
  --image global-geochemical-eval:local \
  --suite isolated \
  --stress-records 10000 \
  --output-dir /tmp/gga-stage-isolated

python3 evaluation/docker/campaign.py stage \
  --image global-geochemical-eval:local \
  --suite all \
  --output-dir /tmp/gga-stage-all
```

stage 默认在同一冻结镜像中运行，repo 只读、结果目录可写，并使用与比赛 campaign 相同的 2 CPU/4 GB/PID/只读根策略。`--host` 仅用于诊断依赖问题。`--refresh-downloads` 必须配合 `--network whitelist`，并明确表示该次 stage 包含预下载，不应把其总时长当作 candidate runtime。正式 Docker campaign 使用已准备的当前题输入，因此记录 `download_seconds=0.0`。

## 6. OpenCode 主 campaign

网关必须兼容 OpenAI API，URL 使用 HTTPS。密钥只通过宿主环境继承，命令、计划和 JSON 均不写密钥值；runner 会在归档前清除日志中的密钥字节。若候选把密钥写入 submission，runner 会等长覆盖该值并以 E1 `74` 失败关闭：

```bash
export EVAL_API_KEY='从密钥管理器注入，不写入仓库'

python3 evaluation/docker/campaign.py run \
  --image global-geochemical-eval:local \
  --campaign-id qwen-main-v1 \
  --agent opencode \
  --network whitelist \
  --provider-base-url https://gateway.example/v1 \
  --api-key-env EVAL_API_KEY \
  --model qwen3.8-max \
  --temperature 0 \
  --supplemental-model qwen3-vl-plus \
  --tasks all \
  --conditions B0,S0 \
  --repeats 3 \
  --timeout-seconds 900 \
  --output-dir /runs/qwen-main-v1
```

网关 hostname 会自动加入本次 allowlist；科学数据域名来自 `allowlist.txt`，新增域名用重复的 `--allow-host` 显式声明。禁止使用 `--network host`。

若独立 grader 已为每次运行生成报告，可接入：

```bash
  --llm-report-dir /frozen/reviews \
  --static-review /frozen/static_review.json
```

每次 LLM 报告可命名为 `<run_id>.json`，或放在 `main/Q01/S0/repeat-1.json`（补充模型使用 `supplemental/`）。缺失报告时不补造分数，相关维度保持 `not_scored`/`partial`。

## 7. 证据目录

```text
campaign/
├── campaign_plan.json
├── campaign_result.json
├── runs.jsonl                  # 主模型 B0/S0 三次记录
├── supplemental_runs.jsonl    # 可选补充模型一次记录
├── summary.csv
├── summary.json
├── main/Q01/B0/repeat-1/
│   ├── task/                   # 本次候选可见输入快照
│   ├── workspace/
│   ├── submission/artifacts/   # E1 十产物
│   ├── candidate.stdout
│   ├── candidate.stderr
│   ├── runner_metadata.json
│   ├── objective_report.json
│   ├── score.json
│   └── run_record.json
└── supplemental/...
```

记录包含 task/Skill/产物哈希、镜像 ID、资源限制、原始退出码、E1 退出码、运行时长、网络模式和 provider hostname。grader 证据在 submission 外，避免污染候选交卷。

## 8. 失败关闭

- Docker daemon 或镜像缺失：`73 environment_invalid`；
- 超时：E1 `71`；OOM/137：E1 `72`；缺产物：E1 `74`；
- grader/finalizer 异常：生成 `ineligible` 分数，不把异常伪装成候选成功分；
- 完整 B0/S0 × 3 聚合失败：campaign 返回 `2`；
- proxy 只接受 allowlist hostname、80/443 端口和公网解析地址，IP literal、内网/环回地址及 DNS rebinding 结果均拒绝。

本地运行目录不得提交。每次正式 campaign 使用新的空输出目录，并保留原始日志和哈希证据。
