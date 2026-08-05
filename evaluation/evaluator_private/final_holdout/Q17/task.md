# Q17 来源真实性

只使用冻结的 `identifier_registry.json` 核验 `candidates.json`，选出可接受记录并拒绝 DOI、title、URL 不一致或不在注册表中的候选。输出 `provenance_verdict.json`，不得联网补充或“纠正”候选。

每条 verdict 包含 `candidate_id,status,reason`，并给出唯一 `selected_candidate_id`。元数据字段一致才表示通过本题的目录核验，不等同数据值已经科学验证。
