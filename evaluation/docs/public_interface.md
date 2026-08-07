# Public Interface

## 交卷位置与文件

每次运行使用一个全新的 submission 根目录。候选程序必须把 E1 的十个固定文件写到该目录的 `artifacts/` 下；文件清单和 MIME 类型以 `contracts/benchmark-execution-contract.json` 为准。

Q01–Q24 的题目专用结果不再作为额外文件提交，而是写入：

```text
artifacts/run_manifest.json
└── benchmark_evidence
    └── <task.json 中声明的 logical key>
```

每个逻辑证据项声明 `format`。每题的精确输出形状位于该题
`task.json.candidate_visible_contract`；这是候选可见题面的一部分，不是隐藏评分信息。

JSON 逻辑证据使用：

```json
{
  "example.json": {
    "format": "json",
    "value": {
      "required_field": "value"
    }
  }
}
```

CSV 逻辑证据使用 `columns` 和对象数组 `rows`。每行必须以列名为键，不能使用位置数组：

```json
{
  "example.csv": {
    "format": "csv",
    "columns": ["record_id", "value"],
    "rows": [
      {"record_id": "R01", "value": "12.5"}
    ]
  }
}
```

JSONL 使用 `{"format":"jsonl","rows":[...]}`；普通文本使用
`{"format":"text","value":"..."}`。空 CSV 单元格可以编码为空字符串或 `null`，
但 `rows` 仍必须是对象数组。这让旧题 checker 可复算，同时保持 E1 的物理交卷接口不变。

候选 bundle 随附一个不含 gold、分值、rubric 或隐藏 checker 的公开契约校验器。它只检查必需物理文件、文件可解析性和上面的候选可见结构：

```bash
python3 validate_submission_contract.py --bundle-root .
```

单题隔离运行使用 `--task-root` 与 `--submission-root`。返回码 `2` 表示公开契约不合格，应修正结构后重跑；这不是分数。

## 条件、分数和退出码

- 裸模型为 `B0`，挂载 Skill 为 `S0`；每题每侧三次；
- checker/LLM 的点数是六维评审证据，不是“80+20”总分；
- 正式单次结果必须是符合 E1 schema 的 `score.json`；
- E1 退出码 `2` 表示候选部分成功；评测器内部异常返回 `75`。

## 答题 AI 可见边界

Q01–Q24 都是当前版本的候选可见回归题。答题 AI 的全部 Benchmark 文件必须只来自
`evaluation/ai_visible_public/`；不得把整个 `evaluation/`、`release/` 或
`evaluator_private/` 作为答题工作目录。

答题 bundle 必须由白名单导出器生成或验证：

```bash
python3 tools/export_ai_bundle.py . /tmp/gga-ai-visible-q01-q24
python3 tools/export_ai_bundle.py --validate-only ai_visible_public
python3 tools/verify_isolation.py --evaluation-root .
```

`public`、`shadow` 和 `final_holdout` 在本版本中只是历史回归分组标签，不代表严格隐藏集。
当前 bundle 禁止包含 gold、checker、rubric、评分 prompt、评分工具或 evaluator-only
目录。正式 Final 必须另行生成并在本 repo 与当前工作区之外私下冻结，不能进入当前 bundle。

## 科学输出原则

- 结构化 CSV/JSON/GeoJSON 优先；
- 原始值与标准化值并存；
- 正确拒绝和部分成功是有效结果；
- 结论必须回链到 record、source 和 QC 证据；
- 统计异常不能直接包装成矿床、污染源或因果结论。
