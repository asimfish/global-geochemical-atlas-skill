TASK:
<!-- candidate-visible-contract-v1:start -->
## 答题 AI 可见的机器提交契约

本题逻辑输出的精确容器、格式、CSV 列和 JSON 结构位于
`task.json.candidate_visible_contract`。该字段是题面的一部分，答题 AI 必须读取并遵守。

特别是，`format="csv"` 的逻辑证据必须使用 `columns` 加对象数组 `rows`；
每个 row 以列名为键，不得使用依赖位置的数组行。JSON 逻辑证据必须使用
`{"format": "json", "value": ...}`。未声明的题目专用物理文件不得创建。
<!-- candidate-visible-contract-v1:end -->

<!-- e1-alignment-v1 -->
## E1 统一交卷要求

只生成 `task.json.required_outputs` 列出的十个 E1 物理产物，并保持 `artifacts/` 固定路径。不得另外创建题目专用文件。

下文提到的 `verification_report.json` 是逻辑评测证据键，不是物理文件。把它们按 JSON/CSV/JSONL/text 的原结构写入 `artifacts/run_manifest.json` 的 `benchmark_evidence` 对象；E2 checker 只从该对象读取。

# Q05 下载资产完整性与媒体类型验证

将 `inputs/` 视为一次冻结下载缓存。根据 `inputs/download_manifest.json` 验证每个文件：

- 实际 SHA-256 是否与 manifest 一致；
- 内容是否真的是预期 CSV，而不是 HTML 错误页；
- 是否可以进入后续科学处理。

输出 `verification_report.json`。JSON 根对象必须包含 `task_id` 和 `records`；不得把记录数组直接作为 `value`：

```json
{
  "task_id": "GGA-PROV-001",
  "records": [
    {
      "filename": "...",
      "computed_sha256": "...",
      "sha256_status": "match|mismatch",
      "media_type_status": "csv|html_detected",
      "safe_to_use": false,
      "reasons": []
    }
  ]
}
```

每条记录包含：

```text
filename,computed_sha256,sha256_status,media_type_status,safe_to_use,reasons
```

只有哈希匹配且内容是 CSV 的文件才可 `safe_to_use=true`。不得修改输入文件来迎合 manifest。

冻结枚举为：

- `sha256_status`：`match` 或 `mismatch`；
- `media_type_status`：内容为 CSV 时写 `csv`，检测到 HTML 时写 `html_detected`；
- `safe_to_use`：JSON 布尔值，不使用字符串；
- 推荐 `reasons` 值：`content_is_html_not_csv`、`sha256_mismatch`；无问题时使用空数组。


RUBRIC:
```json
{
 "criteria": [
  {
   "dimension_id": "scientific_credibility",
   "full_credit": "解释 hash 匹配验证的是固定字节内容，而不是科学正确性本身。",
   "id": "integrity",
   "points": 8
  },
  {
   "dimension_id": "domain_understanding",
   "full_credit": "识别扩展名不能证明内容类型，HTML 错误页必须停止处理。",
   "id": "media",
   "points": 7
  },
  {
   "dimension_id": "engineering_quality",
   "full_credit": "对失败资产明确隔离并保留原因，不声称下载成功。",
   "id": "failure_behavior",
   "points": 5
  }
 ],
 "evidence_paths": [
  "artifacts/run_manifest.json#/benchmark_evidence/verification_report.json",
  "inputs/download_manifest.json"
 ],
 "evidence_points": 20,
 "scoring_contract": "e1-six-dimension-v1",
 "task_id": "GGA-PROV-001"
}
```

