# GGA Language Library -- reviewed records for the Global Geochemical Atlas papers

Version 1.0 (2026-08-20). One reviewed record per concept, super_library card
shape. Scope: the five GGA manuscripts (P1 European Hg/Pb screening; P2
hemispheric contrast; P3 method-transfer models; P4 arsenic co-located
validation; P5 GEOTRACES audit) and future GGA writing for Science of the
Total Environment (STOTEN), Environmental Science & Technology (ES&T),
Applied Geochemistry, Environment International, Marine Chemistry,
Geostandards and Geoanalytical Research, and Earth System Science Data.

## 0. Loading discipline

This file is the whole library, bounded (< 24 KB); never paste it wholesale
into a draft. Identify the writing task, then read only the matching group:
A. Analytical determination (A1-A5) -- methods/comparability text.
B. Survey media, design, screening framing (B1-B8) -- soil/sediment papers.
C. Statistics (C1-C7) -- results text and captions.
D. Spatial support (D1-D2) -- gridding, co-location, maps.
E. Marine geochemistry (E1-E5) -- the GEOTRACES paper only.
F. Data infrastructure and coined terms (F1-F4) -- all papers.
For titles/abstracts, always load protocols P-T and P-A and run audit P-X
before sign-off. Records license terminology, not citations: reopen the
primary source before making a literature claim. Record shape (fixed): term /
definition / Use / Avoid / Patterns (original {placeholder} templates, never
copied sentences) / Verify in primary sources (real papers, year + venue).

---

## A. Analytical determination

### A1. aqua regia digestion (ISO 11466)
Standardized partial ("pseudo-total") extraction in 3:1 HCl:HNO3; dissolves
carbonate, sulfide and organic phases, leaves refractory silicates intact.
**Use:** Name the standard; say "aqua-regia-extractable" or "pseudo-total".
**Avoid:** Calling aqua-regia results "total"; attributing the extraction to
the instrument.
**Patterns:** {element} was determined by {instrument} after aqua-regia
digestion following {standard}.
**Verify in primary sources:** ISO 11466 (ISO, 1995); GEMAS atlas (Geol.
Jahrbuch, 2014).

### A2. total versus partial (extractable) determination
Total methods (XRF, fusion, HF multi-acid) measure the whole element
inventory; partial extractions recover an operationally defined fraction.
**Use:** Label every concentration with its determination basis.
**Avoid:** Pooling across bases without an explicit transfer model.
**Patterns:** Totals and extractables answer different questions:
{inventory question} versus {mobility question}.
**Verify in primary sources:** De Vos & Tarvainen (eds.), Geochemical Atlas
of Europe Part 2 (GSF, 2006); GEMAS atlas (Geol. Jahrbuch, 2014).

### A3. XRF preparation: fusion versus pressed pellet
Fused beads suppress mineralogical and grain-size effects (preferred for
majors); pressed pellets keep trace sensitivity but inherit matrix effects.
**Use:** State specimen preparation whenever XRF data meet digestion data.
**Avoid:** Treating fusion and pellet XRF as interchangeable at trace level.
**Patterns:** XRF determinations on {fused beads | pressed pellets} were
treated as total concentrations, with {matrix correction} applied.
**Verify in primary sources:** Norrish & Hutton (Geochim. Cosmochim. Acta,
1969); Potts & Webb (J. Geochem. Explor., 1992).

### A4. method family / method metadata
Normalized identifier grouping determinations expected to be comparable --
minimally instrument family plus digestion/preparation.
**Use:** Define the resolution rule once; state how unresolvable methodology
is flagged.
**Avoid:** Instrument alone as the family; silent pooling across families.
**Patterns:** Records were assigned to method families by {rule};
unresolvable methodology was flagged as {flag}, not imputed.
**Verify in primary sources:** Schlitzer et al. (Chem. Geol., 2018);
Wilkinson et al. (Scientific Data, 2016).

### A5. detection limit and below-LOD conventions
The limit of detection (LOD) is the smallest concentration reliably
distinguished from blank; below-LOD values are censored data, often
quantized ("banded") by reporting convention.
**Use:** Report LODs, the below-LOD convention and the censored fraction.
**Avoid:** Undisclosed substitution; reading quantized banding as structure.
**Patterns:** Values below the limit of detection ({LOD} {unit}) were
{convention}; {n} records ({pct}%) were censored.
**Verify in primary sources:** Helsel (Chemosphere, 2006); Helsel,
Nondetects and Data Analysis (Wiley, 2005).

