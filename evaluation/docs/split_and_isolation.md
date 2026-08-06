# Public / Shadow / Final 隔离协议

## 三个集合

- Public Q01–Q08：可公开题面、输入、gold、checker，用于接口自测；
- Shadow Q09–Q16：评测侧持有，只反馈聚合失败模式；
- Final Q17–Q24：Skill、模型和沙箱冻结后才执行，逐题内容不对设计组公开。

## 物理边界

Public 留在 `evaluation/release/public/`。Shadow 和 Final 必须位于 E1 工作区与本公开仓库之外的受控私有根目录，例如：

```text
/secure/e2-private-root/
├── shadow/Q09-Q16/
├── final_holdout/Q17-Q24/
├── task_inventory_private.csv
└── PRIVATE_STATUS.json
```

私有根目录不得是符号链接，权限不得开放给 group/other。worker 只读挂载当前题所需的 `task.md`、安全任务元数据和 `inputs/`；gold、checker、rubric 只在评分侧可见。

## 公开导出

禁止手工打包整个 `evaluation/`。必须使用冻结白名单：

```bash
python3 tools/export_public_package.py . /tmp/gga-public
```

随后检查：

```bash
python3 tools/verify_isolation.py . /secure/e2-private-root
```

导出包只包含 alignment contract 明确允许的路径，并生成 `PUBLIC_MANIFEST.json`。`results/raw/`、评审 prompt、私有 manifest、Shadow 和 Final 都不得进入公开包。

## 被测 AI 的最小 Public 目录

不得把整个 `evaluation/` 或上述开发者 Public 导出包交给被测 AI。仓库内的
`ai_visible_public/` 只包含 Q01–Q08 的题面、安全任务元数据、声明的输入、
空 submission 目录和使用提示；不包含 gold、checker、rubric 或评分工具。

使用 `tools/export_ai_bundle.py` 生成或验证该目录。被测 Codex 的工作目录和
提示词见 `ai_visible_public/README.md`。

## 泄漏与 holdout 资格

公开反馈前必须检查是否出现隐藏样品 ID、坐标、数值、文件名、gold 字段组合、阈值或 checker 日志。通过“例如”改写唯一隐藏案例同样属于泄漏。

当前旧版 Q17–Q24 曾存在于公开 Git 历史，因此已失去严格 holdout 资格。迁出只能防止继续混放，不能撤销历史暴露；正式比赛必须由独立评测负责人新建并私下签名一套 Final。
