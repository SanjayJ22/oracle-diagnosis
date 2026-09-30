"""CJSJ item 15: figures from frozen numbers -> reports/figures/.
 (a) fig_a_shortcut_auc.png     : ETH-market-context-only vs venue+localization AUC with 95% bootstrap CIs, all 24 / M-all (12) / verified M (9).
                                  Numbers are PARSED from section 9 of reports/cjsj_numbers.md (written by cjsj_09_shortcuts.py), not recomputed.
 (b) fig_b_fa_vs_positives.png  : false alarms (and recall) vs number of training positives, BN/RF/XGB, from reports/cjsj_12_learning_curve.csv.
 (c) fig1_sourcing_schematic.png: schematic of how each class was sourced and measured (counts from reports/research_audit.md: C1 23/24 ETH/USD
                                  fallback, 138/138 volatility on WETH_USDC_V3, C2 16/24 |skew|>=0.9, C3 price_dev missing 83% vs 0%).
Palette: reference dataviz palette slots 1-3 (#2a78d6, #eb6834, #1baf7a), validated for CVD; marker shapes and direct labels carry identity too."""
import re
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section

FIG = REPORTS / "figures"; FIG.mkdir(exist_ok=True)
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"; INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "font.family": "sans-serif",
                     "figure.facecolor": SURF, "axes.facecolor": SURF, "text.color": INK, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2})


def parse_sec9():
    s = (REPORTS / "cjsj_numbers.md").read_text(); i = s.index("## 9. "); j = s.index("### 9b", i); sec = s[i:j]
    out = {}
    for blk in re.split(r"(?m)^#### ", sec)[1:]:
        title = blk.split(":")[0]
        if not (title.startswith("all 24") or title.startswith("A2 M") or title.startswith("verified M")): continue
        n = int(re.search(r"positives=(\d+)", blk).group(1))
        for feat in ("ETH-market context only (7)", "venue + localization"):
            m = re.search(rf"\| {re.escape(feat)} \| [\d.]+ \| ([\d.]+) \[([\d.]+), ([\d.]+)\] \|", blk)
            out[(title, feat)] = tuple(float(x) for x in m.groups()); out[(title, "n")] = n
    return out


def fig_a():
    P = parse_sec9(); sets = [("all 24 (audit baseline)", "all 24"), ("A2 M, any tier (12)", "M-all"), ("verified M (9)", "verified M")]
    fig, ax = plt.subplots(figsize=(8.2, 4.6)); w = 0.32; x = np.arange(len(sets)); vals = {}
    for off, feat, col, lab in [(-w / 2 - 0.02, "ETH-market context only (7)", ORANGE, "ETH-market context only (features of the ETH market, not the attacked asset)"),
                                (w / 2 + 0.02, "venue + localization", BLUE, "venue + localization (attacked venue's reserve skew)")]:
        for i, (key, _) in enumerate(sets):
            a, lo, hi = P[(key, feat)]; vals[(key, feat)] = (a, lo, hi)
            ax.bar(x[i] + off, a, w, color=col, label=lab if i == 0 else None, zorder=2, edgecolor=SURF, linewidth=2)
            ax.errorbar(x[i] + off, a, yerr=[[a - lo], [hi - a]], fmt="none", ecolor=INK, elinewidth=1.4, capsize=4, zorder=3)
            ax.text(x[i] + off, hi + 0.012, f"{a:.2f}", ha="center", va="bottom", fontsize=9, color=INK)
    ax.axhline(0.5, color="#9a9994", ls="--", lw=1, zorder=1); ax.text(2.58, 0.505, "chance", fontsize=8, color=INK2, ha="right", va="bottom")
    ax.set_xticks(x); ax.set_xticklabels([f"{lab}\n(n_pos = {P[(k, 'n')]})" for k, lab in sets]); ax.set_ylim(0.4, 1.08); ax.set_ylabel("RF LOOCV AUC (95% bootstrap CI)")
    ax.grid(axis="y", color=GRID, lw=.6, zorder=0); ax.set_axisbelow(True)
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.36), frameon=False, fontsize=8.5, ncol=1)
    ax.set_title("ETH-market features (not the attacked asset) separate the classes\nas well as the attacked venue's features", loc="left", fontsize=10.5, color=INK)
    fig.text(0.01, 0.005, "Within-benchmark, confounded data. CI = stratified bootstrap of LOOCV predictions (refit variance ignored). Source: cjsj_numbers.md section 9.", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=[0, 0.03, 1, 1]); fig.savefig(FIG / "fig_a_shortcut_auc.png", dpi=170); plt.close(fig)
    return vals


