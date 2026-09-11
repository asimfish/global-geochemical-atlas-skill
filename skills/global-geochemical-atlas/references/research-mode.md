# research_mode：可选研究后处理层契约

`research_mode` 是叠加在一次**已完成并通过校验**的图谱运行之上的确定性后处理层。它不采集新数据、不修改任何核心产物、不改变十八文件契约，只把已有证据重组为三类面向气候与地球科学研究者的产品：

1. **研究队列构建**（`analysis_cohorts.csv` + `analysis_cohort_exclusions.csv`）：哪些记录可以相互比较，哪些不能、为什么。
2. **环境背景融合**（`research_context.csv`）：以独立样品为单位汇总本次运行内已有证据的环境背景（岩性、地质单元、沉积环境、水体类型、深度、粒级、几何纬度带）。
3. **数据缺口采样建议**（`sampling_priority.geojson`）：把修复队列与单一血缘主导的队列转成可排序的下一批检索/采样候选区。

每次运行同时输出 `research_products_receipt.json`（model-card 式收据：输入 hash、参数、计数、限制与不可宣称事项）。

## 运行方式

```bash
python scripts/build_research_products.py \
  --output-dir OUTPUT_DIR \
  --research-dir OUTPUT_DIR/research \
  --minimum-confidence medium
```

- `--output-dir`：一次已完成运行的根目录，必须含 `geochemistry.csv`、`d1_repair_queue.json`、`sources_and_confidence.json`、`run_summary.json`。
- `--research-dir`：研究产品输出目录，默认 `OUTPUT_DIR/research`；不得写回核心十八文件所在的根目录文件名。
- `--minimum-confidence`：记录级 `workflow_usability` band 下限（`low|medium|high`），默认 `medium`。

核心运行时只用 Python 标准库、单次流式扫描数据库、输出全部按稳定键排序，满足 2 CPU / 4 GB / 无 GPU 沙箱与确定性复现要求。

## 队列（cohort）定义

队列键 = `element × medium × sample_type × grain_fraction × measurement_basis × method_family × digestion_or_extraction × unit_layer`。只有同一队列内的定量值默认可以相互比较；跨队列比较必须由研究者显式论证。

记录级准入：元素与介质非空，且 `operational_confidence.quality_dimensions.workflow_usability.band ≥ minimum_confidence`。进入队列后按三类记账：

- `quantified`：`censored=false` 且有 `normalized_value`；
- `censored`：删失记录（保留 qualifier，不插补、不进入定量统计）；
- `not_normalized`：非删失但无标准化值（单位/基准不可转换）。

`quantified_fraction = quantified / (quantified + censored + not_normalized)`。

### 可比性分层（tier）

| tier | 条件 | 含义 |
|---|---|---|
| `analysis_ready` | 定量样品 ≥ 20 且 quantified_fraction ≥ 0.7 且来源 ≥ 2 且最大单源占比 ≤ 0.9 | 可用于背景值、区域比较等正式分析 |
| `single_lineage_ready` | 定量样品 ≥ 20 且 quantified_fraction ≥ 0.7，但仅 1 个来源或单源占比 > 0.9 | 统计量充足但缺独立血缘，结论受单源系统偏差风险约束 |
| `exploratory_only` | 定量样品 ≥ 8 | 仅可探索性浏览，不得进入正式统计 |
| `insufficient_background` | 其余 | 不可比较，只能作为覆盖缺口证据 |

阈值与 D2 异常筛查的 production 背景组门禁（n≥20、quantified≥70%）保持一致；tier 只描述“当前证据下的可比性”，不是数据质量或科学正确性评级。

## 环境背景融合的证据边界

`research_context.csv` 只汇总**本次运行内已有逐行证据**的背景字段（岩性、匹配地质单元、沉积环境、水体类型、深度、粒级、采样时间）。`latitude_band` 是按 |纬度| 划分的纯几何带（tropical <23.5°、subtropical <35°、temperate <55°、subpolar <66.5°、polar ≥66.5°），**不是气候观测，不得当作气候变量使用**。

外部环境协变量（ERA5-Land 气候、HydroBASINS 流域、SoilGrids 土壤性质）仅作为**声明的扩展接口**写入收据的 `external_covariate_interface`，本层不下载、不联结、不代填；接入时必须走 D1 来源准入与证据链流程。

## 采样建议的证据规则

`sampling_priority.geojson` 的两类 feature：

- `coverage_repair_task`：逐条来自 `d1_repair_queue.json`，保留 task_id、国家/宏区、优先级、reason codes、所需元素与介质、已观测覆盖与发现策略；几何为任务 bbox，**是检索/采样建议范围，不是行政或科学边界**。
- `single_source_dominated_cohort`：来自 tier 为 `single_lineage_ready` 的队列，几何为该队列定量记录的 bbox；建议动作是补充独立血缘来源，而非在原区域重复采样。

排序键 = (`priority`, `task_id`) 与 (`dominant_share` 降序, `cohort_id`)，全部确定性。空间空白 ≠ 自然界无信号；未检索到 ≠ 不存在。

## 不可宣称事项

- 队列、背景表与采样建议都是**筛查与数据准备产品**，不是污染、矿化、风化速率或气候机制结论。
- 本层不建插值面、不补造观测、不合并不可比层。
- 收据中的 hash 只证明字节一致；tier 只证明当前证据满足对应规则。
