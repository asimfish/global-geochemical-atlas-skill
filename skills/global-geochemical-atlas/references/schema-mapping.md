# D1 来源字段与 D2 映射

版本：`d1-schema-mapping-v1`

## 共同映射

| D1 归档字段 | D1 → D2 长表 | D2 `geochemistry-record` | 规则 |
|---|---|---|---|
| `observation.observation_id` | `record_id` | `record_id` | 同一稳定 ID，只改交换字段名 |
| `sample.sample_id` | `sample_id` | `sample_id` | 原样传递 |
| `observation.analyte_reported` | `analyte_reported` | `element_or_analyte` | D1 保留原词；D2 保存原词后再映射 |
| `observation.value_raw` | `value_raw` | `original_value_raw` | 字符串原样传递，包括 `<`/`>`/`ND` |
| `observation.parsed_value` | `parsed_value` | `original_value` | 只允许可逆数值解析，不做单位换算 |
| `observation.value_qualifier` | `value_qualifier` | `value_qualifier` | 语义枚举一致 |
| `observation.unit_raw` | `unit_raw` | `original_unit` | 不覆盖原单位 |
| `observation.measurement_basis_raw` | `measurement_basis_raw` | `measurement_basis` | D2 决定标准词与可比性 |
| `sampling_event.location.*_raw` | `latitude_raw`, `longitude_raw`, `crs_raw` | `original_latitude_raw`, `original_longitude_raw`, `source_crs` | 原值与解析坐标同时提供 |
| `sampling_event.location.latitude/longitude` | `latitude`, `longitude` | `latitude`, `longitude` | 只有可复现转换成功时填写 |
| `analytical_method.*_raw` | 对应 `*_raw` 列 | `analytical_method`, `digestion_or_extraction`, `laboratory` | D2 决定规范化和方法门控 |
| `provenance.source_id` | `source_id` | `source_id` | 原样传递 |
| `provenance.source_locator` | `source_locator` | `source_locator` | 必须能定位原始记录 |
| `dataset_source.license_id` | `license_id` | `license` | 保留数据集/记录级许可 |

## GEOROC

来源字段名称可能随具体预编译集变化；适配器必须先冻结每个版本的 header。

| GEOROC 原字段 | D1 实体字段 | 说明 |
|---|---|---|
| `SAMPLE NAME` | `sample.native_sample_id` | 缺失时用来源记录定位生成稳定样品 ID |
| `MATERIAL` | `sample.material_raw`, `sample.medium_raw` 候选 | `WR` 等缩写保留原词；分类由映射表/D2 审阅 |
| `CITATIONS` | `publication.publication_id/citation` | 引用 ID 必须解析到下载内原始参考文献文本 |
| 纬度/经度相关列 | `sampling_event.location.*_raw` | 保留点或范围表达，不猜测中心点精度 |
| 元素列，例如 `NI(PPM)` | `observation.analyte_reported/value_raw/unit_raw` | header 拆分必须保留完整原列名和 ppm 原单位 |
| 方法、实验室、标准物质列 | `analytical_method.*_raw` | 缺失时记录 `not_reported` |
| 文件名 + 行号 | `provenance.source_file/source_row/source_locator` | DOI 文件 ID 同时进入 dataset file 证据 |

## USGS Data Series 801

| USGS 原字段 | D1 实体字段 | 说明 |
|---|---|---|
| `SiteID` | `sampling_event.site_id` | 三个土层可以共享 site，但样品必须区分 |
| `<Layer>LabID` | `sample.native_sample_id` | 优先于 SiteID 作为层级样品原始 ID |
| `Latitude`, `Longitude` | `sampling_event.location.latitude_raw/longitude_raw` | 单位行声明 Degrees；保留来源原值 |
| `Top5_*`, `A_*`, `C_*` | `observation.*` | header 前缀确定土层，单位从第二个 header 行读取 |
| 文件对应层 | `sample.soil_horizon_raw` | `top-0-5cm`, `a-horizon`, `c-horizon` 不合并 |
| qualifier 编码 | `observation.value_raw/value_qualifier` | 必须按 DS801 元数据解释，不凭通用规则猜测 |
| 文件名 + 行号 | `provenance.source_file/source_row/source_locator` | 每条 observation 继承记录级定位 |

## 不允许的映射

- D1 不把 ppm 无条件改写为 mg/kg 或 mg/L；
- D1 不把 `<5` 改写成普通数值 5；
- D1 不根据经纬值范围自动交换坐标；
- D1 不把缺失方法填成来源常见方法；
- D1 不把 EarthChem/GEOROC 等聚合来源当作原始论文的替代引用；
- D1 不把母样、粉末、切片和溶液子样压成同一个 sample。
