## 变更归属

- [ ] D1 数据源、证据链与数据工程
- [ ] D2 地球化学标准化与分析
- [ ] D3 Skill 架构、地图与 demo 总集成
- [ ] 跨组件接口变更（请列出受影响的生产者和消费者）

## 交付物影响

- [ ] **可交互元素分布地图**
- [ ] **标准化地球化学数据库**
- [ ] **数据来源与置信度说明**
- [ ] **异常区域识别结果**
- [ ] **可复用 Skill 文档**
- [ ] 不影响上述交付物

## 契约与证据

- 变更摘要：
- 输入/输出或 Schema 是否变化：
- 科学依据、适用条件与失败边界：
- 数据来源、许可、版本与 SHA-256（如适用）：
- 是否需要 D1/D2/D3 交叉复核：

## 复现

```bash
python skills/global-geochemical-atlas/scripts/component_test.py --component all
python skills/global-geochemical-atlas/scripts/self_test.py
```

- [ ] 上述命令通过
- [ ] 未新增第二个 Skill、密钥、缓存、生成输出或大文件
- [ ] 新增脚本的 `--help` 可运行
- [ ] README、引用和 Demo 已同步更新
