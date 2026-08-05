# P01–P08 E1/E2 对齐缺陷台账（待最终复审）

> 审计性质：本文件是针对外部 P01–P08 评测框架实现的独立集成审计，不是 Benchmark v6 的裸模型、挂载 Skill、Shadow 或 Final 运行结果。
>
> 对齐基线：Benchmark `6.0.0-draft.1`，E1 `eval_version=1.0.0`，`contract_sha256=b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee`。
>
> 执行对齐契约：`evaluation/contracts/benchmark-execution-contract.json`，SHA-256 见本审计包 `manifest.json`。
> 提交状态：`PENDING_FINAL_REVIEW` / `NOT_READY`。正式签名、official rubric、生产 Skill 和正式 cohort 不得由本审计包代造。

审查日期：2026-08-05

源快照：2026-08-05 21:46 CST（P07 鉴权、READY 与可移植性负向复审）

审查范围：P01 契约与签收、P02 runner/gateway、P03 supervisor、P04 仓库/数据/沙箱、P05 scorer/validator、P06 集成、P07 正式实验与统计、P08 独立验收
当前结论：`NOT_READY`

本台账只保留未关闭项。修复和独立验收证据均已完成的条目直接删除，不保留 `CLOSED` 行；派生验收门禁会引用根缺陷，不代表新增一份根因计数。文中 `governance/`、`handoff/`、`eval/`、`reports/`、`runs/` 与 `tmp/` 都是外部受审工作区相对路径，不表示这些实现文件属于本 Benchmark 仓库。

## 状态说明

| 状态 | 含义 |
|---|---|
| `OPEN` | 当前仍可复现，或关闭条件尚未全部满足 |
| `WAITING_EXTERNAL` | 依赖生产输入、正式运行授权或具名签收，E1 不能自行生成 |
| `INTEGRITY_DRIFT` | 实现或证据晚于完整性清单发生变化，当前 handoff 不可签收 |
| `OPEN_UPSTREAM` | P08 验收项由上游根缺陷阻断，不重复计算根因 |

## 当前审计基线

- 当前冻结身份：`eval_version=1.0.0`，`contract_sha256=b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee`，状态仍为 `FROZEN_FOR_MOCK`。
- P01 契约校验通过；P07 专项回归 `25 passed`。全仓回归 `200 passed, 79 subtests passed`，唯一失败为 P08 检出的 P04 完整性清单漂移；绿色原套件不覆盖本台账中已独立复现的反例。
- P01～P03、P05～P07 的 `SHA256SUMS` 当前通过；P04 的清单早于当前 Docker contract 文件，按 P04-DEF-011 留待 P04 稳定写入后重建，P07 不越权重签。
- P07 的 113 项交付 SHA 已全部通过，统计计算与输入追溯测试为绿色；但当前专项测试把可自填的 G5/E2 断言当作有效签名，且 handoff 可仅凭手改 `checks.json` 创建 READY，不能据此声称本地正式鉴权闭环已完成。
- 当前只有 P03 存在 `READY_FOR_INTEGRATION`，但 P03 仍有 P0 缺陷；P01、P02、P04、P05、P06 均无正式 READY，P07 无 `READY_FOR_FINAL_ACCEPTANCE`，P08 无 `READY_FOR_INTEGRATION`。

## E1/E2 责任边界

| 责任域 | 必须完成的内容 | 本台账的判定方式 |
|---|---|---|
| E1 | 十个固定物理产物、0/2/10–30/70–76 退出码、六维最终计分、契约校验、证据完整性和 fail-closed READY | 可由本地实现和负例关闭；不能以“等待 E2”掩盖签名验证器、receipt 验证器或 READY 生成器的可伪造缺陷 |
| E2 | metric-level official rubric、资源/计时/网络/重试签收、Shadow/Final 密封执行、返回字段白名单和真实签名/独立验证 | 缺少真实外部输入时保持 `WAITING_EXTERNAL`；本地占位字符串、自填 JSON 或自签不能关闭 |
| D3 | 生产 worker/Skill、Git commit/tree hash、只读交付 manifest 与签名 | 必须绑定同一 E1 contract 和 G5 输入；E1/E2 均不得替代 D3 签收 |
| 联合门禁 | E1/D3/E2 的身份、UTC 时间、签名 payload、contract/candidate/image/model/task/rubric/bundle hash 全部一致 | 先关闭本地鉴权旁路，再接收真实外部签名；任一不一致均不得提升 `FROZEN_FOR_OFFICIAL` 或创建 READY |

