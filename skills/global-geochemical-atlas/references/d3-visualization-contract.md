# D3 可视化生成契约

## 1. 目标与边界

D3 是 Agent 可重复执行的“可视化生成步骤”，不是一张固定网页。Agent 根据用户问题生成任务配置，
再用确定性脚本把任意合规 D1/D2 目录渲染为地图。`assets/interactive-atlas-v3.html` 是
`d3-domain-confidence-atlas-v5` 的内部资产；Agent 只填写数据和 profile 参数，不得手工修改 HTML、内嵌 JSON
或 Canvas 代码，也不得在官方渲染成功时另写替代页面。

D3 只消费 D1/D2 结论：

- 不修改 `geochemistry.csv` 的标准值、单位、qualifier、QC 或置信度；
- 不重算 `anomalies.geojson` 的阈值、背景组或 high/low 方向；
- 不重算 `anomaly_regions.geojson` 的精确检验、FDR 或区域状态；
- 不替 D1 判断许可，也不把声明来源升级为已验证来源；
- 不把显示聚合写回标准数据库或记录级 GeoJSON。

页面遵守 `competition-geochemistry-v1` 术语契约。一级导航固定使用“可交互元素分布地图、
标准化地球化学数据库、元素组合对比、数据来源与置信度说明、异常区域识别结果、质量控制与数据复核”。
不得把这些专业名称缩写成“看分布、查记录、比元素”等口语标签。按钮、提示和解释文字可以使用通俗语言，
但不能改变赛题能力与交付物的正式名称。

## 2. Agent 状态机

按顺序执行，不能跳过配置与验证：

1. 读取用户问题，提取主要元素、区域、介质、地质单元和目标视图。
2. 检查输入目录是否包含七个必需 D1/D2 文件（含 `sources_and_confidence.json`）；缺失时返回 `invalid_input`。
3. 把问题解析成 story、空间范围、筛选和可选元素组合；运行 `scripts/create_visualization_profile.py` 生成并验证任务配置，不手写完整 JSON。
4. 运行 `scripts/render_visualization.py`；不要直接编辑 HTML 模板或内嵌数据。
5. 检查 `visualization_report.json.status`、`template_contract_version`、`template_sha256`、`template_variant`、`profile_warnings`、记录计数、文件大小和 `iteration_backlog.csv`；删失观测必须是科学限制，不得伪装成修复失败。
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

若存在 `record_evidence.jsonl`，渲染包一并保留。全球产物选择 `global_globe`，区域产物选择
`regional_focus`；两者共用同一模板契约而不是两份漂移的 HTML。`geochemistry.csv` 至少包含记录 ID、元素、介质、
标准值/单位、坐标、QC、置信度、来源 ID 和来源定位。坐标为空、非有限或超出 WGS84 的记录不进入
地图，但继续保留在数据库和 QC 报告。`--max-points` 是 canonical 输入安全上限（默认 200,000）；`--max-embedded-records` 只是浏览器载荷的绝对上界（默认 200,000），实际内嵌量由 96 MB 字节预算自适应决定：构建先尝试内嵌全部可绘记录，仅当 HTML 或 GeoJSON 序列化体积超预算时才按比例确定性收缩覆盖保持预览并重建。二者不得混用：前者约束完整科研数据库，后者只约束 HTML/GeoJSON 的确定性覆盖保持预览，防止单文件超过 100 MB 后让已采集的近 20 万条数据整轮回滚。预览必须写抽取证明（含 `byte_budget_bytes` 与最终 `maximum_embedded_records`），不能冒充完整结果；筛选、来源链、聚合统计和 CSV 对账仍以 canonical 全集为准。

