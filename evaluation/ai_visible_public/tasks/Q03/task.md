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

下文提到的 `normalized_elements.csv` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q03 固体样品质量分数统一

`inputs/soil_elements.csv` 的所有记录均为固体土壤、质量/质量基准。将其统一到 `mg/kg`，输出 `normalized_elements.csv`。

必须保留以下列：

```text
sample_id,element,original_value,original_unit,normalized_value,normalized_unit,conversion_rule
```

本题固定换算：

```text
1 ppm = 1 mg/kg
1 µg/g = 1 mg/kg
1 ppb = 0.001 mg/kg
1 wt% = 10,000 mg/kg
1 g/kg = 1,000 mg/kg
```

保留至少 6 位有效数字即可；checker 使用绝对容差。

`conversion_rule` 使用以下冻结字符串：

```text
ppm       -> ppm_mass_mass_to_mg_per_kg
mg/kg     -> identity_mg_per_kg
µg/g|ug/g -> ug_per_g_to_mg_per_kg
ppb       -> ppb_mass_mass_times_0.001
wt%       -> wt_percent_times_10000
g/kg      -> g_per_kg_times_1000
```
