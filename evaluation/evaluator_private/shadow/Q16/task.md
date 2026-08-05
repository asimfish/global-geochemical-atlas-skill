# Q16 热力图与网格聚合

按 `inputs/visualization_policy.json` 对 `inputs/cell_observations.csv` 预聚合，输出：

- `cells.csv`：cell_id、sample_count、quantified_count、median_value、censored_fraction；
- `heatmap_config.json`：冻结 aggregation、radius、color domain，并声明 sample-count 与 censored-fraction 图层；
- `heatmap.html`：包含标识 `GGA-HEATMAP-Q16`，以及 `sample_count`、`median_value` 字段说明。

删失值计入 sample_count 和 censored_fraction，但不进入 median。热力图只能称为探索性聚合视图，不得把样本密度表述为浓度。
