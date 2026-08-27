# Figure 1 v4: chemistry-journal style three-panel methods figure.
# (a) atmospheric legacy pathway + paired sampling scene, (b) harmonized data flow,
# (c) site-paired statistics with real-number forest preview. Deterministic.
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Polygon

OUT = '/mnt/nas/data/lyf/hackathon/gga-acquisition-coverage-v12/research-products/paper-demo-20260817/'
INK = '#3a3a3a'; BLUE = '#2166ac'; RED = '#b2182b'; GREY = '#6f6f6f'
SKY = '#eaf2f9'; HUMUS = '#3d2b1f'; TOPS = '#7a5c40'; SUBS = '#c9b391'
GREEN = '#2d6a4f'; TRUNK = '#5e4630'

fig, ax = plt.subplots(figsize=(7.2, 4.05))
ax.set_xlim(0, 100); ax.set_ylim(0, 56); ax.axis('off')

def frame(x, y, w, h):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0,rounding_size=0.8',
                                facecolor='white', edgecolor='#b9b9b9', linewidth=0.9, zorder=1))

def panel_letter(x, y, s):
    ax.text(x, y, s, fontsize=8.5, weight='bold', color=INK, ha='left', va='top', zorder=6)

def arrow(p1, p2, lw=1.1, color=INK, style='-|>', ls='solid', ms=8, z=5):
    ax.add_patch(FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=ms, linewidth=lw,
                                 color=color, linestyle=ls, shrinkA=0.4, shrinkB=0.4, zorder=z))

# ================= panel (a): pathway + paired sampling =================
frame(1.2, 1.6, 38.6, 53.0)
panel_letter(2.6, 54.0, '(a)')
ax.text(6.4, 52.6, 'Atmospheric legacy pathway & paired sampling', fontsize=6.7,
        weight='bold', color=INK, ha='left', va='center')

# sky
ax.add_patch(Rectangle((2.6, 26.5), 35.8, 23.2, facecolor=SKY, edgecolor='none', zorder=1.5))
# deposition arrows
for xd in (6.5, 11.0, 24.5, 29.0, 33.5):
    arrow((xd, 47.5), (xd, 42.5), lw=1.0, color=INK, ms=7, z=4)
ax.text(20.0, 48.9, 'Hg(0) \u00b7 Pb deposition', fontsize=6.2, color=INK,
        ha='center', va='center', zorder=4)

# flat conifer tree (three triangles + trunk)
for i, (w2, yb, yt) in enumerate([(6.2, 33.5, 40.0), (5.0, 36.8, 42.6), (3.7, 40.0, 45.0)]):
    ax.add_patch(Polygon([(17.5 - w2, yb), (17.5 + w2, yb), (17.5, yt)],
                         closed=True, facecolor=GREEN, edgecolor='none', zorder=3))
ax.add_patch(Rectangle((16.6, 26.7), 1.8, 6.9, facecolor=TRUNK, edgecolor='none', zorder=3))
# foliar uptake + litterfall annotations
arrow((28.6, 40.0), (23.2, 40.0), lw=0.9, color=INK, ms=7, z=4)
ax.text(29.4, 40.0, 'foliar uptake', fontsize=5.9, color=INK, ha='left', va='center', zorder=4)
arrow((25.0, 34.5), (25.0, 28.3), lw=0.9, color=INK, ms=7, z=4)
ax.text(26.1, 31.6, 'litterfall', fontsize=5.9, color=INK, ha='left', va='center', zorder=4)

# soil profile (x 2.6-30.4); humus dark on top, subsoil light at bottom
ax.add_patch(Rectangle((2.6, 22.6), 27.8, 3.9, facecolor=HUMUS, edgecolor='none', zorder=2))
ax.add_patch(Rectangle((2.6, 13.6), 27.8, 9.0, facecolor=TOPS, edgecolor='none', zorder=2))
ax.add_patch(Rectangle((2.6, 3.0), 27.8, 10.6, facecolor=SUBS, edgecolor='none', zorder=2))
# subtle speckles in subsoil
rng = np.random.default_rng(7)
for _ in range(28):
    ax.plot(2.6 + 27.8 * rng.random(), 3.0 + 10.2 * rng.random(), '.', ms=1.1,
            color='#a89275', zorder=2.5)
ax.text(4.0, 24.5, 'humus (O)', fontsize=6.0, color='white', ha='left', va='center', zorder=4)
ax.text(4.0, 18.1, 'topsoil  0\u201325 cm', fontsize=6.0, color='white', ha='left', va='center', zorder=4)
ax.text(4.0, 8.3, 'subsoil  50\u2013200 cm', fontsize=6.0, color='#5a4a35', ha='left', va='center', zorder=4)

# paired-ratio brackets: both denominators point to subsoil
for xb, ytop, lab in ((33.0, 24.5, 'H/S'), (36.4, 18.1, 'T/S')):
    ax.plot([xb, xb], [8.3, ytop], color=RED, lw=1.1, zorder=4)
    ax.plot([xb - 0.7, xb], [ytop, ytop], color=RED, lw=1.1, zorder=4)
    ax.plot([xb - 0.7, xb], [8.3, 8.3], color=RED, lw=1.1, zorder=4)
    ax.text(xb + 0.7, (8.3 + ytop) / 2, lab, fontsize=6.2, color=RED, weight='bold',
            ha='left', va='center', zorder=4)
ax.plot([30.4, 32.3], [24.5, 24.5], color=RED, lw=0.7, ls=(0, (2, 2)), zorder=3)
ax.plot([30.4, 35.7], [18.1, 18.1], color=RED, lw=0.7, ls=(0, (2, 2)), zorder=3)
ax.plot([30.4, 35.7], [8.3, 8.3], color=RED, lw=0.7, ls=(0, (2, 2)), zorder=3)

