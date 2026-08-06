# Qwen3.8-Max Skill uplift public case

从本目录下载脚本取得的五个真实开放数据集构建一个可复现的小型地球化学图谱。不得读取仓库中的
`evaluation/stage_benchmark/scripts`、`workstreams` 或任何 `gold`/历史运行目录；它们是参考实现。

## 固定输入

先运行：

```bash
python public_case/prepare_case.py --output-dir case_data
```

数据包含：非洲水体与沉积物、南极沉积物、大洋洲土壤，以及 GLiM 0.5° 全球表层岩性栅格。
所有文件都来自官方/DOI 数据仓库并由大小与 SHA-256 固定。数据下载时间不计执行时间。

## 任务

在 `submission/` 生成：

1. `d1_raw.csv`：一行一个样品×元素测定，保留原值、单位、限定符、坐标、介质、方法、来源定位、版本、
   许可和文件哈希；至少覆盖固定输入中的四个地球化学数据集。来源没有报告方法、地质或坐标精度时必须写显式状态，
   不得编造。
2. `geochemistry.csv`、`qc_report.json`、`confidence_report.json`、`geology_report.json`、
   `anomalies.geojson`、`anomaly_report.json`：固体到 mg/kg、水体到 µg/L；保留删失语义；对 GLiM 执行
   版本化 point-in-cell 连接；水体和明确海洋沉积物不得赋陆地岩性；异常只能称候选高/低值。
3. `interactive_map.html`、`source_confidence.json`：离线自包含地图，支持元素、介质、地质、来源、置信度筛选，
   能下钻原值/标准值/方法/QC/来源，并显示覆盖空白与非因果边界。
4. `run.sh`：从 `case_data/` 一次重建全部输出；`agent_report.md` 和 `agent_report.json`：记录命令、耗时、
   模型、是否使用 Skill、失败案例、局限与评分结果。

允许新增 Python 文件和安装已声明依赖。不得复制参考实现，不得硬编码 scorer 期望值，不得把固定输入以外的
合成点伪装为真实测定。

## 评分

```bash
python public_case/score_submission.py --submission-dir submission --output score.json
```

总分 100：D1 证据链 30、D2 科学处理 35、D3 产品交付 20、可复现性 15。两组实验必须使用相同 commit、
输入、任务、时限和 scorer；唯一自变量是是否允许读取 `skills/global-geochemical-atlas/`。
