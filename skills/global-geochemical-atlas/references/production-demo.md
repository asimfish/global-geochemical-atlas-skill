# 生产阈值真实数据演示

## 目的与边界

该演示证明请求路由、真实来源证据、D2 标准化与地质匹配、生产阈值异常筛查、D3 地图及十五项产物能够在一个命令中闭环。它不是美国土壤的统计代表性抽样，也不支持污染、矿化或成因结论。

输入是 USGS Data Series 801 的确定性切片：249 个源行、三个土层、As/Cu/Ni/Zn 四个分析物，共 996 条测定。`fixtures/production-usgs/run_manifest.json` 固定三个官方源文件的 URL、版本、字节数和 SHA-256；`sources.jsonl` 逐记录绑定源行定位。

地质背景使用 Hartmann & Moosdorf 全球岩性图 0.5° raster（PANGAEA DOI `10.1594/PANGAEA.788537`，CC BY 3.0）。仓库内固定压缩包的 SHA-256 是 `43b4ce3276b155d804db8ff9fb227d620b4c35015a4cf564eac4d06d2b69d88e`，下载证据见 `assets/geology/pangaea-788537.download.json`。

## 一键运行

从 Skill 目录执行：

```bash
python scripts/run_atlas_request.py \
  --request fixtures/production-usgs/request.json \
  --demo production-usgs \
  --analysis-profile production \
  --generated-at 2026-08-07T00:00:00Z \
  --output-dir /tmp/geochemical-production-demo

python scripts/validate_outputs.py \
  --output-dir /tmp/geochemical-production-demo
```

请求、D1 路由、覆盖矩阵和执行解释写入 `/tmp/geochemical-production-demo/request_evidence/`；`execution.json` 遵循 [request-execution.schema.json](request-execution.schema.json)。fixture 请求设置 `offline=true`，所以实时路由会诚实保留 `offline_cache_not_verified`；`execution.json.route_resolution=offline_fixture_hash_verified` 表示本次执行使用的本地输入、逐记录证据及上游文件清单已通过哈希链验证，不代表实时网络状态。

请求执行预期为 `partial_success`，因为 fixture 只能证明固定子集闭环，不能证明冻结请求的全量覆盖；`validate_outputs.py` 仍应返回 `valid`。没有传实验室 controls/policy 时，批次报告明确写 `not_supplied`，不是“默认通过”。

## 固定验收结果

在 Python 3.11+、无第三方运行时依赖下，预期结果为：

| 指标 | 预期值 |
|---|---:|
| 标准化测定 | 996 |
| canonical WGS84 坐标 | 996 |
| GLiM 岩性匹配 | 996 |
| 生产异常最小背景组 | 20 |
| 已分析可比背景组 | 12 |
| 背景不足组 | 60 |
| high/low 候选异常 | 6 |
| 通过生产空间门槛与 FDR 的候选区域 | 0（`insufficient_spatial_background`，不等于不存在） |
| 批次 QC | `not_supplied`（未评估，不等于通过） |
| 输出验证错误/警告 | 0 / 0 |

`confidence_report.json` 预期为 996 条 medium、0 条 high。原因不是记录“错误”，而是源数据没有逐点坐标不确定度，`d2-confidence-v3` 的 `missing_coordinate_uncertainty_medium_cap` 将最高等级封顶为 medium。置信度是五分量 workflow usability 分数，不是记录为真的概率。

候选异常来自 `log10` 浓度上的 median/MAD 双方向稳健筛查，并按元素、介质、土层、measurement basis、方法和地质背景等可比语义分组。结果只用于发现值得复核的候选；空间邻近、图面颜色或高 robust z 都不能单独证明成因。

## 重新生成 fixture

若需要从官方缓存重新生成而不是使用仓库内切片：

```bash
python scripts/generate_demo_data.py \
  --source usgs-conus-soil \
  --cache-dir .cache/data \
  --output-dir /tmp/usgs-production-fixture \
  --mode cached \
  --observations 996 \
  --elements As,Cu,Ni,Zn \
  --generated-at 2026-08-07T00:00:00Z
```

缓存必须与来源注册表中的固定文件和哈希一致；缺文件、hash 冲突或记录配额不足时失败关闭。不要用新响应覆盖旧快照。

## 人工复核门禁

真实数据演示不等于 `benchmark_ready`。每个来源已准备 30 条机器对账记录，但必须由具名领域人员逐条签署后才能升级：

```bash
python scripts/validate_human_review.py \
  --input fixtures/four-media/soil/usgs-conus-soil/human_review.json \
  --require-complete
```

未签署时该命令返回非零并保持 `normalized_analysis`；脚本只检查签名与计数一致性，绝不替人填写判断。
