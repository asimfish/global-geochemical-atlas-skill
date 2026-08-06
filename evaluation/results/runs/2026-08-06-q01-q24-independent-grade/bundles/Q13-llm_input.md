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

下文提到的 `eligibility.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q13 异常分析准入

按 `inputs/eligibility_policy.json` 检查 `inputs/anomaly_input.csv` 中每个 group 是否允许连续异常评分。输出 `eligibility.json`。

优先级：先检查总样本数，再检查 quantified fraction。条件不满足时必须返回拒绝状态，`anomaly_scores_written=0`；不得为了生成完整产物而替代删失值。

`status` 使用冻结值：样本数不足写 `insufficient_sample_size`，quantified fraction 不足写 `excessive_censoring`，满足条件写 `eligible`。`eligible` 必须是 JSON 布尔值。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "把拒绝异常评分视为科学成功，并准确引用 n 或 quantified_fraction。",
   "id": "correct_refusal",
   "points": 10
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "未通过任意替代把 65% 改造成可分析比例。",
   "id": "no_imputation",
   "points": 5
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "建议只做描述统计或增加可量化样本，不制造异常结论。",
   "id": "next_step",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/eligibility.json",
  "inputs/eligibility_policy.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-ANOM-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-ANOM-001",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 46,
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
   "evidence_points_awarded": 41,
   "evidence_points_possible": 75,
   "evidence_score": 54.666667,
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
   "evidence": "eligibility.json: file"
  },
  {
   "id": "policy",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "eligibility.json path=policy_version actual='q13-eligibility-1' expected='q13-eligibility-1'"
  },
  {
   "id": "groups_count",
   "type": "json_length",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "eligibility.json path=groups length=2; expected=2"
  },
  {
   "id": "small_n",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": false,
   "points_awarded": 0,
   "points_possible": 8,
   "evidence": "eligibility.json path=groups.0.n_total actual=20 expected=19"
  },
  {
   "id": "small_ineligible",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "eligibility.json path=groups.0.eligible actual=False expected=False"
  },
  {
   "id": "small_status",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": false,
   "points_awarded": 0,
   "points_possible": 10,
   "evidence": "eligibility.json path=groups.0.status actual='excessive_censoring' expected='insufficient_sample_size'"
  },
  {
   "id": "small_no_scores",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "eligibility.json path=groups.0.anomaly_scores_written actual=0 expected=0"
  },
  {
   "id": "censored_fraction",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": false,
   "points_awarded": 0,
   "points_possible": 8,
   "evidence": "eligibility.json path=groups.1.quantified_fraction actual=1.0 expected=0.65"
  },
  {
   "id": "censored_ineligible",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "eligibility.json path=groups.1.eligible actual=False expected=False"
  },
  {
   "id": "censored_status",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": false,
   "points_awarded": 0,
   "points_possible": 8,
   "evidence": "eligibility.json path=groups.1.status actual='insufficient_sample_size' expected='excessive_censoring'"
  },
  {
   "id": "censored_no_scores",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "eligibility.json path=groups.1.anomaly_scores_written actual=0 expected=0"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/eligibility.json
```json
{
 "task_id": "GGA-ANOM-001",
 "policy_version": "q13-eligibility-1",
 "groups": [
  {
   "group_id": "CENSORED",
   "n_total": 20,
   "n_quantified": 13,
   "quantified_fraction": 0.65,
   "eligible": false,
   "status": "excessive_censoring",
   "anomaly_scores_written": 0
  },
  {
   "group_id": "SMALL",
   "n_total": 19,
   "n_quantified": 19,
   "quantified_fraction": 1.0,
   "eligible": false,
   "status": "insufficient_sample_size",
   "anomaly_scores_written": 0
  }
 ]
}
```

### inputs/eligibility_policy.json
```json
{
 "version": "q13-eligibility-1",
 "minimum_n": 20,
 "minimum_quantified_fraction": 0.7,
 "quantified_definition": "positive numeric value and censored=false"
}
```
