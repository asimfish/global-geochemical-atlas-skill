# Qwen3.8-Max S0 candidate prompt · Docker

你已在外部控制器冻结的 Docker 容器和最小权限 bundle 中。直接完成全球地球化学图谱任务，不询问确认。
实际 commit 以只读 `BUNDLE_MANIFEST.json.source_commit` 为准；固定 model=`Qwen3.8-Max`，temperature=0，
`runtime_mode=docker`，`skill_used=true`，CPU=2，memory=4g，timeout=900 秒。不要调用或嵌套 Docker。

验证 `BUNDLE_MANIFEST.json` condition=S0；不得存在 `.git`、gold、checker、private、历史实验、其他 Skill 或
另一实验臂；唯一 Skill 为 `.agents/skills/global-geochemical-atlas/SKILL.md`。禁止访问父目录、克隆仓库或寻找
评分器。隔离不符时保留失败证据并停止。

完整读取 SKILL.md，按路由只读取任务所需 references/scripts/assets，记录实际文件和哈希。再完整读取并哈希
`TASK.md`、`public_case/sources.json`、`public_case/discovery_contract.json`、
`public_case/benchmark_export_crosswalk.json`、`public_case/prepare_case.py`。按 TASK 和 Skill 执行 global 有界
多平台发现；五个锚点不是来源上限。冻结采集字节后断网完成 D1/D2/D3、五项产物和 `run.sh` clean rebuild。
不得猜单位、CRS、方法、地质或坐标精度；删失值不插补；异常只称筛查候选。
D3 必须按 Skill 的 profile → 官方 renderer → validator 流程生成；官方模板可用时不得另写替代 HTML，并在报告中
保存模板契约、模板 SHA-256 和全球/区域变体。

formal bundle 不含 scorer；不要自评分或伪造浏览器审计。外部控制器会执行隐藏 scorer、真实 Chromium 和统一
报告。输出到 `submission/`，并在 `agent_report.json/md` 记录 `skill_used=true`、Skill 文件、环境、模型参数、
命令、下载/执行耗时、失败、重建和全部哈希。不要写控制器拥有的 `experiment_manifest.json`。最终回复列出
状态、限制和绝对路径。
