# Split 与隔离协议

## Public：Q01-Q08

- 可供 D1、D2、D3 自测；
- 可公开题面、输入、public checker 和 public gold；
- 只用于理解接口和常见科学边界，不计入最终盲测主分。

## Shadow：Q09-Q16

- 评测组持有；
- 可在功能冻结前周期性执行；
- 向设计组只反馈 capability、failure tag、频次和严重度；
- 不反馈样品 ID、具体数值、完整输入行、gold、checker 条件或能反推出答案的截图。

## Final holdout：Q17-Q24

- 评测负责人独占；
- 只有在 Skill 代码、依赖、默认参数和 prompt 冻结后执行；
- 首次正式执行前计算冻结 manifest，执行后不得根据队伍表现改题或调权；
- 如发现评测资产本身错误，整题作废或对所有版本统一重跑，并保留事件记录；
- 不向设计组逐题反馈，只给聚合维度结果和红线计数。

## 物理发布规则

不得把整个 `benchmark_rebuild_v5` 目录复制给设计组。公开包应从白名单构建：

```text
README_public.md
release/public/**
docs/public_interface.md
```

以下路径永不进入被测 Skill 仓库、聊天附件或公开归档：

```text
evaluator_private/**
results/raw/**
results/llm_grader_prompts/**
freeze_manifest_private.json
```

## 泄漏审计

每次公开反馈前检查：

- 是否出现 Q09-Q24 的样品 ID、坐标、数值或文件名；
- 是否出现隐藏 gold 的字段组合和阈值；
- 是否粘贴隐藏 checker 日志；
- 是否通过“例如”复述了唯一隐藏案例；
- 是否共享包含 `evaluator_private` 的压缩包或 Git 历史。

本目录目前只通过组织约定实现隔离；若工作区由多人共享，必须在文件系统权限、独立私有仓库或加密归档层再增加访问控制，不能把目录名当成真正的权限边界。
