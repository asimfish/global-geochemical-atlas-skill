# 公开地球化学数据源路由

核对日期：2026-08-05。端点和许可可能变化；每次运行重新记录访问日期和实际响应。

## 优先级

按“官方结构化数据库 → DOI 数据仓储 → 论文补充材料 → 正文表格”的顺序选择。搜索摘要只用于发现来源。

| 来源 | 适合介质 | 入口 | 使用条件与限制 |
|---|---|---|---|
| USGS National Geochemical Database | rock/soil/sediment/mineral/concentrate | `https://www.usgs.gov/centers/gggsc/science/national-geochemical-database` | 政府来源；具体数据发布可能用不同 legacy qualifier 编码，逐数据集读取元数据 |
| EarthChem Portal | rock 与文献汇编 | `https://earthchem.org/portal` | 联邦检索 PetDB、GEOROC 等；保留原数据库、样品和文献引用；不要把聚合站当唯一证据 |
| EarthChem developer resources | 结构化服务 | `https://earthchem.org/resources/developers` | 使用文档化 WFS/XML；验证 schema、计数和服务版本 |
| GEMStat open archive | water | `https://doi.org/10.5281/zenodo.13881899` | 只使用明确开放批次；通常 CC BY 4.0，并按数据提供者要求署名；大文件先按范围设计本地过滤 |
| GEMStat portal | water | `https://gemstat.org/data-gemstat/data-portal/` | 门户下载可能要求联系信息或限制站点数；不要自动绕过表单；受限批次不再分发 |
| Macrostrat | 地质背景 | `https://macrostrat.org/` | 数据通常 CC BY 4.0；同时引用 API 返回的原始地图来源和 source ID；记录比例尺与边界不确定性 |
| Macrostrat API docs | 点位地质匹配 | `https://dev.macrostrat.org/docs` | API 版本快速演进；固定实际路由和响应字段，不凭记忆构造端点 |

## 来源选择门

1. 先判断介质、区域、元素、时间和 measurement basis。
2. 优先能服务端按区域/元素过滤、提供方法和来源定位的结构化发布。
3. 检查许可是否允许当前用途和再分发；`open_only` 下排除 limited/restricted 原始数据。
4. 同一记录经聚合平台转载时，保留聚合来源和原始提供者两层定位。
5. 数据版本或字段字典缺失时标记 `needs_human_review`，不要猜 qualifier。

## 下载验证

- 只下载明确的数据文件 URL，不把 HTML 搜索结果保存成 CSV。
- 要求 HTTPS、超时、有限重试、最大字节、内容类型和响应形状检查。
- 优先使用发布方给出的 SHA-256；否则首次下载计算哈希并在 manifest 标为 `observed`，不能冒充发布方校验和。
- 压缩包先检查成员路径、总展开大小和成员数，避免路径穿越和压缩炸弹。
- 下载后记录服务端过滤、本地过滤、预期记录数、实际记录数和任何截断。

## 许可边界

MIT 只覆盖本仓库原创代码和文档，不覆盖外部数据。对许可不明、仅限研究或禁止再分发的数据，只保存公开元数据与检索说明；不得打包原始记录。
