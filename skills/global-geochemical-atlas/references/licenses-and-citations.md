# 数据许可与引用说明

核对日期：2026-08-05。机器可读详情以 `../assets/source_manifest.json` 为准。

## 仓库原创内容

仓库中的原创代码和文档使用根目录 `LICENSE` 声明的 MIT License。MIT License 不覆盖第三方数据、第三方文献、图片、商标或来源网站内容。

## GEOROC Archaean Cratons

- 标题：GEOROC Compilation: Archaean Cratons；
- 作者/发布者：DIGIS Team, Göttingen University；
- DOI：<https://doi.org/10.25625/1KRR1P>；
- 冻结版本：12.0；
- 许可：[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)；
- 建议引用：DIGIS Team (2026). *GEOROC Compilation: Archaean Cratons*, Version 12.0. GRO.data. <https://doi.org/10.25625/1KRR1P>。

使用和再分发要求：

1. 保留数据集 DOI、版本、下载日期和查询/筛选条件；
2. 保留每条记录的成员文件和 `CITATIONS` 来源定位；
3. 说明使用的是 GEOROC 预编译选择值，而不是所有重复测量；
4. 再分发衍生数据时遵守 Attribution 与 ShareAlike 条款；
5. 完整第三方数据和本地缓存不提交到本仓库。

## USGS Data Series 801

- 标题：Geochemical and mineralogical data for soils of the conterminous United States；
- 作者：David B. Smith, William F. Cannon, Laurel G. Woodruff, Federico Solano, James E. Kilburn, David L. Fey；
- 发布者：U.S. Geological Survey；
- DOI：<https://doi.org/10.3133/ds801>；
- 数据系列：801，2013；
- 权利状态：USGS 制作的数据和信息属于美国公有领域；USGS 仍要求适当署名。参见 [USGS Copyrights and Credits](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)。
- 建议引用：Smith, D.B., Cannon, W.F., Woodruff, L.G., Solano, F., Kilburn, J.E., and Fey, D.L. (2013). *Geochemical and mineralogical data for soils of the conterminous United States*. U.S. Geological Survey Data Series 801. <https://doi.org/10.3133/ds801>。

使用要求：

1. 保留数据系列、DOI 和建议引用；
2. 保留土层类型、站点 ID、原始字段和原始单位；
3. 使用前阅读采样、分析、QA/QC 和 legacy qualifier 元数据；
4. 不把 USGS 名称、标识或商标当作项目背书；
5. 如文件中含第三方受版权保护材料，按对应标记单独处理。

## Demo 与 fixture

- 仓库现有 `fixtures/demo_input.csv` 是合成数据，声明为 `CC0-1.0`；
- 后续真实来源 demo 必须从允许本次科研使用的来源确定性生成，并记录生成脚本、DOI/PID、输入版本、文件 ID/名称、字节数、schema、行数和筛选步骤；
- fixture 输出必须标明仅用于流水线演示，不得用于科学解释；
- 不兼容许可的数据不合并发布为一个统一开放数据包。

## Natural Earth 离线底图

- 标题：Natural Earth 1:110m Land；
- 冻结版本：4.1.0；
- 来源：<https://www.naturalearthdata.com/downloads/110m-physical-vectors/>；
- 使用条款：Natural Earth 数据为 public domain；
- 源 ZIP SHA-256：`1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de`；
- 仓库资产：`../assets/natural-earth-110m-land.json`，128 个 polygon rings、5,133 个点，坐标四舍五入到 4 位小数。

该底图只提供地图上下文，不参与地质单元匹配、异常推断或覆盖完整性判断。页面显示来源、比例尺、
许可和 WGS84 语义；构建器在嵌入前验证资产版本、许可、坐标范围和点数安全上限。

## Natural Earth 离线国家边界

- 标题：Natural Earth 1:110m Admin 0 Countries；
- 冻结版本：5.1.1；
- 官方说明页：<https://www.naturalearthdata.com/downloads/110m-cultural-vectors/110m-admin-0-countries/>；
- 固定上游提交：`ca96624a56bd078437bca8184e78163e5039ad19`；
- 固定 GeoJSON SHA-256（1:110m Admin-0 Countries）：`6866c877d39cba9c357620878839b336d569f8c662d3cfab4cb1dbe2d39c977f`；
- 固定 GeoJSON SHA-256（1:10m Admin-0 Disputed Areas，同一提交）：`9cafef8b7dfb6b164dc58f218f981f4ace9f716f6c03795d4c62d1ac9f3d50f5`；
- 固定 GeoJSON SHA-256（1:50m Admin-0 Countries，同一提交）：`3e458fc036ad0a66411f2c1e6cac49c5d7bfb81cb1123bc513b22511a2b7fdeb`；
- 使用条款：Natural Earth 数据为 public domain；
- 仓库资产：`../assets/natural-earth-110m-admin0.json`（asset_version `ai4s-natural-earth-admin0-v2`），177 个国家 feature、11,523 个坐标点；
- 生成工具：`../scripts/prepare_country_boundaries.py` 只接受上述固定 hash，并将坐标四舍五入到 4 位小数。

v2 资产在 Natural Earth 底图上应用了三处固定的中国分析单元修正（记录在资产的
`analysis_modifications` 字段）：CHN 并入取自 1:10m Disputed Areas「Arunachal Pradesh」要素的
藏南多边形；IND 以内部排除环剔除同一多边形，避免争议区双重归属；TWN 以 1:50m 几何替换 9 点
1:110m 轮廓（粗轮廓曾把高雄等陆上点误判在界外）。上述修正与自然资源部标准地图
GS(2023)2767 号口径对齐，仅用于科学点位准入与参考线绘制，不构成独立的法定边界主张。

该资产用于绘制 Admin‑0 国家线，并让 `china`、`usa`、`usa48`、`australia` 预设执行国家多边形与
bbox 联合点内判定；`china` 预设按 CHN+TWN 科学分析单元联合判定。Natural Earth 默认表达 de facto
制图边界；它只用于定位和数据范围裁剪，不构成法定边界、外交立场、地质单元或异常范围声明。
`shanghai`、`europe` 与自定义范围仍是显式 bbox。

## Natural Earth Admin-1 搜索地名录

- 标题：Natural Earth 1:50m Admin 1 – States, Provinces；
- 版本：5.1.1；
- 固定上游提交：`ca96624a56bd078437bca8184e78163e5039ad19`；
- 固定 GeoJSON SHA-256：`69a0e06e640b2d505858ae1cb63034e4677f3000b35a98e16312932b98c426b9`；
- 使用条款：Natural Earth 数据为 public domain；
- 仓库资产：`../assets/natural-earth-50m-admin1-search.json`，294 个通用 Admin-1 条目，其中中国 31 个；
- 生成工具：`../scripts/prepare_admin1_search_gazetteer.py` 只接受上述固定 hash。

这个紧凑资产只把空间缺口翻译成可搜索的地名提示，例如 Xinjiang 或 Tibet。其概化 bbox 不参与点在多边形、国家归属、数据覆盖或科学充分性判定，也不构成法定边界声明。
