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

下文提到的 `geologic_matches.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q11 地质单元匹配

对 `inputs/points.csv` 与 `inputs/units.geojson` 做点在多边形匹配，并按 `match_policy.json` 输出 `geologic_matches.csv`：

```text
point_id,unit_id,match_status,distance_to_boundary_deg,coordinate_precision_m,match_confidence,qc_flags
```

共享边界上的点记为 `ambiguous_boundary`，不得任意选一侧；无覆盖点记为 `no_match`。距离边界过近或坐标精度过粗都必须降低置信度。

冻结枚举为：

- `match_status`：`matched`、`no_match`、`ambiguous_boundary`；
- `match_confidence`：`high`、`medium`、`low`；
- `qc_flags`：`near_unit_boundary`、`coordinate_precision_coarse`；多个 flag 使用分号连接并按字母排序，无 flag 留空。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "共享边界与近边界是不同情形，均不应高置信。",
   "id": "boundary",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "把点坐标精度纳入匹配置信度，而非只看算法命中。",
   "id": "precision",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "无覆盖时保留 no_match，不使用最近单元强行填补。",
   "id": "no_match",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv",
  "inputs/match_policy.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-SPATIAL-002"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-SPATIAL-002",
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
   "evidence_points_awarded": 5,
   "evidence_points_possible": 5,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "platform_reusability",
   "weight": 0.14,
   "evidence_points_awarded": 8,
   "evidence_points_possible": 8,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 67,
   "evidence_points_possible": 67,
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
   "id": "output_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "geologic_matches.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "geologic_matches.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "geologic_matches.csv: rows=5; expected=5"
  },
  {
   "id": "g01_unit",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "geologic_matches.csv key={'point_id': 'G01'} column=unit_id actual='UNIT-A' expected='UNIT-A' tol=0.0"
  },
  {
   "id": "g01_confidence",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "geologic_matches.csv key={'point_id': 'G01'} column=match_confidence actual='high' expected='high' tol=0.0"
  },
  {
   "id": "g02_boundary",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 9,
   "points_possible": 9,
   "evidence": "geologic_matches.csv key={'point_id': 'G02'} column=qc_flags actual='near_unit_boundary' expected='near_unit_boundary' tol=0.0"
  },
  {
   "id": "g02_confidence",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "geologic_matches.csv key={'point_id': 'G02'} column=match_confidence actual='low' expected='low' tol=0.0"
  },
  {
   "id": "g03_coarse",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "geologic_matches.csv key={'point_id': 'G03'} column=qc_flags actual='coordinate_precision_coarse' expected='coordinate_precision_coarse' tol=0.0"
  },
  {
   "id": "g04_no_match",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "geologic_matches.csv key={'point_id': 'G04'} column=match_status actual='no_match' expected='no_match' tol=0.0"
  },
  {
   "id": "g04_unit_empty",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "geologic_matches.csv key={'point_id': 'G04'} column=unit_id actual='' expected=None tol=0.0"
  },
  {
   "id": "g05_ambiguous",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "geologic_matches.csv key={'point_id': 'G05'} column=match_status actual='ambiguous_boundary' expected='ambiguous_boundary' tol=0.0"
  },
  {
   "id": "g05_unit_empty",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "geologic_matches.csv key={'point_id': 'G05'} column=unit_id actual='' expected=None tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv
```
point_id,unit_id,match_status,distance_to_boundary_deg,coordinate_precision_m,match_confidence,qc_flags
G01,UNIT-A,matched,5,100,high,
G02,UNIT-A,matched,0.0009999999999994458,100,low,near_unit_boundary
G03,UNIT-B,matched,5,2000,low,coordinate_precision_coarse
G04,,no_match,5,100,none,
G05,,ambiguous_boundary,0,100,low,near_unit_boundary
```

### inputs/match_policy.json
```json
{
 "version": "q11-policy-1",
 "boundary_near_threshold_deg": 0.01,
 "coarse_coordinate_threshold_m": 1000,
 "shared_boundary_behavior": "ambiguous_no_assignment",
 "confidence": {
  "clean_interior": "high",
  "near_boundary": "low",
  "coarse_coordinate": "low",
  "no_match": "none",
  "ambiguous": "low"
 }
}
```
