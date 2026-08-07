# V4 全量字段与覆盖立方体报告

> 本报告由固定缓存全量解析生成；不使用 demo 行数替代全量分母，也不把空间格网插值成观测。

## 总览

- 全量 profile 来源：26/26
- 目标元素测定：4,096,615
- 不同样品（逐来源去重后相加）：773,445
- 有效坐标样品：768,525
- 可比较测定：434,661
- 来源内 1° 观测格网数之和：8,130
- 覆盖立方体行：13,052

## 介质平衡

| 介质 | 测定 | 样品 | 独立血缘 | 坐标样品 | 可比较测定 | 1°格网 |
|---|---:|---:|---:|---:|---:|---:|
| rock | 68,618 | 26,203 | 2 | 21,409 | 1,271 | 420 |
| sediment | 89,825 | 14,036 | 8 | 14,036 | 31,458 | 1,317 |
| soil | 153,973 | 23,946 | 7 | 23,820 | 94,869 | 1,852 |
| water | 3,784,199 | 709,260 | 5 | 709,260 | 307,063 | 2,442 |

## 分来源

| 来源 | 介质 | 测定 | 样品 | 坐标样品 | 可比较测定 | 1°格网 | 方法完整率 |
|---|---|---:|---:|---:|---:|---:|---:|
| `afsis-phase-i-wet-chemistry` | soil | 12,012 | 2,002 | 1,876 | 11,256 | 53 | 100.0% |
| `australia-ngsa-mercury` | sediment | 2,396 | 2,396 | 2,396 | 2,396 | 545 | 100.0% |
| `brazil-sgb-florianopolis-soil` | soil | 192 | 32 | 32 | 128 | 1 | 100.0% |
| `brazil-sgb-florianopolis-stream-sediment` | sediment | 3,132 | 521 | 521 | 2,032 | 2 | 100.0% |
| `cdogs-210102-lake-sediment` | sediment | 4,411 | 684 | 684 | 4,190 | 2 | 100.0% |
| `cdogs-210102-lake-water` | water | 655 | 655 | 655 | 547 | 2 | 100.0% |
| `foregs-floodplain-sediment` | sediment | 9,672 | 749 | 749 | 8,976 | 466 | 100.0% |
| `foregs-humus` | soil | 1,845 | 388 | 388 | 1,845 | 277 | 100.0% |
| `foregs-stream-sediment` | sediment | 11,030 | 852 | 852 | 10,182 | 509 | 100.0% |
| `foregs-stream-water` | water | 4,848 | 808 | 808 | 4,848 | 489 | 100.0% |
| `foregs-subsoil` | soil | 10,201 | 794 | 794 | 10,201 | 484 | 100.0% |
| `foregs-topsoil` | soil | 10,908 | 862 | 862 | 10,908 | 500 | 100.0% |
| `gemas-europe` | soil | 53,703 | 4,131 | 4,131 | 53,703 | 829 | 100.0% |
| `gemstat-open-archive` | water | 3,739,180 | 689,291 | 689,291 | 279,225 | 1,153 | 7.5% |
| `georoc-antarctica-intraplate` | rock | 1,183 | 313 | 312 | 0 | 18 | 0.0% |
| `georoc-archaean` | rock | 65,988 | 25,659 | 20,866 | 0 | 395 | 0.0% |
| `geotraces-idp2025` | water | 39,327 | 18,317 | 18,317 | 22,254 | 1,166 | 56.6% |
| `japan-gsj-geochemical-map` | sediment | 21,168 | 3,023 | 3,023 | 0 | 79 | 0.0% |
| `japan-gsj-marine-sediment` | sediment | 34,334 | 4,905 | 4,905 | 0 | 108 | 0.0% |
| `norway-marchem` | sediment | 3,520 | 880 | 880 | 3,520 | 76 | 100.0% |
| `pangaea-arabian-sea-sediment` | sediment | 162 | 26 | 26 | 162 | 10 | 100.0% |
| `pangaea-north-africa-soil` | soil | 258 | 43 | 43 | 258 | 32 | 100.0% |
| `tpdc-china-mountain-soil` | soil | 6,570 | 1,314 | 1,314 | 6,570 | 42 | 100.0% |
| `us-wqp-sacramento-river-arsenic` | water | 189 | 189 | 189 | 189 | 1 | 100.0% |
| `usgs-conus-soil` | soil | 58,284 | 14,380 | 14,380 | 0 | 884 | 0.0% |
| `usgs-utah-volcanic-whole-rock` | rock | 1,447 | 231 | 231 | 1,271 | 7 | 87.8% |

## 解释边界

- `comparable_observation_count` 要求数值、单位、样品类型、坐标、measurement basis、方法与 method scope 同时存在。
- 不同来源的样品 ID 不跨来源合并，因此总样品数是逐来源去重后的加总。
- 1°格网仅表示有实测点；它不表示格网内每个位置都被测量。
- MarChem 当前外层 ZIP 与注册快照不同，但数据表和方法表逐字节相同；该非科学成员漂移在自动化健康文件中单独记录。

机器可读结果位于 `assets/v4-full-profiles/` 和 `assets/v4-coverage-cube.csv`。
