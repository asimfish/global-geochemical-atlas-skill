# Regenerate fig_p4_scatter, fig_p5_profiles, fig_p5_audit with review fixes.
# Pure-ASCII source. Deterministic; stats unchanged, only presentation + audit fields.
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import FixedLocator, NullFormatter, ScalarFormatter

DB = '/mnt/nas/data/lyf/hackathon/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
LAND = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/skills/global-geochemical-atlas/assets/natural-earth-110m-land.json'
OUT = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'
INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GREY = '#9a9a9a'; GOLD = '#b8860b'
plt.rcParams.update({'font.size': 8, 'axes.titlesize': 9, 'axes.labelsize': 8,
                     'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5})

res = json.load(open(OUT + 'p345_full_results.json'))
df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0)]

# ---------- P4 scatter: annotate both worst-low and worst-high disagreement ----------
j4 = pd.DataFrame(res['P4']['cells_table'])
j4['log2r'] = np.log2(j4.ratio)
fig3, ax3 = plt.subplots(figsize=(4.6, 4.3))
ax3.scatter(j4.foregs, j4.gemas, s=26, c=j4.log2r, cmap='RdBu_r', vmin=-2.2, vmax=2.2,
            edgecolors=INK, linewidths=0.4, zorder=4)
lims = [1.5, 300]
ax3.plot(lims, lims, color=GREY, lw=1.0, ls=(0, (4, 3)), zorder=2)
ax3.fill_between(lims, [l / 2 for l in lims], [l * 2 for l in lims], color=GREY, alpha=0.12,
                 zorder=1, linewidth=0)
for thr in (20, 45):
    ax3.axhline(thr, color=GOLD, lw=0.7, alpha=0.7); ax3.axvline(thr, color=GOLD, lw=0.7, alpha=0.7)
lo = j4.loc[j4.log2r.idxmin()]
hi = j4.loc[j4.log2r.idxmax()]
ax3.annotate('largest low-side disagreement\nGEMAS %.1f vs FOREGS %.1f' % (lo.gemas, lo.foregs),
             xy=(lo.foregs, lo.gemas), xytext=(0.05, 0.68), textcoords='axes fraction',
             fontsize=6.6, color=BLUE, arrowprops=dict(arrowstyle='-', color=BLUE, lw=0.7))
ax3.annotate('largest high-side disagreement\nGEMAS %.1f vs FOREGS %.1f (Brittany)' % (hi.gemas, hi.foregs),
             xy=(hi.foregs, hi.gemas), xytext=(0.30, 0.93), textcoords='axes fraction',
             fontsize=6.6, color=RED, ha='left',
             arrowprops=dict(arrowstyle='-', color=RED, lw=0.7))
ax3.set_xscale('log'); ax3.set_yscale('log'); ax3.set_xlim(*lims); ax3.set_ylim(*lims)
ax3.set_xlabel('FOREGS cell median As (mg/kg), 1997-2001', fontsize=8)
ax3.set_ylabel('GEMAS cell median As (mg/kg), 2008-2009', fontsize=8)
ax3.set_title('Independent surveys, same 0.1$^\\circ$ cells (n = %d):\nSpearman $\\rho$ = %.3f, median ratio %.3f'
              % (res['P4']['colocated_cells'], res['P4']['spearman_rho'], res['P4']['median_ratio']),
              fontsize=8.6)
ax3.text(0.97, 0.03, 'band: factor-2 agreement\nlines: 20 / 45 mg/kg screening values',
         transform=ax3.transAxes, fontsize=6.4, ha='right', va='bottom', color=INK)
ax3.spines[['top', 'right']].set_visible(False)
fig3.tight_layout()
fig3.savefig(OUT + 'fig_p4_scatter.pdf'); fig3.savefig(OUT + 'fig_p4_scatter.png', dpi=220)

# ---------- P5 profiles: clean log ticks ----------
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
BINS = [0, 50, 100, 250, 500, 1000, 2000, 3000, 4500, 7000]
BASIN_C = {'Atlantic': '#1b7837', 'Pacific': '#762a83', 'Indian': '#e08214',
           'Southern': '#2166ac', 'Arctic': '#c51b7d'}
