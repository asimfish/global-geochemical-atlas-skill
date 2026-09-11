# Additional publication figures for P2/P3/P4/P5 (2 new figures each).
# Deterministic; replicates published numbers exactly and asserts against them.
# P2: raw site-paired scatters (EU vs AU) + ECDFs of log2 surface/deep ratios (with KS tests).
# P3: Bland-Altman panels (nonparametric LOA) + out-of-sample validation figure.
# P4: 26-cell dumbbell chart + aggregation-scale sensitivity (0.05-1.0 deg).
# P5: station/basin map (assignment rule visualized) + Zn-Ni / Cu-Ni bottle covariation.
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import os
# Data root for the paper demo; override with GGA_HACKATHON_ROOT when reproducing.
ROOT = os.environ.get("GGA_HACKATHON_ROOT", os.path.expanduser("~/hackathon"))

SEED = 20260819
DB = ROOT + '/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
LAND = ROOT + '/gga-acquisition-coverage-v12/skills/global-geochemical-atlas/assets/natural-earth-110m-land.json'
OUT = ROOT + '/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'

INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GREY = '#9a9a9a'; GOLD = '#b8860b'
plt.rcParams.update({'font.size': 8, 'axes.titlesize': 9, 'axes.labelsize': 8,
                     'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5})

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0)]
dfl = df[df.latitude.notna()]
land = json.load(open(LAND))
res = {'P2': {}, 'P3': {}, 'P4': {}, 'P5': {}, 'seed': SEED}

def draw_land(ax, lw=0.5, color='#bbbbbb'):
    for ring in land['rings']:
        ax.plot([p[0] for p in ring], [p[1] for p in ring], color=color, lw=lw, zorder=1)

def offax(ax):
    ax.spines[['top', 'right']].set_visible(False)

# ============ P3 first: must consume the RNG in the same order as p345_full.py ============
RNG = np.random.default_rng(SEED)
ELS3 = ['As', 'Cr', 'Cu', 'Ni', 'Pb', 'Zn']
gem_mask = df.source_id.astype(str).str.contains('gemas')

def method_pairs(src_mask, el, mfa, mfb):
    d = df[src_mask & (df.element_or_analyte == el)]
    a = d[d.method_family == mfa].groupby('sample_id').normalized_value.median()
    b = d[d.method_family == mfb].groupby('sample_id').normalized_value.median()
    return pd.concat([a.rename('icp'), b.rename('xrf')], axis=1, join='inner').dropna()

PUB_P3 = {  # element: (median_ratio, oos_powerlaw, oos_constant) as published
    'As': (1.228, 0.173, 0.173), 'Cr': (2.942, 0.203, 0.211), 'Cu': (0.864, 0.141, 0.135),
    'Ni': (1.269, 0.116, 0.117), 'Pb': (1.288, 0.110, 0.182), 'Zn': (1.342, 0.062, 0.075)}
gem_pairs, oos, ba = {}, {}, {}
pb_scatter = None
for el in ELS3:
    j = method_pairs(gem_mask, el, 'icp_ms', 'xrf')
    gem_pairs[el] = j
    r = (j.xrf / j.icp).values
    lx, ly = np.log(j.icp.values), np.log(j.xrf.values)
    for _ in range(2000):  # advance RNG identically to p345_full.py fit_transfer
        RNG.choice(r, len(r), replace=True)
    idx = RNG.permutation(len(j)); ntr = int(0.8 * len(j))
    tr, te = idx[:ntr], idx[ntr:]
    s2, i2, *_ = stats.linregress(lx[tr], ly[tr])
    pred_pl = np.exp(i2 + s2 * lx[te])
    pred_cf = np.exp(np.log(np.median(j.xrf.values[tr] / j.icp.values[tr])) + lx[te])
    obs = j.xrf.values[te]
    mdape_pl = float(np.median(np.abs(pred_pl - obs) / obs))
    mdape_cf = float(np.median(np.abs(pred_cf - obs) / obs))
    med = float(np.median(r))
    assert round(med, 3) == PUB_P3[el][0], (el, 'median', med)
    assert round(mdape_pl, 3) == PUB_P3[el][1], (el, 'oos_pl', mdape_pl)
    assert round(mdape_cf, 3) == PUB_P3[el][2], (el, 'oos_cf', mdape_cf)
    oos[el] = dict(n_test=int(len(te)), mdape_powerlaw=round(mdape_pl, 3),
                   mdape_constant=round(mdape_cf, 3))
    if el == 'Pb':
        pb_scatter = dict(obs=obs, pred_pl=pred_pl, pred_cf=pred_cf)
    l2 = np.log2(r)
    ba[el] = dict(median_log2=round(float(np.median(l2)), 3),
                  loa_low=round(float(np.percentile(l2, 2.5)), 3),
                  loa_high=round(float(np.percentile(l2, 97.5)), 3),
                  loa_low_ratio=round(float(2 ** np.percentile(l2, 2.5)), 3),
                  loa_high_ratio=round(float(2 ** np.percentile(l2, 97.5)), 3))
