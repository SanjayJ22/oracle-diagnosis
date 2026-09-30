"""CJSJ item 29: bootstrap CIs on the ETH-context attribution share for RF, XGBoost and the BN (extends item 27's 47-82% vs 4-6% contrast).
200 replicates; each resamples incidents with replacement within class (24 attacks, 138 volatility), REFITS all three models on the resample (RF 150 trees, XGB fixed
config, production BN), and explains the out-of-bag incidents (those not drawn; about 37% of each class; at most 40 out-of-bag volatility incidents per replicate).
Statistic per replicate = mean over the explained incidents of the per-incident share of total |attribution| on ETH-context features (cjsj_attr.py). CI = 2.5th/97.5th percentile over
replicates. Also reported: the point estimate from ONE fit on all 162 incidents explaining all of them (in-sample), and the paired RF-minus-BN / XGB-minus-BN differences per replicate.
Features: ALW (8) for RF/XGB, the full node set for the BN (BN nodes include price_dev, cross_venue_spread, dex_oracle_spread, congestion). Raw: reports/cjsj_29_share_ci.csv."""
from cjsj_common import ensure_omp
ensure_omp()
import time
import numpy as np, pandas as pd
from joblib import Parallel, delayed
from cjsj_common import REPORTS, TAG_CONFOUNDED, write_section
import cjsj_eval as E
import cjsj_attr as A

B = 200; MODELS = ["BN", "RF", "XGB"]


def rep(base, r):
    rng = np.random.default_rng(10_000 + r); pos = np.where(base.label.values == E.MAN)[0]; neg = np.where(base.label.values == E.VOL)[0]
    sp = rng.choice(pos, len(pos)); sn = rng.choice(neg, len(neg)); tr = base.iloc[np.concatenate([sp, sn])].reset_index(drop=True)
    oob_p = np.setdiff1d(pos, sp); oob_n = np.setdiff1d(neg, sn); oob_n = rng.choice(oob_n, min(40, len(oob_n)), replace=False)
    out = {"rep": r, "n_oob_att": len(oob_p), "n_oob_vol": len(oob_n)}
    for m in MODELS:
        out[f"{m}_att"] = float(np.nanmean(A.shares(tr, base.iloc[oob_p], m, E.ALW))) if len(oob_p) else np.nan
        out[f"{m}_vol"] = float(np.nanmean(A.shares(tr, base.iloc[oob_n], m, E.ALW)))
    return out


def ci(v):
    v = np.asarray(v, float); v = v[~np.isnan(v)]; return v.mean(), *np.percentile(v, [2.5, 97.5])


def main():
    t0 = time.time(); base = E.load_base(); L = []; Q = L.append
    R = pd.DataFrame(Parallel(n_jobs=8)(delayed(rep)(base, r) for r in range(B))); R.to_csv(REPORTS / "cjsj_29_share_ci.csv", index=False)
    full = {m: A.shares(base, base, m, E.ALW) for m in MODELS}; isatt = (base.label == E.MAN).values
    Q(f"{B} stratified bootstrap replicates, refit each time, explaining out-of-bag incidents (mean {R.n_oob_att.mean():.1f} attacks and {R.n_oob_vol.mean():.1f} volatility incidents per replicate). Share = fraction of a model's total |attribution| that falls on ETH-context features.")
    Q("")
    Q("| Model | attacks: mean share [95% CI] | volatility incidents: mean share [95% CI] | in-sample point estimate (fit on all 162): attacks / volatility |"); Q("|---|---|---|---|")
    for m in MODELS:
        a, v = ci(R[f"{m}_att"]), ci(R[f"{m}_vol"])
        Q(f"| {m} | {a[0]:.0%} [{a[1]:.0%}, {a[2]:.0%}] | {v[0]:.0%} [{v[1]:.0%}, {v[2]:.0%}] | {np.nanmean(full[m][isatt]):.0%} / {np.nanmean(full[m][~isatt]):.0%} |")
    Q("")
    Q("Paired differences in share (same replicates), attacks:")
    Q("")
    Q("| Comparison | difference [95% CI] | share of replicates where the ML model's share exceeds the BN's |"); Q("|---|---|---|")
    for m in ("RF", "XGB"):
        d = R[f"{m}_att"] - R["BN_att"]; c = ci(d); Q(f"| {m} minus BN | {c[0]:+.0%} [{c[1]:+.0%}, {c[2]:+.0%}] | {(d > 0).mean():.1%} |")
    Q("")
    Q("Volatility incidents:"); Q("")
    Q("| Comparison | difference [95% CI] | share of replicates ML > BN |"); Q("|---|---|---|")
    for m in ("RF", "XGB"):
        d = R[f"{m}_vol"] - R["BN_vol"]; c = ci(d); Q(f"| {m} minus BN | {c[0]:+.0%} [{c[1]:+.0%}, {c[2]:+.0%}] | {(d > 0).mean():.1%} |")
    Q("")
    Q("Reading (computed): " + "; ".join(f"{m} attacks {ci(R[f'{m}_att'])[0]:.0%} [{ci(R[f'{m}_att'])[1]:.0%}, {ci(R[f'{m}_att'])[2]:.0%}]" for m in MODELS) + ". "
      f"The BN interval {'does not overlap' if ci(R['BN_att'])[2] < min(ci(R['RF_att'])[1], ci(R['XGB_att'])[1]) else 'overlaps'} the RF and XGBoost intervals. The CI reflects refit and incident-sampling variance, not the choice of the fixed BN thresholds or the project's feature choices.")
    Q("")
    Q(f"(runtime {time.time() - t0:.0f}s; cjsj_29_share_ci.py)")
    body = "\n".join(L); print(body)
    write_section("cjsj_29_share_ci.py", "29", "Bootstrap CIs on the ETH-context attribution share (RF, XGBoost, BN)", TAG_CONFOUNDED, body)


if __name__ == "__main__":
    main()
