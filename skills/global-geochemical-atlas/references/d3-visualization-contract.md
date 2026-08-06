# D3 可视化生成契约

## 1. 目标与边界

D3 是 Agent 可重复执行的“可视化生成步骤”，不是一张固定网页。Agent 根据用户问题生成任务配置，
再用确定性脚本把任意合规 D1/D2 目录渲染为地图。`assets/interactive-atlas-v3.html` 只是内部资产模板；
不要要求用户或 Agent 手工修改 HTML、内嵌 JSON 或 Canvas 代码。

D3 只消费 D1/D2 结论：

- 不修改 `geochemistry.csv` 的标准值、单位、qualifier、QC 或置信度；
- 不重算 `anomalies.geojson` 的阈值、背景组或 high/low 方向；
- 不替 D1 判断许可，也不把声明来源升级为已验证来源；
- 不把显示聚合写回标准数据库或记录级 GeoJSON。

## 2. Agent 状态机

按顺序执行，不能跳过配置与验证：

1. 读取用户问题，提取主要元素、区域、介质、地质单元和目标视图。
2. 检查输入目录是否包含六个必需 D1/D2 文件；缺失时返回 `invalid_input`。
3. 把问题解析成 story、空间范围、筛选和可选元素组合；运行 `scripts/create_visualization_profile.py` 生成并验证任务配置，不手写完整 JSON。
4. 运行 `scripts/render_visualization.py`；不要直接编辑 HTML 模板或内嵌数据。
5. 检查 `visualization_report.json.status`、`profile_warnings`、记录计数、文件大小和 `iteration_backlog.csv`；删失观测必须是科学限制，不得伪装成修复失败。
6. 运行 `scripts/validate_visualization.py --output-dir VISUALIZATION_OUTPUT`；不要对独立 D3 包运行要求 `run_summary.json` 的核心流程验证器。
7. 打开生成的 HTML 做最小人工检查：首屏任务、空结果、图例、点击证据和来源链接。
8. 返回产物路径、已应用配置、覆盖提示和解释边界。

## 3. 输入目录

必需文件：

```text
geochemistry.csv
anomalies.geojson
qc_report.json
confidence_report.json
source_manifest.json
anomaly_report.json
```

若存在 `record_evidence.jsonl`，渲染包一并保留。`geochemistry.csv` 至少包含记录 ID、元素、介质、
标准值/单位、坐标、QC、置信度、来源 ID 和来源定位。坐标为空、非有限或超出 WGS84 的记录不进入
地图，但继续保留在数据库和 QC 报告。超过 `--max-points` 时失败关闭，不抽样冒充完整结果。

## 4. 任务配置模板

配置使用 `d3-visualization-profile-v2`，完整约束见
[visualization-profile.schema.json](visualization-profile.schema.json)。关键字段：

```json
{
  "story": "overview",
  "spatial_scope": "global",
  "default_region": "global",
  "custom_region": null,
  "filters": {
    "element": null,
    "medium": null,
    "sample_type": null,
    "basis": null,
    "geology": null,
    "method": null,
    "method_scope": null,
    "source": null,
    "confidence": null
  },
  "comparison": {"x": null, "y": null, "medium": null},
  "display": {
    "map_mode": "combined",
    "color_by": "medium",
    "anomaly_grid_degrees": 2,
    "show_anomaly_points": false,
    "show_anomaly_regions": true
  }
}
```

先选择空间产物类型；这不是普通筛选项：

| 调研范围 | `spatial_scope` | `default_region` | D3 输出行为 |
|---|---|---|---|
| 全球分布、跨洲总览 | `global` | 必须为 `global` | 生成世界图，嵌入全部可上图记录，可交互选择区域 |
| 国家、城市、流域、矿区 | `regional` | 非 `global` 预设或 `custom` | 生成区域图，只嵌入严格配置范围内记录并锁定区域入口 |

区域预设支持 `usa`、`usa48`、`china`、`shanghai`、`europe`、`australia`。其中 `usa`、`usa48`、
`china`、`australia` 使用固定 Natural Earth Admin‑0 国家多边形与 bbox 联合判定，避免国家 bbox
误纳邻国样点；`shanghai`、`europe` 仍是 bbox。其他范围使用
`default_region=custom`，并填写 WGS84 `custom_region.label` 与 `bounds={w,s,e,n}`。区域模式下：

