# Skill uplift 对照实验协议

每个 runtime profile 使用两个全新、相互隔离的 Qwen3.8-Max 会话和空目录：

- 主机直跑：[`QWEN_NO_SKILL_PROMPT.md`](QWEN_NO_SKILL_PROMPT.md) 与 [`QWEN_WITH_SKILL_PROMPT.md`](QWEN_WITH_SKILL_PROMPT.md)；
- Docker 隔离：[`QWEN_NO_SKILL_DOCKER_PROMPT.md`](QWEN_NO_SKILL_DOCKER_PROMPT.md) 与 [`QWEN_WITH_SKILL_DOCKER_PROMPT.md`](QWEN_WITH_SKILL_DOCKER_PROMPT.md)。

正式运行禁止让候选 Agent 先克隆完整仓库。外部控制器必须在 Agent 启动前运行
`export_candidate_bundle.py`：B0 只导出任务白名单，S0 只额外导出冻结 Skill；formal bundle 不含 `.git`、历史运行、
gold、私有 checker 或公开开发 scorer。Agent 从第一秒只看到 bundle。development bundle 可带公开 scorer，
但其结果只能用于联调。候选随后下载真实性锚点、执行有界多平台来源发现，冻结 `case_data/`、断网完成
D1/D2/D3，并用 `run.sh` 做干净重建。五个固定资源不是采集上限：只处理四个地球化学锚点属于未完成 D1。

## 实验设计

- 主指标：每个实验臂三次独立运行的最终 `score.json.score` 中位数；`uplift = with_skill − no_skill`；
- 次指标：首轮分数、达到 70 分所需轮次、排除网络传输的执行耗时、干净重建分数和运行成功率；
- D1 广度：候选来源、检索平台、经本地 bytes/hash 验证的数据集、四介质/六元素覆盖，以及来源选择、拒绝和失败证据；公开数量门槛只是最低合约，不代表全球完整性；
- 科学红线：伪造未报告字段、删失值被当作精确值、给水体或海洋沉积物赋陆地岩性、把统计异常写成污染/矿化/成因结论；
- 工程门禁：`run.sh` 能从固定输入重建、离线地图自包含、输出完整、scorer 未修改；控制器用真实 Chromium
  验证底图、样点、筛选、热力图、元素组合、来源和异常交互，并绑定 HTML hash 与截图；
- 公平性：同一个 runtime profile 内使用相同 commit、模型服务版本、temperature、机器资源、网络、输入、时限和 scorer，唯一自变量是 Skill 可见性；主机版和 Docker 版分别聚合，不跨 profile 混算。

每次运行回收 `experiment_manifest.json`、`case_data/discovered_manifest.json`、最终 submission、clean rebuild
证据和 Agent 最终回复；控制器另生成 `browser_audit.json`、截图、`score.json`、`evaluation_report.json/md`。
锚点与新增来源的网络传输耗时单列；来源规划、解析、处理属于任务执行，不能与下载一起排除。

`experiment_manifest.json` 也必须由控制器使用 `evaluation/reporting/build_experiment_manifest.py` 在候选目录外生成，
而不是信任候选自报。生成器逐字节比较两臂公共 bundle，校验 formal mode、commit 和可审计 provider profile，
把 endpoint origin、API model、temperature、thinking、资源与公共题面写入 pair fingerprint；漂移即失败关闭。

公开 scorer 只验证最低锚点、不变量和候选冻结证据。正式结论还需要不可见来源目录与在线权威复核，防止参赛 Agent 只迎合公开门槛或在 `discovered_manifest.json` 中自证来源。

用 `evaluation/reporting/aggregate_uplift.py` 强制每臂三个不同 run ID、同一 pair fingerprint 后再计算 median、range、
MAD 和 uplift。B0 median ≥ 90 时标记天花板饱和，不作为有效 uplift 证据。只有有 Skill 组三次中位数更高、
科学红线没有恶化，且六次运行环境参数一致，才可宣称正 uplift。单次运行、mock agent、host fallback、不同
commit 或不同模型服务版本只能用于联调。
