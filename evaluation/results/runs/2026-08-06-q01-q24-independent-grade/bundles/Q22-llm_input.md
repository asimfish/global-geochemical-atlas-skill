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

下文提到的 `redistribution_decisions.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q22 许可与再分发

严格按 `inputs/license_policy.json` 处理来源，输出：

```text
source_id,license_class,redistribution_allowed,allowed_payload,required_actions,confidence_penalty
```

`required_actions` 多项用分号按字母排序。未知许可不能被当成开放许可；限制再分发的数据只能发布元数据和指针。该决策不要求删除本地受控缓存。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "开放许可仍执行 attribution/share-alike 条件。",
   "id": "open_conditions",
   "points": 7
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "限制数据只输出 metadata/pointer，保留访问控制。",
   "id": "restricted",
   "points": 7
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "未知许可进入人工核验而不是默认开放。",
   "id": "unknown",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/redistribution_decisions.csv",
  "inputs/license_policy.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-LICENSE-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-LICENSE-001",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 80,
 "evidence_points_possible": 80,
 "dimensions": [
  {
   "dimension_id": "scientific_credibility",
   "weight": 0.25,
   "evidence_points_awarded": 67,
   "evidence_points_possible": 67,
   "evidence_score": 100.0,
   "status": "scored"
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
   "evidence": "redistribution_decisions.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "redistribution_decisions.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "redistribution_decisions.csv: rows=4; expected=4"
  },
  {
   "id": "l01_allowed",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L01'} column=redistribution_allowed actual='True' expected=True tol=0.0"
  },
  {
   "id": "l01_attribution",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L01'} column=required_actions actual='attribution' expected='attribution' tol=0.0"
  },
  {
   "id": "l02_sharealike",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 9,
   "points_possible": 9,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L02'} column=required_actions actual='attribution;share_alike' expected='attribution;share_alike' tol=0.0"
  },
  {
   "id": "l03_forbidden",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L03'} column=redistribution_allowed actual='False' expected=False tol=0.0"
  },
  {
   "id": "l03_payload",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L03'} column=allowed_payload actual='metadata_and_pointer_only' expected='metadata_and_pointer_only' tol=0.0"
  },
  {
   "id": "l03_penalty",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L03'} column=confidence_penalty actual='10' expected=10 tol=0.0"
  },
  {
   "id": "l04_unknown",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L04'} column=license_class actual='unknown' expected='unknown' tol=0.0"
  },
  {
   "id": "l04_forbidden",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L04'} column=redistribution_allowed actual='False' expected=False tol=0.0"
  },
  {
   "id": "l04_penalty",
   "type": "csv_cell",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "redistribution_decisions.csv key={'source_id': 'L04'} column=confidence_penalty actual='20' expected=20 tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/redistribution_decisions.csv
```
source_id,license_class,redistribution_allowed,allowed_payload,required_actions,confidence_penalty
L01,CC-BY-4.0,True,raw_and_derived,attribution,0
L02,CC-BY-SA-4.0,True,raw_and_derived,attribution;share_alike,0
L03,restricted_nonredistributable,False,metadata_and_pointer_only,do_not_redistribute_raw;retain_access_controls,10
L04,unknown,False,metadata_only,license_review_required,20
```

### inputs/license_policy.json
```json
{
 "version": "q22-license-1",
 "classes": {
  "CC-BY-4.0": {
   "redistribution_allowed": true,
   "allowed_payload": "raw_and_derived",
   "required_actions": [
    "attribution"
   ],
   "confidence_penalty": 0
  },
  "CC-BY-SA-4.0": {
   "redistribution_allowed": true,
   "allowed_payload": "raw_and_derived",
   "required_actions": [
    "attribution",
    "share_alike"
   ],
   "confidence_penalty": 0
  },
  "restricted_nonredistributable": {
   "redistribution_allowed": false,
   "allowed_payload": "metadata_and_pointer_only",
   "required_actions": [
    "do_not_redistribute_raw",
    "retain_access_controls"
   ],
   "confidence_penalty": 10
  },
  "unknown": {
   "redistribution_allowed": false,
   "allowed_payload": "metadata_only",
   "required_actions": [
    "license_review_required"
   ],
   "confidence_penalty": 20
  }
 }
}
```
