# D1 Demo 生成与证据链测试记录

## 2026-08-05 14:31 CST

### 已提交 fixture

| 来源 | 观测数 | As/Cu/Ni/Zn | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---|---|---|
| GEOROC Archaean Cratons 12.0 | 48 | 各 12 条 | `75e76082fa18af6f3f1b79ed05d4984f34545d202873afed611b68b45e06b8cb` | `c73f495a50c1790d55320f0f3bd75118a44ac27afc470431a34ea18d7968aa45` |
| USGS Data Series 801 | 48 | 各 12 条 | `1a2334a32c25792b0dfc136221fc071dc486b1246ddfa0709cc13b7ad24e3763` | `df5b803264403256371eeabdbb9f005df3182e63a8ef2b51a3d360f555409e72` |
| MarChem snapshot | 112 | 各 28 条 | `7ae5180c7167946d01ae48e4ff980c6531ad8aaafb54a655cb2d0d4ebb150b3b` | `65938d4f927a4739a3ff00aa506558532fcf414f2234a7c81184d1d240cfcf93` |

三个 `run_manifest.json` 均包含：

```json
{
  "data_mode": "fixture",
  "scientific_scope": "pipeline demonstration only",
  "not_for_scientific_interpretation": true
}
```

### 确定性复现

使用相同验证缓存、注册表版本、48 条观测和固定 `--generated-at 2026-08-05T06:25:00Z`，分别在新的 `/tmp` 目录重新生成。

结果：三个来源的 `demo_input.csv`、`sources.jsonl`、`run_manifest.json` 均可按固定参数字节级重建。

### 证据链

- 每个 demo 的 CSV 观测和 JSONL 证据一一对应，`record_id` 集合完全一致；
- GEOROC 证据包含数据集 DOI/版本、成员文件 DOI、文件 SHA-256、源行、citation ID、原始参考文献文本及可解析 DOI；
- USGS 证据包含数据集 DOI/版本、三个官方文件 URL/hash、源行、土层和建议引用；
- MarChem 证据包含动态快照 ID、响应成员 hash、数据行、方法元数据行、批次、LLQ、干湿重基础、部分消解和认可状态；
- 来源、许可和定位覆盖率均为 100%。

### 完整工作流验证

三个 demo 分别运行 `run_workflow.py` 和 `validate_outputs.py`：

| 来源 | 输入记录 | 成功标准化 | 有效坐标 | 输出校验 |
|---|---:|---:|---:|---|
| GEOROC | 48 | 48 | 48 | `valid`，0 errors |
| USGS | 48 | 48 | 48 | `valid`，0 errors |
| MarChem | 112 | 112 | 112 | `valid`，0 errors；8 条 fixture 删失观测未被填补 |

D2 生成 `d2-confidence-v1` 报告，D1 证据打包器验证输入 SHA-256 后原样绑定其报告 SHA-256。D1 不重新计算置信度公式或数值。

## 2026-08-06 16:00 CST：FOREGS 六介质扩展

六个具体数据集从 FOREGS 父项目中独立注册；完整解析共对账 16,364 个 CSV 数据行和 48,504 条 As/Cr/Cu/Hg/Ni/Pb/Zn 映射。小样仅选 48 条观测用于接口回归，不代表抽样密度或区域代表性。

