# Paper-demo analysis: paired-horizon enrichment screening from GGA standardized DB.
# Single input: geochemistry.csv (frozen v12 world run). Deterministic (seeded bootstrap).
import json, math
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

RNG = np.random.default_rng(20260817)
DB = '/mnt/nas/data/lyf/hackathon/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
LAND = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/skills/global-geochemical-atlas/assets/natural-earth-110m-land.json'
OUT = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0) & df.latitude.notna()]

# primary method family per element to avoid duplicate-method mixing
PRIMARY = {'Hg':'aas','Pb':'icp_ms','As':'icp_ms','Cu':'icp_ms','Ni':'icp_ms','Cr':'xrf','Zn':'xrf'}

def site_median(d, src, el, mf, nd=2):
    s = d[(d.source_id==src) & (d.element_or_analyte==el) & (d.method_family==mf)].copy()
    if len(s)==0: return None
    s['site'] = s.latitude.round(nd).astype(str)+'_'+s.longitude.round(nd).astype(str)
    g = s.groupby('site').agg(v=('normalized_value','median'), lat=('latitude','first'), lon=('longitude','first'))
    return g

def paired_stats(top, sub):
    j = top.join(sub, lsuffix='_t', rsuffix='_s', how='inner')
    r = (j.v_t / j.v_s).values
    lr = np.log(r)
    n = len(r)
    if n < 10: return None, j
    med = float(np.median(r))
    boots = [np.median(RNG.choice(r, n, replace=True)) for _ in range(2000)]
    lo, hi = float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))
    w = stats.wilcoxon(lr)
    return dict(n_pairs=int(n), median_ratio=round(med,3), ci95=[round(lo,3), round(hi,3)],
                frac_gt_1_5=round(float((r>1.5).mean()),3), wilcoxon_p=float(w.pvalue)), j

results = {'europe_foregs_top_over_sub': {}, 'europe_foregs_humus_over_sub': {},
           'usa_usgs_a_over_c': {}, 'sensitivity': {}}

# ---- Europe FOREGS topsoil/subsoil ----
pairs_eu = {}
for el, mf in PRIMARY.items():
    t = site_median(df, 'foregs-topsoil', el, mf)
    s = site_median(df, 'foregs-subsoil', el, mf)
    if t is None or s is None: continue
    st, j = paired_stats(t, s)
    if st: results['europe_foregs_top_over_sub'][el] = st | {'method_family': mf}
    pairs_eu[el] = j

# ---- Europe FOREGS humus/subsoil (organic horizon accumulation) ----
for el in ['Hg','Pb','Cu','Ni']:
    mf = PRIMARY[el]
    h = site_median(df, 'foregs-humus', el, mf)
    s = site_median(df, 'foregs-subsoil', el, mf)
    if h is None or s is None: continue
    st, _ = paired_stats(h, s)
    if st: results['europe_foregs_humus_over_sub'][el] = st | {'method_family': mf}

# ---- USA USGS A-horizon / C-horizon ----
usgs_mf = df[df.source_id=='usgs-conus-soil'].method_family.value_counts().index[0]
for el in ['As','Cu','Ni','Zn']:
    a = site_median(df[df.sample_type=='soil_a_horizon'], 'usgs-conus-soil', el, usgs_mf)
    c = site_median(df[df.sample_type=='soil_c_horizon'], 'usgs-conus-soil', el, usgs_mf)
    if a is None or c is None: continue
    st, _ = paired_stats(a, c)
    if st: results['usa_usgs_a_over_c'][el] = st | {'method_family': usgs_mf}

# ---- Sensitivity: coordinate rounding 0.05 deg; Pb alt method icp_oes ----
for el in ['Hg','Pb']:
    t = site_median(df, 'foregs-topsoil', el, PRIMARY[el], nd=1)
    s = site_median(df, 'foregs-subsoil', el, PRIMARY[el], nd=1)
    st, _ = paired_stats(t, s)
    if st: results['sensitivity'][el+'_round0.1deg'] = st
t = site_median(df, 'foregs-topsoil', 'Pb', 'icp_oes'); s = site_median(df, 'foregs-subsoil', 'Pb', 'icp_oes')
st, _ = paired_stats(t, s)
if st: results['sensitivity']['Pb_icp_oes'] = st

# ---- Figure 1: forest plot of paired ratios ----
fig, ax = plt.subplots(figsize=(7.2, 4.6))
rows, labels, colors = [], [], []
order_eu = ['Hg','Pb','Cu','As','Zn','Cr','Ni']
for el in order_eu:
    if el in results['europe_foregs_top_over_sub']:
        st = results['europe_foregs_top_over_sub'][el]
        rows.append((st['median_ratio'], st['ci95'][0], st['ci95'][1]))
        labels.append(f"EU {el} (n={st['n_pairs']})")
        colors.append('#b2182b' if el in ('Hg','Pb') else '#4d4d4d')