res['P3']['bland_altman'] = ba
res['P3']['oos'] = oos
print('P3 asserts passed')

# --- fig P3-3: Bland-Altman panels ---
fig, axes = plt.subplots(2, 3, figsize=(7.0, 4.7))
for k, el in enumerate(ELS3):
    ax = axes.flat[k]; j = gem_pairs[el]
    gm = np.sqrt(j.icp.values * j.xrf.values)
    l2 = np.log2(j.xrf.values / j.icp.values)
    ax.scatter(gm, l2, s=2.5, alpha=0.2, color=BLUE, edgecolors='none', rasterized=True)
    b_ = ba[el]
    ax.axhline(0, color=INK, lw=0.8, ls=(0, (4, 3)))
    ax.axhline(b_['median_log2'], color=RED, lw=1.2)
    ax.axhline(b_['loa_low'], color=RED, lw=0.8, ls=(0, (2, 2)), alpha=0.8)
    ax.axhline(b_['loa_high'], color=RED, lw=0.8, ls=(0, (2, 2)), alpha=0.8)
    q = pd.qcut(gm, 12, duplicates='drop')
    run = pd.DataFrame({'q': q, 'l2': l2}).groupby('q', observed=True).agg(
        x=('l2', 'size'), m=('l2', 'median'))
    mids = [iv.mid for iv in run.index]
    ax.plot(mids, run.m, color=GOLD, lw=1.4, marker='o', ms=2.4, zorder=6)
    ax.set_xscale('log')
    ax.set_title('%s: median %.2f, LOA [%.2f, %.2f]' %
                 (el, b_['median_log2'], b_['loa_low'], b_['loa_high']), fontsize=8.0)
    ax.tick_params(labelsize=6.8)
    if k >= 3: ax.set_xlabel('geometric mean concentration (mg/kg)', fontsize=7.4)
    if k % 3 == 0: ax.set_ylabel('log2 (XRF / ICP-MS)', fontsize=7.4)
    offax(ax)
axes.flat[0].legend(handles=[
    Line2D([0], [0], color=RED, lw=1.2, label='median offset'),
    Line2D([0], [0], color=RED, lw=0.8, ls=(0, (2, 2)), label='95% limits of agreement'),
    Line2D([0], [0], color=GOLD, lw=1.4, marker='o', ms=2.4, label='running median (12 bins)'),
], fontsize=5.8, frameon=False, loc='lower left')
fig.suptitle('Bland-Altman view of GEMAS same-sample pairs (n = 2,224 per element)', fontsize=9, y=0.995)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT + 'fig_p3_ba.pdf'); fig.savefig(OUT + 'fig_p3_ba.png', dpi=220)

# --- fig P3-4: out-of-sample validation ---
fig, (axa, axb) = plt.subplots(1, 2, figsize=(7.0, 3.15))
axa.scatter(pb_scatter['obs'], pb_scatter['pred_cf'], s=7, alpha=0.5, color=GREY,
            edgecolors='none', label='constant factor (MdAPE 18.2%)', rasterized=True)
axa.scatter(pb_scatter['obs'], pb_scatter['pred_pl'], s=7, alpha=0.55, color=BLUE,
            edgecolors='none', label='power law (MdAPE 11.0%)', rasterized=True)
