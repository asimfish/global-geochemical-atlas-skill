# 真实来源的最小演示切片

这些文件用于验证 D1 → D2 → D3 流水线，不是统计代表性样本，不支持区域或全球科学解释。

每个目录包含：

- `demo_input.csv`：D1 交给 D2 的长表输入，保留原值、原单位、来源和许可；
- `sources.jsonl`：逐观测证据链，链接源文件、源行、文件 hash、数据集 DOI/版本和原始引用；
- `run_manifest.json`：固定生成参数、输入文件 hash、记录数、输出 hash 和科学限制。

## GEOROC demo

目录：`georoc-archaean/`。

- 来源：GEOROC Compilation: Archaean Cratons，DOI `10.25625/1KRR1P`，版本 12.0；
- 许可：CC BY-SA 4.0；
- 内容：按源文件顺序选择 whole-rock、精确点坐标记录，并平衡抽取 As、Cu、Ni、Zn 各 12 条；
- 边界：数值是 GEOROC 预编译选择值，不代表全部重复测量。

## USGS demo

目录：`usgs-conus-soil/`。

- 来源：USGS Data Series 801，DOI `10.3133/ds801`；
- 权利状态：USGS 制作的数据属于美国公有领域，仍保留建议引用；
- 内容：0–5 cm、A horizon、C horizon 各选择 4 个源样品，每个样品保留 As、Cu、Ni、Zn；
- 边界：三个土层保持可区分，legacy qualifier 和科学标准化由 D2 处理。

## MarChem demo

目录：`norway-marchem/`。

- 来源：MarChem 挪威海域沉积物动态 API 快照 `norway-marchem:2026-08-05T10:27:11Z:be888784ee2e`；
- 许可：CC BY 4.0，保留来源署名；
- 内容：从已经准备的 30 条分层复核记录中保留 28 条含目标元素的源行，生成 As、Cu、Ni、Zn 各 28 条，共 112 条观测；
- 方法边界：所有值均为干重 `mg/kg` 的部分硝酸消解结果，不代表总含量；批次认可状态和 LLQ 按观测保留；
- 关系边界：完整快照的 1,070 行对应 880 个样品，fixture 不把第二参数组产生的附加行误算成新样品。

## 确定性再生成

先按 `references/data-sources.md` 下载并验证来源。完整第三方文件留在仓库外缓存，然后在仓库根目录运行：

```bash
python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source georoc-archaean \
  --cache-dir .cache/data \
  --output-dir /tmp/georoc-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-05T06:25:00Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source usgs-conus-soil \
  --cache-dir .cache/data \
  --output-dir /tmp/usgs-demo \
  --mode cached \
  --observations 48 \
  --generated-at 2026-08-05T06:25:00Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source norway-marchem \
  --cache-dir .cache/data \
  --archive /path/to/marchem-inorganic-2003-2024.zip \
  --output-dir /tmp/marchem-demo \
  --mode cached \
  --observations 112 \
  --generated-at 2026-08-05T12:50:00Z
```

使用相同注册表版本、验证缓存/快照和 `--generated-at` 时，每个来源的三个输出文件均应字节级一致。不要把 `.cache/data` 或完整第三方数据提交到仓库。
