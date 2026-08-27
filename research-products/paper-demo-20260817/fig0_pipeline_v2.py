# Figure 1 v2: methods overview, per figure-studio S4 spec (S3-S4-record.md).
# Deterministic; no data dependencies. Layout: boustrophedon two-band.
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

OUT = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'
INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GREY = '#666666'
LANE_B = '#f2f6fb'; LANE_R = '#fdf6f3'; CHIP_E = '#8a8a8a'

fig, ax = plt.subplots(figsize=(7.2, 4.7))
ax.set_xlim(0, 100); ax.set_ylim(0, 64); ax.axis('off')

def module(x, y, w, h, title, lines, ec, title_c=None, fs_t=6.6, fs_b=5.9, spacing=None):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=0.7',
                                facecolor='white', edgecolor=ec, linewidth=1.1, zorder=3))
    ax.text(x + w/2, y + h - 2.1, title, ha='center', va='center', fontsize=fs_t,
            weight='bold', color=title_c or ec, zorder=4)
    n = len(lines)
    step = spacing if spacing else ((h - 6.6) / max(n - 1, 1) if n > 1 else 1)
    for i, (txt, bold) in enumerate(lines):
        yy = y + h - 5.4 - i * step
        ax.text(x + w/2, yy, txt, ha='center', va='center', fontsize=fs_b,
                weight='bold' if bold else 'normal', color=INK, zorder=4)

def chip(x, y, w, h, txt, fs=5.5):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=1.1',
                                facecolor='white', edgecolor=CHIP_E, linewidth=0.8, zorder=4))
    ax.text(x + w/2, y + h/2, txt, ha='center', va='center', fontsize=fs, color=INK, zorder=5)

def arrow(p1, p2, lw=1.4, color=INK, style='-|>', ls='solid', ms=10, z=5, rad=0.0):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=ms, linewidth=lw,
                                 color=color, linestyle=ls, shrinkA=0.5, shrinkB=0.5,
                                 connectionstyle=f'arc3,rad={rad}', zorder=z))

# ---------- lanes ----------
ax.add_patch(Rectangle((0.8, 40.2), 98.4, 23.0, facecolor=LANE_B, edgecolor='none', zorder=0))
ax.add_patch(Rectangle((0.8, 2.2), 98.4, 36.4, facecolor=LANE_R, edgecolor='none', zorder=0))
ax.text(2.4, 61.7, 'AUTONOMOUS DATA INFRASTRUCTURE', fontsize=7.0, weight='bold',
        color=BLUE, ha='left', va='center')
ax.text(97.6, 3.7, 'SCREENING STUDY (THIS WORK)', fontsize=7.0, weight='bold',
        color=RED, ha='right', va='center')

# ---------- top band modules ----------
W, H, Y, GAP = 17.6, 15.5, 42.5, 1.95
xs = [2.2 + i * (W + GAP) for i in range(5)]
module(xs[0], Y, W, H, 'Open sources',
       [('63 audited \u2192 29 admitted', True),
        ('FOREGS \u00b7 GEMAS \u00b7 USGS', False),
        ('GEOTRACES \u00b7 \u2026', False)], BLUE)
module(xs[1], Y, W, H, 'Acquisition + audit',
       [('license terms per file', False),
        ('SHA-256 provenance', True),
        ('row-level source locators', False)], BLUE)
module(xs[2], Y, W, H, 'Standardized database',
       [('191,715 records', True),
        ('mg/kg \u00b7 WGS84', False),
        ('method family kept', False)], BLUE)
module(xs[3], Y, W, H, 'Confidence + QC',
       [('4-dim confidence', True),
        ('source / method / spatial', False),
        ('workflow \u00b7 censoring kept', False)], BLUE, fs_b=5.4)
module(xs[4], Y, W, H, 'Research products',
       [('337 cohorts', True),
        ('context table', False),
        ('sampling priorities', False)], BLUE)
for i in range(4):
    arrow((xs[i] + W + 0.25, Y + H/2), (xs[i+1] - 0.25, Y + H/2), lw=1.4)

# ---------- drop connector (carries cohorts) ----------
arrow((89.2, Y - 0.2), (89.2, 34.3), lw=1.6)
ax.text(90.4, 38.9, 'cohorts', fontsize=5.6, color=GREY, ha='left', va='center')

# ---------- screening module (right, wide) ----------
SX, SW, SY, SH = 44.5, 53.5, 5.5, 28.5
module_box = FancyBboxPatch((SX, SY), SW, SH, boxstyle='round,pad=0,rounding_size=0.7',
                            facecolor='white', edgecolor=RED, linewidth=1.1, zorder=3)
