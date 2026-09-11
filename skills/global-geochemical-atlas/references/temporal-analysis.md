# 时序分析与异常成因归因（v20）

本文档定义 v20 引入的两个可复现契约。只用本 Skill 的脚本即可重建全部结论：不需要任何外部工具或人工判断。

## 1. 采样时间契约 `atlas-sampling-time-v1`

**语义铁律**：`sampling_time` 表示样品被物理采集的那一刻——即该时间点介质中的元素含量。论文发表年、数据库版本年、汇编年一律不算采样时间；只报告发表年的来源（如 GEOROC 文献汇编，其 ERUPTION YEAR 字段实测 0/34,939 全空）诚实记为 `publisher_not_reported`，受控原因 `publication_year_not_sampling_time`。

**为什么必须按来源声明格式解析**：已注册档案在同一列位置混用互相矛盾的写法——NGSA 是澳式 `D/M/YYYY`（`21/06/2009`），USGS CONUS 是美式 `MM/DD/YY`（`02/16/09`），BraSol 工作簿 396 行里 273 行是 `DD.MM.YY` 文本、123 行是 Excel 序列日期数（`39650` = 2008-07-21）。全局猜格式必然出错，因此每个来源在 `scripts/sampling_time.py` 的 `SOURCE_SAMPLING_TIME` 中声明原始字段与格式族；不符合声明格式的值降级为 `unparseable_raw_value`，原文保留在 `sampled_at`。

**标准数据库新增三列**（紧跟原始列 `sampled_at` 之后）：

| 列 | 含义 | 取值 |
|---|---|---|
| `sampling_time` | 归一化采样时刻（ISO-8601；年段写 `YYYY/YYYY`） | `2011-11-20T17:06:54`、`2008-07-21`、`2015`、`2009/2013` |
| `sampling_time_precision` | 精度 | second / minute / day / month / year / year_range |
| `sampling_time_status` | 状态 | publisher_reported / publisher_not_reported / unparseable_raw_value |

**逐源声明摘要**（37 个可执行来源全覆盖）：20 个来源带发布方采样时间（GEOTRACES 秒级、GEMStat 分钟级、us-wqp 秒级、USGS/NGSA/NGSA-Hg/BraSol/Amazonas/珠江补充表日级、MarChem 年级、AfSIS 年段；FOREGS 六源、GEMAS、宁波土壤与青藏中心山地土壤用发布方文档声明的**整份数据集采集时段**：FOREGS 五源 1997/2001、河流沉积物 1997/2004（瑞典补采）、GEMAS 2008/2009、宁波 `2016-03`、山地土壤 `2012/2013`）；GEOROC 三源、EarthChem、Gard 2019 全岩汇编与长江流域土壤重金属文献汇编只有发表年（或地质年龄 Ma），均不算采样时间，受控原因 `publication_year_not_sampling_time`；其余 12 源（含闽粤沿海地下水表、4TU 中国北方沉积物、两份 PANGAEA 表、长江黄河沉积物）在已注册档案与出版方元数据内均未见可提取采样时刻，受控原因 `no_extractable_sampling_time_in_registered_archive`。两位年份用固定轴心：00-49 归 2000 年代，50-99 归 1900 年代。

**数据集采集时段的证据门**：整份数据集的采样时段只能来自出版方自己的文档或结构化元数据，逐条登记在 `sampling_time.PUBLISHER_DOCUMENTED_SAMPLING_WINDOWS` 并在 `SOURCE_SAMPLING_TIME` 声明 `evidence` 链接：

| 来源 | 挂载值 | 精度 | 出版方证据 |
|---|---|---|---|
| `eidc-ningbo-soil` | `2016-03` | month | EIDC 数据集摘要 "Data was collected in March 2016"（DOI 10.5285/9c2e8b85-48ab-48c9-b69d-dd676a5d086f） |
| `tpdc-china-mountain-soil` | `2012/2013` | year_range | TPDC 结构化元数据 startTime 2012-07-01 / endTime 2013-03-31（DOI 10.11888/Terre.tpdc.302620） |
| `gemas-europe` | `2008/2009` | year_range | GEMAS 项目文档：2008 年与 2009 年初联合野外采样 |

