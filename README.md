# Global Geochemical Atlas Skill

一个证据优先、覆盖度可解释、可离线降级的全球地球化学元素分布图谱 Agent Skill。它指导智能体从公开科学来源采集岩石、土壤、沉积物和水体元素测定，保守统一单位，执行坐标与方法质量控制，识别候选富集/亏损，并生成标准化数据库、来源与置信度报告、GeoJSON 和自包含交互地图。

本仓库只包含一个正式 Skill：`skills/global-geochemical-atlas/`。正文采用 Agent Skills、OpenCode 与 Codex 可共同读取的最小公共格式。

## 30 秒离线复现

要求：Python 3.11+；不需要第三方依赖、网络、密钥或 GPU。

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input skills/global-geochemical-atlas/fixtures/demo_input.csv \
  --output-dir demo_output
```

生成：

- `geochemistry.csv`：标准化地球化学数据库；
- `source_manifest.json`：记录级来源、许可、输入哈希及置信度报告哈希绑定；
- `record_evidence.jsonl`：与数据库记录一一对应的来源文件、源行、版本、哈希和引用；
- `qc_report.json` 与 `confidence_report.json`：QC 和运行级置信度；
- `anomalies.geojson` 与 `anomaly_report.json`：候选异常及背景组统计；
- `samples.geojson`：地图样点图层；
- `interactive_map.html`：无 CDN 的自包含交互图谱，含区域 bbox、分布图、样点密度热力图、介质/元素/可比浓度着色、元素组合与富集/亏损候选区域；
- `run_summary.json`：稳定输出清单、状态和限制。

地图首页默认展示全部可上图测定，并按 `source_id + sample_id + medium + coordinates`
折叠为样品级符号；没有 `sample_id` 的记录不做推测性去重。颜色默认表示介质，只有筛选结果
收敛到同一元素、介质、measurement basis、方法组和标准单位时才启用浓度对数色阶。
页面同时提供来源与置信度、候选异常、QC 与覆盖边界页签，全部直接消费 D1/D2 公共产物，
不在可视化层重算标准值、置信度或异常。

然后运行自检：

```bash
python skills/global-geochemical-atlas/scripts/self_test.py
```

## 使用自己的 CSV

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /path/to/measurements.csv \
  --output-dir output \
  --region-bbox 73,18,135,54 \
  --max-records 50000
```

`standardize_geochemistry.py` 的最低分析列为 `element_or_analyte,value,unit,medium`；要运行并交付完整 `run_workflow.py`，还必须提供非空 `source_id,source_locator,license`，否则证据打包会失败关闭。正式科学运行还应提供 `source_tier`、样品 ID、measurement basis、经纬度、CRS、分析方法、消解/提取方法、检出限和文件哈希。完整契约见 `skills/global-geochemical-atlas/references/`；D3 消费层详见 [可视化契约](skills/global-geochemical-atlas/references/d3-visualization-contract.md)。

## 科学边界

- 保留原值、原单位、qualifier 和原始坐标表达；无法证明的转换失败关闭。
- 固体质量比可统一为 `mg/kg`；水体质量/体积统一为 `ug/L`，但不把水体 `ppm` 猜成质量/体积。
- `<LOD`、`BDL`、`ND` 不替换为 0 或 LOD/2。
- 不静默交换经纬度，不把未知 CRS 冒充 WGS84。
- 异常是相对已声明背景组的筛查候选，不等于污染、矿床或成因结论。
- demo 是 CC0 合成验收数据，只用于工程复现，不支持真实区域科学结论。
- 真实来源 fixture 也只用于流水线演示；其 `run_manifest.json` 会把该限制传到最终结果。

## 仓库结构

```text
skills/
└── global-geochemical-atlas/
    ├── SKILL.md
    ├── assets/natural-earth-110m-land.json
    ├── fixtures/demo_input.csv
    ├── references/
    └── scripts/
```

没有 `requirements.txt`：运行脚本只使用 Python 标准库。完整数据不进入仓库；可使用受控下载脚本获取公开文件，并保存 URL、时间、许可和 SHA-256。

## 三人协作

仓库仍然只有一个生产 Skill，但内部按稳定接口拆为三个责任域：

- D1 维护下载、缓存、demo 数据和证据打包，负责 **数据来源与置信度说明**；
- D2 维护标准化、QC、置信度算法和异常分析，负责 **标准化地球化学数据库** 与 **异常区域识别结果**；
- D3 维护唯一 `SKILL.md`、总工作流、地图和 demo，负责 **可交互元素分布地图** 与 **可复用 Skill 文档**。

各角色可独立运行最小契约测试：

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component d1
python skills/global-geochemical-atlas/scripts/component_test.py --component d2
python skills/global-geochemical-atlas/scripts/component_test.py --component d3
```

合并前运行 `--component all` 和 `self_test.py`。完整路径归属、接口冻结规则、分支约定和完成定义见仓库根目录 `CONTRIBUTING.md`；该文件服务开发协作，不属于运行时 Skill。

## Skill 加载

- OpenCode：把 `skills/global-geochemical-atlas/` 暴露到其 Skill 搜索路径。
- Codex：在临时验证工作区把同一目录映射到 `.agents/skills/global-geochemical-atlas/`。

不要在仓库中维护多个副本，也不要提交 provider 配置、API key、缓存、评测 gold 或演示视频。

## 许可与数据

代码和原创文档采用 MIT License。每个外部数据集仍服从其自身许可和署名要求；下载或再分发前检查 `source_manifest.json`。Macrostrat 和 GEMStat 等聚合平台还可能要求同时引用原始数据提供者。
