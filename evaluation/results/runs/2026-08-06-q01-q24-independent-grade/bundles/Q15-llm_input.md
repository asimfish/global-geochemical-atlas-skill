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

下文提到的 `points.geojson`、`map_manifest.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q15 点图 GeoJSON

从 `inputs/observations.csv` 生成 RFC 7946 GeoJSON `points.geojson` 和 `map_manifest.json`。

- 只纳入 `eligible_map=true`；
- Position 顺序必须为 `[longitude, latitude]`；
- features 按 record_id 排序；
- properties 保留 record_id、element、value、unit、medium、source_id、confidence_score、qc_flags；
- manifest 报告输入数、映射数、排除数、坐标顺序和 CRS84。

GeoJSON 本身不要添加旧式自定义 `crs` 成员。

`map_manifest.json.coordinate_order` 固定写 `longitude_latitude`，`geojson_crs_member_present` 必须为 JSON 布尔值 `false`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "每个 feature 能回链 record 和 source，且保留 QC/置信度。",
   "id": "traceability",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "排除无效点但在 manifest 计数，不假装输入只有两条。",
   "id": "exclusion",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "正确说明 GeoJSON longitude-latitude 与 CRS84。",
   "id": "standard",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/points.geojson",
  "artifacts/run_manifest.json#/benchmark_evidence/map_manifest.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-MAP-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-MAP-001",
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
   "evidence_points_awarded": 80,
   "evidence_points_possible": 80,
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
   "id": "geojson_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "points.geojson: file"
  },
  {
   "id": "manifest_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "map_manifest.json: file"
  },
  {
   "id": "feature_count",
   "type": "json_length",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "points.geojson path=features length=2; expected=2"
  },
  {
   "id": "map1_id",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "points.geojson path=features.0.id actual='MAP1' expected='MAP1'"
  },
  {
   "id": "map1_coords",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "points.geojson path=features.0.geometry.coordinates actual=[100, 10] expected=[100, 10]"
  },
  {
   "id": "map2_coords",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 12,
   "points_possible": 12,
   "evidence": "points.geojson path=features.1.geometry.coordinates actual=[-120, 40] expected=[-120, 40]"
  },
  {
   "id": "map1_properties",
   "type": "json_object_has_keys",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "points.geojson path=features.0.properties missing keys=[]"
  },
  {
   "id": "mapped_count",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "map_manifest.json path=mapped_features actual=2 expected=2"
  },
  {
   "id": "excluded_count",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "map_manifest.json path=excluded_rows actual=3 expected=3"
  },
  {
   "id": "coordinate_order",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 6,
   "points_possible": 6,
   "evidence": "map_manifest.json path=coordinate_order actual='longitude_latitude' expected='longitude_latitude'"
  },
  {
   "id": "no_crs_member",
   "type": "json_value",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "map_manifest.json path=geojson_crs_member_present actual=False expected=False"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/points.geojson
```json
{
 "type": "FeatureCollection",
 "features": [
  {
   "type": "Feature",
   "id": "MAP1",
   "geometry": {
    "type": "Point",
    "coordinates": [
     100,
     10
    ]
   },
   "properties": {
    "record_id": "MAP1",
    "element": "Ni",
    "value": 50,
    "unit": "mg/kg",
    "medium": "rock",
    "source_id": "SRC1",
    "confidence_score": 90,
    "qc_flags": []
   }
  },
  {
   "type": "Feature",
   "id": "MAP2",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -120,
     40
    ]
   },
   "properties": {
    "record_id": "MAP2",
    "element": "Pb",
    "value": 20,
    "unit": "mg/kg",
    "medium": "soil",
    "source_id": "SRC2",
    "confidence_score": 75,
    "qc_flags": []
   }
  }
 ]
}
```

### artifacts/run_manifest.json#/benchmark_evidence/map_manifest.json
```json
{
 "task_id": "GGA-MAP-001",
 "input_rows": 5,
 "mapped_features": 2,
 "excluded_rows": 3,
 "coordinate_order": "longitude_latitude",
 "crs": "CRS84",
 "geojson_crs_member_present": false
}
```
