# P2 extended analysis + figures: hemispheric asymmetry of the legacy fingerprint.
# EU FOREGS topsoil/subsoil (from results.json) vs AU NGSA outlet sediment top/bottom.
# Outputs: p2_results.json, fig_p2_forest.pdf/png, fig_p2_au_map.pdf/png. Deterministic.
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

RNG = np.random.default_rng(20260818)
DB = '/mnt/nas/data/lyf/hackathon/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
LAND = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/skills/global-geochemical-atlas/assets/natural-earth-110m-land.json'
OUT = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'
EU = json.load(open(OUT + 'results.json'))['europe_foregs_top_over_sub']

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0) & df.latitude.notna()]
ngsa = df[df.source_id.isin(['australia-ngsa', 'australia-ngsa-mercury'])]

def site_median(d, st_, el, mf, nd=2):
    s = d[(d.sample_type == st_) & (d.element_or_analyte == el) & (d.method_family == mf)].copy()
    if len(s) == 0:
        return None
    s['site'] = s.latitude.round(nd).astype(str) + '_' + s.longitude.round(nd).astype(str)
    return s.groupby('site').agg(v=('normalized_value', 'median'), lat=('latitude', 'first'),
                                 lon=('longitude', 'first'))

def paired_stats(t, b):
    j = t.join(b[['v']], lsuffix='_t', rsuffix='_s', how='inner')
    r = (j.v_t / j.v_s).values
    n = len(r)
    if n < 10:
        return None, j
    boots = [np.median(RNG.choice(r, n, replace=True)) for _ in range(2000)]
    w = stats.wilcoxon(np.log(r))
    return dict(n_pairs=int(n), median_ratio=round(float(np.median(r)), 3),
                ci95=[round(float(np.percentile(boots, 2.5)), 3),
                      round(float(np.percentile(boots, 97.5)), 3)],
                frac_gt_1_5=round(float((r > 1.5).mean()), 3), wilcoxon_p=float(w.pvalue)), j

res = {'au_ngsa_top_over_bottom': {}, 'sensitivity': {}, 'eu_reference': EU}
pairs_au = {}
for el in ['Hg', 'Pb', 'As', 'Cu', 'Ni', 'Cr', 'Zn']:
    sub = ngsa[ngsa.element_or_analyte == el]
    if len(sub) == 0:
        continue
    mfc = sub[sub.sample_type == 'sediment_outlet_top'].method_family.value_counts()
    if len(mfc) == 0:
        continue
    mf = mfc.index[0]
    t = site_median(ngsa, 'sediment_outlet_top', el, mf)
    b = site_median(ngsa, 'sediment_outlet_bottom', el, mf)
    if t is None or b is None:
        continue
    st_, j = paired_stats(t, b)
    if st_:
        res['au_ngsa_top_over_bottom'][el] = st_ | {'method_family': mf}
        pairs_au[el] = j

# sensitivity: 0.1 deg rounding for Pb and As
for el in ['Pb', 'As']:
    mf = res['au_ngsa_top_over_bottom'][el]['method_family']
    t = site_median(ngsa, 'sediment_outlet_top', el, mf, nd=1)
    b = site_median(ngsa, 'sediment_outlet_bottom', el, mf, nd=1)
    st_, _ = paired_stats(t, b)
    if st_:
        res['sensitivity'][el + '_round0.1deg'] = st_

json.dump(res, open(OUT + 'p2_results.json', 'w'), indent=1)

