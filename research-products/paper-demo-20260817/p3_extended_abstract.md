# P3 Extended Abstract — Same-sample inter-method offsets in continental soil surveys: quantification and transfer models from harmonized open data

**Status**: pilot complete (2026-08-18, `p345_pilots.py`, deterministic); full draft queued.
**Topic origin**: skill discovery candidates dc-012 – dc-016 (T2_method_artifact tier).
**Target venues**: Environmental Science & Technology; Geostandards and Geoanalytical Research. Conferences: Goldschmidt (data quality / analytical geochemistry sessions).

## Abstract

Continental soil surveys routinely report the same element measured by two
analytical routes on the same physical samples, yet downstream users pool the
numbers as if they were one population. Using a harmonized 191,715-record
open geochemical database, we quantify same-sample offsets between X-ray
fluorescence (XRF, total) and inductively coupled plasma mass spectrometry
(ICP-MS, aqua-regia digestion) across the full GEMAS agricultural-soil
survey (n = 2,224 paired samples per element), with an independent
replication on FOREGS soils (XRF vs ICP-OES, n = 417–420). Median XRF/ICP
ratios are element-specific and large: Cr 2.94 (IQR 2.37–3.66), Zn 1.34,
Pb 1.29, Ni 1.27, As 1.23 — and direction-reversing for Cu (0.86), which
rules out any single instrument-bias explanation and is consistent with
element-wise digestion completeness and matrix effects. FOREGS reproduces
the Cr artifact at 2.54 (topsoil) and 2.50 (subsoil). Log-log regressions
have slopes of 0.74–1.00 (r² 0.65–0.93), i.e. offsets are
concentration-dependent, so a single correction factor is insufficient; we
fit per-element power-law transfer functions instead. The practical outputs
are (i) a transfer-model table that makes "zero multi-source poolable
cohorts" — the honest current state of cross-survey comparability — into
conditionally poolable data with quantified uncertainty, and (ii) a minimum
method-metadata standard for future surveys.

## Key pilot numbers (frozen snapshot `retest-acquisition-coverage-v12-6c221cf`)

| Survey | Pair | Element | n same-sample | median ratio | IQR | log-log slope | r² |
|---|---|---|---|---|---|---|---|
| GEMAS | XRF / ICP-MS (aqua regia) | Cr | 2,224 | 2.942 | 2.366–3.660 | 0.849 | 0.805 |
| GEMAS | XRF / ICP-MS | Zn | 2,224 | 1.342 | 1.250–1.486 | 0.837 | 0.833 |
| GEMAS | XRF / ICP-MS | Pb | 2,224 | 1.288 | 1.108–1.628 | 0.735 | 0.647 |
| GEMAS | XRF / ICP-MS | Ni | 2,224 | 1.269 | 1.146–1.486 | 0.909 | 0.925 |
| GEMAS | XRF / ICP-MS | As | 2,224 | 1.228 | 1.058–1.435 | 0.830 | 0.815 |
| GEMAS | XRF / ICP-MS | Cu | 2,224 | **0.864** | 0.742–0.973 | 1.000 | 0.863 |
| FOREGS topsoil | XRF / ICP-OES | Cr | 420 | 2.537 | 2.093–3.163 | 0.938 | 0.805 |
| FOREGS subsoil | XRF / ICP-OES | Cr | 417 | 2.500 | 2.036–3.160 | 0.891 | 0.864 |
| FOREGS topsoil | XRF / ICP-OES | Zn | 420 | 1.091 | 1.000–1.198 | 1.131 | 0.906 |
| FOREGS subsoil | XRF / ICP-OES | Zn | 417 | 1.075 | 0.982–1.179 | 1.261 | 0.915 |

Interpretation guardrail: GEMAS ICP-MS values follow aqua-regia digestion
(partial for refractory phases), XRF is total — so the "artifact" is a
digestion/matrix effect, not an instrument defect; the Cu reversal and the
non-unit slopes are the scientifically interesting content.

## Frontier anchors (four-step comparison)

1. **Anchored citation**: the Minamata OESG 2025 soil chapter states survey
   data "cannot be compared across surveys" — this paper turns that
   qualitative warning into per-element, per-pair transfer functions.
   The EU Soil Monitoring Law's cross-border comparability provisions
   need exactly this quantification layer.
2. **Numerical comparison**: GEMAS project publications (Reimann et al.)
   document aqua-regia vs total discrepancies qualitatively; our
   contribution is the full 6-element same-sample matrix with uncertainty
   and concentration dependence, replicated across two surveys.
3. **Gap interface**: the harmonized database currently has zero
   multi-source poolable cohorts; transfer functions + minimum metadata
   standard are the concrete unlock.
4. **Timeliness**: EU SML implementation acts (2026–) will require
   harmonized soil indicators across member states.

## Path to full draft
Extend matrix to all 7 elements where pairs exist; add covariate analysis
(pH, clay proxies where available); propose the minimum metadata standard as
a table; validate transfer functions out-of-sample (GEMAS to FOREGS
transfer). Estimated: 1 analysis day + 1 writing day with the P1/P2
template.
