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

下文提到的 `observations.csv`、`qc_report.json`、`sources.jsonl`、`map.geojson`、`anomalies.geojson`、`run_manifest.json`、`summary.md` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q24 端到端小型图谱

使用五个输入资产生成可追溯的小型图谱。必须先做文件完整性和批次准入，再做单位、限定符、坐标、地图和异常。

固定规则：

- SHA-256 与 manifest 不一致的整个来源不得进入 observations；
- 只有 `batch_pass=true` 可进入；
- 固体 mass/mass 的 ppm → mg/kg；水体 mg/L → ug/L，组间不合并；
- `<x` 为左删失，保留 bound/qualifier，不作为精确值；
- 越界坐标进入数据库但不进入地图；
- 异常组按 `medium|basis|phase|element|method`，并要求坐标合法、非删失正值、`n>=20`；
- 合格组使用 log10 median 与 `1.4826*MAD`，`|z|>=3.5`；
- GeoJSON 坐标顺序为 longitude、latitude；每个 feature 必须回链 record_id 和 source_id。

输出：

```text
observations.csv
qc_report.json
sources.jsonl
map.geojson
anomalies.geojson
run_manifest.json
summary.md
```

由于至少一个来源完整性失败且一个分析组不满足异常条件，成功生成其余产物时也应报告 `partial_success` 和退出码 `2`，不能隐藏降级。

异常 GeoJSON 的 `properties.anomaly_type` 固定写
`statistical_relative_enrichment` 或 `statistical_relative_depletion`。
`summary.md` 必须原样包含以下确定性审计标记，并可在其前后补充中文解释：

```text
partial success
Source integrity
censored
invalid coordinate
statistical relative enrichment
does not establish
```


