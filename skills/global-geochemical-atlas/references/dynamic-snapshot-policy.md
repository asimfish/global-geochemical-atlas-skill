# D1 动态来源快照政策

版本：`geochemical-dynamic-snapshot-v4`

## 适用范围

当官方 API 或下载服务没有对应的不可变 DOI/发布版本时，使用“精确请求 + UTC 获取时间 + 文件身份 + 字节数 + 成员清单 + schema + 行数与关键统计”形成项目快照。快照只描述一次已观察响应，不冒充发布方版本或 DOI。

已有不可变发布版本时优先使用发布版本；动态快照与后来出现的 DOI 可以并存，通过 `isVersionOf/replaces` 关系关联。V4 不计算或校验 MD5、SHA-256 等内容哈希；历史字段只做格式兼容，不读取、比对或更新。

## 最小证据

每个快照至少记录：

- `source_id`、`snapshot_id` 和快照类型；
- DOI/PID、数据集版本、发布日期（如有）；
- HTTP 方法、完整请求 URL、端点和有序参数；
- UTC 获取时间、响应状态、类型和字节数；
- 归档文件名、文件 ID（如有）及全部成员的名称和大小；
- 必需字段清单/schema fingerprint、原始行数、解析数、拒绝数、失败数和不同样品数；
- 关键分类计数、元素计数和实际空间/时间范围；
- 获取/验证脚本版本；
- 本次科研使用状态、署名、引用、限制和证据出处。

原 acquisition manifest 没有保存某项事实时必须写 `missing` 或 `null`，不能从成功文件反推具体 HTTP 状态。

## ID 与存储

```text
snapshot_id = <source_id>:<dataset_version-or-observed_at>:<sequence>
```

- 完整第三方响应进入仓库外的只读缓存；
- Git 只保存 snapshot manifest、字段与数量统计、抽样复核和允许提交的小 fixture；
- 新响应创建新 snapshot，不覆盖旧目录；
- 相同请求的文件身份、大小、schema、行数或关键统计变化时必须生成 diff；
- 只有成员、schema、数量和关系对账通过，才能把响应表述为完整快照；
- 文件损坏、响应截断或分页不完整时保留失败证据，但不得标记完整。

## 变化检测

`scripts/snapshot_source.py diff` 比较：

- 精确请求和来源版本；
- 响应文件名、文件 ID、字节数和成员清单；
- schema、记录/样品数量和关键统计；
- 科研使用条件、限制文本和获取时间。

结果：

- `identical`：上述身份与统计完全相同；
- `content_unchanged_new_observation`：只有观测时间或 snapshot ID 变化；
- `changed`：请求、版本、文件身份、成员、schema、数量、科研使用条件或限制发生变化，需重新评分和抽样复核。

## MarChem 基线

```text
source_id: norway-marchem
snapshot_id: norway-marchem:2026-08-05T10:27:11Z:3
raw_records: 1070
distinct_samples: 880
archive_members: 3
identity_basis: source_id + request + observation time + member inventory + byte counts
```

该快照可以进入适配器开发和科研分析路由。它是官方动态 API 的一次已观察响应，不是发布方 DOI；动态服务以后返回的内容可能变化。

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