## B. Survey media, design, screening framing

### B1. topsoil/subsoil versus A/C horizon terminology
FOREGS topsoil (0-25 cm) and subsoil (C horizon, 50-200 cm) are depth-plus-
horizon defined; the USGS US survey samples genetic A and C horizons.
Analogous designs, not identical ones.
**Use:** Give depths and horizon labels at first mention; call cross-survey
layer pairs analogous, keeping each survey's own terms.
**Avoid:** "Topsoil" = "A horizon"; "surface soil" without a depth.
**Patterns:** Surface/deep contrasts reference {survey} {surface layer,
depth} to {deep layer, depth} at the same site.
**Verify in primary sources:** Salminen et al. (eds.), Geochemical Atlas of
Europe Part 1 (GSF, 2005); Smith et al. (USGS Data Series 801, 2013).

### B2. catchment outlet sediment (NGSA TOS/BOS)
NGSA medium: floodplain-like sediment near the catchment outlet integrating
the upstream catchment; Top Outlet Sediment (TOS, 0-10 cm) and Bottom Outlet
Sediment (BOS, ~60-80 cm).
**Use:** Define TOS/BOS with depths at first use; state the medium is
transported, not a residual-soil horizon pair.
**Avoid:** Calling outlet sediment "soil"; BOS as pre-industrial baseline.
**Patterns:** {ratio} compares Top Outlet Sediment (0-10 cm) with Bottom
Outlet Sediment ({depth}), a transported, catchment-integrating medium.
**Verify in primary sources:** de Caritat & Cooper (GA Record 2011/20,
2011); de Caritat & Cooper (Geochem. Explor. Environ. Anal., 2016).

### B3. site-paired design
Forming a ratio between two layers at the same location so lithology shared
by both layers cancels to first order; each site is its own control.
**Use:** State the pairing rule and pair counts; add lithogenic controls.
**Avoid:** Claiming pairing removes all pedogenic effects.
**Patterns:** Same-site pairing cancels first-order parent-material
variation; residual redistribution is bounded by the {controls} controls.
**Verify in primary sources:** Geochemical Atlas of Europe Part 2 (GSF,
2006); Reimann & de Caritat (Sci. Total Environ., 2005).

### B4. enrichment factor versus concentration ratio
An enrichment factor (EF) double-normalizes to a reference element and a
crustal composition, inheriting sensitivity to both choices; a direct
same-site concentration ratio avoids both normalizations.
**Use:** Say "concentration ratio" when no reference-element normalization
is applied; justify the departure from EF practice.
**Avoid:** Calling a plain ratio an "enrichment factor"; treating ratio > 1
as automatic proof of anthropogenic input.
**Patterns:** We use direct same-site {surface}/{deep} concentration ratios
rather than crustal-normalized enrichment factors because {reason}.
**Verify in primary sources:** Reimann & de Caritat (ES&T, 2000); Reimann &
de Caritat (Sci. Total Environ., 2005).

### B5. geogenic versus anthropogenic
Geogenic concentrations derive from parent material and natural processes;
anthropogenic from human activity. Separation requires design (controls,
pairing, isotopes), never assertion.
**Use:** Write "consistent with anthropogenic input" for screening evidence.
**Avoid:** "Contamination" for any elevated value; source attribution from a
concentration or ratio alone.
**Patterns:** Ratios above unity indicate {pattern} consistent with
{process}; they are not, by themselves, source attributions.
**Verify in primary sources:** Reimann & Garrett (Sci. Total Environ.,
2005); Matschullat et al. (Environ. Geol., 2000).

### B6. legacy contamination / atmospheric deposition
Legacy contamination is a historically deposited stock persisting after the
causal emissions declined; atmospheric deposition is the input pathway, not
the stock.
**Use:** Tie "legacy" to a time dimension; name the pathway when mechanism
matters.
**Avoid:** Implying ongoing emission from a statement about a stored stock.
**Patterns:** Surface excess of {element} is consistent with industrial-era
atmospheric deposition retained in {horizon or medium}.
**Verify in primary sources:** Steinnes & Friedland (Environ. Rev., 2006);
Marx et al. (Environ. Pollut., 2016).

