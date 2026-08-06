# Global Geochemical Atlas Benchmark — 独立评分报告（Q01–Q24）

## 0. 冻结身份

- benchmark 版本：`6.0.0-draft.2`（VERSION sha256 `8778356ee247221acd6e1e90c31bb4fa764234724107fe0a2b030ecfc4d059c9`）
- Git commit：`e0a350677c8a7372bf7b9cf90978a11045f847fe`
- 评分输出目录：`/tmp/gga-q01-q24-independent-grade`（全新创建，创建前已确认不存在）
- 冻结时间（UTC）：2026-08-06T14:40:23.102436+00:00
- 每题 `task.md`、`task.json`、`rubric.json`、`checker/grader_spec.json` 及提交目录 10 个产物的 SHA-256 已记录于 `frozen_identity.json`。
- 版本一致性：`ai_visible_public/tasks/Qxx` 与评分源（release/public、evaluator_private/shadow、evaluator_private/final_holdout）逐文件哈希一致，无 `version_mismatch`，无 `version_uncertain`。
- 评分期间提交与题面均未变化；`SUBMISSIONS_ROOT` 未被修改（全部写入仅发生在 OUTPUT_ROOT）。

## 1. 方法与边界遵守

- 逐题运行 `tools/grade_task.py`（确定性 checker），原样保留结果；24/24 退出码 0。
- 逐题按 `docs/llm_grader_protocol.md` 冻结 SYSTEM/USER prompt 执行 LLM rubric 评审；每题只提供 task.md、rubric.json、objective_report.json 与 rubric.evidence_paths 指定的证据；未提供 gold/。Q17–Q24（final holdout）按协议建议独立生成两次（A/B）。
- 全部 24 份 LLM 报告通过与 rubric.json 的 8 项逐条校验（task_id/数量/ID 集合/维度/max/score 范围/非零分证据/类型）。
- Q17 双评分歧（field_consistency 10 vs 8）→ 按协议进入人工复核；canonical 报告保守采用较低分并置 `human_review_required=true`。
- 逐题运行 `tools/finalize_score.py`（未使用 --static-review，因无冻结 static-review rubric）。
- 未执行、未修复、未重写候选提交；未使用 gold/ 作为证据；未把机器点数与 LLM 点数相加成总分。

## Q01 — GGA-DATA-001（release/public/Q01）

- 题面哈希：task.md `ef9ec4e602083c77…`，task.json `0e45d0b8d75df9fb…`，rubric.json `a066ca1d155af626…`，grader_spec `97fcf4d10c646d3d…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**17/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `scope_reasoning` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/source_selection.json/decisions/0/reason: 'Global compilation whose scope explicitly covers igneous rock (basalt); versioned files, record-level coordinates/method metadata...'; MACHINE EVIDENCE REPORT checks target_medium (actual='rock') and target_lithology (actual='basalt'), both passed<br>理由：The primary-source decision reason explicitly maps the target to rock medium (igneous rock/basalt), global coverage ('Global compilation'), and analytical metadata ('record-level coordinates/method metadata'); checker-confirmed target.medium='rock' and target.lithology='basalt' corroborate the scope match. |
| `source_roles` | scientific_credibility | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/source_selection.json/decisions/0: georoc_precompiled status='primary'; artifacts/run_manifest.json#/benchmark_evidence/source_selection.json/decisions/1/reason: 'Federated geochemical discovery service aggregating PETDB/GEOROC/USGS NGDB; used as joint discovery service for cross-searching, not as the primary data store.'; MACHINE EVIDENCE REPORT checks primary_georoc and discovery_earthchem, both passed<br>理由：GEOROC is assigned status 'primary' as the frozen data asset while EarthChem is assigned 'discovery' and explicitly described as a federated discovery layer 'not as the primary data store', so GEOROC content reachable via EarthChem is not double-counted as a second independent source; checker confirms primary_source_id='georoc_precompiled' and discovery_source_id='earthchem_portal'. |
| `limitations` | scientific_credibility | 3/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/source_selection.json/decisions/2/reason: 'no DOI, no versioned files, no license and no metadata; no stable source or provenance, rejected.'; MACHINE EVIDENCE REPORT check hash_required: provenance_plan.json path=download_sha256_required actual=True<br>理由：Exclusion on missing provenance is concretely evidenced by the random_web_table rejection for absent DOI/version/license/provenance and by download_sha256_required=true gating. However, no supplied artifact fragment contains an explicit statement that the frozen catalog snapshot is not a successful real-time download, and on_missing_provenance itself is not among the visible evidence fragments, so only the exclusion/demotion half of the criterion is evidenced. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **69.107143**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, domain_understanding
- not_scored 维度：platform_reusability, innovation_ecosystem, open_source_potential

## Q02 — GGA-DATA-002（release/public/Q02）

- 题面哈希：task.md `e8597d3f478357d8…`，task.json `0799d16a4225df6f…`，rubric.json `feba48bc65ef8425…`，grader_spec `aa30526dc6f64679…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `region` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/dataset_decision.json/alternatives/1/reason; inputs/source_catalog.json:sources[gemas].regions<br>理由：gemas entry states 'Region mismatch: GEMAS covers 33 European countries only and cannot serve a conterminous United States soil map', consistent with catalog regions=['europe_33_countries'] and checker gemas_reject pass. |
| `medium` | domain_understanding | 7/7 | 证据：artifacts/run_manifest.json#/benchmark_evidence/dataset_decision.json/alternatives/0/reason; inputs/source_catalog.json:sources[georoc].media<br>理由：georoc entry states 'Medium mismatch: its media are igneous/metamorphic rock, mineral and volcanic glass, not soil', matching catalog media (no soil) and checker georoc_reject pass. |
| `wosis_boundary` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/dataset_decision.json/alternatives/2/decision; artifacts/run_manifest.json#/benchmark_evidence/dataset_decision.json/alternatives/2/reason<br>理由：wosis is kept as supplement_only, not blanket-rejected; reason flags it is not CONUS-specific and that 'available properties and method detail depend on source metadata', i.e., Pb property, method and coverage verification still required, matching catalog note and checker wosis_supplement pass. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **70.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, domain_understanding
- not_scored 维度：platform_reusability, innovation_ecosystem, open_source_potential

## Q03 — GGA-NORM-001（release/public/Q03）

- 题面哈希：task.md `93c9a72ac4d06f46…`，task.json `9da95624ba067215…`，rubric.json `4d48abb607aded79…`，grader_spec `d28b9132da20834e…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `basis_scope` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv: row S01 conversion_rule=ppm_mass_mass_to_mg_per_kg; row S05 conversion_rule=ppb_mass_mass_times_0.001; artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv: rows S01-S06 original_unit in {ppm, mg/kg, wt%, ug/g, ppb, g/kg} all normalized to mg/kg via mass/mass-qualified frozen rules<br>理由：All six rows apply the frozen mass/mass-qualified conversion-rule strings (mass_mass qualifiers on ppm and ppb rules; wt%, ug/g, g/kg are inherently mass/mass units) consistently to solid soil records, encoding that the equivalences hold under the task-fixed solid mass/mass basis; machine report conversion_rules check passed with missing terms=[]. |
| `traceability` | scientific_credibility | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv: header row retains original_value, original_unit, conversion_rule columns; artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv: row S03 (0.012 wt% -> 120 mg/kg via wt_percent_times_10000), row S05 (8000 ppb -> 8 mg/kg via ppb_mass_mass_times_0.001), row S06 (0.4 g/kg -> 400 mg/kg via g_per_kg_times_1000); MACHINE EVIDENCE REPORT: checks original_values and conversion_rules passed (missing terms=[])<br>理由：Every row S01-S06 keeps original_value, original_unit and the frozen conversion_rule alongside normalized_value/normalized_unit, and each normalized value is arithmetically derivable from its row's original value and rule; row-level traceability is complete and consistent with the checker report. |
| `precision` | domain_understanding | 4/4 | 证据：artifacts/run_manifest.json#/benchmark_evidence/normalized_elements.csv: normalized_value cells 42, 18, 120, 35, 8, 400 are exact conversions with no rounding applied; MACHINE EVIDENCE REPORT: checks s01_value..s06_value passed with tol=1e-06<br>理由：All converted values are exact (e.g., 0.012 wt% -> 120, 8000 ppb -> 8, 0.4 g/kg -> 400) with no premature rounding; every cell check passed at absolute tolerance 1e-06, so no order-of-magnitude-distorting rounding occurred. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **84.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential

## Q04 — GGA-NORM-002（release/public/Q04）

- 题面哈希：task.md `e27457777df38eb9…`，task.json `ee7c66e236c14b00…`，rubric.json `00191d11d923a73b…`，grader_spec `ea8bb983380044bc…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `stoichiometry` | scientific_credibility | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/element_database.csv: rows R01,R02 conversion_factor=0.6994307614270416, conversion_rule=fe2o3_to_fe_frozen_mass_fraction; inputs/conversion_constants.json: fe_mass_fraction_in_fe2o3=0.6994307614270416, atomic_weights Fe=55.845 O=15.999, fe2o3_molar_mass=159.687<br>理由：Factor exactly equals frozen stoichiometric mass fraction (2*55.845/159.687); rule name explicitly cites frozen mass fraction and checker 'factor' verified it to 1e-08. |
| `identity` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/element_database.csv: analyte_reported preserved (R01,R02=Fe2O3; R03=Fe; R04=FeO) with distinct rules fe2o3_to_fe_frozen_mass_fraction / identity_element_unit_conversion / empty rule with status=not_requested<br>理由：All three analyte identities retained and never share one rule: Fe2O3 rows converted with frozen factor, Fe row is unit_conversion_only with factor 1, FeO row status=not_requested with empty normalized_value and no factor applied, matching checker key_set/r03/r04 checks. |
| `traceability` | scientific_credibility | 4/4 | 证据：artifacts/run_manifest.json#/benchmark_evidence/element_database.csv: columns analyte_reported,reported_value,reported_unit populated for all rows (R01 Fe2O3/10/wt%; R02 Fe2O3/70000/mg/kg; R03 Fe/5/wt%; R04 FeO/8/wt%)<br>理由：Every output row retains original reported analyte, value, and unit alongside normalized fields; checker 'columns' reports no missing columns. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **84.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential

