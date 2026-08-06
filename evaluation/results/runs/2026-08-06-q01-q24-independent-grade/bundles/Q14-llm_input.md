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

下文提到的 `group_statistics.csv`、`anomalies.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q14 稳健异常

严格按 `inputs/anomaly_policy.json` 处理 `inputs/values.csv`：正值取 `log10`，中心为 median，尺度为 `1.4826 × MAD`，`|robust_z| >= 3.5` 标异常。若 MAD=0，使用 policy 指定的严格经验分位数回退，不除零、不加任意 epsilon。

输出 `group_statistics.csv` 和 `anomalies.csv`。中心、尺度和 z 至少保留 8 位小数。

`group_statistics.csv.method` 的冻结值为：正常 MAD 路径使用 `robust_log10_mad`，MAD=0 回退使用 `empirical_quantile_fallback`。`anomalies.csv.anomaly_type` 使用 `relative_enrichment` 或 `relative_depletion`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "明确异常相对于本组 log10 稳健背景。",
   "id": "method",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "MAD=0 时使用冻结回退且没有制造常数组异常。",
   "id": "fallback",
   "points": 7
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "仅称相对富集统计异常，不推断矿床或原因。",
   "id": "terminology",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/group_statistics.csv",
  "artifacts/run_manifest.json#/benchmark_evidence/anomalies.csv",
  "inputs/anomaly_policy.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-ANOM-002"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-ANOM-002",
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
   "id": "stats_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "group_statistics.csv: file"
  },
  {
   "id": "anomalies_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "anomalies.csv: file"
  },
  {
   "id": "stats_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "group_statistics.csv: rows=2; expected=2"
  },
  {
   "id": "anomaly_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "anomalies.csv: rows=1; expected=1"
  },
  {
   "id": "variable_center",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "group_statistics.csv key={'group_id': 'VARIABLE'} column=center_log10 actual='1.3010299956639813' expected=1.3010299957 tol=1e-07"
  },
  {
   "id": "variable_scale",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "group_statistics.csv key={'group_id': 'VARIABLE'} column=scale_log10 actual='0.16893241413011612' expected=0.1689324141 tol=1e-07"
  },
  {
   "id": "variable_method",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "group_statistics.csv key={'group_id': 'VARIABLE'} column=method actual='robust_log10_mad' expected='robust_log10_mad' tol=0.0"
  },
  {
   "id": "v21_only",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "anomalies.csv key={'record_id': 'V21'} column=anomaly_type actual='relative_enrichment' expected='relative_enrichment' tol=0.0"
  },
  {
   "id": "v21_z",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "anomalies.csv key={'record_id': 'V21'} column=robust_z actual='6.961904055605489' expected=6.9619040556 tol=1e-06"
  },
  {
   "id": "constant_fallback",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "group_statistics.csv key={'group_id': 'CONSTANT'} column=method actual='empirical_quantile_fallback' expected='empirical_quantile_fallback' tol=0.0"
  },
  {
   "id": "constant_no_anomaly",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "group_statistics.csv key={'group_id': 'CONSTANT'} column=anomaly_count actual='0' expected=0 tol=0.0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/group_statistics.csv
```
group_id,n,method,center_log10,scale_log10,status,anomaly_count
CONSTANT,20,empirical_quantile_fallback,0.6989700043360189,0,mad_zero_fallback,0
VARIABLE,21,robust_log10_mad,1.3010299956639813,0.16893241413011612,ok,1
```

### artifacts/run_manifest.json#/benchmark_evidence/anomalies.csv
```
record_id,group_id,value,robust_z,anomaly_type
V21,VARIABLE,300,6.961904055605489,relative_enrichment
```

### inputs/anomaly_policy.json
```json
{
 "version": "q14-anomaly-1",
 "transform": "log10",
 "center": "median",
 "scale": "1.4826*MAD",
 "robust_z_threshold": 3.5,
 "mad_zero_fallback": "strict empirical values above p97.5 or below p2.5; ties at threshold are not anomalies"
}
```
