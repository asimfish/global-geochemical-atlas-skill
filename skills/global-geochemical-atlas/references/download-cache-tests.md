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

## 2026-08-05 14:22 CST

### USGS 适配器

- 在线获取三个官方 TXT，实际 SHA-256 与注册表全部一致；
- 解析得到 14,571 条源记录：0–5 cm、A horizon、C horizon 各 4,857 条；
- 缓存模式重新验证三个文件的 URL、版本和 SHA-256，结果全部为 `cache_hit`；
- 解析结果保留土层、原字段、原单位、文件名和物理行号。

### GEOROC 适配器

- 在线获取 Dataverse 版本 12.0 的动态 ZIP；
- 安全解压并验证 28 个注册成员，无缺失或额外 CSV；
- 逐成员验证文件大小和发布方 MD5，并计算本次取得文件的 SHA-256；
- 必要字段 `CITATIONS`、位置、坐标范围、样品、岩石名称和材料全部存在；
- 解析得到 33,745 条源记录，28 个成员均包含记录；
- 缓存模式重新验证 ZIP hash、成员集合、成员 MD5 和字段，结果为 `cache_hit`；
- CR 行结束符和 CSV 后附引用文本均已正确处理，引用文本不会被误判为测量记录。

## 2026-08-05 14:39 CST

### 自动化失败注入矩阵

执行：

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component d1
```

使用临时目录、内存响应和可注入下载器完成以下验证，不依赖外部网络：

| 故障 | 预期行为 | 结果 |
|---|---|---|
| 离线且缓存缺失 | 退出码 2，manifest 为 `network_unavailable` | 通过 |
| 缓存 SHA-256 不一致 | 拒绝缓存 | 通过 |
| 缓存数据集版本不一致 | 拒绝缓存 | 通过 |
| HTML/XHTML 响应 | 写正式文件前拒绝 | 通过 |
| 声明体积超限 | 写正式文件前拒绝 | 通过 |
| 无可信 Content-Length 且流量超限 | 流式读取时中止 | 通过 |
| 连续两次超时后恢复 | 退避 1 秒、2 秒，第三次成功 | 通过 |
| HTTP 403 | 第一次即停止，返回 `source_not_accessible` | 通过 |
| HTTP 502 / 500 | 502 可重试；500 不重试 | 通过 |
| ZIP 必要成员缺失 | 报告缺失成员，不发布目录 | 通过 |
| 必要字段缺失 | 报告字段差异并停止 | 通过 |
| ZIP 损坏 | 拒绝并清理临时目录 | 通过 |
| ZIP 路径穿越 | 拒绝且目标目录外无文件 | 通过 |

D1 当前共 46 项契约检查通过。完整降级规则见 `failures.md`。
