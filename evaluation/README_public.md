# Global Geochemical Atlas Benchmark v5 — Public Development Set

本公开包只包含 Q01-Q08，用于对齐输入/输出接口、科学术语和基础失败模式。它不包含 Shadow 或 Final Holdout 的题面、输入、gold、checker 或可反推答案的细节，也不计入正式盲测主分。

公开题覆盖：数据源范围匹配、provenance、固体质量分数单位、氧化物换算、文件完整性、LOD/限定符、坐标 QC、重复与多方法记录。

每题目录：

```text
Qxx/
├── task.json
├── task.md
├── inputs/
├── gold/
├── checker/grader_spec.json
└── rubric.json
```

开发者可查看 public gold 和 checker；因此 public 成绩只能作为接口自测，不代表盲测泛化能力。
