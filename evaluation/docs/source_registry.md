# 科学来源注册表

本文件登记用于设计金标准的外部权威依据。任务运行优先使用冻结的本地 fixture，避免把实时网页变化变成模型得分波动。

| Source ID | 作用 | 权威页面 | 核验日期 | 进入金标准的事实 |
|---|---|---|---|---|
| SRC-GEOROC | 岩石/矿物数据源适用性 | https://georoc.eu/georoc/precompiled/ | 2026-08-05 | 预编译文件包含坐标、分析方法、实验室、标准物质和原始来源等元数据 |
| SRC-EARTHCHEM | 联合发现与数据服务 | https://earthchem.org/about/about-overview | 2026-08-05 | Portal 联合访问 PetDB、GEOROC、USGS NGDB；ECL 支持 DOI 数据保存 |
| SRC-USGS-NGDB | 美国岩石/沉积物/土壤等 | https://www.usgs.gov/centers/gggsc/science/national-geochemical-database | 2026-08-05 | NGDB 覆盖美国及领地的岩石、沉积物、土壤、矿物等地球化学记录 |
| SRC-USGS-2026 | 版本化综合数据发布 | https://www.usgs.gov/data/geochemical-data-rock-sediment-soil-and-mineral-samples-united-states-and-territories-1962 | 2026-08-05 | 数据发布 DOI 为 10.5066/P1FXE9GK，覆盖 1962–2023 年的岩石、沉积物、土壤和矿物样品，官方页面标记 CC0 1.0 |
| SRC-GEMAS | 欧洲农业与草地土壤 | https://eurogeosurveys.org/projects/gemas/ | 2026-08-05 | GEMAS 是欧洲 33 国协调采样的农业土和草地土数据，不适合替代美国土壤主数据 |
| SRC-WOSIS | 全球土壤剖面背景 | https://docs.isric.org/globaldata/wosis/faq-wosis.html | 2026-08-05 | WoSIS 提供质量评估、标准化的世界土壤剖面数据，分析方法信息取决于源元数据 |
| SRC-USGS-QUAL | 限定符与检测限语义 | https://pubs.usgs.gov/of/2002/of02-403/HTMLdocs/enterdat.htm | 2026-08-05 | 未检出/低于检测限、未分析和数值字段应分开记录，检测限进入独立字段 |
| SRC-USGS-QC | 地球化学 QA/QC | https://www.usgs.gov/publications/quality-assurance-and-quality-control-geochemical-data-a-primer-research-scientist | 2026-08-05 | QA/QC 贯穿研究设计、采样和实验室/数据生命周期，不能由“来源可靠”替代 |
| SRC-NIST-FE2O3 | Fe2O3 摩尔质量 | https://webbook.nist.gov/cgi/cbook.cgi?ID=B6004683 | 2026-08-05 | Fe2O3 分子式与相对分子质量 159.688；任务固定原子量后复算 Fe 质量分数 |
| SRC-RFC7946 | GeoJSON 坐标与 CRS | https://www.rfc-editor.org/info/rfc7946/ | 2026-08-05 | Position 前两项为 longitude、latitude；GeoJSON 使用 WGS84 十进制度 |

## 使用边界

- 来源页面只证明数据源范围或格式规范，不证明某个参赛输出中的具体数值正确。
- 真实来源目录题使用冻结元数据快照；若官网更新，先建立新 benchmark 版本，不能静默改变旧 gold。
- 合成 fixture 的数值不引用这些数据库，也不宣称代表真实地区分布。