E2 checker 和 LLM rubric 只产生归属于 E1 六维的评审证据，不组成另一套“80+20”总分；题目专用逻辑结果应进入 `artifacts/run_manifest.json.benchmark_evidence`，不得新增非 E1 物理交卷文件。Shadow/Final 内容必须位于 E1 工作区之外，本审计包只记录门禁状态与不泄题的聚合结论。

## P01：契约冻结后的正式门禁

P01 的 E1 结构实现已完成；以下均是仍未满足的正式运行门禁。

| ID | 优先级 | 状态 | 当前未完善处 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P01-X001 | Gate P0 | `WAITING_EXTERNAL` | 缺 D3 生产 worker 入口、生产 Skill、Git commit/tree hash、只读交付 manifest 与签名 | D3 | D3 manifest 和具名签收绑定当前 contract hash，并通过真实 Skill 前后完整性检查 |
| P01-X002 | Gate P0 | `WAITING_EXTERNAL` | 缺 E2 对资源、计时、网络、重试、metric-level official rubric 和 shadow 返回字段的签收 | E2 | E2 提供机器可读、`official=true`、`FROZEN_FOR_OFFICIAL` 的规则及签名 |
| P01-X003 | Gate P0 | `WAITING_EXTERNAL` | 缺 E1 具名 owner 对当前冻结输入的签收 | E1 owner | 在治理记录中写入身份、UTC 时间和所签 contract/candidate/image/model/task hash |
| P01-X004 | Gate P0 | `WAITING_EXTERNAL` | 官方模型 ID、版本和关键参数尚未进入冻结 manifest | E2 / G0 | 冻结模型配置并与 P07 G5 输入、签名和正式 cohort 绑定 |

## P02：Runner/Gateway

| ID | 优先级 | 状态 | 当前证据 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P01-08-P02-D005 | P1 | `OPEN` | 缺少 `--request` 时进程 exit 10，stdout 声称 `result=result.json`，但输出根没有该文件 | P02 | 可落盘时写 Schema 合法的拒绝结果并输出真实路径；不可落盘时不得虚构文件；新增参数错误回归 |

P02 的 validator/scorer 终态绑定、P04 输入消费、P03 identity 和 timeout 映射分别由 P05-D002、P06-D002/P06-D007、P03-DEF-003/P03-DEF-004 跟踪。

## P03：可靠性、资源与证据

| ID | 优先级 | 状态 | 当前证据 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P03-DEF-001 | P0 | `OPEN` | secret fixture 的 `outcome.json` 仍保留明文秘密；测试仍显式排除该文件 | P03 | outcome 使用同一 redactor 安全落盘或被隔离清除；递归扫描全部 evidence，不得排除任何文件 |
| P03-DEF-002 | P0 | `OPEN` | 本轮 `0.15s deadline + 0.2s grace` 的 ignore-SIGTERM 场景耗时约 `0.562s`，超过 `0.35s` 上界 | P03 | 单一 shutdown deadline 约束 TERM/KILL/wait/pipe drain；四类进程树路径稳定满足严格上界 |
| P03-DEF-003 | P0 | `OPEN` | `parse_plan` 仍接受缺失 `contract_sha256`；P02 生成的 execution plan 仍不写该字段且消费 report 时不回验 | P02 / P03 | plan 强制 exact hash/eval version；report/status/snapshot/handoff 回写同一身份；P02 完整回验 |
| P03-DEF-004 | P0 | `OPEN` | timeout stage 携带清理信号 15 时，P02 `_public_exit` 本轮仍返回 cancel/76，而不是 timeout/71 | P02 | 根分类优先于清理信号；区分 termination/cancellation signal；增加 71/72/76 契约测试 |
| P03-DEF-005 | P1 | `OPEN` | `oom` 与 `memory` fixture 仍是同一 RSS 追加分支，没有真实 MemoryError/RLIMIT_AS/OOM 路径证据 | P03 | 分离 RSS pressure 与 OOM；受控验证 MemoryError/RLIMIT_AS/信号、snapshot、无重试和无残留进程 |
| P03-DEF-006 | P1 | `OPEN` | 预算测试仍依赖宿主调度与 `/proc` 扫描；尚无可控时钟和并发负载 20 次稳定性证据 | P03 | 分离逻辑时钟测试和平台性能测试；记录至少 20 次并发复跑的最大值与失败次数 |

