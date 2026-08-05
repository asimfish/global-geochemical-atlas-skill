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
- `interactive_map.html`：内嵌压缩样点载荷、候选异常、报告上下文和固定底图的单文件应用；
- `run_summary.json.map_report`：记录地图版本、记录/样品/坐标失败计数、默认视图和底图来源。

HTML 不依赖 CDN、外部脚本、远程字体或在线瓦片。`samples.geojson` 保持记录级粒度；地图首页的
样品级去叠加只是显示行为。构建器在原子写出前计算 UTF-8 字节数；HTML 或 GeoJSON 任一超过
100 MB 时失败关闭，要求按范围或来源拆分。HTML 使用 `d3-compact-payload-v1` 字符串池与定长数组，
减少重复字段名；`samples.geojson` 仍是公开、记录级、标准 GeoJSON，不要求下游理解私有载荷。

## 默认视图与色阶门

首页选择全部元素、介质、地质单元、方法、来源和置信度。KPI 显示测定记录数，地图符号按：

```text
source_id + sample_id + medium + longitude + latitude
```

折叠。缺少 `sample_id` 时改用 `record_id`，不得仅凭坐标合并记录。

用户可明确选择“按介质”“按元素”或“按可比浓度”着色。全元素按元素着色时，显示粒度为
`采样身份 + 元素`；按介质或默认总览仍按物理采样身份折叠。只有用户选择浓度且当前筛选同时为
以下单一可比组时才显示浓度对数色阶：

1. 单一元素；
2. 单一介质；
3. 单一且已知的 measurement basis；
4. 单一且已知的方法组；
5. 单一且已知的标准单位。

色阶使用当前组 3%–97% 分位的稳健 `log10` 范围，仅用于描述性展示。异常判定仍完全来自 D2。

## 区域选择与覆盖缺口

内置全球、美国范围框、美国本土范围框、中国范围框、上海范围框、欧洲范围框和澳大利亚范围框，
并允许输入 `W,S,E,N` 自定义 bbox。预设是显式经纬度框，不伪装成精确行政区裁切。区域同时约束
测定、样点、热力图、元素组合和异常显示聚合；页面必须显示当前区域记录数。零记录时显示
“覆盖缺口”，不得解释为元素不存在、含量为零或没有异常。

## 地图层与证据

- 分布图：普通定量值、删失值轮廓，以及明确的介质色或元素色；
- 热力图：按当前区域的物理采样点在屏幕网格内计数，不做核密度或空间浓度插值；
- 组合模式：同时画分布点和样点密度，让密集区可见但不掩盖单点证据；
- 异常点：直接叠加 D2 high/low candidate；
- 候选区域：将当前筛选的 D2 候选点放入用户选择的 1°、2° 或 5° 固定经纬网格；按钮显示当前候选点/网格计数，网格支持悬停、点击详情和从区域表定位回地图；
- 记录面板：展示原值、标准值、basis、方法、QC、置信度、来源定位和许可；
- 来源页：展示 D1 manifest 证据边界与来源统计；
- 异常页：展示 D2 方法版本、阈值、背景组和候选表；
- 质量页：展示 QC flags、坐标失败数和不可解释边界。

拖动和缩放只重绘缓存的当前筛选，不重新扫描全部记录；异常方向通过 `record_id` 索引读取，
不得在逐点绘制中对全部异常做线性搜索。

## 元素组合

元素组合页提供 X/Y 元素配对散点和元素共测样品矩阵。散点只接受：

1. 同一 `source_id + sample_id`；
2. 同介质、同 measurement basis、同方法组；
3. X 与 Y 各恰好一条非删失正定量记录；
4. X、Y 各自单位在所选层内唯一。

存在多个可比层时只画样品对最多的一层，并报告未混合层数和被排除身份数。坐标轴使用 `log10`；
样品对不少于 8 且秩方差非零时才报告 Spearman ρ。矩阵只表示共测身份，不声称浓度可比、相关、
因果或地质成因。

## 富集与亏损候选区域

区域网格的科学状态固定为 `visual_aggregation_only`。D3 不重算 robust z、不合并背景组、不改变
high/low 方向，也不输出新的记录级异常。表格必须列出 bbox、方向、候选点数、元素、介质和最大
`|robust_z|`，并提示网格不是地质、矿体、污染或行政边界。

点击网格时列出当前筛选下落入该网格且方向一致的候选记录，至少展示 `record_id`、元素、介质、
标准值/单位、high/low、robust z 和来源；点击记录继续下钻到记录级证据。若当前区域或筛选为零候选，
按钮和表格必须显式显示 `0`，不得呈现为无响应。

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
