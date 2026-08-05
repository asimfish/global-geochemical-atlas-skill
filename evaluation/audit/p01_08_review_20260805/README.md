# P01–P08 E1/E2 对齐审计包

状态：`PENDING_FINAL_REVIEW` / `NOT_READY`

本目录保存对外部 P01–P08 评测框架实现的独立复核材料。它以本仓库的 E1/E2 统一执行契约为上游，作为候选实现的只读审计归入 `audit/`，不写入 `results/`，也不冒充裸模型、挂载 Skill、Shadow 或 Final 的真实运行结果。

## 基线与边界

- Benchmark 版本：`6.0.0-draft.1`
- 外部框架契约：`eval_version=1.0.0`
- 外部契约 SHA-256：`b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee`
- 执行对齐契约：[`../../contracts/benchmark-execution-contract.json`](../../contracts/benchmark-execution-contract.json)，SHA-256 见 `manifest.json`
- 远端整理基线：`evaluation` 分支提交 `e2f91e6bf77f85bbf3d77b5b7959d23961fc7306`
- 隔离边界：不包含 `evaluator_private/` 内容、私有题目输入、金标准、逐题评分、LLM grader prompt、凭据或个人绝对路径
- 当前限制：P04 完整性清单漂移；P07 的 G5 签名、E2 receipt 验证和 READY 生成仍存在本地可伪造旁路；正式 cohort/G5 尚未完成，P08 尚未具备最终验收条件

## 对齐原则

- E1 是十个物理交卷产物、退出码和六维最终计分的唯一上游；题目专用证据只进入 `artifacts/run_manifest.json.benchmark_evidence`。
- E2 checker 和 LLM rubric 只产生六维评审证据，不再形成独立“80+20”总分。
- E1 必须实现签名、receipt 和 READY 的 fail-closed 校验；缺 E2 真实 key/身份时保持门禁关闭，不能接受本地占位或自填 JSON。
- Shadow/Final 由 E2 在工作区外密封持有；旧版公开 Git 历史中的 Final 只能作回归，不能恢复为严格 holdout。

## 文件

- `defect_register.md`：P01–P08 未关闭缺陷；P07/P08 为待最终同步快照
- `responsibility_and_signoff_mapping.md`：E1/E2/D3 职责、交卷、评分、隔离和正式签收映射
- `p05_validator_findings.json`：P05 validator/scorer 独立反例摘要
- `p06_integration_findings.json`：P06 端到端集成独立反例摘要
- `manifest.json`：本审计包文件哈希和状态；P07/P08 完成后重建

## 使用约束

P05/P06 JSON 中的分数只表示外部 synthetic rubric 对反例的诊断输出，用于证明 validator/scorer 存在误通过；它们不是 Benchmark v6 任务得分或 E1 六维正式总分。外部路径一律按受审工作区相对路径记载，本仓库无需包含对应实现文件。

P07/P08 完成后，提交前必须执行以下步骤：

1. 先关闭 P07-D002～D004 的本地鉴权/READY 旁路，再接收 E1/D3/E2 真实签名；
2. 冻结外部写入并验证 P04、P07、P08 的原生回归、evidence index 与 `SHA256SUMS`；
3. 重新复现所有仍为 `OPEN` 的 P0/P1 条目，删除已满足关闭条件的条目；
4. 更新本目录状态、对齐契约哈希、文件哈希和 `docs/known_limitations.md`；
5. 运行 v6 package validation 与 isolation 检查；
6. 重建冻结候选清单，确认审计材料不进入 Public 白名单、私有资产不进入仓库后再提交。
