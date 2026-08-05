# D1 Demo 生成与证据链测试记录

## 2026-08-05 14:31 CST

### 已提交 fixture

| 来源 | 观测数 | As/Cu/Ni/Zn | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---|---|---|
| GEOROC Archaean Cratons 12.0 | 48 | 各 12 条 | `75e76082fa18af6f3f1b79ed05d4984f34545d202873afed611b68b45e06b8cb` | `c73f495a50c1790d55320f0f3bd75118a44ac27afc470431a34ea18d7968aa45` |
| USGS Data Series 801 | 48 | 各 12 条 | `1a2334a32c25792b0dfc136221fc071dc486b1246ddfa0709cc13b7ad24e3763` | `df5b803264403256371eeabdbb9f005df3182e63a8ef2b51a3d360f555409e72` |

两个 `run_manifest.json` 均包含：

```json
{
  "data_mode": "fixture",
  "scientific_scope": "pipeline demonstration only",
  "not_for_scientific_interpretation": true
}
```

### 确定性复现

使用相同验证缓存、注册表版本、48 条观测和固定 `--generated-at 2026-08-05T06:25:00Z`，分别在新的 `/tmp` 目录重新生成。

结果：两个来源的 `demo_input.csv`、`sources.jsonl`、`run_manifest.json` 均通过 `cmp`，字节级一致。

### 证据链

- 每个 demo 均有 48 条 CSV 观测和 48 条 JSONL 证据，`record_id` 集合完全一致；
- GEOROC 证据包含数据集 DOI/版本、成员文件 DOI、文件 SHA-256、源行、citation ID、原始参考文献文本及可解析 DOI；
- USGS 证据包含数据集 DOI/版本、三个官方文件 URL/hash、源行、土层和建议引用；
- 来源、许可和定位覆盖率均为 100%。

### 完整工作流验证

两个 demo 分别运行 `run_workflow.py` 和 `validate_outputs.py`：

| 来源 | 输入记录 | 成功标准化 | 有效坐标 | 输出校验 |
|---|---:|---:|---:|---|
| GEOROC | 48 | 48 | 48 | `valid`，0 errors |
| USGS | 48 | 48 | 48 | `valid`，0 errors |

D2 生成 `d2-confidence-v1` 报告，D1 证据打包器验证输入 SHA-256 后原样绑定其报告 SHA-256。D1 不重新计算置信度公式或数值。