- `interactive_map.html` 的样点、异常候选、来源卡片和元素组合只来自配置范围内记录；
- `samples.geojson` 只含配置范围内 feature，并声明 `spatial_scope.output_clipped=true`、`clip_method` 与可选 `country_code`；
- 页面不提供切回世界图的入口，URL 参数也不得突破区域范围；
- `geochemistry.csv`、`anomalies.geojson` 等原始 D1/D2 证据文件仍原样保留，避免破坏来源追溯；
- 国家多边形采用 Natural Earth de facto 制图口径，只作定位与严格点内筛选，不构成法定边界声明；bbox 不宣称为精确行政或地质边界。

按问题选择一个 `story`：

| 用户问题 | story | 推荐首屏 |
|---|---|---|
| 数据在哪里、有哪些介质 | `overview` | 分布点 + 密度，按介质着色 |
| 哪些区域有数据或覆盖空洞 | `coverage` | 样点密度，关闭异常层 |
| 哪里富集或亏损 | `anomaly` | 分布图 + 异常区域圆环 |
| 两个元素是否共测或协变 | `comparison` | 元素组合页，并设置 X/Y |
| 数据库有哪些字段或记录 | `database` | 标准化数据库页 |
| 来源是否可靠 | `evidence` | 来源与置信度页 |

只把用户明确指定的元素、介质、地质单元等写入 `filters`。不要为了让地图“看起来有数据”而取消
无匹配筛选；保留该值，使页面显示覆盖缺口，并在 `profile_warnings` 中报告。自定义区域必须写明
WGS84 `W,S,E,N`；国家预设与 bbox 预设必须在报告中明确 `clip_method`。

## 5. 单命令生成

从 Skill 目录先生成任务配置，再渲染：

```bash
python scripts/create_visualization_profile.py \
  --story STORY \
  --spatial-scope global \
  --output TASK_PROFILE.json

python scripts/render_visualization.py \
  --input-dir D1_D2_OUTPUT \
  --profile TASK_PROFILE.json \
  --output-dir VISUALIZATION_OUTPUT
```

任意国家、城市、流域、矿区或研究框使用自定义 WGS84 bbox：

```bash
python scripts/create_visualization_profile.py \
  --story coverage \
  --spatial-scope regional \
  --region custom \
  --bbox W S E N \
  --region-label "研究区域" \
  --element Cu \
  --medium sediment \
  --output TASK_PROFILE.json
```

脚本同时支持 `overview`、`coverage`、`anomaly`、`comparison`、`database` 和 `evidence` 六类问题，
以及元素、介质、细分样品类型、basis、地质单元、方法、方法范围、来源、置信度、元素组合和显示方式参数。运行
`python scripts/create_visualization_profile.py --help` 查看完整接口。仓库中的两个 JSON 模板只是默认资产与降级入口，不要求 Agent 复制修改。

脚本负责解析模板、嵌入数据、复制页面引用的证据文件并生成报告。已有生成文件时不静默覆盖；确需
替换时显式传 `--force`。

渲染后验证独立包：

```bash
python scripts/validate_visualization.py --output-dir VISUALIZATION_OUTPUT
```

`validate_outputs.py` 验证 `run_workflow.py` 的核心十一文件目录；它要求 `run_summary.json`，不用于
独立 D3 目录。D3 验证器改为核对配置、报告、输入与输出哈希、地图计数、离线依赖和科学边界。

## 6. 输出与验收

核心 D3 输出：

- `interactive_map.html`：任务配置驱动、离线、自包含的交互地图；
- `samples.geojson`：一条 feature 对应一条当前空间产物内的合格坐标测定记录；区域模式只含 bbox 内记录；
- `visualization_profile.json`：本次可复现任务配置；
- `visualization_report.json`：输入哈希、配置、警告、地图计数和失败边界，结构见
  [visualization-report.schema.json](visualization-report.schema.json)；
