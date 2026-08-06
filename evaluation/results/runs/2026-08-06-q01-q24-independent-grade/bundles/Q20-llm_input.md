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

下文提到的 `island_points.geojson`、`spatial_manifest.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q20 反经线空间输出

把合法记录写入 `island_points.geojson`，并在 `spatial_manifest.json` 给出覆盖合法点的最小经度跨度 bbox。该集合跨反经线，bbox 按 RFC 7946 可出现 west > east。

manifest 必须包含 `bbox,crosses_antimeridian,longitude_span_deg,mapped_count,excluded_count,coordinate_order`。无效经度不得进入 GeoJSON。

`coordinate_order` 固定写 `longitude_latitude`；`crosses_antimeridian` 使用 JSON 布尔值。跨反经线 bbox 仍按 `[west,south,east,north]` 输出，允许 `west > east`。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "domain_understanding",
   "full_credit": "识别跨反经线表示，避免得到约 359.5° 的伪全球 bbox。",
   "id": "minimal_span",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "GeoJSON 位置使用 longitude-latitude。",
   "id": "axis",
   "points": 6
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "无效经度被排除且计入 manifest。",
   "id": "invalid",
   "points": 6
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/island_points.geojson",
  "artifacts/run_manifest.json#/benchmark_evidence/spatial_manifest.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-SPATIAL-003"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-SPATIAL-003",
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
   "id": "geojson_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "island_points.geojson: file"
  },
  {
   "id": "manifest_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "spatial_manifest.json: file"
  },
  {
   "id": "feature_count",
   "type": "json_length",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "island_points.geojson path=features length=2; expected=2"
  },
  {
   "id": "am01_coords",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "island_points.geojson path=features.0.geometry.coordinates actual=[179.8, -17.0] expected=[179.8, -17]"
  },
  {
   "id": "am02_coords",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "island_points.geojson path=features.1.geometry.coordinates actual=[-179.7, -18.0] expected=[-179.7, -18]"
  },
  {
   "id": "bbox",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 14,
   "points_possible": 14,
   "evidence": "spatial_manifest.json path=bbox actual=[179.8, -18.0, -179.7, -17.0] expected=[179.8, -18, -179.7, -17]"
  },
  {
   "id": "crosses",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "spatial_manifest.json path=crosses_antimeridian actual=True expected=True"
  },
  {
   "id": "span",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "spatial_manifest.json path=longitude_span_deg actual=0.5 expected=0.5"
  },
  {
   "id": "mapped",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "spatial_manifest.json path=mapped_count actual=2 expected=2"
  },
  {
   "id": "excluded",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "spatial_manifest.json path=excluded_count actual=1 expected=1"
  },
  {
   "id": "order",
   "type": "json_value",
   "dimension_id": "domain_understanding",
   "passed": true,
   "points_awarded": 4,
   "points_possible": 4,
   "evidence": "spatial_manifest.json path=coordinate_order actual='longitude_latitude' expected='longitude_latitude'"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/island_points.geojson
```json
{
 "type": "FeatureCollection",
 "features": [
  {
   "type": "Feature",
   "id": "AM01",
   "geometry": {
    "type": "Point",
    "coordinates": [
     179.8,
     -17.0
    ]
   },
   "properties": {
    "record_id": "AM01",
    "value": 10
   }
  },
  {
   "type": "Feature",
   "id": "AM02",
   "geometry": {
    "type": "Point",
    "coordinates": [
     -179.7,
     -18.0
    ]
   },
   "properties": {
    "record_id": "AM02",
    "value": 20
   }
  }
 ]
}
```

### artifacts/run_manifest.json#/benchmark_evidence/spatial_manifest.json
```json
{
 "task_id": "GGA-SPATIAL-003",
 "bbox": [
  179.8,
  -18.0,
  -179.7,
  -17.0
 ],
 "crosses_antimeridian": true,
 "longitude_span_deg": 0.5,
 "mapped_count": 2,
 "excluded_count": 1,
 "coordinate_order": "longitude_latitude"
}
```
