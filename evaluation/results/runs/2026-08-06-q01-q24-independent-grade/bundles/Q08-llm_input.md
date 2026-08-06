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

下文提到的 `observations.csv`、`dedup_log.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q08 重复与多方法记录

处理 `inputs/duplicate_records.csv`：

- 仅去除科学字段和 `source_record_id` 完全相同的重复导入行；
- 实验室平行记录必须保留；
- 同一样品不同方法必须保留；
- 坐标相同但 sample_id 不同，不得自动合并。

输出：

- `observations.csv`：保留的记录，至少包含 `raw_row_id,source_record_id,sample_id,method,replicate_group_id,disposition`；
- `dedup_log.csv`：被移除的 raw row，列为 `removed_raw_row_id,duplicate_of_raw_row_id,reason`。

不需要从多方法记录中选“最佳值”。

`observations.csv.disposition` 使用以下冻结值：

```text
kept_original
kept_replicate
kept_method_difference
kept_distinct_sample
```

`dedup_log.csv.reason` 对完全重复导入固定写
`exact_duplicate_import`，不能使用自由文本同义说明。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "platform_reusability",
   "full_credit": "区分导入重复、实验室平行样、方法差异和样品身份。",
   "id": "identity_model",
   "points": 8
  },
  {
   "dimension_id": "engineering_quality",
   "full_credit": "每个被移除行都能在 dedup_log 回链到保留行。",
   "id": "auditability",
   "points": 6
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "未在没有来源特定规则时擅自选最佳分析值。",
   "id": "no_best_value_overreach",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/observations.csv",
  "artifacts/run_manifest.json#/benchmark_evidence/dedup_log.csv"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-QC-002"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-QC-002",
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
   "evidence_points_awarded": 8,
   "evidence_points_possible": 8,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 64,
   "evidence_points_possible": 64,
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
   "evidence": "observations.csv: file"
  },
  {
   "id": "log_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "dedup_log.csv: file"
  },
  {
   "id": "observation_columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv: missing columns=[]"
  },
  {
   "id": "observation_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv: rows=5; expected=5"
  },
  {
   "id": "kept_rows",
   "type": "csv_key_set",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 20,
   "points_possible": 20,
   "evidence": "observations.csv: actual keys=[('D01',), ('D03',), ('D04',), ('D05',), ('D06',)]; expected=[('D01',), ('D03',), ('D04',), ('D05',), ('D06',)]"
  },
  {
   "id": "replicate_kept",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "observations.csv key={'raw_row_id': 'D03'} column=disposition actual='kept_replicate' expected='kept_replicate' tol=0.0"
  },
  {
   "id": "method_kept",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "observations.csv key={'raw_row_id': 'D04'} column=disposition actual='kept_method_difference' expected='kept_method_difference' tol=0.0"
  },
  {
   "id": "same_coordinate_samples",
   "type": "text_contains_all",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv: missing terms=[]"
  },
  {
   "id": "dedup_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "dedup_log.csv: rows=1; expected=1"
  },
  {
   "id": "dedup_reason",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "dedup_log.csv key={'removed_raw_row_id': 'D02'} column=reason actual='exact_duplicate_import' expected='exact_duplicate_import' tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/observations.csv
```
raw_row_id,source_record_id,sample_id,analyte,value,unit,method,lab,replicate_group_id,latitude,longitude,disposition
D01,SR001,A1,Cu,50,mg/kg,ICP-MS,LAB-X,,10,20,kept_original
D03,SR002,A1,Cu,51,mg/kg,ICP-MS,LAB-X,RG-A1,10,20,kept_replicate
D04,SR003,A1,Cu,48,mg/kg,XRF,LAB-Y,,10,20,kept_method_difference
D05,SR004,B1,Cu,30,mg/kg,ICP-MS,LAB-X,,11,21,kept_original
D06,SR005,B2,Cu,30,mg/kg,ICP-MS,LAB-X,,11,21,kept_distinct_sample
```

### artifacts/run_manifest.json#/benchmark_evidence/dedup_log.csv
```
removed_raw_row_id,duplicate_of_raw_row_id,reason
D02,D01,exact_duplicate_import
```
