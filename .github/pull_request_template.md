# What

<!-- 用一句话描述已经实现且可验证的结果。 -->

- Scope: <!-- D1 | D2 | D3 | cross-component -->
- Deliverables affected: <!-- map | database | provenance/confidence | anomalies | Skill docs | none -->

# Why

<!-- 说明问题、用户/评测价值，以及它对应的验收条件。 -->

# How

<!-- 说明关键设计、D1/D2/D3 边界、失败关闭行为和被否决的主要替代方案。 -->

# Changes

- <!-- 具体且可审查的变更 -->
- Contract or Schema impact: <!-- None，或列出生产者、消费者和迁移方式 -->
- Generated artifacts: <!-- None，或列出生成命令和绑定的输入/hash -->

# Risk Assessment

- Scientific claim risk: <!-- None，或适用条件、竞争解释与人工复核要求 -->
- Security/data risk: <!-- None，或不可信输入、网络、凭据、许可和数据边界 -->
- Compatibility/rollback: <!-- None，或兼容性影响与最小回退方式 -->
- Performance risk: <!-- None，或基准工作负载和前后结果 -->

# Testing

```bash
ruff check .
ruff format --check .
mypy --config-file mypy-critical.ini
uv run pytest -x --tb=short
python skills/global-geochemical-atlas/scripts/component_test.py --component all
python skills/global-geochemical-atlas/scripts/self_test.py
```

- Results: <!-- 命令、通过数量、关键产物或日志 -->
- Unavailable checks: <!-- Docker/OpenCode/官方模型/人工复核；没有则写 None -->

# Breaking Changes

None.

<!-- 若存在，改为说明 BREAKING CHANGE、受影响接口和迁移要求。互不依赖的改动应拆成不同 PR。 -->
