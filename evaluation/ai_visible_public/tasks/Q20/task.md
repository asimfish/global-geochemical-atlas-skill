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
