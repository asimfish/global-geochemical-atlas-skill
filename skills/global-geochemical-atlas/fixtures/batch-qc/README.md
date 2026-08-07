# 实验室批次 QC 最小复现实验

本目录是原创合成 CC0 fixture，仅验证门禁，不代表任何真实实验室或样品。

```bash
python ../../scripts/evaluate_batch_qc.py \
  --input batch_qc.csv \
  --policy qc_policy.json \
  --stdout-contract
```

预期 `LAB-A` 通过：CRM 105%、空白 2、重复样 RPD 约 9.5238%；`LAB-B` 因 CRM 135%、空白 8、RPD 40% 全部失败。判断必须由原始 controls 重新计算，不能读取预置 pass/fail。

完整工作流还要求 `geochemistry.csv` 输入记录使用相同 `analysis_batch_id`。失败或未对账批次仍保留在数据库，但被排除出记录级和空间异常背景。