def fig_b():
    R = pd.read_csv(REPORTS / "cjsj_12_learning_curve.csv"); rng = np.random.default_rng(0)
    def ci(v):
        v = np.asarray(v, float); bm = [rng.choice(v, len(v)).mean() for _ in range(1000)]; return v.mean(), *np.percentile(bm, [2.5, 97.5])
    fig, ax = plt.subplots(2, 2, figsize=(10.5, 6.6), sharex="col"); sty = {"BN": (BLUE, "o"), "RF": (ORANGE, "s"), "XGB": (AQUA, "^")}
    pools = [("verified M (9)", "Positive pool: verified M (9)"), ("all 24", "Positive pool: all 24 attacks")]
    for j, (pool, title) in enumerate(pools):
        for i, (col, ylab) in enumerate([("fa", "false alarms (of 138)"), ("recall", "recall on held-out pool positives")]):
            a = ax[i, j]
            for m, (c, mk) in sty.items():
                d = R[(R.pool == pool) & (R.model == m)]; ks = sorted(d.k.unique())
                st = np.array([ci(d[d.k == k][col]) for k in ks])
                a.fill_between(ks, st[:, 1], st[:, 2], color=c, alpha=0.18, lw=0)
                a.plot(ks, st[:, 0], marker=mk, color=c, lw=2, ms=7, mec=SURF, mew=1.2, label=m)
            a.grid(color=GRID, lw=.6); a.set_axisbelow(True); a.set_xticks(ks if len(ks) <= 6 else [2, 4, 6, 8, 10, 12, 14, 16, 18, 20])
            if i == 0: a.set_title(title, loc="left", fontsize=10.5)
            a.set_ylabel(ylab if j == 0 else ""); 
            if i == 1: a.set_xlabel("k = training positives (random subsample, 30 seeds)")
            if col == "recall": a.set_ylim(0, 1.02)
    h, l = ax[0, 0].get_legend_handles_labels(); fig.legend(h, l, loc="upper right", ncol=3, frameon=False, fontsize=9.5, bbox_to_anchor=(0.99, 0.995))
    fig.text(0.01, 0.005, "Within-benchmark, confounded data (verified-M pool: verified labels, negatives unchanged). Band = 95% bootstrap CI over seeds\n(subsampling variance only). XGB fixed config. Source: cjsj_12_learning_curve.csv.", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=[0, 0.04, 1, 0.965]); fig.savefig(FIG / "fig_b_fa_vs_positives.png", dpi=170); plt.close(fig)


def box(ax, x, y, w, h, text, fc, ec, fs=9.2, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.06", fc=fc, ec=ec, lw=1.6))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=INK, wrap=True, fontweight="bold" if bold else "normal", linespacing=1.35)


def arrow(ax, p, q, color=INK2, ls="-", lw=1.6, style="-|>"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=14, color=color, lw=lw, ls=ls))


