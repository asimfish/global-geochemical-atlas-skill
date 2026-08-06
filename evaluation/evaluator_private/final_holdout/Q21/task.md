<!-- candidate-visible-contract-v1:start -->
## 答题 AI 可见的机器提交契约

本题逻辑输出的精确容器、格式、CSV 列和 JSON 结构位于
`task.json.candidate_visible_contract`。该字段是题面的一部分，答题 AI 必须读取并遵守。

特别是，`format="csv"` 的逻辑证据必须使用 `columns` 加对象数组 `rows`；
每个 row 以列名为键，不得使用依赖位置的数组行。JSON 逻辑证据必须使用
`{"format": "json", "value": ...}`。未声明的题目专用物理文件不得创建。
<!-- candidate-visible-contract-v1:end -->

<!-- e1-alignment-v1 -->
## E1 统一交卷要求

只生成 `task.json.required_outputs` 列出的十个 E1 物理产物，并保持 `artifacts/` 固定路径。不得另外创建题目专用文件。

下文提到的 `batch_acceptance.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q21 实验室批次 QC

按 `inputs/qc_policy.json` 计算每批的 CRM recovery、blank value 和 duplicate RPD，并输出 `batch_acceptance.csv`。

```text
RPD = |x1-x2| / ((x1+x2)/2) * 100
```

三个 QC 子项必须全部通过，批次才能进入科学分析。输出列：

```text
batch_id,crm_recovery_percent,crm_pass,blank_value,blank_pass,duplicate_rpd_percent,duplicate_pass,batch_pass,disposition
```

`disposition` 使用 `accept_for_scientific_analysis` 或
`exclude_batch_and_investigate`。所有 `*_pass` 字段必须是布尔值，不使用字符串。
