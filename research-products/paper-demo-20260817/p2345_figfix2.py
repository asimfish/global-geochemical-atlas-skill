# Patch two figures from p2345_addfigs.py:
#  - fig_p4_scale: right panel gold labels were clipped at panel edges; note overlapped a label.
#  - fig_p5_map: in-figure title too long (clipped); legend overlapped Southern Ocean points.
import json
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
# Data root for the paper demo; override with GGA_HACKATHON_ROOT when reproducing.
ROOT = os.environ.get("GGA_HACKATHON_ROOT", os.path.expanduser("~/hackathon"))

DB = ROOT + '/retest-acquisition-coverage-v12-6c221cf/world/output/geochemistry.csv'
LAND = ROOT + '/gga-acquisition-coverage-v12/skills/global-geochemical-atlas/assets/natural-earth-110m-land.json'
OUT = ROOT + '/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'

INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GOLD = '#b8860b'
plt.rcParams.update({'font.size': 8, 'axes.titlesize': 9, 'axes.labelsize': 8,
                     'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5})

df = pd.read_csv(DB, low_memory=False)
df = df[df.normalized_value.notna() & (df.normalized_value > 0)]
dfl = df[df.latitude.notna()]
land = json.load(open(LAND))

def offax(ax):
    ax.spines[['top', 'right']].set_visible(False)

# ---------- P4 scale figure ----------
gem_mask = df.source_id.astype(str).str.contains('gemas')
as_gem = dfl[gem_mask.reindex(dfl.index, fill_value=False) & (dfl.element_or_analyte == 'As')].copy()
as_for = dfl[dfl.source_id.isin(['foregs-topsoil', 'foregs-subsoil']) &
             (dfl.element_or_analyte == 'As')].copy()

def coloc(scale):
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
rows = []
for s in scales:
    j = coloc(s)
    rho = stats.spearmanr(j.gemas, j.foregs)
    rows.append(dict(scale=s, n=int(len(j)), rho=round(float(rho.statistic), 3),
                     median_ratio=round(float(j.ratio.median()), 3),
                     within2_pct=round(float((j.log2r.abs() <= 1).mean()) * 100, 1)))
r01 = [r for r in rows if r['scale'] == 0.1][0]
assert (r01['n'], r01['rho'], r01['median_ratio']) == (26, 0.681, 0.982), r01

fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.5))
xs = [r['scale'] for r in rows]
panels = [('co-located cells', [r['n'] for r in rows], 'n cells'),
          ('rank agreement', [r['rho'] for r in rows], 'Spearman rho'),
          ('factor-two agreement', [r['within2_pct'] for r in rows], '% of cells within factor 2')]
for k, (title, ys, ylab) in enumerate(panels):
    ax = axes[k]
    ax.plot(xs, ys, color=BLUE, lw=1.5, marker='o', ms=4.5, zorder=5)
    i01 = xs.index(0.1)
    ax.plot(xs[i01], ys[i01], 'o', ms=8, mfc='none', mec=RED, mew=1.4, zorder=6)
    ax.set_xscale('log')
    ax.set_xticks(xs); ax.set_xticklabels([str(s) for s in xs], fontsize=6.8)
    ax.minorticks_off()
    ax.margins(x=0.14)
    ax.set_xlabel('cell size ($^\\circ$)', fontsize=7.6)
    ax.set_ylabel(ylab, fontsize=7.6)
    ax.set_title(title, fontsize=8.4)
    if k == 2:
        ax.set_ylim(min(ys) - 10, max(ys) + 7)
        offs = {0.05: (0, -12), 0.1: (-16, -8), 0.2: (0, -12), 0.5: (0, -12), 1.0: (10, -4)}
        for xv, r in zip(xs, rows):
            ax.annotate('%.2f' % r['median_ratio'], (xv, r['within2_pct']),
                        textcoords='offset points', xytext=offs[r['scale']], ha='center',
                        fontsize=6.0, color=GOLD)
        ax.text(0.04, 0.95, 'gold: median ratio', transform=ax.transAxes, fontsize=6.2,
                color=GOLD, va='top')
    offax(ax)
fig.suptitle('Cross-survey agreement vs aggregation scale (red ring: 0.1$^\\circ$ used in this paper)',
             fontsize=8.8, y=1.0)
fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT + 'fig_p4_scale.pdf'); fig.savefig(OUT + 'fig_p4_scale.png', dpi=220)
print('p4 scale fixed')

# ---------- P5 station map ----------
gt = df[df.source_id == 'geotraces-idp2025'].copy()
gt = gt[gt.sample_depth_min_m.notna()]

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

fig, ax = plt.subplots(figsize=(7.0, 4.05))
for ring in land['rings']:
    ax.plot([p[0] for p in ring], [p[1] for p in ring], color='#bbbbbb', lw=0.4, zorder=1)
for b, c in BASIN_C.items():
    s_ = stations[stations.basin == b]
    ax.scatter(s_.longitude, s_.latitude, s=3.5, color=c, edgecolors='none', zorder=4,
               label='%s (%s rec / %d pos)' % (b, format(int((gt.basin == b).sum()), ','),
                                               len(s_)))
for lat_ in (-50, 66):
    ax.axhline(lat_, color=INK, lw=0.6, ls=(0, (3, 3)), alpha=0.55, zorder=2)
ax.plot([20, 20], [-50, 30], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.plot([-70, -70], [-50, 8], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.plot([150, 150], [-50, 30], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.plot([20, 150], [30, 30], color=INK, lw=0.5, ls=(0, (1, 2)), alpha=0.5, zorder=2)
ax.set_xlim(-180, 180); ax.set_ylim(-78, 88)
ax.set_xlabel('Longitude ($^\\circ$E)', fontsize=8)
ax.set_ylabel('Latitude ($^\\circ$N)', fontsize=8)
ax.set_title('Harmonized GEOTRACES IDP2025 sampling positions (%s records, %s positions)'
             % (format(len(gt), ','), format(len(stations), ',')), fontsize=8.6)
ax.tick_params(labelsize=7)
offax(ax)
h, l = ax.get_legend_handles_labels()
fig.legend(h, l, loc='lower center', ncol=3, fontsize=6.6, frameon=False,
           columnspacing=1.4, handletextpad=0.35, markerscale=1.6)
fig.tight_layout(rect=(0, 0.085, 1, 1))
fig.savefig(OUT + 'fig_p5_map.pdf'); fig.savefig(OUT + 'fig_p5_map.png', dpi=220)
print('p5 map fixed')
print('ALL DONE')
