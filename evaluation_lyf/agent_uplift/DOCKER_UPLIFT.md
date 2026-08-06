# Qwen Skill uplift：零准备 Docker 测试

这不是第三套评分体系。仓库只有两类评测内容，Docker 是它们共用的执行底座：

| 层次 | 用途 | 入口 |
|---|---|---|
| Skill 内部回归 | D1/D2/D3 接口和最小端到端回归 | `skills/global-geochemical-atlas/scripts/component_test.py`、`self_test.py` |
| `evaluation/` | Q01–Q24、B0/S0、E1 十产物和六维评分证据 | `evaluation/README.md` |
| `evaluation_lyf/stage_benchmark/` | D1/D2/D3 独立科学门禁和压力测试 | `evaluation_lyf/README.md` |
| `evaluation_lyf/agent_uplift/` | 公开真实数据上的 Qwen 有/无 Skill 对照 | 本文 |
| `evaluation/docker/` | 为上述评测提供冻结镜像、隔离、OpenCode 和 campaign runner | `evaluation/docs/docker_usage.md` |

## 你实际要做的事

1. 创建两个空目录，并分别把 Qwen Agent 启动在目录中；
2. 无 Skill 目录原样粘贴 [`QWEN_NO_SKILL_DOCKER_PROMPT.md`](QWEN_NO_SKILL_DOCKER_PROMPT.md)；
3. 有 Skill 目录原样粘贴 [`QWEN_WITH_SKILL_DOCKER_PROMPT.md`](QWEN_WITH_SKILL_DOCKER_PROMPT.md)；
4. 回收两个目录的 `experiment_manifest.json`、`score.json` 和 submission。

Prompt 会自行克隆固定 commit、构建或复用评测镜像、准备公开数据、完成任务、最多运行三轮公开 scorer，最后执行一次干净重建。用户无需预先下载仓库或 Skill。固定实验参数见 [`experiment_config.json`](experiment_config.json)。

如果要保留原来的主机直跑方式，使用 [`QWEN_NO_SKILL_PROMPT.md`](QWEN_NO_SKILL_PROMPT.md) 和 [`QWEN_WITH_SKILL_PROMPT.md`](QWEN_WITH_SKILL_PROMPT.md)。主机结果与 Docker 结果属于不同 runtime profile，不能混在同一个三次中位数中。

正式结果每个实验臂应开三个新的隔离会话，分别运行一次，并用三次最终分数的中位数比较。单次运行只适合联调。两个实验臂必须使用相同主机、模型服务版本、资源、网络和 commit；唯一自变量是 `global-geochemical-atlas` Skill 是否可见。

## Docker 文件在哪里

```text
evaluation/docker/
├── Dockerfile                         # 固定 OpenCode 与科学 Python 环境
├── compose.yaml                       # 手工调试候选容器与白名单代理
├── campaign.py                        # 构建、B0/S0 campaign、stage 统一入口
├── preflight.py                       # L0/L1 确定性预检
├── allowlist.txt                      # 允许访问的科学数据域名
├── requirements-sandbox.txt           # 容器科学依赖
├── container/
│   ├── run_opencode.py                # OpenCode 候选入口
│   ├── mock_agent.py                  # runner 冒烟入口，不代表模型成绩
│   └── allowlist_proxy.py             # 受控联网出口
└── tests/                              # Docker 控制器单元测试
```

Docker runner 的标准构建、mock smoke、D1/D2/D3 stage 和正式 OpenCode campaign 命令统一见 [`../../evaluation/docs/docker_usage.md`](../../evaluation/docs/docker_usage.md)。

## 公平性与失败关闭

- 无 Skill 组通过 `git archive` 只导出公开 uplift 任务，不把 `.git` 或 `skills/` 带进工作目录；
- 有 Skill 组只额外导出一个 Skill，并映射到 `.agents/skills/global-geochemical-atlas/`；
- `stage_benchmark/`、`reference_implementation/`、gold、历史运行和另一实验臂的产物都不可见；
- 下载耗时与任务执行耗时分开记录；Docker 不可用时允许主机诊断回退，但必须在 manifest 中记为环境偏差，不能与 Docker 正式结果混算；
- scorer 最多运行三轮，每轮分数原样留存，不得修改 scorer；
- `run.sh` 必须从保留的 `case_data/` 在新目录中重建全部产物，重建失败仍保留证据。

CI 中的 `test_prompt_contract.py` 检查主机版与 Docker 版四份 Prompt 的固定参数、隔离命令和文件入口没有漂移，不替代真实 Qwen 调用。
