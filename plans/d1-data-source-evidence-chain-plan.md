# D1：数据源、证据链与数据工程执行计划

## 计划信息

| 项目 | 内容 |
|---|---|
| 负责人 | 李明伟 |
| 状态 | 进行中 |
| 优先级 | P0（MVP 必需） |
| 启动日期 | 2026-08-05 |
| 目标完成日期 | 2026-08-13（7 个工作日） |
| 最近更新 | 2026-08-05 14:15 CST |
| 跟踪方式 | 本文件任务勾选状态 + Git 提交记录 |
| 工作分支 | `d1/data-source-engineering` |
| 生产目录 | `skills/global-geochemical-atlas/` |

## 一、执行目标

建设一套合法、可复现、可离线、可追溯的数据接入流程。MVP 首期支持：

- GEOROC Archaean Cratons 岩石数据；
- USGS CONUS 土壤数据；
- 仓库内置的小型 fixture/demo 数据；
- `online`、`cached`、`fixture` 三种运行模式。

最终要保证每条进入系统的数据都能追溯到原始文件、原始记录位置、数据集版本、DOI 或官方来源、许可信息和文件校验和；下载、版本、格式和许可问题不得被静默忽略。

## 二、范围边界

### 本计划包含

- 数据源登记、许可和引用信息维护；
- 数据下载、缓存、校验和安全解压；
- GEOROC、USGS 数据源适配器；
- 原始字段解析和逐条证据链；
- 可随仓库分发的确定性 demo 数据；
- 网络、来源、格式、字段和许可失败时的降级策略；
- 来源可靠性和证据完整性相关的置信度输入；
- 下载、缓存、证据链和失败模式测试。

### 本计划不包含

- 异常检测阈值和科学质控规则，由 D2 负责；
- 最终单位换算、检出限处理和标准字段值，由 D2 负责；
- 最终 Skill 目录结构和入口编排，由 D3 负责；
- PDF 全文表格抽取、扫描件 OCR 和批量全文抓取；
- MVP 之外的数据源适配器。

## 三、里程碑

| 里程碑 | 日期 | 状态 | 完成标准 |
|---|---|---|---|
| M0：范围和接口冻结 | 2026-08-05 | 已完成 | 数据源、字段边界、CLI 和输出路径达成一致 |
| M1：数据源注册完成 | 2026-08-06 | 已完成 | 两个数据源的版本、许可、引用和校验规则完整 |
| M2：下载与缓存框架完成 | 2026-08-07 | 已完成 | online/cached 可运行，具备超时、重试、校验和安全写入 |
| M3：两个适配器可运行 | 2026-08-10 | 进行中 | GEOROC、USGS 均可下载、校验并解析原始记录 |
| M4：Demo 与证据链完成 | 2026-08-11 | 未开始 | fixture 可离线运行，逐条来源和运行清单完整 |
| M5：失败模式测试完成 | 2026-08-12 | 未开始 | 关键异常均有明确错误或降级路径 |
| M6：联调与 MVP 验收 | 2026-08-13 | 未开始 | 通过 D2、D3、E1 联调及本文件验收清单 |

状态统一使用：`未开始`、`进行中`、`已完成`、`阻塞`。

## 四、工作分解

### 阶段 0：冻结范围和接口

- [x] 确认 MVP 数据源为 GEOROC Archaean Cratons 和 USGS CONUS 土壤数据。
- [x] 定义统一的 `DataSourceAdapter` 接口：`discover`、`download`、`parse`、`provenance`。
- [x] 定义 `source_id`、`record_id`、`source_record_id` 的稳定生成规则。
- [x] 与 D2 确认原始字段、单位字段和置信度来源分量的交接格式。
- [x] 与 D3 确认 CLI 参数、运行返回码、文件位置和输出文件名。
- [x] 与 E1 确认下载、离线和故障注入测试的运行入口。

上述三个跨角色接口以 `CONTRIBUTING.md`、`component_test.py` 和现有 JSON Schema 为当前冻结基线。

建议 CLI：

```bash
python skills/global-geochemical-atlas/scripts/download_data.py \
  --source georoc_archaean_cratons \
  --mode online \
  --cache-dir .cache/data \
  --output-dir outputs/data
```

### 阶段 1：数据源注册与许可梳理

- [x] 创建 `assets/source_manifest.json`。
- [x] 登记 GEOROC 的标题、DOI、版本、下载地址、文件类型、许可和标准引用。
- [x] 登记 USGS 的标题、官方地址、版本、文件类型、许可和标准引用。
- [x] 记录每个数据源的必要文件、必要字段和预期校验规则。
- [x] 明确 demo 切片是否允许随仓库再分发。
- [x] 区分项目代码许可和第三方数据许可。
- [x] 在文档中标注 GEOROC 预编译值的选择机制及其科学限制。
- [x] 创建 `references/data-sources.md` 和 `references/licenses-and-citations.md`。

### 阶段 2：下载和缓存框架

