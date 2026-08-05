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
