# Q12 置信度评分

严格按 `inputs/confidence_policy.json` 给 `inputs/records.json` 评分，输出 `confidence.json`。每条必须包含五个组件、总分、label 和 `confidence_is_probability=false`。

该分数是透明的 benchmark 启发式完整性分，不是结果为真的概率。不得自行调权或把 59 四舍五入成 medium。
