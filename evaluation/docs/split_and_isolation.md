# 评分源与答题 AI 可见目录隔离协议

## 当前三个回归分组

- Public Q01–Q08：完整评分源位于 `evaluation/release/public/`；
- Shadow Q09–Q16：完整评分源位于 `evaluation/evaluator_private/shadow/`；
- 旧 Final Q17–Q24：完整评分源位于 `evaluation/evaluator_private/final_holdout/`。

后两个名称保留历史分组语义，不代表题目仍对答题 AI 隐藏。Q09–Q24 的候选可见题面已明确导出，Q17–Q24 还曾存在于公开 Git 历史，所以当前 24 题全部是可见回归题。

## 唯一答题 AI 根目录

答题 AI 的工作目录必须是：

```text
evaluation/ai_visible_public/
```

其中只允许：

- `AGENT_PROMPT.md`、`README.md`、`VERSION` 和 `public_interface.md`；
- `tasks/Q01`–`tasks/Q24` 中的 `task.md`、`task.json` 与声明的 `inputs/`；
- `submissions/Q01`–`submissions/Q24`。

禁止把整个 `evaluation/`、`release/`、`evaluator_private/`、`docs/`、`tools/` 或 `results/` 挂载给答题 AI。gold、checker、rubric、评分 prompt 和历史提交不得进入 bundle。目录名本身不是沙箱；runner 必须把 `ai_visible_public/` 作为答题进程可见的文件系统根或唯一工作树。

## 白名单生成与校验

从 repo 根目录执行：

```bash
python3 evaluation/tools/export_ai_bundle.py \
  evaluation /tmp/gga-ai-visible-q01-q24

python3 evaluation/tools/export_ai_bundle.py \
  --validate-only evaluation/ai_visible_public

python3 evaluation/tools/verify_isolation.py \
  --evaluation-root evaluation
```

导出器只复制每题的候选可见文件，并为 Q01–Q24 建立 submission 目录。验证器拒绝符号链接、未列入 manifest 的输入文件以及任何名为 gold、checker、rubric、results 或 evaluator_private 的路径。

## 正式 holdout

当前 Q01–Q24 不能承担严格盲测。正式 Final 必须另外生成、在本 repo 和当前工作区之外私下冻结和签名；其逐题题面不得进入 `ai_visible_public/`，只允许在评测完成后披露经过批准的聚合结果。
