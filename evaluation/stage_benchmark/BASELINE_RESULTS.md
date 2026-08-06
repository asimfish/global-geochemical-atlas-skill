# D2 四层验证基线结果

运行日期：2026-08-05
被测版本：`d2-interface-v2` / `d2-pipeline-v2`
总体状态：`pass_with_findings`

## 1. 结果摘要

| 验证层 | 数据 | 阻断检查 | 评审检查 | 结果 |
|---|---|---:|---:|---|
| D2 独立全面测试 | 规则矩阵 + 10,000 条资源冒烟 | 88/88 通过 | 2/3 通过 | `pass_with_findings` |
| 合成 D1→D2→D3 | 19 条人工边界金标准 | 25/25 通过 | 1/2 通过 | `pass_with_findings` |
| 合成 D3 独立消费 | D2 八项公共输出 + 四项产品验收 | 18/18 通过 | 无 | `pass` |
| **真实 D1→D2→D3 完整基线** | **4 个公开产品，40,131 条测定** | **42/42 通过** | **2/5 通过** | **`pass_with_findings`** |
| **全球 D1→D2→D3 基准** | **5 个公开产品，19,455 条测定** | **37/37 通过** | **0/5 通过** | **`pass_with_findings`** |

这里的 `pass_with_findings` 不是“差不多通过”：所有阻断项均通过，但报告故意保留真实来源暴露的
接口/数据覆盖问题，便于 D1、D2、D3、E1、E2 分工处理。

机器结果：

- [本地组合摘要](runs/latest/summary.json)
- [D2 独立测试报告](runs/latest/isolated_report.json)
- [合成全流程报告](runs/latest/e2e/e2e_report.json)
- [真实数据完整报告](runs/real-latest/real_data_report.json)
- [真实数据离线交互地图](runs/real-latest/d3/atlas.html)
- [真实 D2 标准化数据库](runs/real-latest/d2/geochemistry.csv)
- [真实 QC 报告](runs/real-latest/d2/qc_report.json)
- [真实异常报告](runs/real-latest/d2/anomaly_report.json)
- [真实来源与置信度说明](runs/real-latest/d3/source_confidence.json)
- [真实异常区域 GeoJSON](runs/real-latest/d3/anomaly_regions.geojson)
- [异常区域方法与未上图清单](runs/real-latest/d3/anomaly_region_report.json)
- [四项交付物哈希清单](runs/real-latest/d3/showcase_manifest.json)
- [全球 Agent 基准运行指南](GLOBAL_BENCHMARK_FOR_AGENTS.md)

`runs/` 是本地验证证据并已加入 `.gitignore`；D2 全量输出约 98.8 MB，不进入最终提交仓库。

## 2. 美国完整 holdout 是什么

| 来源 | 介质 | 进入 D2 的测定数 | 关键真实特征 |
|---|---|---:|---|
| USGS DS801 | 0–5 cm 表层土壤 | 33,999 | 4,857 样点、7 元素、`<`、`mg/kg`/`wt. %`、WGS84、多方法/消解 |
| USGS RASS OFR 99-433 Circle | 河流沉积物 | 5,688 | 1,422 筛选样品、4 元素、N/L/G/H/B、NAD27、历史方法与粒级差异 |
| USGS Taylor Mountains OFR 2007-1196 v1.1 | 岩石 | 354 | 59 样品、6 元素、裸 `%`/ppm、`<`、岩性/地层、NAD27、ICP55 |
| WQP `USGS-01594440` | 地表水 | 90 | 砷的 dissolved/suspended/total、未检出与检出限分列、方法缺失、NAD83 |

8 个数据/元数据文件共 2,713,710 bytes，全部以来源 URL、查询、访问日期、许可、版本、字节数和
SHA-256 固定；细节见 [真实数据说明](real-data/README.md) 和
[来源契约](contracts/real-sources.json)。运行时先断网校验，再进入 D1 适配器。

## 3. 全球真实基准指标

