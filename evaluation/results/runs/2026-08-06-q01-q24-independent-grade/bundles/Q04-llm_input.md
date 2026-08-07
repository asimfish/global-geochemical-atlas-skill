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

下文提到的 `element_database.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q04 Fe2O3 转 Fe

处理 `inputs/rock_oxide.csv`，按 `inputs/conversion_constants.json` 的冻结原子量把 **Fe2O3** 换算为元素 Fe，并统一元素结果到 `mg/kg`。

```text
Fe fraction in Fe2O3 = (2 × M(Fe)) / (2 × M(Fe) + 3 × M(O))
```

要求：

- 原始 analyte、值和单位必须保留；
- 原本已是 Fe 的记录只做单位换算；
- FeO 记录保留，但本题不得套用 Fe2O3 因子；将其 `status` 记为 `not_requested`，标准化值留空；
- 输出 `element_database.csv`，列为：

```text
sample_id,analyte_reported,reported_value,reported_unit,element,normalized_value,normalized_unit,conversion_factor,conversion_rule,status
```

数值 checker 的绝对容差为 `0.02 mg/kg`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "解释质量分数因子来自化学计量，并引用冻结常数。",
   "id": "stoichiometry",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "明确 Fe2O3、Fe 和 FeO 的 analyte 身份不能丢失或共用同一规则。",
   "id": "identity",
   "points": 8
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "输出可回溯 reported analyte/value/unit。",
   "id": "traceability",
   "points": 4
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/element_database.csv",
  "inputs/conversion_constants.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-NORM-002"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-NORM-002",
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
   "evidence": "element_database.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "element_database.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "element_database.csv: rows=4; expected=4"
  },
  {
   "id": "key_set",
   "type": "csv_key_set",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "element_database.csv: actual keys=[('R01', 'Fe2O3'), ('R02', 'Fe2O3'), ('R03', 'Fe'), ('R04', 'FeO')]; expected=[('R01', 'Fe2O3'), ('R02', 'Fe2O3'), ('R03', 'Fe'), ('R04', 'FeO')]"
  },
  {
   "id": "r01_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "element_database.csv key={'sample_id': 'R01'} column=normalized_value actual='69943.07614270416' expected=69943.076143 tol=0.02"
  },
  {
   "id": "r02_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "element_database.csv key={'sample_id': 'R02'} column=normalized_value actual='48960.15329989292' expected=48960.1533 tol=0.02"
  },
  {
   "id": "r03_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "element_database.csv key={'sample_id': 'R03'} column=normalized_value actual='50000' expected=50000 tol=0.02"
  },
  {
   "id": "r04_status",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "element_database.csv key={'sample_id': 'R04'} column=status actual='not_requested' expected='not_requested' tol=0.0"
  },
  {
   "id": "r04_value_empty",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "element_database.csv key={'sample_id': 'R04'} column=normalized_value actual='' expected=None tol=0.0"
  },
  {
   "id": "factor",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "element_database.csv key={'sample_id': 'R01'} column=conversion_factor actual='0.6994307614270416' expected=0.6994307614270416 tol=1e-08"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/element_database.csv
```
sample_id,analyte_reported,reported_value,reported_unit,element,normalized_value,normalized_unit,conversion_factor,conversion_rule,status
R01,Fe2O3,10,wt%,Fe,69943.07614270416,mg/kg,0.6994307614270416,fe2o3_to_fe_frozen_mass_fraction,converted
R02,Fe2O3,70000,mg/kg,Fe,48960.15329989292,mg/kg,0.6994307614270416,fe2o3_to_fe_frozen_mass_fraction,converted
R03,Fe,5,wt%,Fe,50000,mg/kg,1,identity_element_unit_conversion,unit_conversion_only
R04,FeO,8,wt%,Fe,,mg/kg,,,not_requested
```

### inputs/conversion_constants.json
```json
{
 "version": "q04-constants-1",
 "atomic_weights": {
  "Fe": 55.845,
  "O": 15.999
 },
 "fe2o3_molar_mass": 159.687,
 "fe_mass_fraction_in_fe2o3": 0.6994307614270416,
 "reference_note": "Benchmark-fixed values; NIST WebBook reports Fe2O3 formula and molecular weight approximately 159.688."
}
```
