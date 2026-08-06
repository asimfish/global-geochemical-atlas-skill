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

下文提到的 `decoded_values.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q18 来源编码解析

严格按 `inputs/encoding_rules.json` 解析 `inputs/encoded_values.csv`，输出：

```text
record_id,reported_value,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_quantitative
```

来源特定负数和哨兵值不得进入真实浓度统计；`G` 表示超过上限。保留 reported_value，不进行删失值替代。

输出中的标准化 `qualifier` 使用 `<` 或 `>`，因此来源代码 `G` 必须转换为 `>`。冻结 `missing_reason` 包括 `not_analyzed` 和 `not_reported`；缺失数值字段留空，不使用字符串 `null`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "明确这些负数语义来自题给来源规则，不推广为所有数据库通则。",
   "id": "source_specific",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "-9999 与左删失负值正确分离。",
   "id": "sentinel",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "上下限值不被当成精确浓度。",
   "id": "bounds",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/decoded_values.csv",
  "inputs/encoding_rules.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-QC-003"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-QC-003",
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
   "evidence": "decoded_values.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "decoded_values.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "decoded_values.csv: rows=5; expected=5"
  },
  {
   "id": "u01_numeric_empty",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "decoded_values.csv key={'record_id': 'U01'} column=numeric_value actual='' expected=None tol=0.0"
  },
  {
   "id": "u01_dl",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "decoded_values.csv key={'record_id': 'U01'} column=detection_limit actual='0.5' expected=0.5 tol=0.0"
  },
  {
   "id": "u02_sentinel",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "decoded_values.csv key={'record_id': 'U02'} column=missing_reason actual='not_analyzed' expected='not_analyzed' tol=0.0"
  },
  {
   "id": "u02_not_eligible",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "decoded_values.csv key={'record_id': 'U02'} column=eligible_quantitative actual='False' expected=False tol=0.0"
  },
  {
   "id": "u03_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "decoded_values.csv key={'record_id': 'U03'} column=numeric_value actual='25' expected=25 tol=0.0"
  },
  {
   "id": "u04_bound",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "decoded_values.csv key={'record_id': 'U04'} column=bound_value actual='1000' expected=1000 tol=0.0"
  },
  {
   "id": "u04_qualifier",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "decoded_values.csv key={'record_id': 'U04'} column=qualifier actual='>' expected='>' tol=0.0"
  },
  {
   "id": "u05_missing",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "decoded_values.csv key={'record_id': 'U05'} column=missing_reason actual='not_reported' expected='not_reported' tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/decoded_values.csv
```
record_id,reported_value,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_quantitative
U01,-0.5,,0.5,<,0.5,True,,False
U02,-9999,,,,,False,not_analyzed,False
U03,25,25,,,,False,,True
U04,1000,,1000,>,,True,above_upper_limit,False
U05,,,,,,False,not_reported,False
```

### inputs/encoding_rules.json
```json
{
 "version": "q18-encoding-1",
 "negative_numeric_except_sentinel": "left_censored_with_detection_limit_equal_absolute_value",
 "not_analyzed_sentinel": -9999,
 "greater_than_qualifier": "G",
 "blank": "not_reported"
}
```