## Q05 — GGA-PROV-001（release/public/Q05）

- 题面哈希：task.md `5655b9443a2a1604…`，task.json `84fb87c12e0080c5…`，rubric.json `53c79ce590e8352b…`，grader_spec `bc09095478a815cf…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**16/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `integrity` | scientific_credibility | 4/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/verification_report.json: records/0/computed_sha256 = manifest files/0/expected_sha256 (73b952b8...) with sha256_status='match'; artifacts/run_manifest.json#/benchmark_evidence/verification_report.json: records/2/sha256_status='mismatch' with reasons=['sha256_mismatch'], computed 84efbab5... vs inputs/download_manifest.json files/2/expected_sha256 'aaaa...'<br>理由：Records demonstrate byte-level verification against the frozen manifest (match for valid_data.csv, mismatch for tampered.csv), but no explicit statement exists in the evidence paths that hash matching verifies fixed byte content rather than scientific correctness itself; partial credit for behavioral demonstration only. |
| `media` | domain_understanding | 7/7 | 证据：artifacts/run_manifest.json#/benchmark_evidence/verification_report.json: records/1 (filename 'html_as_csv.csv') sha256_status='match' yet media_type_status='html_detected', safe_to_use=false, reasons=['content_is_html_not_csv']<br>理由：html_as_csv.csv carries a .csv extension and even a matching hash, yet is identified as HTML and marked safe_to_use=false, concretely showing the extension does not prove content type and HTML error pages halt processing; consistent with checker html_media_status and html_unsafe passes. |
| `failure_behavior` | engineering_quality | 5/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/verification_report.json: records/1/safe_to_use=false reasons=['content_is_html_not_csv']; artifacts/run_manifest.json#/benchmark_evidence/verification_report.json: records/2/safe_to_use=false reasons=['sha256_mismatch']; artifacts/run_manifest.json#/benchmark_evidence/verification_report.json: only records/0 has safe_to_use=true<br>理由：Both failed assets are explicitly flagged unsafe with retained machine-readable reasons and only the verified CSV is marked safe_to_use=true; no failed download is claimed successful, matching checker html_unsafe and tampered_unsafe passes. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **68.795181**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, domain_understanding
- not_scored 维度：platform_reusability, innovation_ecosystem, open_source_potential

## Q06 — GGA-QC-001（release/public/Q06）

- 题面哈希：task.md `33117e24395f1ee5…`，task.json `65625f416cfe0698…`，rubric.json `08b30955553d7a2b…`，grader_spec `340560441aae9a01…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**17/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `semantic_separation` | domain_understanding | 10/10 | 证据：artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C01 qualifier='<', censored=True, bound_value=0.1, numeric_value empty (left-censored); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C03 numeric_value=0, censored=False (reported zero kept as reported value); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C04 qualifier='>', missing_reason=above_upper_limit, censored=True (right-censored); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C05 missing_reason=not_reported, censored=False, numeric_value empty (unreported); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: rows C02/C06 qualifier=ND/BDL, censored=True, missing_reason empty vs below_detection_limit_unknown_limit<br>理由：Left-censored (C01), right-censored (C04), reported zero (C03), unreported (C05), and ND/BDL (C02/C06) are all separated with the frozen semantic values and correct censored flags; consistent with machine checks c01_bound through c06_unknown_dl, all passed. |
| `no_imputation` | domain_understanding | 4/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C01 numeric_value empty although detection_limit=0.1 (no LOD/2=0.05 substitution); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C06 detection_limit empty with missing_reason=below_detection_limit_unknown_limit (no guessed DL for BDL); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: rows C02/C04/C05 numeric_value empty (no 0 or other fill-in for censored/unreported records)<br>理由：No LOD/2 or 0 substitution anywhere: numeric_value is empty for every censored/unreported record and no detection limit is fabricated for C06. However, the declared evidence (CSV only) contains no statement that substitution would require a separate method and sensitivity analysis, so the explanation half of full_credit is unmet. |
| `analysis_eligibility` | domain_understanding | 3/4 | 证据：artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: eligible_log_analysis=False on rows C01, C02, C04, C05, C06; artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: row C03 numeric_value=0 with censored=False but eligible_log_analysis=False (zero correctly excluded from log analysis despite being a valid reported value); artifacts/run_manifest.json#/benchmark_evidence/parsed_values.csv: censored rows C01/C02/C04/C06 have empty numeric_value, structurally preventing direct log computation<br>理由：Eligibility is correctly encoded for all six records, including the subtle reported-zero case, and emptying numeric_value for censored records blocks direct log use; however, the artifact encodes the classification without a narrative explanation of why these records cannot enter log-anomaly computation, so 1 point is withheld. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **58.470588**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：scientific_credibility, innovation_ecosystem, open_source_potential

## Q07 — GGA-SPATIAL-001（release/public/Q07）

