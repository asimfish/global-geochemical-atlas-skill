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

下文提到的 `source_selection.json`、`provenance_plan.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q01 全球玄武岩 Ni 数据源选择

你需要为“全球玄武岩 Ni 元素分布数据库”选择数据源。只能根据 `inputs/data_sources.json` 中冻结的目录作答，不进行实时网络搜索，也不得添加目录之外的 DOI 或数据集。

生成：

1. `source_selection.json`
2. `provenance_plan.json`

`source_selection.json` 必须包含：

```json
{
  "task_id": "GGA-DATA-001",
  "target": {"medium": "rock", "lithology": "basalt", "element": "Ni", "coverage": "global"},
  "primary_source_id": "...",
  "discovery_source_id": "...",
  "decisions": [{"source_id": "...", "status": "primary|discovery|reject", "reason": "..."}]
}
```

`provenance_plan.json` 使用以下精确字段：

```json
{
  "task_id": "GGA-DATA-001",
  "record_fields": [
    "source_id",
    "source_record_id",
    "dataset_title",
    "dataset_version",
    "dataset_doi",
    "source_url",
    "accessed_at",
    "license",
    "sha256",
    "citation"
  ],
  "download_sha256_required": true,
  "allowed_example_doi": "10.25625/2JETOA",
  "on_missing_provenance": "exclude_from_scientific_primary_dataset"
}
```

`record_fields` 可以增加字段，但必须至少包含上述十项。缺失必要 provenance 的记录使用 `on_missing_provenance=exclude_from_scientific_primary_dataset`。`allowed_example_doi` 只能使用冻结目录中已提供的 DOI，不得自行添加其他 DOI。选择理由要区分“数据主来源”和“联合发现服务”，拒绝无稳定来源、无版本、无许可的网页汇总。

正确答案不要求声称实时下载成功；本题只评数据源范围匹配与 provenance 计划。


RUBRIC:
```json
{
 "automatic_zero": [
  "引用目录不存在的 DOI 或声称随机网页表具有已核验科学来源"
 ],
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "明确把全球玄武岩 Ni 与岩石介质、全球覆盖和分析元数据对应起来。",
   "id": "scope_reasoning",
   "points": 8
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "区分 GEOROC 可冻结主数据资产与 EarthChem 联合发现角色，不重复计算成两个独立来源。",
   "id": "source_roles",
   "points": 6
  },
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "说明目录快照不等于实时下载成功，并给出 provenance 缺失时的排除或降级。",
   "id": "limitations",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/source_selection.json/decisions",
  "artifacts/run_manifest.json#/benchmark_evidence/provenance_plan.json/record_fields"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-DATA-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-DATA-001",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 80,
 "evidence_points_possible": 80,
 "dimensions": [
  {
   "dimension_id": "scientific_credibility",
   "weight": 0.25,
   "evidence_points_awarded": 72,
   "evidence_points_possible": 72,
   "evidence_score": 100.0,
   "status": "scored"
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
   "id": "selection_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "source_selection.json: file"
  },
  {
   "id": "provenance_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "provenance_plan.json: file"
  },
  {
   "id": "primary_georoc",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "source_selection.json path=primary_source_id actual='georoc_precompiled' expected='georoc_precompiled'"
  },
  {
   "id": "discovery_earthchem",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "source_selection.json path=discovery_source_id actual='earthchem_portal' expected='earthchem_portal'"
  },
  {
   "id": "decision_count",
   "type": "json_length",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "source_selection.json path=decisions length=3; expected=3"
  },
  {
   "id": "target_medium",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "source_selection.json path=target.medium actual='rock' expected='rock'"
  },
  {
   "id": "target_lithology",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "source_selection.json path=target.lithology actual='basalt' expected='basalt'"
  },
  {
   "id": "reject_random",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 9,
   "points_possible": 9,
   "evidence": "source_selection.json path=decisions.2.status actual='reject' expected='reject'"
  },
  {
   "id": "provenance_fields",
   "type": "json_array_contains",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 13,
   "points_possible": 13,
   "evidence": "provenance_plan.json path=record_fields missing=[]"
  },
  {
   "id": "hash_required",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "provenance_plan.json path=download_sha256_required actual=True expected=True"
  },
  {
   "id": "doi_whitelist",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 7,
   "points_possible": 7,
   "evidence": "provenance_plan.json path=allowed_example_doi actual='10.25625/2JETOA' expected='10.25625/2JETOA'"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/source_selection.json/decisions
```json
[
 {
  "source_id": "georoc_precompiled",
  "status": "primary",
  "reason": "Global compilation whose scope explicitly covers igneous rock (basalt); versioned files, record-level coordinates/method metadata and a frozen example compilation DOI (10.25625/2JETOA) make it the primary data source."
 },
 {
  "source_id": "earthchem_portal",
  "status": "discovery",
  "reason": "Federated geochemical discovery service aggregating PETDB/GEOROC/USGS NGDB; used as joint discovery service for cross-searching, not as the primary data store."
 },
 {
  "source_id": "random_web_table",
  "status": "reject",
  "reason": "Web aggregation with unspecified rock scope, claimed-global coverage, no DOI, no versioned files, no license and no metadata; no stable source or provenance, rejected."
 }
]
```

### artifacts/run_manifest.json#/benchmark_evidence/provenance_plan.json/record_fields
```json
[
 "source_id",
 "source_record_id",
 "dataset_title",
 "dataset_version",
 "dataset_doi",
 "source_url",
 "accessed_at",
 "license",
 "sha256",
 "citation"
]
```
