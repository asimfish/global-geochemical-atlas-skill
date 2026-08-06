# 离线地图资产

`natural-earth-110m-land.json` 是从 Natural Earth 1:110m Land 官方 Shapefile 确定性转换得到的经纬度多边形；
档案内 `VERSION.txt` 为 4.1.0。

- 官方主题页：<https://www.naturalearthdata.com/downloads/110m-physical-vectors/>
- 官方档案：<https://naturalearth.s3.amazonaws.com/110m_physical/ne_110m_land.zip>
- 原档案 SHA-256：`1926c621afd6ac67c3f36639bb1236134a48d82226dc675d3e3df53d02d2a3de`
- 许可：Natural Earth 声明其网站上的矢量与栅格地图为 public domain；见
  <https://www.naturalearthdata.com/about/terms-of-use/>。
- 转换：保留全部 land polygon rings，坐标四舍五入至 4 位小数；不包含国界、地名或任何科学测量值。

重建：

```bash
python3 evaluation/d2-validation/scripts/build_basemap_asset.py --download
```

地图生成器会把该资产嵌入 `atlas.html`，运行时不请求网络。
