# D2 子模块四层测试方案

版本：`d2-validation-plan-v2`
被测接口：`d2-interface-v2`

## 1. 测试目标

验证 D2 是否同时满足四个条件：

1. **科学语义正确**：不混淆介质、单位、删失值、方法背景和异常含义。
2. **证据链不断裂**：原始表达、来源定位、转换公式、QC、参数和文件哈希可追溯。
3. **工程接口稳定**：D1 能传入，D3 能直接消费，E1 能自动核验，失败状态可机器识别。
4. **在比赛沙箱可完成**：标准库可运行、结果确定、无网络也能复现、资源使用有余量。

两套方案使用同一套严重级别：

| 级别 | 含义 | 对退出码的影响 |
|---|---|---|
| `blocking` | 违反版本契约、科学红线或使下游无法工作 | 任一失败即退出 1 |
| `review` | 合理性仍需 D1/D2/D3/E2 共同决策 | 记录 finding，退出仍为 0 |

## 2. 方案一：D2 独立全面测试

### 2.1 定位

这是白盒加契约测试，不依赖 D1 或 D3。测试器直接调用 D2 函数，并通过子进程调用真实 CLI。

### 2.2 测试矩阵

| 测试域 | 主要案例 | 核心判据 |
|---|---|---|
| 接口与版本 | 版本号、九项输出、`--help`、退出码、stdout | 输入错误为 2；成功只输出路径 JSON |
| 输入 Schema | 最低四列、异构列映射、空表、缺列、重复表头、非法映射 | 不猜列名；异常输入失败关闭 |
| 固体单位 | `mg/kg`、`ppm`、`ug/g`、`g/t`、`wt%`、`ppb`、`g/kg` 等 | 全部换算到 `mg/kg`，数值与因子一致 |
| 水体单位 | `ug/L`、`mg/L`、`ng/L`、`g/L` | 全部换算到 `ug/L` |
| 歧义单位 | 水体 `ppm/ppb/wt%`、固体裸 `%`、未知单位 | `normalized_value=null` 且有明确 error flag |
| 分析物和氧化物 | 元素别名、中文名、16 个白名单氧化物、错配、`Fe2O3T` | 白名单公式可审计；非白名单拒绝猜测 |
| 删失和缺失 | `<`、`<=`、`>`、`>=`、`ND`、`BDL`、`trace`、未分析 | 不插补为零；qualifier、limit、missing reason 分离 |
| 坐标和空间 | 合法边界、交换、残缺、零岛、区域 bbox、跨日期变更线、非 WGS84 | 不静默纠正；原坐标保留；无效 canonical 坐标为空 |
| 方法与来源 | 方法族推导、来源等级、许可/定位缺失、文件哈希 | 关键字段缺失降低可用性并有 flag |
| 置信度 | 五分量范围、单调性、error cap | 所有分量在 0–1；有 error 时 overall ≤ 0.59 |
| 重复和复测 | 完全重复、不同方法、相同样品但不同来源行 ID | 不丢记录；重复政策的盲区显式报告 |
| 异常门槛 | n=19/20、70% 边界、MAD=0、高/低异常、方法分组、非正值 | 不满足门槛不评分；只输出 candidate anomaly |
| 变形测试 | 等价单位、输入倒序、统一倍数缩放 | 语义结果保持不变，避免依赖偶然顺序或量纲 |
| 确定性与 manifest | 同输入运行两次、输出哈希 | 九个文件逐字节一致；manifest 哈希匹配 |
| 资源冒烟 | 默认 10,000 条合成记录 | 记录耗时和峰值内存；超预警线标记 review |

数据驱动用例在 [isolated-matrix.json](contracts/isolated-matrix.json)。

### 2.3 通过标准

- `blocking` 通过率必须为 100%。
- 不允许发生未捕获异常、Traceback、NaN/Infinity 输出或记录静默丢失。
- 确定性检查必须逐字节通过，不只比较记录数。
- 资源预警线为 10,000 条记录 30 秒、峰值 512 MB；它是团队预警，不是比赛硬限制。
- `review` 失败必须转成 D2 backlog，不能从报告中删除。

### 2.4 三次运行

合并前连续运行三次，比较：

- `blocking_failed` 是否始终为 0；
- 输出 SHA-256 是否一致；
- 资源耗时取中位数；
- finding 是否稳定出现。