lims = [min(pb_scatter['obs'].min(), 4), pb_scatter['obs'].max() * 1.2]
axa.plot(lims, lims, color=INK, lw=0.9, ls=(0, (4, 3)))
axa.set_xscale('log'); axa.set_yscale('log')
axa.set_xlabel('observed XRF Pb (mg/kg), held-out 20%', fontsize=7.8)
axa.set_ylabel('predicted XRF Pb (mg/kg)', fontsize=7.8)
axa.set_title('Pb: transfer-model predictions on the held-out set\n(n = %d, seeded 80/20 split)'
              % oos['Pb']['n_test'], fontsize=8.4)
axa.legend(fontsize=6.6, frameon=False, loc='upper left')
offax(axa)
x = np.arange(len(ELS3)); w = 0.38
order_b = ['Pb', 'Zn', 'Cr', 'Ni', 'As', 'Cu']
pl = [oos[e]['mdape_powerlaw'] * 100 for e in order_b]
cf = [oos[e]['mdape_constant'] * 100 for e in order_b]
axb.bar(x - w / 2, pl, w, color=BLUE, label='power law')
axb.bar(x + w / 2, cf, w, color='#c6c6c6', label='constant factor')
for i, e in enumerate(order_b):
    gain = (cf[i] - pl[i]) / cf[i] * 100
    axb.text(i, max(pl[i], cf[i]) + 0.5, '%+.0f%%' % gain, ha='center', fontsize=6.6,
             color=(RED if gain < 0 else INK))
axb.set_xticks(x); axb.set_xticklabels(order_b, fontsize=8)
axb.set_ylabel('out-of-sample MdAPE (%)', fontsize=7.8)
axb.set_ylim(0, 24)
axb.set_title('Model comparison per element\n(labels: relative error reduction of the power law)',
              fontsize=8.4)
axb.legend(fontsize=6.6, frameon=False, loc='upper right')
offax(axb)
fig.tight_layout()
fig.savefig(OUT + 'fig_p3_oos.pdf'); fig.savefig(OUT + 'fig_p3_oos.png', dpi=220)
print('P3 figures done')

# ============ P2: raw pairs + ECDFs ============
EU_MF = {'Hg': 'aas', 'Pb': 'icp_ms', 'As': 'icp_ms', 'Cu': 'icp_ms', 'Zn': 'xrf'}
PUB_EU = {'Hg': (392, 1.364), 'Pb': (389, 1.239), 'As': (384, 1.045),
          'Cu': (384, 1.055), 'Zn': (387, 1.027)}
PUB_AU = {'Pb': (1064, 0.982), 'As': (1042, 0.886), 'Cu': (1055, 0.955), 'Zn': (1057, 1.005)}
foregs = dfl[dfl.source_id.isin(['foregs-topsoil', 'foregs-subsoil'])]
ngsa = dfl[dfl.source_id.isin(['australia-ngsa', 'australia-ngsa-mercury'])]

def site_median(d, st_, el, mf, nd=2):
    s = d[(d.sample_type == st_) & (d.element_or_analyte == el) & (d.method_family == mf)].copy()
    s['site'] = s.latitude.round(nd).astype(str) + '_' + s.longitude.round(nd).astype(str)
    return s.groupby('site').agg(v=('normalized_value', 'median'), lat=('latitude', 'first'),
                                 lon=('longitude', 'first'))

def paired(d, st_top, st_bot, el, mf):
    t = site_median(d, st_top, el, mf)
    b = site_median(d, st_bot, el, mf)
    return t.join(b[['v']], lsuffix='_t', rsuffix='_s', how='inner')

eu_pairs, au_pairs = {}, {}
for el, mf in EU_MF.items():
    j = paired(foregs, 'soil_topsoil', 'soil_subsoil', el, mf)
    assert (len(j), round(float((j.v_t / j.v_s).median()), 3)) == PUB_EU[el], (el, len(j))
    eu_pairs[el] = j
for el in ['Pb', 'As', 'Cu', 'Zn']:
    mf = ngsa[(ngsa.element_or_analyte == el) &
              (ngsa.sample_type == 'sediment_outlet_top')].method_family.value_counts().index[0]
    j = paired(ngsa, 'sediment_outlet_top', 'sediment_outlet_bottom', el, mf)
    assert (len(j), round(float((j.v_t / j.v_s).median()), 3)) == PUB_AU[el], (el, len(j))
    au_pairs[el] = j
print('P2 asserts passed')

