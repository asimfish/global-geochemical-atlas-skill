# 协作开发约定

本仓库始终只维护 `skills/global-geochemical-atlas/` 这一份生产 Skill。D1、D2、D3 在同一条稳定流水线上协作，不复制 `SKILL.md`，不维护三套分叉实现。

## 模块所有权

| 角色 | 主要路径 | 负责的稳定接口 | 不直接决定 |
|---|---|---|---|
| D1 数据源、证据链与数据工程 | `score_source_evidence.py`、`snapshot_source.py`、`source_router.py`、`source_audit.py`、`coverage_report.py`、`download_data.py`、`build_evidence_bundle.py`、`validate_acquisition.py`、`build_index.py`、`query_source.py`、`assets/source_catalog.json`、`fixtures/`、D1 来源与归档 Schema | 候选发现、证据分级、科研使用门、动态快照、保守路由与覆盖、下载缓存与降级、原值归档和派生索引、demo 切片、`source_manifest.json`；校验并原样打包 D2 的 `confidence_report.json` | 异常阈值、置信度公式、最终 `SKILL.md` |
| D2 地球化学标准化与分析 | `standardize_geochemistry.py`、`references/scientific-rules.md`、`references/geochemistry-record.schema.json`、`references/confidence-report.schema.json`、`references/schema-map.schema.json`、`references/platform-field-crosswalk.*` | `geochemistry.csv`、`qc_report.json`、`confidence_report.json`、`anomalies.geojson`、`anomaly_report.json`；专业平台语义映射与信息损失说明 | 最终 `SKILL.md`、地图表现和数据源许可判断 |
| D3 Skill 架构、地图与 demo 总集成 | `SKILL.md`、`run_workflow.py`、`build_interactive_map.py`、`validate_outputs.py`、README、请求/结果 Schema、demo 指南 | `interactive_map.html`、`samples.geojson`、`run_summary.json`、稳定 CLI、唯一生产 Skill 和演示流程 | D2 的科学算法、D1 的来源许可结论 |
| 共享契约测试 | `component_test.py`、`self_test.py`、`.github/workflows/ci.yml` | 防止任一角色破坏其他角色的输入输出 | 不承载新的科学业务逻辑 |

其中最终责任对应为：D1 负责 **数据来源与置信度说明**，D2 负责 **标准化地球化学数据库** 和 **异常区域识别结果**，D3 负责 **可交互元素分布地图** 和 **可复用 Skill 文档**。

## 稳定数据流

```text
D1 候选目录 ──证据评分/科研使用门/保守路由──► 本次请求可执行来源
          │
          └──► 缓存/原值归档/demo CSV + record evidence + acquisition manifest
          │ 原值、来源、许可、坐标、方法、逐记录证据
          ▼
D2 标准化 + QC + 置信度算法 + 候选异常
          │ geochemistry / qc / confidence / anomalies
          ├──────────────► D1 证据打包与哈希绑定 ──► source_manifest
          ▼
D3 工作流编排 + 地图 + 输出校验 ──► 十五个稳定交付文件
```

`run_workflow.py` 只负责调用顺序和最终状态，不复制 D1/D2 算法。D1 的证据模块只验证 D2 置信度报告的版本、输入哈希和文件哈希，不重新计算置信度。

## 接口冻结规则

- D1 → D2：CSV 至少提供 `element_or_analyte,value,unit,medium`；正式数据还应携带样品、basis、坐标、方法、来源定位与许可。分层归档先按 `validate_acquisition.py` 校验，再依 `schema-mapping.md` 展开为一行一个 observation；派生 SQLite 只用于 D1 原值检索。
- D2 → D1/D3：固定生成五个分析产物，记录结构以 `geochemistry-record.schema.json` 为准，置信度版本当前为 `d2-confidence-v3`；D1 非 canonical 列名可按 `schema-map.schema.json` 显式映射。
- D1 → D3：固定生成 `source_manifest.json` 和 `record_evidence.jsonl`；输入 SHA-256 必须与 D2 run metadata 相同，sidecar 的 record ID 必须与 canonical database 完全一致，并绑定 acquisition manifest 与 `confidence_report.json` 的 SHA-256。
- D3 → 用户：固定生成 README 所列十五个文件；更名、删减或改变语义属于破坏性接口变更。
- 任何 Schema、版本号、输出文件名或 CLI 参数变更，都要在同一 PR 中更新文档、组件测试和完整回归测试。