- 题面哈希：task.md `b38a07e71bf17281…`，task.json `e183e1bd57a1b6e6…`，rubric.json `633aec8b52c86ebc…`，grader_spec `d67d29bd3c08c144…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**74/80**
- 机器失败检查（原始原因）：
  - `p02_lat`（domain_understanding）：coordinate_qc.csv key={'record_id': 'P02'} column=qc_flags actual='latitude_out_of_range;possible_lat_lon_swap' expected='latitude_out_of_range' tol=0.0
- LLM rubric：**17/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `non_destructive` | domain_understanding | 7/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/coordinate_qc.csv: row P02 (original_latitude=95, original_longitude=10 retained; suggested_latitude=10, suggested_longitude=95; eligible_map=False); artifacts/run_manifest.json#/benchmark_evidence/coordinate_qc.csv: row P05 (original_latitude=120, original_longitude=35 retained; suggested_latitude=35, suggested_longitude=120; eligible_map=False)<br>理由：Originals are preserved in original_latitude/original_longitude for all rows; swap values appear only in suggested_* columns with flagged rows gated eligible_map=False, so swaps are suggestion-only and held from mapping. 1 point withheld because no artifact explicitly documents routing to human confirmation, and deterministic check p02_lat reports P02's swap flag string as deviating from the expected key. |
| `placeholder` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/coordinate_qc.csv: row P04 (original_latitude=0, original_longitude=0; qc_flags=possible_zero_zero_placeholder; suggested fields empty; eligible_map=False)<br>理由：The 0,0 record is retained (not dropped) with the frozen flag possible_zero_zero_placeholder and eligible_map=False (not auto-accepted); deterministic check p04_placeholder passed, consistent with the artifact row. |
| `conflict` | scientific_credibility | 5/7 | 证据：artifacts/run_manifest.json#/benchmark_evidence/coordinate_qc.csv: rows P07A and P07B (both sample_id=S07 with coordinates 40,-105 and 40,-90; both qc_flags=sample_coordinate_conflict; both eligible_map=False)<br>理由：Both conflicting S07 records are kept, both flagged sample_coordinate_conflict, and both suspended from mapping (eligible_map=False), so no silent single-record pick (checks p07a_conflict, p07b_conflict passed). 2 points withheld because no artifact text states the need to trace back to the source; the CSV contains no explanation field. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **75.544643**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential
- 审计意见 `public_contract_ambiguity`：
  - 检查 `p02_lat`：checker expects qc_flags='latitude_out_of_range' for record P02 (lat=95, lon=10), but the candidate-visible task.md explicitly instructs: 多个 flag 使用分号连接并按字母排序, and gives the example '例如纬度越界且交换后合法时使用 latitude_out_of_range;possible_lat_lon_swap'. P02 is exactly that case (swap -> lat=10, lon=95, both valid), and is structurally identical to P05 (lat=120, lon=35), for which the checker expects the combined flag 'latitude_out_of_range;possible_lat_lon_swap' (check p05_flags, passed). The candidate followed the visible example; the checker's P02 expectation contradicts it. Maintainer decision required: revise task text or checker expectation.

## Q08 — GGA-QC-002（release/public/Q08）

- 题面哈希：task.md `f1427eab6134d8a1…`，task.json `a562b05fc7938e65…`，rubric.json `9ea4bbe360b7d1de…`，grader_spec `7e34af0155f28257…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `identity_model` | platform_reusability | 8/8 | 证据：artifacts/run_manifest.json: benchmark_evidence/observations.csv rows D01 (disposition=kept_original), D03 (kept_replicate), D04 (kept_method_difference), D06 (kept_distinct_sample); artifacts/run_manifest.json: benchmark_evidence/dedup_log.csv row D02->D01 reason=exact_duplicate_import<br>理由：Dispositions cleanly separate the four identity cases: import duplicate D02 removed against D01; lab replicate D03 kept_replicate (same sample_id A1, same method); method difference D04 kept_method_difference (XRF vs ICP-MS); same coordinate 11,21 with different sample_ids B1/B2 kept as kept_original/kept_distinct_sample without merging. Consistent with passed checker checks observation_columns, replicate_kept, method_kept, same_coordinate_samples. |
| `auditability` | engineering_quality | 6/6 | 证据：artifacts/run_manifest.json: benchmark_evidence/dedup_log.csv row removed_raw_row_id=D02, duplicate_of_raw_row_id=D01, reason=exact_duplicate_import; artifacts/run_manifest.json: benchmark_evidence/observations.csv row raw_row_id=D01 (kept_original)<br>理由：The only removed row D02 back-links via duplicate_of_raw_row_id=D01 to a retained row present in observations.csv, with the frozen reason token exact_duplicate_import; checker checks dedup_count and dedup_reason passed. |
| `no_best_value_overreach` | scientific_credibility | 6/6 | 证据：artifacts/run_manifest.json: benchmark_evidence/observations.csv rows D01 (50 mg/kg), D03 (51 mg/kg), D04 (48 mg/kg) all retained as separate records; artifacts/run_manifest.json: benchmark_evidence/dedup_log.csv contains only the exact-duplicate removal D02->D01<br>理由：All multi-method/replicate values (50, 51, 48) are retained as distinct observations with no merged, averaged, or 'best value' selection; the dedup log only documents the exact duplicate removal, matching the task rule that no best value need be chosen. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **84.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential

## Q09 — GGA-NORM-003（evaluator_private/shadow/Q09）

- 题面哈希：task.md `e6b2f04e17fd1d08…`，task.json `e1e5d47b6be539c6…`，rubric.json `821274b0d4c89208…`，grader_spec `6ab7b326667dbbd8…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `media` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/normalized_observations.csv: rows M01,M02,M04,M06 (soil) all normalized_unit='mg/kg' (M04 100 ug/g→100 mg/kg, M06 25000 ug/kg→25 mg/kg); artifacts/run_manifest.json#/benchmark_evidence/normalized_observations.csv: rows M03,M05 (water) normalized_unit='ug/L' (M03 0.02 mg/L→20 ug/L via mg_per_l_times_1000_to_ug_per_l); artifacts/run_manifest.json#/benchmark_evidence/group_summary.csv: soil groups keep 'mg/kg' and water|aqueous|dissolved keeps 'ug/L'; 3 separate groups, no cross-medium merge; consistent with checker checks water_conversion, water_unit, ugkg_conversion (all passed)<br>理由：Solid mass-fraction records stay in mg/kg and water mass-volume records are converted to ug/L; unit spaces remain independent per medium and per-group units are preserved in the summary. |
| `basis` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/normalized_observations.csv: row M02 basis='wet', conversion_rule='identity_mg_per_kg', comparison_group='soil|wet|total' — no wet→dry conversion applied; artifacts/run_manifest.json#/benchmark_evidence/group_summary.csv: 'soil|wet|total,Pb,mg/kg,1,30' exists as a separate group from 'soil|dry|total,Pb,mg/kg,3,25'; consistent with checker check wet_group_separate (passed)<br>理由：The wet-basis record M02 is kept in its own soil|wet|total group with identity conversion instead of being disguised as dry basis without moisture content. |
| `phase` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/normalized_observations.csv: row M05 retains original phase='filtered_dissolved' while comparison_group maps to 'water|aqueous|dissolved'; row M03 phase='dissolved' maps to same family; artifacts/run_manifest.json#/benchmark_evidence/group_summary.csv: 'water|aqueous|dissolved,Pb,ug/L,2,20' (M03=20, M05=20) contains only dissolved-family records; all soil groups remain 'total' — no dissolved/total merge; consistent with checker check dissolved_family (passed)<br>理由：filtered_dissolved is mapped into the dissolved family, original phase values are preserved in the phase column, and dissolved and total phase families are never combined into one comparison group. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **45.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, domain_understanding
- not_scored 维度：scientific_credibility, platform_reusability, innovation_ecosystem, open_source_potential

## Q10 — GGA-INGEST-001（evaluator_private/shadow/Q10）

- 题面哈希：task.md `1ffffa745ee29086…`，task.json `7bf38796165e2e75…`，rubric.json `408a9453c301243b…`，grader_spec `fbeb025907d2aed5…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**18/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `mapping_driven` | platform_reusability | 8/8 | 证据：inputs/field_mapping.json: source_a map (source_record_id<-Record, sample_id<-Sample, latitude<-Latitude, longitude<-Longitude, medium<-Material, Cu<-Cu_ppm unit ppm) and source_b map (source_record_id<-source_key, sample_id<-sample_id, latitude<-lat_dd, longitude<-lon_dd, medium<-medium, Cu<-cu_mgkg unit mg/kg); artifacts/run_manifest.json: benchmark_evidence/observations.csv rows A-001..B-102<br>理由：An explicit per-source field mapping file exists whose target keys match the output schema, and output rows are consistent with it for both divergently named sources (SA1 sample id, -111 longitude, sediment medium, ppm vs mg/kg units), corroborated by passed checker cells a_sample_mapping, a_coord_mapping, b_medium_mapping, b_value_mapping, a_reported_unit; no sign of positional/name guessing. |
| `stable_identity` | scientific_credibility | 5/7 | 证据：artifacts/run_manifest.json: benchmark_evidence/observations.csv columns record_id/source_id/source_record_id (rows A-001, A-002, B-101, B-102); MACHINE EVIDENCE REPORT: checks.record_keys actual keys [('source_a','A-001'),('source_a','A-002'),('source_b','B-101'),('source_b','B-102')]<br>理由：Native record identity is fully embedded (record_id equals source_record_id, no row-number substitution) and source identity is preserved in the adjacent source_id column with non-overlapping A-/B- prefixes, but record_id itself does not explicitly embed source_id (e.g., no 'source_a:A-001' form), so the full-credit condition of both identities inside record_id is only partially met. |
| `traceability` | scientific_credibility | 5/5 | 证据：artifacts/run_manifest.json: benchmark_evidence/observations.csv fields reported_value/reported_unit/normalized_value/normalized_unit on all 4 rows (e.g., A-001: 12 ppm -> 12 mg/kg; B-102: 45 mg/kg -> 45 mg/kg); MACHINE EVIDENCE REPORT: checks.a_reported_unit and checks.normalized_units passed<br>理由：All four rows carry reported value and unit alongside normalized value and unit with no blanks; ppm->mg/kg equivalence per task premise is reflected in normalized_unit, and checker unit checks passed. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **64.833333**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability
- not_scored 维度：domain_understanding, innovation_ecosystem, open_source_potential

## Q11 — GGA-SPATIAL-002（evaluator_private/shadow/Q11）

