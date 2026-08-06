# 全球真实数据冻结切片

本目录为 D2 内部评测提供七洲联合覆盖、四类介质和七种元素的真实公开数据。它是值无关、可追溯的
小型测试切片，不是“全球所有地球化学数据”，也不用于推断全球总体分布。

## 数据组成

| 来源 | 介质 | 冻结范围 | 地理用途 | 许可 |
|---|---|---:|---|---|
| GEOROC Archaean Cratons + Antarctica Intraplate | 岩石 | 2,017 个样品行，展开 7,951 条测定 | 七洲岩石联合覆盖 | CC BY-SA 4.0 |
| GEMAS Europe，农业土壤 Aqua Regia layer | 土壤 | 2,113 点，展开 8,452 条测定 | 欧洲统一采样土壤 | CC BY 4.0 |
| Geoscience Australia NGSA Hg | 沉积物 | 2,396 条测定 | 澳洲大陆出口沉积物 | CC BY 4.0 Australia |
| UNEP GEMStat v3 开放档案 | 水体 | 656 条测定、35 国 | 亚、欧、北美、南美水质 | CC BY 4.0 |

总计 19,455 条 D1 测定，元素为 As、Cr、Cu、Hg、Ni、Pb、Zn。

## 冻结与选择规则

- GEOROC：每个命名区域先保留坐标有效且至少有一个目标元素的记录；按 `UNIQUE_ID` 排序后等距抽取
  最多 80 个样品。抽样不读取浓度大小。
- GEMAS：保留固定 ArcGIS layer 3 查询返回的全部 2,113 个农业土壤点；四个 Aqua Regia 字段全部展开，
  缺值仍进入 D2 并标记。
- NGSA：保留官方 CSV 全部 2,396 条记录，包括 TOS、BOS 和来源声明的重复样。
- GEMStat：每站每元素选择最早的受支持水相单位结果，再按国家和站号等距抽取最多 5 站；选择不读取
  浓度大小。`<`、`>` 限定符原样保留。

完整构建算法、父文件 PID、成员哈希和选择参数见 `fixtures/raw/source_manifest.json`；固定资源哈希、
许可和科学限制见 `../contracts/global-sources.json`。

## 真实覆盖边界

“全球”在这里指七洲联合覆盖和四类介质联合覆盖，不是 28 个洲—介质单元全部有数据：

- 非洲：当前只有 GEOROC 岩石；
- 南极洲：只有文献汇编岩石；
- 大洋洲：岩石和澳洲沉积物；
- 水体：开放 GEMStat 目标元素切片只有亚洲、欧洲、北美洲和南美洲；
- 土壤：当前冻结的是 GEMAS 欧洲农业土壤；
- 任何来源都不能代表全球总体抽样密度。

地图和 `source_confidence.json` 必须展示这些空洞，禁止把“七洲至少一点”写成“全球完整覆盖”。

## 上游官方入口

- GEOROC Archaean Cratons: <https://doi.org/10.25625/1KRR1P>
- GEOROC Intraplate Volcanics: <https://doi.org/10.25625/RZZ9VM>
- GEMAS open-data catalog: <https://data.gov.ie/dataset/0c6c5bbc-20a7-4011-8585-7befb511a4b4>
- NGSA Mercury: <https://doi.org/10.26186/150328>
- GEMStat v3: <https://doi.org/10.5281/zenodo.18459694>

## 离线校验

```bash
python3 evaluation/d2-validation/scripts/build_global_fixtures.py --offline
```

该命令只读本地文件，验证 11 个资源的字节数、SHA-256 和必要标记。正常评测不下载 201 MB 的
GEMStat 父档案。重新生成流程只供基准维护者使用，见
`../GLOBAL_BENCHMARK_FOR_AGENTS.md`。
