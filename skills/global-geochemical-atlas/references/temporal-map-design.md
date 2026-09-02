# 时间演变可交互地图 · 设计决策(temporal-atlas-v1)

实现:`scripts/build_temporal_map.py` + `assets/temporal-atlas-v1.html`(模板)。
主产品:`interactive_map.html` 中的一级 `temporalView`；生成器的单文件离线
HTML 以 base64/source bytes 嵌入主图并经 `srcdoc` 懒加载。`temporal_map.html`
仅是相同内容的兼容镜像，零外部依赖、同输入字节级确定性输出，不是独立导航体验。

## CLI

```
python3 scripts/build_temporal_map.py \
  --input <geochemistry.csv> --output <out.html> \
  [--template assets/temporal-atlas-v1.html] [--basemap assets/natural-earth-110m-land.json]
```

stdout 输出 JSON 构建报告(记录/站点统计,无时间戳)。

## 时间语义与诚实降级(硬规则)

- 仅 `sampling_time_status == publisher_reported` 且 `sampling_time` 按 `sampling_time_precision` 可解析的记录参与时间回放;其余记录**绝不假装有时间**。
- 界面三处明示占比:KPI 卡「带采样时间的记录占比」(468/1144 · 40.9% + 进度条)、模式说明条、页脚长文。
- **两个诚实时间层级**(payload v2 `stats.dated_tiers`):`point` = 出版方写在行上的逐样时刻(秒/分/日);`window` = 出版方文档声明的整份数据集采集时段(月/年/年段,按区间处理)。KPI 卡分别列出两层条数,并按 `atlas-sampling-time-v1` 受控原因汇总无时间记录(`stats.undated_by_reason`:仅有发表年 / 存档不含采样时间 / 行缺值 / 来源未纳入合同)。
- **逐来源时间语义表**(`stats.source_time_semantics`,KPI 卡按钮「为什么其余记录没有时间？」展开):每个来源给出记录数、带时间数、时间层级、出版方字段或无时间原因、证据链接。目的是让读者一眼分清「时间占比低」是解析缺口还是档案本身不含采样时间——例如中国专题里 Gard 2019 全岩汇编 21,600 条只有地质年龄、长江流域土壤重金属汇编 6,618 条只有文献发表年,这两项不是任何解析器能补上的。`validate_outputs.py` 强制要求 payload 含 `source_time_semantics`/`dated_tiers` 与 `timeSemanticsTable`。
- 无时间记录默认不上图,可开关为**灰色底衬**(小灰点,不发光、不参与窗口计数)。
- `year_range "YYYY/YYYY"` → 区间 [y0, y1+1),**置于区间中点参与排序**;地图上用**菱形**标记区别于圆点,时间轴直方图中堆叠为**金色柱段**,tooltip 写明「年段记录 · 置于区间中点」。
- 时间统一为十进制年(秒/分精度取瞬时,日/月/年取区间中点),精度构成在页脚披露。
- 坐标回退:canonical latitude/longitude 缺失时用 original_latitude_raw/original_longitude_raw,tooltip 与页脚标注「未规范化」;两者皆无则不上图但计入统计(dated_unmapped)。

## 双模式

- **模式 A 采样史回放**:年粒度直方图刷选条(双把手 + 整窗拖动 + 双击复位)、播放/暂停(右缘按 3/6/12 年每秒平滑推进,requestAnimationFrame 插值)、元素/介质筛选片、左下角窗口计数 HUD。新进入窗口的点有 950ms 发光脉冲扩散环。
- **模式 B 站点演变**:站点 = 同一位置(3 位小数坐标唯一)≥3 个不同采样时刻;站号取 sample_id 竖线前缀(GEMStat/GEOTRACES 类),无竖线时按坐标分组、标签取 sample_id 点分公共前缀(us-wqp → nwisca.01)。GEOTRACES 航次(GA01 等)因坐标漂移被「单一位置」规则自然排除,不会伪装成站点。点击站点弹出 Canvas 迷你折线图:数值点连线 + 虚线趋势线 + 删失点空心倒三角(按检出限绘制,不参与斜率);弹窗注明「仅描述观测序列,不外推」。
- 趋势判定:同单位数值点 ≥3 个不同时刻才做最小二乘斜率,relative = slope×span/median,|relative|>0.15 判上升/下降,否则平稳;不足则「时相不足」。站点着色取数值点最多的元素(暖=升,冷=降,中性=平,灰=不足)。
- 单位处理:站点-元素序列内按多数票选单位,异单位观测不混画,弹窗披露被排除数量。

