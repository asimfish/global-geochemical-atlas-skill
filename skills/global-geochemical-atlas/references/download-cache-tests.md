# D1 下载与缓存测试记录

## 2026-08-05 14:15 CST

环境：macOS，Python 3.13.3。真实下载只写入 `/tmp/d1-usgs-cache/`，没有把第三方数据或缓存提交进仓库。

### USGS 在线下载

测试文件：`Appendix_2b_Top5_18Sept2013.txt`（0–5 cm soil）。

验证参数：

- 官方 URL：`https://pubs.usgs.gov/ds/801/downloads/Appendix_2b_Top5_18Sept2013.txt`；
- 数据集 DOI：`10.3133/ds801`；
- 数据集版本：`ds801-2013`；
- 最大体积：2,000,000 bytes；
- 必要字段：`SiteID`、`Latitude`、`Longitude`；
- 预期 SHA-256：`e831095cba4549a87144804aa1ccb38e07d44550ab91b27390b84fc1dbdbc894`。

结果：

| 检查项 | 结果 |
|---|---|
| 状态 | `downloaded` |
| 尝试次数 | 1 |
| HTTP 状态 | 200 |
| Content-Type | `text/plain` |
| 字节数 | 1,450,062 |
| SHA-256 | 与预期一致 |
| ETag | `W/"16204e-4e8f6e6c34b80-br"` |
| Last-Modified | `Thu, 17 Oct 2013 21:57:18 GMT` |
| 必要字段 | 全部存在 |

### 在线缓存复用

使用相同参数再次运行，结果为 `cache_hit`。下载器验证 URL、版本和 SHA-256 后复用本地文件，没有发起数据下载。

### 离线缓存复用

使用相同参数并增加 `--offline`，结果为 `cache_hit`。离线流程只接受 URL、版本和 SHA-256 匹配的缓存。

### 组件安全测试

执行：

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component d1
```

结果：19 项检查全部通过，其中下载相关检查包括：

- 拒绝 HTTP、loopback 等不安全 URL；
- 只复用通过 hash 和版本验证的缓存；
- ZIP 发布前验证必要成员和必要字段；
- 拒绝 ZIP 路径穿越；
- 证据包与 D2 输入 hash、置信度报告 hash 保持绑定。

### 尚待补充

- GEOROC 真实 ZIP 的 28 个成员 MD5 校验和安全解压记录；
- 429/502/503/504 有限重试的本地 HTTP 故障注入记录；
- 超时、Content-Length 超限、流式大小超限、HTML 伪文件和 checksum 不一致的完整自动化矩阵。
