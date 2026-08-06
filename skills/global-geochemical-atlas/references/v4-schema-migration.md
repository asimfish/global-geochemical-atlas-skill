# V4 schema v2 迁移说明

版本：`d1-v4-schema-migration-v1`

## 兼容边界

- V3 的 27 列交换 CSV 仍可由 `standardize_geochemistry.py` 读取；新增 V4 列缺失时输出为空，不自动推断。
- 新生成的交换 CSV 使用 `generate_demo_data.INPUT_COLUMNS`，包含旧列和全部可选 V4 列。
- 归档 bundle v1 仍可校验、建索引和查询；bundle v2 将 sample 与 analytical method 升级到 v2 实体。
- `geologic_unit` 仅为旧版兼容列。迁移器不会把它复制到 `geologic_unit_raw`，也不会把 `survey_area`、`map_sheet` 或 `cruise_track` 当作地质单元。

## 证据语义

| 类别 | V4 字段 | 要求 |
|---|---|---|
| 样品 | `sample_type_raw`, `sample_type`, `sample_type_mapping_status` | 原词、规范词和映射证据同时保存；不能从元素、单位或方法推断 |
| 分层/分相 | `soil_horizon`, `sediment_environment`, `water_body_type`, `water_fraction`, `filtered_state` | 不同值默认进入不同异常背景组 |
| 地理 | `geographic_context_raw`, `survey_area`, `map_sheet`, `cruise_track` | 仅表示位置或调查范围 |
| 来源地质 | `geologic_unit_raw`, `lithology_raw`, `geologic_age_raw`, `tectonic_setting_raw` | 只保存来源明确报告的内容 |
| 匹配地质 | `matched_geologic_unit`, map/version/method/scale/uncertainty | 空间匹配不能覆盖来源字段；没有地图证据时为空 |
| 方法 | `method_scope`, `method_assignment_basis`, preparation/technique/instrument | 数据集级方法必须明确写 `dataset`，不能冒充逐记录事实 |
| 文献 | DOI/引用 + `citation_scope` + assignment basis | 数据集 DOI、方法论文和测定级引用不合并为同一 scope |
| 使用条件 | access/research/license/redistribution 分列 | 是否可访问、是否可科研使用和是否可再分发分别记录 |

## 工具链

```bash
python3 scripts/validate_acquisition.py --bundle fixtures/schema-v2/archive-bundle.json
python3 scripts/export_archive_exchange.py \
  --bundle fixtures/schema-v2/archive-bundle.json \
  --output /tmp/v4-exchange.csv
python3 scripts/standardize_geochemistry.py \
  --input /tmp/v4-exchange.csv \
  --output-dir /tmp/v4-output
python3 scripts/migrate_v4_source_demos.py --check
```

`export_archive_exchange.py` 先验证实体关系，再把 sample/method/geology/citation scope 写入交换层。标准化输出、SQLite `observation_search`、GeoJSON 和交互地图随后保留这些字段。

## 十四来源迁移状态

十四个生产来源的 source demo 已完成 V4-M2 回填，映射集中定义在 `v4_semantics.py`，生成器与迁移检查共用同一契约。旧 V3 输入仍可读取，但新生成的 source demo 必须带 `exchange_schema=d1-v4-exchange-v1` 和语义版本。

尚未完成的是全量来源统一逐字段 profile、四个来源的方法补齐和真正地质背景。demo 字段完整不代表 full population 完整。
