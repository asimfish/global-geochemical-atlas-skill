# D1/D2 自动复查循环

## 目标

`iteration_backlog.csv` 是可审计的回路控制面，不是自动插补列表。每一项绑定 `record_id`、`source_id`、负责人、问题码、字段、证据说明、建议动作和是否可自动复查。canonical 数据库和原始证据始终不可变；修复通过重新采集、重新映射和重跑 D2 产生新版本。

## 状态与负责人

| 状态 | 含义 | 默认动作 |
|---|---|---|
| `action_required` | 有明确缺失或失败，且可能通过来源证据或确定性处理修复 | 路由给 D1/D2 后重跑 |
| `review_required` | 映射、置信度或空间/方法语义需要人工判断 | 先复核，不自动改值 |
| `scientific_limit` | 删失值等真实科学限制，不等同于流水线失败 | 保留并应用相应统计边界 |

D1 负责来源定位、许可、原始坐标/CRS、样品类型与分析方法证据。D2 负责单位和基准标准化、方法适用范围、地质空间匹配、QC 与置信度。负责人只表示下一步路由，不改变字段的来源归属。

## Agent 状态机

1. 运行全流程或 `build_iteration_backlog.py`，保存第 0 轮清单与 action/review/scientific-limit 计数。
2. 只处理 `action_required`：按 `stage_owner + source_id + issue_code` 分组，优先修复能同时改善多条记录的来源级证据或映射。
3. D1 必须记录新证据定位、访问时间、版本和 hash；D2 必须保留原值并记录确定性转换/匹配规则。无法证明的值继续为空。
4. 重跑标准化、QC、置信度、异常和待办生成；比较本轮与上一轮的稳定 `item_id` 和问题计数。
5. 最多执行 2 轮。`action_required` 归零则成功；数量不下降、同一阻塞重复、来源不可访问、许可/CRS/方法语义不明或只能靠猜测时，停止并输出 `needs_human_review`。
6. `scientific_limit` 不计入“修复率”；删失观测只能通过获得更高质量原始测量或采用明确的删失统计模型改变处理方式，不能填 0、DL/2 或模型猜值后声称已修复。

## 单独运行

```bash
python scripts/build_iteration_backlog.py \
  --database OUTPUT_DIR/geochemistry.csv \
  --output OUTPUT_DIR/iteration_backlog.csv
```

修订页面导出的 `geochemistry-research-patch-v1` 只是人工/Agent 审核输入。应用前逐项验证 `reason` 中的来源定位，并创建新版本；不要在浏览器中直接覆盖 `geochemistry.csv`。