## 3. 方案二：合成金标准 D1→D2→D3 全流程测试

### 3.1 定位

这是黑盒、消费者驱动测试。目的不是替代队友模块，而是回答：即使 D2 自己的单元测试通过，它的接口是否真的足以让上游接入、下游展示和证据回溯？

```text
仓库内 CC0 合成切片
        │
        ▼
极简 D1：异构列名 + schema-map + 来源 manifest
        │
        ▼
真实 D2 CLI：九项标准输出
        │
        ▼
极简 D3：契约检查 + 离线 Canvas 交互地图 + 四项产品验收
        │
        ▼
端到端报告：数值金标准 + 证据链 + D3 可消费性
```

### 3.2 极简 D1

D1 stub 不访问网络，只包装 `evaluation_lyf/reference_implementation/d2/fixtures/demo_input.csv`：

- 把列名改成来源风格，强制走 `--schema-map`；
- 补充 `source_record_id`、`source_file`、`source_row`、数据集标题和版本；
- 保存原始切片 SHA-256、导出 CSV SHA-256、许可和行数；
- 不标准化单位、不插补删失值、不删除重复记录。

这一步验证 D2 是否能接收“不是它自己命名”的真实上游格式。

### 3.3 真实 D2

通过子进程调用：

```bash
python3 evaluation_lyf/reference_implementation/d2/scripts/geochem_d2_pipeline.py \
  --input <d1-export.csv> \
  --schema-map <schema-map.json> \
  --output-dir <d2-output> \
  --min-group-size 8
```

Demo 显式使用 8 只是为了让 12 条 As 记录展示异常路径；报告必须同时确认生产默认仍为 20。

### 3.4 极简 D3

D3 stub 不重算 D2 科学结果。它只：

- 加载 `map_spec.json` 指定的文件；
- 核对 manifest 中的 SHA-256；
- 验证空标准值没有进入色标；
- 把删失样点使用独立符号；
- 把无坐标记录保留在表格，不放到 `(0,0)`；
- 展示候选异常、置信度和来源定位；
- 生成不依赖 CDN 的单文件 `atlas.html`；
- 生成来源与置信度分解、异常区域 GeoJSON 和四项交付物 manifest；
- 检查所有可上图异常均进入区域聚合，无法上图的异常 ID 被单独报告。

若 D3 必须猜字段、重做单位换算或回读 D2 内部代码才能工作，视为 D2 接口不完整。

### 3.5 端到端金标准

版本化期望见 [e2e-expectations.json](contracts/e2e-expectations.json)，主要包括：

- 19 条输入、18 个有效坐标；
- 固体 `2.5 wt.% Fe` 得到 `25000 mg/kg`；
- 水体 `0.02 mg/L Pb` 得到 `20 ug/L`；
- 水体 `1 ppm As` 拒绝换算；
- `<0.10 mg/kg As` 不插补，保留 `0.10 mg/kg` 删失限；
- 交换坐标不进入 GeoJSON；
- Demo 中只产生 `soil-as-012` 一个高值候选；
- 从 D3 点位可回溯到 D2 record，再回到 D1 manifest 和原始切片哈希。

### 3.6 通过标准

- D1、D2、D3 三个进程均正常退出，且 stdout 为机器 JSON。
- D2 九项文件存在，D3 不依赖 D2 私有函数。
- 所有数值金标准、记录计数、候选异常和证据链阻断项通过。
- HTML 中不加载 CDN 或远程脚本；断网可打开。
- 世界陆地轮廓使用固定 SHA-256 的 Natural Earth 1:110m public-domain 资产并嵌入 HTML。
- 相同 D1 输入和参数运行两次，D2 九项结果逐字节一致。
- D3 消费过程中发现的字段缺口或语义歧义进入 `review_findings`。

## 4. 方案三：真实公开数据 D1→D2→D3 Holdout

### 4.1 数据不是生成的

固定原始文件、元数据、查询和 SHA-256 见
[real-sources.json](contracts/real-sources.json)，实际数据说明见
[real-data/README.md](real-data/README.md)。完整运行包含：