# --- fig P2-3: raw site-paired scatters ---
panels = [('EU Pb (FOREGS topsoil vs subsoil)', eu_pairs['Pb'], RED),
          ('EU Hg (FOREGS topsoil vs subsoil)', eu_pairs['Hg'], RED),
          ('AU Pb (NGSA TOS vs BOS)', au_pairs['Pb'], BLUE),
          ('AU As (NGSA TOS vs BOS)', au_pairs['As'], BLUE)]
fig, axes = plt.subplots(2, 2, figsize=(6.4, 6.1))
for k, (title, j, col) in enumerate(panels):
    ax = axes.flat[k]
    ax.scatter(j.v_s, j.v_t, s=4, alpha=0.35, color=col, edgecolors='none', rasterized=True)
    lo = float(min(j.v_s.min(), j.v_t.min())) * 0.8
    hi = float(max(j.v_s.max(), j.v_t.max())) * 1.25
    ax.plot([lo, hi], [lo, hi], color=INK, lw=0.9, ls=(0, (4, 3)))
    share = float((j.v_t > j.v_s).mean()) * 100
    med = float((j.v_t / j.v_s).median())
    ax.text(0.03, 0.955, '%.0f%% of sites above 1:1\nmedian ratio %.3f' % (share, med),
            transform=ax.transAxes, fontsize=6.8, va='top', color=INK)
    ax.set_xscale('log'); ax.set_yscale('log'); ax.set_xlim(lo, hi); ax.set_ylim(lo, hi)
    ax.set_title('%s, n = %s' % (title, format(len(j), ',')), fontsize=8.0)
    ax.set_xlabel('deep concentration (mg/kg)', fontsize=7.4)
    ax.set_ylabel('surface concentration (mg/kg)', fontsize=7.4)
    ax.tick_params(labelsize=6.8)
    offax(ax)
fig.suptitle('Raw site pairs behind the contrast: European surface excess, Australian symmetry',
             fontsize=9, y=0.995)
fig.tight_layout(rect=(0, 0, 1, 0.975))
fig.savefig(OUT + 'fig_p2_pairs.pdf'); fig.savefig(OUT + 'fig_p2_pairs.png', dpi=220)

# --- fig P2-4: ECDFs of log2 ratios + KS ---
ks = {}
fig, axes = plt.subplots(1, 4, figsize=(7.0, 2.45), sharey=True)
for k, el in enumerate(['Pb', 'As', 'Cu', 'Zn']):
    ax = axes[k]
    a = np.sort(np.log2((eu_pairs[el].v_t / eu_pairs[el].v_s).values))
    b = np.sort(np.log2((au_pairs[el].v_t / au_pairs[el].v_s).values))
    d_, p_ = stats.ks_2samp(a, b)
    ks[el] = dict(D=round(float(d_), 3), p=float(p_),
                  eu_share_gt1=round(float((a > 0).mean()), 3),
                  au_share_gt1=round(float((b > 0).mean()), 3))
    ax.plot(a, np.arange(1, len(a) + 1) / len(a), color=RED, lw=1.4, label='EU (FOREGS)')
    ax.plot(b, np.arange(1, len(b) + 1) / len(b), color=BLUE, lw=1.4, label='AU (NGSA)')
    ax.axvline(0, color=INK, lw=0.8, ls=(0, (4, 3)))
    ax.set_xlim(-1.6, 1.6)
    ax.set_title('%s\nKS D = %.2f, p = %.0e' % (el, d_, p_), fontsize=8.0)
    ax.set_xlabel('log2 (surface / deep)', fontsize=7.4)
    ax.tick_params(labelsize=6.8)
    offax(ax)
axes[0].set_ylabel('empirical CDF', fontsize=7.8)
axes[0].legend(fontsize=6.4, frameon=False, loc='upper left')
fig.tight_layout()
fig.savefig(OUT + 'fig_p2_ecdf.pdf'); fig.savefig(OUT + 'fig_p2_ecdf.png', dpi=220)
res['P2']['ks'] = ks
res['P2']['raw_pairs'] = {('EU_' + el): dict(n=int(len(j)), share_above=round(float((j.v_t > j.v_s).mean()), 3))
                          for el, j in eu_pairs.items()}
res['P2']['raw_pairs'].update({('AU_' + el): dict(n=int(len(j)), share_above=round(float((j.v_t > j.v_s).mean()), 3))
                               for el, j in au_pairs.items()})
print('P2 figures done')

