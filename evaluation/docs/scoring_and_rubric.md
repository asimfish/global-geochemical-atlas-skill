# E1 六维评分与 E2 证据规范

## 唯一总分

E2 不再采用“客观 80 分 + LLM 20 分”。checker、LLM 和静态评审只产生 metric 证据，每条证据必须绑定一个 E1 `dimension_id`。`finalize_score.py` 将证据归一化后生成符合 E1 schema 的六维 `score.json`。

| E1 维度 | 权重 | 判定要点 |
|---|---:|---|
| 科学可信性与证据链 `scientific_credibility` | 25% | 来源可靠、引用可追溯；参数标注适用条件，并说明不确定性与失败案例。 |
| 可完成性与工程质量 `engineering_quality` | 30% | 在官方任务上真实完成并优于无 Skill 基线；依赖清晰、接口稳定、结果可复现。 |
| 平台 Skill 复用价值 `platform_reusability` | 14% | 输入/输出 Schema 明确，结构化输出可被平台、其他项目或其他 Skill 复用。 |
| 领域理解与问题定义 `domain_understanding` | 15% | 准确理解课题的科学边界，问题定义清晰，避免将一般性总结包装成科学结论。 |
| 创新性与生态价值 `innovation_ecosystem` | 10% | 思路新颖，能够填补开源 Skill 生态空白，并便于他人复用与扩展。 |
| 开源潜力 `open_source_potential` | 6% | 许可证、文档、样例、baseline 与复现说明完整。 |

单次运行总分为：

```text
total_score = Σ(dimension.score × dimension.weight)
```

不得再把 checker 点数和 LLM 点数直接相加，也不得用 Benchmark 自己的分数覆盖 E1 总分。

## 三类证据

- 确定性 checker：文件、schema、记录、容差、QC、来源和拒绝状态等可复算事实；
- LLM rubric：事实/推断/限制是否分开，解释是否被具体字段支持；
- 静态评审：许可证、文档、样例、依赖、Schema 和复现说明等仓库级证据。

若某个维度没有冻结证据，必须标为 `not_scored`，该次 `score_status` 为 `partial`；不能凭印象补分。只有六维均有合格证据时才是 `complete`。

## 红线与硬门禁

- `task_cap_20`：将科学可信性维度封顶为 20；
- `task_zero`：硬门禁失败，结果为 `ineligible`；
- `acceptance_fail`：硬门禁失败，结果为 `ineligible`。

红线必须指向具体产物位置。伪造来源、违反许可、跨不可比介质强行换算，或把统计异常直接断言为矿床/污染源/因果结论，不能靠其他维度抵消。

## B0/S0 对照与汇总

同一题、同一模型、同一输入和 seed：

- `B0` 不挂载 Skill，运行三次；
- `S0` 只增加冻结 Skill，运行三次；
- 每侧取 E1 `total_score` 中位数并报告极差、MAD 和 uplift；
- 同一 repeat 的 B0/S0 必须有相同 `pair_fingerprint`；
- uplift 为 `median(S0) - median(B0)`，负数不截断。

Public、Shadow、Final 分开报告。聚合结果是描述性证据；是否通过应以冻结的 E1 六维门槛、硬门禁和完整运行记录为准。

## 产物链

```text
submission/artifacts/*
  -> grade_task.py -> objective_report.json（六维机器证据）
  -> LLM/static review JSON（六维评审证据，可选）
  -> finalize_score.py -> score.json（E1 唯一单次总分）
  -> aggregate_runs.py -> B0/S0 描述性汇总
```

原始 prompt、模型标识、参数、响应、checker 报告和 `score.json` 都必须保留，不能只保存最终数字。
