# D1 数据接入失败与降级策略

本文件定义数据下载、缓存、解压、解析和证据链环节的失败关闭行为。任何降级都不得把未验证数据变成科学结论，也不得绕过登录、授权、许可或访问控制。

## 结构化状态

`download_data.py` 失败时退出码为 `2`，并尽力在指定 manifest 路径写入 `geochemical-download-v1` JSON。`status` 与 Skill 公共返回契约保持一致：

| 状态 | 使用条件 | 调用方动作 |
|---|---|---|
| `invalid_input` | URL 非 HTTPS、目标为本机或私网、参数或 hash 格式无效 | 修正请求；不重试 |
| `network_unavailable` | DNS、连接或超时失败，且没有可验证缓存；离线模式缓存缺失 | 可在限定次数内重试瞬态网络错误，随后改用验证缓存或 fixture |
| `source_not_accessible` | HTTP 401/403、需要登录、人工表单或来源已下线 | 停止；不重试、不切换身份、不绕过限制 |
| `incomplete_retrieval` | checksum、版本、大小、文件、字段、格式或解压校验失败 | 停止使用该文件；核对官方来源和注册表 |
| `needs_human_review` | 本次科研使用条件、引用、CRS、方法可比性或科学解释不清 | 保留已验证证据，限制当前 use mode，等待人工判断 |

失败 manifest 至少保留 `status`、`source_url`、`output_filename`、`license`、`offline` 和具体 `error`。调用方不得把“未检索到”解释为“数据不存在”。

## 失败矩阵

| 场景 | 检测与行为 | 允许的降级 |
|---|---|---|
| 网络失败，有有效缓存 | 按 URL、数据集版本和 SHA-256 验证后返回 `cache_hit`，不联网 | 使用缓存，并记录 `cache_verified_at` |
| 网络失败，无缓存 | 返回 `network_unavailable` | 仅可切换到仓库 fixture 演示 |
| HTTP 429/502/503/504 或瞬态超时 | 指数退避，最多按 `--retries` 再试 3 次 | 次数耗尽后返回结构化失败 |
| HTTP 401/403 | 第一次响应即停止 | 返回 `source_not_accessible`；禁止绕过 |
| 其他 HTTP 错误 | 不重试 | 返回 `incomplete_retrieval` |
| 返回 HTML/XHTML | 在写入正式文件前拒绝 | 核对官方直链，不解析页面为数据 |
| `Content-Length` 或实际流量超限 | 中止并删除 `.part` 文件 | 缩小明确的数据请求；不得自动放宽上限 |
| 空文件或 SHA-256 不一致 | 不发布正式文件，不更新成功 manifest | 核对注册表和官方版本 |
| 缓存 URL、版本或 SHA-256 不匹配 | 不复用缓存 | 使用明确的 `--refresh` 获取注册版本，或人工更新注册表 |
| ZIP 损坏、路径穿越、符号链接、成员数或展开体积超限 | 不发布解压目录 | 核对官方包；不得跳过安全校验 |
| 必要成员或字段缺失 | 报告缺失成员或字段并停止解析 | 更新适配器和注册表后重新验证 |
| 允许科研分析但不允许发布原始库 | 原始文件只进入本地只读缓存，不提交 Git | 提交标准化科研结果、地图、下载脚本、引用和证据说明；不制作原数据库镜像 |
| 真实来源全部不可用 | 不生成或声称真实科学结果 | 可运行 fixture；必须保留 `not_for_scientific_interpretation: true` |

## 文献与 PDF 边界

- DOI 没有开放全文时，只记录 DOI、标题、作者、年份和可验证的出版元数据；不尝试绕过订阅或登录。
- PDF、扫描件或表格无法稳定定位到页码、表号和原始行时，不输出其中的数值。
- OCR 或模型推断不能替代原始数值证据；未来若引入人工复核，必须另行记录提取方法、复核人和置信边界。

## Fixture 降级

Fixture 只用于验证流程、接口、地图和交付文件结构。使用 fixture 时必须同时满足：

1. 输出显式标记 `data_mode: fixture`；
2. 输出显式标记 `scientific_scope: pipeline demonstration only`；
3. 输出显式标记 `not_for_scientific_interpretation: true`；
4. 不把 fixture 的异常候选、空间分布或统计量写成现实世界结论；
5. 真实来源恢复后，重新从验证文件生成数据和证据链。

## 自动化验证入口

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component d1
```

测试使用内存响应、临时文件和故障注入覆盖缓存缺失、版本和 checksum 不一致、HTML、声明和流式大小超限、超时重试、403 停止、有限 HTTP 重试、ZIP 损坏与路径穿越、必要成员和字段缺失。测试不会访问受限来源，也不会在仓库内写入第三方完整数据。
