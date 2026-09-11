# Full analyses + publication figures for P3/P4/P5. Deterministic (seed 20260819).
# P3: same-sample XRF vs ICP offsets, power-law transfer models, out-of-sample test.
# P4: GEMAS x FOREGS As co-location, full agreement/disagreement table, global coverage map.
# P5: GEOTRACES Zn/Cu/Ni depth profiles (global + basin), method-fragmentation audit.
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SEED = 20260819
RNG = np.random.default_rng(SEED)
DB = ROOT + '/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
LAND = ROOT + '/gga-acquisition-coverage-v12/skills/global-geochemical-atlas/assets/natural-earth-110m-land.json'
OUT = ROOT + '/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'

INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GREY = '#9a9a9a'; GOLD = '#b8860b'
plt.rcParams.update({'font.size': 8, 'axes.titlesize': 9, 'axes.labelsize': 8,
                     'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5})

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0)]
land = json.load(open(LAND))
res = {'P3': {}, 'P4': {}, 'P5': {}, 'seed': SEED}

def draw_land(ax, lw=0.5, color='#bbbbbb'):
    for ring in land['rings']:
        ax.plot([p[0] for p in ring], [p[1] for p in ring], color=color, lw=lw, zorder=1)

# ================= P3: transfer models =================
def method_pairs(src_mask, el, mfa, mfb):
    d = df[src_mask & (df.element_or_analyte == el)]
    a = d[d.method_family == mfa].groupby('sample_id').normalized_value.median()
    b = d[d.method_family == mfb].groupby('sample_id').normalized_value.median()
    j = pd.concat([a.rename('icp'), b.rename('xrf')], axis=1, join='inner').dropna()
    return j

def fit_transfer(j, boot=2000):
    r = (j.xrf / j.icp).values
    lx, ly = np.log(j.icp.values), np.log(j.xrf.values)
    slope, intercept, rval, _, se = stats.linregress(lx, ly)
    boots = [np.median(RNG.choice(r, len(r), replace=True)) for _ in range(boot)]
    # out-of-sample: seeded 80/20 split, compare power-law vs constant-factor model
    idx = RNG.permutation(len(j)); ntr = int(0.8 * len(j))
    tr, te = idx[:ntr], idx[ntr:]
    s2, i2, *_ = stats.linregress(lx[tr], ly[tr])
    pred_pl = np.exp(i2 + s2 * lx[te])
    pred_cf = np.exp(np.log(np.median(r[tr] if False else (j.xrf.values[tr] / j.icp.values[tr]))) + lx[te])
    ape_pl = np.abs(pred_pl - j.xrf.values[te]) / j.xrf.values[te]
    ape_cf = np.abs(pred_cf - j.xrf.values[te]) / j.xrf.values[te]
    return dict(n=int(len(j)), median_ratio=round(float(np.median(r)), 3),
                ci95=[round(float(np.percentile(boots, 2.5)), 3), round(float(np.percentile(boots, 97.5)), 3)],
                iqr=[round(float(np.percentile(r, 25)), 3), round(float(np.percentile(r, 75)), 3)],
                slope=round(float(slope), 3), intercept=round(float(intercept), 3),
                slope_se=round(float(se), 4), r2=round(float(rval ** 2), 3),
                oos_mdape_powerlaw=round(float(np.median(ape_pl)), 3),
                oos_mdape_constant=round(float(np.median(ape_cf)), 3))

gem_mask = df.source_id.astype(str).str.contains('gemas')
ELS3 = ['As', 'Cr', 'Cu', 'Ni', 'Pb', 'Zn']
gem_pairs = {}
for el in ELS3:
    j = method_pairs(gem_mask, el, 'icp_ms', 'xrf')
    if len(j) >= 30:
        res['P3'][f'GEMAS_{el}'] = fit_transfer(j)
        gem_pairs[el] = j
for el in ELS3:
    for st_, lab in [('soil_topsoil', 'top'), ('soil_subsoil', 'sub')]:
        m = df.source_id.isin(['foregs-topsoil', 'foregs-subsoil']) & (df.sample_type == st_)
        j = method_pairs(m, el, 'icp_oes', 'xrf')
        if len(j) >= 30:
            res['P3'][f'FOREGS_{lab}_{el}'] = fit_transfer(j)

