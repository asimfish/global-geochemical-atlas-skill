# D1 demo 生成与证据链测试记录

核验日期：2026-08-05。fixture 仅用于流水线演示，均声明 `not_for_scientific_interpretation: true`。

## 已提交 fixture

| 来源 | 观测数 | As/Cu/Ni/Zn | `demo_input.csv` SHA-256 | `sources.jsonl` SHA-256 |
|---|---:|---|---|---|
| GEOROC Archaean Cratons 12.0 | 48 | 各 12 条 | `382148f96b6e9f5c4c8beecd696d38921a2413e2a7af69e0d17c26be30291751` | `45d279d0b6fb0b9f9ab4a4840015556e6ce6736f6c3aa3178c5525746d19ef64` |
| USGS Data Series 801 | 108 | 各 27 条 | `fcdfe90941beab0f64fcaa42c7c4277ae50dc719cd6ea8f9abeaed575d205b67` | `4766e7cf9f42b74881b56a6e66681eda24994c29fd8c9c052a4d1c0c63c45031` |

两个 `run_manifest.json` 均绑定 CSV 与 JSONL 哈希、源文件 URL/SHA-256、生成参数和记录数。相同注册表、验证缓存、筛选参数及固定 `--generated-at` 可字节级复现三份 fixture 文件。

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

当前结果为 D1/D2/D3 共 144 项契约检查通过、self-test 68 项通过。D2 生成 `d2-confidence-v2` 及分量定义；`d2-interface-v2` 与 `d2-robust-mad-v2` 分别锁定异常输出接口和算法版本，并保留 `source_qualifier_raw` 与 canonical `value_qualifier`。D1 只验证来源 sidecar、acquisition manifest、输入和报告哈希，不重新计算置信度。