- 题面哈希：task.md `6cb7bfd64b0d31fe…`，task.json `ba36124d93ea87fd…`，rubric.json `3b6d0be94a80d2bc…`，grader_spec `642984205f2e007c…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `boundary` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv: row G02 (match_status=matched, distance_to_boundary_deg=0.0009999999999994458, match_confidence=low, qc_flags=near_unit_boundary); artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv: row G05 (match_status=ambiguous_boundary, distance_to_boundary_deg=0, unit_id empty, match_confidence=low, qc_flags=near_unit_boundary); inputs/match_policy.json: shared_boundary_behavior='ambiguous_no_assignment', confidence.near_boundary='low', confidence.ambiguous='low'<br>理由：Near-boundary G02 (0.001 deg < 0.01 threshold) stays matched but is downgraded to low with near_unit_boundary; shared-boundary G05 (distance 0) is treated as a distinct ambiguous_boundary case with no unit assigned and low confidence. The two situations are distinguished and neither receives high confidence, matching policy and checker checks g02_boundary/g02_confidence/g05_ambiguous/g05_unit_empty. |
| `precision` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv: row G03 (coordinate_precision_m=2000, match_confidence=low, qc_flags=coordinate_precision_coarse); artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv: row G01 (coordinate_precision_m=100, distance_to_boundary_deg=5, match_confidence=high); inputs/match_policy.json: coarse_coordinate_threshold_m=1000, confidence.coarse_coordinate='low'<br>理由：G03 has 2000 m coordinate precision exceeding the 1000 m coarse threshold and is downgraded to low confidence with coordinate_precision_coarse despite a clean interior distance of 5 deg, while comparable G01 with 100 m precision stays high. Confidence therefore incorporates coordinate precision, not just polygon hit (checker g03_coarse passed). |
| `no_match` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/geologic_matches.csv: row G04 (unit_id empty, match_status=no_match, match_confidence=none, qc_flags empty); inputs/match_policy.json: confidence.no_match='none'<br>理由：Uncovered point G04 is retained as no_match with an empty unit_id and 'none' confidence per policy, with no nearest-unit backfill; consistent with checker checks g04_no_match and g04_unit_empty. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **59.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：scientific_credibility, innovation_ecosystem, open_source_potential

## Q12 — GGA-CONF-001（evaluator_private/shadow/Q12）

- 题面哈希：task.md `ad771ee7fd0178e9…`，task.json `59fcc193dba02325…`，rubric.json `26a9e41bca96c76d…`，grader_spec `54ecfa7c17aeb567…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `transparent_components` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json: benchmark_evidence/confidence.json records[0] components {provenance:25, coordinates:20, analysis:20, sample:15, record_qc:20} sum=100 == confidence_score 100; artifacts/run_manifest.json: benchmark_evidence/confidence.json records[1] components {provenance:15, coordinates:12, analysis:12, sample:10, record_qc:10} sum=59 == confidence_score 59; artifacts/run_manifest.json: benchmark_evidence/confidence.json records[2] components {provenance:5, coordinates:0, analysis:0, sample:5, record_qc:0} sum=10 == confidence_score 10; inputs/confidence_policy.json: provenance/coordinates/analysis/sample/record_qc value tables — every awarded component matches an allowed policy value<br>理由：All five components are present per record and each total is exactly recomputable by summation; component values all map to allowed policy buckets, consistent with machine checks k01_components/k02_components/k0x_score. |
| `threshold` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json: benchmark_evidence/confidence.json records[1] confidence_score=59 with confidence_label='low'; inputs/confidence_policy.json: labels {high_min:80, medium_min:60, low_min:0} — 59 < 60, so frozen threshold yields 'low'; MACHINE EVIDENCE REPORT checks[k02_label]: actual='low' expected='low' passed<br>理由：Score 59 is labeled 'low' exactly per frozen thresholds (medium_min=60); no rounding up to medium occurred, matching the deterministic k02_label check. |
| `not_probability` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json: benchmark_evidence/confidence.json records[0].confidence_is_probability=false; artifacts/run_manifest.json: benchmark_evidence/confidence.json records[1].confidence_is_probability=false; artifacts/run_manifest.json: benchmark_evidence/confidence.json records[2].confidence_is_probability=false; inputs/confidence_policy.json: additive completeness/QC component tables and record_qc penalty scheme define a heuristic, not a calibrated probability model<br>理由：Every record explicitly carries confidence_is_probability=false (machine checks k01_not_probability/k02_not_probability passed), and the scoring structure follows the frozen completeness/QC heuristic policy rather than a probability calibration. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **45.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, domain_understanding
- not_scored 维度：scientific_credibility, platform_reusability, innovation_ecosystem, open_source_potential

## Q13 — GGA-ANOM-001（evaluator_private/shadow/Q13）

- 题面哈希：task.md `2b140447b84497a6…`，task.json `278bf4be3d6692bb…`，rubric.json `df91d26cdc95858b…`，grader_spec `1b79f19c114f1880…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**46/80**
- 机器失败检查（原始原因）：
  - `small_n`（domain_understanding）：eligibility.json path=groups.0.n_total actual=20 expected=19
  - `small_status`（domain_understanding）：eligibility.json path=groups.0.status actual='excessive_censoring' expected='insufficient_sample_size'
  - `censored_fraction`（domain_understanding）：eligibility.json path=groups.1.quantified_fraction actual=1.0 expected=0.65
  - `censored_status`（domain_understanding）：eligibility.json path=groups.1.status actual='insufficient_sample_size' expected='excessive_censoring'
- LLM rubric：**15/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `correct_refusal` | scientific_credibility | 10/10 | 证据：artifacts/run_manifest.json#/benchmark_evidence/eligibility.json/groups/0; artifacts/run_manifest.json#/benchmark_evidence/eligibility.json/groups/1<br>理由：Both groups are refused as scientific endpoints: CENSORED eligible=false status='excessive_censoring' with quantified_fraction=0.65 cited; SMALL eligible=false status='insufficient_sample_size' with n_total=19 cited against policy minimum_n=20; anomaly_scores_written=0 for both. Checker failures (small_n/small_status/censored_fraction/censored_status) are positional: checker expected SMALL at index 0, but by group_id each status and cited value is substantively correct per inputs/eligibility_policy.json. |
| `no_imputation` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/eligibility.json/groups/0<br>理由：CENSORED group reports honest n_quantified=13 of n_total=20 (quantified_fraction=0.65, below policy minimum_quantified_fraction=0.7) and refuses with anomaly_scores_written=0; no substitution of censored values to inflate the fraction to analyzability appears anywhere in the artifact. |
| `next_step` | domain_understanding | 0/5 | 证据：（无证据）<br>理由：No next-step recommendation exists in the evidence artifacts: eligibility.json contains only eligibility fields (eligible, status, n_total, quantified_fraction, anomaly_scores_written) and no text recommending descriptive statistics or additional quantifiable samples. Absence of fabricated anomaly scores is already credited under correct_refusal; the affirmative recommendation required by this criterion is missing. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **63.117647**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, domain_understanding
- not_scored 维度：platform_reusability, innovation_ecosystem, open_source_potential
- 审计意见 `public_contract_ambiguity`：
  - 检查 `small_n, small_status, censored_fraction, censored_status`：checker reads eligibility.json groups positionally (json_path groups.0.* = SMALL, groups.1.* = CENSORED), but neither the candidate-visible task.md nor candidate_visible_contract specifies array element order (the json_shape only requires an array of group objects with group_id). The candidate ordered groups alphabetically [CENSORED, SMALL]; every per-group value is substantively correct per inputs/eligibility_policy.json (SMALL n_total=19 insufficient_sample_size; CENSORED quantified_fraction=0.65 excessive_censoring; both eligible=false, anomaly_scores_written=0). The input CSV happens to list SMALL first, which could be read as an implicit first-appearance-order cue, but no ordering rule is made explicit. Maintainer decision required: publish the ordering rule or key checks by group_id.

## Q14 — GGA-ANOM-002（evaluator_private/shadow/Q14）

- 题面哈希：task.md `f91a34409487e426…`，task.json `e966a0bd1fc6bee1…`，rubric.json `8a55e5f4bf958393…`，grader_spec `92dc46d94da484cc…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `method` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json: benchmark_evidence/group_statistics.csv row group_id=VARIABLE (method=robust_log10_mad, center_log10=1.3010299956639813, scale_log10=0.16893241413011612); artifacts/run_manifest.json: benchmark_evidence/anomalies.csv row record_id=V21 (value=300, robust_z=6.961904055605489); inputs/anomaly_policy.json: transform=log10, center=median, scale=1.4826*MAD, robust_z_threshold=3.5<br>理由：Per-group stats are computed on log10 values (center log10(20)=1.3010299957 = median of log10 background), scale 1.4826*MAD=0.1689324141 per policy, and the anomaly V21 (value 300) is flagged with robust_z 6.96 >= 3.5 relative to its own VARIABLE group background; checker cells variable_center, variable_scale, v21_z, v21_only all passed. |
| `fallback` | domain_understanding | 7/7 | 证据：artifacts/run_manifest.json: benchmark_evidence/group_statistics.csv row group_id=CONSTANT (method=empirical_quantile_fallback, center_log10=0.6989700043360189, scale_log10=0, status=mad_zero_fallback, anomaly_count=0); inputs/anomaly_policy.json: mad_zero_fallback = strict empirical values above p97.5 or below p2.5; ties at threshold are not anomalies<br>理由：CONSTANT group (log10 center 0.69897 = all values equal 5) has scale=0/MAD=0 and uses the frozen empirical_quantile_fallback method per policy with no epsilon or division artifacts, and anomaly_count=0 shows no anomalies were fabricated for the constant group; checker cells constant_fallback and constant_no_anomaly passed. |
| `terminology` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json: benchmark_evidence/anomalies.csv row record_id=V21 column anomaly_type=relative_enrichment; artifacts/run_manifest.json: benchmark_evidence/group_statistics.csv column headers (n, method, center_log10, scale_log10, status, anomaly_count contain no causal claims)<br>理由：The single anomaly is labeled only as relative_enrichment (frozen statistical label) relative to group background; no artifact text infers mineral deposits, genesis, or causes; machine report confirms v21_only check with expected label. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **45.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, domain_understanding
- not_scored 维度：scientific_credibility, platform_reusability, innovation_ecosystem, open_source_potential

