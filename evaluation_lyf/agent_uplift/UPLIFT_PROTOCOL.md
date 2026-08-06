# Skill uplift 对照实验协议

使用两个全新、相互隔离的 Qwen3.8-Max 会话和空目录，分别原样发送：

- [`QWEN_NO_SKILL_PROMPT.md`](QWEN_NO_SKILL_PROMPT.md)：只导出公开任务，禁止任何 Skill；
- [`QWEN_WITH_SKILL_PROMPT.md`](QWEN_WITH_SKILL_PROMPT.md)：公开任务相同，只额外导出 `global-geochemical-atlas` Skill。

两份 Prompt 会自行克隆固定 commit、准备 Docker、下载固定公开数据、完成任务、最多运行三轮 scorer，并用 `run.sh` 做干净重建。具体操作和 Docker 文件索引见 [`DOCKER_UPLIFT.md`](DOCKER_UPLIFT.md)，机器可检验参数见 [`experiment_config.json`](experiment_config.json)。

## 实验设计

- 主指标：每个实验臂三次独立运行的最终 `score.json.score` 中位数；`uplift = with_skill − no_skill`；
- 次指标：首轮分数、达到 70 分所需轮次、排除下载的执行耗时、干净重建分数和运行成功率；
- 科学红线：伪造未报告字段、删失值被当作精确值、给水体或海洋沉积物赋陆地岩性、把统计异常写成污染/矿化/成因结论；
- 工程门禁：`run.sh` 能从固定输入重建、离线地图自包含、输出完整、scorer 未修改；
- 公平性：相同 commit、模型服务版本、temperature、机器资源、网络、输入、时限和 scorer，唯一自变量是 Skill 可见性。

每次运行回收 `experiment_manifest.json`、每轮分数、最终 submission、clean rebuild 证据和 Agent 最终回复。下载耗时单列，不从墙钟时间中隐式删除；用于比较的 `execution_seconds` 必须明确排除下载阶段。

只有有 Skill 组的三次中位数更高、科学红线没有恶化，且六次运行的环境参数一致，才可宣称正 uplift。单次运行、mock agent、host fallback、不同 commit 或不同模型服务版本只能用于联调，不能作为正式结论。
