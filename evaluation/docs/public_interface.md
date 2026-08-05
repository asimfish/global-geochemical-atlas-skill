# Public Interface

## 交卷位置与文件

每次运行使用一个全新的 submission 根目录。候选程序必须把 E1 的十个固定文件写到该目录的 `artifacts/` 下；文件清单和 MIME 类型以 `contracts/benchmark-execution-contract.json` 为准。

Q01–Q24 的题目专用结果不再作为额外文件提交，而是写入：

```text
artifacts/run_manifest.json
└── benchmark_evidence
    └── <task.json 中声明的 logical key>
```

每个逻辑证据项声明 `format`，并携带相应的 `value`、`rows` 或 `columns`。这让旧题 checker 可复算，同时保持 E1 的物理交卷接口不变。

## 条件、分数和退出码

- 裸模型为 `B0`，挂载 Skill 为 `S0`；每题每侧三次；
- checker/LLM 的点数是六维评审证据，不是“80+20”总分；
- 正式单次结果必须是符合 E1 schema 的 `score.json`；
- E1 退出码 `2` 表示候选部分成功；评测器内部异常返回 `75`。

## Public 边界

Public 只用于开发，不并入正式隐藏集结论。公开包必须由白名单导出工具生成：

```bash
python3 tools/export_public_package.py . /tmp/gga-public
```

对 Shadow/Final 只能反馈聚合 capability、failure tag、频次和严重度，不得反馈具体输入、gold、阈值组合、样品 ID 或 checker 日志。

## 科学输出原则

- 结构化 CSV/JSON/GeoJSON 优先；
- 原始值与标准化值并存；
- 正确拒绝和部分成功是有效结果；
- 结论必须回链到 record、source 和 QC 证据；
- 统计异常不能直接包装成矿床、污染源或因果结论。
