# 来源真实性独立门禁

`audit_source_truth.py` 补足 Q01、Q05、Q17、Q22、Q24 之外的独立证据核验。原有任务仍负责引用、哈希、元数据一致性、许可证决策和哈希链；本门禁不改变 Q01–Q24 题面与分数。

## 核验范围

冻结契约按岩石、土壤、沉积物、水体分层抽取 8 个来源，独立保存：

- 权威入口、DOI、数据集标题、版本和许可证；
- 原始文件名与 SHA-256；
- 一条可定位到原始行的元素、数值、单位、坐标记录；
- DOI 或权威入口允许解析到的域名。

离线门禁逐行检查 `sources.jsonl` 与 `demo_input.csv` 的来源身份、版本、许可证和文件哈希，并对冻结原始记录做精确比较；它不会把“哈希相同”误写成“科学事实正确”。在线模式额外解析权威入口，网络失败输出 `needs_human_review`，不会伪装成已核验。

```bash
python3 evaluation/tools/audit_source_truth.py \
  --output /tmp/gga-source-truth.json

# 发布前人工复核；网络错误返回 2，证据冲突返回 74
python3 evaluation/tools/audit_source_truth.py \
  --online \
  --output /tmp/gga-source-truth-online.json
```

## 状态与声明边界

| 状态 | 含义 | 是否阻断代码合并 |
|---|---|---|
| `verified` | 冻结契约、来源元数据、文件证据和抽查记录一致 | 否 |
| `needs_human_review` | 离线证据一致，但在线权威入口无法访问 | 否；发布前必须复核 |
| `conflict` | 契约无效、元数据/哈希/抽查记录冲突，或解析到未批准域名 | 是 |

通过仅证明仓库声明与维护者冻结的权威快照、原始行证据一致；不证明出版方无误、样品具有区域代表性，也不证明异常的地质成因。更新上游数据时必须由维护者重新核对权威页与原始行，再显式更新契约和 `verified_at`，禁止从候选输出自动生成契约。
