# 三分钟冠军 Demo

这套 Demo 用真实 D3 运行结果解释 Global Geochemical Atlas Skill：一个研究请求经过 D1 来源系统、D2 标准化与科学门禁、D3 profile-driven 可视化，输出比赛要求的五类结果，并保留完整证据边界。

## 直接打开

推荐从仓库根目录启动本地静态服务：

```bash
python3 -m http.server 8000 --bind 127.0.0.1
```

然后访问：

```text
http://127.0.0.1:8000/demo/presentation.html
```

也可以直接使用 [Global-Geochemical-Atlas-Demo.pptx](Global-Geochemical-Atlas-Demo.pptx)。PPTX 包含 6 页讲稿备注、原生转场与对象动画；页面主体由可编辑 DrawingML 组成。

## 文件

- `presentation.html`：6 页 16:9 动态演示，无 CDN 依赖；第 3、4 页内嵌真实交互地图。
- `Global-Geochemical-Atlas-Demo.pptx`：PPT Master 导出的可编辑稳定后备。
- `speaker-script.md`：严格 180 秒的逐页讲稿、现场动作、失败回退与口径边界。
- `assets/*.png`：两张 1920×1080 真实运行完整截图，iframe 失败时自动作为视觉后备。
- `live/*.html`：全球与中国两个原始、自包含交互地图。
- `prepare_demo.sh`：可选的 996 条 USGS 生产阈值技术复现实验，不属于 expanded run 统计口径。

## 演示控制

- `←` / `→`、`PageUp` / `PageDown`、空格：翻页。
- `Home` / `End`：首页 / 尾页。
- `N`：显示或隐藏当前页讲稿。
- `T`：启动或暂停 3 分钟计时；`R`：归零。
- `F`：全屏。
- 第 3、4 页：点击“启用地图交互”；按 `Esc` 或再次点击按钮退出。
- 右下角 `PPTX`：下载可编辑后备版本。

## 演示使用的数据口径

expanded global run：

- 44,536 canonical records；
- 44,510 mapped measurements；
- 11,548 physical samples；
- 4 种介质；
- 535 个记录级 high/low 候选；
- 15 个声明来源，未升级为独立验证来源；
- 26 条不可上图记录仍保留在数据库与 QC。

China drilldown：

- 7,114 条测定；
- 1,464 个物理样点；
- 136 个记录级候选；
- 6 个元素、2 种介质；
- Natural Earth 国家多边形与 WGS84 bbox 联合严格裁剪。

置信度与护栏：

- overall 0.874；来源 0.897、完整性 0.956、方法 0.813、空间 0.800、QC 0.876；
- 置信度衡量工作流可用性，不是正确概率；
- 248 条删失观测不插补为 0；
- locator 覆盖 100%，但 independent verified count 为 0。

## 可选技术复现

如需在答辩后展示 D1→D2→D3 的离线生产阈值闭环，从仓库根目录运行：

```bash
bash demo/prepare_demo.sh /tmp/global-geochemical-atlas-live
```

该脚本使用仓库内固定的 996 条 USGS 土壤观测，验证生产 `n≥20`、GLiM 匹配、候选异常与十五产物契约。它与本演示的 expanded run 是两套互补验证资产：前者证明确定性闭环，后者证明来源/介质广度与全球、区域产品界面。不要合并两者的统计数字。

## 录制检查

- 分辨率 1920×1080，浏览器缩放 100%。
- 提前加载第 3、4 页 iframe，现场不等待下载。
- 不展示密钥、私人路径、聊天记录或评测私有材料。
- 不说“发现污染/矿床”，只说“在声明的可比背景组内识别记录级 high/low 候选”。
- 不说“15 个已验证来源”，只说“15 个声明来源”。
- 地图异常时使用截图继续，不现场排查。

比赛最终提交物仍是完整、可复用的 Skill 文档；本目录是演示与传播材料，不改变提交格式。
