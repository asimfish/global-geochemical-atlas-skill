# V4 来源完整率审计

> 本报告强制区分全量来源、登记契约和工程演示样板。没有全量分母时写 `not_measured`，不使用 demo 行数替代。

## 摘要

- 可执行来源：34
- 有全量候选审计：23
- 有明确目标测定分母：34
- 缺少全量候选审计：11
- 演示样板记录：1772（仅工程测试）
- 已完成统一全量逐字段 profile：34

## 来源口径

| 来源 | 全量审计 | 全量目标测定 | demo 行 | 样品类型 demo 完整率 | 方法 scope demo 完整率 |
|---|---|---:|---:|---:|---:|
| `4tu-northern-china-sediment` | uniform_full_profile | 6069 | 56 | 100.0% | 85.7% |
| `afsis-phase-i-wet-chemistry` | uniform_full_profile | 12012 | 48 | 100.0% | 100.0% |
| `australia-ngsa` | uniform_full_profile | 10492 | 48 | 100.0% | 100.0% |
| `australia-ngsa-mercury` | uniform_full_profile | 2396 | 48 | 100.0% | 100.0% |
| `earthchem-dehailonggang-rock` | uniform_full_profile | 75 | 75 | 100.0% | 100.0% |
| `eidc-ningbo-soil` | uniform_full_profile | 480 | 48 | 100.0% | 100.0% |
| `figshare-yangtze-basin-soil-heavy-metals` | uniform_full_profile | 6625 | 56 | 100.0% | 0.0% |
| `foregs-floodplain-sediment` | uniform_full_profile | 9672 | 48 | 100.0% | 100.0% |
| `foregs-humus` | uniform_full_profile | 1845 | 48 | 100.0% | 100.0% |
| `foregs-stream-sediment` | uniform_full_profile | 11030 | 48 | 100.0% | 100.0% |
| `foregs-stream-water` | uniform_full_profile | 4848 | 48 | 100.0% | 100.0% |
| `foregs-subsoil` | uniform_full_profile | 10201 | 48 | 100.0% | 100.0% |
| `foregs-topsoil` | uniform_full_profile | 10908 | 48 | 100.0% | 100.0% |
| `gemas-europe` | uniform_full_profile | 53703 | 52 | 100.0% | 100.0% |
| `gemstat-open-archive` | uniform_full_profile | 3739180 | 56 | 100.0% | 100.0% |
| `georoc-antarctica-intraplate` | uniform_full_profile | 1183 | 48 | 100.0% | 0.0% |
| `georoc-archaean` | uniform_full_profile | 65988 | 48 | 100.0% | 0.0% |
| `georoc-convergent-margins` | uniform_full_profile | 177217 | 48 | 100.0% | 0.0% |
| `geotraces-idp2025` | uniform_full_profile | 39327 | 48 | 100.0% | 0.0% |
| `japan-gsj-geochemical-map` | uniform_full_profile | 21168 | 48 | 100.0% | 0.0% |
| `japan-gsj-marine-sediment` | uniform_full_profile | 34334 | 56 | 100.0% | 0.0% |
| `norway-marchem` | uniform_full_profile | 3520 | 112 | 100.0% | 100.0% |
| `pangaea-amazonas-soil` | uniform_full_profile | 1181 | 49 | 100.0% | 100.0% |
| `pangaea-arabian-sea-sediment` | uniform_full_profile | 162 | 48 | 100.0% | 100.0% |
| `pangaea-barents-c-horizon-soil` | uniform_full_profile | 2419 | 32 | 100.0% | 100.0% |
| `pangaea-batagay-soil` | uniform_full_profile | 93 | 48 | 100.0% | 100.0% |
| `pangaea-brasol-ne-brazil-soil` | uniform_full_profile | 1614 | 48 | 100.0% | 100.0% |
| `pangaea-east-china-sea-clay` | uniform_full_profile | 392 | 32 | 100.0% | 100.0% |
| `pangaea-north-africa-soil` | uniform_full_profile | 258 | 48 | 100.0% | 100.0% |
| `pangaea-south-china-sea-sediment` | uniform_full_profile | 220 | 40 | 100.0% | 100.0% |
| `tpdc-china-mountain-soil` | uniform_full_profile | 6570 | 40 | 100.0% | 100.0% |
| `us-wqp-sacramento-river-arsenic` | uniform_full_profile | 189 | 48 | 100.0% | 100.0% |
| `usgs-conus-soil` | uniform_full_profile | 58284 | 108 | 100.0% | 100.0% |
| `zenodo-yangtze-yellow-river-sediment` | uniform_full_profile | 558 | 48 | 100.0% | 0.0% |

## 当前阻塞

1. 统一全量逐字段 profile 已完成 34/34；任何缺口仍显示 `not_measured`。
2. 候选来源审计与全量 adapter profile 分开保留，缺候选审计不再用 demo 补位。
3. 在线实时可用性仍需独立探测；固定缓存的 hash、schema、row-count 与离线重放已纳入 profile。

机器可读结果见 `assets/v4-source-completeness.json`。
