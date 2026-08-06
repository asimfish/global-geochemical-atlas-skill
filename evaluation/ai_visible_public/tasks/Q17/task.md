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

下文提到的 `provenance_verdict.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q17 来源真实性

只使用冻结的 `identifier_registry.json` 核验 `candidates.json`，选出可接受记录并拒绝 DOI、title、URL 不一致或不在注册表中的候选。输出 `provenance_verdict.json`，不得联网补充或“纠正”候选。

每条 verdict 包含 `candidate_id,status,reason`，并给出唯一 `selected_candidate_id`。元数据字段一致才表示通过本题的目录核验，不等同数据值已经科学验证。

`provenance_verdict.json` 根对象必须包含 `registry_version`、`selected_candidate_id`、`validation_scope` 和 `verdicts`。冻结值为：

```text
通过候选 status=accept
不通过候选 status=reject
标识符存在但元数据冲突 reason=identifier_metadata_conflict
标识符不在冻结注册表 reason=identifier_not_in_frozen_registry
validation_scope=metadata_consistency_only
```