RUBRIC:
```json
{
 "automatic_zero": [
  "使用完整性失败来源",
  "把统计异常断言为矿床、污染源或因果机制",
  "地图 feature 无法回链来源"
 ],
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "来源、record、标准化观测、地图 feature 和异常 feature 可双向回链。",
   "id": "evidence_chain",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "完整性失败、无效坐标、删失和小组样本不足分别降级，不隐藏为 success。",
   "id": "scientific_degradation",
   "points": 5
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "固体 Cu 与水体 Pb 保持单位和分析组隔离。",
   "id": "unit_grouping",
   "points": 4
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "异常算法、背景组、n 和 robust z 明确，且不作因果或矿床结论。",
   "id": "anomaly_scope",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/observations.csv",
  "artifacts/run_manifest.json#/benchmark_evidence/qc_report.json",
  "artifacts/run_manifest.json#/benchmark_evidence/sources.jsonl",
  "artifacts/run_manifest.json#/benchmark_evidence/map.geojson",
  "artifacts/run_manifest.json#/benchmark_evidence/anomalies.geojson",
  "artifacts/run_manifest.json#/benchmark_evidence/run_manifest.json",
  "artifacts/run_manifest.json#/benchmark_evidence/summary.md"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-E2E-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-E2E-001",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 80,
 "evidence_points_possible": 80,
 "dimensions": [
  {
   "dimension_id": "scientific_credibility",
   "weight": 0.25,
   "evidence_points_awarded": 6,
   "evidence_points_possible": 6,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "engineering_quality",
   "weight": 0.3,
   "evidence_points_awarded": 63,
   "evidence_points_possible": 63,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "platform_reusability",
   "weight": 0.14,
   "evidence_points_awarded": 11,
   "evidence_points_possible": 11,
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
   "id": "observations_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "observations.csv: file"
  },
  {
   "id": "qc_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "qc_report.json: file"
  },
  {
   "id": "sources_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "sources.jsonl: file"
  },
  {
   "id": "map_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "map.geojson: file"
  },
  {
   "id": "anomalies_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "anomalies.geojson: file"
  },
  {
   "id": "manifest_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "run_manifest.json: file"
  },
  {
   "id": "summary_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 1,
   "points_possible": 1,
   "evidence": "summary.md: file"
  },
  {
   "id": "observation_count",
   "type": "csv_row_count",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "observations.csv: rows=24; expected=24"
  },
  {
   "id": "source_count",
   "type": "jsonl_row_count",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "sources.jsonl: JSONL rows=2; expected=2"
  },
  {
   "id": "map_count",
   "type": "json_length",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "map.geojson path=features length=23; expected=23"
  },
  {
   "id": "anomaly_count",
   "type": "json_length",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "anomalies.geojson path=features length=1; expected=1"
  },
  {
   "id": "e21_value",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "observations.csv key={'record_id': 'E21'} column=normalized_value actual='500' expected=500 tol=0.0"
  },
  {
   "id": "e22_censored",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "observations.csv key={'record_id': 'E22'} column=censored actual='True' expected=True tol=0.0"
  },
  {
   "id": "e23_not_mapped",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "observations.csv key={'record_id': 'E23'} column=eligible_map actual='False' expected=False tol=0.0"
  },
  {
   "id": "e25_unit",
   "type": "csv_cell",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "observations.csv key={'record_id': 'E25'} column=normalized_unit actual='ug/L' expected='ug/L' tol=0.0"
  },
  {
   "id": "qc_raw",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "qc_report.json path=raw_input_rows actual=25 expected=25"
  },
  {
   "id": "qc_accepted",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "qc_report.json path=accepted_database_rows actual=24 expected=24"
  },
  {
   "id": "qc_integrity_excluded",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "qc_report.json path=excluded_integrity_rows actual=1 expected=1"
  },
  {
   "id": "qc_mapped",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "qc_report.json path=mapped_features actual=23 expected=23"
  },
  {
   "id": "qc_anomaly",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "qc_report.json path=anomaly_features actual=1 expected=1"
  },
  {
   "id": "manifest_status",
   "type": "json_value",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "run_manifest.json path=status actual='partial_success' expected='partial_success'"
  },
  {
   "id": "manifest_exit",
   "type": "json_value",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 2,
   "points_possible": 2,
   "evidence": "run_manifest.json path=exit_code actual=2 expected=2"
  },
  {
   "id": "map_traceability",
   "type": "json_object_has_keys",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "map.geojson path=features.0.properties missing keys=[]"
  },
  {
   "id": "anomaly_id",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 3,
   "points_possible": 3,
   "evidence": "anomalies.geojson path=features.0.id actual='E21' expected='E21'"
  },
  {
   "id": "anomaly_type",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "anomalies.geojson path=features.0.properties.anomaly_type actual='statistical_relative_enrichment' expected='statistical_relative_enrichment'"
  },
  {
   "id": "anomaly_z",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "anomalies.geojson path=features.0.properties.robust_z actual=10.408091969133482 expected=10.4080919691"
  },
  {
   "id": "summary_evidence",
   "type": "text_contains_all",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 2,
   "points_possible": 2,
   "evidence": "summary.md: missing terms=[]"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/observations.csv
```
record_id,source_id,batch_id,medium,basis,phase,element,reported_value,reported_unit,qualifier,censored,normalized_value,normalized_unit,latitude,longitude,eligible_map,eligible_anomaly,qc_flags
E01,SRC-A,BATCH-A,soil,dry,total,Cu,20,ppm,,False,20,mg/kg,30.01,-100.01,True,True,
E02,SRC-A,BATCH-A,soil,dry,total,Cu,21,ppm,,False,21,mg/kg,30.02,-100.02,True,True,
E03,SRC-A,BATCH-A,soil,dry,total,Cu,22,ppm,,False,22,mg/kg,30.03,-100.03,True,True,
E04,SRC-A,BATCH-A,soil,dry,total,Cu,23,ppm,,False,23,mg/kg,30.04,-100.04,True,True,
E05,SRC-A,BATCH-A,soil,dry,total,Cu,24,ppm,,False,24,mg/kg,30.05,-100.05,True,True,
E06,SRC-A,BATCH-A,soil,dry,total,Cu,25,ppm,,False,25,mg/kg,30.06,-100.06,True,True,
E07,SRC-A,BATCH-A,soil,dry,total,Cu,26,ppm,,False,26,mg/kg,30.07,-100.07,True,True,
E08,SRC-A,BATCH-A,soil,dry,total,Cu,27,ppm,,False,27,mg/kg,30.08,-100.08,True,True,
E09,SRC-A,BATCH-A,soil,dry,total,Cu,28,ppm,,False,28,mg/kg,30.09,-100.09,True,True,
E10,SRC-A,BATCH-A,soil,dry,total,Cu,29,ppm,,False,29,mg/kg,30.1,-100.1,True,True,
E11,SRC-A,BATCH-A,soil,dry,total,Cu,30,ppm,,False,30,mg/kg,30.11,-100.11,True,True,
E12,SRC-A,BATCH-A,soil,dry,total,Cu,31,ppm,,False,31,mg/kg,30.12,-100.12,True,True,
E13,SRC-A,BATCH-A,soil,dry,total,Cu,32,ppm,,False,32,mg/kg,30.13,-100.13,True,True,
E14,SRC-A,BATCH-A,soil,dry,total,Cu,33,ppm,,False,33,mg/kg,30.14,-100.14,True,True,
E15,SRC-A,BATCH-A,soil,dry,total,Cu,34,ppm,,False,34,mg/kg,30.15,-100.15,True,True,
E16,SRC-A,BATCH-A,soil,dry,total,Cu,35,ppm,,False,35,mg/kg,30.16,-100.16,True,True,
E17,SRC-A,BATCH-A,soil,dry,total,Cu,36,ppm,,False,36,mg/kg,30.17,-100.17,True,True,
E18,SRC-A,BATCH-A,soil,dry,total,Cu,37,ppm,,False,37,mg/kg,30.18,-100.18,True,True,
E19,SRC-A,BATCH-A,soil,dry,total,Cu,38,ppm,,False,38,mg/kg,30.19,-100.19,True,True,
E20,SRC-A,BATCH-A,soil,dry,total,Cu,39,ppm,,False,39,mg/kg,30.2,-100.2,True,True,
E21,SRC-A,BATCH-A,soil,dry,total,Cu,500,ppm,,False,500,mg/kg,30.21,-100.21,True,True,
E22,SRC-A,BATCH-A,soil,dry,total,Cu,<0.5,ppm,<,True,,mg/kg,31,-101,True,False,
E23,SRC-A,BATCH-A,soil,dry,total,Cu,40,ppm,,False,40,mg/kg,95,-102,False,False,latitude_out_of_range
E25,SRC-A,BATCH-A,water,aqueous,dissolved,Pb,0.02,mg/L,,False,20,ug/L,33,-104,True,False,
```

### artifacts/run_manifest.json#/benchmark_evidence/qc_report.json
```json
{
 "task_id": "GGA-E2E-001",
 "policy_version": "q24-policy-1",
 "raw_input_rows": 25,
 "excluded_integrity_rows": 1,
 "accepted_database_rows": 24,
 "censored_rows": 1,
 "invalid_coordinate_rows": 1,
 "mapped_features": 23,
 "anomaly_eligible_rows": 21,
 "anomaly_features": 1,
 "groups_not_scored": [
  "water|aqueous|dissolved|Pb|ICP-MS"
 ]
}
```

### artifacts/run_manifest.json#/benchmark_evidence/sources.jsonl
```json
[
 {
  "source_id": "SRC-A",
  "file": "source_a.csv",
  "expected_sha256": "03116fbcedab6f5d0dee9b551c5647195b9fd9eae3c5197dad99bcce35d0caae",
  "computed_sha256": "03116fbcedab6f5d0dee9b551c5647195b9fd9eae3c5197dad99bcce35d0caae",
  "dataset_version": "A-1",
  "license": "CC-BY-4.0",
  "integrity_status": "match",
  "downstream_used": true
 },
 {
  "source_id": "SRC-B",
  "file": "source_b.csv",
  "expected_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "computed_sha256": "82b9be48047a72bf7be07b61a59a89541b41fb319adcdd6ff9ae128af611263e",
  "dataset_version": "B-1",
  "license": "CC-BY-4.0",
  "integrity_status": "mismatch",
  "downstream_used": false
 }
]
```

### artifacts/run_manifest.json#/benchmark_evidence/map.geojson
```json
{
 "type": "FeatureCollection",
 "features": [
  {
   "type": "Feature",
   "id": "E01",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.01,
     30.01
    ]
   },
   "properties": {
    "record_id": "E01",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 20,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E02",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.02,
     30.02
    ]
   },
   "properties": {
    "record_id": "E02",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 21,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E03",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.03,
     30.03
    ]
   },
   "properties": {
    "record_id": "E03",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 22,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E04",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.04,
     30.04
    ]
   },
   "properties": {
    "record_id": "E04",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 23,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E05",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.05,
     30.05
    ]
   },
   "properties": {
    "record_id": "E05",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 24,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E06",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.06,
     30.06
    ]
   },
   "properties": {
    "record_id": "E06",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 25,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E07",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.07,
     30.07
    ]
   },
   "properties": {
    "record_id": "E07",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 26,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E08",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.08,
     30.08
    ]
   },
   "properties": {
    "record_id": "E08",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 27,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E09",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.09,
     30.09
    ]
   },
   "properties": {
    "record_id": "E09",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 28,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E10",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.1,
     30.1
    ]
   },
   "properties": {
    "record_id": "E10",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 29,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E11",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.11,
     30.11
    ]
   },
   "properties": {
    "record_id": "E11",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 30,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E12",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.12,
     30.12
    ]
   },
   "properties": {
    "record_id": "E12",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 31,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E13",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.13,
     30.13
    ]
   },
   "properties": {
    "record_id": "E13",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 32,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E14",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.14,
     30.14
    ]
   },
   "properties": {
    "record_id": "E14",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 33,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E15",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.15,
     30.15
    ]
   },
   "properties": {
    "record_id": "E15",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 34,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E16",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.16,
     30.16
    ]
   },
   "properties": {
    "record_id": "E16",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 35,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E17",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.17,
     30.17
    ]
   },
   "properties": {
    "record_id": "E17",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 36,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E18",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.18,
     30.18
    ]
   },
   "properties": {
    "record_id": "E18",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 37,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E19",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.19,
     30.19
    ]
   },
   "properties": {
    "record_id": "E19",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 38,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E20",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.2,
     30.2
    ]
   },
   "properties": {
    "record_id": "E20",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 39,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E21",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.21,
     30.21
    ]
   },
   "properties": {
    "record_id": "E21",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": 500,
    "qualifier": "",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E22",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -101.0,
     31.0
    ]
   },
   "properties": {
    "record_id": "E22",
    "source_id": "SRC-A",
    "element": "Cu",
    "normalized_unit": "mg/kg",
    "normalized_value": null,
    "qualifier": "<",
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "E25",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -104.0,
     33.0
    ]
   },
   "properties": {
    "record_id": "E25",
    "source_id": "SRC-A",
    "element": "Pb",
    "normalized_unit": "ug/L",
    "normalized_value": 20,
    "qualifier": "",
    "qc_flags": []
   }
  }
 ]
}
```

### artifacts/run_manifest.json#/benchmark_evidence/anomalies.geojson
```json
{
 "type": "FeatureCollection",
 "features": [
  {
   "type": "Feature",
   "id": "E21",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -100.21,
     30.21
    ]
   },
   "properties": {
    "record_id": "E21",
    "source_id": "SRC-A",
    "group_id": "soil|dry|total|Cu|ICP-MS",
    "anomaly_type": "statistical_relative_enrichment",
    "robust_z": 10.408091969133482,
    "center_log10": 1.4771212547196624,
    "scale_log10": 0.11739411539020832,
    "n": 21
   }
  }
 ]
}
```

### artifacts/run_manifest.json#/benchmark_evidence/run_manifest.json
```json
{
 "task_id": "GGA-E2E-001",
 "status": "partial_success",
 "exit_code": 2,
 "outputs": [
  "observations.csv",
  "qc_report.json",
  "sources.jsonl",
  "map.geojson",
  "anomalies.geojson",
  "run_manifest.json",
  "summary.md"
 ],
 "policy_version": "q24-policy-1",
 "source_manifest_version": "q24-sources-1",
 "batch_status_version": "q24-batches-1",
 "warnings": [
  "Source integrity mismatch for SRC-B (source_b.csv); entire source excluded from observations",
  "anomaly group water|aqueous|dissolved|Pb|ICP-MS not scored (n below minimum)",
  "record E22 censored (<0.5 ppm); retained bound and qualifier, not treated as exact",
  "record E23 invalid coordinate (latitude out of range); kept in database, excluded from map"
 ]
}
```

### artifacts/run_manifest.json#/benchmark_evidence/summary.md
```
# Q24 端到端小型图谱摘要 / End-to-end mini atlas summary

Status: **partial success** (exit code 2). 本运行按固定规则完成了大部分产物，
但存在受控降级，不隐藏部分成功。

- **Source integrity**: SRC-A sha256 校验通过并进入下游；SRC-B (source_b.csv)
  sha256 与 manifest 不一致，整个来源被排除（1 行未进入 observations）。
- Batch 准入：BATCH-A、BATCH-B 均 batch_pass=true。
- 单位换算：固体 ppm → mg/kg；水体 mg/L → ug/L；两组不合并。
- 限定符：记录 E22 为 censored（<0.5 ppm），保留 bound 与 qualifier，
  不作为精确值进入统计。
- 坐标：记录 E23 纬度越界，为 invalid coordinate，保留在数据库但不进入地图。
- 地图：map.geojson 输出 23 个坐标合法要素（longitude, latitude 顺序，
  每个 feature 回链 record_id 与 source_id）。
- 异常：组 soil|dry|total|Cu|ICP-MS (n=21) 通过准入门槛并评分，记录 E21 为
  statistical relative enrichment；水体组 n<20 未评分。
- 解释红线：异常只是统计上的相对富集，does not establish 矿床、污染源或任何
  因果机制；需要独立证据支持后续解释。

```
