# P08 独立复现与工程验收交接

## 结论

P08 已完成当前工作区的独立验收，结论为 **AUDIT_COMPLETE_NOT_READY**，G8 fail-closed。

已交付 runbook、证据索引 Schema/JSON/Markdown、path/hash 验证器、敏感信息与旧规则扫描器、空环境复现器、9 项自测、复现原始证据和工程验收报告。P01–P07 七份 SHA 清单全部通过。十种必需产物均真实打开，已知失败可由日志、归档和具体 check 定位。

没有创建 `READY_FOR_INTEGRATION` 或任何等价通过标记，因为 P07 正式统计/三数字链、D3/E2 签收和多个仓库卫生/集成门禁尚未满足。

## 核心证据

- `reports/reproduction-runbook.md`
- `reports/engineering-acceptance.md`
- `reports/evidence-index.json`
- `reports/evidence-index.md`
- `handoff/P08/acceptance-observation.json`
- `handoff/P08/reproduction-observation.json`
- `handoff/P08/reproduction-evidence/`

## 独立复现结果

- 空 HOME、空输出根、`PYTHONNOUSERSITE=1`、cwd `/`；
- 集成入口 exit 74，状态 `artifact_validation_failed`，stderr 0 bytes；
- candidate raw result 为 success/0，但 P05 发现 11 个真实校验失败并使集成 fail-closed；
- 日志、score/checks 和 `p06-archive.json` 均保留并绑定 SHA-256；
- good fixture 十种产物真实打开；broken-provenance 精确失败于 `provenance.chain`。

## 当前阻断

1. P07 的 `reports/ablation.md` 已正确 fail-closed 为 NOT_READY，但尚无 final statistics、正式 cohort 和 `READY_FOR_FINAL_ACCEPTANCE`，无法抽查三个结果数字。
2. D3 未签生产 Skill 完整性，E2 未签 shadow/gold 隔离和 official rubric。
3. P02 mock 产物仍被 P05 拒绝；P03/P06 登记的正式 P0 未关闭。
4. `tmp/feishu_auth_qr.png` 需要 owner 处置；多份交付材料仍有个人绝对路径。
5. 根依赖锁、许可、README/Demo 缺失；当前目录也不是 Git worktree。

精确 owner、复现与关闭条件见 `defect-register.md` 和 `root-change-request.md`。
