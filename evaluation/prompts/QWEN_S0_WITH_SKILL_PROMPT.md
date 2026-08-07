# evaluation Q01–Q24：Qwen S0 有 Skill 手工 Prompt

把 Qwen/OpenCode Agent 启动在另一个新的空目录中，原样粘贴下面内容。该手工入口用于观察 S0 作答；正式计分仍应由 Docker campaign控制隔离与重复。

````text
你正在执行 Global Geochemical Atlas Benchmark Q01–Q24 的 S0 有 Skill 实验。请直接完成全部任务，不要只给方案，不要询问确认。当前目录应为空。唯一允许使用的 Agent Skill 是固定 commit 中的 `global-geochemical-atlas`；不得读取 checker、rubric、gold、私有评分资料或历史答案。

固定 repository=https://github.com/asimfish/global-geochemical-atlas-skill.git，commit=964e3fe45a7e96146e606057b76523f6246b6ac1，model=Qwen3.8-Max，temperature=0。

执行等价操作，只导出候选可见 bundle 和这一份 Skill：

```bash
git clone --filter=blob:none --no-checkout \
  https://github.com/asimfish/global-geochemical-atlas-skill.git bootstrap_repo
git -C bootstrap_repo checkout --detach 964e3fe45a7e96146e606057b76523f6246b6ac1
test "$(git -C bootstrap_repo rev-parse HEAD)" = "964e3fe45a7e96146e606057b76523f6246b6ac1"
mkdir candidate_bundle skill_export
git -C bootstrap_repo archive 964e3fe45a7e96146e606057b76523f6246b6ac1 \
  evaluation/ai_visible_public | tar -x -C candidate_bundle --strip-components=2
git -C bootstrap_repo archive 964e3fe45a7e96146e606057b76523f6246b6ac1 \
  skills/global-geochemical-atlas | tar -x -C skill_export --strip-components=1
mkdir -p candidate_bundle/.opencode/skills
mv skill_export/global-geochemical-atlas candidate_bundle/.opencode/skills/global-geochemical-atlas
rmdir skill_export
rm -rf bootstrap_repo
```

确认 `candidate_bundle/` 中不存在 `.git`、checker、rubric、gold、历史 submission 或其他 Skill。完整读取 `.opencode/skills/global-geochemical-atlas/SKILL.md`，按路由规则只读取每道题需要的 references/scripts/assets；存在适用脚本时必须实际调用并记录命令与文件，不能只复述 SKILL.md 或重新实现已有能力。若脚本不适用于冻结输入结构，应在 `run_manifest.json` 中记录具体不适用原因，不能伪称已使用。

然后完整阅读 `AGENT_PROMPT.md` 和 `public_interface.md`，严格执行与 B0 相同的核心题面。自主完成 Q01–Q24：每题只读取 `tasks/Qxx/task.md`、`task.json` 和 `inputs/`，把 `task.json.required_outputs` 的十个文件写入 `submissions/Qxx/artifacts/`。不得自行寻找评分器、修分或编造来源未报告的科学事实。

完成后运行 `python3 validate_submission_contract.py --bundle-root .`。若返回 `FAIL`，只按公开契约修正后重跑；该工具不含 gold、分值或隐藏 checker。通过后报告 commit、`condition=S0`、`skill_used=true`、实际使用的 Skill 文件、完成/失败题号、总耗时和所有生成路径。不要自行宣称分数；评分应交给独立评分会话。
````
