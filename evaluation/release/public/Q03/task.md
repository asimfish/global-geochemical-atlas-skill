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