# --- fig P3-1: six-panel log-log scatter ---
fig, axes = plt.subplots(2, 3, figsize=(7.0, 4.9), sharex=False, sharey=False)
for k, el in enumerate(ELS3):
    ax = axes.flat[k]; j = gem_pairs[el]; t = res['P3'][f'GEMAS_{el}']
    ax.scatter(j.icp, j.xrf, s=2.5, alpha=0.22, color=BLUE, edgecolors='none', rasterized=True)
    xs = np.logspace(np.log10(j.icp.min()), np.log10(j.icp.max()), 50)
    ax.plot(xs, xs, color=GREY, lw=0.9, ls=(0, (4, 3)), label='1:1')
    ax.plot(xs, np.exp(t['intercept'] + t['slope'] * np.log(xs)), color=RED, lw=1.3,
            label='power-law fit')
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_title(f"{el}: ratio {t['median_ratio']}, slope {t['slope']}", fontsize=8.2)
    ax.tick_params(labelsize=6.8)
    if k >= 3: ax.set_xlabel('ICP-MS (aqua regia), mg/kg', fontsize=7.4)
    if k % 3 == 0: ax.set_ylabel('XRF (total), mg/kg', fontsize=7.4)
    ax.spines[['top', 'right']].set_visible(False)
axes.flat[0].legend(fontsize=6.4, frameon=False, loc='upper left')
fig.suptitle('GEMAS same-sample pairs (n = 2,224 per element): XRF total vs ICP-MS aqua regia',
             fontsize=9, y=0.995)
fig.tight_layout(rect=(0, 0, 1, 0.97))
fig.savefig(OUT + 'fig_p3_scatter.pdf'); fig.savefig(OUT + 'fig_p3_scatter.png', dpi=220)

# --- fig P3-2: forest of median ratios (GEMAS + FOREGS replication) ---
fig2, ax2 = plt.subplots(figsize=(6.4, 3.6))
order = sorted(ELS3, key=lambda e: -res['P3'][f'GEMAS_{e}']['median_ratio'])
ypos = np.arange(len(order))[::-1]
for i, el in enumerate(order):
    y = ypos[i]; g = res['P3'][f'GEMAS_{el}']
    c = RED if g['median_ratio'] < 1 else BLUE
    ax2.plot(g['iqr'], [y + 0.14, y + 0.14], color=c, lw=2.2, solid_capstyle='butt')
    ax2.plot(g['median_ratio'], y + 0.14, 'o', ms=5, color=c, zorder=5)
    for lab, mk, dy in [('top', 'v', -0.14), ('sub', '^', -0.34)]:
        key = f'FOREGS_{lab}_{el}'
        if key in res['P3']:
            f_ = res['P3'][key]
            ax2.plot(f_['iqr'], [y + dy, y + dy], color=GOLD, lw=1.3, alpha=0.85, solid_capstyle='butt')
            ax2.plot(f_['median_ratio'], y + dy, mk, ms=3.6, color=GOLD, zorder=5)
ax2.axvline(1.0, color=INK, lw=0.9, ls=(0, (4, 3)))
ax2.set_yticks(ypos)
ax2.set_yticklabels([f"{el}\n(n={res['P3'][f'GEMAS_{el}']['n']:,})" for el in order], fontsize=7.2)
ax2.set_xlabel('XRF / ICP same-sample concentration ratio (median, IQR)', fontsize=8)
ax2.set_xscale('log')
ax2.set_xticks([0.8, 1.0, 1.5, 2.0, 3.0])
ax2.set_xticklabels(['0.8', '1.0', '1.5', '2.0', '3.0'])
from matplotlib.lines import Line2D
import os
# Data root for the paper demo; override with GGA_HACKATHON_ROOT when reproducing.
ROOT = os.environ.get("GGA_HACKATHON_ROOT", os.path.expanduser("~/hackathon"))
ax2.legend(handles=[
    Line2D([0], [0], color=BLUE, marker='o', lw=2, label='GEMAS XRF/ICP-MS (ratio > 1)'),
    Line2D([0], [0], color=RED, marker='o', lw=2, label='GEMAS Cu: direction reversed'),
    Line2D([0], [0], color=GOLD, marker='v', lw=1.3, label='FOREGS XRF/ICP-OES replication (top/sub)'),
], fontsize=6.6, loc='lower right', frameon=False)
ax2.set_title('Same-sample inter-method offsets are element-specific and survey-replicated', fontsize=9)
ax2.spines[['top', 'right']].set_visible(False)
fig2.tight_layout()
fig2.savefig(OUT + 'fig_p3_forest.pdf'); fig2.savefig(OUT + 'fig_p3_forest.png', dpi=220)

# ================= P4: arsenic cross-survey validation =================
as_gem = df[gem_mask & (df.element_or_analyte == 'As') & df.latitude.notna()].copy()
as_for = df[df.source_id.isin(['foregs-topsoil', 'foregs-subsoil'])
            & (df.element_or_analyte == 'As') & df.latitude.notna()].copy()