- [x] 实现 `scripts/download_data.py`。
- [x] 下载时先写入 `.part` 临时文件，成功后原子重命名。
- [x] 设置连接超时和读取超时。
- [x] 仅对 `429`、`502`、`503`、`504` 等可恢复 HTTP 错误进行有限重试。
- [x] 设置单文件最大下载体积。
- [x] 检查 Content-Type，拒绝将 HTML 错误页当作数据文件。
- [x] 计算并验证 SHA-256。
- [x] 安全解压 ZIP，阻止路径穿越。
- [x] 校验必要文件和必要字段。
- [x] 记录最终 URL、ETag、Last-Modified、下载时间和文件 hash。
- [x] 有效缓存存在时不重复联网。
- [x] 来源版本或 hash 变化时停止，并要求更新注册表或明确确认。

### 阶段 3：数据源适配器和原始解析

- [ ] 实现 `GeorocAdapter`。
- [ ] 实现 `UsgsSoilAdapter`。
- [ ] 实现 `scripts/inspect_source.py`，输出文件结构、字段和基础统计。
- [ ] 保留原始报告值、原始单位、样品编号、分析方法、实验室和坐标。
- [ ] 保留原始文件名、工作表、行号或来源记录编号。
- [ ] 有 IGSN 时完整保留。
- [ ] 不在 D1 内执行异常阈值判断或最终单位标准化。

### 阶段 4：Demo 数据和证据链

- [ ] 实现 `scripts/generate_demo_data.py`。
- [ ] 生成一个岩石 demo 切片和一个土壤 demo 切片。
- [ ] 固定筛选条件、排序方式和随机种子。
- [ ] 记录原始记录数、筛选条件、demo 记录数和输出 hash。
- [ ] 验证重复生成得到相同内容和 SHA-256。
- [ ] 生成逐条来源记录 `sources.jsonl`。
- [ ] 生成运行清单 `run_manifest.json`。
- [ ] 生成 D1 来源分量相关的 `confidence_report.json`。
- [ ] fixture 输出明确包含：

```json
{
  "data_mode": "fixture",
  "scientific_scope": "pipeline demonstration only",
  "not_for_scientific_interpretation": true
}
```

### 阶段 5：降级策略和失败模式

- [ ] 网络失败时优先使用通过校验的缓存。
- [ ] 无网络且无缓存时返回结构化错误。
- [ ] 403 或授权失败时停止，不尝试绕过访问限制。
- [ ] HTML 伪文件、文件损坏和 checksum 不一致时拒绝使用。
- [ ] 来源格式变化或必要字段缺失时停止解析，并报告具体差异。
- [ ] 数据源版本变化时要求更新注册表。
- [ ] 许可不允许再分发时仅保留下载脚本和来源说明。
- [ ] 所有真实来源不可用时允许 fixture 演示，但禁止科学解释。
- [ ] DOI 无开放全文时只保留文献元数据。
- [ ] 无法可靠提取的 PDF 或扫描件不输出数值。
- [ ] 创建 `references/failures.md`。

### 阶段 6：测试、联调和交付

- [ ] 测试首次在线下载成功。
- [ ] 测试第二次运行命中缓存。
- [ ] 测试 `cached` 模式完全不访问网络。
- [ ] 测试 `fixture` 模式可在断网环境运行。
- [ ] 测试超时和有限重试。
- [ ] 测试 HTML 伪文件和超出大小限制。
- [ ] 测试 checksum 不一致和 ZIP 路径穿越。
- [ ] 测试必要文件或字段缺失。
- [ ] 测试数据源版本变化。
- [ ] 测试每条输出记录均可关联合法 `source_id`。
- [ ] 与 D2 完成原始字段和置信度输入联调。
- [ ] 与 D3 完成 CLI、目录和运行输出联调。
- [ ] 由 E1 在全新环境执行在线、缓存、离线和故障测试。
- [ ] 整理下载与缓存测试记录。

## 五、预期交付物

```text
skills/global-geochemical-atlas/
  scripts/
    download_data.py
    inspect_source.py
    generate_demo_data.py
  assets/
    source_manifest.json
  references/
    data-sources.md
    licenses-and-citations.md
    failures.md
  fixtures/
    demo-rock/
    demo-soil/

tests/
  test_download.py
  test_cache.py
  test_provenance.py
  test_failure_modes.py
```

运行时生成：

```text
sources.jsonl
run_manifest.json
confidence_report.json
```

## 六、接口交接

### 提供给 D2

- 原始报告值和单位；
- 样品、材料、介质、方法、实验室和空间位置字段；
- 来源可靠性、证据完整性和版本可验证性输入；
- `source_id`、原始文件定位和来源记录编号。

### 提供给 D3

- 稳定的 CLI 参数和退出码；
- 数据缓存、输出和 manifest 的路径约定；
- 三种运行模式的行为说明；
- 结构化错误和警告格式。

### 提供给 E1