### B7. screening value
A concentration threshold used to flag samples or cells for further
assessment; jurisdiction- and purpose-specific (soil-As values of 20 and
45 mg/kg span common European guidance ranges, not one regulation).
**Use:** State the thresholds' jurisdictional origin; count exceedances
neutrally.
**Avoid:** "Contaminated" or "safe" from a screening exceedance; "regulatory
limit" without naming regulation and jurisdiction.
**Patterns:** {n} records ({pct}%) exceed the {value} {unit} screening
value; the counts flag {units} for assessment, not regulatory conclusions.
**Verify in primary sources:** Carlon (ed.) (JRC EUR 22805, 2007); Toth et
al. (Environ. Int., 2016).

### B8. screening-level versus regulatory statement
A screening-level statement detects and prioritizes patterns for follow-up;
a regulatory statement asserts compliance or risk under a legal framework.
**Use:** Declare screening scope early; keep verbs at "flag / indicate /
prioritize / consistent with".
**Avoid:** "Risk", "hazard", "non-compliant" in screening outputs.
**Patterns:** All results are screening-level statements about {data basis};
they are not attributions of {source | risk | compliance}.
**Verify in primary sources:** Carlon (ed.) (JRC EUR 22805, 2007); Podgorski
& Berg (Science, 2020).

## C. Statistics

### C1. bootstrap confidence interval of the median
Resampling with replacement to estimate the sampling uncertainty of the
median without distributional assumptions.
**Use:** Report draws, seed, interval method; write "95% bootstrap CI of the
median" so the target statistic is unambiguous.
**Avoid:** Implying an analytic interval; unseeded resampling in a pipeline
claiming determinism.
**Patterns:** Median {statistic} {value} (95% bootstrap CI {lo}-{hi}; {B}
draws, seed {seed}).
**Verify in primary sources:** Efron (Ann. Stat., 1979); Efron & Tibshirani
(Chapman & Hall, 1993).

### C2. Wilcoxon signed-rank test
Nonparametric paired test for a symmetric location shift; on log ratios it
tests whether the typical ratio differs from one.
**Use:** State pairing, sidedness, the null; pair the p-value with an effect
size (median ratio and CI).
**Avoid:** Unpaired data (that is Mann-Whitney); small p read as big effect.
**Patterns:** A two-sided Wilcoxon signed-rank test on log ratios rejected
the null of no shift ({p}); the effect size is the median ratio {value}.
**Verify in primary sources:** Wilcoxon (Biometrics Bull., 1945); Conover
(Wiley, 1999).

### C3. two-sample Kolmogorov-Smirnov test
Compares two empirical cumulative distribution functions; D is the maximum
vertical distance, responding to any distributional difference.
**Use:** Report D and p together; interpret D as magnitude of separation.
**Avoid:** "Distributions identical" from non-rejection; tiny-p emphasis
when D is negligible.
**Patterns:** Two-sample KS tests reject distributional equality (D = {D},
p = {p}); D ranks the separation across {groups}.
**Verify in primary sources:** Massey (J. Am. Stat. Assoc., 1951); Conover
(Wiley, 1999).

### C4. Bland-Altman limits of agreement
Method-comparison standard: difference (or log ratio) of two measurements
against their mean; limits of agreement (LOA) bracket the central 95% of
per-sample differences (nonparametric variant: percentiles).
**Use:** Name the construction; report bias and LOA on a log scale for
ratios; check proportional bias.
**Avoid:** Correlation as evidence of agreement; calling LOA a CI.
**Patterns:** Bland-Altman analysis gives a median offset of {bias} with
nonparametric 95% limits of agreement {lo}-{hi}.
**Verify in primary sources:** Bland & Altman (The Lancet, 1986); Bland &
Altman (Stat. Methods Med. Res., 1999).

### C5. Spearman rank correlation
Correlation on ranks; measures monotone association, robust to monotonic
transforms and outliers.
**Use:** For rank agreement across surveys; report rho, n, p; keep rank
agreement distinct from level agreement (bias).
**Avoid:** Reading rho as absence of bias.
**Patterns:** Rank agreement between {A} and {B} is rho = {value} ({n}
pairs, p = {p}); level agreement is summarized by {ratio statistic}.
**Verify in primary sources:** Spearman (Am. J. Psychol., 1904); Conover
(Wiley, 1999).

