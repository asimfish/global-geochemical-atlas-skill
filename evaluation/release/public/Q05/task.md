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
