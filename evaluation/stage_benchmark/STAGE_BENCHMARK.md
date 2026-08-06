# D1 / D2 / D3 标准单元测试基准

这套基准把赛题要求拆成三个可独立替换的模块。候选模块只接收该阶段应看到的冻结输入，输出后由
同一套机器检查与参考结果比较。评测数据来自真实公开来源切片，但不是全球总体估计，不能把覆盖空白
解释为元素不存在或含量为零。

## 1. 阶段边界

| 阶段 | 固定输入 | 候选模块应产出 | 核心验收 |
|---|---|---|---|
| D1 采集与来源整理 | 官方原始 CSV、XLSX、ZIP、GeoJSON、元数据和来源契约 | 原始测定长表、覆盖/来源 manifest | 四介质、七元素、七洲联合覆盖，原值、坐标、地质、方法和证据不丢失 |
| D2 标准化与科学处理 | 冻结 D1 长表 | 标准数据库、样点、QC、置信度、异常点、方法报告和哈希清单 | 单位与删失值、坐标和空间语义、可比背景组、异常高低方向、来源追溯 |
| D3 专业可视化 | 冻结 D1 manifest 与 D2 八项输出 | 离线交互地图及其标准数据库、来源、置信度、异常和复现配置 | 筛选、热力、组合、证据下钻、空白解释、专业边界和离线可复现 |

完整机器契约位于 `contracts/stage-benchmark-v1.json`。

## 2. 金标准绝对路径

### D1 的未处理输入

```text
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/global-data/fixtures/raw
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/expanded-data/fixtures/raw
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/contracts/global-sources.json
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/contracts/expanded-sources.json
```

### D2 的冻结输入（D1 已处理）

```text
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/runs/expanded-latest/d1/d1_global_export.csv
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/runs/expanded-latest/d1/d1_global_manifest.json
```

### D3 的冻结输入（D2 已处理）

```text
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/runs/expanded-latest/d2
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/runs/expanded-latest/d1/d1_global_manifest.json
```

### 参考 D3 成品

```text
/mnt/nas/data/lyf/hackathon/evaluation/d2-validation/runs/expanded-latest/d3
```

## 3. 候选模块接口

### D1

```text
python candidate_d1.py \
  --core-fixture-dir <core-raw-dir> \
  --expanded-fixture-dir <expanded-raw-dir> \
  --output-dir <new-dir>
```

必须输出 `d1_global_export.csv` 和 `d1_global_manifest.json`。一行表示一次样品—分析物测定；D1
不得预先做 D2 的单位换算、异常删值或删失值插补。

### D2

```text
python candidate_d2.py --input <d1-csv> --output-dir <new-dir>
```

必须输出八个 `d2-interface-v2` 文件。D2 不得下载新来源、重写来源证据或把候选异常解释为污染、
矿化或成因结论。

### D3

```text
python candidate_d3.py --input-dir <gold-d1-d2-dir> --output-dir <new-dir>
```

首选输出 `interactive_map.html` 和 `visualization_report.json`，并原样保留标准数据库、来源、置信度、
QC 和异常证据。D3 只做显示与交互，不重算 D2 标准值、置信度和异常判定。

## 4. 单独运行

测试 D1：

```bash
python3 /mnt/nas/data/lyf/hackathon/evaluation/d2-validation/scripts/run_stage_benchmark.py \
  --stage d1 \
  --d1-script /absolute/path/to/candidate_d1.py \
  --output-dir /tmp/geochem-d1-benchmark
```

测试 D2：

```bash
python3 /mnt/nas/data/lyf/hackathon/evaluation/d2-validation/scripts/run_stage_benchmark.py \
  --stage d2 \
  --d2-script /absolute/path/to/candidate_d2.py \
  --output-dir /tmp/geochem-d2-benchmark
```

测试 D3：

```bash
python3 /mnt/nas/data/lyf/hackathon/evaluation/d2-validation/scripts/run_stage_benchmark.py \
  --stage d3 \
  --d3-script /absolute/path/to/candidate_d3.py \
  --output-dir /tmp/geochem-d3-benchmark
```

同时运行三段参考实现：

```bash
python3 /mnt/nas/data/lyf/hackathon/evaluation/d2-validation/scripts/run_stage_benchmark.py \
  --stage all \
  --output-dir /tmp/geochem-all-stage-benchmark
```

每个输出目录必须不存在或为空。最终查看：

```text
<output-dir>/stage_benchmark_report.json
```

`counts.blocking.failed` 必须为 `0`。`pass_with_findings` 表示模块接口和科学红线通过，但真实来源仍有
覆盖或元数据缺口；不得通过编造地质背景、方法、坐标精度或国家归属消除 finding。

## 5. 金标准自身的边界

当前扩展基线满足四介质、七元素、七洲联合覆盖，提供 44,536 条测定、15 个数据集、102 个显式
来源国家/地区标签、44,510 条可上图记录和 535 个候选异常点。它仍有以下真实边界：

- 七洲 × 四介质共 28 个格子中只有 17 个非空；这不是每洲四介质完整图谱。
- 分析方法覆盖约 80.8%，地质背景/匹配证据覆盖约 43.5%，坐标不确定度覆盖约 1.36%。
- 现有地质信息主要是来源报告的构造背景、母岩、地图幅或流域；没有对全部点执行统一全球地质多边形连接。
- 水体目标元素切片只覆盖四洲；拉美、非洲和小国仍有明显介质空洞。
- 专业交互通过确定性静态检查和真实数据渲染验证，但不能代替地球化学专业人员的正式可用性研究。

这些项目在报告中作为 `review` finding 保留。候选方案如果提供可信的新数据源、统一地质空间连接或更好的
专业交互，可以优于参考实现；比较时不要只追求逐字节复制参考输出。