`handoff/P03/READY_FOR_INTEGRATION` 在上述 P0 关闭并重新生成 handoff 前不能作为正式 Ready 证据。

## P04：仓库、依赖、数据和沙箱

| ID | 优先级 | 状态 | 当前证据 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P04-DEF-001 | P0 | `WAITING_EXTERNAL` | P01 仍为 `FROZEN_FOR_MOCK`，无 P01 READY；根依赖见 P01-X001～X004 | P01 / D3 / E2 / E1 | 三方签收同一 hash，P01 重验并创建 READY |
| P04-DEF-003 | P0 | `OPEN` | 开发镜像证据已有 contract hash，但 P04 CLI、cache marker、dataset materialization、checks/handoff manifest 仍未完整携带并校验 `eval_version/contract_sha256` | P04 / P01 | 全链路写入并回验冻结身份；缺失、格式错误、陈旧 hash 均 preflight 硬失败 |
| P04-DEF-004 | P0 | `OPEN` | P04 仍输出 `layer=data_acquisition` 且 CLI 对所有 `P04Error` exit 2；P06 仍把所有 P04Error 压成 code 12 | P04 / P02 / P06 | 建立唯一版本化 P04→P01 code/exit/layer/retryable 映射并覆盖 11/12/13/内部错误测试 |
| P04-DEF-005 | P0 | `OPEN` | P04 CLI 仍未消费 P01 的 allowlist id/hash、cache namespace、单一 deadline、资源和冻结 5/15 秒重试策略 | P04 / P02 | 从 request/resolved config 注入并校验全策略；证明 B0/S0 数据与策略等价、缓存隔离且重试不重置预算 |
| P04-DEF-006 | P1 | `WAITING_EXTERNAL` | P01 合同 Buildah/chroot 开发候选已通过，但正式 Docker/BuildKit、只读根、网络、cgroup、磁盘和 GPU 隔离仍全部 `NOT_RUN` | P04 / P06 / runtime owner | 在获批 Docker/Kubernetes 后端归档 inspect、日志、结果和 SHA；验证全部正式资源/写边界 |
| P04-DEF-007 | P1 | `OPEN` | `reports/repo-size.*` 是组件稳定前快照，当前工作区已继续新增 P07/P08 文件；且当前目录不是 Git worktree | P04 / repository owner | 在稳定生产 Git worktree 重新审计 Git objects、工作树、提交包、最大文件和未跟踪文件并重建 handoff |
| P04-DEF-008 | P1 | `WAITING_EXTERNAL` | 缺生产 Git、生产 Skill、根 dependency manifest/lock、LICENSE/NOTICE 和正式冷启动输入 | D3 / repository owner | 提供生产仓库与固定依赖、许可、安装来源；空缓存/无用户配置冷启动通过 |
| P04-DEF-009 | P1 | `OPEN` | `tmp/feishu_auth_qr.png` 仍存在于交付树 | repository owner | owner 删除或从提交包明确排除；必要时撤销/轮换凭据；敏感文件扫描归零 |
| P04-DEF-010 | P1 | `OPEN` | 文档仍要求先 curl/检查 digest，再由 online 模式二次下载；动态 API 存在两次响应漂移窗口 | P04 | 单次下载进入 quarantine，验证/签收后将同一字节原子提升到不可变缓存；增加动态响应变化测试 |
| P04-DEF-011 | P1 | `INTEGRITY_DRIFT` | 当前 Docker contract 源码、测试和开发证据晚于 `handoff/P04/SHA256SUMS`；P08 SHA 验收因此失败 | P04 / runtime owner | 停止并发写入，在 P04 范围重跑原生/容器验证，审查新增证据后重建 checks、manifest 与 SHA；P08 再独立复核 |

## P05：Scorer/Validator

