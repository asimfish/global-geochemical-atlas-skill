# Q20 反经线空间输出

把合法记录写入 `island_points.geojson`，并在 `spatial_manifest.json` 给出覆盖合法点的最小经度跨度 bbox。该集合跨反经线，bbox 按 RFC 7946 可出现 west > east。

manifest 必须包含 `bbox,crosses_antimeridian,longitude_span_deg,mapped_count,excluded_count,coordinate_order`。无效经度不得进入 GeoJSON。
