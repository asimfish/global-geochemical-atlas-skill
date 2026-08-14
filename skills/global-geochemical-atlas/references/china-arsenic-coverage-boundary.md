# 中国 As 覆盖证据边界

核对日期：2026-08-12。此页记录一次实跑发现审计的可复用结论；它证明“当前没有获准进入 canonical 中国地图的 As 新来源”，不证明相关数据不存在。

## 本轮结论

- 冻结请求：China，As/Cu/Pb/Zn，soil + sediment；
- 修复队列：17 个空间/维度任务；每个任务都执行注册来源复查与定向发现；
- 定向检索：45 个唯一查询，覆盖国家调查、PANGAEA、EarthChem、Zenodo、Figshare、Mendeley Data 和出版物补充材料；
- 结果：发现 6 个有相关性的候选，但没有一个同时通过记录级数值、记录级坐标、坐标 CRS、许可和非聚合语义门禁；
- 因而交付应写 `delivered 3/4 canonical-map elements`，并把 As 标为精确的 coverage debt。不能删除 As 筛选项，也不能把其余三元素说成“已全面覆盖中国”。

## 候选处置

| 候选 | 证据 | 处置与原因 |
|---|---|---|
| Tarim River saline soils, `10.17632/chvygvfctx.1` | 141 样品；As/Cu/Pb/Zn；CC BY 4.0；原文件 SHA-256 `2e58fc537a83f26757d74287b4ab7be6df59f840fac5443bade54a41f4ff9423` | `not_admitted`：有 E/N 十进制度数，但文件和仓库元数据未声明 datum/CRS；只能 reported-only，不能填 canonical coverage。 |
| Northern East China Sea bottom sediment, `10.17632/ddhjgmcztt.6` | 187 样品；四元素；CC BY 4.0；SHA-256 `4ec35d44307bf2532e0b6928a80d5126b33e3a7cfcca0e2fec3c2039182c0f31` | `not_admitted`：经纬字段无 datum/CRS；R1–R5 是同一血缘版本，且只代表区域簇。 |
| Sanjiangyuan surface sediment, `10.17632/24nfj2vk3s.2` | 48 样品；四元素；CC BY 4.0；SHA-256 `6676e4098ef042787cb2671b0a95f037f15dd9a17204db1b05151bcc25792489` | `not_admitted`：表头顺序与数值范围疑似经纬交换，且 CRS 未声明；不得自动交换后冒充 canonical。 |
| Northeast China catchment source-tracing, `10.17632/ywx6xjm8nk.1` | 171 样品；soil/sediment；四元素；CC BY 4.0；SHA-256 `579b09dbe89d955d9f573fa2fcb2cc0a6e349c0ed63c0993d4f0032dada40398` | `not_admitted`：测定表没有逐样品坐标，论文只有流域级位置；不能生成样点。 |
| Four-river literature aggregation, `10.17632/kgf66z9bmf.1` | 四元素；CC BY 4.0；SHA-256 `51c0307d0d2063e1fccc4cdbe2dd97b93b241a1842fb16a71bb8298b064b641f` | `rejected`：河流/年份聚合值，无记录级坐标，不是一行一个物理样品。 |
| China soil As compilation, `10.6084/m9.figshare.25477366.v2` | As；CC BY 4.0；SHA-256 `057af5f3cbcb4b8d309fb765712658c66da282e9531482017616384f54f561d2` | `rejected`：省/市/区聚合编译，无样品经纬与逐样品来源链。 |

## 下一步规则

继续定向发现时优先寻找官方调查或 DOI 数据集，其文件必须同时具备样品 ID、As 数值与单位、逐样品坐标、明确 datum/CRS、方法或缺失原因、可复用许可和行级定位。仅缺 CRS 的候选可进入 reported-only 数据库，但不得计入 WGS84 空间充分性；补到可信发布方 CRS 证据后才新增 coordinate policy。不得猜测 WGS84、插值补点或用区域中心点替代样品位置。
