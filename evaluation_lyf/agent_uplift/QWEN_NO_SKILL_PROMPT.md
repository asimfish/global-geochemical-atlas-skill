# Qwen3.8-Max 无 Skill 组：空目录直接粘贴 Prompt

下面代码块是完整 Prompt。把 Qwen Agent 启动在一个新的空目录中，然后原样粘贴；不要预先克隆仓库、下载数据或安装 Skill。

````text
你正在执行全球地球化学图谱 Skill uplift 的无 Skill 对照实验。请直接动手完成，不要只给方案，不要询问确认；遇到非破坏性问题自行诊断并继续。当前目录应为空。本组禁止读取、安装、搜索或使用任何 Agent Skill，也禁止复用其他会话的代码或结论。

固定实验参数（不可改）：

- repository: https://github.com/asimfish/global-geochemical-atlas-skill.git
- commit: 5ebb436c3906631f74a2b82e22b5c9a0c7c82a13
- model: Qwen3.8-Max
- temperature=0
- 资源：2 CPU、4 GB 内存、256 PIDs、单次任务 900 秒
- 公开 scorer 最多三轮；下载数据的时间单独记录，不计入任务执行耗时

先确认当前目录没有用户文件；若非空，不要删除任何现有内容，而是在当前目录中新建唯一的 `qwen_no_skill_uplift/` 并进入。随后执行等价于以下步骤的操作，记录每个命令、退出码和耗时：

```bash
git clone --filter=blob:none --no-checkout \
  https://github.com/asimfish/global-geochemical-atlas-skill.git bootstrap_repo
git -C bootstrap_repo checkout --detach 5ebb436c3906631f74a2b82e22b5c9a0c7c82a13
test "$(git -C bootstrap_repo rev-parse HEAD)" = "5ebb436c3906631f74a2b82e22b5c9a0c7c82a13"
mkdir work
git -C bootstrap_repo archive 5ebb436c3906631f74a2b82e22b5c9a0c7c82a13 \
  evaluation_lyf/agent_uplift | tar -x -C work
```

不要扩展上述 archive 范围。`work/` 中不得存在 `.git` 或 `skills/`。你可以在删除 bootstrap 前读取 `bootstrap_repo/evaluation/docker/Dockerfile` 并用它准备执行镜像，但不得读取 bootstrap 中的 Skill、`evaluation_lyf/stage_benchmark/`、`evaluation_lyf/reference_implementation/`、gold、评分私有材料、历史运行结果或其他实验臂产物。

优先使用 Docker 统一执行环境：

1. 检查 Docker daemon 是否可用，并记录 `docker version`；
2. 若本机已有 `global-geochemical-eval:local`，记录 image ID 并复用；否则若有兼容缓存镜像 `global-geochemical-eval:test`，记录偏差后复用；否则从 `bootstrap_repo/evaluation/docker/Dockerfile` 构建 `global-geochemical-eval:local`。构建时可调用 `python3 bootstrap_repo/evaluation/docker/campaign.py build-image --image global-geochemical-eval:local`；
3. 运行任务脚本时使用该镜像，挂载 `work` 到 `/workspace`，设置工作目录 `/workspace/evaluation_lyf/agent_uplift`，使用 `--user "$(id -u):$(id -g)"` 保证只写入这份自建工作区，并施加 `--cpus 2 --memory 4g --pids-limit 256 --read-only --tmpfs /tmp:rw,nosuid,nodev --cap-drop ALL --security-opt no-new-privileges`；数据下载阶段允许默认 bridge 网络，下载完成后的实现、评分和重建优先使用 `--network none`；
4. 如果 Docker daemon、镜像构建或挂载因宿主环境问题确实不可用，允许使用主机 Python 完成诊断运行，但必须把 `runtime_mode=host_fallback`、完整错误和环境偏差写入 manifest。这类结果不能冒充正式 Docker 对照结果。

镜像准备好后，只删除你刚创建的 bootstrap：

```bash
rm -rf bootstrap_repo
```

然后把所有工作限制在 `work/evaluation_lyf/agent_uplift/`。先完整读取 `TASK.md`、`public_case/sources.json` 和两个公开脚本。验证 `public_case/score_submission.py` 的 SHA-256 并记录，之后不得修改 scorer。禁止查看任何 Skill 或私有基准资料。

在 `experiment/no_skill/` 中完成以下全流程：

1. 运行 `public_case/prepare_case.py --output-dir experiment/no_skill/case_data` 获取固定公开数据，记录来源、文件哈希、下载开始/结束时间与 `download_seconds`；
2. 只依赖 Qwen3.8-Max 自身知识、`TASK.md` 和公开数据现场实现。生成 `submission/` 所要求的 D1、D2、D3、来源置信度、异常结果、交互地图、报告和 `run.sh`；
3. 按公开接口运行 `public_case/score_submission.py`。最多三轮“实现→评分→修正”，把每轮 stdout/stderr、退出码、耗时、原始 `score.json` 分别保存为 `score-round-1.json` 至 `score-round-3.json`，不得覆盖或美化失败证据；
4. 最终 `agent_report.json` 必须含有字面字段 `"skill_used": false`，并明确模型、commit、Docker image ID、资源、网络、下载耗时、执行耗时、每轮分数、失败案例和科学边界；
5. 做干净重建：保留只读 `case_data/`，新建 `clean_rebuild/`，复制实现文件和 `run.sh`，从空 submission 实际运行 `run.sh`，再用未修改 scorer 评分。比较原始与重建关键文件哈希，并保留重建 stdout/stderr、退出码和分数；不要用复制最终 submission 冒充重建；
6. 在 `experiment/no_skill/experiment_manifest.json` 写入至少：`protocol_version`、repository、commit、model、temperature、`skill_used=false`、runtime_mode、Docker version/image ID、CPU/内存/PID/timeout、网络模式、scorer SHA-256、数据文件 SHA-256、download_seconds、排除下载的 execution_seconds、每轮分数、clean_rebuild 结果、全部产物路径和 SHA-256。

科学失败边界：来源未报告的分析方法、地质背景、坐标精度必须为显式 unknown；删失值不得当作精确值或零；水体和明确海洋沉积物不得赋陆地岩性；异常只可称候选高/低值，不得写成污染、矿化或成因结论。失败也必须原样保留产物并解释。

完成后先自行检查：固定 commit 一致、`work` 无 `.git`/`skills`、scorer 哈希未变、轮次不超过三次、`run.sh` 真正执行、manifest 可被 JSON 解析。最终回复只做结果交接，列出 runtime_mode、commit、`skill_used=false`、下载耗时、执行耗时、各轮与干净重建分数、失败项，以及 `experiment_manifest.json`、最终 `score.json`、`agent_report.md`、`interactive_map.html` 的绝对路径和字节数。不要只说“已完成”。
````
