# 跨次运行采集记忆（acquisition_memory.py）

## 动机

自纠错 loop 在**一次运行内部**已经会做轮间优先级传递（`next_round_priority_source_ids`：上一轮修复动作涉及的来源在下一轮先被调度）。但每次新运行仍然从零开始：昨天交付过上万条记录的来源，与连续三次返回 HTTP 403 的来源，今天在调度器眼里处于同一起跑线。失败的尝试是最有价值的记忆；被验证过的来源是下一次运行的地基。

## 机制

记忆文件是一个小型可审计 JSON（`atlas-acquisition-memory-v1`），按 `source_id` 累积每个来源的成败账：

- `update --run-dir OUT --memory-file MEM.json`
  收割一次已完成运行：`source_manifest.json` 中被采纳的来源记一次成功（含记录数与介质）；采集清单 `failures` 数组中的条目记一次失败（含失败状态）。成功会清零 `fail_streak`。
- `advise --memory-file MEM.json --request REQUEST.json`
  产出下一次运行的第一轮调度建议：
  - `priority_source_ids`：介质匹配的已证明来源，按（成功次数，累计记录数）排序，默认取前 4 个；
  - `banlist`：连续失败 >= 2 次且从未被采纳的来源，附明确理由（仅建议，不作门禁）。

## 与 autopilot / loop 的接线

```bash
python scripts/autopilot.py --prompt-file TASK_PROMPT.txt --output-dir OUT \
  --time-budget-seconds 14400 --memory-file MEM.json
```

autopilot 在执行前调用 `advise`（建议写入 `memory_advice.json` 并进入合规报告），将 `priority_source_ids` 经 loop 新增的 `--seed-priority-source-id` 注入第一轮；运行结束后调用 `update` 把本次成败收割回记忆文件。手工路径可直接对 loop 传 `--seed-priority-source-id`（可重复）。

## 边界（不可逾越）

- 建议**只重排**技能已经路由的来源，**永不**新增未路由来源——loop 的不可变技能边界不因记忆而放松。
- `banlist` 是建议不是门禁：来源恢复可用后一次成功即清零失败连击。
- 记忆文件是**运行输入**而非 Skill 代码：跨请求的经验积累不修改技能本体，全部可审计、可删除、可重建。
- 种子只影响第 1 轮；后续轮次仍由修复动作推导优先级，运行内的证据永远压过运行间的记忆。
