# Qwen3.8-Max 无 Skill 组：主机正式运行入口

不要把完整仓库交给候选 Agent。本文件是外部实验控制器说明；候选实际只读取导出后的 `AGENT_PROMPT.md`。

固定参数：repository=`https://github.com/asimfish/global-geochemical-atlas-skill.git`；
commit=`1b20c276e8515bcf632cb45efe9f500c587ed3bf`；model=`Qwen3.8-Max`；temperature=0；
`runtime_mode=host`；`skill_used=false`。主机版不使用 Docker，禁止候选调用 Docker。

```bash
git clone --filter=blob:none --no-checkout \
  https://github.com/asimfish/global-geochemical-atlas-skill.git controller_repo
git -C controller_repo checkout --detach 1b20c276e8515bcf632cb45efe9f500c587ed3bf

python3 controller_repo/evaluation_lyf/agent_uplift/export_candidate_bundle.py \
  --repo-root controller_repo \
  --condition B0 \
  --mode formal \
  --prompt controller_repo/evaluation_lyf/agent_uplift/candidate_prompts/HOST_B0.md \
  --output candidate_B0_host
```

然后在全新 Qwen3.8-Max 会话中把工作目录设为 `candidate_B0_host/`，原样提供 `AGENT_PROMPT.md`。候选不得看
controller_repo、公开 scorer、隐藏 checker、rubric、gold、Skill 或另一实验臂。正式 bundle 从第一秒完成隔离；
不再使用“候选先 checkout 再删除”的做法。

候选退出后，由控制器在候选不可见目录运行来源真实性门禁、`evaluation/reporting/browser_audit.py`、带
`--browser-audit` 的 `score_submission.py` 和 `evaluation/reporting/generate_report.py`。正式实验创建三个全新
B0 会话；公开 scorer 最多三轮只适用于另行导出的 development bundle。用控制器侧
`evaluation/reporting/build_experiment_manifest.py --expected-commit <上述固定 commit>` 生成而非接受候选写入的
`experiment_manifest.json`；保存
`case_data/discovered_manifest.json`、clean rebuild、浏览器截图、统一报告和所有 SHA-256。
三个 B0 与三个 S0 报告最终统一交给 `evaluation/reporting/aggregate_uplift.py`。

只处理四个固定地球化学锚点属于未完成 D1；TASK 要求有界多平台发现。检查最终 score 中
`source_truth.anchors.source_truth_score`、`source_truth.discovered.source_truth_score` 和
`source_truth.overall.source_truth_score`。下载传输耗时单列，来源规划、解析和处理属于 execution_seconds。