# ============ P4: dumbbell + scale sensitivity ============
as_gem = dfl[gem_mask.reindex(dfl.index, fill_value=False) & (dfl.element_or_analyte == 'As')].copy()
as_for = dfl[dfl.source_id.isin(['foregs-topsoil', 'foregs-subsoil']) &
             (dfl.element_or_analyte == 'As')].copy()

def coloc(scale):
    # cell index via (coord * mult).round() with integer mult = 1/scale: at 0.1 deg this is
    # arithmetically identical to the published lat.round(1) convention (numpy scaled rounding)
    mult = int(round(1 / scale))
    g_ = as_gem.copy(); f_ = as_for.copy()
    for d in (g_, f_):
        d['cell'] = ((d.latitude * mult).round().astype(int).astype(str) + '_' +
                     (d.longitude * mult).round().astype(int).astype(str))
    g2 = g_.groupby('cell').agg(gemas=('normalized_value', 'median'),
                                lat=('latitude', 'first'), lon=('longitude', 'first'))
    f2 = f_.groupby('cell').normalized_value.median().rename('foregs')
    j = g2.join(f2, how='inner').dropna()
    j['ratio'] = j.gemas / j.foregs
    j['log2r'] = np.log2(j.ratio)
    return j

scales = [0.05, 0.1, 0.2, 0.5, 1.0]
scale_rows = []
for s in scales:
    j = coloc(s)
    rho = stats.spearmanr(j.gemas, j.foregs)
    scale_rows.append(dict(scale=s, n=int(len(j)),
                           rho=round(float(rho.statistic), 3), p=float(rho.pvalue),
                           median_ratio=round(float(j.ratio.median()), 3),
                           within2=int((j.log2r.abs() <= 1).sum()),
                           within2_pct=round(float((j.log2r.abs() <= 1).mean()) * 100, 1)))
res['P4']['scale_sensitivity'] = scale_rows
r01 = [r for r in scale_rows if r['scale'] == 0.1][0]
assert (r01['n'], r01['rho'], r01['median_ratio'], r01['within2']) == (26, 0.681, 0.982, 19), r01
print('P4 asserts passed')

# --- fig P4-3: dumbbell chart of the 26 cells ---
j4 = coloc(0.1).sort_values('ratio', ascending=False).reset_index(drop=True)
fig, ax = plt.subplots(figsize=(6.3, 5.6))
ypos = np.arange(len(j4))[::-1]
for i, row in j4.iterrows():
    y = ypos[i]
    queue = row.ratio > 2 or row.ratio < 0.5
    lc = (RED if row.ratio > 2 else BLUE) if queue else '#c9c9c9'
    ax.plot([row.foregs, row.gemas], [y, y], color=lc, lw=2.0 if queue else 1.3,
            solid_capstyle='round', zorder=3, alpha=0.9)
    ax.plot(row.gemas, y, 'o', ms=4.6, color=INK, zorder=5)
    ax.plot(row.foregs, y, 'o', ms=4.6, mfc='white', mec=GOLD, mew=1.3, zorder=5)
for thr in (20, 45):
    ax.axvline(thr, color=GOLD, lw=0.7, alpha=0.7, zorder=2)
ax.set_xscale('log')
labels = ['%.1f$^\\circ$N, %.1f$^\\circ$%s%s' %
          (row.lat, abs(row.lon), 'E' if row.lon >= 0 else 'W',
           ' *' if (row.ratio > 2 or row.ratio < 0.5) else '')
          for _, row in j4.iterrows()]
ax.set_yticks(ypos); ax.set_yticklabels(labels, fontsize=6.4)
ax.set_xlabel('cell-median soil As (mg/kg), log scale', fontsize=8)
ax.set_title('All 26 co-located validation cells, sorted by GEMAS/FOREGS ratio\n'
             '(*: disagreement queue, outside factor-two agreement)', fontsize=8.6)
ax.legend(handles=[
    Line2D([0], [0], marker='o', color='none', mfc=INK, mec=INK, ms=4.6, label='GEMAS (2008-2009)'),
    Line2D([0], [0], marker='o', color='none', mfc='white', mec=GOLD, mew=1.3, ms=4.6, label='FOREGS (1997-2001)'),
    Line2D([0], [0], color=RED, lw=2, label='queue, GEMAS high'),
    Line2D([0], [0], color=BLUE, lw=2, label='queue, FOREGS high'),
    Line2D([0], [0], color=GOLD, lw=0.7, label='20 / 45 mg/kg'),
], fontsize=6.2, frameon=False, loc='lower right')
offax(ax)
fig.tight_layout()
fig.savefig(OUT + 'fig_p4_cells.pdf'); fig.savefig(OUT + 'fig_p4_cells.png', dpi=220)

