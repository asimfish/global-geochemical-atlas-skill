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
