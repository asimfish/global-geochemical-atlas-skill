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

下文提到的 `verification_report.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q05 下载资产完整性与媒体类型验证

将 `inputs/` 视为一次冻结下载缓存。根据 `inputs/download_manifest.json` 验证每个文件：

- 实际 SHA-256 是否与 manifest 一致；
- 内容是否真的是预期 CSV，而不是 HTML 错误页；
- 是否可以进入后续科学处理。

输出 `verification_report.json`。JSON 根对象必须包含 `task_id` 和 `records`；不得把记录数组直接作为 `value`：

```json
{
  "task_id": "GGA-PROV-001",
  "records": [
    {
      "filename": "...",
      "computed_sha256": "...",
      "sha256_status": "match|mismatch",
      "media_type_status": "csv|html_detected",
      "safe_to_use": false,
      "reasons": []
    }
  ]
}
```

每条记录包含：

```text
filename,computed_sha256,sha256_status,media_type_status,safe_to_use,reasons
```

只有哈希匹配且内容是 CSV 的文件才可 `safe_to_use=true`。不得修改输入文件来迎合 manifest。

冻结枚举为：

- `sha256_status`：`match` 或 `mismatch`；
- `media_type_status`：内容为 CSV 时写 `csv`，检测到 HTML 时写 `html_detected`；
- `safe_to_use`：JSON 布尔值，不使用字符串；
- 推荐 `reasons` 值：`content_is_html_not_csv`、`sha256_mismatch`；无问题时使用空数组。
