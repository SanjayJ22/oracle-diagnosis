"""Publication figures for the CJSJ paper. Values transcribed from
reports/cjsj_numbers.md sections 9 and 21 (see comments)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#1f1f1f", "#5f5e58", "#e6e5df"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.edgecolor": MUTED,
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": MUTED})
OUT = "/home/claude/cjsj/"

# ---------------- Figure 1: sourcing schematic ----------------
fig, ax = plt.subplots(figsize=(11, 5.6)); ax.set_xlim(0, 110); ax.set_ylim(0, 56); ax.axis("off")
def box(x, y, w, h, text, edge, face, size=10.5, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                lw=1.8, edgecolor=edge, facecolor=face))
    ax.text(x + w/2, y + h/2, text, ha="center", va="center", fontsize=size, color=INK,
            weight=weight, linespacing=1.35)
def arrow(x1, x2, y):
    ax.annotate("", xy=(x2, y), xytext=(x1, y), arrowprops=dict(arrowstyle="-|>", lw=1.6, color=MUTED))
ax.text(1, 47, "Exploits\n(n = 24)", fontsize=12.5, weight="bold", color=ORANGE, va="center")
ax.text(1, 9, "Market\nmoves\n(n = 138)", fontsize=12.5, weight="bold", color=BLUE, va="center")
ro, rb = "#fdeee7", "#eaf2fc"
box(17, 41, 26, 12, "Selected from public\nexploit lists (DeFiHackLabs)", ORANGE, ro)
box(47, 41, 27, 12, "Measured at each attacked\nvenue (Curve pools,\nvaults, lenders)", ORANGE, ro)
box(78, 41, 30, 12, "Reserve skew is mostly the\npost-exploit balance change;\nETH market data used as a\nfallback for 23 of 24", ORANGE, ro)
box(17, 3, 26, 12, "Selected because the\nETH/USD price moved\n3 to 5% or more", BLUE, rb)
box(47, 3, 27, 12, "Measured on one venue:\nUniswap WETH/USDC", BLUE, rb)
box(78, 3, 30, 12, "Reserve skew is the pool's\nprice change; ETH market\ndata describe the move\nthat defined the label", BLUE, rb)
for y in (47, 9):
    arrow(43.6, 46.4, y); arrow(74.6, 77.4, y)
box(22, 19.5, 80, 16,
    "Ethereum-market features alone predict the label (AUC 0.91)\n"
    "Reserve skew measures different quantities in the two classes\n"
    "Three price features are missing for 83 to 96% of exploits\nbut for none of the market moves",
    "#8a2b12", "#ffffff", size=10.5)
ax.text(62, 37.2, "Resulting shortcuts", ha="center", va="bottom", fontsize=11.5, weight="bold", color="#8a2b12")
fig.savefig(OUT + "fig1_sourcing.png", dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)

# ---------------- Figure 2: shortcut AUC bars ----------------
# section 9a: RF LOOCV AUC [95% bootstrap CI]
groups = ["All labeled attacks\n(n = 24)", "Verified oracle\nmanipulations (n = 9)"]
eth = [(0.906, 0.845, 0.960), (0.917, 0.802, 0.989)]
ven = [(0.901, 0.811, 0.974), (0.808, 0.623, 0.941)]
fig, ax = plt.subplots(figsize=(7.2, 4.6))
w = 0.34; xs = [0, 1]
for off, data, col, lab in [(-w/2 - 0.01, eth, ORANGE, "Ethereum-market features only"),
                             (w/2 + 0.01, ven, BLUE, "Attacked-venue features")]:
    for i, (v, lo, hi) in enumerate(data):
        ax.bar(xs[i] + off, v - 0.4, bottom=0.4, width=w, color=col, label=lab if i == 0 else None, zorder=2)
        ax.errorbar(xs[i] + off, v, yerr=[[v - lo], [hi - v]], fmt="none", ecolor=INK, capsize=5, lw=1.3, zorder=3)
        ax.text(xs[i] + off, hi + 0.012, f"{v:.2f}", ha="center", va="bottom", fontsize=11, color=INK)
ax.axhline(0.5, color=MUTED, ls="--", lw=1.1, zorder=1)
ax.text(-0.53, 0.505, "chance", color=MUTED, fontsize=10, ha="left", va="bottom")
ax.set_xticks(xs); ax.set_xticklabels(groups); ax.set_ylim(0.4, 1.08); ax.set_xlim(-0.55, 1.55)
ax.set_ylabel("Random-forest AUC (95% CI)")
ax.yaxis.grid(True, color=GRID, zorder=0); ax.set_axisbelow(True)
for s in ("top", "right"): ax.spines[s].set_visible(False)
ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=2, fontsize=10.5)
fig.savefig(OUT + "fig2_shortcut_auc.png", dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)

# ---------------- Figure 3: shortcut reliance (left) and forward-time false alarms (right) ----------------
# left: cjsj_numbers.md item 29 (ETH-context attribution share on attack incidents, 200 refits)
# right: item 21 (false alarms summed over 7 forward cutoffs, 489 test market moves, trained on all 24)
models = ["Bayesian\nnetwork", "Random\nforest", "XGBoost"]
share = [(8, 3, 15), (32, 23, 44), (36, 19, 50)]
# item 32: 30-seed means with combined (seed + incident bootstrap) 95% intervals; BN deterministic
conds = [("All features", BLUE, [(14, 0, 33), (40.3, 13, 70), (99.3, 61, 141)]),
         ("Without market-context features", AQUA, [(7, 0, 21), (1.2, 0, 6), (10.5, 2, 23)]),
         ("Market-context features only", ORANGE, [(0, 0, 0), (101.8, 62, 147), (131.2, 83, 181)]),
         ("All features, verified labels only", "#8c8b84", [(12, 0, 31), (0.2, 0, 3), (48.1, 27, 69)])]  # section 46
fig, (a1, a2) = plt.subplots(1, 2, figsize=(12.4, 4.8), gridspec_kw={"width_ratios": [1, 1.7]})
for i, (v, lo, hi) in enumerate(share):
    a1.bar(i, v, width=0.55, color=ORANGE, zorder=2)
    a1.errorbar(i, v, yerr=[[v - lo], [hi - v]], fmt="none", ecolor=INK, capsize=5, lw=1.3, zorder=3)
    a1.text(i, hi + 1.5, f"{v}%", ha="center", va="bottom", fontsize=10.5, color=INK)
a1.set_xticks(range(3)); a1.set_xticklabels(models); a1.set_ylim(0, 60)
a1.set_ylabel("Attribution on market-context\nfeatures (%, 95% CI)")
a1.set_title("Reliance on shortcut features", fontsize=11.5, loc="left", color=INK)
w = 0.2
for j2, (lab, col, vals) in enumerate(conds):
    for i, (v, lo, hi) in enumerate(vals):
        x = i + (j2 - 1.5) * (w + 0.015)
        a2.bar(x, v, width=w, color=col, label=lab if i == 0 else None, zorder=2)
        if hi > lo:
            a2.errorbar(x, v, yerr=[[v - lo], [hi - v]], fmt="none", ecolor=INK, capsize=3, lw=1.1, zorder=3)
        a2.text(x, hi + 3, f"{v:.1f}" if (v != int(v) and v < 20) else f"{v:.0f}", ha="center", va="bottom",
                fontsize=8.5, color=INK)
a2.set_xticks(range(3)); a2.set_xticklabels(models); a2.set_ylim(0, 200)
a2.set_ylabel("False alarms across 7 time splits\n(mean of 30 seeds, 95% interval)")
a2.set_title("False alarms when tested on later incidents", fontsize=11.5, loc="left", color=INK)
a2.legend(frameon=False, loc="upper left", fontsize=10)
for ax in (a1, a2):
    ax.yaxis.grid(True, color=GRID, zorder=0); ax.set_axisbelow(True)
    for s in ("top", "right"): ax.spines[s].set_visible(False)
fig.tight_layout(w_pad=3)
fig.savefig(OUT + "fig3_forward_false_alarms.png", dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)
print("figures saved")
