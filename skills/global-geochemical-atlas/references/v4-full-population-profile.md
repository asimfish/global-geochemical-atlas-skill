# V4 全量字段与覆盖立方体报告

> 本报告由固定缓存全量解析生成；来源报告坐标与 canonical EPSG:4326 坐标分开统计，不使用 demo 行数替代全量分母。

## 总览

- 全量 profile 来源：34/34
- 目标元素测定：4,294,213
- 不同样品（逐来源去重后相加）：861,738
- 来源报告坐标样品：843,125
- canonical EPSG:4326 坐标样品：737,757
- 可比较测定：424,267
- 来源内 canonical 1° 观测格网数之和：8,169
- 覆盖立方体行：26,163

## 介质平衡

| 介质 | 测定 | 样品 | 独立血缘 | 来源坐标样品 | canonical 坐标样品 | 可比较测定 | canonical 1°格网 |
|---|---:|---:|---:|---:|---:|---:|---:|
| rock | 244,463 | 104,878 | 2 | 86,484 | 0 | 0 | 0 |
| sediment | 100,013 | 16,556 | 11 | 16,463 | 7,668 | 36,340 | 1,260 |
| soil | 166,193 | 31,699 | 12 | 31,573 | 21,673 | 81,600 | 1,869 |
| water | 3,783,544 | 708,605 | 4 | 708,605 | 708,416 | 306,327 | 2,440 |

## 分来源

| 来源 | 介质 | 测定 | 样品 | 来源坐标样品 | canonical 坐标样品 | 可比较测定 | canonical 1°格网 | 方法完整率 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `4tu-northern-china-sediment` | sediment | 6,069 | 867 | 867 | 0 | 0 | 0 | 85.7% |
| `afsis-phase-i-wet-chemistry` | soil | 12,012 | 2,002 | 1,876 | 0 | 0 | 0 | 100.0% |
| `australia-ngsa` | sediment | 10,492 | 2,623 | 2,623 | 2,623 | 10,492 | 551 | 100.0% |
| `australia-ngsa-mercury` | sediment | 2,396 | 2,396 | 2,396 | 2,396 | 2,396 | 545 | 100.0% |
| `earthchem-dehailonggang-rock` | rock | 75 | 15 | 15 | 0 | 0 | 0 | 100.0% |
| `eidc-ningbo-soil` | soil | 480 | 80 | 80 | 0 | 0 | 0 | 100.0% |
| `figshare-yangtze-basin-soil-heavy-metals` | soil | 6,625 | 6,625 | 6,625 | 0 | 0 | 0 | 0.0% |
| `foregs-floodplain-sediment` | sediment | 9,672 | 749 | 749 | 749 | 8,976 | 466 | 100.0% |
| `foregs-humus` | soil | 1,845 | 388 | 388 | 388 | 1,845 | 277 | 100.0% |
| `foregs-stream-sediment` | sediment | 11,030 | 852 | 852 | 852 | 10,182 | 509 | 100.0% |
| `foregs-stream-water` | water | 4,848 | 808 | 808 | 808 | 4,848 | 489 | 100.0% |
| `foregs-subsoil` | soil | 10,201 | 794 | 794 | 794 | 10,201 | 484 | 100.0% |
| `foregs-topsoil` | soil | 10,908 | 862 | 862 | 862 | 10,908 | 500 | 100.0% |
| `gemas-europe` | soil | 53,703 | 4,131 | 4,131 | 4,131 | 53,703 | 829 | 100.0% |
| `gemstat-open-archive` | water | 3,739,180 | 689,291 | 689,291 | 689,291 | 279,225 | 1,153 | 7.5% |
| `georoc-antarctica-intraplate` | rock | 1,183 | 313 | 312 | 0 | 0 | 0 | 0.0% |
| `georoc-archaean` | rock | 65,988 | 25,659 | 20,866 | 0 | 0 | 0 | 0.0% |
| `georoc-convergent-margins` | rock | 177,217 | 78,891 | 65,291 | 0 | 0 | 0 | 0.0% |
| `geotraces-idp2025` | water | 39,327 | 18,317 | 18,317 | 18,317 | 22,254 | 1,166 | 56.6% |
| `japan-gsj-geochemical-map` | sediment | 21,168 | 3,023 | 3,023 | 0 | 0 | 0 | 0.0% |
| `japan-gsj-marine-sediment` | sediment | 34,334 | 4,905 | 4,905 | 0 | 0 | 0 | 0.0% |
| `norway-marchem` | sediment | 3,520 | 880 | 880 | 880 | 3,520 | 76 | 100.0% |
| `pangaea-amazonas-soil` | soil | 1,181 | 174 | 174 | 174 | 1,181 | 11 | 100.0% |
| `pangaea-arabian-sea-sediment` | sediment | 162 | 26 | 26 | 26 | 162 | 10 | 100.0% |
| `pangaea-barents-c-horizon-soil` | soil | 2,419 | 605 | 605 | 605 | 2,419 | 56 | 100.0% |
| `pangaea-batagay-soil` | soil | 93 | 31 | 31 | 31 | 93 | 1 | 100.0% |
| `pangaea-brasol-ne-brazil-soil` | soil | 1,614 | 270 | 270 | 265 | 992 | 73 | 100.0% |
| `pangaea-east-china-sea-clay` | sediment | 392 | 98 | 98 | 98 | 392 | 17 | 100.0% |
| `pangaea-north-africa-soil` | soil | 258 | 43 | 43 | 43 | 258 | 32 | 100.0% |
| `pangaea-south-china-sea-sediment` | sediment | 220 | 44 | 44 | 44 | 220 | 40 | 100.0% |
| `tpdc-china-mountain-soil` | soil | 6,570 | 1,314 | 1,314 | 0 | 0 | 0 | 100.0% |
| `us-wqp-sacramento-river-arsenic` | water | 189 | 189 | 189 | 0 | 0 | 0 | 100.0% |
| `usgs-conus-soil` | soil | 58,284 | 14,380 | 14,380 | 14,380 | 0 | 884 | 0.0% |
| `zenodo-yangtze-yellow-river-sediment` | sediment | 558 | 93 | 0 | 0 | 0 | 0 | 0.0% |

## 解释边界

- 来源坐标只证明数值完整且在经纬度范围内；datum/CRS 未证实时不会进入 canonical 地图。
- `comparable_observation_count` 要求数值、单位、样品类型、canonical 坐标、measurement basis、方法与 method scope 同时存在。
- 不同来源的样品 ID 不跨来源合并；1°格网只表示有实测点，不表示连续覆盖。
- MarChem 外层 ZIP 漂移但数据表和方法表 hash 一致；该边界在自动化健康文件中单列。

机器可读结果位于 `assets/v4-full-profiles/` 和 `assets/v4-coverage-cube.csv`。