## Q15 — GGA-MAP-001（evaluator_private/shadow/Q15）

- 题面哈希：task.md `abbd6d65d0164c10…`，task.json `b2f9fc5a97f254bd…`，rubric.json `2df65f040af927b6…`，grader_spec `5f5fe85351278781…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `traceability` | scientific_credibility | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/points.geojson: features.0.properties (record_id='MAP1', source_id='SRC1', confidence_score=90, qc_flags=[]); artifacts/run_manifest.json#/benchmark_evidence/points.geojson: features.1.properties (record_id='MAP2', source_id='SRC2', confidence_score=75, qc_flags=[])<br>理由：Both features carry record_id, source_id, confidence_score, and qc_flags, enabling record/source back-linkage with QC and confidence retained; feature ids match record_ids. |
| `exclusion` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/map_manifest.json: input_rows=5, mapped_features=2, excluded_rows=3; MACHINE EVIDENCE REPORT checks mapped_features (actual=2 expected=2) and excluded_rows (actual=3 expected=3)<br>理由：Manifest counts all 5 input rows with 2 mapped and 3 excluded (2+3=5), showing invalid rows were excluded but counted rather than hiding them; consistent with checker results. |
| `standard` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/map_manifest.json: coordinate_order='longitude_latitude', crs='CRS84', geojson_crs_member_present=false; artifacts/run_manifest.json#/benchmark_evidence/points.geojson: features.0.geometry.coordinates=[100,10], features.1.geometry.coordinates=[-120,40]; no legacy 'crs' member in FeatureCollection<br>理由：Manifest correctly declares longitude-latitude order and CRS84; coordinates are [longitude, latitude] and the GeoJSON contains no custom crs member, matching checker coordinate_order and no_crs_member passes. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **70.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, domain_understanding
- not_scored 维度：platform_reusability, innovation_ecosystem, open_source_potential

## Q16 — GGA-MAP-002（evaluator_private/shadow/Q16）

- 题面哈希：task.md `979c753b9ccbe12d…`，task.json `b10756219c22bdd1…`，rubric.json `03720acfec8d9ff5…`，grader_spec `42e726a3587764a2…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `density` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/heatmap_config.json: interpretation field; artifacts/run_manifest.json#/benchmark_evidence/heatmap.html: first <p> field descriptions; artifacts/run_manifest.json#/benchmark_evidence/cells.csv: header and rows H001-H003<br>理由：heatmap_config.json interpretation states 'sample_count is sampling density, not concentration'; heatmap.html explicitly defines 'sample_count = number of samples per cell (sampling density, NOT concentration)' separately from 'median_value = median of quantified values in mg/kg'; cells.csv keeps sample_count and median_value as separate columns with consistent values (e.g., H001: 4 samples, median 20). |
| `censoring` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/cells.csv: rows H001 and H003 (censored_fraction, quantified_count vs sample_count); artifacts/run_manifest.json#/benchmark_evidence/heatmap_config.json: layers array and interpretation field; artifacts/run_manifest.json#/benchmark_evidence/heatmap.html: first <p> (censored_fraction definition)<br>理由：Censored values are counted in sample_count and exposed via a dedicated censored_fraction layer (config layers array; html field note) but excluded from the median: H001 censored_fraction=(4-3)/4=0.25 with median 20, H003 (3-1)/3=0.6667 with median 5, matching checker expectations computed on quantified values only; config states 'censored values excluded from median and color scale'. |
| `reproducibility` | engineering_quality | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/heatmap_config.json: aggregation, radius_pixels, color_domain_mg_kg fields; artifacts/run_manifest.json#/benchmark_evidence/cells.csv: precomputed per-cell rows H001-H003; MACHINE EVIDENCE REPORT: checks aggregation_fixed and color_domain passed<br>理由：Config freezes aggregation='precomputed_cell_median', radius_pixels=30, and color_domain_mg_kg=[0,300]; the heatmap renders precomputed cells from cells.csv (html table rows identical to cells.csv), confirmed by passed checker checks aggregation_fixed and color_domain. |

- redline candidates：无
- E1 score_status：**partial**；total_score = **59.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：scientific_credibility, innovation_ecosystem, open_source_potential

## Q17 — GGA-PROV-002（evaluator_private/final_holdout/Q17）

- 题面哈希：task.md `ff90062092ee117d…`，task.json `a99eee5a7d19080c…`，rubric.json `569084631ca46b87…`，grader_spec `7c8ddbd8473fa23c…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**18/20**（grader_uncertainty=medium，human_review_required=true）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `field_consistency` | domain_understanding | 8/10 | 证据：artifacts/run_manifest.json#/benchmark_evidence/provenance_verdict.json: verdicts[0] candidate_id=F-A status=accept reason=metadata_consistent_with_frozen_registry; artifacts/run_manifest.json#/benchmark_evidence/provenance_verdict.json: verdicts[1] candidate_id=F-B status=reject reason=identifier_metadata_conflict; inputs/identifier_registry.json: entries[0] fields doi/dataset_title/authority_url_prefix/allowed_medium<br>理由：Merged from two independent grader runs (A=10, B=8); conservative lower score adopted pending human review. F-B 被判 identifier_metadata_conflict(标识符在注册表但元数据冲突),与 F-C 的 identifier_not_in_frozen_registry 明确区分,说明不是仅做 DOI 字符串存在性匹配,而是将候选元数据与注册表的 title、authority URL、medium 字段做了比对;F-A 的 accept 理由 metadata_consistent_with_frozen_registry 表示与注册表全字段一致,与 MACHINE REPORT 中 b_reject/a_accept 期望值一致。 Grader B withheld full credit because no per-field comparison record exists in the declared evidence, so which specific registry fields conflicted cannot be independently confirmed. |
| `unknown_identifier` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/provenance_verdict.json: verdicts[2] candidate_id=F-C status=reject reason=identifier_not_in_frozen_registry; artifacts/run_manifest.json#/benchmark_evidence/provenance_verdict.json: selected_candidate_id=F-A; inputs/identifier_registry.json: entries 仅含 10.25625/2JETOA 一条记录<br>理由：注册表仅一条冻结记录,F-C 的标识符不在其中,verdict 直接以 identifier_not_in_frozen_registry 拒绝,未被补写、纠正或接受;selected_candidate_id 也未选 F-C,与 MACHINE REPORT c_reject 期望值一致。 |
| `scope_limit` | domain_understanding | 4/4 | 证据：artifacts/run_manifest.json#/benchmark_evidence/provenance_verdict.json: validation_scope=metadata_consistency_only<br>理由：根对象显式声明 validation_scope=metadata_consistency_only,明确本次核验仅限元数据一致性、不证明数据值正确,与 MACHINE REPORT scope check 期望值一致。 |

- redline candidates：无
- 双评（A/B）：分歧 [{"criterion": "field_consistency", "A": 10, "B": 8}]；uncertainty A=low B=medium
- E1 score_status：**partial**；total_score = **68.5**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, domain_understanding
- not_scored 维度：platform_reusability, innovation_ecosystem, open_source_potential

## Q18 — GGA-QC-003（evaluator_private/final_holdout/Q18）

- 题面哈希：task.md `facaaaf6a4e8f2ed…`，task.json `3a9dd3e710583b8b…`，rubric.json `7ed0268be273f0d4…`，grader_spec `e766072977c2aaa7…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**18/20**（grader_uncertainty=medium，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `source_specific` | scientific_credibility | 6/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/decoded_values.csv: row U01 (reported_value=-0.5 -> censored=True, detection_limit=0.5, qualifier='<') and row U02 (reported_value=-9999 -> missing_reason=not_analyzed) apply inputs/encoding_rules.json fields negative_numeric_except_sentinel and not_analyzed_sentinel=-9999 verbatim; inputs/encoding_rules.json: version q18-encoding-1 defines the source-specific negative semantics that the CSV rows follow exactly<br>理由：CSV rows instantiate the task-supplied source rules exactly (DL=absolute value for non-sentinel negatives, sentinel mapped to not_analyzed), showing the negative semantics were treated as source-rule-driven, and no generalization to all databases appears anywhere; however, no explicit written statement attributing the semantics to the source rules exists in the provided evidence, so full credit is not met. |
| `sentinel` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/decoded_values.csv: row U02 reported_value=-9999 has missing_reason=not_analyzed, censored=False, empty detection_limit/numeric_value, eligible_quantitative=False, while row U01 reported_value=-0.5 has censored=True, detection_limit=0.5, qualifier='<'; MACHINE EVIDENCE REPORT checks u02_sentinel and u02_not_eligible both passed<br>理由：-9999 is isolated as a not_analyzed sentinel (not censored, no detection limit) while the non-sentinel negative -0.5 is handled as left-censored with DL=0.5, demonstrating correct separation. |
| `bounds` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/decoded_values.csv: row U01 has bound_value=0.5, qualifier='<', empty numeric_value, eligible_quantitative=False; row U04 has bound_value=1000, qualifier='>', missing_reason=above_upper_limit, empty numeric_value, eligible_quantitative=False; MACHINE EVIDENCE REPORT checks u01_numeric_empty, u04_bound, u04_qualifier all passed<br>理由：Both the lower detection bound (U01) and the upper limit from source code G (U04, converted to '>') are stored only in bound_value with numeric_value left empty and eligible_quantitative=False, so bounds are never treated as exact concentrations; reported values preserved without substitution. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=medium B=medium
- E1 score_status：**partial**；total_score = **77.75**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential

