# D3 可视化消费层契约

## 责任边界

D3 负责唯一生产 Skill、总工作流、地图、输出校验和 demo。D3 只消费 D1/D2 公共产物：

- 不修改 `geochemistry.csv` 的标准值、单位、qualifier、QC 或置信度；
- 不重算 `anomalies.geojson`、阈值、背景组或异常方向；
- 不替 D1 判断来源许可或把声明来源升级为已验证证据；
- 不把地图符号聚合写回记录级数据库或 GeoJSON。

## 输入

独立地图构建器的必需输入：

```text
geochemistry.csv
anomalies.geojson
```

推荐同时提供：

```text
qc_report.json
confidence_report.json
source_manifest.json
anomaly_report.json
```

`geochemistry.csv` 至少包含 `record_id`、元素、介质、标准值/单位、坐标、QC、置信度、
`source_id` 和 `source_locator`。坐标为空、非有限或超出 WGS84 范围的记录不进入地图，但保留在
数据库和 QC 统计中。输入超过 `--max-points` 时失败关闭，不抽样冒充完整结果。

## 输出

- `samples.geojson`：一条 feature 对应一条具有合格坐标的测定记录；
- `interactive_map.html`：内嵌样点、候选异常、报告上下文和固定底图的单文件应用；
- `run_summary.json.map_report`：记录地图版本、记录/样品/坐标失败计数、默认视图和底图来源。

HTML 不依赖 CDN、外部脚本、远程字体或在线瓦片。`samples.geojson` 保持记录级粒度；地图首页的
样品级去叠加只是显示行为。构建器在原子写出前计算 UTF-8 字节数；HTML 或 GeoJSON 任一超过
100 MB 时失败关闭，要求按范围或来源拆分。

## 默认视图与色阶门

首页选择全部元素、介质、地质单元、方法、来源和置信度。KPI 显示测定记录数，地图符号按：

```text
source_id + sample_id + medium + longitude + latitude
```

折叠。缺少 `sample_id` 时改用 `record_id`，不得仅凭坐标合并记录。

默认颜色表示介质。只有当前筛选同时为以下单一可比组时才显示浓度对数色阶：

1. 单一元素；
2. 单一介质；
3. 单一且已知的 measurement basis；
4. 单一且已知的方法组；
5. 单一且已知的标准单位。

色阶使用当前组 3%–97% 分位的稳健 `log10` 范围，仅用于描述性展示。异常判定仍完全来自 D2。

## 地图层与证据

- 观测点：普通定量值、删失值轮廓和样品级介质色；
- 光晕密度：按当前显示样品计数，不做核密度或空间插值；
- 异常点：直接叠加 D2 high/low candidate；
- 记录面板：展示原值、标准值、basis、方法、QC、置信度、来源定位和许可；
- 来源页：展示 D1 manifest 证据边界与来源统计；
- 异常页：展示 D2 方法版本、阈值、背景组和候选表；
- 质量页：展示 QC flags、坐标失败数和不可解释边界。

## 离线底图

`assets/natural-earth-110m-land.json` 是固定的 Natural Earth 1:110m 公有领域陆地轮廓。构建时
验证资产版本、许可、坐标范围和点数上限，再嵌入 HTML。底图只提供地理上下文，不参与地质匹配、
异常分析或覆盖推断。

## 复现

从 Skill 目录运行完整流程：

```bash
python scripts/run_workflow.py \
  --input fixtures/demo_input.csv \
  --output-dir demo_output
```

只消费已存在的 D2 产物：

```bash
python scripts/build_interactive_map.py \
  --database OUTPUT/geochemistry.csv \
  --anomalies OUTPUT/anomalies.geojson \
  --qc-report OUTPUT/qc_report.json \
  --confidence-report OUTPUT/confidence_report.json \
  --source-manifest OUTPUT/source_manifest.json \
  --anomaly-report OUTPUT/anomaly_report.json \
  --output-html OUTPUT/interactive_map.html \
  --output-geojson OUTPUT/samples.geojson
```

验收：

```bash
python scripts/component_test.py --component d3
python scripts/self_test.py
python scripts/validate_outputs.py --output-dir demo_output
```
