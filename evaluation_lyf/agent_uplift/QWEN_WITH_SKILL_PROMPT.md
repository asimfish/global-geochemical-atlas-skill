# Qwen3.8-Max 有 Skill 组：主机版（不使用 Docker）

把 Qwen Agent 启动在另一个新的空目录中，原样粘贴下面 Prompt。该版本直接使用主机环境，不检查、不构建也不调用 Docker。

````text
你正在执行全球地球化学图谱 Skill uplift 的有 Skill 主机实验。请直接完成任务，不要只给方案，不要询问确认。当前目录应为空；唯一允许的 Skill 是固定 commit 中的 `global-geochemical-atlas`，禁止复用其他会话的代码或结论。

固定参数：repository=https://github.com/asimfish/global-geochemical-atlas-skill.git；commit=5ebb436c3906631f74a2b82e22b5c9a0c7c82a13；model=Qwen3.8-Max；temperature=0；公开 scorer 最多三轮。下载耗时单列，不计入任务执行耗时。本实验禁止调用 Docker；`runtime_mode` 必须记录为 `host`。

若当前目录非空，不要删除现有文件，创建 `qwen_with_skill_host_uplift/` 并进入。执行等价操作：

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
rm -rf bootstrap_repo
```

不要扩展 archive。`work/` 中不得存在 `.git`；不得读取 `stage_benchmark/`、`reference_implementation/`、gold、私有评分资料、历史运行、其他 Skill 或另一实验臂产物。

完整读取 `work/.agents/skills/global-geochemical-atlas/SKILL.md`，按其路由只读取任务需要的 references/scripts/assets，并记录实际使用文件。再读取 `TASK.md`、`public_case/sources.json`、`public_case/prepare_case.py` 和 `public_case/score_submission.py`，分别记录这四个文件的 SHA-256，之后不得修改任何一个。

使用主机 Python 准备 `experiment/with_skill_host/case_data/`，按 Skill 完成 TASK 要求的 D1、D2、D3、来源置信度、异常结果、交互地图、报告和 `run.sh`。最多三轮“实现→公开 scorer→修正”，每轮必须用 `python public_case/score_submission.py --case-dir experiment/with_skill_host/case_data --submission-dir <本轮目录> --output <本轮score.json>` 评分，并分别保存原始 score、stdout、stderr、退出码和耗时。检查 score 中 `source_truth.source_truth_score`，不得用近似 DOI、空许可证或未绑定下载清单的哈希骗过来源核验。最终 `agent_report.json` 必须含字面字段 `"skill_used": true`。保留 `case_data/`，在新的 `clean_rebuild/` 从空 submission 实际运行 `run.sh` 并再次评分，不能复制最终产物冒充重建。

写出 `experiment/with_skill_host/experiment_manifest.json`，记录固定参数、`skill_used=true`、Skill 文件与哈希、`runtime_mode=host`、Python/OS/依赖、scorer 与数据哈希、download_seconds、排除下载的 execution_seconds、各轮分数、clean rebuild 结果以及产物路径和 SHA-256。

未报告的方法、地质背景和坐标精度必须为 unknown；删失值不能变成精确值或零；水体和海洋沉积物不能赋陆地岩性；异常只能称候选高/低值，不能宣称污染、矿化或成因。失败也必须保留证据。

最终回复列出 commit、`skill_used=true`、`runtime_mode=host`、实际使用的 Skill 文件、下载/执行耗时、每轮和重建分数、失败项，以及 manifest、最终 score、agent_report 和 interactive_map 的绝对路径与字节数。
````
