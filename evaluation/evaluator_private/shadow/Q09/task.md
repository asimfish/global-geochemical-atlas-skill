# Q09 介质、相态和基准隔离

标准化 `inputs/mixed_media.csv`，但不得把不可比记录强行合并。

- 固体质量/质量统一到 `mg/kg`；
- 水体质量/体积统一到 `ug/L`；
- 不在没有含水率时把湿基换成干基；
- dissolved 与 total 不自动合并；题中 `filtered_dissolved` 映射到 dissolved family；
- `comparison_group` 为 `medium|basis|phase_family`。

输出 `normalized_observations.csv` 与按 comparison_group 汇总的 `group_summary.csv`。汇总使用非删失记录中位数，且必须保留组内单位。
