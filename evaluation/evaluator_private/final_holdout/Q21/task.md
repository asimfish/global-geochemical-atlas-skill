# Q21 实验室批次 QC

按 `inputs/qc_policy.json` 计算每批的 CRM recovery、blank value 和 duplicate RPD，并输出 `batch_acceptance.csv`。

```text
RPD = |x1-x2| / ((x1+x2)/2) * 100
```

三个 QC 子项必须全部通过，批次才能进入科学分析。输出列：

```text
batch_id,crm_recovery_percent,crm_pass,blank_value,blank_pass,duplicate_rpd_percent,duplicate_pass,batch_pass,disposition
```