### C6. median absolute percentage error (MdAPE)
The median of |predicted - observed| / observed over a test set; robust,
scale-free error score suited to multiplicative data.
**Use:** Define at first use; state median-based and out-of-sample status.
**Avoid:** Confusing MdAPE with MAPE (mean-based).
**Patterns:** Out-of-sample MdAPE is {value}% for the {model}, against
{value}% for the {baseline model}.
**Verify in primary sources:** Hyndman & Koehler (Int. J. Forecasting,
2006).

### C7. power-law transfer model
Log-log linear regression, log Y = a + b log X, relating two determination
bases; b = 1 collapses to a constant factor, so b measures concentration
dependence of the offset.
**Use:** Report a, b, SE(b), r^2; validate out-of-sample; state the domain
of validity (survey pair, concentration range).
**Avoid:** Extrapolating beyond the fitted survey pair; "calibration" when
neither basis is a reference method.
**Patterns:** A power-law transfer (b = {b}, SE {se}) outperforms a constant
factor when |b - 1| exceeds several standard errors.
**Verify in primary sources:** Warton et al. (Biol. Rev., 2006); GEMAS atlas
(Geol. Jahrbuch, 2014).

## D. Spatial support

### D1. co-located cells
Grid cells in which two independent surveys both report an analyte;
agreement within them measures operational reproducibility -- the compound
of method, media, time and sampling effects a data user experiences.
**Use:** State cell size, within-cell statistic, survey independence; call
the resulting agreement "operational".
**Avoid:** Calling either survey "ground truth" or a reference standard.
**Patterns:** In {n} co-located {size} cells, {survey A} and {survey B}
agree to {level statistic} at the median, with rank agreement rho = {value}.
**Verify in primary sources:** Podgorski & Berg (Science, 2020); GEMAS atlas
(Geol. Jahrbuch, 2014).

### D2. spatial support and aggregation scale (MAUP)
The support is the area or volume a value represents; statistics on
aggregated units change with cell size and zoning -- the modifiable areal
unit problem (MAUP).
**Use:** Declare cell size as a design parameter and sweep it; state which
conclusions are scale-robust.
**Avoid:** One grid scale presented as canonical without sensitivity.
**Patterns:** Results are reported at {scale}; a sweep over {range} shows
{conclusions} are robust to the aggregation choice.
**Verify in primary sources:** Openshaw (CATMOG 38, Geo Books, 1984); Gotway
& Young (J. Am. Stat. Assoc., 2002).

## E. Marine geochemistry

### E1. nutrient-type vertical profile
The canonical biologically shaped dissolved-metal distribution: depleted at
the surface by uptake, enriched at depth by remineralization; classic for
Zn, Cd, Ni.
**Use:** Define "surface" and "deep" by depth cutoffs; keep one spelling
("nutrient-type") per manuscript.
**Avoid:** Inferring mechanism from a two-depth contrast alone.
**Patterns:** {element} shows a nutrient-type distribution: depleted above
{z1} m, enriched below {z2} m (deep/surface ratio {value}).
**Verify in primary sources:** Bruland (Earth Planet. Sci. Lett., 1980);
Bruland, Middag & Lohan (Treatise on Geochemistry 2nd ed., 2014).

### E2. remineralization
Release of dissolved constituents at depth as sinking biogenic particles are
respired or dissolved; the standard mechanism term for deep enrichment of
nutrient-type elements.
**Use:** "Remineralized {element}" for the deep-accumulated fraction; tie
inter-basin gradients to water-mass age along the overturning circulation.
**Avoid:** Implying instantaneous local balance between export and release.
**Patterns:** Deep {basin} waters, older along the overturning circulation,
accumulate more remineralized {element} than {comparison basin}.
**Verify in primary sources:** Morel & Price (Science, 2003); Sarmiento &
Gruber (Princeton Univ. Press, 2006).

