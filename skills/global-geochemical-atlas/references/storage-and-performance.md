# D1 存储、缓存与性能契约

更新：2026-08-07（Asia/Shanghai）

契约版本：`d1-storage-contract-v2-no-content-hash`

本文件规定 D1 如何保存来源原件、结构化归档、派生索引和一次获取结果。速度不能绕过来源准入、版本、文件身份、字节数、schema、数量、完整性或证据链检查。V4 不计算或校验内容哈希。

## 1. 四层存储

| 层 | 建议位置 | 内容 | 是否提交 Git |
|---|---|---|---|
| 来源原件缓存 | `<cache-dir>/<source_id>/<dataset_version>/` | 发布方原文件、下载 manifest、只读解压结果 | 否 |
| 结构化归档 | `outputs/acquisition/<run_id>/archive-bundle.json` 或等价分表文件 | 数据集、文献、采样、样品、方法、测定、证据、运行 | 否；仅合成 fixture 可提交 |
| 派生查询索引 | `outputs/acquisition/<run_id>/index.sqlite` | 从归档包重建的 SQLite 索引 | 否 |
| D1 交换交付 | `outputs/acquisition/<run_id>/` | `raw_observations.csv`、`sources.jsonl`、`run_manifest.json`、`coverage.json` | 通常否；仅小型 fixture 可提交 |

SQLite 不是科学事实的唯一副本。删除索引后，必须能用同一归档 schema、代码版本、输入文件身份和记录数重新生成。

## 2. 一次 acquisition 的最低输出

```text
outputs/acquisition/<run_id>/
  archive-bundle.json       # 分层、可验证的 D1 原值归档
  raw_observations.csv      # 一行一个测定，兼容 D2
  sources.jsonl             # 一条观测对应一条来源证明
  run_manifest.json         # 请求、版本、文件身份、schema、数量、耗时和状态
  coverage.json             # covered / partial / uncovered / unknown
  index.sqlite              # 可选派生物，不作为唯一交付
```

`run_manifest.json` 必须对账 `source_records = observations + rejected_records + failed_records` 适用的来源级数量，并记录所有输出的路径、文件身份、字节数、schema 和行数。失败或降级运行仍需写明状态和原因，不能只留下一个看似正常的 CSV。

## 3. 两类缓存身份

来源原件缓存和查询结果缓存不能混为一谈：

- 来源原件如果是不可变整库文件，以 `source_id + DOI/PID + dataset_version + file_id/filename + bytes` 验证；地区、元素等查询条件不改变该原件。
- API 响应、筛选结果和其他派生缓存，使用规范化请求的可读序列化文本作为请求身份，并记录 `source_id + dataset_version`。地区、介质、分析物、时间、来源或科研使用条件变化时，必须生成新缓存条目。

`cache_control.py` 实现 V4 无哈希缓存身份。JSON 对象键顺序不影响规范化请求文本，但数组顺序按请求原义保留。缓存命中仍需重新核对 URL、DOI/PID、版本、文件身份、字节数、schema、行数和关键统计；仅目录或文件名相同不能视为命中。

查看一个明确来源版本：

```bash
python3 scripts/cache_control.py status \
  --cache-dir /path/to/cache \
  --source-id usgs-conus-soil \
  --dataset-version 2013-11-28 \
  --request request.json
```

删除必须同时给出缓存根、来源、版本和精确确认串：

```bash
python3 scripts/cache_control.py delete \
  --cache-dir /path/to/cache \
  --source-id usgs-conus-soil \
  --dataset-version 2013-11-28 \
  --confirm usgs-conus-soil@2013-11-28
```

命令拒绝通配符、路径跳转、符号链接和模糊确认；不会自动清理未知目录。删除是不可恢复操作，因此生产使用前应先执行 `status` 并保留所需 manifest。

## 4. SQLite 索引与查询

`references/sqlite-schema.sql` 包含：

- 数据集、文献、采样事件、样品、方法、获取运行、证据和测定表；
- 外键、常用 B-tree 索引、采样点 RTree 和说明文字 FTS5；
- `observation_search`、`sample_summary`、`source_coverage`、`provenance_trace` 四个视图。

构建索引会先验证归档包，在同目录临时文件中完成写入和完整性检查，再原子替换为目标文件。目标已经存在时拒绝覆盖。

```bash
python3 scripts/build_index.py \
  --bundle fixtures/schema-v1/archive-bundle.json \
  --output /tmp/d1-index.sqlite
```

查询入口只以只读模式打开 SQLite，所有条件参数化，单次最多返回 10,000 条：

```bash
python3 scripts/query_source.py \
  --index /tmp/d1-index.sqlite \
  --bbox 73 18 135 54 \
  --medium soil \
  --analyte As \
  --source-id usgs-conus-soil \
  --license-id CC0-1.0
```

支持 bbox、介质、分析物、来源、许可、原始方法、时间和全文条件。时间条件当前只对来源原始 `sampled_at_raw` 做 ISO 字符串比较；非 ISO 日期不得据此扩大科学结论，需待 D2 或后续有证据的日期解析层处理。

## 5. 性能基线

命令：

```bash
python3 scripts/benchmark_index.py --records 100000
```

2026-08-05 本机首次记录：

| 项目 | 结果 |
|---|---:|
| 合成测定数 | 100,000 |
| 解析并写入索引 | 0.354098 秒 |
| 条件筛选 | 0.007049 秒 |
| 合计 | 0.361147 秒 |
| 目标 | 小于 10 秒 |
| SQLite 完整性 | `ok` |

这是合成性能 fixture，不是科学数据，也不代表真实网络下载速度。脚本每次运行都新建临时 SQLite，写入 10 万条测定并执行实际筛选；契约测试只判断是否低于 10 秒，不要求复现某个小数值。真实下载、在线复用、离线复用和错误注入结果另见 `download-cache-tests.md`。

## 6. 失败关闭与复现

- 没有网络且无验证缓存：返回 `network_unavailable`，不伪造空数据为“无覆盖”。
- URL、DOI/PID、版本、文件身份、字节数、schema、行数、关键统计或规范化请求不一致：拒绝复用。
- SQLite 外键或完整性检查失败：不发布索引。
- 相同归档包和 schema 必须产生相同记录集合；fixture 测试检查 SQLite 完整性、表行数和关键查询结果。
- 完整来源文件、缓存和索引受 `.gitignore` 约束，不进入仓库。
- 查询结果始终保留 `value_raw`、限定符、方法和证据，不在索引层执行单位换算、异常判断或地质推测。
