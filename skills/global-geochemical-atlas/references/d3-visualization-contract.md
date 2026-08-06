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
3. 复制 `assets/visualization-profile.template.json`，只修改与用户问题有关的字段。
4. 运行 `scripts/render_visualization.py`；不要直接编辑 HTML 模板。
5. 检查 `visualization_report.json.status`、`profile_warnings`、记录计数和文件大小。
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

配置使用 `d3-visualization-profile-v1`，完整约束见
[visualization-profile.schema.json](visualization-profile.schema.json)。关键字段：

```json
{
  "story": "overview",
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

按问题选择一个 `story`：

| 用户问题 | story | 推荐首屏 |
|---|---|---|
| 数据在哪里、有哪些介质 | `overview` | 分布点 + 密度，按介质着色 |
| 哪些区域有数据或覆盖空洞 | `coverage` | 样点密度，关闭异常层 |
| 哪里富集或亏损 | `anomaly` | 分布图 + 异常区域圆环 |
| 两个元素是否共测或协变 | `comparison` | 元素组合页，并设置 X/Y |
| 来源是否可靠 | `evidence` | 来源与置信度页 |

只把用户明确指定的元素、介质、地质单元等写入 `filters`。不要为了让地图“看起来有数据”而取消
无匹配筛选；保留该值，使页面显示覆盖缺口，并在 `profile_warnings` 中报告。自定义区域必须写明
WGS84 `W,S,E,N`；预设区域只是 bbox，不是假装精确行政裁切。

## 5. 单命令生成

从 Skill 目录执行：

```bash
python scripts/render_visualization.py \
  --input-dir D1_D2_OUTPUT \
  --profile TASK_PROFILE.json \
  --output-dir VISUALIZATION_OUTPUT
```

默认配置可直接用于全局总览：

```bash
python scripts/render_visualization.py \
  --input-dir D1_D2_OUTPUT \
  --output-dir VISUALIZATION_OUTPUT
```

脚本负责解析模板、嵌入数据、复制页面引用的证据文件并生成报告。已有生成文件时不静默覆盖；确需
替换时显式传 `--force`。

渲染后验证独立包：

```bash
python scripts/validate_visualization.py --output-dir VISUALIZATION_OUTPUT
```

`validate_outputs.py` 验证 `run_workflow.py` 的核心十文件目录；它要求 `run_summary.json`，不用于
独立 D3 目录。D3 验证器改为核对配置、报告、输入与输出哈希、地图计数、离线依赖和科学边界。

## 6. 输出与验收

核心 D3 输出：

- `interactive_map.html`：任务配置驱动、离线、自包含的交互地图；
- `samples.geojson`：一条 feature 对应一条合格坐标测定记录；
- `visualization_profile.json`：本次可复现任务配置；
- `visualization_report.json`：输入哈希、配置、警告、地图计数和失败边界，结构见
  [visualization-report.schema.json](visualization-report.schema.json)。

输出目录同时保留页面引用的标准数据库、来源、置信度和异常文件。HTML 不依赖 CDN、远程字体、
在线瓦片或浏览器扩展；HTML 或 GeoJSON 单文件超过 100 MB 的运行时安全上限时失败关闭。该上限约束生成产物，不替代官网对提交包及仓库内文件的更严格限制。

验收至少检查：

- 首屏是否直接对应用户问题，而不是要求用户先理解所有控件；
- 元素、区域、地质单元、介质、来源和置信度筛选是否真实生效；
- 分布、密度、元素组合和异常四类视图是否仍可切换；
- 空区域是否显示“覆盖缺口”而不是零含量或不存在；
- 点、异常区域和来源卡片是否能下钻到记录证据；
- `visualization_report.json` 是否为 `success`，警告是否被向用户说明。

## 7. 科学显示规则

默认全元素总览按 `source_id + sample_id + medium + coordinates` 折叠为物理采样符号；缺少
`sample_id` 时使用 `record_id`，不得只凭坐标去重。按元素着色时使用“采样身份 + 元素”。

只有当前筛选同时满足单一元素、单一介质、单一已知 measurement basis、单一已知方法组和单一
标准单位时，才允许使用浓度 `log10` 色阶；否则明确回退为分类色。密度图统计屏幕网格中的物理
采样点，并用圆形柔光显示；这不是核密度估计，也不是浓度插值。显示层的共同色阶不会合并
D2 按材料、土层或地质背景建立的异常背景组，也不能替代分层敏感性分析。

元素组合只接受同一来源与样品、同介质、同 basis、同方法组、各元素唯一单位、非删失正值。
存在多个可比层时只画样品对最多的一层并报告排除数；少于 8 对或秩方差为零时不报告 Spearman。

异常区域状态固定为 `visual_aggregation_only`。固定 1°/2°/5° 网格只聚合 D2 high/low 候选点；
全球视图可把相邻网格画成缩放自适应红蓝圆环，选中时再展示真实 bbox。圆环面积不表示真实范围，
异常候选也不等于污染、矿化或成因结论。

## 8. 失败状态

- `invalid_input`：目录、必需文件、配置字段或 JSON 无效；
- `unsupported_scope`：记录数或文件大小超过安全范围；
- `incomplete_retrieval`：输入计数或证据产物不完整；
- `needs_human_review`：CRS、许可、方法可比性或解释需专家判断。

失败时仍写 `visualization_report.json`，保留失败位置与下一步；不要生成看似完整但缺少证据的网页。