## 分支与 PR

建议使用 `d1/<topic>`、`d2/<topic>`、`d3/<topic>` 分支，通过 PR 合并到 `main`。一个 PR 聚焦一个角色边界；跨边界修改要在 PR 中列明受影响的生产者和消费者。

- D1 PR：附来源、许可、访问方式、字段映射、缓存/断网行为和下载哈希。
- D2 PR：附科学依据、适用条件、单位/删失值行为、阈值变化和失败案例。
- D3 PR：附完整 Demo、地图截图或操作说明、输出兼容性和 Skill 加载结果。
- D2 不直接修改最终 `SKILL.md`；需要修改科学指令时，在 PR 中提出准确文案和对应规则，由 D3 合并。
- 不把完整全球数据、下载缓存、运行输出、视频、虚拟环境、密钥或评测金标准提交到仓库。

当前未写死 CODEOWNERS，因为还缺 D1、D3 的 GitHub 用户名。获得三人的用户名后再启用真实 CODEOWNERS，避免无效占位账号造成虚假的审核保护。

## Forge 提交与 PR 硬标准

所有提交标题必须使用：

```text
[scope/op]: concise imperative title
```

- `op` 只能是 `feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`、`style`、`ci`、`build` 或 `revert`；
- `scope` 使用小写字母、数字、`_`、`-` 或 `/`，准确描述受影响边界；
- 标题使用简洁祈使句，不超过 72 个字符；
- 破坏性变更使用 `[scope/feat!]: ...`，并在正文添加 `BREAKING CHANGE:` 与迁移要求；
- 一个 commit 只表达一个可独立审查和回退的意图，机械格式化与功能逻辑分开提交。

PR 正文必须按顺序包含 `What`、`Why`、`How`、`Changes`、`Risk Assessment`、`Testing` 和 `Breaking Changes`。无风险或无破坏性变更时明确写 `None`，不得删除小节。互不依赖的 D1、D2、D3、评测、格式化或生成产物变更应拆分；只有同一契约变更要求同步更新生产者、消费者、测试和 fixture 时才放在一个 PR。

## 最小验收

每个人提交前先运行自己的契约：

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component d1
python skills/global-geochemical-atlas/scripts/component_test.py --component d2
python skills/global-geochemical-atlas/scripts/component_test.py --component d3
```

合并前由 D3 运行：

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component all
python skills/global-geochemical-atlas/scripts/self_test.py
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input skills/global-geochemical-atlas/fixtures/demo_input.csv \
  --output-dir demo_output
```

组件测试验证边界契约；`self_test.py` 验证科学边界、异常输入和两次运行的字节级确定性。GitHub Actions 对每个 PR 自动执行两者。

## 完成定义

一个 PR 只有同时满足以下条件才可合并：

1. 自己角色的组件测试通过；跨接口修改时三组组件测试全部通过。
2. `self_test.py` 和输出校验通过，没有新增第三方依赖或未声明依赖。
3. 新数据有来源、许可与哈希；新科学规则有适用边界与失败状态。
4. 没有第二个 Skill 目录，没有密钥、缓存、生成输出或大文件。
5. PR 模板中的交付物、接口影响和复现命令填写完整。
6. `ruff check .`、`ruff format --check .`、`mypy --config-file mypy-critical.ini` 和仓库 CI 通过；已执行的测试与无法执行的外部检查均如实记录。类型门当前明确覆盖评测关键与公共契约边界，其他历史适配器在完成类型化后再加入，不得把“关键边界通过”误写成“全仓严格类型化”。
