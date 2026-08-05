# Q18 来源编码解析

严格按 `inputs/encoding_rules.json` 解析 `inputs/encoded_values.csv`，输出：

```text
record_id,reported_value,numeric_value,bound_value,qualifier,detection_limit,censored,missing_reason,eligible_quantitative
```

来源特定负数和哨兵值不得进入真实浓度统计；`G` 表示超过上限。保留 reported_value，不进行删失值替代。