## 美观决策清单(与 interactive-atlas-v3 保持视觉血缘)

1. **深色星空底图**:纵向深海渐变 + 固定种子 xorshift 星野(确定性,复用 v3 的 88675123 种子算法)+ 右上青色星云辉光;20°/30° 细经纬网。
2. **海岸线**:复用 v3 内嵌 Natural Earth 1:110m rings,双描边(宽 2.2px 低透明度青 + 细 0.8px 亮薄荷)+ evenodd 半透明陆地填充,与 v3 地球仪同款层次。
2b. **参考边界**:国界(Natural Earth 1:110m Admin-0)常显;区域研究命中固定 Admin-1 资产(当前为中国省界 1:50m)时叠加虚线省界;区域研究下邻国国界加粗(1.25px · α.72)、省界加亮(0.9px · α.42),便于定位。**研究国家轮廓(`boundaries.focus`)**:来自 D3 profile 的 `highlight_country_codes`(命名国家请求由 `run_atlas_request` 写入,中国为 CHN+TWN 分析单元),在 Admin-0 资产中按 ISO 码取环,先淡金填充(α.07)再金色描边(2.4px + 光晕),只标注 ISO 码、不带任何政体名称;未知 ISO 码构建失败关闭。它只是制图强调,与是否裁剪记录无关——中国请求带 600 km 邻海分析域时 `country_code` 为空、不裁剪,但研究框仍然画出。边界环预计算包围盒、按视口剔除,脚注披露资产版本与「仅供定位示意」语义。
2c. **区域导航锁**:视口矩形必须留在冻结区域内(每轴留 4% 余量):最小缩放 = 区域适配值(不能缩到比整个区域更远),平移时视口边缘不得越过区域边缘,某一轴上视口比区域还宽时该轴居中锁定;区域内允许最大 120 倍深放大。全球研究保持原 0.85–45 范围与整球平移。主图 `interactive-atlas-v3` 采用同一语义(`regionFrame()` 取景框:缩放上限 = 取景框跨度,平移钳制 = 取景框 ±3%)。
3. **发光样点**:`globalCompositeOperation="lighter"` 加法混合 + 预渲染径向渐变发光精灵(核心实色 → 35% → 透明),同点位多记录自然叠亮,密度即亮度。
4. **元素色板**:As 琥珀 / Cr 玫红 / Cu 铜橙 / Hg 紫 / Ni 青 / Pb 蓝 / Zn 绿,筛选片、图例、弹窗折线全链路同色;未知元素落入 8 色循环备用板。
5. **时间刷**:直方图背景(青色渐变柱 = 精确时点,金色堆叠段 = 年段),窗口外柱体降为 25% 透明度,双把手圆角胶囊 + 中央刻线;播放键圆形发光按钮,播放态换色。
6. **过渡动画**:筛选/模式切换 260ms 渐入(≤300ms 验收线);新点脉冲、KPI/计数即时刷新;绘制全走 requestAnimationFrame,静止时不空转(dirty-flag 调度),60fps 目标。
7. **空状态**:金边卡片写明「是时间元数据缺口,不代表没有观测」,给出该组合无时间记录条数与三条可操作引导。
8. **HUD 体系**:左上模式徽章(呼吸点)、左下窗口计数、右下动态图例、右上圆角缩放工具,统一半透明毛玻璃深色卡片语言(继承 v3)。
9. **中文界面**:介质/精度/趋势全部中文标签;hero 标题渐变强调「时间演变」。

## 确定性实现

