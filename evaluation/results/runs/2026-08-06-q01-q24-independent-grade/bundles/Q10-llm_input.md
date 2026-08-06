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

下文提到的 `observations.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q10 Schema 漂移适配

使用 `inputs/field_mapping.json` 读取两个列名不同的来源文件，生成同一个长表 `observations.csv`：

```text
record_id,source_id,source_record_id,sample_id,latitude,longitude,medium,element,reported_value,reported_unit,normalized_value,normalized_unit
```

两来源中的 Cu 都是固体质量/质量数据；ppm 与 mg/kg 可按题设等价。不得用行号替代 source_record_id，也不得丢失 source_id。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "platform_reusability",
   "full_credit": "字段适配来自显式 mapping，而不是对列位置或名字模糊猜测。",
   "id": "mapping_driven",
   "points": 8
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "record_id 同时包含 source 与 native record identity。",
   "id": "stable_identity",
   "points": 7
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "reported value/unit 与 normalized value/unit 同时存在。",
   "id": "traceability",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/observations.csv",
  "inputs/field_mapping.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-INGEST-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-INGEST-001",
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
   "evidence_points_awarded": 75,
   "evidence_points_possible": 75,
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
   "id": "output_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "observations.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "observations.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "observations.csv: rows=4; expected=4"
  },
  {
   "id": "record_keys",
   "type": "csv_key_set",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 16,
   "points_possible": 16,
   "evidence": "observations.csv: actual keys=[('source_a', 'A-001'), ('source_a', 'A-002'), ('source_b', 'B-101'), ('source_b', 'B-102')]; expected=[('source_a', 'A-001'), ('source_a', 'A-002'), ('source_b', 'B-101'), ('source_b', 'B-102')]"
  },
  {
   "id": "a_sample_mapping",
   "type": "csv_cell",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv key={'source_record_id': 'A-001'} column=sample_id actual='SA1' expected='SA1' tol=0.0"
  },
  {
   "id": "a_coord_mapping",
   "type": "csv_cell",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv key={'source_record_id': 'A-002'} column=longitude actual='-111' expected=-111 tol=0.0"
  },
  {
   "id": "b_medium_mapping",
   "type": "csv_cell",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv key={'source_record_id': 'B-101'} column=medium actual='sediment' expected='sediment' tol=0.0"
  },
  {
   "id": "b_value_mapping",
   "type": "csv_cell",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "observations.csv key={'source_record_id': 'B-102'} column=normalized_value actual='45' expected=45 tol=0.0"
  },
  {
   "id": "a_reported_unit",
   "type": "csv_cell",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "observations.csv key={'source_record_id': 'A-001'} column=reported_unit actual='ppm' expected='ppm' tol=0.0"
  },
  {
   "id": "normalized_units",
   "type": "text_contains_all",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "observations.csv: missing terms=[]"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/observations.csv
```
record_id,source_id,source_record_id,sample_id,latitude,longitude,medium,element,reported_value,reported_unit,normalized_value,normalized_unit
A-001,source_a,A-001,SA1,40,-110,soil,Cu,12,ppm,12,mg/kg
A-002,source_a,A-002,SA2,41,-111,soil,Cu,25,ppm,25,mg/kg
B-101,source_b,B-101,SB1,35,-100,sediment,Cu,30,mg/kg,30,mg/kg
B-102,source_b,B-102,SB2,36,-101,sediment,Cu,45,mg/kg,45,mg/kg
```

### inputs/field_mapping.json
```json
{
 "source_a": {
  "source_record_id": "Record",
  "sample_id": "Sample",
  "latitude": "Latitude",
  "longitude": "Longitude",
  "medium": "Material",
  "Cu": {
   "column": "Cu_ppm",
   "unit": "ppm"
  }
 },
 "source_b": {
  "source_record_id": "source_key",
  "sample_id": "sample_id",
  "latitude": "lat_dd",
  "longitude": "lon_dd",
  "medium": "medium",
  "Cu": {
   "column": "cu_mgkg",
   "unit": "mg/kg"
  }
 }
}
```