| 指标 | 结果 |
|---|---:|
| 公开数据集 / 冻结资源 | 5 / 11 |
| 冻结 fixture 大小 | 2,155,895 bytes |
| D1 输入 / D2 输出记录 | 19,455 / 19,455 |
| 岩石 / 土壤 / 沉积物 / 水体 | 7,951 / 8,452 / 2,396 / 656 |
| 覆盖洲 | 非、南极、亚、欧、北美、大洋、南美 |
| GEMStat 明确国家 | 35 |
| 非空洲—介质单元 | 13/28 |
| 成功得到 normalized value | 19,187 |
| 删失/限定记录 | 248 |
| 可进入地图的测定 | 19,435 |
| 完成分析的异常背景组 | 132 |
| 候选异常 / 异常区域网格 / 候选聚集区 | 302 / 156 / 17 |
| D2 八项输出大小 | 约 57.3 MB |
| 离线交互地图大小 | 约 5.14 MB |
| 完整流程 wall time | 约 4.87 秒 |

全球层的 5 个 review finding 不是候选 D2 的阻断失败，而是必须披露的来源边界：

- 只有 13/28 个洲—介质单元非空；
- 只有 55.965% 测定有显式分析方法；
- 只有 3.12% 测定公布或可从坐标范围计算不确定性；
- GEOROC 以十进制度范围发布坐标，但未声明 geodetic datum；
- 当前 GEMStat 目标元素水体切片只覆盖亚、欧、北美、南美四洲。

完整复现命令：

```bash
python3 evaluation/d2-validation/scripts/run_global_data_suite.py \
  --output-dir /tmp/d2-global-baseline
```

通过门槛是 `global_data_report.json` 中 `counts.blocking.failed == 0`。状态为
`pass_with_findings` 是预期结果；如果 Agent 把上述真实缺口填造成“已完整覆盖”，应视为科学性回归。

## 4. 美国真实完整基线指标

| 指标 | 结果 |
|---|---:|
| D1 输入 / D2 输出记录 | 40,131 / 40,131 |
| 唯一 record ID | 40,131 |
| 成功得到 normalized value | 35,585 |
| 删失/未检出/trace 记录 | 4,375 |
| 可进入地图的 WGS84 测定 | 33,999 |
| 因未重投影而停止上图的 NAD27/NAD83 测定 | 6,132 |
| 完成分析的独立异常背景组 | 13 |
| 候选异常 | 663 |
| 有合格坐标并进入区域聚合的候选异常 | 638 |
| 因坐标 QC 未进入区域聚合的候选异常 | 25 |
| 2° 元素—介质异常网格 | 272 |
| 达到门槛的候选聚集区 | 57 |
| 高/低工作流置信度 | 33,887 / 6,244 |
| D1 + D2 + D3 + fixture 校验耗时 | 约 7.14 秒 |
| D2 八项输出大小 | 约 98.78 MB |
| 离线交互地图大小 | 约 7.19 MB |

663 条只能称为“相对于声明背景组的候选异常”；其中 638 条带合格坐标，聚合为 272 个 2° 网格，
57 个网格达到“至少 3 个异常且至少 10 个同组观测”的候选聚集门槛。其余 25 条因 NAD27 尚未
安全转换而留在点级异常文件和未上图清单。报告和 GeoJSON 明确标注无因果解释，不代表污染、
矿化或地质成因；网格也不是地质边界。

## 5. 真实数据已经发现并修复的问题

### 5.1 `wt. %` 真实写法未被识别

USGS DS801 单位行使用 `wt. %`（点号后有空格）。旧规则先匹配 `wt.%`、后删除空格，导致 Fe
产生 `UNSUPPORTED_UNIT`。真实金标准 `C-328818 Fe` 因此无法从 `0.52 wt. %` 转为
`5200 mg/kg`。

现已在 D2 和最终 Skill 的标准化脚本中增加精确别名 `wt.% → wt%`。重跑后该金标准通过，且
`conversion_factor=10000` 可追溯。

### 5.2 DS801 的 `N.S.` 不是唯一实验室 ID

完整 4,857 行中有 16 个无样品站点把 `Top5_LabID` 写成相同字面量 `N.S.`。小样没暴露此问题；
全量首次运行保留 39,777 行，但只得到 39,672 个唯一 record ID。

真实 D1 适配器现对这类记录使用 `SiteID` 生成 `site-<SiteID>-no-sample`，不改变正常 LabID，
不删除无样品记录。加入岩石 holdout 后全量重跑仍为 40,131/40,131 ID 唯一。

### 5.3 来源原始 qualifier 已贯通 D2 公共接口

