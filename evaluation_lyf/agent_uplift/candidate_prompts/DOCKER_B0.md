# Qwen3.8-Max B0 candidate prompt · Docker

你已在外部控制器冻结的 Docker 容器和最小权限 bundle 中。直接完成全球地球化学图谱任务，不询问确认。
固定参数：commit=`c59f2ab424480e5dc700d0628833c7cae9323bdf`，model=`Qwen3.8-Max`，temperature=0，
`runtime_mode=docker`，`skill_used=false`，CPU=2，memory=4g，timeout=900 秒。不要调用或嵌套 Docker。

验证 `BUNDLE_MANIFEST.json` condition=B0；不得存在 `.git`、`.agents`、gold、checker、private、历史实验或另一
实验臂。禁止访问父目录、克隆仓库、搜索/安装/使用 Skill 或寻找评分器。隔离不符时保留失败证据并停止。

完整读取并哈希 `TASK.md`、`public_case/sources.json`、`public_case/discovery_contract.json`、
`public_case/benchmark_export_crosswalk.json`、`public_case/prepare_case.py`。按 TASK 执行 global 有界多平台发现；
五个锚点不是来源上限。冻结采集字节后断网完成 D1/D2/D3、五项产物和 `run.sh` clean rebuild。不得猜单位、
CRS、方法、地质或坐标精度；删失值不插补；异常只称筛查候选。

formal bundle 不含 scorer；不要自评分或伪造浏览器审计。外部控制器会执行隐藏 scorer、真实 Chromium 和统一
报告。输出到 `submission/`，并在 `agent_report.json/md` 记录 `skill_used=false`、环境、模型参数、命令、下载/
执行耗时、失败、重建和全部哈希。不要写控制器拥有的 `experiment_manifest.json`。最终回复列出状态、限制和
绝对路径。
