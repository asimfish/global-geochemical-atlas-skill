# P3/P4/P5 pilots on the frozen snapshot. Deterministic (seeded where sampling used).
# P3: same-sample inter-method offsets (ICP vs XRF) per element per survey.
# P4: cross-survey As co-location checks (GEMAS x FOREGS) + exceedance screening.
# P5: GEOTRACES nutrient-type vertical profiles + method-family fragmentation audit.
import json
import numpy as np
import pandas as pd
from scipy import stats
import os
# Data root for the paper demo; override with GGA_HACKATHON_ROOT when reproducing.
ROOT = os.environ.get("GGA_HACKATHON_ROOT", os.path.expanduser("~/hackathon"))

DB = ROOT + '/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
OUT = ROOT + '/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/p345_results.json'
RNG = np.random.default_rng(20260818)

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0)]
res = {'P3_method_offsets': {}, 'P4_arsenic': {}, 'P5_geotraces': {}}

# ---------------- P3: same-sample method offsets ----------------
def method_offset(src_ids, sample_types, el, mfa, mfb):
    d = df[df.source_id.isin(src_ids) & df.sample_type.isin(sample_types)
           & (df.element_or_analyte == el)]
    a = d[d.method_family == mfa].groupby('sample_id').normalized_value.median()
    b = d[d.method_family == mfb].groupby('sample_id').normalized_value.median()
    j = pd.concat([a.rename('a'), b.rename('b')], axis=1, join='inner').dropna()
    if len(j) < 30:
        return None
    r = (j.b / j.a).values  # b relative to a
    lr = np.log(r)
    slope, intercept, rval, _, _ = stats.linregress(np.log(j.a), np.log(j.b))
    return dict(n_samples=int(len(j)), median_ratio=round(float(np.median(r)), 3),
                iqr=[round(float(np.percentile(r, 25)), 3), round(float(np.percentile(r, 75)), 3)],
                log_log_slope=round(float(slope), 3), log_log_r2=round(float(rval ** 2), 3))

for el in ['As', 'Cr', 'Cu', 'Ni', 'Pb', 'Zn']:
    o = method_offset(['gemas-ap', 'gemas-gr', 'gemas'], ['soil_agricultural_ploughed', 'soil_grazing_land'],
                      el, 'icp_ms', 'xrf')
    if o is None:
        # fall back: any gemas-like source id
        gem_src = [s for s in df.source_id.unique() if 'gemas' in str(s)]
        o = method_offset(gem_src, list(df[df.source_id.isin(gem_src)].sample_type.unique()), el, 'icp_ms', 'xrf')
    if o:
        res['P3_method_offsets'][f'GEMAS_{el}_xrf_over_icpms'] = o
for el in ['Cr', 'Zn', 'Pb', 'Ni', 'Cu', 'As']:
    for st_ in ['soil_topsoil', 'soil_subsoil']:
        o = method_offset(['foregs-topsoil', 'foregs-subsoil'], [st_], el, 'icp_oes', 'xrf')
        if o:
            res['P3_method_offsets'][f'FOREGS_{st_}_{el}_xrf_over_icpoes'] = o

# ---------------- P4: arsenic cross-survey co-location ----------------
gem_src = [s for s in df.source_id.unique() if 'gemas' in str(s)]
as_gem = df[df.source_id.isin(gem_src) & (df.element_or_analyte == 'As')
            & df.latitude.notna()].copy()
as_for = df[df.source_id.isin(['foregs-topsoil', 'foregs-subsoil'])
            & (df.element_or_analyte == 'As') & df.latitude.notna()].copy()
for d in (as_gem, as_for):
    d['cell'] = d.latitude.round(1).astype(str) + '_' + d.longitude.round(1).astype(str)
g = as_gem.groupby('cell').normalized_value.median()
f = as_for.groupby('cell').normalized_value.median()
j = pd.concat([g.rename('gemas'), f.rename('foregs')], axis=1, join='inner').dropna()
lr = stats.spearmanr(j.gemas, j.foregs)
soil_as = df[(df.element_or_analyte == 'As') & df.sample_type.astype(str).str.startswith('soil')
             & df.latitude.notna()]
res['P4_arsenic'] = {
    'colocated_0p1deg_cells': int(len(j)),
    'spearman_rho': round(float(lr.statistic), 3),
    'spearman_p': float(lr.pvalue),
    'median_gemas_over_foregs': round(float((j.gemas / j.foregs).median()), 3),
    'both_gt20_cells': int(((j.gemas > 20) & (j.foregs > 20)).sum()),
    'both_gt45_cells': int(((j.gemas > 45) & (j.foregs > 45)).sum()),
    'soil_as_records': int(len(soil_as)),
    'soil_as_gt20': int((soil_as.normalized_value > 20).sum()),
    'soil_as_gt45': int((soil_as.normalized_value > 45).sum()),
    'top_colocated_cells': [
        dict(cell=c, gemas=round(float(j.loc[c, 'gemas']), 1), foregs=round(float(j.loc[c, 'foregs']), 1))
        for c in (j.gemas + j.foregs).sort_values(ascending=False).head(5).index
    ],
}

# ---------------- P5: GEOTRACES profiles + fragmentation ----------------
gt = df[(df.source_id == 'geotraces-idp2025') & df.normalized_value.notna()].copy()
depth_col = None
for c in ['depth_m', 'depth', 'sample_depth_m']:
    if c in gt.columns and gt[c].notna().any():
        depth_col = c
        break
p5 = {'records': int(len(gt)), 'depth_column': depth_col}
if depth_col:
    gt = gt[gt[depth_col].notna()]
    for el in ['Zn', 'Cu', 'Ni', 'Pb']:
        d = gt[gt.element_or_analyte == el]
        surf = d[d[depth_col] < 100].normalized_value
        deep = d[d[depth_col] > 1000].normalized_value
        if len(surf) > 50 and len(deep) > 50:
            u = stats.mannwhitneyu(surf, deep, alternative='two-sided')
            p5[el] = dict(n_surface=int(len(surf)), n_deep=int(len(deep)),
                          median_surface=round(float(surf.median()), 4),
                          median_deep=round(float(deep.median()), 4),
                          deep_over_surface=round(float(deep.median() / surf.median()), 2),
                          mannwhitney_p=float(u.pvalue))
mf = gt.method_family.fillna('(missing)')
p5['method_families_total'] = int(mf.nunique())
p5['records_missing_method'] = int((mf == '(missing)').sum())
p5['top_method_share'] = round(float(mf.value_counts(normalize=True).iloc[0]), 3)
for el in ['Zn', 'Cu', 'Ni']:
    p5[f'{el}_method_families'] = int(gt[gt.element_or_analyte == el].method_family.fillna('(missing)').nunique())
res['P5_geotraces'] = p5

with open(OUT, 'w') as fh:
    json.dump(res, fh, indent=1)
print(json.dumps(res, indent=1)[:4000])
print('p345 done ->', OUT)
