# Qwen3.8-Max S0 candidate prompt · host

你正在一个由外部控制器预先生成的最小权限 bundle 中执行全球地球化学图谱 uplift。直接完成任务，不询问
确认。实际 commit 以只读 `BUNDLE_MANIFEST.json.source_commit` 为准；固定 model=`Qwen3.8-Max`，
temperature=0，`runtime_mode=host`，`skill_used=true`。

先验证 `BUNDLE_MANIFEST.json`：condition 必须是 S0；当前目录不得有 `.git`、gold、checker、private、历史实验、
其他 Skill 或另一臂产物；唯一 Skill 必须是 `.agents/skills/global-geochemical-atlas/SKILL.md`。禁止访问父目录、
克隆仓库或寻找评分器。若隔离不符，写明失败并停止；不要自行清理后继续。

完整读取 SKILL.md，并按其路由只读取本任务需要的 references/scripts/assets，记录实际使用文件和 SHA-256。再
完整读取 `TASK.md`、`public_case/sources.json`、`public_case/discovery_contract.json`、
`public_case/benchmark_export_crosswalk.json` 和 `public_case/prepare_case.py`，记录哈希且禁止修改。

按 TASK 冻结 global 请求执行：准备真实性锚点，主动完成有界多平台来源发现并冻结新增来源，按 Skill 断网完成
D1/D2/D3、五项产物和 `run.sh` 干净重建。五个锚点不是来源上限；只处理四个地球化学锚点属于未完成 D1。
不得猜单位、CRS、方法、地质或坐标精度；删失值不变成零；异常只称筛查候选。

formal bundle 没有 scorer；不要自评分或伪造浏览器审计。若 development bundle 提供公开 scorer，最多三轮并
原样保存每轮证据。外部控制器会在你退出后运行隐藏门禁、真实 Chromium、统一报告和三次独立聚合。

输出放在 `submission/`；在 `agent_report.json/md` 记录 `skill_used=true`、实际 Skill 文件、runtime、环境、下载与
执行耗时、命令、失败、clean rebuild、输入与产物哈希。不要写 `experiment_manifest.json`，该公平性证据由候选
目录外的控制器生成。最终回复列出状态、限制和绝对路径。
