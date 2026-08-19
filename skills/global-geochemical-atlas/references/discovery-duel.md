# 来源发现对决（discovery_duel.py）

## 动机

缺口到数据的链路（修复队列 → `propose_adapter_spec` → 人工批准 → `declarative_adapter`）一次只审一个来源，而且要有人先想到它。数据丰富性的瓶颈不在门禁，在**候选漏斗太窄**。对决层把跨模型研究流水线的「fan-out 生成 + 对抗审查 + 陪审裁决」搬到来源发现上：宽进严出，幻觉在提名阶段是廉价的，因为没有任何来源凭 Scout 的一句话被采纳。

## 三个角色

- **Scout（侦察，鼓励过度生成）**：按 `scout_brief.json` 对每个缺口提名至多 6 个候选来源（标题 / https 直链 / 许可线索 / DOI / 介质 / 覆盖区域）。立场写在 brief 里：提错一个候选只花一轮裁决，漏掉一个候选就是一块空白地图。
- **Skeptic（质疑，跨模型家族 + 新鲜线程）**：只看 `candidates.json`，按固定分类附上反对（license_unclear / domain_untrusted / medium_mismatch / region_mismatch / duplicate_of_registered / paywalled / no_dataset_identifier / method_incomparable）。
- **Referee（裁判，本脚本，确定性）**：逐候选打分——开放许可 +3、数据集 DOI +2、介质匹配缺口 +2、区域命中 +2、表格直链 +1、每条未解决反对 −3；裁决 `admit_to_spec_draft`（≥7，附可直接执行的 `propose_adapter_spec` 命令）/ `revise`（4–6，附逐条行动项）/ `reject`（<4）。

## 轮次与停止

修订轮把行动项答完（`resolved_objections` 声明已解决的反对）再裁一次；每个受击缺口拿到至少一个 admit 记 `threshold_met`，否则打满 `--max-rounds`（默认 3）如实停下。轮次状态累积在 `duel_state.json`。

```bash
python scripts/discovery_duel.py --output-dir OUT --mode brief            # 生成两份 brief
python scripts/discovery_duel.py --output-dir OUT --mode adjudicate \
  --candidates DUEL/candidates.json --objections DUEL/objections.json    # 裁决一轮
```

## 边界（不可逾越）

对决裁决**只能起草 spec，永远不能批准 spec**：许可证据、哈希固定、`spec-*` 命名空间与人工批准原样保留。对决拓宽的是候选漏斗，不是信任边界——这就是「用互搏提高数据丰富性，同时不稀释置信度」的机制表达。
