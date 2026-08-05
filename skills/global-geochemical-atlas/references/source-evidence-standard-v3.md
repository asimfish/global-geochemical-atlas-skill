# D1 V3 来源证据评分规范

版本：`geochemical-source-evidence-v3`

本文件定义 `scripts/score_source_evidence.py` 的机器判定契约。科研解释与操作边界见 [source-acceptance-standard.md](source-acceptance-standard.md)，JSON 输出见 [source-evidence-report.schema.json](source-evidence-report.schema.json)。

## 输入

评分器只读取已经提交并可追溯的证据：

- `assets/source_catalog.json`：来源身份、接口、版本线索、旧许可描述和限制；
- `assets/source_manifest.json`：冻结版本、下载契约、文件清单和适配器注册；
- `fixtures/candidate-audits/*.json`：动态快照、字段盘点、方法盘点和人工复核进度。

未写入证据文件的口头判断不得获得分数。缺失证据记为 `missing`，不能由来源知名度自动补分。

## 评分

固定权重为：身份 10、版本/快照 15、文件与记录完整性 15、来源追溯 15、schema 15、方法与 QC 10、适配器与复现 10、人工复核 10。

`verified=1.0`，`partial=0.5`，`missing/conflict=0`；`not_applicable` 从分母移除并要求理由。人工复核按 0/2/5/10 渐进计分。

总分计算：

```text
source_evidence_score = 100 × Σ awarded_points / Σ applicable_weights
```

分级：A 85–100、B 70–84、C 50–69、D 1–49、U 无法评分。

## 独立状态

- `access_status` 只根据正常接口访问方式计算，不用许可描述替代访问事实；
- `research_use_status` 只表示本次科研分析条件，不参与证据分；
- `evidence_tier` 由八维证据计算；
- `use_mode` 由访问、科研使用、关键证据、适配器和人工复核共同决定。

`benchmark_ready` 要求 A 级、适配器已验证且人工复核维度为 `verified`。满足 A 级但未完成 30 条复核的来源最多为 `normalized_analysis`。

## 当前可复现基线

截至 2026-08-05：

| 来源 | 分数/等级 | use mode | 关键未完成项 |
|---|---|---|---|
| `georoc-archaean` | 85 / A | `normalized_analysis` | 30 条人工复核、方法/QC 完整率审计 |
| `usgs-conus-soil` | 85 / A | `normalized_analysis` | 跨三土层 30 条人工复核、方法/QC 完整率审计 |
| `norway-marchem` | 85 / A | `normalized_analysis` | 30 条人工复核 |
| `geotraces-idp2025` | 85 / A | `normalized_analysis` | 30 条人工复核、贡献者/方法完整率审计；As 由 GEMStat 淡水路由补充但背景必须隔离 |
| `gemstat-open-archive` | 85 / A | `normalized_analysis` | 30 条人工复核；大量方法代码 0，需按方法完备性限制可比较子集 |

机器基线保存在 `assets/source_evidence_scores.json`，必须能由评分命令逐字重建。

## 运行

```bash
python scripts/score_source_evidence.py \
  --output assets/source_evidence_scores.json

python scripts/source_audit.py \
  --output source_audit.json
```

评分更新时必须同时更新证据文件、测试和计划执行记录；不能直接手改总分。
