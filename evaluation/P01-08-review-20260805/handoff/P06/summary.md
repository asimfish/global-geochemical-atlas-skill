# P06 集成、故障矩阵与双端兼容交接

## 结论

P06 可控范围内的实现和测试已经完成：新增唯一入口
`eval/bin/eval-run`，串联 P04 acquisition、P02 runner、P03 supervisor、P05
真实 validator/scorer，并生成 `p06-archive.json`；同时交付 Codex 协议适配、
依赖快照、三种数据模式 smoke、真实产物拒绝测试、12 类故障矩阵，以及包含
P01～P06 全组件 hash 的确定性候选 bundle。

本次 P06 自测为 `19 passed in 70.19s`；全仓回归为
`148 passed, 74 subtests passed in 144.79s`；P01 契约校验通过，当前
`contract_sha256=b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee`。

状态为 **NOT_READY**，没有创建 `READY_FOR_INTEGRATION`。原因不是 P06
入口无法运行，而是正式准入条件未满足：P01/P02/P04/P05 缺少 READY、
P02 success mock 的 10 个产物被 P05 真实解析器检出 11 项失败、生产
Skill/D3 manifest/Git worktree 不存在、P05 rubric 非 official，且 P03/P04
仍有未关闭 P0 缺陷。

## 一条命令

```bash
eval/bin/eval-run \
  --request eval/contracts/examples/success.request.json \
  --output-root /tmp/p06-runs
```

当前固定 mock 的预期集成退出码是 74，而不是 0：P02 raw result 为 success，
P05 随后真实打开产物并拒绝其结构，P06 将这一结果 fail-closed 地写入 stdout
和 `p06-archive.json`。原始 `result.json`、execution report、日志、manifest、
score/checks 和全部 hash 证据均保留。

## 任务状态

| 任务 | 状态 | 说明 |
|---|---|---|
| P06-01 | PASS_FIXTURE | 唯一入口复用真实 P02/P03/P05；生产 D3 worker 缺失 |
| P06-02 | PARTIAL | 已审计 hash-pinned contract lock、镜像 digest、六组件 hash 和无重复实现；根 lock 仍需 P01 签收 |
| P06-03 | PASS_FIXTURE | 干净 HOME、任意 CWD 一条命令可跑全链并归档 |
| P06-04 | PARTIAL_BLOCKED | 12 类机器可读故障矩阵可复现；P03 仍有秘密、deadline、身份和分类 P0 |
| P06-05 | PASS | 损坏、缺失、结构错误、恶意路径均被真实解析器拒绝 |
| P06-06 | PARTIAL_BLOCKED | tree hash 算法测试通过；生产 Skill/Git worktree 不存在 |
| P06-07 | PASS_FIXTURE | 双端 discovery/load/trigger/exit/产物协议等价；无 native Codex smoke |
| P06-08 | PARTIAL | fixture/cached/local-online 通过；official live online 未获批准 |

## 复现

```bash
python eval/contracts/validate_contracts.py
python -m eval.integration.audit --output /tmp/p06-candidate-bundle.json
python -m eval.integration.fault_matrix --output /tmp/p06-fault-matrix.json
python -m pytest -q eval/tests/integration
python -m pytest -q
```

兼容性细节见 `reports/opencode-codex-compatibility.md`；冻结候选、故障矩阵和
精确门禁分别见 `candidate-bundle.json`、`fault-matrix.json`、`checks.json`
和 `root-change-request.md`。
