# 时间演变可交互地图 · 设计决策(temporal-atlas-v1)

交付物:`scripts/build_temporal_map.py` + `assets/temporal-atlas-v1.html`(模板)。
产物:单文件离线 HTML,零外部依赖,同输入字节级确定性输出。

## CLI

```
python3 scripts/build_temporal_map.py \
  --input <geochemistry.csv> --output <out.html> \
  [--template assets/temporal-atlas-v1.html] [--basemap assets/natural-earth-110m-land.json]
```

stdout 输出 JSON 构建报告(记录/站点统计,无时间戳)。

## 时间语义与诚实降级(硬规则)

- 仅 `sampling_time_status == publisher_reported` 且 `sampling_time` 按 `sampling_time_precision` 可解析的记录参与时间回放;其余记录**绝不假装有时间**。
- 界面三处明示占比:KPI 卡「带采样时刻的记录占比」(468/1144 · 40.9% + 进度条)、模式说明条、页脚长文。
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
3. **发光样点**:`globalCompositeOperation="lighter"` 加法混合 + 预渲染径向渐变发光精灵(核心实色 → 35% → 透明),同点位多记录自然叠亮,密度即亮度。
4. **元素色板**:As 琥珀 / Cr 玫红 / Cu 铜橙 / Hg 紫 / Ni 青 / Pb 蓝 / Zn 绿,筛选片、图例、弹窗折线全链路同色;未知元素落入 8 色循环备用板。
5. **时间刷**:直方图背景(青色渐变柱 = 精确时点,金色堆叠段 = 年段),窗口外柱体降为 25% 透明度,双把手圆角胶囊 + 中央刻线;播放键圆形发光按钮,播放态换色。
6. **过渡动画**:筛选/模式切换 260ms 渐入(≤300ms 验收线);新点脉冲、KPI/计数即时刷新;绘制全走 requestAnimationFrame,静止时不空转(dirty-flag 调度),60fps 目标。
7. **空状态**:金边卡片写明「是时间元数据缺口,不代表没有观测」,给出该组合无时间记录条数与三条可操作引导。
8. **HUD 体系**:左上模式徽章(呼吸点)、左下窗口计数、右下动态图例、右上圆角缩放工具,统一半透明毛玻璃深色卡片语言(继承 v3)。
9. **中文界面**:介质/精度/趋势全部中文标签;hero 标题渐变强调「时间演变」。

## 确定性实现

- 载荷 `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` + `<`/`>`/`&` 转义(照搬 v3 `safe_embedded_json`);记录按 record_id 排序;元素/介质/来源/精度字典序;无时间戳、无随机数(星空种子固定且在运行时生成,不影响文件字节)。
- 内嵌底图仅保留 rings/title/scale/license/asset_version,剥离 source_url 等 URL 字段 → 整个 HTML 零 `http(s)://` 出现。
- 兼容性:内嵌 JS 避免 `?.`/`??` 等 ES2020 语法,通过 node v12 `--check`。

## 集成接线建议(主线)

- run_workflow 在 D3 阶段追加调用本生成器,输出放包内 `temporal_map.html`;
- component_test 可断言:两次构建 sha256 相等、`http(s)://` 计数为 0、报告 stats.dated_share 与 CSV 实际一致。
