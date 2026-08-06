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

下文提到的 `normalized_elements.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q03 固体样品质量分数统一

`inputs/soil_elements.csv` 的所有记录均为固体土壤、质量/质量基准。将其统一到 `mg/kg`，输出 `normalized_elements.csv`。

必须保留以下列：

```text
sample_id,element,original_value,original_unit,normalized_value,normalized_unit,conversion_rule
```

本题固定换算：

```text
1 ppm = 1 mg/kg
1 µg/g = 1 mg/kg
1 ppb = 0.001 mg/kg
1 wt% = 10,000 mg/kg
1 g/kg = 1,000 mg/kg
```

保留至少 6 位有效数字即可；checker 使用绝对容差。

`conversion_rule` 使用以下冻结字符串：

```text
ppm       -> ppm_mass_mass_to_mg_per_kg
mg/kg     -> identity_mg_per_kg
µg/g|ug/g -> ug_per_g_to_mg_per_kg
ppb       -> ppb_mass_mass_times_0.001
wt%       -> wt_percent_times_10000
g/kg      -> g_per_kg_times_1000
```


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "说明这些等价只在题目已固定固体质量/质量基准时成立。",
   "id": "basis_scope",
   "points": 8
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "原值、原单位和转换规则逐行可追溯。",
   "id": "traceability",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "不使用会造成数量级变化的过早舍入。",
   "id": "precision",
   "points": 4
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-NORM-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-NORM-001",
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
   "evidence": "normalized_elements.csv: file"
  },
  {
   "id": "columns",
   "type": "csv_columns",
   "dimension_id": "platform_reusability",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "normalized_elements.csv: missing columns=[]"
  },
  {
   "id": "row_count",
   "type": "csv_row_count",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "normalized_elements.csv: rows=6; expected=6"
  },
  {
   "id": "key_set",
   "type": "csv_key_set",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv: actual keys=[('S01', 'Ni'), ('S02', 'Pb'), ('S03', 'Zn'), ('S04', 'Cu'), ('S05', 'Co'), ('S06', 'As')]; expected=[('S01', 'Ni'), ('S02', 'Pb'), ('S03', 'Zn'), ('S04', 'Cu'), ('S05', 'Co'), ('S06', 'As')]"
  },
  {
   "id": "s01_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv key={'sample_id': 'S01'} column=normalized_value actual='42' expected=42 tol=1e-06"
  },
  {
   "id": "s02_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv key={'sample_id': 'S02'} column=normalized_value actual='18' expected=18 tol=1e-06"
  },
  {
   "id": "s03_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv key={'sample_id': 'S03'} column=normalized_value actual='120' expected=120 tol=1e-06"
  },
  {
   "id": "s04_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv key={'sample_id': 'S04'} column=normalized_value actual='35' expected=35 tol=1e-06"
  },
  {
   "id": "s05_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv key={'sample_id': 'S05'} column=normalized_value actual='8' expected=8 tol=1e-06"
  },
  {
   "id": "s06_value",
   "type": "csv_cell",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "normalized_elements.csv key={'sample_id': 'S06'} column=normalized_value actual='400' expected=400 tol=1e-06"
  },
  {
   "id": "original_values",
   "type": "text_contains_all",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "normalized_elements.csv: missing terms=[]"
  },
  {
   "id": "conversion_rules",
   "type": "text_contains_all",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "normalized_elements.csv: missing terms=[]"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv
```
sample_id,element,original_value,original_unit,normalized_value,normalized_unit,conversion_rule
S01,Ni,42,ppm,42,mg/kg,ppm_mass_mass_to_mg_per_kg
S02,Pb,18,mg/kg,18,mg/kg,identity_mg_per_kg
S03,Zn,0.012,wt%,120,mg/kg,wt_percent_times_10000
S04,Cu,35,ug/g,35,mg/kg,ug_per_g_to_mg_per_kg
S05,Co,8000,ppb,8,mg/kg,ppb_mass_mass_times_0.001
S06,As,0.4,g/kg,400,mg/kg,g_per_kg_times_1000
```