ax.add_patch(module_box)
ax.text(SX + SW/2, SY + SH - 2.2, 'Site-paired screening', ha='center', va='center',
        fontsize=6.6, weight='bold', color=RED, zorder=4)

# chip flow: setup row then stats row
chip(58.5, 24.0, 11.8, 5.4, 'sites = 0.01\u00b0 grid')
chip(71.3, 24.0, 11.4, 5.4, 'per-site median')
chip(83.7, 24.0, 12.6, 5.4, 'one method family')
arrow((70.4, 26.7), (71.2, 26.7), lw=1.0, ms=7)
arrow((82.8, 26.7), (83.6, 26.7), lw=1.0, ms=7)
arrow((77.5, 23.8), (77.5, 19.6), lw=1.0, ms=7)
chip(58.5, 14.0, 13.4, 5.4, 'r = c$_{surf}$ / c$_{deep}$')
chip(72.9, 14.0, 14.6, 5.4, 'bootstrap 95% CI \u00b7 Wilcoxon', fs=5.0)
chip(88.5, 14.0, 7.8, 5.4, 'controls:\nNi, Cr', fs=5.0)
arrow((72.0, 16.7), (72.8, 16.7), lw=1.0, ms=7)
arrow((87.6, 16.7), (88.4, 16.7), lw=1.0, ms=7)
ax.text(77.5, 10.4, 'sensitivity: 0.1\u00b0 grid \u00b7 alternative method family',
        fontsize=5.2, color=GREY, ha='center', va='center', zorder=4)

# soil-column inset (subordinate, inside-left)
ax.text(51.5, 29.6, 'paired horizons', fontsize=5.6, color=GREY, ha='center',
        va='center', style='italic', zorder=4)
col_x, col_w = 48.8, 6.4
ax.add_patch(Rectangle((col_x, 23.2), col_w, 3.2, facecolor='#c7b299', edgecolor=INK, lw=0.7, zorder=4))
ax.add_patch(Rectangle((col_x, 16.2), col_w, 7.0, facecolor='#b09070', edgecolor=INK, lw=0.7, zorder=4))
ax.add_patch(Rectangle((col_x, 8.6), col_w, 6.2, facecolor='#8a6c50', edgecolor=INK, lw=0.7, zorder=4))
ax.text(col_x + col_w/2, 24.8, 'humus', fontsize=5.2, ha='center', va='center', color='#3d2f22', zorder=5)
ax.text(col_x + col_w/2, 19.7, 'topsoil', fontsize=5.2, ha='center', va='center', color='white', zorder=5)
ax.text(col_x + col_w/2, 11.7, 'subsoil', fontsize=5.2, ha='center', va='center', color='white', zorder=5)
arrow((56.1, 24.8), (56.1, 12.2), lw=0.9, color=RED, ms=6)
ax.text(56.1, 26.6, 'H/S', fontsize=5.2, color=RED, ha='center', va='center', weight='bold', zorder=5)
arrow((57.4, 19.7), (57.4, 12.2), lw=0.9, color=RED, ms=6)
ax.text(57.5, 21.4, 'T/S', fontsize=5.2, color=RED, ha='center', va='center', weight='bold', zorder=5)

# ---------- outputs module (left) ----------
module(2.2, SY, 36.0, SH, 'Screening outputs',
       [('Hg 1.36\u00d7 \u00b7 Pb 1.24\u00d7  enriched', True),
        ('Ni 0.95 \u00b7 Cr 0.98  \u2248 1  (controls)', False),
        ('humus Hg 5.3\u00d7', True),
        ('enrichment maps \u00b7 coverage-gap queue', False)], RED, fs_b=6.0, spacing=5.6)
arrow((SX - 0.3, SY + SH/2), (38.6, SY + SH/2), lw=1.6)

# ---------- feedback edge ----------
arrow((10.0, 34.3), (10.0, Y - 0.2), lw=1.1, color=GREY, ls=(0, (4, 2.6)), ms=8)
ax.text(11.3, 38.9, 'gaps \u2192 next acquisition', fontsize=5.6, color=GREY,
        ha='left', va='center')

fig.tight_layout(pad=0.3)
fig.savefig(OUT + 'fig0_pipeline.pdf')
fig.savefig(OUT + 'fig0_pipeline.png', dpi=220)
print('fig0 v2 done')