## Q19 — GGA-NORM-004（evaluator_private/final_holdout/Q19）

- 题面哈希：task.md `294996b62f47361d…`，task.json `77de543091a4b3b9…`，rubric.json `c36312060b87eea5…`，grader_spec `59481c51a0e53f6c…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `new_factor` | platform_reusability | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv: row N01 column conversion_factor = 0.7858015005542733, conversion_rule = nio_to_ni_frozen_mass_fraction; inputs/constants.json: ni_mass_fraction_in_nio = 0.7858015005542733 (Ni=58.6934, O=15.999)<br>理由：N01/N02 use factor 0.7858015005542733 exactly matching the frozen NiO mass fraction (Ni/(Ni+O) from NiO formula), with a NiO-specific rule name; no Fe2O3 factor is reused. |
| `identity` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv: row N01/N02 (NiO) status=converted with nio_to_ni_frozen_mass_fraction; artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv: row N03 (Ni) conversion_factor=1, conversion_rule=identity_element_unit_conversion, status=unit_conversion_only, normalized_value=200; artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv: row N04 (Ni2O3) status=not_requested with empty normalized_value/conversion_factor/conversion_rule<br>理由：NiO rows converted with NiO rule; Ni row N03 gets unit conversion only (0.020 wt% -> 200 mg/kg, factor 1); Ni2O3 row N04 left unconverted and marked not_requested. All three identities and rules kept distinct. |
| `precision` | domain_understanding | 4/4 | 证据：artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv: conversion_factor stored at full 16-digit precision 0.7858015005542733; artifacts/run_manifest.json#/benchmark_evidence/nickel_elements.csv: N01 normalized_value=157.16030011085468 (=200*0.7858015005542733) and N02 normalized_value=392.9007502771367 (=500*0.7858015005542733)<br>理由：Frozen constant from inputs/constants.json is used verbatim and multiplied at full double precision before output (verified against machine report n01_value/n02_value checks), with no premature rounding. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=low B=low
- E1 score_status：**partial**；total_score = **59.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：scientific_credibility, innovation_ecosystem, open_source_potential

## Q20 — GGA-SPATIAL-003（evaluator_private/final_holdout/Q20）

- 题面哈希：task.md `da0e068123b88b77…`，task.json `df9804ccc59dc5d7…`，rubric.json `13d6fc9a8cc07df6…`，grader_spec `20c1e5a8a863bc3a…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `minimal_span` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/spatial_manifest.json: bbox=[179.8,-18.0,-179.7,-17.0] with west 179.8 > east -179.7; longitude_span_deg=0.5; crosses_antimeridian=true<br>理由：bbox wraps across the antimeridian (west > east) with longitude_span_deg=0.5, matching the checker bbox/crosses/span checks; this is the minimal span, not a pseudo-global ~359.5-degree bbox. |
| `axis` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/island_points.geojson: features.0.geometry.coordinates=[179.8,-17.0]; features.1.geometry.coordinates=[-179.7,-18.0]; artifacts/run_manifest.json#/benchmark_evidence/spatial_manifest.json: coordinate_order="longitude_latitude"<br>理由：Both GeoJSON point positions are ordered [longitude, latitude], consistent with the declared coordinate_order and the passed checker checks am01_coords, am02_coords, and order. |
| `invalid` | domain_understanding | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/spatial_manifest.json: excluded_count=1; mapped_count=2; artifacts/run_manifest.json#/benchmark_evidence/island_points.geojson: features array contains only the two valid records AM01 and AM02<br>理由：excluded_count=1 and mapped_count=2 match checker expectations; the GeoJSON contains only the 2 features with valid longitudes, showing the invalid record was excluded from the GeoJSON and accounted for in the manifest. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=low B=low
- E1 score_status：**partial**；total_score = **45.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, domain_understanding
- not_scored 维度：scientific_credibility, platform_reusability, innovation_ecosystem, open_source_potential

## Q21 — GGA-QC-004（evaluator_private/final_holdout/Q21）

