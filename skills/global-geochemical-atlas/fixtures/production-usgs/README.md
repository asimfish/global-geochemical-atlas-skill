# USGS production-profile fixture

该目录是 USGS Data Series 801（DOI `10.3133/ds801`，美国政府公开数据）的确定性真实数据切片，用于生产阈值端到端回归，不用于科学解释。

- `request.json`：可复现请求；
- `demo_input.csv`：249 个源行展开成 As/Cu/Ni/Zn 共 996 条测定；
- `sources.jsonl`：逐记录来源、源文件 hash 和定位；
- `run_manifest.json`：三个官方文件、版本、生成参数和输出 hash。

运行方法、固定验收指标、GLiM 署名和重生成命令见 [`references/production-demo.md`](../../references/production-demo.md)。
