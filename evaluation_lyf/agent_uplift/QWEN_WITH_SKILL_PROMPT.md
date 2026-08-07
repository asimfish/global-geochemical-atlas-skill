# Qwen3.8-Max 有 Skill 组：主机正式运行入口

不要把完整仓库交给候选 Agent。本文件是外部实验控制器说明；候选实际只读取导出后的 `AGENT_PROMPT.md`。

固定参数：repository=`https://github.com/asimfish/global-geochemical-atlas-skill.git`；
commit=`7538b156bb719f45b478b7e4997e04a49084ebe7`；model=`Qwen3.8-Max`；temperature=0；
`runtime_mode=host`；`skill_used=true`。主机版不使用 Docker，禁止候选调用 Docker。

```bash
git clone --filter=blob:none --no-checkout \
  https://github.com/asimfish/global-geochemical-atlas-skill.git controller_repo
git -C controller_repo checkout --detach 7538b156bb719f45b478b7e4997e04a49084ebe7

python3 controller_repo/evaluation_lyf/agent_uplift/export_candidate_bundle.py \
  --repo-root controller_repo \
  --condition S0 \
  --mode formal \
  --prompt controller_repo/evaluation_lyf/agent_uplift/candidate_prompts/HOST_S0.md \
  --output candidate_S0_host
```

然后在另一个全新 Qwen3.8-Max 会话中把工作目录设为 `candidate_S0_host/`，原样提供 `AGENT_PROMPT.md`。
S0 bundle 相比 B0 只额外包含 `.agents/skills/global-geochemical-atlas/SKILL.md` 及其路由资源。候选不得看
controller_repo、公开 scorer、隐藏 checker、rubric、gold、其他 Skill、历史运行或另一实验臂。

候选退出后，由控制器运行来源真实性门禁、真实 Chromium、带 `--browser-audit` 的 scorer 和统一报告。正式
实验创建三个全新 S0 会话，并与三个 B0 报告交给 `evaluation/reporting/aggregate_uplift.py`。公开 scorer 最多
三轮仅用于 development bundle。用控制器侧 `evaluation/reporting/build_experiment_manifest.py
--expected-commit <上述固定 commit>` 生成而非接受
候选写入的 `experiment_manifest.json`；记录 Skill 文件/hash、发现清单、clean rebuild、截图和所有产物哈希。

只处理四个固定地球化学锚点属于未完成 D1；TASK 要求有界多平台发现。检查最终 score 的 anchors、discovered、
overall 三个 source_truth 分数。下载传输耗时单列，来源规划、解析和处理属于 execution_seconds。