- `iteration_backlog.csv`：从完整 canonical 数据库派生的 D1/D2 修复、复核与科学限制清单，行结构见
  [iteration-backlog.schema.json](iteration-backlog.schema.json)。

输出目录同时保留页面引用的标准数据库、来源、置信度和异常文件。HTML 不依赖 CDN、远程字体、
在线瓦片或浏览器扩展；HTML 或 GeoJSON 单文件超过 100 MB 的运行时安全上限时失败关闭。该上限约束生成产物，不替代官网对提交包及仓库内文件的更严格限制。

页面首部必须提供一个始终可见的“产物与下载 · 4/4 可核查”一级产物坞；为减少首屏噪声可默认收起，但展开后四项比赛交付物必须同等显著，不能只藏在文件目录中：

- “标准化地球化学数据库”入口必须显示完整 `geochemistry.csv` 记录数、数据库行语义、下载按钮和可检索、排序、分页的记录预览；新增、修改、删除只生成审计修订包，删除为逻辑排除，不直接改写 canonical 数据；
- “数据来源与置信度说明”入口必须显示来源数、置信度版本、五个分量、权重、分量均值、等级分布、门控规则和“不是概率”边界；
- “异常区域识别结果”入口必须链接记录级候选与区域显示聚合，并保留判据；
- “可交互元素分布地图”入口必须链接任务配置驱动的地图及运行报告。

地图在全球和区域产物中都允许拖动/方向键平移与滚轮/按钮缩放，并提供“上一步视图”和明确的全球/区域重置。区域平移只改变观察窗口，不能加载范围外记录。用户可见术语统一为中文；内部 `measurement_basis` 通过确定性词表显示为“测量基准”，未知枚举可保留原值但不得与中文标签混排成无解释的控制项。

页面信息层级固定为 `task-first-progressive-disclosure-v2`：只保留一套动词式主标签导航；四项交付物使用
可展开产物坞，地图页顶部只显示四项决策指标，不再在页头重复文件胶囊或能力徽章；`story` 只决定初始标签和显示预设，不再生成第二个
“任务视图”选择器。地图首屏只平铺区域、元素、介质、地图表达四个高频控件，细分样品类型、地质单元、
颜色、bbox、basis、方法、方法范围、来源、置信度和异常网格放入“更多筛选”。不得为突出功能而把同一入口、
同一状态或同一组能力重复展示两次。该规则适用于任何新数据和区域报告，不是 demo 专用样式。

`visualization_report.json.map_report.visual_question_contract` 必须使用
`d3-visual-question-contract-v1`，并覆盖 map、database、combination、sources、anomalies、quality 六个视图。
每个视图都声明 `question`、`comparison_baseline`、`encoding` 和 `boundary`；页面标题与图形必须能回到这四项，
不能先选图再事后编造解释。

页面数据库预览只浏览 HTML 内嵌的可上图记录，完整数据库始终以原样保留的 `geochemistry.csv` 为准。
全球页面须分别报告完整记录、可上图记录和坐标失败记录；区域页面还须报告范围外未嵌入记录，不能让用户误以为
全球数据库被裁成了区域数据库。置信度等级和分量汇总来自完整 D2 `confidence_report.json`，不随地图筛选变化；
区域页面的来源卡片和记录预览则只统计当前空间产物。两种统计口径必须在页面中并列说明。

验收至少检查：

