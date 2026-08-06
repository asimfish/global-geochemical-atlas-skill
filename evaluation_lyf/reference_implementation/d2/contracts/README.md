# D2 interface contracts

- `interface-contract.json`：D1、D3、E1、E2 的角色边界和文件协议。
- `schema-map.schema.json`：任意来源 CSV 到 D2 canonical 列的映射格式。
- `run-manifest.schema.json`：E1 用于验证输出路径、SHA-256、计数和版本的运行清单格式。
- `../schema.json`：D2 canonical 长表单条记录的 JSON Schema；CSV 中 `qc_flags` 和
  `operational_confidence` 需先解析 JSON，`censored` 需解析为布尔值。

接口版本为 `d2-interface-v2`。字段只能通过新版本显式变更，D1/D3 不应自行维护同名但不同语义的字段。
