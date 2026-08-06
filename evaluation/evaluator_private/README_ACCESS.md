# Evaluator-only assets

本目录是 repo 内 Q09–Q24 的评分源，包含题面、输入、gold、checker 和 rubric。目录名中的 `private` 表示“不可交给答题 AI 的评分侧材料”，不表示这些题仍是秘密 holdout。

- 答题 AI 只能使用 `evaluation/ai_visible_public/`；
- Q09–Q24 的候选可见白名单投影由 `tools/export_ai_bundle.py` 生成；
- 不得把本目录作为答题 AI 工作目录或挂载给答题 AI；
- `shadow` 与 `final_holdout` 仅保留历史回归分组语义；
- Q17–Q24 已在历史中暴露，不具备正式 holdout 资格。