被明确拒绝的情形：Figshare 长江流域土壤重金属数据集标题与摘要中的 "2000-2020" 是**被检索文献的发表年份**（"by searching peer-reviewed literatures published between 2000 and 2020"），不是采样期，因此保持无时间；4TU 中国北方沉积物的 README.pdf 与摘要只记录点位、深度与方法，不含野外年份；两份 PANGAEA 表的 Event 行没有 DATE/TIME；Mendeley 与 Zenodo 数据集描述均未声明采集时期。D1 适配器只对登记表内的来源写入 `sampled_at`，绝不为未登记的来源发明时段。

**时序查询口径**：同一站点的多时相序列用 `sample_id` 识别——GEMStat 的 `sample_id` 形如 `站号|时间|深度`（竖线分隔，前缀是站号）；其余来源用坐标圆整 0.01° 聚合。置信度说明 `sources_and_confidence.json` 新增 `sampling_time_coverage` 节（总体与逐源的时间覆盖、最早/最晚采样时刻）。

## 2. 异常成因归因契约 `anomaly-provenance-v1`

**回答的问题（大白话）**：对每个偏高的异常候选，判断这里的富集究竟是土壤或其他介质的**母质先天决定**的（比如西南地区土壤砷本底就高，按通用标准会判成假异常），还是**工业排放或其他人为原因后天造成**的。异常区域识别因此多了一系列类型的异常检测。

**四条证据线**（每条给通俗一句话结论）：

| 证据线 | 看什么 | 指向 |
|---|---|---|
| 岩性线 | 样本是否落在该元素天然高背景的岩类上（超基性岩之于 Ni/Cr/Co，黑色页岩之于 As/Mo） | 母质 |
| 空间线 | 同元素同介质的偏高点在约 1° 邻域内成片（地质格局）还是孤立（点源特征） | 两可 |
| 伴生线 | 同一样本上其它元素是否组合性偏高：Pb-Zn-Cd-Cu 等亲硫组合像污染指纹；Ni-Cr-Co-V 基性岩组合像母质信号 | 两可 |
| 时序线 | 同一点位 ≥3 次带采样时间的观测：浓度上升支持后天输入，平稳支持稳定背景（这里直接消费契约 1 的 `sampling_time`） | 两可 |

**判定规则（保守）**：至少两条证据线同向才归类；一边一线判混合；不足两线可用或仅单线支持一律「证据不足，暂不判定」。亏损（偏低）候选本版不做归因。判定绝不指认具体污染源——那需要同位素或排放清单证据，已注册来源不含。

**四类结论**：母质高背景型（地质成因）/ 疑似人为输入型 / 混合叠加型 / 证据不足暂不判定。

**产物**：`anomaly_provenance.json`（第十七个固定输出，`validate_outputs.py` 强制校验存在）。每条含 classification、中文标签、通俗解释、四条证据线的逐线结论。

## 3. 可复现命令

```bash
# 完整工作流（自动生成含三列时间字段的数据库、时间覆盖统计与成因归因报告）
python scripts/run_workflow.py --input INPUT.csv --evidence-jsonl SOURCES.jsonl \
  --acquisition-manifest MANIFEST.json --output-dir OUTPUT_DIR

# 单独重算成因归因
python scripts/classify_anomaly_provenance.py --database OUTPUT_DIR/geochemistry.csv \
  --anomalies OUTPUT_DIR/anomalies.geojson --output OUTPUT_DIR/anomaly_provenance.json
```

两个契约均由 `scripts/component_test.py` 钉死（37 源声明覆盖、逐格式族解析样例、combined fixture 的逐源时间分布与归因计数、判定规则白盒断言）。修改契约必须同步更新组件测试，否则门禁失败。