for d in (as_gem, as_for):
    d['cell'] = d.latitude.round(1).astype(str) + '_' + d.longitude.round(1).astype(str)
g = as_gem.groupby('cell').agg(v=('normalized_value', 'median'), lat=('latitude', 'first'),
                               lon=('longitude', 'first'))
f = as_for.groupby('cell').normalized_value.median().rename('foregs')
j4 = g.join(f, how='inner').dropna().rename(columns={'v': 'gemas'})
j4['ratio'] = j4.gemas / j4.foregs
j4['log2r'] = np.log2(j4.ratio)
rho = stats.spearmanr(j4.gemas, j4.foregs)
soil_as = df[(df.element_or_analyte == 'As') & df.sample_type.astype(str).str.startswith('soil')
             & df.latitude.notna()]
by_source = soil_as.groupby('source_id').agg(
    n=('normalized_value', 'size'), median=('normalized_value', 'median'),
    gt20=('normalized_value', lambda v: int((v > 20).sum())),
    gt45=('normalized_value', lambda v: int((v > 45).sum()))).round(2)
res['P4'] = {
    'colocated_cells': int(len(j4)),
    'spearman_rho': round(float(rho.statistic), 3), 'spearman_p': float(rho.pvalue),
    'median_ratio': round(float(j4.ratio.median()), 3),
    'within_factor2': int((j4.log2r.abs() <= 1).sum()),
    'both_gt20': int(((j4.gemas > 20) & (j4.foregs > 20)).sum()),
    'both_gt45': int(((j4.gemas > 45) & (j4.foregs > 45)).sum()),
    'soil_as_records': int(len(soil_as)),
    'soil_as_gt20': int((soil_as.normalized_value > 20).sum()),
    'soil_as_gt45': int((soil_as.normalized_value > 45).sum()),
    'by_source': by_source.reset_index().to_dict('records'),
    'cells_table': j4.reset_index()[['cell', 'lat', 'lon', 'gemas', 'foregs', 'ratio']]
        .round({'gemas': 1, 'foregs': 1, 'ratio': 3, 'lat': 2, 'lon': 2})
        .sort_values('ratio', ascending=False).to_dict('records'),
}

# --- fig P4-1: co-location scatter ---
fig3, ax3 = plt.subplots(figsize=(4.6, 4.3))
ax3.scatter(j4.foregs, j4.gemas, s=26, c=j4.log2r, cmap='RdBu_r', vmin=-2.2, vmax=2.2,
            edgecolors=INK, linewidths=0.4, zorder=4)
lims = [1.5, 300]
ax3.plot(lims, lims, color=GREY, lw=1.0, ls=(0, (4, 3)), zorder=2)
ax3.fill_between(lims, [l / 2 for l in lims], [l * 2 for l in lims], color=GREY, alpha=0.12,
                 zorder=1, linewidth=0)
for thr in (20, 45):
    ax3.axhline(thr, color=GOLD, lw=0.7, alpha=0.7); ax3.axvline(thr, color=GOLD, lw=0.7, alpha=0.7)
worst = j4.loc[j4.log2r.abs().idxmax()]
ax3.annotate(f"largest disagreement\nGEMAS {worst.gemas:.0f} vs FOREGS {worst.foregs:.0f} mg/kg",
             xy=(worst.foregs, worst.gemas), xytext=(0.04, 0.86), textcoords='axes fraction',
             fontsize=6.8, color=RED, arrowprops=dict(arrowstyle='-', color=RED, lw=0.7))
ax3.set_xscale('log'); ax3.set_yscale('log'); ax3.set_xlim(*lims); ax3.set_ylim(*lims)
ax3.set_xlabel('FOREGS cell median As (mg/kg), 1997-2001', fontsize=8)
ax3.set_ylabel('GEMAS cell median As (mg/kg), 2008-2009', fontsize=8)
ax3.set_title(f'Independent surveys, same 0.1$^\circ$ cells (n = {len(j4)}):\n'
              f'Spearman $\\rho$ = {res["P4"]["spearman_rho"]}, median ratio {res["P4"]["median_ratio"]}',
              fontsize=8.6)
ax3.text(0.97, 0.03, 'band: factor-2 agreement\nlines: 20 / 45 mg/kg screening values',
         transform=ax3.transAxes, fontsize=6.4, ha='right', va='bottom', color=INK)
ax3.spines[['top', 'right']].set_visible(False)
fig3.tight_layout()
fig3.savefig(OUT + 'fig_p4_scatter.pdf'); fig3.savefig(OUT + 'fig_p4_scatter.png', dpi=220)