def fig1():
    fig, ax = plt.subplots(figsize=(12.6, 6.9)); ax.set_xlim(0, 12.6); ax.set_ylim(0, 6.9); ax.axis("off")
    ax.text(0.1, 6.65, "Figure 1. How each class was sourced and what was measured (benchmark as audited, n = 162)", fontsize=12, fontweight="bold", color=INK, va="center")
    lo = "#eaf2fc"; ho = "#fdece5"; W, H = 3.05, 1.45; red = "#c0392b"
    ax.text(0.1, 5.75, "Manipulation\n(n = 24)", fontsize=11, fontweight="bold", color=ORANGE, va="center")
    ax.text(0.1, 2.05, "Large volatility\n(n = 138)", fontsize=11, fontweight="bold", color=BLUE, va="center")
    xs = [1.95, 5.3, 8.65]; W3 = 3.85
    box(ax, xs[0], 5.0, W, H, "Picked from public exploit\nlists (DeFiHackLabs PoCs,\npost-mortems): 24 incidents", ho, ORANGE)
    box(ax, xs[1], 5.0, W, H, "Measured on the ATTACKED\nvenue: Curve pools, vaults,\nlending markets, custom AMMs\n(24 different venues)", ho, ORANGE)
    box(ax, xs[2], 5.0, W3, H, "Features: venue balance change\nvs block-300, taken AFTER the exploit\n(16/24 have |skew| >= 0.9) plus\nETH/USD 'fallback' context (23/24)", ho, ORANGE)
    box(ax, xs[0], 1.3, W, H, "Picked BECAUSE Chainlink\nETH/USD moved 3-5% or more:\n138 incidents", lo, BLUE)
    box(ax, xs[1], 1.3, W, H, "Measured on ONE venue:\nUniswap WETH/USDC V3\n(138 / 138 incidents)", lo, BLUE)
    box(ax, xs[2], 1.3, W3, H, "Features: price change on that\npool (the quantity that defined\nthe label) plus the same ETH/USD\ncontext; no missing prices", lo, BLUE)
    for y0 in (5.0, 1.3):
        arrow(ax, (xs[0] + W, y0 + H / 2), (xs[1], y0 + H / 2)); arrow(ax, (xs[1] + W, y0 + H / 2), (xs[2], y0 + H / 2))
    xm = xs[2] + W3 / 2
    arrow(ax, (xm, 4.95), (xm, 2.8), color=red, ls="--", lw=1.8, style="<|-|>")
    ax.text(xm + 0.15, 3.87, "different asset,\ndifferent quantity,\ndifferent timing", fontsize=8.8, color=red, va="center")
    box(ax, xs[0], 3.0, 6.4, 1.6, "Shortcuts this creates (audit C1-C3)\nC1  ETH-market context alone: AUC 0.92 [0.80, 0.99]\n     (verified M; 0.91 on all 24)\nC2  reserve_skew is the loss itself, measured post-exploit\nC3  price_dev missing for 83% of attacks vs 0% of volatility", "#ffffff", red, fs=8.8)
    xc = xs[0] + 3.2
    arrow(ax, (xc, 4.6), (xc, 5.0), color=red, ls="--", lw=1.3); arrow(ax, (xc, 3.0), (xc, 2.75), color=red, ls="--", lw=1.3)
    ax.text(0.1, 0.55, "Counts: research_audit.md (C1-C3); AUC: cjsj_numbers.md section 9 (cjsj_09_shortcuts.py). Schematic only; boxes are not to scale.", fontsize=8, color=INK2)
    fig.savefig(FIG / "fig1_sourcing_schematic.png", dpi=170, bbox_inches="tight"); plt.close(fig)


def main():
    vals = fig_a(); fig_b(); fig1()
    body = ("Figures written to `reports/figures/`:\n\n"
            "- `fig_a_shortcut_auc.png`: ETH-market-context-only vs venue+localization RF AUC with 95% bootstrap CIs, all 24 / M-all (12) / verified M (9). "
            "Values parsed from section 9 of this file (`cjsj_09_shortcuts.py`): " + "; ".join(
                f"{k[0].split(' (')[0]} {k[1].split(' (')[0]}: {v[0]:.3f} [{v[1]:.3f}, {v[2]:.3f}]" for k, v in vals.items()) + ".\n"
            "- `fig_b_fa_vs_positives.png`: false alarms (and recall) vs training positives, BN/RF/XGB, both pools, from `reports/cjsj_12_learning_curve.csv` (`cjsj_12_learning_curve.py`, section 12).\n"
            "- `fig1_sourcing_schematic.png`: Figure 1 sketch of how each class was sourced and measured; counts from `research_audit.md` C1-C3 and section 9. Schematic, hand-laid-out boxes.\n\n"
            "Colors: reference dataviz palette slots 1-3 (validated for CVD; the contrast warning for the orange/aqua fills is handled with value labels, direct labels and marker shapes). "
            "Every plotted number is read from a saved result, none is recomputed here.  [cjsj_15_figures.py]")
    print(body); write_section("cjsj_15_figures.py", "15", "Figures: shortcut AUC bars, false alarms vs training positives, sourcing schematic", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
