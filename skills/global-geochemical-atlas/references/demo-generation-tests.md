# D1–D3 demo 生成、证据链与可视化测试记录

核验日期：2026-08-05。fixture 仅用于流水线演示，均声明 `not_for_scientific_interpretation: true`。

## 已提交 fixture

| 来源 | 观测数 | As/Cu/Ni/Zn | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---|---|---|
| GEOROC Archaean Cratons 12.0 | 48 | 各 12 条 | `382148f96b6e9f5c4c8beecd696d38921a2413e2a7af69e0d17c26be30291751` | `45d279d0b6fb0b9f9ab4a4840015556e6ce6736f6c3aa3178c5525746d19ef64` |
| USGS Data Series 801 | 108 | 各 27 条 | `fcdfe90941beab0f64fcaa42c7c4277ae50dc719cd6ea8f9abeaed575d205b67` | `4766e7cf9f42b74881b56a6e66681eda24994c29fd8c9c052a4d1c0c63c45031` |
| MarChem snapshot | 112 | 各 28 条 | `7ae5180c7167946d01ae48e4ff980c6531ad8aaafb54a655cb2d0d4ebb150b3b` | `65938d4f927a4739a3ff00aa506558532fcf414f2234a7c81184d1d240cfcf93` |

十三个 `run_manifest.json` 均绑定 CSV 与 JSONL 哈希、源文件 URL/SHA-256、生成参数、生成器契约版本和记录数；相同注册表、验证缓存、筛选参数及固定 `--generated-at` 可确定性重建。各 fixture 保留其生成时的 `d1-demo-slice-v1` 或 `v2` 契约，不伪造升级历史。

## 科学证据检查

- GEOROC demo 的 CSV/JSONL 均为 48 条，USGS 均为 108 条；各自的 `record_id` 集合完全相等，最终 `record_evidence.jsonl` 与 canonical database 也完全相等。
- GEOROC 保留数据集 DOI/版本、成员 DOI/hash/源行、citation ID 和原始文献；reported coordinates 有值，但因 datum 未证实，48 条 canonical 坐标全部留空并标记 `COORDINATE_NOT_CANONICALIZED`。
- USGS 保留三个官方文件 URL/hash/源行/土层；As 映射 HG-AAS + fusion，Cu/Ni/Zn 映射 ICP-AES + near-total four-acid digestion；3 条 `<0.6 mg/kg` As 记录保留 qualifier 与 detection limit；三个 horizon 各有 9 个样品并通过 `material` 独立分组。
- 使用 sidecar + acquisition manifest 运行时，最终 source manifest 的 `verified_evidence_rate` 为 1.0；该值表示证据关联完整，不表示测量正确率。

## 完整工作流验证

| 来源 | 标准化 | 有效 canonical 坐标 | 删失记录 | 输出校验 |
|---|---:|---:|---:|---|
| GEOROC | 48/48 | 0/48（datum 未证实，预期失败关闭） | 0 | `valid`，0 errors |
| USGS | 108/108 | 108/108 | 3 | `valid`，0 errors |

离线回归入口：

```bash
python scripts/component_test.py --component all
python scripts/self_test.py
```

合并后结果为 D1 201 项、D2 31 项、D3 20 项，共 252 项契约检查通过；self-test 68 项通过。

### 确定性复现

十三个来源均通过输出哈希、记录数及一对一证据关联检查；联合 fixture 还会在新的临时目录重建输入与完整十一文件输出，并逐字节比较。

### 证据链

- 每个 demo 的 CSV 观测和 JSONL 证据一一对应，`record_id` 集合完全一致；
- GEOROC 证据包含数据集 DOI/版本、成员文件 DOI、文件 SHA-256、源行、citation ID、原始参考文献文本及可解析 DOI；datum 未证实时 canonical 坐标失败关闭；
- USGS 证据包含数据集 DOI/版本、三个官方文件 URL/hash、源行、土层、分析方法和建议引用；
- MarChem 证据包含动态快照 ID、响应成员 hash、数据行、方法元数据行、批次、LLQ、干湿重基础、部分消解和认可状态；
- 其余来源保留水体分相/深度/QC、粒级、消解方法、坐标参考系和重复样品次序等来源特有语义；
- `verified_evidence_rate=1.0` 仅代表可定位记录的证据关联完整，不代表测量正确率。

### 完整工作流验证

基础 demo 分别运行 `run_workflow.py` 和 `validate_outputs.py`：

| 来源 | 输入记录 | 成功标准化 | 有效坐标 | 输出校验 |
|---|---:|---:|---:|---|
| GEOROC | 48 | 48 | 0（datum 未证实） | `valid`，0 errors |
| USGS | 108 | 108 | 108 | `valid`，0 errors；3 条删失观测未被填补 |
| MarChem | 112 | 112 | 112 | `valid`，0 errors；8 条 fixture 删失观测未被填补 |

D2 生成 `d2-confidence-v2` 及分量定义；`d2-interface-v2` 与 `d2-robust-mad-v2` 分别锁定异常接口和算法版本。D1 证据打包器验证输入和报告 SHA-256，但不重新计算置信度。D3 从完整 D1/D2 输出目录读取任务配置，并由专用验证器检查可视化包。

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

### 十三来源联合回归

联合四介质 fixture 在保留主线 108 条 USGS 三土层样本后共有 748 条观测；标准化前为 86 个输入分区，标准化后按 D2 当前默认键形成 93 个比较组，其中水体 17 个：

- `demo_input.csv`：`f316cc08a165de4845a001ec2fd80c38c084ec33e5bdf90459e1d11823fdc236`
- `sources.jsonl`：`3fa4ae1c24663bfd6be181cc9ef4d53e3e7ff38509dcca208ac145fc8e876d2e`
- `run_manifest.json`：`d4ccad9164e5176189e88ee4773bd737fd8d9436ab41d6d31d0ab4ed5047943c`

完整工作流成功标准化 748/748 条记录；700/748 条具有有效 canonical 坐标，48 条 GEOROC 记录因 datum 未证实而失败关闭。流程保留 23 条已确认删失观测，输出 16 条工程异常候选。联合输入、证据和十一文件输出包均通过字节级重建。异常仅是相对已声明背景组的工程筛查候选，不构成污染、矿化或成因结论。
