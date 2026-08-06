# 扩展全球真实数据基准

这一目录为稳定的 19,455 条核心全球基准追加中国、非洲、欧洲小国、日本与北非真实数据。它用于检验 D2 在更多来源格式、单位、分析方法、坐标系和小国样本下是否仍然可靠；它不是完整的全球元素总体，也不能用于直接发布科学结论。

## 已冻结数据

| 来源 | 区域与介质 | 离线选择 | 目标元素 | 关键边界 |
|---|---|---:|---|---|
| TPDC 中国山地土壤，DOI `10.11888/Terre.tpdc.302620` | 中国，土壤 | 1,314 个观察全部保留，6,570 个测定 | Cr、Cu、Ni、Pb、Zn | 30 个山地、O/A/C 层位，不是全国规则网格；数据条款与论文 CC BY 需分开 |
| AfSIS Phase I，DOI `10.34725/DVN/66BFOB` | 非洲 18 个源国家标签，土壤 | 每个国家×深度最多 40 个样品，小组全部保留；4,440 个测定 | As、Cr、Cu、Ni、Pb、Zn | 王水准全量；数值低于检出限不代表源数据提供了逐行删失符号 |
| FOREGS | 欧洲，土壤/沉积物/水 | 每个国家×介质最多 12 个站点，小国不足 12 个全部保留；9,613 个测定 | As、Cr、Cu、Hg、Ni、Pb、Zn（视介质可用） | 源文件已将低于检出限值替换为 DL/2，原始删失符号无法恢复 |
| GSJ 日本地球化学图 | 日本，河流沉积物 | 按样品编号与重复出现次序均匀选择 600 个样品；4,200 个测定 | 全部七元素 | Hg 为 ppb，其余为 ppm；源 CSV 未逐行重复分析方法 |
| PANGAEA 北非土壤，DOI `10.1594/PANGAEA.949903` | 撒哈拉—萨赫勒，细粒土壤 | Table S5 的 43 个样品全部保留；258 个测定 | As、Cr、Cu、Ni、Pb、Zn | 面向粉尘来源的 `<20 µm` 细粒组分，不是农业土壤基线；边界样品不强制归国 |

新增冻结文件共 18 个、7,671,723 bytes；与核心基准合计 29 个文件、9,827,618 bytes，远低于 250 MB 限制。所有文件和使用到的 ZIP 成员均由 SHA-256、字节数与证据关键词共同校验。

## 选择规则

- 抽样从不读取目标元素浓度，因此不会为了让地图“更亮”而挑高值。
- 小国或稀疏组低于上限时全部保留。
- GSJ 的重复编号 `78013` 按官方文件中的出现次序配对，不静默去重。
- FOREGS 的 `-1/-1.0` 缺失哨兵转成显式缺失；DL/2 上游替换事实保存在每一行的来源限定信息中。
- 只在 PANGAEA `Location` 明确时映射国家；跨境位置保持国家为空。

## 离线校验与在线刷新

仅校验仓库内冻结文件，不访问网络：

```bash
python3 evaluation/d2-validation/scripts/build_expanded_fixtures.py --offline
```

从官方端点重新下载，并要求内容仍与冻结契约完全一致：

```bash
python3 evaluation/d2-validation/scripts/build_expanded_fixtures.py --refresh
```

如果官方文件发生变化，`--refresh` 会因字节数或 SHA-256 不一致而失败，不会悄悄接受新版本。更新数据版本时需要人工审查方法、许可、字段和科学边界，然后显式更新 `contracts/expanded-sources.json`。

## 运行完整扩展评测

测试团队 D2 基线：

```bash
make d2-test-global-expanded OUTPUT=/tmp/d2-expanded
```

测试另一个 Agent 开发的 D2：

```bash
make d2-test-global-expanded \
  OUTPUT=/tmp/candidate-expanded \
  D2_SCRIPT=/absolute/path/to/candidate.py \
  CANDIDATE_LABEL=my-d2
```

候选脚本必须实现：

```bash
python candidate.py --input INPUT.csv --output-dir NEW_OUTPUT_DIR
```

评测完成后重点查看：

- `global_data_report.json`：阻断检查、评审发现、各来源/洲/介质统计；
- `d2/geochemistry.csv`：标准化地球化学数据库；
- `d3/atlas.html`：完全离线的可交互元素分布地图；
- `d3/source_confidence.json`：来源、证据链、置信度与覆盖盲区；
- `d3/anomaly_regions.geojson` 与 `anomaly_region_report.json`：候选异常区域及可追溯记录。

当前基线结果位于 `evaluation/d2-validation/runs/expanded-latest/`：44,536 个输入测定、44,199 个可标准化值、44,510 个可映射记录、535 个候选异常点和 276 个异常网格，所有 45 个阻断检查通过。5 个 review finding 是主动暴露的覆盖/元数据不足，不应伪装为已经解决。

完整来源路由见 `contracts/global-source-catalog.json`；精确许可、哈希和科学限制见 `contracts/expanded-sources.json`。
