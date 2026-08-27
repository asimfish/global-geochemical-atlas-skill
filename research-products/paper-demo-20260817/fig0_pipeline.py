# Figure 1: methods/pipeline schematic. Flat publication style, no data dependencies.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

OUT = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'
GREY = '#4d4d4d'; BLUE = '#2166ac'; RED = '#b2182b'; LIGHT = '#f0f0f0'; LBLUE = '#d1e5f0'

fig, ax = plt.subplots(figsize=(7.2, 4.9))
ax.set_xlim(0, 100); ax.set_ylim(0, 68); ax.axis('off')

def box(x, y, w, h, title, lines, fc=LIGHT, ec=GREY, title_c='black', fs=6.4):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.6,rounding_size=1.2',
                                facecolor=fc, edgecolor=ec, linewidth=1.0))
    ax.text(x + w/2, y + h - 2.6, title, ha='center', va='top', fontsize=fs+0.8, weight='bold', color=title_c)
    body = chr(10).join(lines)
    ax.text(x + w/2, y + h - 6.4, body, ha='center', va='top', fontsize=fs, color='#222222', linespacing=1.35)

def arrow(x1, y1, x2, y2, color=GREY, lw=1.4):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle='-|>', mutation_scale=11,
                                 linewidth=lw, color=color, shrinkA=1, shrinkB=1))

# ---- top row: pipeline stages ----
Y, H, W, GAP = 46, 19, 17.6, 2.6
xs = [1.5]
for i in range(4): xs.append(xs[-1] + W + GAP)
box(xs[0], Y, W, H, '29 open sources', ['FOREGS - GEMAS', 'USGS DS801 - GSJ', 'GEOTRACES - AfSIS', 'NGSA - GEMStat ...', '(63 candidates audited)'])
box(xs[1], Y, W, H, 'Acquisition and audit', ['license and terms', 'recorded per file', 'file SHA-256 chain', 'source locators', 'kept row-level'])
box(xs[2], Y, W, H, 'Standardized DB', ['191,715 records', 'units to mg/kg', 'WGS84 + lineage', 'method family +', 'digestion retained'])
box(xs[3], Y, W, H, 'Confidence and QC', ['4-dim confidence', '(source, method,', 'spatial, workflow)', 'QC gates, censoring', 'kept explicit'])
box(xs[4], Y, W, H, 'Research products', ['comparability cohorts', 'context table', 'sampling priorities', 'exclusion accounting', '(deterministic)'], fc=LBLUE, ec=BLUE, title_c=BLUE)
for i in range(4):
    arrow(xs[i] + W + 0.3, Y + H/2, xs[i+1] - 0.3, Y + H/2)

# ---- bottom left: paired-horizon design ----
sx, sy, sw = 6, 6, 13
layers = [('Humus (O)', 8.5, '#c7b299'), ('Topsoil 0-25 cm', 5.5, '#a08060'), ('Subsoil (C) 50-200 cm', 2.0, '#7a5c44')]
ax.text(sx + sw/2, sy + 26.5, 'Site-paired design', ha='center', fontsize=7.2, weight='bold')
ax.add_patch(Rectangle((sx, sy + 20), sw, 3.6, facecolor='#c7b299', edgecolor=GREY, lw=0.8))
ax.add_patch(Rectangle((sx, sy + 13), sw, 7.0, facecolor='#b09070', edgecolor=GREY, lw=0.8))
ax.add_patch(Rectangle((sx, sy), sw, 10.0, facecolor='#8a6c50', edgecolor=GREY, lw=0.8))
ax.text(sx + sw/2, sy + 21.8, 'humus (O)', ha='center', va='center', fontsize=6.2, color='black')
ax.text(sx + sw/2, sy + 16.5, 'topsoil 0-25 cm', ha='center', va='center', fontsize=6.2, color='white')
ax.text(sx + sw/2, sy + 5.0, 'subsoil (C)' + chr(10) + '50-200 cm', ha='center', va='center', fontsize=6.2, color='white')
ax.text(sx + sw + 2.2, sy + 18.5, 'H/S ratio', fontsize=6.6, color=RED, weight='bold')
ax.text(sx + sw + 2.2, sy + 10.5, 'T/S ratio', fontsize=6.6, color=RED, weight='bold')
arrow(sx + sw + 1.6, sy + 21.5, sx + sw + 1.6, sy + 6, color=RED, lw=1.2)

# ---- bottom middle: statistics box ----
box(31, 8, 26, 24, 'This study: paired screening', [
    'sites = coords rounded 0.01 deg', 'per-site median, single method', 'ratio = surface / deep',
    'median + bootstrap 95% CI', 'Wilcoxon signed-rank on log r', 'sensitivity: 0.1 deg, alt method',
    'controls: Ni, Cr (geogenic)'], fc='#fdf0ec', ec=RED, title_c=RED)

# ---- bottom right: outputs ----
box(62, 8, 30, 24, 'Outputs', [
    'EU: Hg 1.36, Pb 1.24 enriched;', 'Ni 0.95, Cr 0.98 at unity', 'humus: Hg 5.3x, Pb 2.2x, Ni 0.29',
    'US replication (A/C): Ni 0.92', 'external check vs LUCAS', 'machine-actionable gap queue'], fc=LBLUE, ec=BLUE, title_c=BLUE)

arrow(xs[4] + W/2, Y - 0.4, 44, 32.6, color=RED)
arrow(19.5, 20, 30.4, 20, color=RED)
arrow(57.4, 20, 61.4, 20, color=BLUE)

fig.tight_layout()
fig.savefig(OUT + 'fig0_pipeline.pdf'); fig.savefig(OUT + 'fig0_pipeline.png', dpi=220)
print('fig0 done')