# --- fig P4-2: global coverage map + Europe inset ---
fig4, ax4 = plt.subplots(figsize=(7.0, 3.9))
draw_land(ax4, lw=0.4)
ax4.scatter(soil_as.longitude, soil_as.latitude, s=1.1, color=GREY, alpha=0.35,
            edgecolors='none', zorder=2, rasterized=True)
ax4.scatter(j4.lon, j4.lat, s=13, c=j4.log2r, cmap='RdBu_r', vmin=-2.2, vmax=2.2,
            edgecolors=INK, linewidths=0.3, zorder=5)
ax4.set_xlim(-180, 180); ax4.set_ylim(-62, 84)
ax4.set_xlabel('Longitude ($^\circ$E)', fontsize=8); ax4.set_ylabel('Latitude ($^\circ$N)', fontsize=8)
ax4.set_title('Harmonized soil-As records (grey, n = %s) and independent co-located validation cells (colored, n = %d)'
              % (f"{len(soil_as):,}", len(j4)), fontsize=8.4)
axins = ax4.inset_axes([0.015, 0.06, 0.30, 0.52])
draw_land(axins, lw=0.35)
sc = axins.scatter(j4.lon, j4.lat, s=22, c=j4.log2r, cmap='RdBu_r', vmin=-2.2, vmax=2.2,
                   edgecolors=INK, linewidths=0.35, zorder=5)
axins.set_xlim(-11, 26); axins.set_ylim(36, 62)
axins.set_xticks([]); axins.set_yticks([])
axins.set_title('Europe (all 26 cells)', fontsize=6.6)
ax4.indicate_inset_zoom(axins, edgecolor=INK, alpha=0.5)
cb = fig4.colorbar(sc, ax=ax4, shrink=0.75, pad=0.01)
cb.set_label('log2 (GEMAS / FOREGS)', fontsize=7.5); cb.ax.tick_params(labelsize=6.8)
fig4.tight_layout()
fig4.savefig(OUT + 'fig_p4_map.pdf'); fig4.savefig(OUT + 'fig_p4_map.png', dpi=220)

# ================= P5: GEOTRACES profiles + audit =================
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
ELS5 = ['Zn', 'Cu', 'Ni']
res['P5']['records'] = int(len(gt))
res['P5']['elements'] = {el: int((gt.element_or_analyte == el).sum()) for el in ELS5}
res['P5']['basin_counts'] = gt.basin.value_counts().to_dict()
for el in ELS5:
    d = gt[gt.element_or_analyte == el]
    surf, deep = d[d.depth < 100].normalized_value, d[d.depth > 1000].normalized_value
    u = stats.mannwhitneyu(surf, deep, alternative='two-sided')
    ent = dict(n_surface=int(len(surf)), n_deep=int(len(deep)),
               median_surface=round(float(surf.median()), 3), median_deep=round(float(deep.median()), 3),
               deep_over_surface=round(float(deep.median() / surf.median()), 2),
               mannwhitney_p=float(u.pvalue), by_basin={})
    for b in ['Atlantic', 'Pacific', 'Indian', 'Southern', 'Arctic']:
        db_ = d[d.basin == b]
        s_, dp_ = db_[db_.depth < 100].normalized_value, db_[db_.depth > 1000].normalized_value
        if len(s_) >= 30 and len(dp_) >= 30:
            ent['by_basin'][b] = dict(n_surface=int(len(s_)), n_deep=int(len(dp_)),
                                      ratio=round(float(dp_.median() / s_.median()), 2))
    res['P5'][el] = ent
mf = gt.method_family.fillna('(missing)')
res['P5']['audit'] = {
    'method_families_total': int(mf.nunique()),
    'records_missing_method': int((mf == '(missing)').sum()),
    'missing_share': round(float((mf == '(missing)').mean()), 3),
    'top_family_share': round(float(mf.value_counts(normalize=True).iloc[0]), 3),
    'top5_families': [{'family': k, 'n': int(v)} for k, v in mf.value_counts().head(5).items()],
    'per_element_families': {el: int(gt[gt.element_or_analyte == el].method_family
                                     .fillna('(missing)').nunique()) for el in ELS5},
}

# --- fig P5-1: depth profiles, global + basins ---
BINS = [0, 50, 100, 250, 500, 1000, 2000, 3000, 4500, 7000]
BASIN_C = {'Atlantic': '#1b7837', 'Pacific': '#762a83', 'Indian': '#e08214',
           'Southern': '#2166ac', 'Arctic': '#c51b7d'}