- 题面哈希：task.md `ba7e7f797df5332e…`，task.json `6c3e3a91f0ac5f19…`，rubric.json `3a550c8c7b80db7f…`，grader_spec `2f74638785e86562…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `all_checks` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json: benchmark_evidence/batch_acceptance.csv row BATCH-2 (crm_pass=False, blank_pass=False, duplicate_pass=False, batch_pass=False, disposition=exclude_batch_and_investigate); artifacts/run_manifest.json: benchmark_evidence/batch_acceptance.csv row BATCH-1 (all three sub-checks True, batch_pass=True); inputs/qc_policy.json: batch_rule=all_checks_must_pass<br>理由：batch_pass is True only where all three QC sub-checks are True (BATCH-1) and False where checks fail (BATCH-2, excluded); no row releases a batch on partial QC success, consistent with policy batch_rule and machine checks b1_pass/b2_batch_fail. |
| `calculations` | domain_understanding | 7/7 | 证据：artifacts/run_manifest.json: benchmark_evidence/batch_acceptance.csv fields crm_recovery_percent=105 and duplicate_rpd_percent=9.523809523809524 (BATCH-1), crm_recovery_percent=135 and duplicate_rpd_percent=40 (BATCH-2); MACHINE EVIDENCE REPORT: checks b1_recovery (actual 105 = expected 105), b1_rpd (actual 9.523809523809524 vs expected 9.5238095238, tol 1e-06), b2_recovery (135), b2_rpd (40) all passed<br>理由：Deterministic checker recomputed recovery and RPD from raw QC rows and every value in batch_acceptance.csv matches within tolerance, including the non-rounded RPD 9.523809523809524 consistent with the RPD formula. |
| `disposition` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json: benchmark_evidence/batch_acceptance.csv row BATCH-2: disposition=exclude_batch_and_investigate with QC values retained (crm_recovery_percent=135, blank_value=8, duplicate_rpd_percent=40); artifacts/run_manifest.json: benchmark_evidence/batch_acceptance.csv row BATCH-1: disposition=accept_for_scientific_analysis<br>理由：Failed BATCH-2 is labeled exclude_batch_and_investigate and its failing QC measurements remain recorded in the row rather than being deleted, while passing BATCH-1 is accepted. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=low B=low
- E1 score_status：**partial**；total_score = **59.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：scientific_credibility, innovation_ecosystem, open_source_potential

## Q22 — GGA-LICENSE-001（evaluator_private/final_holdout/Q22）

- 题面哈希：task.md `c62ec74f2b1137c6…`，task.json `987fe314c4eb33ce…`，rubric.json `c9c7f9fbace83d15…`，grader_spec `511035397b5dc303…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `open_conditions` | scientific_credibility | 7/7 | 证据：artifacts/run_manifest.json#/benchmark_evidence/redistribution_decisions.csv: row L01 (CC-BY-4.0) required_actions='attribution'; artifacts/run_manifest.json#/benchmark_evidence/redistribution_decisions.csv: row L02 (CC-BY-SA-4.0) required_actions='attribution;share_alike'; inputs/license_policy.json: classes.CC-BY-SA-4.0.required_actions=['attribution','share_alike']<br>理由：Open-license rows still carry conditions: L01 keeps attribution and L02 keeps attribution plus share_alike, alphabetically joined with semicolons, exactly matching license_policy.json; checker checks l01_attribution and l02_sharealike passed. |
| `restricted` | domain_understanding | 7/7 | 证据：artifacts/run_manifest.json#/benchmark_evidence/redistribution_decisions.csv: row L03 redistribution_allowed='False', allowed_payload='metadata_and_pointer_only', required_actions='do_not_redistribute_raw;retain_access_controls', confidence_penalty='10'; inputs/license_policy.json: classes.restricted_nonredistributable<br>理由：Restricted source L03 forbids redistribution, limits payload to metadata_and_pointer_only, and retains access controls per required_actions, matching policy values confirmed by checker checks l03_forbidden, l03_payload, l03_penalty. |
| `unknown` | scientific_credibility | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/redistribution_decisions.csv: row L04 license_class='unknown', redistribution_allowed='False', required_actions='license_review_required', confidence_penalty='20'; inputs/license_policy.json: classes.unknown.redistribution_allowed=false, required_actions=['license_review_required']<br>理由：Unknown-license source L04 is not treated as open: redistribution_allowed=False with required action license_review_required routing it to human review and a 20-point confidence penalty, consistent with policy and checker checks l04_unknown, l04_forbidden, l04_penalty. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=low B=low
- E1 score_status：**partial**；total_score = **84.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential

## Q23 — GGA-ANOM-003（evaluator_private/final_holdout/Q23）