# ================= panel (b): harmonized data =================
frame(41.4, 1.6, 20.6, 53.0)
panel_letter(42.8, 54.0, '(b)')
ax.text(46.2, 52.6, 'Harmonized open data', fontsize=6.7, weight='bold', color=INK,
        ha='left', va='center')
bboxes = [
    ('29 open sources', 'FOREGS \u00b7 GEMAS \u00b7 USGS \u00b7 \u2026'),
    ('191,715 records', 'mg/kg \u00b7 WGS84'),
    ('confidence + QC', 'SHA-256 provenance'),
    ('comparability cohorts', 'method family kept'),
]
BY, BH, BG = 44.2, 7.6, 3.6
for i, (t1, t2) in enumerate(bboxes):
    yy = BY - i * (BH + BG)
    ax.add_patch(FancyBboxPatch((43.2, yy), 17.0, BH, boxstyle='round,pad=0,rounding_size=0.9',
                                facecolor='white', edgecolor=BLUE, linewidth=1.0, zorder=3))
    ax.text(51.7, yy + BH - 2.2, t1, fontsize=6.1, weight='bold', color=BLUE,
            ha='center', va='center', zorder=4)
    ax.text(51.7, yy + 2.3, t2, fontsize=5.6, color=INK, ha='center', va='center', zorder=4)
    if i < 3:
        arrow((51.7, yy - 0.3), (51.7, yy - BG + 0.3), lw=1.3, color=BLUE, ms=8)

# handoff arrow (b) -> (c)
arrow((60.4, 24.0), (63.4, 24.0), lw=1.5, color=INK, ms=9)

# ================= panel (c): statistics + preview =================
frame(63.6, 1.6, 35.2, 53.0)
panel_letter(65.0, 54.0, '(c)')
ax.text(68.6, 52.6, 'Site-paired screening statistics', fontsize=6.7, weight='bold',
        color=INK, ha='left', va='center')

# formula + design chips
ax.add_patch(FancyBboxPatch((70.0, 44.4), 22.4, 5.2, boxstyle='round,pad=0,rounding_size=0.9',
                            facecolor='white', edgecolor=RED, linewidth=1.0, zorder=3))
ax.text(81.2, 47.0, r'$r = c_{\mathrm{surf}} \, / \, c_{\mathrm{deep}}$   per site',
        fontsize=6.8, color=INK, ha='center', va='center', zorder=4)
ax.text(81.2, 41.7, 'sites = 0.01\u00b0 grid \u00b7 per-site median \u00b7 one method family',
        fontsize=5.5, color=GREY, ha='center', va='center', zorder=4)

# mini forest plot with real EU numbers (log2 scale)
fx0, fx1 = 67.4, 95.4
r_lo, r_hi = 0.86, 1.55
def fx(r):
    return fx0 + (np.log2(r) - np.log2(r_lo)) / (np.log2(r_hi) - np.log2(r_lo)) * (fx1 - fx0)
fy0, fy1 = 13.4, 37.4
ax.add_patch(Rectangle((fx0 - 0.4, fy0 - 0.6), fx1 - fx0 + 2.4, fy1 - fy0 - 3.0,
                       facecolor='white', edgecolor='#c9c9c9', lw=0.8, zorder=2))
ax.plot([fx(1.0), fx(1.0)], [fy0 + 2.4, fy1 - 4.6], color=GREY, lw=0.9, ls=(0, (3, 2)), zorder=3)
rows = [('Hg', 1.364, 1.303, 1.444, RED), ('Pb', 1.239, 1.194, 1.299, RED),
        ('Ni', 0.947, 0.926, 0.970, GREY), ('Cr', 0.976, 0.947, 1.000, GREY)]
for i, (el, m, lo, hi, c) in enumerate(rows):
    yy = fy1 - 6.6 - i * 5.2
    ax.plot([fx(lo), fx(hi)], [yy, yy], color=c, lw=1.5, zorder=4)
    ax.plot(fx(m), yy, 'o', ms=3.6, color=c, zorder=5)
    ax.text(fx0 - 1.3, yy, el, fontsize=6.0, color=INK, ha='right', va='center', zorder=4)
for tv in (0.9, 1.0, 1.2, 1.4):
    ax.text(fx(tv), fy0 + 0.6, f'{tv:g}', fontsize=5.2, color=GREY, ha='center', va='center', zorder=4)
    ax.plot([fx(tv), fx(tv)], [fy0 + 1.6, fy0 + 2.2], color='#c9c9c9', lw=0.7, zorder=3)
ax.text((fx0 + fx1) / 2, fy0 - 2.2 + 0.4, 'topsoil / subsoil ratio (EU, this work)',
        fontsize=5.5, color=GREY, ha='center', va='center', zorder=4)
ax.text(81.2, 8.3, 'bootstrap 95% CI \u00b7 Wilcoxon signed-rank \u00b7 Ni/Cr geogenic controls',
        fontsize=5.4, color=INK, ha='center', va='center', zorder=4)

# feedback loop (c) -> (b)
arrow((81.2, 5.9), (52.0, 5.9), lw=1.0, color=GREY, ls=(0, (4, 2.6)), ms=7)
arrow((52.0, 5.9), (52.0, 12.6), lw=1.0, color=GREY, ls=(0, (4, 2.6)), ms=7)
ax.text(66.8, 4.4, 'coverage gaps \u2192 next acquisition', fontsize=5.5, color=GREY,
        ha='center', va='center', zorder=4)

fig.tight_layout(pad=0.25)
fig.savefig(OUT + 'fig0_pipeline.pdf')
fig.savefig(OUT + 'fig0_pipeline.png', dpi=220)
print('fig0 v4 done')