### E3. scavenging and hybrid-type metals (Cu)
Scavenging is removal of dissolved metal onto sinking particle surfaces;
hybrid-type metals such as Cu combine nutrient-type recycling with
reversible scavenging, flattening deep gradients.
**Use:** Reserve "hybrid" for the recognized category; invoke it for Cu's
departures from pure nutrient-type behaviour.
**Avoid:** Labeling Cu "scavenged-type" (that category is Al, Mn, Pb).
**Patterns:** The absence of {expected deep-water pattern} for Cu is
consistent with its hybrid character: remineralization overprinted by
reversible scavenging.
**Verify in primary sources:** Bruland & Lohan (Treatise on Geochemistry 1st
ed., 2003); Morel & Price (Science, 2003).

### E4. biological pump
The ensemble of processes exporting biologically fixed carbon and associated
elements from the surface ocean to depth, setting vertical gradients of
nutrient-type constituents.
**Use:** As context for nutrient-type profiles; name the specific limb
(uptake, export, remineralization) doing the work.
**Avoid:** Attributing a metal profile to "the pump" without that chain.
**Patterns:** Surface depletion of {element} reflects uptake and export by
the biological pump, with {ratio} enrichment at depth.
**Verify in primary sources:** Volk & Hoffert (AGU Geophys. Monogr. 32,
1985); Boyd et al. (Nature, 2019).

### E5. GEOTRACES IDP, crossover stations, intercalibration
The Intermediate Data Product (IDP) is GEOTRACES' periodic community-
quality-controlled release; crossover stations are locations occupied by two
or more cruises for consistency checks; intercalibration is the programme
protocol for consistent numbers across laboratories.
**Use:** Cite the specific IDP release; credit programme QC when auditing
metadata; use crossovers as the ocean analogue of same-sample pairs.
**Avoid:** Implying IDP data are unvetted; drifting to "intercomparison".
**Patterns:** Crossover-station agreement provides the ocean analogue of
same-sample method pairs and could be expressed as {transfer construct}.
**Verify in primary sources:** Schlitzer et al. (Chem. Geol., 2018); Cutter
(Limnol. Oceanogr. Methods, 2013).

## F. Data infrastructure and coined terms

### F1. harmonization versus pooling versus poolability
Harmonization places records in one schema (units, coordinates, media,
method metadata); pooling analyzes multi-source records as one population;
poolability is the demonstrated condition -- shared method family or a
validated transfer model -- under which pooling is defensible.
**Use:** Keep the three words distinct; "harmonized but not poolable" is a
legitimate, reportable state.
**Avoid:** Letting "harmonized" imply poolable.
**Patterns:** Records are harmonized into one schema; pooling across {axis}
additionally requires {condition}.
**Verify in primary sources:** GEMAS atlas (Geol. Jahrbuch, 2014); Smith et
al. (USGS Data Series 801, 2013).

### F2. provenance hash / frozen snapshot
A content hash (e.g., SHA-256) linking each record to its exact source file,
and a fixed, hash-identified dataset state ("frozen snapshot") from which
all published numbers regenerate.
**Use:** Give snapshot identifier, script, and seed together.
**Avoid:** "Fully reproducible" without the snapshot-script-seed triple.
**Patterns:** All numbers regenerate deterministically from snapshot {id}
via {script} (seed {seed}).
**Verify in primary sources:** Wilkinson et al. (Scientific Data, 2016);
Stall et al. (Nature, 2019).

### F3. validation desert -- COINED TERM, paper-defined
GGA-coined term for regions where no two independent surveys overlap, so no
co-located validation cell can be formed there. Paper-defined, not
field-standard: every manuscript using it must define it explicitly and
operationally at first use (italicized), before any title/abstract use.
**Use:** Only after the first-use definition; keep the operational meaning
(absence of independent survey overlap).
**Avoid:** Using it as if established; stretching it to mean "sparsely
sampled" (that is sparsity, not a desert).
**Patterns:** We term regions where no independent survey pair overlaps --
so no validation cell can be formed -- a {emphasized term}.
**Verify in primary sources (motivating context, not the term):** Podgorski
& Berg (Science, 2020) -- the ground-truth scarcity the term names.

