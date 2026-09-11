# P5 Extended Abstract — Automated profile-type screening and comparability audit of GEOTRACES seawater trace metals

**Status**: pilot complete (2026-08-18, depth stats re-derived from standardized DB, `sample_depth_min_m`); full draft queued.
**Topic origin**: skill discovery candidates dc-009 – dc-011 (T2_method_artifact, seawater).
**Target venues**: Marine Chemistry; Earth System Science Data (data-paper track). Community: GEOTRACES IDP user group.

## Abstract

The GEOTRACES Intermediate Data Product is the reference archive for ocean
trace-metal sections, but its method documentation is fragmented across
originator records, which silently limits cross-cruise pooling. Ingesting
GEOTRACES IDP2025 seawater data into a harmonized schema (18,563 records for
As, Cu, Hg, Ni, Pb, Zn; depth populated on 100% of records), we demonstrate
two automated products. (1) **Profile-type screening**: surface (<100 m) vs
deep (>1000 m) contrasts recover the canonical nutrient-type vertical
structure — deep/surface median ratios Zn 5.57 (0.96 → 5.33 nmol/kg,
n = 1,768/1,754, p < 10⁻²⁸²), Cu 1.91 (n = 2,159/1,293, p < 10⁻¹⁶⁹) and
Ni 1.85 (n = 1,946/1,559, p < 10⁻¹⁹²) — the biological-pump fingerprint
extracted by a survey-agnostic screening statistic with no oceanographic
tuning. (2) **Comparability audit**: the same records fragment into 34
method families (Zn alone spans 23; Ni 25; Cu 13), the largest covering only
37.7% of records, and 7,007 records (37.7%) carry no resolvable method at
all — so the pipeline certifies *zero* multi-family poolable cohorts and
emits the missing-metadata list as a machine-actionable curation task for
originators. The pair of products — automatic recovery of known
oceanography plus an honest, quantified statement of what cannot yet be
pooled — is precisely the intake-QC layer that IDP users currently
hand-build per study.

## Key pilot numbers (frozen snapshot)

| Element | n surface (<100 m) | n deep (>1000 m) | median surface | median deep | deep/surface | Mann–Whitney p |
|---|---|---|---|---|---|---|
| Zn | 1,768 | 1,754 | 0.958 nmol/kg | 5.334 nmol/kg | **5.57** | 6×10⁻²⁸³ |
| Cu | 2,159 | 1,293 | 1.225 nmol/kg | 2.337 nmol/kg | **1.91** | 3×10⁻¹⁷⁰ |
| Ni | 1,946 | 1,559 | 3.742 nmol/kg | 6.921 nmol/kg | **1.85** | 2×10⁻¹⁹³ |

Fragmentation audit: 34 method families total; top family share 37.7%;
records without resolvable method 7,007/18,563; per-element family counts
Zn 23, Ni 25, Cu 13. Poolable multi-family cohorts: **0** (honest state).

## Frontier anchors (four-step comparison)

1. **Anchored citation**: nutrient-type profiles of Zn/Cu/Ni are canonical
   since Bruland (1980, *Earth Planet. Sci. Lett.* 47, 176–198); recovering
   them *automatically* from harmonized records validates the pipeline on
   known ocean science before it claims anything new.
2. **Numerical comparison**: our deep/surface ratios are consistent with
   classical North Pacific profile shapes (order-of-magnitude Zn surface
   depletion); deviations across basins become the follow-up science.
3. **Gap interface**: the audit converts "method metadata is fragmented"
   into a per-record curation queue for BODC/GEOTRACES originators.
4. **Timeliness**: IDP2025 was just released; an independent intake-QC and
   comparability layer serves every downstream user immediately.

## Path to full draft
Split profiles by ocean basin; add scavenged-type contrast (Pb) and
hybrid types; classify all stations into profile types; quantify
inter-cruise offsets within one method family at crossover stations
(GEOTRACES' own crossover QC, reproduced automatically). Estimated: 1–2
analysis days + 1 writing day.