- 载荷契约 `temporal-atlas-payload-v2`(v1 → v2 新增 `boundaries.focus`、`region.highlight_country_codes`、`stats.dated_tiers`、`stats.undated_by_reason`、`stats.source_time_semantics`;模板与 `validate_outputs.py` 同步钉住 v2)。
- 载荷 `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` + `<`/`>`/`&` 转义(照搬 v3 `safe_embedded_json`);记录按 record_id 排序;元素/介质/来源/精度字典序;无时间戳、无随机数(星空种子固定且在运行时生成,不影响文件字节)。
- 内嵌底图仅保留 rings/title/scale/license/asset_version,剥离 source_url 等 URL 字段 → 整个 HTML 零 `http(s)://` 出现。
- 兼容性:内嵌 JS 避免 `?.`/`??` 等 ES2020 语法,通过 node v12 `--check`。

## 集成接线（已实现）

- `run_workflow` 在 D3 阶段先生成时序文档，再把其 exact bytes 传给
  `build_interactive_map.py`，输出主图内一级选项和兼容 `temporal_map.html`；
- `validate_outputs.py` 解码主图 payload，断言它与兼容文件逐字节一致，并拒绝
  主导航 `<a href="temporal_map.html">` 或 iframe `src`；
- `component_test` 断言两次构建 SHA-256 相等、`http(s)://` 计数为 0、报告
  `stats.dated_share` 与 CSV 实际一致。
- 命名国家请求的主图与时序一级视图固定按冻结 Admin-0 国家范围
  取景；D1 可依请求在完整数据库中保留距边界不超过宣告距离的邻海
  记录，但邻海矩形包络盒不得改变国家主视图的初始范围。

## v2 追加：区域对比成为默认模式（同一区域的含量升降）

用户核心问题是「同一个地区的元素含量随时间怎么变」，v2 把它设为第一表达：

- **区域对比（默认模式）**：把带采样时刻的实测数值观测按 5° 网格分组（同元素 × 同介质 × 同单位，跨层浓度不可比），
  用可拖动的分割年切成早晚两期。同一格子两期都有 ≥2 条实测值时直接对比两期中位数：
  |变化| > 15% 记为上升（红）/ 下降（蓝），否则基本持平（灰）；只有单期观测的格子画虚线暗格并如实说明「无法比较」。
  点击格子弹出该区域的含量—时间散点（早期青 / 晚期橙、两期中位横线、分割年虚线、删失点空心倒三角）。
  删失值不参与分位与中位数统计，只按检出限绘制。
- **能力感知默认页**：只有至少一个元素在同层网格内同时具有早、晚两期
  可比观测时才默认打开「区域对比」；有真实日期但不足以构成对比时默认
  打开「采样史回放」，没有任何日期时也打开回放的明确缺口空态。
  不得为了让默认页“有数据”而伪造采样年或放宽同层可比门槛。
- **采样史回放**：点色默认改为「按含量高低」（同元素 × 同介质 × 同单位层内分位，蓝低红高），
  可切回「按元素类别」；含量高低随时间窗口即见即所得。
- **站点演变**：保持 v1（同一位置 ≥3 采样时相的浓度—时间序列与趋势）。

阈值 15% 与站点趋势的 TREND_RELATIVE_THRESHOLD 一致；分割年默认取带时记录时间中位数所在年。

## v3 追加：异常成因模式（把归因判定画到图上）

anomaly_provenance.json 此前只是 JSON 交付物，v3 把它嵌入时间地图的第四个模式「异常成因」：

- run_workflow 自动把 anomaly_provenance.json 传给 build_temporal_map（CLI 为可选 --provenance，
  不传时该模式显示引导性空态，绝不伪造判定）；
- 每个异常候选按 record_id 关联 D2 坐标上图，颜色 = 判定类别（绿=母质高背景 / 红=疑似人为输入 /
  紫=混合叠加 / 灰=证据不足不硬判 / 蓝=亏损候选不归因），大标记=富集、小标记=亏损；
- 点击标记弹出四条证据线（岩性 / 空间 / 伴生元素 / 时序）的通俗解释与「两条同向才判」规则说明；
- 无可用坐标的候选计入 unmapped 并在页脚如实说明。