# ---------------- figure 1: EU vs AU forest ----------------
INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GREY = '#8a8a8a'
els = ['Hg', 'Pb', 'Cu', 'As', 'Zn', 'Cr', 'Ni']
fig, ax = plt.subplots(figsize=(6.4, 4.0))
ypos = np.arange(len(els))[::-1] * 1.0
for i, el in enumerate(els):
    y = ypos[i]
    if el in EU:
        e = EU[el]
        ax.plot(e['ci95'], [y + 0.17, y + 0.17], color=RED, lw=2.0, solid_capstyle='butt')
        ax.plot(e['median_ratio'], y + 0.17, 'o', ms=4.5, color=RED, zorder=5)
    a = res['au_ngsa_top_over_bottom'].get(el)
    if a and el != 'Hg':
        ax.plot(a['ci95'], [y - 0.17, y - 0.17], color=BLUE, lw=2.0, solid_capstyle='butt')
        ax.plot(a['median_ratio'], y - 0.17, 's', ms=4.5, color=BLUE, zorder=5)
    elif a and el == 'Hg':
        ax.plot(a['ci95'], [y - 0.17, y - 0.17], color=BLUE, lw=1.2, alpha=0.55,
                solid_capstyle='butt')
        ax.plot(a['median_ratio'], y - 0.17, 's', ms=4.0, color=BLUE, alpha=0.55, zorder=5)
        ax.text(0.64, y + 0.44, 'AU Hg faint: n=17 only (emitted as coverage gap)',
                fontsize=6.4, color=BLUE, ha='left', va='center', alpha=0.9)
ax.axvline(1.0, color=INK, lw=0.9, ls=(0, (4, 3)))
ax.set_yticks(ypos)
ax.set_yticklabels([f"{el}\n(EU n={EU[el]['n_pairs']}, AU n={res['au_ngsa_top_over_bottom'][el]['n_pairs']})"
                    if el in res['au_ngsa_top_over_bottom'] else f"{el}\n(EU n={EU[el]['n_pairs']}, AU absent)"
                    for el in els], fontsize=7)
ax.set_xlabel('surface / deep concentration ratio (site-paired median, 95% bootstrap CI)', fontsize=8)
ax.set_xlim(0.62, 1.78)
ax.tick_params(axis='x', labelsize=8)
from matplotlib.lines import Line2D
ax.legend(handles=[
    Line2D([0], [0], color=RED, marker='o', lw=2, label='EU: FOREGS topsoil/subsoil (residual soil)'),
    Line2D([0], [0], color=BLUE, marker='s', lw=2, label='AU: NGSA outlet sediment top/bottom (0\u201310 / ~60\u201380 cm)'),
], fontsize=7, loc='lower right', frameon=False)
ax.set_title('Hemispheric contrast of the surface legacy-metal fingerprint', fontsize=9)
ax.spines[['top', 'right']].set_visible(False)
fig.tight_layout()
fig.savefig(OUT + 'fig_p2_forest.pdf'); fig.savefig(OUT + 'fig_p2_forest.png', dpi=220)

# ---------------- figure 2: AU Pb ratio map ----------------
land = json.load(open(LAND))
fig2, ax2 = plt.subplots(figsize=(6.2, 4.6))
for ring in land['rings']:
    xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
    ax2.plot(xs, ys, color='#bbbbbb', lw=0.6, zorder=1)
jj = pairs_au['Pb'].copy()
jj['log2r'] = np.log2(jj.v_t / jj.v_s)
sc = ax2.scatter(jj.lon, jj.lat, c=jj.log2r, cmap='RdBu_r', vmin=-1.2, vmax=1.2,
                 s=9, edgecolors='none', zorder=3)
ax2.set_xlim(110, 155); ax2.set_ylim(-45, -9)
ax2.set_xlabel('Longitude (deg E)', fontsize=8); ax2.set_ylabel('Latitude (deg N)', fontsize=8)
ax2.tick_params(labelsize=7.5)
cb = fig2.colorbar(sc, ax=ax2, shrink=0.8)
cb.set_label('log2 (top / bottom Pb)', fontsize=8); cb.ax.tick_params(labelsize=7)
ax2.set_title('Outlet-sediment top/bottom Pb ratio at NGSA paired sites (log2)', fontsize=9)
fig2.tight_layout()
fig2.savefig(OUT + 'fig_p2_au_map.pdf'); fig2.savefig(OUT + 'fig_p2_au_map.png', dpi=220)

print(json.dumps(res['au_ngsa_top_over_bottom'], indent=1))
print(json.dumps(res['sensitivity'], indent=1))
print('p2 extra done')