| ID | 优先级 | 状态 | 当前证据 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P05-D001 | P0 gate | `WAITING_EXTERNAL` | E2 metric-level official rubric 未签收；当前 synthetic rubric 只能给 partial diagnostic 90 分 | E2 / P05 | official rubric 绑定当前 contract hash，公式/边界/确定性测试重跑后创建 P05 READY |
| P05-D002 | P1 | `OPEN` | P02 仍在 P05 前发布 raw success 和 `COMPLETED`，P06 只能事后 fail-closed | P02 / P06 | success marker 前完成 validator/scorer；最终 result、score、manifest、archive 和 marker 原子绑定 |
| P05-D005 | P0 | `OPEN` | 清空 anomaly CSV 和 GeoJSON 后，本轮仍 `hard_gate_passed=true`、0 fail、90 分 | P05 | 每个有效 observation 恰好有一条异常结果；分组覆盖完整；GeoJSON 与 actionable anomaly 双向一致 |
| P05-D006 | P0 | `OPEN` | SQLite observation 内容改成与 CSV 矛盾但行数不变，本轮仍通过并得 90 分 | P05 | 按 observation ID/source/sample/element/value/medium 逐条双向比较并补负例 |
| P05-D007 | P0 | `OPEN` | artifact/run manifest 的 run/config/contract 身份改为其他值或非法 hash，本轮仍通过并得 90 分 | P05 / P01 | result、artifact manifest、run manifest、resolved config 的全部身份全等且 hash 可回算 |
| P05-D008 | P0 | `OPEN` | sources JSONL 写入重复 `source_id` 键，本轮仍按最后值静默通过并得 90 分 | P05 | JSONL 每行使用 duplicate-key rejecting loader；覆盖关键来源字段重复键负例 |
| P05-D009 | P0 | `OPEN` | QC check 明确改为 `fail`，本轮仍通过科学硬门禁并得 90 分 | P05 | 冻结 fail/warn 终态语义；fail 触发 P0，warn 与 partial/限制披露一致 |
| P05-D010 | P0 | `OPEN` | H3 cell 改为 `000000000000000` 后，本轮仍通过并得 90 分 | P05 | 使用独立 H3 实现验证 index/resolution，并从坐标回算及校验 H3/GeoJSON/anomaly 一致性 |
| P05-D011 | P0 | `OPEN` | source row 改为 999999、文件/文档改为不存在对象并填任意合法形状 hash，本轮仍通过并得 90 分 | P05 / P04 | 打开并 hash 冻结源文件；验证行号、sample、version、document/report 的真实绑定及负例 |

## P06：端到端集成

| ID | 优先级 | 状态 | 当前证据 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P06-D001 | P0 | `OPEN` | P02 mock success/COMPLETED 的十种产物仍被 P05 检出 11 项失败 | P02 / P05 | worker 输出十种合法科学产物并在最终 success 前全部通过 P05 |
| P06-D002 | P0 | `OPEN` | P04 物化数据只被归档，P02 mock/生产 worker 没有消费冻结路径 | P02 / P04 / D3 | 冻结输入以只读方式进入 worker；证明 B0/S0 消费完全相同的数据字节 |
| P06-D003 | P0 | `OPEN` | 继承 P03-DEF-001：attempt outcome 明文秘密 | P03 | 关闭 P03-DEF-001并重跑 P06 fault matrix 的全 evidence 扫描 |
| P06-D004 | P0 | `OPEN` | 继承 P03-DEF-002～004：deadline、contract identity、timeout/cancel 分类未关闭 | P02 / P03 | 关闭三个根缺陷并使用真实 P03 CLI 重跑集成分类测试 |
| P06-D005 | P0 | `WAITING_EXTERNAL` | 上游 READY、生产 Skill/Git、根 lock/镜像验收、official rubric、G5 联合签收均缺失 | integration owners / D3 / E2 | 所有冻结输入和签名绑定同一 candidate/contract/image/Skill/rubric hash |
| P06-D006 | P1 | `WAITING_EXTERNAL` | 缺获批 official online 和 native Codex smoke | G0 / Codex owner | 以获批网络和 native Codex host 运行同一冻结 fixture 并归档证据 |
| P06-D007 | P0 | `OPEN` | 统一入口 exit 74，但 raw `result.json`/`COMPLETED` 仍为 success/0、`score=null`，archive 与 score 表达不同终态 | P06 / P02 | 形成唯一 final result；process exit、result、archive、score、manifest 和 marker 一致且 hash 绑定 |
| P06-D008 | P0 | `OPEN` | `pipeline.py` 仍将任意 P04Error 无条件映射为 `SOURCE_DOWNLOAD_INVALID`/12，403 不能得到 11 | P06 / P04 | 与 P04-DEF-004 共用穷举映射；覆盖权限、下载、格式和未知内部错误 |
| P06-D009 | P1 | `OPEN` | `composition_audit()` 命中 import 字符串后仍硬编码 `duplicate_worker_implementation=false` | P06 | 枚举允许实现并做 AST/依赖图或等价结构审计；新增第二 worker/runner/scorer 负例 |
| P06-D010 | P1 | `OPEN` | clean environment 测试只设置空 HOME/有限环境/cwd `/`，仍不是正式 namespace/cgroup/read-only/network 沙箱 | P06 / P04 | 将状态保持 PARTIAL，直到正式 runtime 的隔离和写逃逸负例全部通过并归档 |

