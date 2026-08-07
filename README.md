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
- `source_manifest.json`：记录级来源、许可、输入文件身份、字节数、记录数及置信度报告关联；
- `qc_report.json` 与 `confidence_report.json`：QC 和运行级置信度；
- `anomalies.geojson` 与 `anomaly_report.json`：候选异常及背景组统计；
- `samples.geojson`：地图样点图层；
- `interactive_map.html`：无 CDN 的自包含交互地图；
- `run_summary.json`：稳定输出清单、状态和限制。

然后运行自检：

```bash
python skills/global-geochemical-atlas/scripts/self_test.py
```

## 真实来源四介质离线复现

仓库提供 21 个已接入真实来源的最小切片，覆盖岩石、土壤、沉积物和水体。它们可合成一个 1,084 条观测的四介质输入，并生成统一地图包：

```bash
python skills/global-geochemical-atlas/scripts/build_four_media_demo.py \
  --output-dir /tmp/four-media-demo \
  --generated-at 2026-08-05T15:20:00Z

python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /tmp/four-media-demo/demo_input.csv \
  --output-dir /tmp/four-media-output
```

这套 fixture 用于证明真实数据的接口、证据链和比较隔离可以共同运行，不代表全球空间完整。海水/淡水、三种砷分相、部分消解沉积物、土层和岩石预编译值仍是不同背景组。

## 使用自己的 CSV

```bash
python skills/global-geochemical-atlas/scripts/run_workflow.py \
  --input /path/to/measurements.csv \
  --output-dir output \
  --region-bbox 73,18,135,54 \
  --max-records 50000
```

最低输入列为 `element_or_analyte,value,unit,medium`。正式科学运行还应提供样品 ID、measurement basis、经纬度、CRS、分析方法、消解/提取方法、检出限、来源定位和许可。完整契约见 `skills/global-geochemical-atlas/references/`。

## 科学边界

- 保留原值、原单位、qualifier 和原始坐标表达；无法证明的转换失败关闭。
- 固体质量比可统一为 `mg/kg`；水体质量/体积统一为 `ug/L`，但不把水体 `ppm` 猜成质量/体积。
- `<LOD`、`BDL`、`ND` 不替换为 0 或 LOD/2。
- 不静默交换经纬度，不把未知 CRS 冒充 WGS84。
- 异常是相对已声明背景组的筛查候选，不等于污染、矿床或成因结论。
- 合成 demo 和真实来源最小 fixture 都只用于工程复现；后者保留各数据集许可与引用，也不支持全球或区域代表性结论。

## 仓库结构

```text
skills/
└── global-geochemical-atlas/
    ├── SKILL.md
    ├── fixtures/demo_input.csv
    ├── references/
    └── scripts/
```

没有 `requirements.txt`：运行脚本只使用 Python 标准库。完整数据不进入仓库；可使用受控下载脚本获取公开文件，并保存 DOI/PID、版本、文件 ID/名称、发布与访问时间、字节数、schema、行数、关键统计和许可。V4 不计算或校验 MD5、SHA-256 等内容哈希。

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