真实首轮验证发现 D1 的 `source_qualifier_raw` 没有进入 D2 公共 CSV。现已把该字段加入输入映射、
标准化记录 Schema、`geochemistry.csv` 和样点 GeoJSON；canonical `value_qualifier` 仍独立保留。
人工金标准已验证 RASS `N`/`L`、Taylor `<` 和 WQP `Not Detected` 均可回溯。

### 5.4 异常 GeoJSON 已补充自描述版本

`anomalies.geojson` 顶层现包含 `interface_version=d2-interface-v2` 和
`method_version=d2-robust-mad-v2`，单独转交文件时也能识别契约和方法版本。

### 5.5 版本化岩性与地层上下文已实际贯通

Taylor 岩石数据把 `RockName`、`Rock Formation` 及 FGDC 元数据版本送入 D2。人工金标准验证
`C-289853 Ni` 保留 `siltstone, claystone, mudstone`、`Kuskokwim(?)`、来源 URL、v1.1 版本和
`source_table_reported` 匹配方法；问号不会被擅自删掉。真实地质上下文覆盖率为 0.7476%，因此
“至少存在版本化地质背景”的评审项已通过，但这不代表其他介质已有地质空间匹配。

## 6. 当前美国真实数据 Findings

### A. 岩石、沉积物和水体尚未完成真实 CRS 重投影

RASS 与 Taylor 为 NAD27，WQP 站点为 NAD83。当前适配器没有安装/伪造空间转换，因此 D2 正确增加
`UNSUPPORTED_SOURCE_CRS` 并将 6,132 条 canonical 坐标置空。目前 D3 地图只有土壤介质。

这不是让 D2 放宽校验的理由。D1 应提供真实的 EPSG 转换、转换库/网格版本、方法名和误差说明，
再填写 `coordinate_transform_method`。

### B. Taylor 岩石 Fe 的裸 `%` 尚未绑定质量基准

Taylor 的 59 条 Fe 结果以裸 `%` 发布。当前 D2 按既定安全规则拒绝把它自动当作 `wt.%`，保留
原值并产生 `UNSUPPORTED_UNIT`；因此不会未经证据就输出 mg/kg。D1 需要从来源字典明确绑定质量
分数语义，再用显式转换决策传给 D2。这个缺口不会影响同表 Cr、Cu、Ni、Pb、Zn 的 ppm 标准化。

### C. WQP 历史结果有 63 条缺少分析方法

全体记录的方法完整率为 99.8430%，缺失集中在 90 条 WQP 历史结果中的 63 条。D2 没有猜测方法，
正确产生 `MISSING_ANALYTICAL_METHOD` 并降低工作流置信度。D3 必须在详情和筛选中保持该缺失可见。

## 7. 合成层保留的 Findings

### D. 不同来源行 ID 会遮蔽重复候选

现有 `duplicate_key` 包含 `source_record_id`，因此不同源行对同一次测定的重复收录可能不被标记。
建议保留两级 flag：完全重复导入和跨行/跨源候选重复；只标记，不自动删行。

## 8. 独立与合成层仍然通过的能力

- 固体/水体单位矩阵、16 个氧化物白名单、歧义单位失败关闭；
- `<`、`ND`、`BDL`、`trace` 与 missing reason 分离，绝不插补为零；
- 坐标交换、零岛、bbox、日期变更线和非 WGS84 边界；
- 置信度分量、error cap、来源/方法缺失降分；
- n=20、70% quantified fraction、MAD=0、高/低候选异常和方法/消解分组；
- 输入倒序、统一比例缩放和等价单位变形测试；
- D2 八项输出确定性、manifest 哈希与 D3 离线消费。

10,000 条独立资源冒烟耗时约 3.24 秒，`tracemalloc` 峰值约 36.8 MiB，记录保留
10,000/10,000。

## 9. 当前判断

D2 不再只是“规则看起来对”：它已在美国完整 holdout 和七洲联合基准两套真实数据上运行，
合计处理 59,586 条测定，覆盖岩石、土壤、沉积物和水体。D3 已把比赛要求的交互地图、标准化数据库、
来源与置信度说明、异常区域结果全部接入阻断验收。下一步不是再用“全球”两字包装缺口，而是优先扩充
当前 15 个空的洲—介质单元，并增加可版本化的地质单元空间匹配金标准。
