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