| 来源 | 原始范围 | 进入 D2 的记录 | 主要验证目标 |
|---|---:|---:|---|
| USGS DS801 表层土壤 | 4,857 样点 | 7 元素 × 4,857 = 33,999 | `<`、`wt. %`、多方法/消解、WGS84 |
| USGS RASS Circle 沉积物 | 1,662 原始行；筛选 1,422 样品 | 4 元素 × 1,422 = 5,688 | N/L/G/H/B、粒级、NAD27、年代方法差异 |
| USGS Taylor Mountains 岩石 | 59 岩石样品 | 6 元素 × 59 = 354 | 裸 `%`、ppm、`<`、岩性/地层、NAD27、ICP55 |
| WQP USGS-01594440 砷 | 90 结果 + 1 站点 | 90 | 水体 fraction、未检出/检出限分列、方法缺失、NAD83 |

共 40,131 条 D2 输入测定。四者是独立数据产品和传输 Schema；测试不把它们伪装成全球代表性样本。

### 4.2 下载与离线策略

`fetch_real_fixtures.py` 实现：

- HTTPS、30 秒默认 timeout、有限重试、单文件 5 MB 上限；
- 预期字段、最低记录数、字节大小和 SHA-256 四重校验；
- `--offline` 完全断网校验；
- `--refresh` 重新下载，但上游字节漂移时失败且不覆盖固定 holdout；
- 数据文件与方法/CRS/许可元数据共同冻结，总计 2,713,710 bytes（约 2.71 MB）。

### 4.3 真实 D1 适配器

`real_d1_adapter.py` 做来源语义映射但不替 D2 完成标准化：

- DS801 的 `mg/kg`、`wt. %` 和 `<x` 原样传递；
- RASS `N` 映射为 `nd + detection_limit`，`L` 映射为 `trace + limit`；
- Taylor 岩石的岩性、来源表地层、地质背景版本与 ICP55 方法原样贯通；裸 `%` 不擅自解释成 `wt.%`；
- WQP 结果与站点按 `MonitoringLocationIdentifier` 连接；
- NAD27/NAD83 只声明原 CRS，不伪造重投影；
- 每条记录携带源文件、逻辑源行、精确查询/定位、文件哈希、DOI、版本和许可；
- 原始限定符另存 `source_qualifier_raw`，用于检查 D2 输出是否丢失来源词汇。

### 4.4 人工金标准与通过条件

[real-gold.json](contracts/real-gold.json) 在运行 D2 之前按明确源记录人工转录，至少核对：

- DS801 `C-328818` 的 `0.52 wt. % Fe → 5200 mg/kg`；
- DS801 `<0.1 mg/kg Cd` 只形成 0.1 mg/kg 删失限；
- RASS `CBH571 As: N + 200 ppm` 是 nondetect，不是 200 ppm 测得值；
- RASS `CBV067 Zn: L + 200 ppm` 是 trace，不是 nondetect；
- Taylor `C-289851 Fe: 3.21 %` 在质量基准未明确绑定前失败关闭，不直接换成 `32100 mg/kg`；
- Taylor `C-289822 Cu: <5 ppm` 只形成 5 mg/kg 删失限；
- Taylor `C-289853 Ni` 保留岩性、带问号地层、上下文来源与版本；
- WQP `NWIS-72607870` 的 Not Detected 与 1 ug/L 报告限分离；
- NAD27/NAD83 在无声明转换时不进入 canonical GeoJSON。

阻断通过标准：9 个文件哈希正确、记录不丢失且 ID 唯一、所有金标准正确、删失值不插补、证据链
闭合、至少一个真实背景组完成异常筛查、D3 能离线消费全部九项输出，并且比赛要求的四项产品
交付物存在、哈希闭合、来源置信度可解释、异常候选无静默丢失。字段覆盖缺口作为 `review` finding
保留，不能删除或包装成通过。

完整运行：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_real_data_suite.py \
  --output-dir /tmp/d2-real-full
