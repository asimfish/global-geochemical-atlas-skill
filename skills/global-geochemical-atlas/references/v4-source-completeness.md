# V4 来源完整率审计

> 本报告强制区分全量来源、登记契约和工程演示样板。没有全量分母时写 `not_measured`，不使用 demo 行数替代。

## 摘要

- 可执行来源：14
- 有全量候选审计：12
- 有明确目标测定分母：12
- 缺少全量候选审计：2
- 演示样板记录：736（仅工程测试）
- 已完成统一全量逐字段 profile：0

## 来源口径

| 来源 | 全量审计 | 全量目标测定 | demo 行 | 样品类型 demo 完整率 | 方法 scope demo 完整率 |
|---|---|---:|---:|---:|---:|
| `afsis-phase-i-wet-chemistry` | audited_snapshot | 12012 | 48 | 100.0% | 100.0% |
| `foregs-floodplain-sediment` | audited_snapshot | 9672 | 48 | 100.0% | 100.0% |
| `foregs-humus` | audited_snapshot | 1845 | 48 | 100.0% | 100.0% |
| `foregs-stream-sediment` | audited_snapshot | 11030 | 48 | 100.0% | 100.0% |
| `foregs-stream-water` | audited_snapshot | 4848 | 48 | 100.0% | 100.0% |
| `foregs-subsoil` | audited_snapshot | 10201 | 48 | 100.0% | 100.0% |
| `foregs-topsoil` | audited_snapshot | 10908 | 48 | 100.0% | 100.0% |
| `gemstat-open-archive` | audited_snapshot | 492999 | 48 | 100.0% | 100.0% |
| `georoc-archaean` | not_measured | not_measured | 48 | 100.0% | 0.0% |
| `geotraces-idp2025` | audited_snapshot | 39327 | 48 | 100.0% | 0.0% |
| `japan-gsj-geochemical-map` | audited_snapshot | 21168 | 48 | 100.0% | 0.0% |
| `norway-marchem` | audited_snapshot | 3520 | 112 | 100.0% | 100.0% |
| `pangaea-north-africa-soil` | audited_snapshot | 258 | 48 | 100.0% | 100.0% |
| `usgs-conus-soil` | not_measured | not_measured | 48 | 100.0% | 0.0% |

## 当前阻塞

1. 目前没有任一来源完成统一 V4 字段的全量逐行 numerator/denominator 统计。
2. 缺少全量审计的来源不能用 demo 完整率代表真实来源完整率。
3. 在线获取健康、schema drift 和 row-count drift 尚未由离线 profile 主动探测。

机器可读结果见 `assets/v4-source-completeness.json`。