MACHINE EVIDENCE REPORT:
```json
{
 "task_id": "GGA-PROV-001",
 "scoring_contract": "e1-six-dimension-v1",
 "score_status": "evidence_only",
 "hard_gate_passed": true,
 "evidence_points_awarded": 80,
 "evidence_points_possible": 80,
 "dimensions": [
  {
   "dimension_id": "scientific_credibility",
   "weight": 0.25,
   "evidence_points_awarded": 75,
   "evidence_points_possible": 75,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "engineering_quality",
   "weight": 0.3,
   "evidence_points_awarded": 5,
   "evidence_points_possible": 5,
   "evidence_score": 100.0,
   "status": "scored"
  },
  {
   "dimension_id": "platform_reusability",
   "weight": 0.14,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "domain_understanding",
   "weight": 0.15,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "innovation_ecosystem",
   "weight": 0.1,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  },
  {
   "dimension_id": "open_source_potential",
   "weight": 0.06,
   "evidence_points_awarded": 0,
   "evidence_points_possible": 0,
   "evidence_score": null,
   "status": "not_scored"
  }
 ],
 "checks": [
  {
   "id": "output_exists",
   "type": "file_exists",
   "dimension_id": "engineering_quality",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "verification_report.json: file"
  },
  {
   "id": "record_count",
   "type": "json_length",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 5,
   "points_possible": 5,
   "evidence": "verification_report.json path=records length=3; expected=3"
  },
  {
   "id": "valid_safe",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "verification_report.json path=records.0.safe_to_use actual=True expected=True"
  },
  {
   "id": "html_unsafe",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "verification_report.json path=records.1.safe_to_use actual=False expected=False"
  },
  {
   "id": "tampered_unsafe",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 10,
   "points_possible": 10,
   "evidence": "verification_report.json path=records.2.safe_to_use actual=False expected=False"
  },
  {
   "id": "valid_hash_status",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "verification_report.json path=records.0.sha256_status actual='match' expected='match'"
  },
  {
   "id": "html_media_status",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "verification_report.json path=records.1.media_type_status actual='html_detected' expected='html_detected'"
  },
  {
   "id": "tampered_hash_status",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "verification_report.json path=records.2.sha256_status actual='mismatch' expected='mismatch'"
  },
  {
   "id": "valid_digest",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "verification_report.json path=records.0.computed_sha256 actual='73b952b81b4e4f41c00968d242946a78e09e7e878fa42fb31d9bb7084477cca5' expected='73b952b81b4e4f41c00968d242946a78e09e7e878fa42fb31d9bb7084477cca5'"
  },
  {
   "id": "tampered_digest",
   "type": "json_value",
   "dimension_id": "scientific_credibility",
   "passed": true,
   "points_awarded": 8,
   "points_possible": 8,
   "evidence": "verification_report.json path=records.2.computed_sha256 actual='84efbab5cb3f1d35038167bff6bc1b21c8c093593639ec936a1de63525ae81b5' expected='84efbab5cb3f1d35038167bff6bc1b21c8c093593639ec936a1de63525ae81b5'"
  }
 ],
 "redline_events": [],
 "grader_version": "6.0.0-draft.2"
}
```

EVIDENCE ARTIFACTS:
### artifacts/run_manifest.json#/benchmark_evidence/verification_report.json
```json
{
 "task_id": "GGA-PROV-001",
 "records": [
  {
   "filename": "valid_data.csv",
   "computed_sha256": "73b952b81b4e4f41c00968d242946a78e09e7e878fa42fb31d9bb7084477cca5",
   "sha256_status": "match",
   "media_type_status": "csv",
   "safe_to_use": true,
   "reasons": []
  },
  {
   "filename": "html_as_csv.csv",
   "computed_sha256": "9bec9bfb2fad5bd77c78df04f45441e80a3000bf3ccd9d1c416197fe4e6fed38",
   "sha256_status": "match",
   "media_type_status": "html_detected",
   "safe_to_use": false,
   "reasons": [
    "content_is_html_not_csv"
   ]
  },
  {
   "filename": "tampered.csv",
   "computed_sha256": "84efbab5cb3f1d35038167bff6bc1b21c8c093593639ec936a1de63525ae81b5",
   "sha256_status": "mismatch",
   "media_type_status": "csv",
   "safe_to_use": false,
   "reasons": [
    "sha256_mismatch"
   ]
  }
 ]
}
```

### inputs/download_manifest.json
```json
{
 "manifest_version": "q05-downloads-1",
 "files": [
  {
   "filename": "valid_data.csv",
   "expected_sha256": "73b952b81b4e4f41c00968d242946a78e09e7e878fa42fb31d9bb7084477cca5",
   "expected_media_type": "text/csv"
  },
  {
   "filename": "html_as_csv.csv",
   "expected_sha256": "9bec9bfb2fad5bd77c78df04f45441e80a3000bf3ccd9d1c416197fe4e6fed38",
   "expected_media_type": "text/csv"
  },
  {
   "filename": "tampered.csv",
   "expected_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
   "expected_media_type": "text/csv"
  }
 ]
}
```
