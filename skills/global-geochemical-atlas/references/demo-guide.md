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

## 三分钟演示顺序

1. 展示请求和输入来源说明。
2. 运行一键命令并展示稳定文件清单。
3. 对比原值、标准值、qualifier、QC 和置信度。
4. 打开地图，筛选 As/soil，点击 500 mg/kg 候选点查看证据。
5. 展示异常报告中的背景组、样本量、MAD 和解释边界。
6. 展示水体 ppm、坐标交换与小样本组的失败关闭。