核心十八产物目录还包含 `sources_and_confidence.json`、`batch_acceptance.csv`、`batch_qc_report.json`、`anomaly_regions.geojson`、
`spatial_anomaly_report.json`、`anomaly_provenance.json` 与 `temporal_map.html`。D3 在它们存在时必须原样嵌入/复制并展示；独立兼容模式要求上方七个最小输入，缺少统计区域时只能显示记录级候选和显示聚合，不能补造 FDR 结果。

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
    "color_by": "value",
    "anomaly_grid_degrees": 2,
    "show_anomaly_points": false,
    "show_anomaly_regions": true
  }
}
```

先选择空间产物类型；这不是普通筛选项：

| 调研范围 | `spatial_scope` | `default_region` | D3 输出行为 |
|---|---|---|---|
| 全球分布、跨洲总览 | `global` | 必须为 `global` | `global_globe`：二维世界地图 + 三维地球仪；小数据嵌入全部可上图记录，大数据嵌入可审计的覆盖保持预览 |
| 国家、城市、流域、矿区 | `regional` | 非 `global` 预设或 `custom` | `regional_focus`：只嵌入严格范围内记录，锁定区域入口且不显示地球仪 |

区域参数接受 `usa48`、`shanghai`、`europe` 三个研究预设，以及随 Skill 冻结的 Natural Earth
Admin‑0 国家名称、常用中英文别名或 ISO-3。国家范围使用固定多边形与最小圆周 bbox 联合判定，
避免普通 bbox 误纳邻国样点，并正确支持 Fiji 等跨日期变更线国家；研究预设仍按其冻结边界执行。
全球二维地图使用 `single-world-no-repeat-v1` 导航策略：初始范围和缩放上限均不超过 360°，横向拖动与键盘平移在
`[-180°, 180°]` 停止，不在画布旁复制第二个世界。需要连续跨日期变更线旋转时切换三维地球仪；区域产物使用
`regional-bounded-antimeridian-v1` 策略，仍按冻结区域范围约束并保留 `w > e` 的跨日期变更线语义。
非国家研究范围使用 `default_region=custom`，并填写 WGS84 `custom_region.label` 与
`bounds={w,s,e,n}`；`w>e` 表示跨日期变更线。区域模式下：

- `interactive_map.html` 的样点、异常候选、来源卡片和元素组合只来自配置范围内记录；
- `samples.geojson` 只含配置范围内 feature，并声明 `spatial_scope.output_clipped=true`、`clip_method`、可选 `country_code` 与 `highlight_country_codes`；
- 页面不提供切回世界图的入口，URL 参数也不得突破区域范围；导航锁定在冻结区域的取景框内：缩放上限等于取景框跨度（不能缩到比整个区域更远），平移时视口不得越过取景框 ±3%，区域内可继续放大；
- 滚轮缩放是可选行为：只有点击过地图（激活）或按住 Ctrl/⌘ 时滚轮才缩放画布，否则滚轮照常滚动页面并短暂提示；指针离开或 Esc 取消激活。二维画布、地球仪与内嵌时序画布同一策略。内嵌时序文档向父页上报内容高度（`gga-temporal-height` 消息），父页据此自适应 iframe 高度，整页只有一个滚动条；
- **制图强调与裁剪分离**：`custom_region.highlight_country_codes`（1–6 个 ISO-3，须存在于冻结 Admin-0 资产，否则构建失败关闭）只决定哪些国家轮廓被画成研究框（淡金填充 + 金色描边 + 光晕，主图与时序图同一语义），**不裁剪任何记录**；`country_code` 才触发严格多边形裁剪。命名国家请求由 `run_atlas_request` 自动写入 `highlight_country_codes = analysis_country_codes`（中国为 `["CHN","TWN"]`），因此带邻海分析域的国家图谱既保留海洋记录又画出国界；国家预设按 `analysis_country_codes` 或 `country_code` 自动推导，无国家的 bbox 区域不画研究框。区域模式下邻国 Admin-0 与中国 Admin-1 参考线同时加粗，便于定位。
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

逐记录详情必须把“空间匹配地质单元”与“发布方地质 / 沉积背景”分开。后者可来自发布方直报的岩性、土层、沉积环境、水体类型、构造背景或调查区描述；它用于说明背景证据并避免把“未完成 polygon join”误写成“没有任何背景”，但不得升级为正式地质单元或空间匹配成功。区域字段完整度同时显示地质 / 环境背景覆盖率，正式单元覆盖率仍可单独审计。

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

冻结注册表中的国家直接传名称/别名/ISO-3；城市、流域、矿区或其他研究框使用自定义 WGS84 bbox：

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

`validate_outputs.py` 验证 `run_workflow.py` 的核心十八文件目录；它要求 `run_summary.json`，不用于
独立 D3 目录。D3 验证器改为核对配置、报告、输入与输出哈希、地图计数、离线依赖和科学边界。

## 6. 输出与验收

核心 D3 输出：

- `interactive_map.html`：任务配置驱动、离线、自包含的唯一主交互体验；主导航必须含
  `temporalView` 和 `autoResearchView`。完整时序文档以 base64 bytes 嵌入并经 sandboxed
  `srcdoc` 懒加载，禁止链接/iframe `src` 依赖 `temporal_map.html`；Auto-Research 在静态
  模式只导出 typed request，在 loopback controller 模式才可创建真实运行；
- `samples.geojson`：一条 feature 对应一条当前空间产物内的合格坐标测定记录；区域模式先严格按 bbox/国家多边形裁剪。可上图记录不超过 `--max-embedded-records` 时全量嵌入；超过时使用 `d3-coverage-preserving-preview-v1` 确定性选择，保留全部异常记录、任何入选物理样品的全部元素测定，并优先覆盖来源 × 介质 × 元素 × 5°空间格，再以稳定 hash 补足。feature properties 采用 `d3-map-sample-properties-v3` 最小空间交换字段，并以 `record_id` 无损连接完整 `geochemistry.csv`。GeoJSON 和报告必须写 input/output 记录数、物理样品数、阈值、分层粒度与声明边界；这是一种浏览器性能预览，不是完整库、随机样本或统计代表性样本；
- `visualization_profile.json`：本次可复现任务配置；
- `visualization_report.json`：输入哈希、配置、警告、地图计数和失败边界，结构见
  [visualization-report.schema.json](visualization-report.schema.json)；
- `iteration_backlog.csv`：从完整 canonical 数据库派生的 D1/D2 修复、复核与科学限制清单，行结构见
  [iteration-backlog.schema.json](iteration-backlog.schema.json)。

profile 触发的结构化研究产物：

- `story=comparison` 时生成 `element_comparison.json`，只配对同一来源、稳定物理样品和完整可比层，报告输入数、排除原因、log10 配对、tie-corrected Spearman、四象限和非因果边界，结构见 [element-comparison.schema.json](element-comparison.schema.json)；
- `filters.element` 非空时生成 `concentration_grid.geojson`，按固定 1°/2°/5° WGS84 观测格网和显式可比层报告样品数、删失比例、可定量中位数与 IQR，不做空间插值，结构见 [concentration-grid.schema.json](concentration-grid.schema.json)。

两项均由 `visualization_report.json.outputs` 与 `output_sha256` 绑定；不满足触发条件时不得残留上一次 `--force` 运行的旧文件。

输出目录同时保留页面引用的标准数据库、来源、置信度和异常文件。HTML 不依赖 CDN、远程字体、
在线瓦片或浏览器扩展；HTML 或 GeoJSON 单文件超过 100 MB 的运行时安全上限时失败关闭。该上限约束生成产物，不替代官网对提交包及仓库内文件的更严格限制。

页面首部必须提供一个始终可见的“产物与下载 · 4/4 可核查”一级产物坞；为减少首屏噪声可默认收起，但展开后四项比赛交付物必须同等显著，不能只藏在文件目录中：

- “标准化地球化学数据库”入口必须显示完整 `geochemistry.csv` 记录数、数据库行语义、下载按钮和可检索、排序、分页的记录预览；新增、修改、删除只生成审计修订包，删除为逻辑排除，不直接改写 canonical 数据；
- 数据库页面必须显示单元素最大可比层的 log10 含量直方图与 P10/中位数/P90、元素×介质覆盖矩阵和标准值/坐标/方法/地质/来源/QC 完整率；
- “数据来源与置信度说明”入口必须显示来源数、置信度版本、五个分量、权重、分量均值、等级分布、门控规则和“不是概率”边界；
- “异常区域识别结果”入口必须分别链接记录级候选、D2 FDR 统计候选区域与 D3 显示聚合，并保留各自判据；
- 异常页面必须显示 high/low 数量、候选空间密度图、统计区域和带表头的记录表；候选密度图只显示已观测候选聚集，不得称为浓度插值或异常真实边界；
- “可交互元素分布地图”入口必须链接任务配置驱动的地图及运行报告。

地图在全球和区域产物中都允许拖动/方向键平移与滚轮/按钮缩放，并提供“上一步视图”和明确的全球/区域重置。区域平移只改变观察窗口，不能加载范围外记录。用户可见术语统一为中文；内部 `measurement_basis` 通过确定性词表显示为“测量基准”，未知枚举可保留原值但不得与中文标签混排成无解释的控制项。

页面信息层级固定为 `atlas-progressive-disclosure-v2`：只保留一套动词式主标签导航；四项交付物使用
可展开产物坞，地图页顶部只显示四项决策指标，不再在页头重复文件胶囊或能力徽章；`story` 只决定初始标签和显示预设，不再生成第二个
“任务视图”选择器。区域地图首屏平铺区域、元素、介质、地图表达四个高频控件；全球产物增加二维/三维视图控件。细分样品类型、地质单元、
颜色、bbox、basis、方法、方法范围、来源、置信度和异常网格放入“更多筛选”。不得为突出功能而把同一入口、
同一状态或同一组能力重复展示两次。该规则适用于任何新数据和区域报告，不是 demo 专用样式。

元素组合页单独显示“对比区域”和自定义 WGS84 `W,S,E,N`，并与地图区域双向同步。全球产物可选择全球、
命名区域或自定义 bbox；区域产物的选择器只显示并锁定生成时裁剪范围，不能借组合页读取范围外记录。
样品配对散点、四象限、Spearman ρ、共测矩阵和 Agent 结论必须共同调用同一 `rowInRegion` 空间判定。
网页内的范围、元素与介质选择属于探索状态。正式报告、引用或 Agent 交接必须从页面导出合法的
`d3-visualization-profile-v2`，再交给 `scripts/render_visualization.py` 生成独立区域产物并运行
`scripts/validate_visualization.py`。`visualization_report.json` 必须同时绑定 D1/D2 输入哈希、profile 输入哈希和
输出哈希；没有 profile 重渲染记录的瞬时浏览器状态不能作为最终元素组合结论。

`visualization_report.json.map_report.visual_question_contract` 必须使用
`d3-visual-question-contract-v1`，并覆盖 map、database、combination、sources、anomalies、quality 六个视图。
每个视图都声明 `question`、`comparison_baseline`、`encoding` 和 `boundary`；页面标题与图形必须能回到这四项，
不能先选图再事后编造解释。

页面数据库预览只浏览 HTML/GeoJSON 内嵌的可上图记录，完整数据库始终以原样保留的 `geochemistry.csv` 为准。
全球页面须分别报告完整记录、全库可上图记录、实际内嵌预览记录和坐标失败记录；区域页面还须报告范围外未嵌入记录，不能让用户误以为
全球数据库被裁成了区域数据库。置信度等级和分量汇总来自完整 D2 `confidence_report.json`，不随地图筛选变化；
区域页面的来源卡片和记录预览则只统计当前空间产物。两种统计口径必须在页面中并列说明。

验收至少检查：

- 首屏是否直接对应用户问题，而不是要求用户先理解所有控件；
- 是否只有一套赛题专业术语主导航、一个可展开交付物产物坞、四项顶部指标，且首屏只平铺高频地图控件；
- 全球任务是否生成世界图，区域任务是否只生成并锁定区域图；
- 全球产物能否在二维地图与三维地球仪间切换、旋转、缩放和点击样点；区域产物是否隐藏地球仪；
- 元素、区域、地质单元、介质、来源和置信度筛选是否真实生效；
- 分布、密度、元素组合和异常四类视图是否仍可切换；
- 四项交付物是否在首屏形成一级入口，数据库和置信度是否能在页面内直接核验，而不只是下载文件；
- 数据库完整记录、全库可上图记录、覆盖保持预览记录、区域排除记录与坐标失败记录是否对账；抽样证明是否保留全部异常候选和入选物理样品的元素组合；
- 数据库含量直方图、元素×介质矩阵和字段完整率是否由当前输入生成并随检索更新；
- 数据库工作台是否支持查、排序、分页、地图定位及增/改/逻辑删除提案，且导出修订包不改写 canonical CSV；
- 置信度五分量、权重、均值、等级分布、门控和“不是概率”边界是否清楚；
- 来源表能否按来源、数据集、元素、介质或许可检索，并下钻方法/坐标完整率、证据级别和来源定位；
- 异常页是否用候选值—背景中位数—稳健高低阈值对照尺显示倍数差、robust z 与完整背景条件；
- 异常候选密度图是否区分富集/亏损，且没有把显示密度写成未采样区浓度预测；
- 元素组合结论是否写清区域、介质、测量基准、方法、单位、有效 n、四象限占比、排除数和“非因果”边界；
- 元素组合页是否能直接选择命名区域或自定义 bbox，是否与地图同步，区域产物是否仍锁定裁剪范围；
- 元素组合探索状态是否能导出合法 profile，并由同一 D1/D2 输入重渲染为哈希绑定的正式区域产物；
- 质量页是否使用中文问题名称、保留内部 QC code 作为次级标识，并可筛选、下载 `iteration_backlog.csv`，区分 action/review/scientific-limit；
- 空区域是否显示“覆盖缺口”而不是零含量或不存在；
- 点、异常区域和来源卡片是否能下钻到记录证据；
- `visualization_report.json` 是否为 `success`，模板契约、模板 SHA-256 和空间变体是否与 Skill 资产一致，警告是否被向用户说明。

## 7. 科学显示规则

默认全元素总览按“采样身份 + 元素”显示分类色，避免把不同元素的含量放入同一色阶；缺少
`sample_id` 时使用 `record_id`，不得只凭坐标去重。密度统计仍按物理采样身份去重。

`medium` 是岩石、土壤、沉积物、水体等宽类介质；`sample_type` 是细分样品类型；`analytical_method` / `method_family` 是测定方法证据，三者不可互相推断。
D2 方法缺失必须原样显示并进入覆盖诊断。选择单一元素时，D3 自动选取记录数最多的“介质 + measurement basis + 已知方法组 + 标准单位”可比层使用浓度 `log10` 色阶；同元素的其他层显示为灰色，不混入色阶。未选择单一元素或可比层不足两条时回退为元素/介质分类色。密度图统计屏幕网格中的物理
采样点，并用圆形柔光显示；这不是核密度估计，也不是浓度插值。热力模式仍保留可点击的半透明
样点锚点，确保任何视觉汇总都能下钻到记录证据。显示层的共同色阶不会合并
D2 按材料、土层或地质背景建立的异常背景组，也不能替代分层敏感性分析。

元素组合先按组合页声明的空间范围过滤，再只接受同一来源与样品、同介质、同 basis、同方法组、各元素唯一单位、非删失正值。
存在多个可比层时只画样品对最多的一层并报告排除数；少于 8 对或秩方差为零时不报告 Spearman。
默认专业表达是 log10 样品配对散点 + 两轴样本中位数线 + Spearman ρ，以及独立的共测覆盖矩阵。
矩阵表示共同测量数量，不表示相关强度。Agent 可生成确定性结论，但必须带完整比较范围和非因果边界。
只有给出明确的归一化参照与元素序列时才生成 REE spider；只有满足闭合组成和删失处理条件时才生成 ternary/CLR 图。

异常区域有两套不得混用的语义。`anomaly_regions.geojson` 来自 D2
`d2-spatial-hypergeometric-fdr-v1`：它在同一可比组内做一侧精确富集检验并控制 BH-FDR，D3 只能按虚线 Polygon 原样显示。交互页面另有固定 1°/2°/5° 网格圆环和 high/low 候选空间密度图，仅聚合 D2 已判定记录，不带 p/q 值，也不预测未采样区浓度。全球视图可把圆环画成缩放自适应红蓝符号，选中时再展示网格 bbox。两类边界都不表示真实异常范围、地质/行政边界、污染、矿化或成因结论。记录详情必须给出
`z = 0.67448975 × (log10(value) − median) / MAD`、阈值、背景组分层字段、组内样本量、中位数、
MAD 与相对中位数倍数，并明确不是与附近空间点平均值比较。

## 8. 迭代与修订边界

渲染器从完整 `geochemistry.csv` 确定性生成 `iteration_backlog.csv`，HTML 只内嵌有限预览以控制性能。
清单完整文件必须保留。D1 来源定位、许可、原始坐标/CRS、样品类型与方法证据缺口，D2 标准化、
方法 scope、地质匹配、QC 和低置信度问题分别路由；删失值使用 `scientific_limit`。最多两轮自动复查，
无改善或需推测时停止转人工。详细状态机由 Skill 直接路由到 `iteration-loop.md`。

## 9. 失败状态

- `invalid_input`：目录、必需文件、配置字段或 JSON 无效；
- `unsupported_scope`：记录数或文件大小超过安全范围；
- `incomplete_retrieval`：输入计数或证据产物不完整；
- `needs_human_review`：CRS、许可、方法可比性或解释需专家判断。

失败时仍写 `visualization_report.json`，保留失败位置与下一步；不要生成看似完整但缺少证据的网页。
