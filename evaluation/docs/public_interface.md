# Public Interface

## 任务交付

评测运行器为每题提供该题 `inputs/`，被测 Skill 把 `task.json.required_outputs` 中列出的文件写入独立 submission directory。任务之间不得复用上题输出或隐藏状态。

## 分数

- 客观 checker：80；
- 证据锚定 LLM rubric：20；
- Public 只用于开发，不并入最终盲测主分。

## 允许反馈

设计组可以接收 Public 的逐题报告。对 Shadow/Final 只能接收聚合 capability、failure tag、频次和严重度，不接收具体输入、gold、阈值组合、样品 ID 或 checker 日志。

## 输出原则

- 结构化 CSV/JSON/GeoJSON 优先；
- 原始值与标准化值并存；
- 正确拒绝和部分成功是有效结果；
- 所有科学结论必须能回链到 record、source 和 QC 证据；
- 统计异常不是矿床、污染源或因果结论。