# --- fig P4-4: aggregation-scale sensitivity ---
fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.5))
xs = [r['scale'] for r in scale_rows]
panels = [('co-located cells', [r['n'] for r in scale_rows], 'n cells'),
          ('rank agreement', [r['rho'] for r in scale_rows], 'Spearman rho'),
          ('factor-two agreement', [r['within2_pct'] for r in scale_rows], '% of cells within factor 2')]
for k, (title, ys, ylab) in enumerate(panels):
    ax = axes[k]
    ax.plot(xs, ys, color=BLUE, lw=1.5, marker='o', ms=4.5, zorder=5)
    i01 = xs.index(0.1)
    ax.plot(xs[i01], ys[i01], 'o', ms=8, mfc='none', mec=RED, mew=1.4, zorder=6)
    ax.set_xscale('log')
    ax.set_xticks(xs); ax.set_xticklabels([str(s) for s in xs], fontsize=6.8)
    ax.minorticks_off()
    ax.set_xlabel('cell size ($^\\circ$)', fontsize=7.6)
    ax.set_ylabel(ylab, fontsize=7.6)
    ax.set_title(title, fontsize=8.4)
    if k == 2:
        for xv, r in zip(xs, scale_rows):
            ax.annotate('%.2f' % r['median_ratio'], (xv, r['within2_pct']),
                        textcoords='offset points', xytext=(0, -11), ha='center',
                        fontsize=5.8, color=GOLD)
        ax.text(0.03, 0.04, 'gold: median ratio', transform=ax.transAxes, fontsize=6.0, color=GOLD)
    offax(ax)
fig.suptitle('Cross-survey agreement vs aggregation scale (red ring: 0.1$^\\circ$ used in this paper)',
             fontsize=8.8, y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT + 'fig_p4_scale.pdf'); fig.savefig(OUT + 'fig_p4_scale.png', dpi=220)
print('P4 figures done')

# ============ P5: station/basin map + covariation ============
gt = df[df.source_id == 'geotraces-idp2025'].copy()
gt = gt[gt.sample_depth_min_m.notna()]
gt['depth'] = gt.sample_depth_min_m

def basin_of(lon, lat):
    if lat <= -50: return 'Southern'
    if lat >= 66: return 'Arctic'
    if -70 <= lon < 20: return 'Atlantic'
    if 20 <= lon < 150: return 'Indian' if lat < 30 else 'Pacific'
    return 'Pacific'

gt['basin'] = [basin_of(o, a) for o, a in zip(gt.longitude, gt.latitude)]
BASIN_C = {'Atlantic': '#1b7837', 'Pacific': '#762a83', 'Indian': '#e08214',
           'Southern': '#2166ac', 'Arctic': '#c51b7d'}
stations = gt[['latitude', 'longitude', 'basin']].drop_duplicates(['latitude', 'longitude'])
res['P5']['stations'] = int(len(stations))
res['P5']['records'] = int(len(gt))
res['P5']['by_basin'] = {b: dict(records=int((gt.basin == b).sum()),
                                 stations=int((stations.basin == b).sum()))
                         for b in BASIN_C}

# --- fig P5-3: station map with basin rule ---
fig, ax = plt.subplots(figsize=(7.0, 3.7))
draw_land(ax, lw=0.4)
for b, c in BASIN_C.items():
    s_ = stations[stations.basin == b]
    ax.scatter(s_.longitude, s_.latitude, s=3.5, color=c, edgecolors='none', zorder=4,
               label='%s (%s rec / %d st)' % (b, format(res['P5']['by_basin'][b]['records'], ','),
                                              res['P5']['by_basin'][b]['stations']))
for lat_ in (-50, 66):
    ax.axhline(lat_, color=INK, lw=0.6, ls=(0, (3, 3)), alpha=0.55, zorder=2)