```

CI 冒烟使用 `--max-source-samples 20`，仍读取同一批真实冻结原始文件，不使用生成数据。

完整真实层的 D3 最终验收对象为：交互元素地图、标准化地球化学数据库、来源与置信度说明、
异常区域识别结果。异常区域使用 2° 固定经纬网格聚合 D2 候选点；至少 3 个异常且该元素—介质网格
至少 10 个观测才标记为 `candidate_cluster`。它是可复核的筛查规则，不是地质边界推断。

## 5. 方案四：全球真实数据 D1→候选 D2→D3 基准

### 5.1 定位与数据

美国完整 holdout 擅长验证限定符和历史 CRS，但不能检验全球异构性。因此另建
`run_global_data_suite.py`，使用四个国际/国家开放平台的五个数据产品：

| 来源 | 介质 | 冻结范围 | 覆盖用途 |
|---|---|---:|---|
| GEOROC Archaean Cratons + Antarctica Intraplate | 岩石 | 2,017 样品行 / 7,951 测定 | 七洲岩石联合覆盖 |
| GEMAS Europe agricultural soil | 土壤 | 2,113 点 / 8,452 测定 | 欧洲协调采样与 Aqua Regia 基准 |
| NGSA Australia Hg | 沉积物 | 2,396 测定 | 大洋洲出口沉积物、深度和复样 |
| UNEP GEMStat v3 OPEN archive | 水体 | 656 测定 / 35 国 | 亚、欧、北美、南美水质异构数据 |

合计 19,455 条 D1 测定，覆盖 As、Cr、Cu、Hg、Ni、Pb、Zn。仓库只保存 2.16 MB
值无关冻结切片和官方元数据；父档案只在基准维护者刷新时下载到仓库外缓存。

### 5.2 选择偏差控制

- GEOROC 按命名区域和 `UNIQUE_ID` 确定性等距抽样，最多 80 个样品，不读取浓度大小。
- GEMAS 保留官方 layer 3 的全部 2,113 点和真实缺值。
- NGSA 保留全部 2,396 条，不删除 TOS/BOS 和声明复样。
- GEMStat 先选每站每元素最早的受支持单位结果，再按国家—元素和站号抽取最多 5 站，不按结果值选样。
- 每条 D1 记录带来源定位、原行、版本、许可、DOI/持久标识符和父文件 SHA-256。

### 5.3 候选 Agent 接口

评测器可以替换 D2，而不需改 D1、D3 或重写采分逻辑：

```bash
python3 evaluation_lyf/stage_benchmark/scripts/run_global_data_suite.py \
  --output-dir /tmp/d2-global-candidate \
  --d2-script /absolute/path/to/candidate_d2.py \
  --candidate-label candidate-name
```

候选脚本必须支持 `--input <csv> --output-dir <new-dir>` 并生成 `d2-interface-v2` 的九个文件。
硬门槛是 `global_data_report.json` 中 `counts.blocking.failed == 0`；覆盖和上游元数据缺口保留为
`review` finding，不允许候选实现伪造方法、CRS 或不确定性来换取通过。

### 5.4 阻断验收

全球层机器验收包括：

- 11 个冻结资源的字节数、SHA-256 和必要标记离线匹配；
- 七洲联合覆盖、四介质、五数据集、35 个明确国家和七元素齐全；
- D1 行级证据链、导出哈希和记录数闭合；
- GEMAS、NGSA、GEMStat、GEOROC 四类真实点值金标准和至少一个删失值语义核对；
- D2 不丢记录、不插补删失值、不静默填造方法/CRS，八文件可由 D3 独立消费；
- 交互地图、标准化数据库、来源与置信度说明、异常区域结果四项产品存在且 SHA-256 闭合。

当前全球基线 37/37 阻断项通过。评审项故意显示 13/28 个洲—介质单元非空、GEOROC
坐标基准未声明、方法/坐标不确定性缺失以及 GEMStat 水体只覆盖四洲，防止把“七洲联合”
误写成“全球均匀代表”。

## 6. 结果解释

四层方案回答不同问题：

| 结果 | 解释 |
|---|---|
| 独立通过、全流程通过 | D2 规则和接口均达到当前 v2 验收线 |
| 独立通过、全流程失败 | 多半是契约、来源链或 D3 消费字段不完整 |
| 独立失败、全流程通过 | Demo 路径偶然成功，不能说明科学边界可靠 |
| 两套均失败 | 先修 D2 阻断项，再继续地图集成 |

合成层负责穷举边界和精确回归，真实层负责揭露来源 Schema、限定符、单位、CRS 与缺失模式问题。
四层全部通过阻断项仍不证明全球均匀覆盖或异常成因正确；许可适用性、地质匹配、代表性和科学解释仍需
来源核验及领域人工复核。
