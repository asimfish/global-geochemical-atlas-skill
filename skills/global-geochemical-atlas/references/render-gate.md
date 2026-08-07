# 交互地图渲染冒烟硬门禁

本文定义 `interactive_map.html` 的交付门禁语义。SKILL.md 第 7 节的 MUST 条款以本文为完整契约。

## 为什么存在

2026-08-08 消融实测中，一次中国区域运行交付了主画布全空的地图：数据集 datum 未声明导致 canonical 坐标为空，执行方绕过 skill 渲染器手写了自定义 HTML，仅做 `node --check` 语法校验就交付，运行时 `Uncaught TypeError` 使 SVG 内 0 个图形元素。语法校验、文件存在性和 hash 一致都不能证明地图真的渲染出来；本门禁把"真实渲染"变成可执行检查。

## 命令

单文件冒烟（交付前最少执行一次）：

```bash
python scripts/validate_visualization.py --html OUTPUT_DIR/interactive_map.html
```

完整 D3 bundle 校验（profile 驱动产物）会自动包含同一渲染冒烟：

```bash
python scripts/validate_visualization.py --output-dir VISUALIZATION_OUTPUT
```

## 通过标准（全部满足）

1. 无头浏览器（自动发现 Chromium 族：`google-chrome`、`chromium`、`chromium-browser`、`msedge` 等，或 `GCA_HEADLESS_BROWSER` 显式指定）能加载页面；
2. 可见图形元素数 > 0，满足下列任一渲染证明：
   - DOM 内 SVG `circle`/`path`/`rect`/`polygon` 图形元素 > 0；
   - 存在 `<canvas>` 且 `document.body.dataset.gcaRenderAttest` 声明 `symbols > 0`（skill 模板在每次绘制后写入该证明）；
   - 同时截图像素分析必须显示非背景着色比例与颜色多样性超过阈值（防止"有元素但全空白"）；
3. console 无未捕获异常（`Uncaught`/`ERROR` 级过滤规则见脚本内注释）；
4. `--coordinate-mode reported` 产物必须包含警示条（`gca-reported-banner`，文案含"报告坐标"与"datum 未验证"）；canonical 产物不得包含该警示条。

## 退出码

| 退出码 | 含义 | 允许交付？ |
|---|---|---|
| 0 | 渲染冒烟通过 | 是 |
| 1 | 渲染失败（空画布、未捕获异常、缺警示条等） | 否，必须修复后重跑 |
| 3 | `skipped_no_browser`：未发现可用无头浏览器 | 仅在人工打开地图确认可见图形并在交付说明中记录"人工渲染确认"后 |

退出码 3 是显式跳过，不是通过。禁止把 skipped 静默当成绿灯；沙箱无浏览器时必须在 run summary/交付说明里保留 `needs_render_confirmation` 状态。

## 禁止事项

- MUST NOT 绕过 `render_visualization.py`/`build_interactive_map.py` 手写、复制或改写地图 HTML；
- MUST NOT 用 `node --check`、文件大小、hash 或"打开过一次没报错"替代本门禁；
- MUST NOT 在渲染失败时改用截图、静态图或"看起来正常"的部分产物交付；
- 确需自定义模板时，产物 MUST 通过同一 `--html` 冒烟检查并保留检查输出。

## 降级路径（canonical 坐标为空）

数据集只有报告坐标（datum 未验证）时，用 `--coordinate-mode reported` 重新渲染：报告坐标上图并自动注入警示条；两种坐标都没有的记录不上图、计入侧栏与 `map_report.coordinate_statistics`。canonical 模式零可映射记录会失败关闭并提示该选项，绝不交付空地图。
