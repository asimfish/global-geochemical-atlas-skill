# V4 来源完整率审计

> 本报告强制区分全量来源、登记契约和工程演示样板。没有全量分母时写 `not_measured`，不使用 demo 行数替代。

## 摘要

- 可执行来源：26
- 有 30 条结构化自动审计：26
- 有明确目标测定分母：26
- 缺少结构化自动审计：0
- 演示样板记录：1271（仅工程测试）
- 已完成统一全量逐字段 profile：26

## 来源口径

| 来源 | 自动审计 | 全量目标测定 | demo 行 | 样品类型 demo 完整率 | 方法 scope demo 完整率 |
|---|---|---:|---:|---:|---:|
| `afsis-phase-i-wet-chemistry` | automated_audit_complete | 12012 | 48 | 100.0% | 100.0% |
| `australia-ngsa-mercury` | automated_audit_complete | 2396 | 48 | 100.0% | 100.0% |
| `brazil-sgb-florianopolis-soil` | automated_audit_complete | 192 | 30 | 100.0% | 100.0% |
| `brazil-sgb-florianopolis-stream-sediment` | automated_audit_complete | 3132 | 31 | 100.0% | 100.0% |
| `cdogs-210102-lake-sediment` | automated_audit_complete | 4411 | 48 | 100.0% | 100.0% |
| `cdogs-210102-lake-water` | automated_audit_complete | 655 | 30 | 100.0% | 100.0% |
| `foregs-floodplain-sediment` | automated_audit_complete | 9672 | 48 | 100.0% | 100.0% |
| `foregs-humus` | automated_audit_complete | 1845 | 48 | 100.0% | 100.0% |
| `foregs-stream-sediment` | automated_audit_complete | 11030 | 48 | 100.0% | 100.0% |
| `foregs-stream-water` | automated_audit_complete | 4848 | 48 | 100.0% | 100.0% |
| `foregs-subsoil` | automated_audit_complete | 10201 | 48 | 100.0% | 100.0% |
| `foregs-topsoil` | automated_audit_complete | 10908 | 48 | 100.0% | 100.0% |
| `gemas-europe` | automated_audit_complete | 53703 | 52 | 100.0% | 100.0% |
| `gemstat-open-archive` | automated_audit_complete | 3739180 | 56 | 100.0% | 100.0% |
| `georoc-antarctica-intraplate` | automated_audit_complete | 1183 | 48 | 100.0% | 0.0% |
| `georoc-archaean` | automated_audit_complete | 65988 | 48 | 100.0% | 0.0% |
| `geotraces-idp2025` | automated_audit_complete | 39327 | 48 | 100.0% | 100.0% |
| `japan-gsj-geochemical-map` | automated_audit_complete | 21168 | 48 | 100.0% | 0.0% |
| `japan-gsj-marine-sediment` | automated_audit_complete | 34334 | 56 | 100.0% | 0.0% |
| `norway-marchem` | automated_audit_complete | 3520 | 112 | 100.0% | 100.0% |
| `pangaea-arabian-sea-sediment` | automated_audit_complete | 162 | 48 | 100.0% | 100.0% |
| `pangaea-north-africa-soil` | automated_audit_complete | 258 | 48 | 100.0% | 100.0% |
| `tpdc-china-mountain-soil` | automated_audit_complete | 6570 | 40 | 100.0% | 100.0% |
| `us-wqp-sacramento-river-arsenic` | automated_audit_complete | 189 | 48 | 100.0% | 100.0% |
| `usgs-conus-soil` | automated_audit_complete | 58284 | 48 | 100.0% | 0.0% |
| `usgs-utah-volcanic-whole-rock` | automated_audit_complete | 1447 | 48 | 100.0% | 64.6% |

## 当前证据缺口

1. 统一全量逐字段 profile、候选来源审计和 30 条结构化自动审计均完成 26/26；任何缺失字段仍显示 `not_measured` 或明确缺失原因。
2. GEOROC、USGS CONUS Soil、GSJ 等来源仍缺逐记录方法；这会降低可比较范围，不由自动审计补造。
3. AfSIS 和 TPDC 的注册文件及关联资料未声明原始 CRS，因此保持 `unknown`；不根据坐标外观推断 EPSG。
4. 在线实时可用性仍需独立探测；固定缓存的文件身份、字节数、schema、row-count 与离线重放已纳入 profile。

机器可读结果见 `assets/v4-source-completeness.json`。
