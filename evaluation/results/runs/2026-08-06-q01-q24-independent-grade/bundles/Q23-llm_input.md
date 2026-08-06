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

下文提到的 `contextual_anomalies.csv`、`interpretation.md` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q23 背景条件化异常

使用每个地质单元的冻结 `center_log10` 和 `scale_log10` 计算候选记录的 robust z；`|z| >= 3.5` 才写入 `contextual_anomalies.csv`。异常方向为 `relative_enrichment` 或 `relative_depletion`。

另写 `interpretation.md`，说明结果是相对于地质单元背景的统计异常，不能单独建立矿床、污染源或因果机制。不得使用全局背景替代 unit_id 匹配。

`anomaly_type` 使用 `relative_enrichment` 或 `relative_depletion`。为使确定性审计不依赖写作语言，`interpretation.md` 必须原样包含以下四个英文证据标记，并可在其前后补充中文解释：

```text
statistical anomalies
relative to each matched geologic unit
does not establish
independent
```


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "同一浓度在不同 unit 背景下方向不同，解释与 z 一致。",
   "id": "context",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "只报告统计异常/相对富集亏损。",
   "id": "statistical_scope",
   "points": 7
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "列出需要独立地质、采样、分析和过程证据。",
   "id": "validation_needs",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/contextual_anomalies.csv",
  "artifacts/run_manifest.json#/benchmark_evidence/interpretation.md",
  "inputs/backgrounds.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-ANOM-003"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-ANOM-003",
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
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 72,
   "evidence_points_possible": 72,
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
   "id": "anomalies_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "contextual_anomalies.csv: file"
  },
  {
   "id": "interpretation_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "interpretation.md: file"
  },
  {
   "id": "anomaly_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "contextual_anomalies.csv: rows=2; expected=2"
  },
  {
   "id": "anomaly_keys",
   "type": "csv_key_set",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "contextual_anomalies.csv: actual keys=[('CTX1', 'UNIT-A'), ('CTX2', 'UNIT-B')]; expected=[('CTX1', 'UNIT-A'), ('CTX2', 'UNIT-B')]"
  },
  {
   "id": "ctx1_z",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "contextual_anomalies.csv key={'record_id': 'CTX1'} column=robust_z actual='5.228787452803374' expected=5.2287874528 tol=1e-06"
  },
  {
   "id": "ctx1_type",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "contextual_anomalies.csv key={'record_id': 'CTX1'} column=anomaly_type actual='relative_enrichment' expected='relative_enrichment' tol=0.0"
  },
  {
   "id": "ctx2_z",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "contextual_anomalies.csv key={'record_id': 'CTX2'} column=robust_z actual='-4.771212547196626' expected=-4.7712125472 tol=1e-06"
  },
  {
   "id": "ctx2_type",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "contextual_anomalies.csv key={'record_id': 'CTX2'} column=anomaly_type actual='relative_depletion' expected='relative_depletion' tol=0.0"
  },
  {
   "id": "limitations",
   "type": "text_contains_all",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "interpretation.md: missing terms=[]"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/contextual_anomalies.csv
```
record_id,unit_id,value_mg_kg,robust_z,anomaly_type,background_version
CTX1,UNIT-A,50,5.228787452803374,relative_enrichment,q23-background-1
CTX2,UNIT-B,50,-4.771212547196626,relative_depletion,q23-background-1
```

### artifacts/run_manifest.json#/benchmark_evidence/interpretation.md
```
# Q23 背景条件化异常解释 / Contextual anomaly interpretation

The records listed in `contextual_anomalies.csv` are **statistical anomalies**
computed **relative to each matched geologic unit** using that unit's frozen
background (`center_log10`, `scale_log10`) and a robust |z| >= 3.5 rule.

这些记录只是相对于各自地质单元背景的统计异常（statistical anomalies），
方向分为 relative_enrichment 与 relative_depletion。

A statistical deviation from unit background **does not establish** the
presence of an ore deposit, a pollution source, or any causal mechanism.
该结论不能单独建立矿床、污染源或因果机制；

Any follow-up requires **independent** geological, mineralogical or
source-appraisal evidence. independent 证据是后续解释的必要前提；
本解释未使用全局背景替代 unit_id 匹配。

```

### inputs/backgrounds.json
```json
{
 "version": "q23-background-1",
 "threshold_abs_z": 3.5,
 "groups": {
  "UNIT-A": {
   "center_log10": 1.1760912590556813,
   "scale_log10": 0.1
  },
  "UNIT-B": {
   "center_log10": 2.1760912590556813,
   "scale_log10": 0.1
  }
 }
}
```
