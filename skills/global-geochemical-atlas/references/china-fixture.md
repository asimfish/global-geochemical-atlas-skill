# 中国区域 fixture（fixtures/china/combined-v1）

hash 固定的中国区域双源 fixture，服务 bbox 73–135E、18–54N 的土壤+沉积物回归与演示。它不是中国在线研究请求的默认数据；只在显式 `--demo china`、离线回归或已说明的网络降级中使用。运行入口：

```bash
python scripts/run_atlas_request.py \
  --request fixtures/china/combined-v1/request.json \
  --demo china \
  --coordinate-mode reported \
  --analysis-profile production \
  --generated-at 2026-08-08T00:00:00Z \
  --output-dir OUTPUT_DIR
```

实测（2 CPU 容器）端到端 <10 秒，适合快速确认接口、科学规则和渲染器没有回归。在线获取必须服从当前 840 秒内部评测预算；如果完整 TPDC 下载与解析超出预算，保留已完成来源证据并诚实返回检查点。环境允许时可显式使用长研究模式继续，这不构成优先用 fixture 冒充在线结果的理由。

## 来源登记

### 1. TPDC 中国山地土壤剖面（源全量 6,570；随包 demo 2,400）

- 标题：Multi-element dataset of soil profiles across climatic zones in China's mountains；
- DOI `10.11888/Terre.tpdc.302620`，CSTR `18406.11.Terre.tpdc.302620`，许可 CC-BY-4.0（TPDC licence code 1）；
- 版本 `tpdc-file-2025-07-23`；官方 POST bundle（fileId `d4c22475-e614-42d2-b8ec-d768f1c26426`）1,828,683 bytes，SHA-256 `8cf3189b44aad64b65cd213c0fd015d30df5f1c59676823846292f83baa1a84a`；
- 内层 `Soil dataset.xlsx` 577,715 bytes，SHA-256 `923da5a896c0f403d227799cb04d565f75d641d5c81290889fcaddaa42ff593d`；
- 源全量：1,314 个 O/A/C 层位样品 × Cr/Cu/Ni/Pb/Zn = 6,570 观测（注册 `expected_counts` 全量，无 As/Hg）；随包 fixture 按源顺序对五元素平衡抽取 2,400 条（480 个样品），以满足提交包大小限制。在线/缓存研究路径与 full profile 仍保留 6,570 条能力；
- 坐标：逐样品 GPS 报告坐标；注册元数据与数据文件均未声明 CRS/datum，canonical 保持空，上图必须 `--coordinate-mode reported`；
- 方法：ESSD 论文（doi:10.5194/essd-17-4779-2025）按元素登记 ICP-MS (Agilent 7700x)/ICP-AES (PerkinElmer Optima 2000)。

### 2. Zenodo 7098563 长江/黄河沉积物（全量 558 观测；已注册在线适配器 `zenodo-yangtze-yellow-river-sediment`）

- 标题：Evaluation of Grain size, Amorphous Fe-Mn Oxides, and Chemical Weathering Effects on Geochemical Identification of the Yangtze River and Yellow River Sediments（Data Set S2）；
- 存缴者 Chao Wu（中国科学院广州地球化学研究所），发布 2022-09-21，记录修订 rev2；
- DOI `10.5281/zenodo.7098563`，许可 CC-BY-4.0（Zenodo 记录元数据 `cc-by-4.0`）；
- `Data Set S2.xlsx` 76,596 bytes，SHA-256 `413f54f6544967d1d96b9eacfbeae41ba410a8c4b0375bdfaabc1293fd6fadd2`，Zenodo 官方校验和 `md5:f71702e1fc28c92ad4fcc139ce77b934`；
- 切片：93 个 HCl-/AC-残余粒级分离沉积物样品（黄河 HH 54、长江 CJ 39；80 HCl + 13 AC）× As/Cr/Cu/Ni/Pb/Zn = 558 观测，逐行定位 `Data Set S2.xlsx#sheet1-row=N`；
- 单位证据：工作簿不含单位行；构建器强制比对内嵌 BHVO-2/AGV-2/W-2/GSP-2 的 Preferred/Measured QC 块与认证 µg/g 值（容差 20%），全部通过才接受 `ug/g` 判定，失败即拒绝构建；
- 坐标：S2 不发布采样坐标；记录只入标准化数据库，不进任何地图层（失败关闭）；
- 方法：工作簿未声明逐行分析方法，方法字段留空并写入 `workbook_reports_no_analytical_method`。

## 组合契约

`fixtures/china/combined-v1/run_manifest.json` 绑定：请求、两源逐 fixture 输入/证据 SHA-256、逐源 generation manifest 摘要、源文件哈希绑定、2,958 条 record_id 与证据 1:1 对账、介质/元素计数、比较隔离边界（O/A/C 层位、HCl/AC 残余、粒级、坐标政策）。`run_atlas_request.py --demo china` 在执行前重新核验 fixture 输出哈希（`offline_fixture_hash_verified`）。

## 重建与在线重下载验证

fixture 由 `scripts/build_china_demo.py` 从原件确定性重建；原件字节或哈希不符即失败关闭：

```bash
python scripts/build_china_demo.py \
  --tpdc-cache-dir CACHE_ROOT \
  --zenodo-file "CACHE_ROOT/zenodo/Data Set S2.xlsx" \
  --generated-at 2026-08-08T00:00:00Z \
  --overwrite
```

`CACHE_ROOT/tpdc-china-mountain-soil/tpdc-file-2025-07-23/` 需包含 TPDC bundle 解出的三个成员（`Soil dataset.xlsx`、`Soil bulk density.xlsx`、`Description of the dataset.docx`）。实时重下载路径：

- TPDC：官方 file-ID POST 接口重新获取 bundle（`assets/source_catalog.json` 的 `official_file_download` 接口），核对 bundle 与成员 SHA-256 后重建；
- Zenodo：`https://zenodo.org/api/records/7098563/files/Data%20Set%20S2.xlsx/content` 重新下载，核对 76,596 bytes、`md5:f71702e1...`（Zenodo 官方）与 SHA-256 `413f54f6...` 后重建。

两条重下载路径是在线研究的正常可审计路径，不是预算外的可选后台动作。获取后仍必须校验官方 checksum/固定 SHA-256，并保留本次获取时间与 manifest。

## 声明边界

- fixture 证明接口兼容与预算合规，不代表全国代表性覆盖：TPDC 覆盖 30 个山地生态系统，Zenodo 覆盖两条河流体系；
- TPDC reported 坐标 datum 未验证，位置仅供示意浏览；Zenodo 记录无坐标，不参与空间筛查；
- 由 fixture 组产生的候选异常仅是管线候选，不支持污染或亏损结论。
