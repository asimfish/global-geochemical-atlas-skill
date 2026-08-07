# Skill uplift 对照实验协议

每个 runtime profile 使用两个全新、相互隔离的 Qwen3.8-Max 会话和空目录：

- 主机直跑：[`QWEN_NO_SKILL_PROMPT.md`](QWEN_NO_SKILL_PROMPT.md) 与 [`QWEN_WITH_SKILL_PROMPT.md`](QWEN_WITH_SKILL_PROMPT.md)；
- Docker 隔离：[`QWEN_NO_SKILL_DOCKER_PROMPT.md`](QWEN_NO_SKILL_DOCKER_PROMPT.md) 与 [`QWEN_WITH_SKILL_DOCKER_PROMPT.md`](QWEN_WITH_SKILL_DOCKER_PROMPT.md)。

四份 Prompt 都会自行克隆固定 commit，下载五个 hash 固定的真实性锚点，并按同一冻结请求执行有界多平台来源发现；随后冻结 `case_data/`、断网完成 D1/D2/D3、最多运行三轮 scorer，并用 `run.sh` 做干净重建。五个固定资源不是采集上限：只处理四个地球化学锚点属于未完成 D1。Docker 版额外准备冻结镜像和隔离参数。具体操作和 Docker 文件索引见 [`DOCKER_UPLIFT.md`](DOCKER_UPLIFT.md)，机器可检验参数见 [`experiment_config.json`](experiment_config.json)，发现门槛见 [`public_case/discovery_contract.json`](public_case/discovery_contract.json)。

## 实验设计

- 主指标：每个实验臂三次独立运行的最终 `score.json.score` 中位数；`uplift = with_skill − no_skill`；
- 次指标：首轮分数、达到 70 分所需轮次、排除网络传输的执行耗时、干净重建分数和运行成功率；
- D1 广度：候选来源、检索平台、经本地 bytes/hash 验证的数据集、四介质/六元素覆盖，以及来源选择、拒绝和失败证据；公开数量门槛只是最低合约，不代表全球完整性；
- 科学红线：伪造未报告字段、删失值被当作精确值、给水体或海洋沉积物赋陆地岩性、把统计异常写成污染/矿化/成因结论；
- 工程门禁：`run.sh` 能从固定输入重建、离线地图自包含、输出完整、scorer 未修改；
- 公平性：同一个 runtime profile 内使用相同 commit、模型服务版本、temperature、机器资源、网络、输入、时限和 scorer，唯一自变量是 Skill 可见性；主机版和 Docker 版分别聚合，不跨 profile 混算。

每次运行回收 `experiment_manifest.json`、`case_data/discovered_manifest.json`、每轮分数、最终 submission、clean rebuild 证据和 Agent 最终回复。锚点与新增来源的网络传输耗时单列；来源规划、解析、处理属于任务执行，不能与下载一起排除。用于比较的 `execution_seconds` 只能明确排除网络传输阶段。

公开 scorer 只验证最低锚点、不变量和候选冻结证据。正式结论还需要不可见来源目录与在线权威复核，防止参赛 Agent 只迎合公开门槛或在 `discovered_manifest.json` 中自证来源。

只有有 Skill 组的三次中位数更高、科学红线没有恶化，且六次运行的环境参数一致，才可宣称正 uplift。单次运行、mock agent、host fallback、不同 commit 或不同模型服务版本只能用于联调，不能作为正式结论。
