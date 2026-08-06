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

下文提到的 `parsed_values.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q06 LOD 与限定符解析

解析 `inputs/censored_values.csv`，输出 `parsed_values.csv`：

```text
record_id,reported_value_text,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_log_analysis
```

规则：

- `<x`：左删失，`bound_value=x`、`detection_limit=x`，不能把 x 当精确浓度；
- `ND`/`BDL`：未检出；有独立 DL 时保留，无 DL 时不得猜测；
- 数值 `0` 是报告值，不等同 ND，但不能直接进入对数分析；
- `>x`：右删失/超过上限，不能把 x 当精确浓度；
- 空字符串：未报告，不等同未检出或 0。

本题不要求对删失值进行替代估计。

使用以下冻结语义值；不使用同义改写：

```text
<x       qualifier=<,  missing_reason 留空
ND       qualifier=ND
BDL      qualifier=BDL
>x       qualifier=>,  missing_reason=above_upper_limit
空字符串 missing_reason=not_reported
BDL/ND 且无可用 DL  missing_reason=below_detection_limit_unknown_limit
```

`censored` 和 `eligible_log_analysis` 必须是布尔值。未知、删失和未报告记录的 `numeric_value` 留空；数值 0 的 `numeric_value=0`、`censored=false`、`eligible_log_analysis=false`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "清楚区分左删失、右删失、报告零、未分析/未报告。",
   "id": "semantic_separation",
   "points": 10
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "不擅自用 LOD/2 或 0 替代，并说明替代需要单独方法和敏感性分析。",
   "id": "no_imputation",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "说明为何这些记录不能直接进入对数异常计算。",
   "id": "analysis_eligibility",
   "points": 4
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-QC-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-QC-001",
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
   "evidence_points_awarded": 10,
   "evidence_points_possible": 10,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 65,
   "evidence_points_possible": 65,
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
   "evidence": "parsed_values.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "parsed_values.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "parsed_values.csv: rows=6; expected=6"
  },
  {
   "id": "c01_bound",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C01'} column=bound_value actual='0.1' expected=0.1 tol=1e-06"
  },
  {
   "id": "c01_numeric_empty",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C01'} column=numeric_value actual='' expected=None tol=0.0"
  },
  {
   "id": "c02_nd",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C02'} column=qualifier actual='ND' expected='ND' tol=0.0"
  },
  {
   "id": "c02_dl",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C02'} column=detection_limit actual='0.20' expected=0.2 tol=1e-06"
  },
  {
   "id": "c03_zero",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C03'} column=numeric_value actual='0' expected=0 tol=0.0"
  },
  {
   "id": "c03_not_censored",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C03'} column=censored actual='False' expected=False tol=0.0"
  },
  {
   "id": "c04_upper",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "parsed_values.csv key={'record_id': 'C04'} column=missing_reason actual='above_upper_limit' expected='above_upper_limit' tol=0.0"
  },
  {
   "id": "c05_missing",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "parsed_values.csv key={'record_id': 'C05'} column=missing_reason actual='not_reported' expected='not_reported' tol=0.0"
  },
  {
   "id": "c06_unknown_dl",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "parsed_values.csv key={'record_id': 'C06'} column=missing_reason actual='below_detection_limit_unknown_limit' expected='below_detection_limit_unknown_limit' tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv
```
record_id,reported_value_text,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_log_analysis
C01,<0.10,,0.1,<,0.1,True,,False
C02,ND,,0.2,ND,0.20,True,,False
C03,0,0,,,0.05,False,,False
C04,>1000,,1000,>,,True,above_upper_limit,False
C05,,,,,,False,not_reported,False
C06,BDL,,,BDL,,True,below_detection_limit_unknown_limit,False
```
