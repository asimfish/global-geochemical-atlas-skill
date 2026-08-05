# Q04 Fe2O3 转 Fe

处理 `inputs/rock_oxide.csv`，按 `inputs/conversion_constants.json` 的冻结原子量把 **Fe2O3** 换算为元素 Fe，并统一元素结果到 `mg/kg`。

```text
Fe fraction in Fe2O3 = (2 × M(Fe)) / (2 × M(Fe) + 3 × M(O))
```

要求：

- 原始 analyte、值和单位必须保留；
- 原本已是 Fe 的记录只做单位换算；
- FeO 记录保留，但本题不得套用 Fe2O3 因子；将其 `status` 记为 `not_requested`，标准化值留空；
- 输出 `element_database.csv`，列为：

```text
sample_id,analyte_reported,reported_value,reported_unit,element,normalized_value,normalized_unit,conversion_factor,conversion_rule,status
```

数值 checker 的绝对容差为 `0.02 mg/kg`。
