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

下文提到的 `coordinate_qc.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q07 坐标 QC

检查 `inputs/coordinates.csv`，输出 `coordinate_qc.csv`：

```text
record_id,sample_id,original_latitude,original_longitude,qc_flags,suggested_latitude,suggested_longitude,eligible_map
```

规则：纬度范围 `[-90,90]`、经度范围 `[-180,180]`；`0,0` 标记为疑似占位；缺失值不可地图化；若交换后范围合法，只能标记 `possible_lat_lon_swap` 并给建议值，不得静默修改；同一 `sample_id` 出现相距明显的坐标时，两条都标记 `sample_coordinate_conflict` 并暂停入图。

多个 flag 使用分号连接并按字母排序；无 flag 留空。

`qc_flags` 只使用以下冻结字符串：

```text
latitude_out_of_range
longitude_out_of_range
possible_lat_lon_swap
possible_zero_zero_placeholder
missing_latitude
missing_longitude
sample_coordinate_conflict
```

例如纬度越界且交换后合法时使用
`latitude_out_of_range;possible_lat_lon_swap`。疑似 `0,0` 占位必须写
`possible_zero_zero_placeholder`，不能缩写为 `possible_placeholder`；缺少纬度或经度分别写 `missing_latitude`、`missing_longitude`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "原坐标始终保留，possible swap 只是建议并进入人工确认。",
   "id": "non_destructive",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "0,0 被视为疑似占位而非自动删除或自动接受。",
   "id": "placeholder",
   "points": 5
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "同 sample_id 冲突不静默选一条，并说明需回查来源。",
   "id": "conflict",
   "points": 7
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/coordinate_qc.csv"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-SPATIAL-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-SPATIAL-001",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 74,
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
   "evidence_points_awarded": 61,
   "evidence_points_possible": 67,
   "evidence_score": 91.044776,
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
   "evidence": "coordinate_qc.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "coordinate_qc.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "coordinate_qc.csv: rows=9; expected=9"
  },
  {
   "id": "p01_valid",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "coordinate_qc.csv key={'record_id': 'P01'} column=eligible_map actual='True' expected=True tol=0.0"
  },
  {
   "id": "p02_lat",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": false,
   "points_awarded": 0,
   "points_possible": 6,
   "evidence": "coordinate_qc.csv key={'record_id': 'P02'} column=qc_flags actual='latitude_out_of_range;possible_lat_lon_swap' expected='latitude_out_of_range' tol=0.0"
  },
  {
   "id": "p03_lon",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "coordinate_qc.csv key={'record_id': 'P03'} column=qc_flags actual='longitude_out_of_range' expected='longitude_out_of_range' tol=0.0"
  },
  {
   "id": "p04_placeholder",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "coordinate_qc.csv key={'record_id': 'P04'} column=qc_flags actual='possible_zero_zero_placeholder' expected='possible_zero_zero_placeholder' tol=0.0"
  },
  {
   "id": "p05_flags",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "coordinate_qc.csv key={'record_id': 'P05'} column=qc_flags actual='latitude_out_of_range;possible_lat_lon_swap' expected='latitude_out_of_range;possible_lat_lon_swap' tol=0.0"
  },
  {
   "id": "p05_suggestion",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "coordinate_qc.csv key={'record_id': 'P05'} column=suggested_longitude actual='120' expected=120 tol=0.0"
  },
  {
   "id": "p05_not_mapped",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "coordinate_qc.csv key={'record_id': 'P05'} column=eligible_map actual='False' expected=False tol=0.0"
  },
  {
   "id": "p06_missing",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "coordinate_qc.csv key={'record_id': 'P06'} column=qc_flags actual='missing_latitude' expected='missing_latitude' tol=0.0"
  },
  {
   "id": "p07a_conflict",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "coordinate_qc.csv key={'record_id': 'P07A'} column=qc_flags actual='sample_coordinate_conflict' expected='sample_coordinate_conflict' tol=0.0"
  },
  {
   "id": "p07b_conflict",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "coordinate_qc.csv key={'record_id': 'P07B'} column=eligible_map actual='False' expected=False tol=0.0"
  },
  {
   "id": "p08_valid",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "coordinate_qc.csv key={'record_id': 'P08'} column=eligible_map actual='True' expected=True tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/coordinate_qc.csv
```
record_id,sample_id,original_latitude,original_longitude,qc_flags,suggested_latitude,suggested_longitude,eligible_map
P01,S01,35,-117,,,,True
P02,S02,95,10,latitude_out_of_range;possible_lat_lon_swap,10,95,False
P03,S03,45,200,longitude_out_of_range,,,False
P04,S04,0,0,possible_zero_zero_placeholder,,,False
P05,S05,120,35,latitude_out_of_range;possible_lat_lon_swap,35,120,False
P06,S06,,10,missing_latitude,,,False
P07A,S07,40,-105,sample_coordinate_conflict,,,False
P07B,S07,40,-90,sample_coordinate_conflict,,,False
P08,S08,-33,151,,,,True
```