TICKS = {'Zn': [0.3, 1, 3, 10], 'Cu': [0.5, 1, 2, 4], 'Ni': [3, 4, 6, 10]}
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
    ax.set_xscale('log')
    ax.xaxis.set_major_locator(FixedLocator(TICKS[el]))
    ax.xaxis.set_major_formatter(ScalarFormatter())
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.set_title('%s  (deep/surface = %.2f)' % (el, res['P5'][el]['deep_over_surface']), fontsize=8.6)
    ax.set_xlabel('%s (nmol/kg)' % el, fontsize=7.8)
    ax.spines[['top', 'right']].set_visible(False)
axes5[0].set_ylim(6200, -120)
axes5[0].set_ylabel('Depth (m)', fontsize=8)
h, l = axes5[0].get_legend_handles_labels()
fig5.legend(h, l, fontsize=6.6, ncol=6, frameon=False, loc='lower center', bbox_to_anchor=(0.5, -0.005))
fig5.suptitle('Nutrient-type vertical structure recovered automatically from harmonized GEOTRACES IDP2025 records',
              fontsize=9, y=0.99)
fig5.tight_layout(rect=(0, 0.045, 1, 0.965))
fig5.savefig(OUT + 'fig_p5_profiles.pdf'); fig5.savefig(OUT + 'fig_p5_profiles.png', dpi=220)

# ---------- P5 audit: exclude (missing) from family bars, honest title ----------
mf = gt.method_family.fillna('(missing)')
vc = mf.value_counts()
resolvable = vc[vc.index != '(missing)']
missing_share = float((mf == '(missing)').mean())
top_res = resolvable.head(5)
res['P5']['audit']['top_resolvable_share'] = round(float(top_res.iloc[0] / len(gt)), 3)
res['P5']['audit']['top5_resolvable'] = [
    {'family': k, 'n': int(v), 'share': round(float(v / len(gt)), 3)} for k, v in top_res.items()]
res['P5']['audit']['resolvable_families_total'] = int(len(resolvable))

fig6, (axa, axb) = plt.subplots(1, 2, figsize=(7.0, 3.1))
per_el = res['P5']['audit']['per_element_families']
els_n = [per_el[el] for el in ELS5]
axa.barh(range(len(ELS5)), els_n, color=BLUE, height=0.55)
axa.set_yticks(range(len(ELS5))); axa.set_yticklabels(ELS5, fontsize=8)
axa.invert_yaxis()
for i, v in enumerate(els_n):
    axa.text(v + 0.3, i, str(v), va='center', fontsize=7.5, color=INK)
axa.set_xlabel('distinct method families per element', fontsize=8)
axa.set_xlim(0, 29)
axa.set_title('One element, dozens of method families', fontsize=8.6)
axa.spines[['top', 'right']].set_visible(False)

labels = ['BODC record %s' % k.rsplit('_', 1)[-1] for k in top_res.index] + ['no resolvable method']
vals = [v / len(gt) * 100 for v in top_res.values] + [missing_share * 100]
cols = [BLUE] * len(top_res) + [RED]
axb.barh(range(len(labels)), vals, color=cols, height=0.6)
axb.set_yticks(range(len(labels))); axb.set_yticklabels(labels, fontsize=7)
axb.invert_yaxis()
for i, v in enumerate(vals):
    axb.text(v + 0.5, i, '%.1f%%' % v, va='center', fontsize=7, color=INK)
axb.set_xlabel('share of records (%)', fontsize=8)
axb.set_xlim(0, 46)
axb.set_title('Largest resolvable family: %.1f%%; no method metadata: %.1f%%'
              % (res['P5']['audit']['top_resolvable_share'] * 100, missing_share * 100), fontsize=8.2)
axb.spines[['top', 'right']].set_visible(False)
fig6.tight_layout()
fig6.savefig(OUT + 'fig_p5_audit.pdf'); fig6.savefig(OUT + 'fig_p5_audit.png', dpi=220)

json.dump(res, open(OUT + 'p345_full_results.json', 'w'), indent=1, default=str)
print(json.dumps(res['P5']['audit'], indent=1))
print('worst low:', lo.to_dict()); print('worst high:', hi.to_dict())
print('FIGFIX DONE')