| 来源 | 全量 CSV 行 | 小样观测 | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---:|---|---|
| `foregs-topsoil` | 4,195 | 48 | `e45f573db608634a65453acaf2a724a46b7291e6a0ae11ad93af50878cf8dee1` | `d2fb99230b6ad0b3243ec43a5271836b21d45e9ca231c1f10aa1fad5749cd08c` |
| `foregs-subsoil` | 3,922 | 48 | `196c056e57c26303df2fc270245bb344a2b53abc34992bde0c6909e6ee8d1286` | `41292d6dfe213e99ae4487c2ac657fb217b694e9c8c8cd2477309337371fcdbb` |
| `foregs-humus` | 1,111 | 48 | `38886457c87bcc27878c1c8581f1a38ea95dcdac91475229f2c66ab41b2bdfb5` | `00739879086c5e3bb3d70624e97f6ca084d60507da7b03ca9a3d8642e3968d64` |
| `foregs-stream-water` | 808 | 48 | `bb7a887e7688ff02b76a0c1988df2c7f86164a70143b1164a903c79373ae3554` | `d7010d0d74ea551a3d82316b530cfae033e410e48c4c9cb932b38ca243aefa5b` |
| `foregs-stream-sediment` | 3,393 | 48 | `59fd2c203464e751547da9bdc3a08ad7bfd3d4acdb46758d0f44665252f87097` | `8a0f97953f2ff8ab6d0538e0c25b663ae6d793487fef89462b8ccc072abd4c91` |
| `foregs-floodplain-sediment` | 2,935 | 48 | `82e767778a5e8fb0faf2e5241427866f18ee457d315400aa70ef3fe42625dad2` | `da77e2ec474f6a22b9465ed059eee07812dbf7723c7a83de8041ce7fc45b3284` |

### FOREGS 复现与边界检查

- 六个来源均用同一份 hash 校验缓存、48 条观测和固定 `generated_at=2026-08-06T08:00:00Z` 在独立临时目录重建；CSV、JSONL 和 manifest 均逐字节一致。
- 另从官方 GTK 地址在线重取 837,779-byte `Topsoil.zip`，实测 SHA-256 为 `ac23bffd5e116545a8c5618c943c75d995e81cdf5adc6d2902238d2e11e40357`；在线下载、解压、4,195 行解析和 48 条小样生成全部通过，随后两次离线缓存重放逐字节一致。
- 缓存模式只沿用已有在线获取记录的原始时间；手工填充但 hash 已验证的缓存不伪造 `retrieved_at`，避免把每次本地校验时间写成来源获取时间。
- 每个来源准备 30 条分层人工复核记录，机器预检均为 30/30 PASS；`completed_comparisons` 仍为 0，因此来源保持 `normalized_analysis`，不冒充 `benchmark_ready`。
- 总量、王水可浸出、温和硝酸可浸出和溶解态保持不同 `measurement_basis`；CSV 中恰好等于 `DL/2` 的值只标记为“可能的上游替代”，不直接断言为检出或删失。

## 2026-08-06 18:05 CST：AfSIS Phase I V2.0 扩展

| 来源 | 原始样品行 | fixture 观测 | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---:|---|---|
| `afsis-phase-i-wet-chemistry` | 2,002 | 48 | `563f4e461892913088cbc6f65e74f31126210c4375dcf070596fd5c2ff974fe8` | `0d241dfca9acedd34d2e898d9355f529f01b7ce872962319ea8ed267094600af` |

全量对账固定三份 original 文件和 publisher MD5/SHA-256，核实 2,002 个唯一 SSN/RES.ID、18 个国家标签、51 个国家-站点对、1,876 个完整坐标对和六目标元素各 2,002 个数值。30 条 review 覆盖所有国家标签、上下层、缺坐标、负数、低于 DL、DL–QL 和高于 QL 类别，自动检查 30/30 PASS、人工字段保持空白。fixture 只选 12 个国家标签的正值完整坐标行，原国家名和独立规范名同时保留。

### 十四来源联合回归

联合四介质 fixture 扩为 736 条观测、89 个比较分区，其中水体仍为 17 个分区：

- `demo_input.csv`：`e6fc39def68699f5c71eb413ce15c06f1014c02456ccf5c7634f1b26f80b88fc`
- `sources.jsonl`：`adf4a1f0e675055dfbd90e11d573a74d86fb7afb48b12e02be1944c64432df89`
- `run_manifest.json`：`0ee8250b730ece2cfd0dd0a7263a141720bae37bbecc5b4b2b3cfef06a4a1f3b`
- `sources.jsonl`：`925dd4489d18b63ffb1d44c86ada895c64038d90feeeafce71bb29f2f02738a1`
- `run_manifest.json`：`f70f773fdb51e2d63cf11fd1a1cbfa689e193e44177d8d2c5f69d96825d8d523`

完整工作流成功标准化并验证 736/736 条坐标，保留 20 条已确认删失观测，输出 16 条工程异常候选。联合输入、证据和九文件输出包均通过字节级重建。
