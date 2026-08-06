<!-- e1-alignment-v1 -->
## E1 统一交卷要求

只生成 `task.json.required_outputs` 列出的十个 E1 物理产物，并保持 `artifacts/` 固定路径。不得另外创建题目专用文件。

下文提到的 `verification_report.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q05 下载资产完整性与媒体类型验证

将 `inputs/` 视为一次冻结下载缓存。根据 `inputs/download_manifest.json` 验证每个文件：

- 实际 SHA-256 是否与 manifest 一致；
- 内容是否真的是预期 CSV，而不是 HTML 错误页；
- 是否可以进入后续科学处理。

输出 `verification_report.json`，每条记录包含：

```text
filename,computed_sha256,sha256_status,media_type_status,safe_to_use,reasons
```

只有哈希匹配且内容是 CSV 的文件才可 `safe_to_use=true`。不得修改输入文件来迎合 manifest。
