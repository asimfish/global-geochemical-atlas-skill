# P4 Extended Abstract — Independent cross-survey validation points for global arsenic screening from harmonized open data

**Status**: pilot complete (2026-08-18, `p345_pilots.py`, deterministic); full draft queued.
**Topic origin**: skill anomaly-detection outputs (As hotspot replication) + coverage products.
**Target venues**: Environment International; Water Research; Applied Geochemistry. Conferences: Goldschmidt, EGU (geochemistry & health sessions).

## Abstract

Machine-learning global arsenic risk maps (e.g. Podgorski & Berg 2020,
*Science* 368, 845–850) explicitly call for more independent ground-truth
measurements. We show that harmonized open continental surveys can supply a
quality-controlled, provenance-chained validation point set at near-zero
marginal cost. Within a 191,715-record harmonized database we identify
0.1°-grid cells where two *independent* European surveys (GEMAS agricultural
soils, 2008+ sampling, ICP-MS; FOREGS soils, 1997–2001 sampling) both report
As: n = 26 co-located cells. Despite different decades, media details and
laboratories, the surveys agree strongly: Spearman ρ = 0.681
(p = 1.3×10⁻⁴), median GEMAS/FOREGS ratio 0.982 — independent replication
to within 2% at the median. Both surveys jointly confirm elevated cells
(2 cells above 20 mg/kg in both; 1 above 45 mg/kg in both), and the
screening layer flags 688 of 8,979 harmonized soil-As records (7.7%) above
20 mg/kg and 162 (1.8%) above 45 mg/kg. One strongly divergent cell
(47.6°N, 2.3°W, Brittany: GEMAS 208.5 vs FOREGS 59.5 mg/kg) illustrates the
second product: an automatically generated *disagreement list* that
prioritizes re-sampling. Deliverable: a confidence-scored validation point
set + disagreement list, published as machine-readable layers for risk-map
builders.

## Key pilot numbers (frozen snapshot)

- Co-located 0.1° cells (GEMAS × FOREGS, As): **26**
- Spearman ρ = **0.681**, p = 1.3×10⁻⁴; median ratio GEMAS/FOREGS = **0.982**
- Joint exceedance: **2** cells both > 20 mg/kg; **1** cell both > 45 mg/kg
- Harmonized soil-As screening: 8,979 records; **688 > 20 mg/kg (7.7%)**, **162 > 45 mg/kg (1.8%)**
- Largest disagreement: 47.6°N 2.3°W — GEMAS 208.5 vs FOREGS 59.5 mg/kg (re-sampling priority)
- Thresholds are screening values spanning common European guidance ranges, not regulatory conclusions.

## Frontier anchors (four-step comparison)

1. **Anchored citation**: Podgorski & Berg (2020) state their global
   groundwater-As hazard model is limited by sparse independent validation
   data; our point set is exactly that (soil pathway complement).
2. **Numerical comparison**: cross-survey agreement (ρ 0.68, ratio 0.98)
   quantifies the reliability of open surveys as validation sources —
   a number neither survey can produce alone.
3. **Gap interface**: the disagreement list (Brittany-type cells) is a
   machine-actionable re-sampling queue; joint-coverage maps show where no
   independent validation exists (most of the globe).
4. **Timeliness**: WHO/UNICEF arsenic exposure programs and EU soil-health
   monitoring both need third-party validation layers now.

## Path to full draft
Add US NGDB co-location panel; formalize the validation-point schema
(value, CI, method family, provenance hash); produce global joint-coverage
map; quantify how many risk-map grid cells gain a validation point.
Estimated: 1 analysis day + 1 writing day.
