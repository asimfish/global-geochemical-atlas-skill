# 对抗审计与多 Agent 互搏协议

版本：`adversarial-audit-v1`

## 动机与核心原则

十轮在线复测反复证明：执行者（尤其弱执行器）会漏跑循环、凭印象复述数字、把最低线当停止线。提示约束无法根治，必须用可机检的对抗机制。本协议把 ARIS 式跨模型互搏改造成本 Skill 的确定性裁判层，核心原则只有一条：

> **执行者可以驱动修复，但永远不能自我豁免（it can drive, never acquit）。**

三个角色：

| 角色 | 承担者 | 职责 |
|---|---|---|
| Builder（建造者） | 执行主流程的 Agent | 采集、标准化、渲染、修复 |
| Skeptic（怀疑者） | 独立 Agent 或确定性检查套件 | 攻击最强主张：证据链、单位换算、删失处理、异常统计、坐标一致性、地图完整性 |
| Referee（裁判） | `scripts/adversarial_audit.py` | 金丝雀校准 + 确定性复核 + 裁决可采信性 |

## 金丝雀校准（本 Skill 的独到设计）

审计工具先把产物目录复制为影子副本，按种子确定性植入 10 类已知缺陷（数值篡改、单位翻转、删失填补、伪造来源、证据孤儿、哈希损坏、定位越界、URL 掉包、坐标交换、异常 z 值篡改），再用同一套检查审计影子副本：

- **全部抓到（recall = 1.0）**：对真实目录的裁决才可采信（admissible）；
- **有漏网**：裁决自动降级为 `inadmissible_calibration_failed`，不允许出具 PASS。

这样"审计者是否称职"本身每次运行都被机械验证，杜绝"跑了个空审计然后宣布通过"。金丝雀只进影子副本，真实交付目录只读，不破坏逐字节一致性门禁。

## 单 Agent 模式（官方评审默认）

官方评审沙箱只有一个 Agent，互搏退化为**角色轮换 + 确定性裁判**：

```bash
python scripts/adversarial_audit.py --output-dir OUTPUT_DIR
```

- 退出码 0 = PASS 且可采信；1 = 发现错误（读 `audit_receipt.json` 的 findings 逐条修复）；2 = 不可采信；3 = 产物无法加载。
- 审计产物写到 `OUTPUT_DIR_audit/`（独立目录，不污染交付）。
- `autopilot.py` 已内置本步骤，合规报告会拒绝无审计收据的"完成"声明。

## 双 Agent 模式（授权的深度互搏）

有第二个 Agent（子代理、另一会话或另一模型）时：

```bash
python scripts/adversarial_audit.py --output-dir OUTPUT_DIR --mode brief
```

生成 `audit_brief.json` 与 `AUDIT_INSTRUCTIONS.md`。独立性规则（改编自 ARIS 评审独立性协议）：

1. Skeptic 使用全新上下文，只读产物字节，不接收 Builder 的任何叙述或修复摘要；
2. Skeptic 先考试：审计含金丝雀的影子目录并提交发现；裁判核对 `referee_canary_truth.json`（编排者必须对 Skeptic 隐藏该文件）；考试不满分则其真实发现仅作参考，不构成豁免；
3. Skeptic 必须至少执行一项脚本没有的检查（抽样比对来源原始字节、许可措辞核对、术语漂移检查）；
4. 发现按 schema 写入 findings JSON，由裁判 `--adjudicate FINDINGS.json` 逐条分类：`confirmed_deterministic` / `recorded_suspicion` / `unconfirmed_requires_evidence`；
5. 已确认发现回流修复队列，进入下一轮 Builder 修复——互搏结果直接驱动自纠错循环，而不是停在报告里。

## 与交付门禁的关系

`validate_outputs.py` 与 `validate_research_delivery.py` 检查契约完整性；对抗审计检查**内容真实性**（可重推导性）。三者独立，缺一不可。最终回复必须引用 `audit_receipt.json` 的 verdict 与 calibration recall；没有可采信 PASS 的交付一律如实标注。

## 边界

- 审计只证明"可机检的一致性成立"，不证明测量值科学正确；
- 金丝雀类目是已知缺陷家族的下界，不是攻击面的全集；
- 双 Agent 模式的独立性依赖编排者执行隐藏规则，单 Agent 模式的独立性由确定性代码保证。
