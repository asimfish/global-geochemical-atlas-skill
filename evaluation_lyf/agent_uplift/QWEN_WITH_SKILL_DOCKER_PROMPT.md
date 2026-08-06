# Qwen3.8-Max 有 Skill 组：零准备 Docker Prompt

下面代码块是完整 Prompt。把 Qwen Agent 启动在另一个新的空目录中，然后原样粘贴；不要预先克隆仓库、下载数据或安装 Skill。

````text
你正在执行全球地球化学图谱 Skill uplift 的有 Skill Docker 实验。请直接动手完成，不要只给方案，不要询问确认；遇到非破坏性问题自行诊断并继续。当前目录应为空。本组只允许使用指定 commit 中的 `global-geochemical-atlas` Agent Skill，禁止复用其他会话的代码或结论。

固定实验参数（不可改）：

- repository: https://github.com/asimfish/global-geochemical-atlas-skill.git
- commit: 5ebb436c3906631f74a2b82e22b5c9a0c7c82a13
- model: Qwen3.8-Max
- temperature=0
- 资源：2 CPU、4 GB 内存、256 PIDs、单次任务 900 秒
- 公开 scorer 最多三轮；下载数据的时间单独记录，不计入任务执行耗时

先确认当前目录没有用户文件；若非空，不要删除任何现有内容，而是在当前目录中新建唯一的 `qwen_with_skill_docker_uplift/` 并进入。随后执行等价于以下步骤的操作，记录每个命令、退出码和耗时：

```bash
git clone --filter=blob:none --no-checkout \
  https://github.com/asimfish/global-geochemical-atlas-skill.git bootstrap_repo
git -C bootstrap_repo checkout --detach 5ebb436c3906631f74a2b82e22b5c9a0c7c82a13
test "$(git -C bootstrap_repo rev-parse HEAD)" = "5ebb436c3906631f74a2b82e22b5c9a0c7c82a13"
mkdir work
git -C bootstrap_repo archive 5ebb436c3906631f74a2b82e22b5c9a0c7c82a13 \
  evaluation_lyf/agent_uplift skills/global-geochemical-atlas | tar -x -C work
mkdir -p work/.agents/skills
mv work/skills/global-geochemical-atlas work/.agents/skills/global-geochemical-atlas
rmdir work/skills
```

不要扩展上述 archive 范围。`work/` 中不得存在 `.git`。你可以在删除 bootstrap 前读取 `bootstrap_repo/evaluation/docker/Dockerfile` 并用它准备执行镜像，但不得读取 bootstrap 中的 `stage_benchmark/`、`reference_implementation/`、gold、评分私有材料、历史运行、其他 Skill 或另一实验臂产物。

优先使用 Docker 统一执行环境：

1. 检查 Docker daemon 是否可用，并记录 `docker version`；
2. 若本机已有 `global-geochemical-eval:local`，记录 image ID 并复用；否则若有兼容缓存镜像 `global-geochemical-eval:test`，记录偏差后复用；否则调用 `python3 bootstrap_repo/evaluation/docker/campaign.py build-image --image global-geochemical-eval:local` 构建；
3. 运行任务脚本时挂载 `work` 到 `/workspace`，工作目录设为 `/workspace/evaluation_lyf/agent_uplift`，使用 `--user "$(id -u):$(id -g)" --cpus 2 --memory 4g --pids-limit 256 --read-only --tmpfs /tmp:rw,nosuid,nodev --cap-drop ALL --security-opt no-new-privileges`，并把 `work/.agents/skills/global-geochemical-atlas` 只读挂载到容器内同一路径；下载阶段允许 bridge，之后优先 `--network none`；
4. Docker 确实不可用时允许主机诊断回退，但必须把 `runtime_mode=host_fallback`、完整错误和环境偏差写入 manifest，且不得与正式 Docker 结果混算。

镜像准备好后，只删除你刚创建的 bootstrap：

```bash
rm -rf bootstrap_repo
```

完整读取 `work/.agents/skills/global-geochemical-atlas/SKILL.md`，按其路由只读取本任务所需 references/scripts/assets，并记录实际使用文件。再读取 `TASK.md`、`public_case/sources.json`、`public_case/prepare_case.py` 和 `public_case/score_submission.py`；记录 scorer SHA-256，之后不得修改。

在 `experiment/with_skill_docker/` 中完成全流程：准备固定公开数据；按 Skill 执行全部交付；最多进行三轮公开 scorer；每轮保存独立 score、日志、退出码和耗时；`agent_report.json` 必须包含字面字段 `"skill_used": true`；从保留的 `case_data/` 在 `clean_rebuild/` 实际执行 `run.sh` 并重新评分，不能复制最终 submission 冒充重建。

写出 `experiment/with_skill_docker/experiment_manifest.json`，至少记录 repository、commit、model、temperature、`skill_used=true`、Skill 文件与哈希、`runtime_mode=docker` 或真实 fallback、Docker version/image ID、资源、网络、scorer 与数据哈希、download_seconds、排除下载的 execution_seconds、每轮分数、clean_rebuild 结果以及全部产物路径和 SHA-256。

科学失败边界：未报告的方法、地质背景和坐标精度必须为 unknown；删失值不得当作精确值或零；水体和海洋沉积物不得赋陆地岩性；异常只能称候选高/低值，不得声明污染、矿化或成因。失败也必须保留证据。

最终检查固定 commit、隔离边界、唯一 Skill、scorer 哈希、最多三轮、真实重建和 manifest。回复列出 runtime_mode、commit、`skill_used=true`、实际使用的 Skill 文件、下载/执行耗时、各轮与重建分数、失败项，以及 manifest、最终 score、agent_report 和 interactive_map 的绝对路径与字节数。
````