## P07：正式实验、统计与消融

| ID | 优先级 | 状态 | 当前证据 | Owner | 关闭条件 |
|---|---|---|---|---|---|
| P07-D001 | P0 gate | `WAITING_EXTERNAL` | G5 为 `NOT_READY`；无正式 public B0/S0 各三次 cohort、E2 shadow 回执、final statistics、最终消融数字或 `READY_FOR_FINAL_ACCEPTANCE` | P07 / G5 owners / E2 | 上游 READY 与 G5 签收后执行不可变正式 cohort，完成 sealed receipt、自动统计和 final report |
| P07-D002 | P0 auth | `OPEN` | `gate._validate_signatures()` 只检查 E1/D3/E2 三条记录及 `signature` 非空；`test_preregister.py` 用任意字符串 `"external"` 即使 G5 得到 `PASS` 并允许正式预注册 | P07 / P01 / security owner | 冻结签名 payload、算法、可信 key/identity；验证三方授权签名及时间/角色，篡改 payload、签名、key、role 均硬失败；缺真实外部 key 时再转 `WAITING_EXTERNAL` |
| P07-D003 | P0 auth | `OPEN` | `verify_shadow_receipt()` 不验证 receipt 签名值，只信任任意本地 JSON 中 `verified=true`、`verifier_id` 和 receipt hash；现有测试用 `algorithm=external`、`value=opaque` 与自填 verification 即返回 `PASS` | P07 / E2 / security owner | 使用可信 E2 key/证书或不可伪造的外部验证回执校验精确 receipt bytes；伪造 verifier、签名值、算法、key 和 verification 文件必须失败 |
| P07-D004 | P0 integrity | `OPEN` | `handoff.generate()` 直接信任 `checks.json.formal_ready`；`test_handoff.py` 仅写最小手工 checks 即能创建 `READY_FOR_FINAL_ACCEPTANCE`，未独立重跑 G5、public/shadow、报告和 size 证据 | P07 / P08 | handoff 在写 READY 前独立调用完整 verifier 或验证不可伪造的完整 checks schema/签名；最小、手改、过期或缺证据 checks 均不得创建 marker |
| P07-D005 | P1 hygiene | `OPEN` | 8 个 P07 交付文件持久化 `<workspace-root>/...` 宿主绝对路径，涉及 G5 audit、smoke plan/report/events/status/archive；换目录复核与隐私扫描不闭环 | P02 / P06 / P07 | 上游运行证据改为 bundle-relative path 或明确可重定位 token，必要宿主信息单独脱敏；复制到不同根目录后 P07/P08 验证与 SHA 全通过 |

P07-D001 及关闭 P07-D002/P07-D003 所需的真实 D3/E2 key/身份属于后期正式验证；但签名验证器、READY fail-closed 和路径可移植性是 E1 当前可实现范围，不能因外部输入缺失而跳过。

## P08：独立验收派生门禁

下列条目描述 P08 为什么不能正式 Ready；对应根因仍以上述条目为准。