ax.plot([20, 20], [-50, 30], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.plot([-70, -70], [-50, 8], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.plot([150, 150], [-50, 30], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.plot([20, 150], [30, 30], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.set_xlim(-180, 180); ax.set_ylim(-78, 88)
ax.set_xlabel('Longitude ($^\\circ$E)', fontsize=8); ax.set_ylabel('Latitude ($^\\circ$N)', fontsize=8)
ax.set_title('Harmonized GEOTRACES IDP2025 sampling positions (%s records, %d positions) '
             'and the fixed basin-assignment rule (dotted)' %
             (format(res['P5']['records'], ','), res['P5']['stations']), fontsize=8.4)
ax.legend(fontsize=6.2, frameon=False, loc='lower left', ncol=2, columnspacing=0.9,
          handletextpad=0.3, borderaxespad=0.2)
ax.tick_params(labelsize=7)
offax(ax)
fig.tight_layout()
fig.savefig(OUT + 'fig_p5_map.pdf'); fig.savefig(OUT + 'fig_p5_map.png', dpi=220)

# --- fig P5-4: bottle-level covariation ---
def bottle_series(el):
    d = gt[gt.element_or_analyte == el].copy()
    d['key'] = (d.latitude.round(3).astype(str) + '_' + d.longitude.round(3).astype(str)
                + '_' + d.depth.round(1).astype(str))
    g = d.groupby('key').agg(v=('normalized_value', 'median'), depth=('depth', 'first'))
    return g

zn, cu, ni = bottle_series('Zn'), bottle_series('Cu'), bottle_series('Ni')
covar = {}
fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.35))
for k, (name, a, b, xl, yl) in enumerate([
        ('Zn vs Ni', ni, zn, 'Ni (nmol/kg)', 'Zn (nmol/kg)'),
        ('Cu vs Ni', ni, cu, 'Ni (nmol/kg)', 'Cu (nmol/kg)')]):
    ax = axes[k]
    j = a[['v', 'depth']].rename(columns={'v': 'x'}).join(b[['v']].rename(columns={'v': 'y'}),
                                                          how='inner').dropna()
    surf = j[j.depth < 100]; deep = j[j.depth > 1000]; mid = j[(j.depth >= 100) & (j.depth <= 1000)]
    ax.scatter(mid.x, mid.y, s=3, alpha=0.18, color='#c0c0c0', edgecolors='none',
               rasterized=True, label='100-1,000 m (n=%s)' % format(len(mid), ','))
    ax.scatter(surf.x, surf.y, s=3.5, alpha=0.3, color=GOLD, edgecolors='none',
               rasterized=True, label='surface <100 m (n=%s)' % format(len(surf), ','))
    ax.scatter(deep.x, deep.y, s=3.5, alpha=0.3, color=BLUE, edgecolors='none',
               rasterized=True, label='deep >1,000 m (n=%s)' % format(len(deep), ','))
    rs = stats.spearmanr(surf.x, surf.y); rd = stats.spearmanr(deep.x, deep.y)
    ra = stats.spearmanr(j.x, j.y)
    key = name.replace(' vs ', '_').lower()
    covar[key] = dict(n=int(len(j)), rho_all=round(float(ra.statistic), 3),
                      rho_surface=round(float(rs.statistic), 3),
                      rho_deep=round(float(rd.statistic), 3),
                      n_surface=int(len(surf)), n_deep=int(len(deep)))
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlabel(xl, fontsize=7.8); ax.set_ylabel(yl, fontsize=7.8)
    ax.set_title('%s at the same bottle (n = %s)\nSpearman rho: all %.2f, deep %.2f, surface %.2f'
                 % (name, format(len(j), ','), ra.statistic, rd.statistic, rs.statistic), fontsize=8.2)
    ax.legend(fontsize=6.0, frameon=False, loc='lower right', handletextpad=0.3)
    ax.tick_params(labelsize=6.8)
    offax(ax)
fig.suptitle('Coupled nutrient-type covariation across harmonized bottles', fontsize=9, y=0.99)
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(OUT + 'fig_p5_covar.pdf'); fig.savefig(OUT + 'fig_p5_covar.png', dpi=220)
res['P5']['covariation'] = covar
print('P5 figures done')

json.dump(res, open(OUT + 'p2345_addfigs_results.json', 'w'), indent=1, default=str)
print(json.dumps(res, indent=1, default=str)[:3500])
print('ALL DONE')
