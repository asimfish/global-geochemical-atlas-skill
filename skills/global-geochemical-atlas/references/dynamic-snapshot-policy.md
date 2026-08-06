# D1 动态来源快照政策

版本：`geochemical-dynamic-snapshot-v3`

## 适用范围

当官方 API 或下载服务没有对应不可变 DOI/发布版本时，使用“精确请求 + UTC 获取时间 + 原始响应 SHA-256 + 全部文件成员清单”形成项目快照。快照固定的是一次已观察响应，不冒充发布方版本或 DOI。

已有不可变发布版本时优先使用发布版本；动态快照与后来出现的 DOI 可以并存，通过 `isVersionOf/replaces` 关系关联，不修改历史 hash。

## 最小证据

每个快照至少记录：

- `source_id`、`snapshot_id` 和 `snapshot_kind=dynamic_api_snapshot`；
- HTTP 方法、完整请求 URL、端点、参数顺序和 canonical request SHA-256；
- UTC 获取时间；
- 响应状态、类型、字节数和 SHA-256；
- 归档文件名及全部成员的名称、大小和 SHA-256；
- 请求范围与实际经纬度、时间、元素范围；
- 原始、解析、拒绝、失败和不同样品数量；
- 获取/验证脚本版本；
- 本次科研使用状态、署名和引用；
- 已知限制和证据来源。

原 acquisition manifest 没有保存某项事实时必须写 `missing` 或 `null`，不能从成功文件反推具体 HTTP 状态。本次 MarChem 首个快照已明确记录 `http_status=null`，后续重新获取时补齐真实状态。

## ID 与存储

```text
snapshot_id = <source_id>:<observed_at>:<response_sha256前12位>
```

- 完整第三方响应进入仓库外的只读内容寻址缓存；
- Git 只保存 snapshot manifest、hash、字段统计、抽样复核和允许分发的小 fixture；
- 新响应创建新 snapshot，不覆盖旧目录；
- 相同请求获得不同 hash 时必须生成 diff；
- 只有 hash、成员、数量和关系对账通过，才能把响应表述为完整快照；
- 文件损坏、响应截断或分页不完整时保留失败证据，但不得标记完整。

## 变化检测

`scripts/snapshot_source.py diff` 比较：

- canonical request；
- 原始响应 hash；
- 成员新增、删除和内容变化；
- 记录/样品数量；
- 科研使用条件；
- 限制文本；
- 获取时间。

结果：

- `identical`：同一 manifest；
- `content_unchanged_new_observation`：时间或 snapshot ID 不同，但请求和内容证据相同；
- `changed`：请求、内容、成员、数量、科研使用条件或限制发生变化，必须重新评分和复核。

## MarChem 基线

```text
source_id: norway-marchem
snapshot_id: norway-marchem:2026-08-05T10:27:11Z:be888784ee2e
request_sha256: ae8fd044ad9a43c0fba34d18fdcbf677311f77da1cdb76094c6054c447eb3445
response_sha256: be888784ee2eafd45ab43c036eefbae9e760057d25f64fbc323993e8809ca6c6
raw_records: 1070
distinct_samples: 880
archive_members: 3
```

该快照可以进入适配器开发和原始观察，不因缺少发布方 checksum 或人工复核而删除；它当前仍不是 `normalized_analysis` 或 `benchmark_ready`。

## 命令

```bash
python scripts/snapshot_source.py create \
  --candidate-evidence fixtures/candidate-audits/marchem-inorganic-20260805T102709Z.json \
  --output fixtures/four-media/sediment/norway-marchem/snapshot_manifest.json

python scripts/snapshot_source.py diff \
  --before OLD/snapshot_manifest.json \
  --after NEW/snapshot_manifest.json \
  --output snapshot_diff.json
```
