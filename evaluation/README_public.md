# Global Geochemical Atlas Benchmark v6 — Public Development Set

本公开包只包含 Q01–Q08，用于理解 E1 交卷接口、地球化学科学边界和常见失败模式。Public 的题面、输入、gold 与 checker 都可见，因此 Public 结果只能用于开发诊断，不能证明对隐藏题的泛化能力。

每题的 `task.json.required_outputs` 都是 E1 的十个固定 `artifacts/` 文件。题目原有的专用结构化结果保存在 `artifacts/run_manifest.json.benchmark_evidence`，具体逻辑键由题面说明。

```text
Qxx/
├── task.json
├── task.md
├── inputs/
├── gold/artifacts/               # E1 形状的公开自测答案
├── checker/grader_spec.json       # 六维证据检查，不是另一套总分
└── rubric.json                    # 证据标准及所属 E1 维度
```

最终评分只采用 E1 六维权重与 E1 `score.json`；退出码也只采用 E1 映射。
