# 离线 demo 指南

## 目的

使用固定合成数据演示单位换算、删失值、坐标 QC、重复检测、运行级置信度、候选异常和交互地图。该数据不代表真实区域，不能用于科学结论。

## 运行

从 Skill 目录执行：

```bash
python scripts/run_workflow.py \
  --input fixtures/demo_input.csv \
  --output-dir demo_output
python scripts/validate_outputs.py --output-dir demo_output
python scripts/component_test.py --component all
```

单独演示 D3 时，不修改 HTML，也不手写整份配置。先把问题转成显式参数，再生成任务配置：

```bash
python scripts/create_visualization_profile.py \
  --story overview \
  --spatial-scope global \
  --output /tmp/task-profile.json

python scripts/render_visualization.py \
  --input-dir demo_output \
  --profile /tmp/task-profile.json \
  --output-dir visualization_output
python scripts/validate_visualization.py --output-dir visualization_output
```

国家、城市或任意研究框改用 `--spatial-scope regional --region PRESET`，或使用
`--region custom --bbox W S E N --region-label LABEL`；元素组合使用 `--story comparison --comparison-x X --comparison-y Y`。
打开 `visualization_output/interactive_map.html` 时应直接进入该任务视图。检查
`visualization_report.json`，不要隐藏 `profile_warnings`。全球配置生成世界图；区域配置会将 HTML、
异常显示和 `samples.geojson` 裁剪并锁定到预设或自定义范围。中国、美国和澳大利亚预设使用离线
国家多边形严格裁剪；上海、欧洲与自定义范围仍是 bbox。
这里不要把 `validate_outputs.py` 指向 `visualization_output`：该验证器面向含 `run_summary.json` 的
核心全流程目录；独立 D3 包由 `validate_visualization.py` 验证。

## 真实来源证据链 demo

仓库还包含两个合法的小型真实来源 fixture，均明确标记为 `not_for_scientific_interpretation`。推荐用 USGS demo 展示完整地图、方法、删失值和来源证据：

```bash
python scripts/run_workflow.py \
  --input fixtures/source-demos/usgs-conus-soil/demo_input.csv \
  --evidence-jsonl fixtures/source-demos/usgs-conus-soil/sources.jsonl \
  --acquisition-manifest fixtures/source-demos/usgs-conus-soil/run_manifest.json \
  --output-dir usgs_demo_output
python scripts/validate_outputs.py --output-dir usgs_demo_output
```

预期得到 108 条标准化记录、108 条有效 WGS‑84 坐标、3 条来源报告的 As `<0.6 mg/kg` 删失记录，以及 `verified_evidence_rate=1.0`。0–5 cm、A 与 C horizon 各自形成独立背景组；候选异常仍只是确定性切片的筛查结果，不能外推 CONUS 分布。

GEOROC fixture 的 datum 尚无足够证据，故 48 条记录保留 reported coordinates 而不进入地图；这是预期的失败关闭演示，不是坐标丢失 bug。

## 预期结果

- 输入 19 条测定；
- 识别 1 条土壤 As high candidate anomaly；
- 水体 `0.02 mg/L` 转为 `20 ug/L`；
- 水体 `1 ppm` 因缺少密度/basis 拒绝换算；
- `<0.10 mg/kg` 不插补，保留 censoring limit；
- 疑似经纬度交换只标记，不修正；
- 两条重复候选保留在数据库，但不进入异常背景；
- 生成自包含 `interactive_map.html`，断网可打开。
- 地图使用仓库内固定的 Natural Earth 1:110m 公有领域底图，不请求 CDN。

## 三分钟演示顺序

1. 展示用户问题和由 Agent 生成的 `visualization_profile.json`，说明 HTML 是内部模板而非参赛主体。
2. 运行一键命令并打开页面首部“比赛四项核心交付物”，核对“标准化地球化学数据库、数据来源与置信度说明、异常区域识别结果、可交互元素分布地图”四张一级入口卡片。
3. 打开“标准化数据库”，对账完整 CSV 记录数、页面内嵌可上图记录、物理采样点、范围外记录和坐标失败记录；搜索一条 record ID，对比原值、标准值、qualifier、QC 和来源。
4. 打开“置信度与来源说明”，展示五分量的定义、权重、均值、high/medium/low 分布、错误门控和“不是正确概率”边界，再下钻一个来源卡片。
5. 打开地图，首屏直接进入配置指定的问题视图；使用唯一主标签导航切换“可交互元素分布地图、标准化地球化学数据库、元素组合对比、数据来源与置信度说明、异常区域识别结果、质量控制与自动迭代”。
6. 分别演示全球模板、中国国家模板与上海区域模板：全球产物可切换范围；中国产物必须排除日本等 bbox 内邻国记录；上海产物只显示上海 bbox，若为 0 则展示“覆盖缺口，不是元素不存在”的失败可见化。区域数据库页仍须指向完整 CSV，并明确当前页面预览的裁剪口径。
7. 在“样点分布 / 采样密度 / 组合核查”之间切换，强调热力柔光只统计物理样点密度、不插值浓度，并点击半透明锚点查看记录。
8. 筛选 As/soil 并选择“按可比浓度”；只有 basis、方法组和单位收敛后才出现浓度对数色阶。
9. 点击候选点核对原值、标准值、样品类型、元素、方法缺失状态、QC、置信度和来源定位；展开 robust z 阈值、背景组样本量、中位数、MAD 和相对倍数，说明不是邻域平均。
10. 打开“元素组合”，展示最大可比层散点、Spearman 报告门和共测矩阵。
11. 在全球视图展示简洁的红蓝异常圆环，说明它会随缩放展开且圆环面积不代表地理范围；点击圆环后才显示真实 bbox，并展示方向、候选数量、最大 |z|、来源与记录下钻。再打开“异常结果”，用“地图定位”返回同一 2° 网格，并说明 `visual_aggregation_only`。
12. 切换“质量与边界”，展示证据等级、坐标空洞和解释边界，再展示水体 ppm、坐标交换与小样本组的失败关闭。

地图中的全元素总览按 `source_id + sample_id + medium + coordinates` 折叠为采样点，顶部 KPI
仍统计测定记录。没有 `sample_id` 的记录不会仅凭坐标合并。该差异用于避免一个样品的多个元素
在总览中重复增亮，不改变 `geochemistry.csv` 或 `samples.geojson` 的记录级内容。

## 真实来源四介质演示

需要展示赛题要求的岩石、土壤、沉积物和水体时，从 Skill 目录执行：

```bash
python scripts/build_four_media_demo.py \
  --output-dir /tmp/four-media-demo \
  --generated-at 2026-08-06T10:05:00Z

python scripts/run_workflow.py \
  --input /tmp/four-media-demo/demo_input.csv \
  --output-dir /tmp/four-media-output
```

预期为 796 条真实来源最小观测、四介质、十四来源、796/796 标准化、700/796 有效 canonical 坐标、23 条已确认删失值、93 个隔离背景组及完整十一文件输出（含 `iteration_backlog.csv`）。GEOROC 与 AfSIS 的 96 条 reported coordinates 因 datum/CRS 未证实而不冒充 WGS84；FOREGS 中可能的 `DL/2` 数值和 AfSIS 中低于来源 DL/QL 的已发布数值只带证据边界。演示时先展示覆盖空白和来源范围，再展示地图；16 个工程异常候选只用于说明筛查界面，不能作污染、矿化或区域元素丰亏结论。
