# D1 / D2 / D3 单元与端到端验证

这个目录位于 `evaluation_lyf/reference_implementation/d2/` 之外，只作为团队内部验证工程，不是第二个参赛 Skill。

它提供五层互补验证：

1. `run_isolated_suite.py`：直接验证 D2 的标准化、QC、置信度、异常算法、命令行契约、确定性和资源占用。
2. `run_e2e_suite.py`：用小型合成金标准精确验证 D1→D2→D3 接口和边界条件。
3. `run_real_data_suite.py`：离线校验 4 个真实公开数据产品的固定哈希，经真实来源适配器送入 D2，
   再由 D3 生成并验收比赛要求的四项产品输出。
4. `run_global_data_suite.py`：核心模式保持 GEOROC、GEMAS、NGSA 和 GEMStat 的 19,455 条稳定回归；
   `--expanded` 模式再加入 TPDC 中国山地土壤、AfSIS、FOREGS、GSJ 日本与 PANGAEA 北非数据，
   用 44,536 条真实测定检验 15 个来源数据集、七洲、四介质、七元素和小国可见性。
5. `run_stage_benchmark.py`：把冻结真实数据分别停在 D1、D2、D3 接口，独立评测候选采集、标准化分析或
   专业可视化模块。标准契约见 [STAGE_BENCHMARK.md](STAGE_BENCHMARK.md)，参考审计见
   [STAGE_BASELINE_RESULTS.md](STAGE_BASELINE_RESULTS.md)。

详细测试矩阵、通过标准和边界见 [TEST_PLAN.md](TEST_PLAN.md)。
当前基线运行结论与发现见 [BASELINE_RESULTS.md](BASELINE_RESULTS.md)。
研究报告所列平台与当前实际适配范围的逐项对照见
[DATA_PLATFORM_COVERAGE.md](DATA_PLATFORM_COVERAGE.md)。
新增来源、许可与空白路线见 [DATA_SOURCE_CATALOG.md](DATA_SOURCE_CATALOG.md)。
让 OpenCode / Codex Agent 调用全球基准的方法见
[GLOBAL_BENCHMARK_FOR_AGENTS.md](GLOBAL_BENCHMARK_FOR_AGENTS.md)。

## 快速运行

从仓库根目录运行：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_isolated_suite.py \
  --report /tmp/d2-isolated-report.json
```

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_e2e_suite.py \
  --output-dir /tmp/d2-e2e-run
```

真实数据完整基线（40,131 条测定）：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_real_data_suite.py \
  --output-dir /tmp/d2-real-run
```

全球真实数据基线（19,455 条测定、七洲联合覆盖）：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_global_data_suite.py \
  --output-dir /tmp/d2-global-run
```

扩展全球真实基准（44,536 条测定；重点补中国、非洲、欧洲小国与日本）：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_global_data_suite.py \
  --expanded \
  --output-dir /tmp/d2-global-expanded
```

独立评测 D1、D2、D3 三个阶段的参考实现：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_stage_benchmark.py \
  --stage all \
  --output-dir /tmp/geochem-stage-benchmark
```

该命令默认从仓库内固定哈希的离线切片临时重建 D1/D2 金标准，不依赖未提交的 `runs/`
目录，也不会把生成数据写入仓库。若要复用已有参考运行，可显式传入
`--gold-run-dir /absolute/path/to/run`（其中须包含 `d1/`，评测 D3 时还须包含 `d2/`）。

评测另一个 Agent 产出的兼容 D2 脚本：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_global_data_suite.py \
  --expanded \
  --output-dir /tmp/d2-global-candidate \
  --d2-script /absolute/path/to/candidate_d2.py \
  --candidate-label candidate-name
```

一次运行四层方案；默认美国真实层将三个样品表各限制为 20 个样品以适合 CI，全球层使用完整冻结切片：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_all.py \
  --output-dir /tmp/d2-validation-run
```

如需让组合命令也使用全部真实记录，加 `--real-max-source-samples 0`。冻结真实数据的来源、许可、
查询和科学限制见 [real-data/README.md](real-data/README.md)。

每个命令成功时在 stdout 只打印一个 JSON 对象。测试报告中的状态含义：

- `pass`：全部阻断项和评审项通过。
- `pass_with_findings`：阻断项通过，但存在需要讨论或后续增强的评审项。
- `fail`：至少一个接口、科学红线或端到端阻断项失败。

输出目录必须不存在或为空，避免覆盖已有测试证据。

## 目录结构

```text
evaluation_lyf/stage_benchmark/
├── README.md
├── DATA_PLATFORM_COVERAGE.md
├── TEST_PLAN.md
├── assets/
│   └── natural-earth-110m-land.json # 已固定、public-domain 的离线陆地轮廓
├── contracts/
│   ├── e2e-expectations.json
│   ├── isolated-matrix.json
│   ├── real-gold.json
│   ├── real-sources.json
│   ├── global-sources.json
│   ├── expanded-sources.json
│   └── global-source-catalog.json
├── expanded-data/
│   ├── README.md
│   └── fixtures/raw/             # 7.67 MB 中国/非洲/欧洲/日本官方文件与证据
├── global-data/
│   ├── README.md
│   └── fixtures/raw/             # 2.16 MB 七洲联合真实切片与证据快照
├── real-data/
│   ├── README.md
│   └── fixtures/raw/             # 2.71 MB 真实原始数据、元数据与来源 manifest
└── scripts/
    ├── d1_stub.py
    ├── d3_stub.py
    ├── build_expanded_fixtures.py
    ├── build_global_fixtures.py
    ├── fetch_real_fixtures.py
    ├── global_d1_adapter.py
    ├── expanded_global_d1_adapter.py
    ├── lab_common.py
    ├── real_d1_adapter.py
    ├── run_all.py
    ├── showcase_builder.py
    ├── run_e2e_suite.py
    ├── run_global_data_suite.py
    ├── run_isolated_suite.py
    └── run_real_data_suite.py
```

测试运行产生的约 98.8 MB D2 全量输出不要提交到最终参赛 Skill；2.71 MB
固定原始 holdout、契约和下载器应保留，以满足无数据集场景下的离线复现。

全球父数据不进入仓库：GEMStat v3 ZIP 约 201 MB，GEOROC 父 CSV 约 31 MB，仅在维护者刷新切片时
下载到仓库外缓存。地图使用已嵌入的 Natural Earth 1:110m 陆地轮廓，普通评测和演示全程离线。

完整真实运行会额外产出并自动验收：

- `d3/atlas.html`：离线单文件交互元素地图；
- `d2/geochemistry.csv`：标准化地球化学数据库；
- `d3/source_confidence.json`：来源、许可、文件哈希、字段覆盖和置信度分解；
- `d3/anomaly_regions.geojson`：候选异常区域；
- `d3/anomaly_region_report.json`：阈值、未上图异常和解释边界；
- `d3/showcase_manifest.json`：四项交付物的路径、媒体类型和 SHA-256。
