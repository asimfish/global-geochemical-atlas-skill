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