for el in ['As','Cu','Zn','Ni']:
    if el in results['usa_usgs_a_over_c']:
        st = results['usa_usgs_a_over_c'][el]
        rows.append((st['median_ratio'], st['ci95'][0], st['ci95'][1]))
        labels.append(f"US {el} (n={st['n_pairs']})")
        colors.append('#2166ac')
y = np.arange(len(rows))[::-1]
for yi, (m, lo, hi), c in zip(y, rows, colors):
    ax.plot([lo, hi], [yi, yi], color=c, lw=2)
    ax.plot(m, yi, 'o', color=c, ms=6)
ax.axvline(1.0, color='k', lw=0.8, ls='--')
ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=9)
ax.set_xlabel('Surface / deep horizon concentration ratio (site-paired median, 95% bootstrap CI)')
ax.set_title('Paired-horizon enrichment: FOREGS topsoil/subsoil (EU) and USGS A/C horizon (US)')
fig.tight_layout(); fig.savefig(OUT+'fig1_forest.pdf'); fig.savefig(OUT+'fig1_forest.png', dpi=200)

# ---- Figure 2: map of per-site Hg topsoil/subsoil log2 ratio over Europe ----
land = json.load(open(LAND))
fig, ax = plt.subplots(figsize=(7.2, 6.0))
for ring in land['rings']:
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    ax.plot(xs, ys, color='0.75', lw=0.5, zorder=1)
j = pairs_eu['Hg']
lr2 = np.log2(j.v_t / j.v_s)
sc = ax.scatter(j.lon_t, j.lat_t, c=lr2, cmap='RdBu_r', vmin=-2, vmax=2, s=22, zorder=2, edgecolors='k', linewidths=0.2)
ax.set_xlim(-11, 32); ax.set_ylim(34, 71)
ax.set_xlabel('Longitude (deg E)'); ax.set_ylabel('Latitude (deg N)')
ax.set_title('Topsoil/subsoil Hg ratio at FOREGS paired sites (log2)')
cb = fig.colorbar(sc, ax=ax, shrink=0.8); cb.set_label('log2(topsoil Hg / subsoil Hg)')
fig.tight_layout(); fig.savefig(OUT+'fig2_hg_map.pdf'); fig.savefig(OUT+'fig2_hg_map.png', dpi=200)

# ---- Figure 3: humus vs topsoil vs subsoil distributions for Hg and Pb ----
fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.8))
for ax, el in zip(axes, ['Hg','Pb']):
    mf = PRIMARY[el]
    data, ticklabels = [], []
    for src, lab in [('foregs-humus','Humus (O)'), ('foregs-topsoil','Topsoil'), ('foregs-subsoil','Subsoil')]:
        g = site_median(df, src, el, mf)
        if g is None: continue
        data.append(np.log10(g.v.values)); ticklabels.append(f'{lab}\n(n={len(g)})')
    bp = ax.boxplot(data, tick_labels=ticklabels, showfliers=False, patch_artist=True, widths=0.55)
    for patch in bp['boxes']: patch.set_facecolor('#d1e5f0')
    ax.set_title(el); ax.set_ylabel('log10 concentration (mg/kg)')
fig.suptitle('FOREGS horizon distributions (site medians)')
fig.tight_layout(); fig.savefig(OUT+'fig3_horizons.pdf'); fig.savefig(OUT+'fig3_horizons.png', dpi=200)

# ---- top enriched 2-deg bins for Hg ----
j = pairs_eu['Hg'].copy()
j['bin'] = (j.lat_t//2*2).astype(int).astype(str)+'N_'+(j.lon_t//2*2).astype(int).astype(str)+'E'
b = j.groupby('bin').apply(lambda x: pd.Series({'n': len(x), 'median_log2r': float(np.median(np.log2(x.v_t/x.v_s)))}), include_groups=False)
top_bins = b[b.n>=5].sort_values('median_log2r', ascending=False).head(8)
results['hg_top_enriched_2deg_bins'] = {k: {'n': int(v.n), 'median_log2_ratio': round(v.median_log2r,2)} for k, v in top_bins.iterrows()}

pairs_eu['Hg'].assign(log2_ratio=np.log2(pairs_eu['Hg'].v_t/pairs_eu['Hg'].v_s)).to_csv(OUT+'hg_site_pairs.csv')
json.dump(results, open(OUT+'results.json','w'), indent=2)
print(json.dumps(results, indent=2))
