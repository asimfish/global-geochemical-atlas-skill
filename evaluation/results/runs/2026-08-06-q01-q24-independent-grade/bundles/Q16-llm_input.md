TASK:
<!-- candidate-visible-contract-v1:start -->
## 答题 AI 可见的机器提交契约

本题逻辑输出的精确容器、格式、CSV 列和 JSON 结构位于
`task.json.candidate_visible_contract`。该字段是题面的一部分，答题 AI 必须读取并遵守。

特别是，`format="csv"` 的逻辑证据必须使用 `columns` 加对象数组 `rows`；
每个 row 以列名为键，不得使用依赖位置的数组行。JSON 逻辑证据必须使用
`{"format": "json", "value": ...}`。未声明的题目专用物理文件不得创建。
<!-- candidate-visible-contract-v1:end -->

<!-- e1-alignment-v1 -->
## E1 统一交卷要求

只生成 `task.json.required_outputs` 列出的十个 E1 物理产物，并保持 `artifacts/` 固定路径。不得另外创建题目专用文件。

下文提到的 `cells.csv`、`heatmap_config.json`、`heatmap.html` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q16 热力图与网格聚合

按 `inputs/visualization_policy.json` 对 `inputs/cell_observations.csv` 预聚合，输出：

- `cells.csv`：cell_id、sample_count、quantified_count、median_value、censored_fraction；
- `heatmap_config.json`：冻结 aggregation、radius、color domain，并声明 sample-count 与 censored-fraction 图层；
- `heatmap.html`：包含标识 `GGA-HEATMAP-Q16`，以及 `sample_count`、`median_value` 字段说明。

删失值计入 sample_count 和 censored_fraction，但不进入 median。热力图只能称为探索性聚合视图，不得把样本密度表述为浓度。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "清楚区分 sample_count 与 median concentration。",
   "id": "density",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "删失值影响覆盖/QC 图层但不伪装成精确浓度。",
   "id": "censoring",
   "points": 6
  },
  {
   "dimension_id": "engineering_quality",
   "full_credit": "固定聚合、radius 和 color domain，并使用预计算 cells。",
   "id": "reproducibility",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/cells.csv",
  "artifacts/run_manifest.json#/benchmark_evidence/heatmap_config.json",
  "artifacts/run_manifest.json#/benchmark_evidence/heatmap.html"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-MAP-002"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-MAP-002",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 80,
 "evidence_points_possible": 80,
 "dimensions": [
  {
   "dimension_id": "scientific_credibility",
   "weight": 0.25,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "engineering_quality",
   "weight": 0.3,
   "evidence_points_awarded": 78,
   "evidence_points_possible": 78,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "platform_reusability",
   "weight": 0.14,
   "evidence_points_awarded": 2,
   "evidence_points_possible": 2,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "innovation_ecosystem",
   "weight": 0.1,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "open_source_potential",
   "weight": 0.06,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  }
 ],
 "checks": [
  {
   "id": "cells_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "cells.csv: file"
  },
  {
   "id": "config_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "heatmap_config.json: file"
  },
  {
   "id": "html_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "heatmap.html: file"
  },
  {
   "id": "cell_count",
   "type": "csv_row_count",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "cells.csv: rows=3; expected=3"
  },
  {
   "id": "h001_median",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "cells.csv key={'cell_id': 'H001'} column=median_value actual='20' expected=20 tol=0.0"
  },
  {
   "id": "h001_censored",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "cells.csv key={'cell_id': 'H001'} column=censored_fraction actual='0.25' expected=0.25 tol=1e-06"
  },
  {
   "id": "h002_median",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "cells.csv key={'cell_id': 'H002'} column=median_value actual='200' expected=200 tol=0.0"
  },
  {
   "id": "h003_counts",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "cells.csv key={'cell_id': 'H003'} column=quantified_count actual='1' expected=1 tol=0.0"
  },
  {
   "id": "h003_censored",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "cells.csv key={'cell_id': 'H003'} column=censored_fraction actual='0.6666666666666666' expected=0.6666666667 tol=1e-06"
  },
  {
   "id": "aggregation_fixed",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "heatmap_config.json path=aggregation actual='precomputed_cell_median' expected='precomputed_cell_median'"
  },
  {
   "id": "color_domain",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "heatmap_config.json path=color_domain_mg_kg actual=[0, 300] expected=[0, 300]"
  },
  {
   "id": "required_layers",
   "type": "json_array_contains",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "heatmap_config.json path=layers missing=[]"
  },
  {
   "id": "html_size",
   "type": "file_min_bytes",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "heatmap.html: 924 bytes; required >= 200"
  },
  {
   "id": "html_fields",
   "type": "text_contains_all",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 2,
   "points_possible": 2,
   "evidence": "heatmap.html: missing terms=[]"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/cells.csv
```
cell_id,sample_count,quantified_count,median_value,censored_fraction
H001,4,3,20,0.25
H002,3,3,200,0
H003,3,1,5,0.6666666666666666
```

### artifacts/run_manifest.json#/benchmark_evidence/heatmap_config.json
```json
{
 "task_id": "GGA-MAP-002",
 "policy_version": "q16-vis-1",
 "aggregation": "precomputed_cell_median",
 "radius_pixels": 30,
 "color_domain_mg_kg": [
  0,
  300
 ],
 "layers": [
  "median_value",
  "sample_count",
  "censored_fraction"
 ],
 "interpretation": "exploratory_precomputed_cell_aggregation; sample_count is sampling density, not concentration; censored values excluded from median and color scale"
}
```

### artifacts/run_manifest.json#/benchmark_evidence/heatmap.html
```
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>GGA-HEATMAP-Q16</title></head>
<body>
<h1>GGA-HEATMAP-Q16 exploratory precomputed heatmap</h1>
<p>Identifier: GGA-HEATMAP-Q16. Aggregation: precomputed_cell_median. This is an exploratory
aggregated view. sample_count = number of samples per cell (sampling density,
NOT concentration). median_value = median of quantified values in mg/kg
(censored values excluded). censored_fraction = fraction of censored samples
per cell. Color domain fixed to [0, 300] mg/kg.</p>
<table border="1" cellpadding="3">
<tr><th>cell_id</th><th>sample_count</th><th>quantified_count</th><th>median_value</th><th>censored_fraction</th></tr>
<tr><td>H001</td><td>4</td><td>3</td><td>20</td><td>0.25</td></tr><tr><td>H002</td><td>3</td><td>3</td><td>200</td><td>0</td></tr><tr><td>H003</td><td>3</td><td>1</td><td>5</td><td>0.6666666666666666</td></tr>
</table>
</body>
</html>

```
