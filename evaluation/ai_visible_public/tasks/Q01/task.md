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
