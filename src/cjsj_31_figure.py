"""CJSJ item 31: figure tying shortcut reliance to failure under shift. Reads saved results only (nothing is refit):
 left  : reports/cjsj_29_share_ci.csv  (200 bootstrap replicates; share of each model's decision that rests on ETH-market features; mean and 95% interval over replicates)
 right : reports/cjsj_30_configs.csv   (forward-time false alarms for the same models with all features vs without ETH-market features (venue-only set), training on all 24 attacks and on the 9 verified)
Plain labels for a paper figure; colors = reference dataviz palette slots 1-3 with hatching for 'without'. Output: reports/figures/fig_shortcut_reliance_and_failure.png"""
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section

COL = {"BN": "#2a78d6", "RF": "#eb6834", "XGB": "#1baf7a"}; NAME = {"BN": "Bayesian network", "RF": "Random forest", "XGB": "XGBoost"}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e1", "#fcfcfb"
plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "font.family": "sans-serif", "figure.facecolor": SURF, "axes.facecolor": SURF, "text.color": INK,
                     "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "hatch.linewidth": 1.0})


def main():
    R = pd.read_csv(REPORTS / "cjsj_29_share_ci.csv"); P = pd.read_csv(REPORTS / "cjsj_30_configs.csv")
    fig, ax = plt.subplots(1, 2, figsize=(12.2, 5.0), gridspec_kw={"width_ratios": [1, 1.25]})
    a = ax[0]; w = 0.36; x = np.arange(3); nums = {}
    for off, grp, alpha, lab in [(-w / 2 - .02, "att", 1.0, "manipulation incidents"), (w / 2 + .02, "vol", 0.45, "large-volatility incidents")]:
        for i, m in enumerate(["BN", "RF", "XGB"]):
            v = R[f"{m}_{grp}"].dropna().values; mu, lo, hi = v.mean(), *np.percentile(v, [2.5, 97.5]); nums[(m, grp)] = (mu, lo, hi)
            a.bar(x[i] + off, 100 * mu, w, color=COL[m], alpha=alpha, edgecolor=SURF, linewidth=2, zorder=2)
            a.errorbar(x[i] + off, 100 * mu, yerr=[[100 * (mu - lo)], [100 * (hi - mu)]], fmt="none", ecolor=INK, capsize=4, lw=1.4, zorder=3)
            a.text(x[i] + off, 100 * hi + 1.5, f"{100 * mu:.0f}%", ha="center", fontsize=9)
    a.set_xticks(x); a.set_xticklabels(["Bayesian\nnetwork", "Random\nforest", "XGBoost"]); a.set_ylim(0, 75); a.set_ylabel("share of decision resting on\nETH-market features (%)")
    a.grid(axis="y", color=GRID, lw=.6, zorder=0); a.set_axisbelow(True); a.set_title("Reliance on ETH-market features", loc="left", fontsize=10.5)
    from matplotlib.patches import Patch as _P
    a.legend([_P(fc="#8a8a86"), _P(fc="#8a8a86", alpha=.45)], ["manipulation incidents", "large-volatility incidents"], frameon=False, fontsize=8.5, loc="upper left")
    a.text(0.0, -0.17, "Whiskers: 95% interval over 200 refits (held-out incidents only).", transform=a.transAxes, fontsize=8, color=INK2, va="top")
    C = pd.read_csv(REPORTS / "cjsj_32_fig3_ci.csv"); b = ax[1]; bw = 0.27; fa = {}
    sets = [("all features", "with all features", 1.0, ""), ("without market-context (venue only)", "without ETH-market features", 0.45, "///"), ("market-context only", "ETH-market features only", 0.8, "...")]
    for i, (m, mk) in enumerate([("BN", "BN"), ("RF", "RF"), ("XGB", "XGB (30 seeds)")]):
        for j, (sn, lab, al, ht) in enumerate(sets):
            r = C[(C.feature_set == sn) & (C.model == mk)].iloc[0]; x0 = i + (j - 1) * (bw + .02); fa[(m, sn)] = (r["mean"], r.comb_lo, r.comb_hi)
            b.bar(x0, r["mean"], bw, color=COL[m], alpha=al, hatch=ht, edgecolor=COL[m] if ht else SURF, linewidth=1.2 if ht else 2, zorder=2)
            b.errorbar(x0, r["mean"], yerr=[[r["mean"] - r.comb_lo], [r.comb_hi - r["mean"]]], fmt="none", ecolor=INK, capsize=3, lw=1.2, zorder=3)
            b.text(x0, r.comb_hi + 3, f"{r['mean']:.0f}", ha="center", fontsize=8.5)
    b.set_xticks(range(3)); b.set_xticklabels(["Bayesian\nnetwork", "Random\nforest", "XGBoost"]); b.set_ylabel("false alarms on later events\n(total over 7 date-based train/test splits)"); b.set_ylim(0, 200)
    b.grid(axis="y", color=GRID, lw=.6, zorder=0); b.set_axisbelow(True); b.set_title("False alarms on later events (trained on all 24 attacks)", loc="left", fontsize=10.5)
    from matplotlib.patches import Patch
    b.legend([Patch(fc="#8a8a86"), Patch(fc="#8a8a86", alpha=.45, hatch="///", ec="#8a8a86"), Patch(fc="#8a8a86", alpha=.8, hatch="...", ec="#8a8a86")], [s_[1] for s_ in sets], frameon=False, fontsize=8.5, loc="upper left")
    fig.text(0.01, 0.005, "Within-benchmark, confounded data. Right: mean over 30 seeds (BN deterministic) with 95% interval over seeds and test incidents; XGBoost uses row/column sampling. Sources: cjsj_29_share_ci.csv, cjsj_32_fig3_ci.csv.", fontsize=7.5, color=INK2)
    fig.tight_layout(rect=[0, 0.03, 1, 1]); (REPORTS / "figures").mkdir(exist_ok=True); fig.savefig(REPORTS / "figures" / "fig_shortcut_reliance_and_failure.png", dpi=170); plt.close(fig)
    body = ("Figure written to `reports/figures/fig_shortcut_reliance_and_failure.png` from saved results (nothing refit). Left panel (mean [95% interval over 200 refits], held-out incidents): " +
            "; ".join(f"{NAME[m]} {100 * nums[(m, 'att')][0]:.0f}% [{100 * nums[(m, 'att')][1]:.0f}%, {100 * nums[(m, 'att')][2]:.0f}%] (manipulation) / {100 * nums[(m, 'vol')][0]:.0f}% [{100 * nums[(m, 'vol')][1]:.0f}%, {100 * nums[(m, 'vol')][2]:.0f}%] (volatility)" for m in ["BN", "RF", "XGB"]) +
            ". Right panel (training on all 24; 30-seed mean [combined 95% interval], item 32): " + "; ".join(f"{NAME[m]} all features {fa[(m, 'all features')][0]:.0f} [{fa[(m, 'all features')][1]:.0f}, {fa[(m, 'all features')][2]:.0f}], without market-context {fa[(m, 'without market-context (venue only)')][0]:.1f} [{fa[(m, 'without market-context (venue only)')][1]:.0f}, {fa[(m, 'without market-context (venue only)')][2]:.0f}], market-context only {fa[(m, 'market-context only')][0]:.0f} [{fa[(m, 'market-context only')][1]:.0f}, {fa[(m, 'market-context only')][2]:.0f}]" for m in ["BN", "RF", "XGB"]) +
            ". Sources: `reports/cjsj_29_share_ci.csv` (`cjsj_29_share_ci.py`), `reports/cjsj_32_fig3_ci.csv` (`cjsj_32_fig3_ci.py`); the verified-9 training bars of the first version were dropped (no intervals computed for them).  [cjsj_31_figure.py]")
    print(body); write_section("cjsj_31_figure.py", "31", "Figure: ETH-market reliance and false alarms under shift", TAG_CONFOUNDED + " (verified-M training bars: verified labels, negatives unchanged)", body)


if __name__ == "__main__":
    main()