### F4. disagreement queue -- COINED TERM, paper-defined
GGA-coined term for the automatically generated, provenance-linked list of
co-located cells (or records) failing a stated agreement criterion, ordered
as re-sampling or curation priorities. Paper-defined, not field-standard:
requires explicit first-use definition giving criterion and consumer.
**Use:** State criterion (e.g., outside factor-two agreement), ordering, and
consumer (survey planners, data stewards).
**Avoid:** Bare use in a title without an abstract-level definition; "queue"
phrasing implying a maintained service when the artifact is static.
**Patterns:** Cells outside {criterion} form a {emphasized term}: a
provenance-linked priority list for {consumer}.
**Verify in primary sources (motivating context, not the term):** Bland &
Altman (The Lancet, 1986); Cutter (Limnol. Oceanogr. Methods, 2013).

---

## P-T. TITLE protocol (chemistry / geochemistry journals)

Calibration: STOTEN and ES&T titles are declarative or design-revealing and
name element, medium and scale ("A spatial assessment of mercury content in
the European Union topsoil", STOTEN 2021; "Climate and vegetation as primary
drivers for global mercury storage in surface soil", ES&T 2019); Applied
Geochemistry and Marine Chemistry favor plain topic-plus-design statements.

1. Name the element(s), the medium, and the scale or region.
2. Prefer a declarative finding or design-revealing description; a
   "finding: design" colon construction is accepted in all target venues.
3. Match verb strength to the evidence tier: a screening study says "not
   detected" / "screening of", never "absent" / "proof of".
4. No hype words: novel, unprecedented, first-ever, paradigm.
5. No computer-science compounds ("X-aware", decorative "X-driven"); use the
   field's own modifiers (method-stratified, site-paired, harmonized).
6. Universal method acronyms (XRF, ICP-MS) are acceptable; survey acronyms
   (FOREGS, GEMAS, NGSA) belong in the abstract; GEOTRACES stands alone.
7. Aim for about 20 words or fewer; cut articles before content words.
8. A coined term may appear in a title only if it is the paper's named
   product and is defined in the abstract.

## P-A. ABSTRACT protocol (chemistry / geochemistry journals)

Calibration: ES&T and STOTEN abstracts are single-paragraph, quantitative,
self-contained (~150-300 words); medium, element and scale appear in the
first two sentences; headline numbers carry n and uncertainty. Marine
Chemistry and Applied Geochemistry tolerate more methodological detail.

1. Sentences 1-2: problem, medium, element(s), scale.
2. Quantitative: every headline claim carries its number with n and CI;
   include the key control or negative result too.
3. Define every acronym at first use; none defined but never reused.
4. No hype: novel, unprecedented, paradigm-shifting banned; "first" only
   with "to our knowledge" and a defensibly narrow scope.
5. State the evidence tier (screening-level, operational agreement, method
   transfer) in the abstract itself.
6. No citations in the abstract unless the venue requires them.
7. Every number in the abstract must exist identically in the results.
8. Close with reproducibility or availability if the venue allows it.

## P-X. 12-item overclaim / translationese audit checklist

Run over title, abstract, and any edited paragraph before sign-off.

1. Every "significant" is statistical with the test named nearby -- or
   replaced.
2. No p-value described with a size adjective ("enormous p"); significance
   and effect size reported separately.
3. Claim verbs match the evidence tier: screening results flag / indicate /
   are consistent with; never prove, confirm risk, or attribute source.
4. No "total" for extractable determinations; determination basis named
   wherever two bases could be confused.
5. Coined terms italicized and operationally defined at first use; never in
   title or abstract before that definition (F3-F4).
6. No software or agent register: ship, mint, hand-build, first-class,
   guardrail, unsafe (for data). "Emit" only for described pipeline outputs.
7. No anthropomorphic tics ("honest" data, databases that "complain");
   replace with certified, explicit, quantified.
8. Translationese scan: "researches show", "more and more", "obviously",
   doubled intensifiers, noun strings a preposition would fix.
9. Every comparative names its comparator and metric; no bare "better /
   stronger / more robust".
10. Absence claims phrased as "not detected" with power or CI context; a
    null is a bounded statement, not proof of absence.
11. LaTeX: ranges use --, degrees use $^\circ$, % and & escaped, units
    upright; one spelling variant (US or UK) per manuscript.
12. Acronym hygiene: defined at first use in abstract and again in body;
    none defined-but-unused; none used-but-undefined.

---
End of library. 31 reviewed records (A1-A5, B1-B8, C1-C7, D1-D2, E1-E5,
F1-F4) + 2 section protocols + 1 audit checklist. ASCII-only by design.
