# 统一评测报告与浏览器验收

`evaluation` Q01–Q24、主机 uplift 和 Docker uplift 都使用同一个机器报告
`global-geochemical-evaluation-report-v1`，Markdown 只能由该 JSON 确定性渲染。候选 Agent 不写正式报告，
也不生成浏览器审计；二者均由评测控制器在候选退出后执行。

## 单次运行

先由候选目录外的控制器绑定 B0/S0 公共任务字节、provider profile 和本次 run ID。候选不得生成或修改该文件：

```bash
python3 evaluation/reporting/build_experiment_manifest.py \
  --config evaluation_lyf/agent_uplift/experiment_config.json \
  --b0-bundle-manifest B0/BUNDLE_MANIFEST.json \
  --s0-bundle-manifest S0/BUNDLE_MANIFEST.json \
  --condition S0 \
  --runtime docker-uplift \
  --run-id S0-01 \
  --expected-commit <experiment_config.json 中冻结的完整 commit> \
  --provider-base-url https://<网关主机>/v1 \
  --output RUN/experiment_manifest.json
```

它会在公共任务字节不一致、commit/profile/model/temperature/thinking 漂移、bundle 不是 formal 或 endpoint 不安全时
失败关闭，并为两臂生成相同 `pair_fingerprint`、不同 `run_fingerprint`。

```bash
python3 evaluation/reporting/browser_audit.py \
  --html RUN/submission/interactive_map.html \
  --output RUN/controller/browser_audit.json \
  --screenshots RUN/controller/screenshots

python3 evaluation_lyf/agent_uplift/public_case/score_submission.py \
  --case-dir RUN/case_data \
  --submission-dir RUN/submission \
  --browser-audit RUN/controller/browser_audit.json \
  --output RUN/controller/score.json

python3 evaluation/reporting/generate_report.py \
  --submission-dir RUN/submission \
  --runtime docker-uplift \
  --condition S0 \
  --run-id S0-01 \
  --independent-session \
  --blind-bundle \
  --score RUN/controller/score.json \
  --browser-audit RUN/controller/browser_audit.json \
  --experiment-manifest RUN/experiment_manifest.json \
  --skill-document skills/global-geochemical-atlas/SKILL.md \
  --output-json RUN/evaluation_report.json \
  --output-md RUN/evaluation_report.md
```

浏览器验收固定检查：页面加载与 JS error、Natural Earth 底图、可见样点、筛选是否改变结果、密度热力图、
元素组合、来源下钻、异常页和截图。`browser_audit.json` 绑定提交 HTML 的 bytes 与 SHA-256；缺少外部审计时，
静态 HTML 无法获得完整 D3 分数。截图必须与审计 JSON 相邻，且每张截图的文件大小和 SHA-256 也会重新验证。

统一报告把 D1 的候选/入选/拒绝/失败来源、检索平台、四介质与字段完整率，D2 的转换证据、坐标、地质、
QC、置信度和 high/low 候选，以及 D3 的真实浏览器交互分别列出；“测定记录”“唯一样品”“唯一坐标”永不混写。

## B0/S0 聚合

```bash
python3 evaluation/reporting/aggregate_uplift.py \
  --reports B0-01/evaluation_report.json B0-02/evaluation_report.json B0-03/evaluation_report.json \
            S0-01/evaluation_report.json S0-02/evaluation_report.json S0-03/evaluation_report.json \
  --output uplift_aggregate.json
```

聚合器要求每臂恰好三个不同 run ID、六个 run 都满足隔离与浏览器门禁，并共享一个 pair fingerprint。
它输出原始分、median、range、MAD 和 `S0−B0`。B0 median ≥ 90 标记 `ceiling_saturated`；两臂满分或
天花板饱和的任务保留作回归，但不算有效 uplift 证据。