- 题面哈希：task.md `3f22571c0f0ddc42…`，task.json `b6c5d66e839b3ecc…`，rubric.json `35cda38a270568d9…`，grader_spec `57d68ecd478ea341…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**18/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `context` | domain_understanding | 8/8 | 证据：artifacts/run_manifest.json#/benchmark_evidence/contextual_anomalies.csv: rows CTX1 (value_mg_kg=50, robust_z=5.228787452803374, relative_enrichment on UNIT-A) and CTX2 (value_mg_kg=50, robust_z=-4.771212547196626, relative_depletion on UNIT-B); artifacts/run_manifest.json#/benchmark_evidence/interpretation.md: paragraph 1 ('relative to each matched geologic unit using that unit's frozen background (center_log10, scale_log10) and a robust |z| >= 3.5 rule'); inputs/backgrounds.json: groups.UNIT-A.center_log10=1.1760912590556813 vs groups.UNIT-B.center_log10=2.1760912590556813<br>理由：Same concentration (50 mg/kg) gets opposite directions under different unit backgrounds, consistent with z signs verified by checker (ctx1_z, ctx2_z); interpretation explicitly conditions on matched unit backgrounds, not global background. |
| `statistical_scope` | domain_understanding | 7/7 | 证据：artifacts/run_manifest.json#/benchmark_evidence/contextual_anomalies.csv: anomaly_type column contains only relative_enrichment/relative_depletion; artifacts/run_manifest.json#/benchmark_evidence/interpretation.md: 'statistical anomalies computed relative to each matched geologic unit' and 'does not establish the presence of an ore deposit, a pollution source, or any causal mechanism'<br>理由：Both artifact and narrative restrict claims to statistical anomalies and relative enrichment/depletion, with no deposit/pollution/mechanism claims; checker limitations check passed with no missing terms. |
| `validation_needs` | domain_understanding | 3/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/interpretation.md: 'Any follow-up requires independent geological, mineralogical or source-appraisal evidence'<br>理由：Interpretation states the need for independent geological/mineralogical/source-appraisal evidence, but omits explicit mention of sampling, analytical, and process evidence named in the full-credit bar; partial credit. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=low B=low
- E1 score_status：**partial**；total_score = **44.673913**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：engineering_quality, domain_understanding
- not_scored 维度：scientific_credibility, platform_reusability, innovation_ecosystem, open_source_potential

## Q24 — GGA-E2E-001（evaluator_private/final_holdout/Q24）

- 题面哈希：task.md `1607983c166c4367…`，task.json `ea829b89ba128537…`，rubric.json `ac5b9f4159b1e7d3…`，grader_spec `a2a0013d5d35b23d…`（完整值见 frozen_identity.json）
- 提交哈希：10 个 artifacts 文件 SHA-256 见 frozen_identity.json
- hard_gate_passed：`True`；redline events：0 条
- machine evidence：**80/80**
- 机器失败检查：无
- LLM rubric：**20/20**（grader_uncertainty=low，human_review_required=false）

| criterion | dimension | score/max | 证据与理由 |
|---|---|---:|---|
| `evidence_chain` | scientific_credibility | 6/6 | 证据：artifacts/run_manifest.json#/benchmark_evidence/sources.jsonl: SRC-A integrity_status='match', downstream_used=true; SRC-B integrity_status='mismatch', downstream_used=false; artifacts/run_manifest.json#/benchmark_evidence/observations.csv: every row carries record_id and source_id columns; all 24 rows link to SRC-A only; artifacts/run_manifest.json#/benchmark_evidence/map.geojson: features.0.properties {record_id:'E01', source_id:'SRC-A'}; all 23 features carry both keys (checker map_traceability missing keys=[]); artifacts/run_manifest.json#/benchmark_evidence/anomalies.geojson: features.0.properties.record_id='E21', source_id='SRC-A', group_id='soil|dry|total|Cu|ICP-MS'<br>理由：Forward/backward links verified: sources.jsonl -> observations.csv source_id -> map/anomaly feature record_id+source_id; E21 value 500 mg/kg identical across observations.csv and map.geojson; censored E22 shown with null value and '<' qualifier in map; checker map_traceability and anomaly_id passed; no SRC-B record entered observations. |
| `scientific_degradation` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/qc_report.json: excluded_integrity_rows=1, censored_rows=1, invalid_coordinate_rows=1, groups_not_scored=['water|aqueous|dissolved|Pb|ICP-MS'], raw_input_rows=25 vs accepted_database_rows=24; artifacts/run_manifest.json#/benchmark_evidence/run_manifest.json: status='partial_success', exit_code=2, warnings list SRC-B exclusion, E22 censoring, E23 invalid coordinate, water-group n below minimum; artifacts/run_manifest.json#/benchmark_evidence/observations.csv: E22 censored=True with empty normalized_value, eligible_anomaly=False; E23 latitude=95, eligible_map=False, qc_flags=latitude_out_of_range; artifacts/run_manifest.json#/benchmark_evidence/map.geojson: no feature for E23 (23 features only); artifacts/run_manifest.json#/benchmark_evidence/summary.md: 'partial success' and each degradation item stated explicitly<br>理由：All four degradations are separately reported and numerically consistent across qc_report, manifest warnings, observations flags and map exclusion, with partial_success/exit_code 2 instead of hidden success. |
| `unit_grouping` | domain_understanding | 4/4 | 证据：artifacts/run_manifest.json#/benchmark_evidence/observations.csv: soil|dry|total|Cu rows reported ppm normalized to mg/kg 1:1 (e.g. E01 20 ppm -> 20 mg/kg); E25 water|aqueous|dissolved|Pb reported 0.02 mg/L -> normalized_value=20, normalized_unit='ug/L'; artifacts/run_manifest.json#/benchmark_evidence/qc_report.json: groups_not_scored contains 'water|aqueous|dissolved|Pb|ICP-MS' (separate group key medium|basis|phase|element|method); artifacts/run_manifest.json#/benchmark_evidence/anomalies.geojson: sole anomaly scored within group_id='soil|dry|total|Cu|ICP-MS' only; artifacts/run_manifest.json#/benchmark_evidence/summary.md: '固体 ppm → mg/kg；水体 mg/L → ug/L；两组不合并'<br>理由：Solid Cu uses ppm->mg/kg and water Pb uses mg/L->ug/L (0.02->20 is the correct x1000 conversion, checker e25_unit passed); the two media form distinct medium|basis|phase|element|method groups and are never merged in scoring or mapping. |
| `anomaly_scope` | domain_understanding | 5/5 | 证据：artifacts/run_manifest.json#/benchmark_evidence/anomalies.geojson: features.0.properties center_log10=1.4771212547196624 (=log10(30), median), scale_log10=0.11739411539020832 (=1.4826*MAD), robust_z=10.408091969133482, n=21, anomaly_type='statistical_relative_enrichment'; artifacts/run_manifest.json#/benchmark_evidence/qc_report.json: anomaly_eligible_rows=21 (=23 soil rows minus censored E22 and invalid-coordinate E23), anomaly_features=1; artifacts/run_manifest.json#/benchmark_evidence/summary.md: '异常只是统计上的相对富集，does not establish 矿床、污染源或任何因果机制'<br>理由：Algorithm parameters are explicit and internally consistent (median log10=1.47712, 1.4826*MAD=0.117394, z=(log10 500-center)/scale=10.4081, n=21>=20; checker anomaly_z/anomaly_type passed), censored and invalid-coordinate rows excluded, and the anomaly is framed strictly as statistical relative enrichment with an explicit no-causality disclaimer. |

- redline candidates：无
- 双评（A/B）：分歧 无；uncertainty A=low B=low
- E1 score_status：**partial**；total_score = **84.0**（partial — 不是完整官方总分（存在 not_scored 维度））
- 已评分维度：scientific_credibility, engineering_quality, platform_reusability, domain_understanding
- not_scored 维度：innovation_ecosystem, open_source_potential

## 跨题汇总（描述性，非总分）

| 题 | task_id | hard gate | machine evidence | LLM | total_score | score_status | 人工复核 |
|---|---|---|---|---|---:|---|---|
| Q01 | GGA-DATA-001 | True | 80/80 | 17/20 | 69.107143 | partial | 否 |
| Q02 | GGA-DATA-002 | True | 80/80 | 20/20 | 70.0 | partial | 否 |
| Q03 | GGA-NORM-001 | True | 80/80 | 20/20 | 84.0 | partial | 否 |
| Q04 | GGA-NORM-002 | True | 80/80 | 20/20 | 84.0 | partial | 否 |
| Q05 | GGA-PROV-001 | True | 80/80 | 16/20 | 68.795181 | partial | 否 |
| Q06 | GGA-QC-001 | True | 80/80 | 17/20 | 58.470588 | partial | 否 |
| Q07 | GGA-SPATIAL-001 | True | 74/80 | 17/20 | 75.544643 | partial | 否 |
| Q08 | GGA-QC-002 | True | 80/80 | 20/20 | 84.0 | partial | 否 |
| Q09 | GGA-NORM-003 | True | 80/80 | 20/20 | 45.0 | partial | 否 |
| Q10 | GGA-INGEST-001 | True | 80/80 | 18/20 | 64.833333 | partial | 否 |
| Q11 | GGA-SPATIAL-002 | True | 80/80 | 20/20 | 59.0 | partial | 否 |
| Q12 | GGA-CONF-001 | True | 80/80 | 20/20 | 45.0 | partial | 否 |
| Q13 | GGA-ANOM-001 | True | 46/80 | 15/20 | 63.117647 | partial | 否 |
| Q14 | GGA-ANOM-002 | True | 80/80 | 20/20 | 45.0 | partial | 否 |
| Q15 | GGA-MAP-001 | True | 80/80 | 20/20 | 70.0 | partial | 否 |
| Q16 | GGA-MAP-002 | True | 80/80 | 20/20 | 59.0 | partial | 否 |
| Q17 | GGA-PROV-002 | True | 80/80 | 18/20 | 68.5 | partial | 是 |
| Q18 | GGA-QC-003 | True | 80/80 | 18/20 | 77.75 | partial | 否 |
| Q19 | GGA-NORM-004 | True | 80/80 | 20/20 | 59.0 | partial | 否 |
| Q20 | GGA-SPATIAL-003 | True | 80/80 | 20/20 | 45.0 | partial | 否 |
| Q21 | GGA-QC-004 | True | 80/80 | 20/20 | 59.0 | partial | 否 |
| Q22 | GGA-LICENSE-001 | True | 80/80 | 20/20 | 84.0 | partial | 否 |
| Q23 | GGA-ANOM-003 | True | 80/80 | 18/20 | 44.673913 | partial | 否 |
| Q24 | GGA-E2E-001 | True | 80/80 | 20/20 | 84.0 | partial | 否 |

- 24 题 E1 total_score 中位数 64.83，最小 44.67，最大 84.00。
- **不得把 24 题 machine evidence points 或 E1 total_score 简单相加称为总分**：每题 total_score 只在单题六维证据内定义，且全部为 `partial`（每题都有维度缺冻结证据：innovation_ecosystem 与 open_source_potential 在所有 24 题均无冻结证据；部分题 scientific_credibility 或 platform_reusability 也缺证据）。
- **不得把本结果称为隐藏集泛化成绩**：Q01–Q24 均为候选可见回归题（shadow / final_holdout 仅为历史回归分组标记），只能作为回归证据。
- 机器证据满分题数：22/24；部分得分题：Q07 (74/80), Q13 (46/80)。
- 硬门禁：24/24 通过；redline events 总计 0；LLM redline candidates 总计 0。
- 需要人工复核：**Q17**（final holdout 双评分歧 field_consistency 10 vs 8，canonical 采用 8）。

## 独立审计清单（不改变候选得分）

### public_contract_ambiguity

- **Q07**（检查 `p02_lat`）：checker expects qc_flags='latitude_out_of_range' for record P02 (lat=95, lon=10), but the candidate-visible task.md explicitly instructs: 多个 flag 使用分号连接并按字母排序, and gives the example '例如纬度越界且交换后合法时使用 latitude_out_of_range;possible_lat_lon_swap'. P02 is exactly that case (swap -> lat=10, lon=95, both valid), and is structurally identical to P05 (lat=120, lon=35), for which the checker expects the combined flag 'latitude_out_of_range;possible_lat_lon_swap' (check p05_flags, passed). The candidate followed the visible example; the checker's P02 expectation contradicts it. Maintainer decision required: revise task text or checker expectation.
- **Q13**（检查 `small_n, small_status, censored_fraction, censored_status`）：checker reads eligibility.json groups positionally (json_path groups.0.* = SMALL, groups.1.* = CENSORED), but neither the candidate-visible task.md nor candidate_visible_contract specifies array element order (the json_shape only requires an array of group objects with group_id). The candidate ordered groups alphabetically [CENSORED, SMALL]; every per-group value is substantively correct per inputs/eligibility_policy.json (SMALL n_total=19 insufficient_sample_size; CENSORED quantified_fraction=0.65 excessive_censoring; both eligible=false, anomaly_scores_written=0). The input CSV happens to list SMALL first, which could be read as an implicit first-appearance-order cue, but no ordering rule is made explicit. Maintainer decision required: publish the ordering rule or key checks by group_id.

### candidate_nonconformance

- 无

### version_uncertain

- 无（候选可见题面与评分源逐文件哈希一致）

## 需要人工复核的事项

1. **Q17**：两次独立 LLM 评审在 `field_consistency`（10 vs 8）与不确定性（low vs medium）上分歧；canonical 已按保守原则取 8 并 human_review_required=true。复核只能依据同一 rubric 和证据，不能添加新维度。
2. **Q07 p02_lat**：可见题面示例与 checker 期望冲突（见审计），由 benchmark 维护者决定修订题面或 checker 期望；本次评分保留 checker 原始失败，未修改 objective report。
3. **Q13 groups 顺序**：checker 位置化读取未在候选可见契约中公开（见审计），由维护者决定公开顺序规则或按 group_id 键控；本次评分保留 checker 原始失败。

## 输出文件清单

```text
/tmp/gga-q01-q24-independent-grade/
  frozen_identity.json
  Qxx-objective_report.json     (x24)
  Qxx-llm_grader_report.json    (x24, canonical)
  Qxx-A/B-llm_grader_report.json (Q17–Q24 双评原件)
  Qxx-score.json                (x24, E1)
  ab_divergences.json
  independent_grading_report.md
  independent_grading_summary.json
```