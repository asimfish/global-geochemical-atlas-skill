# D1–D3 demo 生成、证据链与可视化测试记录

核验日期：2026-08-05。fixture 仅用于流水线演示，均声明 `not_for_scientific_interpretation: true`。

## 已提交 fixture

| 来源 | 观测数 | As/Cu/Ni/Zn | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---|---|---|
| GEOROC Archaean Cratons 12.0 | 48 | 各 12 条 | `cf6f105867c0f5d3f031b0b95cc703df89b196f06b604de331b05e46b9309446` | `45d279d0b6fb0b9f9ab4a4840015556e6ce6736f6c3aa3178c5525746d19ef64` |
| USGS Data Series 801 | 108 | 各 27 条 | `75da16e1c262a7e5b4c97929c5085467d3b5cdb653f1bd7579de15e9c54f1cda` | `4766e7cf9f42b74881b56a6e66681eda24994c29fd8c9c052a4d1c0c63c45031` |
| MarChem snapshot | 112 | 各 28 条 | `243b51d529fc1c79e093fb59ec920c8ef22f7d1066f086e66c55729b6aaaeea3` | `65938d4f927a4739a3ff00aa506558532fcf414f2234a7c81184d1d240cfcf93` |

十四个 `run_manifest.json` 均绑定 CSV 与 JSONL 哈希、源文件 URL/SHA-256、生成参数、生成器契约版本和记录数；相同注册表、验证缓存、筛选参数及固定 `--generated-at` 可确定性重建。各 fixture 保留其生成时的 `d1-demo-slice-v1` 或 `v2` 契约，不伪造升级历史。

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

合并后结果为 D1 227 项、D2 29 项、D3 20 项，共 276 项契约检查通过；self-test 68 项通过。

### 确定性复现

十四个来源均通过输出哈希、记录数及一对一证据关联检查；联合 fixture 还会在新的临时目录重建输入与完整十文件输出，并逐字节比较。

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
| `foregs-topsoil` | 4,195 | 48 | `0d0b870b578852b7b090665a3878eee2ab01dfd26cb830a92e3aa213af77f740` | `d2fb99230b6ad0b3243ec43a5271836b21d45e9ca231c1f10aa1fad5749cd08c` |
| `foregs-subsoil` | 3,922 | 48 | `1bb134e661d0731c5b7ca16cbe3058b15b9760711492fdc0ae0051cf9c9eae83` | `41292d6dfe213e99ae4487c2ac657fb217b694e9c8c8cd2477309337371fcdbb` |
| `foregs-humus` | 1,111 | 48 | `cf5cef52177eb0d3b75d47270ebda2228f883590256f830bb4e746f67bd32eb1` | `00739879086c5e3bb3d70624e97f6ca084d60507da7b03ca9a3d8642e3968d64` |
| `foregs-stream-water` | 808 | 48 | `a5e5c23eeed54ab1f686637738fb86defc6251b6fc2f486e93ccd98d1a7aed11` | `d7010d0d74ea551a3d82316b530cfae033e410e48c4c9cb932b38ca243aefa5b` |
| `foregs-stream-sediment` | 3,393 | 48 | `2f6810d81624a26d901b1c9487c556ba9a5c7c7d2dd5d900eb119f3956650490` | `8a0f97953f2ff8ab6d0538e0c25b663ae6d793487fef89462b8ccc072abd4c91` |
| `foregs-floodplain-sediment` | 2,935 | 48 | `6011bfcad51ec4ac488fd76958a317a09ca1efbac1e196fc7671991a6aa900d3` | `da77e2ec474f6a22b9465ed059eee07812dbf7723c7a83de8041ce7fc45b3284` |

### FOREGS 复现与边界检查

- 六个来源均用同一份 hash 校验缓存、48 条观测和固定 `generated_at=2026-08-06T08:00:00Z` 在独立临时目录重建；CSV、JSONL 和 manifest 均逐字节一致。
- 另从官方 GTK 地址在线重取 837,779-byte `Topsoil.zip`，实测 SHA-256 为 `ac23bffd5e116545a8c5618c943c75d995e81cdf5adc6d2902238d2e11e40357`；在线下载、解压、4,195 行解析和 48 条小样生成全部通过，随后两次离线缓存重放逐字节一致。
- 缓存模式只沿用已有在线获取记录的原始时间；手工填充但 hash 已验证的缓存不伪造 `retrieved_at`，避免把每次本地校验时间写成来源获取时间。
- 每个来源准备 30 条分层人工复核记录，机器预检均为 30/30 PASS；`completed_comparisons` 仍为 0，因此来源保持 `normalized_analysis`，不冒充 `benchmark_ready`。
- 总量、王水可浸出、温和硝酸可浸出和溶解态保持不同 `measurement_basis`；CSV 中恰好等于 `DL/2` 的值只标记为“可能的上游替代”，不直接断言为检出或删失。

## 2026-08-06 18:05 CST：AfSIS Phase I V2.0 扩展

| 来源 | 原始样品行 | fixture 观测 | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---:|---|---|
| `afsis-phase-i-wet-chemistry` | 2,002 | 48 | `28927291305197ccfa75bd92c3e2f6c9fe366d10bfb04347c52b20918405c376` | `0d241dfca9acedd34d2e898d9355f529f01b7ce872962319ea8ed267094600af` |

全量对账固定三份 original 文件和 publisher MD5/SHA-256，核实 2,002 个唯一 SSN/RES.ID、18 个国家标签、51 个国家-站点对、1,876 个完整坐标对和六目标元素各 2,002 个数值。30 条 review 覆盖所有国家标签、上下层、缺坐标、负数、低于 DL、DL–QL 和高于 QL 类别，自动检查 30/30 PASS、人工字段保持空白。fixture 只选 12 个国家标签的正值完整坐标行，原国家名和独立规范名同时保留。

### 十四来源联合回归

联合四介质 fixture 在保留主线 108 条 USGS 三土层样本并加入 AfSIS 后共有 796 条观测，标准化前后均为 93 个比较分区，其中水体 18 个。完整工作流成功标准化 796/796 条记录；700/796 条具有有效 canonical 坐标，GEOROC 与 AfSIS 共 96 条 reported coordinates 因 datum/CRS 未证实而失败关闭。流程保留 23 条已确认删失观测、输出 16 条工程异常候选并生成十文件输出包；异常仅是相对已声明背景组的工程筛查候选，不构成污染、矿化或成因结论。