- 首屏是否直接对应用户问题，而不是要求用户先理解所有控件；
- 是否只有一套动词式主导航、一个可展开交付物产物坞、四项顶部指标，且首屏只平铺四个高频地图控件；
- 全球任务是否生成世界图，区域任务是否只生成并锁定区域图；
- 元素、区域、地质单元、介质、来源和置信度筛选是否真实生效；
- 分布、密度、元素组合和异常四类视图是否仍可切换；
- 四项交付物是否在首屏形成一级入口，数据库和置信度是否能在页面内直接核验，而不只是下载文件；
- 数据库完整记录、内嵌可上图记录、区域排除记录与坐标失败记录是否对账；
- 数据库工作台是否支持查、排序、分页、地图定位及增/改/逻辑删除提案，且导出修订包不改写 canonical CSV；
- 置信度五分量、权重、均值、等级分布、门控和“不是概率”边界是否清楚；
- 来源表能否按来源、数据集、元素、介质或许可检索，并下钻方法/坐标完整率、证据级别和来源定位；
- 异常页是否用候选值—背景中位数—稳健高低阈值对照尺显示倍数差、robust z 与完整背景条件；
- 元素组合结论是否写清区域、介质、测量基准、方法、单位、有效 n、四象限占比、排除数和“非因果”边界；
- 质量页是否可筛选、下载 `iteration_backlog.csv`，并区分 action/review/scientific-limit；
- 空区域是否显示“覆盖缺口”而不是零含量或不存在；
- 点、异常区域和来源卡片是否能下钻到记录证据；
- `visualization_report.json` 是否为 `success`，警告是否被向用户说明。

## 7. 科学显示规则

默认全元素总览按 `source_id + sample_id + medium + coordinates` 折叠为物理采样符号；缺少
`sample_id` 时使用 `record_id`，不得只凭坐标去重。按元素着色时使用“采样身份 + 元素”。

`medium` 是岩石、土壤、沉积物、水体等宽类介质；`sample_type` 是细分样品类型；`analytical_method` / `method_family` 是测定方法证据，三者不可互相推断。
D2 方法缺失必须原样显示并进入覆盖诊断。只有当前筛选同时满足单一元素、单一介质、单一已知 measurement basis、单一已知方法组和单一
标准单位时，才允许使用浓度 `log10` 色阶；否则明确回退为分类色。密度图统计屏幕网格中的物理
采样点，并用圆形柔光显示；这不是核密度估计，也不是浓度插值。热力模式仍保留可点击的半透明
样点锚点，确保任何视觉汇总都能下钻到记录证据。显示层的共同色阶不会合并
D2 按材料、土层或地质背景建立的异常背景组，也不能替代分层敏感性分析。

元素组合只接受同一来源与样品、同介质、同 basis、同方法组、各元素唯一单位、非删失正值。
存在多个可比层时只画样品对最多的一层并报告排除数；少于 8 对或秩方差为零时不报告 Spearman。
默认专业表达是 log10 样品配对散点 + 两轴样本中位数线 + Spearman ρ，以及独立的共测覆盖矩阵。
矩阵表示共同测量数量，不表示相关强度。Agent 可生成确定性结论，但必须带完整比较范围和非因果边界。
只有给出明确的归一化参照与元素序列时才生成 REE spider；只有满足闭合组成和删失处理条件时才生成 ternary/CLR 图。

异常区域状态固定为 `visual_aggregation_only`。固定 1°/2°/5° 网格只聚合 D2 high/low 候选点；
全球视图可把相邻网格画成缩放自适应红蓝圆环，选中时再展示真实 bbox。圆环面积不表示真实范围，
异常候选也不等于污染、矿化或成因结论。记录详情必须给出
`z = 0.67448975 × (log10(value) − median) / MAD`、阈值、背景组分层字段、组内样本量、中位数、
MAD 与相对中位数倍数，并明确不是与附近空间点平均值比较。

## 8. 迭代与修订边界

渲染器从完整 `geochemistry.csv` 确定性生成 `iteration_backlog.csv`，HTML 只内嵌有限预览以控制性能。
清单完整文件必须保留。D1 来源定位、许可、原始坐标/CRS、样品类型与方法证据缺口，D2 标准化、
方法 scope、地质匹配、QC 和低置信度问题分别路由；删失值使用 `scientific_limit`。最多两轮自动复查，
无改善或需推测时停止转人工。详细状态机见 [iteration-loop.md](iteration-loop.md)。

## 9. 失败状态

- `invalid_input`：目录、必需文件、配置字段或 JSON 无效；
- `unsupported_scope`：记录数或文件大小超过安全范围；
- `incomplete_retrieval`：输入计数或证据产物不完整；
- `needs_human_review`：CRS、许可、方法可比性或解释需专家判断。

失败时仍写 `visualization_report.json`，保留失败位置与下一步；不要生成看似完整但缺少证据的网页。
