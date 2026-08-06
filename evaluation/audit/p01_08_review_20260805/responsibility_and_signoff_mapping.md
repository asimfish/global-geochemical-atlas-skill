# E1/E2 对齐审计口径

## 绑定基线

| 项目 | 值 |
|---|---|
| Benchmark | `6.0.0-draft.1` |
| E1 eval version | `1.0.0` |
| E1 contract SHA-256 | `b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee` |
| Benchmark execution contract | `evaluation/contracts/benchmark-execution-contract.json` |
| Execution contract SHA-256 | `d113eb7b9b5ee185e0a07bb00e4a5f16ee8ee1113fa84c33e305eb65797b275c` |
| 当前正式状态 | `FROZEN_FOR_MOCK` / `NOT_READY` |

E1 契约变化时，应先提升 Benchmark 版本并重新冻结 campaign；不得把不同 contract hash 的结果合并。

## 交卷与评分映射

每次运行只允许声明 E1 的十个物理产物：observations、SQLite database、sources、QC、anomaly table、anomaly GeoJSON、H3 cells、static map、interactive map 和 run manifest。Q01–Q24 的题目专用逻辑证据放入 `artifacts/run_manifest.json.benchmark_evidence`，不得创建第二套交卷文件协议。

E1 六维是唯一最终总分：科学可信性 25%、工程质量 30%、平台复用 14%、领域理解 15%、创新生态 10%、开源潜力 6%。E2 checker/LLM rubric 只产生归属到六维的 metric 证据；未覆盖维度保持 `not_scored`/`partial`，不能用“80+20”或临时平均值补齐。

候选、runner、validator 和 scorer 统一采用 E1 退出码 `0`、`2`、`10–30`、`70–76`。`2` 只表示候选 `partial_success`；grader 自身异常为 `75`，原始子进程码只能作为 cause 证据。

## 角色与签收

| 角色 | 可在本地完成 | 必须由真实外部主体提供 |
|---|---|---|
| E1 | 契约/schema、十产物校验、六维计分、证据完整性、签名/receipt 验证器、READY fail-closed | 具名 E1 owner 对精确 contract/G5 payload 的签名 |
| E2 | 对公开 fixture 的接口适配与返回字段 schema 校验 | official metric rubric、资源/计时/网络/重试确认、密封 Shadow/Final、真实签名或不可伪造的独立验证回执 |
| D3 | 生产构件格式与完整性算法验证 | 生产 Skill、入口、Git commit/tree hash、只读交付 manifest 与签名 |

本地字符串非空、`verified=true`、自填 verifier JSON 或手改 `checks.json.formal_ready` 都不是签收。E1 可实现的鉴权验证器和 READY fail-closed 必须先通过伪签名、篡改 payload、错误 key/role、陈旧 checks 等负例；随后缺少真实 E2/D3 身份时才归类为 `WAITING_EXTERNAL`。

## Shadow/Final 隔离

E2 在 E1 工作区之外持有 Shadow/Final，并只读挂载密封 worker。E1 只能接收 opaque job id、冻结 bundle hash、允许披露的聚合状态/分数和与精确 receipt bytes 绑定的签名验证结果；不得接收输入、gold、阈值、逐记录判断、原始日志或可逆诊断。

旧版 Q17–Q24 曾进入公开 Git 历史，已失去严格 holdout 资格。迁出只能用于隔离回归；正式 Final 必须重新生成、私下冻结并由独立评测负责人签名。

## 对缺陷状态的影响

- P05-D001 是 E2 official rubric 外部门禁；P05-D005～D011 是 E1 本地 validator/scorer 误通过，不能混为同一类阻塞。
- P07-D001 是正式 cohort/G5 外部门禁；P07-D002～D004 是当前可修复的本地鉴权和 READY 缺陷，不能仅标记为等待 E2。
- P07-D003 的最终关闭需要真实 E2 key/证书或独立验证服务，但本地 verifier 必须先证明无法被自填 JSON 绕过。
- P08 必须用伪签名、伪 verification、手改/陈旧 checks 做独立负例；仅检查 READY 文件存在或字段非空不能验收。