fig5, axes5 = plt.subplots(1, 3, figsize=(7.0, 4.2), sharey=True)
for k, el in enumerate(ELS5):
    ax = axes5[k]; d = gt[gt.element_or_analyte == el].copy()
    d['bin'] = pd.cut(d.depth, BINS)
    st_ = d.groupby('bin', observed=True).normalized_value.agg(
        med='median', q1=lambda v: v.quantile(0.25), q3=lambda v: v.quantile(0.75))
    mid = [iv.mid for iv in st_.index]
    ax.fill_betweenx(mid, st_.q1, st_.q3, color=BLUE, alpha=0.16, linewidth=0)
    ax.plot(st_.med, mid, color=INK, lw=1.7, marker='o', ms=2.8, zorder=6, label='global median (IQR)')
    for b, c in BASIN_C.items():
        db_ = d[d.basin == b]
        if len(db_) < 200: continue
        sb = db_.groupby('bin', observed=True).normalized_value.median()
        sb = sb[db_.groupby('bin', observed=True).size() >= 25]
        ax.plot(sb.values, [iv.mid for iv in sb.index], color=c, lw=0.9, alpha=0.85, label=b)
    ax.set_xscale('log'); ax.invert_yaxis() if k == 0 else None
    ax.set_title(f"{el}  (deep/surface = {res['P5'][el]['deep_over_surface']})", fontsize=8.6)
    ax.set_xlabel(f'{el} (nmol/kg)', fontsize=7.8)
    ax.spines[['top', 'right']].set_visible(False)
axes5[0].set_ylim(6200, -120)
axes5[0].set_ylabel('Depth (m)', fontsize=8)
h, l = axes5[0].get_legend_handles_labels()
fig5.legend(h, l, fontsize=6.6, ncol=6, frameon=False, loc='lower center', bbox_to_anchor=(0.5, -0.005))
fig5.suptitle('Nutrient-type vertical structure recovered automatically from harmonized GEOTRACES IDP2025 records',
              fontsize=9, y=0.99)
fig5.tight_layout(rect=(0, 0.045, 1, 0.965))
fig5.savefig(OUT + 'fig_p5_profiles.pdf'); fig5.savefig(OUT + 'fig_p5_profiles.png', dpi=220)

# --- fig P5-2: fragmentation audit ---
fig6, (axa, axb) = plt.subplots(1, 2, figsize=(7.0, 3.1))
els_n = [res['P5']['audit']['per_element_families'][el] for el in ELS5]
axa.barh(range(len(ELS5)), els_n, color=BLUE, height=0.55)
axa.set_yticks(range(len(ELS5))); axa.set_yticklabels(ELS5, fontsize=8)
for i, v in enumerate(els_n):
    axa.text(v + 0.3, i, str(v), va='center', fontsize=7.5, color=INK)
axa.set_xlabel('distinct method families per element', fontsize=8)
axa.set_title('One element, dozens of method families', fontsize=8.6)
axa.spines[['top', 'right']].set_visible(False)
top5 = res['P5']['audit']['top5_families']
labels = [t['family'][:26] for t in top5] + ['no resolvable method']
vals = [t['n'] / len(gt) * 100 for t in top5] + [res['P5']['audit']['missing_share'] * 100]
cols = [BLUE] * len(top5) + [RED]
axb.barh(range(len(labels)), vals, color=cols, height=0.6)
axb.set_yticks(range(len(labels))); axb.set_yticklabels(labels, fontsize=6.8)
axb.invert_yaxis()
for i, v in enumerate(vals):
    axb.text(v + 0.5, i, f'{v:.1f}%', va='center', fontsize=7, color=INK)
axb.set_xlabel('share of records (%)', fontsize=8)
axb.set_xlim(0, max(vals) * 1.22)
axb.set_title('Largest family covers %.1f%%; %.1f%% lack method metadata'
              % (res['P5']['audit']['top_family_share'] * 100,
                 res['P5']['audit']['missing_share'] * 100), fontsize=8.6)
axb.spines[['top', 'right']].set_visible(False)
fig6.tight_layout()
fig6.savefig(OUT + 'fig_p5_audit.pdf'); fig6.savefig(OUT + 'fig_p5_audit.png', dpi=220)

json.dump(res, open(OUT + 'p345_full_results.json', 'w'), indent=1, default=str)
print(json.dumps({k: v for k, v in res['P3'].items() if k.startswith('GEMAS')}, indent=1))
print(json.dumps({k: v for k, v in res['P4'].items() if k != 'cells_table' and k != 'by_source'}, indent=1))
print(json.dumps(res['P5'], indent=1, default=str)[:2600])
print('ALL DONE')
