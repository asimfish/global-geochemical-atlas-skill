# Benchmark 统一执行契约说明

## 唯一上游

E2 不再定义独立的交卷文件、路径、总分或退出码。`contracts/benchmark-execution-contract.json` 固定引用 E1 `eval_version=1.0.0` 和 `contract_sha256=b113743f...acc4ee`；E1 契约变化时，先提升本 Benchmark 版本并重新冻结，再执行新 campaign。

## 交卷

每次运行只允许生成 E1 的十个固定物理产物，路径均位于 `artifacts/`。缺失、损坏、额外声明或路径逃逸按 E1 exit 74 处理。

原 Q01–Q24 的题目专用输出名不再是物理文件。为保留组件题的确定性检查，把这些逻辑证据写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象。每个键保留原逻辑输出名，值必须声明 `format` 并保存结构化内容。该对象是 Benchmark 证据扩展，不改变十个物理产物的身份。

## 条件和重复

- `bare` 映射为 E1 `B0`；
- `skill` 映射为 E1 `S0`；
- 每题每条件运行三次，同一 repeat 使用配对输入、模型参数和 seed；
- 只允许 Skill 的只读挂载差异，其余解析配置必须一致。

## 评分

E1 六维评分是唯一总分。E2 checker 和 LLM rubric 只产生绑定到六维之一的 metric 证据，不再把“80 分客观 + 20 分 LLM”相加成另一套总分。

正式 `score.json` 必须使用 E1 的六个 `dimension_id`、固定权重和 `total_score = sum(dimension.score * dimension.weight)`。尚未覆盖的维度标为 `not_scored`，整体保持 `partial`；不得用临时平均值填满。科学红线属于硬门禁：伪造来源、违反许可、跨不可比介质强行换算或作因果/矿床断言时，结果为 `ineligible`，不能靠其他维度补分。

## 退出码

候选、runner、artifact validator 和 scorer 全部采用 E1 的 0、2、10–30、70–76 映射。`2` 只表示候选 `partial_success`；grader 自身异常必须返回 `75`。原始子进程码只能写 `cause_exit_code`，不得覆盖公开 E1 退出码。

## 隐藏集

Public 只能通过白名单导出。Shadow 和 Final 必须放在 E1 工作区之外的受控私有根目录，并由 E2 worker 只读挂载；E1 只接收 opaque job、冻结 bundle hash 和允许披露的签名聚合结果。

当前公开 Git 历史中的 Q17–Q24 已失去严格 holdout 资格，只能作为开发回归集。正式 Final 必须由独立评测负责人重新生成、私下冻结和签名。