| ID | 优先级 | 状态 | 当前证据 | 根缺陷/Owner | 关闭条件 |
|---|---|---|---|---|---|
| P08-D001 | P0 gate | `OPEN_UPSTREAM` | 没有可随机抽查的三条 official `report→aggregate→score→raw` 数字链 | P07-D001 / P07 | final report 生成后随机三条链的路径、hash、run_id 和数值全部一致 |
| P08-D002 | P0 | `OPEN_UPSTREAM` | 空环境复现仍 exit 74；raw candidate success/0，P05 检出 11 项失败 | P06-D001/D002/D007 | 生产 worker 消费冻结数据，十种产物全过且最终终态一致 |
| P08-D003 | P0 | `OPEN_UPSTREAM` | P03 的秘密、deadline、identity、timeout/cancel P0 仍开放 | P03-DEF-001～004 | 关闭根缺陷并对全部 evidence 无排除递归扫描 |
| P08-D004 | P0 hygiene | `OPEN` | `tmp/feishu_auth_qr.png` 和多处个人绝对路径仍在交付证据中 | P04-DEF-009 / P07-D005 / repository/P02 owners | owner 处置认证材料、替换个人路径、重建对应 SHA，P08 扫描归零 |
| P08-D005 | P1 delivery | `OPEN` | 根 dependency manifest/lock、LICENSE/NOTICE、reviewer README 和 Demo link 缺失 | integration window | 补齐后执行真正 clone/install/run/score/open-artifacts 冷启动复现 |
| P08-D006 | P0 gate | `WAITING_EXTERNAL` | D3 生产 Skill 完整性、E2 shadow/gold 隔离和 official rubric、E1 冻结输入签收缺失 | D3 / E2 / E1 | 三方签收绑定同一 contract/candidate/image/model/task/Skill/rubric hash |
| P08-D007 | P1 gate | `WAITING_EXTERNAL` | 当前不是 Git worktree；只有 Codex 协议 fixture evidence，无 native certification | repository / Codex owner | 提供 clean Git tree/hash 证据和 native Codex smoke，并同步兼容报告 hash |
| P08-D009 | P0 integrity | `OPEN_UPSTREAM` | G5、E2 receipt verification 和 P07 READY 均可由本地自填 JSON/非空字符串满足，独立验收无法证明签收主体真实性 | P07-D002～D004 / P07 | 关闭三项根缺陷后，P08 使用伪签名、伪 verification、手改 checks 和陈旧证据做独立负向复核 |
| P08-D010 | P1 integrity | `OPEN_UPSTREAM` | P08 自有 summary/defect-register 仍称 P01～P07 SHA 全通过且旧 P07 漂移已关闭，但当前 P04 清单有 10 项失败，`test_acceptance.py` 为 1 failed/9 passed | P04-DEF-011 / P08 | P04 稳定并重建 handoff 后，P08 重建 observation、evidence index、summary、defect register、manifest 和 SHA，再跑独立验收 |

## 关闭与删项规则

1. 不因测试总数为绿色而关闭反例仍可复现的缺陷。
2. `WAITING_EXTERNAL` 必须有具名 owner、UTC 时间和所签 hash；占位文件或自签不能关闭。
3. 影响正式分数、公平性、隔离、错误分类或证据完整性的修复，必须重跑受影响 cohort；不能只改文档或 READY marker。
4. 删除条目前必须同时满足实现修复、针对性负例、原生回归、handoff manifest/hash 和独立复核五类证据。
5. 修改外部源台账后，P08 必须重建 evidence index 和自身 `SHA256SUMS`；若 P07/P08 等上游仍在并发写入，保持 `NOT_READY`。本审计副本还必须重新同步并重建 `manifest.json`。

## 建议关闭顺序

1. 先冻结 P04/runtime 当前写入并关闭 P04-DEF-011，恢复跨模块完整性基线。
2. 关闭 P03-DEF-001～004 与 P05-D005～D011，消除安全、计时、身份和科学误通过 P0。
3. 关闭 P04-DEF-003～005、P06-D002/D007/D008，统一冻结输入、错误映射和最终终态。
4. 关闭 P06-D001，让生产或验收 worker 输出真正可评分的十种产物。
5. 补齐生产 Git/Skill/依赖/许可/README/Demo 和正式 Docker/native Codex/online 证据。
6. 先关闭 P07-D002～D004 的鉴权与 READY fail-closed 缺口，并处理 P07-D005 的可移植路径；再接收真实 D3/E2/E1 签收与 G5，执行正式 cohort、shadow 回执和最终报告。
7. 最后由 P08 用伪签名/手改 checks 负例重验数字链、证据索引和全部 SHA，所有门禁归零后才创建正式 READY。
