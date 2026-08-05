# P05 客观评分器与产物验证器交接

## 结论

P05 的 E1 结构内容已完成，状态为 `E1_SCOPE_COMPLETE`。已交付独立 CLI、真实格式解析器、科学语义/四层溯源校验器、确定性评分模型、公开合成 fixtures 和正反输出示例。

当前契约为 `contract_sha256=b113743f47bbea4f3df8e13c93961071d1a1787243c1a857b4226b79c8acc4ee`，状态仍是 `FROZEN_FOR_MOCK`。E2 尚未签收 metric 级正式 rubric，所以没有创建 `READY_FOR_INTEGRATION`；mock 输出的 `score_status=partial` 和 90 分上限是“客观项下界诊断”，不是正式比赛分数。

## CLI

```bash
eval/scorers/eval-score \
  --contract eval/contracts \
  --run <raw-run> \
  --out <score-dir>
```

- scorer 正常完成一律 exit 0，包括候选失败、缺产物和坏产物。
- scorer 内部错误或契约/ rubric 不兼容 exit 75。
- 输出固定为 `<score-dir>/score.json` 与 `<score-dir>/checks.json`。
- 评分过程不访问网络、不调用 LLM、不导入或执行生产 Skill。

## 任务覆盖

| 任务 | 状态 | 证据 |
|---|---|---|
| P05-01 score/check/evidence 模型 | 完成 | `eval/scorers/engine.py`、`eval/schemas/score/checks.schema.json` |
| P05-02 真实解析器 | 完成 | JSON/JSONL、CSV、SQLite、GeoJSON、PNG、HTML 均真实解析 |
| P05-03 文件/Schema/字段/引用/MIME/大小/SHA | 完成 | `eval/validators/artifacts.py` |
| P05-04 单位/介质/censored/DL/方法/QC | 完成 | `eval/validators/science.py` |
| P05-05 四层来源链 | 完成 | observation → file/line → dataset version/hash/DOI → document/report/sample |
| P05-06 异常/H3/地图/停止降级 | 完成 | 已知答案 z-score、样本不足和高 censored 比例测试 |
| P05-07 fixture 矩阵 | 完成 | 22 个公开合成 fixture 目录；10 种必需产物各有合法/损坏样例 |
| P05-08 E2 权重映射 | E1 完成、E2 待签 | 六维权重固定；创新主观项 `not_scored`；未发明正式阈值 |

## 验证结果

固定命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s eval/tests/scorer -p 'test_*.py' -v
```

结果：`Ran 19 tests ... OK`。覆盖 24 个单位转换、15 个非法坐标、8 类下载错误、5 种用户 CSV 变体、2 个具名公开数据适配器、5 组合成异常数据、10 种必需产物损坏、10 类业务负例、恶意路径、超大文件、契约漂移和逐字节重复评分。

正例输出见 `handoff/P05/examples/good/`；断链负例见 `handoff/P05/examples/bad/`。good fixture 的 mock 客观下界为 90.0，剩余 10% 创新项因无 E2 客观规则而不计分。

## 未决门禁

1. E2 提供并签收 metric 级 `FROZEN_FOR_OFFICIAL` rubric，明确主观项归一化规则。
2. P02/P06 把 CLI 接入 runner 终态流程，将 worker 自报 `validation_status/evidence` 替换为 validator 的最终证据。
3. 上述门禁完成并重跑全套测试后，才能创建 `handoff/P05/READY_FOR_INTEGRATION`。

缺陷统一归档于 `handoff/P04/P01-08缺陷台账.md`；集成请求见
`root-change-request.md`。
