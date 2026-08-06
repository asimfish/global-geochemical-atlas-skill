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

下文提到的 `dataset_decision.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q02 美国本土土壤 Pb 数据源匹配

目标是生成美国本土（CONUS）土壤 Pb 分布图。根据 `inputs/source_catalog.json` 选择唯一主数据源，并说明其他候选为什么不能替代该主数据源。

输出 `dataset_decision.json`：

```json
{
  "task_id": "GGA-DATA-002",
  "target_region": "conterminous_united_states",
  "target_medium": "soil",
  "selected_source_id": "...",
  "alternatives": [{"source_id": "...", "decision": "reject_as_primary|supplement_only", "reason": "..."}]
}
```

不得因为某来源“全球”或“欧洲协调”就忽略目标区域，也不得把岩石主库当成土壤主库。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "明确 GEMAS 的欧洲范围不能替代 CONUS。",
   "id": "region",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "明确 GEOROC 的主要介质不匹配土壤任务。",
   "id": "medium",
   "points": 7
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "不把 WoSIS 一概否定，但指出 Pb 属性、方法和覆盖仍需核验。",
   "id": "wosis_boundary",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/dataset_decision.json/alternatives",
  "inputs/source_catalog.json:sources"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-DATA-002"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-DATA-002",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 80,
 "evidence_points_possible": 80,
 "dimensions": [
  {
   "dimension_id": "scientific_credibility",
   "weight": 0.25,
   "evidence_points_awarded": 75,
   "evidence_points_possible": 75,
   "evidence_score": 100.0,
   "status": "scored"
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
   "id": "output_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "dataset_decision.json: file"
  },
  {
   "id": "selected_usgs",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 20,
   "points_possible": 20,
   "evidence": "dataset_decision.json path=selected_source_id actual='usgs_ngdb' expected='usgs_ngdb'"
  },
  {
   "id": "region_exact",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "dataset_decision.json path=target_region actual='conterminous_united_states' expected='conterminous_united_states'"
  },
  {
   "id": "medium_exact",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "dataset_decision.json path=target_medium actual='soil' expected='soil'"
  },
  {
   "id": "alternatives_count",
   "type": "json_length",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "dataset_decision.json path=alternatives length=3; expected=3"
  },
  {
   "id": "georoc_reject",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "dataset_decision.json path=alternatives.0.decision actual='reject_as_primary' expected='reject_as_primary'"
  },
  {
   "id": "gemas_reject",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "dataset_decision.json path=alternatives.1.decision actual='reject_as_primary' expected='reject_as_primary'"
  },
  {
   "id": "wosis_supplement",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "dataset_decision.json path=alternatives.2.decision actual='supplement_only' expected='supplement_only'"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/dataset_decision.json/alternatives
```json
[
 {
  "source_id": "georoc",
  "decision": "reject_as_primary",
  "reason": "Medium mismatch: its media are igneous/metamorphic rock, mineral and volcanic glass, not soil; it is also a global compilation rather than a CONUS-authoritative database."
 },
 {
  "source_id": "gemas",
  "decision": "reject_as_primary",
  "reason": "Region mismatch: GEMAS covers 33 European countries only and cannot serve a conterminous United States soil map."
 },
 {
  "source_id": "wosis",
  "decision": "supplement_only",
  "reason": "Global soil-profile holdings can supplement coverage, but it is not CONUS-specific, available properties and method detail depend on source metadata, so it cannot replace the national database as primary."
 }
]
```

### inputs/source_catalog.json:sources
```json
[
 {
  "source_id": "usgs_ngdb",
  "regions": [
   "united_states",
   "territories"
  ],
  "media": [
   "rock",
   "sediment",
   "soil",
   "mineral"
  ],
  "record_level_coordinates": true,
  "authority_url": "https://www.usgs.gov/centers/gggsc/science/national-geochemical-database"
 },
 {
  "source_id": "georoc",
  "regions": [
   "global"
  ],
  "media": [
   "igneous_rock",
   "metamorphic_rock",
   "mineral",
   "volcanic_glass"
  ],
  "record_level_coordinates": true,
  "authority_url": "https://georoc.eu/georoc/precompiled/"
 },
 {
  "source_id": "gemas",
  "regions": [
   "europe_33_countries"
  ],
  "media": [
   "agricultural_soil",
   "grazing_land_soil"
  ],
  "record_level_coordinates": true,
  "authority_url": "https://eurogeosurveys.org/projects/gemas/"
 },
 {
  "source_id": "wosis",
  "regions": [
   "global"
  ],
  "media": [
   "soil_profile"
  ],
  "record_level_coordinates": true,
  "authority_url": "https://docs.isric.org/globaldata/wosis/faq-wosis.html",
  "note": "available properties and method detail depend on source metadata"
 }
]
```
