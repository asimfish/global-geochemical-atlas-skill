# 让 Agent 使用全球真实数据基准

这套基准用于比较候选 D2 实现，而不是让 Agent 复述规则。它会离线校验真实来源切片，运行
`D1 → 候选 D2 → D3`，并机器验收比赛要求的四项产品：

- 可交互元素分布地图；
- 标准化地球化学数据库；
- 数据来源与置信度说明；
- 异常区域识别结果。

## 最短用法

在仓库根目录执行团队当前扩展基线。它保留原核心基准，并追加中国、非洲、欧洲小国和日本：

```bash
python3 evaluation/d2-validation/scripts/run_global_data_suite.py \
  --expanded \
  --output-dir /tmp/d2-global-baseline
```

不加 `--expanded` 时仍运行稳定的 19,455 条核心回归；建议日常快速回归用核心模式，提交前和横向比较用扩展模式。

评测 Agent 新写或修改后的候选实现：

```bash
python3 evaluation/d2-validation/scripts/run_global_data_suite.py \
  --expanded \
  --output-dir /tmp/d2-global-agent-001 \
  --d2-script /absolute/path/to/candidate_d2.py \
  --candidate-label agent-001
```

等价的 Make 入口：

```bash
make d2-test-global-expanded \
  OUTPUT=/tmp/d2-global-agent-001 \
  D2_SCRIPT=/absolute/path/to/candidate_d2.py \
  CANDIDATE_LABEL=agent-001
```

每次必须使用不存在或为空的输出目录，防止覆盖先前证据。

候选脚本只需遵守公共 CLI 契约：

```text
python candidate_d2.py --input <D1 UTF-8 CSV> --output-dir <new directory>
```

成功时退出码为 `0`，stdout 只能有一行 JSON，并在输出目录生成：

```text
geochemistry.csv
samples.geojson
anomalies.geojson
qc_report.json
confidence_report.json
anomaly_report.json
map_spec.json
run_manifest.json
```

这是普通命令行与文件接口，OpenCode、Codex 和本地 CI 都可以调用，不依赖某个专有 Agent API。

## 可直接发给 OpenCode / Codex Agent 的任务

```text
你是 D2 候选实现的维护 Agent。先阅读 workstreams/d2/ 的接口、Schema、科学边界与现有实现。
禁止修改 evaluation/d2-validation/ 下的基准、冻结数据、契约和评分器；只修改候选 D2 代码。

候选脚本必须支持：
  python candidate_d2.py --input <csv> --output-dir <new-dir>
并输出 d2-interface-v2 规定的 8 个文件，成功 stdout 仅一行 JSON。

完成后运行：
  python3 evaluation/d2-validation/scripts/run_global_data_suite.py \
    --expanded \
    --output-dir /tmp/d2-global-agent-run \
    --d2-script <你的候选脚本绝对路径> \
    --candidate-label <本次候选名称>

以 global_data_report.json 中 counts.blocking.failed == 0 为硬门槛。
不要通过删除真实记录、填造方法/坐标元数据、把删失值当数值或弱化检查来获得通过。
最后报告状态、阻断失败数、评审发现数和四项产品路径。
```

若希望评测 Agent 在完全不读取团队 D2 实现的情况下从头实现，可把提示词中的
“阅读现有实现”改为“只阅读接口契约、Schema 和参考文档”，但仍需实现同一个 CLI，才能进行自动横向比较。

## 怎么判分

评分报告位于：

```text
<output-dir>/global_data_report.json
```

CI 硬门槛：

```bash
jq -e '.counts.blocking.failed == 0' \
  /tmp/d2-global-agent-001/global_data_report.json
```

状态含义：

- `pass`：阻断项和评审项全部通过；
- `pass_with_findings`：候选 D2 的阻断项通过，但公开来源本身仍有覆盖或元数据空洞；
- `fail`：接口、证据链、科学语义或产品验收至少一项阻断失败。

当前扩展基线预期是 `pass_with_findings`：44,536 条输入、15 个来源数据集、102 个显式来源国家/地区
标签、44,199 个成功标准化值、44,510 条可上图记录，阻断检查为 0。5 个评审发现来自真实来源边界，
例如 GEOROC 未逐条公开分析方法和坐标基准、开放 GEMStat 目标元素水质切片只覆盖四洲、7×4 洲—介质矩阵并不完整。
这些不能靠 Agent 编造字段“修复”。比较候选时优先看：

1. `counts.blocking.failed`，必须为 0；
2. `findings`，区分候选缺陷和来源固有限制；
3. `metrics`，检查记录数、标准化数、删失数、可上图数、候选异常和运行时间；
4. `checks`，查看每个失败的 expected / actual / note；
5. `candidate.sha256`，确认评分绑定到哪一版候选脚本。

## 四项产品在哪里

```text
<output-dir>/d3/atlas.html                  # 可交互、离线、自包含地图
<output-dir>/d2/geochemistry.csv            # 标准化地球化学数据库
<output-dir>/d3/source_confidence.json       # 来源、哈希、许可、置信度、七洲覆盖矩阵和盲区
<output-dir>/d3/anomaly_regions.geojson      # 异常区域筛查结果
<output-dir>/d3/anomaly_region_report.json   # 阈值、点—区域对账和解释边界
<output-dir>/d3/showcase_manifest.json       # 四项交付物 SHA-256
```

直接用浏览器打开 `atlas.html` 即可演示；不需要联网或启动 Web 服务。

地图首页默认选择“全部”元素、介质、来源和置信度，KPI 统计可上图的测定记录，地图则按
`来源 + 样品 ID + 介质 + 坐标` 去重为采样点，并按岩石、土壤、沉积物和水体分类着色。
这样既能看到全部全球覆盖，又不会让同一样品的多个元素重复叠点。只有筛选结果已经收敛到
单一元素、单一介质和单一标准单位时，地图才切换到浓度对数色阶；不同元素或介质的数值禁止
共用一个“高低浓度”色标。

## 基准数据与运行隔离

核心模式保存约 2.16 MB 的冻结切片；扩展模式再保存 7.67 MB 官方文件与证据。正常评测使用
`--offline` 校验哈希，不访问网络。
完整 GEMStat v3 ZIP 约 201 MB，GEOROC 父文件约 31 MB，只在维护者重新生成切片时下载到仓库外缓存：

```bash
python3 evaluation/d2-validation/scripts/build_global_fixtures.py \
  --refresh \
  --fixture-dir /tmp/new-global-fixture \
  --cache-dir /tmp/global-geochemical-parent-cache
```

`--refresh` 不会自动改写已发布契约。维护者必须独立检查来源版本、许可、选择规则、记录数和新哈希，
再决定是否升级基准版本；普通 Agent 评测禁止运行该模式。

扩展来源维护者可运行：

```bash
python3 evaluation/d2-validation/scripts/build_expanded_fixtures.py --offline
```

只有在人工审查许可、方法、字段和哈希时才使用 `--refresh`。来源清单与下一批接入路线见
`evaluation/d2-validation/DATA_SOURCE_CATALOG.md`。

## 防止 Agent “刷题”

正式横评时建议：

- 把 `evaluation/d2-validation/` 设为只读；
- 固定候选提交后再记录脚本 SHA-256；
- 只把 CLI 契约和 D1 输入路径交给被测 Agent，不告诉它点值 spot check；
- 评分器由独立进程运行，不让候选代码改写评分报告；
- 保留 stdout、stderr、`global_data_report.json` 和四项产品；
- 后续可使用相同 Schema 再放入未公开的第二批真实 holdout，检验是否过拟合当前切片。
