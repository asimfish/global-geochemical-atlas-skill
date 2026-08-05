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

`provenance_plan.json` 必须列出每条观测需保留的字段，并明确下载文件需要 SHA-256 完整性校验。选择理由要区分“数据主来源”和“联合发现服务”，拒绝无稳定来源、无版本、无许可的网页汇总。

正确答案不要求声称实时下载成功；本题只评数据源范围匹配与 provenance 计划。
