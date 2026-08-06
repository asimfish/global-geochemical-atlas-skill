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

下文提到的 `confidence.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q12 置信度评分

严格按 `inputs/confidence_policy.json` 给 `inputs/records.json` 评分，输出 `confidence.json`。每条必须包含五个组件、总分、label 和 `confidence_is_probability=false`。

该分数是透明的 benchmark 启发式完整性分，不是结果为真的概率。不得自行调权或把 59 四舍五入成 medium。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "每个总分能从五个组件精确复算。",
   "id": "transparent_components",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "59 按冻结阈值为 low，不任意四舍五入。",
   "id": "threshold",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "明确分数是 completeness/QC heuristic，不是校准概率。",
   "id": "not_probability",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/confidence.json",
  "inputs/confidence_policy.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-CONF-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-CONF-001",
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
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 75,
   "evidence_points_possible": 75,
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
   "evidence": "confidence.json: file"
  },
  {
   "id": "policy_version",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "confidence.json path=policy_version actual='q12-confidence-1' expected='q12-confidence-1'"
  },
  {
   "id": "record_count",
   "type": "json_length",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "confidence.json path=records length=3; expected=3"
  },
  {
   "id": "k01_score",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "confidence.json path=records.0.confidence_score actual=100 expected=100"
  },
  {
   "id": "k01_components",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "confidence.json path=records.0.components actual={'provenance': 25, 'coordinates': 20, 'analysis': 20, 'sample': 15, 'record_qc': 20} expected={'analysis': 20, 'coordinates': 20, 'provenance': 25, 'record_qc': 20, 'sample': 15}"
  },
  {
   "id": "k02_score",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "confidence.json path=records.1.confidence_score actual=59 expected=59"
  },
  {
   "id": "k02_label",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "confidence.json path=records.1.confidence_label actual='low' expected='low'"
  },
  {
   "id": "k02_components",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "confidence.json path=records.1.components actual={'provenance': 15, 'coordinates': 12, 'analysis': 12, 'sample': 10, 'record_qc': 10} expected={'analysis': 12, 'coordinates': 12, 'provenance': 15, 'record_qc': 10, 'sample': 10}"
  },
  {
   "id": "k03_score",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "confidence.json path=records.2.confidence_score actual=10 expected=10"
  },
  {
   "id": "k01_not_probability",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "confidence.json path=records.0.confidence_is_probability actual=False expected=False"
  },
  {
   "id": "k02_not_probability",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "confidence.json path=records.1.confidence_is_probability actual=False expected=False"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/confidence.json
```json
{
 "task_id": "GGA-CONF-001",
 "policy_version": "q12-confidence-1",
 "records": [
  {
   "record_id": "K01",
   "components": {
    "provenance": 25,
    "coordinates": 20,
    "analysis": 20,
    "sample": 15,
    "record_qc": 20
   },
   "confidence_score": 100,
   "confidence_label": "high",
   "confidence_is_probability": false
  },
  {
   "record_id": "K02",
   "components": {
    "provenance": 15,
    "coordinates": 12,
    "analysis": 12,
    "sample": 10,
    "record_qc": 10
   },
   "confidence_score": 59,
   "confidence_label": "low",
   "confidence_is_probability": false
  },
  {
   "record_id": "K03",
   "components": {
    "provenance": 5,
    "coordinates": 0,
    "analysis": 0,
    "sample": 5,
    "record_qc": 0
   },
   "confidence_score": 10,
   "confidence_label": "low",
   "confidence_is_probability": false
  }
 ]
}
```

### inputs/confidence_policy.json
```json
{
 "version": "q12-confidence-1",
 "provenance": {
  "all_url_version_license_sha256": 25,
  "at_least_three": 15,
  "at_least_one": 5,
  "none": 0
 },
 "coordinates": {
  "valid_crs_precision_le_100m": 20,
  "valid_crs_precision_le_1000m": 12,
  "valid_crs_other_precision": 5,
  "invalid": 0
 },
 "analysis": {
  "method_lab_detection_limit": 20,
  "method_detection_limit": 12,
  "method_only": 8,
  "none": 0
 },
 "sample": {
  "medium_material_lithology": 15,
  "medium_material": 10,
  "medium_only": 5,
  "none": 0
 },
 "record_qc": {
  "base": 20,
  "penalty_per_flag": 5,
  "minimum": 0
 },
 "labels": {
  "high_min": 80,
  "medium_min": 60,
  "low_min": 0
 }
}
```
