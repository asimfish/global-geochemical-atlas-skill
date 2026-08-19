# 声明式运行内适配器通道

版本：`declarative-adapter-engine-v1`

## 要解决的断点

旧闭环在"发现了新来源但没有注册适配器"处断裂：修复队列只能生成 `skill_maintenance_new_run` 项，要求停机、分叉仓库、手写 Python 适配器、冻结新 hash、重启。十轮复测证明弱执行器几乎从不完成这条路径，缺口停在报告里。

本通道把"新来源 → 可审计数据"压缩为三步，全程不修改冻结的 Skill 快照：

```
缺口(d1_repair_queue) ─→ propose_adapter_spec.py ─→ 草案 spec（机器填表）
                                                        │ 人工/授权策略补许可与版本后批准
                                                        ▼
                          declarative_adapter.py ──→ 采集包（demo_input.csv + sources.jsonl + manifest + receipt）
                                                        │
                                                        ▼
                          run_atlas_request.py --input ──→ 完整十六文件交付（走既有 provided-input 契约）
```

## 教义相容性

- **快照不可变**：spec 是运行输入（如同用户 CSV），不是 Skill 代码；spec 的 SHA-256 写入 receipt 与每条证据行（`adapter_spec_sha256`），运行身份可完整复现。
- **失败关闭**：许可不在冻结开放许可白名单 → 拒绝；非 HTTPS → 拒绝；哈希不匹配 → 拒绝；`dataset_version` 缺失 → 拒绝；未知单位/介质 → 逐行拒绝并留 reason_code，绝不猜补。
- **命名空间隔离**：来源 ID 强制 `spec-*` 前缀，证据行带 `in_run_adapter: true`，永远不能冒充注册适配器或抬升证据层级；该通道产物是补充筛查层证据。
- **哈希固定**：spec 未给 `expected_sha256` 时，引擎固定首次抓取哈希（`hash_pinned_at_acquisition`），后续重跑不一致即失败。
- **审批门**：引擎只执行 `approved_by_operator`；`auto_candidate_open_license`（许可已在白名单且证据齐全）还需显式 `--allow-auto-approved` 旗标，防止无授权自动扩权。

## 命令

```bash
# 1. 从修复队列缺口 + 候选表头生成草案（只嗅探表头，不采集数据）
python scripts/propose_adapter_spec.py \
  --from-repair-queue OUTPUT_DIR/d1_repair_queue.json \
  --candidate-url https://example.org/data.csv --sniff \
  --output adapter_proposals/spec-example.json

# 2. 人工补全许可 id、许可证据 URL、dataset_version、介质与 CRS 证据后批准

# 3. 执行采集（全部门禁生效）
python scripts/declarative_adapter.py --spec spec-example.json --workspace WS

# 4. 用既有 provided-input 契约生成完整交付
python scripts/run_atlas_request.py --request REQUEST.json \
  --input WS/demo_input.csv --evidence-jsonl WS/sources.jsonl \
  --acquisition-manifest WS/acquisition_manifest.json --output-dir OUT
```

`adapter_receipt.json` 记录每个门禁决定、逐行拒绝统计与下一步命令；产物随后照常通过 `validate_outputs.py` 与对抗审计。

## 能力边界

- v1 支持 csv / tsv / json_records 与 long / wide 两种布局；XLSX 等二进制表格必须先由发布方或操作者提供文本导出，不在运行内转换；
- 该通道不注册永久适配器；被证明有价值的 spec 应按隔离维护协议升级为带 fixture 与组件测试的注册适配器（spec 即是现成的字段 crosswalk 草稿）；
- 与在线循环的合并：v1 以独立补充运行交付，由 continuation receipt 关联；统一合并进主图谱仍走注册适配器路径。
