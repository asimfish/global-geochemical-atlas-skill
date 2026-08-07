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

## 真实来源四介质演示

需要展示赛题要求的岩石、土壤、沉积物和水体时，从 Skill 目录执行：

```bash
python scripts/build_four_media_demo.py \
  --output-dir /tmp/four-media-demo \
  --generated-at 2026-08-05T15:20:00Z

python scripts/run_workflow.py \
  --input /tmp/four-media-demo/demo_input.csv \
  --output-dir /tmp/four-media-output
```

预期为 1,084 条真实来源最小观测、四介质、二十一来源、1,076 条可标准化记录、1,084 个有效坐标、57 条已确认删失值、160 个隔离背景组及完整九文件输出。FOREGS/GEMAS 中可能或已知的 `DL/2` 数值和 AfSIS 中低于来源 DL/QL 的已发布数值都只带证据边界，不冒充普通可靠检出。岩石异常背景额外按构造背景隔离，避免把太古宙克拉通与南极板内火山岩直接混用。演示时先展示覆盖空白和来源范围，再展示地图；22 个候选异常只用于说明筛查界面，不能作污染、矿化或区域元素丰亏结论。
