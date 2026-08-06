# D2 地球化学标准化与分析工作包

状态：`d2-interface-v2`，可供 D1/D3/E1/E2 联调。

## 职责边界

D2 负责长表 Schema、介质感知单位换算、受控氧化物换算、删失值、坐标/方法/重复 QC、运行级置信度、
候选异常筛查及机器接口。D2 不负责下载数据、裁决第三方许可、实现地图 UI、制作评测 gold 或合并最终
`SKILL.md`。

## 目录

```text
workstreams/d2/
├── README.md
├── HANDOFF.md
├── contracts/
│   ├── interface-contract.json
│   ├── schema-map.schema.json
│   └── run-manifest.schema.json
├── demo_output/
├── fixtures/
│   ├── demo_input.csv
│   ├── demo_mapped_input.csv
│   └── demo_schema_map.json
├── references/standardization-qc-anomaly.md
├── schema.json
└── scripts/geochem_d2_pipeline.py
```

根目录测试：`tests/test_d2_geochem_pipeline.py`。

## D1 输入

最低 canonical 列：

```text
element_or_analyte,value,unit,medium
```

来源列名不一致时，传入 `canonical_field -> source_column` JSON：

```bash
python3 workstreams/d2/scripts/geochem_d2_pipeline.py \
  --input workstreams/d2/fixtures/demo_mapped_input.csv \
  --schema-map workstreams/d2/fixtures/demo_schema_map.json \
  --output-dir /tmp/geochem-mapped
```

正式数据应提供数据集、文件、源行、版本、许可和定位字段，详见
[`contracts/interface-contract.json`](contracts/interface-contract.json)。不要预先插补删失值、删除重复记录或做第二套单位换算。

## D2 运行

生产默认值要求每个可比背景组至少 20 条有效记录、可量化比例至少 70%：

```bash
python3 workstreams/d2/scripts/geochem_d2_pipeline.py \
  --input workstreams/d2/fixtures/demo_input.csv \
  --output-dir /tmp/geochem-d2-output
```

合成 demo 只有 12 条有效 As 记录，因此为演示异常路径显式降低样本门槛：

```bash
python3 workstreams/d2/scripts/geochem_d2_pipeline.py \
  --input workstreams/d2/fixtures/demo_input.csv \
  --output-dir workstreams/d2/demo_output \
  --min-group-size 8
```

可选参数：`--schema-map`、`--region-bbox W,S,E,N`、`--group-by`、`--min-group-size`、
`--min-quantified-fraction` 和 `--robust-z-threshold`。

## D2 输出

- `geochemistry.csv`：canonical 长表；解码后每条记录符合 [`schema.json`](schema.json)。
- `samples.geojson`：D3 可直接显示的有效坐标样点。
- `anomalies.geojson`：候选高/低异常。
- `qc_report.json`：计数、标准化率、删失、坐标和 flags。
- `confidence_report.json`：五分量运行级置信度。
- `anomaly_report.json`：背景组、有效比例、阈值和失败状态。
- `map_spec.json`：D3 的筛选、图层、空值行为和免责声明契约。
- `run_manifest.json`：E1 可验证的输入/输出 SHA-256、参数、计数和版本。

CSV 中 `qc_flags`、`operational_confidence` 是 JSON 字符串，`censored` 是小写 `true/false`。
相同输入字节、映射和参数必须产生逐字节相同结果。

`fixtures/demo_input.csv` 是 CC0 合成验收数据，只证明流水线行为，不构成真实科学结论。

## 验收

```bash
python3 workstreams/d2/scripts/geochem_d2_pipeline.py --help
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q tests/test_d2_geochem_pipeline.py
```

核心红线：不把删失值变成零；不猜未知单位；不静默交换坐标；不混合不同介质、basis、方法族和提取方法；
不把统计候选异常写成污染、矿床或成因结论。
