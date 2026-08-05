# Q22 许可与再分发

严格按 `inputs/license_policy.json` 处理来源，输出：

```text
source_id,license_class,redistribution_allowed,allowed_payload,required_actions,confidence_penalty
```

`required_actions` 多项用分号按字母排序。未知许可不能被当成开放许可；限制再分发的数据只能发布元数据和指针。该决策不要求删除本地受控缓存。
