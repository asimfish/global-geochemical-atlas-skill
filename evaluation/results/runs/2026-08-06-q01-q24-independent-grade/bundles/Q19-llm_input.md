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

下文提到的 `nickel_elements.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q19 NiO 转 Ni

按冻结常数把 NiO 转为元素 Ni 并统一到 mg/kg。原本为 Ni 的记录只换单位；Ni2O3 不在本题换算范围，保留但标为 `not_requested`，不得套用 NiO 因子。

输出 `nickel_elements.csv`：

```text
record_id,analyte_reported,reported_value,reported_unit,element,normalized_value,normalized_unit,conversion_factor,conversion_rule,status
```


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "platform_reusability",
   "full_credit": "根据 NiO 化学式重新计算，不复用 Fe2O3 因子。",
   "id": "new_factor",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "Ni、NiO、Ni2O3 身份和规则独立保留。",
   "id": "identity",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "使用冻结常数并在最终输出前保留足够精度。",
   "id": "precision",
   "points": 4
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv",
  "inputs/constants.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-NORM-004"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-NORM-004",
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
   "evidence": "nickel_elements.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "nickel_elements.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "nickel_elements.csv: rows=4; expected=4"
  },
  {
   "id": "key_set",
   "type": "csv_key_set",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "nickel_elements.csv: actual keys=[('N01', 'NiO'), ('N02', 'NiO'), ('N03', 'Ni'), ('N04', 'Ni2O3')]; expected=[('N01', 'NiO'), ('N02', 'NiO'), ('N03', 'Ni'), ('N04', 'Ni2O3')]"
  },
  {
   "id": "n01_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "nickel_elements.csv key={'record_id': 'N01'} column=normalized_value actual='157.16030011085468' expected=157.16030011 tol=0.001"
  },
  {
   "id": "n02_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "nickel_elements.csv key={'record_id': 'N02'} column=normalized_value actual='392.9007502771367' expected=392.90075028 tol=0.001"
  },
  {
   "id": "n03_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "nickel_elements.csv key={'record_id': 'N03'} column=normalized_value actual='200' expected=200 tol=0.001"
  },
  {
   "id": "n04_status",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "nickel_elements.csv key={'record_id': 'N04'} column=status actual='not_requested' expected='not_requested' tol=0.0"
  },
  {
   "id": "n04_empty",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "nickel_elements.csv key={'record_id': 'N04'} column=normalized_value actual='' expected=None tol=0.0"
  },
  {
   "id": "factor",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "nickel_elements.csv key={'record_id': 'N01'} column=conversion_factor actual='0.7858015005542733' expected=0.7858015005542733 tol=1e-08"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv
```
record_id,analyte_reported,reported_value,reported_unit,element,normalized_value,normalized_unit,conversion_factor,conversion_rule,status
N01,NiO,0.020,wt%,Ni,157.16030011085468,mg/kg,0.7858015005542733,nio_to_ni_frozen_mass_fraction,converted
N02,NiO,500,mg/kg,Ni,392.9007502771367,mg/kg,0.7858015005542733,nio_to_ni_frozen_mass_fraction,converted
N03,Ni,0.020,wt%,Ni,200,mg/kg,1,identity_element_unit_conversion,unit_conversion_only
N04,Ni2O3,0.020,wt%,Ni,,mg/kg,,,not_requested
```

### inputs/constants.json
```json
{
 "version": "q19-constants-1",
 "atomic_weights": {
  "Ni": 58.6934,
  "O": 15.999
 },
 "ni_mass_fraction_in_nio": 0.7858015005542733
}
```
