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

下文提到的 `batch_acceptance.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q21 实验室批次 QC

按 `inputs/qc_policy.json` 计算每批的 CRM recovery、blank value 和 duplicate RPD，并输出 `batch_acceptance.csv`。

```text
RPD = |x1-x2| / ((x1+x2)/2) * 100
```

三个 QC 子项必须全部通过，批次才能进入科学分析。输出列：

```text
batch_id,crm_recovery_percent,crm_pass,blank_value,blank_pass,duplicate_rpd_percent,duplicate_pass,batch_pass,disposition
```

`disposition` 使用 `accept_for_scientific_analysis` 或
`exclude_batch_and_investigate`。所有 `*_pass` 字段必须是布尔值，不使用字符串。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "不因其中一个 QC 通过而放行整个批次。",
   "id": "all_checks",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "recovery 与 RPD 可从原始 QC 行复算。",
   "id": "calculations",
   "points": 7
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "失败批次被排除并建议调查，而非删除 QC 证据。",
   "id": "disposition",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/batch_acceptance.csv",
  "inputs/qc_policy.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-QC-004"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-QC-004",
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
   "evidence": "batch_acceptance.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "batch_acceptance.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "batch_acceptance.csv: rows=2; expected=2"
  },
  {
   "id": "b1_recovery",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-1'} column=crm_recovery_percent actual='105' expected=105 tol=0.0"
  },
  {
   "id": "b1_rpd",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-1'} column=duplicate_rpd_percent actual='9.523809523809524' expected=9.5238095238 tol=1e-06"
  },
  {
   "id": "b1_pass",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-1'} column=batch_pass actual='True' expected=True tol=0.0"
  },
  {
   "id": "b2_recovery",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-2'} column=crm_recovery_percent actual='135' expected=135 tol=0.0"
  },
  {
   "id": "b2_blank",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-2'} column=blank_pass actual='False' expected=False tol=0.0"
  },
  {
   "id": "b2_rpd",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-2'} column=duplicate_rpd_percent actual='40' expected=40 tol=0.0"
  },
  {
   "id": "b2_duplicate_fail",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-2'} column=duplicate_pass actual='False' expected=False tol=0.0"
  },
  {
   "id": "b2_batch_fail",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "batch_acceptance.csv key={'batch_id': 'BATCH-2'} column=batch_pass actual='False' expected=False tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/batch_acceptance.csv
```
batch_id,crm_recovery_percent,crm_pass,blank_value,blank_pass,duplicate_rpd_percent,duplicate_pass,batch_pass,disposition
BATCH-1,105,True,2,True,9.523809523809524,True,True,accept_for_scientific_analysis
BATCH-2,135,False,8,False,40,False,False,exclude_batch_and_investigate
```

### inputs/qc_policy.json
```json
{
 "version": "q21-qc-1",
 "crm_recovery_percent": {
  "minimum": 80,
  "maximum": 120,
  "inclusive": true
 },
 "blank_maximum": 5,
 "duplicate_rpd_maximum_percent": 20,
 "batch_rule": "all_checks_must_pass"
}
```
