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

下文提到的 `normalized_observations.csv`、`group_summary.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q09 介质、相态和基准隔离

标准化 `inputs/mixed_media.csv`，但不得把不可比记录强行合并。

- 固体质量/质量统一到 `mg/kg`；
- 水体质量/体积统一到 `ug/L`；
- 不在没有含水率时把湿基换成干基；
- dissolved 与 total 不自动合并；题中 `filtered_dissolved` 映射到 dissolved family；
- `comparison_group` 为 `medium|basis|phase_family`。

输出 `normalized_observations.csv` 与按 comparison_group 汇总的 `group_summary.csv`。汇总使用非删失记录中位数，且必须保留组内单位。

`comparison_group` 必须按冻结的 `medium|basis|phase_family` 三段格式输出。例如湿基土壤 total 为 `soil|wet|total`，aqueous 水体的 dissolved family 为 `water|aqueous|dissolved`。不得使用自由文本同义标签。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "固体质量分数与水体质量浓度保持独立单位空间。",
   "id": "media",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "湿基记录在无含水率时不伪装成干基。",
   "id": "basis",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "dissolved family 与 total 不混合，并保留原 phase。",
   "id": "phase",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/normalized_observations.csv",
  "artifacts/run_manifest.json#/benchmark_evidence/group_summary.csv"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-NORM-003"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-NORM-003",
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
   "evidence_points_awarded": 8,
   "evidence_points_possible": 8,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "platform_reusability",
   "weight": 0.14,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 72,
   "evidence_points_possible": 72,
   "evidence_score": 100.0,
   "status": "scored"
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
   "id": "observations_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "normalized_observations.csv: file"
  },
  {
   "id": "summary_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "group_summary.csv: file"
  },
  {
   "id": "observation_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_observations.csv: rows=6; expected=6"
  },
  {
   "id": "group_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "group_summary.csv: rows=3; expected=3"
  },
  {
   "id": "water_conversion",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "normalized_observations.csv key={'record_id': 'M03'} column=normalized_value actual='20' expected=20 tol=1e-06"
  },
  {
   "id": "water_unit",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "normalized_observations.csv key={'record_id': 'M03'} column=normalized_unit actual='ug/L' expected='ug/L' tol=0.0"
  },
  {
   "id": "wet_group_separate",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "normalized_observations.csv key={'record_id': 'M02'} column=comparison_group actual='soil|wet|total' expected='soil|wet|total' tol=0.0"
  },
  {
   "id": "dissolved_family",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "normalized_observations.csv key={'record_id': 'M05'} column=comparison_group actual='water|aqueous|dissolved' expected='water|aqueous|dissolved' tol=0.0"
  },
  {
   "id": "ugkg_conversion",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "normalized_observations.csv key={'record_id': 'M06'} column=normalized_value actual='25' expected=25 tol=1e-06"
  },
  {
   "id": "dry_median",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "group_summary.csv key={'comparison_group': 'soil|dry|total'} column=median_value actual='25' expected=25 tol=1e-06"
  },
  {
   "id": "water_median",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "group_summary.csv key={'comparison_group': 'water|aqueous|dissolved'} column=median_value actual='20' expected=20 tol=1e-06"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/normalized_observations.csv
```
record_id,element,reported_value,reported_unit,medium,basis,phase,normalized_value,normalized_unit,comparison_group,conversion_rule
M01,Pb,25,mg/kg,soil,dry,total,25,mg/kg,soil|dry|total,identity_mg_per_kg
M02,Pb,30,mg/kg,soil,wet,total,30,mg/kg,soil|wet|total,identity_mg_per_kg
M03,Pb,0.02,mg/L,water,aqueous,dissolved,20,ug/L,water|aqueous|dissolved,mg_per_l_times_1000_to_ug_per_l
M04,Pb,100,ug/g,soil,dry,total,100,mg/kg,soil|dry|total,ug_per_g_to_mg_per_kg
M05,Pb,20,ug/L,water,aqueous,filtered_dissolved,20,ug/L,water|aqueous|dissolved,identity_ug_per_l
M06,Pb,25000,ug/kg,soil,dry,total,25,mg/kg,soil|dry|total,ug_per_kg_to_mg_per_kg
```

### artifacts/run_manifest.json#/benchmark_evidence/group_summary.csv
```
comparison_group,element,normalized_unit,n,median_value
soil|dry|total,Pb,mg/kg,3,25
soil|wet|total,Pb,mg/kg,1,30
water|aqueous|dissolved,Pb,ug/L,2,20
```
