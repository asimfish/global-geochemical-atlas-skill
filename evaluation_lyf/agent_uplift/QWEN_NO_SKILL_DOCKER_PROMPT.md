# Qwen3.8-Max 无 Skill 组：Docker 正式运行入口

外部控制器先 checkout 固定 repository/commit，再构建 `evaluation/docker/Dockerfile`（CPU 2、memory 4g、
pids 256、timeout 900 秒），并在候选容器启动前运行：

```bash
python3 evaluation_lyf/agent_uplift/export_candidate_bundle.py \
  --repo-root . --condition B0 --mode formal \
  --prompt evaluation_lyf/agent_uplift/candidate_prompts/DOCKER_B0.md \
  --output candidate_B0_docker
```

固定：repository=`https://github.com/asimfish/global-geochemical-atlas-skill.git`，
commit=`7538b156bb719f45b478b7e4997e04a49084ebe7`，model=`Qwen3.8-Max`，temperature=0，
`runtime_mode=docker`，`skill_used=false`。把 bundle 只读挂载为候选初始目录；不得挂载完整仓库。原样提供
`AGENT_PROMPT.md`。候选不可见 `.git`、Skill、score_submission.py、checker、rubric、gold、历史或另一臂。

候选退出后控制器用 `evaluation/reporting/build_experiment_manifest.py --expected-commit <上述固定 commit>` 生成
候选不可写的实验 manifest，再运行
来源真实性门禁、真实 Chromium、带 `--browser-audit` 的 scorer 和统一报告。每臂三个新会话，同 pair
fingerprint；用 `aggregate_uplift.py` 聚合。公开 scorer 最多三轮仅限 development bundle。
只处理四个固定地球化学锚点属于未完成 D1；保存发现 manifest、clean_rebuild、截图和全部 SHA-256，并核对
`source_truth.anchors.source_truth_score`、`source_truth.discovered.source_truth_score`、
`source_truth.overall.source_truth_score`。
