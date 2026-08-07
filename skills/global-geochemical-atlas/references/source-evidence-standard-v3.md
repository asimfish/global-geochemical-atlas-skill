# D1 V4 来源证据评分规范

版本：`geochemical-source-evidence-v4`

本文件定义 `scripts/score_source_evidence.py` 的机器判定契约。文件名为兼容旧链接保留；新审计结构见 [automated-audit.schema.json](automated-audit.schema.json)。

## 输入与原则

评分器只读取已经提交并可追溯的证据：

- `assets/source_catalog.json`：来源身份、接口、版本、科研使用条件和限制；
- `assets/source_manifest.json`：版本、文件身份、字节数、schema 与适配器注册；
- `fixtures/candidate-audits/*.json`：全量统计、字段和方法盘点；
- `fixtures/four-media/**/automated_audit.json`：30 条结构化 Codex 自动审计；同目录 `human_review.json` 只作历史兼容输入。

新流程不要求具名人工签署。历史人工复核文件仍可读取，但未签署的旧准备单不获得自动审计分，也不阻断来源的科研分析用途。

不计算、读取或校验内容哈希。版本与漂移依靠 DOI/PID、版本、文件 ID/名称、发布日期、字节数、schema、行数和关键统计追踪。

## 评分

固定权重为：身份 10、版本/快照 15、文件与记录完整性 15、来源追溯 15、schema 15、方法与 QC 10、适配器与复现 10、自动审计 10。

`verified=1.0`，`partial=0.5`，`missing/conflict=0`。缺失证据降低分数和适用范围，不自动淘汰来源；来源身份无法确认、文件损坏、访问条件冲突或记录无法回溯才属于红线。

自动审计至少考虑：普通值、删失或负值、极值、缺坐标、重复样品号、方法缺失或多候选，以及来源或映射冲突。某类异常在 30 条分层样本中不存在时明确写 `no_case_in_stratified_sample`，不得伪造案例。

总分计算：

```text
source_evidence_score = 100 × Σ awarded_points / Σ applicable_weights
```

分级：A 85–100、B 70–84、C 50–69、D 1–49、U 无法评分。

## 独立状态

- `access_status` 表示正常接口访问方式；
- `research_use_status` 表示本次科研分析条件，不把再分发当作默认科研准入门槛；
- `evidence_tier` 表示证据完整度，不是测量为真的概率；
- `use_mode` 表示当前工程允许用途。

`benchmark_ready` 要求 A 级、适配器已验证且 30 条结构化自动审计完成。方法、QC、坐标或引用仍不完整时必须继续在字段、完整率报告和限制中显示，不能因为等级较高而隐藏。

## 当前基线

截至 2026-08-07：

- 21 个可执行来源均有 30 条结构化 Codex 审计；
- 21 个来源均有统一全量字段 profile 和候选来源审计；
- 评分基线为 21 个 A 级 `benchmark_ready`、33 个 discovery 候选；
- GEOROC、USGS CONUS Soil、GSJ 等来源仍缺逐记录方法；AfSIS、TPDC 原始 CRS 仍未得到来源声明，这些是明确的证据缺口，不是被自动填充的字段。

机器基线保存在 `assets/source_evidence_scores.json`，必须能由评分命令重建。

## 运行

```bash
python3 scripts/migrate_automated_audits.py \
  --root fixtures/four-media \
  --check

python3 scripts/score_source_evidence.py \
  --output assets/source_evidence_scores.json
```
