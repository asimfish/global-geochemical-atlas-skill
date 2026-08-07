# USGS 2026 独立岩石来源适配说明

## 结论

`usgs-utah-volcanic-whole-rock` 已作为非 GEOROC 的独立岩石血缘接入。生产适配来源为 USGS 数据发布 [10.5066/P1NZXUZF](https://doi.org/10.5066/P1NZXUZF)，包含 4 个 ScienceBase 子数据集的固定 CSV、数据字典、方法和检出限表。它只代表美国西北犹他及邻近爱达荷、内华达的火山岩离散样品，不能表述为美国或全球岩石覆盖。

首选的 USGS 全国性发布 [10.5066/P1FXE9GK](https://doi.org/10.5066/P1FXE9GK) 已完成官方元数据审计：ScienceBase 登记了 `Geochem_DataRelease_2025_11_18.parquet.zip`、297,251,708 字节和文件 ID `cmi6freth002j0upm7cs35yz0`，但公开 JSON 将文件标为 `published=false`，匿名下载 URI 返回文件管理器 HTML，而不是 Parquet ZIP。因此本轮不把它冒充可执行来源，待稳定公开子文件端点出现后再升级。

## 全量对账

| 指标 | 结果 |
|---|---:|
| 官方 CSV 文件 | 11 个数据、字典、方法或检出限文件 |
| 物理样品行 | 246 |
| 有目标元素的样品行 | 231 |
| 有效坐标行 | 246 |
| 七目标元素测定 | 1,447 |
| 删失测定 | 454 |
| 精确关联方法 | 1,271 |
| 保留多个方法候选 | 176 |
| As / Cr / Cu / Hg / Ni / Pb / Zn | 188 / 284 / 226 / 0 / 295 / 145 / 309 |

四个子数据文件分别为 10、60、85、91 行。USGS Analytical Laboratories 子页面描述为 90 个样品，但发布 CSV 实际有 91 个非空且唯一的 `LAB_ID`；适配器以文件事实为准，并在证据中保留这一差异。

## 原始语义

- 负数是发布者的 `<LDL` 编码。适配器同时保留有符号的 `reported_value`，并输出正的 censor limit、`value_qualifier=<`，不把负值解释为真实浓度。
- UGS-ALS 的 Cu、Ni、Pb、Zn 在部分记录中同时列出 `ME-MS81` 和 `ME-4ACD81`，但单一结果列没有指出胜出方法。176 条测定保留两个候选、`method_scope=candidate_set` 和缺失原因，不从数值或单位猜方法。
- USGS contract-lab 结果通过记录级 `AnalyticalMethods` 与方法表、检出限表真实关联；USGS historical lab 结果通过发布字段后缀和数据字典关联 XRF 或 INAA。
- USGS historical lab CSV 的 `LATITUDE` 列实际为约 -114 至 -112 的西经，`LONGITUDE` 列实际为约 40 至 42 的北纬。适配器保留两个原始字段，并显式记录按合法地理范围交换到经纬度接口的依据。
- 岩性、地质年龄、位置不确定度、实验室、原始样品号、ScienceBase 子项目 ID、DOI 和逐行 source locator 均保留。

## 可重放证据

- 生产 adapter：`scripts/source_adapters.py`
- 全量/候选 profile：`fixtures/source-profiles/usgs-utah-volcanic-whole-rock.json`
- 30 条 Codex 自动审计：`fixtures/four-media/rock/usgs-utah-volcanic-whole-rock/automated_review.json`
- 48 条交换 fixture：`fixtures/source-demos/usgs-utah-volcanic-whole-rock/`
- 31 条源生离线 fixture：`fixtures/source-native/usgs-utah-volcanic-whole-rock/`

在线、缓存和离线测试命令：

```bash
python3 scripts/audit_usgs_utah_volcanic_rock.py --cache-dir /path/to/cache --mode online
python3 scripts/audit_usgs_utah_volcanic_rock.py --cache-dir /path/to/cache --mode cached
python3 scripts/audit_usgs_utah_volcanic_rock.py --cache-dir /unused --mode fixture --skill-dir /tmp/usgs-fixture-output
python3 scripts/test_usgs_utah_volcanic_rock.py
```

所有身份和漂移检查使用 DOI/PID、版本、ScienceBase 文件 ID、文件名、字节数、CSV schema、行数和关键统计；不计算、读取或校验内容哈希。
