# D1 / D2 / D3 stage-v2 真实数据基准

本版在 v1 的基础上补齐七洲×四介质的结构测试、摩尔水体单位和版本化全球表层岩性连接。它仍是冻结的真实数据
工作流基准，不是全球样品总体，也不代表每个国家已有公开数据。

```bash
python evaluation/stage_benchmark/scripts/run_completion_reference.py \
  --output-dir /tmp/geochem-stage-v2-reference
```

首次运行会下载并校验约 1.3 MB 新增来源；下载时间不计比赛运行时。参考运行会生成较大的可删除产物，因此不要把
`/tmp/geochem-stage-v2-reference` 提交到 Git。

阶段接口：

- D1 输入：`completion-data/fixtures/raw/` 及三个既有 raw fixture 目录；输出 `d1_completion_export.csv` 和 manifest。
- D2 输入：D1 CSV 与 GLiM ZIP；输出标准数据库、QC、置信度、空间地质报告、样点和候选异常。
- D3 输入：D2 公共文件与 D1 coverage manifest；输出自包含 atlas、来源/置信度、异常区域和消费校验报告。

参考门槛见 `contracts/stage-benchmark-v2.json`。关键解释方式：

- 介质格子：17/28 → 28/28；仅表示结构测试非空。
- 水体洲覆盖：4/7 → 7/7；不表示洲内均匀覆盖。
- 分析方法非空率：80.76% → 90.76%；其中“具体、可执行方法”另报 68.20%，部分说明不得混入该分母。
- 坐标精度：数值不确定度仍只有约 1.13%，但状态覆盖为 100%；另有 99.94% 坐标文本分辨率，明确不是准确度。
- 来源地质背景：仍单独报告；D2 GLiM 对适用固体记录匹配率 90.14%，全记录处置率 100%，水体误赋为 0。

机器报告 `stage_v2_reference_report.json` 会列出 D1、D2、D3 产物的绝对路径，可直接把某阶段的金标准输入交给
对应 Agent 做隔离测试。