- 确定性的 fixture；
- 下载和缓存测试入口；
- 失败注入样例；
- 预期错误码和降级结果。

## 七、MVP 验收清单

- [ ] 全新环境可以下载并解析至少一个真实数据源。
- [ ] GEOROC 和 USGS 均可完成下载、校验和解析流程。
- [ ] 第二次运行命中缓存且不重复下载。
- [ ] `cached` 模式完全不访问网络。
- [ ] `fixture` 模式可完全离线运行。
- [ ] 损坏文件、HTML 伪文件和 checksum 异常均会被拒绝。
- [ ] 数据源版本变化不会被静默接受。
- [ ] 每条输出记录均能追溯到原始文件和原始记录位置。
- [ ] 每个来源均有版本、许可、引用以及 DOI 或官方链接。
- [ ] Demo 数据可确定性地重新生成。
- [ ] 仓库未提交完整第三方数据集和本地下载缓存。
- [ ] 已通过 D2、D3 和 E1 联调。

## 八、风险与应对

| 风险 | 影响 | 应对措施 | 状态 |
|---|---|---|---|
| 来源下载地址或格式变化 | 下载或解析失败 | 版本锁定、内容类型检查、结构探测和显式报错 | 跟踪中 |
| 数据许可不允许再分发 | Demo 无法直接提交 | 仅提交脚本、manifest 和可合法分发的小型 fixture | 跟踪中 |
| 数据体积过大 | 仓库或评测包超限 | 完整数据仅缓存，小型切片随仓库提交 | 跟踪中 |
| 网络不稳定或评测环境断网 | 在线流程不可用 | cached/fixture 模式和完整离线测试 | 跟踪中 |
| D1、D2 字段边界不清 | 重复实现或科学语义冲突 | 阶段 0 冻结原始字段与标准化字段边界 | 跟踪中 |
| 上游版本静默更新 | 结果不可复现 | SHA-256、版本和元数据比对，不一致时停止 | 跟踪中 |

## 九、后续扩展

MVP 验收后，再按优先级处理：

1. EarthChem / PetDB 数据源适配；
2. GEMAS、AusGeochem 或 WoSIS 数据源适配；
3. Crossref、DataCite、OpenAlex 文献元数据发现；
4. 更多缓存镜像和来源切换策略；
5. 半结构化附件解析；
6. 全文 PDF 表格抽取与人工复核流程。

## 十、进展更新日志

每次有实质进展时，在本节顶部追加一条记录，时间精确到分钟，并在同一次 Git 提交中同步更新对应任务和里程碑状态。

### 2026-08-05 14:15 CST

- 扩展下载器：`.part` 临时文件、原子替换、严格 HTTP 重试范围、ETag/Last-Modified、版本绑定和在线缓存命中。
- 增加安全 ZIP 解压、成员数与展开体积上限、路径穿越/符号链接拒绝、必要成员和必要字段校验。
- 使用 USGS 官方 0–5 cm 文本完成真实在线下载，验证 1,450,062 bytes 和预期 SHA-256。
- 相同参数第二次运行命中缓存，`--offline` 运行也成功命中验证缓存。
- D1 组件测试扩展到 19 项并全部通过，新增下载与缓存测试记录。
- 当前下一步：实现 GEOROC 和 USGS 注册表驱动适配器及原始解析。

### 2026-08-05 14:11 CST

- 完成 `DataSourceAdapter`、`DatasetCandidate`、`DownloadedFile`、`RawRecord` 接口契约。
- 冻结不依赖本地路径和下载时间的 `source_record_id`、`record_id` 生成规则。
- 建立 GEOROC 12.0 与 USGS Data Series 801 的机器可读注册表，包含官方入口、许可、引用、必要字段和校验规则。
- 新增独立许可与引用说明；区分仓库 MIT、GEOROC CC BY-SA 4.0、USGS public domain 和 fixture CC0。
- D1 组件测试由 11 项扩展到 16 项并全部通过。
- 当前下一步：完成 M2 下载、缓存和安全解压增强。

### 2026-08-05 14:04 CST

- 将计划迁移到 `asimfish/global-geochemical-atlas-skill`，建立本地持续维护目录和 `d1/data-source-engineering` 分支。
- 识别并复用仓库已有的 D1/D2/D3 协作契约、D1 下载器、证据打包器和组件测试，避免重复搭建。
- 核验 GEOROC Archaean Cratons 当前正式版本为 12.0，发布时间为 2026-06-11，共 28 个 CSV、31,696,168 字节，许可为 CC BY-SA 4.0。
- 核验 USGS Data Series 801 的三个官方 TXT 下载文件及其当前 SHA-256。
- 当前下一步：完成稳定 ID/适配器契约，并建立两个真实数据源的注册表。

### 2026-08-05 13:50 CST

- 创建 D1 执行计划。
- 确定 7 个工作日的 MVP 节奏。
- 当前下一步：冻结 D1 与 D2、D3、E1 的接口约定。
