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
- 内容：按源文件顺序选择 whole-rock、reported point coordinates 记录，并平衡抽取 As、Cu、Ni、Zn 各 12 条；
- 边界：数值是 GEOROC 预编译选择值，不代表全部重复测量；公开元数据未充分声明统一 datum，因此 reported coordinates 只写入原始字段，canonical 坐标与 CRS 留空，不进入地图。

## USGS demo

目录：`usgs-conus-soil/`。

- 来源：USGS Data Series 801，DOI `10.3133/ds801`；
- 权利状态：USGS 制作的数据属于美国公有领域，仍保留建议引用；
- 内容：0–5 cm、A horizon、C horizon 各选择 9 个源样品，每个样品保留 As、Cu、Ni、Zn，并在每层确定性纳入一条删失记录；`material` 显式编码土层，避免异常背景混合；
- 边界：三个土层保持可区分；D1 按 USGS Appendix 5 映射 WGS 84、分析方法、消解方式和原始 qualifier，D2 负责 canonical qualifier、单位标准化、QC 和置信度。

## 确定性再生成

先按 `references/data-sources.md` 下载并验证两个完整来源，然后在 Skill 目录的上级仓库根目录运行：

```bash
python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source georoc-archaean \
  --cache-dir .cache/data \
  --output-dir /tmp/georoc-demo \
  --mode cached \
  --elements As,Cu,Ni,Zn \
  --observations 48 \
  --generated-at 2026-08-05T06:25:00Z

python skills/global-geochemical-atlas/scripts/generate_demo_data.py \
  --source usgs-conus-soil \
  --cache-dir .cache/data \
  --output-dir /tmp/usgs-demo \
  --mode cached \
  --elements As,Cu,Ni,Zn \
  --observations 108 \
  --generated-at 2026-08-05T06:25:00Z
```

使用相同注册表版本、验证缓存和 `--generated-at` 时，三个输出文件均应字节级一致。不要把 `.cache/data` 或完整第三方数据提交到仓库。
