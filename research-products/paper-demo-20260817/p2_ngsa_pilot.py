# P2 pilot: Southern-Hemisphere legacy fingerprint replication.
# Australia NGSA catchment-outlet sediment, top (0-10 cm) vs bottom (~60-80 cm),
# same site-paired method-stratified design as paper_analysis.py. Deterministic.
import json
import numpy as np
import pandas as pd
from scipy import stats
import os
# Data root for the paper demo; override with GGA_HACKATHON_ROOT when reproducing.
ROOT = os.environ.get("GGA_HACKATHON_ROOT", os.path.expanduser("~/hackathon"))

RNG = np.random.default_rng(20260818)
DB = ROOT + '/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0) & df.latitude.notna()]
ngsa = df[df.source_id.isin(['australia-ngsa', 'australia-ngsa-mercury'])]

print('== method families per element (top layer) ==')
top = ngsa[ngsa.sample_type == 'sediment_outlet_top']
print(top.groupby(['element_or_analyte', 'method_family']).size().to_string())

def site_median(d, st_, el, mf, nd=2):
    s = d[(d.sample_type == st_) & (d.element_or_analyte == el) & (d.method_family == mf)].copy()
    if len(s) == 0:
        return None
    s['site'] = s.latitude.round(nd).astype(str) + '_' + s.longitude.round(nd).astype(str)
    return s.groupby('site').agg(v=('normalized_value', 'median'))

def paired_stats(t, b):
    j = t.join(b, lsuffix='_t', rsuffix='_s', how='inner')
    r = (j.v_t / j.v_s).values
    n = len(r)
    if n < 10:
        return None
    boots = [np.median(RNG.choice(r, n, replace=True)) for _ in range(2000)]
    w = stats.wilcoxon(np.log(r))
    return dict(n_pairs=int(n), median_ratio=round(float(np.median(r)), 3),
                ci95=[round(float(np.percentile(boots, 2.5)), 3),
                      round(float(np.percentile(boots, 97.5)), 3)],
                frac_gt_1_5=round(float((r > 1.5).mean()), 3), wilcoxon_p=float(w.pvalue))

out = {}
for el in ['Hg', 'Pb', 'As', 'Cu', 'Ni', 'Cr', 'Zn']:
    sub = ngsa[ngsa.element_or_analyte == el]
    if len(sub) == 0:
        continue
    mf = sub[sub.sample_type == 'sediment_outlet_top'].method_family.value_counts()
    if len(mf) == 0:
        continue
    mf = mf.index[0]
    t = site_median(ngsa, 'sediment_outlet_top', el, mf)
    b = site_median(ngsa, 'sediment_outlet_bottom', el, mf)
    if t is None or b is None:
        continue
    st_ = paired_stats(t, b)
    if st_:
        out[el] = st_ | {'method_family': mf}

print('\n== NGSA outlet top/bottom paired ratios ==')
print(json.dumps(out, indent=1))
